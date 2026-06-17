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
from typing import Any, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded
from sqlmodel import Session, select
from starlette.requests import Request
from starlette.responses import JSONResponse

from logging_config import get_logger, request_id_var, setup_logging
from orchestrator.services.agent_runtimes import normalize_agent_runtime
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
    _build_custom_agent_structured_report,
)
from utils.agent_tool_allowlists import get_agent_allowed_tools
from utils.claude_config import copy_claude_project_config  # noqa: F401
from utils.playwright_mcp import (
    browser_runtime_status,
    prepare_run_playwright_config_content,  # noqa: F401
    write_playwright_test_mcp_config,  # noqa: F401
)
from utils.project_utils import derive_project_id_from_url  # noqa: F401

from . import (
    agent_background_runner_support,
    agent_coding_patch,
    agent_compat_support,
    agent_definitions,
    agent_exploratory,
    agent_flow_spec_support,
    agent_queue_ops,
    agent_reports,
    agent_run_control,
    agent_run_launch,
    agent_run_observability,
    agent_run_report_support,
    agent_run_runtime_support,
    agent_sessions,
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
    test_run_read_model_support,
    test_run_runtime_support,
    test_run_schedule_watchdog_support,
    testrail,
    testrail_files,
    users,
    workflows,
)
from .db import engine, get_database_type, get_session, init_db, is_parallel_mode_available
from .middleware.auth import get_current_user_optional
from .middleware.permissions import ProjectRole, check_project_access  # noqa: F401
from .middleware.rate_limit import limiter, rate_limit_exceeded_handler
from .models_db import (
    AgentDefinition,
    AgentRun,
    AgentToolDefinition,
    ExplorationSession,  # noqa: F401
    RegressionBatch,  # noqa: F401
)
from .models_db import ExecutionSettings as DBExecutionSettings
from .models_db import SpecMetadata as DBSpecMetadata
from .models_db import TestRun as DBTestRun
from .models_db import get_spec_metadata as get_db_spec_metadata
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


class QueueManager:
    """Manages test execution queue with configurable parallelism."""

    _instance: Optional["QueueManager"] = None
    _lock: asyncio.Lock | None = None

    def __init__(self):
        self._semaphore: asyncio.Semaphore | None = None
        self._parallelism: int = 2
        self._parallel_mode_enabled: bool = False

    @classmethod
    async def get_instance(cls) -> "QueueManager":
        """Get or create the singleton QueueManager instance."""
        if cls._instance is None:
            cls._instance = QueueManager()
            await cls._instance.initialize()
        return cls._instance

    async def initialize(self):
        """Initialize the queue manager from database settings or environment defaults."""
        # Read environment defaults
        env_parallelism = int(os.environ.get("DEFAULT_PARALLELISM", "4"))
        env_parallel_enabled = os.environ.get("PARALLEL_MODE_ENABLED", "false").lower() == "true"

        with Session(engine) as session:
            settings = session.get(DBExecutionSettings, 1)
            if settings:
                self._parallelism = settings.parallelism
                self._parallel_mode_enabled = settings.parallel_mode_enabled
            else:
                # Use environment defaults when no DB settings exist
                self._parallelism = max(1, min(10, env_parallelism))
                self._parallel_mode_enabled = env_parallel_enabled and is_parallel_mode_available()
                logger.info(
                    f"Using environment defaults: parallelism={self._parallelism}, enabled={self._parallel_mode_enabled}"
                )

        self._semaphore = asyncio.Semaphore(self._parallelism)
        logger.info(f"QueueManager initialized: parallelism={self._parallelism}, enabled={self._parallel_mode_enabled}")

    async def reload_settings(self):
        """Reload settings from database and update semaphore if needed."""
        with Session(engine) as session:
            settings = session.get(DBExecutionSettings, 1)
            if settings:
                new_parallelism = settings.parallelism
                self._parallel_mode_enabled = settings.parallel_mode_enabled

                # Only recreate semaphore if parallelism changed
                if new_parallelism != self._parallelism:
                    self._parallelism = new_parallelism
                    self._semaphore = asyncio.Semaphore(self._parallelism)
                    logger.info(f"QueueManager updated: parallelism={self._parallelism}")

    @property
    def parallelism(self) -> int:
        return self._parallelism

    @property
    def parallel_mode_enabled(self) -> bool:
        return self._parallel_mode_enabled

    async def acquire(self):
        """Acquire a slot for test execution."""
        if self._semaphore:
            await self._semaphore.acquire()

    def release(self):
        """Release a slot after test execution."""
        if self._semaphore:
            self._semaphore.release()

    def get_queue_position(self, run_id: str) -> int | None:
        """Get the queue position for a run (based on waiting count)."""
        with Session(engine) as session:
            # Count runs that are queued (status='queued') and were queued before this run
            run = session.get(DBTestRun, run_id)
            if not run or run.status != "queued":
                return None

            statement = select(DBTestRun).where(DBTestRun.status == "queued", DBTestRun.queued_at < run.queued_at)
            earlier_runs = session.exec(statement).all()
            return len(earlier_runs) + 1  # 1-indexed position

    def get_queue_status(self) -> dict[str, Any]:
        """Get current queue status with orphan detection and auto-cleanup."""
        ORPHAN_AGE_SECONDS = 120

        with Session(engine) as session:
            running = session.exec(select(DBTestRun).where(DBTestRun.status.in_(["running", "in_progress"]))).all()
            queued = session.exec(select(DBTestRun).where(DBTestRun.status == "queued")).all()

            # Detect orphaned runs: in DB as running but no active process
            orphaned_running = [r for r in running if not r.temporal_workflow_id and not is_process_active(r.id)]

            # Auto-clean orphans that have been orphaned for >120 seconds
            auto_cleaned_count = 0
            batch_ids_to_update = set()
            now = datetime.utcnow()
            for r in orphaned_running:
                age_ref = r.started_at or r.queued_at
                if age_ref and (now - age_ref).total_seconds() > ORPHAN_AGE_SECONDS:
                    r.status = "stopped"
                    r.completed_at = now
                    r.queue_position = None
                    session.add(r)

                    run_dir = RUNS_DIR / r.id
                    if run_dir.exists():
                        (run_dir / "status.txt").write_text("stopped")

                    if r.batch_id:
                        batch_ids_to_update.add(r.batch_id)

                    auto_cleaned_count += 1
                    logger.warning(f"Auto-cleaned orphaned run {r.id} (age={int((now - age_ref).total_seconds())}s)")

            if auto_cleaned_count > 0:
                session.commit()
                for batch_id in batch_ids_to_update:
                    try:
                        update_batch_stats(batch_id)
                    except Exception as e:
                        logger.error(f"Failed to update batch stats for {batch_id} after orphan cleanup: {e}")

            # Detect orphaned queued entries: queued in DB but no backing asyncio task
            orphaned_queued = [
                r
                for r in queued
                if not (
                    r.temporal_workflow_id
                    or (
                    PROCESS_MANAGER
                    and r.id in PROCESS_MANAGER._asyncio_tasks
                    and not PROCESS_MANAGER._asyncio_tasks[r.id].done()
                    )
                )
                and r.queued_at
                and (datetime.utcnow() - r.queued_at).total_seconds() > 60
            ]

            return {
                "running_count": len(running) - len(orphaned_running),
                "queued_count": len(queued),
                "parallelism_limit": self._parallelism,
                "database_type": get_database_type(),
                "parallel_mode_enabled": self._parallel_mode_enabled,
                "orphaned_running_count": len(orphaned_running),
                "active_process_count": get_active_process_count(),
                "orphaned_queued_count": len(orphaned_queued),
                "auto_cleaned_count": auto_cleaned_count,
            }


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


