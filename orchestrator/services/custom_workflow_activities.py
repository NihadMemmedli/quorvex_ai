"""Temporal activities for durable custom workflow execution."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session

from orchestrator.api.db import engine
from orchestrator.api.models_db import WorkflowRun
from orchestrator.services.workflow_runner import (
    execute_workflow_step_once,
    handle_workflow_step_failure,
    prepare_next_workflow_step,
    run_workflow,
)


def mark_custom_workflow_started(payload: dict[str, Any]) -> dict[str, Any]:
    """Record Temporal metadata for a durable custom workflow run."""
    run_id = str(payload["run_id"])
    with Session(engine) as session:
        run = session.get(WorkflowRun, run_id)
        if not run:
            return {"run_id": run_id, "status": "missing", "error_message": "Workflow run disappeared"}
        run.temporal_workflow_id = payload.get("workflow_id") or run.temporal_workflow_id
        run.temporal_run_id = payload.get("temporal_run_id") or run.temporal_run_id
        run.heartbeat_at = datetime.utcnow()
        run.updated_at = datetime.utcnow()
        session.add(run)
        session.commit()
        return {"run_id": run_id, "status": run.status}


def prepare_custom_workflow_step(payload: dict[str, Any]) -> dict[str, Any]:
    """Prepare and return the next runnable workflow step."""
    return prepare_next_workflow_step(str(payload["run_id"]))


async def execute_custom_workflow_step(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one persisted workflow step."""
    return await execute_workflow_step_once(str(payload["run_id"]), payload.get("step_id"))


def handle_custom_workflow_step_failure(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply persisted custom workflow step recovery semantics."""
    return handle_workflow_step_failure(
        str(payload["run_id"]),
        payload.get("step_id"),
        str(payload.get("error_message") or "Workflow step failed"),
    )


async def execute_custom_workflow_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute an existing workflow run using the DB-backed runner."""
    run_id = str(payload["run_id"])
    with Session(engine) as session:
        run = session.get(WorkflowRun, run_id)
        if run:
            run.temporal_workflow_id = payload.get("workflow_id") or run.temporal_workflow_id
            run.temporal_run_id = payload.get("temporal_run_id") or run.temporal_run_id
            run.heartbeat_at = datetime.utcnow()
            session.add(run)
            session.commit()

    await run_workflow(run_id)

    with Session(engine) as session:
        run = session.get(WorkflowRun, run_id)
        return {
            "run_id": run_id,
            "status": run.status if run else "missing",
            "error_message": run.error_message if run else "Workflow run disappeared",
        }


def set_custom_workflow_status(payload: dict[str, Any]) -> None:
    """Apply a control signal to the DB row for the running workflow."""
    run_id = str(payload["run_id"])
    status = str(payload["status"])
    with Session(engine) as session:
        run = session.get(WorkflowRun, run_id)
        if not run:
            return
        run.status = status
        run.pause_reason = payload.get("reason") or run.pause_reason
        run.updated_at = datetime.utcnow()
        if status in {"cancelled", "failed"}:
            run.completed_at = datetime.utcnow()
            run.error_message = payload.get("reason") or run.error_message
        session.add(run)
        session.commit()
