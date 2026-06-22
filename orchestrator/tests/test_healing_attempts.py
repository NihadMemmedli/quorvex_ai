import json
import os
import sys
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, select

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-healing-attempts")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.api import db as db_module
from orchestrator.api.db import engine
from orchestrator.api.models_db import (
    AgentRun,
    AgentRunEvent,
    AgentRunEvidence,
    AgentRunNote,
    AgentRunTaskContract,
    AgentTraceSnapshot,
    AgentTraceSpan,
)
from orchestrator.services.agent_native_runs import list_agent_run_notes
from orchestrator.services.agent_run_events import list_agent_run_events
from orchestrator.services.handoff_manifest import init_manifest, record_artifact
from orchestrator.utils.agent_runner import AgentResult
from orchestrator.workflows.full_native_pipeline import FullNativePipeline, TestResult


def _bare_pipeline() -> FullNativePipeline:
    return object.__new__(FullNativePipeline)


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
        for evidence in session.exec(select(AgentRunEvidence).where(AgentRunEvidence.run_id == run_id)).all():
            session.delete(evidence)
        for note in session.exec(select(AgentRunNote).where(AgentRunNote.run_id == run_id)).all():
            session.delete(note)
        for contract in session.exec(select(AgentRunTaskContract).where(AgentRunTaskContract.run_id == run_id)).all():
            session.delete(contract)
        for span in session.exec(select(AgentTraceSpan).where(AgentTraceSpan.run_id == run_id)).all():
            session.delete(span)
        for snapshot in session.exec(select(AgentTraceSnapshot).where(AgentTraceSnapshot.run_id == run_id)).all():
            session.delete(snapshot)
        for event in session.exec(select(AgentRunEvent).where(AgentRunEvent.run_id == run_id)).all():
            session.delete(event)
        run = session.get(AgentRun, run_id)
        if run:
            session.delete(run)
        session.commit()


def _wire_observed_pipeline(pipeline: FullNativePipeline, run_id: str, healer) -> None:
    pipeline.owner_id = run_id
    pipeline.project_id = None
    pipeline.native_healer = healer
    pipeline.failure_triage_agent = type(
        "FakeTriage",
        (),
        {"condensed_context": lambda self, diagnosis: None},
    )()
    pipeline._build_structured_failure_context = lambda **kwargs: "STRUCTURED-CONTEXT"
    pipeline._publish_agentic_summary = lambda run_dir: None


def test_build_attempt_context_empty():
    assert FullNativePipeline._build_attempt_context([]) is None


def test_build_attempt_context_summarizes_attempts():
    records = [
        {
            "attempt": 1,
            "changed": True,
            "diff_stat": "+3 -1",
            "error_category": "selector",
            "passed_after": False,
            "healer_summary": "Replaced #submit with getByRole",
        }
    ]
    context = FullNativePipeline._build_attempt_context(records)

    assert "Attempt 1: changed the test file (+3 -1); still failed [selector]." in context
    assert "Most recent healer summary: Replaced #submit with getByRole" in context


@pytest.mark.asyncio
async def test_pipeline_debug_validates_planner_draft_before_handoff(
    tmp_path, monkeypatch
):
    captured: dict = {}
    draft_path = tmp_path / "plan.draft.spec.ts"
    draft_path.write_text(
        "import { test, expect } from '@playwright/test';\n"
        "test('draft', async ({ page }) => {\n"
        "  await expect(page.locator('body')).toBeVisible();\n"
        "});\n"
    )

    class FakeRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self, prompt):
            captured["prompt"] = prompt
            return AgentResult(
                success=True,
                output="planner_draft_debug_status: passed\nroot_cause: none",
            )

    monkeypatch.setattr(
        "orchestrator.workflows.full_native_pipeline.AgentRunner", FakeRunner
    )
    pipeline = _bare_pipeline()
    pipeline.on_tool_use = None
    pipeline.on_progress = None
    pipeline.on_task_enqueued = None
    pipeline.owner_type = "test_run"
    pipeline.owner_id = "run-1"
    pipeline.owner_label = "Run 1"
    pipeline.model_tier = "tool_deep"
    pipeline.test_data_env_vars = {}

    result = await pipeline._debug_validate_planner_draft_script(
        draft_path=draft_path,
        run_dir=tmp_path,
        browser="chromium",
    )

    assert result["attempted"] is True
    assert result["status"] == "passed"
    assert "test_debug" in captured["prompt"]
    assert any(tool.endswith("__test_debug") for tool in captured["allowed_tools"])
    assert captured["cwd"] == tmp_path
    assert captured["preserve_browser_on_failure"] is True


