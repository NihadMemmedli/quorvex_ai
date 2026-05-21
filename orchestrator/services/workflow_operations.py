"""Operational helpers for custom workflow revisions, events, and schedules."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, select

from orchestrator.api.models_db import (
    WorkflowDefinition,
    WorkflowDefinitionRevision,
    WorkflowEvent,
    WorkflowNotification,
    WorkflowRun,
    WorkflowSchedule,
    WorkflowScheduleExecution,
)

NOTIFICATION_EVENT_TYPES = {
    "workflow.completed",
    "workflow.failed",
    "workflow.cancelled",
    "workflow.awaiting_input",
    "workflow.step_failed",
    "workflow.schedule_failed",
    "workflow.schedule_completed",
    "workflow.schedule_review_needed",
    "workflow.review_needed",
}


def utcnow() -> datetime:
    return datetime.utcnow()


def latest_workflow_revision(session: Session, definition_id: str) -> WorkflowDefinitionRevision | None:
    return session.exec(
        select(WorkflowDefinitionRevision)
        .where(WorkflowDefinitionRevision.definition_id == definition_id)
        .order_by(col(WorkflowDefinitionRevision.version).desc())
    ).first()


def create_workflow_revision(
    session: Session,
    definition: WorkflowDefinition,
    *,
    change_summary: str = "",
    created_by: str | None = None,
    version: int | None = None,
) -> WorkflowDefinitionRevision:
    if version is None:
        latest = latest_workflow_revision(session, definition.id)
        version = (latest.version + 1) if latest else max(1, int(definition.version or 1))
    definition.version = version
    revision = WorkflowDefinitionRevision(
        definition_id=definition.id,
        project_id=definition.project_id,
        version=version,
        name=definition.name,
        description=definition.description,
        change_summary=change_summary,
        created_by=created_by,
    )
    revision.steps = definition.steps
    session.add(definition)
    session.add(revision)
    session.flush()
    return revision


def ensure_workflow_revision(
    session: Session,
    definition: WorkflowDefinition,
    *,
    created_by: str | None = None,
) -> WorkflowDefinitionRevision:
    latest = latest_workflow_revision(session, definition.id)
    if latest:
        return latest
    return create_workflow_revision(
        session,
        definition,
        change_summary="Initial workflow revision",
        created_by=created_by or definition.created_by,
        version=max(1, int(definition.version or 1)),
    )


def restore_workflow_revision(
    session: Session,
    definition: WorkflowDefinition,
    revision: WorkflowDefinitionRevision,
    *,
    created_by: str | None = None,
) -> WorkflowDefinitionRevision:
    definition.name = revision.name
    definition.description = revision.description
    definition.steps = revision.steps
    definition.updated_at = utcnow()
    return create_workflow_revision(
        session,
        definition,
        change_summary=f"Restored from version {revision.version}",
        created_by=created_by,
    )


def emit_workflow_event(
    session: Session,
    *,
    event_type: str,
    message: str,
    severity: str = "info",
    run: WorkflowRun | None = None,
    schedule: WorkflowSchedule | None = None,
    definition_id: str | None = None,
    step_id: int | None = None,
    payload: dict[str, Any] | None = None,
    notify: bool | None = None,
) -> WorkflowEvent:
    project_id = (run.project_id if run else None) or (schedule.project_id if schedule else None)
    resolved_definition_id = definition_id or (run.definition_id if run else None) or (schedule.definition_id if schedule else None)
    event = WorkflowEvent(
        project_id=project_id,
        definition_id=resolved_definition_id,
        run_id=run.id if run else None,
        step_id=step_id,
        schedule_id=schedule.id if schedule else None,
        event_type=event_type,
        severity=severity,
        message=message,
    )
    event.payload = payload or {}
    session.add(event)
    session.flush()

    should_notify = event_type in NOTIFICATION_EVENT_TYPES if notify is None else notify
    if should_notify:
        notification = WorkflowNotification(
            project_id=project_id,
            event_id=event.id,
            title=_notification_title(event_type),
            body=message,
            target_url=f"/workflow?tab=runs&runId={run.id}" if run else "/workflow",
            delivered_at=utcnow(),
        )
        session.add(notification)
    return event


def _notification_title(event_type: str) -> str:
    return {
        "workflow.completed": "Workflow completed",
        "workflow.failed": "Workflow failed",
        "workflow.cancelled": "Workflow cancelled",
        "workflow.awaiting_input": "Workflow needs review",
        "workflow.step_failed": "Workflow step failed",
        "workflow.schedule_failed": "Workflow schedule failed",
        "workflow.schedule_completed": "Workflow schedule completed",
        "workflow.schedule_review_needed": "Workflow schedule needs review",
        "workflow.review_needed": "Workflow review needed",
    }.get(event_type, "Workflow update")


def workflow_schedule_to_dict(schedule: WorkflowSchedule) -> dict[str, Any]:
    return {
        "id": schedule.id,
        "project_id": schedule.project_id,
        "definition_id": schedule.definition_id,
        "revision_id": schedule.revision_id,
        "name": schedule.name,
        "description": schedule.description,
        "cron_expression": schedule.cron_expression,
        "timezone": schedule.timezone,
        "inputs": schedule.inputs,
        "start_step_key": schedule.start_step_key,
        "enabled": schedule.enabled,
        "status": schedule.status,
        "last_error": schedule.last_error,
        "notify_on_completion": schedule.notify_on_completion,
        "notify_on_failure": schedule.notify_on_failure,
        "notify_on_review_needed": schedule.notify_on_review_needed,
        "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
        "last_run_status": schedule.last_run_status,
        "last_run_id": schedule.last_run_id,
        "total_executions": schedule.total_executions,
        "successful_executions": schedule.successful_executions,
        "failed_executions": schedule.failed_executions,
        "avg_duration_seconds": schedule.avg_duration_seconds,
        "success_rate": schedule.success_rate,
        "created_by": schedule.created_by,
        "created_at": schedule.created_at.isoformat(),
        "updated_at": schedule.updated_at.isoformat(),
    }


def workflow_schedule_execution_to_dict(execution: WorkflowScheduleExecution) -> dict[str, Any]:
    return {
        "id": execution.id,
        "schedule_id": execution.schedule_id,
        "workflow_run_id": execution.workflow_run_id,
        "status": execution.status,
        "trigger_type": execution.trigger_type,
        "error_message": execution.error_message,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
        "duration_seconds": execution.duration_seconds,
        "created_at": execution.created_at.isoformat(),
    }


def workflow_event_to_dict(event: WorkflowEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "project_id": event.project_id,
        "definition_id": event.definition_id,
        "run_id": event.run_id,
        "step_id": event.step_id,
        "schedule_id": event.schedule_id,
        "event_type": event.event_type,
        "severity": event.severity,
        "message": event.message,
        "payload": event.payload,
        "created_at": event.created_at.isoformat(),
    }


def workflow_notification_to_dict(notification: WorkflowNotification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "project_id": notification.project_id,
        "event_id": notification.event_id,
        "channel": notification.channel,
        "title": notification.title,
        "body": notification.body,
        "target_url": notification.target_url,
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
        "delivered_at": notification.delivered_at.isoformat() if notification.delivered_at else None,
        "created_at": notification.created_at.isoformat(),
    }


def json_changed(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True) != json.dumps(right, sort_keys=True)


def avg_duration(existing: float | None, latest: int | None) -> float | None:
    if latest is None:
        return existing
    if existing is None:
        return float(latest)
    return round(existing * 0.8 + latest * 0.2, 2)


def workflow_duration_seconds(run: WorkflowRun) -> int | None:
    if not run.started_at or not run.completed_at:
        return None
    return max(0, int((run.completed_at - run.started_at).total_seconds()))


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * pct)))
    return round(float(ordered[index]), 2)


def count_unread_notifications(session: Session, project_id: str | None) -> int:
    stmt = select(func.count()).select_from(WorkflowNotification).where(WorkflowNotification.read_at == None)
    if project_id:
        stmt = stmt.where(WorkflowNotification.project_id == project_id)
    return int(session.exec(stmt).one())
