import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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


def test_planner_max_attempts_defaults_to_five_and_caps_env(monkeypatch):
    monkeypatch.delenv("PLANNER_MAX_ATTEMPTS", raising=False)
    assert NativePlanner._planner_max_attempts() == 5

    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "9")
    assert NativePlanner._planner_max_attempts() == 5

    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "0")
    assert NativePlanner._planner_max_attempts() == 1

    monkeypatch.setenv("PLANNER_MAX_ATTEMPTS", "bad")
    assert NativePlanner._planner_max_attempts() == 5


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
async def test_live_plan_sequence_warning_override_accepts_valid_saved_plan(
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
    assert warning["target_navigation_observed"] is False
    assert warning["generated_plan_path"] == str(path)


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
async def test_unproductive_stream_recovers_saved_planner_artifact(tmp_path, monkeypatch):
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

    result = await planner._run_planner_with_retry(
        subject_type="flow",
        subject_name="Checkout",
        prompt="plan checkout",
        target_url="https://example.test/checkout",
        expected_output_path=output_path,
    )

    assert result == output_path
    assert output_path.read_text() == VALID_PLAN


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
