"""
Scheduling API — Cron schedule CRUD, execution history, and management.

Stores schedule configurations in the CronSchedule table. APScheduler handles
the actual cron timing, while this router provides the management interface.
"""

import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, col, select

from .db import get_session
from .middleware.auth import get_current_user_optional
from .models_auth import User
from .models_db import CronSchedule, Project, ScheduleExecution

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scheduling", tags=["scheduling"])


# ── Request / Response Models ──────────────────────────────────


class ScheduleCreateRequest(BaseModel):
    name: str
    description: str | None = None
    cron_expression: str  # 5-field: "0 8 * * 1-5"
    timezone: str = "UTC"
    tags: list[str] | None = None
    automated_only: bool = True
    browser: str = "chromium"
    hybrid_mode: bool = False
    max_iterations: int = 20
    spec_names: list[str] | None = None
    enabled: bool = True


class ScheduleUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    tags: list[str] | None = None
    automated_only: bool | None = None
    browser: str | None = None
    hybrid_mode: bool | None = None
    max_iterations: int | None = None
    spec_names: list[str] | None = None
    enabled: bool | None = None


class ValidateCronRequest(BaseModel):
    cron_expression: str
    timezone: str = "UTC"


class ValidateCronResponse(BaseModel):
    valid: bool
    error: str | None = None
    human_readable: str | None = None
    next_runs: list[str] = []


class ScheduleResponse(BaseModel):
    id: str
    project_id: str | None
    name: str
    description: str | None
    cron_expression: str
    timezone: str
    tags: list[str]
    automated_only: bool
    browser: str
    hybrid_mode: bool
    max_iterations: int
    spec_names: list[str]
    enabled: bool
    status: str
    last_error: str | None
    last_run_at: str | None
    last_batch_id: str | None
    last_run_status: str | None
    total_executions: int
    successful_executions: int
    failed_executions: int
    avg_duration_seconds: float | None
    success_rate: float
    next_run_at: str | None
    created_by: str | None
    created_at: str
    updated_at: str


class ExecutionResponse(BaseModel):
    id: int
    schedule_id: str
    batch_id: str | None
    status: str
    trigger_type: str
    total_tests: int
    passed: int
    failed: int
    duration_seconds: int | None
    error_message: str | None
    started_at: str | None
    completed_at: str | None
    created_at: str


# ── Helpers ────────────────────────────────────────────────────


def _require_project(project_id: str, session: Session) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _schedule_to_response(schedule: CronSchedule) -> dict:
    """Convert a CronSchedule model to a response dict."""
    from orchestrator.services.scheduler import get_next_run_time

    next_run = get_next_run_time(schedule.id, schedule.cron_expression, schedule.timezone)

    return {
        "id": schedule.id,
        "project_id": schedule.project_id,
        "name": schedule.name,
        "description": schedule.description,
        "cron_expression": schedule.cron_expression,
        "timezone": schedule.timezone,
        "tags": schedule.tags,
        "automated_only": schedule.automated_only,
        "browser": schedule.browser,
        "hybrid_mode": schedule.hybrid_mode,
        "max_iterations": schedule.max_iterations,
        "spec_names": schedule.spec_names,
        "enabled": schedule.enabled,
        "status": schedule.status,
        "last_error": schedule.last_error,
        "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
        "last_batch_id": schedule.last_batch_id,
        "last_run_status": schedule.last_run_status,
        "total_executions": schedule.total_executions,
        "successful_executions": schedule.successful_executions,
        "failed_executions": schedule.failed_executions,
        "avg_duration_seconds": schedule.avg_duration_seconds,
        "success_rate": schedule.success_rate,
        "next_run_at": next_run.isoformat() if next_run else None,
        "created_by": schedule.created_by,
        "created_at": schedule.created_at.isoformat(),
        "updated_at": schedule.updated_at.isoformat(),
    }


