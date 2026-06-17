"""Batch stats and watchdog support for legacy helpers exposed from main."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


def update_batch_stats(runtime: Any, batch_id: str) -> None:
    """Update batch statistics after a run completes.

    Uses explicit transaction with rollback on failure to ensure data integrity.
    Locks the batch row to prevent race conditions when multiple runs complete simultaneously.
    """
    if not batch_id:
        return

    with runtime.Session(runtime.engine) as session:
        try:
            batch = session.get(runtime.RegressionBatch, batch_id)
            if not batch:
                return
            previous_status = batch.status

            # PostgreSQL can lock the batch row; SQLite's database lock is enough.
            if runtime.get_database_type() == "postgresql":
                session.execute(
                    text("SELECT id FROM regression_batches WHERE id = :batch_id FOR UPDATE"), {"batch_id": batch_id}
                )
                session.refresh(batch)

            runs = session.exec(runtime.select(runtime.DBTestRun).where(runtime.DBTestRun.batch_id == batch_id)).all()

            batch.total_tests = len(runs)
            batch.passed = sum(1 for r in runs if r.status in ("passed", "completed"))
            batch.failed = sum(1 for r in runs if r.status in ("failed", "error"))
            batch.stopped = sum(1 for r in runs if r.status in ("stopped", "cancelled"))
            batch.running = sum(1 for r in runs if r.status in ("running", "in_progress"))
            batch.queued = sum(1 for r in runs if r.status == "queued")

            if batch.running > 0 or batch.queued > 0:
                batch.status = "running"
                if not batch.started_at:
                    started_runs = [r for r in runs if r.started_at]
                    if started_runs:
                        batch.started_at = min(r.started_at for r in started_runs)
            elif batch.total_tests > 0 and (batch.passed + batch.failed + batch.stopped) == batch.total_tests:
                batch.status = "completed"
                completed_runs = [r for r in runs if r.completed_at]
                if completed_runs:
                    batch.completed_at = max(r.completed_at for r in completed_runs)
                else:
                    batch.completed_at = runtime.datetime.utcnow()

                try:
                    from .regression import _calculate_actual_test_counts

                    actual_total, actual_passed, actual_failed = _calculate_actual_test_counts(runs)
                    batch.actual_total_tests = actual_total
                    batch.actual_passed = actual_passed
                    batch.actual_failed = actual_failed
                except Exception as count_err:
                    runtime.logger.warning(f"Failed to cache actual test counts for {batch_id}: {count_err}")
            elif batch.total_tests == 0:
                batch.status = "completed"
                if not batch.completed_at:
                    batch.completed_at = runtime.datetime.utcnow()

            session.add(batch)
            session.commit()

            if previous_status != "completed" and batch.status == "completed":
                try:
                    loop = runtime.asyncio.get_running_loop()
                    loop.create_task(runtime._finalize_quality_gate_for_batch_safe(batch_id))
                except RuntimeError:
                    runtime.logger.debug(
                        "No running event loop available to finalize quality gate for batch %s", batch_id
                    )

        except Exception as e:
            session.rollback()
            runtime.logger.error(f"Failed to update batch stats for {batch_id}: {e}", exc_info=True)
            raise


async def _finalize_quality_gate_for_batch_safe(runtime: Any, batch_id: str) -> None:
    try:
        from orchestrator.services.quality_gate import finalize_quality_gate_for_batch

        finalized = await finalize_quality_gate_for_batch(batch_id)
        if finalized:
            runtime.logger.info("Finalized %d quality gate(s) for batch %s", finalized, batch_id)
    except Exception as e:
        runtime.logger.warning("Failed to finalize quality gate feedback for batch %s: %s", batch_id, e)


async def _quality_gate_finalizer_loop(runtime: Any) -> None:
    """Periodically publish missed final PR quality gate feedback."""
    while True:
        try:
            await runtime.asyncio.sleep(60)
            from orchestrator.services.quality_gate import finalize_stale_quality_gates

            finalized = await finalize_stale_quality_gates()
            if finalized:
                runtime.logger.info("Quality gate finalizer published %d stale final update(s)", finalized)
        except runtime.asyncio.CancelledError:
            break
        except Exception as e:
            runtime.logger.warning("Quality gate finalizer loop error: %s", e)


async def _batch_watchdog(runtime: Any) -> None:
    """Background task that detects and cleans up stuck runs."""
    max_run_age_minutes = int(runtime.os.environ.get("MAX_RUN_AGE_MINUTES", "120"))
    orphan_age_seconds = 120

    while True:
        try:
            await runtime.asyncio.sleep(60)

            with runtime.Session(runtime.engine) as session:
                running_runs = session.exec(
                    runtime.select(runtime.DBTestRun).where(
                        runtime.DBTestRun.status.in_(["running", "in_progress"])
                    )
                ).all()

                now = runtime.datetime.utcnow()
                orphan_batch_ids = set()
                orphan_cleaned = 0
                for run in running_runs:
                    if run.temporal_workflow_id:
                        continue
                    if runtime.is_process_active(run.id):
                        continue
                    age_ref = run.started_at or run.queued_at
                    if not age_ref or (now - age_ref).total_seconds() <= orphan_age_seconds:
                        continue

                    run.status = "stopped"
                    run.completed_at = now
                    run.queue_position = None
                    session.add(run)

                    run_dir = runtime.RUNS_DIR / run.id
                    if run_dir.exists():
                        (run_dir / "status.txt").write_text("stopped")

                    if run.batch_id:
                        orphan_batch_ids.add(run.batch_id)

                    orphan_cleaned += 1
                    runtime.logger.warning(
                        f"Watchdog: Orphaned run {run.id} (no active process, "
                        f"age={int((now - age_ref).total_seconds())}s). Marked stopped."
                    )

                if orphan_cleaned > 0:
                    session.commit()
                    runtime.logger.info(f"Watchdog: Cleaned {orphan_cleaned} orphaned runs")
                    for batch_id in orphan_batch_ids:
                        try:
                            runtime.update_batch_stats(batch_id)
                        except Exception as e:
                            runtime.logger.error(
                                f"Watchdog: Failed to update batch {batch_id} after orphan cleanup: {e}"
                            )

            with runtime.Session(runtime.engine) as session:
                now = runtime.datetime.utcnow()
                cutoff = now - runtime.timedelta(minutes=max_run_age_minutes)

                stuck_runs = session.exec(
                    runtime.select(runtime.DBTestRun).where(
                        runtime.DBTestRun.status.in_(["running", "in_progress"]),
                        (runtime.DBTestRun.started_at < cutoff) | (runtime.DBTestRun.started_at == None),
                    )
                ).all()
                stuck_runs = [
                    run
                    for run in stuck_runs
                    if not run.temporal_workflow_id
                    and (run.started_at is not None or (run.queued_at and run.queued_at < cutoff))
                ]

                if not stuck_runs:
                    continue

                batch_ids_to_update = set()
                killed_runs = []
                for run in stuck_runs:
                    run_dir = runtime.RUNS_DIR / run.id
                    log_file = run_dir / "execution.log"
                    if log_file.exists():
                        log_age = (
                            now - runtime.datetime.utcfromtimestamp(log_file.stat().st_mtime)
                        ).total_seconds()
                        if log_age < 300:
                            runtime.logger.info(
                                f"Watchdog: Run {run.id} still active (log updated {int(log_age)}s ago), skipping"
                            )
                            continue

                    runtime.logger.warning(
                        f"Watchdog: Run {run.id} stuck in '{run.status}' since {run.started_at}. "
                        "Forcing to 'error'."
                    )
                    run.status = "error"
                    run.error_message = f"Watchdog: Run stuck for >{max_run_age_minutes} minutes"
                    run.completed_at = runtime.datetime.utcnow()
                    session.add(run)

                    if run_dir.exists():
                        (run_dir / "status.txt").write_text("error")

                    if run.batch_id:
                        batch_ids_to_update.add(run.batch_id)

                    killed_runs.append(run)

                session.commit()
                if killed_runs:
                    runtime.logger.info(f"Watchdog: Force-errored {len(killed_runs)} stuck runs")

                for run in killed_runs:
                    proc = runtime.get_process(run.id)
                    if proc:
                        try:
                            import signal as _signal

                            runtime.os.killpg(runtime.os.getpgid(proc.pid), _signal.SIGKILL)
                        except (ProcessLookupError, OSError):
                            try:
                                proc.kill()
                            except (ProcessLookupError, OSError):
                                pass
                        runtime.unregister_process(run.id)

                for batch_id in batch_ids_to_update:
                    try:
                        runtime.update_batch_stats(batch_id)
                    except Exception as e:
                        runtime.logger.error(f"Watchdog: Failed to update batch {batch_id}: {e}")

        except runtime.asyncio.CancelledError:
            runtime.logger.info("Batch watchdog cancelled")
            break
        except Exception as e:
            runtime.logger.error(f"Batch watchdog error: {e}", exc_info=True)
            await runtime.asyncio.sleep(30)


async def _queue_watchdog(runtime: Any) -> None:
    """Background task that detects orphaned queued entries after uvicorn reload."""
    grace_period_seconds = 60

    while True:
        try:
            await runtime.asyncio.sleep(30)

            with runtime.Session(runtime.engine) as session:
                queued_runs = session.exec(
                    runtime.select(runtime.DBTestRun).where(runtime.DBTestRun.status == "queued")
                ).all()

                if not queued_runs:
                    continue

                cutoff = runtime.datetime.utcnow() - runtime.timedelta(seconds=grace_period_seconds)
                batch_ids_to_update = set()
                cleaned = 0

                for run in queued_runs:
                    if run.temporal_workflow_id:
                        continue
                    if run.queued_at and run.queued_at > cutoff:
                        continue

                    has_task = (
                        runtime.PROCESS_MANAGER
                        and run.id in runtime.PROCESS_MANAGER._asyncio_tasks
                        and not runtime.PROCESS_MANAGER._asyncio_tasks[run.id].done()
                    )
                    if has_task:
                        continue

                    runtime.logger.warning(
                        f"Queue watchdog: Run {run.id} orphaned in 'queued' status "
                        f"(queued_at={run.queued_at}). Marking as stopped."
                    )
                    run.status = "stopped"
                    run.queue_position = None
                    run.error_message = "Orphaned: server restarted while queued"
                    run.completed_at = runtime.datetime.utcnow()
                    session.add(run)

                    run_dir = runtime.RUNS_DIR / run.id
                    if run_dir.exists():
                        (run_dir / "status.txt").write_text("stopped")

                    if run.batch_id:
                        batch_ids_to_update.add(run.batch_id)
                    cleaned += 1

                if cleaned > 0:
                    session.commit()
                    runtime.logger.info(f"Queue watchdog: Cleaned {cleaned} orphaned queued runs")

                    for batch_id in batch_ids_to_update:
                        try:
                            runtime.update_batch_stats(batch_id)
                        except Exception as e:
                            runtime.logger.error(f"Queue watchdog: Failed to update batch {batch_id}: {e}")

        except runtime.asyncio.CancelledError:
            runtime.logger.info("Queue watchdog cancelled")
            break
        except Exception as e:
            runtime.logger.error(f"Queue watchdog error: {e}", exc_info=True)
            await runtime.asyncio.sleep(30)
