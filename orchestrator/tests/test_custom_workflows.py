import copy
import os
import sys
import types
import uuid
from datetime import datetime, timezone

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-workflow-tests")

if "slowapi" not in sys.modules:
    slowapi = types.ModuleType("slowapi")
    slowapi_errors = types.ModuleType("slowapi.errors")
    slowapi_util = types.ModuleType("slowapi.util")

    class _TestLimiter:
        def __init__(self, *args, **kwargs):
            self._storage = types.SimpleNamespace(expirations={})

    class _TestRateLimitExceeded(Exception):
        retry_after = 60

    slowapi.Limiter = _TestLimiter
    slowapi_errors.RateLimitExceeded = _TestRateLimitExceeded
    slowapi_util.get_remote_address = lambda request: "test-client"
    sys.modules["slowapi"] = slowapi
    sys.modules["slowapi.errors"] = slowapi_errors
    sys.modules["slowapi.util"] = slowapi_util

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, select

from orchestrator.api.db import _has_empty_alembic_version, _required_workflow_schema_present, engine
from orchestrator.api.workflows import RUNS_DIR, _launch_run_durably, _workflow_debug_payload, get_workflow_temporal_health
from orchestrator.api.models_db import (
    AgentRun,
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowNotification,
    WorkflowRun,
    WorkflowRunStep,
    WorkflowSchedule,
    WorkflowScheduleExecution,
)
from orchestrator.services import custom_workflow_activities, custom_workflow_worker
from orchestrator.api.time_utils import utc_iso
from orchestrator.services.scheduler import execute_workflow_schedule
from orchestrator.services.temporal_client import TemporalUnavailableError, TemporalWorkflowStart, _parse_activity_history, _parse_workflow_history
from orchestrator.services.workflow_operations import (
    create_workflow_revision,
    emit_workflow_event,
    query_workflow_events,
    workflow_event_to_dict,
    workflow_revision_diff,
)
from orchestrator.services.workflow_runner import (
    WorkflowCancelled,
    WorkflowPaused,
    _dispatch_step,
    _execute_step,
    _raise_if_run_controlled,
    create_workflow_run_steps,
    duplicate_workflow_definition_record,
    handle_workflow_step_failure,
    prepare_next_workflow_step,
    reset_workflow_run_for_step_retry,
    run_workflow,
    validate_workflow_definition_payload,
    validate_workflow_steps,
    workflow_step_catalog,
)
from orchestrator.services.workflow_step_registry import WORKFLOW_TEMPLATES, sync_builtin_workflow_step_types


def _ensure_tables() -> None:
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        inspector = inspect(conn)
        if "workflow_definitions" in inspector.get_table_names():
            cols = {column["name"] for column in inspector.get_columns("workflow_definitions")}
            if "version" not in cols:
                conn.execute(text("ALTER TABLE workflow_definitions ADD COLUMN version INTEGER NOT NULL DEFAULT 1"))
            if "created_by" not in cols:
                conn.execute(text("ALTER TABLE workflow_definitions ADD COLUMN created_by VARCHAR"))
        if "workflow_run_steps" in inspector.get_table_names():
            cols = {column["name"] for column in inspector.get_columns("workflow_run_steps")}
            if "step_type_version" not in cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN step_type_version INTEGER NOT NULL DEFAULT 1"))
            if "step_config_json" not in cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN step_config_json TEXT NOT NULL DEFAULT '{}'"))
            if "rendered_input_json" not in cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN rendered_input_json TEXT NOT NULL DEFAULT '{}'"))
            if "context_snapshot_json" not in cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN context_snapshot_json TEXT NOT NULL DEFAULT '{}'"))
            if "input_resolution_json" not in cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN input_resolution_json TEXT NOT NULL DEFAULT '[]'"))
            if "output_validation_errors_json" not in cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN output_validation_errors_json TEXT NOT NULL DEFAULT '[]'"))
            if "created_at" not in cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN created_at DATETIME"))
            for column_name, column_type in {
                "attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "max_attempts": "INTEGER NOT NULL DEFAULT 1",
                "retry_backoff_seconds": "INTEGER NOT NULL DEFAULT 0",
                "recovery_action": "VARCHAR NOT NULL DEFAULT 'fail'",
                "skipped_reason": "VARCHAR",
            }.items():
                if column_name not in cols:
                    conn.execute(text(f"ALTER TABLE workflow_run_steps ADD COLUMN {column_name} {column_type}"))
        if "workflow_runs" in inspector.get_table_names():
            cols = {column["name"] for column in inspector.get_columns("workflow_runs")}
            for column_name, column_type in {
                "revision_id": "VARCHAR",
                "definition_version": "INTEGER NOT NULL DEFAULT 1",
                "recovery_policy_json": "TEXT NOT NULL DEFAULT '{}'",
                "trigger_type": "VARCHAR NOT NULL DEFAULT 'manual'",
                "trigger_id": "VARCHAR",
                "temporal_workflow_id": "VARCHAR",
                "temporal_run_id": "VARCHAR",
                "heartbeat_at": "DATETIME",
                "pause_reason": "VARCHAR",
            }.items():
                if column_name not in cols:
                    conn.execute(text(f"ALTER TABLE workflow_runs ADD COLUMN {column_name} {column_type}"))
        if "workflow_schedules" in inspector.get_table_names():
            cols = {column["name"] for column in inspector.get_columns("workflow_schedules")}
            if "revision_mode" not in cols:
                conn.execute(text("ALTER TABLE workflow_schedules ADD COLUMN revision_mode VARCHAR NOT NULL DEFAULT 'pinned'"))
        if "workflow_step_types" in inspector.get_table_names():
            cols = {column["name"] for column in inspector.get_columns("workflow_step_types")}
            if "category" not in cols:
                conn.execute(text("ALTER TABLE workflow_step_types ADD COLUMN category VARCHAR NOT NULL DEFAULT 'Utility'"))
            if "risk_level" not in cols:
                conn.execute(text("ALTER TABLE workflow_step_types ADD COLUMN risk_level VARCHAR NOT NULL DEFAULT 'low'"))
            if "is_async" not in cols:
                conn.execute(text("ALTER TABLE workflow_step_types ADD COLUMN is_async BOOLEAN NOT NULL DEFAULT 0"))
            if "auto_wait_defaults_json" not in cols:
                conn.execute(text("ALTER TABLE workflow_step_types ADD COLUMN auto_wait_defaults_json TEXT NOT NULL DEFAULT '{}'"))


