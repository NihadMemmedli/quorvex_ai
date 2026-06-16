import importlib
import json
import sys
import types
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.utils.agent_runner import AgentResult
from orchestrator.workflows.agentic_quality import (
    FailureTriageAgent,
    StabilityVerifier,
    TestDesignAgent,
    build_agentic_summary,
    extract_plan_selectors,
    normalize_failure_diagnosis,
    normalize_stability_report,
    normalize_test_critic,
    normalize_test_design,
)

memory_stub = types.ModuleType("orchestrator.memory")
memory_stub.get_memory_manager = lambda *args, **kwargs: None
sys.modules.setdefault("orchestrator.memory", memory_stub)

full_native_pipeline = importlib.import_module("orchestrator.workflows.full_native_pipeline")
if sys.modules.get("orchestrator.memory") is memory_stub:
    del sys.modules["orchestrator.memory"]

FullNativePipeline = full_native_pipeline.FullNativePipeline
PipelineTestResult = full_native_pipeline.TestResult


def test_artifact_normalizers_fallback_to_valid_shapes():
    design = normalize_test_design({"flake_risk": "wild", "warnings": ["x"]})
    critic = normalize_test_critic({"risk_level": "strange", "issues": [{"message": "x"}]})
    diagnosis = normalize_failure_diagnosis({"category": "wat", "confidence": "bad"})
    stability = normalize_stability_report({"attempts": [{"passed": True}, {"passed": False}]})

    assert design["flake_risk"] == "medium"
    assert design["testability"] == "medium"
    assert critic["risk_level"] == "medium"
    assert diagnosis["category"] == "unknown"
    assert diagnosis["confidence"] == 0.3
    assert stability["status"] == "flaky"
    assert stability["passed_runs"] == 1
    assert stability["failed_runs"] == 1


def test_extract_plan_selectors_strips_markdown_dedupes_and_limits():
    plan_text = """
- await page.getByRole('button', { name: 'Save' }).click();
* await page.getByLabel('Email').fill('user@example.test');
1. await page.getByRole('button', { name: 'Save' }).click();
> await page.locator('[data-testid="toast"]').isVisible();
- No selector on this line
"""

    assert extract_plan_selectors(plan_text, limit=2) == [
        "await page.getByRole('button', { name: 'Save' }).click();",
        "await page.getByLabel('Email').fill('user@example.test');",
    ]


def test_extract_plan_selectors_returns_empty_without_matches():
    assert extract_plan_selectors("No browser locators here") == []


def test_test_design_agent_uses_plan_selectors_and_oracles(tmp_path: Path):
    plan_path = tmp_path / "planner.md"
    plan_path.write_text(
        "\n".join(
            [
                "- await page.getByRole('button', { name: 'Save' }).click();",
                "- Verify the saved toast is visible",
            ]
        )
    )

    design = TestDesignAgent().analyze(
        spec_content="# Save flow\nNavigate to https://example.test",
        target_url="https://example.test",
        credentials=None,
        plan_path=plan_path,
        run_dir=tmp_path,
    )

    assert any(
        "getByRole('button', { name: 'Save' })" in guidance
        for guidance in design["selector_guidance"]
    )
    assert "Verify the saved toast is visible" in design["success_oracles"]


def test_build_agentic_summary_includes_costs_and_stage_outcomes(tmp_path: Path):
    (tmp_path / "plan.json").write_text("{}")
    (tmp_path / "export.json").write_text("{}")
    (tmp_path / "status.txt").write_text("passed")
    (tmp_path / "validation.json").write_text(
        json.dumps({"status": "success", "iterations": 1})
    )
    (tmp_path / "healing_attempts.json").write_text(
        json.dumps(
            {
                "attempts": [
                    {
                        "attempt": 1,
                        "passed_after": True,
                    }
                ]
            }
        )
    )
    (tmp_path / "agent_costs.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "stage": "native_generator",
                        "agent_type": "NativeGenerator",
                        "cost_usd": 0.12,
                        "tool_calls": 3,
                        "duration_seconds": 10.5,
                        "timed_out": False,
                    }
                ),
                json.dumps(
                    {
                        "stage": "native_healer",
                        "agent_type": "NativeHealer",
                        "cost_usd": 0.03,
                        "tool_calls": 2,
                        "duration_seconds": 4,
                        "timed_out": False,
                    }
                ),
            ]
        )
    )

    summary = build_agentic_summary(tmp_path)

    assert summary["costs"]["total_usd"] == 0.15
    assert summary["costs"]["by_stage"]["native_generator"]["tool_calls"] == 3
    assert summary["stage_outcomes"]["planned"] is True
    assert summary["stage_outcomes"]["generated"] is True
    assert summary["stage_outcomes"]["first_run_passed"] is False
    assert summary["stage_outcomes"]["healed"] is True
    assert summary["stage_outcomes"]["healing_attempts"] == 1


