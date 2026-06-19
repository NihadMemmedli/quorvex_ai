from typing import Any

from fastapi import APIRouter
from sqlalchemy import func
from sqlmodel import Session, select

from logging_config import get_logger
from services.browser_pool import get_browser_pool

from .db import engine
from .models_db import AgentRun

logger = get_logger(__name__)
router = APIRouter(tags=["agent-queue"])

AGENT_QUEUE_ACTIVE_STATUSES = ["queued", "pending", "running", "paused"]
AGENT_QUEUE_QUEUED_STATUSES = ["queued", "pending"]


def _runtime():
    from . import main as main_runtime

    return main_runtime


async def _browser_pool():
    runtime = _runtime()
    return runtime.BROWSER_POOL or await get_browser_pool()


def _agent_run_queue_summary(run: AgentRun) -> dict[str, Any]:
    """Return a compact queue-compatible summary for a persisted AgentRun."""
    progress = run.progress or {}
    progress_summary = {
        key: progress.get(key)
        for key in (
            "phase",
            "activity_label",
            "status",
            "message",
            "current_stage",
            "tool_calls",
            "browser_tool_calls",
            "interactions",
            "last_tool",
            "last_tool_label",
        )
        if key in progress and progress.get(key) is not None
    }
    return {
        "id": run.id,
        "status": run.status,
        "worker_id": None,
        "agent_type": run.agent_type,
        "operation_type": "agent",
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "timeout_seconds": None,
        "heartbeat_alive": None,
        "owner_type": "agent_run",
        "owner_id": run.id,
        "agent_run_id": run.id,
        "agent_task_id": run.agent_task_id,
        "source": "agent_run",
        "live": True,
        "orphaned": False,
        "progress": progress_summary,
        "message": progress_summary.get("message"),
    }


@router.get("/api/agents/queue-status")
async def get_agent_queue_status():
    """Get current agent queue status.

    Returns Redis-backed agent queue metrics when queue mode is active.
    Browser pool status is included only as auxiliary capacity context.
    """
    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE, get_agent_queue, should_use_agent_queue

        if REDIS_AVAILABLE and should_use_agent_queue():
            queue = get_agent_queue()
            await queue.connect()
            metrics = await queue.get_metrics()
            health = await queue.get_worker_health()
            running_task_summaries = await queue.get_running_task_summaries()
            live_running_tasks = [
                task for task in running_task_summaries if task.get("live")
            ]
            active_agent_runs: list[AgentRun] = []
            try:
                with Session(engine) as session:
                    active_agent_runs = list(
                        session.exec(
                            select(AgentRun)
                            .where(AgentRun.status.in_(AGENT_QUEUE_ACTIVE_STATUSES))
                            .order_by(AgentRun.created_at.desc())
                        ).all()
                    )
            except Exception as exc:
                logger.debug("Failed to load active AgentRun rows for queue status: %s", exc)

            live_task_ids = {str(task.get("id")) for task in live_running_tasks if task.get("id")}
            live_agent_run_owner_ids = {
                str(task.get("owner_id"))
                for task in live_running_tasks
                if task.get("owner_type") == "agent_run" and task.get("owner_id")
            }
            active_run_ids = {run.id for run in active_agent_runs}
            active_run_task_ids = {run.agent_task_id for run in active_agent_runs if run.agent_task_id}
            persisted_run_summaries = [
                _agent_run_queue_summary(run)
                for run in active_agent_runs
                if run.id not in live_agent_run_owner_ids
                and (not run.agent_task_id or run.agent_task_id not in live_task_ids)
            ]
            redis_tasks_not_backed_by_active_runs = [
                task
                for task in live_running_tasks
                if not (
                    task.get("owner_type") == "agent_run"
                    and task.get("owner_id")
                    and str(task.get("owner_id")) in active_run_ids
                )
                and not (task.get("id") and str(task.get("id")) in active_run_task_ids)
            ]
            active_run_count = len(active_agent_runs)
            queue_task_active_count = len(live_running_tasks)
            redis_queue_length = int(metrics.get("queue_length", 0) or 0)
            unrepresented_queued_runs = [
                run
                for run in active_agent_runs
                if run.status in AGENT_QUEUE_QUEUED_STATUSES
                and run.id not in live_agent_run_owner_ids
                and (not run.agent_task_id or run.agent_task_id not in live_task_ids)
            ]
            merged_running_tasks = live_running_tasks + persisted_run_summaries
            pool = await _browser_pool()
            browser_pool_status = await pool.get_status()
            linked_tasks = [task for task in live_running_tasks if task.get("owner_type")]
            background_tasks = [task for task in live_running_tasks if not task.get("owner_type")]
            orphaned_tasks = [
                task for task in running_task_summaries if task.get("orphaned")
            ]
            worker_process_count = int(health.get("worker_count") or 0)
            alive_running_tasks = int(health.get("alive_tasks") or 0)
            raw_running_count = int(metrics.get("running", 0) or 0)
            running_count = active_run_count + len(redis_tasks_not_backed_by_active_runs)
            workers_busy = min(worker_process_count, running_count)
            workers_idle = max(0, worker_process_count - workers_busy)
            if worker_process_count > 0:
                capacity_state = "workers_saturated" if workers_idle == 0 and running_count > 0 else "workers_available"
            elif running_count > 0 and alive_running_tasks > 0:
                capacity_state = "running_tasks_alive"
            elif raw_running_count > 0:
                capacity_state = "running_tasks_stale"
            else:
                capacity_state = "no_workers"
            return {
                "mode": "redis",
                "active": running_count,
                "active_runs": active_run_count,
                "queue_tasks_active": queue_task_active_count,
                "raw_running": raw_running_count,
                "queued": redis_queue_length + len(unrepresented_queued_runs),
                "workers_alive": metrics.get("workers_alive", 0),
                "worker_processes_alive": worker_process_count,
                "workers_busy": workers_busy,
                "workers_idle": workers_idle,
                "running_task_heartbeats_alive": alive_running_tasks,
                "capacity_state": capacity_state,
                "stale_running": metrics.get("stale_running", 0),
                "oldest_queued_age_seconds": metrics.get("oldest_queued_age_seconds"),
                "by_status": metrics.get("by_status", {}),
                "worker_health": health,
                "running_tasks": merged_running_tasks,
                "linked_tasks": len(linked_tasks),
                "background_tasks": len(background_tasks),
                "orphaned_tasks": len(orphaned_tasks),
                "browser_pool": browser_pool_status,
            }
    except Exception as exc:
        logger.warning(f"Failed to read Redis agent queue status: {exc}")

    pool = await _browser_pool()
    status = await pool.get_status()
    agent_running = status["by_type"].get("agent", 0)
    temporal_health = None
    temporal_workers_alive = 0
    active_temporal_agent_runs = 0
    temporal_queued_agent_runs = 0
    try:
        from orchestrator.services.temporal_client import check_agent_run_temporal_health

        temporal_health = await check_agent_run_temporal_health()
        pollers = temporal_health.get("worker_pollers") or {}
        temporal_workers_alive = min(int(pollers.get("workflow") or 0), int(pollers.get("activity") or 0))
    except Exception as exc:
        temporal_health = {"available": False, "status": "unavailable", "error": str(exc)}

    try:
        with Session(engine) as session:
            active_temporal_agent_runs = session.exec(
                select(func.count())
                .select_from(AgentRun)
                .where(AgentRun.status.in_(AGENT_QUEUE_ACTIVE_STATUSES))
                .where(AgentRun.temporal_workflow_id != None)  # noqa: E711
            ).one()
            temporal_queued_agent_runs = session.exec(
                select(func.count())
                .select_from(AgentRun)
                .where(AgentRun.status.in_(["queued", "pending"]))
                .where(AgentRun.temporal_workflow_id != None)  # noqa: E711
            ).one()
    except Exception as exc:
        logger.debug("Failed to count Temporal agent runs: %s", exc)

    running_tasks = []
    for request_id in status.get("running_requests", []):
        slot = pool.get_slot(request_id)
        if not slot or slot.operation_type.value != "agent":
            continue
        running_tasks.append(
            {
                "id": request_id,
                "status": slot.status.value,
                "worker_id": None,
                "agent_type": None,
                "operation_type": slot.operation_type.value,
                "created_at": slot.queued_at.isoformat() if slot.queued_at else None,
                "started_at": slot.started_at.isoformat() if slot.started_at else None,
                "timeout_seconds": slot.max_operation_duration,
                "heartbeat_alive": True,
                "progress": {
                    "activity_label": slot.description,
                },
            }
        )

    return {
        "mode": "temporal",
        "active": active_temporal_agent_runs or agent_running,
        "max": status["max_browsers"],
        "queued": temporal_queued_agent_runs,
        "available": status["available"],
        "workers_alive": temporal_workers_alive,
        "worker_processes_alive": temporal_workers_alive,
        "workers_busy": min(temporal_workers_alive, active_temporal_agent_runs),
        "workers_idle": max(0, temporal_workers_alive - min(temporal_workers_alive, active_temporal_agent_runs)),
        "capacity_state": "workers_alive" if temporal_workers_alive > 0 else "no_temporal_workers",
        "temporal": temporal_health,
        "pool_status": {"total_running": status["running"], "by_type": status["by_type"]},
        "browser_pool": status,
        "running_tasks": running_tasks,
    }