def _definition_steps() -> list[dict]:
    return validate_workflow_steps(
        [
            {"key": "first", "type": "review_gate", "input": {"question": "First?"}},
            {"key": "second", "type": "review_gate", "input": {"question": "Second?"}},
            {"key": "third", "type": "review_gate", "input": {"question": "Third?"}},
        ]
    )


def _create_definition(session: Session, *, name: str | None = None) -> WorkflowDefinition:
    definition = WorkflowDefinition(
        name=name or f"Workflow {uuid.uuid4()}",
        description="Test workflow",
    )
    definition.steps = _definition_steps()
    session.add(definition)
    session.commit()
    session.refresh(definition)
    return definition


def test_validate_workflow_steps_normalizes_review_gate():
    steps = validate_workflow_steps(
        [
            {
                "key": "approval",
                "type": "review_gate",
                "input": {"question": "Continue?"},
            }
        ]
    )

    assert steps == [
        {
            "key": "approval",
            "type": "review_gate",
            "label": "Review Gate",
            "input": {"question": "Continue?"},
            "continue_on_error": False,
        }
    ]


def test_validate_workflow_steps_rejects_inline_secret_values():
    with pytest.raises(ValueError, match="Do not store secrets"):
        validate_workflow_steps(
            [
                {
                    "key": "autopilot",
                    "type": "start_autopilot",
                    "input": {
                        "entry_urls": ["https://example.com"],
                        "credentials": {"password": "plaintext"},
                    },
                }
            ]
        )


def test_validate_workflow_steps_requires_supported_type_and_inputs():
    with pytest.raises(ValueError, match="Unsupported workflow step type"):
        validate_workflow_steps([{"key": "bad", "type": "unknown", "input": {}}])

    with pytest.raises(ValueError, match="missing required"):
        validate_workflow_steps([{"key": "run", "type": "run_spec", "input": {}}])


def test_workflow_step_catalog_exposes_dynamic_ui_metadata():
    _ensure_tables()
    with Session(engine) as session:
        sync_builtin_workflow_step_types(session)
        catalog = workflow_step_catalog(session)

    custom_agent = next(item for item in catalog if item["type"] == "start_custom_agent")
    assert custom_agent["handler_kind"] == "agent_run"
    assert custom_agent["category"] == "Agent"
    assert custom_agent["risk_level"] == "high"
    assert custom_agent["is_async"] is True
    assert custom_agent["auto_wait_defaults"]["timeout_seconds"] == 3600
    assert custom_agent["default_input"]["prompt"]
    assert "findings" in custom_agent["output_schema"]["tokens"]
    assert any(field["control"] == "agent_definition" for field in custom_agent["ui_schema"]["fields"])
    assert "token_catalog" in custom_agent["output_schema"]
    assert any(token["path"] == "structured_report.findings" for token in custom_agent["output_schema"]["token_catalog"])

    generate_requirements = next(item for item in catalog if item["type"] == "generate_requirements")
    assert generate_requirements["default_input"]["exploration_session_id"] == ""
    assert generate_requirements["ui_schema"]["recommended_next_steps"][0]["type"] == "review_gate"

    start_exploration = next(item for item in catalog if item["type"] == "start_exploration")
    assert start_exploration["ui_schema"]["recommended_next_steps"][0]["type"] == "generate_requirements"

    wait_for_status = next(item for item in catalog if item["type"] == "wait_for_status")
    assert wait_for_status["default_input"]["source_step"] == ""


def test_workflow_templates_cover_common_review_paths():
    templates = {template["id"]: template for template in WORKFLOW_TEMPLATES}

    assert "explore-requirements-review" in templates
    assert "custom-agent-review" in templates
    assert "regression-review" in templates

    assert [step["type"] for step in templates["explore-requirements-review"]["steps"]] == [
        "start_exploration",
        "wait_for_status",
        "generate_requirements",
        "wait_for_status",
        "review_gate",
    ]
    assert [step["type"] for step in templates["custom-agent-review"]["steps"]] == [
        "start_custom_agent",
        "wait_for_status",
        "review_gate",
    ]
    assert [step["type"] for step in templates["regression-review"]["steps"]] == [
        "run_regression_batch",
        "wait_for_status",
        "review_gate",
    ]

    for template in templates.values():
        assert template["step_types"] == [step["type"] for step in template["steps"]]
        assert template["sort_order"] > 0
        steps = copy.deepcopy(template["steps"])
        for step in steps:
            if step["type"] == "start_custom_agent":
                step["input"]["definition_id"] = "agent-1"
        validate_workflow_steps(steps)


def test_validate_workflow_definition_payload_returns_structured_errors():
    result = validate_workflow_definition_payload(
        name="Broken workflow",
        steps=[
            {"key": "wait_first", "type": "wait_for_status", "input": {"source_step": "agent"}},
            {"key": "agent", "type": "start_custom_agent", "input": {"definition_id": "", "prompt": "Inspect"}},
        ],
    )

    assert result["valid"] is False
    assert "0" in result["step_errors"]
    assert any(error["code"] in {"wait_source", "reference"} for error in result["step_errors"]["0"])
    assert any(error["field"] == "definition_id" for error in result["step_errors"]["1"])
    assert any(
        error["message"] == "Choose an agent before creating this workflow."
        for error in result["step_errors"]["1"]
    )


