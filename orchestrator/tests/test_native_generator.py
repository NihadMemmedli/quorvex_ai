import json
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.services.handoff_manifest import (
    init_manifest,
    load_manifest,
    record_artifact,
)
from orchestrator.utils.agent_runner import AgentResult
from orchestrator.utils.agent_tool_allowlists import get_agent_allowed_tools
from orchestrator.workflows.native_generator import NativeGenerator


def test_generator_prompt_accepts_memory_run_id(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    generator = object.__new__(NativeGenerator)
    generator._extract_credential_placeholders = lambda _content: {}

    prompt = generator._build_generator_prompt(
        spec_path="/tmp/spec.md",
        spec_content="# Test\n1. Navigate to https://example.test",
        spec_name="recorded-flow",
        output_path="/tmp/recorded-flow.spec.ts",
        target_url="https://example.test",
        memory_run_id="run-123",
    )

    assert "https://example.test" in prompt
    assert "<test-file>/tmp/recorded-flow.spec.ts</test-file>" in prompt
    assert 'generator_setup_page` with `seedFile: "tests/seed.spec.ts"`' in prompt
    assert "## Robust Synchronization Requirements" in prompt
    assert "Do not use `page.waitForTimeout()`" in prompt
    assert "await expect(locator).toBeVisible()" in prompt


def test_generator_prompt_includes_verified_plan_section(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    generator = object.__new__(NativeGenerator)
    generator._extract_credential_placeholders = lambda _content: {}

    prompt = generator._build_generator_prompt(
        spec_path="/tmp/spec.md",
        spec_content="# Test\n1. Navigate to https://example.test",
        spec_name="recorded-flow",
        output_path="/tmp/recorded-flow.spec.ts",
        target_url="https://example.test",
        plan_content="- await page.getByRole('button', { name: 'Save' }).click();",
    )

    assert "## Verified Test Plan" in prompt
    assert "Prefer these selectors over guessing" in prompt
    assert "getByRole('button', { name: 'Save' })" in prompt


def test_generator_prompt_consumes_planner_draft_script_with_wait_guidance(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    generator = object.__new__(NativeGenerator)
    generator._extract_credential_placeholders = lambda _content: {}

    prompt = generator._build_generator_prompt(
        spec_path="/tmp/spec.md",
        spec_content="# Checkout\n1. Submit the order",
        spec_name="checkout",
        output_path="/tmp/checkout.spec.ts",
        target_url="https://example.test/checkout",
        plan_content="# Test Plan: Checkout\n\n### TC-001: Submit Checkout\n**Steps:**\n1. Click the Place order button.",
        planner_draft_script_content="""
test.describe('Checkout', () => {
  test('Submit Checkout', async ({ page }) => {
    const submitButton = page.getByRole('button', { name: 'Place order' });
    await expect(submitButton).toBeVisible();
    await submitButton.click();
    await expect(page.getByText('Thanks for your order')).toBeVisible();
  });
});
""",
    )

    assert "## Verified Test Plan" in prompt
    assert "## Planner Draft Script" in prompt
    assert "getByRole('button', { name: 'Place order' })" in prompt
    assert "## Robust Synchronization Requirements" in prompt
    assert "Do not use `page.waitForTimeout()`" in prompt
    assert "wait for the durable result" in prompt


@pytest.mark.asyncio
async def test_generator_reads_planner_draft_script_path(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    captured = {}

    async def fake_query(prompt):
        captured["prompt"] = prompt
        return "done"

    generator = NativeGenerator()
    generator.tests_dir = tmp_path
    generator._extract_credential_placeholders = lambda _content: {}
    generator._query_generator_agent = fake_query
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Test\n1. Navigate to https://example.test")
    draft_path = tmp_path / "planner.draft.spec.ts"
    draft_path.write_text(
        "import { test, expect } from '@playwright/test';\n"
        "test('draft', async ({ page }) => {\n"
        "  await expect(page.getByRole('button', { name: 'Save' })).toBeVisible();\n"
        "});\n"
    )

    await generator.generate_test(
        str(spec_path),
        target_url="https://example.test",
        output_name="generated",
        planner_draft_script_path=draft_path,
        enable_self_run=False,
    )

    assert "## Planner Draft Script" in captured["prompt"]
    assert "getByRole('button', { name: 'Save' })" in captured["prompt"]
    assert "write the final test with `generator_write_test`" in captured["prompt"]


@pytest.mark.asyncio
async def test_generator_records_handoff_consumption_and_generated_hash(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    manifest_path = init_manifest(tmp_path)
    captured = {}

    async def fake_query(prompt):
        captured["prompt"] = prompt
        return (
            "```typescript\n"
            "import { test, expect } from '@playwright/test';\n"
            "test('generated', async ({ page }) => {\n"
            "  await expect(page.getByRole('button', { name: 'Save' })).toBeVisible();\n"
            "});\n"
            "```"
        )

    generator = NativeGenerator()
    generator.tests_dir = tmp_path
    generator._extract_credential_placeholders = lambda _content: {}
    generator._query_generator_agent = fake_query
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Test\n1. Navigate to https://example.test")
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("# Test Plan: Save\n- getByRole('button', { name: 'Save' })")
    draft_path = tmp_path / "plan.draft.spec.ts"
    draft_path.write_text(
        "import { test, expect } from '@playwright/test';\n"
        "test('draft', async ({ page }) => {\n"
        "  await expect(page.getByRole('button', { name: 'Save' })).toBeVisible();\n"
        "});\n"
    )
    record_artifact(
        manifest_path,
        "planner_plan",
        plan_path,
        kind="planner_markdown_plan",
        producer_stage="planner",
    )
    record_artifact(
        manifest_path,
        "planner_draft_script",
        draft_path,
        kind="planner_draft_playwright",
        producer_stage="planner",
    )

    output = await generator.generate_test(
        str(spec_path),
        target_url="https://example.test",
        output_name="generated",
        plan_path=plan_path,
        planner_draft_script_path=draft_path,
        handoff_manifest_path=manifest_path,
        enable_self_run=False,
    )

    data = load_manifest(tmp_path)
    consumed = data["stages"]["generator"]["artifacts_consumed"]
    generated = data["artifacts"]["generated_test"]
    assert output == tmp_path / "generated.spec.ts"
    assert consumed["planner_plan"]["status"] == "used"
    assert consumed["planner_draft_script"]["status"] == "used"
    assert generator.last_handoff_consumption["planner_draft_script_status"] == "used"
    assert generated["path"] == str(output)
    assert len(generated["hash"]) == 64
    assert "## Planner Draft Script" in captured["prompt"]


def test_generator_prompt_truncates_long_verified_plan(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    monkeypatch.setenv("GENERATOR_PLAN_EVIDENCE_MODE", "full")
    monkeypatch.setenv("AGENT_CONTEXT_BUDGET_GENERATOR_PLAN", "20")
    generator = object.__new__(NativeGenerator)
    generator._extract_credential_placeholders = lambda _content: {}

    prompt = generator._build_generator_prompt(
        spec_path="/tmp/spec.md",
        spec_content="# Test\n1. Navigate to https://example.test",
        spec_name="recorded-flow",
        output_path="/tmp/recorded-flow.spec.ts",
        target_url="https://example.test",
        plan_content="PLAN-HEAD " + ("x" * 200) + " PLAN-TAIL",
    )

    assert "PLAN-HEAD" in prompt
    assert "PLAN-TAIL" in prompt
    assert "[truncated" in prompt


def test_generator_coverage_warnings_detect_missing_steps():
    warnings = NativeGenerator._coverage_warnings(
        "### TC-001: Save\n**Steps:**\n1. Click the purple Save button\n**Expected Result:** Success toast appears",
        "import { test, expect } from '@playwright/test';\ntest('x', async ({ page }) => { await expect(page.locator('body')).toBeVisible(); });",
    )

    assert any("purple Save" in warning for warning in warnings)
    assert any("Success toast" in warning for warning in warnings)


def test_generator_prompt_omits_verified_plan_section_without_plan(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    generator = object.__new__(NativeGenerator)
    generator._extract_credential_placeholders = lambda _content: {}

    prompt = generator._build_generator_prompt(
        spec_path="/tmp/spec.md",
        spec_content="# Test\n1. Navigate to https://example.test",
        spec_name="recorded-flow",
        output_path="/tmp/recorded-flow.spec.ts",
        target_url="https://example.test",
    )

    assert "## Verified Test Plan" not in prompt


def test_generator_extract_code_strips_markdown_response():
    generator = object.__new__(NativeGenerator)
    response = """Here is the test:

```typescript
import { test, expect } from '@playwright/test';

test('x', async ({ page }) => {
  await expect(page).toHaveURL(/.*/);
});
```
"""

    code = generator._extract_code(response)

    assert code.startswith("import { test, expect }")
    assert "```" not in code


def test_generator_extract_code_accepts_fixture_import_with_testdata():
    generator = object.__new__(NativeGenerator)
    response = """```typescript
import { test, expect } from '../fixtures/test-data';

test('uses project test data', async ({ page, testData }) => {
  const user = testData.get<{ username: string }>('auth.valid-user');
  await page.getByLabel('Email').fill(user.username);
  await expect(page.getByRole('button', { name: /submit/i })).toBeVisible();
});
```"""

    code = generator._extract_code(response)

    assert code is not None
    assert "from '../fixtures/test-data'" in code
    assert "testData.get" in code


def test_generator_extract_code_rejects_narrative_without_import():
    generator = object.__new__(NativeGenerator)

    assert generator._extract_code("test('x', async () => {});") is None


def test_generator_agent_definition_requires_seed_file():
    content = (
        Path(__file__).resolve().parents[2]
        / ".claude"
        / "agents"
        / "playwright-test-generator.md"
    ).read_text()

    assert 'generator_setup_page` tool with `seedFile: "tests/seed.spec.ts"`' in content
    assert (
        "Include every test case from the provided spec in that single file" in content
    )


def test_generator_agent_definition_consumes_draft_script_with_wait_best_practices():
    content = (
        Path(__file__).resolve().parents[2]
        / ".claude"
        / "agents"
        / "playwright-test-generator.md"
    ).read_text()

    assert "## Draft Playwright Script" in content
    assert "consume it as a starting scaffold" in content
    assert "Never copy `page.waitForTimeout()`" in content
    assert "await expect(locator).toBeVisible()" in content


def test_generator_tool_profile_includes_self_run_diagnostics():
    tools = get_agent_allowed_tools("playwright-test-generator")

    assert any(tool.endswith("__test_run") for tool in tools)
    assert any(tool.endswith("__test_debug") for tool in tools)
    assert any(tool.endswith("__browser_resume") for tool in tools)
    assert any(tool.endswith("__browser_console_messages") for tool in tools)
    assert any(tool.endswith("__browser_network_requests") for tool in tools)
    assert any(tool.endswith("__browser_generate_locator") for tool in tools)
    assert not any(tool.endswith("__browser_close") for tool in tools)


def test_generator_agent_definition_requires_self_run_after_write():
    content = (
        Path(__file__).resolve().parents[2]
        / ".claude"
        / "agents"
        / "playwright-test-generator.md"
    ).read_text()

    assert "Immediately after `generator_write_test`, run the exact generated file with `test_debug` before handoff" in content
    assert "keep using `test_debug` for the exact failed generated test before" in content
    assert "self_run_status" in content
    assert "changed_selectors" in content


def test_generator_self_heal_prompt_uses_test_debug_before_diagnostics(tmp_path):
    generator = NativeGenerator()
    prompt = generator._build_generator_self_heal_prompt(
        output_path=tmp_path / "generated.spec.ts",
        browser="chromium",
        output_dir=tmp_path,
        attempt_number=1,
        max_attempts=3,
        failure_summary="Timeout waiting for locator",
        previous_fixes=[],
        current_file_content="import { test, expect } from '@playwright/test';",
    )

    assert "Use `test_debug` scoped to this exact file" in prompt
    assert "Use diagnostic tools only after `test_debug` has paused" in prompt
    assert "with `test_run` scoped to this exact file" in prompt
    assert "browser_close" not in prompt


def test_generator_self_run_prompt_uses_test_debug_before_handoff(tmp_path):
    generator = NativeGenerator()
    prompt = generator._build_generator_self_run_prompt(
        output_path=tmp_path / "generated.spec.ts",
        browser="chromium",
        output_dir=tmp_path,
    )

    assert "Call `test_debug` for exactly this file" in prompt
    assert "before handoff" in prompt
    assert "test_run" not in prompt


@pytest.mark.asyncio
async def test_generator_runner_does_not_inject_memory_twice(monkeypatch):
    captured = {}

    class FakeResult:
        output = "done"
        messages_received = 1
        tool_calls = []
        duration_seconds = 0.1
        timed_out = False
        success = True
        error = None

    class FakeRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self, prompt):
            captured["prompt"] = prompt
            return FakeResult()

    monkeypatch.setattr(
        "orchestrator.workflows.native_generator.AgentRunner", FakeRunner
    )
    generator = NativeGenerator(model_tier="tool_deep")

    result = await generator._query_generator_agent("prompt with native memory section")

    assert result == "done"
    assert captured["model_tier"] == "tool_deep"
    assert captured["memory_agent_type"] == "NativeGenerator"
    assert captured["inject_memory"] is False


@pytest.mark.asyncio
async def test_generator_format_retry_reuses_session_without_browser_tools(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    monkeypatch.setenv("GENERATOR_SCHEMA_MAX_ATTEMPTS", "2")
    captured: list[dict] = []

    valid_code = (
        "import { test, expect } from '@playwright/test';\n"
        "test('generated', async ({ page }) => {\n"
        "  await expect(page.locator('body')).toBeVisible();\n"
        "});\n"
    )

    class FakeRunner:
        def __init__(self, **kwargs):
            captured.append(kwargs)

        async def run(self, prompt):
            if len(captured) == 1:
                return AgentResult(
                    success=True, output="not a code block", session_id="sdk-session-1"
                )
            return AgentResult(
                success=True,
                output=f"```typescript\n{valid_code}```",
                session_id="sdk-session-1",
            )

    monkeypatch.setattr(
        "orchestrator.workflows.native_generator.AgentRunner", FakeRunner
    )
    generator = NativeGenerator()
    generator.tests_dir = tmp_path
    generator._extract_credential_placeholders = lambda _content: {}
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Test\n1. Navigate to https://example.test")

    output = await generator.generate_test(
        str(spec_path),
        target_url="https://example.test",
        output_name="generated",
        enable_self_run=False,
    )

    assert output == tmp_path / "generated.spec.ts"
    assert output.read_text() == valid_code
    assert len(captured) == 2
    retry_kwargs = captured[1]
    assert retry_kwargs["allowed_tools"] == []
    assert retry_kwargs["tools"] == []
    assert retry_kwargs["requires_live_browser"] is False
    assert retry_kwargs["force_direct_execution"] is True
    assert retry_kwargs["resume_session_id"] == "sdk-session-1"


@pytest.mark.asyncio
async def test_generator_self_run_passes_first_try_reuses_original_session(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    calls: list[dict] = []
    valid_code = (
        "import { test, expect } from '@playwright/test';\n"
        "test('generated', async ({ page }) => {\n"
        "  await expect(page.locator('body')).toBeVisible();\n"
        "});\n"
    )

    class FakeRunner:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def run(self, prompt):
            if len(calls) == 1:
                return AgentResult(
                    success=True,
                    output=f"```typescript\n{valid_code}```",
                    session_id="gen-session",
                )
            return AgentResult(
                success=True,
                output=(
                    "self_run_status: passed\n"
                    "self_heal_attempts: 0\n"
                    "root_cause: none\n"
                    "changed_selectors: []"
                ),
                session_id="self-run-session",
            )

    monkeypatch.setattr(
        "orchestrator.workflows.native_generator.AgentRunner", FakeRunner
    )
    generator = NativeGenerator(
        owner_type="test_run",
        owner_id="run-123",
        owner_label="Run 123",
    )
    generator.tests_dir = tmp_path
    generator._extract_credential_placeholders = lambda _content: {}
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Test\n1. Navigate to https://example.test")

    output = await generator.generate_test(
        str(spec_path),
        target_url="https://example.test",
        output_name="generated",
        self_run_browser="chromium",
        self_run_output_dir=tmp_path,
    )

    assert output == tmp_path / "generated.spec.ts"
    assert len(calls) == 2
    assert calls[1]["resume_session_id"] == "gen-session"
    assert calls[1]["continue_conversation"] is False
    assert calls[1]["owner_type"] == "test_run"
    assert calls[1]["owner_id"] == "run-123"
    assert generator.last_self_heal_passed is True
    assert generator.last_self_heal_attempts == 0
    artifact = tmp_path / "generator_self_heal.json"
    data = json.loads(artifact.read_text())
    assert data["final_status"] == "passed"
    assert data["attempt_count"] == 0


@pytest.mark.asyncio
async def test_generator_self_heal_reuses_latest_session_until_pass(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    calls: list[dict] = []
    valid_code = (
        "import { test, expect } from '@playwright/test';\n"
        "test('generated', async ({ page }) => {\n"
        "  await expect(page.locator('body')).toBeVisible();\n"
        "});\n"
    )

    class FakeRunner:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def run(self, prompt):
            if len(calls) == 1:
                return AgentResult(
                    success=True,
                    output=f"```typescript\n{valid_code}```",
                    session_id="gen-session",
                )
            if len(calls) == 2:
                return AgentResult(
                    success=True,
                    output="self_run_status: failed\nroot_cause: selector timeout",
                    session_id="run-session",
                )
            if len(calls) == 3:
                return AgentResult(
                    success=True,
                    output="self_run_status: failed\nself_heal_attempts: 1\nroot_cause: wrong selector\nchanged_selectors: []",
                    session_id="heal-session-1",
                )
            return AgentResult(
                success=True,
                output="self_run_status: passed\nself_heal_attempts: 2\nroot_cause: fixed selector\nchanged_selectors: []",
                session_id="heal-session-2",
            )

    monkeypatch.setattr(
        "orchestrator.workflows.native_generator.AgentRunner", FakeRunner
    )
    generator = NativeGenerator()
    generator.tests_dir = tmp_path
    generator._extract_credential_placeholders = lambda _content: {}
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Test\n1. Navigate to https://example.test")

    await generator.generate_test(
        str(spec_path),
        target_url="https://example.test",
        output_name="generated",
        self_run_browser="chromium",
        self_run_output_dir=tmp_path,
        self_heal_max_attempts=3,
    )

    assert len(calls) == 4
    assert calls[1]["resume_session_id"] == "gen-session"
    assert calls[2]["resume_session_id"] == "run-session"
    assert calls[3]["resume_session_id"] == "heal-session-1"
    assert calls[2]["preserve_browser_on_failure"] is True
    assert calls[3]["preserve_browser_on_failure"] is True
    assert generator.last_self_heal_passed is True
    assert generator.last_self_heal_attempts == 2


@pytest.mark.asyncio
async def test_generator_self_run_uses_continue_when_no_session_id(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    calls: list[dict] = []
    valid_code = (
        "import { test, expect } from '@playwright/test';\n"
        "test('generated', async ({ page }) => {\n"
        "  await expect(page.locator('body')).toBeVisible();\n"
        "});\n"
    )

    class FakeRunner:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def run(self, prompt):
            if len(calls) == 1:
                return AgentResult(success=True, output=f"```typescript\n{valid_code}```")
            return AgentResult(
                success=True,
                output="self_run_status: passed\nself_heal_attempts: 0",
            )

    monkeypatch.setattr(
        "orchestrator.workflows.native_generator.AgentRunner", FakeRunner
    )
    generator = NativeGenerator()
    generator.tests_dir = tmp_path
    generator._extract_credential_placeholders = lambda _content: {}
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Test\n1. Navigate to https://example.test")

    await generator.generate_test(
        str(spec_path),
        target_url="https://example.test",
        output_name="generated",
        self_run_output_dir=tmp_path,
    )

    assert calls[1]["resume_session_id"] is None
    assert calls[1]["continue_conversation"] is True


@pytest.mark.asyncio
async def test_generator_self_heal_rejects_invalid_rewrite_and_retries(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    calls: list[dict] = []
    valid_code = (
        "import { test, expect } from '@playwright/test';\n"
        "test('generated', async ({ page }) => {\n"
        "  await expect(page.locator('body')).toBeVisible();\n"
        "});\n"
    )

    class FakeRunner:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def run(self, prompt):
            output_path = tmp_path / "generated.spec.ts"
            if len(calls) == 1:
                return AgentResult(
                    success=True,
                    output=f"```typescript\n{valid_code}```",
                    session_id="gen-session",
                )
            if len(calls) == 2:
                return AgentResult(
                    success=True,
                    output="self_run_status: failed\nroot_cause: initial failure",
                    session_id="run-session",
                )
            if len(calls) == 3:
                output_path.write_text("not a playwright test\n")
                return AgentResult(
                    success=True,
                    output="self_run_status: failed\nself_heal_attempts: 1\nroot_cause: bad rewrite",
                    session_id="heal-session-1",
                )
            output_path.write_text(valid_code)
            return AgentResult(
                success=True,
                output="self_run_status: passed\nself_heal_attempts: 2\nroot_cause: valid rewrite",
                session_id="heal-session-2",
            )

    monkeypatch.setattr(
        "orchestrator.workflows.native_generator.AgentRunner", FakeRunner
    )
    generator = NativeGenerator()
    generator.tests_dir = tmp_path
    generator._extract_credential_placeholders = lambda _content: {}
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Test\n1. Navigate to https://example.test")

    output = await generator.generate_test(
        str(spec_path),
        target_url="https://example.test",
        output_name="generated",
        self_run_output_dir=tmp_path,
        self_heal_max_attempts=2,
    )

    assert output.read_text() == valid_code
    data = json.loads((tmp_path / "generator_self_heal.json").read_text())
    assert data["final_status"] == "passed_after_self_heal"
    assert data["attempts"][1]["status"] == "rejected_invalid_code"


@pytest.mark.asyncio
async def test_generator_handoff_records_final_self_healed_hash(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    calls: list[dict] = []
    manifest_path = init_manifest(tmp_path, pipeline_type="browser")
    initial_code = (
        "import { test, expect } from '@playwright/test';\n"
        "test('generated', async ({ page }) => {\n"
        "  await expect(page.locator('#old')).toBeVisible();\n"
        "});\n"
    )
    healed_code = initial_code.replace("#old", "#new")

    class FakeRunner:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def run(self, prompt):
            output_path = tmp_path / "generated.spec.ts"
            if len(calls) == 1:
                output_path.write_text(initial_code)
                return AgentResult(success=True, output="generated", session_id="gen-session")
            if len(calls) == 2:
                assert "test_debug" in prompt
                return AgentResult(
                    success=True,
                    output="self_run_status: failed\nroot_cause: old selector",
                    session_id="debug-session",
                )
            output_path.write_text(healed_code)
            return AgentResult(
                success=True,
                output="self_run_status: passed\nself_heal_attempts: 1\nroot_cause: fixed selector",
                session_id="heal-session",
            )

    monkeypatch.setattr(
        "orchestrator.workflows.native_generator.AgentRunner", FakeRunner
    )
    generator = NativeGenerator()
    generator.tests_dir = tmp_path
    generator._extract_credential_placeholders = lambda _content: {}
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Test\n1. Navigate to https://example.test")

    output = await generator.generate_test(
        str(spec_path),
        target_url="https://example.test",
        output_name="generated",
        self_run_browser="chromium",
        self_run_output_dir=tmp_path,
        handoff_manifest_path=manifest_path,
    )

    data = load_manifest(tmp_path)
    generated = data["artifacts"]["generated_test"]
    assert output.read_text() == healed_code
    assert generated["hash"] == hashlib.sha256(healed_code.encode()).hexdigest()
    assert generated["metadata"]["generator_self_run_status"] == "passed_after_self_heal"
    assert generated["metadata"]["generator_self_heal_attempts"] == 1