def _agent_tool(
    id: str,
    label: str,
    description: str,
    category: str,
    tool_name: str,
    risk: str = "low",
    requires_mcp_server: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "label": label,
        "description": description,
        "category": category,
        "tool_name": tool_name,
        "risk": risk,
        "requires_mcp_server": requires_mcp_server,
    }


AGENT_TOOL_CATALOG: list[dict[str, Any]] = [
    _agent_tool("read_file", "Read files", "Read repository and generated artifact files.", "Workspace", "Read"),
    _agent_tool("list_files", "List files", "Inspect directories and workspace structure.", "Workspace", "LS"),
    _agent_tool("glob_files", "Find files", "Find files by pattern.", "Workspace", "Glob"),
    _agent_tool("grep_files", "Search text", "Search file contents by pattern.", "Workspace", "Grep"),
    _agent_tool("write_file", "Write files", "Create or overwrite files in the workspace.", "Workspace", "Write", "high"),
    _agent_tool("edit_file", "Edit files", "Apply targeted edits to workspace files.", "Workspace", "Edit", "high"),
    _agent_tool(
        "multi_edit_file",
        "Multi-edit files",
        "Apply multiple edits to workspace files in one operation.",
        "Workspace",
        "MultiEdit",
        "high",
    ),
    _agent_tool("bash", "Shell command", "Run shell commands in the agent workspace.", "Workspace", "Bash", "destructive"),
    _agent_tool(
        "browser_navigate",
        "Browser navigate",
        "Open web pages in an isolated Playwright browser.",
        "Browser",
        "mcp__playwright-test__browser_navigate",
        "medium",
        "playwright-test",
    ),
    _agent_tool(
        "browser_navigate_back",
        "Browser back",
        "Return to the previous page in browser history.",
        "Browser",
        "mcp__playwright-test__browser_navigate_back",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "browser_close",
        "Browser close",
        "Close the active browser page.",
        "Browser",
        "mcp__playwright-test__browser_close",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "browser_snapshot",
        "Browser snapshot",
        "Read the current page accessibility tree.",
        "Browser",
        "mcp__playwright-test__browser_snapshot",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "browser_click",
        "Browser click",
        "Click page elements.",
        "Browser",
        "mcp__playwright-test__browser_click",
        "medium",
        "playwright-test",
    ),
    _agent_tool(
        "browser_type",
        "Browser type",
        "Type into page inputs.",
        "Browser",
        "mcp__playwright-test__browser_type",
        "medium",
        "playwright-test",
    ),
    _agent_tool(
        "browser_drag",
        "Browser drag",
        "Drag one page element onto another.",
        "Browser",
        "mcp__playwright-test__browser_drag",
        "medium",
        "playwright-test",
    ),
    _agent_tool(
        "browser_hover",
        "Browser hover",
        "Hover over page elements.",
        "Browser",
        "mcp__playwright-test__browser_hover",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "browser_evaluate",
        "Browser JavaScript",
        "Evaluate JavaScript in the page context.",
        "Browser",
        "mcp__playwright-test__browser_evaluate",
        "high",
        "playwright-test",
    ),
    _agent_tool(
        "browser_select",
        "Browser select",
        "Choose values in dropdowns.",
        "Browser",
        "mcp__playwright-test__browser_select_option",
        "medium",
        "playwright-test",
    ),
    _agent_tool(
        "browser_press_key",
        "Browser key press",
        "Press keyboard keys in the page.",
        "Browser",
        "mcp__playwright-test__browser_press_key",
        "medium",
        "playwright-test",
    ),
    _agent_tool(
        "browser_upload",
        "File upload",
        "Upload files into a page.",
        "Browser",
        "mcp__playwright-test__browser_file_upload",
        "high",
        "playwright-test",
    ),
    _agent_tool(
        "browser_dialog",
        "Handle dialogs",
        "Accept or dismiss browser dialogs.",
        "Browser",
        "mcp__playwright-test__browser_handle_dialog",
        "medium",
        "playwright-test",
    ),
    _agent_tool(
        "browser_network",
        "Network requests",
        "Inspect browser network traffic.",
        "Diagnostics",
        "mcp__playwright-test__browser_network_requests",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "browser_console",
        "Console messages",
        "Inspect browser console output.",
        "Diagnostics",
        "mcp__playwright-test__browser_console_messages",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "browser_screenshot",
        "Screenshot",
        "Capture browser screenshots.",
        "Diagnostics",
        "mcp__playwright-test__browser_take_screenshot",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "browser_wait",
        "Browser wait",
        "Wait for text, disappearance, or time.",
        "Diagnostics",
        "mcp__playwright-test__browser_wait_for",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "browser_generate_locator",
        "Generate locator",
        "Generate a robust locator for a page element.",
        "Testing",
        "mcp__playwright-test__browser_generate_locator",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "browser_verify_element",
        "Verify element visible",
        "Check that a target element is visible.",
        "Assertions",
        "mcp__playwright-test__browser_verify_element_visible",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "browser_verify_list",
        "Verify list visible",
        "Check that a list of elements is visible.",
        "Assertions",
        "mcp__playwright-test__browser_verify_list_visible",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "browser_verify_text",
        "Verify text visible",
        "Check that expected text is visible.",
        "Assertions",
        "mcp__playwright-test__browser_verify_text_visible",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "browser_verify_value",
        "Verify value",
        "Check an element value.",
        "Assertions",
        "mcp__playwright-test__browser_verify_value",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "browser_resume",
        "Resume browser",
        "Resume browser state for diagnostic workflows.",
        "Testing",
        "mcp__playwright-test__browser_resume",
        "medium",
        "playwright-test",
    ),
    _agent_tool(
        "browser_start_tracing",
        "Start tracing",
        "Start browser tracing for diagnostics.",
        "Diagnostics",
        "mcp__playwright-test__browser_start_tracing",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "browser_stop_tracing",
        "Stop tracing",
        "Stop browser tracing and collect trace artifacts.",
        "Diagnostics",
        "mcp__playwright-test__browser_stop_tracing",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "test_list",
        "List tests",
        "List runnable Playwright tests.",
        "Testing",
        "mcp__playwright-test__test_list",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "test_run",
        "Run tests",
        "Run Playwright tests and collect failure output.",
        "Testing",
        "mcp__playwright-test__test_run",
        "medium",
        "playwright-test",
    ),
    _agent_tool(
        "planner_setup_page",
        "Planner setup page",
        "Prepare a page for planner workflows.",
        "Pipeline",
        "mcp__playwright-test__planner_setup_page",
        "medium",
        "playwright-test",
    ),
    _agent_tool(
        "planner_save_plan",
        "Planner save plan",
        "Save a generated test plan artifact.",
        "Pipeline",
        "mcp__playwright-test__planner_save_plan",
        "high",
        "playwright-test",
    ),
    _agent_tool(
        "generator_setup_page",
        "Generator setup page",
        "Prepare a page for generator workflows.",
        "Pipeline",
        "mcp__playwright-test__generator_setup_page",
        "medium",
        "playwright-test",
    ),
    _agent_tool(
        "generator_read_log",
        "Generator read log",
        "Read generator workflow logs.",
        "Pipeline",
        "mcp__playwright-test__generator_read_log",
        requires_mcp_server="playwright-test",
    ),
    _agent_tool(
        "generator_write_test",
        "Generator write test",
        "Write generated Playwright test code.",
        "Pipeline",
        "mcp__playwright-test__generator_write_test",
        "high",
        "playwright-test",
    ),
]


