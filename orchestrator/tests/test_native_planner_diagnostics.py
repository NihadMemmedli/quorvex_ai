import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.utils import agent_runner as _agent_runner_module
from orchestrator.utils.agent_runner import AgentResult, AgentRunner, ToolCall
from orchestrator.workflows.native_planner import NativePlanner, SpecGenerationError

VALID_PLAN = """# Test Plan: Checkout

### TC-001: Complete checkout
**Description:** User completes checkout.
**Preconditions:** User has items in the cart.
**Steps:**
1. Navigate to the checkout page.
2. Fill required shipping details.
3. Submit payment.
**Expected Result:** The order confirmation appears.

## Draft Playwright Script
```typescript
import { test, expect } from '@playwright/test';

test('complete checkout', async ({ page }) => {
  await page.goto('https://example.test/checkout');
  await expect(page.getByRole('heading', { name: /checkout/i })).toBeVisible();
  await page.getByRole('button', { name: /pay/i }).click();
  await expect(page.getByText(/order confirmation/i)).toBeVisible();
});
```
"""

INVALID_PLAN_WITH_EVIDENCE = """# Test Plan: Checkout

### TC-001: Complete checkout
The checkout button was seen after cart review. The user can submit payment and see confirmation.
"""

VALID_PLAN_WITHOUT_DRAFT = """# Test Plan: Checkout

### TC-001: Complete checkout
**Description:** User completes checkout.
**Preconditions:** User has items in the cart.
**Steps:**
1. Navigate to the checkout page.
2. Fill required shipping details.
3. Submit payment.
**Expected Result:** The order confirmation appears.
"""

VALID_PLAN_WITH_BAD_DRAFT = """# Test Plan: Checkout

### TC-001: Complete checkout
**Description:** User completes checkout.
**Preconditions:** User has items in the cart.
**Steps:**
1. Navigate to the checkout page.
2. Fill required shipping details.
3. Submit payment.
**Expected Result:** The order confirmation appears.

## Draft Playwright Script
```typescript
import { test, expect } from '@playwright/test';

test('complete checkout', async ({ page }) => {
  await page.goto('https://example.test/checkout');
  await page.waitForTimeout(1000);
  await expect(page.getByText(/order confirmation/i)).toBeVisible();
});
```
"""


def _planner(tmp_path: Path) -> NativePlanner:
    planner = object.__new__(NativePlanner)
    planner.project_id = "project"
    planner.on_tool_use = None
    planner.on_progress = None
    planner.on_task_enqueued = None
    planner.owner_type = None
    planner.owner_id = None
    planner.owner_label = None
    planner.model_tier = "tool_deep"
    planner.session_dir = tmp_path / "run"
    planner.cwd = planner.session_dir
    planner.env_vars = {}
    planner.last_draft_script_path = None
    planner.last_runtime_preflight = None
    planner.specs_dir = tmp_path / "specs"
    planner.specs_dir.mkdir(parents=True)
    planner.session_dir.mkdir(parents=True)
    planner.memory_manager = SimpleNamespace(
        vector_store=SimpleNamespace(
            search_prd_context=lambda **_kwargs: [
                {
                    "content": "Checkout requirements",
                    "metadata": {"feature": "Checkout"},
                }
            ]
        )
    )
    return planner


def test_native_planner_disables_memory_when_env_false(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")

    def fail_memory(**_kwargs):
        raise AssertionError("memory should not initialize")

    import orchestrator.workflows.native_planner as native_planner_module

    monkeypatch.setattr(native_planner_module, "get_memory_manager", fail_memory)

    planner = NativePlanner(project_id="project", session_dir=tmp_path)

    assert planner.memory_manager is None


def test_native_planner_degrades_when_memory_initialization_fails(tmp_path, monkeypatch):
    class MemoryPanic(BaseException):
        pass

    def fail_memory(**_kwargs):
        raise MemoryPanic("chroma panic")

    import orchestrator.workflows.native_planner as native_planner_module

    monkeypatch.setenv("MEMORY_ENABLED", "true")
    monkeypatch.setattr(native_planner_module, "get_memory_manager", fail_memory)

    planner = NativePlanner(project_id="project", session_dir=tmp_path)

    assert planner.memory_manager is None


def _write_mcp_config(tmp_path: Path, server_name: str = "playwright-test") -> None:
    (tmp_path / ".mcp.json").write_text(
        f"""
{{
  "mcpServers": {{
    "{server_name}": {{
      "command": "npx",
      "args": ["@playwright/mcp"]
    }}
  }}
}}
"""
    )


def _patch_agent(
    monkeypatch: pytest.MonkeyPatch, planner: NativePlanner, result: AgentResult
) -> None:
    async def fake_query(_prompt: str, target_url: str | None = None) -> AgentResult:
        return result

    monkeypatch.setattr(planner, "_query_planner_agent", fake_query)


def _patch_agent_sequence(
    monkeypatch: pytest.MonkeyPatch,
    planner: NativePlanner,
    results: list[AgentResult],
) -> list[str]:
    prompts: list[str] = []
    remaining = list(results)

    async def fake_query(prompt: str, target_url: str | None = None) -> AgentResult:
        prompts.append(prompt)
        if not remaining:
            raise AssertionError("planner queried more times than expected")
        return remaining.pop(0)

    monkeypatch.setattr(planner, "_query_planner_agent", fake_query)
    return prompts


def _patch_repair_agent(
    monkeypatch: pytest.MonkeyPatch, planner: NativePlanner, result: AgentResult
) -> None:
    async def fake_repair(_prompt: str) -> AgentResult:
        return result

    monkeypatch.setattr(planner, "_query_repair_agent", fake_repair)


def _live_save_result(plan: str) -> AgentResult:
    return AgentResult(
        success=True,
        output=plan,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_setup_page",
                timestamp=datetime.now(),
                input={"seedFile": "tests/seed.spec.ts"},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_navigate",
                timestamp=datetime.now(),
                input={"url": "https://example.test/checkout"},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_snapshot",
                timestamp=datetime.now(),
                input={},
            ),
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": plan},
            ),
        ],
    )


@pytest.mark.asyncio
async def test_live_native_planner_does_not_attach_permission_guard_by_default(
    tmp_path, monkeypatch
):
    import orchestrator.workflows.native_planner as native_planner_module

    planner = _planner(tmp_path)
    captured: dict[str, Any] = {}

    class FakeRunner:
        def diagnostics(self, *, agent_class=None, prompt=None):
            return {
                "agent_class": agent_class,
                "execution_path": "queue",
                "provider": "anthropic_compatible",
                "runtime": "claude_sdk",
                "tier": "tool_deep",
                "model": "test-model",
                "api_key_set": True,
                "api_key_env": "QUORVEX_LLM_API_KEY",
                "claude_code_oauth_token_set": False,
                "auth_mode": "api_key",
                "queue": {"queue_eligible": True},
                "runtime_env_keys": ["QUORVEX_LLM_API_KEY"],
            }

        async def run(self, prompt):
            result = AgentResult(success=True, output=VALID_PLAN)
            return result

    def fake_create_agent_runner(source, **kwargs):
        captured.update(kwargs)
        return FakeRunner()

    monkeypatch.setattr(
        native_planner_module,
        "create_agent_runner",
        fake_create_agent_runner,
    )

    result = await planner._query_planner_agent(
        "plan checkout",
        target_url="https://example.test/checkout",
    )

    assert result.success is True
    assert captured["requires_live_browser"] is True
    assert "tool_permission_guard" not in captured
    assert result.runtime_diagnostics["execution_path"] == "queue"


