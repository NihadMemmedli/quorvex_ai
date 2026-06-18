# CRITICAL: Load environment variables FIRST before any other imports
from dotenv import load_dotenv

load_dotenv()

# CRITICAL: Add orchestrator directory to sys.path BEFORE any other imports
# This ensures that imports like "from utils.json_utils" work correctly
import os
import sys
from pathlib import Path

orchestrator_dir = Path(__file__).resolve().parent.parent
if str(orchestrator_dir) not in sys.path:
    sys.path.insert(0, str(orchestrator_dir))

import asyncio
import shutil  # noqa: F401
import subprocess
import threading
import uuid
from datetime import datetime, timedelta  # noqa: F401
from typing import Any

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from sqlmodel import Session, select
from starlette.requests import Request
from starlette.responses import JSONResponse

from logging_config import get_logger, request_id_var, setup_logging
from orchestrator.services.agent_runtimes import normalize_agent_runtime  # noqa: F401
from orchestrator.services.browser_auth_sessions import (
    BrowserAuthSessionError,  # noqa: F401
    ensure_browser_auth_session_usable,  # noqa: F401
    resolve_browser_auth_for_run,  # noqa: F401
    resolve_browser_auth_session_row,  # noqa: F401
)
from orchestrator.services.browser_slots import browser_operation_slot  # noqa: F401
from orchestrator.services.coding_agent import (  # noqa: F401
    CODING_ARTIFACT_PATCH,
    DEFAULT_REPO_ROOT,
    build_coding_agent_prompt,
    build_coding_tool_permission_guard,
    coding_agent_allowed_tools,
    coding_agent_subagents,
    validate_patch_for_repo,
    write_coding_artifacts,
)
from services.browser_pool import AbstractBrowserPool, get_browser_pool
from services.browser_pool import OperationType as BrowserOpType  # noqa: F401
from services.resource_manager import (
    ResourceManager,
    get_resource_manager,  # noqa: F401
)
from utils.agent_report import (  # noqa: F401
    CUSTOM_AGENT_REPORT_INSTRUCTIONS,
    _as_report_list,
    _build_custom_agent_structured_report,
    _clean_text,
)
from utils.agent_tool_allowlists import get_agent_allowed_tools  # noqa: F401
from utils.claude_config import copy_claude_project_config  # noqa: F401
from utils.playwright_mcp import (
    browser_runtime_status,  # noqa: F401
    prepare_run_playwright_config_content,  # noqa: F401
    write_playwright_test_mcp_config,  # noqa: F401
)
from utils.project_utils import derive_project_id_from_url  # noqa: F401

from . import (
    agent_background_runner_support,
    agent_coding_patch,
    agent_compat_alias_support,
    agent_definitions,
    agent_dependency_support,
    agent_exploratory,
    agent_queue_ops,
    agent_reports,
    agent_run_control,
    agent_run_launch,
    agent_run_observability,
    agent_run_runtime_support,
    agent_sessions,
    agent_tool_catalog_support,
    analytics,
    api_testing,
    auth,
    autonomous,
    autopilot,
    backup_control,
    browser_auth_sessions,
    chat,
    ci_control,
    dashboard,
    database_testing,
    exploration,
    github_ci,
    gitlab_ci,
    health,
    jira,
    llm_testing,
    load_testing,
    memory,
    prd,
    projects,
    recordings,
    regression,
    requirements,
    rtm,
    run_files,
    runs,
    runtime_ops,
    scheduling,
    security_testing,
    settings,
    spec_files,
    specs,
    startup_diagnostics_support,
    test_data,
    test_run_batch_watchdog_support,
    test_run_cleanup_support,
    test_run_maintenance_loop_support,
    test_run_process_registry_support,
    test_run_queue_manager_support,
    test_run_read_model_support,
    test_run_runtime_support,
    test_run_schedule_watchdog_support,
    testrail,
    testrail_files,
    users,
    workflows,
)
from .db import (
    engine,
    get_database_type,  # noqa: F401
    get_session,
    init_db,
    is_parallel_mode_available,  # noqa: F401
)
from .middleware.auth import get_current_user_optional
from .middleware.permissions import ProjectRole, check_project_access  # noqa: F401
from .middleware.rate_limit import limiter, rate_limit_exceeded_handler
from .models_db import (
    AgentRun,  # noqa: F401 - exposed through main for agent dependency compatibility
    ExplorationSession,  # noqa: F401
    RegressionBatch,  # noqa: F401
)
from .models_db import ExecutionSettings as DBExecutionSettings
from .models_db import SpecMetadata as DBSpecMetadata  # noqa: F401
from .models_db import TestRun as DBTestRun
from .models_db import get_spec_metadata as get_db_spec_metadata  # noqa: F401
from .process_manager import ProcessManager, get_process_manager

# Initialize logging
setup_logging(level="INFO", console=True)
logger = get_logger(__name__)

BASE_DIR = spec_files.BASE_DIR
SPECS_DIR = spec_files.SPECS_DIR
RUNS_DIR = spec_files.RUNS_DIR
METADATA_FILE = spec_files.METADATA_FILE
MAX_UPLOAD_SIZE_BYTES = testrail_files.MAX_UPLOAD_SIZE_BYTES
ALLOWED_UPLOAD_TYPES = testrail_files.ALLOWED_UPLOAD_TYPES
sync_spec_metadata_from_file = spec_files.sync_spec_metadata_from_file
get_try_code_path_fast = spec_files.get_try_code_path_fast
get_cached_spec_info = spec_files.get_cached_spec_info
get_try_code_path = spec_files.get_try_code_path
invalidate_code_path_cache = spec_files.invalidate_code_path_cache

RUN_BROWSER_METADATA_FILE = run_files.RUN_BROWSER_METADATA_FILE
RUN_SEED_SPEC_RELATIVE_PATH = run_files.RUN_SEED_SPEC_RELATIVE_PATH
RUN_TARGET_URL_PATTERNS = run_files.RUN_TARGET_URL_PATTERNS
REAL_BROWSER_EXECUTABLE_NAMES = run_files.REAL_BROWSER_EXECUTABLE_NAMES
ACTIVE_RUN_STATUSES = run_files.ACTIVE_RUN_STATUSES
_build_run_browser_metadata = run_files.build_run_browser_metadata
_merge_run_browser_metadata = run_files.merge_run_browser_metadata
_write_run_browser_metadata = run_files.write_run_browser_metadata
_load_run_browser_metadata = run_files.load_run_browser_metadata
_extract_run_target_url_from_content = run_files.extract_run_target_url_from_content
_extract_run_target_url = run_files.extract_run_target_url
_write_run_seed_spec = run_files.write_run_seed_spec
_is_real_browser_process_line = run_files.is_real_browser_process_line
_browser_window_lines = run_files.browser_window_lines
_live_browser_display_diagnostics = run_files.live_browser_display_diagnostics_for_run
_augment_active_browser_metadata = run_files.augment_active_browser_metadata
_compose_test_run_log_payload = run_files.compose_test_run_log_payload