def test_failure_triage_keeps_broad_server_text_advisory(tmp_path: Path):
    diagnosis = FailureTriageAgent().diagnose(
        test_path=tmp_path / "test.spec.ts",
        error_output="Error: 500 Internal Server Error",
        design=None,
        critic=None,
        run_dir=tmp_path,
    )

    assert diagnosis["category"] == "product_bug"
    assert diagnosis["confidence"] < 0.8
    assert diagnosis["heal_allowed"] is True
    assert (tmp_path / "failure_diagnosis.json").exists()


def test_failure_triage_allows_low_confidence_unknown(tmp_path: Path):
    diagnosis = FailureTriageAgent().diagnose(
        test_path=tmp_path / "test.spec.ts",
        error_output="Unexpected failure with no useful details",
        design=None,
        critic=None,
        run_dir=tmp_path,
    )

    assert diagnosis["category"] == "unknown"
    assert diagnosis["heal_allowed"] is True


def test_stability_verifier_aggregates_passes_and_failures(tmp_path: Path):
    results = [
        PipelineTestResult(passed=True, exit_code=0, output="passed"),
        PipelineTestResult(passed=False, exit_code=1, output="failed", error_summary="boom"),
    ]

    def run_test(_test_file: str, _output_dir: str, _browser: str):
        return results.pop(0)

    report = StabilityVerifier(reruns=2).verify(
        test_file="tests/generated/example.spec.ts",
        output_dir=str(tmp_path),
        browser="chromium",
        run_test=run_test,
    )

    assert report["status"] == "flaky"
    assert report["total_runs"] == 2
    assert report["passed_runs"] == 1
    assert report["failed_runs"] == 1
    assert json.loads((tmp_path / "stability_report.json").read_text())["status"] == "flaky"


def test_run_test_uses_playwright_json_as_primary_result(monkeypatch, tmp_path: Path):
    pipeline = object.__new__(FullNativePipeline)
    test_file = tmp_path / "example.spec.ts"
    test_file.write_text("import { test } from '@playwright/test';\ntest('x', async () => {});\n")

    class FakeCompleted:
        returncode = 0
        stdout = "list reporter did not print passed"
        stderr = ""

    def fake_run(cmd, **kwargs):
        json_path = tmp_path / "test-results.json"
        json_path.write_text(json.dumps({"status": "passed", "suites": []}))
        return FakeCompleted()

    monkeypatch.setattr(full_native_pipeline.subprocess, "run", fake_run)

    result = pipeline._run_test(str(test_file), str(tmp_path), "chromium")

    assert result.passed is True
    assert result.error_summary == ""


def test_validate_generated_test_file_rejects_markdown(tmp_path: Path):
    pipeline = object.__new__(FullNativePipeline)
    pipeline.generated_preflight_list_enabled = False
    test_path = tmp_path / "bad.spec.ts"
    test_path.write_text(
        "```typescript\n"
        "import { test, expect } from '@playwright/test';\n"
        "test('x', async ({ page }) => { await expect(page).toHaveURL(/.*/); });\n"
        "```"
    )

    error = pipeline._validate_generated_test_file(
        test_path=test_path,
        run_dir=tmp_path,
        browser="chromium",
        test_type="browser",
    )

    assert "markdown fences" in error


def test_validate_generated_api_test_requires_request_fixture(tmp_path: Path):
    pipeline = object.__new__(FullNativePipeline)
    pipeline.generated_preflight_list_enabled = False
    test_path = tmp_path / "bad.api.spec.ts"
    test_path.write_text(
        "import { test, expect } from '@playwright/test';\n"
        "test('x', async ({ page }) => { await expect(page).toHaveURL(/.*/); });\n"
    )

    error = pipeline._validate_generated_test_file(
        test_path=test_path,
        run_dir=tmp_path,
        browser="chromium",
        test_type="api",
    )

    assert "request fixture" in error