def test_native_and_custom_queue_runners_receive_same_masked_runtime_env_keys(
    tmp_path, monkeypatch
):
    from orchestrator.services.agent_prompt_runtime import create_agent_runner

    runtime_env = {
        "QUORVEX_LLM_PROVIDER": "anthropic_compatible",
        "QUORVEX_LLM_AUTH_MODE": "api_key",
        "QUORVEX_LLM_API_KEY": "secret-runtime-key",
        "QUORVEX_LLM_TOOL_DEEP_MODEL": "tool-model",
        "CLAUDE_CODE_OAUTH_TOKEN": "secret-oauth-token",
    }
    planner = _planner(tmp_path)
    planner.env_vars = dict(runtime_env)
    custom_runner = AgentRunner(
        allowed_tools=["Read"],
        tools=["Read"],
        model_tier="tool_deep",
        env_vars=dict(runtime_env),
    )
    native_runner = create_agent_runner(
        planner,
        timeout_seconds=30,
        tool_config={"allowed_tools": ["Read"], "tools": ["Read"]},
        log_tools=False,
        memory_agent_type="NativePlanner",
        memory_source_type="prd",
        memory_stage="native_planner",
        inject_memory=False,
        model_tier="tool_deep",
        session_dir=planner.session_dir,
    )

    custom_keys = set((custom_runner._collect_api_env_vars() or {}).keys())
    native_keys = set((native_runner._collect_api_env_vars() or {}).keys())
    native_diagnostics = native_runner.diagnostics(prompt="plan")

    assert native_keys == custom_keys
    assert "QUORVEX_LLM_API_KEY" in native_keys
    assert "CLAUDE_CODE_OAUTH_TOKEN" in native_keys
    assert native_diagnostics["runtime_env_keys"] == sorted(native_keys)
    assert "secret-runtime-key" not in json.dumps(native_diagnostics)
    assert "secret-oauth-token" not in json.dumps(native_diagnostics)


def test_planner_max_attempts_defaults_to_five_and_caps_env(monkeypatch):
    monkeypatch.delenv("PLANNER_MAX_ATTEMPTS", raising=False)
    assert NativePlanner._planner_max_attempts() == 5

    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "9")
    assert NativePlanner._planner_max_attempts() == 5

    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "0")
    assert NativePlanner._planner_max_attempts() == 1

    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "bad")
    assert NativePlanner._planner_max_attempts() == 5


async def _run_agent_with_events(
    monkeypatch: pytest.MonkeyPatch,
    events: list[Any],
) -> AgentResult:
    async def fake_query(*args, **kwargs):
        for event in events:
            yield event

    monkeypatch.setattr(_agent_runner_module, "query", fake_query)
    monkeypatch.setattr(_agent_runner_module, "ClaudeAgentOptions", lambda **kwargs: kwargs)
    monkeypatch.setattr(_agent_runner_module, "AGENT_QUEUE_AVAILABLE", False)

    runner = AgentRunner(
        allowed_tools=[],
        log_tools=False,
        inject_memory=False,
        capture_memory=False,
    )
    return await runner.run("plan checkout")


class TextBlock:
    def __init__(self, text: str):
        self.text = text


class ToolUseBlock:
    def __init__(self, id: str, name: str, input: dict):
        self.id = id
        self.name = name
        self.input = input


class ToolResultBlock:
    def __init__(self, tool_use_id: str, content: str, is_error: bool | None = None):
        self.tool_use_id = tool_use_id
        self.content = content
        self.is_error = is_error


class AssistantMessage:
    def __init__(self, content: list[Any]):
        self.content = content


class UserMessage:
    def __init__(self, content: list[Any]):
        self.content = content


@pytest.mark.asyncio
async def test_agent_runner_parses_assistant_text_message(monkeypatch):
    result = await _run_agent_with_events(
        monkeypatch,
        [
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "done"}]},
            }
        ],
    )

    assert result.success is True
    assert result.output == "done"
    assert result.messages_received == 1
    assert result.text_blocks_received == 1
    assert result.tool_calls == []


@pytest.mark.asyncio
async def test_agent_runner_parses_sdk_block_objects_without_type_attributes(monkeypatch):
    result = await _run_agent_with_events(
        monkeypatch,
        [
            AssistantMessage(
                [
                    TextBlock("opening page"),
                    ToolUseBlock(
                        "toolu_snapshot",
                        "mcp__playwright-test__browser_snapshot",
                        {},
                    ),
                ]
            ),
            UserMessage([ToolResultBlock("toolu_snapshot", "snapshot captured")]),
            AssistantMessage([TextBlock("done")]),
        ],
    )

    assert result.success is True
    assert result.output == "opening page\ndone"
    assert result.messages_received == 3
    assert result.text_blocks_received == 2
    assert [call.name for call in result.tool_calls] == [
        "mcp__playwright-test__browser_snapshot"
    ]
    assert result.tool_calls[0].result_preview == "snapshot captured"


@pytest.mark.asyncio
async def test_agent_runner_parses_sdk_stream_event_text_delta(monkeypatch):
    result = await _run_agent_with_events(
        monkeypatch,
        [
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "partial text"},
                },
            }
        ],
    )

    assert result.success is True
    assert result.output == "partial text"
    assert result.messages_received == 1
    assert result.text_blocks_received == 1


@pytest.mark.asyncio
async def test_agent_runner_parses_top_level_sdk_text_delta(monkeypatch):
    result = await _run_agent_with_events(
        monkeypatch,
        [
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "top-level text"},
            }
        ],
    )

    assert result.success is True
    assert result.output == "top-level text"
    assert result.text_blocks_received == 1


@pytest.mark.asyncio
async def test_agent_runner_parses_sdk_stream_event_tool_lifecycle(monkeypatch):
    result = await _run_agent_with_events(
        monkeypatch,
        [
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_start",
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "mcp__playwright-test__browser_snapshot",
                        "input": {"fullPage": True},
                    },
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "snapshot captured",
                        }
                    ]
                },
            },
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "done"},
                },
            },
        ],
    )

    assert result.success is True
    assert result.output == "done"
    assert result.messages_received == 3
    assert result.text_blocks_received == 1
    assert [call.name for call in result.tool_calls] == ["mcp__playwright-test__browser_snapshot"]
    assert result.tool_calls[0].input == {"fullPage": True}
    assert result.tool_calls[0].result_preview == "snapshot captured"


@pytest.mark.asyncio
async def test_agent_runner_reconstructs_streamed_tool_input(monkeypatch):
    payload = json.dumps({"content": VALID_PLAN, "fileName": "checkout.md"})
    split_at = payload.index(VALID_PLAN[:10])
    result = await _run_agent_with_events(
        monkeypatch,
        [
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_save",
                    "name": "mcp__playwright-test__planner_save_plan",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": payload[:split_at],
                },
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": payload[split_at:],
                },
            },
            {"type": "content_block_stop", "index": 1},
        ],
    )

    assert result.success is True
    assert [call.name for call in result.tool_calls] == [
        "mcp__playwright-test__planner_save_plan"
    ]
    assert result.tool_calls[0].duration_ms is None
    assert result.tool_calls[0].input == {
        "content": VALID_PLAN,
        "fileName": "checkout.md",
    }


@pytest.mark.asyncio
async def test_agent_runner_treats_tool_activity_without_text_as_productive(
    monkeypatch,
):
    result = await _run_agent_with_events(
        monkeypatch,
        [
            {
                "type": "stream_event",
                "stream_event": {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_snapshot",
                        "name": "mcp__playwright-test__browser_snapshot",
                        "input": {},
                    },
                },
            }
        ],
    )

    assert result.success is True
    assert result.output == ""
    assert result.tool_calls[0].name == "mcp__playwright-test__browser_snapshot"


@pytest.mark.asyncio
async def test_pending_planner_save_plan_can_supply_plan_content(monkeypatch):
    payload = json.dumps({"content": VALID_PLAN})
    result = await _run_agent_with_events(
        monkeypatch,
        [
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu_save",
                    "name": "mcp__playwright-test__planner_save_plan",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": payload},
            },
            {"type": "content_block_stop", "index": 0},
        ],
    )

    assert NativePlanner._extract_plan_content(result) == VALID_PLAN


