"""Schedule execution watchdog support for legacy helpers exposed from main."""

from __future__ import annotations

from typing import Any


async def _schedule_execution_watchdog(runtime: Any) -> None:
    """Sync schedule execution status from completed batches."""
    from .models_db import CronSchedule, ScheduleExecution

    # On first run, clean up stale executions from previous server instances.
    try:
        from orchestrator.services.scheduler import (
            cleanup_stale_executions,
            reconcile_workflow_schedule_executions,
        )

        await cleanup_stale_executions()
        await reconcile_workflow_schedule_executions()
    except Exception as e:
        runtime.logger.debug(f"Stale execution cleanup on startup: {e}")

    while True:
        try:
            await runtime.asyncio.sleep(30)
            try:
                from orchestrator.services.scheduler import reconcile_workflow_schedule_executions

                await reconcile_workflow_schedule_executions()
            except Exception as e:
                runtime.logger.debug(f"Workflow schedule reconciliation skipped: {e}")

            now = runtime.datetime.utcnow()

            with runtime.Session(runtime.engine) as session:
                running_execs = session.exec(
                    runtime.select(ScheduleExecution).where(ScheduleExecution.status.in_(["pending", "running"]))
                ).all()

                for execution in running_execs:
                    if not execution.batch_id:
                        age_seconds = (now - execution.created_at).total_seconds() if execution.created_at else 0
                        if age_seconds > 300:
                            execution.status = "failed"
                            execution.error_message = "No batch was created for this execution"
                            execution.completed_at = now
                            session.add(execution)
                        continue

                    batch = session.get(runtime.RegressionBatch, execution.batch_id)
                    if not batch:
                        execution.status = "failed"
                        execution.error_message = "Linked batch no longer exists"
                        execution.completed_at = now
                        session.add(execution)
                        continue

                    if batch.status == "completed":
                        execution.status = "pass" if batch.failed == 0 and batch.passed > 0 else "failed"
                        execution.passed = batch.passed
                        execution.failed = batch.failed
                        execution.total_tests = batch.total_tests
                        execution.completed_at = batch.completed_at or now
                        if batch.started_at and execution.completed_at:
                            execution.duration_seconds = int(
                                (execution.completed_at - batch.started_at).total_seconds()
                            )

                        schedule = session.get(CronSchedule, execution.schedule_id)
                        if schedule:
                            schedule.last_run_status = "passed" if batch.failed == 0 else "failed"
                            if batch.failed == 0:
                                schedule.successful_executions += 1
                            else:
                                schedule.failed_executions += 1
                            if execution.duration_seconds:
                                if schedule.avg_duration_seconds:
                                    schedule.avg_duration_seconds = (
                                        schedule.avg_duration_seconds * 0.8 + execution.duration_seconds * 0.2
                                    )
                                else:
                                    schedule.avg_duration_seconds = float(execution.duration_seconds)
                            session.add(schedule)

                        session.add(execution)

                    elif batch.status == "running" and execution.status == "pending":
                        execution.status = "running"
                        execution.started_at = batch.started_at
                        session.add(execution)

                    elif batch.status not in ("running", "pending", "completed"):
                        execution.status = "failed"
                        execution.error_message = f"Batch ended with status: {batch.status}"
                        execution.completed_at = now
                        session.add(execution)

                session.commit()

        except runtime.asyncio.CancelledError:
            runtime.logger.info("Schedule execution watchdog cancelled")
            break
        except Exception as e:
            runtime.logger.error(f"Schedule execution watchdog error: {e}", exc_info=True)
            await runtime.asyncio.sleep(30)