def test_validate_generated_test_file_accepts_project_fixture_import(tmp_path: Path):
    pipeline = object.__new__(FullNativePipeline)
    pipeline.generated_preflight_list_enabled = False
    test_path = tmp_path / "fixture.spec.ts"
    test_path.write_text(
        "import { expect, test } from '../fixtures/test-data';\n"
        "test('uses fixture', async ({ page, testData }) => {\n"
        "  const user = testData.get<{ email: string }>('auth.valid-user');\n"
        "  await page.getByLabel('Email').fill(user.email);\n"
        "  await expect(page.getByRole('button', { name: /submit/i })).toBeVisible();\n"
        "});\n"
    )

    error = pipeline._validate_generated_test_file(
        test_path=test_path,
        run_dir=tmp_path,
        browser="chromium",
        test_type="browser",
    )

    assert error is None


@pytest.mark.asyncio
async def test_generation_format_repair_accepts_valid_repaired_code(tmp_path: Path, monkeypatch):
    pipeline = object.__new__(FullNativePipeline)
    pipeline.generated_preflight_list_enabled = False
    pipeline.test_data_execution_context = {}
    pipeline.test_data_env_vars = {}
    pipeline.owner_type = None
    pipeline.owner_id = None
    pipeline.owner_label = None
    pipeline.model_tier = "tool_deep"
    pipeline.native_generator = types.SimpleNamespace(cwd=tmp_path)
    test_path = tmp_path / "generated.spec.ts"
    test_path.write_text(
        "```typescript\n"
        "import { test, expect } from '@playwright/test';\n"
        "test('x', async ({ page }) => { await expect(page).toHaveURL(/.*/); });\n"
        "```"
    )

    async def fake_repair(_prompt: str):
        return AgentResult(
            success=True,
            output=(
                "import { test, expect } from '@playwright/test';\n"
                "test('x', async ({ page }) => {\n"
                "  await page.goto('https://example.test');\n"
                "  await expect(page).toHaveURL(/example/);\n"
                "});\n"
            ),
        )

    monkeypatch.setattr(pipeline, "_query_generation_repair_agent", fake_repair)

    metadata = await pipeline._attempt_generation_format_repair(
        test_path=test_path,
        run_dir=tmp_path,
        browser="chromium",
        test_type="browser",
        original_validation_error="Generated test file contains markdown fences or narrative output",
        spec_content="# Test\nNavigate to https://example.test",
        spec_path=tmp_path / "spec.md",
        target_url="https://example.test",
        plan_path=None,
        planner_draft_script_path=None,
    )

    assert metadata["generation_repair_attempted"] is True
    assert metadata["generation_repair_accepted"] is True
    assert metadata["original_validation_error"].startswith("Generated test file")
    assert len(metadata["repaired_file_hash"]) == 64
    assert "```" not in test_path.read_text()
    assert json.loads((tmp_path / "generation_repair_attempt.json").read_text())[
        "generation_repair_accepted"
    ] is True


@pytest.mark.asyncio
async def test_generation_format_repair_failure_keeps_original_file(tmp_path: Path, monkeypatch):
    pipeline = object.__new__(FullNativePipeline)
    pipeline.generated_preflight_list_enabled = False
    pipeline.test_data_execution_context = {}
    pipeline.test_data_env_vars = {}
    pipeline.owner_type = None
    pipeline.owner_id = None
    pipeline.owner_label = None
    pipeline.model_tier = "tool_deep"
    pipeline.native_generator = types.SimpleNamespace(cwd=tmp_path)
    test_path = tmp_path / "generated.spec.ts"
    original = (
        "```typescript\n"
        "import { test, expect } from '@playwright/test';\n"
        "test('x', async ({ page }) => { await expect(page).toHaveURL(/.*/); });\n"
        "```"
    )
    test_path.write_text(original)

    async def fake_repair(_prompt: str):
        return AgentResult(success=True, output="I cannot repair this.")

    monkeypatch.setattr(pipeline, "_query_generation_repair_agent", fake_repair)

    metadata = await pipeline._attempt_generation_format_repair(
        test_path=test_path,
        run_dir=tmp_path,
        browser="chromium",
        test_type="browser",
        original_validation_error="Generated test file contains markdown fences or narrative output",
        spec_content="# Test\nNavigate to https://example.test",
        spec_path=tmp_path / "spec.md",
        target_url="https://example.test",
        plan_path=None,
        planner_draft_script_path=None,
    )

    assert metadata["generation_repair_attempted"] is True
    assert metadata["generation_repair_accepted"] is False
    assert metadata["original_validation_error"].startswith("Generated test file")
    assert "generation_repair_validation_error" in metadata
    assert test_path.read_text() == original