# Background task handles for graceful shutdown
_BACKGROUND_TASKS: list[asyncio.Task] = []


app = FastAPI(title="Quorvex AI API")

# Add rate limiter state to app
app.state.limiter = limiter

# Add rate limit exception handler
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    req_id = request_id_var.get("")
    logger.error(f"Unhandled exception [req={req_id}]: {exc}", exc_info=True)
    # Include CORS headers so browsers can read the error response
    origin = request.headers.get("origin", "")
    headers = {}
    if origin in ALLOWED_ORIGINS:
        headers["access-control-allow-origin"] = origin
        headers["access-control-allow-credentials"] = "true"
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": req_id},
        headers=headers,
    )


# Include routers
app.include_router(auth.router)  # Auth endpoints first
app.include_router(users.router)  # User management (superuser only)
app.include_router(dashboard.router)
app.include_router(settings.router)
app.include_router(specs.router)
app.include_router(memory.router)
app.include_router(prd.router)
app.include_router(regression.router)
app.include_router(projects.router)
app.include_router(test_data.router)
app.include_router(browser_auth_sessions.router)
app.include_router(recordings.router)
app.include_router(exploration.router)
app.include_router(requirements.router)
app.include_router(rtm.router)
app.include_router(testrail.router)  # TestRail integration
app.include_router(testrail_files.router)  # Legacy TestRail file import/export
app.include_router(jira.router)  # Jira integration
app.include_router(scheduling.router)  # Cron scheduling
app.include_router(ci_control.router)  # Provider-neutral CI/CD control center
app.include_router(gitlab_ci.router)  # GitLab CI/CD integration
app.include_router(github_ci.router)  # GitHub Actions integration
app.include_router(api_testing.router)  # API testing endpoints
app.include_router(load_testing.router)  # Load testing endpoints
app.include_router(security_testing.router)  # Security testing endpoints
app.include_router(database_testing.router)  # Database testing endpoints
app.include_router(llm_testing.router)  # LLM/AI testing endpoints
app.include_router(analytics.router)  # Analytics dashboard
app.include_router(health.router)  # Storage health endpoints
app.include_router(chat.router)  # AI assistant chat endpoints
app.include_router(autopilot.router)  # Auto Pilot pipeline endpoints
app.include_router(autonomous.router)  # Persistent autonomous testing missions
app.include_router(runs.router)  # Test run lifecycle endpoints
app.include_router(runtime_ops.router)  # Operational runtime, queue, health, and debug endpoints
app.include_router(agent_queue_ops.router)  # Legacy agent queue operation endpoints
app.include_router(workflows.router)  # Custom workflow endpoints
app.include_router(backup_control.router)  # Database backup control endpoints
app.include_router(agent_sessions.router)  # Legacy agent authentication session endpoints
app.mount("/artifacts", StaticFiles(directory=RUNS_DIR), name="artifacts")

# CORS Configuration - restrict origins in production
# Set ALLOWED_ORIGINS env var with comma-separated URLs (e.g., "https://app.company.com,http://localhost:3000")
DEFAULT_ALLOWED_ORIGINS = "http://localhost:3000,http://host.docker.internal:3000"
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Add request logging middleware
from starlette.middleware.base import BaseHTTPMiddleware


class RequestLoggingMiddlewareHTTP(BaseHTTPMiddleware):
    """HTTP middleware wrapper for request logging."""

    async def dispatch(self, request, call_next):
        import time as time_module

        request_id = str(uuid.uuid4())[:8]
        start_time = time_module.time()

        # Log request (skip noisy endpoints)
        path = request.url.path
        if not path.startswith("/health") and not path.startswith("/artifacts"):
            logger.info(f"[{request_id}] --> {request.method} {path}")

        try:
            response = await call_next(request)

            # Log response (skip noisy endpoints)
            if not path.startswith("/health") and not path.startswith("/artifacts"):
                duration_ms = (time_module.time() - start_time) * 1000
                log_level = (
                    "info" if response.status_code < 400 else "warning" if response.status_code < 500 else "error"
                )
                getattr(logger, log_level)(f"[{request_id}] <-- {response.status_code} in {duration_ms:.1f}ms")

            # Add request ID header
            response.headers["X-Request-ID"] = request_id
            return response

        except Exception as e:
            duration_ms = (time_module.time() - start_time) * 1000
            logger.error(f"[{request_id}] <-- ERROR in {duration_ms:.1f}ms: {e}")
            raise


app.add_middleware(RequestLoggingMiddlewareHTTP)


