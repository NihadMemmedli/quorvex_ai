"""Custom workflow definition and execution endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from orchestrator.services.temporal_client import (
    TemporalUnavailableError,
    signal_custom_workflow_run,
    start_custom_workflow_run,
)
from orchestrator.services.workflow_operations import (
    create_workflow_revision,
    emit_workflow_event,
    ensure_workflow_revision,
    json_changed,
    percentile,
    restore_workflow_revision,
    workflow_duration_seconds,
    workflow_event_to_dict,
    workflow_notification_to_dict,
    workflow_schedule_execution_to_dict,
    workflow_schedule_to_dict,
)
from orchestrator.services.workflow_runner import (
    ACTIVE_STATUSES,
    RECOVERY_ACTIONS,
    TERMINAL_STATUSES,
    create_workflow_run_steps,
    duplicate_workflow_definition_record,
    launch_workflow_run,
    reset_workflow_run_for_step_retry,
    validate_workflow_definition_payload,
    validate_workflow_steps,
    workflow_step_catalog,
)
from orchestrator.services.workflow_step_registry import WORKFLOW_TEMPLATES, sync_builtin_workflow_step_types

from .db import get_session
from .middleware.auth import get_current_user_optional
from .middleware.permissions import ProjectRole, check_project_access
from .models_db import (
    WorkflowDefinition,
    WorkflowDefinitionRevision,
    WorkflowEvent,
    WorkflowNotification,
    WorkflowRun,
    WorkflowRunStep,
    WorkflowSchedule,
    WorkflowScheduleExecution,
)
from .time_utils import utc_iso

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowStepSpec(BaseModel):
    key: str | None = None
    type: str
    label: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    continue_on_error: bool = False
    recovery_policy: dict[str, Any] | None = None


class WorkflowDefinitionRequest(BaseModel):
    name: str
    description: str = ""
    project_id: str | None = None
    steps: list[WorkflowStepSpec]


class WorkflowDefinitionUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    steps: list[WorkflowStepSpec] | None = None
    status: str | None = None


class WorkflowRunRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    triggered_by: str | None = None
    start_step_key: str | None = None
    trigger_type: str | None = None
    trigger_id: str | None = None
    recovery_policy: dict[str, Any] = Field(default_factory=dict)


class WorkflowValidationRequest(WorkflowDefinitionRequest):
    pass


class WorkflowImportRequest(BaseModel):
    project_id: str | None = None
    workflow: dict[str, Any]


class WorkflowRollbackRequest(BaseModel):
    change_summary: str | None = None


class WorkflowScheduleRequest(BaseModel):
    definition_id: str
    name: str
    description: str = ""
    cron_expression: str
    timezone: str = "UTC"
    inputs: dict[str, Any] = Field(default_factory=dict)
    start_step_key: str | None = None
    enabled: bool = True
    notify_on_completion: bool = False
    notify_on_failure: bool = True
    notify_on_review_needed: bool = True


class WorkflowScheduleUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    inputs: dict[str, Any] | None = None
    start_step_key: str | None = None
    enabled: bool | None = None
    notify_on_completion: bool | None = None
    notify_on_failure: bool | None = None
    notify_on_review_needed: bool | None = None


def _step_to_dict(step: WorkflowRunStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "run_id": step.run_id,
        "definition_id": step.definition_id,
        "step_order": step.step_order,
        "step_key": step.step_key,
        "step_type": step.step_type,
        "step_type_version": step.step_type_version,
        "label": step.label,
        "status": step.status,
        "continue_on_error": step.continue_on_error,
        "input": step.input,
        "rendered_input": step.rendered_input,
        "context_snapshot": step.context_snapshot,
        "input_resolution": step.input_resolution,
        "output": step.output,
        "output_validation_errors": step.output_validation_errors,
        "step_config": step.step_config,
        "error_message": step.error_message,
        "attempt_count": step.attempt_count,
        "max_attempts": step.max_attempts,
        "retry_backoff_seconds": step.retry_backoff_seconds,
        "recovery_action": step.recovery_action,
        "skipped_reason": step.skipped_reason,
        "external_kind": step.external_kind,
        "external_id": step.external_id,
        "started_at": utc_iso(step.started_at),
        "completed_at": utc_iso(step.completed_at),
        "updated_at": utc_iso(step.updated_at),
    }


def _definition_to_dict(definition: WorkflowDefinition) -> dict[str, Any]:
    return {
        "id": definition.id,
        "project_id": definition.project_id,
        "name": definition.name,
        "description": definition.description,
        "version": definition.version,
        "steps": definition.steps,
        "status": definition.status,
        "created_by": definition.created_by,
        "created_at": utc_iso(definition.created_at),
        "updated_at": utc_iso(definition.updated_at),
    }


def _definition_export(definition: WorkflowDefinition) -> dict[str, Any]:
    return {
        "schema_version": "quorvex.workflow.v1",
        "name": definition.name,
        "description": definition.description,
        "version": definition.version,
        "steps": definition.steps,
        "metadata": {
            "source": "quorvex",
            "exported_at": utc_iso(datetime.utcnow()),
        },
    }


def _run_to_dict(run: WorkflowRun, session: Session, *, include_steps: bool = True) -> dict[str, Any]:
    payload = {
        "id": run.id,
        "definition_id": run.definition_id,
        "revision_id": run.revision_id,
        "definition_version": run.definition_version,
        "project_id": run.project_id,
        "status": run.status,
        "current_step_index": run.current_step_index,
        "progress": run.progress,
        "inputs": run.inputs,
        "context": run.context,
        "recovery_policy": run.recovery_policy,
        "result": run.result,
        "error_message": run.error_message,
        "triggered_by": run.triggered_by,
        "trigger_type": run.trigger_type,
        "trigger_id": run.trigger_id,
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
        "heartbeat_at": utc_iso(run.heartbeat_at),
        "pause_reason": run.pause_reason,
        "created_at": utc_iso(run.created_at),
        "started_at": utc_iso(run.started_at),
        "completed_at": utc_iso(run.completed_at),
        "updated_at": utc_iso(run.updated_at),
    }
    definition = session.get(WorkflowDefinition, run.definition_id)
    if definition:
        payload["definition"] = {
            "id": definition.id,
            "name": definition.name,
            "description": definition.description,
        }
    if include_steps:
        steps = session.exec(
            select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id).order_by(WorkflowRunStep.step_order)
        ).all()
        payload["steps"] = [_step_to_dict(step) for step in steps]
    return payload


def _revision_to_dict(revision: WorkflowDefinitionRevision) -> dict[str, Any]:
    return {
        "id": revision.id,
        "definition_id": revision.definition_id,
        "project_id": revision.project_id,
        "version": revision.version,
        "name": revision.name,
        "description": revision.description,
        "steps": revision.steps,
        "change_summary": revision.change_summary,
        "created_by": revision.created_by,
        "created_at": utc_iso(revision.created_at),
    }


async def _ensure_write_access(project_id: str | None, user: Any, session: Session) -> None:
    if project_id:
        await check_project_access(project_id, user, [ProjectRole.ADMIN, ProjectRole.EDITOR], session)


def _get_definition_or_404(definition_id: str, project_id: str | None, session: Session) -> WorkflowDefinition:
    definition = session.get(WorkflowDefinition, definition_id)
    if not definition or definition.status == "archived":
        raise HTTPException(status_code=404, detail="Workflow definition not found")
    if project_id:
        if project_id == "default":
            if definition.project_id not in (None, "default"):
                raise HTTPException(status_code=404, detail="Workflow definition not found")
        elif definition.project_id != project_id:
            raise HTTPException(status_code=404, detail="Workflow definition not found")
    return definition


def _validate_recovery_policy(policy: dict[str, Any], *, label: str = "recovery_policy") -> dict[str, Any]:
    if not policy:
        return {}
    action = str(policy.get("action") or "fail").strip().lower()
    if action not in RECOVERY_ACTIONS:
        raise HTTPException(status_code=400, detail=f"{label}.action must be one of: {', '.join(sorted(RECOVERY_ACTIONS))}")
    try:
        max_attempts = max(1, int(policy.get("max_attempts") or 1))
        retry_backoff_seconds = max(0, int(policy.get("retry_backoff_seconds") or 0))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{label} retry values must be numbers") from exc
    return {
        "action": action,
        "max_attempts": max_attempts,
        "retry_backoff_seconds": retry_backoff_seconds,
    }


async def _launch_run_durably(run: WorkflowRun, background_tasks: BackgroundTasks | None = None, session: Session | None = None) -> None:
    """Prefer Temporal execution, with local fallback for development environments."""
    try:
        temporal = await start_custom_workflow_run(run.id)
        if session:
            refreshed = session.get(WorkflowRun, run.id)
            if refreshed:
                refreshed.temporal_workflow_id = temporal.workflow_id
                refreshed.temporal_run_id = temporal.run_id
                refreshed.updated_at = datetime.utcnow()
                session.add(refreshed)
                session.commit()
        return
    except TemporalUnavailableError:
        logger_msg = f"Temporal unavailable for workflow run {run.id}; falling back to FastAPI background task"
    except Exception as exc:
        logger_msg = f"Failed to start Temporal workflow for run {run.id}: {exc}; falling back to background task"
    import logging

    logging.getLogger(__name__).warning(logger_msg)
    if background_tasks:
        background_tasks.add_task(launch_workflow_run, run.id)
    else:
        await launch_workflow_run(run.id)


def _validate_cron(cron_expression: str, timezone: str) -> datetime | None:
    try:
        from orchestrator.services.scheduler import get_next_n_run_times

        next_runs = get_next_n_run_times(cron_expression, timezone, count=1)
        return next_runs[0] if next_runs else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/catalog")
def get_workflow_catalog(
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    sync_builtin_workflow_step_types(session)
    return {"steps": workflow_step_catalog(session, project_id), "templates": WORKFLOW_TEMPLATES}


@router.get("/admin/step-types")
def get_admin_workflow_step_types(
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    if not getattr(user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    sync_builtin_workflow_step_types(session)
    return {"steps": workflow_step_catalog(session, None)}


@router.post("/validate")
def validate_workflow_definition(
    request: WorkflowValidationRequest,
    session: Session = Depends(get_session),
):
    sync_builtin_workflow_step_types(session)
    return validate_workflow_definition_payload(
        name=request.name,
        steps=[step.model_dump() for step in request.steps],
        session=session,
        project_id=request.project_id,
    )


@router.post("/import/validate")
def validate_workflow_import(
    request: WorkflowImportRequest,
    session: Session = Depends(get_session),
):
    workflow = request.workflow or {}
    if workflow.get("schema_version") != "quorvex.workflow.v1":
        return {
            "valid": False,
            "form_errors": [{"code": "schema_version", "message": "Unsupported workflow export schema version."}],
            "step_errors": {},
            "warnings": {},
        }
    sync_builtin_workflow_step_types(session)
    return validate_workflow_definition_payload(
        name=str(workflow.get("name") or ""),
        steps=list(workflow.get("steps") or []),
        session=session,
        project_id=request.project_id,
    )


@router.post("/import")
async def import_workflow_definition(
    request: WorkflowImportRequest,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    workflow = request.workflow or {}
    if workflow.get("schema_version") != "quorvex.workflow.v1":
        raise HTTPException(status_code=400, detail="Unsupported workflow export schema version")
    await _ensure_write_access(request.project_id, user, session)
    name = str(workflow.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Workflow name is required")
    try:
        sync_builtin_workflow_step_types(session)
        steps = validate_workflow_steps(list(workflow.get("steps") or []), session=session, project_id=request.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing = session.exec(
        select(WorkflowDefinition)
        .where(WorkflowDefinition.project_id == request.project_id)
        .where(WorkflowDefinition.status == "active")
        .where(WorkflowDefinition.name == name)
    ).first()
    if existing:
        name = f"{name} Copy"
    definition = WorkflowDefinition(
        project_id=request.project_id,
        name=name,
        description=str(workflow.get("description") or "").strip(),
        created_by=getattr(user, "id", None),
    )
    definition.steps = steps
    session.add(definition)
    session.flush()
    create_workflow_revision(
        session,
        definition,
        change_summary="Imported workflow",
        created_by=getattr(user, "id", None),
        version=1,
    )
    session.commit()
    session.refresh(definition)
    return _definition_to_dict(definition)


@router.get("")
def get_workflow_overview(
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    active_statuses = {"queued", "running", "awaiting_input", "paused"}
    definitions_stmt = select(WorkflowDefinition).where(WorkflowDefinition.status == "active")
    runs_stmt = select(WorkflowRun)
    if project_id:
        definitions_stmt = definitions_stmt.where(WorkflowDefinition.project_id == project_id)
        runs_stmt = runs_stmt.where(WorkflowRun.project_id == project_id)
    definitions = session.exec(definitions_stmt).all()
    runs = session.exec(runs_stmt).all()
    return {
        "definitions": len(definitions),
        "runs": len(runs),
        "active_runs": len([run for run in runs if run.status in active_statuses]),
        "failed_runs": len([run for run in runs if run.status == "failed"]),
        "completed_runs": len([run for run in runs if run.status == "completed"]),
    }


@router.get("/analytics")
def get_workflow_analytics(
    project_id: str | None = Query(default=None),
    definition_id: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_session),
):
    runs_stmt = select(WorkflowRun).order_by(col(WorkflowRun.created_at).desc()).limit(limit)
    steps_stmt = select(WorkflowRunStep)
    if project_id:
        runs_stmt = runs_stmt.where(WorkflowRun.project_id == project_id)
        steps_stmt = steps_stmt.where(WorkflowRunStep.definition_id.in_(
            [d.id for d in session.exec(select(WorkflowDefinition).where(WorkflowDefinition.project_id == project_id)).all()]
        ))
    if definition_id:
        runs_stmt = runs_stmt.where(WorkflowRun.definition_id == definition_id)
        steps_stmt = steps_stmt.where(WorkflowRunStep.definition_id == definition_id)
    runs = session.exec(runs_stmt).all()
    run_ids = [run.id for run in runs]
    steps = session.exec(steps_stmt.where(WorkflowRunStep.run_id.in_(run_ids))).all() if run_ids else []
    durations = [value for value in (workflow_duration_seconds(run) for run in runs) if value is not None]
    terminal = [run for run in runs if run.status in TERMINAL_STATUSES]
    failed = [run for run in runs if run.status == "failed"]
    completed = [run for run in runs if run.status == "completed"]
    by_trigger: dict[str, int] = {}
    for run in runs:
        by_trigger[run.trigger_type or "manual"] = by_trigger.get(run.trigger_type or "manual", 0) + 1
    step_failures: dict[str, int] = {}
    step_durations: dict[str, list[float]] = {}
    for step in steps:
        if step.status == "failed":
            step_failures[step.step_type] = step_failures.get(step.step_type, 0) + 1
        if step.started_at and step.completed_at:
            step_durations.setdefault(step.step_type, []).append(max(0, (step.completed_at - step.started_at).total_seconds()))
    return {
        "runs": len(runs),
        "active_runs": len([run for run in runs if run.status in ACTIVE_STATUSES]),
        "completed_runs": len(completed),
        "failed_runs": len(failed),
        "success_rate": round((len(completed) / len(terminal)) * 100, 1) if terminal else 0.0,
        "failure_rate": round((len(failed) / len(terminal)) * 100, 1) if terminal else 0.0,
        "duration_seconds": {
            "median": percentile(durations, 0.5),
            "p95": percentile(durations, 0.95),
        },
        "trigger_breakdown": by_trigger,
        "flakiest_steps": sorted(
            [{"step_type": step_type, "failures": count} for step_type, count in step_failures.items()],
            key=lambda item: item["failures"],
            reverse=True,
        )[:10],
        "slowest_steps": sorted(
            [
                {"step_type": step_type, "p95_duration_seconds": percentile(values, 0.95)}
                for step_type, values in step_durations.items()
            ],
            key=lambda item: item["p95_duration_seconds"] or 0,
            reverse=True,
        )[:10],
        "recent_failures": [_run_to_dict(run, session, include_steps=False) for run in failed[:10]],
    }


@router.get("/events")
def list_workflow_events(
    project_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    stmt = select(WorkflowEvent).order_by(col(WorkflowEvent.created_at).desc()).limit(limit)
    if project_id:
        stmt = stmt.where(WorkflowEvent.project_id == project_id)
    if run_id:
        stmt = stmt.where(WorkflowEvent.run_id == run_id)
    return [workflow_event_to_dict(event) for event in session.exec(stmt).all()]


@router.get("/notifications")
def list_workflow_notifications(
    project_id: str | None = Query(default=None),
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    stmt = select(WorkflowNotification).order_by(col(WorkflowNotification.created_at).desc()).limit(limit)
    if project_id:
        stmt = stmt.where(WorkflowNotification.project_id == project_id)
    if unread_only:
        stmt = stmt.where(WorkflowNotification.read_at == None)
    return [workflow_notification_to_dict(notification) for notification in session.exec(stmt).all()]


@router.post("/notifications/{notification_id}/read")
def mark_workflow_notification_read(notification_id: str, session: Session = Depends(get_session)):
    notification = session.get(WorkflowNotification, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read_at = datetime.utcnow()
    session.add(notification)
    session.commit()
    return workflow_notification_to_dict(notification)


@router.get("/schedules")
def list_workflow_schedules(
    project_id: str | None = Query(default=None),
    definition_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    stmt = select(WorkflowSchedule).order_by(col(WorkflowSchedule.created_at).desc())
    if project_id:
        stmt = stmt.where(WorkflowSchedule.project_id == project_id)
    if definition_id:
        stmt = stmt.where(WorkflowSchedule.definition_id == definition_id)
    return [workflow_schedule_to_dict(schedule) for schedule in session.exec(stmt).all()]


@router.post("/schedules")
async def create_workflow_schedule(
    request: WorkflowScheduleRequest,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    definition = _get_definition_or_404(request.definition_id, None, session)
    await _ensure_write_access(definition.project_id, user, session)
    next_run = _validate_cron(request.cron_expression, request.timezone)
    if request.start_step_key and not any(step.get("key") == request.start_step_key for step in definition.steps):
        raise HTTPException(status_code=400, detail=f"Workflow step not found: {request.start_step_key}")
    revision = ensure_workflow_revision(session, definition, created_by=getattr(user, "id", None))
    schedule = WorkflowSchedule(
        project_id=definition.project_id,
        definition_id=definition.id,
        revision_id=revision.id,
        name=request.name.strip(),
        description=request.description.strip(),
        cron_expression=request.cron_expression,
        timezone=request.timezone,
        start_step_key=request.start_step_key,
        enabled=request.enabled,
        next_run_at=next_run,
        notify_on_completion=request.notify_on_completion,
        notify_on_failure=request.notify_on_failure,
        notify_on_review_needed=request.notify_on_review_needed,
        created_by=getattr(user, "id", None),
    )
    schedule.inputs = request.inputs
    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    try:
        from orchestrator.services.scheduler import add_workflow_schedule_job

        add_workflow_schedule_job(schedule.id, schedule.cron_expression, schedule.timezone)
    except Exception as exc:
        schedule.status = "error"
        schedule.last_error = str(exc)
        session.add(schedule)
        session.commit()
    return workflow_schedule_to_dict(schedule)


@router.put("/schedules/{schedule_id}")
async def update_workflow_schedule(
    schedule_id: str,
    request: WorkflowScheduleUpdateRequest,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    schedule = session.get(WorkflowSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Workflow schedule not found")
    await _ensure_write_access(schedule.project_id, user, session)
    definition = _get_definition_or_404(schedule.definition_id, schedule.project_id, session)
    cron = request.cron_expression or schedule.cron_expression
    timezone = request.timezone or schedule.timezone
    schedule.next_run_at = _validate_cron(cron, timezone)
    if request.start_step_key and not any(step.get("key") == request.start_step_key for step in definition.steps):
        raise HTTPException(status_code=400, detail=f"Workflow step not found: {request.start_step_key}")
    for field in ("name", "description", "cron_expression", "timezone", "start_step_key"):
        value = getattr(request, field)
        if value is not None:
            setattr(schedule, field, value)
    for field in ("enabled", "notify_on_completion", "notify_on_failure", "notify_on_review_needed"):
        value = getattr(request, field)
        if value is not None:
            setattr(schedule, field, value)
    if request.inputs is not None:
        schedule.inputs = request.inputs
    schedule.updated_at = datetime.utcnow()
    schedule.status = "active" if schedule.enabled else "paused"
    schedule.last_error = None
    session.add(schedule)
    session.commit()
    try:
        from orchestrator.services.scheduler import add_workflow_schedule_job, pause_schedule_job

        if schedule.enabled:
            add_workflow_schedule_job(schedule.id, schedule.cron_expression, schedule.timezone)
        else:
            pause_schedule_job(schedule.id)
    except Exception as exc:
        schedule.status = "error"
        schedule.last_error = str(exc)
        session.add(schedule)
        session.commit()
    return workflow_schedule_to_dict(schedule)


@router.delete("/schedules/{schedule_id}")
async def delete_workflow_schedule(
    schedule_id: str,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    schedule = session.get(WorkflowSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Workflow schedule not found")
    await _ensure_write_access(schedule.project_id, user, session)
    try:
        from orchestrator.services.scheduler import remove_schedule_job

        remove_schedule_job(schedule.id)
    except Exception:
        pass
    executions = session.exec(select(WorkflowScheduleExecution).where(WorkflowScheduleExecution.schedule_id == schedule.id)).all()
    for execution in executions:
        session.delete(execution)
    events = session.exec(select(WorkflowEvent).where(WorkflowEvent.schedule_id == schedule.id)).all()
    for event in events:
        event.schedule_id = None
        session.add(event)
    session.flush()
    session.delete(schedule)
    session.commit()
    return {"status": "deleted", "id": schedule_id}


@router.post("/schedules/{schedule_id}/run-now")
async def run_workflow_schedule_now(
    schedule_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    schedule = session.get(WorkflowSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Workflow schedule not found")
    await _ensure_write_access(schedule.project_id, user, session)
    execution = WorkflowScheduleExecution(
        schedule_id=schedule.id,
        status="running",
        trigger_type="manual",
        started_at=datetime.utcnow(),
    )
    session.add(execution)
    session.commit()
    session.refresh(execution)
    try:
        from orchestrator.services.scheduler import execute_workflow_schedule

        background_tasks.add_task(execute_workflow_schedule, schedule.id, execution.id, "manual")
    except Exception as exc:
        execution.status = "failed"
        execution.error_message = str(exc)
        execution.completed_at = datetime.utcnow()
        session.add(execution)
        session.commit()
    return workflow_schedule_execution_to_dict(execution)


@router.get("/schedules/{schedule_id}/executions")
def list_workflow_schedule_executions(
    schedule_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
):
    if not session.get(WorkflowSchedule, schedule_id):
        raise HTTPException(status_code=404, detail="Workflow schedule not found")
    executions = session.exec(
        select(WorkflowScheduleExecution)
        .where(WorkflowScheduleExecution.schedule_id == schedule_id)
        .order_by(col(WorkflowScheduleExecution.created_at).desc())
        .limit(limit)
    ).all()
    return [workflow_schedule_execution_to_dict(execution) for execution in executions]


@router.get("/definitions")
def list_workflow_definitions(
    project_id: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    session: Session = Depends(get_session),
):
    stmt = select(WorkflowDefinition).order_by(WorkflowDefinition.updated_at.desc())
    if not include_archived:
        stmt = stmt.where(WorkflowDefinition.status == "active")
    if project_id:
        if project_id == "default":
            stmt = stmt.where((WorkflowDefinition.project_id == project_id) | (WorkflowDefinition.project_id == None))
        else:
            stmt = stmt.where(WorkflowDefinition.project_id == project_id)
    return [_definition_to_dict(item) for item in session.exec(stmt).all()]


@router.post("/definitions")
async def create_workflow_definition(
    request: WorkflowDefinitionRequest,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    await _ensure_write_access(request.project_id, user, session)
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Workflow name is required")
    try:
        sync_builtin_workflow_step_types(session)
        steps = validate_workflow_steps([step.model_dump() for step in request.steps], session=session, project_id=request.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    definition = WorkflowDefinition(
        project_id=request.project_id,
        name=request.name.strip(),
        description=request.description.strip(),
        created_by=getattr(user, "id", None),
    )
    definition.steps = steps
    session.add(definition)
    session.flush()
    create_workflow_revision(
        session,
        definition,
        change_summary="Initial workflow revision",
        created_by=getattr(user, "id", None),
        version=1,
    )
    session.commit()
    session.refresh(definition)
    return _definition_to_dict(definition)


@router.get("/definitions/{definition_id}")
def get_workflow_definition(
    definition_id: str,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    return _definition_to_dict(_get_definition_or_404(definition_id, project_id, session))


@router.get("/definitions/{definition_id}/export")
def export_workflow_definition(
    definition_id: str,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    return _definition_export(definition)


@router.post("/definitions/{definition_id}/duplicate")
async def duplicate_workflow_definition(
    definition_id: str,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    await _ensure_write_access(definition.project_id, user, session)
    clone = duplicate_workflow_definition_record(definition, created_by=getattr(user, "id", None))
    session.add(clone)
    session.flush()
    create_workflow_revision(
        session,
        clone,
        change_summary=f"Duplicated from {definition.name}",
        created_by=getattr(user, "id", None),
        version=1,
    )
    session.commit()
    session.refresh(clone)
    return _definition_to_dict(clone)


@router.get("/definitions/{definition_id}/runs")
def list_definition_runs(
    definition_id: str,
    project_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.definition_id == definition.id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    )
    return [_run_to_dict(run, session, include_steps=False) for run in session.exec(stmt).all()]


@router.get("/definitions/{definition_id}/revisions")
def list_definition_revisions(
    definition_id: str,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    ensure_workflow_revision(session, definition)
    session.commit()
    revisions = session.exec(
        select(WorkflowDefinitionRevision)
        .where(WorkflowDefinitionRevision.definition_id == definition.id)
        .order_by(col(WorkflowDefinitionRevision.version).desc())
    ).all()
    return [_revision_to_dict(revision) for revision in revisions]


@router.get("/definitions/{definition_id}/revisions/{version}")
def get_definition_revision(
    definition_id: str,
    version: int,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    revision = session.exec(
        select(WorkflowDefinitionRevision)
        .where(WorkflowDefinitionRevision.definition_id == definition.id)
        .where(WorkflowDefinitionRevision.version == version)
    ).first()
    if not revision:
        raise HTTPException(status_code=404, detail="Workflow revision not found")
    return _revision_to_dict(revision)


@router.post("/definitions/{definition_id}/revisions/{version}/rollback")
async def rollback_definition_revision(
    definition_id: str,
    version: int,
    request: WorkflowRollbackRequest,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    await _ensure_write_access(definition.project_id, user, session)
    revision = session.exec(
        select(WorkflowDefinitionRevision)
        .where(WorkflowDefinitionRevision.definition_id == definition.id)
        .where(WorkflowDefinitionRevision.version == version)
    ).first()
    if not revision:
        raise HTTPException(status_code=404, detail="Workflow revision not found")
    restored = restore_workflow_revision(session, definition, revision, created_by=getattr(user, "id", None))
    if request.change_summary:
        restored.change_summary = request.change_summary
        session.add(restored)
    session.commit()
    session.refresh(restored)
    return {"definition": _definition_to_dict(definition), "revision": _revision_to_dict(restored)}


@router.put("/definitions/{definition_id}")
async def update_workflow_definition(
    definition_id: str,
    request: WorkflowDefinitionUpdateRequest,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    await _ensure_write_access(definition.project_id, user, session)
    previous_steps = definition.steps

    if request.name is not None:
        if not request.name.strip():
            raise HTTPException(status_code=400, detail="Workflow name is required")
        definition.name = request.name.strip()
    if request.description is not None:
        definition.description = request.description.strip()
    if request.steps is not None:
        try:
            sync_builtin_workflow_step_types(session)
            next_steps = validate_workflow_steps(
                [step.model_dump() for step in request.steps],
                session=session,
                project_id=definition.project_id,
            )
            definition.steps = next_steps
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if request.status is not None:
        if request.status not in {"active", "archived"}:
            raise HTTPException(status_code=400, detail="Invalid workflow status")
        definition.status = request.status
    definition.updated_at = datetime.utcnow()
    session.add(definition)
    if request.steps is not None and json_changed(previous_steps, definition.steps):
        create_workflow_revision(
            session,
            definition,
            change_summary="Workflow steps updated",
            created_by=getattr(user, "id", None),
        )
    session.commit()
    session.refresh(definition)
    return _definition_to_dict(definition)


@router.delete("/definitions/{definition_id}")
async def archive_workflow_definition(
    definition_id: str,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    await _ensure_write_access(definition.project_id, user, session)
    definition.status = "archived"
    definition.updated_at = datetime.utcnow()
    session.add(definition)
    session.commit()
    return {"status": "archived", "id": definition.id}


@router.post("/definitions/{definition_id}/runs")
async def start_workflow_run(
    definition_id: str,
    request: WorkflowRunRequest,
    background_tasks: BackgroundTasks,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    await _ensure_write_access(definition.project_id, user, session)
    if request.start_step_key and not any(step.get("key") == request.start_step_key for step in definition.steps):
        raise HTTPException(status_code=400, detail=f"Workflow step not found: {request.start_step_key}")
    active_count = session.exec(
        select(WorkflowRun)
        .where(WorkflowRun.project_id == definition.project_id)
        .where(WorkflowRun.status.in_(list(ACTIVE_STATUSES)))
    ).all()
    if len(active_count) >= 10:
        raise HTTPException(status_code=429, detail="Too many active workflow runs for this project")

    revision = ensure_workflow_revision(session, definition, created_by=getattr(user, "id", None))
    recovery_policy = _validate_recovery_policy(request.recovery_policy, label="run recovery_policy")
    run = WorkflowRun(
        definition_id=definition.id,
        workflow_id=definition.id,
        revision_id=revision.id,
        definition_version=revision.version,
        project_id=definition.project_id,
        status="queued",
        triggered_by=request.triggered_by or getattr(user, "id", None) or "ui",
        trigger_type=request.trigger_type or ("assistant" if request.triggered_by == "chat" else "manual"),
        trigger_id=request.trigger_id,
    )
    run.inputs = request.inputs
    run.recovery_policy = recovery_policy
    session.add(run)
    session.commit()
    session.refresh(run)
    try:
        create_workflow_run_steps(session, definition, run, start_step_key=request.start_step_key, steps_override=revision.steps)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _launch_run_durably(run, background_tasks, session)
    return {"run_id": run.id, "status": run.status, "definition_id": definition.id}


@router.get("/runs")
def list_workflow_runs(
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    stmt = select(WorkflowRun).order_by(WorkflowRun.created_at.desc())
    if project_id:
        stmt = stmt.where(WorkflowRun.project_id == project_id)
    if status:
        stmt = stmt.where(WorkflowRun.status == status)
    runs = session.exec(stmt.limit(limit)).all()
    return [_run_to_dict(run, session, include_steps=False) for run in runs]


@router.get("/runs/{run_id}")
def get_workflow_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return _run_to_dict(run, session)


@router.get("/runs/{run_id}/steps")
def list_workflow_run_steps(run_id: str, session: Session = Depends(get_session)):
    if not session.get(WorkflowRun, run_id):
        raise HTTPException(status_code=404, detail="Workflow run not found")
    steps = session.exec(
        select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id).order_by(WorkflowRunStep.step_order)
    ).all()
    return [_step_to_dict(step) for step in steps]


@router.post("/runs/{run_id}/steps/{step_id}/retry")
async def retry_workflow_run_step(run_id: str, step_id: int, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    step = session.get(WorkflowRunStep, step_id)
    if not step or step.run_id != run_id:
        raise HTTPException(status_code=404, detail="Workflow run step not found")
    try:
        reset_workflow_run_for_step_retry(session, run, step)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await _launch_run_durably(run, background_tasks, session)
    return {"run_id": run.id, "step_id": step.id, "status": "queued"}


@router.post("/runs/{run_id}/pause")
async def pause_workflow_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Cannot pause a terminal workflow run")
    run.status = "paused"
    run.pause_reason = "manual_pause"
    run.updated_at = datetime.utcnow()
    session.add(run)
    steps = session.exec(
        select(WorkflowRunStep)
        .where(WorkflowRunStep.run_id == run_id)
        .where(WorkflowRunStep.status.in_(["running"]))
    ).all()
    for step in steps:
        step.status = "paused"
        step.updated_at = datetime.utcnow()
        session.add(step)
    session.commit()
    if run.temporal_workflow_id:
        try:
            await signal_custom_workflow_run(run.temporal_workflow_id, "pause", "manual_pause")
        except Exception:
            pass
    return {"run_id": run.id, "status": run.status}


@router.post("/runs/{run_id}/resume")
async def resume_workflow_run(run_id: str, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Cannot resume a terminal workflow run")
    if run.status == "awaiting_input":
        steps = session.exec(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id)).all()
        for step in steps:
            if step.status == "awaiting_input":
                step.status = "completed"
                step.completed_at = datetime.utcnow()
                step.updated_at = datetime.utcnow()
                session.add(step)
            elif step.status == "paused":
                step.status = "pending"
                step.started_at = None
                step.updated_at = datetime.utcnow()
                session.add(step)
    elif run.status == "paused":
        steps = session.exec(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id)).all()
        for step in steps:
            if step.status == "paused":
                step.status = "pending"
                step.started_at = None
                step.updated_at = datetime.utcnow()
                session.add(step)
    run.status = "queued"
    run.pause_reason = None
    run.updated_at = datetime.utcnow()
    session.add(run)
    session.commit()
    if run.temporal_workflow_id:
        try:
            await signal_custom_workflow_run(run.temporal_workflow_id, "resume")
            return {"run_id": run.id, "status": "running"}
        except Exception:
            pass
    await _launch_run_durably(run, background_tasks, session)
    return {"run_id": run.id, "status": "running"}


@router.post("/runs/{run_id}/cancel")
async def cancel_workflow_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Workflow run is already terminal")
    run.status = "cancelled"
    run.completed_at = datetime.utcnow()
    run.updated_at = datetime.utcnow()
    steps = session.exec(
        select(WorkflowRunStep)
        .where(WorkflowRunStep.run_id == run_id)
        .where(WorkflowRunStep.status.in_(["pending", "running", "awaiting_input", "paused"]))
    ).all()
    for step in steps:
        step.status = "cancelled"
        step.completed_at = datetime.utcnow()
        step.updated_at = datetime.utcnow()
        session.add(step)
    session.add(run)
    emit_workflow_event(
        session,
        event_type="workflow.cancelled",
        message=f"Workflow run {run.id} was cancelled.",
        severity="warning",
        run=run,
    )
    session.commit()
    if run.temporal_workflow_id:
        try:
            await signal_custom_workflow_run(run.temporal_workflow_id, "cancel", "manual_cancel")
        except Exception:
            pass
    return {"run_id": run.id, "status": run.status}


@router.post("/runs/{run_id}/steps/{step_id}/skip")
async def skip_workflow_run_step(run_id: str, step_id: int, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    step = session.get(WorkflowRunStep, step_id)
    if not step or step.run_id != run_id:
        raise HTTPException(status_code=404, detail="Workflow run step not found")
    if step.status not in {"failed", "pending", "running", "awaiting_input"}:
        raise HTTPException(status_code=409, detail=f"Cannot skip a {step.status} step")
    step.status = "skipped"
    step.skipped_reason = "manual_skip"
    step.output = {"skipped": True, "reason": "manual_skip"}
    step.completed_at = datetime.utcnow()
    step.updated_at = datetime.utcnow()
    run.context = {**run.context, "steps": {**(run.context.get("steps") or {}), step.step_key: step.output or {}}}
    if run.status in {"failed", "awaiting_input", "paused"}:
        run.status = "queued"
        run.completed_at = None
        run.error_message = None
    run.updated_at = datetime.utcnow()
    session.add(step)
    session.add(run)
    emit_workflow_event(
        session,
        event_type="workflow.step_skipped",
        message=f"Workflow step {step.step_key} was skipped.",
        severity="warning",
        run=run,
        step_id=step.id,
        notify=True,
    )
    session.commit()
    await _launch_run_durably(run, background_tasks, session)
    return {"run_id": run.id, "step_id": step.id, "status": "queued"}