def test_prepare_run_browser_context_detects_run_local_storage_state(tmp_path: Path):
    pipeline = object.__new__(FullNativePipeline)

    class Agent:
        pass

    pipeline.native_planner = Agent()
    pipeline.native_generator = Agent()
    pipeline.native_healer = Agent()
    storage = tmp_path / "browser-auth-storage-state.json"
    storage.write_text("{}")

    pipeline.prepare_run_browser_context(run_dir=tmp_path)

    config = tmp_path / "playwright.config.ts"
    if config.exists():
        assert "browser-auth-storage-state.json" in config.read_text()
    assert pipeline.native_healer.cwd == tmp_path


class _FakeGenerator:
    async def generate_test(self, spec_path, target_url=None, output_name=None, design_context=None, **kwargs):
        path = Path(spec_path).parent / f"{output_name or 'generated'}.spec.ts"
        path.write_text(
            "import { test, expect } from '@playwright/test';\n"
            "test('generated', async ({ page }) => { await expect(page).toHaveURL(/.*/); });\n"
        )
        self.design_context = design_context
        self.kwargs = kwargs
        return path


class _FakeInvalidGenerator:
    async def generate_test(self, spec_path, target_url=None, output_name=None, design_context=None, **kwargs):
        path = Path(spec_path).parent / f"{output_name or 'generated'}.spec.ts"
        path.write_text(
            "```typescript\n"
            "import { test, expect } from '@playwright/test';\n"
            "test('generated', async ({ page }) => { await expect(page).toHaveURL(/.*/); });\n"
            "```"
        )
        self.design_context = design_context
        self.kwargs = kwargs
        return path


class _FakeHealer:
    last_tool_calls = [
        {"name": "mcp__playwright-test__test_run"},
        {"name": "mcp__playwright-test__browser_snapshot"},
        {"name": "mcp__playwright-test__browser_network_requests"},
    ]

    async def heal_test(self, test_file, error_log=None, timeout_seconds=None, diagnosis_context=None, **kwargs):
        Path(test_file).write_text(
            "import { test, expect } from '@playwright/test';\n"
            "test('healed', async ({ page }) => { await expect(page).toHaveURL(/.*/); });\n"
        )
        self.diagnosis_context = diagnosis_context
        return Path(test_file).read_text()


def _pipeline_with_results(results: list[PipelineTestResult], tmp_path: Path) -> FullNativePipeline:
    pipeline = object.__new__(FullNativePipeline)
    pipeline.project_id = "default"
    pipeline.native_generator = _FakeGenerator()
    pipeline.native_healer = _FakeHealer()
    pipeline.test_design_agent = __import__(
        "orchestrator.workflows.agentic_quality", fromlist=["TestDesignAgent"]
    ).TestDesignAgent()
    pipeline.test_critic_agent = __import__(
        "orchestrator.workflows.agentic_quality", fromlist=["TestCriticAgent"]
    ).TestCriticAgent()
    pipeline.failure_triage_agent = FailureTriageAgent()
    pipeline.stability_verifier = StabilityVerifier(reruns=2)
    pipeline.api_generator = None
    pipeline.api_healer = None

    remaining = list(results)

    def fake_run_test(_test_file: str, _output_dir: str, _browser: str) -> PipelineTestResult:
        if not remaining:
            return PipelineTestResult(passed=True, exit_code=0, output="1 passed")
        return remaining.pop(0)

    pipeline._run_test = fake_run_test
    return pipeline