def test_validate_workflow_definition_payload_returns_actionable_dependency_errors():
    result = validate_workflow_definition_payload(
        name="Broken dependency workflow",
        steps=[
            {"key": "requirements", "type": "generate_requirements", "input": {"exploration_session_id": ""}},
            {"key": "wait_requirements", "type": "wait_for_status", "input": {"source_step": ""}},
        ],
    )

    assert result["valid"] is False
    assert any(
        error["message"] == "Add Start Exploration before Generate Requirements, then insert its External ID token."
        for error in result["step_errors"]["0"]
    )
    assert any(
        error["message"] == "Choose the earlier step this wait should monitor."
        for error in result["step_errors"]["1"]
    )


def test_validate_workflow_steps_uses_registry_schema_validation():
    with pytest.raises(ValueError, match="input invalid"):
        validate_workflow_steps(
            [
                {
                    "key": "autopilot",
                    "type": "start_autopilot",
                    "input": {"entry_urls": "https://example.com"},
                }
            ]
        )


def test_validate_workflow_steps_accepts_custom_agent_extras():
    steps = validate_workflow_steps(
        [
            {
                "key": "agent",
                "type": "start_custom_agent",
                "input": {
                    "definition_id": "agent-1",
                    "prompt": "Inspect the page.",
                    "url": "https://example.com",
                    "config": {"focus_areas": ["navigation"]},
                },
            }
        ]
    )

    assert steps[0]["input"]["config"] == {"focus_areas": ["navigation"]}


def test_validate_workflow_steps_rejects_broken_token_references():
    with pytest.raises(ValueError, match="unknown or later step"):
        validate_workflow_steps(
            [
                {"key": "review", "type": "review_gate", "input": {"question": "{{steps.agent.summary}}"}},
                {"key": "agent", "type": "start_custom_agent", "input": {"definition_id": "agent-1", "prompt": "Inspect"}},
            ]
        )

    with pytest.raises(ValueError, match="unsupported output token"):
        validate_workflow_steps(
            [
                {"key": "agent", "type": "start_custom_agent", "input": {"definition_id": "agent-1", "prompt": "Inspect"}},
                {"key": "review", "type": "review_gate", "input": {"question": "{{steps.agent.not_a_token}}"}},
            ]
        )


def test_validate_workflow_steps_accepts_declared_nested_token_references():
    steps = validate_workflow_steps(
        [
            {"key": "agent", "type": "start_custom_agent", "input": {"definition_id": "agent-1", "prompt": "Inspect"}},
            {"key": "review", "type": "review_gate", "input": {"question": "{{steps.agent.structured_report.findings}}"}},
        ]
    )

    assert steps[1]["input"]["question"] == "{{steps.agent.structured_report.findings}}"


@pytest.mark.asyncio
async def test_dispatch_custom_agent_step_uses_agent_handler(monkeypatch):
    calls: list[tuple[str, dict, str | None]] = []

    async def fake_post_json(path: str, body: dict, *, expected_kind: str | None = None):
        calls.append((path, body, expected_kind))
        return {"status": "queued", "run_id": "agent-run-1", "external_kind": "agent_run", "external_id": "agent-run-1"}

    monkeypatch.setattr("orchestrator.services.workflow_runner._post_json", fake_post_json)

    result = await _dispatch_step(
        "start_custom_agent",
        {"definition_id": "agent-def-1", "prompt": "Inspect", "url": "https://example.com"},
        "project-1",
        {"steps": {}},
        {"handler_kind": "agent_run", "handler_config": {"external_kind": "agent_run"}},
    )

    assert result["external_id"] == "agent-run-1"
    assert calls == [
        (
            "/api/agents/definitions/agent-def-1/runs",
            {"prompt": "Inspect", "url": "https://example.com", "project_id": "project-1"},
            "agent_run",
        )
    ]


@pytest.mark.parametrize(
    "steps",
    [
        [
            {"key": "explore", "type": "start_exploration", "input": {"entry_url": "https://example.com", "max_interactions": 30}},
            {"key": "wait_explore", "type": "wait_for_status", "input": {"source_step": "explore", "timeout_seconds": 3600, "poll_seconds": 10}},
            {"key": "requirements", "type": "generate_requirements", "input": {"exploration_session_id": "{{steps.explore.external_id}}"}},
            {"key": "wait_requirements", "type": "wait_for_status", "input": {"source_step": "requirements", "timeout_seconds": 1800, "poll_seconds": 10}},
            {"key": "review", "type": "review_gate", "input": {"question": "Review requirements?", "suggested_answers": ["Continue"]}},
        ],
        [
            {"key": "bulk_specs", "type": "generate_specs_from_requirements", "input": {"target_url": "https://example.com"}},
            {"key": "wait_specs", "type": "wait_for_status", "input": {"source_step": "bulk_specs", "timeout_seconds": 3600, "poll_seconds": 10}},
            {"key": "review", "type": "review_gate", "input": {"question": "Review generated specs?"}},
        ],
        [
            {"key": "spec_run", "type": "run_spec", "input": {"spec_name": "examples/hello-world.md"}},
            {"key": "wait_spec_run", "type": "wait_for_status", "input": {"source_step": "spec_run", "timeout_seconds": 1800, "poll_seconds": 10}},
            {"key": "review", "type": "review_gate", "input": {"question": "Review spec run?"}},
        ],
        [
            {"key": "regression", "type": "run_regression_batch", "input": {"browser": "chromium", "automated_only": True}},
            {"key": "wait_regression", "type": "wait_for_status", "input": {"source_step": "regression", "timeout_seconds": 7200, "poll_seconds": 15}},
            {"key": "review", "type": "review_gate", "input": {"question": "Review regression?"}},
        ],
    ],
)
def test_validate_workflow_steps_accepts_qa_template_shapes(steps):
    normalized = validate_workflow_steps(steps)

    assert [step["key"] for step in normalized] == [step["key"] for step in steps]
    assert all("label" in step for step in normalized)


