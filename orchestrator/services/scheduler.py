"""
Cron Scheduler Service - APScheduler-based job scheduling for regression batches.

Uses AsyncIOScheduler with SQLAlchemyJobStore for persistence across restarts.
Jobs are coalesced (missed runs merge) and limited to 1 instance per schedule.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler | None:
    """Get the global scheduler instance."""
    return _scheduler


def init_scheduler(engine) -> AsyncIOScheduler:
    """Initialize the scheduler with SQLAlchemy-backed job store.

    Args:
        engine: SQLAlchemy engine for persisting jobs.

    Returns:
        The running AsyncIOScheduler instance.
    """
    global _scheduler

    if _scheduler and _scheduler.running:
        logger.warning("Scheduler already running, returning existing instance")
        return _scheduler

    jobstores = {
        "default": SQLAlchemyJobStore(engine=engine, tablename="apscheduler_jobs"),
    }

    job_defaults = {
        "coalesce": True,  # Merge missed runs into one
        "max_instances": 1,  # No overlapping executions per schedule
        "misfire_grace_time": 300,  # 5 minutes grace for misfires
    }

    _scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        job_defaults=job_defaults,
        timezone="UTC",
    )

    # Listen for job errors and missed events
    _scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
    _scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)

    _scheduler.start()
    logger.info("APScheduler started with SQLAlchemy job store")

    return _scheduler


def shutdown_scheduler():
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down")
    _scheduler = None


def add_schedule_job(schedule_id: str, cron_expression: str, timezone_str: str = "UTC"):
    """Add or replace a cron job for a schedule.

    Args:
        schedule_id: Unique schedule identifier (used as job ID).
        cron_expression: 5-field cron expression (minute hour day month dow).
        timezone_str: IANA timezone name.
    """
    if not _scheduler:
        logger.error("Scheduler not initialized, cannot add job")
        return

    parts = cron_expression.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: expected 5 fields, got {len(parts)}")

    trigger = CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=parts[4],
        timezone=timezone_str,
    )

    # Replace existing job if any
    _scheduler.add_job(
        _execute_scheduled_batch,
        trigger=trigger,
        id=schedule_id,
        args=[schedule_id],
        replace_existing=True,
        name=f"schedule:{schedule_id}",
    )
    logger.info(f"Added/updated cron job for schedule {schedule_id}: {cron_expression} ({timezone_str})")


def add_workflow_schedule_job(schedule_id: str, cron_expression: str, timezone_str: str = "UTC"):
    """Add or replace a cron job for a custom workflow schedule."""
    if not _scheduler:
        raise RuntimeError("Scheduler not initialized, cannot add workflow schedule job")

    parts = cron_expression.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: expected 5 fields, got {len(parts)}")

    trigger = CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=parts[4],
        timezone=timezone_str,
    )
    _scheduler.add_job(
        execute_workflow_schedule,
        trigger=trigger,
        id=schedule_id,
        args=[schedule_id, None, "schedule"],
        replace_existing=True,
        name=f"workflow-schedule:{schedule_id}",
    )
    logger.info("Added/updated custom workflow schedule %s: %s (%s)", schedule_id, cron_expression, timezone_str)


def remove_schedule_job(schedule_id: str):
    """Remove a scheduled job."""
    if not _scheduler:
        return
    try:
        _scheduler.remove_job(schedule_id)
        logger.info(f"Removed cron job for schedule {schedule_id}")
    except Exception:
        logger.debug(f"Job {schedule_id} not found for removal (may not exist)")


def pause_schedule_job(schedule_id: str):
    """Pause a scheduled job."""
    if not _scheduler:
        return
    try:
        _scheduler.pause_job(schedule_id)
        logger.info(f"Paused cron job for schedule {schedule_id}")
    except Exception:
        logger.debug(f"Job {schedule_id} not found for pause")


def resume_schedule_job(schedule_id: str):
    """Resume a paused scheduled job."""
    if not _scheduler:
        return
    try:
        _scheduler.resume_job(schedule_id)
        logger.info(f"Resumed cron job for schedule {schedule_id}")
    except Exception:
        logger.debug(f"Job {schedule_id} not found for resume")


def get_next_run_time(schedule_id: str, cron_expression: str = None, timezone_str: str = "UTC") -> datetime | None:
    """Get the next fire time for a scheduled job.

    Falls back to computing from cron_expression if APScheduler can't provide it.
    """
    if _scheduler:
        try:
            job = _scheduler.get_job(schedule_id)
            if job and job.next_run_time:
                return job.next_run_time
        except Exception:
            pass

    # Fallback: compute from cron expression directly
    if cron_expression:
        try:
            times = get_next_n_run_times(cron_expression, timezone_str, count=1)
            if times:
                return times[0]
        except Exception:
            pass

    return None


def get_next_n_run_times(cron_expression: str, timezone_str: str = "UTC", count: int = 5) -> list[datetime]:
    """Compute the next N fire times for a cron expression without adding a job.

    Args:
        cron_expression: 5-field cron expression.
        timezone_str: IANA timezone name.
        count: Number of fire times to compute.

    Returns:
        List of datetime objects for the next N fire times.
    """
    parts = cron_expression.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: expected 5 fields, got {len(parts)}")

    try:
        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
            timezone=timezone_str,
        )
    except Exception as e:
        raise ValueError(f"Invalid cron expression: {e}")

    times = []
    next_time = datetime.now(timezone.utc)
    for _ in range(count):
        next_time = trigger.get_next_fire_time(None, next_time)
        if next_time is None:
            break
        times.append(next_time)
        # Move slightly past to get the next one
        next_time = next_time + timedelta(seconds=1)

    return times


async def execute_workflow_schedule(schedule_id: str, execution_id: int | None = None, trigger_type: str = "schedule"):
    """Execute a custom workflow schedule by creating and launching a workflow run."""
    from sqlmodel import Session

    from orchestrator.api.db import engine
    from orchestrator.api.models_db import (
        WorkflowDefinition,
        WorkflowDefinitionRevision,
        WorkflowRun,
        WorkflowSchedule,
        WorkflowScheduleExecution,
    )
    from orchestrator.services.temporal_client import start_custom_workflow_run
    from orchestrator.services.workflow_operations import emit_workflow_event, ensure_workflow_revision
    from orchestrator.services.workflow_runner import create_workflow_run_steps

    logger.info("Executing custom workflow schedule %s", schedule_id)
    with Session(engine) as session:
        schedule = session.get(WorkflowSchedule, schedule_id)
        if not schedule:
            logger.error("Workflow schedule %s not found", schedule_id)
            return
        if not schedule.enabled and trigger_type != "manual":
            logger.info("Workflow schedule %s is disabled, skipping", schedule_id)
            if execution_id is not None:
                execution = session.get(WorkflowScheduleExecution, execution_id)
                if execution:
                    execution.status = "skipped"
                    execution.error_message = "Schedule is disabled"
                    execution.completed_at = datetime.now(timezone.utc)
                    session.add(execution)
                    emit_workflow_event(
                        session,
                        event_type="workflow.schedule_execution_skipped",
                        message=f"Workflow schedule {schedule.name} execution was skipped because the schedule is disabled.",
                        severity="warning",
                        schedule=schedule,
                        payload={
                            "execution_id": execution.id,
                            "trigger_type": trigger_type,
                            "reason": "schedule_disabled",
                        },
                        notify=False,
                    )
                    session.commit()
            return
        definition = session.get(WorkflowDefinition, schedule.definition_id)
        if not definition or definition.status == "archived":
            schedule.status = "error"
            schedule.last_error = "Workflow definition not found"
            session.add(schedule)
            session.commit()
            return
        if execution_id is None:
            execution = WorkflowScheduleExecution(
                schedule_id=schedule.id,
                status="running",
                trigger_type=trigger_type,
                started_at=datetime.now(timezone.utc),
            )
            session.add(execution)
            session.commit()
            session.refresh(execution)
            execution_id = execution.id
        else:
            execution = session.get(WorkflowScheduleExecution, execution_id)
            if execution:
                execution.status = "running"
                execution.started_at = execution.started_at or datetime.now(timezone.utc)
                session.add(execution)
                session.commit()

        revision = None
        if schedule.revision_mode == "pinned":
            revision = session.get(WorkflowDefinitionRevision, schedule.revision_id) if schedule.revision_id else None
        if not revision or revision.definition_id != definition.id:
            revision = ensure_workflow_revision(session, definition)
            if schedule.revision_mode == "pinned":
                schedule.revision_id = revision.id
                session.add(schedule)
        run = WorkflowRun(
            definition_id=definition.id,
            workflow_id=definition.id,
            revision_id=revision.id,
            definition_version=revision.version,
            project_id=definition.project_id,
            status="queued",
            triggered_by=f"schedule:{schedule.id}",
            trigger_type="schedule",
            trigger_id=schedule.id,
        )
        run.inputs = schedule.inputs
        session.add(run)
        session.commit()
        session.refresh(run)
        create_workflow_run_steps(session, definition, run, start_step_key=schedule.start_step_key, steps_override=revision.steps)
        execution = session.get(WorkflowScheduleExecution, execution_id)
        if execution:
            execution.workflow_run_id = run.id
            session.add(execution)
        schedule.last_run_at = datetime.now(timezone.utc)
        schedule.last_run_id = run.id
        schedule.total_executions += 1
        schedule.last_error = None
        schedule.status = "active"
        session.add(schedule)
        emit_workflow_event(
            session,
            event_type="workflow.schedule_started",
            message=f"Workflow schedule {schedule.name} started run {run.id}.",
            run=run,
            schedule=schedule,
            payload={
                "execution_id": execution_id,
                "run_id": run.id,
                "trigger_type": trigger_type,
                "revision_id": revision.id,
                "definition_version": revision.version,
            },
            notify=False,
        )
        session.commit()
        run_id = run.id

    try:
        temporal = await start_custom_workflow_run(run_id)
        with Session(engine) as session:
            run = session.get(WorkflowRun, run_id)
            if run:
                run.temporal_workflow_id = temporal.workflow_id
                run.temporal_run_id = temporal.run_id
                session.add(run)
                session.commit()
    except Exception as exc:
        error_message = str(exc)
        with Session(engine) as session:
            run = session.get(WorkflowRun, run_id)
            schedule = session.get(WorkflowSchedule, schedule_id)
            execution = session.get(WorkflowScheduleExecution, execution_id) if execution_id is not None else None
            if run:
                run.status = "failed"
                run.error_message = error_message
                run.completed_at = datetime.now(timezone.utc)
                run.updated_at = datetime.now(timezone.utc)
                session.add(run)
                emit_workflow_event(
                    session,
                    event_type="workflow.temporal_start_failed",
                    message=f"Temporal failed to start workflow run {run.id}: {error_message}",
                    severity="error",
                    run=run,
                    payload={"execution_id": execution_id, "temporal_error": error_message},
                    notify=True,
                )
            if execution:
                execution.status = "failed"
                execution.completed_at = datetime.now(timezone.utc)
                execution.error_message = error_message
                session.add(execution)
            if schedule:
                schedule.last_run_status = "failed"
                schedule.last_error = error_message
                schedule.failed_executions += 1
                session.add(schedule)
                emit_workflow_event(
                    session,
                    event_type="workflow.schedule_failed",
                    message=f"Workflow schedule {schedule.name} run failed: {error_message}",
                    severity="error",
                    run=run,
                    schedule=schedule,
                    payload={"execution_id": execution_id, "run_id": run_id, "trigger_type": trigger_type, "temporal_error": error_message},
                    notify=schedule.notify_on_failure,
                )
            session.commit()
        return

    asyncio.create_task(_monitor_workflow_schedule_execution(schedule_id, execution_id, run_id))


async def _monitor_workflow_schedule_execution(schedule_id: str, execution_id: int | None, run_id: str):
    from sqlmodel import Session, select

    from orchestrator.api.db import engine
    from orchestrator.api.models_db import WorkflowEvent, WorkflowRun, WorkflowSchedule, WorkflowScheduleExecution
    from orchestrator.services.workflow_operations import avg_duration, emit_workflow_event, workflow_duration_seconds

    if execution_id is None:
        return
    deadline = datetime.now(timezone.utc) + timedelta(hours=12)
    terminal = {"completed", "failed", "cancelled"}
    while datetime.now(timezone.utc) < deadline:
        with Session(engine) as session:
            run = session.get(WorkflowRun, run_id)
            if run and run.status in {"awaiting_input", "paused"}:
                execution = session.get(WorkflowScheduleExecution, execution_id)
                schedule = session.get(WorkflowSchedule, schedule_id)
                if schedule:
                    existing_review_event = session.exec(
                        select(WorkflowEvent)
                        .where(WorkflowEvent.schedule_id == schedule_id)
                        .where(WorkflowEvent.run_id == run_id)
                        .where(WorkflowEvent.event_type == "workflow.schedule_review_needed")
                    ).first()
                    schedule.last_run_status = run.status
                    session.add(schedule)
                    if not existing_review_event:
                        emit_workflow_event(
                            session,
                            event_type="workflow.schedule_review_needed",
                            message=f"Workflow schedule {schedule.name} run needs review.",
                            severity="warning",
                            run=run,
                            schedule=schedule,
                            payload={
                                "execution_id": execution_id,
                                "run_id": run.id,
                                "trigger_type": execution.trigger_type if execution else None,
                                "duration_seconds": workflow_duration_seconds(run),
                            },
                            notify=schedule.notify_on_review_needed,
                        )
                if execution:
                    execution.status = "running"
                    session.add(execution)
                session.commit()
            if run and run.status in terminal:
                execution = session.get(WorkflowScheduleExecution, execution_id)
                schedule = session.get(WorkflowSchedule, schedule_id)
                duration = workflow_duration_seconds(run)
                if execution:
                    execution.status = "completed" if run.status == "completed" else "failed"
                    execution.completed_at = datetime.now(timezone.utc)
                    execution.duration_seconds = duration
                    execution.error_message = run.error_message
                    session.add(execution)
                if schedule:
                    schedule.last_run_status = run.status
                    if run.status == "completed":
                        schedule.successful_executions += 1
                    else:
                        schedule.failed_executions += 1
                    schedule.avg_duration_seconds = avg_duration(schedule.avg_duration_seconds, duration)
                    if run.status == "completed":
                        emit_workflow_event(
                            session,
                            event_type="workflow.schedule_completed",
                            message=f"Workflow schedule {schedule.name} run completed.",
                            run=run,
                            schedule=schedule,
                            payload={
                                "execution_id": execution_id,
                                "run_id": run.id,
                                "trigger_type": execution.trigger_type if execution else None,
                                "duration_seconds": duration,
                            },
                            notify=schedule.notify_on_completion,
                        )
                    else:
                        schedule.last_error = run.error_message
                        emit_workflow_event(
                            session,
                            event_type="workflow.schedule_failed",
                            message=f"Workflow schedule {schedule.name} run failed: {run.error_message or run.status}",
                            severity="error",
                            run=run,
                            schedule=schedule,
                            payload={
                                "execution_id": execution_id,
                                "run_id": run.id,
                                "trigger_type": execution.trigger_type if execution else None,
                                "duration_seconds": duration,
                                "error_message": run.error_message,
                            },
                            notify=schedule.notify_on_failure,
                        )
                    session.add(schedule)
                session.commit()
                return
        await asyncio.sleep(5)

    with Session(engine) as session:
        execution = session.get(WorkflowScheduleExecution, execution_id)
        schedule = session.get(WorkflowSchedule, schedule_id)
        if execution:
            execution.status = "failed"
            execution.error_message = "Timed out waiting for scheduled workflow completion"
            execution.completed_at = datetime.now(timezone.utc)
            session.add(execution)
        if schedule:
            schedule.failed_executions += 1
            schedule.last_run_status = "failed"
            schedule.last_error = "Timed out waiting for scheduled workflow completion"
            session.add(schedule)
        session.commit()


async def _execute_scheduled_batch(schedule_id: str, execution_id: int = None):
    """Execute a scheduled regression batch.

    This is called by APScheduler when the cron fires, or directly for manual triggers.
    It loads the schedule config, creates or updates an execution record,
    and delegates to the batch executor.

    Args:
        schedule_id: The schedule to execute.
        execution_id: If provided, update an existing ScheduleExecution record instead
                      of creating a new one (used for manual "Run Now" triggers).
    """
    from sqlmodel import Session

    from orchestrator.api.db import engine
    from orchestrator.api.models_db import CronSchedule, ScheduleExecution

    logger.info(f"Cron fired for schedule {schedule_id}")

    with Session(engine) as session:
        schedule = session.get(CronSchedule, schedule_id)
        if not schedule:
            logger.error(f"Schedule {schedule_id} not found in database")
            return

        if not schedule.enabled:
            logger.info(f"Schedule {schedule_id} is disabled, skipping execution")
            return

        # Copy needed attributes before session closes
        project_id = schedule.project_id
        browser = schedule.browser
        hybrid_mode = schedule.hybrid_mode
        max_iterations = schedule.max_iterations
        tags = schedule.tags if schedule.tags else None
        automated_only = schedule.automated_only
        spec_names = schedule.spec_names if schedule.spec_names else None
        schedule_name = schedule.name

        if execution_id is not None:
            # Update the existing execution record (manual "Run Now" trigger)
            execution = session.get(ScheduleExecution, execution_id)
            if execution:
                execution.status = "running"
                execution.started_at = datetime.now(timezone.utc)
                session.add(execution)
                session.commit()
        else:
            # Create a new execution record (normal cron trigger)
            execution = ScheduleExecution(
                schedule_id=schedule_id,
                status="running",
                trigger_type="cron",
                started_at=datetime.now(timezone.utc),
            )
            session.add(execution)
            session.commit()
            session.refresh(execution)
            execution_id = execution.id

    # Build batch config and create the batch
    try:
        from orchestrator.services.batch_executor import BatchConfig, create_regression_batch

        config = BatchConfig(
            project_id=project_id,
            browser=browser,
            hybrid_mode=hybrid_mode,
            max_iterations=max_iterations,
            tags=tags,
            automated_only=automated_only,
            spec_names=spec_names,
            triggered_by=f"schedule:{schedule_id}",
            batch_name=f"Scheduled: {schedule_name}",
        )

        with Session(engine) as session:
            result = create_regression_batch(config, session)

        batch_id = result.batch_id

        # Update execution with batch link
        with Session(engine) as session:
            execution = session.get(ScheduleExecution, execution_id)
            if execution:
                execution.batch_id = batch_id
                execution.total_tests = len(result.run_ids)
                session.add(execution)
                session.commit()

        # Start the actual test tasks
        # Import here to avoid circular imports
        from orchestrator.api.main import PROCESS_MANAGER, _task_exception_handler, execute_run_task_wrapper

        tasks = []
        for task_args in result.tasks_to_start:
            task = asyncio.create_task(
                execute_run_task_wrapper(
                    spec_path=task_args["spec_path"],
                    run_dir=task_args["run_dir"],
                    run_id=task_args["run_id"],
                    try_code_path=task_args["try_code_path"],
                    browser=task_args["browser"],
                    hybrid=task_args["hybrid"],
                    max_iterations=task_args["max_iterations"],
                    batch_id=task_args["batch_id"],
                    spec_name=task_args["spec_name"],
                    project_id=task_args["project_id"],
                )
            )
            task.add_done_callback(_task_exception_handler)
            if PROCESS_MANAGER:
                PROCESS_MANAGER.register_task(task_args["run_id"], task)
            tasks.append(task)

        # Update schedule stats
        with Session(engine) as session:
            schedule = session.get(CronSchedule, schedule_id)
            if schedule:
                schedule.last_run_at = datetime.now(timezone.utc)
                schedule.last_batch_id = batch_id
                schedule.total_executions += 1
                schedule.last_error = None
                schedule.status = "active"
                session.add(schedule)
                session.commit()

        logger.info(f"Schedule {schedule_id} created batch {batch_id} with {len(result.run_ids)} tests")

        # Monitor batch completion in background to update execution status
        asyncio.create_task(_monitor_execution_completion(schedule_id, execution_id, batch_id, tasks))

    except Exception as e:
        logger.error(f"Schedule {schedule_id} execution failed: {e}", exc_info=True)

        with Session(engine) as session:
            # Update execution as failed
            execution = session.get(ScheduleExecution, execution_id)
            if execution:
                execution.status = "failed"
                execution.error_message = str(e)
                execution.completed_at = datetime.now(timezone.utc)
                session.add(execution)

            # Update schedule error state
            schedule = session.get(CronSchedule, schedule_id)
            if schedule:
                schedule.last_error = str(e)
                schedule.total_executions += 1
                schedule.failed_executions += 1
                schedule.status = "error"
                session.add(schedule)

            session.commit()


async def _monitor_execution_completion(schedule_id: str, execution_id: int, batch_id: str, tasks: list):
    """Wait for all batch tasks to complete and update execution status."""
    from sqlmodel import Session

    from orchestrator.api.db import engine
    from orchestrator.api.models_db import CronSchedule, RegressionBatch, ScheduleExecution

    try:
        # Wait for all test tasks to finish (with a safety timeout of 4 hours)
        await asyncio.wait(tasks, timeout=14400)

        # Read batch results to determine execution outcome
        with Session(engine) as session:
            batch = session.get(RegressionBatch, batch_id)
            execution = session.get(ScheduleExecution, execution_id)
            if not execution:
                return

            now = datetime.now(timezone.utc)
            if batch:
                execution.passed = batch.passed
                execution.failed = batch.failed
                execution.total_tests = batch.total_tests
                if execution.started_at:
                    execution.duration_seconds = int((now - execution.started_at).total_seconds())
                execution.status = "pass" if batch.failed == 0 and batch.passed > 0 else "failed"
            else:
                execution.status = "failed"
                execution.error_message = "Batch not found after completion"

            execution.completed_at = now
            session.add(execution)

            # Update schedule stats
            schedule = session.get(CronSchedule, schedule_id)
            if schedule:
                if execution.status == "pass":
                    schedule.successful_executions += 1
                else:
                    schedule.failed_executions += 1
                schedule.last_run_status = execution.status
                session.add(schedule)

            session.commit()

        logger.info(f"Schedule {schedule_id} execution {execution_id} completed: {execution.status}")
    except Exception as e:
        logger.error(f"Error monitoring execution {execution_id}: {e}", exc_info=True)
        try:
            with Session(engine) as session:
                execution = session.get(ScheduleExecution, execution_id)
                if execution and execution.status == "running":
                    execution.status = "failed"
                    execution.error_message = f"Monitor error: {e}"
                    execution.completed_at = datetime.now(timezone.utc)
                    session.add(execution)
                    session.commit()
        except Exception:
            pass


async def cleanup_stale_executions():
    """Mark stale 'running'/'pending' executions as failed.

    Called on startup to clean up executions that were interrupted
    by a server restart.
    """
    from sqlmodel import Session, select

    from orchestrator.api.db import engine
    from orchestrator.api.models_db import ScheduleExecution

    try:
        with Session(engine) as session:
            stale = session.exec(
                select(ScheduleExecution).where(ScheduleExecution.status.in_(["running", "pending"]))
            ).all()

            if not stale:
                return

            now = datetime.now(timezone.utc)
            for ex in stale:
                ex.status = "failed"
                ex.error_message = "Marked as failed: server restarted while execution was in progress"
                ex.completed_at = now
                session.add(ex)

            session.commit()
            logger.info(f"Cleaned up {len(stale)} stale schedule executions")
    except Exception as e:
        logger.debug(f"Stale execution cleanup skipped: {e}")


async def reconcile_workflow_schedule_executions():
    """Finalize workflow schedule executions that survived a process restart."""
    from sqlmodel import Session, select

    from orchestrator.api.db import engine
    from orchestrator.api.models_db import WorkflowEvent, WorkflowRun, WorkflowSchedule, WorkflowScheduleExecution
    from orchestrator.services.workflow_operations import avg_duration, emit_workflow_event, workflow_duration_seconds

    terminal = {"completed", "failed", "cancelled"}
    now = datetime.utcnow()
    reconciled = 0
    with Session(engine) as session:
        executions = session.exec(
            select(WorkflowScheduleExecution).where(WorkflowScheduleExecution.status.in_(["pending", "running"]))
        ).all()
        for execution in executions:
            schedule = session.get(WorkflowSchedule, execution.schedule_id)
            run = session.get(WorkflowRun, execution.workflow_run_id) if execution.workflow_run_id else None
            if not schedule:
                execution.status = "failed"
                execution.error_message = "Workflow schedule no longer exists"
                execution.completed_at = now
                session.add(execution)
                reconciled += 1
                continue
            if not run:
                age_seconds = (now - execution.created_at).total_seconds() if execution.created_at else 0
                if age_seconds > 300:
                    execution.status = "failed"
                    execution.error_message = "No workflow run was created for this execution"
                    execution.completed_at = now
                    schedule.failed_executions += 1
                    schedule.last_run_status = "failed"
                    schedule.last_error = execution.error_message
                    emit_workflow_event(
                        session,
                        event_type="workflow.schedule_execution_skipped",
                        message=f"Workflow schedule {schedule.name} execution did not create a workflow run.",
                        severity="error",
                        schedule=schedule,
                        payload={
                            "execution_id": execution.id,
                            "trigger_type": execution.trigger_type,
                            "reason": "no_workflow_run_created",
                        },
                        notify=False,
                    )
                    session.add(execution)
                    session.add(schedule)
                    reconciled += 1
                continue
            if run.status in {"awaiting_input", "paused"}:
                schedule.last_run_status = run.status
                session.add(schedule)
                existing = session.exec(
                    select(WorkflowEvent)
                    .where(WorkflowEvent.schedule_id == schedule.id)
                    .where(WorkflowEvent.run_id == run.id)
                    .where(WorkflowEvent.event_type == "workflow.schedule_review_needed")
                ).first()
                if not existing:
                    emit_workflow_event(
                        session,
                        event_type="workflow.schedule_review_needed",
                        message=f"Workflow schedule {schedule.name} run needs review.",
                        severity="warning",
                        run=run,
                        schedule=schedule,
                        payload={
                            "execution_id": execution.id,
                            "run_id": run.id,
                            "trigger_type": execution.trigger_type,
                            "duration_seconds": workflow_duration_seconds(run),
                        },
                        notify=schedule.notify_on_review_needed,
                    )
                continue
            if run.status not in terminal:
                continue

            execution.status = "completed" if run.status == "completed" else "failed"
            execution.completed_at = execution.completed_at or now
            execution.duration_seconds = workflow_duration_seconds(run)
            execution.error_message = run.error_message
            schedule.last_run_status = run.status
            schedule.avg_duration_seconds = avg_duration(schedule.avg_duration_seconds, execution.duration_seconds)
            if run.status == "completed":
                schedule.successful_executions += 1
                event_type = "workflow.schedule_completed"
                notify = schedule.notify_on_completion
                message = f"Workflow schedule {schedule.name} run completed."
                severity = "info"
            else:
                schedule.failed_executions += 1
                schedule.last_error = run.error_message or run.status
                event_type = "workflow.schedule_failed"
                notify = schedule.notify_on_failure
                message = f"Workflow schedule {schedule.name} run failed: {run.error_message or run.status}"
                severity = "error"
            existing = session.exec(
                select(WorkflowEvent)
                .where(WorkflowEvent.schedule_id == schedule.id)
                .where(WorkflowEvent.run_id == run.id)
                .where(WorkflowEvent.event_type == event_type)
            ).first()
            if not existing:
                emit_workflow_event(
                    session,
                    event_type=event_type,
                    message=message,
                    severity=severity,
                    run=run,
                    schedule=schedule,
                    payload={
                        "execution_id": execution.id,
                        "run_id": run.id,
                        "trigger_type": execution.trigger_type,
                        "duration_seconds": execution.duration_seconds,
                        "error_message": run.error_message,
                    },
                    notify=notify,
                )
            session.add(execution)
            session.add(schedule)
            reconciled += 1
        session.commit()
    if reconciled:
        logger.info("Reconciled %d workflow schedule execution(s)", reconciled)


def _on_job_error(event):
    """Handle APScheduler job errors."""
    logger.error(f"Scheduler job error: {event.job_id} - {event.exception}", exc_info=event.traceback)


def _on_job_missed(event):
    """Handle APScheduler missed jobs."""
    logger.warning(f"Scheduler job missed: {event.job_id} at {event.scheduled_run_time}")


async def restore_schedules_from_db():
    """Restore all enabled schedules from database on startup.

    Called after init_scheduler() to re-register any schedules
    that were saved but not yet in the APScheduler job store
    (e.g., after a fresh database migration).
    """
    from sqlmodel import Session, select

    from orchestrator.api.db import engine
    from orchestrator.api.models_db import CronSchedule, WorkflowSchedule

    with Session(engine) as session:
        schedules = session.exec(select(CronSchedule).where(CronSchedule.enabled == True)).all()
        workflow_schedules = session.exec(select(WorkflowSchedule).where(WorkflowSchedule.enabled == True)).all()

    restored = 0
    for schedule in schedules:
        try:
            add_schedule_job(schedule.id, schedule.cron_expression, schedule.timezone)
            restored += 1
        except Exception as e:
            logger.error(f"Failed to restore schedule {schedule.id}: {e}")
    for schedule in workflow_schedules:
        try:
            add_workflow_schedule_job(schedule.id, schedule.cron_expression, schedule.timezone)
            restored += 1
        except Exception as e:
            logger.error("Failed to restore workflow schedule %s: %s", schedule.id, e)

    if restored:
        logger.info(f"Restored {restored} schedules from database")


# ========== LLM Dataset Schedule Functions ==========


def add_llm_schedule_job(schedule_id: str, cron_expression: str, timezone_str: str = "UTC"):
    """Add or replace a cron job for an LLM dataset schedule.

    Args:
        schedule_id: Unique schedule identifier (used as job ID).
        cron_expression: 5-field cron expression (minute hour day month dow).
        timezone_str: IANA timezone name.
    """
    if not _scheduler:
        logger.error("Scheduler not initialized, cannot add LLM schedule job")
        return

    parts = cron_expression.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: expected 5 fields, got {len(parts)}")

    trigger = CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=parts[4],
        timezone=timezone_str,
    )

    _scheduler.add_job(
        _execute_llm_scheduled_run,
        trigger=trigger,
        id=f"llm:{schedule_id}",
        args=[schedule_id],
        replace_existing=True,
        name=f"llm-schedule:{schedule_id}",
    )
    logger.info(f"Added/updated LLM cron job for schedule {schedule_id}: {cron_expression} ({timezone_str})")


async def _execute_llm_scheduled_run(schedule_id: str):
    """Execute a scheduled LLM dataset run.

    Called by APScheduler when cron fires.
    Loads schedule config, runs dataset against all configured providers,
    and records execution results.
    """
    from sqlmodel import Session, select

    from orchestrator.api.db import engine
    from orchestrator.api.models_db import (
        LlmDataset,
        LlmDatasetCase,
        LlmSchedule,
        LlmScheduleExecution,
    )

    logger.info(f"LLM cron fired for schedule {schedule_id}")

    with Session(engine) as session:
        schedule = session.get(LlmSchedule, schedule_id)
        if not schedule:
            logger.error(f"LLM schedule {schedule_id} not found in database")
            return
        if not schedule.enabled:
            logger.info(f"LLM schedule {schedule_id} is disabled, skipping")
            return

        dataset = session.get(LlmDataset, schedule.dataset_id)
        if not dataset:
            logger.error(f"Dataset {schedule.dataset_id} not found for schedule {schedule_id}")
            return

        cases = session.exec(
            select(LlmDatasetCase)
            .where(LlmDatasetCase.dataset_id == schedule.dataset_id)
            .order_by(LlmDatasetCase.case_index)
        ).all()
        if not cases:
            logger.warning(f"No cases in dataset {schedule.dataset_id} for schedule {schedule_id}")
            return

        # Import here to avoid circular
        from orchestrator.api.llm_testing import RunRequest, _dataset_to_suite, _execute_run, _llm_jobs

        suite = _dataset_to_suite(dataset, cases)
        ds_name = dataset.name
        ds_version = dataset.version
        provider_ids = schedule.provider_ids

    # Create execution record
    execution = LlmScheduleExecution(
        schedule_id=schedule_id,
        status="running",
        dataset_version=ds_version,
        started_at=datetime.now(timezone.utc),
    )
    with Session(engine) as session:
        session.add(execution)
        session.commit()
        session.refresh(execution)
        exec_id = execution.id

    run_ids = []
    try:
        import asyncio
        import time
        import uuid

        sem = asyncio.Semaphore(3)
        tasks = []

        for pid in provider_ids:

            async def _run_for_provider(provider_id=pid):
                async with sem:
                    sub_run_id = f"llmr-{uuid.uuid4().hex[:8]}"
                    sub_job_id = f"llmj-sub-{uuid.uuid4().hex[:8]}"
                    _llm_jobs[sub_job_id] = {
                        "job_id": sub_job_id,
                        "run_id": sub_run_id,
                        "type": "run",
                        "status": "running",
                        "started_at": time.time(),
                        "progress_current": 0,
                        "progress_total": 0,
                        "passed": 0,
                        "failed": 0,
                    }
                    inner_req = RunRequest(
                        spec_name=f"dataset:{ds_name}",
                        provider_id=provider_id,
                        project_id="default",
                    )
                    await _execute_run(
                        sub_job_id,
                        sub_run_id,
                        inner_req,
                        suite=suite,
                        dataset_id=schedule.dataset_id,
                        dataset_name=ds_name,
                        dataset_version=ds_version,
                    )
                    return sub_run_id

            tasks.append(_run_for_provider())

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, str):
                run_ids.append(r)

        with Session(engine) as session:
            ex = session.get(LlmScheduleExecution, exec_id)
            if ex:
                ex.status = "completed"
                ex.run_ids_json = json.dumps(run_ids)
                ex.completed_at = datetime.now(timezone.utc)
                session.add(ex)

            sched = session.get(LlmSchedule, schedule_id)
            if sched:
                sched.last_run_at = datetime.now(timezone.utc)
                sched.total_executions += 1
                session.add(sched)
            session.commit()

        logger.info(f"LLM schedule {schedule_id} completed: {len(run_ids)} runs")

    except Exception as e:
        logger.error(f"LLM schedule {schedule_id} execution failed: {e}", exc_info=True)
        with Session(engine) as session:
            ex = session.get(LlmScheduleExecution, exec_id)
            if ex:
                ex.status = "failed"
                ex.error_message = str(e)
                ex.completed_at = datetime.now(timezone.utc)
                session.add(ex)
            session.commit()


async def restore_llm_schedules_from_db():
    """Restore all enabled LLM dataset schedules from database on startup."""
    from sqlmodel import Session, select

    from orchestrator.api.db import engine
    from orchestrator.api.models_db import LlmSchedule

    try:
        with Session(engine) as session:
            schedules = session.exec(select(LlmSchedule).where(LlmSchedule.enabled == True)).all()

        restored = 0
        for schedule in schedules:
            try:
                add_llm_schedule_job(schedule.id, schedule.cron_expression, schedule.timezone)
                restored += 1
            except Exception as e:
                logger.error(f"Failed to restore LLM schedule {schedule.id}: {e}")

        if restored:
            logger.info(f"Restored {restored} LLM schedules from database")
    except Exception as e:
        logger.debug(f"LLM schedule restoration skipped (table may not exist yet): {e}")