# Request size limit middleware (50MB max)
class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests larger than the configured limit."""

    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB

    async def dispatch(self, request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.MAX_CONTENT_LENGTH:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request too large. Maximum size is {self.MAX_CONTENT_LENGTH // (1024 * 1024)}MB."},
            )
        return await call_next(request)


app.add_middleware(RequestSizeLimitMiddleware)

# Limit concurrent test executions
EXECUTION_SEMAPHORE: asyncio.Semaphore | None = None
# Track active processes: run_id -> subprocess.Popen object
# NOTE: This is now also backed by ProcessManager for persistence
# Protected by _processes_lock for thread safety (accessed from both event loop and thread pool)
ACTIVE_PROCESSES: dict[str, subprocess.Popen] = {}
_processes_lock = threading.Lock()


def register_process(run_id: str, proc: subprocess.Popen) -> None:
    """Thread-safe registration of an active process."""
    return test_run_process_registry_support.register_process(_test_run_runtime(), run_id, proc)


def unregister_process(run_id: str) -> subprocess.Popen | None:
    """Thread-safe removal of an active process. Returns the process if found."""
    return test_run_process_registry_support.unregister_process(_test_run_runtime(), run_id)


def get_process(run_id: str) -> subprocess.Popen | None:
    """Thread-safe retrieval of an active process."""
    return test_run_process_registry_support.get_process(_test_run_runtime(), run_id)


def is_process_active(run_id: str) -> bool:
    """Thread-safe check if a process is active."""
    return test_run_process_registry_support.is_process_active(_test_run_runtime(), run_id)


def get_active_process_count() -> int:
    """Thread-safe count of active processes."""
    return test_run_process_registry_support.get_active_process_count(_test_run_runtime())


def list_active_process_ids() -> list:
    """Thread-safe list of active process IDs."""
    return test_run_process_registry_support.list_active_process_ids(_test_run_runtime())


def clear_all_processes() -> dict[str, subprocess.Popen]:
    """Thread-safe clear of all processes. Returns the old dict."""
    return test_run_process_registry_support.clear_all_processes(_test_run_runtime())


# Process manager for persistent tracking and graceful termination
PROCESS_MANAGER: ProcessManager | None = None


QueueManager = test_run_queue_manager_support.QueueManager


# Global queue manager instance
QUEUE_MANAGER: QueueManager | None = None

# Global resource manager instance for agent/exploration/PRD concurrency
# DEPRECATED: Use BROWSER_POOL instead for unified browser management
RESOURCE_MANAGER: ResourceManager | None = None

# Unified browser resource pool - limits ALL browser operations to MAX_BROWSER_INSTANCES (default: 5)
BROWSER_POOL: AbstractBrowserPool | None = None


def cleanup_orphaned_runs():
    """Mark stuck running/queued entries as stopped on startup.

    This handles the case where the server restarts and loses the in-memory
    ACTIVE_PROCESSES dict, leaving DB entries in running/queued state.

    IMPORTANT: Preserves runs that already completed (status.txt has terminal status).
    """
    return test_run_cleanup_support.cleanup_orphaned_runs(_test_run_runtime())


async def _cleanup_test_run_runtime(run_id: str, reason: str = "cleanup requested") -> dict[str, object]:
    """Cancel agent tasks and browser process trees owned by one test run."""
    return await test_run_cleanup_support.cleanup_test_run_runtime(
        _test_run_runtime(),
        run_id,
        reason,
    )


def cleanup_terminal_test_run_processes() -> int:
    """Kill browser process trees for test runs already marked terminal."""
    return test_run_cleanup_support.cleanup_terminal_test_run_processes(_test_run_runtime())


def sync_data_from_files():
    """Sync existing file-based runs and metadata to DB on startup."""
    return test_run_read_model_support.sync_data_from_files(_test_run_runtime())


@app.on_event("startup")
async def startup_event():
    global EXECUTION_SEMAPHORE, QUEUE_MANAGER, PROCESS_MANAGER, RESOURCE_MANAGER, BROWSER_POOL

    # Initialize DB first (this also initializes ExecutionSettings)
    # NOTE: Alembic's env.py calls fileConfig(alembic.ini) which resets
    # the root logger to WARN level with only a stderr handler, wiping
    # any handlers setup_logging() attached at module-import time.
    init_db()

    # Re-apply logging AFTER init_db() so our handlers survive Alembic's
    # fileConfig() call.  This restores both the RotatingFileHandler
    # (/app/logs/orchestrator.log) and the coloured console handler,
    # and also overrides uvicorn's default LOGGING_CONFIG.
    setup_logging(level="INFO", console=True)
    logger.info("Logging re-initialized after uvicorn startup + Alembic migrations")

    try:
        from orchestrator.services.workflow_step_registry import sync_builtin_workflow_step_types

        with Session(engine) as session:
            synced_steps = sync_builtin_workflow_step_types(session)
        logger.info("Workflow step registry synced: %d built-in step types", len(synced_steps))
    except Exception as exc:
        logger.warning("Workflow step registry sync failed during startup: %s", exc)

    # Initialize ProcessManager and cleanup orphaned processes from previous runs
    PROCESS_MANAGER = get_process_manager()
    # Clear stale asyncio task references from previous server instance
    # (tasks don't survive uvicorn reload, so any references are dangling)
    PROCESS_MANAGER._asyncio_tasks.clear()
    orphans_cleaned = PROCESS_MANAGER.cleanup_orphans()
    if orphans_cleaned > 0:
        logger.info(f"Cleaned up {orphans_cleaned} orphaned processes from previous server instance")

    # Clean up orphaned runs in database before initializing queue (important for accurate queue status)
    cleanup_orphaned_runs()
    terminal_run_processes_cleaned = cleanup_terminal_test_run_processes()
    if terminal_run_processes_cleaned:
        logger.info(
            "Cleaned up %d browser process(es) from terminal test runs",
            terminal_run_processes_cleaned,
        )

    # Read parallelism from database settings (or use env default)
    db_max_browsers = int(os.environ.get("MAX_BROWSER_INSTANCES", "5"))
    with Session(engine) as session:
        settings = session.get(DBExecutionSettings, 1)
        if settings:
            db_max_browsers = settings.parallelism
            logger.info(f"Using parallelism from database settings: {db_max_browsers}")
        else:
            logger.info(f"No database settings found, using default: {db_max_browsers}")

    # Initialize unified BrowserResourcePool with parallelism from DB
    BROWSER_POOL = await get_browser_pool(max_browsers=db_max_browsers)
    logger.info(f"BrowserResourcePool initialized: max_browsers={BROWSER_POOL.max_browsers}")

    # Clean up any stale browser slots from previous server instance
    stale_cleaned = await BROWSER_POOL.cleanup_stale(max_age_minutes=60)
    if stale_cleaned:
        logger.info(f"Cleaned up {len(stale_cleaned)} stale browser slots")

    # Initialize QueueManager (DEPRECATED - kept for backward compatibility)
    QUEUE_MANAGER = await QueueManager.get_instance()

    # Initialize ResourceManager for agent/exploration/PRD concurrency control
    # DEPRECATED - use BROWSER_POOL instead for unified browser management
    RESOURCE_MANAGER = await ResourceManager.get_instance()
    logger.info(
        f"ResourceManager initialized with limits: agents={RESOURCE_MANAGER._max_agents}, explorations={RESOURCE_MANAGER._max_explorations}, prd={RESOURCE_MANAGER._max_prd}"
    )

    # Legacy semaphore for backward compatibility during transition
    EXECUTION_SEMAPHORE = asyncio.Semaphore(QUEUE_MANAGER.parallelism)

    # Run Sync in background or immediate? Immediate is safer for consistency on first load
    sync_data_from_files()

    # Start agent queue: clean orphaned tasks from previous run, then start cleanup loop
    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE, get_agent_queue, should_use_agent_queue

        if REDIS_AVAILABLE and should_use_agent_queue():
            queue = get_agent_queue()
            await queue.connect()
            # Flush orphaned "running" tasks from previous container/process
            orphaned = await queue.cleanup_orphaned_tasks()
            if orphaned:
                logger.info(f"Cleaned {orphaned} orphaned agent tasks from previous run")
            _BACKGROUND_TASKS.append(asyncio.create_task(queue.start_cleanup_loop(interval_seconds=300)))
            logger.info("Started agent queue cleanup loop")
    except Exception as e:
        logger.warning(f"Could not start agent queue cleanup loop: {e}")

    # Start K6 queue stale task cleanup loop (every 5 minutes)
    try:
        from orchestrator.services.k6_queue import REDIS_AVAILABLE as K6_REDIS_AVAILABLE
        from orchestrator.services.k6_queue import get_k6_queue, should_use_k6_queue

        if K6_REDIS_AVAILABLE and should_use_k6_queue():
            k6_queue = get_k6_queue()
            await k6_queue.connect()
            _BACKGROUND_TASKS.append(asyncio.create_task(k6_queue.start_cleanup_loop(interval_seconds=300)))
            logger.info("K6 distributed mode ACTIVE - started queue cleanup loop")
        else:
            logger.info("K6 distributed mode INACTIVE - load tests will run locally in backend container")
    except Exception as e:
        logger.warning(f"Could not start K6 queue cleanup loop: {e}")
        logger.info("K6 distributed mode INACTIVE - load tests will run locally in backend container")

    # Start job queue cleanup loop
    try:
        from orchestrator.services.job_queue import REDIS_AVAILABLE as JOB_REDIS_AVAILABLE
        from orchestrator.services.job_queue import get_job_queue

        if JOB_REDIS_AVAILABLE:
            jq = get_job_queue()
            await jq.connect()
            _BACKGROUND_TASKS.append(asyncio.create_task(jq.start_cleanup_loop(interval_seconds=300)))
            logger.info("Started job queue cleanup loop")
    except Exception as e:
        logger.warning(f"Could not start job queue cleanup loop: {e}")

    # Start batch watchdog to detect and clean up stuck runs
    _BACKGROUND_TASKS.append(asyncio.create_task(_batch_watchdog()))
    logger.info("Started batch watchdog")

    # Start queue watchdog to detect orphaned queued entries after uvicorn reload
    _BACKGROUND_TASKS.append(asyncio.create_task(_queue_watchdog()))
    logger.info("Started queue watchdog (30s interval, 60s grace period)")

    # Start PR quality gate finalizer to recover missed GitHub feedback updates
    _BACKGROUND_TASKS.append(asyncio.create_task(_quality_gate_finalizer_loop()))
    logger.info("Started quality gate finalizer loop")

    # Start exploration cleanup loop to detect stuck explorations
    _BACKGROUND_TASKS.append(asyncio.create_task(_exploration_cleanup_loop()))
    logger.info("Started exploration cleanup loop")

    # Start periodic browser pool cleanup (every 10 min)
    _BACKGROUND_TASKS.append(asyncio.create_task(_browser_pool_cleanup_loop()))
    logger.info("Started browser pool cleanup loop (10 min interval)")

    # Start infrastructure maintenance (orphan/temp cleanup every 15 min, DB maintenance daily)
    _BACKGROUND_TASKS.append(asyncio.create_task(_infrastructure_maintenance_loop()))
    logger.info("Started infrastructure maintenance loop (15 min interval)")

    # Initialize cron scheduler
    try:
        from orchestrator.services.scheduler import (
            init_scheduler,
            reconcile_workflow_schedule_executions,
            restore_schedules_from_db,
        )

        init_scheduler(engine)
        await restore_schedules_from_db()
        await reconcile_workflow_schedule_executions()
        _BACKGROUND_TASKS.append(asyncio.create_task(_schedule_execution_watchdog()))
        logger.info("Started cron scheduler and execution watchdog")
    except Exception as e:
        logger.error(f"Failed to initialize scheduler: {e}")

    # Resume interrupted Auto Pilot sessions
    try:
        from .autopilot import resume_interrupted_sessions

        resumed = await resume_interrupted_sessions()
        if resumed:
            logger.info(f"Resumed {resumed} interrupted Auto Pilot session(s)")
    except Exception as e:
        logger.warning(f"Could not resume Auto Pilot sessions: {e}")

    # Log startup diagnostics
    await _log_startup_diagnostics()

    logger.info("Server startup complete")


@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully shut down all running processes."""
    global PROCESS_MANAGER

    logger.info("Server shutting down, stopping all processes...")

    # Shut down cron scheduler first
    try:
        from orchestrator.services.scheduler import shutdown_scheduler

        shutdown_scheduler()
    except Exception as e:
        logger.debug(f"Scheduler shutdown: {e}")

    if PROCESS_MANAGER:
        stopped = PROCESS_MANAGER.shutdown_all(timeout=10)
        logger.info(f"Stopped {stopped} processes during shutdown")

    # Update all running/queued runs to stopped in database
    with Session(engine) as session:
        stuck_runs = session.exec(
            select(DBTestRun).where(DBTestRun.status.in_(["running", "in_progress", "queued"]))
        ).all()

        for run in stuck_runs:
            run.status = "stopped"
            run.queue_position = None
            run.completed_at = datetime.utcnow()
            session.add(run)

            # Update status file
            run_dir = RUNS_DIR / run.id
            if run_dir.exists():
                (run_dir / "status.txt").write_text("stopped")

        session.commit()
        if stuck_runs:
            logger.info(f"Marked {len(stuck_runs)} runs as stopped during shutdown")

    # Cancel background tasks first (before Redis disconnect since tasks may use Redis)
    for task in _BACKGROUND_TASKS:
        task.cancel()
    for task in _BACKGROUND_TASKS:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    _BACKGROUND_TASKS.clear()
    logger.info("All background tasks cancelled")

    # Disconnect Redis connections to prevent connection leaks
    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE, get_agent_queue

        if REDIS_AVAILABLE:
            queue = get_agent_queue()
            await queue.disconnect()
            logger.info("Disconnected agent queue Redis connection")
    except Exception as e:
        logger.debug(f"Agent queue disconnect: {e}")

    try:
        from orchestrator.services.k6_queue import REDIS_AVAILABLE as K6_REDIS_AVAILABLE
        from orchestrator.services.k6_queue import get_k6_queue

        if K6_REDIS_AVAILABLE:
            k6q = get_k6_queue()
            await k6q.disconnect()
            logger.info("Disconnected K6 queue Redis connection")
    except Exception as e:
        logger.debug(f"K6 queue disconnect: {e}")

    try:
        from orchestrator.services.job_queue import REDIS_AVAILABLE as JOB_REDIS_AVAILABLE
        from orchestrator.services.job_queue import get_job_queue

        if JOB_REDIS_AVAILABLE:
            jq = get_job_queue()
            await jq.disconnect()
            logger.info("Disconnected job queue Redis connection")
    except Exception as e:
        logger.debug(f"Job queue disconnect: {e}")

    # Shut down browser pool
    try:
        pool = await get_browser_pool()
        await pool.shutdown()
        logger.info("Browser pool shut down")
    except Exception as e:
        logger.debug(f"Browser pool shutdown: {e}")

    # Dispose database engine connections
    try:
        engine.dispose()
        logger.info("Database engine disposed")
    except Exception as e:
        logger.debug(f"Engine dispose: {e}")

    logger.info("Shutdown complete")