@pytest.mark.asyncio
async def test_query_live_planner_uses_restricted_tool_config(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    _write_mcp_config(planner.cwd)
    captured: dict = {}

    class FakeRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self, prompt: str) -> AgentResult:
            captured["prompt"] = prompt
            return AgentResult(success=True, output="")

    monkeypatch.setattr("orchestrator.workflows.native_planner.AgentRunner", FakeRunner)

    await planner._query_planner_agent(
        "plan this flow",
        target_url="https://example.test/checkout",
    )

    assert "mcp__playwright-test__planner_setup_page" in captured["allowed_tools"]
    assert "mcp__playwright-test__generator_write_test" in captured["allowed_tools"]
    assert "mcp__playwright-test__test_run" in captured["allowed_tools"]
    assert "mcp__playwright-test__browser_snapshot" in captured["tools"]
    assert "mcp__playwright-test__browser_handle_dialog" in captured["allowed_tools"]
    assert "mcp__playwright-test__browser_handle_dialog" in captured["tools"]
    assert "mcp__playwright-test__browser_run_code" not in captured["allowed_tools"]
    assert "mcp__playwright-test__browser_evaluate" not in captured["tools"]
    assert "mcp__playwright-test__browser_close" not in captured["allowed_tools"]
    assert "mcp__playwright-test__browser_close" not in captured["tools"]


@pytest.mark.asyncio
async def test_planner_retry_passes_resume_session_to_agent_runner(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    captured: dict = {}

    class FakeRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self, prompt: str) -> AgentResult:
            return AgentResult(success=True, output="", session_id="sdk-session-2")

    monkeypatch.setattr("orchestrator.workflows.native_planner.AgentRunner", FakeRunner)
    planner._planner_retry_session_id = "sdk-session-1"
    planner._planner_retry_continue_conversation = False

    result = await planner._query_planner_agent("retry this", target_url=None)

    assert result.session_id == "sdk-session-2"
    assert captured["resume_session_id"] == "sdk-session-1"
    assert captured["continue_conversation"] is False


