import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from logging_config import get_logger
from services.browser_pool import get_browser_pool
from services.resource_manager import get_resource_manager

from . import autopilot, exploration, spec_files
from .db import engine, get_session
from .models import (
    ClearQueueRequest,
    ClearQueueResponse,
    ExecutionSettingsResponse,
    QueueStatusResponse,
    UpdateExecutionSettingsRequest,
)
from .models_db import ExecutionSettings as DBExecutionSettings
from .models_db import TestRun as DBTestRun
from .test_run_runtime_support import apply_browser_pool_parallelism

logger = get_logger(__name__)
router = APIRouter()

RUNS_DIR = spec_files.RUNS_DIR


def _runtime():
    from . import main as main_runtime

    return main_runtime


def _runs_dir() -> Path:
    return getattr(_runtime(), "RUNS_DIR", RUNS_DIR)


async def _browser_pool():
    runtime = _runtime()
    return runtime.BROWSER_POOL or await get_browser_pool()


@router.get("/health")
def health():
    """Enhanced health check with dependency status."""
    runtime = _runtime()
    checks = {}

    try:
        from sqlalchemy import text as sa_text

        with Session(engine) as session:
            session.exec(sa_text("SELECT 1"))
            checks["database"] = {"status": "ok", "type": runtime.get_database_type()}
    except Exception as e:
        checks["database"] = {"status": "error", "error": str(e)}

    try:
        runs_dir = _runs_dir()
        if runs_dir.exists() and os.access(runs_dir, os.W_OK):
            import shutil as _shutil

            disk = _shutil.disk_usage(str(runs_dir))
            disk_pct = round((disk.used / disk.total) * 100, 1)
            fs_status = "ok"
            if disk_pct >= 95:
                fs_status = "critical"
            elif disk_pct >= 90:
                fs_status = "warning"
            checks["filesystem"] = {
                "status": fs_status,
                "runs_dir": str(runs_dir),
                "disk_used_pct": disk_pct,
                "disk_free_gb": round(disk.free / (1024**3), 1),
            }
        else:
            checks["filesystem"] = {"status": "error", "error": "runs directory not writable"}
    except Exception as e:
        checks["filesystem"] = {"status": "error", "error": str(e)}

    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE

        if REDIS_AVAILABLE:
            checks["redis"] = {"status": "ok", "configured": True}
        else:
            checks["redis"] = {"status": "ok", "configured": False}
    except Exception:
        checks["redis"] = {"status": "ok", "configured": False}

    checks["processes"] = {
        "status": "ok",
        "active_count": runtime.get_active_process_count(),
        "process_manager": runtime.PROCESS_MANAGER is not None,
    }

    critical_checks = ["database", "filesystem"]
    has_critical = any(checks.get(k, {}).get("status") == "error" for k in critical_checks)
    has_warning = any(c.get("status") in ("warning", "critical") for c in checks.values())
    overall_status = "unhealthy" if has_critical else "degraded" if has_warning else "healthy"

    return {"status": overall_status, "checks": checks, "version": "1.0.0"}


@router.get("/api/browser-pool/status")
async def get_browser_pool_status():
    """Get current unified browser pool status."""
    pool = await _browser_pool()
    return await pool.get_status()


@router.get("/api/browser-pool/recent")
async def get_browser_pool_recent(limit: int = 50):
    """Get recent browser slot activity for monitoring."""
    pool = await _browser_pool()
    return {"recent_slots": await pool.get_recent_slots(limit), "current_status": await pool.get_status()}


@router.post("/api/browser-pool/cleanup")
async def cleanup_browser_pool():
    """Force cleanup of stale browser slots."""
    pool = await _browser_pool()

    stale_cleaned = await pool.cleanup_stale(max_age_minutes=60)
    old_cleaned = await pool.cleanup_old_completed(max_age_hours=24)

    return {
        "status": "success",
        "stale_slots_cleaned": stale_cleaned,
        "old_records_cleaned": old_cleaned,
        "current_status": await pool.get_status(),
    }