ExploratoryRunRequest = agent_exploratory.ExploratoryRunRequest


class SpecSynthesisRequest(BaseModel):
    """Spec synthesis request."""

    exploration_run_id: str  # Run ID of exploration to synthesize


FlowUpdateRequest = agent_exploratory.FlowUpdateRequest
GenerateReportItemSpecRequest = agent_exploratory.GenerateReportItemSpecRequest


class ImportReportRequirementsRequest(BaseModel):
    item_ids: list[str] | None = None
    import_all: bool = False


class UpdateAgentReportItemRequest(BaseModel):
    patch: dict[str, Any]


class UpdateAgentReportOverviewRequest(BaseModel):
    summary: str | None = None
    scope: str | None = None


GenerateFlowTestRequest = agent_exploratory.GenerateFlowTestRequest


def _agent_compat_runtime():
    return sys.modules[__name__]


def _sync_agent_run_observability_runs_dir() -> None:
    agent_compat_support.sync_agent_run_observability_runs_dir(_agent_compat_runtime())


def _collect_agent_run_artifacts(run_id: str) -> list[dict[str, Any]]:
    return agent_compat_support.collect_agent_run_artifacts(_agent_compat_runtime(), run_id)


def _read_run_text_artifact(run_id: str, name: str, max_chars: int | None = None) -> str:
    return agent_compat_support.read_run_text_artifact(_agent_compat_runtime(), run_id, name, max_chars)