@pytest.mark.asyncio
async def test_flow_context_normalizes_target_url_before_prompt(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    prompts: list[str] = []
    target_urls: list[str | None] = []

    async def fake_query(prompt: str, target_url: str | None = None) -> AgentResult:
        prompts.append(prompt)
        target_urls.append(target_url)
        return _live_save_result(VALID_PLAN)

    monkeypatch.setattr(planner, "_query_planner_agent", fake_query)

    await planner.generate_spec_from_flow_context(
        flow_title="Checkout",
        flow_context="Checkout flow",
        target_url="https://example.test/checkout`",
        output_dir=tmp_path / "run",
    )

    assert target_urls == ["https://example.test/checkout"]
    assert "https://example.test/checkout`" not in prompts[0]
    assert "- **Target URL**: https://example.test/checkout" in prompts[0]


def test_retry_prompt_preserves_compact_rejected_attempt_context(tmp_path):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    expected.parent.mkdir(parents=True)
    expected.write_text(VALID_PLAN_WITHOUT_DRAFT)
    error = SpecGenerationError(
        "Live-browser planner did not navigate to the Target URL before finishing.",
        diagnostics={
            "expected_target_url": "https://example.test/checkout",
            "target_navigation_observed": False,
        },
    )

    prompt = planner._build_planner_retry_prompt(
        original_prompt="Original checkout task",
        subject_type="flow",
        subject_name="Checkout",
        error=error,
        target_url="https://example.test/checkout",
        expected_output_path=expected,
        agent_result=_live_save_result(VALID_PLAN_WITHOUT_DRAFT),
    )

    assert "Previous attempt compact context" in prompt
    assert "Previous tool sequence" in prompt
    assert "Rejected saved plan preview" in prompt
    assert "browser_navigate" in prompt
    assert "payload_preview" in prompt
    assert "Complete checkout" in prompt


@pytest.mark.asyncio
async def test_empty_agent_result_raises_diagnostic_error(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(
            success=True,
            output="",
            messages_received=0,
            text_blocks_received=0,
            tool_calls=[],
        ),
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_for_feature("Checkout", "prd-project")

    message = str(exc_info.value)
    assert "agent produced no output" in message
    assert "messages=0" in message
    assert "tool_calls=0" in message
    assert "planner_save_plan_observed=False" in message
    assert "expected_output_path=" in message
    assert exc_info.value.diagnostics["valid_saved_plan_observed"] is False


@pytest.mark.asyncio
async def test_timed_out_agent_result_surfaces_timeout(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(
            success=False,
            output="",
            timed_out=True,
            messages_received=2,
            text_blocks_received=1,
        ),
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert "timed out" in str(exc_info.value)
    assert exc_info.value.diagnostics["timed_out"] is True
    assert "longer planner timeout" in exc_info.value.diagnostics["next_action"]


@pytest.mark.asyncio
async def test_errored_agent_result_surfaces_agent_error(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(
            success=False, output="", error="queue unavailable", messages_received=1
        ),
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert "queue unavailable" in str(exc_info.value)
    assert exc_info.value.diagnostics["agent_error"] == "queue unavailable"
    assert "SDK/queue" in exc_info.value.diagnostics["next_action"]


@pytest.mark.asyncio
async def test_valid_saved_plan_recovered_from_expected_output_path(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    expected.parent.mkdir(parents=True)
    expected.write_text(VALID_PLAN)
    _patch_agent(monkeypatch, planner, AgentResult(success=True, output=""))

    path = await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert path == expected
    assert path.read_text().strip() == VALID_PLAN.strip()


@pytest.mark.asyncio
async def test_valid_saved_plan_recovered_from_session_artifact(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    artifact = planner.session_dir / "nested" / "planner-output.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(VALID_PLAN)
    _patch_agent(monkeypatch, planner, AgentResult(success=True, output=""))

    path = await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert path == planner.specs_dir / "prd-project" / "checkout.md"
    assert path.read_text() == VALID_PLAN


@pytest.mark.asyncio
async def test_valid_save_plan_payload_used_before_recursive_artifact_scan(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    noisy_artifact = planner.session_dir / "planner-output.md"
    noisy_artifact.write_text("# Checkout Summary\n\nNot a structured plan.")
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(
            success=True,
            output="",
            tool_calls=[
                ToolCall(
                    name="mcp__playwright-test__planner_save_plan",
                    timestamp=datetime.now(),
                    input={"content": VALID_PLAN},
                )
            ],
        ),
    )

    path = await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert path.read_text().strip() == VALID_PLAN.strip()


def test_saved_plan_recovery_ignores_claude_prompt_agent_and_skill_markdown(tmp_path):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    for relative in (
        ".claude/agents/planner-output.md",
        ".claude/prompts/test-plan.md",
        ".claude/skills/browser/test-plan.md",
    ):
        artifact = planner.session_dir / relative
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(VALID_PLAN)

    assert planner._recover_saved_plan(expected) is None
    assert not expected.exists()


def test_saved_plan_recovery_uses_conservative_artifact_names(tmp_path):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    artifact = planner.session_dir / "generated-plan.md"
    artifact.write_text(VALID_PLAN)

    assert planner._recover_saved_plan(expected) is None
    assert not expected.exists()


def test_invalid_likely_saved_plan_logs_single_warning(tmp_path, caplog):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    artifact = planner.session_dir / "planner-output.md"
    artifact.write_text("# Checkout Summary\n\nNot a structured plan.")

    caplog.set_level("WARNING")

    assert planner._recover_saved_plan(expected) is None

    warnings = [
        record
        for record in caplog.records
        if "Ignoring invalid saved plan" in record.getMessage()
    ]
    assert len(warnings) == 1
    assert str(artifact) in warnings[0].getMessage()


def test_expected_saved_plan_is_not_revalidated_after_direct_recovery(tmp_path, caplog):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    expected.parent.mkdir(parents=True)
    expected.write_text("# Checkout Summary\n\nNot a structured plan.")

    caplog.set_level("WARNING")

    assert planner._recover_expected_saved_plan(expected) is None
    assert planner._recover_saved_plan(expected, include_expected=False) is None

    expected_warnings = [
        record
        for record in caplog.records
        if "Ignoring invalid saved plan" in record.getMessage()
        and str(expected) in record.getMessage()
    ]
    assert len(expected_warnings) == 1


@pytest.mark.asyncio
async def test_invalid_saved_plan_without_test_case_structure_fails(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    expected.parent.mkdir(parents=True)
    expected.write_text("# Checkout Summary\n\nI created a plan in the workspace.")
    _patch_agent(monkeypatch, planner, AgentResult(success=True, output=""))
    _patch_repair_agent(
        monkeypatch,
        planner,
        AgentResult(success=True, output="# Checkout Summary\n\nStill invalid."),
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert "repair did not produce a valid test plan" in str(exc_info.value)


@pytest.mark.asyncio
async def test_invalid_saved_markdown_with_save_plan_evidence_invokes_repair(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    expected.parent.mkdir(parents=True)
    expected.write_text(INVALID_PLAN_WITH_EVIDENCE)
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(
            success=True,
            output="I created checkout coverage.",
            tool_calls=[
                ToolCall(
                    name="mcp__playwright-test__planner_save_plan",
                    timestamp=datetime.now(),
                    input={"content": INVALID_PLAN_WITH_EVIDENCE},
                )
            ],
        ),
    )
    _patch_repair_agent(
        monkeypatch, planner, AgentResult(success=True, output=VALID_PLAN)
    )

    path = await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert path == expected
    assert path.read_text().strip() == VALID_PLAN.strip()
    attempt = json.loads(
        (planner.session_dir / "planner_repair_attempt.json").read_text()
    )
    assert attempt["attempted"] is True
    assert attempt["accepted"] is True
    assert attempt["rejected_artifacts"][0]["path"] == str(expected)
    assert attempt["rejected_save_plan_payloads"][0]["length"] == len(
        INVALID_PLAN_WITH_EVIDENCE
    )


@pytest.mark.asyncio
async def test_repair_not_attempted_when_no_useful_evidence_exists(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(
            success=True,
            output="",
            messages_received=0,
            text_blocks_received=0,
            tool_calls=[],
        ),
    )

    async def fail_if_called(_prompt: str) -> AgentResult:
        raise AssertionError("repair should not be attempted without evidence")

    monkeypatch.setattr(planner, "_query_repair_agent", fail_if_called)

    with pytest.raises(SpecGenerationError):
        await planner.generate_spec_for_feature("Checkout", "prd-project")

    attempt = json.loads(
        (planner.session_dir / "planner_repair_attempt.json").read_text()
    )
    assert attempt["attempted"] is False
    assert attempt["accepted"] is False
    assert attempt["useful_evidence"] is False


@pytest.mark.asyncio
async def test_repair_failure_raises_with_diagnostics_and_artifact_metadata(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    expected.parent.mkdir(parents=True)
    expected.write_text(INVALID_PLAN_WITH_EVIDENCE)
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(
            success=True,
            output="I found checkout evidence.",
            tool_calls=[
                ToolCall(
                    name="mcp__playwright-test__planner_save_plan",
                    timestamp=datetime.now(),
                    input={"content": INVALID_PLAN_WITH_EVIDENCE},
                )
            ],
        ),
    )
    _patch_repair_agent(
        monkeypatch,
        planner,
        AgentResult(
            success=True,
            output="# Test Plan: Checkout\n\n### TC-001: Still missing fields\n",
        ),
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert "repair did not produce a valid test plan" in str(exc_info.value)
    assert exc_info.value.diagnostics["planner_repair_attempted"] is True
    assert exc_info.value.diagnostics["planner_repair_accepted"] is False
    assert exc_info.value.diagnostics["rejected_artifact_count"] == 1
    assert exc_info.value.diagnostics["rejected_save_plan_payload_count"] == 1
    assert exc_info.value.diagnostics["planner_repair_artifact_path"].endswith(
        "planner_repair_attempt.json"
    )
    attempt = json.loads(
        (planner.session_dir / "planner_repair_attempt.json").read_text()
    )
    assert attempt["attempted"] is True
    assert attempt["accepted"] is False
    assert "missing required fields" in attempt["validation_failure_reason"]


@pytest.mark.asyncio
async def test_flow_context_generation_uses_same_repair_recovery(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    output_dir = planner.specs_dir / "flows"
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(
            success=True,
            output="Saved a rough plan.",
            tool_calls=[
                ToolCall(
                    name="mcp__playwright-test__planner_setup_page",
                    timestamp=datetime.now(),
                    input={"seedFile": "tests/seed.spec.ts"},
                ),
                ToolCall(
                    name="mcp__playwright-test__browser_navigate",
                    timestamp=datetime.now(),
                    input={"url": "https://example.test/checkout"},
                ),
                ToolCall(
                    name="mcp__playwright-test__browser_snapshot",
                    timestamp=datetime.now(),
                    input={},
                ),
                ToolCall(
                    name="mcp__playwright-test__planner_save_plan",
                    timestamp=datetime.now(),
                    input={"content": INVALID_PLAN_WITH_EVIDENCE},
                ),
            ],
        ),
    )
    _patch_repair_agent(
        monkeypatch, planner, AgentResult(success=True, output=VALID_PLAN)
    )

    path = await planner.generate_spec_from_flow_context(
        "Checkout",
        "Flow context",
        "https://example.test/checkout",
        output_dir=output_dir,
    )

    assert path == output_dir / "checkout.md"
    assert path.read_text().strip() == VALID_PLAN.strip()


def test_extract_plan_content_ignores_unstructured_save_plan_tool_call():
    result = AgentResult(
        success=True,
        output="",
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": "# Checkout Summary\n\nI created the plan."},
            )
        ],
    )

    assert NativePlanner._extract_plan_content(result) is None


def test_extract_plan_content_requires_required_schema_fields():
    result = AgentResult(
        success=True,
        output="",
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": INVALID_PLAN_WITH_EVIDENCE},
            )
        ],
    )

    assert NativePlanner._extract_plan_content(result) is None


def test_extract_plan_content_renders_structured_planner_save_plan_payload():
    result = AgentResult(
        success=True,
        output="",
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={
                    "name": "Test Plan: Checkout",
                    "fileName": "/tmp/checkout.md",
                    "overview": (
                        "Checkout page observed.\n\n"
                        "## Draft Playwright Script\n"
                        "```typescript\n"
                        "import { test, expect } from '@playwright/test';\n"
                        "test('checkout', async ({ page }) => {\n"
                        "  await expect(page.getByRole('button', { name: /pay/i })).toBeVisible();\n"
                        "});\n"
                        "```"
                    ),
                    "suites": [
                        {
                            "name": "Checkout",
                            "seedFile": "tests/seed.spec.ts",
                            "tests": [
                                {
                                    "name": "Complete checkout",
                                    "file": "tests/generated/checkout.spec.ts",
                                    "steps": ["Click Pay"],
                                    "expectedResults": ["Confirmation appears"],
                                }
                            ],
                        }
                    ],
                },
            )
        ],
    )

    content = NativePlanner._extract_plan_content(result)

    assert content is not None
    assert "### TC-001: Complete checkout" in content
    assert "## Draft Playwright Script" in content
    assert NativePlanner._is_valid_test_plan(content)


def test_repair_evidence_preview_redacts_sensitive_text(tmp_path):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    expected.parent.mkdir(parents=True)
    expected.write_text(
        "# Test Plan: Checkout\n\npassword: do-not-store\nAuthorization: Bearer abc123"
    )

    evidence = planner._collect_repair_evidence(
        AgentResult(success=True, output="token=raw-output-secret"), expected
    )

    assert "do-not-store" not in evidence["rejected_artifacts"][0]["preview"]
    assert "abc123" not in evidence["rejected_artifacts"][0]["preview"]
    assert "raw-output-secret" not in evidence["raw_output"]["preview"]
    assert "[REDACTED]" in evidence["rejected_artifacts"][0]["preview"]


def test_tool_call_debug_output_includes_redacted_truncated_input_metadata(tmp_path):
    runner = AgentRunner(session_dir=tmp_path)
    long_content = "# Test Plan: Checkout\n" + ("A" * 1500)
    runner._save_debug_output(
        "raw output",
        [
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                duration_ms=12,
                success=True,
                input={
                    "content": long_content,
                    "password": "super-secret",
                    "nested": {"api_key": "abc123"},
                },
            )
        ],
        messages_received=1,
    )

    tool_calls = json.loads((tmp_path / "tool_calls.json").read_text())
    first = tool_calls[0]
    assert first["name"] == "mcp__playwright-test__planner_save_plan"
    assert first["success"] is True
    assert first["input_content_length"] == len(long_content)
    assert len(first["content_hash"]) == 64
    assert first["input_preview"]["password"] == "[REDACTED]"
    assert first["input_preview"]["nested"]["api_key"] == "[REDACTED]"
    assert "truncated" in first["input_preview"]["content"]


def test_session_jsonl_recovery_produces_valid_live_planner_sequence(tmp_path):
    session_id = "sdk-session-jsonl"
    project_dir = tmp_path / "projects" / "checkout"
    project_dir.mkdir(parents=True)

    def tool_use(tool_id, name, tool_input=None):
        return {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": f"mcp__playwright-test__{name}",
                        "input": tool_input or {},
                    }
                ]
            },
        }

    def tool_result(tool_id, content="ok"):
        return {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": content,
                    }
                ]
            },
        }

    events = [
        tool_use("setup", "planner_setup_page", {"seedFile": "tests/seed.spec.ts"}),
        tool_result("setup"),
        tool_use("nav", "browser_navigate", {"url": "https://example.test/checkout"}),
        tool_result("nav"),
        tool_use("snapshot", "browser_snapshot"),
        tool_result("snapshot", 'https://example.test/checkout\n- heading "Checkout"'),
        tool_use("save", "planner_save_plan", {"content": VALID_PLAN}),
        tool_result("save"),
    ]
    (project_dir / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events)
    )

    runner = AgentRunner(session_dir=tmp_path, cwd=tmp_path)
    tool_calls = runner._recover_tool_calls_from_session_jsonl(session_id)
    result = AgentResult(success=True, output=VALID_PLAN, tool_calls=tool_calls)

    assert [NativePlanner._tool_call_short_name(call) for call in tool_calls] == [
        "planner_setup_page",
        "browser_navigate",
        "browser_snapshot",
        "planner_save_plan",
    ]
    assert tool_calls[2].result_preview.startswith("https://example.test/checkout")
    NativePlanner._validate_live_plan_tool_sequence(
        result, "https://example.test/checkout"
    )