def test_build_attempt_context_warns_on_repeated_category():
    records = [
        {"attempt": 1, "changed": True, "diff_stat": "+1 -1", "error_category": "selector", "passed_after": False},
        {"attempt": 2, "changed": True, "diff_stat": "+2 -2", "error_category": "selector", "passed_after": False},
    ]
    context = FullNativePipeline._build_attempt_context(records)

    assert "Do NOT retry the same fix strategy" in context
    assert len(context) <= 1500


def test_diff_stat_counts_changed_lines():
    before = "line1\nline2\nline3"
    after = "line1\nlineX\nline3\nline4"
    assert FullNativePipeline._diff_stat(before, after) == "+2 -1"


def test_record_healing_attempt_accumulates(tmp_path):
    pipeline = _bare_pipeline()
    test_path = tmp_path / "foo.spec.ts"
    records: list[dict] = []

    pipeline._record_healing_attempt(tmp_path, test_path, records, {"attempt": 1, "passed_after": False})
    pipeline._record_healing_attempt(tmp_path, test_path, records, {"attempt": 2, "passed_after": True})

    payload = json.loads((tmp_path / "healing_attempts.json").read_text())
    assert payload["test_file"] == str(test_path)
    assert [a["attempt"] for a in payload["attempts"]] == [1, 2]


@pytest.mark.asyncio
async def test_native_healing_writes_attempt_history(tmp_path, monkeypatch):
    """Heal attempt 1 fails, attempt 2 passes; the loop must persist both
    records and pass prior-attempt context to the second heal."""
    monkeypatch.setattr(
        "orchestrator.workflows.full_native_pipeline.report_progress",
        lambda *args, **kwargs: None,
    )

    pipeline = _bare_pipeline()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    test_path = tmp_path / "foo.spec.ts"
    test_path.write_text("test('v1', async ({ page }) => {});")
    plan_path = tmp_path / "planner.md"
    plan_path.write_text("- await page.getByRole('button', { name: 'Save' }).click();")

    heal_calls: list[dict] = []
    run_results = [
        TestResult(passed=False, exit_code=1, output="boom", error_summary="locator timeout"),
        TestResult(passed=True, exit_code=0, output="ok"),
    ]

    class FakeHealer:
        last_agent_output = "I changed the locator"
        last_tool_calls = [
            {"name": "mcp__playwright-test__test_run"},
            {"name": "mcp__playwright-test__browser_snapshot"},
        ]

        async def heal_test(self, test_file, error_log, **kwargs):
            heal_calls.append({"error_log": error_log, **kwargs})
            content = f"test('v{len(heal_calls) + 1}', async ({{ page }}) => {{}});"
            Path(test_file).write_text(content)
            return content

    class FakeTriage:
        def condensed_context(self, diagnosis):
            return None

    pipeline.native_healer = FakeHealer()
    pipeline.failure_triage_agent = FakeTriage()
    pipeline._run_test = lambda *args, **kwargs: run_results.pop(0)
    pipeline._build_structured_failure_context = lambda **kwargs: "STRUCTURED-CONTEXT"

    async def _no_stability(**kwargs):
        return None

    pipeline._verify_stability_or_harden = _no_stability
    pipeline._publish_agentic_summary = lambda run_dir: None

    initial_result = TestResult(passed=False, exit_code=1, output="boom", error_summary="locator timeout")
    outcome = await pipeline._native_healing(
        test_path,
        run_dir,
        "chromium",
        initial_result,
        plan_path=plan_path,
    )

    assert outcome["success"] is True
    assert outcome["attempts"] == 2

    payload = json.loads((run_dir / "healing_attempts.json").read_text())
    attempts = payload["attempts"]
    assert len(attempts) == 2
    assert attempts[0]["passed_after"] is False
    assert attempts[0]["changed"] is True
    assert attempts[1]["passed_after"] is True
    assert attempts[1]["error_category"] == "passed"

    # First heal has no prior context; second heal sees attempt 1 and the delta-framed error log
    assert heal_calls[0]["attempt_context"] is None
    assert heal_calls[0]["attempt_number"] == 1
    assert heal_calls[0]["error_log"].startswith("## Planner-Verified Selectors")
    assert "getByRole('button', { name: 'Save' })" in heal_calls[0]["error_log"]
    assert "Attempt 1" in heal_calls[1]["attempt_context"]
    assert heal_calls[1]["attempt_number"] == 2
    assert heal_calls[1]["error_log"].startswith("## Failure After Previous Heal Attempt")