def _read_run_json_artifact(run_id: str, name: str) -> Any:
    return agent_compat_support.read_run_json_artifact(_agent_compat_runtime(), run_id, name)


def _run_artifact_counts(run_id: str, artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return agent_compat_support.run_artifact_counts(_agent_compat_runtime(), run_id, artifacts)


def _jsonl_latest_url(path: Path) -> str | None:
    return agent_compat_support.jsonl_latest_url(_agent_compat_runtime(), path)


def _latest_observed_url_for_run(run: AgentRun) -> str | None:
    return agent_compat_support.latest_observed_url_for_run(_agent_compat_runtime(), run)


def _recover_custom_agent_partial_result(run: AgentRun, error: Exception | str) -> dict[str, Any] | None:
    return agent_compat_support.recover_custom_agent_partial_result(_agent_compat_runtime(), run, error)


def _agent_run_summary(run: AgentRun) -> str | None:
    return agent_compat_support.agent_run_summary(_agent_compat_runtime(), run)


def _exploratory_result_is_zero_evidence_failure(result: Any) -> bool:
    return agent_compat_support.exploratory_result_is_zero_evidence_failure(_agent_compat_runtime(), result)


def _exploratory_result_is_terminal_failure(result: Any) -> bool:
    return agent_compat_support.exploratory_result_is_terminal_failure(_agent_compat_runtime(), result)


def _exploratory_result_has_usable_evidence(result: Any) -> bool:
    return agent_compat_support.exploratory_result_has_usable_evidence(_agent_compat_runtime(), result)


def _merge_agent_failure_into_result(result: Any, error: Exception | str, *, failure_reason: str) -> dict[str, Any]:
    return agent_compat_support.merge_agent_failure_into_result(
        _agent_compat_runtime(),
        result,
        error,
        failure_reason=failure_reason,
    )


def _recover_exploratory_partial_result(run_id: str, config: dict[str, Any], error: Exception | str) -> dict[str, Any] | None:
    return agent_compat_support.recover_exploratory_partial_result(_agent_compat_runtime(), run_id, config, error)


def _filter_agent_run_project(run: AgentRun, project_id: str | None) -> None:
    agent_compat_support.filter_agent_run_project(_agent_compat_runtime(), run, project_id)


def _agent_report_project_filter(project_id: str):
    return agent_compat_support.agent_report_project_filter(_agent_compat_runtime(), project_id)


def _get_agent_report_run(session: Session, run_id: str, project_id: str) -> AgentRun:
    return agent_compat_support.get_agent_report_run(_agent_compat_runtime(), session, run_id, project_id)


AGENT_PARTIAL_STATUS = agent_run_observability.AGENT_PARTIAL_STATUS
AGENT_TERMINAL_STATUSES = agent_run_observability.AGENT_TERMINAL_STATUSES
AGENT_ACTIVE_STATUSES = agent_run_observability.AGENT_ACTIVE_STATUSES


def _coerce_progress_int(value: Any, default: int = 0) -> int:
    return agent_compat_support.coerce_progress_int(_agent_compat_runtime(), value, default)


def _normalize_agent_run_progress(progress: dict[str, Any] | None) -> dict[str, Any]:
    return agent_compat_support.normalize_agent_run_progress(_agent_compat_runtime(), progress)


def _record_agent_run_event(
    run_id: str,
    *,
    event_type: str,
    message: str,
    level: str = "info",
    payload: dict[str, Any] | None = None,
    agent_task_id: str | None = None,
    session: Session | None = None,
) -> None:
    agent_compat_support.record_agent_run_event(
        _agent_compat_runtime(),
        run_id,
        event_type=event_type,
        message=message,
        level=level,
        payload=payload,
        agent_task_id=agent_task_id,
        session=session,
    )


async def _start_agent_run_temporal_or_fail(run: AgentRun, session: Session, *, workflow_attempt: int | None = None) -> None:
    await agent_compat_support.start_agent_run_temporal_or_fail(
        _agent_compat_runtime(),
        run,
        session,
        workflow_attempt=workflow_attempt,
    )


async def _agent_run_temporal_payload(run: AgentRun) -> dict[str, Any]:
    return await agent_compat_support.agent_run_temporal_payload(_agent_compat_runtime(), run)


async def _signal_agent_run_temporal(run: AgentRun, signal_name: str, *args) -> None:
    await agent_compat_support.signal_agent_run_temporal(_agent_compat_runtime(), run, signal_name, *args)


async def _cancel_agent_run_queue_task(run: AgentRun) -> dict[str, Any] | None:
    return await agent_compat_support.cancel_agent_run_queue_task(_agent_compat_runtime(), run)


async def _wait_if_agent_run_paused(run_id: str, poll_interval: float = 0.5) -> bool:
    return await agent_compat_support.wait_if_agent_run_paused(_agent_compat_runtime(), run_id, poll_interval)


def _mark_agent_run_paused(run: AgentRun, message: str = "Agent is paused") -> None:
    agent_compat_support.mark_agent_run_paused(_agent_compat_runtime(), run, message)


def _mark_agent_run_cancelled(run: AgentRun, message: str = "Agent cancelled") -> None:
    agent_compat_support.mark_agent_run_cancelled(_agent_compat_runtime(), run, message)


def _agent_run_health(run: AgentRun, session: Session | None = None) -> dict[str, Any]:
    return agent_compat_support.agent_run_health(_agent_compat_runtime(), run, session)


def _serialize_agent_run(run: AgentRun, session: Session | None = None) -> dict[str, Any]:
    return agent_compat_support.serialize_agent_run(_agent_compat_runtime(), run, session)


def _safe_json_dict(value: str | None) -> dict[str, Any]:
    return agent_compat_support.safe_json_dict(_agent_compat_runtime(), value)


def _compact_agent_run_config(config: dict[str, Any]) -> dict[str, Any]:
    return agent_compat_support.compact_agent_run_config(_agent_compat_runtime(), config)


def _compact_agent_run_summary(progress: dict[str, Any]) -> str | None:
    return agent_compat_support.compact_agent_run_summary(_agent_compat_runtime(), progress)


def _encode_agent_run_cursor(created_at: datetime, run_id: str) -> str:
    return agent_compat_support.encode_agent_run_cursor(_agent_compat_runtime(), created_at, run_id)


def _decode_agent_run_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    return agent_compat_support.decode_agent_run_cursor(_agent_compat_runtime(), cursor)


def _agent_run_project_filters(project_id: str | None) -> list[Any]:
    return agent_compat_support.agent_run_project_filters(_agent_compat_runtime(), project_id)


def _agent_run_search_filter(q: str | None) -> Any | None:
    return agent_compat_support.agent_run_search_filter(_agent_compat_runtime(), q)


def _agent_run_status_filter(status: str | None) -> Any | None:
    return agent_compat_support.agent_run_status_filter(_agent_compat_runtime(), status)


def _agent_run_type_filter(agent_type: str | None) -> Any | None:
    return agent_compat_support.agent_run_type_filter(_agent_compat_runtime(), agent_type)


def _agent_run_history_filters(
    *,
    project_id: str | None,
    status: str | None = None,
    agent_type: str | None = None,
    q: str | None = None,
) -> list[Any]:
    return agent_compat_support.agent_run_history_filters(
        _agent_compat_runtime(),
        project_id=project_id,
        status=status,
        agent_type=agent_type,
        q=q,
    )


def _agent_run_history_counts(session: Session, *, project_id: str | None, q: str | None) -> dict[str, Any]:
    return agent_compat_support.agent_run_history_counts(_agent_compat_runtime(), session, project_id=project_id, q=q)


def _serialize_agent_run_summary_row(row: Any) -> dict[str, Any]:
    return agent_compat_support.serialize_agent_run_summary_row(_agent_compat_runtime(), row)


async def _live_agent_queue_progress(run: AgentRun) -> dict[str, Any]:
    return await agent_compat_support.live_agent_queue_progress(_agent_compat_runtime(), run)


async def _serialize_agent_run_live(run: AgentRun, session: Session | None = None) -> dict[str, Any]:
    return await agent_compat_support.serialize_agent_run_live(_agent_compat_runtime(), run, session)


def _clean_text(value: Any, max_len: int = 2000) -> str:
    return agent_compat_support.clean_text(_agent_compat_runtime(), value, max_len)


def _as_report_list(value: Any) -> list[Any]:
    return agent_compat_support.as_report_list(_agent_compat_runtime(), value)


REPORT_ITEM_COLLECTIONS = agent_run_report_support.REPORT_ITEM_COLLECTIONS
REPORT_ITEM_EDITABLE_FIELDS = agent_run_report_support.REPORT_ITEM_EDITABLE_FIELDS
REPORT_ITEM_LIST_FIELDS = agent_run_report_support.REPORT_ITEM_LIST_FIELDS
REPORT_ITEM_PROTECTED_FIELDS = agent_run_report_support.REPORT_ITEM_PROTECTED_FIELDS


def _report_confidence(value: str | None) -> float:
    return agent_compat_support.report_confidence(_agent_compat_runtime(), value)


def _report_importance(value: str | None) -> float:
    return agent_compat_support.report_importance(_agent_compat_runtime(), value)


def _report_requirement_confidence(value: Any) -> float:
    return agent_compat_support.report_requirement_confidence(_agent_compat_runtime(), value)


def _report_requirement_acceptance_criteria(item: dict[str, Any]) -> list[str]:
    return agent_compat_support.report_requirement_acceptance_criteria(_agent_compat_runtime(), item)


def _requirement_create_body_from_report_item(item: dict[str, Any]) -> dict[str, Any]:
    return agent_compat_support.requirement_create_body_from_report_item(_agent_compat_runtime(), item)


def _normalize_report_item_type(item_type: str | None) -> str:
    return agent_compat_support.normalize_report_item_type(_agent_compat_runtime(), item_type)


def _stored_custom_agent_report(run: AgentRun) -> tuple[dict[str, Any], dict[str, Any]]:
    return agent_compat_support.stored_custom_agent_report(_agent_compat_runtime(), run)


def _normalize_report_patch_value(field: str, value: Any) -> Any:
    return agent_compat_support.normalize_report_patch_value(_agent_compat_runtime(), field, value)


def _editable_report_item_patch(item_type: str, patch: dict[str, Any]) -> dict[str, Any]:
    return agent_compat_support.editable_report_item_patch(_agent_compat_runtime(), item_type, patch)


def _find_report_item(report: dict[str, Any], item_type: str, item_id: str) -> dict[str, Any]:
    return agent_compat_support.find_report_item(_agent_compat_runtime(), report, item_type, item_id)


def _capture_custom_agent_report_memory(
    *,
    run_id: str,
    project_id: str | None,
    structured_report: dict[str, Any],
    config: dict[str, Any],
) -> list[str]:
    return agent_compat_support.capture_custom_agent_report_memory(
        _agent_compat_runtime(),
        run_id=run_id,
        project_id=project_id,
        structured_report=structured_report,
        config=config,
    )


def _sync_agent_tool_catalog(session: Session) -> list[AgentToolDefinition]:
    return agent_compat_support.sync_agent_tool_catalog(_agent_compat_runtime(), session)


def _serialize_agent_tool(tool: AgentToolDefinition) -> dict[str, Any]:
    return agent_compat_support.serialize_agent_tool(_agent_compat_runtime(), tool)


AGENT_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "destructive": 3}