@pytest.mark.asyncio
async def test_api_pipeline_records_handoff_manifest(tmp_path: Path):
    spec = tmp_path / "api.md"
    spec.write_text("# API\nBase URL: https://example.test\nGET /health\nVerify response status is 200")
    run_dir = tmp_path / "api-run"
    run_dir.mkdir()

    class FakeApiGenerator:
        last_handoff_consumption = {"received_spec": True, "spec_status": "used"}

        async def generate_test(self, spec_path, target_url=None, output_name=None, handoff_manifest_path=None):
            path = tmp_path / f"{output_name or 'api'}.api.spec.ts"
            path.write_text(
                "import { test, expect } from '@playwright/test';\n"
                "test('api', async ({ request }) => { const response = await request.get('/health'); expect(response.status()).toBe(200); });\n"
            )
            return path

    pipeline = object.__new__(FullNativePipeline)
    pipeline.project_id = "default"
    pipeline.api_generator = FakeApiGenerator()
    pipeline.api_healer = None
    pipeline.generated_preflight_list_enabled = False
    pipeline._run_test = lambda *_args, **_kwargs: PipelineTestResult(
        passed=True, exit_code=0, output="1 passed"
    )

    result = await pipeline._run_api_pipeline(
        spec_path=str(spec),
        spec_content=spec.read_text(),
        run_dir=run_dir,
        browser="chromium",
        target_url="https://example.test",
    )

    manifest = json.loads((run_dir / "handoff_manifest.json").read_text())
    assert result["success"] is True
    assert manifest["stages"]["api_generator"]["status"] == "ready"
    assert manifest["stages"]["test_run"]["status"] == "passed"
    assert manifest["artifacts"]["generated_api_test"]["kind"] == "playwright_api_test"
    assert len(manifest["artifacts"]["generated_api_test"]["hash"]) == 64


@pytest.mark.asyncio
async def test_run_native_generator_forwards_plan_path(tmp_path: Path):
    pipeline = object.__new__(FullNativePipeline)
    pipeline.native_generator = _FakeGenerator()
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Test\nNavigate to https://example.test")
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("await page.getByRole('button', { name: 'Save' }).click();")
    draft_script_path = tmp_path / "plan.draft.spec.ts"
    draft_script_path.write_text(
        "import { test, expect } from '@playwright/test';\n"
        "test('draft', async ({ page }) => { await expect(page.getByRole('button', { name: 'Save' })).toBeVisible(); });\n"
    )

    output = await pipeline._run_native_generator(
        spec_path=str(spec_path),
        target_url="https://example.test",
        output_name="generated",
        plan_path=plan_path,
        planner_draft_script_path=draft_script_path,
    )

    assert output == tmp_path / "generated.spec.ts"
    assert pipeline.native_generator.kwargs["plan_path"] == plan_path
    assert pipeline.native_generator.kwargs["planner_draft_script_path"] == draft_script_path


@pytest.mark.asyncio
async def test_pipeline_aborts_when_native_planner_validation_fails(monkeypatch, tmp_path: Path):
    spec = tmp_path / "spec.md"
    spec.write_text("# Test\nNavigate to https://example.test/checkout\n1. Verify checkout")
    run_dir = tmp_path / "run"

    class FailingPlanner:
        env_vars = {}

        async def generate_spec_from_flow_context(self, **_kwargs):
            raise full_native_pipeline.SpecGenerationError(
                "Live-browser planner saved a plan before navigating to the Target URL and capturing a snapshot.",
                diagnostics={
                    "target_navigation_observed": False,
                    "planner_save_plan_observed": True,
                },
            )

    class ExplodingGenerator:
        env_vars = {}
        called = False

        async def generate_test(self, **_kwargs):
            self.called = True
            raise AssertionError("generator should not run after planner validation failure")

    monkeypatch.setattr(full_native_pipeline, "cleanup_orphaned_browsers", lambda: None)
    pipeline = FullNativePipeline(project_id="")
    pipeline.native_planner = FailingPlanner()
    pipeline.native_generator = ExplodingGenerator()

    result = await pipeline.run(str(spec), run_dir, skip_planning=False)

    assert result["success"] is False
    assert result["stage"] == "planning"
    assert result["planner_diagnostics"]["target_navigation_observed"] is False
    assert pipeline.native_generator.called is False
    assert (run_dir / "status.txt").read_text() == "error"
    error_payload = json.loads((run_dir / "pipeline_error.json").read_text())
    assert error_payload["stage"] == "planning"
    assert error_payload["planner_diagnostics"]["planner_save_plan_observed"] is True
    metrics = json.loads((run_dir / "run_metrics.json").read_text())
    assert metrics["planner_success"] is False
    assert metrics["failure_category"] == "planner_validation"