def test_create_workflow_run_steps_can_start_from_specific_step():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="queued")
        session.add(run)
        session.commit()
        session.refresh(run)

        start_index = create_workflow_run_steps(session, definition, run, start_step_key="second")

        steps = session.exec(
            select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id).order_by(WorkflowRunStep.step_order)
        ).all()
        session.refresh(run)

    assert start_index == 1
    assert [step.status for step in steps] == ["skipped", "pending", "pending"]
    assert steps[0].step_type_version == 1
    assert steps[0].step_config["handler_kind"] == "review_gate"
    assert steps[0].step_config["category"] == "Review"
    assert steps[0].step_config["risk_level"] == "low"
    assert run.current_step_index == 1
    assert run.progress == pytest.approx(1 / 3)


@pytest.mark.asyncio
async def test_execute_step_persists_rendered_input_and_context_snapshot():
    _ensure_tables()
    with Session(engine) as session:
        definition = WorkflowDefinition(
            name=f"Rendered Context {uuid.uuid4()}",
            description="Test rendered input snapshots",
        )
        definition.steps = validate_workflow_steps(
            [
                {"key": "first", "type": "review_gate", "input": {"question": "First?"}},
                {"key": "second", "type": "review_gate", "input": {"question": "{{steps.first.summary}}"}},
            ]
        )
        session.add(definition)
        session.commit()
        session.refresh(definition)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="queued")
        session.add(run)
        session.commit()
        session.refresh(run)
        create_workflow_run_steps(session, definition, run)
        steps = session.exec(
            select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id).order_by(WorkflowRunStep.step_order)
        ).all()
        steps[0].status = "completed"
        steps[0].output = {"status": "completed", "summary": "First summary"}
        run.context = {"steps": {"first": steps[0].output or {}}}
        session.add(steps[0])
        session.add(run)
        session.commit()
        run_id = run.id
        step_id = steps[1].id

    await _execute_step(run_id, step_id)

    with Session(engine) as session:
        step = session.get(WorkflowRunStep, step_id)

    assert step.rendered_input == {"question": "First summary"}
    assert step.context_snapshot["steps"]["first"]["summary"] == "First summary"
    assert step.input_resolution[0]["reference"] == "steps.first.summary"
    assert step.output["contract_version"] == 1


@pytest.mark.asyncio
async def test_workflow_debug_payload_aggregates_findings_artifacts_and_health():
    _ensure_tables()
    agent_id = f"agent-{uuid.uuid4()}"
    artifact_dir = RUNS_DIR / agent_id
    artifact_file = artifact_dir / "live-step-001.png"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_file.write_bytes(b"fake-png")
    try:
        with Session(engine) as session:
            agent_run = AgentRun(
                id=agent_id,
                agent_type="custom",
                status="running",
                agent_task_id="task-1",
            )
            agent_run.progress = {
                "phase": "tool_use",
                "message": "Using browser click",
                "last_tool": "mcp__playwright__browser_click",
                "last_tool_label": "browser click",
                "tool_calls": 4,
                "browser_tool_calls": 2,
                "interactions": 2,
                "has_browser_tools": True,
                "recent_tools": [
                    {"name": "mcp__playwright__browser_navigate", "label": "browser navigate", "at": utc_iso(datetime.utcnow())},
                    {"name": "mcp__playwright__browser_click", "label": "browser click", "at": utc_iso(datetime.utcnow())},
                ],
            }
            session.add(agent_run)
            definition = WorkflowDefinition(
                name=f"Debug Payload {uuid.uuid4()}",
                description="Debug payload aggregation",
            )
            definition.steps = validate_workflow_steps(
                [
                    {"key": "run_tests", "type": "review_gate", "input": {"question": "Run tests?"}},
                ]
            )
            session.add(definition)
            session.commit()
            session.refresh(definition)

            run = WorkflowRun(
                definition_id=definition.id,
                project_id=definition.project_id,
                status="completed",
                progress=1.0,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
            )
            session.add(run)
            session.commit()
            session.refresh(run)

            step = WorkflowRunStep(
                run_id=run.id,
                definition_id=definition.id,
                step_order=0,
                step_key="run_tests",
                step_type="review_gate",
                label="Run Tests",
                status="completed",
                started_at=run.started_at,
                completed_at=run.completed_at,
                external_kind="agent_run",
                external_id=agent_id,
            )
            step.output = {
                "status": "completed",
                "summary": "Generated test evidence",
                "findings": [
                    {
                        "severity": "high",
                        "title": "Checkout test failed",
                        "description": "Expected success but received a validation error.",
                        "recommendation": "Inspect checkout validation rules.",
                    }
                ],
                "artifacts": [{"name": "trace.zip", "path": "/artifacts/run/trace.zip"}],
            }
            session.add(step)
            emit_workflow_event(
                session,
                event_type="workflow.completed",
                message="Workflow completed",
                severity="info",
                run=run,
            )
            session.commit()
            payload = await _workflow_debug_payload(run, session, include_temporal=False)
    finally:
        artifact_file.unlink(missing_ok=True)
        try:
            artifact_dir.rmdir()
        except OSError:
            pass

    assert payload["health"]["finding_count"] == 1
    assert payload["health"]["artifact_count"] == 2
    assert payload["health"]["finding_counts"]["high"] == 1
    assert payload["findings"][0]["title"] == "Checkout test failed"
    assert payload["artifacts"][0]["name"] == "trace.zip"
    assert payload["external_children"][0]["kind"] == "agent_run"
    assert payload["external_children"][0]["id"] == agent_id
    assert payload["external_children"][0]["progress"]["browser_tool_calls"] == 2
    assert payload["external_children"][0]["latest_image"]["name"] == "live-step-001.png"
    assert payload["external_children"][0]["artifacts"][0]["path"].endswith("/live-step-001.png")
    assert any(item["type"] == "step" and item["step_key"] == "run_tests" for item in payload["timeline"])


