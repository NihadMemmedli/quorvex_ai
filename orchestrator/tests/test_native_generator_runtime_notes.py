import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.api import db as db_module
from orchestrator.api.db import engine
from orchestrator.api.models_db import (
    AgentRun,
    AgentRunEvent,
    AgentRunEvidence,
    AgentRunNote,
    AgentRunTaskContract,
)
from orchestrator.services.agent_native_runs import list_agent_run_notes
from orchestrator.services.agent_run_events import list_agent_run_events
from orchestrator.services.handoff_manifest import init_manifest, load_manifest
from orchestrator.utils.agent_runner import AgentResult, ToolCall
from orchestrator.utils.spec_detector import SpecType
from orchestrator.workflows.full_native_pipeline import (
    FullNativePipeline,
    _BrowserGenerationStageResult,
    _NativeRunContext,
)


def _ensure_tables() -> None:
    SQLModel.metadata.create_all(engine, checkfirst=True)
    db_module._run_migrations()


def _create_agent_run(run_id: str) -> None:
    with Session(engine) as session:
        session.add(
            AgentRun(
                id=run_id,
                agent_type="spec_generation",
                status="running",
                config_json="{}",
                project_id=None,
            )
        )
        session.commit()


def _cleanup_run(run_id: str) -> None:
    with Session(engine) as session:
        for evidence in session.exec(
            select(AgentRunEvidence).where(AgentRunEvidence.run_id == run_id)
        ).all():
            session.delete(evidence)
        for note in session.exec(
            select(AgentRunNote).where(AgentRunNote.run_id == run_id)
        ).all():
            session.delete(note)
        for contract in session.exec(
            select(AgentRunTaskContract).where(AgentRunTaskContract.run_id == run_id)
        ).all():
            session.delete(contract)
        for event in session.exec(
            select(AgentRunEvent).where(AgentRunEvent.run_id == run_id)
        ).all():
            session.delete(event)
        run = session.get(AgentRun, run_id)
        if run:
            session.delete(run)
        session.commit()


class _GeneratorSuccess:
    model_tier = "tool_deep"
    last_handoff_consumption = {}
    last_self_run_result = None
    last_self_heal_attempts = 0
    last_self_heal_passed = False
    last_self_heal_artifact_path = None

    def __init__(self) -> None:
        self.last_agent_result = AgentResult(
            success=True,
            messages_received=3,
            text_blocks_received=2,
            tool_calls=[
                ToolCall(name="generator_setup_page", timestamp=datetime.utcnow()),
                ToolCall(name="generator_write_test", timestamp=datetime.utcnow()),
            ],
            session_id="gen-session-1",
        )

    async def generate_test(
        self,
        spec_path,
        target_url=None,
        output_name=None,
        **_kwargs,
    ):
        path = Path(spec_path).parent / f"{output_name or 'generated'}.spec.ts"
        path.write_text(
            "import { test, expect } from '@playwright/test';\n"
            "test('generated', async ({ page }) => { "
            "await expect(page).toHaveURL(/.*/); });\n"
        )
        return path


class _GeneratorAcceptedOutput(_GeneratorSuccess):
    def __init__(self) -> None:
        super().__init__()
        self.last_agent_result = AgentResult(
            success=False,
            error="provider overloaded after writing",
            error_type="provider_overloaded",
            api_error_status=529,
            messages_received=2,
            text_blocks_received=1,
            tool_calls=[
                ToolCall(name="generator_write_test", timestamp=datetime.utcnow()),
            ],
            session_id="gen-session-accepted-output",
        )


