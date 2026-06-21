"""Stale autonomous work-item recovery helpers."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta

from sqlmodel import Session, col, select

from orchestrator.api.models_db import AutonomousAgentWorkItem, AutonomousMission, AutonomousMissionRun
from orchestrator.services import autonomous_activities as facade
from orchestrator.services.autonomous_events import emit_work_item_status_event


def _recover_stale_work_items(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
) -> int:
    now = facade._utcnow()
    stale_after = now - timedelta(
        minutes=max(
            5, facade._config_int(mission.config, "work_item_stale_minutes", facade.DEFAULT_WORK_ITEM_STALE_MINUTES)
        )
    )
    running_items = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission.id,
            AutonomousAgentWorkItem.status == "running",
        )
    ).all()
    created = 0
    for item in running_items:
        if not facade._work_item_is_stale(item, now=now, stale_after=stale_after):
            continue
        task_state = facade._agent_task_recovery_state(str(item.agent_task_id or ""))
        if task_state in {"running", "paused"}:
            item.lease_until = now + timedelta(minutes=30)
            item.last_heartbeat_at = now
            item.updated_at = now
            session.add(item)
            continue
        if facade._active_recovery_work_item_exists(session, mission.id, item.id):
            continue
        reason = (
            task_state
            if task_state != "unknown"
            else facade._stale_work_item_reason(item, now=now, stale_after=stale_after)
        )
        replacement = facade._create_recovery_work_item(session, mission, run, item, reason=reason)
        if not replacement:
            continue
        item.status = "failed"
        item.error_message = f"Recovered stale autonomous work item: {reason}"
        item.completed_at = now
        item.updated_at = now
        item.recovery_reason = reason
        item.progress = {
            **item.progress,
            "phase": "recovered",
            "message": item.error_message,
            "recovery_reason": reason,
            "recovery_work_item_id": replacement.id,
        }
        item.result = {
            **item.result,
            "recovery_reason": reason,
            "recovery_work_item_id": replacement.id,
            "recovered_at": now.isoformat(),
        }
        session.add(item)
        emit_work_item_status_event(item, item.error_message, event_type="error")
        created += 1
    if created:
        session.commit()
    return created


def _work_item_is_stale(item: AutonomousAgentWorkItem, *, now: datetime, stale_after: datetime) -> bool:
    if item.lease_until and item.lease_until <= now:
        return True
    if item.last_heartbeat_at and item.last_heartbeat_at <= stale_after:
        return True
    if not item.last_heartbeat_at and item.updated_at <= stale_after:
        return True
    return False


def _stale_work_item_reason(item: AutonomousAgentWorkItem, *, now: datetime, stale_after: datetime) -> str:
    if item.lease_until and item.lease_until <= now:
        return "lease_expired"
    if item.last_heartbeat_at and item.last_heartbeat_at <= stale_after:
        return "heartbeat_stale"
    return "updated_at_stale"


def _agent_task_recovery_state(task_id: str) -> str:
    if not task_id:
        return "missing_agent_task"
    try:
        from orchestrator.services.agent_queue import AgentTaskStatus, get_agent_queue

        async def _load() -> str:
            queue = get_agent_queue()
            await queue.connect()
            try:
                task = await queue.get_task(task_id)
            finally:
                await queue.disconnect()
            if not task:
                return "missing_agent_task"
            if task.status == AgentTaskStatus.COMPLETED:
                return "completed_out_of_band"
            if task.status == AgentTaskStatus.FAILED:
                return "agent_task_failed"
            if task.status == AgentTaskStatus.TIMEOUT:
                return "agent_task_timeout"
            if task.status == AgentTaskStatus.CANCELLED:
                return "agent_task_cancelled"
            if task.status == AgentTaskStatus.PAUSED:
                return "paused"
            return "running"

        return asyncio.run(_load())
    except Exception:
        facade.logger.debug("Unable to inspect agent task %s during recovery.", task_id, exc_info=True)
        return "unknown"


def _active_recovery_work_item_exists(session: Session, mission_id: str, stale_item_id: str) -> bool:
    items = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission_id,
            col(AutonomousAgentWorkItem.status).in_(("queued", "running")),
        )
    ).all()
    return any((item.progress or {}).get("recovered_from_work_item_id") == stale_item_id for item in items)


def _create_recovery_work_item(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    stale_item: AutonomousAgentWorkItem,
    *,
    reason: str,
) -> AutonomousAgentWorkItem | None:
    progress = stale_item.progress or {}
    recovery_count = int(stale_item.recovery_count or progress.get("recovery_count") or 0) + 1
    replacement = AutonomousAgentWorkItem(
        id=f"amwork-{uuid.uuid4().hex[:12]}",
        mission_id=mission.id,
        run_id=run.id,
        project_id=mission.project_id,
        role=stale_item.role,
        planner_key=stale_item.planner_key or progress.get("planner_key"),
        objective=stale_item.objective,
        assigned_surface_json=stale_item.assigned_surface_json,
        status="queued",
        priority=max(1, int(stale_item.priority or 50) - 1),
        recovery_count=recovery_count,
        recovery_reason=reason,
    )
    replacement.progress = {
        **progress,
        "phase": "created",
        "message": "Recovered from a stale autonomous work item.",
        "planner_key": replacement.planner_key,
        "recovered_from_work_item_id": stale_item.id,
        "recovery_reason": reason,
        "recovery_count": recovery_count,
    }
    session.add(replacement)
    return replacement