# ========= Execution Logic =========


def update_batch_stats(batch_id: str):
    """Update batch statistics after a run completes.

    Uses explicit transaction with rollback on failure to ensure data integrity.
    Locks the batch row to prevent race conditions when multiple runs complete simultaneously.
    """
    return test_run_batch_watchdog_support.update_batch_stats(_test_run_runtime(), batch_id)


async def _finalize_quality_gate_for_batch_safe(batch_id: str):
    return await test_run_batch_watchdog_support._finalize_quality_gate_for_batch_safe(
        _test_run_runtime(), batch_id
    )


async def _quality_gate_finalizer_loop():
    """Periodically publish missed final PR quality gate feedback."""
    return await test_run_batch_watchdog_support._quality_gate_finalizer_loop(_test_run_runtime())


async def _batch_watchdog():
    """Background task that detects and cleans up stuck runs.

    Runs every 60 seconds. First cleans orphaned runs (running in DB but no
    active process, >120s old). Then checks for runs stuck beyond MAX_RUN_AGE_MINUTES
    (default 120, configurable via env). Skips runs with recently-updated log files.
    """
    return await test_run_batch_watchdog_support._batch_watchdog(_test_run_runtime())


async def _queue_watchdog():
    """Background task that detects orphaned queued entries after uvicorn reload.

    Runs every 30 seconds. If a run has been in 'queued' status for > 60 seconds
    and has no backing asyncio task in PROCESS_MANAGER, it's marked as 'stopped'.
    This catches the case where uvicorn reloads kill asyncio tasks silently.
    """
    return await test_run_batch_watchdog_support._queue_watchdog(_test_run_runtime())


