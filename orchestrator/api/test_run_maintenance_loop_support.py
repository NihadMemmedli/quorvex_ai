"""Maintenance loop support for legacy helpers exposed from main."""

from __future__ import annotations

import glob
import json
import time as time_module
from typing import Any

from sqlalchemy import text


async def _exploration_cleanup_loop(runtime: Any) -> None:
    """Background task that cleans up stuck exploration sessions."""
    cleanup_interval = 300
    default_timeout_minutes = 60

    while True:
        try:
            await runtime.asyncio.sleep(cleanup_interval)

            from .exploration import _running_explorations, _sweep_done_tasks

            _sweep_done_tasks()

            with runtime.Session(runtime.engine) as session:
                cutoff = runtime.datetime.utcnow() - runtime.timedelta(minutes=default_timeout_minutes)

                stuck_explorations = session.exec(
                    runtime.select(runtime.ExplorationSession).where(
                        runtime.ExplorationSession.status.in_(["running", "queued"]),
                        runtime.ExplorationSession.created_at < cutoff,
                    )
                ).all()

                for exploration in stuck_explorations:
                    timeout = default_timeout_minutes
                    try:
                        config = json.loads(exploration.config_json or "{}")
                        timeout = config.get("timeout_minutes", default_timeout_minutes)
                    except Exception:
                        pass

                    exploration_cutoff = runtime.datetime.utcnow() - runtime.timedelta(minutes=timeout)
                    if exploration.created_at < exploration_cutoff:
                        runtime.logger.warning(
                            f"Exploration cleanup: {exploration.id} stuck in '{exploration.status}' "
                            f"since {exploration.created_at}. Marking as failed."
                        )
                        exploration.status = "failed"
                        exploration.error_message = f"Cleanup: stuck for >{timeout} minutes"
                        exploration.completed_at = runtime.datetime.utcnow()
                        session.add(exploration)

                        entry = _running_explorations.pop(exploration.id, None)
                        if entry:
                            task, _ = entry
                            task.cancel()

                if stuck_explorations:
                    session.commit()
                    runtime.logger.info(f"Exploration cleanup: processed {len(stuck_explorations)} stuck sessions")

            if runtime.BROWSER_POOL:
                stale_cleaned = await runtime.BROWSER_POOL.cleanup_stale(max_age_minutes=default_timeout_minutes)
                if stale_cleaned:
                    runtime.logger.info(f"Exploration cleanup: cleaned {len(stale_cleaned)} stale browser slots")

                try:
                    await runtime.BROWSER_POOL.cleanup_old_completed()
                except Exception:
                    pass

        except runtime.asyncio.CancelledError:
            runtime.logger.info("Exploration cleanup loop cancelled")
            break
        except Exception as e:
            runtime.logger.error(f"Exploration cleanup loop error: {e}", exc_info=True)
            await runtime.asyncio.sleep(60)


async def _browser_pool_cleanup_loop(runtime: Any) -> None:
    """Periodically clean up stale browser slots every 10 minutes."""
    while True:
        try:
            await runtime.asyncio.sleep(600)
            if runtime.BROWSER_POOL:
                stale = await runtime.BROWSER_POOL.cleanup_stale(max_age_minutes=120)
                old = await runtime.BROWSER_POOL.cleanup_old_completed(max_age_hours=24)
                if stale:
                    runtime.logger.info(f"Periodic cleanup: freed {len(stale)} stale browser slots")
                if old:
                    runtime.logger.info(f"Periodic cleanup: removed {old} old completed slot records")
        except runtime.asyncio.CancelledError:
            runtime.logger.info("Browser pool cleanup loop cancelled")
            break
        except Exception as e:
            runtime.logger.error(f"Browser pool cleanup error: {e}")
            await runtime.asyncio.sleep(60)


async def _infrastructure_maintenance_loop(runtime: Any) -> None:
    """Periodic infrastructure maintenance: orphan cleanup, temp cleanup, DB maintenance."""
    iteration = 0
    db_maintenance_iterations = 96

    while True:
        try:
            await runtime.asyncio.sleep(900)
            iteration += 1

            if runtime.PROCESS_MANAGER:
                stale = runtime.PROCESS_MANAGER.cleanup_stale_pid_files()
                if stale > 0:
                    runtime.logger.info(f"Infrastructure: removed {stale} stale PID files")

            try:
                tmp_cleaned = 0
                for directory in glob.glob("/tmp/tmp*"):
                    if runtime.os.path.isdir(directory) and (
                        time_module.time() - runtime.os.path.getmtime(directory)
                    ) > 7200:
                        runtime.shutil.rmtree(directory, ignore_errors=True)
                        tmp_cleaned += 1
                if tmp_cleaned:
                    runtime.logger.info(f"Infrastructure: removed {tmp_cleaned} stale temp directories")
            except Exception as e:
                runtime.logger.debug(f"Temp cleanup error: {e}")

            try:
                from .middleware.rate_limit import cleanup_expired_entries

                cleaned = cleanup_expired_entries()
                if cleaned > 0:
                    runtime.logger.info(f"Infrastructure: cleaned {cleaned} expired rate limit entries")
            except Exception as e:
                runtime.logger.debug(f"Rate limiter cleanup error: {e}")

            if iteration % db_maintenance_iterations == 0:
                await runtime._run_db_maintenance()

        except runtime.asyncio.CancelledError:
            runtime.logger.info("Infrastructure maintenance loop cancelled")
            break
        except Exception as e:
            runtime.logger.error(f"Infrastructure maintenance error: {e}", exc_info=True)
            await runtime.asyncio.sleep(60)


async def _run_db_maintenance(runtime: Any) -> None:
    """Run periodic database maintenance: ANALYZE and old data pruning."""
    db_type = runtime.get_database_type()
    if db_type != "postgresql":
        return

    try:
        with runtime.engine.connect() as conn:
            for table in ["testrun", "exploration_sessions", "requirements", "agentrun"]:
                try:
                    conn.execute(text(f"ANALYZE {table}"))
                except Exception:
                    pass

            try:
                result = conn.execute(text("DELETE FROM storage_stats WHERE recorded_at < NOW() - INTERVAL '90 days'"))
                if result.rowcount:
                    runtime.logger.info(f"DB maintenance: pruned {result.rowcount} old storage_stats rows")
            except Exception:
                pass

            try:
                result = conn.execute(
                    text(
                        "DELETE FROM archive_jobs WHERE status = 'completed' "
                        "AND created_at < NOW() - INTERVAL '90 days'"
                    )
                )
                if result.rowcount:
                    runtime.logger.info(f"DB maintenance: pruned {result.rowcount} old archive_jobs rows")
            except Exception:
                pass

            conn.commit()
            runtime.logger.info("DB maintenance: ANALYZE and pruning complete")
    except Exception as e:
        runtime.logger.error(f"DB maintenance error: {e}")
