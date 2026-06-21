import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from claude_agent_sdk.types import AssistantMessage, ResultMessage, ToolResultBlock, ToolUseBlock, UserMessage

import orchestrator.agents.base_agent as base_agent_module
from orchestrator.agents.exploratory_agent import ExplorationState, ExploratoryAgent
from orchestrator.agents.auth_handler import AuthHandler
from orchestrator.api.exploration import ExplorationStartRequest, _build_exploratory_agent_config


def _agent() -> ExploratoryAgent:
    agent = ExploratoryAgent()
    agent.state = ExplorationState(start_time=time.time())
    return agent


def test_exploratory_prompt_requires_explicit_credentials_login_url():
    agent = _agent()

    with pytest.raises(ValueError, match="requires login_url"):
        agent._build_exploration_prompt(
            url="https://example.com",
            instructions="Explore",
            time_limit_minutes=5,
            auth_config={"type": "credentials", "credentials": {"username": "user", "password": "secret"}},
            test_data={},
            focus_areas=[],
            excluded_patterns=[],
        )


def test_exploration_config_does_not_default_credentials_login_url_to_login(monkeypatch):
    from orchestrator.memory import agent_memory as agent_memory_module
    from orchestrator.memory import context_builder as context_builder_module

    class DummyMemoryContextBuilder:
        def __init__(self, service):
            self.service = service

        def build_prompt_context(self, **kwargs):
            return ""

    monkeypatch.setattr(agent_memory_module, "get_agent_memory_service", lambda: object())
    monkeypatch.setattr(context_builder_module, "MemoryContextBuilder", DummyMemoryContextBuilder)

    request = ExplorationStartRequest(
        entry_url="https://example.com",
        credentials={"username": "user", "password": "secret"},
        login_url="  /sign-in  ",
    )

    config = _build_exploratory_agent_config(request, run_id="run-explicit-login")

    assert config["auth"]["login_url"] == "/sign-in"


def test_exploration_config_rejects_credentials_without_login_url():
    request = ExplorationStartRequest(
        entry_url="https://example.com",
        credentials={"username": "user", "password": "secret"},
    )

    with pytest.raises(Exception) as exc_info:
        _build_exploratory_agent_config(request, run_id="run-missing-login")

    assert getattr(exc_info.value, "status_code", None) == 400
    assert "requires login_url" in str(getattr(exc_info.value, "detail", exc_info.value))


@pytest.mark.asyncio
async def test_auth_handler_does_not_default_credentials_login_url(tmp_path):
    handler = AuthHandler(storage_dir=tmp_path)

    result = await handler.authenticate(
        None,
        {"type": "credentials", "credentials": {"username": "user", "password": "secret"}},
        "https://example.com",
    )

    assert result["success"] is False
    assert result["error"] == "Missing login URL"