def _serialize_agent_definition(
    definition: AgentDefinition,
    tools_by_id: dict[str, AgentToolDefinition] | None = None,
) -> dict[str, Any]:
    return agent_compat_support.serialize_agent_definition(_agent_compat_runtime(), definition, tools_by_id)


def _get_agent_definition_or_404(definition_id: str, project_id: str | None, session: Session) -> AgentDefinition:
    return agent_compat_support.get_agent_definition_or_404(
        _agent_compat_runtime(),
        definition_id,
        project_id,
        session,
    )


async def _ensure_agent_write_access(project_id: str | None, current_user: Any, session: Session) -> None:
    await agent_compat_support.ensure_agent_write_access(_agent_compat_runtime(), project_id, current_user, session)


def _resolve_agent_tools(tool_ids: list[str], session: Session) -> tuple[list[str], list[dict[str, Any]]]:
    return agent_compat_support.resolve_agent_tools(_agent_compat_runtime(), tool_ids, session)


def _browser_auth_selection(config: dict[str, Any]) -> tuple[str | None, bool]:
    return agent_compat_support.browser_auth_selection(_agent_compat_runtime(), config)


AgentBrowserAuthResolutionError = agent_run_runtime_support.AgentBrowserAuthResolutionError


def _browser_auth_request_fields_set(request: Any) -> set[str]:
    return agent_compat_support.browser_auth_request_fields_set(_agent_compat_runtime(), request)


