import os
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-autopilot-temporal")
os.environ.setdefault("REQUIRE_AUTH", "false")

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if "slowapi" not in sys.modules:
    slowapi_module = types.ModuleType("slowapi")
    slowapi_errors = types.ModuleType("slowapi.errors")
    slowapi_util = types.ModuleType("slowapi.util")

    class _Limiter:
        def __init__(self, *args, **kwargs):
            pass

        def limit(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    class _RateLimitExceeded(Exception):
        pass

    slowapi_module.Limiter = _Limiter
    slowapi_errors.RateLimitExceeded = _RateLimitExceeded
    slowapi_util.get_remote_address = lambda request: "test-client"
    sys.modules["slowapi"] = slowapi_module
    sys.modules["slowapi.errors"] = slowapi_errors
    sys.modules["slowapi.util"] = slowapi_util

from orchestrator.api import db as db_module
from orchestrator.api import autopilot as autopilot_api
from orchestrator.api.db import engine
from orchestrator.api.models_db import (
    AutoPilotPhase,
    AutoPilotQuestion,
    AutoPilotSession,
    AutoPilotSpecTask,
    AutoPilotTestTask,
)
from orchestrator.services.autopilot_activities import mark_autopilot_temporal_started, set_autopilot_control_status
from orchestrator.services.custom_workflow_worker import get_worker_contract
from orchestrator.services import temporal_client
from orchestrator.services.temporal_client import TemporalUnavailableError, TemporalWorkflowStart
from orchestrator.workflows.autopilot_pipeline import AutoPilotPipeline


def _ensure_tables() -> None:
    SQLModel.metadata.create_all(engine, checkfirst=True)
    db_module._run_migrations()


def _cleanup_session(session_id: str) -> None:
    with Session(engine) as session:
        for model in (AutoPilotQuestion, AutoPilotTestTask, AutoPilotSpecTask, AutoPilotPhase):
            for row in session.exec(select(model).where(model.session_id == session_id)).all():
                session.delete(row)
        ap_session = session.get(AutoPilotSession, session_id)
        if ap_session:
            session.delete(ap_session)
        session.commit()


def _create_autopilot_session(session_id: str, status: str = "pending") -> AutoPilotSession:
    _ensure_tables()
    _cleanup_session(session_id)
    with Session(engine) as session:
        ap_session = AutoPilotSession(id=session_id, project_id="default", status=status, triggered_by="test-user")
        ap_session.entry_urls = ["https://example.com"]
        ap_session.config = {"strategy": "goal_directed"}
        session.add(ap_session)
        session.commit()
        session.refresh(ap_session)
        return ap_session


def test_custom_workflow_worker_registers_autopilot_workflow_and_activities():
    contract = get_worker_contract()

    assert "AutoPilotWorkflow" in contract["workflows"]
    assert "mark_autopilot_temporal_started" in contract["activities"]
    assert "execute_autopilot_pipeline" in contract["activities"]
    assert "set_autopilot_control_status" in contract["activities"]
    assert "finalize_autopilot_workflow" in contract["activities"]


def test_autopilot_temporal_start_activity_records_workflow_metadata():
    session_id = f"autopilot-test-{uuid4().hex}"
    _create_autopilot_session(session_id)

    payload = mark_autopilot_temporal_started(
        {
            "session_id": session_id,
            "workflow_id": f"autopilot-{session_id}",
            "temporal_run_id": "temporal-run-1",
        }
    )

    assert payload["status"] == "running"
    assert payload["temporal_workflow_id"] == f"autopilot-{session_id}"
    with Session(engine) as session:
        ap_session = session.get(AutoPilotSession, session_id)
        assert ap_session is not None
        assert ap_session.temporal_workflow_id == f"autopilot-{session_id}"
        assert ap_session.temporal_run_id == "temporal-run-1"

    _cleanup_session(session_id)


def test_autopilot_temporal_control_updates_session_status():
    session_id = f"autopilot-test-{uuid4().hex}"
    _create_autopilot_session(session_id, status="running")

    paused = set_autopilot_control_status(
        {"session_id": session_id, "status": "paused", "reason": "manual_pause"}
    )

    assert paused["status"] == "paused"
    with Session(engine) as session:
        ap_session = session.get(AutoPilotSession, session_id)
        assert ap_session is not None
        assert ap_session.status == "paused"

    _cleanup_session(session_id)


@pytest.mark.asyncio
async def test_start_autopilot_temporal_helper_stores_temporal_ids(monkeypatch):
    session_id = f"autopilot-test-{uuid4().hex}"
    _create_autopilot_session(session_id)

    async def fake_start(session_id_arg: str, *, task_queue: str | None = None):
        assert session_id_arg == session_id
        assert task_queue
        return TemporalWorkflowStart(workflow_id=f"autopilot-{session_id}", run_id="run-123")

    monkeypatch.setattr("orchestrator.services.temporal_client.start_autopilot_workflow", fake_start)

    with Session(engine) as session:
        ap_session = session.get(AutoPilotSession, session_id)
        assert ap_session is not None
        await autopilot_api._start_autopilot_temporal_or_fail(ap_session, session)

    with Session(engine) as session:
        ap_session = session.get(AutoPilotSession, session_id)
        assert ap_session is not None
        assert ap_session.temporal_workflow_id == f"autopilot-{session_id}"
        assert ap_session.temporal_run_id == "run-123"

    _cleanup_session(session_id)


@pytest.mark.asyncio
async def test_start_autopilot_temporal_helper_marks_session_failed_on_temporal_error(monkeypatch):
    session_id = f"autopilot-test-{uuid4().hex}"
    _create_autopilot_session(session_id)

    async def fake_start(session_id_arg: str, *, task_queue: str | None = None):
        raise TemporalUnavailableError("temporal down")

    monkeypatch.setattr("orchestrator.services.temporal_client.start_autopilot_workflow", fake_start)

    with Session(engine) as session:
        ap_session = session.get(AutoPilotSession, session_id)
        assert ap_session is not None
        with pytest.raises(HTTPException) as exc:
            await autopilot_api._start_autopilot_temporal_or_fail(ap_session, session)

    assert exc.value.status_code == 503
    with Session(engine) as session:
        ap_session = session.get(AutoPilotSession, session_id)
        assert ap_session is not None
        assert ap_session.status == "failed"
        assert "temporal down" in (ap_session.error_message or "")
        assert ap_session.config["live_browser"]["status"] == "failed"

    _cleanup_session(session_id)


def test_autopilot_live_runtime_prefers_temporal_vnc_state():
    runtime = autopilot_api._current_autopilot_runtime(
        {
            "browser_runtime": "vnc",
            "live_view_available": True,
            "runtime_message": "Browser will run on the VNC display.",
        }
    )

    assert runtime["browser_runtime"] == "vnc"
    assert runtime["live_view_available"] is True
    assert runtime["runtime_message"] == "Browser will run on the VNC display."


def test_temporal_pending_activity_marks_scheduled_activity_started():
    activities = [
        {
            "activity_id": "2",
            "activity_type": "execute_autopilot_pipeline",
            "status": "scheduled",
            "scheduled_at": "2026-05-26T10:33:04Z",
            "started_at": None,
            "completed_at": None,
            "attempt_count": 0,
            "last_failure": None,
            "scheduled_event_id": 11,
            "started_event_id": None,
            "last_event_type": "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED",
            "failure_type": None,
            "failure_message": None,
            "failure_stack_trace": None,
            "timeout_type": None,
        }
    ]
    started_at = datetime(2026, 5, 26, 10, 33, 5)

    class _ProtoTime:
        def ToDatetime(self, tzinfo=None):
            return started_at.replace(tzinfo=tzinfo)

    description = types.SimpleNamespace(
        raw_description=types.SimpleNamespace(
            pending_activities=[
                types.SimpleNamespace(
                    activity_id="2",
                    activity_type=types.SimpleNamespace(name="execute_autopilot_pipeline"),
                    state=2,
                    last_started_time=_ProtoTime(),
                    attempt=1,
                    last_worker_identity="30@worker",
                )
            ]
        )
    )

    merged = temporal_client._merge_pending_activity_history(activities, description)

    assert merged[0]["status"] == "started"
    assert merged[0]["started_at"] == "2026-05-26T10:33:05Z"
    assert merged[0]["last_started_at"] == "2026-05-26T10:33:05Z"
    assert merged[0]["attempt_count"] == 1
    assert merged[0]["last_worker_identity"] == "30@worker"


@pytest.mark.asyncio
async def test_autopilot_temporal_payload_without_workflow_id_reports_missing_link():
    session_id = f"autopilot-test-{uuid4().hex}"
    ap_session = _create_autopilot_session(session_id)

    payload = await autopilot_api._autopilot_temporal_payload(ap_session)

    assert payload["available"] is False
    assert payload["workflow_type"] == "AutoPilotWorkflow"
    assert payload["temporal_workflow_id"] is None
    assert "No Temporal workflow id" in payload["error"]

    _cleanup_session(session_id)


@pytest.mark.asyncio
async def test_autopilot_temporal_payload_returns_workflow_diagnostics(monkeypatch):
    session_id = f"autopilot-test-{uuid4().hex}"
    _create_autopilot_session(session_id)
    from orchestrator.config import settings

    monkeypatch.setattr(settings, "temporal_ui_url", "http://localhost:8233")

    async def fake_diagnostics(workflow_id: str, run_id: str | None = None):
        assert workflow_id == f"autopilot-{session_id}"
        assert run_id == "run-456"
        return {
            "available": True,
            "workflow_status": "RUNNING",
            "task_queue": "quorvex-browser-workflows",
            "workflow_type": "AutoPilotWorkflow",
            "activities": [{"activity_type": "execute_autopilot_pipeline", "status": "started"}],
            "summary": {
                "total_activities": 1,
                "failed_activities": 0,
                "retry_count": 0,
                "last_failure": None,
                "last_workflow_task_failure": None,
            },
        }

    monkeypatch.setattr(
        "orchestrator.services.temporal_client.get_autopilot_temporal_diagnostics",
        fake_diagnostics,
    )

    with Session(engine) as session:
        ap_session = session.get(AutoPilotSession, session_id)
        assert ap_session is not None
        ap_session.temporal_workflow_id = f"autopilot-{session_id}"
        ap_session.temporal_run_id = "run-456"
        session.add(ap_session)
        session.commit()
        session.refresh(ap_session)

        payload = await autopilot_api._autopilot_temporal_payload(ap_session)

    assert payload["available"] is True
    assert payload["workflow_status"] == "RUNNING"
    assert payload["workflow_type"] == "AutoPilotWorkflow"
    assert payload["task_queue"] == "quorvex-browser-workflows"
    assert payload["temporal_ui_workflow_url"]
    assert f"/workflows/autopilot-{session_id}/run-456/history" in payload["temporal_ui_workflow_url"]
    assert payload["summary"]["total_activities"] == 1

    _cleanup_session(session_id)


@pytest.mark.asyncio
async def test_autopilot_temporal_health_uses_browser_workflow_queue(monkeypatch):
    from orchestrator.config import settings
    from orchestrator.services import temporal_client

    async def fake_connect():
        return object()

    async def fake_describe(task_queue: str):
        assert task_queue == settings.temporal_browser_workflow_task_queue
        return {
            "task_queue": task_queue,
            "workflow_pollers": 1,
            "activity_pollers": 1,
            "has_workflow_pollers": True,
            "has_activity_pollers": True,
        }

    monkeypatch.setattr(temporal_client, "_connect_client", fake_connect)
    monkeypatch.setattr(temporal_client, "describe_temporal_task_queue", fake_describe)

    health = await temporal_client.check_autopilot_temporal_health()

    assert health["available"] is True
    assert health["status"] == "healthy"
    assert health["workflow_type"] == "AutoPilotWorkflow"
    assert health["task_queue"] == settings.temporal_browser_workflow_task_queue


def test_autopilot_live_progress_tracks_browser_artifacts_as_captures():
    now = datetime.utcnow()
    live = {
        "tool_calls": 0,
        "browser_tool_calls": 0,
        "interactions": 0,
        "last_tool": None,
        "last_tool_label": None,
        "recent_tools": [],
        "updated_at": (now - timedelta(minutes=5)).isoformat(),
        "message": "Browser slot acquired",
    }
    artifacts = [
        autopilot_api.AutoPilotLiveArtifactResponse(
            name="live-step-002.png",
            path="/artifacts/autopilot/test/live-step-002.png",
            type="image",
            modified_at=now,
        ),
        autopilot_api.AutoPilotLiveArtifactResponse(
            name="live-step-001.png",
            path="/artifacts/autopilot/test/live-step-001.png",
            type="image",
            modified_at=now - timedelta(seconds=30),
        ),
    ]

    merged = autopilot_api._merge_artifact_live_progress(live, artifacts)

    assert merged["tool_calls"] == 0
    assert merged["browser_tool_calls"] == 0
    assert merged["interactions"] == 0
    assert merged["capture_count"] == 2
    assert merged["latest_capture_at"] == now.isoformat()
    assert merged["activity_source"] == "artifact_fallback"
    assert merged["last_tool"] is None
    assert merged["last_tool_label"] is None
    assert merged["recent_tools"] == []
    assert merged["updated_at"] == now.isoformat()
    assert merged["message"] == "Latest browser capture available."


def test_autopilot_live_progress_preserves_real_tool_telemetry():
    now = datetime.utcnow()
    live = {
        "tool_calls": 7,
        "browser_tool_calls": 6,
        "interactions": 5,
        "last_tool": "mcp__playwright-test__browser_click",
        "last_tool_label": "browser click",
        "recent_tools": [{"name": "mcp__playwright-test__browser_click", "at": now.isoformat()}],
        "updated_at": now.isoformat(),
        "message": "Clicking target.",
    }
    artifacts = [
        autopilot_api.AutoPilotLiveArtifactResponse(
            name="live-step-008.png",
            path="/artifacts/autopilot/test/live-step-008.png",
            type="image",
            modified_at=now - timedelta(seconds=5),
        )
    ]

    merged = autopilot_api._merge_artifact_live_progress(live, artifacts)

    assert merged["tool_calls"] == 7
    assert merged["browser_tool_calls"] == 6
    assert merged["interactions"] == 5
    assert merged["capture_count"] == 1
    assert merged["last_tool"] == "mcp__playwright-test__browser_click"
    assert merged["last_tool_label"] == "browser click"
    assert merged["message"] == "Clicking target."


def test_autopilot_pipeline_live_state_persists_real_progress():
    session_id = f"autopilot-test-{uuid4().hex}"
    _create_autopilot_session(session_id, status="running")
    pipeline = AutoPilotPipeline(session_id=session_id, project_id="default")

    pipeline._update_live_browser_state(
        {
            "active": True,
            "phase": "exploration",
            "tool_calls": 3,
            "browser_tool_calls": 2,
            "interactions": 2,
            "last_tool": "mcp__playwright-test__browser_click",
        }
    )

    with Session(engine) as session:
        ap_session = session.get(AutoPilotSession, session_id)
        assert ap_session is not None
        live = ap_session.config["live_browser"]

    assert live["tool_calls"] == 3
    assert live["browser_tool_calls"] == 2
    assert live["interactions"] == 2
    assert live["last_tool"] == "mcp__playwright-test__browser_click"
    assert live["activity_source"] == "real_tool_progress"

    _cleanup_session(session_id)


def test_autopilot_pipeline_record_tool_use_persists_recent_tool():
    session_id = f"autopilot-test-{uuid4().hex}"
    _create_autopilot_session(session_id, status="running")
    pipeline = AutoPilotPipeline(session_id=session_id, project_id="default")

    pipeline._record_live_tool_use(
        "mcp__playwright-test__browser_type",
        {
            "tool_calls": 4,
            "browser_tool_calls": 4,
            "interactions": 3,
            "message": "Using browser type",
        },
    )

    with Session(engine) as session:
        ap_session = session.get(AutoPilotSession, session_id)
        assert ap_session is not None
        live = ap_session.config["live_browser"]

    assert live["tool_calls"] == 4
    assert live["browser_tool_calls"] == 4
    assert live["interactions"] == 3
    assert live["last_tool"] == "mcp__playwright-test__browser_type"
    assert live["last_tool_label"] == "browser type"
    assert live["activity_source"] == "real_tool_progress"
    assert live["recent_tools"][-1]["name"] == "mcp__playwright-test__browser_type"

    _cleanup_session(session_id)


def test_autopilot_session_response_derives_stale_aggregate_stats():
    session_id = f"autopilot-test-{uuid4().hex}"
    _ensure_tables()
    try:
        with Session(engine) as session:
            ap_session = AutoPilotSession(
                id=session_id,
                project_id="default",
                status="completed",
                coverage_percentage=0.0,
            )
            session.add(ap_session)

            exploration = AutoPilotPhase(session_id=session_id, phase_name="exploration", phase_order=1)
            exploration.result_summary = {"pages_discovered": 4, "flows_discovered": 2}
            requirements = AutoPilotPhase(session_id=session_id, phase_name="requirements", phase_order=2)
            requirements.result_summary = {"requirements_generated": 3}
            session.add(exploration)
            session.add(requirements)

            session.add(
                AutoPilotSpecTask(
                    session_id=session_id,
                    requirement_id=1,
                    requirement_title="Login",
                    status="completed",
                    spec_name="login.md",
                )
            )
            session.add(
                AutoPilotSpecTask(
                    session_id=session_id,
                    requirement_id=2,
                    requirement_title="Checkout",
                    status="completed",
                    spec_name="checkout.md",
                )
            )
            session.add(
                AutoPilotSpecTask(
                    session_id=session_id,
                    requirement_id=2,
                    requirement_title="Checkout edge",
                    status="completed",
                    spec_name="checkout-edge.md",
                )
            )

            session.add(AutoPilotTestTask(session_id=session_id, spec_name="login.md", status="passed", passed=True))
            session.add(AutoPilotTestTask(session_id=session_id, spec_name="checkout.md", status="failed", passed=False))
            session.add(AutoPilotTestTask(session_id=session_id, spec_name="edge.md", status="error", passed=None))
            session.commit()
            session.refresh(ap_session)

            response = autopilot_api._session_to_response(ap_session, session)

        assert response.total_pages_discovered == 4
        assert response.total_flows_discovered == 2
        assert response.total_requirements_generated == 3
        assert response.total_specs_generated == 3
        assert response.total_tests_generated == 3
        assert response.total_tests_passed == 1
        assert response.total_tests_failed == 2
        assert response.coverage_percentage == 33.3
    finally:
        _cleanup_session(session_id)