def test_process_results_fails_parse_fallback_with_zero_evidence(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    agent = _agent()

    result = agent._process_results(
        "I could not complete the task. There is no structured result here.",
        {"url": "https://example.com", "time_limit_minutes": 1, "project_id": "default"},
    )

    assert result["status"] == "failed"
    assert result["exploration_failed"] is True
    assert result["failure_reason"] == "zero_evidence_parse_fallback"
    assert result["parsing_failed"] is True
    assert result["action_trace"] == []
    assert result["total_flows_discovered"] == 0
    assert result["coverage"]["coverage_score"] == 0.0
    assert result["error_details"]
    assert "no structured result" in result["raw_output_preview"]


def test_process_results_classifies_claude_login_failure_without_flows_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    agent = _agent()
    monkeypatch.setattr(agent, "_run_dir", lambda run_id: tmp_path / run_id)

    result = agent._process_results(
        "Not logged in · Please run /login",
        {"url": "https://example.com", "time_limit_minutes": 1, "project_id": "default", "run_id": "run-1"},
    )

    assert result["status"] == "failed"
    assert result["exploration_failed"] is True
    assert result["failure_reason"] == "runtime_auth_failed"
    assert result["parsing_failed"] is False
    assert result["action_trace"] == []
    assert result["total_flows_discovered"] == 0
    assert "Claude SDK runtime is not authenticated" in result["summary"]
    assert not (tmp_path / "run-1" / "flows.json").exists()


def test_process_results_does_not_infer_flows_from_regex_fallback(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    agent = _agent()

    result = agent._process_results(
        "\n".join(
            [
                "Step 1: Navigate https://example.com",
                "Step 2: Click Sign in",
                "Step 3: Fill Email",
            ]
        ),
        {"url": "https://example.com", "time_limit_minutes": 1, "project_id": "default"},
    )

    assert result["status"] == "failed"
    assert result["parsing_failed"] is True
    assert result["action_trace"] == []
    assert result["total_flows_discovered"] == 0
    assert result["coverage"]["coverage_score"] == 0.0


def test_process_results_writes_event_log_and_observed_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    agent = _agent()
    monkeypatch.setattr(agent, "_run_dir", lambda run_id: tmp_path / run_id)

    output = "\n".join(
        [
            '{"id":"evt_001","event_type":"page_observed","url":"https://example.com","title":"Home","summary":"Home page","screenshot_path":"live-step-001.png"}',
            '{"id":"evt_002","event_type":"action_result","action":"click","target":"Sign in","success":true,"outcome":"Login opened","url":"https://example.com/login"}',
            '{"id":"evt_003","event_type":"flow_candidate","title":"Open sign in","step_event_ids":["evt_001","evt_002"],"evidence_event_ids":["evt_001","evt_002"],"entry_point":"https://example.com","exit_point":"https://example.com/login","test_ideas":["Verify sign in opens."],"edge_cases":[]}',
            '```json\n{"summary":"Observed sign-in entry","coverage_notes":"Home and login covered","blocker_status":"none","event_counts":{"page_observed":1,"action_result":1,"flow_candidate":1},"termination_reason":"completed"}\n```',
        ]
    )

    result = agent._process_results(
        output,
        {"url": "https://example.com", "time_limit_minutes": 1, "project_id": "default", "run_id": "run-1"},
    )

    event_log = tmp_path / "run-1" / "exploration_events.jsonl"
    flows_file = tmp_path / "run-1" / "flows.json"

    assert event_log.exists()
    assert flows_file.exists()
    assert result.get("status") != "failed"
    assert result["parsing_failed"] is False
    assert result["total_flows_discovered"] == 1
    assert result["discovered_flow_summaries"][0]["id"] == "flow_1"
    assert result["action_trace"][0]["event_id"] == "evt_002"
    assert result["coverage"]["flows_discovered"] == 1


def test_process_results_recovers_from_malformed_final_json_with_events(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    agent = _agent()

    output = "\n".join(
        [
            '{"id":"evt_001","event_type":"page_observed","url":"https://example.com","title":"Home"}',
            '{"id":"evt_002","event_type":"action_result","action":"navigate","target":"https://example.com","success":true,"outcome":"Loaded"}',
            "```json\n{not valid json\n```",
        ]
    )

    result = agent._process_results(
        output,
        {"url": "https://example.com", "time_limit_minutes": 1, "project_id": "default"},
    )

    assert result.get("status") != "failed"
    assert result["parsing_failed"] is True
    assert result["total_flows_discovered"] == 1
    assert result["action_trace"][0]["event_id"] == "evt_002"


def test_process_results_synthesizes_evidence_from_browser_tool_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    agent = _agent()
    monkeypatch.setattr(agent, "_run_dir", lambda run_id: tmp_path / run_id)

    result = agent._process_results(
        "I explored the page and found useful paths.",
        {
            "url": "https://example.com",
            "time_limit_minutes": 1,
            "project_id": "default",
            "run_id": "run-browser-tools",
            "_runtime_tool_calls": [
                {
                    "name": "mcp__playwright-test__browser_navigate",
                    "success": True,
                    "input": {"url": "https://example.com"},
                },
                {
                    "name": "mcp__playwright-test__browser_click",
                    "success": True,
                    "input": {"element": "Sign in", "target": "Sign in"},
                },
            ],
        },
    )

    assert result.get("status") != "failed"
    assert result["total_flows_discovered"] == 1
    assert result["diagnostics"]["tool_calls"] == 2
    assert result["diagnostics"]["browser_tool_calls"] == 2
    assert result["diagnostics"]["successful_browser_tool_calls"] == 2
    assert result["diagnostics"]["evidence_event_count"] >= 3
    assert (tmp_path / "run-browser-tools" / "exploration_events.jsonl").exists()


def test_process_results_does_not_treat_missing_tool_success_as_success(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    agent = _agent()

    result = agent._process_results(
        "The browser stream was interrupted.",
        {
            "url": "https://example.com",
            "time_limit_minutes": 1,
            "project_id": "default",
            "_runtime_tool_calls": [
                {
                    "name": "mcp__playwright-test__browser_navigate",
                    "input": {"url": "https://example.com"},
                },
                {
                    "name": "mcp__playwright-test__browser_click",
                    "input": {"element": "Sign in"},
                },
            ],
        },
    )

    assert result["diagnostics"]["browser_tool_calls"] == 2
    assert result["diagnostics"]["successful_browser_tool_calls"] == 0
    assert result["total_flows_discovered"] == 0
    assert result["exploration_status"] in {"no_flows_observed", "contract_violation"}


def test_process_results_dedupes_repeated_browser_actions(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    agent = _agent()

    calls = [
        {"name": "mcp__playwright-test__browser_navigate", "success": True, "input": {"url": "https://example.com"}},
        {"name": "mcp__playwright-test__browser_click", "success": True, "input": {"element": "Sign in"}},
        {"name": "mcp__playwright-test__browser_navigate", "success": True, "input": {"url": "https://example.com"}},
        {"name": "mcp__playwright-test__browser_click", "success": True, "input": {"element": "Sign in"}},
    ]

    result = agent._process_results(
        "Done.",
        {
            "url": "https://example.com",
            "time_limit_minutes": 1,
            "project_id": "default",
            "_runtime_tool_calls": calls,
        },
    )

    assert result["total_flows_discovered"] == 1
    assert result["diagnostics"]["dedupe_stats"]["duplicate_flows_removed"] >= 0


def test_process_results_warns_on_prose_flow_claim_without_evidence(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    agent = _agent()

    result = agent._process_results(
        "I documented 4 flows: login, checkout, profile, and search.",
        {"url": "https://example.com", "time_limit_minutes": 1, "project_id": "default"},
    )

    assert result["total_flows_discovered"] == 0
    assert result["contract_warning"]
    assert result["exploration_status"] == "contract_violation"


def test_process_results_keeps_valid_flow_candidates(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    agent = _agent()

    output = "\n".join(
        [
            '{"id":"evt_001","event_type":"page_observed","url":"https://example.com","title":"Home"}',
            '{"id":"evt_002","event_type":"action_result","action":"click","target":"Pricing","success":true,"outcome":"Pricing opened","url":"https://example.com/pricing"}',
            '{"id":"evt_003","event_type":"flow_candidate","title":"Open pricing","step_event_ids":["evt_001","evt_002"],"evidence_event_ids":["evt_001","evt_002"],"entry_point":"https://example.com","exit_point":"https://example.com/pricing","test_ideas":["Verify pricing opens."],"edge_cases":[]}',
            '{"id":"evt_004","event_type":"flow_candidate","title":"Open pricing duplicate","step_event_ids":["evt_001","evt_002"],"evidence_event_ids":["evt_001","evt_002"],"entry_point":"https://example.com","exit_point":"https://example.com/pricing","test_ideas":["Verify pricing opens."],"edge_cases":[]}',
            '```json\n{"summary":"done","termination_reason":"completed"}\n```',
        ]
    )

    result = agent._process_results(
        output,
        {"url": "https://example.com", "time_limit_minutes": 1, "project_id": "default"},
    )

    assert result["total_flows_discovered"] == 1
    assert result["discovered_flow_summaries"][0]["title"] == "Open pricing"
    assert result["diagnostics"]["dedupe_stats"]["duplicate_flows_removed"] == 1


def test_process_results_runtime_tool_calls_match_structured_result(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    agent = _agent()

    result = agent._process_results(
        "Exploration completed.",
        {
            "url": "https://example.com",
            "time_limit_minutes": 1,
            "project_id": "default",
            "_runtime_diagnostics": {"runtime": "claude_sdk"},
            "_runtime_tool_calls": [
                {"name": "browser_navigate", "success": True, "input": {"url": "https://example.com"}},
                {"name": "browser_click", "success": True, "input": {"target": "Docs"}},
            ],
        },
    )

    assert result["diagnostics"]["runtime"] == "claude_sdk"
    assert result["total_flows_discovered"] == 1
    assert result["coverage"]["flows_discovered"] == 1


@pytest.mark.asyncio
async def test_run_captures_claude_sdk_tool_telemetry_when_output_is_malformed(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    monkeypatch.setattr(base_agent_module, "AGENT_QUEUE_AVAILABLE", False)

    async def fake_query(*_args, **_kwargs):
        yield AssistantMessage(
            content=[
                ToolUseBlock(
                    id="toolu_nav",
                    name="mcp__playwright-test__browser_navigate",
                    input={"url": "https://example.test"},
                )
            ],
            model="claude-test",
        )
        yield UserMessage(
            content=[
                ToolResultBlock(
                    tool_use_id="toolu_nav",
                    content='Page title: Home\nhttps://example.test\n- button "Pricing"',
                    is_error=False,
                )
            ]
        )
        yield AssistantMessage(
            content=[
                ToolUseBlock(
                    id="toolu_click",
                    name="mcp__playwright-test__browser_click",
                    input={"element": "Pricing", "target": "Pricing"},
                )
            ],
            model="claude-test",
        )
        yield UserMessage(content=[ToolResultBlock(tool_use_id="toolu_click", content="Clicked", is_error=False)])
        yield ResultMessage(
            subtype="success",
            duration_ms=10,
            duration_api_ms=10,
            is_error=False,
            num_turns=1,
            session_id="sdk-session-1",
            total_cost_usd=0.01,
            result="```json\n{not valid json\n```",
        )

    agent = ExploratoryAgent()
    agent.agent_cwd = str(tmp_path / "run-sdk")
    monkeypatch.setattr(agent, "_run_dir", lambda run_id: tmp_path / run_id)
    monkeypatch.setattr(base_agent_module, "query", fake_query)
    monkeypatch.setattr(
        agent,
        "_refresh_runtime_settings",
        lambda: ({}, SimpleNamespace(runtime="claude_sdk", tier="tool_deep", model="claude-test", base_url="")),
    )
    monkeypatch.setattr(agent, "_preflight_claude_sdk_auth", lambda _selection: None)

    result = await agent.run(
        {
            "url": "https://example.test",
            "time_limit_minutes": 1,
            "project_id": "default",
            "run_id": "run-sdk",
        }
    )

    tool_calls = result["diagnostics"]["tool_call_records"]
    assert result.get("status") != "failed"
    assert result["parsing_failed"] is True
    assert result["total_flows_discovered"] == 1
    assert result["coverage"]["flows_discovered"] == 1
    assert result["action_trace"][0]["action"] == "navigate"
    assert result["diagnostics"]["tool_calls"] == 2
    assert result["diagnostics"]["successful_browser_tool_calls"] == 2
    assert tool_calls[0]["tool_use_id"] == "toolu_nav"
    assert tool_calls[1]["success"] is True
    assert (tmp_path / "run-sdk" / "tool_calls.json").exists()


def test_process_results_counts_flow_candidates_with_empty_evidence_refs(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    agent = _agent()

    output = "\n".join(
        [
            '{"id":"evt_001","event_type":"flow_candidate","title":"Unsupported checkout","step_event_ids":[],"evidence_event_ids":[],"entry_point":"https://example.test","exit_point":"https://example.test/checkout","test_ideas":["Verify checkout"],"edge_cases":[]}',
            '```json\n{"summary":"done","termination_reason":"completed"}\n```',
        ]
    )

    result = agent._process_results(
        output,
        {"url": "https://example.test", "time_limit_minutes": 1, "project_id": "default"},
    )

    assert result["total_flows_discovered"] == 0
    assert result["unsupported_flow_candidates"][0]["title"] == "Unsupported checkout"
    assert result["unsupported_flow_candidates"][0]["reason"] == "No evidence_event_ids or step_event_ids were provided."
    assert result["diagnostics"]["flow_candidate_records"] == 1
    assert result["diagnostics"]["unsupported_flow_candidates"] == 1
    assert result["diagnostics"]["empty_evidence_ref_flow_candidates"] == 1