@pytest.mark.asyncio
async def test_pipeline_passes_and_stability_passes(tmp_path: Path):
    spec = tmp_path / "spec.md"
    spec.write_text("# Test\nNavigate to https://example.com\n1. Verify page is visible")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    pipeline = _pipeline_with_results(
        [
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
        ],
        tmp_path,
    )

    result = await pipeline.run(str(spec), run_dir, skip_planning=True)

    assert result["success"] is True
    assert result["stage"] == "completed"
    assert (run_dir / "test_design.json").exists()
    assert (run_dir / "test_critic.json").exists()
    assert json.loads((run_dir / "stability_report.json").read_text())["status"] == "stable"
    metrics = json.loads((run_dir / "run_metrics.json").read_text())
    assert metrics["initial_run_passed"] is True
    assert metrics["stable_first_pass"] is True
    manifest = json.loads((run_dir / "handoff_manifest.json").read_text())
    assert manifest["stages"]["planner"]["status"] == "skipped"
    assert manifest["artifacts"]["planner_plan"]["validation_status"] == "optional_missing"
    assert manifest["artifacts"]["planner_draft_script"]["validation_status"] == "optional_missing"
    assert manifest["stages"]["generator"]["status"] == "ready"
    assert len(manifest["artifacts"]["generated_test"]["hash"]) == 64


@pytest.mark.asyncio
async def test_pipeline_repairs_generation_validation_and_continues(tmp_path: Path, monkeypatch):
    spec = tmp_path / "spec.md"
    spec.write_text("# Test\nNavigate to https://example.com\n1. Verify page is visible")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    pipeline = _pipeline_with_results(
        [
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
        ],
        tmp_path,
    )
    pipeline.native_generator = _FakeInvalidGenerator()

    async def fake_repair(_prompt: str):
        return AgentResult(
            success=True,
            output=(
                "import { test, expect } from '@playwright/test';\n"
                "test('generated', async ({ page }) => {\n"
                "  await page.goto('https://example.com');\n"
                "  await expect(page).toHaveURL(/example/);\n"
                "});\n"
            ),
        )

    monkeypatch.setattr(pipeline, "_query_generation_repair_agent", fake_repair)

    result = await pipeline.run(str(spec), run_dir, skip_planning=True)

    assert result["success"] is True
    assert result["stage"] == "completed"
    metrics = json.loads((run_dir / "run_metrics.json").read_text())
    assert metrics["generation_repair_attempted"] is True
    assert metrics["generation_repair_accepted"] is True
    assert "markdown fences" in metrics["original_validation_error"]
    manifest = json.loads((run_dir / "handoff_manifest.json").read_text())
    assert manifest["stages"]["generator"]["metadata"]["generation_repair_accepted"] is True
    assert manifest["artifacts"]["generated_test"]["validation_status"] == "valid"
    assert (run_dir / "export.json").exists()


@pytest.mark.asyncio
async def test_planned_pipeline_records_and_consumes_planner_draft(tmp_path: Path):
    spec = tmp_path / "spec.md"
    spec.write_text("# Test\nNavigate to https://example.com\n1. Click Save")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    class FakePlanner:
        env_vars = {}
        last_draft_script_path = None
        cwd = None
        session_dir = None

        async def generate_spec_from_flow_context(self, output_dir, **_kwargs):
            plan_path = Path(output_dir) / "planner-output.md"
            plan_path.write_text(
                "# Test Plan: Save\n\n"
                "### TC-001: Save record\n"
                "**Description:** User saves a record.\n"
                "**Preconditions:** User can access the page.\n"
                "**Steps:**\n"
                "1. Click `page.getByRole('button', { name: 'Save' })`.\n"
                "**Expected Result:** Save confirmation appears.\n"
                "\n## Draft Playwright Script\n"
                "```typescript\n"
                "import { test, expect } from '@playwright/test';\n"
                "test('save record', async ({ page }) => {\n"
                "  await expect(page.getByRole('button', { name: 'Save' })).toBeVisible();\n"
                "});\n"
                "```\n"
            )
            draft_path = Path(output_dir) / "planner-output.draft.spec.ts"
            draft_path.write_text(
                "import { test, expect } from '@playwright/test';\n"
                "test('save record', async ({ page }) => {\n"
                "  await expect(page.getByRole('button', { name: 'Save' })).toBeVisible();\n"
                "});\n"
            )
            self.last_draft_script_path = draft_path
            return plan_path

    pipeline = _pipeline_with_results(
        [
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
        ],
        tmp_path,
    )
    pipeline.native_planner = FakePlanner()

    result = await pipeline.run(str(spec), run_dir, skip_planning=False)

    manifest = json.loads((run_dir / "handoff_manifest.json").read_text())
    plan_json = json.loads((run_dir / "plan.json").read_text())
    consumed = manifest["stages"]["generator"]["artifacts_consumed"]
    assert result["success"] is True
    assert (run_dir / "plan.md").exists()
    assert plan_json["plannerDraftScriptPath"].endswith("planner-output.draft.spec.ts")
    assert plan_json["handoffManifestPath"].endswith("handoff_manifest.json")
    assert manifest["artifacts"]["planner_plan"]["path"] == str(run_dir / "plan.md")
    assert manifest["artifacts"]["planner_draft_script"]["validation_status"] == "valid"
    assert consumed["planner_plan"]["status"] == "used"
    assert consumed["planner_draft_script"]["status"] == "used"
    assert pipeline.native_generator.kwargs["planner_draft_script_path"] == Path(
        plan_json["plannerDraftScriptPath"]
    )