def test_live_plan_rejected_when_saved_before_target_navigation():
    result = AgentResult(
        success=True,
        output=VALID_PLAN,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_setup_page",
                timestamp=datetime.now(),
                input={"seedFile": "tests/seed.spec.ts"},
            ),
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": VALID_PLAN},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_navigate",
                timestamp=datetime.now(),
                input={"url": "https://example.test/checkout"},
            ),
        ],
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        NativePlanner._validate_live_plan_tool_sequence(
            result, "https://example.test/checkout"
        )

    assert "before navigating" in str(exc_info.value)
    assert exc_info.value.diagnostics["target_navigation_observed"] is False


def test_live_plan_accepted_after_setup_target_navigation_snapshot_and_save():
    result = AgentResult(
        success=True,
        output=VALID_PLAN,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_setup_page",
                timestamp=datetime.now(),
                input={"seedFile": "tests/seed.spec.ts"},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_navigate",
                timestamp=datetime.now(),
                input={"url": "https://example.test/checkout/"},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_snapshot",
                timestamp=datetime.now(),
                input={},
            ),
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": VALID_PLAN},
            ),
        ],
    )

    NativePlanner._validate_live_plan_tool_sequence(
        result, "https://example.test/checkout"
    )


def test_live_plan_accepts_target_url_from_snapshot_metadata_when_navigate_input_missing():
    result = AgentResult(
        success=True,
        output=VALID_PLAN,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_setup_page",
                timestamp=datetime.now(),
                input={"seedFile": "tests/seed.spec.ts"},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_navigate",
                timestamp=datetime.now(),
                input={},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_snapshot",
                timestamp=datetime.now(),
                input={},
                result_preview='Page URL: https://example.test/checkout\n- heading "Checkout"',
            ),
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": VALID_PLAN},
            ),
        ],
    )

    NativePlanner._validate_live_plan_tool_sequence(
        result, "https://example.test/checkout"
    )


def test_live_plan_validation_cleans_markdown_target_url():
    result = AgentResult(
        success=True,
        output=VALID_PLAN,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_setup_page",
                timestamp=datetime.now(),
                input={"seedFile": "tests/seed.spec.ts"},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_navigate",
                timestamp=datetime.now(),
                input={"url": "https://example.test/checkout?view=List"},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_snapshot",
                timestamp=datetime.now(),
                input={},
            ),
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": VALID_PLAN},
            ),
        ],
    )

    NativePlanner._validate_live_plan_tool_sequence(
        result, "https://example.test/checkout?view=List`"
    )


def test_live_plan_rejected_when_saved_before_snapshot_after_navigation():
    result = AgentResult(
        success=True,
        output=VALID_PLAN,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_setup_page",
                timestamp=datetime.now(),
                input={"seedFile": "tests/seed.spec.ts"},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_navigate",
                timestamp=datetime.now(),
                input={"url": "https://example.test/checkout"},
            ),
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": VALID_PLAN},
            ),
        ],
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        NativePlanner._validate_live_plan_tool_sequence(
            result, "https://example.test/checkout"
        )

    assert "before navigating" in str(exc_info.value)
    assert exc_info.value.diagnostics["target_navigation_observed"] is True
    assert (
        exc_info.value.diagnostics["browser_snapshot_after_navigation_observed"]
        is False
    )


def test_failed_browser_navigate_does_not_satisfy_live_plan_sequence():
    result = AgentResult(
        success=True,
        output=VALID_PLAN,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_setup_page",
                timestamp=datetime.now(),
                input={"seedFile": "tests/seed.spec.ts"},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_navigate",
                timestamp=datetime.now(),
                input={"url": "https://example.test/checkout"},
                success=False,
                error="Browser tool timed out: browser_navigate",
            ),
            ToolCall(
                name="mcp__playwright-test__browser_snapshot",
                timestamp=datetime.now(),
                input={},
            ),
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": VALID_PLAN},
            ),
        ],
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        NativePlanner._validate_live_plan_tool_sequence(
            result, "https://example.test/checkout"
        )

    assert exc_info.value.diagnostics["phase"] == "browser_session_failed"
    assert exc_info.value.diagnostics["requires_fresh_browser"] is True
    assert exc_info.value.diagnostics["target_navigation_observed"] is False


def test_finalize_live_plan_writes_planner_draft_script(tmp_path):
    planner = _planner(tmp_path)
    plan_path = tmp_path / "run" / "checkout.md"
    plan_path.write_text(VALID_PLAN)

    output = planner._finalize_plan_artifact(
        plan_path=plan_path,
        expected_output_path=plan_path,
        require_draft_script=True,
    )

    draft_path = plan_path.with_suffix(".draft.spec.ts")
    assert output == plan_path
    assert planner.last_draft_script_path == draft_path
    assert draft_path.exists()
    assert "test('complete checkout'" in draft_path.read_text()