@pytest.mark.asyncio
async def test_native_healing_persists_runtime_notes_and_tool_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "orchestrator.workflows.full_native_pipeline.report_progress",
        lambda *args, **kwargs: None,
    )
    _ensure_tables()
    run_id = "native-healer-observability"
    _cleanup_run(run_id)
    _create_agent_run(run_id)

    try:
        pipeline = _bare_pipeline()
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        test_path = tmp_path / "foo.spec.ts"
        test_path.write_text(
            "import { test, expect } from '@playwright/test';\n"
            "test('x', async ({ page }) => { await expect(page.locator('#old')).toBeVisible(); });\n"
        )

        class FakeHealer:
            last_agent_output = "strategy: replace selector\nroot_cause: selector changed"
            last_tool_calls = [
                {
                    "name": "mcp__playwright-test__test_debug",
                    "input": {"file": str(test_path), "project": "chromium", "grep": "x"},
                    "success": True,
                },
                {"name": "mcp__playwright-test__browser_snapshot", "success": True},
            ]

            async def heal_test(self, test_file, error_log, **kwargs):
                content = Path(test_file).read_text().replace("#old", "#new")
                Path(test_file).write_text(content)
                return content

        _wire_observed_pipeline(pipeline, run_id, FakeHealer())
        pipeline._run_test = lambda *args, **kwargs: TestResult(passed=True, exit_code=0, output="ok")

        async def _no_stability(**kwargs):
            return None

        pipeline._verify_stability_or_harden = _no_stability

        outcome = await pipeline._native_healing(
            test_path,
            run_dir,
            "chromium",
            TestResult(passed=False, exit_code=1, output="boom", error_summary="locator timeout"),
        )

        assert outcome["success"] is True
        notes = list_agent_run_notes(run_id=run_id)
        note_titles = [note.title for note in notes]
        assert "Healer handoff ready" in note_titles
        assert "Healer attempt 1 started" in note_titles
        assert "Failure-state evidence captured" in note_titles
        assert "Healer edit accepted for verification" in note_titles
        assert "Healer verification passed on attempt 1" in note_titles
        passed_note = next(note for note in notes if note.title == "Healer verification passed on attempt 1")
        assert passed_note.source == "runtime"
        assert passed_note.tags == ["healer", "native"]
        assert passed_note.payload["attempt"] == 1
        assert passed_note.payload["browser"] == "chromium"
        assert passed_note.payload["test_file"] == str(test_path)
        assert passed_note.payload["tool_summary"]["count"] == 2
        assert passed_note.payload["guardrail_status"] == "passed"

        agent_note_events = list_agent_run_events(run_id=run_id, event_type="agent_note")
        assert len(agent_note_events) >= 5
        generic_tool_events = list_agent_run_events(run_id=run_id, event_type="tool_call")
        browser_events = list_agent_run_events(run_id=run_id, event_type="browser_action")
        assert any(event.payload["tool"] == "test_debug" for event in generic_tool_events)
        assert any(event.payload["tool"] == "browser_snapshot" for event in browser_events)

        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            assert run is not None
            assert run.progress["live_notes_tail"][-1]["title"] == "Healer verification passed on attempt 1"
            spans = session.exec(select(AgentTraceSpan).where(AgentTraceSpan.run_id == run_id)).all()
            assert any(span.span_type == "tool_call" and span.tool_name == "mcp__playwright-test__test_debug" for span in spans)
            assert any(span.span_type == "tool_result" and span.tool_name == "mcp__playwright-test__browser_snapshot" for span in spans)
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_native_healing_persists_guardrail_warning_note(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "orchestrator.workflows.full_native_pipeline.report_progress",
        lambda *args, **kwargs: None,
    )
    _ensure_tables()
    run_id = "native-healer-guardrail-note"
    _cleanup_run(run_id)
    _create_agent_run(run_id)

    try:
        pipeline = _bare_pipeline()
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        test_path = tmp_path / "foo.spec.ts"
        original = (
            "import { test, expect } from '@playwright/test';\n"
            "test('x', async ({ page }) => { await expect(page.locator('#old')).toBeVisible(); });\n"
        )
        test_path.write_text(original)

        class FakeHealer:
            last_agent_output = "strategy: guessed selector\nroot_cause: selector changed"
            last_tool_calls = [
                {"name": "mcp__playwright-test__test_debug", "success": True},
            ]

            async def heal_test(self, test_file, error_log, **kwargs):
                content = Path(test_file).read_text().replace("#old", "#new")
                Path(test_file).write_text(content)
                return content

        _wire_observed_pipeline(pipeline, run_id, FakeHealer())
        pipeline._run_test = lambda *args, **kwargs: TestResult(passed=False, exit_code=1, output="still failing")

        async def _no_stability(**kwargs):
            return None

        pipeline._verify_stability_or_harden = _no_stability

        outcome = await pipeline._native_healing(
            test_path,
            run_dir,
            "chromium",
            TestResult(passed=False, exit_code=1, output="boom", error_summary="locator timeout"),
        )

        assert outcome["success"] is False
        assert test_path.read_text() == original
        notes = list_agent_run_notes(run_id=run_id)
        guardrail_notes = [note for note in notes if note.title == "Healer edit rejected by guardrail"]
        assert guardrail_notes
        assert guardrail_notes[0].level == "warning"
        assert "browser_snapshot_or_browser_generate_locator" in guardrail_notes[0].payload["missing_required_tools"]
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_native_healing_includes_manifest_draft_context(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "orchestrator.workflows.full_native_pipeline.report_progress",
        lambda *args, **kwargs: None,
    )
    pipeline = _bare_pipeline()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    manifest_path = init_manifest(run_dir)
    test_path = tmp_path / "foo.spec.ts"
    test_path.write_text("test('v1', async ({ page }) => {});")
    draft_path = run_dir / "plan.draft.spec.ts"
    draft_path.write_text(
        "import { test, expect } from '@playwright/test';\n"
        "test('draft', async ({ page }) => {\n"
        "  await expect(page.getByRole('button', { name: 'Save' })).toBeVisible();\n"
        "});\n"
    )
    record_artifact(
        manifest_path,
        "planner_draft_script",
        draft_path,
        kind="planner_draft_playwright",
        producer_stage="planner",
    )

    heal_calls: list[dict] = []

    class FakeHealer:
        last_agent_output = "strategy: use draft selector"
        last_tool_calls = [
            {"name": "mcp__playwright-test__test_run"},
            {"name": "mcp__playwright-test__browser_snapshot"},
        ]

        async def heal_test(self, test_file, error_log, **kwargs):
            heal_calls.append({"error_log": error_log, **kwargs})
            content = "test('v2', async ({ page }) => {});"
            Path(test_file).write_text(content)
            return content

    class FakeTriage:
        def condensed_context(self, diagnosis):
            return None

    pipeline.native_healer = FakeHealer()
    pipeline.failure_triage_agent = FakeTriage()
    pipeline._run_test = lambda *args, **kwargs: TestResult(passed=True, exit_code=0, output="ok")
    pipeline._build_structured_failure_context = lambda **kwargs: "STRUCTURED-CONTEXT"
    pipeline._verify_stability_or_harden = lambda **kwargs: None
    pipeline._publish_agentic_summary = lambda run_dir: None
    async def _no_stability(**kwargs):
        return None
    pipeline._verify_stability_or_harden = _no_stability

    outcome = await pipeline._native_healing(
        test_path,
        run_dir,
        "chromium",
        TestResult(passed=False, exit_code=1, output="boom", error_summary="locator timeout"),
        handoff_manifest_path=manifest_path,
    )

    assert outcome["success"] is True
    assert "## Planner Draft Script Context" in heal_calls[0]["error_log"]
    assert "getByRole('button', { name: 'Save' })" in heal_calls[0]["error_log"]