def _without_spec_generation_auth(config: dict[str, Any]) -> dict[str, Any]:
    return agent_compat_support.without_spec_generation_auth(_agent_compat_runtime(), config)


def _apply_report_spec_browser_auth_request(
    inherited_config: dict[str, Any],
    request: GenerateReportItemSpecRequest | None,
) -> tuple[dict[str, Any], bool]:
    return agent_compat_support.apply_report_spec_browser_auth_request(
        _agent_compat_runtime(),
        inherited_config,
        request,
    )


def _resolve_agent_browser_auth_storage_path(
    *,
    run_id: str,
    project_id: str | None,
    config: dict[str, Any],
    run_dir: Path,
) -> Path | None:
    return agent_compat_support.resolve_agent_browser_auth_storage_path(
        _agent_compat_runtime(),
        run_id=run_id,
        project_id=project_id,
        config=config,
        run_dir=run_dir,
    )


def _prepare_custom_agent_mcp_config(run_id: str, storage_state_path: Path | str | None = None) -> Path:
    return agent_compat_support.prepare_custom_agent_mcp_config(
        _agent_compat_runtime(),
        run_id,
        storage_state_path=storage_state_path,
    )


def _prepare_spec_generation_mcp_config(
    run_dir: Path,
    storage_state_path: Path | str | None = None,
) -> dict[str, Any]:
    return agent_compat_support.prepare_spec_generation_mcp_config(
        _agent_compat_runtime(),
        run_dir,
        storage_state_path,
    )


def _safe_inherited_auth_config(value: Any) -> dict[str, Any]:
    return agent_compat_support.safe_inherited_auth_config(_agent_compat_runtime(), value)


def _build_spec_generation_source_config(
    source_config: dict[str, Any],
    *,
    target_url: str,
    project_id: str | None,
) -> dict[str, Any]:
    return agent_compat_support.build_spec_generation_source_config(
        _agent_compat_runtime(),
        source_config,
        target_url=target_url,
        project_id=project_id,
    )


def _spec_generation_auth_metadata(config: dict[str, Any], *, inherited: bool = True) -> dict[str, Any]:
    return agent_compat_support.spec_generation_auth_metadata(_agent_compat_runtime(), config, inherited=inherited)


def _resolve_playwright_chromium_executable() -> Path | None:
    return agent_compat_support.resolve_playwright_chromium_executable(_agent_compat_runtime())


def _playwright_chromium_probe_script(executable_path: str | None = None) -> str:
    return agent_compat_support.playwright_chromium_probe_script(_agent_compat_runtime(), executable_path)