def _cron_to_human(expr: str) -> str:
    """Convert a 5-field cron expression to a human-readable string."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return expr

    minute, hour, dom, month, dow = parts

    # Common patterns
    if dom == "*" and month == "*":
        time_str = ""
        if minute == "0" and hour != "*":
            time_str = f"at {hour.zfill(2)}:00"
        elif minute != "*" and hour != "*":
            time_str = f"at {hour.zfill(2)}:{minute.zfill(2)}"
        elif minute == "0" and hour == "*":
            time_str = "every hour"
        elif hour == "*" and minute.startswith("*/"):
            return f"Every {minute[2:]} minutes"
        elif hour.startswith("*/"):
            return f"Every {hour[2:]} hours"
        else:
            time_str = f"at minute {minute} of hour {hour}"

        dow_map = {
            "0": "Sunday",
            "1": "Monday",
            "2": "Tuesday",
            "3": "Wednesday",
            "4": "Thursday",
            "5": "Friday",
            "6": "Saturday",
            "1-5": "weekday",
            "0-6": "day",
            "*": "day",
        }

        if dow in dow_map:
            day_str = dow_map[dow]
            if day_str == "day":
                return f"Every day {time_str}"
            elif day_str == "weekday":
                return f"Every weekday {time_str}"
            else:
                return f"Every {day_str} {time_str}"
        else:
            return f"On day-of-week {dow} {time_str}"

    return expr


# ── Endpoints ──────────────────────────────────────────────────


@router.get("/{project_id}/schedules")
def list_schedules(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List all schedules for a project."""
    _require_project(project_id, session)

    schedules = session.exec(
        select(CronSchedule).where(CronSchedule.project_id == project_id).order_by(col(CronSchedule.created_at).desc())
    ).all()

    return [_schedule_to_response(s) for s in schedules]


