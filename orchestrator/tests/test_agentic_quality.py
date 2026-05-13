import importlib
import json
import sys
import types
from pathlib import Path

import pytest

from orchestrator.workflows.agentic_quality import (
    FailureTriageAgent,
    StabilityVerifier,
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


def test_failure_triage_blocks_high_confidence_non_healable(tmp_path: Path):
    diagnosis = FailureTriageAgent().diagnose(
        test_path=tmp_path / "test.spec.ts",
        error_output="Error: 500 Internal Server Error",
        design=None,
        critic=None,
        run_dir=tmp_path,
    )

    assert diagnosis["category"] == "product_bug"
    assert diagnosis["confidence"] >= 0.8
    assert diagnosis["heal_allowed"] is False
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


class _FakeGenerator:
    async def generate_test(self, spec_path, target_url=None, output_name=None, design_context=None):
        path = Path(spec_path).parent / f"{output_name or 'generated'}.spec.ts"
        path.write_text(
            "import { test, expect } from '@playwright/test';\n"
            "test('generated', async ({ page }) => { await expect(page).toHaveURL(/.*/); });\n"
        )
        self.design_context = design_context
        return path


class _FakeHealer:
    async def heal_test(self, test_file, error_log=None, timeout_seconds=None, diagnosis_context=None):
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


@pytest.mark.asyncio
async def test_pipeline_marks_flaky_when_stability_fails(tmp_path: Path):
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

    assert result["success"] is False
    assert result["stage"] == "stability_failed"
    assert (run_dir / "status.txt").read_text() == "failed"
    assert json.loads((run_dir / "agentic_summary.json").read_text())["stability"]["status"] == "flaky"


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
async def test_pipeline_skips_healing_for_non_healable_failure(tmp_path: Path):
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

    assert result["success"] is False
    assert result["stage"] == "triage_blocked_healing"
    diagnosis = json.loads((run_dir / "failure_diagnosis.json").read_text())
    assert diagnosis["category"] == "product_bug"
    assert diagnosis["heal_allowed"] is False