def _probe_custom_agent_browser(timeout_seconds: int = 30) -> tuple[bool, str]:
    return agent_compat_support.probe_custom_agent_browser(_agent_compat_runtime(), timeout_seconds)


async def _probe_custom_agent_browser_with_slot(run_id: str, timeout_seconds: int = 30) -> tuple[bool, str]:
    return await agent_compat_support.probe_custom_agent_browser_with_slot(
        _agent_compat_runtime(),
        run_id,
        timeout_seconds,
    )


def _custom_agent_uses_browser_tools(allowed_tools: list[Any]) -> bool:
    return agent_compat_support.custom_agent_uses_browser_tools(_agent_compat_runtime(), allowed_tools)


def _custom_agent_browser_runs_via_queue() -> bool:
    return agent_compat_support.custom_agent_browser_runs_via_queue(_agent_compat_runtime())


def _agent_run_has_browser_tools(agent_type: str, config: dict[str, Any]) -> bool:
    return agent_compat_support.agent_run_has_browser_tools(_agent_compat_runtime(), agent_type, config)


async def _ensure_custom_agent_browser_available(run_id: str, *, force_direct_execution: bool = False) -> None:
    await agent_compat_support.ensure_custom_agent_browser_available(
        _agent_compat_runtime(),
        run_id,
        force_direct_execution=force_direct_execution,
    )


def _worker_managed_agent_browser_slot():
    return agent_compat_support.worker_managed_agent_browser_slot(_agent_compat_runtime())


def _short_tool_name(tool_name: str | None) -> str:
    return agent_compat_support.short_tool_name(_agent_compat_runtime(), tool_name)


def _update_agent_run_progress(run_id: str, patch: dict[str, Any]) -> None:
    agent_compat_support.update_agent_run_progress(_agent_compat_runtime(), run_id, patch)


def _generic_agent_runtime_prompt(agent_type: str, config: dict[str, Any]) -> str:
    return agent_compat_support.generic_agent_runtime_prompt(_agent_compat_runtime(), agent_type, config)


KNOWN_AGENT_TYPE_TOOL_PROFILES = agent_run_runtime_support.KNOWN_AGENT_TYPE_TOOL_PROFILES


def _agent_tool_profile_for_run(agent_type: str, config: dict[str, Any]) -> str | None:
    return agent_compat_support.agent_tool_profile_for_run(_agent_compat_runtime(), agent_type, config)


def _resolve_known_agent_allowed_tools(
    agent_type: str,
    config: dict[str, Any],
    *,
    mcp_config_dir: Path | str | None = None,
) -> list[str] | None:
    return agent_compat_support.resolve_known_agent_allowed_tools(
        _agent_compat_runtime(),
        agent_type,
        config,
        mcp_config_dir=mcp_config_dir,
    )


def _resolve_agent_execution_test_data_context(
    *,
    project_id: str | None,
    refs: list[Any] | None = None,
    markdown: str | None = None,
) -> dict[str, Any]:
    return agent_compat_support.resolve_agent_execution_test_data_context(
        _agent_compat_runtime(),
        project_id=project_id,
        refs=refs,
        markdown=markdown,
    )


def _agent_background_runner_dependencies() -> agent_background_runner_support.AgentBackgroundRunnerDependencies:
    return agent_compat_support.agent_background_runner_dependencies(_agent_compat_runtime())


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


def _agent_exploratory_dependencies() -> agent_exploratory.AgentExploratoryDependencies:
    project_root = Path(__file__).parent.parent.parent
    return agent_exploratory.AgentExploratoryDependencies(
        agent_run_model=AgentRun,
        db_session_factory=Session,
        db_engine=engine,
        runs_dir=RUNS_DIR,
        project_root=project_root,
        flow_spec_jobs=_flow_spec_jobs,
        max_flow_spec_jobs=MAX_FLOW_SPEC_JOBS,
        agent_partial_status=AGENT_PARTIAL_STATUS,
        agent_browser_auth_resolution_error=AgentBrowserAuthResolutionError,
        browser_runtime_status=browser_runtime_status,
        record_agent_run_event=_record_agent_run_event,
        start_agent_run_temporal_or_fail=_start_agent_run_temporal_or_fail,
        get_agent_report_run=_get_agent_report_run,
        serialize_agent_run=_serialize_agent_run,
        build_spec_generation_source_config=_build_spec_generation_source_config,
        apply_report_spec_browser_auth_request=_apply_report_spec_browser_auth_request,
        spec_generation_auth_metadata=_spec_generation_auth_metadata,
        resolve_agent_browser_auth_storage_path=_resolve_agent_browser_auth_storage_path,
        prepare_spec_generation_mcp_config=_prepare_spec_generation_mcp_config,
        update_agent_run_progress=_update_agent_run_progress,
        get_spec_metadata=get_db_spec_metadata,
        spec_metadata_model=DBSpecMetadata,
        short_tool_name=_short_tool_name,
        run_flow_spec_generation=_run_flow_spec_generation,
        normalize_agent_runtime=normalize_agent_runtime,
        get_agent_allowed_tools=get_agent_allowed_tools,
        logger_override=logger,
    )


def _verify_exploration_run_project(run_id: str, project_id: str | None, session: Session) -> AgentRun:
    return agent_exploratory._verify_exploration_run_project(
        run_id,
        project_id,
        session,
        _agent_exploratory_dependencies(),
    )