async def _exploration_cleanup_loop():
    """Background task that cleans up stuck exploration sessions.

    Runs every 5 minutes. Marks explorations that have been "running" longer than
    their configured timeout as "failed". Also sweeps the in-memory tracking dict
    and cleans up stale browser pool slots.
    """
    return await test_run_maintenance_loop_support._exploration_cleanup_loop(_test_run_runtime())


async def _browser_pool_cleanup_loop():
    """Periodically clean up stale browser slots every 10 minutes.

    If a browser slot crashes mid-operation, it stays "acquired" forever
    until the next restart. This loop prevents that leak.
    """
    return await test_run_maintenance_loop_support._browser_pool_cleanup_loop(_test_run_runtime())


async def _infrastructure_maintenance_loop():
    """Periodic infrastructure maintenance: orphan cleanup, temp cleanup, DB maintenance.

    Runs every 15 minutes for orphan/temp cleanup.
    Runs DB maintenance every 24 hours.
    """
    return await test_run_maintenance_loop_support._infrastructure_maintenance_loop(_test_run_runtime())


async def _schedule_execution_watchdog():
    """Sync schedule execution status from completed batches.

    Runs every 30 seconds, checks running ScheduleExecution records and
    syncs their status from the linked RegressionBatch records.
    Also cleans up stale executions that have no batch or are too old.
    """
    return await test_run_schedule_watchdog_support._schedule_execution_watchdog(_test_run_runtime())


async def _run_db_maintenance():
    """Run periodic database maintenance: ANALYZE and old data pruning."""
    return await test_run_maintenance_loop_support._run_db_maintenance(_test_run_runtime())


async def _log_startup_diagnostics():
    """Log system diagnostics at startup for early problem detection."""
    return await startup_diagnostics_support._log_startup_diagnostics(_test_run_runtime())


_STARTUP_IMPORT_FAILURE_MESSAGE = (
    test_run_runtime_support._STARTUP_IMPORT_FAILURE_MESSAGE
)


def _test_run_runtime():
    return sys.modules[__name__]


test_run_queue_manager_support.configure_runtime(_test_run_runtime)


def _record_startup_import_failure(run_id: str, run_dir_path: Path, *, retrying: bool) -> None:
    test_run_runtime_support.record_startup_import_failure(
        _test_run_runtime(),
        run_id,
        run_dir_path,
        retrying=retrying,
    )


def _run_test_cli_subprocess_with_retry(
    *,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    run_id: str,
    run_dir_path: Path,
    spec_name: str,
    batch_id: str | None,
    append_workflow_log,
    timeout_seconds: int = 3600,
) -> int | None:
    """Run the CLI subprocess, retrying only early Errno 35 import failures."""
    return test_run_runtime_support.run_test_cli_subprocess_with_retry(
        _test_run_runtime(),
        cmd=cmd,
        cwd=cwd,
        env=env,
        run_id=run_id,
        run_dir_path=run_dir_path,
        spec_name=spec_name,
        batch_id=batch_id,
        append_workflow_log=append_workflow_log,
        timeout_seconds=timeout_seconds,
    )


def execute_run_task(
    spec_path: str,
    run_dir: str,
    run_id: str,
    try_code_path: str = None,
    browser: str = "chromium",
    hybrid: bool = False,
    max_iterations: int = 20,
    headless: bool = False,
    memory_enabled: bool = True,
    spec_name: str = "",
    batch_id: str = None,
    project_id: str = None,
    model_tier: str | None = None,
    storage_state_path: str | None = None,
    browser_auth_context: dict[str, Any] | None = None,
    test_data_refs: list[str] | None = None,
):
    """Execute the native pipeline (default) with optional hybrid healing mode.

    Native pipeline is always used. The only choice is healing mode:
    - hybrid=False: Native Healer (3 attempts using test_run + diagnostic/devtools tools)
    - hybrid=True: Native + Ralph (3 attempts + up to 17 more)

    Process groups are used to ensure all child processes can be terminated together.
    """
    return test_run_runtime_support.execute_run_task(
        _test_run_runtime(),
        spec_path,
        run_dir,
        run_id,
        try_code_path,
        browser,
        hybrid,
        max_iterations,
        headless,
        memory_enabled,
        spec_name,
        batch_id,
        project_id,
        model_tier,
        storage_state_path,
        browser_auth_context,
        test_data_refs,
    )


def _task_exception_handler(task: asyncio.Task):
    """Log exceptions from completed tasks to prevent silent failures."""
    try:
        exc = task.exception()
        if exc:
            logger.error(f"Task {task.get_name()} failed with unhandled exception: {exc}")
    except asyncio.CancelledError:
        # Task was cancelled, not an error
        pass
    except asyncio.InvalidStateError:
        # Task not done yet, shouldn't happen in done callback
        pass


