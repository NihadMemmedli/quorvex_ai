"""Shared cancellation helpers for agent-owned work."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from orchestrator.api.models_db import AgentRun, AutonomousAgentWorkItem, AutonomousMission, WorkflowRun, WorkflowRunStep
from orchestrator.services.agent_run_events import create_agent_run_event
from orchestrator.services.autonomous_events import emit_work_item_status_event
from orchestrator.services.workflow_operations import emit_workflow_event

logger = logging.getLogger(__name__)

TERMINAL_AGENT_STATUSES = {"completed", "failed", "cancelled", "timeout"}
ACTIVE_WORK_ITEM_STATUSES = {"queued", "running"}


async def cancel_agent_task_id(task_id: str | None, *, runtime: str | None = None) -> dict[str, Any] | None:
    """Cancel a Redis queue task by external task id."""
    if not task_id:
        return None
    result = {"agent_task_id": task_id, "runtime": runtime or "queue", "status": "not_active"}
    try:
        from orchestrator.services.agent_queue import get_agent_queue

        queue = get_agent_queue()
        await queue.connect()
        try:
            before = await queue.get_task(str(task_id))
            cancelled = await queue.cancel_task(str(task_id))
            after = await queue.get_task(str(task_id))
            result.update(
                {
                    "status": after.status.value if after else "missing",
                    "cancel_requested": bool(cancelled),
                    "previous_status": before.status.value if before else None,
                }
            )
        finally:
            await queue.disconnect()
    except Exception as exc:
        logger.warning("Failed to cancel agent task %s: %s", task_id, exc)
        result.update({"status": "error", "error": str(exc)})
    return result


async def cancel_agent_run_by_id(run_id: str, session: Session, *, reason: str = "cancelled") -> dict[str, Any]:
    """Cancel a standalone AgentRun and its underlying Temporal/queue work."""
    run = session.get(AgentRun, run_id)
    if not run:
        return {"run_id": run_id, "status": "missing"}
    if run.status in TERMINAL_AGENT_STATUSES:
        return {"run_id": run.id, "status": run.status, "already_terminal": True}

    temporal_result: dict[str, Any] | None = None
    try:
        from orchestrator.api.main import _signal_agent_run_temporal

        await _signal_agent_run_temporal(run, "cancel", reason)
        temporal_result = {"status": "signalled", "workflow_id": run.temporal_workflow_id}
    except Exception as exc:
        logger.debug("Unable to signal agent run Temporal workflow %s: %s", run.id, exc)
        temporal_result = {"status": "error", "error": str(exc)}

    queue_result = None
    try:
        from orchestrator.api.main import _cancel_agent_run_queue_task, _mark_agent_run_cancelled

        _mark_agent_run_cancelled(run, f"Agent run cancelled: {reason}")
        session.add(run)
        session.commit()
        session.refresh(run)
        queue_result = await _cancel_agent_run_queue_task(run)
    except Exception as exc:
        logger.debug("Falling back to local agent run cancellation for %s: %s", run.id, exc)
        previous_status = run.status
        run.status = "cancelled"
        run.completed_at = datetime.utcnow()
        run.progress = {
            **(run.progress or {}),
            "phase": "cancelled",
            "status": "cancelled",
            "cancelled_from": previous_status,
            "message": f"Agent run cancelled: {reason}",
            "updated_at": datetime.utcnow().isoformat(),
        }
        session.add(run)
        session.commit()
        session.refresh(run)
        queue_result = await cancel_agent_task_id(run.agent_task_id, runtime=getattr(run, "runtime", None) or (run.config or {}).get("runtime"))

    create_agent_run_event(
        run_id=run.id,
        event_type="cancel",
        message=f"Agent run cancelled: {reason}",
        payload={"status": run.status, "reason": reason, "temporal": temporal_result, "queue_cancel": queue_result},
        agent_task_id=run.agent_task_id,
        session=session,
    )
    return {"run_id": run.id, "status": run.status, "temporal": temporal_result, "queue_cancel": queue_result}


def _walk_external_agent_ids(value: Any) -> set[str]:
    ids: set[str] = set()
    if isinstance(value, dict):
        external_kind = str(value.get("external_kind") or "")
        external_id = value.get("external_id")
        run_id = value.get("run_id")
        if external_kind == "agent_run" and external_id:
            ids.add(str(external_id))
        if run_id and (external_kind == "agent_run" or value.get("agent_type") or value.get("agent_task_id")):
            ids.add(str(run_id))
        for item in value.values():
            ids.update(_walk_external_agent_ids(item))
    elif isinstance(value, list):
        for item in value:
            ids.update(_walk_external_agent_ids(item))
    return ids


def collect_workflow_child_agent_run_ids(session: Session, run: WorkflowRun) -> set[str]:
    """Collect child AgentRun ids from step refs, step output, and workflow context."""
    ids: set[str] = set()
    steps = session.exec(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id)).all()
    for step in steps:
        if step.external_kind == "agent_run" and step.external_id:
            ids.add(str(step.external_id))
        ids.update(_walk_external_agent_ids(step.output or {}))
        ids.update(_walk_external_agent_ids(step.context_snapshot or {}))
    ids.update(_walk_external_agent_ids(run.context or {}))
    return ids


async def cancel_workflow_child_agent_runs(run: WorkflowRun, session: Session, *, reason: str) -> dict[str, Any]:
    child_ids = sorted(collect_workflow_child_agent_run_ids(session, run))
    results = [await cancel_agent_run_by_id(child_id, session, reason=reason) for child_id in child_ids]
    if child_ids:
        emit_workflow_event(
            session,
            event_type="workflow.children_cancelled",
            message=f"Cancelled {len(child_ids)} child agent run(s).",
            severity="warning",
            run=run,
            payload={"agent_run_ids": child_ids, "results": results},
            notify=False,
        )
        session.commit()
    return {"agent_run_ids": child_ids, "results": results}


async def cancel_autonomous_work_item_task(item: AutonomousAgentWorkItem, *, runtime: str | None = None) -> dict[str, Any] | None:
    return await cancel_agent_task_id(item.agent_task_id, runtime=runtime)


async def cancel_active_autonomous_work_items(
    mission_id: str,
    session: Session,
    *,
    runtime: str | None = None,
    reason: str = "Mission cancelled",
) -> dict[str, Any]:
    items = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission_id,
            AutonomousAgentWorkItem.status.in_(tuple(ACTIVE_WORK_ITEM_STATUSES)),
        )
    ).all()
    now = datetime.utcnow()
    task_results: list[dict[str, Any]] = []
    for item in items:
        cancel_result = await cancel_autonomous_work_item_task(item, runtime=runtime)
        if cancel_result:
            task_results.append({"work_item_id": item.id, **cancel_result})
        item.status = "cancelled"
        item.error_message = reason
        item.completed_at = item.completed_at or now
        item.updated_at = now
        item.progress = {
            **(item.progress or {}),
            "phase": "cancelled",
            "status": "cancelled",
            "message": reason,
            "task_cancel": cancel_result,
        }
        session.add(item)
    session.commit()
    for item in items:
        emit_work_item_status_event(item, reason, event_type="lifecycle", payload={"task_cancelled": bool(item.agent_task_id)})
    return {"work_item_ids": [item.id for item in items], "task_results": task_results}


def owner_is_cancelled_sync(owner_type: str, owner_id: str) -> bool:
    from orchestrator.api.db import engine

    with Session(engine) as session:
        if owner_type == "agent_run":
            run = session.get(AgentRun, owner_id)
            return not run or run.status == "cancelled"
        if owner_type == "autonomous_work_item":
            item = session.get(AutonomousAgentWorkItem, owner_id)
            if not item or item.status == "cancelled":
                return True
            mission = session.get(AutonomousMission, item.mission_id)
            return bool(mission and mission.status == "cancelled")
    return False
