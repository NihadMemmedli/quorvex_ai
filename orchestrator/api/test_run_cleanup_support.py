"""Startup cleanup support for legacy test-run helpers exposed from main."""

from __future__ import annotations

from typing import Any


def cleanup_orphaned_runs(runtime: Any) -> None:
    """Mark stuck running/queued entries as stopped on startup."""
    runtime.logger.info("Cleaning up orphaned runs...")
    cleaned_count = 0
    preserved_count = 0

    with runtime.Session(runtime.engine) as session:
        stuck_runs = session.exec(
            runtime.select(runtime.DBTestRun).where(
                runtime.DBTestRun.status.in_(["running", "in_progress", "queued"])
            )
        ).all()

        for run in stuck_runs:
            if run.temporal_workflow_id:
                continue
            run_dir = runtime.RUNS_DIR / run.id

            status_file = run_dir / "status.txt" if run_dir.exists() else None
            if status_file and status_file.exists():
                file_status = status_file.read_text().strip()
                if file_status in ("passed", "failed", "error", "completed"):
                    run.status = file_status
                    run.completed_at = run.completed_at or runtime.datetime.utcnow()
                    run.queue_position = None
                    session.add(run)
                    preserved_count += 1
                    runtime.logger.debug(f"Preserved run {run.id}: status={file_status}")
                    continue

            run.status = "stopped"
            run.queue_position = None
            session.add(run)
            cleaned_count += 1

            if run_dir.exists():
                (run_dir / "status.txt").write_text("stopped")

        session.commit()

    if cleaned_count > 0:
        runtime.logger.info(f"Cleaned up {cleaned_count} orphaned runs (marked as stopped)")
    if preserved_count > 0:
        runtime.logger.info(f"Preserved {preserved_count} runs with terminal status from files")
    if cleaned_count == 0 and preserved_count == 0:
        runtime.logger.info("No orphaned runs found")


async def cleanup_test_run_runtime(
    runtime: Any,
    run_id: str,
    reason: str = "cleanup requested",
) -> dict[str, object]:
    """Cancel agent tasks and browser process trees owned by one test run."""
    cleanup: dict[str, object] = {
        "run_id": run_id,
        "reason": reason,
        "agent_tasks": None,
        "processes": None,
    }

    try:
        from orchestrator.services.agent_queue import get_agent_queue

        queue = get_agent_queue()
        await queue.connect()
        cleanup["agent_tasks"] = await queue.cancel_tasks_for_test_run(run_id)
    except Exception as exc:
        runtime.logger.warning("Failed to cancel agent tasks for test run %s: %s", run_id, exc)
        cleanup["agent_tasks"] = {"error": str(exc)}

    try:
        from orchestrator.utils.browser_cleanup import kill_test_run_process_tree

        cleanup["processes"] = await runtime.asyncio.to_thread(kill_test_run_process_tree, run_id)
    except Exception as exc:
        runtime.logger.warning("Failed to clean browser processes for test run %s: %s", run_id, exc)
        cleanup["processes"] = {"error": str(exc)}

    return cleanup


def cleanup_terminal_test_run_processes(runtime: Any) -> int:
    """Kill browser process trees for test runs already marked terminal."""
    try:
        from orchestrator.utils.browser_cleanup import (
            find_test_run_ids_in_processes,
            kill_test_run_process_tree,
        )
    except Exception as exc:
        runtime.logger.debug("Terminal test-run process cleanup unavailable: %s", exc)
        return 0

    terminal_statuses = {"passed", "failed", "error", "stopped", "cancelled", "completed"}
    cleaned = 0
    run_ids = find_test_run_ids_in_processes()
    if not run_ids:
        return 0

    with runtime.Session(runtime.engine) as session:
        for run_id in sorted(run_ids):
            run = session.get(runtime.DBTestRun, run_id)
            status = str(getattr(run, "status", "") or "")
            if status not in terminal_statuses:
                status_file = runtime.RUNS_DIR / run_id / "status.txt"
                if status_file.exists():
                    status = status_file.read_text(errors="replace").strip()
            if status not in terminal_statuses:
                continue
            cleanup = kill_test_run_process_tree(run_id, grace_seconds=0.5)
            if cleanup.get("matched"):
                cleaned += int(cleanup.get("matched") or 0)
                runtime.logger.info(
                    "Cleaned terminal test-run browser process tree for %s: %s",
                    run_id,
                    cleanup,
                )
    return cleaned