def test_create_workflow_run_steps_rejects_unknown_start_step():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="queued")
        session.add(run)
        session.commit()
        session.refresh(run)

        with pytest.raises(ValueError, match="Workflow step not found"):
            create_workflow_run_steps(session, definition, run, start_step_key="missing")


@pytest.mark.asyncio
async def test_run_workflow_continues_after_continue_on_error_step(monkeypatch):
    _ensure_tables()
    with Session(engine) as session:
        definition = WorkflowDefinition(
            name=f"Continue On Error {uuid.uuid4()}",
            description="Test continue-on-error behavior",
        )
        definition.steps = validate_workflow_steps(
            [
                {
                    "key": "allowed_failure",
                    "type": "review_gate",
                    "input": {"question": "This step fails."},
                    "continue_on_error": True,
                },
                {
                    "key": "next_step",
                    "type": "review_gate",
                    "input": {"question": "This step should still run."},
                },
            ]
        )
        session.add(definition)
        session.commit()
        session.refresh(definition)

        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="queued")
        session.add(run)
        session.commit()
        session.refresh(run)
        create_workflow_run_steps(session, definition, run)
        run_id = run.id

    async def fake_execute_step(run_id: str, step_id: int | None) -> None:
        if step_id is None:
            return
        with Session(engine) as session:
            step = session.get(WorkflowRunStep, step_id)
            if not step:
                return
            if step.step_key == "allowed_failure":
                raise RuntimeError("planned failure")
            step.status = "completed"
            step.output = {"ok": True}
            step.completed_at = datetime.utcnow()
            step.updated_at = datetime.utcnow()
            session.add(step)
            session.commit()

    monkeypatch.setattr("orchestrator.services.workflow_runner._execute_step", fake_execute_step)

    await run_workflow(run_id)

    with Session(engine) as session:
        run = session.get(WorkflowRun, run_id)
        steps = session.exec(
            select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id).order_by(WorkflowRunStep.step_order)
        ).all()

    assert run.status == "completed"
    assert [step.status for step in steps] == ["failed", "completed"]
    assert steps[0].continue_on_error is True
    assert steps[0].error_message == "planned failure"
    assert steps[1].output == {"ok": True}


def test_utc_iso_serializes_naive_datetimes_as_utc_with_timezone():
    assert utc_iso(datetime(2026, 5, 19, 23, 19, 51)) == "2026-05-19T23:19:51Z"


def test_utc_iso_converts_aware_datetimes_to_utc():
    source = datetime(2026, 5, 20, 3, 19, 51, tzinfo=timezone.utc)

    assert utc_iso(source) == "2026-05-20T03:19:51Z"


def test_reset_workflow_run_for_step_retry_preserves_prior_completed_context():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="queued")
        session.add(run)
        session.commit()
        session.refresh(run)
        create_workflow_run_steps(session, definition, run)
        steps = session.exec(
            select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id).order_by(WorkflowRunStep.step_order)
        ).all()
        steps[0].status = "completed"
        steps[0].output = {"external_kind": "review_gate", "answer": "yes"}
        steps[0].completed_at = steps[0].updated_at
        steps[1].status = "failed"
        steps[1].error_message = "boom"
        steps[1].external_kind = "review_gate"
        steps[1].external_id = "failed-external"
        run.status = "failed"
        run.error_message = "boom"
        run.result = {"stale": True}
        run.completed_at = run.updated_at
        run.context = {"steps": {"first": steps[0].output or {}, "second": {"stale": True}}}
        for step in steps:
            session.add(step)
        session.add(run)
        session.commit()

        reset_workflow_run_for_step_retry(session, run, steps[1])
        refreshed_steps = session.exec(
            select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id).order_by(WorkflowRunStep.step_order)
        ).all()
        session.refresh(run)

    assert [step.status for step in refreshed_steps] == ["completed", "pending", "pending"]
    assert refreshed_steps[1].error_message is None
    assert refreshed_steps[1].external_kind is None
    assert run.status == "queued"
    assert run.error_message is None
    assert run.result is None
    assert run.context == {"steps": {"first": {"external_kind": "review_gate", "answer": "yes"}}}


def test_reset_workflow_run_for_step_retry_rejects_non_failed_state():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="queued")
        session.add(run)
        session.commit()
        session.refresh(run)
        create_workflow_run_steps(session, definition, run)
        step = session.exec(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id)).first()

        with pytest.raises(ValueError, match="Only failed workflow runs"):
            reset_workflow_run_for_step_retry(session, run, step)


def test_duplicate_workflow_definition_record_copies_active_definition():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session, name=f"Duplicate Source {uuid.uuid4()}")
        definition_id = definition.id
        expected_name = definition.name
        expected_description = definition.description
        expected_steps = definition.steps

        clone = duplicate_workflow_definition_record(definition, created_by="user-1")
        session.add(clone)
        session.commit()
        session.refresh(clone)

    assert clone.id != definition_id
    assert clone.name == f"{expected_name} Copy"
    assert clone.description == expected_description
    assert clone.status == "active"
    assert clone.created_by == "user-1"
    assert clone.steps == expected_steps


def test_create_workflow_run_steps_uses_revision_snapshot_override():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session)
        original_steps = copy.deepcopy(definition.steps)
        definition.steps = validate_workflow_steps([
            {"key": "changed", "type": "review_gate", "input": {"question": "Changed?"}},
        ])
        session.add(definition)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="queued")
        session.add(run)
        session.commit()
        session.refresh(run)

        create_workflow_run_steps(session, definition, run, steps_override=original_steps)
        run_steps = session.exec(
            select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id).order_by(WorkflowRunStep.step_order)
        ).all()

    assert [step.step_key for step in run_steps] == ["first", "second", "third"]


def test_validate_workflow_steps_rejects_invalid_recovery_policy_action():
    with pytest.raises(ValueError, match="recovery_policy.action"):
        validate_workflow_steps(
            [
                {
                    "key": "approval",
                    "type": "review_gate",
                    "input": {"question": "Continue?"},
                    "recovery_policy": {"action": "explode"},
                }
            ]
        )