class _GeneratorSelfRun(_GeneratorSuccess):
    def __init__(
        self,
        *,
        final_status: str,
        self_heal_attempts: int = 0,
        self_heal_passed: bool = False,
        self_heal_artifact_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.last_self_run_result = {"final_status": final_status}
        self.last_self_heal_attempts = self_heal_attempts
        self.last_self_heal_passed = self_heal_passed
        self.last_self_heal_artifact_path = self_heal_artifact_path


class _GeneratorFailure:
    model_tier = "tool_deep"
    last_handoff_consumption = {}
    last_agent_result = AgentResult(
        success=False,
        error="provider overloaded",
        error_type="provider_overloaded",
        messages_received=1,
        text_blocks_received=0,
        tool_calls=[],
    )

    async def generate_test(self, **_kwargs):
        raise RuntimeError("provider overloaded")


class _DesignAgent:
    def analyze(self, **_kwargs):
        return {}

    def condensed_context(self, _design):
        return ""


class _CriticAgent:
    def review(self, **_kwargs):
        return {"status": "ok"}


def _agent_note_events(run_id: str) -> list[AgentRunEvent]:
    return list_agent_run_events(run_id=run_id, event_type="agent_note")


def _run_progress(run_id: str) -> dict:
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        assert run is not None
        return run.progress or {}


def _make_context(tmp_path: Path, run_id: str) -> _NativeRunContext:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Test\nNavigate to https://example.test")
    (run_dir / "spec_resolved.md").write_text(spec_path.read_text())
    handoff_manifest_path = init_manifest(run_dir, pipeline_type="browser")
    return _NativeRunContext(
        spec_path=str(spec_path),
        spec_file=spec_path,
        run_dir=run_dir,
        browser="chromium",
        hybrid_healing=False,
        max_iterations=20,
        skip_planning=True,
        existing_test_path=None,
        source_test_path=None,
        force_api=False,
        handoff_manifest_path=handoff_manifest_path,
        spec_content=spec_path.read_text(),
        raw_included_spec_content=spec_path.read_text(),
        resolved_spec_content=spec_path.read_text(),
        target_url="https://example.test",
        auth_context={},
        test_data_context={},
        credentials=None,
        login_url=None,
        run_id=run_id,
        spec_type=SpecType.STANDARD,
    )


def _make_pipeline(run_id: str, generator) -> FullNativePipeline:
    pipeline = object.__new__(FullNativePipeline)
    pipeline.owner_id = run_id
    pipeline.project_id = None
    pipeline.native_generator = generator
    pipeline.test_design_agent = _DesignAgent()
    pipeline.test_critic_agent = _CriticAgent()
    pipeline.generated_preflight_list_enabled = False
    pipeline._publish_agentic_summary = lambda _run_dir: None
    pipeline._attribute_memory_outcome = lambda **_kwargs: None
    return pipeline


def _patch_stage_side_effects(monkeypatch) -> None:
    monkeypatch.setattr(
        "orchestrator.workflows.full_native_pipeline.report_progress",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "orchestrator.workflows.full_native_pipeline.cleanup_orphaned_browsers",
        lambda: None,
    )


@pytest.mark.asyncio
async def test_run_native_generator_writes_start_and_success_notes(tmp_path: Path):
    _ensure_tables()
    run_id = "spec-generation-generator-success-notes"
    _cleanup_run(run_id)
    _create_agent_run(run_id)
    spec_path = tmp_path / "spec_resolved.md"
    spec_path.write_text("# Test\nNavigate to https://example.test")

    pipeline = object.__new__(FullNativePipeline)
    pipeline.owner_id = run_id
    pipeline.native_generator = _GeneratorSuccess()

    try:
        output = await pipeline._run_native_generator(
            spec_path=str(spec_path),
            target_url="https://example.test",
            output_name="generated",
            run_dir=tmp_path,
            browser="chromium",
        )

        assert output == tmp_path / "generated.spec.ts"
        notes = list_agent_run_notes(run_id=run_id)
        assert [note.title for note in notes] == [
            "Generator started",
            "Generator artifact produced",
        ]
        assert notes[1].payload["tool_calls"] == 2
        assert notes[1].payload["messages_received"] == 3
        assert notes[1].payload["file_hash"]
        events = _agent_note_events(run_id)
        assert [event.message for event in events] == [
            "Generator started",
            "Generator artifact produced",
        ]
        progress = _run_progress(run_id)
        assert [note["title"] for note in progress["live_notes_tail"]] == [
            "Generator started",
            "Generator artifact produced",
        ]
        assert progress["current_state"]["title"] == "Generator artifact produced"
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_run_native_generator_writes_success_note_for_accepted_output(
    tmp_path: Path,
):
    _ensure_tables()
    run_id = "spec-generation-generator-accepted-output-note"
    _cleanup_run(run_id)
    _create_agent_run(run_id)
    spec_path = tmp_path / "spec_resolved.md"
    spec_path.write_text("# Test\nNavigate to https://example.test")

    pipeline = object.__new__(FullNativePipeline)
    pipeline.owner_id = run_id
    pipeline.native_generator = _GeneratorAcceptedOutput()

    try:
        output = await pipeline._run_native_generator(
            spec_path=str(spec_path),
            target_url="https://example.test",
            output_name="generated",
            run_dir=tmp_path,
            browser="chromium",
        )

        assert output == tmp_path / "generated.spec.ts"
        notes = list_agent_run_notes(run_id=run_id)
        assert [note.title for note in notes] == [
            "Generator started",
            "Generator artifact produced",
        ]
        assert notes[-1].payload["error_type"] == "provider_overloaded"
        assert "Generator failed" not in [note.title for note in notes]
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_run_native_generator_idempotent_retry_refreshes_progress(
    tmp_path: Path,
):
    _ensure_tables()
    run_id = "spec-generation-generator-idempotent-retry-note"
    _cleanup_run(run_id)
    _create_agent_run(run_id)
    spec_path = tmp_path / "spec_resolved.md"
    spec_path.write_text("# Test\nNavigate to https://example.test")

    pipeline = object.__new__(FullNativePipeline)
    pipeline.owner_id = run_id
    pipeline.native_generator = _GeneratorSuccess()

    try:
        first_output = await pipeline._run_native_generator(
            spec_path=str(spec_path),
            target_url="https://example.test",
            output_name="generated",
            run_dir=tmp_path,
            browser="chromium",
        )
        assert first_output == tmp_path / "generated.spec.ts"

        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run is not None
            run.progress = {
                "current_state": {
                    "phase": "stale",
                    "status": "running",
                    "title": "stale progress",
                },
                "live_notes_tail": [],
            }
            session.add(run)
            session.commit()

        retry_output = await pipeline._run_native_generator(
            spec_path=str(spec_path),
            target_url="https://example.test",
            output_name="generated",
            run_dir=tmp_path,
            browser="chromium",
        )

        assert retry_output == first_output
        notes = list_agent_run_notes(run_id=run_id)
        events = _agent_note_events(run_id)
        assert [note.title for note in notes] == [
            "Generator started",
            "Generator artifact produced",
        ]
        assert [event.message for event in events] == [
            "Generator started",
            "Generator artifact produced",
        ]
        progress = _run_progress(run_id)
        assert progress["current_state"]["title"] == "Generator artifact produced"
        assert [note["title"] for note in progress["live_notes_tail"]] == [
            "Generator started",
            "Generator artifact produced",
        ]
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_browser_generation_stage_writes_failure_note(tmp_path: Path, monkeypatch):
    _ensure_tables()
    run_id = "spec-generation-generator-failure-note"
    _cleanup_run(run_id)
    _create_agent_run(run_id)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Test\nNavigate to https://example.test")
    (run_dir / "spec_resolved.md").write_text(spec_path.read_text())
    handoff_manifest_path = init_manifest(run_dir, pipeline_type="browser")

    pipeline = object.__new__(FullNativePipeline)
    pipeline.owner_id = run_id
    pipeline.native_generator = _GeneratorFailure()
    pipeline.test_design_agent = _DesignAgent()
    pipeline._publish_agentic_summary = lambda _run_dir: None
    pipeline._attribute_memory_outcome = lambda **_kwargs: None
    monkeypatch.setattr(
        "orchestrator.workflows.full_native_pipeline.report_progress",
        lambda *_args, **_kwargs: None,
    )

    ctx = _NativeRunContext(
        spec_path=str(spec_path),
        spec_file=spec_path,
        run_dir=run_dir,
        browser="chromium",
        hybrid_healing=False,
        max_iterations=20,
        skip_planning=True,
        existing_test_path=None,
        source_test_path=None,
        force_api=False,
        handoff_manifest_path=handoff_manifest_path,
        spec_content=spec_path.read_text(),
        raw_included_spec_content=spec_path.read_text(),
        resolved_spec_content=spec_path.read_text(),
        target_url="https://example.test",
        auth_context={},
        test_data_context={},
        credentials=None,
        login_url=None,
        run_id=run_id,
        spec_type=SpecType.STANDARD,
    )

    try:
        result = await pipeline._run_browser_generation_stage(
            ctx,
            plan_path=None,
            planner_draft_script_path=None,
        )

        assert isinstance(result, _BrowserGenerationStageResult)
        assert result.result is not None
        assert result.result["success"] is False
        notes = list_agent_run_notes(run_id=run_id)
        assert [note.title for note in notes] == [
            "Generator started",
            "Generator failed",
        ]
        assert notes[-1].level == "error"
        assert notes[-1].payload["failure_category"] == "generation"
        assert "provider overloaded" in notes[-1].body
        assert [note.title for note in notes].count("Generator failed") == 1
        events = _agent_note_events(run_id)
        assert [event.message for event in events].count("Generator failed") == 1
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_browser_generation_stage_writes_self_run_passed_note(
    tmp_path: Path,
    monkeypatch,
):
    _ensure_tables()
    run_id = "spec-generation-generator-self-run-passed-note"
    _cleanup_run(run_id)
    _create_agent_run(run_id)
    ctx = _make_context(tmp_path, run_id)
    pipeline = _make_pipeline(run_id, _GeneratorSelfRun(final_status="passed"))
    _patch_stage_side_effects(monkeypatch)

    try:
        result = await pipeline._run_browser_generation_stage(
            ctx,
            plan_path=None,
            planner_draft_script_path=None,
        )

        assert isinstance(result, _BrowserGenerationStageResult)
        assert result.test_path == ctx.run_dir / "spec.spec.ts"
        notes = list_agent_run_notes(run_id=run_id)
        assert [note.title for note in notes] == [
            "Generator started",
            "Generator artifact produced",
            "Generator self-run passed",
            "Generator output accepted",
        ]
        self_run_note = next(
            note for note in notes if note.title == "Generator self-run passed"
        )
        assert self_run_note.note_type == "verifier_note"
        assert self_run_note.level == "info"
        assert self_run_note.payload["final_status"] == "passed"
        assert self_run_note.payload["self_heal_attempts"] == 0
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_browser_generation_stage_writes_self_heal_warning_note(
    tmp_path: Path,
    monkeypatch,
):
    _ensure_tables()
    run_id = "spec-generation-generator-self-heal-warning-note"
    _cleanup_run(run_id)
    _create_agent_run(run_id)
    ctx = _make_context(tmp_path, run_id)
    artifact_path = ctx.run_dir / "generator_self_heal.json"
    artifact_path.write_text("{}")
    pipeline = _make_pipeline(
        run_id,
        _GeneratorSelfRun(
            final_status="failed",
            self_heal_attempts=2,
            self_heal_passed=False,
            self_heal_artifact_path=artifact_path,
        ),
    )
    _patch_stage_side_effects(monkeypatch)

    try:
        result = await pipeline._run_browser_generation_stage(
            ctx,
            plan_path=None,
            planner_draft_script_path=None,
        )

        assert isinstance(result, _BrowserGenerationStageResult)
        notes = list_agent_run_notes(run_id=run_id)
        assert [note.title for note in notes] == [
            "Generator started",
            "Generator artifact produced",
            "Generator self-heal required",
            "Generator output accepted",
        ]
        self_heal_note = next(
            note for note in notes if note.title == "Generator self-heal required"
        )
        assert self_heal_note.note_type == "blocker"
        assert self_heal_note.level == "warning"
        assert self_heal_note.artifact_path == str(artifact_path)
        assert self_heal_note.payload["final_status"] == "failed"
        assert self_heal_note.payload["self_heal_attempts"] == 2
        assert self_heal_note.payload["self_heal_passed"] is False
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_browser_generation_stage_writes_validation_failure_warning_note(
    tmp_path: Path,
    monkeypatch,
):
    _ensure_tables()
    run_id = "spec-generation-generator-validation-warning-note"
    _cleanup_run(run_id)
    _create_agent_run(run_id)
    ctx = _make_context(tmp_path, run_id)
    pipeline = _make_pipeline(run_id, _GeneratorSuccess())
    _patch_stage_side_effects(monkeypatch)
    monkeypatch.setattr(
        pipeline,
        "_validate_generated_test_file",
        lambda **_kwargs: "Generated test file contains markdown fences or narrative output",
    )

    async def no_repair(**_kwargs):
        return {
            "generation_repair_attempted": True,
            "generation_repair_accepted": False,
        }

    pipeline._attempt_generation_format_repair = no_repair

    try:
        result = await pipeline._run_browser_generation_stage(
            ctx,
            plan_path=None,
            planner_draft_script_path=None,
        )

        assert isinstance(result, _BrowserGenerationStageResult)
        assert result.result is not None
        assert result.result["success"] is False
        assert result.result["stage"] == "generation_validation"
        notes = list_agent_run_notes(run_id=run_id)
        assert [note.title for note in notes] == [
            "Generator started",
            "Generator artifact produced",
            "Generator output failed validation",
        ]
        assert notes[-1].level == "warning"
        assert notes[-1].payload["failure_category"] == "generation_validation"
        assert "markdown fences" in notes[-1].payload["message"]
        manifest = load_manifest(ctx.handoff_manifest_path)
        generator_attempts = [
            attempt
            for attempt in manifest["attempt_history"]
            if attempt["stage"] == "generator"
        ]
        assert [attempt["status"] for attempt in generator_attempts] == [
            "produced",
            "failed",
        ]
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_browser_generation_stage_accepts_repaired_output_without_failure_note(
    tmp_path: Path,
    monkeypatch,
):
    _ensure_tables()
    run_id = "spec-generation-generator-repair-accepted-note"
    _cleanup_run(run_id)
    _create_agent_run(run_id)
    ctx = _make_context(tmp_path, run_id)
    pipeline = _make_pipeline(run_id, _GeneratorSuccess())
    _patch_stage_side_effects(monkeypatch)
    validation_results = iter(
        [
            "Generated test file contains markdown fences or narrative output",
            None,
        ]
    )
    monkeypatch.setattr(
        pipeline,
        "_validate_generated_test_file",
        lambda **_kwargs: next(validation_results),
    )

    async def accept_repair(**kwargs):
        artifact_path = kwargs["run_dir"] / "generation_repair.json"
        artifact_path.write_text("{}")
        return {
            "generation_repair_attempted": True,
            "generation_repair_accepted": True,
            "generation_repair_artifact_path": str(artifact_path),
        }

    pipeline._attempt_generation_format_repair = accept_repair

    try:
        result = await pipeline._run_browser_generation_stage(
            ctx,
            plan_path=None,
            planner_draft_script_path=None,
        )

        assert isinstance(result, _BrowserGenerationStageResult)
        assert result.result is None
        notes = list_agent_run_notes(run_id=run_id)
        assert [note.title for note in notes] == [
            "Generator started",
            "Generator artifact produced",
            "Generator output accepted",
        ]
        assert "Generator output failed validation" not in [note.title for note in notes]
        assert notes[-1].payload["generation_repair_accepted"] is True
        manifest = load_manifest(ctx.handoff_manifest_path)
        generator_attempts = [
            attempt
            for attempt in manifest["attempt_history"]
            if attempt["stage"] == "generator"
        ]
        assert [attempt["status"] for attempt in generator_attempts] == [
            "produced",
            "passed",
        ]
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_browser_generation_stage_marks_self_run_result_pre_repair(
    tmp_path: Path,
    monkeypatch,
):
    _ensure_tables()
    run_id = "spec-generation-generator-self-run-pre-repair-note"
    _cleanup_run(run_id)
    _create_agent_run(run_id)
    ctx = _make_context(tmp_path, run_id)
    pipeline = _make_pipeline(run_id, _GeneratorSelfRun(final_status="passed"))
    _patch_stage_side_effects(monkeypatch)
    validation_results = iter(
        [
            "Generated test file contains markdown fences or narrative output",
            None,
        ]
    )
    monkeypatch.setattr(
        pipeline,
        "_validate_generated_test_file",
        lambda **_kwargs: next(validation_results),
    )

    async def accept_changed_repair(**kwargs):
        test_path = kwargs["test_path"]
        before = test_path.read_text()
        after = (
            "import { test, expect } from '@playwright/test';\n"
            "test('generated repaired', async ({ page }) => { "
            "await expect(page).toHaveURL(/.*/); });\n"
        )
        test_path.write_text(after)
        artifact_path = kwargs["run_dir"] / "generation_repair.json"
        artifact_path.write_text("{}")
        return {
            "generation_repair_attempted": True,
            "generation_repair_accepted": True,
            "generation_repair_artifact_path": str(artifact_path),
            "generated_file_hash_before_repair": pipeline._full_content_hash(before),
            "repaired_file_hash": pipeline._full_content_hash(after),
        }

    pipeline._attempt_generation_format_repair = accept_changed_repair

    try:
        result = await pipeline._run_browser_generation_stage(
            ctx,
            plan_path=None,
            planner_draft_script_path=None,
        )

        assert isinstance(result, _BrowserGenerationStageResult)
        assert result.result is None
        notes = list_agent_run_notes(run_id=run_id)
        assert [note.title for note in notes] == [
            "Generator started",
            "Generator artifact produced",
            "Generator self-run passed before repair",
            "Generator output accepted",
        ]
        self_run_note = notes[2]
        assert self_run_note.payload["self_run_pre_repair"] is True
        assert self_run_note.payload["repair_changed_after_self_run"] is True
    finally:
        _cleanup_run(run_id)
