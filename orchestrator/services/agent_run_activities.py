"""Temporal activities for durable standalone agent runs."""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlmodel import Session

from orchestrator.api.db import engine
from orchestrator.api.models_db import AgentRun
from orchestrator.services.agent_run_events import create_agent_run_event

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "timeout"}


@contextmanager
def _temporal_agent_execution_env():
    """Run agent work inside the Temporal activity instead of Redis queue workers."""
    previous = os.environ.get("USE_AGENT_QUEUE")
    os.environ["USE_AGENT_QUEUE"] = "false"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("USE_AGENT_QUEUE", None)
        else:
            os.environ["USE_AGENT_QUEUE"] = previous


def _run_payload(run: AgentRun | None) -> dict[str, Any]:
    if not run:
        return {"status": "missing", "terminal": True, "error_message": "Agent run disappeared"}
    return {
        "run_id": run.id,
        "status": run.status,
        "terminal": run.status in TERMINAL_STATUSES,
        "agent_task_id": run.agent_task_id,
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
    }


def mark_agent_run_temporal_started(payload: dict[str, Any]) -> dict[str, Any]:
    """Record Temporal metadata for a durable standalone agent run."""
    run_id = str(payload["run_id"])
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if not run:
            return {"run_id": run_id, "status": "missing", "terminal": True, "error_message": "Agent run disappeared"}
        run.temporal_workflow_id = payload.get("workflow_id") or run.temporal_workflow_id
        run.temporal_run_id = payload.get("temporal_run_id") or run.temporal_run_id
        run.started_at = run.started_at or datetime.utcnow()
        if run.status not in TERMINAL_STATUSES and run.status != "paused":
            run.status = "running"
        run.progress = {
            **(run.progress or {}),
            "phase": run.status,
            "status": run.status,
            "message": "Agent run is managed by Temporal.",
            "updated_at": datetime.utcnow().isoformat(),
        }
        session.add(run)
        session.commit()
        create_agent_run_event(
            run_id=run.id,
            event_type="temporal_started",
            message="Agent Temporal workflow started.",
            payload={
                "workflow_id": run.temporal_workflow_id,
                "temporal_run_id": run.temporal_run_id,
                "status": run.status,
            },
            session=session,
        )
        return _run_payload(run)