def test_run_level_recovery_policy_defaults_step_recovery():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="queued")
        run.recovery_policy = {"action": "retry", "max_attempts": 3, "retry_backoff_seconds": 4}
        session.add(run)
        session.commit()
        session.refresh(run)

        create_workflow_run_steps(session, definition, run)
        step = session.exec(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id)).first()

    assert step.recovery_action == "retry"
    assert step.max_attempts == 3
    assert step.retry_backoff_seconds == 4


def test_emit_workflow_event_respects_explicit_notification_flag():
    _ensure_tables()
    marker = str(uuid.uuid4())
    silent_body = f"Schedule completed without notification {marker}."
    notified_body = f"Schedule failed with notification {marker}."
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="failed")
        session.add(run)
        session.commit()
        session.refresh(run)

        emit_workflow_event(
            session,
            event_type="workflow.schedule_completed",
            message=silent_body,
            run=run,
            notify=False,
        )
        emit_workflow_event(
            session,
            event_type="workflow.schedule_failed",
            message=notified_body,
            run=run,
            notify=True,
        )
        session.commit()
        notifications = session.exec(
            select(WorkflowNotification).where(WorkflowNotification.body == notified_body)
        ).all()

    assert len(notifications) == 1
    assert notifications[0].title == "Workflow schedule failed"


def test_raise_if_run_controlled_marks_running_step_paused():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="queued")
        session.add(run)
        session.commit()
        session.refresh(run)
        create_workflow_run_steps(session, definition, run)
        step = session.exec(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id)).first()
        step.status = "running"
        run.status = "paused"
        session.add(step)
        session.add(run)
        session.commit()
        step_id = step.id
        run_id = run.id

    with pytest.raises(WorkflowPaused):
        _raise_if_run_controlled(run_id)

    with Session(engine) as session:
        paused_step = session.get(WorkflowRunStep, step_id)

    assert paused_step.status == "paused"


def test_raise_if_run_controlled_rejects_cancelled_run():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="cancelled")
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    with pytest.raises(WorkflowCancelled):
        _raise_if_run_controlled(run_id)


def test_active_workflow_definition_query_hides_archived_by_default():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session, name=f"Archived {uuid.uuid4()}")
        definition_id = definition.id
        definition.status = "archived"
        session.add(definition)
        session.commit()

        listed = session.exec(select(WorkflowDefinition).where(WorkflowDefinition.status == "active")).all()

    assert all(item.id != definition_id for item in listed)


def test_prepare_next_workflow_step_updates_run_projection():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="queued")
        session.add(run)
        session.commit()
        session.refresh(run)
        create_workflow_run_steps(session, definition, run)
        run_id = run.id

    prepared = prepare_next_workflow_step(run_id)

    with Session(engine) as session:
        run = session.get(WorkflowRun, run_id)
        step = session.get(WorkflowRunStep, prepared["step_id"])

    assert prepared["action"] == "execute"
    assert prepared["step_key"] == "first"
    assert run.status == "running"
    assert run.current_step_index == 0
    assert run.heartbeat_at is not None
    assert step.status == "pending"


def test_handle_workflow_step_failure_returns_retry_action_with_backoff():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="running")
        session.add(run)
        session.commit()
        session.refresh(run)
        create_workflow_run_steps(session, definition, run)
        step = session.exec(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id)).first()
        step.recovery_action = "retry"
        step.max_attempts = 3
        step.retry_backoff_seconds = 17
        step.attempt_count = 1
        session.add(step)
        session.commit()
        run_id = run.id
        step_id = step.id

    recovery = handle_workflow_step_failure(run_id, step_id, "planned failure")

    with Session(engine) as session:
        step = session.get(WorkflowRunStep, step_id)

    assert recovery == {"action": "retry", "status": "queued", "backoff_seconds": 17, "step_id": step_id}
    assert step.status == "pending"
    assert step.error_message == "planned failure"
    assert step.completed_at is None


def test_handle_workflow_step_failure_skip_merges_step_output():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="running")
        session.add(run)
        session.commit()
        session.refresh(run)
        create_workflow_run_steps(session, definition, run)
        step = session.exec(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id)).first()
        step.recovery_action = "skip"
        step.attempt_count = 1
        session.add(step)
        session.commit()
        run_id = run.id
        step_id = step.id
        step_key = step.step_key

    recovery = handle_workflow_step_failure(run_id, step_id, "skip this")

    with Session(engine) as session:
        run = session.get(WorkflowRun, run_id)
        step = session.get(WorkflowRunStep, step_id)

    assert recovery["action"] == "continue"
    assert step.status == "skipped"
    assert step.skipped_reason == "skip this"
    assert run.context["steps"][step_key] == {"skipped": True, "reason": "skip this"}


def test_query_workflow_events_filters_run_type_severity_scope_search_and_order():
    _ensure_tables()
    marker = f"workflow.test_marker.{uuid.uuid4()}"
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="queued")
        session.add(run)
        session.commit()
        session.refresh(run)
        emit_workflow_event(
            session,
            event_type=marker,
            message="First marker event",
            severity="info",
            run=run,
            notify=False,
        )
        emit_workflow_event(
            session,
            event_type=marker,
            message="Second marker event",
            severity="warning",
            run=run,
            notify=False,
        )
        schedule = WorkflowSchedule(
            definition_id=definition.id,
            project_id=definition.project_id,
            name=f"Scoped schedule {uuid.uuid4()}",
            cron_expression="0 8 * * 1-5",
            timezone="UTC",
        )
        session.add(schedule)
        session.flush()
        emit_workflow_event(
            session,
            event_type=f"{marker}.schedule",
            message="Scoped schedule marker event",
            severity="info",
            schedule=schedule,
            notify=False,
        )
        emit_workflow_event(
            session,
            event_type=f"{marker}.definition",
            message="Scoped definition marker event",
            severity="info",
            definition_id=definition.id,
            notify=False,
        )
        session.commit()

        events = query_workflow_events(
            session,
            run_id=run.id,
            event_type=marker,
            severity="warning",
            order="asc",
            limit=10,
        )
        schedule_events = query_workflow_events(
            session,
            q=marker,
            entity_scope="schedule",
            order="asc",
            limit=10,
        )
        definition_events = query_workflow_events(
            session,
            q=marker,
            entity_scope="definition",
            order="asc",
            limit=10,
        )

    event_dicts = [workflow_event_to_dict(event) for event in events]
    assert [event["message"] for event in event_dicts] == ["Second marker event"]
    assert event_dicts[0]["event_type"] == marker
    assert event_dicts[0]["severity"] == "warning"
    assert [event.message for event in schedule_events] == ["Scoped schedule marker event"]
    assert [event.message for event in definition_events] == ["Scoped definition marker event"]