def test_selector_guardrail_requires_failure_debug_and_snapshot_or_locator():
    pipeline = _bare_pipeline()
    before = "import { test, expect } from '@playwright/test';\ntest('x', async ({ page }) => { await expect(page.locator('#old')).toBeVisible(); });"
    after = before.replace("#old", "#new")

    missing_test_run = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after=after,
        tool_calls=[{"name": "mcp__playwright-test__browser_snapshot", "tool": "browser_snapshot"}],
        error_category="selector",
    )
    assert missing_test_run["guardrail_status"] == "failed"
    assert "test_debug_or_test_run" in missing_test_run["missing_required_tools"]

    missing_snapshot = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after=after,
        tool_calls=[{"name": "mcp__playwright-test__test_debug", "tool": "test_debug"}],
        error_category="selector",
    )
    assert missing_snapshot["guardrail_status"] == "failed"
    assert "browser_snapshot_or_browser_generate_locator" in missing_snapshot["missing_required_tools"]

    ok = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after=after,
        tool_calls=[
            {"name": "mcp__playwright-test__test_debug", "tool": "test_debug"},
            {"name": "mcp__playwright-test__browser_generate_locator", "tool": "browser_generate_locator"},
        ],
        error_category="selector",
    )
    assert ok["guardrail_status"] == "passed"
    assert ok["used_failure_state_tool"] is True

    legacy_test_run_ok = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after=after,
        tool_calls=[
            {"name": "mcp__playwright-test__test_run", "tool": "test_run"},
            {"name": "mcp__playwright-test__browser_generate_locator", "tool": "browser_generate_locator"},
        ],
        error_category="selector",
    )
    assert legacy_test_run_ok["guardrail_status"] == "passed"