async def execute_run_task_wrapper(
    spec_path: str,
    run_dir: str,
    run_id: str,
    try_code_path: str = None,
    browser: str = "chromium",
    hybrid: bool = False,
    max_iterations: int = 20,
    batch_id: str = None,
    spec_name: str = "",
    project_id: str = None,
    model_tier: str | None = None,
    storage_state_path: str | None = None,
    browser_auth_context: dict[str, Any] | None = None,
    test_data_refs: list[str] | None = None,
):
    """Async wrapper for execute_run_task with unified browser queue management.

    Uses BrowserResourcePool to limit concurrent browser operations across
    ALL operation types (test runs, explorations, agents, PRD).

    Note: BROWSER_POOL is initialized at startup in startup_event().
    """
    return await test_run_runtime_support.execute_run_task_wrapper(
        _test_run_runtime(),
        spec_path,
        run_dir,
        run_id,
        try_code_path,
        browser,
        hybrid,
        max_iterations,
        batch_id,
        spec_name,
        project_id,
        model_tier,
        storage_state_path,
        browser_auth_context,
        test_data_refs,
    )


def execute_mobile_run_task(
    spec_path: str,
    run_dir: str,
    run_id: str,
    platform: str = "ios",
    appium_server_url: str | None = None,
    capabilities_file: str | None = None,
    spec_name: str = "",
    batch_id: str = None,
    project_id: str = None,
):
    """Execute the Appium mobile pipeline in an isolated subprocess."""
    return test_run_runtime_support.execute_mobile_run_task(
        _test_run_runtime(),
        spec_path,
        run_dir,
        run_id,
        platform,
        appium_server_url,
        capabilities_file,
        spec_name,
        batch_id,
        project_id,
    )


async def execute_mobile_run_task_wrapper(
    spec_path: str,
    run_dir: str,
    run_id: str,
    platform: str = "ios",
    appium_server_url: str | None = None,
    capabilities_file: str | None = None,
    batch_id: str = None,
    spec_name: str = "",
    project_id: str = None,
):
    """Async wrapper for Appium mobile runs."""
    return await test_run_runtime_support.execute_mobile_run_task_wrapper(
        _test_run_runtime(),
        spec_path,
        run_dir,
        run_id,
        platform,
        appium_server_url,
        capabilities_file,
        batch_id,
        spec_name,
        project_id,
    )


async def _start_test_run_temporal_or_fail(
    run: DBTestRun,
    payload: dict[str, Any],
    session: Session,
    *,
    task_queue: str | None = None,
) -> None:
    await test_run_runtime_support.start_test_run_temporal_or_fail(
        _test_run_runtime(),
        run,
        payload,
        session,
        task_queue=task_queue,
    )


async def _signal_test_run_temporal(run: DBTestRun, signal_name: str, *args) -> None:
    await test_run_runtime_support.signal_test_run_temporal(_test_run_runtime(), run, signal_name, *args)


def _has_browser_auth_selection(
    *,
    browser_auth_session_id: str | None,
    use_project_default_browser_auth: bool,
) -> bool:
    return test_run_runtime_support.has_browser_auth_selection(
        _test_run_runtime(),
        browser_auth_session_id=browser_auth_session_id,
        use_project_default_browser_auth=use_project_default_browser_auth,
    )


def _validate_browser_auth_selection_for_project(
    session: Session,
    project_id: str | None,
    *,
    browser_auth_session_id: str | None,
    use_project_default_browser_auth: bool,
) -> None:
    test_run_runtime_support.validate_browser_auth_selection_for_project(
        _test_run_runtime(),
        session,
        project_id,
        browser_auth_session_id=browser_auth_session_id,
        use_project_default_browser_auth=use_project_default_browser_auth,
    )


def _resolve_browser_auth_storage_state_for_run(
    session: Session,
    project_id: str | None,
    *,
    run_dir: Path,
    browser_auth_session_id: str | None,
    use_project_default_browser_auth: bool,
) -> tuple[str | None, dict[str, Any]]:
    return test_run_runtime_support.resolve_browser_auth_storage_state_for_run(
        _test_run_runtime(),
        session,
        project_id,
        run_dir=run_dir,
        browser_auth_session_id=browser_auth_session_id,
        use_project_default_browser_auth=use_project_default_browser_auth,
    )


def _normalize_request_test_data_refs(refs: list[str] | None) -> list[str]:
    return test_run_runtime_support.normalize_request_test_data_refs(_test_run_runtime(), refs)


# ========= Agents =========


AgentRunRequest = agent_run_launch.AgentRunRequest


_agent_tool = agent_tool_catalog_support.agent_tool


AGENT_TOOL_CATALOG = agent_tool_catalog_support.AGENT_TOOL_CATALOG
AGENT_RISK_ORDER = agent_tool_catalog_support.AGENT_RISK_ORDER


ExploratoryRunRequest = agent_exploratory.ExploratoryRunRequest


SpecSynthesisRequest = agent_exploratory.SpecSynthesisRequest
FlowUpdateRequest = agent_exploratory.FlowUpdateRequest
GenerateReportItemSpecRequest = agent_exploratory.GenerateReportItemSpecRequest


ImportReportRequirementsRequest = agent_reports.ImportReportRequirementsRequest
UpdateAgentReportItemRequest = agent_reports.UpdateAgentReportItemRequest
UpdateAgentReportOverviewRequest = agent_reports.UpdateAgentReportOverviewRequest


GenerateFlowTestRequest = agent_exploratory.GenerateFlowTestRequest


def _agent_compat_runtime():
    return sys.modules[__name__]


_sync_agent_run_observability_runs_dir = agent_compat_alias_support._sync_agent_run_observability_runs_dir
_collect_agent_run_artifacts = agent_compat_alias_support._collect_agent_run_artifacts
_read_run_text_artifact = agent_compat_alias_support._read_run_text_artifact
_read_run_json_artifact = agent_compat_alias_support._read_run_json_artifact
_run_artifact_counts = agent_compat_alias_support._run_artifact_counts
_jsonl_latest_url = agent_compat_alias_support._jsonl_latest_url
_latest_observed_url_for_run = agent_compat_alias_support._latest_observed_url_for_run
_recover_custom_agent_partial_result = agent_compat_alias_support._recover_custom_agent_partial_result
_agent_run_summary = agent_compat_alias_support._agent_run_summary
_exploratory_result_is_zero_evidence_failure = (
    agent_compat_alias_support._exploratory_result_is_zero_evidence_failure
)
_exploratory_result_is_terminal_failure = agent_compat_alias_support._exploratory_result_is_terminal_failure
_exploratory_result_has_usable_evidence = agent_compat_alias_support._exploratory_result_has_usable_evidence
_merge_agent_failure_into_result = agent_compat_alias_support._merge_agent_failure_into_result
_recover_exploratory_partial_result = agent_compat_alias_support._recover_exploratory_partial_result
_filter_agent_run_project = agent_compat_alias_support._filter_agent_run_project
_agent_report_project_filter = agent_compat_alias_support._agent_report_project_filter
_get_agent_report_run = agent_compat_alias_support._get_agent_report_run
AGENT_PARTIAL_STATUS = agent_compat_alias_support.AGENT_PARTIAL_STATUS
AGENT_TERMINAL_STATUSES = agent_compat_alias_support.AGENT_TERMINAL_STATUSES
AGENT_ACTIVE_STATUSES = agent_compat_alias_support.AGENT_ACTIVE_STATUSES
_coerce_progress_int = agent_compat_alias_support._coerce_progress_int
_normalize_agent_run_progress = agent_compat_alias_support._normalize_agent_run_progress
_record_agent_run_event = agent_compat_alias_support._record_agent_run_event
_start_agent_run_temporal_or_fail = agent_compat_alias_support._start_agent_run_temporal_or_fail
_agent_run_temporal_payload = agent_compat_alias_support._agent_run_temporal_payload