def test_workflow_revision_diff_reports_step_changes():
    current_steps = validate_workflow_steps(
        [
            {"key": "first", "type": "review_gate", "label": "Review", "input": {"question": "Now?"}},
            {"key": "removed", "type": "review_gate", "input": {"question": "Remove?"}},
        ]
    )
    target_steps = validate_workflow_steps(
        [
            {"key": "added", "type": "review_gate", "input": {"question": "Add?"}},
            {"key": "first", "type": "review_gate", "label": "Review", "input": {"question": "Before?"}},
        ]
    )

    diff = workflow_revision_diff(current_steps, target_steps)

    assert diff["summary"]["added"] == 1
    assert diff["summary"]["removed"] == 1
    assert diff["summary"]["changed"] == 1
    assert diff["summary"]["reordered"] == 1
    assert diff["changed"][0]["key"] == "first"


@pytest.mark.asyncio
async def test_latest_revision_schedule_resolves_latest_without_persisting_revision(monkeypatch):
    _ensure_tables()

    async def fake_start_custom_workflow_run(run_id: str):
        return TemporalWorkflowStart(workflow_id=f"wf-{run_id}", run_id="temporal-run")

    monkeypatch.setattr("orchestrator.services.temporal_client.start_custom_workflow_run", fake_start_custom_workflow_run)

    with Session(engine) as session:
        definition = _create_definition(session)
        revision_1 = create_workflow_revision(session, definition, version=1)
        definition.steps = validate_workflow_steps(
            [{"key": "latest", "type": "review_gate", "input": {"question": "Latest?"}}]
        )
        revision_2 = create_workflow_revision(session, definition, version=2)
        schedule = WorkflowSchedule(
            definition_id=definition.id,
            project_id=definition.project_id,
            revision_id=revision_1.id,
            revision_mode="latest",
            name=f"Latest schedule {uuid.uuid4()}",
            cron_expression="0 8 * * 1-5",
            timezone="UTC",
        )
        session.add(schedule)
        session.commit()
        schedule_id = schedule.id
        revision_1_id = revision_1.id
        revision_2_id = revision_2.id

    await execute_workflow_schedule(schedule_id, trigger_type="manual")

    with Session(engine) as session:
        schedule = session.get(WorkflowSchedule, schedule_id)
        run = session.exec(select(WorkflowRun).where(WorkflowRun.trigger_id == schedule_id)).first()

    assert schedule.revision_mode == "latest"
    assert schedule.revision_id == revision_1_id
    assert run.revision_id == revision_2_id
    assert run.definition_version == 2


def test_empty_alembic_version_with_workflow_schema_is_legacy_drift():
    _ensure_tables()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
        existing = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
        conn.execute(text("DELETE FROM alembic_version"))

    try:
        assert _has_empty_alembic_version() is True
        assert _required_workflow_schema_present() is True
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM alembic_version"))
            for row in existing:
                conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:version)"), {"version": row[0]})


@pytest.mark.asyncio
async def test_workflow_temporal_health_endpoint_reports_healthy(monkeypatch):
    async def healthy():
        return {
            "available": True,
            "status": "healthy",
            "address": "temporal:7233",
            "namespace": "default",
            "task_queue": "custom-workflows",
            "error": None,
        }

    monkeypatch.setattr("orchestrator.api.workflows.check_custom_workflow_temporal_health", healthy)

    result = await get_workflow_temporal_health()

    assert result["available"] is True
    assert result["status"] == "healthy"
    assert result["task_queue"] == "custom-workflows"


@pytest.mark.asyncio
async def test_workflow_temporal_health_endpoint_reports_unavailable(monkeypatch):
    async def unavailable():
        return {
            "available": False,
            "status": "unavailable",
            "address": "temporal:7233",
            "namespace": "default",
            "task_queue": "custom-workflows",
            "error": "Temporal is unavailable",
        }

    monkeypatch.setattr("orchestrator.api.workflows.check_custom_workflow_temporal_health", unavailable)

    result = await get_workflow_temporal_health()

    assert result["available"] is False
    assert result["status"] == "unavailable"
    assert "Temporal is unavailable" in result["error"]