@router.post("/api/agents/queue-flush")
async def flush_agent_queue():
    """Flush the agent queue — cancel queued tasks and fail running ones.

    Use this to recover from stuck queue state (e.g., after container restart
    left orphaned tasks, or workers are unresponsive).
    """
    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE, get_agent_queue, should_use_agent_queue

        if not REDIS_AVAILABLE or not should_use_agent_queue():
            return {"status": "skipped", "message": "Agent queue not active (no Redis)"}

        queue = get_agent_queue()
        await queue.connect()
        result = await queue.flush_queue()
        return {
            "status": "success",
            **result,
            "message": f"Flushed queue: {result['queued_cancelled']} queued cancelled, {result['running_failed']} running failed",
        }
    except Exception as e:
        logger.error(f"Queue flush failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


async def _clean_stale_agent_queue_tasks() -> dict[str, Any]:
    """Cancel agent queue tasks whose owner, heartbeat, or timeout state is invalid."""
    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE, get_agent_queue, should_use_agent_queue

        if not REDIS_AVAILABLE or not should_use_agent_queue():
            return {"status": "skipped", "message": "Agent queue not active (no Redis)"}

        queue = get_agent_queue()
        await queue.connect()
        result = await queue.cleanup_orphaned_and_stale_tasks()
        cleaned = sum(v for k, v in result.items() if k != "skipped_active")
        return {
            "status": "success",
            "cleaned": cleaned,
            **result,
        }
    except Exception as e:
        logger.error(f"Agent queue cleanup failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@router.post("/api/agents/queue-clean-stale")
async def clean_stale_agent_queue_tasks():
    """Cancel stale or orphaned agent queue tasks."""
    return await _clean_stale_agent_queue_tasks()


@router.post("/api/agents/queue-clean-orphans")
async def clean_orphaned_agent_queue_tasks():
    """Compatibility alias for stale/orphaned agent queue cleanup."""
    return await _clean_stale_agent_queue_tasks()
