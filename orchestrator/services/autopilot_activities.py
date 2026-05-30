"""Temporal activities for durable AutoPilot sessions."""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlmodel import Session

from orchestrator.api.db import engine
from orchestrator.api.models_db import AutoPilotSession
from orchestrator.workflows.autopilot_pipeline import AutoPilotConfig, AutoPilotPipeline

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


@contextmanager
def _temporal_autopilot_execution_env():
    """Run AutoPilot browser work inside the Temporal worker process."""
    managed_names = (
        "USE_AGENT_QUEUE",
        "HEADLESS",
        "PLAYWRIGHT_HEADLESS",
        "PLAYWRIGHT_WORKERS",
    )
    previous_values = {name: os.environ.get(name) for name in managed_names}
    if os.environ.get("VNC_ENABLED", "").lower() == "true" and os.environ.get("DISPLAY"):
        os.environ["USE_AGENT_QUEUE"] = "false"
        os.environ["HEADLESS"] = "false"
        os.environ["PLAYWRIGHT_HEADLESS"] = "false"
        os.environ["PLAYWRIGHT_WORKERS"] = "1"
    try:
        yield
    finally:
        for name, previous_value in previous_values.items():
            if previous_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous_value


def _session_payload(session: AutoPilotSession | None) -> dict[str, Any]:
    if not session:
        return {"status": "missing", "terminal": True, "error_message": "AutoPilot session disappeared"}
    return {
        "session_id": session.id,
        "status": session.status,
        "terminal": session.status in TERMINAL_STATUSES,
        "temporal_workflow_id": session.temporal_workflow_id,
        "temporal_run_id": session.temporal_run_id,
    }


def _build_config_from_session(session: AutoPilotSession) -> AutoPilotConfig:
    cfg = session.config
    return AutoPilotConfig(
        entry_urls=session.entry_urls,
        project_id=session.project_id or "default",
        login_url=session.login_url,
        credentials=session.credentials,
        test_data=session.test_data,
        instructions=session.instructions,
        strategy=cfg.get("strategy", "goal_directed"),
        max_interactions=cfg.get("max_interactions", 50),
        max_depth=cfg.get("max_depth", 10),
        timeout_minutes=cfg.get("timeout_minutes", 30),
        reactive_mode=cfg.get("reactive_mode", True),
        auto_continue_hours=cfg.get("auto_continue_hours", 24),
        priority_threshold=cfg.get("priority_threshold", "low"),
        max_specs=cfg.get("max_specs", 50),
        parallel_generation=cfg.get("parallel_generation", 2),
        hybrid_healing=cfg.get("hybrid_healing", False),
    )


def mark_autopilot_temporal_started(payload: dict[str, Any]) -> dict[str, Any]:
    """Record Temporal metadata for a durable AutoPilot session."""
    session_id = str(payload["session_id"])
    with Session(engine) as db:
        session = db.get(AutoPilotSession, session_id)
        if not session:
            return {"session_id": session_id, "status": "missing", "terminal": True}
        session.temporal_workflow_id = payload.get("workflow_id") or session.temporal_workflow_id
        session.temporal_run_id = payload.get("temporal_run_id") or session.temporal_run_id
        session.started_at = session.started_at or datetime.utcnow()
        if session.status not in TERMINAL_STATUSES and session.status != "paused":
            session.status = "running"
        db.add(session)
        db.commit()
        return _session_payload(session)


async def execute_autopilot_pipeline(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute the persisted AutoPilot session inside a Temporal activity."""
    session_id = str(payload["session_id"])
    with Session(engine) as db:
        session = db.get(AutoPilotSession, session_id)
        if not session:
            return {"session_id": session_id, "status": "missing", "terminal": True}
        if session.status in TERMINAL_STATUSES:
            return _session_payload(session)
        config = _build_config_from_session(session)
        project_id = session.project_id or "default"

    pipeline = AutoPilotPipeline(session_id, project_id)
    try:
        with _temporal_autopilot_execution_env():
            return await pipeline.run(config)
    except asyncio.CancelledError:
        with Session(engine) as db:
            session = db.get(AutoPilotSession, session_id)
            if session and session.status not in TERMINAL_STATUSES:
                session.status = "cancelled"
                session.completed_at = datetime.utcnow()
                db.add(session)
                db.commit()
        return {"session_id": session_id, "status": "cancelled"}
    except Exception as exc:
        with Session(engine) as db:
            session = db.get(AutoPilotSession, session_id)
            if session and session.status not in TERMINAL_STATUSES:
                session.status = "failed"
                session.error_message = str(exc)[:500]
                session.completed_at = datetime.utcnow()
                db.add(session)
                db.commit()
        return {"session_id": session_id, "status": "failed", "error": str(exc)}


def set_autopilot_control_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a Temporal control signal to the AutoPilotSession row."""
    session_id = str(payload["session_id"])
    status = str(payload["status"])
    reason = str(payload.get("reason") or status)
    with Session(engine) as db:
        session = db.get(AutoPilotSession, session_id)
        if not session:
            return {"session_id": session_id, "status": "missing", "terminal": True}
        if session.status in TERMINAL_STATUSES:
            return _session_payload(session)
        session.status = status
        if status in TERMINAL_STATUSES:
            session.completed_at = datetime.utcnow()
        if status in {"failed", "cancelled"}:
            session.error_message = reason
        db.add(session)
        db.commit()
        return _session_payload(session)


def finalize_autopilot_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure workflow-level completion timestamps are consistent."""
    session_id = str(payload["session_id"])
    result = payload.get("result") or {}
    status = str(result.get("status") or "")
    with Session(engine) as db:
        session = db.get(AutoPilotSession, session_id)
        if not session:
            return {"session_id": session_id, "status": "missing", "terminal": True}
        if status in TERMINAL_STATUSES and session.status not in TERMINAL_STATUSES:
            session.status = status
        if session.status in TERMINAL_STATUSES and not session.completed_at:
            session.completed_at = datetime.utcnow()
        db.add(session)
        db.commit()
        return _session_payload(session)
