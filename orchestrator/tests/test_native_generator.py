import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.workflows.native_generator import NativeGenerator
from orchestrator.services.handoff_manifest import init_manifest, load_manifest, record_artifact


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
    )

    assert "## Planner Draft Script" in captured["prompt"]
    assert "getByRole('button', { name: 'Save' })" in captured["prompt"]
    assert "write the final test with `generator_write_test`" in captured["prompt"]


@pytest.mark.asyncio
async def test_generator_records_handoff_consumption_and_generated_hash(monkeypatch, tmp_path):
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
    monkeypatch.setenv("GENERATOR_PLAN_CONTEXT_CHARS", "60")
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
    content = (Path(__file__).resolve().parents[2] / ".claude" / "agents" / "playwright-test-generator.md").read_text()

    assert 'generator_setup_page` tool with `seedFile: "tests/seed.spec.ts"`' in content
    assert "Include every test case from the provided spec in that single file" in content


def test_generator_agent_definition_consumes_draft_script_with_wait_best_practices():
    content = (Path(__file__).resolve().parents[2] / ".claude" / "agents" / "playwright-test-generator.md").read_text()

    assert "## Draft Playwright Script" in content
    assert "consume it as a starting scaffold" in content
    assert "Never copy `page.waitForTimeout()`" in content
    assert "await expect(locator).toBeVisible()" in content


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

    monkeypatch.setattr("orchestrator.workflows.native_generator.AgentRunner", FakeRunner)
    generator = NativeGenerator(model_tier="tool_deep")

    result = await generator._query_generator_agent("prompt with native memory section")

    assert result == "done"
    assert captured["model_tier"] == "tool_deep"
    assert captured["memory_agent_type"] == "NativeGenerator"
    assert captured["inject_memory"] is False