_signal_agent_run_temporal = agent_compat_alias_support._signal_agent_run_temporal


_cancel_agent_run_queue_task = agent_compat_alias_support._cancel_agent_run_queue_task


_wait_if_agent_run_paused = agent_compat_alias_support._wait_if_agent_run_paused


_mark_agent_run_paused = agent_compat_alias_support._mark_agent_run_paused


_mark_agent_run_cancelled = agent_compat_alias_support._mark_agent_run_cancelled


_agent_run_health = agent_compat_alias_support._agent_run_health


_serialize_agent_run = agent_compat_alias_support._serialize_agent_run


_safe_json_dict = agent_compat_alias_support._safe_json_dict


_compact_agent_run_config = agent_compat_alias_support._compact_agent_run_config


_compact_agent_run_summary = agent_compat_alias_support._compact_agent_run_summary


_encode_agent_run_cursor = agent_compat_alias_support._encode_agent_run_cursor


_decode_agent_run_cursor = agent_compat_alias_support._decode_agent_run_cursor


_agent_run_project_filters = agent_compat_alias_support._agent_run_project_filters


_agent_run_search_filter = agent_compat_alias_support._agent_run_search_filter


_agent_run_status_filter = agent_compat_alias_support._agent_run_status_filter


_agent_run_type_filter = agent_compat_alias_support._agent_run_type_filter


_agent_run_history_filters = agent_compat_alias_support._agent_run_history_filters


_agent_run_history_counts = agent_compat_alias_support._agent_run_history_counts


_serialize_agent_run_summary_row = agent_compat_alias_support._serialize_agent_run_summary_row


_live_agent_queue_progress = agent_compat_alias_support._live_agent_queue_progress


_serialize_agent_run_live = agent_compat_alias_support._serialize_agent_run_live


REPORT_ITEM_COLLECTIONS = agent_compat_alias_support.REPORT_ITEM_COLLECTIONS
REPORT_ITEM_EDITABLE_FIELDS = agent_compat_alias_support.REPORT_ITEM_EDITABLE_FIELDS
REPORT_ITEM_LIST_FIELDS = agent_compat_alias_support.REPORT_ITEM_LIST_FIELDS
REPORT_ITEM_PROTECTED_FIELDS = agent_compat_alias_support.REPORT_ITEM_PROTECTED_FIELDS


_report_confidence = agent_compat_alias_support._report_confidence
_report_importance = agent_compat_alias_support._report_importance
_report_requirement_confidence = agent_compat_alias_support._report_requirement_confidence
_report_requirement_acceptance_criteria = agent_compat_alias_support._report_requirement_acceptance_criteria
_requirement_create_body_from_report_item = agent_compat_alias_support._requirement_create_body_from_report_item
_normalize_report_item_type = agent_compat_alias_support._normalize_report_item_type
_stored_custom_agent_report = agent_compat_alias_support._stored_custom_agent_report
_normalize_report_patch_value = agent_compat_alias_support._normalize_report_patch_value
_editable_report_item_patch = agent_compat_alias_support._editable_report_item_patch
_find_report_item = agent_compat_alias_support._find_report_item
_capture_custom_agent_report_memory = agent_compat_alias_support._capture_custom_agent_report_memory


_sync_agent_tool_catalog = agent_compat_alias_support._sync_agent_tool_catalog
_serialize_agent_tool = agent_compat_alias_support._serialize_agent_tool
_serialize_agent_definition = agent_compat_alias_support._serialize_agent_definition
_get_agent_definition_or_404 = agent_compat_alias_support._get_agent_definition_or_404
_ensure_agent_write_access = agent_compat_alias_support._ensure_agent_write_access
_resolve_agent_tools = agent_compat_alias_support._resolve_agent_tools


_browser_auth_selection = agent_compat_alias_support._browser_auth_selection


AgentBrowserAuthResolutionError = agent_compat_alias_support.AgentBrowserAuthResolutionError


_browser_auth_request_fields_set = agent_compat_alias_support._browser_auth_request_fields_set


_without_spec_generation_auth = agent_compat_alias_support._without_spec_generation_auth


_apply_report_spec_browser_auth_request = agent_compat_alias_support._apply_report_spec_browser_auth_request


_resolve_agent_browser_auth_storage_path = agent_compat_alias_support._resolve_agent_browser_auth_storage_path


_prepare_custom_agent_mcp_config = agent_compat_alias_support._prepare_custom_agent_mcp_config


_prepare_spec_generation_mcp_config = agent_compat_alias_support._prepare_spec_generation_mcp_config


_safe_inherited_auth_config = agent_compat_alias_support._safe_inherited_auth_config


_build_spec_generation_source_config = agent_compat_alias_support._build_spec_generation_source_config


_spec_generation_auth_metadata = agent_compat_alias_support._spec_generation_auth_metadata


_resolve_playwright_chromium_executable = agent_compat_alias_support._resolve_playwright_chromium_executable


_playwright_chromium_probe_script = agent_compat_alias_support._playwright_chromium_probe_script


_probe_custom_agent_browser = agent_compat_alias_support._probe_custom_agent_browser


_probe_custom_agent_browser_with_slot = agent_compat_alias_support._probe_custom_agent_browser_with_slot


_custom_agent_uses_browser_tools = agent_compat_alias_support._custom_agent_uses_browser_tools


_custom_agent_browser_runs_via_queue = agent_compat_alias_support._custom_agent_browser_runs_via_queue


_agent_run_has_browser_tools = agent_compat_alias_support._agent_run_has_browser_tools


_ensure_custom_agent_browser_available = agent_compat_alias_support._ensure_custom_agent_browser_available


_worker_managed_agent_browser_slot = agent_compat_alias_support._worker_managed_agent_browser_slot