@router.post("/{project_id}/schedules")
def create_schedule(
    project_id: str,
    req: ScheduleCreateRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Create a new schedule."""
    from orchestrator.services.scheduler import add_schedule_job, get_next_n_run_times

    _require_project(project_id, session)

    # Validate cron expression
    try:
        get_next_n_run_times(req.cron_expression, req.timezone, count=1)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    schedule_id = f"sched-{uuid.uuid4().hex[:8]}"

    schedule = CronSchedule(
        id=schedule_id,
        project_id=project_id,
        name=req.name,
        description=req.description,
        cron_expression=req.cron_expression,
        timezone=req.timezone,
        tags_json=json.dumps(req.tags or []),
        automated_only=req.automated_only,
        browser=req.browser,
        hybrid_mode=req.hybrid_mode,
        max_iterations=req.max_iterations,
        spec_names_json=json.dumps(req.spec_names or []),
        enabled=req.enabled,
        status="active" if req.enabled else "paused",
        created_by=current_user.email if current_user else None,
    )
    session.add(schedule)
    session.commit()
    session.refresh(schedule)

    # Register with APScheduler if enabled
    if schedule.enabled:
        try:
            add_schedule_job(schedule_id, req.cron_expression, req.timezone)
        except Exception as e:
            logger.error(f"Failed to register job: {e}")
            schedule.status = "error"
            schedule.last_error = str(e)
            session.add(schedule)
            session.commit()

    return _schedule_to_response(schedule)


@router.get("/{project_id}/schedules/{schedule_id}")
def get_schedule(
    project_id: str,
    schedule_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Get schedule details."""
    schedule = session.get(CronSchedule, schedule_id)
    if not schedule or schedule.project_id != project_id:
        raise HTTPException(status_code=404, detail="Schedule not found")

    return _schedule_to_response(schedule)


@router.put("/{project_id}/schedules/{schedule_id}")
def update_schedule(
    project_id: str,
    schedule_id: str,
    req: ScheduleUpdateRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Update an existing schedule."""
    from orchestrator.services.scheduler import add_schedule_job, get_next_n_run_times, remove_schedule_job

    schedule = session.get(CronSchedule, schedule_id)
    if not schedule or schedule.project_id != project_id:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Validate cron if changing
    tz = req.timezone or schedule.timezone
    if req.cron_expression:
        try:
            get_next_n_run_times(req.cron_expression, tz, count=1)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Apply updates
    if req.name is not None:
        schedule.name = req.name
    if req.description is not None:
        schedule.description = req.description
    if req.cron_expression is not None:
        schedule.cron_expression = req.cron_expression
    if req.timezone is not None:
        schedule.timezone = req.timezone
    if req.tags is not None:
        schedule.tags_json = json.dumps(req.tags)
    if req.automated_only is not None:
        schedule.automated_only = req.automated_only
    if req.browser is not None:
        schedule.browser = req.browser
    if req.hybrid_mode is not None:
        schedule.hybrid_mode = req.hybrid_mode
    if req.max_iterations is not None:
        schedule.max_iterations = req.max_iterations
    if req.spec_names is not None:
        schedule.spec_names_json = json.dumps(req.spec_names)
    if req.enabled is not None:
        schedule.enabled = req.enabled
        schedule.status = "active" if req.enabled else "paused"

    schedule.updated_at = datetime.utcnow()
    session.add(schedule)
    session.commit()

    # Update APScheduler job
    if schedule.enabled:
        try:
            add_schedule_job(schedule.id, schedule.cron_expression, schedule.timezone)
            schedule.last_error = None
            schedule.status = "active"
        except Exception as e:
            schedule.status = "error"
            schedule.last_error = str(e)
    else:
        remove_schedule_job(schedule.id)

    session.add(schedule)
    session.commit()
    session.refresh(schedule)

    return _schedule_to_response(schedule)


@router.delete("/{project_id}/schedules/{schedule_id}")
def delete_schedule(
    project_id: str,
    schedule_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Delete a schedule and its APScheduler job."""
    from orchestrator.services.scheduler import remove_schedule_job

    schedule = session.get(CronSchedule, schedule_id)
    if not schedule or schedule.project_id != project_id:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Remove APScheduler job
    remove_schedule_job(schedule_id)

    # Delete executions first, then flush to satisfy FK constraints
    executions = session.exec(select(ScheduleExecution).where(ScheduleExecution.schedule_id == schedule_id)).all()
    for ex in executions:
        session.delete(ex)
    session.flush()  # Ensure child rows are deleted before parent

    session.delete(schedule)
    session.commit()

    return {"status": "deleted", "id": schedule_id}


@router.post("/{project_id}/schedules/{schedule_id}/toggle")
def toggle_schedule(
    project_id: str,
    schedule_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Toggle a schedule on/off."""
    from orchestrator.services.scheduler import add_schedule_job, remove_schedule_job

    schedule = session.get(CronSchedule, schedule_id)
    if not schedule or schedule.project_id != project_id:
        raise HTTPException(status_code=404, detail="Schedule not found")

    schedule.enabled = not schedule.enabled
    schedule.status = "active" if schedule.enabled else "paused"
    schedule.updated_at = datetime.utcnow()

    if schedule.enabled:
        try:
            add_schedule_job(schedule.id, schedule.cron_expression, schedule.timezone)
        except Exception as e:
            schedule.status = "error"
            schedule.last_error = str(e)
    else:
        remove_schedule_job(schedule.id)

    session.add(schedule)
    session.commit()

    return _schedule_to_response(schedule)


async def _run_schedule_now_task(schedule_id: str, execution_id: int):
    """Wrapper to run _execute_scheduled_batch as a background task."""
    from orchestrator.services.scheduler import _execute_scheduled_batch

    await _execute_scheduled_batch(schedule_id, execution_id=execution_id)


@router.post("/{project_id}/schedules/{schedule_id}/run-now")
async def run_schedule_now(
    project_id: str,
    schedule_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Trigger an immediate execution of a schedule."""
    schedule = session.get(CronSchedule, schedule_id)
    if not schedule or schedule.project_id != project_id:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Create execution record
    execution = ScheduleExecution(
        schedule_id=schedule_id,
        status="pending",
        trigger_type="manual",
    )
    session.add(execution)
    session.commit()
    session.refresh(execution)

    # Run in background
    background_tasks.add_task(_run_schedule_now_task, schedule_id, execution.id)

    return {
        "status": "triggered",
        "execution_id": execution.id,
        "schedule_id": schedule_id,
    }


@router.get("/{project_id}/schedules/{schedule_id}/executions")
def list_executions(
    project_id: str,
    schedule_id: str,
    limit: int = 20,
    offset: int = 0,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List execution history for a schedule."""
    schedule = session.get(CronSchedule, schedule_id)
    if not schedule or schedule.project_id != project_id:
        raise HTTPException(status_code=404, detail="Schedule not found")

    total = session.exec(select(ScheduleExecution).where(ScheduleExecution.schedule_id == schedule_id)).all()

    executions = session.exec(
        select(ScheduleExecution)
        .where(ScheduleExecution.schedule_id == schedule_id)
        .order_by(col(ScheduleExecution.created_at).desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return {
        "total": len(total),
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": ex.id,
                "schedule_id": ex.schedule_id,
                "batch_id": ex.batch_id,
                "status": ex.status,
                "trigger_type": ex.trigger_type,
                "total_tests": ex.total_tests,
                "passed": ex.passed,
                "failed": ex.failed,
                "duration_seconds": ex.duration_seconds,
                "error_message": ex.error_message,
                "started_at": ex.started_at.isoformat() if ex.started_at else None,
                "completed_at": ex.completed_at.isoformat() if ex.completed_at else None,
                "created_at": ex.created_at.isoformat(),
            }
            for ex in executions
        ],
    }


@router.get("/{project_id}/executions")
def list_project_executions(
    project_id: str,
    limit: int = 15,
    offset: int = 0,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List all execution history for all schedules in a project."""
    _require_project(project_id, session)

    # Get all schedule IDs for this project
    schedules = session.exec(select(CronSchedule).where(CronSchedule.project_id == project_id)).all()
    schedule_map = {s.id: s.name for s in schedules}
    schedule_ids = list(schedule_map.keys())

    if not schedule_ids:
        return {"executions": [], "total": 0}

    all_executions = session.exec(
        select(ScheduleExecution).where(col(ScheduleExecution.schedule_id).in_(schedule_ids))
    ).all()
    total = len(all_executions)

    executions = session.exec(
        select(ScheduleExecution)
        .where(col(ScheduleExecution.schedule_id).in_(schedule_ids))
        .order_by(col(ScheduleExecution.created_at).desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return {
        "executions": [
            {
                "id": ex.id,
                "schedule_id": ex.schedule_id,
                "schedule_name": schedule_map.get(ex.schedule_id),
                "batch_id": ex.batch_id,
                "status": ex.status,
                "trigger_type": ex.trigger_type,
                "total_tests": ex.total_tests,
                "passed": ex.passed,
                "failed": ex.failed,
                "duration_seconds": ex.duration_seconds,
                "error_message": ex.error_message,
                "started_at": ex.started_at.isoformat() if ex.started_at else None,
                "completed_at": ex.completed_at.isoformat() if ex.completed_at else None,
                "created_at": ex.created_at.isoformat(),
            }
            for ex in executions
        ],
        "total": total,
    }


@router.get("/{project_id}/schedules/{schedule_id}/next-runs")
def get_next_runs(
    project_id: str,
    schedule_id: str,
    count: int = 5,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Get the next N fire times for a schedule."""
    from orchestrator.services.scheduler import get_next_n_run_times

    schedule = session.get(CronSchedule, schedule_id)
    if not schedule or schedule.project_id != project_id:
        raise HTTPException(status_code=404, detail="Schedule not found")

    try:
        times = get_next_n_run_times(schedule.cron_expression, schedule.timezone, count=count)
        return {
            "schedule_id": schedule_id,
            "cron_expression": schedule.cron_expression,
            "timezone": schedule.timezone,
            "next_runs": [t.isoformat() for t in times],
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/validate-cron")
def validate_cron(
    req: ValidateCronRequest,
    current_user: User | None = Depends(get_current_user_optional),
):
    """Validate a cron expression and return next 5 fire times."""
    from orchestrator.services.scheduler import get_next_n_run_times

    try:
        times = get_next_n_run_times(req.cron_expression, req.timezone, count=5)
        return ValidateCronResponse(
            valid=True,
            human_readable=_cron_to_human(req.cron_expression),
            next_runs=[t.isoformat() for t in times],
        )
    except ValueError as e:
        return ValidateCronResponse(
            valid=False,
            error=str(e),
        )