@router.get("/api/resources/status")
async def get_resource_status():
    """Get current resource usage status for all managed resources."""
    resource_manager = await get_resource_manager()
    legacy_status = resource_manager.get_full_status()

    pool = await _browser_pool()
    browser_pool_status = await pool.get_status()

    return {
        **legacy_status,
        "browser_pool": browser_pool_status,
        "_note": "Legacy resource_manager is deprecated. Use /api/browser-pool/status for unified browser management.",
    }


@router.get("/api/key-rotation/status")
async def get_key_rotation_status():
    """Get API key rotation status — shows available/cooled-down keys."""
    try:
        from orchestrator.services.api_key_rotator import get_api_key_rotator

        rotator = get_api_key_rotator()
        return rotator.get_status()
    except ImportError:
        return {"total_keys": 0, "available_keys": 0, "keys": [], "error": "Rotator not available"}


@router.post("/api/resources/cleanup")
async def cleanup_stale_resources():
    """Force cleanup of stale resource slots."""
    resource_manager = await get_resource_manager()
    legacy_cleaned = await resource_manager.cleanup_stale_slots()

    pool = await _browser_pool()
    pool_cleaned = await pool.cleanup_stale(max_age_minutes=60)

    return {
        "status": "success",
        "legacy_cleaned": legacy_cleaned,
        "browser_pool_cleaned": pool_cleaned,
        "message": f"Cleaned {len(legacy_cleaned)} legacy slots, {len(pool_cleaned)} browser pool slots",
    }


@router.get("/execution-settings", response_model=ExecutionSettingsResponse)
def get_execution_settings(session: Session = Depends(get_session)):
    """Get current execution settings including database type detection."""
    runtime = _runtime()
    settings = session.get(DBExecutionSettings, 1)
    if not settings:
        settings = DBExecutionSettings(id=1)
        session.add(settings)
        session.commit()
        session.refresh(settings)

    return ExecutionSettingsResponse(
        parallelism=settings.parallelism,
        parallel_mode_enabled=settings.parallel_mode_enabled,
        headless_in_parallel=settings.headless_in_parallel,
        memory_enabled=settings.memory_enabled,
        database_type=runtime.get_database_type(),
        parallel_mode_available=runtime.is_parallel_mode_available(),
    )


@router.put("/execution-settings", response_model=ExecutionSettingsResponse)
async def update_execution_settings(request: UpdateExecutionSettingsRequest, session: Session = Depends(get_session)):
    """Update execution settings."""
    runtime = _runtime()
    settings = session.get(DBExecutionSettings, 1)
    if not settings:
        settings = DBExecutionSettings(id=1)

    new_parallelism = request.parallelism if request.parallelism is not None else settings.parallelism
    if new_parallelism > 1 and not runtime.is_parallel_mode_available():
        raise HTTPException(
            status_code=400,
            detail="Parallelism > 1 requires PostgreSQL database. SQLite has write locking issues that prevent concurrent test execution.",
        )

    if request.parallelism is not None:
        settings.parallelism = max(1, min(10, request.parallelism))

    if request.parallel_mode_enabled is not None:
        if request.parallel_mode_enabled and settings.parallelism <= 1:
            settings.parallel_mode_enabled = False
        elif request.parallel_mode_enabled and not runtime.is_parallel_mode_available():
            raise HTTPException(status_code=400, detail="Parallel mode requires PostgreSQL database.")
        else:
            settings.parallel_mode_enabled = request.parallel_mode_enabled

    if request.headless_in_parallel is not None:
        settings.headless_in_parallel = request.headless_in_parallel

    if request.memory_enabled is not None:
        settings.memory_enabled = request.memory_enabled

    settings.updated_at = datetime.utcnow()

    session.add(settings)
    session.commit()
    session.refresh(settings)

    if runtime.QUEUE_MANAGER:
        await runtime.QUEUE_MANAGER.reload_settings()

    if runtime.BROWSER_POOL and (request.parallelism is not None or request.headless_in_parallel is not None):
        resolved_parallelism = await apply_browser_pool_parallelism(
            runtime.BROWSER_POOL,
            requested_parallelism=settings.parallelism,
            env=runtime.os.environ,
            execution_settings=settings,
        )
        logger.info(
            "Browser pool updated: requested=%s effective=%s mode=%s clamp=%s",
            resolved_parallelism["requested_parallelism"],
            resolved_parallelism["effective_parallelism"],
            resolved_parallelism["browser_runtime_mode"],
            resolved_parallelism["parallelism_clamp_reason"],
        )

    return ExecutionSettingsResponse(
        parallelism=settings.parallelism,
        parallel_mode_enabled=settings.parallel_mode_enabled,
        headless_in_parallel=settings.headless_in_parallel,
        memory_enabled=settings.memory_enabled,
        database_type=runtime.get_database_type(),
        parallel_mode_available=runtime.is_parallel_mode_available(),
    )