def test_selector_guardrail_requires_scoped_test_run_when_metadata_exists():
    pipeline = _bare_pipeline()
    before = "test('can submit form', async ({ page }) => { await expect(page.locator('#old')).toBeVisible(); });"
    after = before.replace("#old", "#new")
    metadata = {
        "file": "tests/generated/foo.spec.ts",
        "project": "chromium",
        "title": "can submit form",
    }

    unscoped = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after=after,
        tool_calls=[
            {"name": "mcp__playwright-test__test_debug", "tool": "test_debug", "input": {"file": "tests/generated/foo.spec.ts"}},
            {"name": "mcp__playwright-test__browser_snapshot", "tool": "browser_snapshot"},
        ],
        error_category="selector",
        failure_metadata=metadata,
    )
    assert unscoped["guardrail_status"] == "failed"
    assert "scoped_test_run" in unscoped["missing_required_tools"]
    assert set(unscoped["scoped_test_run"]["missing"]) == {"project", "title"}

    scoped = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after=after,
        tool_calls=[
            {
                "name": "mcp__playwright-test__test_debug",
                "tool": "test_debug",
                "input": {
                    "file": "tests/generated/foo.spec.ts",
                    "project": "chromium",
                    "grep": "can submit form",
                },
            },
            {"name": "mcp__playwright-test__browser_snapshot", "tool": "browser_snapshot"},
        ],
        error_category="selector",
        failure_metadata=metadata,
    )
    assert scoped["guardrail_status"] == "passed"