def test_finalize_live_plan_rejects_missing_draft_script(tmp_path):
    planner = _planner(tmp_path)
    plan_path = tmp_path / "run" / "checkout.md"
    plan_path.write_text(VALID_PLAN_WITHOUT_DRAFT)

    with pytest.raises(SpecGenerationError) as exc_info:
        planner._finalize_plan_artifact(
            plan_path=plan_path,
            expected_output_path=plan_path,
            require_draft_script=True,
        )

    assert "Draft Playwright Script" in str(exc_info.value)
    assert exc_info.value.diagnostics["planner_draft_script_observed"] is False


@pytest.mark.asyncio
async def test_live_plan_repairs_missing_draft_without_browser_retry(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "2")
    prompts = _patch_agent_sequence(
        monkeypatch,
        planner,
        [_live_save_result(VALID_PLAN_WITHOUT_DRAFT)],
    )
    _patch_repair_agent(
        monkeypatch, planner, AgentResult(success=True, output=VALID_PLAN)
    )

    path = await planner.generate_spec_from_flow_context(
        flow_title="Checkout",
        flow_context="Checkout flow",
        target_url="https://example.test/checkout",
        output_dir=tmp_path / "run",
    )

    draft_path = path.with_suffix(".draft.spec.ts")
    assert len(prompts) == 1
    assert path.read_text().strip() == VALID_PLAN.strip()
    assert planner.last_draft_script_path == draft_path
    assert draft_path.exists()
    attempt = json.loads(
        (planner.session_dir / "planner_repair_attempt.json").read_text()
    )
    assert attempt["attempted"] is True
    assert attempt["accepted"] is True
    assert (
        attempt["draft_script_validation_failure"]
        == "missing Draft Playwright Script fenced TypeScript block"
    )
    assert (
        attempt["rejected_artifacts"][0]["validation_failure_reason"]
        == "missing Draft Playwright Script fenced TypeScript block"
    )


@pytest.mark.asyncio
async def test_live_plan_repairs_invalid_draft_without_browser_retry(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "2")
    prompts = _patch_agent_sequence(
        monkeypatch,
        planner,
        [_live_save_result(VALID_PLAN_WITH_BAD_DRAFT)],
    )
    _patch_repair_agent(
        monkeypatch, planner, AgentResult(success=True, output=VALID_PLAN)
    )

    path = await planner.generate_spec_from_flow_context(
        flow_title="Checkout",
        flow_context="Checkout flow",
        target_url="https://example.test/checkout",
        output_dir=tmp_path / "run",
    )

    assert len(prompts) == 1
    assert path.read_text().strip() == VALID_PLAN.strip()
    attempt = json.loads(
        (planner.session_dir / "planner_repair_attempt.json").read_text()
    )
    assert attempt["attempted"] is True
    assert attempt["accepted"] is True
    assert (
        attempt["draft_script_validation_failure"]
        == "draft script uses page.waitForTimeout()"
    )


def test_collect_repair_evidence_keeps_schema_valid_plan_for_draft_failure(tmp_path):
    planner = _planner(tmp_path)
    expected = planner.specs_dir / "prd-project" / "checkout.md"
    expected.parent.mkdir(parents=True)
    expected.write_text(VALID_PLAN_WITHOUT_DRAFT)

    evidence = planner._collect_repair_evidence(
        _live_save_result(VALID_PLAN_WITHOUT_DRAFT),
        expected,
        draft_script_validation_failure="missing Draft Playwright Script fenced TypeScript block",
    )

    assert evidence["useful_evidence"] is True
    assert evidence["rejected_artifacts"][0]["path"] == str(expected)
    assert (
        evidence["rejected_artifacts"][0]["validation_failure_reason"]
        == "missing Draft Playwright Script fenced TypeScript block"
    )
    assert (
        evidence["rejected_save_plan_payloads"][0]["validation_failure_reason"]
        == "missing Draft Playwright Script fenced TypeScript block"
    )


@pytest.mark.asyncio
async def test_live_plan_draft_repair_failure_retries_until_max_attempts(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "2")
    prompts = _patch_agent_sequence(
        monkeypatch,
        planner,
        [
            _live_save_result(VALID_PLAN_WITHOUT_DRAFT),
            _live_save_result(VALID_PLAN_WITHOUT_DRAFT),
        ],
    )
    _patch_repair_agent(
        monkeypatch,
        planner,
        AgentResult(success=True, output=VALID_PLAN_WITHOUT_DRAFT),
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_from_flow_context(
            flow_title="Checkout",
            flow_context="Checkout flow",
            target_url="https://example.test/checkout",
            output_dir=tmp_path / "run",
        )

    assert len(prompts) == 2
    assert "Previous tool sequence" in prompts[1]
    assert "Rejected saved plan preview" in prompts[1]
    assert exc_info.value.diagnostics["planner_repair_attempted"] is True
    assert exc_info.value.diagnostics["planner_repair_accepted"] is False
    assert (
        exc_info.value.diagnostics["planner_draft_script_validation_failure"]
        == "missing Draft Playwright Script fenced TypeScript block"
    )


@pytest.mark.asyncio
async def test_live_plan_permission_guard_blocks_save_until_contract(tmp_path):
    planner = _planner(tmp_path)
    guard = planner._build_live_plan_permission_guard("https://example.test/checkout")
    if guard is None:
        pytest.skip("claude_agent_sdk permission result classes unavailable")

    denied = await guard("mcp__playwright-test__planner_save_plan", {}, None)
    assert denied.behavior == "deny"
    assert "planner_setup_page" in denied.message

    denied_close = await guard("mcp__playwright-test__browser_close", {}, None)
    assert denied_close.behavior == "deny"
    assert "system-owned" in denied_close.message

    denied_run_code = await guard("mcp__playwright-test__browser_run_code", {}, None)
    assert denied_run_code.behavior == "deny"

    denied_upload = await guard("mcp__playwright-test__browser_file_upload", {}, None)
    assert denied_upload.behavior == "deny"

    allowed_evaluate = await guard("mcp__playwright-test__browser_evaluate", {}, None)
    assert allowed_evaluate.behavior == "allow"

    await guard(
        "mcp__playwright-test__planner_setup_page",
        {"seedFile": "tests/seed.spec.ts"},
        None,
    )
    await guard(
        "mcp__playwright-test__browser_navigate",
        {"url": "https://example.test/checkout"},
        None,
    )
    denied_before_snapshot = await guard(
        "mcp__playwright-test__planner_save_plan",
        {"content": VALID_PLAN},
        None,
    )
    assert denied_before_snapshot.behavior == "deny"
    assert "browser_snapshot" in denied_before_snapshot.message

    await guard("mcp__playwright-test__browser_snapshot", {}, None)
    allowed = await guard(
        "mcp__playwright-test__planner_save_plan",
        {"content": VALID_PLAN},
        None,
    )
    assert allowed.behavior == "allow"


@pytest.mark.asyncio
async def test_live_plan_rejects_valid_saved_plan_with_sequence_warning_by_default(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "1")
    monkeypatch.delenv("NATIVE_PLANNER_ALLOW_LIVE_SEQUENCE_WARNING", raising=False)
    result = AgentResult(
        success=True,
        output=VALID_PLAN,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_setup_page",
                timestamp=datetime.now(),
                input={"seedFile": "tests/seed.spec.ts"},
            ),
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": VALID_PLAN},
            ),
        ],
    )
    prompts = _patch_agent_sequence(monkeypatch, planner, [result])

    with pytest.raises(SpecGenerationError, match="saved a plan before navigating"):
        await planner.generate_spec_from_flow_context(
            flow_title="Checkout",
            flow_context="Checkout flow",
            target_url="https://example.test/checkout",
            output_dir=tmp_path / "run",
        )

    assert len(prompts) == 1
    assert not (tmp_path / "run" / "checkout.md").exists()


