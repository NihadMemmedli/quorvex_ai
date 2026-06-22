import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.services.agent_runtimes import AgentRuntimeContext, get_agent_runtime, normalize_agent_runtime
from orchestrator.services.agent_runtimes.claude import ClaudeAgentSdkRuntime
from orchestrator.utils.agent_runner import AgentRunner


def test_normalize_agent_runtime_defaults_and_aliases(monkeypatch):
    monkeypatch.delenv("QUORVEX_AGENT_RUNTIME", raising=False)

    assert normalize_agent_runtime(None) == "claude_sdk"
    assert normalize_agent_runtime("claude") == "claude_sdk"
    assert normalize_agent_runtime("claude-agent-sdk") == "claude_sdk"
    assert normalize_agent_runtime("hermes") == "claude_sdk"
    assert normalize_agent_runtime("hermes-agent") == "claude_sdk"
    assert normalize_agent_runtime("hermes_agent") == "claude_sdk"

    with pytest.raises(ValueError, match="Unsupported agent runtime"):
        normalize_agent_runtime("unknown")


def test_runtime_resolver_coerces_legacy_hermes_to_claude_sdk():
    assert isinstance(get_agent_runtime("hermes"), ClaudeAgentSdkRuntime)


def test_runtime_resolver_rejects_unknown_runtime():
    with pytest.raises(ValueError, match="Unsupported agent runtime"):
        get_agent_runtime("unknown")


def test_agent_runner_queue_task_kwargs_preserve_runtime_adapter_fields(monkeypatch):
    monkeypatch.setenv("BROWSER_SLOT_PARENT_OWNER_TYPE", "test_run")
    monkeypatch.setenv("BROWSER_SLOT_PARENT_RUN_ID", "parent-run-1")
    runner = AgentRunner(
        allowed_tools=["Read"],
        tools=["Read", "Bash"],
        disallowed_tools=["Write"],
        permission_mode="bypassPermissions",
        strict_mcp_config=False,
        max_budget_usd=1.25,
        task_budget={"total": 1200},
        include_hook_events=True,
        include_partial_messages=True,
        output_format={"type": "json_schema"},
        resume_session_id="session-1",
        continue_conversation=True,
        max_turns=7,
        fallback_model="claude-fallback",
        betas=["beta-1"],
        owner_type="agent_run",
        owner_id="agent-1",
        owner_label="Agent 1",
        requires_live_browser=True,
        env_vars={"QUEUE_ONLY": "yes"},
    )

    kwargs = runner._queue_task_kwargs(
        prompt="inspect",
        timeout=123,
        owner_metadata=runner._queue_owner_metadata(),
    )

    assert kwargs["prompt"] == "inspect"
    assert kwargs["timeout_seconds"] == 123
    assert kwargs["agent_type"] == "AgentRunner"
    assert kwargs["operation_type"] == "run"
    assert kwargs["env_vars"]["QUEUE_ONLY"] == "yes"
    assert kwargs["allowed_tools"] == ["Read"]
    assert kwargs["tools"] == ["Read", "Bash"]
    assert kwargs["disallowed_tools"] == ["Write"]
    assert kwargs["permission_mode"] == "bypassPermissions"
    assert kwargs["strict_mcp_config"] is False
    assert kwargs["max_budget_usd"] == 1.25
    assert kwargs["task_budget"] == {"total": 1200}
    assert kwargs["include_hook_events"] is True
    assert kwargs["include_partial_messages"] is True
    assert kwargs["output_format"] == {"type": "json_schema"}
    assert kwargs["resume_session_id"] == "session-1"
    assert kwargs["continue_conversation"] is True
    assert kwargs["max_turns"] == 7
    assert kwargs["fallback_model"] == "claude-fallback"
    assert kwargs["betas"] == ["beta-1"]
    assert kwargs["owner_type"] == "agent_run"
    assert kwargs["owner_id"] == "agent-1"
    assert kwargs["owner_label"] == "Agent 1"
    assert kwargs["browser_slot_parent_owner_type"] == "test_run"
    assert kwargs["browser_slot_parent_run_id"] == "parent-run-1"
    assert kwargs["requires_live_browser"] is True
    assert kwargs["cwd"] == os.getcwd()


@pytest.mark.asyncio
async def test_claude_runtime_passes_env_vars_to_agent_runner(monkeypatch):
    captured = {}

    class FakeRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self, prompt):
            assert prompt == "inspect"
            from orchestrator.utils.agent_runner import AgentResult

            return AgentResult(success=True, output="ok")

    monkeypatch.setattr(
        "orchestrator.services.agent_runtimes.claude.AgentRunner", FakeRunner
    )

    result = await ClaudeAgentSdkRuntime().run(
        "inspect",
        AgentRuntimeContext(
            env_vars={"TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME": "user@example.com"}
        ),
    )

    assert result.success is True
    assert captured["env_vars"] == {
        "TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME": "user@example.com"
    }


@pytest.mark.asyncio
async def test_claude_runtime_passes_advanced_sdk_options_to_agent_runner(monkeypatch):
    captured = {}

    class FakeRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self, prompt):
            from orchestrator.utils.agent_runner import AgentResult

            return AgentResult(success=True, output=prompt)

    async def permission_guard(tool_name, input_data, context):
        return True

    hooks = {"PreToolUse": []}
    agents = {
        "read-only-reviewer": {
            "description": "Read-only reviewer",
            "prompt": "Review using read-only tools.",
            "tools": ["Read", "Grep", "Glob"],
        }
    }
    plugins = [{"type": "local", "path": "./.claude/plugins/reviewer"}]
    session_store = object()

    monkeypatch.setattr(
        "orchestrator.services.agent_runtimes.claude.AgentRunner", FakeRunner
    )

    result = await ClaudeAgentSdkRuntime().run(
        "inspect",
        AgentRuntimeContext(
            cwd="/tmp/work",
            fallback_model="claude-fallback",
            reasoning_budget=4096,
            include_partial_messages=True,
            max_buffer_size=123456,
            betas=["context-1m-2025-08-07"],
            user="operator@example.test",
            permission_prompt_tool_name="permission_prompt",
            enable_file_checkpointing=True,
            sandbox={"enabled": True},
            hooks=hooks,
            agents=agents,
            skills=["playwright"],
            plugins=plugins,
            session_store=session_store,
            fork_session=True,
            tool_search_policy="force",
            tool_permission_guard=permission_guard,
        ),
    )

    assert result.success is True
    assert captured["cwd"] == "/tmp/work"
    assert captured["fallback_model"] == "claude-fallback"
    assert captured["reasoning_budget"] == 4096
    assert captured["include_partial_messages"] is True
    assert captured["max_buffer_size"] == 123456
    assert captured["betas"] == ["context-1m-2025-08-07"]
    assert captured["user"] == "operator@example.test"
    assert captured["permission_prompt_tool_name"] == "permission_prompt"
    assert captured["enable_file_checkpointing"] is True
    assert captured["sandbox"] == {"enabled": True}
    assert captured["hooks"] is hooks
    assert captured["agents"] is agents
    assert captured["skills"] == ["playwright"]
    assert captured["plugins"] is plugins
    assert captured["session_store"] is session_store
    assert captured["fork_session"] is True
    assert captured["tool_search_policy"] == "force"
    assert captured["tool_permission_guard"] is permission_guard