def test_scoped_guardrail_accepts_location_and_aliases_and_later_scoped_call():
    pipeline = _bare_pipeline()
    before = "test('can sort results', async ({ page }) => { await expect(page.locator('#sort')).toHaveValue('new'); });"
    after = before.replace("new", "asc")
    metadata = {
        "file": "runs/abc/tests/generated/foo.spec.ts",
        "projectName": "chromium",
        "title": "can sort results",
    }

    result = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after=after,
        tool_calls=[
            {"name": "mcp__playwright-test__test_debug", "input": {"file": "other.spec.ts"}},
            {
                "name": "mcp__playwright-test__test_run",
                "input": {
                    "locations": ["runs/abc/tests/generated/foo.spec.ts:180"],
                    "projectName": "chromium",
                    "testName": "can sort results",
                },
            },
            {"name": "mcp__playwright-test__browser_snapshot"},
        ],
        error_category="selector",
        failure_metadata=metadata,
    )

    assert result["guardrail_status"] == "passed"
    assert result["scoped_test_run"]["scoped"] is True


def test_sort_select_category_accepts_dom_evaluate_evidence():
    pipeline = _bare_pipeline()
    before = "test('sort', async ({ page }) => { await expect(page.locator('select')).toHaveValue('new'); });"
    after = "test('sort', async ({ page }) => { await page.locator('select').selectOption('asc'); await expect(page.locator('select')).toHaveValue('asc'); });"

    missing = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after=after,
        tool_calls=[{"name": "mcp__playwright-test__test_debug"}],
        error_category="sort_select",
    )
    assert "browser_snapshot_or_browser_evaluate_or_browser_generate_locator" in missing["missing_required_tools"]

    ok = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after=after,
        tool_calls=[
            {"name": "mcp__playwright-test__test_debug"},
            {"name": "mcp__playwright-test__browser_evaluate"},
        ],
        error_category="sort_select",
    )
    assert ok["guardrail_status"] == "passed"


def test_auth_data_server_guardrail_requires_network_or_console():
    pipeline = _bare_pipeline()
    before = "test('x', async ({ page }) => { await page.goto('/login'); });"
    after = "test('x', async ({ page }) => { await page.goto('/dashboard'); });"

    missing = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after=after,
        tool_calls=[{"name": "mcp__playwright-test__test_run", "tool": "test_run"}],
        error_category="auth",
    )
    assert missing["guardrail_status"] == "failed"
    assert "browser_network_requests_or_browser_console_messages" in missing["missing_required_tools"]

    ok = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after=after,
        tool_calls=[
            {"name": "mcp__playwright-test__test_run", "tool": "test_run"},
            {"name": "mcp__playwright-test__browser_network_requests", "tool": "browser_network_requests"},
        ],
        error_category="auth",
    )
    assert ok["guardrail_status"] == "passed"


def test_assertion_removal_blocks_new_fixme_without_triage_override():
    pipeline = _bare_pipeline()
    before = "test('x', async ({ page }) => { await expect(page.locator('#done')).toBeVisible(); });"
    after = "test('x', async ({ page }) => { await page.locator('#done').click(); });"
    calls = [
        {"name": "mcp__playwright-test__test_run", "tool": "test_run"},
        {"name": "mcp__playwright-test__browser_snapshot", "tool": "browser_snapshot"},
    ]

    rejected = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after=after,
        tool_calls=calls,
        error_category="selector",
    )
    assert rejected["guardrail_status"] == "failed"
    assert "assertion_preservation_or_explicit_test_fixme" in rejected["missing_required_tools"]

    fixme_blocked = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after="test.fixme('x is blocked', async () => {});",
        tool_calls=calls,
        error_category="selector",
    )
    assert "new_test_fixme_requires_non_healable_triage" in fixme_blocked["missing_required_tools"]

    fixme_allowed = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after="test.fixme('x is blocked', async () => {});",
        tool_calls=calls,
        error_category="selector",
        triage_allows_fixme=True,
    )
    assert "assertion_preservation_or_explicit_test_fixme" not in fixme_allowed["missing_required_tools"]
    assert "new_test_fixme_requires_non_healable_triage" not in fixme_allowed["missing_required_tools"]