@pytest.mark.asyncio
async def test_pipeline_hardens_once_when_stability_fails(tmp_path: Path):
    spec = tmp_path / "spec.md"
    spec.write_text("# Test\nNavigate to https://example.com\n1. Verify page is visible")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    pipeline = _pipeline_with_results(
        [
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
            PipelineTestResult(passed=False, exit_code=1, output="failed", error_summary="flaked"),
        ],
        tmp_path,
    )

    result = await pipeline.run(str(spec), run_dir, skip_planning=True)

    assert result["success"] is True
    assert result["stage"] == "completed"
    assert result["stability_hardened"] is True
    assert (run_dir / "status.txt").read_text() == "passed"


@pytest.mark.asyncio
async def test_pipeline_heals_when_triage_allows(tmp_path: Path):
    spec = tmp_path / "spec.md"
    spec.write_text("# Test\nNavigate to https://example.com\n1. Verify page is visible")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    pipeline = _pipeline_with_results(
        [
            PipelineTestResult(
                passed=False, exit_code=1, output="TimeoutError: waiting for locator", error_summary="timeout"
            ),
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
        ],
        tmp_path,
    )

    result = await pipeline.run(str(spec), run_dir, skip_planning=True)

    assert result["success"] is True
    assert result["stage"] == "healed"
    diagnosis = json.loads((run_dir / "failure_diagnosis.json").read_text())
    assert diagnosis["heal_allowed"] is True
    assert "Failure category" in pipeline.native_healer.diagnosis_context


@pytest.mark.asyncio
async def test_pipeline_heals_broad_server_text_when_unconfirmed(tmp_path: Path):
    spec = tmp_path / "spec.md"
    spec.write_text("# Test\nNavigate to https://example.com\n1. Verify page is visible")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    pipeline = _pipeline_with_results(
        [
            PipelineTestResult(
                passed=False,
                exit_code=1,
                output="Error: 500 Internal Server Error",
                error_summary="500",
            ),
        ],
        tmp_path,
    )

    result = await pipeline.run(str(spec), run_dir, skip_planning=True)

    assert result["success"] is True
    assert result["stage"] == "healed"
    diagnosis = json.loads((run_dir / "failure_diagnosis.json").read_text())
    assert diagnosis["category"] == "product_bug"
    assert diagnosis["heal_allowed"] is True