@router.get("/queue-status", response_model=QueueStatusResponse)
async def get_queue_status():
    """Get current browser-capacity queue status with legacy test-run diagnostics."""
    runtime = _runtime()

    if runtime.QUEUE_MANAGER is None:
        runtime.QUEUE_MANAGER = await runtime.QueueManager.get_instance()

    legacy_status = runtime.QUEUE_MANAGER.get_queue_status()
    pool = await _browser_pool()
    browser_pool_status = await pool.get_status()
    status = {
        **legacy_status,
        "legacy_running_count": legacy_status.get("running_count"),
        "legacy_queued_count": legacy_status.get("queued_count"),
        "legacy_parallelism_limit": legacy_status.get("parallelism_limit"),
        "running_count": int(browser_pool_status.get("running", 0) or 0),
        "queued_count": int(browser_pool_status.get("queued", 0) or 0),
        "parallelism_limit": int(browser_pool_status.get("max_browsers", 0) or 0),
        "browser_pool": browser_pool_status,
        "browser_pool_by_type": browser_pool_status.get("by_type", {}),
    }

    agent_health = None
    try:
        from orchestrator.services.agent_queue import get_agent_queue, should_use_agent_queue

        if should_use_agent_queue():
            queue = get_agent_queue()
            agent_health = await queue.get_worker_health()
    except Exception as e:
        logger.debug(f"Could not fetch agent worker health: {e}")

    return QueueStatusResponse(**status, agent_worker_health=agent_health)


@router.post("/queue/clear", response_model=ClearQueueResponse)
def clear_queue(request: ClearQueueRequest, session: Session = Depends(get_session)):
    """Clear stuck queue entries."""
    runtime = _runtime()
    cleared_runs = []

    if request.include_queued:
        queued = session.exec(select(DBTestRun).where(DBTestRun.status == "queued")).all()
        for run in queued:
            if run.temporal_workflow_id:
                continue
            if runtime.PROCESS_MANAGER:
                runtime.PROCESS_MANAGER.stop(run.id)
            run.status = "stopped"
            run.queue_position = None
            session.add(run)
            cleared_runs.append(run.id)

            run_dir = _runs_dir() / run.id
            if run_dir.exists():
                (run_dir / "status.txt").write_text("stopped")

    if request.include_running:
        running = session.exec(select(DBTestRun).where(DBTestRun.status.in_(["running", "in_progress"]))).all()
        for run in running:
            if run.temporal_workflow_id:
                continue
            if not runtime.is_process_active(run.id):
                if runtime.PROCESS_MANAGER:
                    runtime.PROCESS_MANAGER.stop(run.id)
                run.status = "stopped"
                run.queue_position = None
                session.add(run)
                cleared_runs.append(run.id)

                run_dir = _runs_dir() / run.id
                if run_dir.exists():
                    (run_dir / "status.txt").write_text("stopped")

    session.commit()

    message_parts = []
    if request.include_queued:
        message_parts.append("queued")
    if request.include_running:
        message_parts.append("orphaned running")

    return ClearQueueResponse(
        cleared_count=len(cleared_runs),
        cleared_runs=cleared_runs,
        message=f"Cleared {len(cleared_runs)} {' and '.join(message_parts)} entries",
    )