@pytest.mark.asyncio
async def test_launch_run_durably_requires_temporal_and_marks_run_failed(monkeypatch):
    _ensure_tables()

    async def unavailable(run_id: str):
        raise TemporalUnavailableError("Temporal is unavailable for test")

    monkeypatch.setattr("orchestrator.api.workflows.start_custom_workflow_run", unavailable)

    with Session(engine) as session:
        definition = _create_definition(session)
        revision = create_workflow_revision(session, definition, version=1)
        run = WorkflowRun(
            definition_id=definition.id,
            revision_id=revision.id,
            definition_version=revision.version,
            project_id=definition.project_id,
            status="queued",
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

        with pytest.raises(HTTPException) as exc_info:
            await _launch_run_durably(run, session=session)

        assert exc_info.value.status_code == 503
        failed = session.get(WorkflowRun, run_id)
        event = session.exec(
            select(WorkflowEvent)
            .where(WorkflowEvent.run_id == run_id)
            .where(WorkflowEvent.event_type == "workflow.temporal_start_failed")
        ).first()

    assert failed.status == "failed"
    assert "Temporal is unavailable for test" in failed.error_message
    assert event is not None


@pytest.mark.asyncio
async def test_schedule_execution_fails_when_temporal_start_fails(monkeypatch):
    _ensure_tables()

    async def unavailable(run_id: str):
        raise TemporalUnavailableError("Temporal schedule unavailable")

    monkeypatch.setattr("orchestrator.services.temporal_client.start_custom_workflow_run", unavailable)

    with Session(engine) as session:
        definition = _create_definition(session)
        revision = create_workflow_revision(session, definition, version=1)
        schedule = WorkflowSchedule(
            definition_id=definition.id,
            project_id=definition.project_id,
            revision_id=revision.id,
            revision_mode="pinned",
            name=f"Temporal required schedule {uuid.uuid4()}",
            cron_expression="0 8 * * 1-5",
            timezone="UTC",
        )
        session.add(schedule)
        session.flush()
        execution = WorkflowScheduleExecution(schedule_id=schedule.id, status="pending", trigger_type="manual")
        session.add(execution)
        session.commit()
        schedule_id = schedule.id
        execution_id = execution.id

    await execute_workflow_schedule(schedule_id, execution_id=execution_id, trigger_type="manual")

    with Session(engine) as session:
        schedule = session.get(WorkflowSchedule, schedule_id)
        execution = session.get(WorkflowScheduleExecution, execution_id)
        run = session.exec(select(WorkflowRun).where(WorkflowRun.trigger_id == schedule_id)).first()
        temporal_event = session.exec(
            select(WorkflowEvent)
            .where(WorkflowEvent.run_id == run.id)
            .where(WorkflowEvent.event_type == "workflow.temporal_start_failed")
        ).first()
        schedule_failed_event = session.exec(
            select(WorkflowEvent)
            .where(WorkflowEvent.schedule_id == schedule_id)
            .where(WorkflowEvent.event_type == "workflow.schedule_failed")
        ).first()

    assert run.status == "failed"
    assert execution.status == "failed"
    assert schedule.last_run_status == "failed"
    assert "Temporal schedule unavailable" in schedule.last_error
    assert temporal_event is not None
    assert schedule_failed_event is not None


def test_custom_workflow_worker_registers_only_step_level_temporal_activities():
    assert not hasattr(custom_workflow_activities, "execute_custom_workflow_run")
    assert "execute_custom_workflow_run" not in custom_workflow_worker.main.__code__.co_names


def test_temporal_activity_history_parser_summarizes_attempts_and_failure():
    from google.protobuf.timestamp_pb2 import Timestamp
    from temporalio.api.common.v1 import ActivityType
    from temporalio.api.enums.v1 import EventType
    from temporalio.api.failure.v1 import Failure
    from temporalio.api.history.v1 import (
        ActivityTaskFailedEventAttributes,
        ActivityTaskScheduledEventAttributes,
        ActivityTaskStartedEventAttributes,
        HistoryEvent,
    )

    def ts() -> Timestamp:
        stamp = Timestamp()
        stamp.GetCurrentTime()
        return stamp

    events = [
        HistoryEvent(
            event_id=1,
            event_time=ts(),
            event_type=EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED,
            activity_task_scheduled_event_attributes=ActivityTaskScheduledEventAttributes(
                activity_id="activity-1",
                activity_type=ActivityType(name="execute_custom_workflow_step"),
            ),
        ),
        HistoryEvent(
            event_id=2,
            event_time=ts(),
            event_type=EventType.EVENT_TYPE_ACTIVITY_TASK_STARTED,
            activity_task_started_event_attributes=ActivityTaskStartedEventAttributes(
                scheduled_event_id=1,
                attempt=2,
                last_failure=Failure(message="previous failure"),
            ),
        ),
        HistoryEvent(
            event_id=3,
            event_time=ts(),
            event_type=EventType.EVENT_TYPE_ACTIVITY_TASK_FAILED,
            activity_task_failed_event_attributes=ActivityTaskFailedEventAttributes(
                scheduled_event_id=1,
                started_event_id=2,
                failure=Failure(message="final failure"),
            ),
        ),
    ]

    activities = _parse_activity_history(events)

    assert activities == [
        {
            "activity_id": "activity-1",
            "activity_type": "execute_custom_workflow_step",
            "status": "failed",
            "scheduled_at": activities[0]["scheduled_at"],
            "started_at": activities[0]["started_at"],
            "completed_at": activities[0]["completed_at"],
            "attempt_count": 2,
            "last_failure": "final failure",
            "scheduled_event_id": 1,
            "started_event_id": 2,
            "last_event_type": "EVENT_TYPE_ACTIVITY_TASK_FAILED",
            "failure_type": None,
            "failure_message": "final failure",
            "failure_stack_trace": "",
            "timeout_type": None,
        }
    ]


def test_temporal_workflow_history_parser_reports_lifecycle_metadata():
    from google.protobuf.timestamp_pb2 import Timestamp
    from temporalio.api.enums.v1 import EventType
    from temporalio.api.history.v1 import HistoryEvent

    def ts() -> Timestamp:
        stamp = Timestamp()
        stamp.GetCurrentTime()
        return stamp

    events = [
        HistoryEvent(
            event_id=1,
            event_time=ts(),
            event_type=EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED,
        ),
        HistoryEvent(
            event_id=2,
            event_time=ts(),
            event_type=EventType.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED,
        ),
    ]

    parsed = _parse_workflow_history(events)

    assert parsed["history_event_count"] == 2
    assert parsed["workflow_started_at"]
    assert parsed["workflow_closed_at"]
    assert parsed["history_first_event_at"]
    assert parsed["history_last_event_at"]
    assert parsed["close_event_type"] == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED"