_short_tool_name = agent_compat_alias_support._short_tool_name


_update_agent_run_progress = agent_compat_alias_support._update_agent_run_progress


_generic_agent_runtime_prompt = agent_compat_alias_support._generic_agent_runtime_prompt


KNOWN_AGENT_TYPE_TOOL_PROFILES = agent_run_runtime_support.KNOWN_AGENT_TYPE_TOOL_PROFILES


_agent_tool_profile_for_run = agent_compat_alias_support._agent_tool_profile_for_run


_resolve_known_agent_allowed_tools = agent_compat_alias_support._resolve_known_agent_allowed_tools


_resolve_agent_execution_test_data_context = agent_compat_alias_support._resolve_agent_execution_test_data_context


def _agent_background_runner_dependencies() -> agent_background_runner_support.AgentBackgroundRunnerDependencies:
    return agent_dependency_support.agent_background_runner_dependencies(_agent_compat_runtime())


async def execute_agent_background(run_id: str, agent_type: str, config: dict):
    return await agent_background_runner_support.execute_agent_background(
        run_id,
        agent_type,
        config,
        deps=_agent_background_runner_dependencies(),
    )


async def run_agent(request: AgentRunRequest, session: Session = Depends(get_session)):
    return await agent_run_launch.run_agent(request, session=session)


async def pause_agent_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    return await agent_run_control.pause_agent_run(
        id,
        project_id=project_id,
        session=session,
        current_user=current_user,
    )


async def resume_agent_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    return await agent_run_control.resume_agent_run(
        id,
        project_id=project_id,
        session=session,
        current_user=current_user,
    )


async def cancel_agent_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    return await agent_run_control.cancel_agent_run(
        id,
        project_id=project_id,
        session=session,
        current_user=current_user,
    )


async def retry_agent_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    return await agent_run_control.retry_agent_run(
        id,
        project_id=project_id,
        session=session,
        current_user=current_user,
    )


def get_agent_run_report(
    id: str,
    project_id: str = Query(..., description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    return agent_reports.get_agent_run_report(id, project_id=project_id, session=session)


def update_agent_run_report_overview(
    run_id: str,
    request: UpdateAgentReportOverviewRequest,
    project_id: str = Query(..., description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return agent_reports.update_agent_run_report_overview(
        run_id,
        request,
        project_id=project_id,
        session=session,
    )


def update_agent_run_report_item(
    run_id: str,
    item_id: str,
    request: UpdateAgentReportItemRequest,
    item_type: str = Query(..., description="finding, test_idea, or requirement"),
    project_id: str = Query(..., description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return agent_reports.update_agent_run_report_item(
        run_id,
        item_id,
        request,
        item_type=item_type,
        project_id=project_id,
        session=session,
    )


def search_agent_reports(
    project_id: str | None = Query(default=None),
    query: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    item_type: str | None = Query(default=None, description="finding, test_idea, requirement, page, evidence, or action"),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    return agent_reports.search_agent_reports(
        project_id=project_id,
        query=query,
        severity=severity,
        item_type=item_type,
        limit=limit,
        session=session,
    )


def import_agent_report_requirements(
    run_id: str,
    request: ImportReportRequirementsRequest,
    project_id: str = Query(..., description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """Import reviewed custom-agent report requirements as candidate requirements."""
    return agent_reports.import_agent_report_requirements(
        run_id,
        request,
        project_id=project_id,
        session=session,
    )


# ========= Enhanced Exploratory Testing Compatibility Wrappers =========


_agent_exploratory_dependencies = agent_compat_alias_support._agent_exploratory_dependencies
_verify_exploration_run_project = agent_compat_alias_support._verify_exploration_run_project
_build_single_flow_prompt = agent_compat_alias_support._build_single_flow_prompt
_generate_fallback_spec = agent_compat_alias_support._generate_fallback_spec


# =============================================================================
# Native Pipeline Flow Generation
# =============================================================================


_requires_authentication = agent_compat_alias_support._requires_authentication
_detect_login_url = agent_compat_alias_support._detect_login_url
_is_login_page = agent_compat_alias_support._is_login_page
_extract_domain_name = agent_compat_alias_support._extract_domain_name
_slugify = agent_compat_alias_support._slugify


# ========== Flow Spec Generation Job Tracking ==========
_flow_spec_jobs = agent_compat_alias_support._flow_spec_jobs
MAX_FLOW_SPEC_JOBS = agent_compat_alias_support.MAX_FLOW_SPEC_JOBS
_cleanup_flow_spec_jobs = agent_compat_alias_support._cleanup_flow_spec_jobs


async def _run_flow_spec_generation(
    job_id: str,
    run_id: str,
    flow_id: str,
    flow: dict,
    flows: list,
    flows_file_path: str,
    run_project_id: str | None,
    run_config: dict,
    spec_agent_run_id: str | None = None,
):
    """Compatibility wrapper for the support-owned background runner."""
    await agent_exploratory._run_flow_spec_generation_impl(
        job_id=job_id,
        run_id=run_id,
        flow_id=flow_id,
        flow=flow,
        flows=flows,
        flows_file_path=flows_file_path,
        run_project_id=run_project_id,
        run_config=run_config,
        spec_agent_run_id=spec_agent_run_id,
        deps=_agent_exploratory_dependencies(),
    )


run_exploratory_agent = agent_exploratory.run_exploratory_agent
synthesize_specs = agent_exploratory.synthesize_specs
get_exploration_specs = agent_exploratory.get_exploration_specs
get_flow_details = agent_exploratory.get_flow_details
update_flow = agent_exploratory.update_flow
delete_flow = agent_exploratory.delete_flow
analyze_prerequisites = agent_exploratory.analyze_prerequisites
generate_flow_spec = agent_exploratory.generate_flow_spec
get_flow_spec_job_status = agent_exploratory.get_flow_spec_job_status
generate_report_item_spec = agent_exploratory.generate_report_item_spec
generate_flow_test = agent_exploratory.generate_flow_test


agent_exploratory.configure_dependencies_provider(_agent_exploratory_dependencies)


app.include_router(agent_definitions.router)  # Custom agent tool catalog and definition endpoints
app.include_router(agent_run_launch.router)  # Agent run launch endpoint
app.include_router(agent_run_observability.router)  # Read-only agent run visibility endpoints
app.include_router(agent_coding_patch.router)  # Coding agent patch review endpoints
app.include_router(agent_run_control.router)  # Agent run pause, resume, cancel, and retry endpoints
app.include_router(agent_reports.router)  # Custom agent report retrieval, editing, search, and import endpoints
app.include_router(agent_exploratory.router)  # Exploratory agent and spec generation endpoints