@router.post("/stop-all")
async def stop_all_jobs():
    """Global emergency stop for active runtime work."""
    runtime = _runtime()
    stopped_processes = 0
    cancelled_autopilot = 0
    cancelled_explorations = 0
    cleaned_db_entries = 0

    for run_id in runtime.list_active_process_ids():
        try:
            if runtime.PROCESS_MANAGER:
                runtime.PROCESS_MANAGER.stop(run_id)
            else:
                proc = runtime.get_process(run_id)
                if proc:
                    try:
                        import signal as _signal

                        os.killpg(os.getpgid(proc.pid), _signal.SIGTERM)
                    except (ProcessLookupError, OSError):
                        try:
                            proc.kill()
                        except (ProcessLookupError, OSError):
                            pass
        except Exception as e:
            logger.warning(f"stop-all: Error stopping process {run_id}: {e}")
        stopped_processes += 1
    runtime.clear_all_processes()

    for _sid, (task, pipeline, _) in list(autopilot._running_pipelines.items()):
        try:
            pipeline.cancel()
        except Exception:
            pass
        task.cancel()
        cancelled_autopilot += 1
    autopilot._running_pipelines.clear()

    for _sid, (task, _) in list(exploration._running_explorations.items()):
        task.cancel()
        cancelled_explorations += 1
    exploration._running_explorations.clear()

    batch_ids_to_update = set()
    active_test_run_ids: list[str] = []
    with Session(engine) as session:
        active_runs = session.exec(
            select(DBTestRun).where(DBTestRun.status.in_(["running", "in_progress", "queued"]))
        ).all()

        now = datetime.utcnow()
        for run in active_runs:
            active_test_run_ids.append(run.id)
            if run.temporal_workflow_id:
                try:
                    await runtime._signal_test_run_temporal(run, "stop", "stop_all")
                except Exception as exc:
                    logger.warning("stop-all: Failed to signal Temporal test run %s: %s", run.id, exc)
            run.status = "stopped" if run.status in ("running", "in_progress") else "cancelled"
            run.completed_at = now
            run.queue_position = None
            session.add(run)
            cleaned_db_entries += 1

            run_dir = _runs_dir() / run.id
            if run_dir.exists():
                (run_dir / "status.txt").write_text(run.status)

            if run.batch_id:
                batch_ids_to_update.add(run.batch_id)

        session.commit()

    cleaned_runtime_entries = 0
    for run_id in active_test_run_ids:
        cleanup = await runtime._cleanup_test_run_runtime(run_id, "stop all")
        agent_tasks = cleanup.get("agent_tasks")
        processes = cleanup.get("processes")
        if isinstance(agent_tasks, dict):
            cleaned_runtime_entries += int(agent_tasks.get("cancelled") or 0)
        if isinstance(processes, dict):
            cleaned_runtime_entries += int(processes.get("matched") or 0)

    for batch_id in batch_ids_to_update:
        try:
            runtime.update_batch_stats(batch_id)
        except Exception as e:
            logger.error(f"stop-all: Failed to update batch {batch_id}: {e}")

    logger.warning(
        f"stop-all: stopped_processes={stopped_processes}, "
        f"cancelled_autopilot={cancelled_autopilot}, "
        f"cancelled_explorations={cancelled_explorations}, "
        f"cleaned_db_entries={cleaned_db_entries}, "
        f"cleaned_runtime_entries={cleaned_runtime_entries}"
    )

    return {
        "stopped_processes": stopped_processes,
        "cancelled_autopilot": cancelled_autopilot,
        "cancelled_explorations": cancelled_explorations,
        "cleaned_db_entries": cleaned_db_entries,
        "cleaned_runtime_entries": cleaned_runtime_entries,
    }


@router.get("/debug-imports")
def debug_imports():
    """Debug endpoint to check sys.path and test imports."""
    import_result: dict[str, Any] = {"success": False, "error": None}
    try:
        import_result["success"] = True
    except Exception as e:
        import_result["error"] = str(e)

    orchestrator_dir = Path(__file__).resolve().parent.parent
    return {
        "sys.path_first_5": sys.path[:5],
        "orchestrator_dir": str(orchestrator_dir),
        "orchestrator_in_path": str(orchestrator_dir) in sys.path,
        "utils_exists": (orchestrator_dir / "utils" / "json_utils.py").exists(),
        "import_test": import_result,
        "current_dir": str(Path.cwd()),
    }