@pytest.mark.asyncio
async def test_live_plan_sequence_warning_override_rejects_missing_navigation(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("NATIVE_PLANNER_ALLOW_LIVE_SEQUENCE_WARNING", "1")
    result = AgentResult(
        success=True,
        output=VALID_PLAN,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_setup_page",
                timestamp=datetime.now(),
                input={"seedFile": "tests/seed.spec.ts"},
            ),
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": VALID_PLAN},
            ),
        ],
    )
    prompts = _patch_agent_sequence(monkeypatch, planner, [result])

    with pytest.raises(SpecGenerationError, match="saved a plan before navigating"):
        await planner.generate_spec_from_flow_context(
            flow_title="Checkout",
            flow_context="Checkout flow",
            target_url="https://example.test/checkout",
            output_dir=tmp_path / "run",
        )

    assert len(prompts) == 1
    assert not (planner.session_dir / "planner_live_sequence_warning.json").exists()
    assert not (tmp_path / "run" / "checkout.md").exists()


@pytest.mark.asyncio
async def test_live_plan_accepts_valid_saved_plan_with_later_generator_setup_missing_seed(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "1")
    monkeypatch.delenv("NATIVE_PLANNER_ALLOW_LIVE_SEQUENCE_WARNING", raising=False)
    result = _live_save_result(VALID_PLAN)
    result.tool_calls.append(
        ToolCall(
            name="mcp__playwright-test__generator_setup_page",
            timestamp=datetime.now(),
            input={},
        )
    )
    prompts = _patch_agent_sequence(monkeypatch, planner, [result])

    path = await planner.generate_spec_from_flow_context(
        flow_title="Checkout",
        flow_context="Checkout flow",
        target_url="https://example.test/checkout",
        output_dir=tmp_path / "run",
    )

    warning = json.loads(
        (planner.session_dir / "planner_live_sequence_warning.json").read_text()
    )
    assert path.read_text().strip() == VALID_PLAN.strip()
    assert len(prompts) == 1
    assert warning["valid_saved_plan_observed"] is True
    assert warning["failure_category"] == "planner_live_sequence_setup_seed_warning"
    assert warning["setup_tool"] == "generator_setup_page"
    assert warning["setup_seed_file_omitted"] is True
    assert warning["target_navigation_observed"] is True


@pytest.mark.asyncio
async def test_live_plan_rejects_missing_target_navigation_despite_generator_seed_warning(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "1")
    monkeypatch.delenv("NATIVE_PLANNER_ALLOW_LIVE_SEQUENCE_WARNING", raising=False)
    result = AgentResult(
        success=True,
        output=VALID_PLAN,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_setup_page",
                timestamp=datetime.now(),
                input={"seedFile": "tests/seed.spec.ts"},
            ),
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": VALID_PLAN},
            ),
            ToolCall(
                name="mcp__playwright-test__generator_setup_page",
                timestamp=datetime.now(),
                input={},
            ),
        ],
    )
    _patch_agent_sequence(monkeypatch, planner, [result])

    with pytest.raises(SpecGenerationError, match="before navigating"):
        await planner.generate_spec_from_flow_context(
            flow_title="Checkout",
            flow_context="Checkout flow",
            target_url="https://example.test/checkout",
            output_dir=tmp_path / "run",
        )

    assert not (planner.session_dir / "planner_live_sequence_warning.json").exists()
    assert not (tmp_path / "run" / "checkout.md").exists()


@pytest.mark.asyncio
async def test_live_plan_rejects_explicitly_wrong_generator_setup_seed(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "1")
    monkeypatch.delenv("NATIVE_PLANNER_ALLOW_LIVE_SEQUENCE_WARNING", raising=False)
    result = _live_save_result(VALID_PLAN)
    result.tool_calls.append(
        ToolCall(
            name="mcp__playwright-test__generator_setup_page",
            timestamp=datetime.now(),
            input={"seedFile": "tests/not-seed.spec.ts"},
        )
    )
    _patch_agent_sequence(monkeypatch, planner, [result])

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_from_flow_context(
            flow_title="Checkout",
            flow_context="Checkout flow",
            target_url="https://example.test/checkout",
            output_dir=tmp_path / "run",
        )

    assert "invalid setup seed file" in str(exc_info.value)
    assert exc_info.value.diagnostics["failure_category"] == "native_setup_seed_file_error"
    assert exc_info.value.diagnostics["received_seed_file"] == "tests/not-seed.spec.ts"
    assert not (planner.session_dir / "planner_live_sequence_warning.json").exists()
    assert not (tmp_path / "run" / "checkout.md").exists()


@pytest.mark.asyncio
async def test_live_plan_retries_after_contract_failure_without_valid_saved_plan(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "2")
    first = AgentResult(
        success=True,
        output="",
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_setup_page",
                timestamp=datetime.now(),
                input={"seedFile": "tests/seed.spec.ts"},
            ),
        ],
    )
    second = AgentResult(
        success=True,
        output=VALID_PLAN,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_setup_page",
                timestamp=datetime.now(),
                input={"seedFile": "tests/seed.spec.ts"},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_navigate",
                timestamp=datetime.now(),
                input={"url": "https://example.test/checkout"},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_snapshot",
                timestamp=datetime.now(),
                input={},
            ),
            ToolCall(
                name="mcp__playwright-test__planner_save_plan",
                timestamp=datetime.now(),
                input={"content": VALID_PLAN},
            ),
        ],
    )
    prompts = _patch_agent_sequence(monkeypatch, planner, [first, second])

    path = await planner.generate_spec_from_flow_context(
        flow_title="Checkout",
        flow_context="Checkout flow",
        target_url="https://example.test/checkout",
        output_dir=tmp_path / "run",
    )

    assert path.read_text().strip() == VALID_PLAN.strip()
    assert len(prompts) == 2
    assert "previous attempt" in prompts[1].lower()
    assert "planner_setup_page" in prompts[1]


@pytest.mark.asyncio
async def test_live_plan_with_valid_markdown_but_no_tool_calls_retries_as_contract_failure(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "2")
    first = AgentResult(
        success=True,
        output=VALID_PLAN,
        messages_received=2,
        text_blocks_received=1,
        tool_calls=[],
    )
    prompts = _patch_agent_sequence(
        monkeypatch,
        planner,
        [first, _live_save_result(VALID_PLAN)],
    )

    path = await planner.generate_spec_from_flow_context(
        flow_title="Checkout",
        flow_context="Checkout flow",
        target_url="https://example.test/checkout",
        output_dir=tmp_path / "run",
    )

    assert path.read_text().strip() == VALID_PLAN.strip()
    assert len(prompts) == 2
    assert "no real recorded MCP tool calls" in prompts[1]
    assert "do not write `<function_calls>`" in prompts[1]


@pytest.mark.asyncio
async def test_live_plan_fake_text_tool_call_markup_has_specific_diagnostics(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "1")
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(
            success=True,
            output=(
                '<function_calls><invoke name="planner_setup_page">'
                '{"seedFile":"tests/seed.spec.ts"}</invoke></function_calls>\n'
                + VALID_PLAN
            ),
            messages_received=3,
            text_blocks_received=2,
            tool_calls=[],
        ),
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_from_flow_context(
            flow_title="Checkout",
            flow_context="Checkout flow",
            target_url="https://example.test/checkout",
            output_dir=tmp_path / "run",
        )

    assert (
        exc_info.value.diagnostics["failure_category"]
        == "planner_text_tool_call_contract_failure"
    )
    assert exc_info.value.diagnostics["tool_calls"] == 0
    assert exc_info.value.diagnostics["fake_tool_call_markup_observed"] is True
    assert exc_info.value.diagnostics["expected_target_url"] == "https://example.test/checkout"
    assert exc_info.value.diagnostics["missing_sequence_steps"] == [
        "planner_setup_page",
        "browser_navigate",
        "browser_snapshot",
    ]
    assert "<function_calls>" in exc_info.value.diagnostics["output_preview"]