def _build_single_flow_prompt(flow: dict[str, Any], base_url: str) -> str:
    return agent_exploratory._build_single_flow_prompt(flow, base_url)


def _generate_fallback_spec(flow: dict[str, Any], base_url: str) -> tuple[str, str]:
    return agent_exploratory._generate_fallback_spec(flow, base_url)


# =============================================================================
# Native Pipeline Flow Generation
# =============================================================================


def _requires_authentication(url: str) -> bool:
    return agent_flow_spec_support._requires_authentication(url)


def _detect_login_url(target_url: str) -> str:
    return agent_flow_spec_support._detect_login_url(target_url)


def _is_login_page(url: str) -> bool:
    return agent_flow_spec_support._is_login_page(url)


def _extract_domain_name(url: str) -> str:
    return agent_flow_spec_support._extract_domain_name(url)


def _slugify(text: str) -> str:
    return agent_flow_spec_support._slugify(text)


# ========== Flow Spec Generation Job Tracking ==========
_flow_spec_jobs = agent_flow_spec_support._flow_spec_jobs
MAX_FLOW_SPEC_JOBS = agent_flow_spec_support.MAX_FLOW_SPEC_JOBS


def _cleanup_flow_spec_jobs():
    return agent_exploratory._cleanup_flow_spec_jobs(_agent_exploratory_dependencies())


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


async def run_exploratory_agent(
    request: ExploratoryRunRequest, session: Session = Depends(get_session)
):
    return await agent_exploratory.run_exploratory_agent_impl(
        request,
        session=session,
        deps=_agent_exploratory_dependencies(),
    )


async def synthesize_specs(run_id: str, session: Session = Depends(get_session)):
    return await agent_exploratory.synthesize_specs_impl(
        run_id,
        session=session,
        deps=_agent_exploratory_dependencies(),
    )


async def get_exploration_specs(
    run_id: str,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await agent_exploratory.get_exploration_specs_impl(
        run_id,
        project_id=project_id,
        session=session,
        deps=_agent_exploratory_dependencies(),
    )


async def get_flow_details(
    run_id: str,
    flow_id: str,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await agent_exploratory.get_flow_details_impl(
        run_id,
        flow_id,
        project_id=project_id,
        session=session,
        deps=_agent_exploratory_dependencies(),
    )


async def update_flow(
    run_id: str,
    flow_id: str,
    request: FlowUpdateRequest,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await agent_exploratory.update_flow_impl(
        run_id,
        flow_id,
        request,
        project_id=project_id,
        session=session,
        deps=_agent_exploratory_dependencies(),
    )


async def delete_flow(
    run_id: str,
    flow_id: str,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await agent_exploratory.delete_flow_impl(
        run_id,
        flow_id,
        project_id=project_id,
        session=session,
        deps=_agent_exploratory_dependencies(),
    )


async def analyze_prerequisites(
    run_id: str,
    force_reanalyze: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await agent_exploratory.analyze_prerequisites_impl(
        run_id,
        force_reanalyze=force_reanalyze,
        project_id=project_id,
        session=session,
        deps=_agent_exploratory_dependencies(),
    )


async def generate_flow_spec(
    run_id: str,
    flow_id: str,
    force_regenerate: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await agent_exploratory.generate_flow_spec_impl(
        run_id,
        flow_id,
        force_regenerate=force_regenerate,
        project_id=project_id,
        session=session,
        deps=_agent_exploratory_dependencies(),
    )


async def get_flow_spec_job_status(job_id: str):
    return await agent_exploratory.get_flow_spec_job_status_impl(
        job_id,
        deps=_agent_exploratory_dependencies(),
    )


async def generate_report_item_spec(
    run_id: str,
    item_id: str,
    item_type: str | None = Query(default=None, description="finding or test_idea"),
    project_id: str = Query(..., description="Project ID for verification"),
    request_body: GenerateReportItemSpecRequest | None = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: Session = Depends(get_session),
):
    return await agent_exploratory.generate_report_item_spec_impl(
        run_id,
        item_id,
        item_type=item_type,
        project_id=project_id,
        request_body=request_body,
        background_tasks=background_tasks,
        session=session,
        deps=_agent_exploratory_dependencies(),
    )


async def generate_flow_test(
    run_id: str,
    flow_id: str,
    force_regenerate: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    request_body: GenerateFlowTestRequest | None = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: Session = Depends(get_session),
):
    return await agent_exploratory.generate_flow_test_impl(
        run_id,
        flow_id,
        force_regenerate=force_regenerate,
        project_id=project_id,
        request_body=request_body,
        background_tasks=background_tasks,
        session=session,
        deps=_agent_exploratory_dependencies(),
    )


agent_exploratory.configure_dependencies_provider(_agent_exploratory_dependencies)


app.include_router(agent_definitions.router)  # Custom agent tool catalog and definition endpoints
app.include_router(agent_run_launch.router)  # Agent run launch endpoint
app.include_router(agent_run_observability.router)  # Read-only agent run visibility endpoints
app.include_router(agent_coding_patch.router)  # Coding agent patch review endpoints
app.include_router(agent_run_control.router)  # Agent run pause, resume, cancel, and retry endpoints
app.include_router(agent_reports.router)  # Custom agent report retrieval, editing, search, and import endpoints
app.include_router(agent_exploratory.router)  # Exploratory agent and spec generation endpoints