def test_assertion_guardrail_allows_equivalent_assertion_replacement():
    pipeline = _bare_pipeline()
    before = (
        "test('x', async ({ page }) => {\n"
        "  await expect(page.locator('#done')).toBeVisible();\n"
        "  await expect(page.locator('#status')).toHaveText('Done');\n"
        "});"
    )
    after = (
        "test('x', async ({ page }) => {\n"
        "  await expect(page.locator('#done')).toBeVisible();\n"
        "});"
    )

    result = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after=after,
        tool_calls=[
            {"name": "mcp__playwright-test__test_debug"},
            {"name": "mcp__playwright-test__browser_snapshot"},
        ],
        error_category="selector",
    )

    assert "assertion_preservation_or_explicit_test_fixme" not in result["missing_required_tools"]


def test_noop_edit_is_guardrail_failure():
    pipeline = _bare_pipeline()
    content = "test('x', async ({ page }) => { await page.goto('/'); });"

    result = pipeline._evaluate_healer_guardrails(
        content_before=content,
        content_after=content,
        tool_calls=[{"name": "mcp__playwright-test__test_run", "tool": "test_run"}],
        error_category="assertion",
    )

    assert result["guardrail_status"] == "failed"
    assert "non_noop_edit" in result["missing_required_tools"]


def test_broad_rewrite_requires_stability_status():
    pipeline = _bare_pipeline()
    before = "\n".join(f"line {i}" for i in range(20))
    after = "\n".join(f"new line {i}" for i in range(120))

    result = pipeline._evaluate_healer_guardrails(
        content_before=before,
        content_after=after,
        tool_calls=[{"name": "mcp__playwright-test__test_run", "tool": "test_run"}],
        error_category="assertion",
    )

    assert result["guardrail_status"] == "requires_stability"
    assert result["broad_rewrite"] is True


def test_failure_evidence_packet_artifact_contains_tool_summary(tmp_path):
    pipeline = _bare_pipeline()
    test_path = tmp_path / "foo.spec.ts"
    test_path.write_text("test('x', async ({ page }) => { await page.goto('/'); });")
    (tmp_path / "test-results").mkdir()
    (tmp_path / "test-results" / "error-context.md").write_text("page snapshot")
    (tmp_path / "test-results.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "suites": [
                    {
                        "title": "suite",
                        "specs": [
                            {
                                "title": "x",
                                "file": str(test_path),
                                "tests": [
                                    {
                                        "projectName": "chromium",
                                        "results": [
                                            {
                                                "status": "failed",
                                                "retry": 0,
                                                "error": {"message": "locator timeout"},
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    )

    path = pipeline._write_failure_evidence_packet(
        run_dir=tmp_path,
        test_path=test_path,
        result=TestResult(passed=False, exit_code=1, output="boom", error_summary="locator timeout"),
        browser="chromium",
        attempt=1,
        failure_metadata=None,
        tool_calls=[
            {"name": "mcp__playwright-test__test_run", "tool": "test_run"},
            {"name": "mcp__playwright-test__browser_snapshot", "tool": "browser_snapshot"},
        ],
        guardrail={
            "first_tool": "test_run",
            "mcp_evidence_tools_used": ["test_run", "browser_snapshot"],
            "used_failure_state_tool": True,
            "missing_required_tools": [],
        },
    )

    assert path
    payload = json.loads(Path(path).read_text())
    assert payload["failed_test"]["title"] == "x"
    assert payload["mcp_evidence"]["first_tool"] == "test_run"
    assert (tmp_path / "failure_evidence_packet.json").exists()
