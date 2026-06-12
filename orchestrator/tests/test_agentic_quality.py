import importlib
import json
import sys
import types
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.workflows.agentic_quality import (
    FailureTriageAgent,
    StabilityVerifier,
    build_agentic_summary,
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


class _FakeGenerator:
    async def generate_test(self, spec_path, target_url=None, output_name=None, design_context=None, **kwargs):
        path = Path(spec_path).parent / f"{output_name or 'generated'}.spec.ts"
        path.write_text(
            "import { test, expect } from '@playwright/test';\n"
            "test('generated', async ({ page }) => { await expect(page).toHaveURL(/.*/); });\n"
        )
        self.design_context = design_context
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