@pytest.mark.asyncio
async def test_unstructured_plan_retries_after_repair_fails(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "2")
    first = AgentResult(
        success=True,
        output="I explored the page but did not create a structured plan.",
        tool_calls=[],
    )
    second = AgentResult(success=True, output=VALID_PLAN, tool_calls=[])
    prompts = _patch_agent_sequence(monkeypatch, planner, [first, second])

    async def fake_repair(**_kwargs):
        return None

    monkeypatch.setattr(planner, "_attempt_repair_plan", fake_repair)

    path = await planner.generate_spec_for_feature("Checkout", "prd-project")

    assert path.read_text().strip() == VALID_PLAN.strip()
    assert len(prompts) == 2
    assert "valid markdown test plan" in prompts[1]


@pytest.mark.asyncio
async def test_live_plan_repeated_contract_failure_raises_after_retry(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "2")
    invalid = AgentResult(
        success=True,
        output="",
        messages_received=1,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__planner_setup_page",
                timestamp=datetime.now(),
                input={"seedFile": "tests/seed.spec.ts"},
            )
        ],
    )
    prompts = _patch_agent_sequence(monkeypatch, planner, [invalid, invalid])

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_from_flow_context(
            flow_title="Checkout",
            flow_context="Checkout flow",
            target_url="https://example.test/checkout",
            output_dir=tmp_path / "run",
        )

    assert len(prompts) == 2
    assert "did not navigate" in str(exc_info.value)
    assert exc_info.value.diagnostics["target_navigation_observed"] is False


@pytest.mark.asyncio
async def test_zero_output_live_planner_process_error_is_runtime_failed(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "1")
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(
            success=False,
            output="",
            error="ProcessError: process exited before producing output",
            error_type="agent_process_error",
            messages_received=0,
            text_blocks_received=0,
            tool_calls=[],
        ),
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_from_flow_context(
            flow_title="Checkout",
            flow_context="Checkout flow",
            target_url="https://example.test/checkout",
            output_dir=tmp_path / "run",
        )

    assert "did not navigate" not in str(exc_info.value)
    assert "runtime failed" in str(exc_info.value)
    assert exc_info.value.diagnostics["failure_category"] == "runtime_failed"
    assert exc_info.value.diagnostics["messages_received"] == 0
    assert exc_info.value.diagnostics["tool_calls"] == 0
    runtime_error_path = Path(exc_info.value.diagnostics["runtime_error_path"])
    assert runtime_error_path.exists()
    assert json.loads(runtime_error_path.read_text())["failure_category"] == "runtime_failed"


@pytest.mark.asyncio
async def test_live_planner_auth_failure_preempts_zero_tool_contract_and_does_not_retry(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "3")
    prompts = _patch_agent_sequence(
        monkeypatch,
        planner,
        [
            AgentResult(
                success=False,
                output="Not logged in · Please run /login",
                error="Not logged in · Please run /login",
                error_type="claude_code_auth_required",
                messages_received=1,
                text_blocks_received=1,
                tool_calls=[],
            )
        ],
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner.generate_spec_from_flow_context(
            flow_title="Checkout",
            flow_context="Checkout flow",
            target_url="https://example.test/checkout",
            output_dir=tmp_path / "run",
        )

    assert len(prompts) == 1
    assert "Claude Code authentication failed" in str(exc_info.value)
    assert (
        exc_info.value.diagnostics["failure_category"]
        == "claude_code_auth_required"
    )
    assert "OAuth token" in exc_info.value.diagnostics["next_action"]
    assert "planner_live_tool_call_contract_failure" not in str(exc_info.value.diagnostics)


@pytest.mark.asyncio
async def test_unproductive_stream_with_no_tool_calls_rejects_saved_planner_artifact(
    tmp_path, monkeypatch
):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "1")
    output_path = tmp_path / "run" / "checkout.md"
    output_path.write_text(VALID_PLAN)
    _patch_agent(
        monkeypatch,
        planner,
        AgentResult(
            success=False,
            output="",
            error="Agent stream produced 500 messages but no parsed output",
            error_type="unproductive_stream",
            messages_received=500,
            text_blocks_received=0,
            tool_calls=[],
        ),
    )

    with pytest.raises(SpecGenerationError) as exc_info:
        await planner._run_planner_with_retry(
            subject_type="flow",
            subject_name="Checkout",
            prompt="plan checkout",
            target_url="https://example.test/checkout",
            expected_output_path=output_path,
        )

    assert (
        exc_info.value.diagnostics["failure_category"]
        == "planner_live_tool_call_contract_failure"
    )
    assert output_path.exists()


@pytest.mark.asyncio
async def test_unproductive_stream_retries_once_with_fresh_session(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "2")
    output_path = tmp_path / "run" / "checkout.md"
    retry_runtime: list[tuple[str | None, bool]] = []

    async def fake_query(_prompt: str, target_url: str | None = None) -> AgentResult:
        retry_runtime.append(
            (
                getattr(planner, "_planner_retry_session_id", None),
                bool(getattr(planner, "_planner_retry_continue_conversation", False)),
            )
        )
        if len(retry_runtime) == 1:
            return AgentResult(
                success=False,
                output="",
                error="Agent stream produced 500 messages but no parsed output",
                error_type="unproductive_stream",
                messages_received=500,
                text_blocks_received=0,
                tool_calls=[],
                session_id="broken-sdk-session",
            )
        return _live_save_result(VALID_PLAN)

    monkeypatch.setattr(planner, "_query_planner_agent", fake_query)

    result = await planner._run_planner_with_retry(
        subject_type="flow",
        subject_name="Checkout",
        prompt="plan checkout",
        target_url="https://example.test/checkout",
        expected_output_path=output_path,
    )

    assert result == output_path
    assert retry_runtime == [(None, False), (None, False)]


@pytest.mark.asyncio
async def test_browser_timeout_retry_abandons_claude_session_and_starts_fresh(tmp_path, monkeypatch):
    planner = _planner(tmp_path)
    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "2")
    output_path = tmp_path / "run" / "checkout.md"
    retry_runtime: list[tuple[str | None, bool, str]] = []

    async def fake_query(prompt: str, target_url: str | None = None) -> AgentResult:
        retry_runtime.append(
            (
                getattr(planner, "_planner_retry_session_id", None),
                bool(getattr(planner, "_planner_retry_continue_conversation", False)),
                prompt,
            )
        )
        if len(retry_runtime) == 1:
            return AgentResult(
                success=False,
                output="",
                error="Browser tool timed out: mcp__playwright-test__browser_navigate",
                error_type="browser_tool_timeout",
                tool_calls=[
                    ToolCall(
                        name="mcp__playwright-test__planner_setup_page",
                        timestamp=datetime.now(),
                        input={"seedFile": "tests/seed.spec.ts"},
                    ),
                    ToolCall(
                        name="mcp__playwright-test__browser_navigate",
                        timestamp=datetime.now(),
                        input={"url": "https://example.test/checkout"},
                        success=False,
                        error="Browser tool timed out: mcp__playwright-test__browser_navigate",
                    ),
                ],
                session_id="failed-browser-session",
            )
        return _live_save_result(VALID_PLAN)

    monkeypatch.setattr(planner, "_query_planner_agent", fake_query)

    result = await planner._run_planner_with_retry(
        subject_type="flow",
        subject_name="Checkout",
        prompt="plan checkout",
        target_url="https://example.test/checkout",
        expected_output_path=output_path,
    )

    assert result == output_path
    assert retry_runtime[0][0:2] == (None, False)
    assert retry_runtime[1][0:2] == (None, False)
    assert "previous browser session was abandoned" in retry_runtime[1][2].lower()
    assert "do not use `browser_resume`" in retry_runtime[1][2].lower()