async def execute_agent_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute or reattach to the Redis-backed agent task for one AgentRun."""
    run_id = str(payload["run_id"])
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if not run:
            return {"run_id": run_id, "status": "missing", "terminal": True, "error_message": "Agent run disappeared"}
        if run.status in TERMINAL_STATUSES:
            return _run_payload(run)
        agent_type = run.agent_type
        config = run.config
        agent_task_id = run.agent_task_id

    if agent_type == "__temporal_smoke__" and config.get("temporal_smoke") is True:
        return _complete_smoke_agent_run(run_id)

    if agent_task_id:
        return await _reattach_agent_task(run_id, agent_task_id)

    from orchestrator.api.main import execute_agent_background

    with _temporal_agent_execution_env():
        try:
            await execute_agent_background(run_id, agent_type, config)
        except asyncio.CancelledError:
            with Session(engine) as session:
                run = session.get(AgentRun, run_id)
                if run and run.status not in TERMINAL_STATUSES:
                    run.status = "cancelled"
                    run.completed_at = datetime.utcnow()
                    run.progress = {
                        **(run.progress or {}),
                        "phase": "cancelled",
                        "status": "cancelled",
                        "message": "Agent run cancelled.",
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    session.add(run)
                    session.commit()
                    create_agent_run_event(
                        run_id=run.id,
                        agent_task_id=run.agent_task_id,
                        event_type="cancel",
                        message="Agent activity cancelled.",
                        payload={"status": run.status},
                        session=session,
                    )
                return _run_payload(run)
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        return _run_payload(run)


def _complete_smoke_agent_run(run_id: str) -> dict[str, Any]:
    """Complete a deterministic no-op run used by Temporal smoke tests."""
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if run and run.status not in TERMINAL_STATUSES:
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            run.result = {"summary": "Temporal smoke agent run completed.", "smoke": True}
            run.progress = {
                **(run.progress or {}),
                "phase": "completed",
                "status": "completed",
                "message": "Temporal smoke agent run completed.",
                "updated_at": datetime.utcnow().isoformat(),
            }
            session.add(run)
            session.commit()
            create_agent_run_event(
                run_id=run.id,
                event_type="complete",
                message="Temporal smoke agent run completed.",
                payload={"smoke": True},
                session=session,
            )
        return _run_payload(run)


async def _reattach_agent_task(run_id: str, agent_task_id: str) -> dict[str, Any]:
    """Wait for an existing queued task instead of enqueueing a duplicate."""
    from orchestrator.services.agent_queue import get_agent_queue

    queue = get_agent_queue()
    await queue.connect()

    try:
        result_text = await queue.wait_for_result(agent_task_id, timeout=12 * 60 * 60, poll_interval=1.0)
    except Exception as exc:
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            if run and run.status not in TERMINAL_STATUSES:
                run.status = "failed"
                run.completed_at = datetime.utcnow()
                run.result = {"error": str(exc)}
                run.progress = {
                    **(run.progress or {}),
                    "phase": "failed",
                    "status": "failed",
                    "message": str(exc),
                    "updated_at": datetime.utcnow().isoformat(),
                }
                session.add(run)
                session.commit()
                create_agent_run_event(
                    run_id=run.id,
                    agent_task_id=agent_task_id,
                    event_type="error",
                    level="error",
                    message=f"Agent task reattach failed: {exc}",
                    payload={"error": str(exc)},
                    session=session,
                )
            return _run_payload(run)

    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if run and run.status not in TERMINAL_STATUSES:
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            run.result = {"summary": (result_text or "")[:500], "output": result_text or ""}
            run.progress = {
                **(run.progress or {}),
                "phase": "completed",
                "status": "completed",
                "message": "Agent task completed after Temporal reattach.",
                "updated_at": datetime.utcnow().isoformat(),
            }
            session.add(run)
            session.commit()
            create_agent_run_event(
                run_id=run.id,
                agent_task_id=agent_task_id,
                event_type="complete",
                message="Agent run completed after Temporal reattach.",
                payload={"result_preview": (result_text or "")[:1200]},
                session=session,
            )
        return _run_payload(run)


def set_agent_run_control_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a Temporal control signal to the AgentRun row."""
    run_id = str(payload["run_id"])
    status = str(payload["status"])
    reason = str(payload.get("reason") or status)
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if not run:
            return {"run_id": run_id, "status": "missing", "terminal": True}
        if run.status in TERMINAL_STATUSES:
            return _run_payload(run)
        previous_status = run.status
        run.status = status
        if status in TERMINAL_STATUSES:
            run.completed_at = datetime.utcnow()
        run.progress = {
            **(run.progress or {}),
            "phase": status,
            "status": status,
            "message": reason,
            "paused_from": previous_status if status == "paused" else (run.progress or {}).get("paused_from"),
            "updated_at": datetime.utcnow().isoformat(),
        }
        session.add(run)
        session.commit()
        create_agent_run_event(
            run_id=run.id,
            agent_task_id=run.agent_task_id,
            event_type=status if status in {"paused", "cancelled"} else "control",
            message=f"Agent run marked {status}: {reason}",
            payload={"status": status, "previous_status": previous_status, "reason": reason},
            session=session,
        )
        return _run_payload(run)


def finalize_agent_run_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    """Record workflow-level completion metadata after agent execution returns."""
    run_id = str(payload["run_id"])
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if not run:
            return {"run_id": run_id, "status": "missing", "terminal": True}
        if run.status in TERMINAL_STATUSES and not run.completed_at:
            run.completed_at = datetime.utcnow()
            session.add(run)
            session.commit()
        create_agent_run_event(
            run_id=run.id,
            agent_task_id=run.agent_task_id,
            event_type="temporal_finished",
            message=f"Agent Temporal workflow finished with status {run.status}.",
            payload={"status": run.status, "result": payload.get("result") or {}},
            session=session,
        )
        return _run_payload(run)