@pytest.mark.asyncio
async def test_memory_full_loop_attributes_pipeline_outcomes(monkeypatch, tmp_path: Path):
    from orchestrator.api import db as db_module
    from orchestrator.api.models_db import MemoryFeedbackEvent, MemoryInjectionEvent
    from orchestrator.memory import agent_memory as agent_memory_module
    from orchestrator.memory import telemetry as telemetry_module
    from orchestrator.memory.agent_memory import AgentMemoryService
    from orchestrator.memory.effectiveness import MemoryEffectivenessService
    from orchestrator.memory.telemetry import record_memory_injection

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(agent_memory_module, "engine", engine)
    monkeypatch.setattr(telemetry_module, "engine", engine)
    monkeypatch.setattr(AgentMemoryService, "_index_memory", lambda self, memory: None)
    monkeypatch.setenv("MEMORY_ENABLED", "true")
    monkeypatch.setenv("MEMORY_PROJECT_ID", "project-memory-loop")

    memory_service = AgentMemoryService()
    helpful = memory_service.create_memory(
        kind="project_fact",
        content="Login starts on /login and uses email plus password.",
        project_id="project-memory-loop",
        confidence=0.9,
        importance=0.85,
    )
    risky = memory_service.create_memory(
        kind="agent_lesson",
        content="Old login selector used text Submit.",
        project_id="project-memory-loop",
        confidence=0.4,
        importance=0.7,
    )

    class MemoryRecordingGenerator:
        def __init__(self, memory_id: str):
            self.memory_id = memory_id

        async def generate_test(self, spec_path, target_url=None, output_name=None, design_context=None, **kwargs):
            path = Path(spec_path).parent / f"{output_name or 'generated'}.spec.ts"
            path.write_text(
                "import { test, expect } from '@playwright/test';\n"
                "test('generated', async ({ page }) => { await expect(page).toHaveURL(/.*/); });\n"
            )
            record_memory_injection(
                project_id="project-memory-loop",
                actor_type="agent",
                stage="native_generator",
                source_type="spec",
                source_id=str(spec_path),
                query="login",
                bundle={"unified": {"agent_memories": {"semantic": [{"id": self.memory_id}]}}},
                context_text="## Memory Context\n- seeded memory",
                extra_data={
                    "spec_path": str(spec_path),
                    "run_id": kwargs.get("memory_run_id"),
                    "empty_recall": False,
                },
            )
            return path

    passing_run = tmp_path / "memory-pass-run"
    passing_run.mkdir()
    passing_spec = tmp_path / "passing-spec.md"
    passing_spec.write_text("# Login\nNavigate to https://example.test\n1. Log in")
    passing_pipeline = _pipeline_with_results(
        [
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
            PipelineTestResult(passed=True, exit_code=0, output="1 passed"),
        ],
        tmp_path,
    )
    passing_pipeline.project_id = "project-memory-loop"
    passing_pipeline.native_generator = MemoryRecordingGenerator(helpful.id)

    passing_result = await passing_pipeline.run(str(passing_spec), passing_run, skip_planning=True)

    failing_run = tmp_path / "memory-fail-run"
    failing_run.mkdir()
    failing_spec = tmp_path / "failing-spec.md"
    failing_spec.write_text("# Login\nNavigate to https://example.test\n1. Log in with old selector")
    failing_pipeline = _pipeline_with_results(
        [
            PipelineTestResult(
                passed=False,
                exit_code=1,
                output="Error: 500 Internal Server Error",
                error_summary="500",
            ),
            PipelineTestResult(
                passed=False,
                exit_code=1,
                output="Error: 500 Internal Server Error",
                error_summary="500",
            ),
            PipelineTestResult(
                passed=False,
                exit_code=1,
                output="Error: 500 Internal Server Error",
                error_summary="500",
            ),
            PipelineTestResult(
                passed=False,
                exit_code=1,
                output="Error: 500 Internal Server Error",
                error_summary="500",
            ),
        ],
        tmp_path,
    )
    failing_pipeline.project_id = "project-memory-loop"
    failing_pipeline.native_generator = MemoryRecordingGenerator(risky.id)

    failing_result = await failing_pipeline.run(str(failing_spec), failing_run, skip_planning=True)

    summary = MemoryEffectivenessService().summarize(project_id="project-memory-loop")
    helpful_ids = {item["memory_id"] for item in summary["top_helpful_memories"]}
    harmful_ids = {item["memory_id"] for item in summary["top_harmful_memories"]}

    with Session(engine) as session:
        events = session.exec(select(MemoryInjectionEvent)).all()
        feedback = session.exec(select(MemoryFeedbackEvent)).all()

    assert passing_result["success"] is True
    assert failing_result["success"] is False
    assert {event.extra_data.get("run_id") for event in events} == {"memory-pass-run", "memory-fail-run"}
    assert any(event.extra_data.get("outcome_status") == "first_run_passed" for event in events)
    assert any(event.extra_data.get("outcome_status") == "first_run_failed" for event in events)
    assert any(row.rating == "up" and row.memory_id == helpful.id for row in feedback)
    assert any(row.rating == "down" and row.memory_id == risky.id for row in feedback)
    assert helpful.id in helpful_ids
    assert risky.id in harmful_ids
