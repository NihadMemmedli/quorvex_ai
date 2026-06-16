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
import base64
import json
import re
import shutil
import subprocess
import threading
import time as time_module
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded
from sqlalchemy import and_, func, or_
from sqlmodel import Session, select
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from logging_config import get_logger, request_id_var, setup_logging
from orchestrator.services.agent_runtimes import normalize_agent_runtime
from orchestrator.services.browser_auth_sessions import (
    BrowserAuthSessionError,
    ensure_browser_auth_session_usable,
    resolve_browser_auth_for_run,
    resolve_browser_auth_session_row,
)
from orchestrator.services.browser_slots import browser_operation_slot
from orchestrator.services.coding_agent import (
    CODING_ARTIFACT_PATCH,
    DEFAULT_REPO_ROOT,
    apply_patch_to_repo,
    build_coding_agent_prompt,
    build_coding_tool_permission_guard,
    coding_agent_allowed_tools,
    coding_agent_subagents,
    validate_patch_for_repo,
    write_coding_artifacts,
)
from services.browser_pool import AbstractBrowserPool, get_browser_pool
from services.browser_pool import OperationType as BrowserOpType
from services.resource_manager import ResourceManager, get_resource_manager
from utils.agent_report import (
    CUSTOM_AGENT_REPORT_INSTRUCTIONS,
    _as_report_list,
    _build_custom_agent_structured_report,
    _clean_text,
)
from utils.agent_tool_allowlists import get_agent_allowed_tools
from utils.claude_config import copy_claude_project_config
from utils.playwright_mcp import (
    browser_live_worker_enabled,
    browser_runtime_status,
    prepare_run_playwright_config_content,
    resolve_playwright_chromium_executable,
    write_playwright_mcp_config,
    write_playwright_test_mcp_config,
)
from utils.project_utils import derive_project_id_from_url

from . import (
    agent_routes,
    analytics,
    api_testing,
    auth,
    autonomous,
    autopilot,
    browser_auth_sessions,
    chat,
    ci_control,
    dashboard,
    database_testing,
    exploration,
    github_ci,
    gitlab_ci,
    health,
    import_utils,
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
    test_data,
    testrail,
    users,
    workflows,
)
from .db import engine, get_database_type, get_session, init_db, is_parallel_mode_available
from .middleware.auth import get_current_user_optional
from .middleware.permissions import ProjectRole, check_project_access
from .middleware.rate_limit import limiter, rate_limit_exceeded_handler
from .models_db import (
    AgentDefinition,
    AgentRun,
    AgentRunEvent,
    AgentToolDefinition,
    ExplorationSession,
    RegressionBatch,
)
from .models_db import ExecutionSettings as DBExecutionSettings
from .models_db import SpecMetadata as DBSpecMetadata
from .models_db import TestRun as DBTestRun
from .models_db import get_spec_metadata as get_db_spec_metadata
from .process_manager import ProcessManager, get_process_manager

# Initialize logging
setup_logging(level="INFO", console=True)
logger = get_logger(__name__)

AGENT_QUEUE_ACTIVE_STATUSES = ["queued", "pending", "running", "paused"]
AGENT_QUEUE_QUEUED_STATUSES = ["queued", "pending"]

BASE_DIR = spec_files.BASE_DIR
SPECS_DIR = spec_files.SPECS_DIR
RUNS_DIR = spec_files.RUNS_DIR
METADATA_FILE = spec_files.METADATA_FILE
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
app.include_router(workflows.router)  # Custom workflow endpoints
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
    with _processes_lock:
        ACTIVE_PROCESSES[run_id] = proc


def unregister_process(run_id: str) -> subprocess.Popen | None:
    """Thread-safe removal of an active process. Returns the process if found."""
    with _processes_lock:
        return ACTIVE_PROCESSES.pop(run_id, None)


def get_process(run_id: str) -> subprocess.Popen | None:
    """Thread-safe retrieval of an active process."""
    with _processes_lock:
        return ACTIVE_PROCESSES.get(run_id)


def is_process_active(run_id: str) -> bool:
    """Thread-safe check if a process is active."""
    with _processes_lock:
        return run_id in ACTIVE_PROCESSES


def get_active_process_count() -> int:
    """Thread-safe count of active processes."""
    with _processes_lock:
        return len(ACTIVE_PROCESSES)


def list_active_process_ids() -> list:
    """Thread-safe list of active process IDs."""
    with _processes_lock:
        return list(ACTIVE_PROCESSES.keys())


def clear_all_processes() -> dict[str, subprocess.Popen]:
    """Thread-safe clear of all processes. Returns the old dict."""
    with _processes_lock:
        old = dict(ACTIVE_PROCESSES)
        ACTIVE_PROCESSES.clear()
        return old


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
    logger.info("Cleaning up orphaned runs...")
    cleaned_count = 0
    preserved_count = 0

    with Session(engine) as session:
        stuck_runs = session.exec(
            select(DBTestRun).where(DBTestRun.status.in_(["running", "in_progress", "queued"]))
        ).all()

        for run in stuck_runs:
            if run.temporal_workflow_id:
                continue
            run_dir = RUNS_DIR / run.id

            # Check if status.txt already has a terminal status
            status_file = run_dir / "status.txt" if run_dir.exists() else None
            if status_file and status_file.exists():
                file_status = status_file.read_text().strip()
                # Terminal statuses that indicate the run actually completed
                if file_status in ("passed", "failed", "error", "completed"):
                    # Update DB to match file status, don't mark as stopped
                    run.status = file_status
                    run.completed_at = run.completed_at or datetime.utcnow()
                    run.queue_position = None
                    session.add(run)
                    preserved_count += 1
                    logger.debug(f"Preserved run {run.id}: status={file_status}")
                    continue

            # Only mark as stopped if we don't have a terminal status
            run.status = "stopped"
            run.queue_position = None
            session.add(run)
            cleaned_count += 1

            # Update status.txt file too (only for truly orphaned runs)
            if run_dir.exists():
                (run_dir / "status.txt").write_text("stopped")

        session.commit()

    if cleaned_count > 0:
        logger.info(f"Cleaned up {cleaned_count} orphaned runs (marked as stopped)")
    if preserved_count > 0:
        logger.info(f"Preserved {preserved_count} runs with terminal status from files")
    if cleaned_count == 0 and preserved_count == 0:
        logger.info("No orphaned runs found")


async def _cleanup_test_run_runtime(run_id: str, reason: str = "cleanup requested") -> dict[str, object]:
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
        logger.warning("Failed to cancel agent tasks for test run %s: %s", run_id, exc)
        cleanup["agent_tasks"] = {"error": str(exc)}

    try:
        from orchestrator.utils.browser_cleanup import kill_test_run_process_tree

        cleanup["processes"] = await asyncio.to_thread(kill_test_run_process_tree, run_id)
    except Exception as exc:
        logger.warning("Failed to clean browser processes for test run %s: %s", run_id, exc)
        cleanup["processes"] = {"error": str(exc)}

    return cleanup


def cleanup_terminal_test_run_processes() -> int:
    """Kill browser process trees for test runs already marked terminal."""
    try:
        from orchestrator.utils.browser_cleanup import (
            find_test_run_ids_in_processes,
            kill_test_run_process_tree,
        )
    except Exception as exc:
        logger.debug("Terminal test-run process cleanup unavailable: %s", exc)
        return 0

    terminal_statuses = {"passed", "failed", "error", "stopped", "cancelled", "completed"}
    cleaned = 0
    run_ids = find_test_run_ids_in_processes()
    if not run_ids:
        return 0

    with Session(engine) as session:
        for run_id in sorted(run_ids):
            run = session.get(DBTestRun, run_id)
            status = str(getattr(run, "status", "") or "")
            if status not in terminal_statuses:
                status_file = RUNS_DIR / run_id / "status.txt"
                if status_file.exists():
                    status = status_file.read_text(errors="replace").strip()
            if status not in terminal_statuses:
                continue
            cleanup = kill_test_run_process_tree(run_id, grace_seconds=0.5)
            if cleanup.get("matched"):
                cleaned += int(cleanup.get("matched") or 0)
                logger.info("Cleaned terminal test-run browser process tree for %s: %s", run_id, cleanup)
    return cleaned


def sync_data_from_files():
    """Sync existing file-based runs and metadata to DB on startup."""
    logger.info("Syncing data from files to DB...")
    with Session(engine) as session:
        # 0. Fix any existing runs with null test_name
        runs_with_null_name = session.exec(
            select(DBTestRun).where(DBTestRun.test_name == None)  # noqa: E711
        ).all()
        for run in runs_with_null_name:
            run.test_name = run.spec_name
        session.commit()
        if runs_with_null_name:
            logger.info(f"Fixed {len(runs_with_null_name)} runs with null test_name")

        # 1. Sync Runs
        if RUNS_DIR.exists():
            for d in RUNS_DIR.iterdir():
                if not d.is_dir():
                    continue
                run_id = d.name

                # Check if exists
                if session.get(DBTestRun, run_id):
                    continue

                # Derive info
                plan_file = d / "plan.json"
                run_file = d / "run.json"
                status_file = d / "status.txt"
                execution_log = d / "execution.log"

                test_name = None
                steps_completed = 0
                total_steps = 0
                browser = "chromium"
                status = "unknown"

                # Try to get Plan info
                if plan_file.exists():
                    try:
                        plan_data = json.loads(plan_file.read_text())
                        test_name = plan_data.get("testName")
                        total_steps = len(plan_data.get("steps", []))
                        browser = plan_data.get("browser", "chromium")
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON in plan file {plan_file}: {e}")
                    except OSError as e:
                        logger.warning(f"Cannot read plan file {plan_file}: {e}")

                # Determine Status & Progress
                if run_file.exists():
                    try:
                        run_data = json.loads(run_file.read_text())
                        status = run_data.get("finalState", "completed")
                        steps_completed = len(run_data.get("steps", []))
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON in run file {run_file}: {e}")
                        status = "completed"
                    except OSError as e:
                        logger.warning(f"Cannot read run file {run_file}: {e}")
                        status = "completed"
                elif status_file.exists():
                    status = status_file.read_text().strip()
                elif plan_file.exists() or execution_log.exists():
                    status = "failed"  # Assume failed if incomplete and old

                # Check validation.json to override status if validation passed/failed
                validation_file = d / "validation.json"
                if validation_file.exists():
                    try:
                        val_data = json.loads(validation_file.read_text())
                        if val_data.get("status") == "success":
                            status = "passed"
                        elif val_data.get("status") == "failed" and status not in ["passed"]:
                            status = "failed"
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON in validation file {validation_file}: {e}")
                    except OSError as e:
                        logger.warning(f"Cannot read validation file {validation_file}: {e}")

                # Spec Name from spec.md if available
                spec_name = "unknown"
                if (d / "spec.md").exists():
                    # We don't easily know the original filename, but we can try to guess or leave it generic
                    spec_name = "restored_run"
                    # Try to find which spec it matches? Too expensive.

                # Create DB Entry
                # We use file modification time as creation time approximate
                mtime = datetime.utcfromtimestamp(os.path.getmtime(d))

                run = DBTestRun(
                    id=run_id,
                    spec_name=spec_name,
                    status=status,
                    created_at=mtime,
                    test_name=test_name or spec_name,  # Use spec_name as fallback
                    steps_completed=steps_completed,
                    total_steps=total_steps,
                    browser=browser,
                )
                session.add(run)

        # 2. Sync Metadata
        sync_spec_metadata_from_file(session)

        session.commit()
    logger.info("Sync complete.")


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
            pool = BROWSER_POOL or await get_browser_pool()
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

    pool = BROWSER_POOL or await get_browser_pool()
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


async def clean_stale_agent_queue_tasks():
    """Cancel stale or orphaned agent queue tasks."""
    return await _clean_stale_agent_queue_tasks()


async def clean_orphaned_agent_queue_tasks():
    """Compatibility alias for stale/orphaned agent queue cleanup."""
    return await _clean_stale_agent_queue_tasks()


# File upload security constants
MAX_UPLOAD_SIZE_BYTES = 5_000_000  # 5MB
ALLOWED_UPLOAD_TYPES = {"text/csv", "application/csv", "text/markdown", "text/plain"}


@app.post("/import/testrail")
async def import_testrail(file: UploadFile = File(...)):
    # Security: Validate file size
    # Read content first to check size (UploadFile.size may not be reliable)
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413, detail=f"File exceeds maximum size of {MAX_UPLOAD_SIZE_BYTES // 1_000_000}MB"
        )

    # Security: Validate content type
    if file.content_type and file.content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{file.content_type}'. Allowed: {', '.join(ALLOWED_UPLOAD_TYPES)}",
        )

    try:
        specs = import_utils.parse_testrail_csv(content)

        saved_files = []
        for spec in specs:
            fname = spec["name"]
            # Ensure safe filename
            if not fname.endswith(".md"):
                fname += ".md"

            # Security: Remove path components to prevent path traversal
            fname = Path(fname).name

            fpath = SPECS_DIR / fname
            # Ensure specs dir exists
            SPECS_DIR.mkdir(parents=True, exist_ok=True)

            fpath.write_text(spec["content"])
            saved_files.append(fname)

            # Sync to DB if needed?
            # The system syncs on startup, but maybe we should add to DB here too?
            # existing sync_data_from_files() logic runs at startup.
            # But the user might want to see them immediately.
            # However, spec metadata is separately managed.
            # The list_specs() endpoint reads from file system directly, so it should be fine.

        return {"count": len(saved_files), "files": saved_files}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ========= TestRail Export =========


class ExportTestrailRequest(BaseModel):
    spec_names: list[str]
    format: str = "xml"  # "xml" or "csv"
    separated_steps: bool = True
    project_id: str | None = None


@app.post("/export/testrail")
def export_testrail(request: ExportTestrailRequest, session: Session = Depends(get_session)):
    """Export selected specs as TestRail-compatible XML or CSV file."""
    import io

    from fastapi.responses import StreamingResponse

    from utils.spec_parser import parse_spec_file

    from .export_utils import generate_testrail_csv, generate_testrail_xml

    if not request.spec_names:
        raise HTTPException(status_code=400, detail="No specs selected for export")

    if request.format not in ("xml", "csv"):
        raise HTTPException(status_code=400, detail="Format must be 'xml' or 'csv'")

    all_cases = []
    for spec_name in request.spec_names:
        spec_path = SPECS_DIR / spec_name
        if not spec_path.exists():
            continue

        # Load DB metadata for tags
        metadata = None
        meta = get_db_spec_metadata(session, spec_name, request.project_id)
        if meta:
            metadata = {"tags": meta.tags}

        try:
            cases = parse_spec_file(spec_path, metadata=metadata, specs_dir=SPECS_DIR)
            all_cases.extend(cases)
        except Exception as e:
            logger.warning(f"Failed to parse spec {spec_name}: {e}")
            continue

    if not all_cases:
        raise HTTPException(status_code=400, detail="No test cases could be parsed from the selected specs")

    project_name = "Exported Tests"
    if request.project_id:
        project_name = request.project_id

    if request.format == "xml":
        content = generate_testrail_xml(all_cases, project_name=project_name)
        media_type = "application/xml"
        filename = "testrail-export.xml"
    else:
        content = generate_testrail_csv(all_cases, separated_steps=request.separated_steps)
        media_type = "text/csv"
        filename = "testrail-export.csv"

    return StreamingResponse(
        io.StringIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ========= Execution Logic =========


def update_batch_stats(batch_id: str):
    """Update batch statistics after a run completes.

    Uses explicit transaction with rollback on failure to ensure data integrity.
    Locks the batch row to prevent race conditions when multiple runs complete simultaneously.
    """
    if not batch_id:
        return

    with Session(engine) as session:
        try:
            # Use SELECT FOR UPDATE to lock the batch row and prevent race conditions
            # This ensures only one concurrent update can happen at a time
            from sqlalchemy import text

            from .db import get_database_type

            batch = session.get(RegressionBatch, batch_id)
            if not batch:
                return
            previous_status = batch.status

            # For PostgreSQL, use row-level locking to prevent race conditions
            # For SQLite, the database-level locking handles this
            if get_database_type() == "postgresql":
                session.execute(
                    text("SELECT id FROM regression_batches WHERE id = :batch_id FOR UPDATE"), {"batch_id": batch_id}
                )
                # Refresh to get locked row
                session.refresh(batch)

            # Get all runs for this batch (within the same transaction)
            runs = session.exec(select(DBTestRun).where(DBTestRun.batch_id == batch_id)).all()

            # Recalculate counts (total_tests from actual runs, not original spec count)
            batch.total_tests = len(runs)
            batch.passed = sum(1 for r in runs if r.status in ("passed", "completed"))
            batch.failed = sum(1 for r in runs if r.status in ("failed", "error"))
            batch.stopped = sum(1 for r in runs if r.status in ("stopped", "cancelled"))
            batch.running = sum(1 for r in runs if r.status in ("running", "in_progress"))
            batch.queued = sum(1 for r in runs if r.status == "queued")

            # Update batch status
            if batch.running > 0 or batch.queued > 0:
                batch.status = "running"
                if not batch.started_at:
                    # Find earliest started run
                    started_runs = [r for r in runs if r.started_at]
                    if started_runs:
                        batch.started_at = min(r.started_at for r in started_runs)
            elif batch.total_tests > 0 and (batch.passed + batch.failed + batch.stopped) == batch.total_tests:
                batch.status = "completed"
                # Find latest completed run
                completed_runs = [r for r in runs if r.completed_at]
                if completed_runs:
                    batch.completed_at = max(r.completed_at for r in completed_runs)
                else:
                    batch.completed_at = datetime.utcnow()

                # Cache actual test counts on completion
                try:
                    from .regression import _calculate_actual_test_counts

                    actual_total, actual_passed, actual_failed = _calculate_actual_test_counts(runs)
                    batch.actual_total_tests = actual_total
                    batch.actual_passed = actual_passed
                    batch.actual_failed = actual_failed
                except Exception as count_err:
                    logger.warning(f"Failed to cache actual test counts for {batch_id}: {count_err}")
            elif batch.total_tests == 0:
                batch.status = "completed"
                if not batch.completed_at:
                    batch.completed_at = datetime.utcnow()

            session.add(batch)
            session.commit()

            if previous_status != "completed" and batch.status == "completed":
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(_finalize_quality_gate_for_batch_safe(batch_id))
                except RuntimeError:
                    logger.debug("No running event loop available to finalize quality gate for batch %s", batch_id)

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update batch stats for {batch_id}: {e}", exc_info=True)
            raise


async def _finalize_quality_gate_for_batch_safe(batch_id: str):
    try:
        from orchestrator.services.quality_gate import finalize_quality_gate_for_batch

        finalized = await finalize_quality_gate_for_batch(batch_id)
        if finalized:
            logger.info("Finalized %d quality gate(s) for batch %s", finalized, batch_id)
    except Exception as e:
        logger.warning("Failed to finalize quality gate feedback for batch %s: %s", batch_id, e)


async def _quality_gate_finalizer_loop():
    """Periodically publish missed final PR quality gate feedback."""
    while True:
        try:
            await asyncio.sleep(60)
            from orchestrator.services.quality_gate import finalize_stale_quality_gates

            finalized = await finalize_stale_quality_gates()
            if finalized:
                logger.info("Quality gate finalizer published %d stale final update(s)", finalized)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Quality gate finalizer loop error: %s", e)


async def _batch_watchdog():
    """Background task that detects and cleans up stuck runs.

    Runs every 60 seconds. First cleans orphaned runs (running in DB but no
    active process, >120s old). Then checks for runs stuck beyond MAX_RUN_AGE_MINUTES
    (default 120, configurable via env). Skips runs with recently-updated log files.
    """
    MAX_RUN_AGE_MINUTES = int(os.environ.get("MAX_RUN_AGE_MINUTES", "120"))
    ORPHAN_AGE_SECONDS = 120

    while True:
        try:
            await asyncio.sleep(60)

            # --- Orphan cleanup (belt-and-suspenders with get_queue_status) ---
            with Session(engine) as session:
                running_runs = session.exec(
                    select(DBTestRun).where(DBTestRun.status.in_(["running", "in_progress"]))
                ).all()

                now = datetime.utcnow()
                orphan_batch_ids = set()
                orphan_cleaned = 0
                for r in running_runs:
                    if r.temporal_workflow_id:
                        continue
                    if is_process_active(r.id):
                        continue
                    age_ref = r.started_at or r.queued_at
                    if not age_ref or (now - age_ref).total_seconds() <= ORPHAN_AGE_SECONDS:
                        continue

                    r.status = "stopped"
                    r.completed_at = now
                    r.queue_position = None
                    session.add(r)

                    run_dir = RUNS_DIR / r.id
                    if run_dir.exists():
                        (run_dir / "status.txt").write_text("stopped")

                    if r.batch_id:
                        orphan_batch_ids.add(r.batch_id)

                    orphan_cleaned += 1
                    logger.warning(
                        f"Watchdog: Orphaned run {r.id} (no active process, "
                        f"age={int((now - age_ref).total_seconds())}s). Marked stopped."
                    )

                if orphan_cleaned > 0:
                    session.commit()
                    logger.info(f"Watchdog: Cleaned {orphan_cleaned} orphaned runs")
                    for bid in orphan_batch_ids:
                        try:
                            update_batch_stats(bid)
                        except Exception as e:
                            logger.error(f"Watchdog: Failed to update batch {bid} after orphan cleanup: {e}")

            # --- Stuck run check ---
            with Session(engine) as session:
                now = datetime.utcnow()
                cutoff = now - timedelta(minutes=MAX_RUN_AGE_MINUTES)

                # Find runs stuck in running for too long, or running with no started_at
                stuck_runs = session.exec(
                    select(DBTestRun).where(
                        DBTestRun.status.in_(["running", "in_progress"]),
                        (DBTestRun.started_at < cutoff) | (DBTestRun.started_at == None),
                    )
                ).all()
                # For runs with no started_at, only include if queued_at is also old
                stuck_runs = [
                    r
                    for r in stuck_runs
                    if not r.temporal_workflow_id
                    and (r.started_at is not None or (r.queued_at and r.queued_at < cutoff))
                ]

                if not stuck_runs:
                    continue

                batch_ids_to_update = set()
                killed_runs = []
                for run in stuck_runs:
                    # Check if run is still making progress (log file recently modified)
                    run_dir = RUNS_DIR / run.id
                    log_file = run_dir / "execution.log"
                    if log_file.exists():
                        log_age = (now - datetime.utcfromtimestamp(log_file.stat().st_mtime)).total_seconds()
                        if log_age < 300:  # Log updated in last 5 minutes = still active
                            logger.info(
                                f"Watchdog: Run {run.id} still active (log updated {int(log_age)}s ago), skipping"
                            )
                            continue

                    logger.warning(
                        f"Watchdog: Run {run.id} stuck in '{run.status}' since {run.started_at}. Forcing to 'error'."
                    )
                    run.status = "error"
                    run.error_message = f"Watchdog: Run stuck for >{MAX_RUN_AGE_MINUTES} minutes"
                    run.completed_at = datetime.utcnow()
                    session.add(run)

                    # Write status file
                    if run_dir.exists():
                        (run_dir / "status.txt").write_text("error")

                    if run.batch_id:
                        batch_ids_to_update.add(run.batch_id)

                    killed_runs.append(run)

                session.commit()
                if killed_runs:
                    logger.info(f"Watchdog: Force-errored {len(killed_runs)} stuck runs")

                # Kill associated processes
                for run in killed_runs:
                    proc = get_process(run.id)
                    if proc:
                        try:
                            import signal as _signal

                            os.killpg(os.getpgid(proc.pid), _signal.SIGKILL)
                        except (ProcessLookupError, OSError):
                            try:
                                proc.kill()
                            except (ProcessLookupError, OSError):
                                pass
                        unregister_process(run.id)

                # Update batch stats
                for batch_id in batch_ids_to_update:
                    try:
                        update_batch_stats(batch_id)
                    except Exception as e:
                        logger.error(f"Watchdog: Failed to update batch {batch_id}: {e}")

        except asyncio.CancelledError:
            logger.info("Batch watchdog cancelled")
            break
        except Exception as e:
            logger.error(f"Batch watchdog error: {e}", exc_info=True)
            await asyncio.sleep(30)


async def _queue_watchdog():
    """Background task that detects orphaned queued entries after uvicorn reload.

    Runs every 30 seconds. If a run has been in 'queued' status for > 60 seconds
    and has no backing asyncio task in PROCESS_MANAGER, it's marked as 'stopped'.
    This catches the case where uvicorn reloads kill asyncio tasks silently.
    """
    GRACE_PERIOD_SECONDS = 60

    while True:
        try:
            await asyncio.sleep(30)

            with Session(engine) as session:
                queued_runs = session.exec(select(DBTestRun).where(DBTestRun.status == "queued")).all()

                if not queued_runs:
                    continue

                cutoff = datetime.utcnow() - timedelta(seconds=GRACE_PERIOD_SECONDS)
                batch_ids_to_update = set()
                cleaned = 0

                for run in queued_runs:
                    if run.temporal_workflow_id:
                        continue
                    # Grace period: skip recently queued entries
                    if run.queued_at and run.queued_at > cutoff:
                        continue

                    # Check if there's a backing asyncio task
                    has_task = (
                        PROCESS_MANAGER
                        and run.id in PROCESS_MANAGER._asyncio_tasks
                        and not PROCESS_MANAGER._asyncio_tasks[run.id].done()
                    )
                    if has_task:
                        continue

                    # Orphaned: queued in DB but no asyncio task backing it
                    logger.warning(
                        f"Queue watchdog: Run {run.id} orphaned in 'queued' status "
                        f"(queued_at={run.queued_at}). Marking as stopped."
                    )
                    run.status = "stopped"
                    run.queue_position = None
                    run.error_message = "Orphaned: server restarted while queued"
                    run.completed_at = datetime.utcnow()
                    session.add(run)

                    # Update status.txt file
                    run_dir = RUNS_DIR / run.id
                    if run_dir.exists():
                        (run_dir / "status.txt").write_text("stopped")

                    if run.batch_id:
                        batch_ids_to_update.add(run.batch_id)
                    cleaned += 1

                if cleaned > 0:
                    session.commit()
                    logger.info(f"Queue watchdog: Cleaned {cleaned} orphaned queued runs")

                    # Update batch stats
                    for batch_id in batch_ids_to_update:
                        try:
                            update_batch_stats(batch_id)
                        except Exception as e:
                            logger.error(f"Queue watchdog: Failed to update batch {batch_id}: {e}")

        except asyncio.CancelledError:
            logger.info("Queue watchdog cancelled")
            break
        except Exception as e:
            logger.error(f"Queue watchdog error: {e}", exc_info=True)
            await asyncio.sleep(30)


async def _exploration_cleanup_loop():
    """Background task that cleans up stuck exploration sessions.

    Runs every 5 minutes. Marks explorations that have been "running" longer than
    their configured timeout as "failed". Also sweeps the in-memory tracking dict
    and cleans up stale browser pool slots.
    """
    CLEANUP_INTERVAL = 300  # 5 minutes
    DEFAULT_TIMEOUT_MINUTES = 60  # Max exploration timeout

    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL)

            # 1. Sweep done tasks from exploration tracking dict
            from .exploration import _running_explorations, _sweep_done_tasks

            _sweep_done_tasks()

            # 2. Mark stuck explorations in database as failed
            with Session(engine) as session:
                cutoff = datetime.utcnow() - timedelta(minutes=DEFAULT_TIMEOUT_MINUTES)

                stuck_explorations = session.exec(
                    select(ExplorationSession).where(
                        ExplorationSession.status.in_(["running", "queued"]), ExplorationSession.created_at < cutoff
                    )
                ).all()

                for exp in stuck_explorations:
                    # Parse config to get actual timeout
                    timeout = DEFAULT_TIMEOUT_MINUTES
                    try:
                        import json

                        config = json.loads(exp.config_json or "{}")
                        timeout = config.get("timeout_minutes", DEFAULT_TIMEOUT_MINUTES)
                    except Exception:
                        pass

                    exp_cutoff = datetime.utcnow() - timedelta(minutes=timeout)
                    if exp.created_at < exp_cutoff:
                        logger.warning(
                            f"Exploration cleanup: {exp.id} stuck in '{exp.status}' "
                            f"since {exp.created_at}. Marking as failed."
                        )
                        exp.status = "failed"
                        exp.error_message = f"Cleanup: stuck for >{timeout} minutes"
                        exp.completed_at = datetime.utcnow()
                        session.add(exp)

                        # Cancel the task if tracked in memory
                        entry = _running_explorations.pop(exp.id, None)
                        if entry:
                            task, _ = entry
                            task.cancel()

                if stuck_explorations:
                    session.commit()
                    logger.info(f"Exploration cleanup: processed {len(stuck_explorations)} stuck sessions")

            # 3. Clean up stale browser pool slots
            if BROWSER_POOL:
                stale_cleaned = await BROWSER_POOL.cleanup_stale(max_age_minutes=DEFAULT_TIMEOUT_MINUTES)
                if stale_cleaned:
                    logger.info(f"Exploration cleanup: cleaned {len(stale_cleaned)} stale browser slots")

                # Also clean completed slot history
                try:
                    await BROWSER_POOL.cleanup_old_completed()
                except Exception:
                    pass

        except asyncio.CancelledError:
            logger.info("Exploration cleanup loop cancelled")
            break
        except Exception as e:
            logger.error(f"Exploration cleanup loop error: {e}", exc_info=True)
            await asyncio.sleep(60)  # Backoff on error


async def _browser_pool_cleanup_loop():
    """Periodically clean up stale browser slots every 10 minutes.

    If a browser slot crashes mid-operation, it stays "acquired" forever
    until the next restart. This loop prevents that leak.
    """
    while True:
        try:
            await asyncio.sleep(600)  # 10 minutes
            if BROWSER_POOL:
                stale = await BROWSER_POOL.cleanup_stale(max_age_minutes=120)
                old = await BROWSER_POOL.cleanup_old_completed(max_age_hours=24)
                if stale:
                    logger.info(f"Periodic cleanup: freed {len(stale)} stale browser slots")
                if old:
                    logger.info(f"Periodic cleanup: removed {old} old completed slot records")
        except asyncio.CancelledError:
            logger.info("Browser pool cleanup loop cancelled")
            break
        except Exception as e:
            logger.error(f"Browser pool cleanup error: {e}")
            await asyncio.sleep(60)


async def _infrastructure_maintenance_loop():
    """Periodic infrastructure maintenance: orphan cleanup, temp cleanup, DB maintenance.

    Runs every 15 minutes for orphan/temp cleanup.
    Runs DB maintenance every 24 hours.
    """
    import glob
    import time as time_module

    iteration = 0
    DB_MAINTENANCE_ITERATIONS = 96  # 96 * 15 min = 24 hours

    while True:
        try:
            await asyncio.sleep(900)  # 15 minutes
            iteration += 1

            # --- Process PID file cleanup (every 15 min) ---
            # Only remove stale PID files for dead processes, don't kill anything.
            # cleanup_orphans() (which kills) is only called once at startup.
            if PROCESS_MANAGER:
                stale = PROCESS_MANAGER.cleanup_stale_pid_files()
                if stale > 0:
                    logger.info(f"Infrastructure: removed {stale} stale PID files")

            # --- Temp directory cleanup (every 15 min) ---
            try:
                tmp_cleaned = 0
                for d in glob.glob("/tmp/tmp*"):
                    if os.path.isdir(d) and (time_module.time() - os.path.getmtime(d)) > 7200:
                        shutil.rmtree(d, ignore_errors=True)
                        tmp_cleaned += 1
                if tmp_cleaned:
                    logger.info(f"Infrastructure: removed {tmp_cleaned} stale temp directories")
            except Exception as e:
                logger.debug(f"Temp cleanup error: {e}")

            # --- Rate limiter cleanup (every 15 min) ---
            try:
                from .middleware.rate_limit import cleanup_expired_entries

                cleaned = cleanup_expired_entries()
                if cleaned > 0:
                    logger.info(f"Infrastructure: cleaned {cleaned} expired rate limit entries")
            except Exception as e:
                logger.debug(f"Rate limiter cleanup error: {e}")

            # --- Database maintenance (every ~24 hours) ---
            if iteration % DB_MAINTENANCE_ITERATIONS == 0:
                await _run_db_maintenance()

        except asyncio.CancelledError:
            logger.info("Infrastructure maintenance loop cancelled")
            break
        except Exception as e:
            logger.error(f"Infrastructure maintenance error: {e}", exc_info=True)
            await asyncio.sleep(60)


async def _schedule_execution_watchdog():
    """Sync schedule execution status from completed batches.

    Runs every 30 seconds, checks running ScheduleExecution records and
    syncs their status from the linked RegressionBatch records.
    Also cleans up stale executions that have no batch or are too old.
    """
    from .models_db import CronSchedule, ScheduleExecution

    # On first run, clean up stale executions from previous server instances
    try:
        from orchestrator.services.scheduler import (
            cleanup_stale_executions,
            reconcile_workflow_schedule_executions,
        )

        await cleanup_stale_executions()
        await reconcile_workflow_schedule_executions()
    except Exception as e:
        logger.debug(f"Stale execution cleanup on startup: {e}")

    while True:
        try:
            await asyncio.sleep(30)
            try:
                from orchestrator.services.scheduler import reconcile_workflow_schedule_executions

                await reconcile_workflow_schedule_executions()
            except Exception as e:
                logger.debug(f"Workflow schedule reconciliation skipped: {e}")

            now = datetime.utcnow()

            with Session(engine) as session:
                # Find running/pending executions
                running_execs = session.exec(
                    select(ScheduleExecution).where(ScheduleExecution.status.in_(["pending", "running"]))
                ).all()

                for execution in running_execs:
                    # Handle executions without a batch (stuck in pending)
                    if not execution.batch_id:
                        # If pending for more than 5 minutes with no batch, mark failed
                        age_seconds = (now - execution.created_at).total_seconds() if execution.created_at else 0
                        if age_seconds > 300:
                            execution.status = "failed"
                            execution.error_message = "No batch was created for this execution"
                            execution.completed_at = now
                            session.add(execution)
                        continue

                    batch = session.get(RegressionBatch, execution.batch_id)
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

                        # Update schedule stats
                        schedule = session.get(CronSchedule, execution.schedule_id)
                        if schedule:
                            schedule.last_run_status = "passed" if batch.failed == 0 else "failed"
                            if batch.failed == 0:
                                schedule.successful_executions += 1
                            else:
                                schedule.failed_executions += 1
                            # Update avg duration
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
                        # Batch is in an unexpected terminal state (e.g., cancelled)
                        execution.status = "failed"
                        execution.error_message = f"Batch ended with status: {batch.status}"
                        execution.completed_at = now
                        session.add(execution)

                session.commit()

        except asyncio.CancelledError:
            logger.info("Schedule execution watchdog cancelled")
            break
        except Exception as e:
            logger.error(f"Schedule execution watchdog error: {e}", exc_info=True)
            await asyncio.sleep(30)


async def _run_db_maintenance():
    """Run periodic database maintenance: ANALYZE and old data pruning."""
    from sqlalchemy import text

    db_type = get_database_type()
    if db_type != "postgresql":
        return

    try:
        with engine.connect() as conn:
            # ANALYZE heavily-written tables for query plan optimization
            for table in ["testrun", "exploration_sessions", "requirements", "agentrun"]:
                try:
                    conn.execute(text(f"ANALYZE {table}"))
                except Exception:
                    pass

            # Prune storage_stats older than 90 days
            try:
                result = conn.execute(text("DELETE FROM storage_stats WHERE recorded_at < NOW() - INTERVAL '90 days'"))
                if result.rowcount:
                    logger.info(f"DB maintenance: pruned {result.rowcount} old storage_stats rows")
            except Exception:
                pass

            # Prune completed archive_jobs older than 90 days
            try:
                result = conn.execute(
                    text(
                        "DELETE FROM archive_jobs WHERE status = 'completed' "
                        "AND created_at < NOW() - INTERVAL '90 days'"
                    )
                )
                if result.rowcount:
                    logger.info(f"DB maintenance: pruned {result.rowcount} old archive_jobs rows")
            except Exception:
                pass

            conn.commit()
            logger.info("DB maintenance: ANALYZE and pruning complete")
    except Exception as e:
        logger.error(f"DB maintenance error: {e}")


async def _log_startup_diagnostics():
    """Log system diagnostics at startup for early problem detection."""
    diagnostics = []

    # Database
    db_type = get_database_type()
    diagnostics.append(f"Database: {db_type}")
    if db_type == "postgresql":
        diagnostics.append("  Pool: size=30, max_overflow=60, timeout=30s, statement_timeout=30s")

    # Redis
    redis_status = "unavailable"
    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE

        if REDIS_AVAILABLE:
            redis_status = "connected"
    except Exception:
        pass
    diagnostics.append(f"Redis: {redis_status}")

    # MinIO
    minio_status = "not configured"
    try:
        minio_endpoint = os.environ.get("MINIO_ENDPOINT")
        if minio_endpoint:
            from orchestrator.services.storage import StorageService

            storage = StorageService()
            if await asyncio.to_thread(storage.health_check):
                minio_status = f"connected ({minio_endpoint})"
            else:
                minio_status = f"unhealthy ({minio_endpoint})"
    except Exception:
        minio_status = "error"
    diagnostics.append(f"MinIO: {minio_status}")

    # Disk space
    try:
        stat = shutil.disk_usage(str(RUNS_DIR))
        free_gb = stat.free / (1024**3)
        total_gb = stat.total / (1024**3)
        pct_free = (stat.free / stat.total) * 100
        level = "OK" if pct_free > 10 else "LOW" if pct_free > 5 else "CRITICAL"
        diagnostics.append(f"Disk: {free_gb:.1f}GB free / {total_gb:.1f}GB total ({pct_free:.0f}% free) [{level}]")
    except Exception:
        diagnostics.append("Disk: unknown")

    # Browser pool
    max_browsers = int(os.environ.get("MAX_BROWSER_INSTANCES", "5"))
    diagnostics.append(f"Browser pool: max_instances={max_browsers}")

    # Missing env vars that affect functionality
    optional_vars = {
        "OPENAI_API_KEY": "memory system embeddings",
        "MINIO_ENDPOINT": "artifact archival",
        "REDIS_URL": "distributed queue/rate limiting",
    }
    missing = [f"{k} ({v})" for k, v in optional_vars.items() if not os.environ.get(k)]
    if missing:
        diagnostics.append(f"Optional env vars not set: {', '.join(missing)}")

    logger.info("=== Startup Diagnostics ===\n  " + "\n  ".join(diagnostics))


_STARTUP_IMPORT_FAILURE_MESSAGE = (
    "Transient Docker bind-mount import failure while starting the test runner (Errno 35)."
)


def _record_startup_import_failure(run_id: str, run_dir_path: Path, *, retrying: bool) -> None:
    message = (
        f"{_STARTUP_IMPORT_FAILURE_MESSAGE} Retrying test runner."
        if retrying
        else f"{_STARTUP_IMPORT_FAILURE_MESSAGE} Retry attempts exhausted."
    )
    try:
        with Session(engine) as session:
            run = session.get(DBTestRun, run_id)
            if run:
                if not retrying:
                    run.status = "error"
                    run.error_message = message
                    run.completed_at = datetime.utcnow()
                run.current_stage = "startup"
                run.stage_message = message
                session.add(run)
                session.commit()
    except Exception as exc:
        logger.debug(
            "Could not record startup import failure status for %s: %s",
            run_id,
            exc,
        )

    if not retrying:
        try:
            (run_dir_path / "status.txt").write_text("error")
            (run_dir_path / "pipeline_error.json").write_text(
                json.dumps({"stage": "startup", "error": message}, indent=2)
            )
        except OSError:
            pass


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
    from orchestrator.services.test_run_subprocess_retry import run_test_cli_subprocess_with_retry

    return run_test_cli_subprocess_with_retry(
        cmd=cmd,
        cwd=cwd,
        env=env,
        run_id=run_id,
        run_dir_path=run_dir_path,
        spec_name=spec_name,
        batch_id=batch_id,
        append_workflow_log=append_workflow_log,
        register_process=register_process,
        unregister_process=unregister_process,
        process_manager=PROCESS_MANAGER,
        logger=logger,
        record_startup_import_failure=_record_startup_import_failure,
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
    global PROCESS_MANAGER

    def _append_workflow_log(message: str, **payload: Any) -> None:
        try:
            run_dir_path = Path(run_dir)
            run_dir_path.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": datetime.utcnow().isoformat() + "Z",
                "message": message,
                **payload,
            }
            with (run_dir_path / "workflow.log").open("a", encoding="utf-8") as log:
                log.write(json.dumps(entry, default=str) + "\n")
        except Exception:
            pass

    _append_workflow_log("Subprocess preparing.", run_id=run_id, spec_path=spec_path)

    with Session(engine) as session:
        run = session.get(DBTestRun, run_id)
        if run and run.status in ("stopped", "cancelled"):
            logger.info(f"Run {run_id} was {run.status} before subprocess start. Aborting.")
            _append_workflow_log("Subprocess aborted before start.", status=run.status)
            return

    cmd = [sys.executable, "orchestrator/cli.py", spec_path, "--run-dir", run_dir, "--browser", browser]
    if try_code_path:
        cmd.extend(["--try-code", try_code_path])
    if hybrid:
        cmd.extend(["--hybrid", "--max-iterations", str(max_iterations)])

    run_dir_path = Path(run_dir)
    _write_run_browser_metadata(run_dir_path, _build_run_browser_metadata(headless=headless, phase="executing"))

    # Copy reusable .claude/ project artifacts into the run sandbox.
    # Local settings stay in the project config and are not copied per run.
    copy_claude_project_config(BASE_DIR / ".claude", run_dir_path / ".claude")

    # Copy Playwright config to run directory with absolute paths
    # The workflow scripts change to CLAUDE_CONFIG_DIR for MCP config isolation,
    # but Playwright needs its config file in the current directory with correct paths
    playwright_config_src = BASE_DIR / "playwright.config.ts"
    playwright_config_dst = run_dir_path / "playwright.config.ts"
    if playwright_config_src.exists() and not playwright_config_dst.exists():
        config_content = prepare_run_playwright_config_content(
            playwright_config_src.read_text(),
            base_dir=BASE_DIR,
            run_dir=run_dir_path,
            headless=headless,
            storage_state_path=storage_state_path,
        )
        playwright_config_dst.write_text(config_content)

    runtime_metadata = write_playwright_test_mcp_config(
        run_dir=run_dir_path,
        server_name="playwright-test",
        config_path=playwright_config_dst,
        headless=headless,
        storage_state_path=storage_state_path,
    )
    _write_run_browser_metadata(
        run_dir_path,
        _merge_run_browser_metadata(
            _build_run_browser_metadata(headless=headless, phase="executing"),
            runtime_metadata,
            headless=headless,
            phase="executing",
        ),
    )
    logger.info(
        "Created Playwright Test MCP config for run %s (headless=%s, args=%s)",
        run_id,
        headless,
        runtime_metadata.get("mcp_args"),
    )

    # The Playwright Test MCP setup tools resolve seed files relative to cwd.
    # Generate a run-local seed from this spec so setup opens the target app
    # instead of falling back to the MCP package's blank default seed.
    target_url = _extract_run_target_url(spec_path)
    seed_dst = _write_run_seed_spec(run_dir_path, target_url)
    logger.debug(f"Wrote run seed file: {seed_dst} (target_url={target_url or 'about:blank'})")

    # Set up environment with headless, memory, and config directory settings
    env = os.environ.copy()
    env["HEADLESS"] = "true" if headless else "false"
    env["PLAYWRIGHT_HEADLESS"] = "true" if headless else "false"
    if not headless:
        env["CI"] = ""
        env["PLAYWRIGHT_WORKERS"] = "1"
    env["MEMORY_ENABLED"] = "true" if memory_enabled else "false"
    env["QUORVEX_RUN_MODEL_TIER"] = model_tier or "tool_deep"
    env["BROWSER_SLOT_PARENT_OWNER_TYPE"] = "test_run"
    env["BROWSER_SLOT_PARENT_RUN_ID"] = run_id
    # Tell workflows to use run-specific config directory
    env["CLAUDE_CONFIG_DIR"] = str(run_dir_path)
    # Pass project_id for credentials and memory isolation
    if project_id:
        env["PROJECT_ID"] = project_id
        env["MEMORY_PROJECT_ID"] = project_id
    if browser_auth_context:
        env["QUORVEX_BROWSER_AUTH_CONTEXT"] = json.dumps(browser_auth_context)
    normalized_test_data_refs = _normalize_request_test_data_refs(test_data_refs)
    if normalized_test_data_refs:
        env["QUORVEX_TEST_DATA_REFS"] = json.dumps(normalized_test_data_refs)

    with Session(engine) as session:
        run = session.get(DBTestRun, run_id)
        if run and run.status in ("stopped", "cancelled"):
            logger.info(f"Run {run_id} was {run.status} before process spawn. Aborting.")
            _append_workflow_log("Subprocess aborted before process spawn.", status=run.status)
            return

    _run_test_cli_subprocess_with_retry(
        cmd=cmd,
        cwd=BASE_DIR,
        env=env,
        run_id=run_id,
        run_dir_path=run_dir_path,
        spec_name=spec_name,
        batch_id=batch_id,
        append_workflow_log=_append_workflow_log,
        timeout_seconds=3600,
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
    def _append_workflow_log(message: str, **payload: Any) -> None:
        try:
            run_dir_path = Path(run_dir)
            run_dir_path.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": datetime.utcnow().isoformat() + "Z",
                "message": message,
                **payload,
            }
            with (run_dir_path / "workflow.log").open("a", encoding="utf-8") as log:
                log.write(json.dumps(entry, default=str) + "\n")
        except Exception:
            pass

    _append_workflow_log("Test run wrapper started.", run_id=run_id, spec_path=spec_path)

    # Get execution settings for this run
    headless = False
    memory_enabled = True
    with Session(engine) as session:
        settings = session.get(DBExecutionSettings, 1)
        if settings:
            # Always respect headless setting (user can force headless for any run)
            headless = settings.headless_in_parallel
            memory_enabled = settings.memory_enabled
    if os.environ.get("VNC_ENABLED", "").lower() == "true":
        headless = False

    # Use unified browser pool for slot management
    pool = BROWSER_POOL or await get_browser_pool()
    try:
        stale_cleaned = await pool.cleanup_stale(max_age_minutes=60)
        if stale_cleaned:
            _append_workflow_log("Cleaned stale browser slots before acquisition.", cleaned_slots=stale_cleaned)
    except Exception as exc:
        _append_workflow_log("Browser slot cleanup before acquisition failed.", error=str(exc))

    # Block if a load test is running
    from orchestrator.services.load_test_lock import check_system_available

    await check_system_available("test run")

    try:
        _append_workflow_log("Waiting for browser slot.", browser_slot_request_id=run_id)
        async with pool.browser_slot(
            request_id=run_id,
            operation_type=BrowserOpType.TEST_RUN,
            description=f"Test: {spec_name or spec_path}",
            max_operation_duration=7200,  # 2 hours - matches realistic pipeline max
        ) as acquired:
            if not acquired:
                # Timeout waiting for slot
                logger.warning(f"Run {run_id} failed to acquire browser slot (timeout)")
                with Session(engine) as session:
                    run = session.get(DBTestRun, run_id)
                    if run:
                        run.status = "error"
                        run.error_message = "Timeout waiting for browser slot"
                        run.queue_position = None
                        run.completed_at = datetime.utcnow()
                        session.add(run)
                        session.commit()
                status_file = Path(run_dir) / "status.txt"
                status_file.write_text("error")
                if batch_id:
                    update_batch_stats(batch_id)
                return

            _append_workflow_log("Browser slot acquired.", browser_slot_request_id=run_id)

            # Update status to 'running' and set started_at
            # Guard: check if the run was stopped/cancelled while waiting in queue
            with Session(engine) as session:
                run = session.get(DBTestRun, run_id)
                if run:
                    if run.status in ("stopped", "cancelled"):
                        logger.info(f"Run {run_id} was {run.status} while queued. Aborting.")
                        _append_workflow_log("Run aborted after browser slot acquisition.", status=run.status)
                        if batch_id:
                            update_batch_stats(batch_id)
                        return  # Browser slot released by context manager
                    run.status = "running"
                    run.started_at = datetime.utcnow()
                    run.queue_position = None  # No longer queued
                    session.add(run)
                    session.commit()

            # Update batch stats (now running)
            if batch_id:
                update_batch_stats(batch_id)

            # Execute the test
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                execute_run_task,
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
            _append_workflow_log("Native run executor returned.", run_id=run_id)

            # Update DB Status after completion
            with Session(engine) as session:
                run = session.get(DBTestRun, run_id)
                if run:
                    try:
                        # Primary source: status.txt (written by CLI)
                        status_file = Path(run_dir) / "status.txt"
                        if status_file.exists():
                            file_status = status_file.read_text().strip()
                            if file_status:  # Only update if not empty
                                run.status = file_status
                                logger.debug(f"[{run_id}] Status from status.txt: {file_status}")

                        # Secondary source: run.json (legacy standard pipeline)
                        run_file = Path(run_dir) / "run.json"
                        if run_file.exists():
                            try:
                                run_data = json.loads(run_file.read_text())
                                if "finalState" in run_data:
                                    run.status = run_data["finalState"]
                                run.steps_completed = len(run_data.get("steps", []))

                                # Extract error message from failed steps
                                if run.status == "failed":
                                    for step in run_data.get("steps", []):
                                        if step.get("error"):
                                            run.error_message = step.get("error")[:500]
                                            break
                            except json.JSONDecodeError:
                                pass  # Ignore malformed JSON

                        # Get step count from plan.json
                        plan_file = Path(run_dir) / "plan.json"
                        if plan_file.exists():
                            try:
                                plan_data = json.loads(plan_file.read_text())
                                if "testName" in plan_data:
                                    run.test_name = plan_data["testName"]
                                if "steps" in plan_data:
                                    run.total_steps = len(plan_data["steps"])
                            except json.JSONDecodeError:
                                pass  # Ignore malformed JSON

                        # Read pipeline error details (written by full_native_pipeline.py)
                        error_file = Path(run_dir) / "pipeline_error.json"
                        if error_file.exists():
                            try:
                                error_data = json.loads(error_file.read_text())
                                if error_data.get("error"):
                                    error_msg = str(error_data["error"])[:500]
                                    stage = str(error_data.get("stage", "") or "")
                                    if stage == "test_data_resolution":
                                        run.stage_message = f"{stage}: {error_msg}"
                                    if not run.error_message:
                                        if stage:
                                            run.error_message = f"[{stage}] {error_msg}"
                                        else:
                                            run.error_message = error_msg
                            except json.JSONDecodeError:
                                pass

                        # Fallback: if subprocess completed but status is still non-terminal, force to 'error'
                        if run.status in ("running", "queued"):
                            logger.warning(
                                f"[{run_id}] Process exited but status still '{run.status}'. Forcing to 'error'."
                            )
                            run.status = "error"
                            if not run.error_message:
                                run.error_message = (
                                    "Process exited without writing status. Check execution.log for details."
                                )
                            # Also update status.txt so file and DB are consistent
                            try:
                                (Path(run_dir) / "status.txt").write_text("error")
                            except Exception:
                                pass

                        # Set completed_at timestamp
                        run.completed_at = datetime.utcnow()

                        # Invalidate code path cache for this spec to pick up new generated code
                        if run.status in ("passed", "completed"):
                            invalidate_code_path_cache(run.spec_name)

                    except Exception as e:
                        # Log error but still try to commit what we have
                        logger.warning(f"Error reading status files for {run_id}: {e}")

                    session.add(run)
                    session.commit()
                    logger.info(f"[{run_id}] Final DB status: {run.status}")
                    _append_workflow_log("Final DB status recorded.", status=run.status)

            # Update batch stats after run completion
            if batch_id:
                update_batch_stats(batch_id)

    except asyncio.CancelledError:
        # Task was cancelled while waiting or running
        logger.info(f"Run {run_id} cancelled")
        _append_workflow_log("Run wrapper cancelled.")
        with Session(engine) as session:
            run = session.get(DBTestRun, run_id)
            if run and run.status not in ("stopped", "cancelled", "passed", "failed", "error", "completed"):
                run.status = "cancelled"
                run.queue_position = None
                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()
        # Update status file
        status_file = Path(run_dir) / "status.txt"
        status_file.write_text("cancelled")
        # Update batch stats
        if batch_id:
            update_batch_stats(batch_id)
        raise  # Re-raise to properly handle cancellation

    except Exception as e:
        # Handle all other exceptions - prevents silent failures
        logger.error(f"Run {run_id} failed with exception: {e}", exc_info=True)
        _append_workflow_log("Run wrapper failed.", error=str(e))
        with Session(engine) as session:
            run = session.get(DBTestRun, run_id)
            if run:
                run.status = "error"
                run.error_message = str(e)[:500]
                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()
        # Update status file
        status_file = Path(run_dir) / "status.txt"
        status_file.write_text("error")
        # Update batch stats
        if batch_id:
            update_batch_stats(batch_id)


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
    global PROCESS_MANAGER

    from orchestrator.workflows.mobile_appium import MobileAppiumConfig, build_appium_mcp_config

    with Session(engine) as session:
        run = session.get(DBTestRun, run_id)
        if run and run.status in ("stopped", "cancelled"):
            logger.info(f"Mobile run {run_id} was {run.status} before subprocess start. Aborting.")
            return

    run_dir_path = Path(run_dir)
    run_dir_path.mkdir(parents=True, exist_ok=True)

    config = MobileAppiumConfig.from_env(
        platform=platform,
        appium_server_url=appium_server_url,
        capabilities_file=capabilities_file,
    )

    mcp_output_dir = run_dir_path / "appium-mcp-output"
    mcp_output_dir.mkdir(parents=True, exist_ok=True)
    config.screenshots_dir = str(mcp_output_dir)
    run_mcp_config_path = run_dir_path / ".mcp.json"
    run_mcp_config_path.write_text(json.dumps(build_appium_mcp_config(config), indent=2))
    logger.info(f"Created Appium MCP config for mobile run {run_id}")

    copy_claude_project_config(BASE_DIR / ".claude", run_dir_path / ".claude")

    cmd = [
        sys.executable,
        "orchestrator/cli.py",
        spec_path,
        "--run-dir",
        run_dir,
        "--target",
        "mobile",
        "--platform",
        platform,
    ]
    if appium_server_url:
        cmd.extend(["--appium-server-url", appium_server_url])
    if capabilities_file:
        cmd.extend(["--capabilities-file", capabilities_file])

    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(run_dir_path)
    env["APPIUM_SCREENSHOTS_DIR"] = str(mcp_output_dir)
    if appium_server_url:
        env["APPIUM_SERVER_URL"] = appium_server_url
    if capabilities_file:
        env["APPIUM_CAPABILITIES_CONFIG"] = capabilities_file
    if project_id:
        env["PROJECT_ID"] = project_id
        env["MEMORY_PROJECT_ID"] = project_id

    with Session(engine) as session:
        run = session.get(DBTestRun, run_id)
        if run and run.status in ("stopped", "cancelled"):
            logger.info(f"Mobile run {run_id} was {run.status} before process spawn. Aborting.")
            return

    log_file = run_dir_path / "execution.log"
    with open(log_file, "w") as f:
        process = subprocess.Popen(
            cmd,
            cwd=BASE_DIR,
            stdout=f,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )

        try:
            pgid = os.getpgid(process.pid)
        except (ProcessLookupError, OSError):
            pgid = process.pid

        register_process(run_id, process)
        if PROCESS_MANAGER:
            PROCESS_MANAGER.register(run_id=run_id, pid=process.pid, pgid=pgid, spec_name=spec_name, batch_id=batch_id)

        logger.info(f"Started mobile process for {run_id}: pid={process.pid}, pgid={pgid}")
        try:
            process.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            logger.warning(f"Mobile process for {run_id} timed out after 1800s")
            import signal as _signal

            try:
                os.killpg(os.getpgid(process.pid), _signal.SIGKILL)
            except (ProcessLookupError, OSError):
                try:
                    process.kill()
                except (ProcessLookupError, OSError):
                    pass
            process.wait(timeout=10)
        finally:
            unregister_process(run_id)
            if PROCESS_MANAGER:
                PROCESS_MANAGER.unregister(run_id)
            logger.info(f"Mobile process completed for {run_id}: exit_code={process.returncode}")


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
    try:
        with Session(engine) as session:
            run = session.get(DBTestRun, run_id)
            if run:
                if run.status in ("stopped", "cancelled"):
                    return
                run.status = "running"
                run.started_at = datetime.utcnow()
                run.queue_position = None
                session.add(run)
                session.commit()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            execute_mobile_run_task,
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

        with Session(engine) as session:
            run = session.get(DBTestRun, run_id)
            if run:
                run_dir_path = Path(run_dir)
                status_file = run_dir_path / "status.txt"
                if status_file.exists():
                    file_status = status_file.read_text().strip()
                    if file_status:
                        run.status = file_status

                plan_file = run_dir_path / "plan.json"
                if plan_file.exists():
                    try:
                        plan_data = json.loads(plan_file.read_text())
                        run.test_name = plan_data.get("testName") or run.test_name
                        run.total_steps = len(plan_data.get("steps", []))
                    except json.JSONDecodeError:
                        pass

                error_file = run_dir_path / "pipeline_error.json"
                if error_file.exists():
                    try:
                        error_data = json.loads(error_file.read_text())
                        if error_data.get("error"):
                            error_msg = str(error_data["error"])[:500]
                            stage = str(error_data.get("stage", "") or "")
                            if stage == "test_data_resolution":
                                run.stage_message = f"{stage}: {error_msg}"
                            if not run.error_message:
                                run.error_message = f"[{stage}] {error_msg}" if stage else error_msg
                    except json.JSONDecodeError:
                        pass

                if run.status in ("running", "queued"):
                    run.status = "error"
                    run.error_message = run.error_message or "Mobile process exited without writing status."
                    try:
                        status_file.write_text("error")
                    except Exception:
                        pass

                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()

        if batch_id:
            update_batch_stats(batch_id)

    except asyncio.CancelledError:
        with Session(engine) as session:
            run = session.get(DBTestRun, run_id)
            if run and run.status not in ("stopped", "cancelled", "passed", "failed", "error", "completed"):
                run.status = "cancelled"
                run.queue_position = None
                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()
        Path(run_dir, "status.txt").write_text("cancelled")
        raise
    except Exception as e:
        logger.error(f"Mobile run {run_id} failed with exception: {e}", exc_info=True)
        with Session(engine) as session:
            run = session.get(DBTestRun, run_id)
            if run:
                run.status = "error"
                run.error_message = str(e)[:500]
                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()
        Path(run_dir, "status.txt").write_text("error")
        if batch_id:
            update_batch_stats(batch_id)


async def _start_test_run_temporal_or_fail(
    run: DBTestRun,
    payload: dict[str, Any],
    session: Session,
    *,
    task_queue: str | None = None,
) -> None:
    from orchestrator.config import settings as app_settings
    from orchestrator.services.temporal_client import TemporalUnavailableError, start_test_run_workflow

    selected_task_queue = task_queue or app_settings.temporal_browser_workflow_task_queue
    try:
        temporal = await start_test_run_workflow(run.id, payload, task_queue=selected_task_queue)
    except TemporalUnavailableError as exc:
        run.status = "error"
        run.queue_position = None
        run.completed_at = datetime.utcnow()
        run.error_message = f"Failed to start Temporal workflow: {exc}"
        run.stage_message = str(exc)
        session.add(run)
        session.commit()
        run_dir = RUNS_DIR / run.id
        if run_dir.exists():
            (run_dir / "status.txt").write_text("error")
        if run.batch_id:
            update_batch_stats(run.batch_id)
        raise HTTPException(status_code=503, detail=f"Temporal is required for test runs: {exc}") from exc

    run.temporal_workflow_id = temporal.workflow_id
    run.temporal_run_id = temporal.run_id
    session.add(run)
    session.commit()


async def _signal_test_run_temporal(run: DBTestRun, signal_name: str, *args) -> None:
    if not run.temporal_workflow_id:
        return
    from orchestrator.services.temporal_client import TemporalUnavailableError, signal_test_run_workflow

    try:
        await signal_test_run_workflow(run.temporal_workflow_id, signal_name, *args)
    except TemporalUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"Temporal is unavailable for test run control: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to signal test run workflow: {exc}") from exc


def _has_browser_auth_selection(
    *,
    browser_auth_session_id: str | None,
    use_project_default_browser_auth: bool,
) -> bool:
    return bool((browser_auth_session_id or "").strip() or use_project_default_browser_auth)


def _validate_browser_auth_selection_for_project(
    session: Session,
    project_id: str | None,
    *,
    browser_auth_session_id: str | None,
    use_project_default_browser_auth: bool,
) -> None:
    browser_auth_session_id = (browser_auth_session_id or "").strip() or None
    if not _has_browser_auth_selection(
        browser_auth_session_id=browser_auth_session_id,
        use_project_default_browser_auth=use_project_default_browser_auth,
    ):
        return
    if not project_id:
        raise HTTPException(status_code=400, detail="Browser auth session selection requires a project")
    try:
        row = resolve_browser_auth_session_row(
            session,
            project_id,
            browser_auth_session_id=browser_auth_session_id,
            use_default=use_project_default_browser_auth,
        )
        if not row:
            raise BrowserAuthSessionError("Project default browser auth session was not found")
        ensure_browser_auth_session_usable(row)
    except BrowserAuthSessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _resolve_browser_auth_storage_state_for_run(
    session: Session,
    project_id: str | None,
    *,
    run_dir: Path,
    browser_auth_session_id: str | None,
    use_project_default_browser_auth: bool,
) -> tuple[str | None, dict[str, Any]]:
    browser_auth_session_id = (browser_auth_session_id or "").strip() or None
    intent: dict[str, Any] = {
        "mode": "project_default" if use_project_default_browser_auth else ("session" if browser_auth_session_id else "none"),
        "requested_browser_auth_session_id": browser_auth_session_id,
        "browser_auth_session_id": None,
        "browser_auth_session_name": None,
        "use_project_default_browser_auth": bool(use_project_default_browser_auth),
        "project_default_used": False,
        "storage_state_attached": False,
    }
    if not _has_browser_auth_selection(
        browser_auth_session_id=browser_auth_session_id,
        use_project_default_browser_auth=use_project_default_browser_auth,
    ):
        return None, intent
    try:
        resolved = resolve_browser_auth_for_run(
            session,
            project_id,
            run_dir=run_dir,
            browser_auth_session_id=browser_auth_session_id,
            use_default=use_project_default_browser_auth,
        )
    except BrowserAuthSessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not resolved:
        return None, intent
    intent.update(
        {
            "browser_auth_session_id": resolved.session_id,
            "browser_auth_session_name": resolved.session_name,
            "project_default_used": bool(use_project_default_browser_auth),
            "storage_state_attached": True,
        }
    )
    return str(resolved.storage_state_path), intent


def _normalize_request_test_data_refs(refs: list[str] | None) -> list[str]:
    from orchestrator.services.test_data_resolver import extract_test_data_refs_from_sources

    return extract_test_data_refs_from_sources(refs=refs or [])


# ========= Agents =========


class AgentRunRequest(BaseModel):
    agent_type: str  # "exploratory", "writer", or "spec-synthesis"
    config: dict[str, Any]
    project_id: str | None = None  # Project isolation
    runtime: str | None = None
    model_tier: str | None = None
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False


class AgentDefinitionRequest(BaseModel):
    name: str
    description: str = ""
    system_prompt: str
    runtime: str | None = None
    model: str | None = None
    model_tier: str | None = None
    timeout_seconds: int = 1800
    tool_ids: list[str] = []
    test_data_refs: list[str] = []
    project_id: str | None = None


class AgentDefinitionUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    runtime: str | None = None
    model: str | None = None
    model_tier: str | None = None
    timeout_seconds: int | None = None
    tool_ids: list[str] | None = None
    test_data_refs: list[str] | None = None
    status: str | None = None


class CustomAgentRunRequest(BaseModel):
    prompt: str
    url: str | None = None
    config: dict[str, Any] | None = None
    test_data_refs: list[str] = []
    project_id: str | None = None
    runtime: str | None = None
    model_tier: str | None = None
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False


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


class ExploratoryRunRequest(BaseModel):
    """Enhanced exploratory testing request."""

    url: str
    time_limit_minutes: int = 15
    instructions: str = ""
    auth: dict[str, Any] | None = None  # {"type": "credentials|session|none", ...}
    test_data: dict[str, Any] | None = None
    test_data_refs: list[str] | None = None
    focus_areas: list[str] | None = None
    excluded_patterns: list[str] | None = None
    project_id: str | None = None  # Project to associate generated specs with
    runtime: str | None = None
    model_tier: str | None = "tool_deep"
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False
    advanced_tools: bool = False
    record_video: bool = False


class SpecSynthesisRequest(BaseModel):
    """Spec synthesis request."""

    exploration_run_id: str  # Run ID of exploration to synthesize


class FlowUpdateRequest(BaseModel):
    """Partial update request for a discovered flow."""

    title: str | None = None
    pages: list[str] | None = None
    happy_path: str | None = None
    edge_cases: list[str] | None = None
    test_ideas: list[str] | None = None
    entry_point: str | None = None
    exit_point: str | None = None
    complexity: str | None = None


class GenerateReportItemSpecRequest(BaseModel):
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False
    skip_browser_auth: bool = False
    inherit_browser_auth: bool = False


class ImportReportRequirementsRequest(BaseModel):
    item_ids: list[str] | None = None
    import_all: bool = False


class UpdateAgentReportItemRequest(BaseModel):
    patch: dict[str, Any]


class UpdateAgentReportOverviewRequest(BaseModel):
    summary: str | None = None
    scope: str | None = None


class GenerateFlowTestRequest(BaseModel):
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False
    skip_browser_auth: bool = False
    inherit_browser_auth: bool = True


def _collect_agent_run_artifacts(run_id: str) -> list[dict[str, Any]]:
    """Return browser recording/screenshot artifacts for an agent run."""
    try:
        return jsonable_encoder(exploration._collect_exploration_artifacts(run_id))
    except Exception as exc:
        logger.debug("Failed to collect artifacts for agent run %s: %s", run_id, exc)
        return []


def _read_run_text_artifact(run_id: str, name: str, max_chars: int | None = None) -> str:
    path = RUNS_DIR / run_id / name
    if not path.exists() or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.debug("Failed to read %s for agent run %s: %s", name, run_id, exc)
        return ""
    return text if max_chars is None else text[:max_chars]


def _read_run_json_artifact(run_id: str, name: str) -> Any:
    text = _read_run_text_artifact(run_id, name)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception as exc:
        logger.debug("Failed to parse %s for agent run %s: %s", name, run_id, exc)
        return None


def _run_artifact_counts(run_id: str, artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    artifacts = list(artifacts if artifacts is not None else _collect_agent_run_artifacts(run_id))
    run_dir = RUNS_DIR / run_id
    raw_output = _read_run_text_artifact(run_id, "raw_output.txt")
    tool_calls = _read_run_json_artifact(run_id, "tool_calls.json")
    return {
        "artifact_count": len(artifacts),
        "screenshot_count": len([item for item in artifacts if str(item.get("type") or "") == "image"]),
        "log_count": len([item for item in artifacts if str(item.get("type") or "") == "log"]),
        "raw_output_chars": len(raw_output),
        "tool_call_count": len(tool_calls) if isinstance(tool_calls, list) else 0,
        "storage_state_reused": (run_dir / "browser-auth-storage-state.json").exists(),
    }


def _jsonl_latest_url(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None
    for line in reversed(lines[-500:]):
        try:
            event = json.loads(line)
        except Exception:
            match = re.search(r"https?://[^\s\"'<>),]+", line)
            if match:
                return match.group(0)
            continue
        if isinstance(event, dict):
            for key in ("url", "last_url", "target"):
                value = event.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return value
    return None


def _latest_observed_url_for_run(run: AgentRun) -> str | None:
    progress = run.progress or {}
    for key in ("last_observed_url", "current_url", "last_url", "url"):
        value = progress.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value

    run_dir = RUNS_DIR / run.id
    candidates = [
        run_dir / "exploration_events.jsonl",
        run_dir / "browser-memory-observations.jsonl",
        run_dir / "agent_summary.json",
        run_dir / "tool_calls.json",
        run_dir / "raw_output.txt",
    ]
    existing = [path for path in candidates if path.exists()]
    for path in sorted(existing, key=lambda item: item.stat().st_mtime, reverse=True):
        if path.suffix == ".jsonl":
            url = _jsonl_latest_url(path)
            if url:
                return url
        else:
            text = _read_run_text_artifact(run.id, path.name, max_chars=250_000)
            matches = re.findall(r"https?://[^\s\"'<>),]+", text)
            if matches:
                return matches[-1]
    value = (run.config or {}).get("url")
    return value if isinstance(value, str) and value.startswith(("http://", "https://")) else None


def _recover_custom_agent_partial_result(run: AgentRun, error: Exception | str) -> dict[str, Any] | None:
    artifacts = _collect_agent_run_artifacts(run.id)
    raw_output = _read_run_text_artifact(run.id, "raw_output.txt")
    tool_calls = _read_run_json_artifact(run.id, "tool_calls.json")
    tool_calls = tool_calls if isinstance(tool_calls, list) else []
    counts = _run_artifact_counts(run.id, artifacts)
    if not raw_output.strip() and not artifacts and not tool_calls:
        return None

    def fallback_recovery() -> dict[str, Any]:
        structured = _build_custom_agent_structured_report(raw_output, run.config, artifacts)
        warnings = [
            "Structured JSON was not returned; a minimal report was synthesized from available evidence.",
            f"Custom agent recovered partial evidence after runtime failure: {error}",
        ]
        return {
            "summary": structured.get("summary") or _clean_text(raw_output, 500),
            "output": raw_output,
            "structured_report": structured,
            "error": str(error),
            "partial_results": True,
            "failure_reason": "runtime_failed_after_evidence",
            "contract_status": "partial",
            "repair_attempts": [
                {
                    "attempt": 1,
                    "strategy": "synthesize_minimal_report_from_evidence",
                    "status": "success",
                }
            ],
            "contract_warnings": warnings,
            "diagnostics": {
                "finalizer": {
                    "agent_type": "custom",
                    "source": "runtime_failure_recovery_fallback",
                    "recovered_after_error": True,
                    "error": str(error),
                    **counts,
                }
            },
        }

    try:
        from orchestrator.services.agent_run_finalizer import AgentRunFinalizer

        finalized = AgentRunFinalizer().finalize(
            run_id=run.id,
            agent_type="custom",
            config=run.config,
            raw_model_output=raw_output,
            tool_calls=tool_calls,
            runtime_diagnostics={
                "source": "runtime_failure_recovery",
                "recovered_after_error": True,
                "error": str(error),
                **counts,
            },
            artifacts=artifacts,
            existing_result=run.result if isinstance(run.result, dict) else None,
        )
    except Exception as exc:
        logger.debug("Failed to recover custom agent partial result for %s: %s", run.id, exc)
        return fallback_recovery()

    if finalized.status == "failed":
        return fallback_recovery()
    recovered = dict(finalized.result)
    recovered["error"] = str(error)
    recovered["partial_results"] = True
    recovered["failure_reason"] = "runtime_failed_after_evidence"
    recovered.setdefault("contract_warnings", [])
    if isinstance(recovered["contract_warnings"], list):
        warning = f"Custom agent recovered partial evidence after runtime failure: {error}"
        if warning not in recovered["contract_warnings"]:
            recovered["contract_warnings"].append(warning)
    return recovered


def _agent_run_summary(run: AgentRun) -> str | None:
    result = run.result or {}
    structured = result.get("structured_report") if isinstance(result, dict) else None
    if isinstance(structured, dict) and structured.get("summary"):
        return structured.get("summary")
    return result.get("summary") if isinstance(result, dict) else None


def _exploratory_result_is_zero_evidence_failure(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    action_trace = result.get("action_trace") if isinstance(result.get("action_trace"), list) else []
    flows = result.get("discovered_flows") if isinstance(result.get("discovered_flows"), list) else []
    flow_summaries = (
        result.get("discovered_flow_summaries")
        if isinstance(result.get("discovered_flow_summaries"), list)
        else []
    )
    try:
        total_flows = int(result.get("total_flows_discovered") or 0)
    except (TypeError, ValueError):
        total_flows = 0
    return bool(
        result.get("failure_reason") in {"zero_evidence_parse_fallback", "zero_evidence"}
        or (
            result.get("parsing_failed")
            and not action_trace
            and not flows
            and not flow_summaries
            and total_flows == 0
        )
    )


def _exploratory_result_is_terminal_failure(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("failure_reason") == "runtime_auth_failed":
        return True
    return _exploratory_result_is_zero_evidence_failure(result)


def _exploratory_result_has_usable_evidence(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    action_trace = result.get("action_trace") if isinstance(result.get("action_trace"), list) else []
    flow_summaries = (
        result.get("discovered_flow_summaries")
        if isinstance(result.get("discovered_flow_summaries"), list)
        else []
    )
    pages = result.get("pages_visited") if isinstance(result.get("pages_visited"), list) else []
    screenshots = result.get("screenshots") if isinstance(result.get("screenshots"), list) else []
    diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {}
    event_count = _coerce_progress_int(diagnostics.get("evidence_event_count"), 0)
    successful_browser_actions = _coerce_progress_int(diagnostics.get("successful_browser_tool_calls"), 0)
    return bool(action_trace or flow_summaries or pages or screenshots or event_count > 0 or successful_browser_actions > 0)


def _merge_agent_failure_into_result(result: Any, error: Exception | str, *, failure_reason: str) -> dict[str, Any]:
    merged = dict(result) if isinstance(result, dict) else {}
    error_text = str(error)
    diagnostics = dict(merged.get("diagnostics") or {})
    diagnostics["runtime_error"] = error_text
    merged["diagnostics"] = diagnostics
    merged["error"] = error_text
    merged.setdefault("failure_reason", failure_reason)
    merged["partial_results"] = True
    merged["exploration_status"] = merged.get("exploration_status") or "completed_partial"
    warnings = list(merged.get("contract_warnings") or [])
    warning = f"Explorer recovered partial evidence after runtime failure: {error_text}"
    if warning not in warnings:
        warnings.append(warning)
    merged["contract_warnings"] = warnings
    merged.setdefault("contract_warning", warning)
    merged.setdefault("summary", "Exploration recovered partial evidence after the agent runtime failed.")
    return merged


def _recover_exploratory_partial_result(run_id: str, config: dict[str, Any], error: Exception | str) -> dict[str, Any] | None:
    try:
        from orchestrator.agents.exploratory_agent import ExplorationState, ExploratoryAgent

        run_dir = RUNS_DIR / run_id
        runtime_tool_calls: list[Any] = []
        tool_calls_path = run_dir / "tool_calls.json"
        if tool_calls_path.exists():
            try:
                loaded_calls = json.loads(tool_calls_path.read_text(encoding="utf-8"))
                if isinstance(loaded_calls, list):
                    runtime_tool_calls = loaded_calls
            except Exception as exc:
                logger.debug("Failed to read tool call recovery artifact for %s: %s", run_id, exc)
        processor = ExploratoryAgent()
        processor.state = ExplorationState(start_time=time_module.time())
        result = processor._process_results(
            "",
            {
                **config,
                "run_id": run_id,
                "_runtime_tool_calls": runtime_tool_calls,
                "_runtime_diagnostics": {
                    "runtime": normalize_agent_runtime(config.get("runtime")),
                    "recovered_after_error": True,
                    "error": str(error),
                },
            },
        )
        if _exploratory_result_has_usable_evidence(result):
            return _merge_agent_failure_into_result(
                result,
                error,
                failure_reason="runtime_failed_after_evidence",
            )
    except Exception as exc:
        logger.debug("Failed to recover exploratory partial result for %s: %s", run_id, exc)
    return None


def _filter_agent_run_project(run: AgentRun, project_id: str | None) -> None:
    if not project_id:
        return
    if run.project_id:
        if project_id == "default":
            if run.project_id not in (None, "default"):
                raise HTTPException(status_code=404, detail="Run not found")
        elif run.project_id != project_id:
            raise HTTPException(status_code=404, detail="Run not found")


def _agent_report_project_filter(project_id: str):
    if project_id == "default":
        return or_(AgentRun.project_id == None, AgentRun.project_id == "default")
    return or_(AgentRun.project_id == None, AgentRun.project_id == project_id)


def _get_agent_report_run(session: Session, run_id: str, project_id: str) -> AgentRun:
    run = session.exec(
        select(AgentRun).where(
            AgentRun.id == run_id,
            _agent_report_project_filter(project_id),
        )
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


AGENT_PARTIAL_STATUS = "completed_partial"
AGENT_TERMINAL_STATUSES = {"completed", AGENT_PARTIAL_STATUS, "failed", "cancelled", "timeout"}
AGENT_ACTIVE_STATUSES = {"queued", "pending", "running", "in_progress", "waiting", "paused"}


def _coerce_progress_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_agent_run_progress(progress: dict[str, Any] | None) -> dict[str, Any]:
    """Keep live agent progress compatible across direct, queue, and event paths."""
    normalized = dict(progress or {})
    for key in ("tool_calls", "browser_tool_calls", "interactions"):
        if key in normalized:
            normalized[key] = _coerce_progress_int(normalized.get(key))

    last_tool = normalized.get("last_tool") or normalized.get("current_tool")
    if last_tool:
        normalized["last_tool"] = str(last_tool)
        normalized["current_tool"] = str(last_tool)

    label = normalized.get("last_tool_label") or normalized.get("current_tool_label")
    if not label and last_tool:
        label = _short_tool_name(str(last_tool))
    if label:
        normalized["last_tool_label"] = str(label)
        normalized["current_tool_label"] = str(label)

    return normalized


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
    try:
        from orchestrator.services.agent_run_events import create_agent_run_event

        create_agent_run_event(
            run_id=run_id,
            agent_task_id=agent_task_id,
            event_type=event_type,
            level=level,
            message=message,
            payload=payload or {},
            session=session,
        )
    except Exception as exc:
        logger.debug("Failed to record agent run event for %s: %s", run_id, exc)


async def _start_agent_run_temporal_or_fail(run: AgentRun, session: Session, *, workflow_attempt: int | None = None) -> None:
    from orchestrator.config import settings as app_settings
    from orchestrator.services.temporal_client import (
        TemporalUnavailableError,
        describe_temporal_task_queue,
        start_agent_run_workflow,
    )

    task_queue = app_settings.temporal_workflow_task_queue
    if _agent_run_has_browser_tools(run.agent_type, run.config) and browser_live_worker_enabled():
        task_queue = app_settings.temporal_browser_workflow_task_queue

    task_queue_status: dict[str, Any] = {}
    try:
        task_queue_status = await describe_temporal_task_queue(task_queue)
    except Exception as exc:
        task_queue_status = {"status": "unknown", "error": str(exc)}

    try:
        if workflow_attempt:
            temporal = await start_agent_run_workflow(run.id, task_queue=task_queue, attempt=workflow_attempt)
        else:
            temporal = await start_agent_run_workflow(run.id, task_queue=task_queue)
    except TemporalUnavailableError as exc:
        run.status = "failed"
        run.completed_at = datetime.utcnow()
        run.result = {"error": f"Failed to start Temporal workflow: {exc}"}
        run.progress = {
            **(run.progress or {}),
            "phase": "failed",
            "status": "failed",
            "message": str(exc),
            "updated_at": datetime.utcnow().isoformat(),
        }
        session.add(run)
        session.commit()
        _record_agent_run_event(
            run.id,
            event_type="temporal_start_failed",
            level="error",
            message=f"Failed to start Temporal workflow: {exc}",
            payload={"temporal_error": str(exc)},
            session=session,
        )
        raise HTTPException(status_code=503, detail=f"Temporal is required for agent runs: {exc}") from exc

    run.temporal_workflow_id = temporal.workflow_id
    run.temporal_run_id = temporal.run_id
    session.add(run)
    session.commit()
    _record_agent_run_event(
        run.id,
        event_type="temporal_scheduled",
        message="Agent Temporal workflow scheduled.",
        payload={
            "workflow_id": temporal.workflow_id,
            "temporal_run_id": temporal.run_id,
            "attempt": workflow_attempt,
            "task_queue": task_queue,
            "task_queue_status": task_queue_status,
        },
        session=session,
    )


async def _agent_run_temporal_payload(run: AgentRun) -> dict[str, Any]:
    from orchestrator.config import settings as app_settings
    from orchestrator.services.temporal_client import TemporalUnavailableError, get_agent_run_temporal_diagnostics

    workflow_url = None
    if app_settings.temporal_ui_url and run.temporal_workflow_id:
        workflow_url = (
            f"{app_settings.temporal_ui_url.rstrip('/')}/namespaces/"
            f"{app_settings.temporal_namespace}/workflows/{run.temporal_workflow_id}"
        )
    payload: dict[str, Any] = {
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
        "temporal_ui_url": app_settings.temporal_ui_url,
        "temporal_ui_workflow_url": workflow_url,
        "temporal_namespace": app_settings.temporal_namespace,
        "task_queue": app_settings.temporal_workflow_task_queue,
        "workflow_type": "AgentRunWorkflow",
        "available": False,
        "workflow_status": None,
        "activities": [],
        "summary": {"total_activities": 0, "failed_activities": 0, "retry_count": 0, "last_failure": None},
        "error": None,
    }
    if not run.temporal_workflow_id:
        payload["error"] = "No Temporal workflow id recorded for this agent run."
        return payload
    try:
        return {**payload, **await get_agent_run_temporal_diagnostics(run.temporal_workflow_id, run.temporal_run_id)}
    except TemporalUnavailableError as exc:
        payload["error"] = str(exc)
    except Exception as exc:
        payload["error"] = f"Temporal diagnostics unavailable: {exc}"
    return payload


async def _signal_agent_run_temporal(run: AgentRun, signal_name: str, *args) -> None:
    if not run.temporal_workflow_id:
        return
    from orchestrator.services.temporal_client import TemporalUnavailableError, signal_agent_run_workflow

    try:
        await signal_agent_run_workflow(run.temporal_workflow_id, signal_name, *args)
    except TemporalUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"Temporal is unavailable for agent control: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to signal agent workflow: {exc}") from exc


async def _cancel_agent_run_queue_task(run: AgentRun) -> dict[str, Any] | None:
    """Cancel and finalize the Redis task linked to an already-cancelled agent run."""
    if not run.agent_task_id:
        return None

    result: dict[str, Any] = {"agent_task_id": run.agent_task_id, "status": "not_active"}
    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE, get_agent_queue, should_use_agent_queue

        if not REDIS_AVAILABLE or not should_use_agent_queue():
            return result

        queue = get_agent_queue()
        await queue.connect()
        before = await queue.get_task(str(run.agent_task_id))
        cancelled = await queue.cancel_task(str(run.agent_task_id))
        after = await queue.get_task(str(run.agent_task_id))
        result.update(
            {
                "status": after.status.value if after else "missing",
                "cancel_requested": bool(cancelled),
                "previous_status": before.status.value if before else None,
                "cleanup": await queue.cleanup_orphaned_and_stale_tasks(),
            }
        )
    except Exception as exc:
        logger.warning("Failed to cancel agent queue task %s for run %s: %s", run.agent_task_id, run.id, exc)
        result.update({"status": "error", "error": str(exc)})
    return result


async def _wait_if_agent_run_paused(run_id: str, poll_interval: float = 0.5) -> bool:
    """Block background execution while the user-visible run is paused.

    Returns False if the run became terminal or disappeared while waiting.
    """
    while True:
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            if not run or run.status in AGENT_TERMINAL_STATUSES:
                return False
            if run.status != "paused":
                return True
        await asyncio.sleep(poll_interval)


def _mark_agent_run_paused(run: AgentRun, message: str = "Agent is paused") -> None:
    previous_status = run.status if run.status != "paused" else (run.progress or {}).get("paused_from")
    run.status = "paused"
    run.progress = {
        **(run.progress or {}),
        "phase": "paused",
        "status": "paused",
        "paused_from": previous_status if previous_status in AGENT_ACTIVE_STATUSES else "queued",
        "message": message,
        "updated_at": datetime.utcnow().isoformat(),
    }


def _mark_agent_run_cancelled(run: AgentRun, message: str = "Agent cancelled") -> None:
    previous_status = run.status
    run.status = "cancelled"
    run.progress = {
        **(run.progress or {}),
        "phase": "cancelled",
        "status": "cancelled",
        "cancelled_from": previous_status if previous_status in AGENT_ACTIVE_STATUSES else None,
        "message": message,
        "updated_at": datetime.utcnow().isoformat(),
    }


def _agent_run_health(run: AgentRun, session: Session | None = None) -> dict[str, Any]:
    if session is None:
        with Session(engine) as scoped_session:
            return _agent_run_health(run, scoped_session)

    latest_event = session.exec(
        select(AgentRunEvent).where(AgentRunEvent.run_id == run.id).order_by(AgentRunEvent.sequence.desc()).limit(1)
    ).first()
    event_count = session.exec(select(func.count(AgentRunEvent.id)).where(AgentRunEvent.run_id == run.id)).one()
    tool_count = session.exec(
        select(func.count(AgentRunEvent.id)).where(
            AgentRunEvent.run_id == run.id,
            AgentRunEvent.event_type.in_(["tool_call", "browser_action"]),
        )
    ).one()
    error_count = session.exec(
        select(func.count(AgentRunEvent.id)).where(
            AgentRunEvent.run_id == run.id,
            AgentRunEvent.level.in_(["error", "critical"]),
        )
    ).one()

    progress = run.progress or {}
    latest_event_response = None
    if latest_event:
        from orchestrator.services.agent_run_events import event_to_response

        latest_event_response = event_to_response(latest_event)

    return {
        "event_count": int(event_count or 0),
        "tool_event_count": int(tool_count or 0),
        "error_event_count": int(error_count or 0),
        "latest_event": latest_event_response,
        "latest_heartbeat_at": progress.get("updated_at"),
        "agent_task_id": run.agent_task_id,
        "terminal": run.status in AGENT_TERMINAL_STATUSES,
        "terminal_reason": (latest_event.message if latest_event and run.status in AGENT_TERMINAL_STATUSES else None),
    }


def _serialize_agent_run(run: AgentRun, session: Session | None = None) -> dict[str, Any]:
    progress = run.progress or {}
    if _agent_run_has_browser_tools(run.agent_type, run.config):
        progress = {**browser_runtime_status(), **progress}
    progress = _normalize_agent_run_progress(progress)
    payload = {
        "id": run.id,
        "agent_type": run.agent_type,
        "runtime": getattr(run, "runtime", "claude_sdk") or "claude_sdk",
        "status": run.status,
        "created_at": run.created_at.isoformat(),
        "config": run.config,
        "result": run.result,
        "project_id": run.project_id,
        "progress": progress,
        "agent_task_id": run.agent_task_id,
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "artifacts": _collect_agent_run_artifacts(run.id) if run.agent_type in ("exploratory", "custom", "spec_generation") else [],
    }
    payload["health"] = _agent_run_health(run, session)
    return payload


def _safe_json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _compact_agent_run_config(config: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "url",
        "agent_name",
        "flow_title",
        "prompt",
        "instructions",
        "runtime",
        "timeout_seconds",
        "browser_auth_session_id",
        "retry_of",
        "source_run_id",
    }
    compact: dict[str, Any] = {}
    for key in keys:
        value = config.get(key)
        if value is not None and value != "":
            compact[key] = value
    selected_tools = config.get("selected_tools")
    if isinstance(selected_tools, list):
        compact["selected_tools"] = selected_tools[:12]
    return compact


def _compact_agent_run_summary(progress: dict[str, Any]) -> str | None:
    for key in ("summary", "message", "phase"):
        value = progress.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
    return None


def _encode_agent_run_cursor(created_at: datetime, run_id: str) -> str:
    payload = json.dumps({"created_at": created_at.isoformat(), "id": run_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_agent_run_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        created_at = datetime.fromisoformat(str(payload["created_at"]).replace("Z", "+00:00"))
        if created_at.tzinfo is not None:
            created_at = created_at.replace(tzinfo=None)
        return created_at, str(payload["id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


def _agent_run_project_filters(project_id: str | None) -> list[Any]:
    if not project_id:
        return []
    if project_id == "default":
        return [or_(AgentRun.project_id == project_id, AgentRun.project_id == None)]
    return [AgentRun.project_id == project_id]


def _agent_run_search_filter(q: str | None) -> Any | None:
    needle = (q or "").strip().lower()
    if not needle:
        return None
    pattern = f"%{needle}%"
    return or_(
        func.lower(AgentRun.id).like(pattern),
        func.lower(AgentRun.agent_type).like(pattern),
        func.lower(AgentRun.status).like(pattern),
        func.lower(AgentRun.config_json).like(pattern),
        func.lower(AgentRun.progress_json).like(pattern),
    )


def _agent_run_status_filter(status: str | None) -> Any | None:
    normalized = (status or "").strip().lower()
    if not normalized or normalized == "all":
        return None
    if normalized == "active":
        return AgentRun.status.in_(AGENT_ACTIVE_STATUSES)
    if normalized == "completed":
        return AgentRun.status.in_({"completed", AGENT_PARTIAL_STATUS})
    if normalized == "cancelled":
        return AgentRun.status.in_({"cancelled", "canceled"})
    return AgentRun.status == normalized


def _agent_run_type_filter(agent_type: str | None) -> Any | None:
    normalized = (agent_type or "").strip()
    if not normalized or normalized == "all":
        return None
    return AgentRun.agent_type == normalized


def _agent_run_history_filters(
    *,
    project_id: str | None,
    status: str | None = None,
    agent_type: str | None = None,
    q: str | None = None,
) -> list[Any]:
    filters = _agent_run_project_filters(project_id)
    for item in (
        _agent_run_status_filter(status),
        _agent_run_type_filter(agent_type),
        _agent_run_search_filter(q),
    ):
        if item is not None:
            filters.append(item)
    return filters


def _agent_run_history_counts(session: Session, *, project_id: str | None, q: str | None) -> dict[str, Any]:
    base_filters = _agent_run_history_filters(project_id=project_id, q=q)
    status_counts = {status: int(count or 0) for status, count in session.exec(
        select(AgentRun.status, func.count(AgentRun.id)).where(*base_filters).group_by(AgentRun.status)
    ).all()}
    type_counts = {agent_type: int(count or 0) for agent_type, count in session.exec(
        select(AgentRun.agent_type, func.count(AgentRun.id)).where(*base_filters).group_by(AgentRun.agent_type)
    ).all()}
    total = sum(status_counts.values())
    completed = status_counts.get("completed", 0) + status_counts.get(AGENT_PARTIAL_STATUS, 0)
    active = sum(status_counts.get(status, 0) for status in AGENT_ACTIVE_STATUSES)
    cancelled = status_counts.get("cancelled", 0) + status_counts.get("canceled", 0)
    return {
        "status": {
            "all": total,
            "active": active,
            "completed": completed,
            "failed": status_counts.get("failed", 0),
            "cancelled": cancelled,
            "paused": status_counts.get("paused", 0),
        },
        "type": {
            "all": total,
            "exploratory": type_counts.get("exploratory", 0),
            "custom": type_counts.get("custom", 0),
            "writer": type_counts.get("writer", 0),
            "spec_generation": type_counts.get("spec_generation", 0),
        },
    }


def _serialize_agent_run_summary_row(row: Any) -> dict[str, Any]:
    (
        run_id,
        agent_type,
        runtime,
        status,
        created_at,
        started_at,
        completed_at,
        project_id,
        config_json,
        progress_json,
    ) = row
    config = _compact_agent_run_config(_safe_json_dict(config_json))
    progress = _normalize_agent_run_progress(_safe_json_dict(progress_json))
    return {
        "id": run_id,
        "agent_type": agent_type,
        "runtime": runtime or "claude_sdk",
        "status": status,
        "created_at": created_at.isoformat(),
        "started_at": started_at.isoformat() if started_at else None,
        "completed_at": completed_at.isoformat() if completed_at else None,
        "project_id": project_id,
        "config": config,
        "progress": progress,
        "summary": _compact_agent_run_summary(progress),
    }


async def _live_agent_queue_progress(run: AgentRun) -> dict[str, Any]:
    if not run.agent_task_id or run.status in AGENT_TERMINAL_STATUSES:
        return {}
    try:
        from orchestrator.services.agent_queue import get_agent_queue

        queue = get_agent_queue()
        await queue.connect()
        progress = await queue.get_task_progress(str(run.agent_task_id))
        return progress if isinstance(progress, dict) else {}
    except Exception as exc:
        logger.debug("Failed to read live queue progress for agent run %s: %s", run.id, exc)
        return {}


async def _serialize_agent_run_live(run: AgentRun, session: Session | None = None) -> dict[str, Any]:
    payload = _serialize_agent_run(run, session)
    live_progress = await _live_agent_queue_progress(run)
    if live_progress:
        payload["progress"] = _normalize_agent_run_progress(
            {
                **(payload.get("progress") or {}),
                **live_progress,
            }
        )
    return payload


def _report_confidence(value: str | None) -> float:
    normalized = str(value or "").lower()
    if normalized == "high":
        return 0.86
    if normalized == "low":
        return 0.58
    return 0.72


def _report_importance(value: str | None) -> float:
    normalized = str(value or "").lower()
    if normalized == "critical":
        return 0.95
    if normalized == "high":
        return 0.84
    if normalized == "low":
        return 0.54
    if normalized == "info":
        return 0.42
    return 0.7


def _report_requirement_confidence(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(float(value), 1.0))
    normalized = _clean_text(value, 20).lower()
    if normalized == "high":
        return 0.86
    if normalized == "low":
        return 0.58
    if normalized == "medium":
        return 0.72
    try:
        return max(0.0, min(float(normalized), 1.0))
    except (TypeError, ValueError):
        return 0.7


def _report_requirement_acceptance_criteria(item: dict[str, Any]) -> list[str]:
    criteria = [
        _clean_text(criterion, 500)
        for criterion in _as_report_list(item.get("acceptance_criteria") or item.get("criteria"))
        if _clean_text(criterion, 500)
    ]
    if not criteria:
        expected = _clean_text(item.get("expected") or item.get("expected_result"), 500)
        if expected:
            criteria.append(expected)
    if not criteria and item.get("evidence"):
        criteria.append(f"Evidence reviewed: {_clean_text(item.get('evidence'), 450)}")
    return criteria[:10]


def _requirement_create_body_from_report_item(item: dict[str, Any]) -> dict[str, Any]:
    priority = _clean_text(item.get("priority") or item.get("severity") or "medium", 20).lower()
    if priority not in {"critical", "high", "medium", "low"}:
        priority = "medium"
    description_parts = [
        _clean_text(item.get("description") or item.get("summary"), 2000),
        f"Page: {_clean_text(item.get('page') or item.get('url'), 500)}" if item.get("page") or item.get("url") else "",
        f"Evidence: {_clean_text(item.get('evidence'), 1200)}" if item.get("evidence") else "",
    ]
    description = " ".join(part for part in description_parts if part).strip() or None
    return {
        "title": _clean_text(item.get("title") or item.get("name") or item.get("requirement"), 180),
        "description": description,
        "category": _clean_text(item.get("category") or "functional", 80).lower() or "functional",
        "priority": priority,
        "acceptance_criteria": _report_requirement_acceptance_criteria(item),
        "truth_state": "candidate_requirement",
        "source_type": "custom_agent_run",
        "confidence": _report_requirement_confidence(item.get("confidence")),
        "uncertainty_reason": "Imported from a custom agent report; agent-derived requirement requires human review.",
    }


REPORT_ITEM_COLLECTIONS = {
    "finding": "findings",
    "test_idea": "test_ideas",
    "requirement": "requirements",
}

REPORT_ITEM_EDITABLE_FIELDS = {
    "finding": {"title", "severity", "page", "description", "evidence", "suggested_action", "confidence"},
    "test_idea": {"title", "priority", "page", "steps", "expected", "source_finding_id"},
    "requirement": {
        "title",
        "description",
        "category",
        "priority",
        "acceptance_criteria",
        "page",
        "evidence",
        "confidence",
    },
}

REPORT_ITEM_LIST_FIELDS = {"steps", "acceptance_criteria"}
REPORT_ITEM_PROTECTED_FIELDS = {"id", "imported_requirement_id", "imported_requirement_code", "imported_at"}


def _normalize_report_item_type(item_type: str | None) -> str:
    normalized = (item_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "findings": "finding",
        "test": "test_idea",
        "test_ideas": "test_idea",
        "tests": "test_idea",
        "requirement": "requirement",
        "requirements": "requirement",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in REPORT_ITEM_COLLECTIONS:
        raise HTTPException(status_code=400, detail="item_type must be finding, test_idea, or requirement")
    return normalized


def _stored_custom_agent_report(run: AgentRun) -> tuple[dict[str, Any], dict[str, Any]]:
    if run.agent_type != "custom":
        raise HTTPException(status_code=400, detail="Only custom agent reports can be edited")
    result = run.result or {}
    report = result.get("structured_report") if isinstance(result, dict) else None
    if not isinstance(report, dict):
        raise HTTPException(status_code=400, detail="This run does not have a stored structured report")
    return result, report


def _normalize_report_patch_value(field: str, value: Any) -> Any:
    if field in REPORT_ITEM_LIST_FIELDS:
        return [_clean_text(item, 1000) for item in _as_report_list(value) if _clean_text(item, 1000)]
    if value is None:
        return None
    if field == "confidence" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    max_length = 2000 if field in {"description", "evidence", "suggested_action", "expected"} else 500
    if field in {"title"}:
        max_length = 220
    if field in {"severity", "priority", "category", "source_finding_id"}:
        max_length = 80
    return _clean_text(value, max_length)


def _editable_report_item_patch(item_type: str, patch: dict[str, Any]) -> dict[str, Any]:
    allowed = REPORT_ITEM_EDITABLE_FIELDS[item_type]
    blocked = sorted(field for field in patch if field not in allowed or field in REPORT_ITEM_PROTECTED_FIELDS)
    if blocked:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Report item patch contains uneditable fields",
                "fields": blocked,
                "allowed_fields": sorted(allowed),
            },
        )
    return {
        field: _normalize_report_patch_value(field, value)
        for field, value in patch.items()
    }


def _find_report_item(report: dict[str, Any], item_type: str, item_id: str) -> dict[str, Any]:
    collection = REPORT_ITEM_COLLECTIONS[item_type]
    for item in _as_report_list(report.get(collection)):
        if isinstance(item, dict) and str(item.get("id") or "") == item_id:
            return item
    raise HTTPException(status_code=404, detail=f"Report {item_type} item {item_id} not found")


def _capture_custom_agent_report_memory(
    *,
    run_id: str,
    project_id: str | None,
    structured_report: dict[str, Any],
    config: dict[str, Any],
) -> list[str]:
    """Store review-gated memories from a custom agent's normalized report."""
    if not project_id or not isinstance(structured_report, dict):
        return []

    try:
        from orchestrator.memory.agent_memory import get_agent_memory_service
    except Exception as exc:
        logger.debug("Custom agent memory capture unavailable for %s: %s", run_id, exc)
        return []

    service = get_agent_memory_service()
    stored_ids: list[str] = []
    agent_name = _clean_text(config.get("agent_name") or "Custom agent", 120)
    source_type = "custom_agent_run"

    def store(
        *,
        kind: str,
        content: str,
        summary: str,
        tags: list[str],
        confidence: float,
        importance: float,
        extra_data: dict[str, Any],
    ) -> None:
        try:
            memory = service.create_memory(
                kind=kind,
                content=content,
                project_id=project_id,
                summary=summary,
                tags=["custom-agent", *tags],
                confidence=confidence,
                importance=importance,
                source_type=source_type,
                source_id=run_id,
                agent_type="CustomAgent",
                review_required=True,
                extra_data={"agent_run_id": run_id, "agent_name": agent_name, **extra_data},
            )
            if memory and memory.id not in stored_ids:
                stored_ids.append(memory.id)
        except Exception as exc:
            logger.debug("Skipped custom agent memory candidate for %s: %s", run_id, exc)

    summary = _clean_text(structured_report.get("summary"), 500)
    scope = _clean_text(structured_report.get("scope") or config.get("prompt") or config.get("url"), 500)
    if summary:
        store(
            kind="project_fact",
            content=f"{agent_name} summary: {summary}" + (f" Scope: {scope}" if scope else ""),
            summary=f"{agent_name}: {summary}",
            tags=["summary"],
            confidence=0.68,
            importance=0.5,
            extra_data={"report_section": "summary"},
        )

    findings = _as_report_list(structured_report.get("findings"))[:5]
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        title = _clean_text(finding.get("title"), 180)
        if not title:
            continue
        severity = _clean_text(finding.get("severity") or "medium", 30).lower()
        page = _clean_text(finding.get("page"), 300)
        description = _clean_text(finding.get("description"), 600)
        evidence = _clean_text(finding.get("evidence"), 500)
        suggested_action = _clean_text(finding.get("suggested_action"), 400)
        content = (
            f"Custom agent finding: {title}. "
            f"Severity: {severity}. "
            f"{f'Page: {page}. ' if page else ''}"
            f"{f'Description: {description}. ' if description else ''}"
            f"{f'Evidence: {evidence}. ' if evidence else ''}"
            f"{f'Suggested action: {suggested_action}.' if suggested_action else ''}"
        )
        store(
            kind="project_fact" if severity == "info" else "failure_pattern",
            content=content,
            summary=f"{title} ({severity})",
            tags=["finding", severity],
            confidence=_report_confidence(str(finding.get("confidence") or "")),
            importance=_report_importance(severity),
            extra_data={"report_section": "findings", "finding_id": finding.get("id")},
        )

    test_ideas = _as_report_list(structured_report.get("test_ideas"))[:5]
    for idea in test_ideas:
        if not isinstance(idea, dict):
            continue
        title = _clean_text(idea.get("title"), 180)
        if not title:
            continue
        priority = _clean_text(idea.get("priority") or "medium", 30).lower()
        page = _clean_text(idea.get("page"), 300)
        steps = [_clean_text(step, 220) for step in _as_report_list(idea.get("steps")) if _clean_text(step, 220)]
        expected = _clean_text(idea.get("expected"), 400)
        steps_text = "; ".join(steps[:5])
        content = (
            f"Custom agent test idea: {title}. "
            f"Priority: {priority}. "
            f"{f'Page: {page}. ' if page else ''}"
            f"{f'Steps: {steps_text}. ' if steps_text else ''}"
            f"{f'Expected: {expected}.' if expected else ''}"
        )
        store(
            kind="workflow_decision",
            content=content,
            summary=f"Test idea: {title}",
            tags=["test-idea", priority],
            confidence=0.72,
            importance=_report_importance(priority),
            extra_data={"report_section": "test_ideas", "test_idea_id": idea.get("id")},
        )

    return stored_ids


def _sync_agent_tool_catalog(session: Session) -> list[AgentToolDefinition]:
    """Upsert the built-in selectable tool catalog."""
    now = datetime.utcnow()
    for item in AGENT_TOOL_CATALOG:
        tool = session.get(AgentToolDefinition, item["id"])
        if not tool:
            tool = AgentToolDefinition(id=item["id"], tool_name=item["tool_name"])
        tool.label = item["label"]
        tool.description = item["description"]
        tool.category = item["category"]
        tool.tool_name = item["tool_name"]
        tool.risk = item["risk"]
        tool.enabled = True
        tool.requires_mcp_server = item.get("requires_mcp_server")
        tool.updated_at = now
        session.add(tool)
    session.commit()
    return session.exec(
        select(AgentToolDefinition)
        .where(AgentToolDefinition.enabled == True)
        .order_by(AgentToolDefinition.category, AgentToolDefinition.label)
    ).all()


def _serialize_agent_tool(tool: AgentToolDefinition) -> dict[str, Any]:
    return {
        "id": tool.id,
        "label": tool.label,
        "description": tool.description,
        "category": tool.category,
        "tool_name": tool.tool_name,
        "risk": tool.risk,
        "enabled": tool.enabled,
        "requires_mcp_server": tool.requires_mcp_server,
    }


AGENT_RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "destructive": 3}


def _serialize_agent_definition(
    definition: AgentDefinition,
    tools_by_id: dict[str, AgentToolDefinition] | None = None,
) -> dict[str, Any]:
    selected_tools: list[dict[str, Any]] = []
    if tools_by_id is not None:
        selected_tools = [
            _serialize_agent_tool(tools_by_id[tool_id])
            for tool_id in definition.tool_ids
            if tool_id in tools_by_id
        ]
    risk_level = "low"
    if selected_tools:
        risk_level = max(
            (str(tool.get("risk") or "low") for tool in selected_tools),
            key=lambda risk: AGENT_RISK_ORDER.get(risk, 0),
        )
    return {
        "id": definition.id,
        "project_id": definition.project_id,
        "name": definition.name,
        "description": definition.description,
        "system_prompt": definition.system_prompt,
        "runtime": getattr(definition, "runtime", "claude_sdk") or "claude_sdk",
        "model": definition.model,
        "model_tier": getattr(definition, "model_tier", None),
        "timeout_seconds": definition.timeout_seconds,
        "tool_ids": definition.tool_ids,
        "test_data_refs": getattr(definition, "test_data_refs", []),
        "tools": selected_tools,
        "risk_level": risk_level,
        "status": definition.status,
        "created_at": definition.created_at.isoformat(),
        "updated_at": definition.updated_at.isoformat(),
    }


def _get_agent_definition_or_404(definition_id: str, project_id: str | None, session: Session) -> AgentDefinition:
    definition = session.get(AgentDefinition, definition_id)
    if not definition or definition.status == "archived":
        raise HTTPException(status_code=404, detail="Agent definition not found")
    if project_id:
        if project_id == "default":
            if definition.project_id not in (None, "default"):
                raise HTTPException(status_code=404, detail="Agent definition not found")
        elif definition.project_id != project_id:
            raise HTTPException(status_code=404, detail="Agent definition not found")
    return definition


async def _ensure_agent_write_access(project_id: str | None, current_user: Any, session: Session) -> None:
    if project_id:
        await check_project_access(project_id, current_user, [ProjectRole.ADMIN, ProjectRole.EDITOR], session)


def _resolve_agent_tools(tool_ids: list[str], session: Session) -> tuple[list[str], list[dict[str, Any]]]:
    _sync_agent_tool_catalog(session)
    if not tool_ids:
        raise HTTPException(status_code=400, detail="Select at least one tool for this agent")

    tools: list[AgentToolDefinition] = []
    unknown: list[str] = []
    for tool_id in tool_ids:
        tool = session.get(AgentToolDefinition, tool_id)
        if not tool or not tool.enabled:
            unknown.append(tool_id)
        else:
            tools.append(tool)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown or disabled tools: {', '.join(unknown)}")

    allowed_tools = sorted({tool.tool_name for tool in tools})
    return allowed_tools, [_serialize_agent_tool(tool) for tool in tools]


def _browser_auth_selection(config: dict[str, Any]) -> tuple[str | None, bool]:
    auth_config = config.get("browser_auth") if isinstance(config.get("browser_auth"), dict) else {}
    legacy_auth = config.get("auth") if isinstance(config.get("auth"), dict) else {}
    browser_auth_session_id = (
        config.get("browser_auth_session_id")
        or auth_config.get("session_id")
        or legacy_auth.get("browser_auth_session_id")
        or legacy_auth.get("session_id")
    )
    use_default = bool(
        config.get("use_project_default_browser_auth")
        or auth_config.get("use_project_default")
        or auth_config.get("use_project_default_browser_auth")
        or legacy_auth.get("use_default")
        or legacy_auth.get("use_project_default")
        or legacy_auth.get("use_project_default_browser_auth")
    )
    return browser_auth_session_id, use_default


class AgentBrowserAuthResolutionError(RuntimeError):
    def __init__(self, message: str, *, browser_auth_session_id: str | None, use_default: bool):
        super().__init__(message)
        self.browser_auth_session_id = browser_auth_session_id
        self.use_default = use_default


def _browser_auth_request_fields_set(request: Any) -> set[str]:
    fields = getattr(request, "model_fields_set", None)
    if fields is None:
        fields = getattr(request, "__fields_set__", set())
    return set(fields or set())


def _without_spec_generation_auth(config: dict[str, Any]) -> dict[str, Any]:
    cleaned = {
        key: value
        for key, value in config.items()
        if key not in {"auth", "browser_auth", "browser_auth_session_id", "use_project_default_browser_auth"}
    }
    return cleaned


def _apply_report_spec_browser_auth_request(
    inherited_config: dict[str, Any],
    request: GenerateReportItemSpecRequest | None,
) -> tuple[dict[str, Any], bool]:
    if request is None:
        return inherited_config, True

    fields_set = _browser_auth_request_fields_set(request)
    browser_auth_session_id = str(request.browser_auth_session_id or "").strip()
    if request.skip_browser_auth:
        return _without_spec_generation_auth(inherited_config), False
    if browser_auth_session_id:
        return {**_without_spec_generation_auth(inherited_config), "browser_auth_session_id": browser_auth_session_id}, False
    if request.use_project_default_browser_auth:
        return {**_without_spec_generation_auth(inherited_config), "use_project_default_browser_auth": True}, False
    if request.inherit_browser_auth or not fields_set:
        return inherited_config, True
    return _without_spec_generation_auth(inherited_config), False


def _resolve_agent_browser_auth_storage_path(
    *,
    run_id: str,
    project_id: str | None,
    config: dict[str, Any],
    run_dir: Path,
) -> Path | None:
    browser_auth_session_id, use_default = _browser_auth_selection(config)
    if not (browser_auth_session_id or use_default):
        return None
    try:
        with Session(engine) as db_session:
            resolved = resolve_browser_auth_for_run(
                db_session,
                project_id,
                run_dir=run_dir,
                browser_auth_session_id=browser_auth_session_id,
                use_default=use_default,
            )
    except BrowserAuthSessionError as exc:
        message = f"{exc}. Refresh browser auth session."
        _update_agent_run_progress(
            run_id,
            {
                "phase": "failed",
                "status": "failed",
                "message": message,
            },
        )
        raise AgentBrowserAuthResolutionError(
            message,
            browser_auth_session_id=browser_auth_session_id,
            use_default=use_default,
        ) from exc
    if resolved:
        _update_agent_run_progress(
            run_id,
            {
                "browser_auth_session_id": resolved.session_id,
                "browser_auth_session_name": resolved.session_name,
                "message": "Using project browser auth session.",
            },
        )
    return resolved.storage_state_path if resolved else None


def _prepare_custom_agent_mcp_config(run_id: str, storage_state_path: Path | str | None = None) -> Path:
    """Create run-local Playwright MCP config for UI-created custom agents."""
    run_dir = RUNS_DIR / run_id
    runtime = write_playwright_mcp_config(
        run_dir=run_dir,
        server_name="playwright-test",
        project_root=BASE_DIR,
        storage_state_path=storage_state_path,
    )
    _update_agent_run_progress(run_id, runtime)
    return run_dir


def _prepare_spec_generation_mcp_config(
    run_dir: Path,
    storage_state_path: Path | str | None = None,
) -> dict[str, Any]:
    """Create run-local Playwright MCP config for browser-backed spec generation."""
    return write_playwright_mcp_config(
        run_dir=run_dir,
        server_name="playwright-test",
        project_root=BASE_DIR,
        storage_state_path=storage_state_path,
    )


def _safe_inherited_auth_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    safe_keys = {
        "browser_auth_session_id",
        "session_id",
        "session_name",
        "use_default",
        "use_project_default",
        "use_project_default_browser_auth",
    }
    return {key: value[key] for key in safe_keys if key in value and value[key] is not None}


def _build_spec_generation_source_config(
    source_config: dict[str, Any],
    *,
    target_url: str,
    project_id: str | None,
) -> dict[str, Any]:
    """Carry only non-secret context needed by browser-backed spec generation."""
    inherited: dict[str, Any] = {
        "url": str(source_config.get("url") or target_url or "").strip(),
    }
    if project_id:
        inherited["project_id"] = project_id
    elif source_config.get("project_id"):
        inherited["project_id"] = source_config.get("project_id")

    if source_config.get("browser_auth_session_id"):
        inherited["browser_auth_session_id"] = source_config.get("browser_auth_session_id")
    if source_config.get("use_project_default_browser_auth"):
        inherited["use_project_default_browser_auth"] = True

    auth_config = _safe_inherited_auth_config(source_config.get("auth"))
    if auth_config:
        inherited["auth"] = auth_config
    browser_auth_config = _safe_inherited_auth_config(source_config.get("browser_auth"))
    if browser_auth_config:
        inherited["browser_auth"] = browser_auth_config
    return inherited


def _spec_generation_auth_metadata(config: dict[str, Any], *, inherited: bool = True) -> dict[str, Any]:
    browser_auth_session_id, use_default = _browser_auth_selection(config)
    metadata: dict[str, Any] = {}
    if browser_auth_session_id:
        metadata["browser_auth_session_id"] = browser_auth_session_id
    if use_default:
        metadata["use_project_default_browser_auth"] = True
    if metadata and inherited:
        metadata["browser_auth_inherited"] = True
    return metadata


def _resolve_playwright_chromium_executable() -> Path | None:
    """Find a Chromium executable already installed in the backend image."""
    return resolve_playwright_chromium_executable()


def _playwright_chromium_probe_script(executable_path: str | None = None) -> str:
    """Return a Node probe that launches and closes the installed Chromium."""
    executable_option = (
        f", executablePath: {json.dumps(executable_path)}"
        if executable_path
        else ""
    )
    return f"""
const {{ chromium }} = require('playwright');
const headless = String(process.env.HEADLESS || 'true').toLowerCase() !== 'false';
(async () => {{
  const browser = await chromium.launch({{ headless{executable_option.strip()} }});
  await browser.close();
}})().catch((error) => {{
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
}});
"""


def _probe_custom_agent_browser(timeout_seconds: int = 30) -> tuple[bool, str]:
    """Check whether the installed Playwright Chromium can launch without installing it."""
    env = os.environ.copy()
    env.setdefault("PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT", "300000")
    executable_path = _resolve_playwright_chromium_executable()
    try:
        result = subprocess.run(
            ["node", "-e", _playwright_chromium_probe_script(str(executable_path) if executable_path else None)],
            cwd=str(BASE_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(
            str(value)
            for value in (getattr(exc, "stdout", None), getattr(exc, "stderr", None))
            if value
        ).strip()
        return False, output or f"Timed out after {timeout_seconds}s launching Playwright Chromium"

    combined_output = f"{result.stdout}\n{result.stderr}".strip()
    return result.returncode == 0, combined_output


async def _probe_custom_agent_browser_with_slot(run_id: str, timeout_seconds: int = 30) -> tuple[bool, str]:
    async def _run_probe() -> tuple[bool, str]:
        loop = asyncio.get_running_loop()
        if timeout_seconds == 30:
            return await loop.run_in_executor(None, _probe_custom_agent_browser)
        return await loop.run_in_executor(None, _probe_custom_agent_browser, timeout_seconds)

    try:
        pool = BROWSER_POOL or await get_browser_pool()
        if await pool.is_running(run_id):
            return await _run_probe()
    except Exception as exc:
        logger.debug("Could not verify existing agent browser slot for %s: %s", run_id, exc)

    async with browser_operation_slot(
        request_id=f"agent-probe:{run_id}",
        operation_type=BrowserOpType.AGENT,
        description=f"Custom agent browser readiness probe {run_id}",
        timeout=timeout_seconds,
        max_operation_duration=timeout_seconds + 15,
    ):
        return await _run_probe()


def _custom_agent_uses_browser_tools(allowed_tools: list[Any]) -> bool:
    """Return whether selected custom-agent tools require Playwright Chromium."""
    return any(str(tool).startswith("mcp__playwright") for tool in allowed_tools)


def _custom_agent_browser_runs_via_queue() -> bool:
    """Return whether browser execution will be delegated to an agent worker."""
    if browser_live_worker_enabled():
        return True
    try:
        from orchestrator.services.agent_queue import should_use_agent_queue

        return should_use_agent_queue()
    except Exception as exc:
        logger.debug("Could not determine custom agent queue mode: %s", exc)
        return False


def _agent_run_has_browser_tools(agent_type: str, config: dict[str, Any]) -> bool:
    """Return whether this agent run will need a Playwright browser."""
    if agent_type == "custom":
        return _custom_agent_uses_browser_tools(config.get("allowed_tools") or [])
    return agent_type in ("exploratory", "spec_generation")


async def _ensure_custom_agent_browser_available(run_id: str, *, force_direct_execution: bool = False) -> None:
    """Fail fast if the Playwright browser required by @playwright/mcp is unavailable."""
    if _custom_agent_browser_runs_via_queue() and not force_direct_execution:
        _update_agent_run_progress(
            run_id,
            {
                **browser_runtime_status(),
                "phase": "browser_delegated",
                "message": "Browser execution delegated to agent worker",
            },
        )
        return

    _update_agent_run_progress(
        run_id,
        {
            "phase": "browser_setup",
            "message": "Checking local Playwright browser availability",
        },
    )
    _update_agent_run_progress(run_id, browser_runtime_status())

    available, output = await _probe_custom_agent_browser_with_slot(run_id)
    if not available:
        _update_agent_run_progress(
            run_id,
            {
                "phase": "failed",
                "message": "Playwright Chromium is not installed or cannot launch in the local execution container",
                "browser_probe_output": output[-2000:],
            },
        )
        raise RuntimeError(
            "Playwright Chromium is not installed or cannot launch in the local execution container. "
            "Custom agent browser tools require Chromium to be present before a direct run starts. "
            "For `make start`, rebuild/recreate the backend image so Dockerfile's "
            "`npx playwright install chromium` step runs, or enable USE_AGENT_QUEUE=true "
            "to delegate browser execution to an agent worker. "
            f"Browser probe output: {output[-1000:]}"
        )

    _update_agent_run_progress(
        run_id,
        {
            "phase": "browser_ready",
            "message": "Local Playwright browser is ready",
        },
    )


@asynccontextmanager
async def _worker_managed_agent_browser_slot():
    """No-op slot context for queued agents that acquire browser slots in workers."""
    yield True


def _short_tool_name(tool_name: str | None) -> str:
    if not tool_name:
        return ""
    return str(tool_name).rsplit("__", 1)[-1] if "__" in str(tool_name) else str(tool_name)


def _update_agent_run_progress(run_id: str, patch: dict[str, Any]) -> None:
    """Persist live progress for custom agent runs."""
    try:
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            if not run:
                return
            existing = run.progress or {}
            recent_tools = list(existing.get("recent_tools") or [])
            progress_patch = dict(patch or {})
            last_tool = progress_patch.get("last_tool") or progress_patch.get("current_tool")
            if not last_tool:
                progress_patch.pop("last_tool", None)
                progress_patch.pop("current_tool", None)
                last_tool = existing.get("last_tool") or existing.get("current_tool")
            if last_tool and (not recent_tools or recent_tools[-1].get("name") != last_tool):
                recent_tools.append(
                    {
                        "name": str(last_tool),
                        "label": _short_tool_name(str(last_tool)),
                        "at": datetime.utcnow().isoformat(),
                    }
                )
                recent_tools = recent_tools[-12:]

            progress = {
                **existing,
                **progress_patch,
                "recent_tools": recent_tools,
                "updated_at": datetime.utcnow().isoformat(),
            }
            progress = _normalize_agent_run_progress(progress)
            run.progress = progress
            if progress_patch.get("agent_task_id"):
                run.agent_task_id = str(progress_patch["agent_task_id"])
            session.add(run)
            session.commit()
    except Exception as exc:
        logger.debug("Failed to update custom agent progress for %s: %s", run_id, exc)


def _generic_agent_runtime_prompt(agent_type: str, config: dict[str, Any]) -> str:
    """Build a Quorvex-owned prompt for non-Claude runtime adapters."""

    if agent_type == "exploratory":
        from orchestrator.agents.exploratory_agent import ExploratoryAgent

        agent = ExploratoryAgent()
        return agent._build_exploration_prompt(
            url=config.get("url"),
            instructions=config.get("instructions", ""),
            time_limit_minutes=int(config.get("time_limit_minutes") or 15),
            auth_config=config.get("auth") or {"type": "none"},
            test_data=config.get("test_data") or {},
            focus_areas=config.get("focus_areas") or [],
            excluded_patterns=config.get("excluded_patterns") or [],
            browser_memory_context=config.get("browser_memory_context") or "",
            advanced_tools=bool(config.get("advanced_tools") or config.get("record_video") or config.get("capture_video")),
        )
    if agent_type == "spec-synthesis":
        return "\n".join(
            [
                "You are a Quorvex test-spec synthesis agent.",
                "Use the supplied exploration result to draft production-ready test scenarios. Return JSON with summary and specs.",
                "Do not write repository files; propose content only.",
                f"Config JSON:\n{json.dumps(config, indent=2, default=str)}",
            ]
        )
    return "\n".join(
        [
            "You are a Quorvex QA automation agent.",
            "Complete the requested task and return a concise factual report.",
            f"Config JSON:\n{json.dumps(config, indent=2, default=str)}",
        ]
    )


KNOWN_AGENT_TYPE_TOOL_PROFILES = {
    "exploratory": "app-explorer-basic",
    "writer": "app-explorer-basic",
    "spec-synthesis": "text-analysis",
}


def _agent_tool_profile_for_run(agent_type: str, config: dict[str, Any]) -> str | None:
    configured = str(config.get("agent_tool_profile") or "").strip()
    if configured:
        return configured
    if agent_type == "exploratory" and bool(
        config.get("advanced_tools") or config.get("record_video") or config.get("capture_video")
    ):
        return "app-explorer-advanced"
    return KNOWN_AGENT_TYPE_TOOL_PROFILES.get(agent_type)


def _resolve_known_agent_allowed_tools(
    agent_type: str,
    config: dict[str, Any],
    *,
    mcp_config_dir: Path | str | None = None,
) -> list[str] | None:
    """Resolve explicit tools for known built-in agent types.

    Built-in agents must not inherit legacy wildcard access when callers omit
    allowed_tools. Unknown/custom agents keep their existing behavior elsewhere.
    """
    profile_name = _agent_tool_profile_for_run(agent_type, config)
    if not profile_name:
        return None
    config["agent_tool_profile"] = profile_name
    return get_agent_allowed_tools(profile_name, mcp_config_dir=mcp_config_dir)


def _resolve_agent_execution_test_data_context(
    *,
    project_id: str | None,
    refs: list[Any] | None = None,
    markdown: str | None = None,
) -> dict[str, Any]:
    try:
        from orchestrator.services.test_data_resolver import (
            resolve_test_data_execution_context,
        )

        with Session(engine) as session:
            return resolve_test_data_execution_context(
                session,
                project_id=project_id or "default",
                refs=[str(ref) for ref in (refs or [])],
                markdown=markdown or "",
            )
    except Exception as exc:
        logger.warning("Failed to resolve agent execution test data: %s", exc)
        return {}


async def execute_agent_background(run_id: str, agent_type: str, config: dict):
    """Execute an agent in the background with unified browser pool management.

    Uses BrowserResourcePool to limit concurrent browser operations across
    ALL operation types (test runs, explorations, agents, PRD).
    """
    from sqlmodel import Session

    # Block if a load test is running
    from orchestrator.services.load_test_lock import check_system_available

    from .db import engine
    from .models_db import AgentRun

    await check_system_available("agent run")

    try:
        runtime_name = normalize_agent_runtime(config.get("runtime"))
        if not await _wait_if_agent_run_paused(run_id):
            return
        from orchestrator.services.agent_cancellation import owner_is_cancelled_sync

        def _agent_run_cancelled() -> bool:
            return owner_is_cancelled_sync("agent_run", run_id)

        uses_worker_browser_slot = (
            _agent_run_has_browser_tools(agent_type, config)
            and not bool(config.get("_force_direct_agent_execution"))
            and _custom_agent_browser_runs_via_queue()
        )
        if uses_worker_browser_slot:
            slot_context = _worker_managed_agent_browser_slot()
        else:
            pool = BROWSER_POOL or await get_browser_pool()
            slot_context = pool.browser_slot(
                request_id=run_id,
                operation_type=BrowserOpType.AGENT,
                description=f"Agent: {agent_type}",
            )

        async with slot_context as acquired:
            if not acquired:
                # Timeout waiting for slot
                logger.warning(f"Agent {run_id} failed to acquire browser slot (timeout)")
                raise TimeoutError("Timeout waiting for browser slot")

            if not await _wait_if_agent_run_paused(run_id):
                return

            # Update status to "running" now that we have a slot
            with Session(engine) as session:
                run = session.get(AgentRun, run_id)
                if run and run.status == "queued":
                    runtime_name = normalize_agent_runtime(getattr(run, "runtime", None) or config.get("runtime"))
                    run.status = "running"
                    run.started_at = run.started_at or datetime.utcnow()
                    session.add(run)
                    session.commit()

            logger.info(f"Browser slot acquired for agent {run_id}")

            # Use relative imports since server runs from orchestrator/ directory
            from orchestrator.agents.exploratory_agent import ExploratoryAgent
            from orchestrator.agents.spec_synthesis_agent import SpecSynthesisAgent
            from orchestrator.agents.spec_writer_agent import SpecWriterAgent

            result = {}
            if agent_type == "exploratory":
                agent = ExploratoryAgent()
                agent.owner_type = "agent_run"
                agent.owner_id = run_id
                agent.owner_label = f"Agent run {run_id}"
                run_dir = RUNS_DIR / run_id
                storage_state_path = _resolve_agent_browser_auth_storage_path(
                    run_id=run_id,
                    project_id=config.get("project_id"),
                    config=config,
                    run_dir=run_dir,
                )
                run_dir = exploration._prepare_exploration_mcp_config(run_id, storage_state_path=storage_state_path)
                agent.agent_cwd = str(run_dir)
                resolved_allowed_tools = _resolve_known_agent_allowed_tools(
                    agent_type,
                    config,
                    mcp_config_dir=run_dir,
                )
                if resolved_allowed_tools is not None:
                    config["allowed_tools"] = resolved_allowed_tools
                agent.agent_tool_profile = config.get("agent_tool_profile") or "app-explorer-basic"
                agent.on_task_enqueued = lambda task_id: _update_agent_run_progress(
                    run_id,
                    {
                        "phase": "queued",
                        "message": "Agent task queued for worker",
                        "agent_task_id": task_id,
                    },
                )

                # Inject project_id from URL if not present
                if "project_id" not in config:
                    config["project_id"] = derive_project_id_from_url(config.get("url"))

                # Pass run_id to agent for file storage
                config["run_id"] = run_id
                test_data_refs = config.get("test_data_refs") if isinstance(config.get("test_data_refs"), list) else []
                if test_data_refs:
                    resolved_test_data = _resolve_agent_execution_test_data_context(
                        project_id=config.get("project_id"),
                        refs=test_data_refs,
                        markdown=json.dumps(config, default=str),
                    )
                    runtime_fixtures = resolved_test_data.get("runtime_fixtures") or {}
                    if runtime_fixtures:
                        merged_test_data = config.get("test_data") if isinstance(config.get("test_data"), dict) else {}
                        for ref, fixture in runtime_fixtures.items():
                            if not isinstance(fixture, dict):
                                continue
                            if fixture.get("data") is not None:
                                merged_test_data[ref] = fixture.get("data")
                            elif fixture.get("text"):
                                merged_test_data[ref] = fixture.get("text")
                        config["test_data"] = merged_test_data
                    if resolved_test_data.get("prompt_markdown"):
                        existing_context = str(config.get("browser_memory_context") or "").strip()
                        test_data_context = (
                            f"{resolved_test_data['prompt_markdown']}\n\n"
                            "If you delegate work to subagents, copy the relevant test-data ref names and plaintext values needed for execution "
                            "into each delegated prompt. Subagents do not automatically inherit this full parent context."
                        )
                        config["browser_memory_context"] = "\n\n".join(
                            part for part in [existing_context, test_data_context] if part
                        )
                if not await _wait_if_agent_run_paused(run_id):
                    return
                result = await agent.run(config)

                # Note: Persistence is now handled within ExploratoryAgent.run() -> _process_results()

                # Auto-analyze prerequisites after exploration completes
                try:
                    from pathlib import Path

                    from agents.prerequisites_agent import PrerequisitesAgent

                    logger.info(f"Auto-analyzing prerequisites for run {run_id}")

                    project_root = Path(__file__).parent.parent.parent
                    flows_file = project_root / "runs" / run_id / "flows.json"

                    if flows_file.exists():
                        with open(flows_file) as f:
                            flows_data = json.load(f)

                        flows = flows_data.get("flows", [])
                        if flows:
                            prereq_agent = PrerequisitesAgent()
                            prereq_result = await prereq_agent.run(
                                {
                                    "flows": flows,
                                    "action_trace": result.get("action_trace", []),
                                    "exploration_url": config.get("url", ""),
                                    "auth_config": config.get("auth", {}),
                                    "test_data": config.get("test_data", {}),
                                }
                            )

                            # Save enriched flows back to flows.json
                            enriched_flows = prereq_result.get("enriched_flows", flows)
                            with open(flows_file, "w") as f:
                                json.dump(
                                    {
                                        "flows": enriched_flows,
                                        "flow_graph": prereq_result.get("flow_graph", {}),
                                        "entities_discovered": prereq_result.get("entities_discovered", []),
                                        "prerequisites_analyzed_at": prereq_result.get("analyzed_at"),
                                    },
                                    f,
                                    indent=2,
                                )

                            # Add prerequisites summary to result
                            result["prerequisites_analysis"] = {
                                "summary": prereq_result.get("summary"),
                                "entities_discovered": prereq_result.get("entities_discovered", []),
                                "flow_graph": prereq_result.get("flow_graph", {}),
                            }
                            logger.info(f"Prerequisites analysis complete: {prereq_result.get('summary')}")
                        else:
                            logger.warning("No flows found to analyze")
                    else:
                        logger.debug(f"flows.json not found at {flows_file}")

                except Exception as prereq_error:
                    logger.warning(f"Prerequisites auto-analysis failed: {prereq_error}")
                    # Don't fail the whole run, just log the error
                    result["prerequisites_analysis"] = {"error": str(prereq_error)}

            elif agent_type == "writer":
                agent = SpecWriterAgent()
                agent.owner_type = "agent_run"
                agent.owner_id = run_id
                agent.owner_label = f"Agent run {run_id}"
                agent.agent_tool_profile = _agent_tool_profile_for_run(agent_type, config)
                result = await agent.run(config)
            elif agent_type == "spec-synthesis":
                agent = SpecSynthesisAgent()
                agent.owner_type = "agent_run"
                agent.owner_id = run_id
                agent.owner_label = f"Agent run {run_id}"
                agent.agent_tool_profile = _agent_tool_profile_for_run(agent_type, config)
                result = await agent.run(config)
            elif agent_type == "coding":
                from orchestrator.services.agent_runtimes import AgentRuntimeContext, get_agent_runtime
                from orchestrator.services.agent_trace import (
                    ensure_trace_snapshot,
                    record_tool_result_spans,
                    record_trace_span,
                )

                repo_root = DEFAULT_REPO_ROOT
                run_dir = RUNS_DIR / run_id
                run_dir.mkdir(parents=True, exist_ok=True)
                task_prompt = str(config.get("prompt") or config.get("task") or "").strip()
                if not task_prompt:
                    raise ValueError("Coding agent prompt is required")

                allowed_tools = coding_agent_allowed_tools()
                final_prompt = build_coding_agent_prompt(task_prompt, repo_root)
                trace_snapshot = ensure_trace_snapshot(
                    run_id=run_id,
                    prompt=final_prompt,
                    context=None,
                    runtime=runtime_name,
                    model=config.get("model"),
                    model_tier=config.get("model_tier") or "tool_deep",
                    allowed_tools=allowed_tools,
                    test_data_refs=[],
                    runtime_diagnostics={
                        "runtime": runtime_name,
                        "agent_type": "coding",
                        "repo_root": str(repo_root),
                        "mode": "propose_diff_only",
                    },
                )

                _update_agent_run_progress(
                    run_id,
                    {
                        "phase": "starting",
                        "message": "Starting coding agent in propose-diff-only mode",
                        "runtime": runtime_name,
                        "repo_root": str(repo_root),
                        "autonomy_mode": "propose_diff_only",
                    },
                )

                def _on_coding_tool_use(tool_name: str, tool_input: dict[str, Any]) -> None:
                    _update_agent_run_progress(
                        run_id,
                        {
                            "phase": "tool_use",
                            "message": f"Using {_short_tool_name(tool_name)}",
                            "runtime": runtime_name,
                            "last_tool": tool_name,
                            "last_tool_input": tool_input,
                            "autonomy_mode": "propose_diff_only",
                        },
                    )
                    _record_agent_run_event(
                        run_id,
                        event_type="tool_call",
                        message=f"Using {_short_tool_name(tool_name)}.",
                        payload={
                            "tool_name": tool_name,
                            "tool_label": _short_tool_name(tool_name),
                        },
                    )

                def _on_coding_progress(progress: dict[str, Any]) -> None:
                    last_tool = progress.get("last_tool")
                    record_trace_span(
                        run_id=run_id,
                        trace_id=trace_snapshot.id if trace_snapshot else None,
                        span_type="provider_event",
                        name=str(progress.get("phase") or "coding progress"),
                        message=str(progress.get("message") or "Coding agent runtime progress."),
                        tool_name=str(last_tool) if last_tool else None,
                        payload={"progress": progress, "runtime": runtime_name},
                    )
                    _update_agent_run_progress(
                        run_id,
                        {
                            **progress,
                            "runtime": runtime_name,
                            "phase": progress.get("phase") or "running",
                            "message": f"Using {_short_tool_name(str(last_tool))}" if last_tool else "Coding agent is running",
                            "autonomy_mode": "propose_diff_only",
                        },
                    )

                runtime_adapter = get_agent_runtime(runtime_name)
                runtime_context = AgentRuntimeContext(
                    timeout_seconds=int(config.get("timeout_seconds") or 1800),
                    allowed_tools=allowed_tools,
                    tools=allowed_tools,
                    permission_mode=str(config.get("permission_mode") or "plan"),
                    session_dir=run_dir,
                    on_tool_use=_on_coding_tool_use,
                    on_progress=_on_coding_progress,
                    cwd=repo_root,
                    owner_type="agent_run",
                    owner_id=run_id,
                    owner_label=f"Coding agent run {run_id}",
                    memory_project_id=config.get("project_id"),
                    memory_agent_type="CodingAgent",
                    memory_source_type="coding_agent_run",
                    memory_source_id=run_id,
                    memory_stage="coding_agent",
                    inject_memory=False,
                    capture_memory=False,
                    force_direct_execution=True,
                    model=config.get("model"),
                    model_tier=config.get("model_tier") or "tool_deep",
                    enable_file_checkpointing=True,
                    agents=coding_agent_subagents(),
                    tool_permission_guard=build_coding_tool_permission_guard(),
                    agent_name="CodingAgent",
                    metadata={
                        "agent_type": "coding",
                        "run_id": run_id,
                        "repo_root": str(repo_root),
                        "autonomy_mode": "propose_diff_only",
                    },
                    trace_id=trace_snapshot.id if trace_snapshot else None,
                    prompt_hash=trace_snapshot.prompt_hash if trace_snapshot else None,
                    agent_run_id=run_id,
                    is_cancelled=_agent_run_cancelled,
                )
                if not await _wait_if_agent_run_paused(run_id):
                    return
                agent_result = await runtime_adapter.run(final_prompt, runtime_context)
                if agent_result.cancelled:
                    raise asyncio.CancelledError("Agent run cancelled")
                record_tool_result_spans(run_id, agent_result.tool_calls)
                raw_output = agent_result.output or ""
                (run_dir / "raw_output.txt").write_text(raw_output, encoding="utf-8")
                artifact_info = write_coding_artifacts(run_dir, raw_output)
                patch_text = _read_run_text_artifact(run_id, CODING_ARTIFACT_PATCH)
                patch_valid = False
                patch_validation_error = None
                if patch_text:
                    try:
                        validate_patch_for_repo(patch_text, repo_root)
                        patch_valid = True
                    except Exception as validation_error:
                        patch_validation_error = str(validation_error)

                result = {
                    "summary": artifact_info.get("summary") or (raw_output[:500] if raw_output else agent_result.error),
                    "output": raw_output,
                    "review": artifact_info.get("review"),
                    "tests": artifact_info.get("tests"),
                    "affected_files": artifact_info.get("affected_files") or [],
                    "patch_artifact": artifact_info.get("patch_path"),
                    "patch_bytes": artifact_info.get("patch_bytes") or 0,
                    "patch_valid": patch_valid,
                    "patch_validation_error": patch_validation_error,
                    "autonomy_mode": "propose_diff_only",
                    "repo_root": str(repo_root),
                    "error": agent_result.error,
                    "duration_seconds": agent_result.duration_seconds,
                    "runtime": runtime_name,
                    "session_id": agent_result.session_id,
                    "total_cost_usd": agent_result.total_cost_usd,
                    "tool_calls": [
                        {
                            "name": call.name,
                            "timestamp": call.timestamp.isoformat(),
                            "duration_ms": call.duration_ms,
                            "success": call.success,
                            "error": call.error,
                            "input": call.input,
                        }
                        for call in agent_result.tool_calls
                    ],
                    "messages_received": agent_result.messages_received,
                    "text_blocks_received": agent_result.text_blocks_received,
                    "timed_out": agent_result.timed_out,
                }
                if not patch_valid:
                    result["partial_results"] = True
                if not agent_result.success:
                    raise RuntimeError(agent_result.error or "Coding agent failed")
                _update_agent_run_progress(
                    run_id,
                    {
                        "phase": "completed" if patch_valid else AGENT_PARTIAL_STATUS,
                        "status": "completed" if patch_valid else AGENT_PARTIAL_STATUS,
                        "message": "Coding agent proposed a patch" if patch_valid else "Coding agent completed without a valid patch",
                        "runtime": runtime_name,
                        "tool_calls": len(agent_result.tool_calls),
                        "interactions": len(agent_result.tool_calls),
                        "affected_files": artifact_info.get("affected_files") or [],
                        "patch_artifact": artifact_info.get("patch_path"),
                        "patch_valid": patch_valid,
                        "autonomy_mode": "propose_diff_only",
                    },
                )
            elif agent_type == "custom":
                from orchestrator.services.agent_runtimes import AgentRuntimeContext, get_agent_runtime
                from orchestrator.services.agent_trace import (
                    ensure_trace_snapshot,
                    record_tool_result_spans,
                    record_trace_span,
                )

                allowed_tools = config.get("allowed_tools") or []
                run_dir = None
                has_browser_tools = _custom_agent_uses_browser_tools(allowed_tools)
                has_screenshot_tool = any(str(tool).endswith("__browser_take_screenshot") for tool in allowed_tools)
                force_direct_execution = bool(config.get("_force_direct_agent_execution"))
                runtime = browser_runtime_status() if has_browser_tools else {}
                with Session(engine) as session:
                    custom_run = session.get(AgentRun, run_id)
                    custom_project_id = custom_run.project_id if custom_run else None
                if any(str(tool).startswith("mcp__") for tool in allowed_tools):
                    if has_browser_tools:
                        await _ensure_custom_agent_browser_available(
                            run_id,
                            force_direct_execution=force_direct_execution,
                        )
                    candidate_run_dir = RUNS_DIR / run_id
                    storage_state_path = _resolve_agent_browser_auth_storage_path(
                        run_id=run_id,
                        project_id=custom_project_id or config.get("project_id"),
                        config=config,
                        run_dir=candidate_run_dir,
                    )
                    run_dir = _prepare_custom_agent_mcp_config(run_id, storage_state_path=storage_state_path)
                    runtime = browser_runtime_status()

                _update_agent_run_progress(
                    run_id,
                    {
                        "phase": "starting",
                        "message": "Starting custom agent",
                        "tool_calls": 0,
                        "browser_tool_calls": 0,
                            "interactions": 0,
                            "has_browser_tools": has_browser_tools,
                            "force_direct_execution": force_direct_execution,
                            **runtime,
                        },
                    )

                task_prompt = config.get("prompt", "")
                target_url = config.get("url")
                custom_config = config.get("custom_config") or {}
                prompt_parts = [
                    config.get("system_prompt") or "You are a focused QA automation agent.",
                    "",
                    "Run this task using only the tools you have been granted.",
                    CUSTOM_AGENT_REPORT_INSTRUCTIONS,
                ]
                if has_screenshot_tool:
                    prompt_parts.append(
                        "While working in the browser, periodically call browser_take_screenshot with filenames "
                        "like live-step-001.png, live-step-002.png, etc. so the UI can show your current state."
                    )
                if target_url:
                    prompt_parts.append(f"Target URL: {target_url}")
                if custom_config:
                    prompt_parts.append(f"Additional config JSON:\n{json.dumps(custom_config, indent=2)}")
                retry_context = config.get("retry_context") if isinstance(config.get("retry_context"), dict) else {}
                if retry_context:
                    context_lines = [
                        "Retry continuation context:",
                        f"- This is retry attempt {retry_context.get('attempt')} for the same AgentRun id `{run_id}`.",
                        "- Resume from the saved browser auth/session artifacts and prior findings; do not restart discovery unless the saved page is unavailable.",
                    ]
                    if retry_context.get("last_observed_url"):
                        context_lines.append(f"- Last observed browser URL: {retry_context['last_observed_url']}")
                    if retry_context.get("raw_output_chars"):
                        context_lines.append(f"- Previous raw output artifact contains {retry_context['raw_output_chars']} characters.")
                    if retry_context.get("artifact_count"):
                        context_lines.append(
                            f"- Preserved artifacts: {retry_context['artifact_count']} total, "
                            f"{retry_context.get('screenshot_count', 0)} screenshots."
                        )
                    if retry_context.get("storage_state_reused"):
                        context_lines.append("- Browser auth storage state is available in the run directory.")
                    prompt_parts.append("\n".join(context_lines))
                test_data_refs = config.get("test_data_refs") if isinstance(config.get("test_data_refs"), list) else []
                resolved_test_data = _resolve_agent_execution_test_data_context(
                    project_id=custom_project_id or config.get("project_id"),
                    refs=test_data_refs,
                    markdown="\n".join(str(part) for part in [task_prompt, json.dumps(custom_config, default=str)]),
                )
                markdown = resolved_test_data.get("prompt_markdown")
                if markdown:
                    prompt_parts.extend(["", markdown])
                    prompt_parts.append(
                        "If you delegate work to subagents, copy the relevant test-data ref names and plaintext values needed for execution into each delegated prompt. Subagents do not automatically inherit this full parent context."
                    )
                prompt_parts.extend(["", "Task:", task_prompt])
                final_prompt = "\n".join(prompt_parts)
                trace_snapshot = ensure_trace_snapshot(
                    run_id=run_id,
                    prompt=final_prompt,
                    context=markdown,
                    runtime=runtime_name,
                    model=config.get("model"),
                    model_tier=config.get("model_tier") or "tool_deep",
                    allowed_tools=allowed_tools,
                    test_data_refs=test_data_refs,
                    runtime_diagnostics={
                        "runtime": runtime_name,
                        "agent_type": "custom",
                        "has_browser_tools": has_browser_tools,
                        "force_direct_execution": force_direct_execution,
                    },
                )

                def _on_custom_task_enqueued(task_id: str) -> None:
                    ensure_trace_snapshot(run_id=run_id, agent_task_id=task_id, runtime=runtime_name)
                    queued_message = "Agent task queued for worker"
                    runtime_metadata = runtime if has_browser_tools else {}
                    runtime_message = runtime_metadata.get(
                        "runtime_message",
                        "Browser execution is running in an agent worker. Screenshots are shown as fallback.",
                    )
                    _update_agent_run_progress(
                        run_id,
                        {
                            **runtime_metadata,
                            "phase": "queued",
                            "runtime": runtime_name,
                            "message": queued_message,
                            "agent_task_id": task_id,
                            "runtime_message": runtime_message,
                        },
                    )

                def _on_custom_tool_use(tool_name: str, tool_input: dict[str, Any]) -> None:
                    _update_agent_run_progress(
                        run_id,
                        {
                            "phase": "tool_use",
                            "message": f"Using {_short_tool_name(tool_name)}",
                            "runtime": runtime_name,
                            "last_tool": tool_name,
                            "last_tool_input": tool_input,
                            "has_browser_tools": has_browser_tools,
                            **runtime,
                        },
                    )
                    _record_agent_run_event(
                        run_id,
                        event_type="browser_action" if str(tool_name).startswith("mcp__playwright") else "tool_call",
                        message=f"Using {_short_tool_name(tool_name)}.",
                        payload={
                            "tool_name": tool_name,
                            "tool_label": _short_tool_name(tool_name),
                            "tool_input": tool_input,
                        },
                    )

                def _on_custom_progress(progress: dict[str, Any]) -> None:
                    last_tool = progress.get("last_tool")
                    record_trace_span(
                        run_id=run_id,
                        trace_id=trace_snapshot.id if trace_snapshot else None,
                        span_type="provider_event",
                        name=str(progress.get("phase") or "runtime progress"),
                        message=str(progress.get("message") or "Agent runtime progress."),
                        tool_name=str(last_tool) if last_tool else None,
                        payload={"progress": progress, "runtime": runtime_name},
                    )
                    _update_agent_run_progress(
                        run_id,
                        {
                            **progress,
                            "runtime": runtime_name,
                            "phase": progress.get("phase") or "running",
                            "message": f"Using {_short_tool_name(str(last_tool))}" if last_tool else "Agent is running",
                            "has_browser_tools": has_browser_tools,
                            **runtime,
                        },
                    )

                runtime_adapter = get_agent_runtime(runtime_name)
                runtime_context = AgentRuntimeContext(
                    timeout_seconds=int(config.get("timeout_seconds") or 1800),
                    allowed_tools=allowed_tools,
                    tools=allowed_tools,
                    session_dir=run_dir,
                    on_task_enqueued=_on_custom_task_enqueued,
                    on_tool_use=_on_custom_tool_use,
                    on_progress=_on_custom_progress,
                    cwd=run_dir,
                    owner_type="agent_run",
                    owner_id=run_id,
                    owner_label=f"Agent run {run_id}",
                    memory_project_id=custom_project_id,
                    memory_agent_type="CustomAgent",
                    memory_source_type="custom_agent_run",
                    memory_source_id=run_id,
                    memory_stage="custom_agent",
                    inject_memory=True,
                    capture_memory=False,
                    force_direct_execution=force_direct_execution,
                    model=config.get("model"),
                    model_tier=config.get("model_tier") or "tool_deep",
                    agent_name=config.get("agent_name") or "CustomAgent",
                    metadata={
                        "agent_type": "custom",
                        "agent_definition_id": config.get("agent_definition_id"),
                        "run_id": run_id,
                    },
                    trace_id=trace_snapshot.id if trace_snapshot else None,
                    prompt_hash=trace_snapshot.prompt_hash if trace_snapshot else None,
                    agent_run_id=run_id,
                    env_vars=None,
                    is_cancelled=_agent_run_cancelled,
                )
                if not await _wait_if_agent_run_paused(run_id):
                    return
                agent_result = await runtime_adapter.run(final_prompt, runtime_context)
                if agent_result.cancelled:
                    raise asyncio.CancelledError("Agent run cancelled")
                record_tool_result_spans(run_id, agent_result.tool_calls)
                artifacts = _collect_agent_run_artifacts(run_id)
                structured_report = _build_custom_agent_structured_report(
                    agent_result.output or "",
                    config,
                    artifacts,
                )
                captured_memory_ids = _capture_custom_agent_report_memory(
                    run_id=run_id,
                    project_id=custom_project_id,
                    structured_report=structured_report,
                    config=config,
                )
                result = {
                    "summary": structured_report.get("summary")
                    or (agent_result.output[:500] if agent_result.output else agent_result.error),
                    "output": agent_result.output,
                    "structured_report": structured_report,
                    "captured_memory_ids": captured_memory_ids,
                    "error": agent_result.error,
                    "duration_seconds": agent_result.duration_seconds,
                    "runtime": runtime_name,
                    "session_id": agent_result.session_id,
                    "total_cost_usd": agent_result.total_cost_usd,
                    "tool_calls": [
                        {
                            "name": call.name,
                            "timestamp": call.timestamp.isoformat(),
                            "duration_ms": call.duration_ms,
                            "success": call.success,
                            "error": call.error,
                            "input": call.input,
                        }
                        for call in agent_result.tool_calls
                    ],
                    "messages_received": agent_result.messages_received,
                    "text_blocks_received": agent_result.text_blocks_received,
                    "timed_out": agent_result.timed_out,
                }
                if not agent_result.success:
                    raise RuntimeError(agent_result.error or "Custom agent failed")
                _update_agent_run_progress(
                    run_id,
                    {
                        "phase": "completed",
                        "status": "completed",
                        "message": "Custom agent completed",
                        "runtime": runtime_name,
                        "tool_calls": len(agent_result.tool_calls),
                        "browser_tool_calls": len(
                            [call for call in agent_result.tool_calls if call.name.startswith("mcp__playwright")]
                        ),
                        "interactions": len(agent_result.tool_calls),
                    },
                )

            # Update DB success
            with Session(engine) as session:
                run = session.get(AgentRun, run_id)
                if run and run.status not in AGENT_TERMINAL_STATUSES:
                    finalized = None
                    if agent_type in {"custom", "exploratory"} and isinstance(result, dict):
                        try:
                            from orchestrator.services.agent_run_finalizer import AgentRunFinalizer

                            finalized = AgentRunFinalizer().finalize(
                                run_id=run_id,
                                agent_type=agent_type,
                                config=config,
                                raw_model_output=result.get("output") or result.get("raw_output_preview"),
                                tool_calls=result.get("tool_calls") if isinstance(result.get("tool_calls"), list) else [],
                                runtime_diagnostics={
                                    "runtime": runtime_name,
                                    "source": "execute_agent_background",
                                },
                                artifacts=_collect_agent_run_artifacts(run_id)
                                if agent_type in {"custom", "exploratory"}
                                else [],
                                existing_result=result,
                            )
                            result = finalized.result
                        except Exception as finalizer_error:
                            logger.warning("Agent result finalizer failed for %s: %s", run_id, finalizer_error)

                    exploratory_failed = (
                        finalized.status == "failed"
                        if finalized is not None
                        else agent_type == "exploratory" and _exploratory_result_is_terminal_failure(result)
                    )
                    failure_reason = result.get("failure_reason") if isinstance(result, dict) else None
                    partial_result = (
                        finalized.status == AGENT_PARTIAL_STATUS
                        if finalized is not None
                        else isinstance(result, dict) and bool(result.get("partial_results"))
                    )
                    run.status = (
                        finalized.status
                        if finalized is not None
                        else "failed" if exploratory_failed else AGENT_PARTIAL_STATUS if partial_result else "completed"
                    )
                    run.completed_at = datetime.utcnow()
                    run.result = result
                    if exploratory_failed:
                        run.progress = {
                            **(run.progress or {}),
                            "phase": "failed",
                            "status": "failed",
                            "message": result.get(
                                "summary",
                                "Exploration completed but result parsing failed and no structured data recovered.",
                            ),
                            "updated_at": datetime.utcnow().isoformat(),
                        }
                    session.add(run)
                    session.commit()
                    _record_agent_run_event(
                        run_id,
                        event_type="error" if exploratory_failed else "complete",
                        level="error" if exploratory_failed else "info",
                        message=(
                            result.get("summary")
                            if exploratory_failed and failure_reason == "runtime_auth_failed"
                            else "Exploratory agent run failed: result parsing failed and no structured data recovered."
                            if exploratory_failed
                            else "Agent run completed."
                        ),
                        payload={
                            "status": run.status,
                            "summary": _agent_run_summary(run),
                            "failure_reason": failure_reason,
                        },
                        agent_task_id=run.agent_task_id,
                        session=session,
                    )

    except asyncio.CancelledError:
        logger.info(f"Agent {run_id} cancelled")
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            if run:
                run.status = "cancelled"
                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()
                _record_agent_run_event(
                    run_id,
                    event_type="cancel",
                    message="Agent run cancelled.",
                    payload={"status": run.status},
                    agent_task_id=run.agent_task_id,
                    session=session,
                )
        raise

    except Exception as e:
        import traceback

        traceback.print_exc()
        logger.error(f"Agent {run_id} failed with exception: {e}")
        retry_via_temporal = os.environ.get("QUORVEX_AGENT_TEMPORAL_ACTIVITY") == "true"
        should_reraise = retry_via_temporal
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            if run and run.status not in AGENT_TERMINAL_STATUSES:
                recovered = None
                if agent_type == "custom":
                    recovered = _recover_custom_agent_partial_result(run, e)
                elif agent_type == "exploratory":
                    if _exploratory_result_has_usable_evidence(run.result):
                        recovered = _merge_agent_failure_into_result(
                            run.result,
                            e,
                            failure_reason="runtime_failed_after_evidence",
                        )
                    else:
                        recovered = _recover_exploratory_partial_result(run_id, config, e)

                if recovered is not None:
                    should_reraise = False
                    run.status = AGENT_PARTIAL_STATUS
                    run.completed_at = datetime.utcnow()
                    run.result = recovered
                    run.progress = {
                        **(run.progress or {}),
                        "phase": AGENT_PARTIAL_STATUS,
                        "status": AGENT_PARTIAL_STATUS,
                        "message": recovered.get("summary")
                        or (
                            "Recovered partial custom agent evidence after runtime failure."
                            if agent_type == "custom"
                            else "Recovered partial Explorer evidence after runtime failure."
                        ),
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    event_type = "partial"
                    event_level = "warning"
                    event_message = "Exploratory agent recovered partial evidence after runtime failure."
                    if agent_type == "custom":
                        event_message = "Custom agent recovered partial evidence after runtime failure."
                    event_payload = {
                        "status": run.status,
                        "error": str(e),
                        "summary": _agent_run_summary(run),
                        "failure_reason": recovered.get("failure_reason"),
                        "artifact_recovery": _run_artifact_counts(run_id),
                    }
                elif should_reraise:
                    run.progress = {
                        **(run.progress or {}),
                        "phase": "retrying",
                        "status": run.status,
                        "message": f"Agent execution failed and will be retried by Temporal: {e}",
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    event_type = "retry"
                    event_level = "warning"
                    event_message = f"Agent run failed; Temporal will retry if attempts remain: {e}"
                    event_payload = {"status": run.status, "error": str(e), "retryable": True}
                else:
                    run.status = "failed"
                    run.completed_at = datetime.utcnow()
                    existing_result = run.result if isinstance(run.result, dict) else {}
                    run.result = {**existing_result, "error": str(e)}
                    run.progress = {
                        **(run.progress or {}),
                        "phase": "failed",
                        "status": "failed",
                        "message": str(e),
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    event_type = "error"
                    event_level = "error"
                    event_message = f"Agent run failed: {e}"
                    event_payload = {"status": run.status, "error": str(e)}
                session.add(run)
                session.commit()
                _record_agent_run_event(
                    run_id,
                    event_type=event_type,
                    level=event_level,
                    message=event_message,
                    payload=event_payload,
                    agent_task_id=run.agent_task_id,
                    session=session,
                )
        if should_reraise:
            raise


async def run_agent(request: AgentRunRequest, session: Session = Depends(get_session)):
    """Run an autonomous agent through a durable Temporal workflow."""
    # Check resource availability
    resource_manager = await get_resource_manager()
    agent_status = resource_manager.get_agent_status()

    # Determine initial status based on slot availability
    initial_status = "queued"
    queue_position = None if initial_status == "running" else agent_status.queued + 1

    # Create DB Record
    run_id = str(uuid.uuid4())
    runtime = normalize_agent_runtime(request.runtime or request.config.get("runtime"))
    run_config = {**request.config, "runtime": runtime}
    if request.project_id and not run_config.get("project_id"):
        run_config["project_id"] = request.project_id
    if request.model_tier:
        run_config["model_tier"] = request.model_tier
    if request.browser_auth_session_id:
        run_config["browser_auth_session_id"] = request.browser_auth_session_id
    if request.use_project_default_browser_auth:
        run_config["use_project_default_browser_auth"] = True
    browser_metadata = browser_runtime_status() if _agent_run_has_browser_tools(request.agent_type, run_config) else {}
    run = AgentRun(
        id=run_id,
        agent_type=request.agent_type,
        runtime=runtime,
        config_json=json.dumps(run_config),
        status=initial_status,
        project_id=request.project_id,  # Project isolation
    )
    run.progress = {
        **browser_metadata,
        "phase": "queued",
        "status": initial_status,
        "runtime": runtime,
        "message": "Agent run is queued for Temporal.",
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.add(run)
    session.commit()
    _record_agent_run_event(
        run_id,
        event_type="created",
        message=f"Agent run created with status {initial_status}.",
        payload={
            "agent_type": request.agent_type,
            "runtime": runtime,
            "status": initial_status,
            "queue_position": queue_position,
        },
        session=session,
    )

    await _start_agent_run_temporal_or_fail(run, session)
    session.refresh(run)

    response = {
        "status": initial_status,
        "run_id": run_id,
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
        "browser_runtime": browser_metadata.get("browser_runtime", "temporal_worker"),
        "live_view_available": bool(browser_metadata.get("live_view_available")),
        "vnc_url": browser_metadata.get("vnc_url"),
        "agent_runtime": runtime,
        "agent_slots": {
            "active": agent_status.active,
            "max": agent_status.max_slots,
            "queued": agent_status.queued + (1 if initial_status == "queued" else 0),
        },
    }

    if queue_position:
        response["queue_position"] = queue_position
        response["message"] = f"Request queued at position {queue_position}. Will start when a slot becomes available."

    return response


def list_agent_tool_catalog(session: Session = Depends(get_session)):
    tools = _sync_agent_tool_catalog(session)
    serialized = [_serialize_agent_tool(tool) for tool in tools]
    categories: dict[str, list[dict[str, Any]]] = {}
    for tool in serialized:
        categories.setdefault(tool["category"], []).append(tool)
    return {"tools": serialized, "categories": categories}


def list_agent_definitions(
    project_id: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    session: Session = Depends(get_session),
):
    tools = _sync_agent_tool_catalog(session)
    tools_by_id = {tool.id: tool for tool in tools}
    statement = select(AgentDefinition).order_by(AgentDefinition.updated_at.desc())
    if not include_archived:
        statement = statement.where(AgentDefinition.status == "active")
    if project_id:
        if project_id == "default":
            statement = statement.where((AgentDefinition.project_id == project_id) | (AgentDefinition.project_id == None))
        else:
            statement = statement.where(AgentDefinition.project_id == project_id)
    return [_serialize_agent_definition(item, tools_by_id) for item in session.exec(statement).all()]


async def create_agent_definition(
    request: AgentDefinitionRequest,
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    await _ensure_agent_write_access(request.project_id, current_user, session)
    _resolve_agent_tools(request.tool_ids, session)
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Agent name is required")
    if not request.system_prompt.strip():
        raise HTTPException(status_code=400, detail="System prompt is required")

    definition = AgentDefinition(
        project_id=request.project_id,
        name=request.name.strip(),
        description=request.description.strip(),
        system_prompt=request.system_prompt.strip(),
        runtime=normalize_agent_runtime(request.runtime),
        model=request.model,
        model_tier=request.model_tier,
        timeout_seconds=max(60, min(int(request.timeout_seconds or 1800), 7200)),
        status="active",
    )
    definition.tool_ids = request.tool_ids
    definition.test_data_refs = request.test_data_refs
    session.add(definition)
    session.commit()
    session.refresh(definition)
    return _serialize_agent_definition(definition)


def get_agent_definition(
    definition_id: str,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    tools = _sync_agent_tool_catalog(session)
    tools_by_id = {tool.id: tool for tool in tools}
    return _serialize_agent_definition(_get_agent_definition_or_404(definition_id, project_id, session), tools_by_id)


async def update_agent_definition(
    definition_id: str,
    request: AgentDefinitionUpdateRequest,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    definition = _get_agent_definition_or_404(definition_id, project_id, session)
    await _ensure_agent_write_access(definition.project_id, current_user, session)

    if request.tool_ids is not None:
        _resolve_agent_tools(request.tool_ids, session)
        definition.tool_ids = request.tool_ids
    if request.test_data_refs is not None:
        definition.test_data_refs = request.test_data_refs
    if request.name is not None:
        if not request.name.strip():
            raise HTTPException(status_code=400, detail="Agent name is required")
        definition.name = request.name.strip()
    if request.description is not None:
        definition.description = request.description.strip()
    if request.system_prompt is not None:
        if not request.system_prompt.strip():
            raise HTTPException(status_code=400, detail="System prompt is required")
        definition.system_prompt = request.system_prompt.strip()
    if request.runtime is not None:
        definition.runtime = normalize_agent_runtime(request.runtime)
    if request.model is not None:
        definition.model = request.model
    if request.model_tier is not None:
        definition.model_tier = request.model_tier
    if request.timeout_seconds is not None:
        definition.timeout_seconds = max(60, min(int(request.timeout_seconds), 7200))
    if request.status is not None:
        if request.status not in {"active", "archived"}:
            raise HTTPException(status_code=400, detail="Invalid status")
        definition.status = request.status
    definition.updated_at = datetime.utcnow()
    session.add(definition)
    session.commit()
    session.refresh(definition)
    return _serialize_agent_definition(definition)


async def archive_agent_definition(
    definition_id: str,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    definition = _get_agent_definition_or_404(definition_id, project_id, session)
    await _ensure_agent_write_access(definition.project_id, current_user, session)
    definition.status = "archived"
    definition.updated_at = datetime.utcnow()
    session.add(definition)
    session.commit()
    return {"status": "archived", "id": definition.id}


async def run_agent_definition(
    definition_id: str,
    request: CustomAgentRunRequest,
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    definition = _get_agent_definition_or_404(definition_id, request.project_id, session)
    await _ensure_agent_write_access(definition.project_id, current_user, session)
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required")

    allowed_tools, selected_tools = _resolve_agent_tools(definition.tool_ids, session)

    resource_manager = await get_resource_manager()
    agent_status = resource_manager.get_agent_status()
    initial_status = "queued"
    queue_position = None if initial_status == "running" else agent_status.queued + 1

    run_id = str(uuid.uuid4())
    run_project_id = definition.project_id or request.project_id
    run_test_data_refs = [
        *getattr(definition, "test_data_refs", []),
        *request.test_data_refs,
        *(
            (request.config or {}).get("test_data_refs", [])
            if isinstance((request.config or {}).get("test_data_refs", []), list)
            else []
        ),
    ]
    run_config = {
        "agent_definition_id": definition.id,
        "agent_name": definition.name,
        "prompt": request.prompt.strip(),
        "url": request.url,
        "project_id": run_project_id,
        "custom_config": request.config or {},
        "test_data_refs": run_test_data_refs,
        "system_prompt": definition.system_prompt,
        "timeout_seconds": definition.timeout_seconds,
        "runtime": normalize_agent_runtime(request.runtime or definition.runtime),
        "model": definition.model,
        "model_tier": request.model_tier
        or ((request.config or {}).get("model_tier") if isinstance(request.config, dict) else None)
        or getattr(definition, "model_tier", None),
        "browser_auth_session_id": request.browser_auth_session_id
        or ((request.config or {}).get("browser_auth_session_id") if isinstance(request.config, dict) else None),
        "use_project_default_browser_auth": bool(
            request.use_project_default_browser_auth
            or ((request.config or {}).get("use_project_default_browser_auth") if isinstance(request.config, dict) else False)
        ),
        "tool_ids": definition.tool_ids,
        "allowed_tools": allowed_tools,
        "selected_tools": selected_tools,
    }
    runtime = normalize_agent_runtime(run_config.get("runtime"))
    browser_metadata = browser_runtime_status() if _agent_run_has_browser_tools("custom", run_config) else {}
    run = AgentRun(
        id=run_id,
        agent_type="custom",
        runtime=runtime,
        config_json=json.dumps(run_config),
        status=initial_status,
        project_id=run_project_id,
    )
    run.progress = {
        **browser_metadata,
        "phase": "queued",
        "status": initial_status,
        "runtime": runtime,
        "has_browser_tools": _agent_run_has_browser_tools("custom", run_config),
        "message": "Custom agent run is queued for Temporal.",
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.add(run)
    session.commit()
    _record_agent_run_event(
        run_id,
        event_type="created",
        message=f"Custom agent run created with status {initial_status}.",
        payload={
            "agent_type": "custom",
            "agent_definition_id": definition.id,
            "runtime": runtime,
            "status": initial_status,
            "queue_position": queue_position,
        },
        session=session,
    )

    await _start_agent_run_temporal_or_fail(run, session)
    session.refresh(run)

    response = {
        "status": initial_status,
        "run_id": run_id,
        "agent_definition_id": definition.id,
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
        "agent_runtime": runtime,
        "browser_runtime": browser_metadata.get("browser_runtime", "temporal_worker"),
        "live_view_available": bool(browser_metadata.get("live_view_available")),
        "vnc_url": browser_metadata.get("vnc_url"),
        "agent_slots": {
            "active": agent_status.active,
            "max": agent_status.max_slots,
            "queued": agent_status.queued + (1 if initial_status == "queued" else 0),
        },
    }
    if queue_position:
        response["queue_position"] = queue_position
        response["message"] = f"Request queued at position {queue_position}. Will start when a slot becomes available."
    return response


def list_agent_runs(
    project_id: str | None = None,
    status: str | None = Query(default=None, description="Status filter: all, active, completed, failed, cancelled, paused, or exact status"),
    agent_type: str | None = Query(default=None, description="Agent type filter"),
    q: str | None = Query(default=None, description="Case-insensitive search across IDs and compact run metadata"),
    limit: int = Query(default=40, ge=1, le=100, description="Max items to return"),
    cursor: str | None = Query(default=None, description="Cursor returned from the previous page"),
    offset: int = Query(default=0, ge=0, description="Items to skip"),
    session: Session = Depends(get_session),
):
    filters = _agent_run_history_filters(project_id=project_id, status=status, agent_type=agent_type, q=q)
    decoded_cursor = _decode_agent_run_cursor(cursor)
    if decoded_cursor:
        cursor_created_at, cursor_id = decoded_cursor
        filters.append(
            or_(
                AgentRun.created_at < cursor_created_at,
                and_(AgentRun.created_at == cursor_created_at, AgentRun.id < cursor_id),
            )
        )

    total_filters = _agent_run_history_filters(project_id=project_id, status=status, agent_type=agent_type, q=q)
    total = int(session.exec(select(func.count(AgentRun.id)).where(*total_filters)).one() or 0)
    counts = _agent_run_history_counts(session, project_id=project_id, q=q)
    statement = (
        select(
            AgentRun.id,
            AgentRun.agent_type,
            AgentRun.runtime,
            AgentRun.status,
            AgentRun.created_at,
            AgentRun.started_at,
            AgentRun.completed_at,
            AgentRun.project_id,
            AgentRun.config_json,
            AgentRun.progress_json,
        )
        .where(*filters)
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(limit)
    )
    if offset and not cursor:
        statement = statement.offset(offset)

    rows = session.exec(statement).all()
    items = [_serialize_agent_run_summary_row(row) for row in rows]
    next_cursor = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = _encode_agent_run_cursor(last[4], last[0])
    return {
        "items": items,
        "total": total,
        "counts": counts,
        "next_cursor": next_cursor,
    }


async def get_agent_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    r = session.get(AgentRun, id)
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")

    _filter_agent_run_project(r, project_id)

    payload = await _serialize_agent_run_live(r, session)
    payload["temporal"] = await _agent_run_temporal_payload(r)
    return payload


def get_coding_agent_diff(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(run, project_id)
    if run.agent_type != "coding":
        raise HTTPException(status_code=400, detail="Run is not a coding agent run")

    patch_text = _read_run_text_artifact(id, CODING_ARTIFACT_PATCH)
    if not patch_text:
        raise HTTPException(status_code=404, detail="Coding patch artifact not found")
    try:
        validation = validate_patch_for_repo(patch_text, DEFAULT_REPO_ROOT)
        valid = True
        validation_error = None
        affected_files = list(validation.paths)
    except Exception as exc:
        valid = False
        validation_error = str(exc)
        affected_files = []
    return {
        "run_id": id,
        "status": run.status,
        "valid": valid,
        "validation_error": validation_error,
        "affected_files": affected_files,
        "diff": patch_text,
        "summary": _read_run_text_artifact(id, "summary.md", max_chars=20000),
        "review": _read_run_text_artifact(id, "review.md", max_chars=20000),
    }


async def reject_coding_agent_diff(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(run, project_id)
    if run.agent_type != "coding":
        raise HTTPException(status_code=400, detail="Run is not a coding agent run")
    await _ensure_agent_write_access(run.project_id, current_user, session)

    existing_result = run.result if isinstance(run.result, dict) else {}
    run.result = {**existing_result, "patch_status": "rejected", "patch_rejected_at": datetime.utcnow().isoformat()}
    run.progress = {
        **(run.progress or {}),
        "phase": "rejected",
        "status": run.status,
        "message": "Coding agent patch rejected.",
        "patch_status": "rejected",
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.add(run)
    session.commit()
    _record_agent_run_event(
        id,
        event_type="coding_patch_rejected",
        message="Coding agent patch rejected.",
        payload={"status": run.status, "patch_status": "rejected"},
        agent_task_id=run.agent_task_id,
        session=session,
    )
    return {"status": "rejected", "run_id": id}


async def apply_coding_agent_diff(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(run, project_id)
    if run.agent_type != "coding":
        raise HTTPException(status_code=400, detail="Run is not a coding agent run")
    if run.status not in {"completed", AGENT_PARTIAL_STATUS}:
        raise HTTPException(status_code=409, detail="Coding run must be completed before applying a patch")
    await _ensure_agent_write_access(run.project_id, current_user, session)

    existing_result = run.result if isinstance(run.result, dict) else {}
    if existing_result.get("patch_status") == "applied":
        raise HTTPException(status_code=409, detail="Coding patch has already been applied")
    if existing_result.get("patch_status") == "rejected":
        raise HTTPException(status_code=409, detail="Coding patch has been rejected")

    patch_text = _read_run_text_artifact(id, CODING_ARTIFACT_PATCH)
    if not patch_text:
        raise HTTPException(status_code=404, detail="Coding patch artifact not found")
    try:
        apply_result = apply_patch_to_repo(patch_text, DEFAULT_REPO_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    applied_at = datetime.utcnow().isoformat()
    run.result = {
        **existing_result,
        "patch_status": "applied",
        "patch_applied_at": applied_at,
        "applied_files": apply_result.get("affected_files") or [],
    }
    run.progress = {
        **(run.progress or {}),
        "phase": "applied",
        "status": run.status,
        "message": "Coding agent patch applied.",
        "patch_status": "applied",
        "affected_files": apply_result.get("affected_files") or [],
        "updated_at": applied_at,
    }
    session.add(run)
    session.commit()
    _record_agent_run_event(
        id,
        event_type="coding_patch_applied",
        message="Coding agent patch applied.",
        payload={
            "status": run.status,
            "patch_status": "applied",
            "affected_files": apply_result.get("affected_files") or [],
        },
        agent_task_id=run.agent_task_id,
        session=session,
    )
    return {"status": "applied", "run_id": id, "affected_files": apply_result.get("affected_files") or []}


def list_agent_run_events_api(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    after_sequence: int = Query(default=0, ge=0),
    event_type: str | None = Query(default=None),
    level: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_session),
):
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(run, project_id)

    from orchestrator.services.agent_run_events import event_to_response, list_agent_run_events

    events = list_agent_run_events(
        run_id=run.id,
        after_sequence=after_sequence,
        event_type=event_type,
        level=level,
        limit=limit,
        session=session,
    )
    return [event_to_response(event) for event in events]


async def stream_agent_run_events_api(
    request: Request,
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    with Session(engine) as session:
        run = session.get(AgentRun, id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        _filter_agent_run_project(run, project_id)

    async def event_generator():
        sequence = after_sequence
        idle_ticks = 0
        from orchestrator.services.agent_run_events import event_to_response, list_agent_run_events

        while True:
            if await request.is_disconnected():
                break
            terminal = False
            with Session(engine) as session:
                run = session.get(AgentRun, id)
                terminal = bool(run and run.status in AGENT_TERMINAL_STATUSES)
                events = list_agent_run_events(run_id=id, after_sequence=sequence, limit=limit, session=session)
                for event in events:
                    sequence = max(sequence, event.sequence)
                    yield f"data: {json.dumps(event_to_response(event))}\n\n"
                if events:
                    idle_ticks = 0
                else:
                    idle_ticks += 1
            if terminal and not events:
                yield f"event: complete\ndata: {json.dumps({'run_id': id, 'sequence': sequence})}\n\n"
                break
            if idle_ticks >= 15:
                yield f": heartbeat {datetime.utcnow().isoformat()}\n\n"
                idle_ticks = 0
            await asyncio.sleep(1.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


async def get_agent_run_trace_api(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(run, project_id)

    from orchestrator.services.agent_trace import trace_bundle_for_run

    return await trace_bundle_for_run(run=run, session=session)


def list_agent_run_trace_spans_api(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    trace_id: str | None = Query(default=None),
    span_type: str | None = Query(default=None),
    level: str | None = Query(default=None),
    tool: str | None = Query(default=None),
    q: str | None = Query(default=None),
    after_sequence: int = Query(default=0, ge=0),
    before_sequence: int | None = Query(default=None, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_session),
):
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(run, project_id)

    from orchestrator.services.agent_trace import list_trace_spans, serialize_span

    spans = list_trace_spans(
        run_id=run.id,
        trace_id=trace_id,
        span_type=span_type,
        level=level,
        tool=tool,
        q=q,
        after_sequence=after_sequence,
        before_sequence=before_sequence,
        limit=limit,
        session=session,
    )
    return [serialize_span(span) for span in spans]


async def export_agent_run_trace_api(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(run, project_id)

    from orchestrator.services.agent_trace import trace_bundle_for_run

    bundle = await trace_bundle_for_run(run=run, session=session)
    response = JSONResponse(
        {
            "schema": "quorvex.agent_trace_export.v1",
            "exported_at": datetime.utcnow().isoformat(),
            "run": _serialize_agent_run(run, session),
            **bundle,
        }
    )
    response.headers["Content-Disposition"] = f'attachment; filename="agent-trace-{run.id}.json"'
    return response


async def get_agent_temporal_health():
    from orchestrator.services.temporal_client import check_agent_run_temporal_health

    return await check_agent_run_temporal_health()


async def pause_agent_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(run, project_id)
    await _ensure_agent_write_access(run.project_id, current_user, session)

    if run.status in AGENT_TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot pause a {run.status} run")
    if run.status == "paused":
        return _serialize_agent_run(run, session)

    await _signal_agent_run_temporal(run, "pause", "manual_pause")

    _mark_agent_run_paused(run)
    session.add(run)
    session.commit()
    session.refresh(run)
    _record_agent_run_event(
        run.id,
        event_type="pause",
        message="Agent run paused.",
        payload={"status": run.status, "agent_task_id": run.agent_task_id},
        agent_task_id=run.agent_task_id,
        session=session,
    )
    return _serialize_agent_run(run, session)


async def resume_agent_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(run, project_id)
    await _ensure_agent_write_access(run.project_id, current_user, session)

    if run.status in AGENT_TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot resume a {run.status} run")
    if run.status != "paused":
        return _serialize_agent_run(run, session)

    await _signal_agent_run_temporal(run, "resume")

    paused_from = (run.progress or {}).get("paused_from")
    run.status = paused_from if paused_from in {"queued", "running", "pending"} else "queued"
    run.progress = {
        **(run.progress or {}),
        "phase": "resumed",
        "status": run.status,
        "message": "Agent resumed",
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.add(run)
    session.commit()
    session.refresh(run)
    _record_agent_run_event(
        run.id,
        event_type="resume",
        message=f"Agent run resumed as {run.status}.",
        payload={"status": run.status, "agent_task_id": run.agent_task_id},
        agent_task_id=run.agent_task_id,
        session=session,
    )
    return _serialize_agent_run(run, session)


async def cancel_agent_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(run, project_id)
    await _ensure_agent_write_access(run.project_id, current_user, session)

    if run.status in AGENT_TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot cancel a {run.status} run")

    await _signal_agent_run_temporal(run, "cancel", "manual_cancel")

    _mark_agent_run_cancelled(run)
    session.add(run)
    session.commit()
    session.refresh(run)
    queue_cancel_result = await _cancel_agent_run_queue_task(run)
    _record_agent_run_event(
        run.id,
        event_type="cancel",
        message="Agent run cancelled.",
        payload={
            "status": run.status,
            "agent_task_id": run.agent_task_id,
            "queue_cancel": queue_cancel_result,
        },
        agent_task_id=run.agent_task_id,
        session=session,
    )
    return _serialize_agent_run(run, session)


async def retry_agent_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    source = session.get(AgentRun, id)
    if not source:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(source, project_id)
    await _ensure_agent_write_access(source.project_id, current_user, session)

    if source.status not in AGENT_TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot retry a {source.status} run")

    retry_config = dict(source.config or {})
    previous_attempt = max(
        _coerce_progress_int(retry_config.get("retry_attempt"), 0),
        _coerce_progress_int((source.progress or {}).get("retry_attempt"), 0),
    )
    next_attempt = previous_attempt + 1
    previous_workflow_id = source.temporal_workflow_id
    previous_temporal_run_id = source.temporal_run_id
    last_failure = None
    if isinstance(source.result, dict):
        last_failure = source.result.get("error") or source.result.get("summary")
    last_failure = last_failure or (source.progress or {}).get("message") or source.status
    last_observed_url = _latest_observed_url_for_run(source)
    artifacts = _collect_agent_run_artifacts(source.id) if source.agent_type in ("exploratory", "custom") else []
    artifact_counts = _run_artifact_counts(source.id, artifacts)
    retry_config.update(
        {
            "runtime": normalize_agent_runtime(source.runtime or retry_config.get("runtime")),
            "retry_in_place": True,
            "source_run_id": source.id,
            "retry_attempt": next_attempt,
            "retry_context": {
                "attempt": next_attempt,
                "last_failure": str(last_failure)[:1200],
                "last_observed_url": last_observed_url,
                **artifact_counts,
            },
        }
    )
    if source.project_id and not retry_config.get("project_id"):
        retry_config["project_id"] = source.project_id
    browser_metadata = browser_runtime_status() if _agent_run_has_browser_tools(source.agent_type, retry_config) else {}
    previous_status = source.status
    source.config = retry_config
    source.runtime = normalize_agent_runtime(retry_config.get("runtime"))
    source.status = "queued"
    source.started_at = None
    source.completed_at = None
    source.agent_task_id = None
    source.temporal_workflow_id = None
    source.temporal_run_id = None
    source.progress = {
        **(source.progress or {}),
        **browser_metadata,
        "phase": "queued",
        "status": "queued",
        "runtime": source.runtime,
        "message": "Retrying in same run using saved browser auth/session artifacts.",
        "retry_in_place": True,
        "retry_attempt": next_attempt,
        "previous_status": previous_status,
        "previous_temporal_workflow_id": previous_workflow_id,
        "previous_temporal_run_id": previous_temporal_run_id,
        "last_failure": str(last_failure)[:1200],
        "last_observed_url": last_observed_url,
        **artifact_counts,
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.add(source)
    session.commit()

    _record_agent_run_event(
        source.id,
        event_type="retry_started",
        message="Retrying in same run using saved browser auth/session artifacts.",
        payload={
            "agent_type": source.agent_type,
            "runtime": source.runtime,
            "status": source.status,
            "previous_status": previous_status,
            "retry_attempt": next_attempt,
            "previous_temporal_workflow_id": previous_workflow_id,
            "previous_temporal_run_id": previous_temporal_run_id,
            "last_failure": str(last_failure)[:1200],
            "last_observed_url": last_observed_url,
            **artifact_counts,
        },
        session=session,
    )

    await _start_agent_run_temporal_or_fail(source, session, workflow_attempt=next_attempt)
    session.refresh(source)
    return {
        **_serialize_agent_run(source, session),
        "run_id": source.id,
        "source_run_id": source.id,
        "retry_in_place": True,
        "retry_attempt": next_attempt,
        "previous_temporal_workflow_id": previous_workflow_id,
    }


def get_agent_run_report(
    id: str,
    project_id: str = Query(..., description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    run = _get_agent_report_run(session, id, project_id)

    result = run.result or {}
    artifacts = _collect_agent_run_artifacts(run.id) if run.agent_type in ("exploratory", "custom") else []
    structured = result.get("structured_report") if isinstance(result, dict) else None
    if run.agent_type == "custom" and not isinstance(structured, dict):
        structured = _build_custom_agent_structured_report(result.get("output", "") if isinstance(result, dict) else "", run.config, artifacts)

    return {
        "id": run.id,
        "agent_type": run.agent_type,
        "status": run.status,
        "created_at": run.created_at.isoformat(),
        "config": run.config,
        "project_id": run.project_id,
        "summary": _agent_run_summary(run),
        "structured_report": structured,
        "raw_output": result.get("output") if isinstance(result, dict) else None,
        "artifacts": artifacts,
    }


def update_agent_run_report_overview(
    run_id: str,
    request: UpdateAgentReportOverviewRequest,
    project_id: str = Query(..., description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    run = _get_agent_report_run(session, run_id, project_id)

    result, report = _stored_custom_agent_report(run)
    fields_set = getattr(request, "model_fields_set", None)
    if fields_set is None:
        fields_set = getattr(request, "__fields_set__", set())
    if "summary" in fields_set:
        report["summary"] = _clean_text(request.summary, 2000)
    if "scope" in fields_set:
        report["scope"] = _clean_text(request.scope, 2000)

    result["structured_report"] = report
    run.result = result
    session.add(run)
    session.commit()
    session.refresh(run)

    return {
        "structured_report": report,
        "run": _serialize_agent_run(run, session),
    }


def update_agent_run_report_item(
    run_id: str,
    item_id: str,
    request: UpdateAgentReportItemRequest,
    item_type: str = Query(..., description="finding, test_idea, or requirement"),
    project_id: str = Query(..., description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    run = _get_agent_report_run(session, run_id, project_id)

    normalized_type = _normalize_report_item_type(item_type)
    result, report = _stored_custom_agent_report(run)
    item = _find_report_item(report, normalized_type, item_id)
    if normalized_type == "requirement" and (
        item.get("imported_requirement_id") or item.get("imported_requirement_code") or item.get("imported_at")
    ):
        raise HTTPException(
            status_code=409,
            detail="This report requirement was already imported. Edit it in Requirements instead.",
        )

    for field, value in _editable_report_item_patch(normalized_type, request.patch or {}).items():
        item[field] = value

    result["structured_report"] = report
    run.result = result
    session.add(run)
    session.commit()
    session.refresh(run)

    return {
        "item": item,
        "run": _serialize_agent_run(run, session),
    }


def search_agent_reports(
    project_id: str | None = Query(default=None),
    query: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    item_type: str | None = Query(default=None, description="finding, test_idea, requirement, page, evidence, or action"),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    statement = select(AgentRun).where(AgentRun.agent_type == "custom").order_by(AgentRun.created_at.desc())
    if project_id:
        if project_id == "default":
            statement = statement.where((AgentRun.project_id == project_id) | (AgentRun.project_id == None))
        else:
            statement = statement.where(AgentRun.project_id == project_id)

    needle = (query or "").strip().lower()
    severity_filter = (severity or "").strip().lower()
    type_filter = (item_type or "").strip().lower()
    results: list[dict[str, Any]] = []

    for run in session.exec(statement.limit(200)).all():
        result = run.result or {}
        structured = result.get("structured_report") if isinstance(result, dict) else None
        if not isinstance(structured, dict):
            continue

        collections = {
            "finding": structured.get("findings") or [],
            "test_idea": structured.get("test_ideas") or [],
            "requirement": structured.get("requirements") or [],
            "page": structured.get("pages_checked") or [],
            "evidence": structured.get("evidence") or [],
            "action": structured.get("follow_up_actions") or [],
        }
        for current_type, items in collections.items():
            if type_filter and current_type != type_filter:
                continue
            for item in _as_report_list(items):
                if not isinstance(item, dict):
                    continue
                haystack = json.dumps(item, ensure_ascii=False).lower()
                if needle and needle not in haystack:
                    continue
                item_severity = _clean_text(item.get("severity") or item.get("priority"), 30).lower()
                if severity_filter and item_severity != severity_filter:
                    continue
                results.append(
                    {
                        "run_id": run.id,
                        "agent_name": run.config.get("agent_name") or "Custom Agent",
                        "created_at": run.created_at.isoformat(),
                        "type": current_type,
                        "item": item,
                    }
                )
                if len(results) >= limit:
                    return {"items": results, "count": len(results)}
    return {"items": results, "count": len(results)}


def import_agent_report_requirements(
    run_id: str,
    request: ImportReportRequirementsRequest,
    project_id: str = Query(..., description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """Import reviewed custom-agent report requirements as candidate requirements."""
    from memory.exploration_store import get_exploration_store

    run = _get_agent_report_run(session, run_id, project_id)
    if run.agent_type != "custom":
        raise HTTPException(status_code=400, detail="Only custom agent reports can import requirements")

    result = run.result or {}
    report = result.get("structured_report") if isinstance(result, dict) else None
    if not isinstance(report, dict):
        raise HTTPException(status_code=400, detail="This run does not have a stored structured report")

    requirements_items = [item for item in _as_report_list(report.get("requirements")) if isinstance(item, dict)]
    if not requirements_items:
        raise HTTPException(status_code=400, detail="This report does not contain structured requirements")

    requested_ids = {_clean_text(item_id, 80) for item_id in (request.item_ids or []) if _clean_text(item_id, 80)}
    if not request.import_all and not requested_ids:
        raise HTTPException(status_code=400, detail="Provide item_ids or set import_all=true")

    indexed = {str(item.get("id") or ""): item for item in requirements_items if item.get("id")}
    if request.import_all:
        selected = requirements_items
    else:
        missing = sorted(item_id for item_id in requested_ids if item_id not in indexed)
        if missing:
            raise HTTPException(status_code=404, detail={"message": "Report requirement item not found", "missing_item_ids": missing})
        selected = [indexed[item_id] for item_id in requested_ids]

    target_project_id = run.project_id or project_id or run.config.get("project_id") or "default"
    store = get_exploration_store(project_id=target_project_id)
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for item in selected:
        item_id = _clean_text(item.get("id"), 80)
        imported_id = item.get("imported_requirement_id")
        imported_code = item.get("imported_requirement_code")
        if imported_id or imported_code:
            skipped.append(
                {
                    "item_id": item_id,
                    "reason": "already_imported",
                    "requirement_id": imported_id,
                    "req_code": imported_code,
                }
            )
            continue

        body = _requirement_create_body_from_report_item(item)
        if not body["title"]:
            skipped.append({"item_id": item_id, "reason": "missing_title"})
            continue

        req_code = store.get_next_requirement_code()
        requirement = store.store_requirement(
            req_code=req_code,
            title=body["title"],
            description=body["description"],
            category=body["category"],
            priority=body["priority"],
            acceptance_criteria=body["acceptance_criteria"],
            truth_state=body["truth_state"],
            source_type=body["source_type"],
            confidence=body["confidence"],
            uncertainty_reason=body["uncertainty_reason"],
        )
        item["imported_requirement_id"] = requirement.id
        item["imported_requirement_code"] = requirement.req_code
        item["imported_at"] = datetime.utcnow().isoformat()
        created.append(
            {
                "item_id": item_id,
                "id": requirement.id,
                "req_code": requirement.req_code,
                "title": requirement.title,
                "project_id": target_project_id,
            }
        )

    if not isinstance(result, dict):
        result = {}
    result["structured_report"] = report
    run.result = result
    session.add(run)
    session.commit()
    session.refresh(run)

    if created:
        _record_agent_run_event(
            run.id,
            event_type="requirements_imported",
            message=f"Imported {len(created)} custom-agent report requirement(s).",
            payload={
                "created_requirements": created,
                "created_requirement_ids": [item["id"] for item in created],
                "created_requirement_codes": [item["req_code"] for item in created],
                "skipped": skipped,
            },
            session=session,
        )

    return {
        "created": len(created),
        "skipped": len(skipped),
        "requirements": created,
        "skipped_items": skipped,
        "run": _serialize_agent_run(run, session),
    }


# ========= Enhanced Exploratory Testing Endpoints =========


async def run_exploratory_agent(
    request: ExploratoryRunRequest, session: Session = Depends(get_session)
):
    """
    Run enhanced exploratory testing with 10-15 minute autonomous exploration.

    Features:
    - Smart state tracking to avoid loops
    - Coverage goals for guided exploration
    - Auth support (credentials, session, none)
    - Test data integration
    - Focus areas and exclusion patterns
    """
    from agents.auth_handler import AuthHandler, get_auth_test_data

    # Build config for agent
    config = request.dict()
    runtime = normalize_agent_runtime(request.runtime or config.get("runtime"))
    config["runtime"] = runtime
    config["agent_tool_profile"] = (
        "app-explorer-advanced"
        if bool(config.get("advanced_tools") or config.get("record_video"))
        else "app-explorer-basic"
    )

    # Process auth configuration
    auth_result = {"success": True, "type": "none"}
    if request.auth:
        auth_handler = AuthHandler()
        auth_result = await auth_handler.authenticate(None, request.auth, request.url)

        # Add auth instructions to prompt
        if auth_result.get("success") and auth_result.get("instructions"):
            config["auth_instructions"] = auth_result["instructions"]

        # Add auth test data (ensure test_data is a dict)
        if config.get("test_data") is None:
            config["test_data"] = {}
        config["test_data"].update(get_auth_test_data(request.auth or {}))

    # Create DB record
    run_id = str(uuid.uuid4())
    run = AgentRun(
        id=run_id,
        agent_type="exploratory",
        runtime=runtime,
        config_json=json.dumps(config),
        status="queued",
        project_id=request.project_id,  # Project isolation in DB field
    )
    browser_metadata = browser_runtime_status()
    run.progress = {
        **browser_metadata,
        "phase": "queued",
        "status": "queued",
        "runtime": runtime,
        "message": "Exploratory agent run is queued for Temporal.",
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.add(run)
    session.commit()

    _record_agent_run_event(
        run_id,
        event_type="created",
        message="Exploratory agent run created with status queued.",
        payload={"agent_type": "exploratory", "runtime": runtime, "status": "queued"},
        session=session,
    )

    await _start_agent_run_temporal_or_fail(run, session)
    session.refresh(run)

    return {
        "run_id": run_id,
        "status": run.status,
        "auth": auth_result.get("type", "none"),
        "project_id": request.project_id,
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
        "agent_runtime": runtime,
        "browser_runtime": browser_metadata.get("browser_runtime"),
        "live_view_available": bool(browser_metadata.get("live_view_available")),
        "vnc_url": browser_metadata.get("vnc_url"),
    }


async def synthesize_specs(run_id: str, session: Session = Depends(get_session)):
    """
    Generate .md test specs from exploration results.

    Takes the exploration results and synthesizes them into
    production-ready .md specs that work with the existing pipeline.
    """
    # Get exploration run
    exploration_run = session.get(AgentRun, run_id)
    if not exploration_run:
        raise HTTPException(status_code=404, detail="Exploration run not found")

    exploration_result = exploration_run.result
    if not exploration_result:
        raise HTTPException(status_code=400, detail="No exploration results found")
    flow_summaries = (
        exploration_result.get("discovered_flow_summaries")
        if isinstance(exploration_result, dict) and isinstance(exploration_result.get("discovered_flow_summaries"), list)
        else []
    )
    if exploration_run.status not in {"completed", AGENT_PARTIAL_STATUS}:
        raise HTTPException(status_code=400, detail="Exploration must be completed before synthesis")
    if exploration_run.status == AGENT_PARTIAL_STATUS and not flow_summaries:
        raise HTTPException(status_code=400, detail="Recovered exploration has no evidence-backed flows to synthesize")

    # Create synthesis run
    import os

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    output_dir = os.path.join(project_root, "specs", "generated")

    synthesis_run_id = str(uuid.uuid4())

    # Extract project_id from exploration run - prefer DB field, fallback to config
    exploration_project_id = exploration_run.project_id
    if not exploration_project_id:
        # Fallback: get from result config if not in DB field (backwards compatibility)
        exploration_project_id = exploration_result.get("config", {}).get("project_id")
    if not exploration_project_id and exploration_run.config_json:
        # Final fallback: get from stored config_json
        run_config = json.loads(exploration_run.config_json)
        exploration_project_id = run_config.get("project_id")

    synthesis_config = {
        "exploration_results": exploration_result,
        "url": exploration_result.get("config", {}).get("url", ""),
        "output_dir": output_dir,
        "run_id": run_id,  # Pass run_id so agent can read flows.json
        "project_id": exploration_project_id,  # Propagate project association
        "runtime": getattr(exploration_run, "runtime", "claude_sdk") or exploration_run.config.get("runtime") or "claude_sdk",
    }
    synthesis_runtime = normalize_agent_runtime(synthesis_config.get("runtime"))

    synthesis_run = AgentRun(
        id=synthesis_run_id,
        agent_type="spec-synthesis",
        runtime=synthesis_runtime,
        config_json=json.dumps(synthesis_config),
        status="queued",
        project_id=exploration_project_id,  # Project isolation in DB field
    )
    session.add(synthesis_run)
    session.commit()

    _record_agent_run_event(
        synthesis_run_id,
        event_type="created",
        message="Spec synthesis agent run created with status queued.",
        payload={
            "agent_type": "spec-synthesis",
            "runtime": synthesis_runtime,
            "status": "queued",
            "exploration_run_id": run_id,
        },
        session=session,
    )

    await _start_agent_run_temporal_or_fail(synthesis_run, session)
    session.refresh(synthesis_run)

    return {
        "synthesis_run_id": synthesis_run_id,
        "exploration_run_id": run_id,
        "status": synthesis_run.status,
        "temporal_workflow_id": synthesis_run.temporal_workflow_id,
        "temporal_run_id": synthesis_run.temporal_run_id,
    }


def _verify_exploration_run_project(run_id: str, project_id: str | None, session: Session) -> AgentRun:
    """Helper to verify an exploration run exists and belongs to the specified project."""
    exploration_run = session.get(AgentRun, run_id)
    if not exploration_run:
        raise HTTPException(status_code=404, detail="Exploration run not found")

    if project_id:
        if exploration_run.project_id:
            if project_id == "default":
                if exploration_run.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Exploration run not found")
            elif exploration_run.project_id != project_id:
                raise HTTPException(status_code=404, detail="Exploration run not found")

    return exploration_run


async def get_exploration_specs(
    run_id: str,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """
    Get generated specs from an exploration run.

    Returns the specs that were generated from the exploration.
    """
    # Verify exploration run belongs to project
    _verify_exploration_run_project(run_id, project_id, session)

    # Get synthesis runs for this exploration
    statement = select(AgentRun).where(AgentRun.config_json.contains(run_id)).order_by(AgentRun.created_at.desc())

    synthesis_runs = session.exec(statement).all()

    if not synthesis_runs:
        return {"specs": {}, "message": "No specs generated yet. Run /synthesize first."}

    # Get the most recent completed synthesis
    for run in synthesis_runs:
        if run.status == "completed" and run.result:
            return {
                "specs": run.result.get("specs", {}),
                "summary": run.result.get("summary", ""),
                "total_specs": run.result.get("total_specs", 0),
                "flows_covered": run.result.get("flows_covered", []),
                "generated_at": run.result.get("generated_at"),
            }

    raise HTTPException(status_code=404, detail="No completed spec synthesis found")


async def get_flow_details(
    run_id: str,
    flow_id: str,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """
    Get full details for a specific discovered flow.

    Reads the flows.json file saved during exploration and returns
    the complete flow data including happy path, edge cases, and test ideas.
    """
    from pathlib import Path

    # Verify exploration run belongs to project
    _verify_exploration_run_project(run_id, project_id, session)

    # Path to flows.json file (at project root)
    project_root = Path(__file__).parent.parent.parent
    flows_file = project_root / "runs" / run_id / "flows.json"

    if not await asyncio.to_thread(flows_file.exists):
        raise HTTPException(
            status_code=404,
            detail=f"Flows file not found for run {run_id}. The exploration may not have completed yet.",
        )

    try:
        raw = await asyncio.to_thread(flows_file.read_text)
        data = json.loads(raw)

        flows = data.get("flows", [])

        # Find the requested flow by id
        flow = next((f for f in flows if f.get("id") == flow_id), None)

        if not flow:
            # Try to find by index (flow_1 = index 0, flow_2 = index 1, etc.)
            if flow_id.startswith("flow_"):
                try:
                    index = int(flow_id.split("_")[1]) - 1
                    if 0 <= index < len(flows):
                        flow = flows[index]
                except (ValueError, IndexError):
                    pass

        if not flow:
            raise HTTPException(
                status_code=404,
                detail=f"Flow {flow_id} not found in run {run_id}. Available flows: {[f.get('id') for f in flows]}",
            )

        return {"flow": flow}

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse flows.json file")
    except Exception as e:
        logger.error(f"Error reading flow details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


async def update_flow(
    run_id: str,
    flow_id: str,
    request: FlowUpdateRequest,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """
    Update a specific discovered flow with partial data.

    Reads the flows.json file, applies the partial update to the matching flow,
    and writes the updated data back.
    """
    from pathlib import Path

    # Verify exploration run belongs to project
    _verify_exploration_run_project(run_id, project_id, session)

    # Path to flows.json file (at project root)
    project_root = Path(__file__).parent.parent.parent
    flows_file = project_root / "runs" / run_id / "flows.json"

    if not await asyncio.to_thread(flows_file.exists):
        raise HTTPException(
            status_code=404,
            detail=f"Flows file not found for run {run_id}. The exploration may not have completed yet.",
        )

    try:
        raw = await asyncio.to_thread(flows_file.read_text)
        data = json.loads(raw)

        flows = data.get("flows", [])

        # Find the requested flow by id
        flow = next((fl for fl in flows if fl.get("id") == flow_id), None)
        flow_index = None

        if flow:
            flow_index = flows.index(flow)
        elif flow_id.startswith("flow_"):
            try:
                index = int(flow_id.split("_")[1]) - 1
                if 0 <= index < len(flows):
                    flow = flows[index]
                    flow_index = index
            except (ValueError, IndexError):
                pass

        if flow is None or flow_index is None:
            raise HTTPException(
                status_code=404,
                detail=f"Flow {flow_id} not found in run {run_id}. Available flows: {[fl.get('id') for fl in flows]}",
            )

        # Apply partial update
        updates = request.model_dump(exclude_none=True)
        flow.update(updates)
        flows[flow_index] = flow

        data["flows"] = flows
        updated_json = json.dumps(data, indent=2)
        await asyncio.to_thread(flows_file.write_text, updated_json)

        return {"flow": flow}

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse flows.json file")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


async def delete_flow(
    run_id: str,
    flow_id: str,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """
    Delete a specific discovered flow.

    Reads the flows.json file, removes the matching flow,
    and writes the updated data back.
    """
    from pathlib import Path

    # Verify exploration run belongs to project
    _verify_exploration_run_project(run_id, project_id, session)

    # Path to flows.json file (at project root)
    project_root = Path(__file__).parent.parent.parent
    flows_file = project_root / "runs" / run_id / "flows.json"

    if not await asyncio.to_thread(flows_file.exists):
        raise HTTPException(
            status_code=404,
            detail=f"Flows file not found for run {run_id}. The exploration may not have completed yet.",
        )

    try:
        raw = await asyncio.to_thread(flows_file.read_text)
        data = json.loads(raw)

        flows = data.get("flows", [])

        # Find the requested flow by id
        flow = next((fl for fl in flows if fl.get("id") == flow_id), None)
        flow_index = None

        if flow:
            flow_index = flows.index(flow)
        elif flow_id.startswith("flow_"):
            try:
                index = int(flow_id.split("_")[1]) - 1
                if 0 <= index < len(flows):
                    flow = flows[index]
                    flow_index = index
            except (ValueError, IndexError):
                pass

        if flow is None or flow_index is None:
            raise HTTPException(
                status_code=404,
                detail=f"Flow {flow_id} not found in run {run_id}. Available flows: {[fl.get('id') for fl in flows]}",
            )

        # Remove the flow
        flows.pop(flow_index)

        data["flows"] = flows
        updated_json = json.dumps(data, indent=2)
        await asyncio.to_thread(flows_file.write_text, updated_json)

        return {"deleted": True, "flow_id": flow_id, "remaining_flows": len(flows)}

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse flows.json file")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting flow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


async def analyze_prerequisites(
    run_id: str,
    force_reanalyze: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """
    Analyze all discovered flows and enrich them with prerequisites information.

    This endpoint runs the Prerequisites Analysis Agent which:
    - Identifies authentication requirements for each flow
    - Detects data dependencies (must have existing entities)
    - Builds flow dependency graph (flow A must complete before B)
    - Determines setup steps needed before each test

    Results are saved back to flows.json for use in spec generation.
    """
    from pathlib import Path

    from agents.prerequisites_agent import PrerequisitesAgent
    from load_env import setup_claude_env

    # Verify exploration run belongs to project
    _verify_exploration_run_project(run_id, project_id, session)

    project_root = Path(__file__).parent.parent.parent
    flows_file = project_root / "runs" / run_id / "flows.json"
    result_file = project_root / "runs" / run_id / "result.json"

    if not await asyncio.to_thread(flows_file.exists):
        raise HTTPException(status_code=404, detail=f"Flows file not found for run {run_id}")

    setup_claude_env()

    try:
        raw = await asyncio.to_thread(flows_file.read_text)
        data = json.loads(raw)

        flows = data.get("flows", [])

        # Check if already analyzed (unless force_reanalyze)
        if not force_reanalyze and flows and flows[0].get("prerequisites"):
            return {
                "enriched_flows": flows,
                "flow_graph": data.get("flow_graph", {}),
                "summary": "Loaded previously analyzed prerequisites",
                "cached": True,
            }

        # Load exploration results for context
        exploration_results = {}
        auth_config = {}
        test_data = {}
        exploration_url = ""

        if await asyncio.to_thread(result_file.exists):
            result_raw = await asyncio.to_thread(result_file.read_text)
            exploration_results = json.loads(result_raw)
            auth_config = exploration_results.get("config", {}).get("auth", {})
            test_data = exploration_results.get("config", {}).get("test_data", {})
            exploration_url = exploration_results.get("exploration_url", "")

        # Run Prerequisites Analysis Agent
        agent = PrerequisitesAgent()
        result = await agent.run(
            {
                "flows": flows,
                "action_trace": exploration_results.get("action_trace", []),
                "exploration_url": exploration_url,
                "auth_config": auth_config,
                "test_data": test_data,
            }
        )

        # Save enriched flows back to flows.json
        enriched_flows = result.get("enriched_flows", flows)

        updated_json = json.dumps(
            {
                "flows": enriched_flows,
                "flow_graph": result.get("flow_graph", {}),
                "entities_discovered": result.get("entities_discovered", []),
                "prerequisites_analyzed_at": result.get("analyzed_at"),
            },
            indent=2,
        )
        await asyncio.to_thread(flows_file.write_text, updated_json)

        return {
            "enriched_flows": enriched_flows,
            "flow_graph": result.get("flow_graph", {}),
            "entities_discovered": result.get("entities_discovered", []),
            "summary": result.get("summary", "Analysis complete"),
            "cached": False,
        }

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse flows.json file")
    except Exception as e:
        logger.error(f"Error analyzing prerequisites: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


async def generate_flow_spec(
    run_id: str,
    flow_id: str,
    force_regenerate: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """
    Generate a test spec for a single discovered flow.

    Takes a specific flow from exploration and generates a focused
    .md test spec that can be run through the pipeline.
    Uses LLM-powered generation for better quality specs.

    If a spec already exists for this flow, returns the cached version.
    Use force_regenerate=true to generate a new spec even if one exists.
    """
    from datetime import datetime
    from pathlib import Path

    from agents.spec_synthesis_agent import SpecSynthesisAgent
    from load_env import setup_claude_env

    # Verify exploration run belongs to project
    _verify_exploration_run_project(run_id, project_id, session)

    # Get project root
    project_root = Path(__file__).parent.parent.parent
    flows_file = project_root / "runs" / run_id / "flows.json"
    result_file = project_root / "runs" / run_id / "result.json"

    if not await asyncio.to_thread(flows_file.exists):
        raise HTTPException(status_code=404, detail=f"Flows file not found for run {run_id}")

    # Setup Claude environment for agent
    setup_claude_env()

    try:
        raw = await asyncio.to_thread(flows_file.read_text)
        data = json.loads(raw)

        flows = data.get("flows", [])

        # Find the requested flow
        flow = next((f for f in flows if f.get("id") == flow_id), None)

        if not flow and flow_id.startswith("flow_"):
            try:
                index = int(flow_id.split("_")[1]) - 1
                if 0 <= index < len(flows):
                    flow = flows[index]
            except (ValueError, IndexError):
                pass

        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        # Check if spec already exists (return cached version unless force_regenerate)
        if not force_regenerate and "generated_spec" in flow:
            existing_spec = flow["generated_spec"]
            return {
                "spec_content": existing_spec["spec_content"],
                "filename": existing_spec.get("filename", f"{flow.get('title', 'spec').lower().replace(' ', '_')}.md"),
                "flow_title": flow.get("title", "Unnamed Flow"),
                "summary": "Loaded previously generated spec",
                "generated_at": existing_spec.get("generated_at", datetime.now().isoformat()),
                "cached": True,
            }

        # Load exploration result for context
        exploration_results = {}
        if await asyncio.to_thread(result_file.exists):
            result_raw = await asyncio.to_thread(result_file.read_text)
            exploration_results = json.loads(result_raw)

        # Get base URL from exploration results
        base_url = exploration_results.get("exploration_url", "")
        if not base_url:
            # Try to infer from the first page in the flow
            pages = flow.get("pages", [])
            if pages:
                from urllib.parse import urlparse

                parsed = urlparse(pages[0])
                base_url = f"{parsed.scheme}://{parsed.netloc}"

        # Generate spec content using SpecSynthesisAgent
        agent = SpecSynthesisAgent()

        # Build synthesis prompt for single flow
        prompt = _build_single_flow_prompt(flow, base_url)

        # Query agent for spec generation
        result = await agent._query_agent(prompt)

        # Parse the agent response
        from utils.json_utils import extract_json_from_markdown

        spec_data = extract_json_from_markdown(result)

        # Extract spec content from agent response
        if "specs" in spec_data and spec_data["specs"]:
            # Get the first spec from happy_path or any category
            spec_content = None
            filename = None

            for category in ["happy_path", "negative", "edge_case", "edge_cases", "accessibility", "regression"]:
                if category in spec_data["specs"] and spec_data["specs"][category]:
                    for fname, content in spec_data["specs"][category].items():
                        spec_content = content
                        filename = fname
                        break
                if spec_content:
                    break

            if not spec_content:
                # Fallback to any spec
                for _category, files in spec_data["specs"].items():
                    for fname, content in files.items():
                        spec_content = content
                        filename = fname
                        break
                    if spec_content:
                        break
        else:
            # Fallback: generate spec directly
            spec_content, filename = _generate_fallback_spec(flow, base_url)

        flow_title = flow.get("title", "Unnamed Flow")

        # Prepare the spec data
        spec_result = {
            "spec_content": spec_content,
            "filename": filename or f"{flow_title.lower().replace(' ', '_')}.md",
            "flow_title": flow_title,
            "summary": spec_data.get("summary", f"Generated test spec for {flow_title}"),
            "generated_at": datetime.now().isoformat(),
            "cached": False,
        }

        # Save generated spec to flows.json for caching
        flow["generated_spec"] = {
            "spec_content": spec_result["spec_content"],
            "filename": spec_result["filename"],
            "generated_at": spec_result["generated_at"],
        }

        # Update the flow in the flows list
        for i, f in enumerate(flows):
            if f.get("id") == flow.get("id"):
                flows[i] = flow
                break

        # Write back to flows.json
        updated_json = json.dumps({"flows": flows}, indent=2)
        await asyncio.to_thread(flows_file.write_text, updated_json)

        return spec_result

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse flows.json file")
    except Exception as e:
        logger.error(f"Error generating spec: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


def _build_single_flow_prompt(flow: dict[str, Any], base_url: str) -> str:
    """Build a synthesis prompt for generating a spec from a single flow."""
    flow_title = flow.get("title", "Unnamed Flow")
    happy_path = flow.get("happy_path", "")
    pages = flow.get("pages", [])
    edge_cases = flow.get("edge_cases", [])
    test_ideas = flow.get("test_ideas", [])
    entry = flow.get("entry_point", "")
    exit_point = flow.get("exit_point", "")

    # Get prerequisites (if analyzed)
    prerequisites = flow.get("prerequisites", {})
    produces = flow.get("produces", {})
    dependency_reason = flow.get("dependency_reason", "")

    # Build flow description
    flow_desc = f"\nFLOW: {flow_title}\n"
    flow_desc += f"Description: {happy_path}\n"
    if pages:
        flow_desc += f"Pages visited: {' → '.join(pages)}\n"
    if entry:
        flow_desc += f"Entry point: {entry}\n"
    if exit_point:
        flow_desc += f"Exit point: {exit_point}\n"
    if edge_cases:
        flow_desc += f"Edge cases: {', '.join(edge_cases[:5])}\n"
    if test_ideas:
        flow_desc += f"Test ideas: {', '.join(test_ideas[:3])}\n"

    # Build prerequisites section
    prereq_section = ""
    if prerequisites:
        prereq_section = "\n## PREREQUISITES (CRITICAL - Include in spec)\n"

        # Authentication
        auth = prerequisites.get("authentication", {})
        if auth.get("required"):
            prereq_section += "\n### Authentication Required:\n"
            prereq_section += f"- User type: {auth.get('user_type', 'standard user')}\n"
            prereq_section += f"- Login URL: {auth.get('login_url', '/login')}\n"
            if auth.get("permissions"):
                prereq_section += f"- Permissions: {', '.join(auth.get('permissions', []))}\n"

        # Data requirements
        data_reqs = prerequisites.get("data_requirements", [])
        if data_reqs:
            prereq_section += "\n### Data Requirements:\n"
            for req in data_reqs:
                entity = req.get("entity", "unknown")
                state = req.get("state", "exists")
                desc = req.get("description", f"{entity} must {state}")
                prereq_section += f"- {desc}\n"

        # Prior flows
        prior_flows = prerequisites.get("prior_flows", [])
        if prior_flows:
            prereq_section += "\n### Prior Flows Required:\n"
            prereq_section += f"- Must complete: {', '.join(prior_flows)}\n"
            if dependency_reason:
                prereq_section += f"- Reason: {dependency_reason}\n"

        # Application state
        app_state = prerequisites.get("application_state", {})
        if app_state.get("starting_page"):
            prereq_section += "\n### Application State:\n"
            prereq_section += f"- Starting page: {app_state.get('starting_page')}\n"
            if app_state.get("required_state"):
                prereq_section += f"- Required state: {app_state.get('required_state')}\n"

        # Setup steps
        setup_steps = prerequisites.get("setup_steps", [])
        if setup_steps:
            prereq_section += "\n### Setup Steps (include these BEFORE main test steps):\n"
            for i, step in enumerate(setup_steps, 1):
                prereq_section += f"{i}. {step}\n"

    # Build produces section
    produces_section = ""
    if produces:
        entities = produces.get("entities", [])
        enables = produces.get("enables_flows", [])
        if entities or enables:
            produces_section = "\n## WHAT THIS FLOW PRODUCES:\n"
            if entities:
                produces_section += f"- Creates: {', '.join(entities)}\n"
            if enables:
                produces_section += f"- Enables flows: {', '.join(enables)}\n"

    return f"""You are a Test Specification Generator.

Generate COMPREHENSIVE individual .md E2E scenario specs for the following discovered user flow.

{flow_desc}
{prereq_section}
{produces_section}

REQUIREMENTS:
1. Return one runnable spec per scenario. Use balanced E2E coverage where evidence supports it:
   - happy path
   - navigation/state transition
   - negative/error
   - edge case
   - accessibility
   - responsive/mobile or critical console-error regression

2. Follow this EXACT spec format for each file:
   ```markdown
   # Test: [Feature Name] - [Scenario Name]

   ## Description
   [Brief description of what this tests]

   ## Prerequisites
   [List all prerequisites - authentication, data, prior flows, etc.]
   - Authentication: [Required/Not required, user type]
   - Data: [What data must exist before running]
   - Prior flows: [What flows must complete first]

   ## Steps
   1. [Setup step - e.g., Login as user type]
   2. [Setup step - e.g., Navigate to starting page]
   3. [Main test step]
   4. [Continue with actual test actions]
   ...
   N. Assert [expected outcome]

   ## Expected Outcome
   - [Expected result 1]
   - [Expected result 2]

   ## Test Data
   - [Any test data requirements]
   ```

3. CRITICAL RULES:
   - **ALWAYS include Prerequisites section** - even if minimal
   - **Setup steps come FIRST** in the Steps section
   - Parse the happy_path description into specific, actionable steps
   - Don't use placeholders like "Complete step X" - use actual actions
   - Include specific URLs and element descriptions based on the flow
   - Use placeholders `{{{{VAR_NAME}}}}` for secrets/passwords
   - If authentication is required, include login steps at the beginning
   - If data requirements exist, mention them in Prerequisites
   - Do not invent unsupported business behavior; if evidence is thin, use conservative page/journey checks

OUTPUT FORMAT (return ONLY JSON):
```json
{{
  "specs": {{
    "happy_path": {{
      "tc-001-{flow_title.lower().replace(" ", "_").replace("/", "_")}-happy-path.md": "# Test: {flow_title} - Happy Path\\n\\n## Description\\n...\\n\\n## Prerequisites\\n...\\n\\n## Steps\\n..."
    }},
    "edge_case": {{
      "tc-002-{flow_title.lower().replace(" ", "_").replace("/", "_")}-edge-case.md": "# Test: {flow_title} - Edge Case\\n\\n## Description\\n..."
    }}
  }},
  "summary": "Generated individual E2E scenario specs for {flow_title}"
}}
```

Now generate the test spec."""


def _generate_fallback_spec(flow: dict[str, Any], base_url: str) -> tuple[str, str]:
    """Generate a basic spec as fallback when agent fails."""
    import re

    from orchestrator.workflows.spec_scenario_builder import render_scenario_markdown, scenario_from_requirement

    flow_title = flow.get("title", "Unnamed Flow")
    happy_path = flow.get("happy_path", "")
    pages = flow.get("pages", [])
    entry = flow.get("entry_point", "")
    exit_point = flow.get("exit_point", "")

    # Get prerequisites (if analyzed)
    prerequisites = flow.get("prerequisites", {})

    preconditions = []
    if prerequisites:
        auth = prerequisites.get("authentication", {})
        if auth.get("required"):
            preconditions.append(f"Authentication required ({auth.get('user_type', 'standard user')})")
        else:
            preconditions.append("Authentication not required")

        data_reqs = prerequisites.get("data_requirements", [])
        if data_reqs:
            for req in data_reqs:
                preconditions.append(f"Data: {req.get('description', req.get('entity', 'unknown'))}")

        prior_flows = prerequisites.get("prior_flows", [])
        if prior_flows:
            preconditions.append(f"Prior flows: {', '.join(prior_flows)}")

    # Parse happy path into steps
    steps = []

    # Add setup steps from prerequisites first
    setup_steps = prerequisites.get("setup_steps", [])
    for setup_step in setup_steps:
        steps.append(str(setup_step))

    # Entry point (only if no setup steps included navigation)
    if not any("navigate" in s.lower() for s in setup_steps):
        if entry:
            destination = entry if str(entry).startswith(("http://", "https://")) else f"{{{{BASE_URL}}}}{entry}"
            steps.append(f"Navigate to {destination}")
        elif pages:
            steps.append(f"Navigate to {pages[0]}")

    # Parse happy path description for actionable steps
    if happy_path:
        # Split by common delimiters and create steps
        actions = re.split(r"[,.]", happy_path)
        for action in actions:
            action = action.strip()
            if action and len(action) > 5:  # Skip short fragments
                # Convert to imperative form
                if not action.startswith(("Navigate", "Click", "Fill", "Verify", "Check", "Select", "Assert")):
                    # Just add the action as-is
                    steps.append(action)

    # Exit point
    if exit_point:
        destination = (
            exit_point
            if str(exit_point).startswith(("http://", "https://"))
            else f"{{{{BASE_URL}}}}{exit_point}"
        )
        steps.append(f"Verify arrival at {destination}")
    else:
        steps.append("Verify successful completion")

    edge_cases = flow.get("edge_cases", [])
    expected = [
        f"User successfully completes the {flow_title}",
        "All pages load correctly",
        "No blocking errors are displayed",
    ]
    if edge_cases:
        expected.append("Known edge cases are handled safely or documented for separate coverage")

    scenario = scenario_from_requirement(
        title=flow_title,
        description=happy_path or f"Validate the {flow_title} flow.",
        target_url=entry or base_url,
        flow_steps=steps,
        acceptance_criteria=expected,
        category="happy_path",
        priority="medium",
        source_flows=[flow_title],
    )
    scenario.preconditions = preconditions or ["Fresh browser session"]
    scenario.test_data.append("Base URL: {{BASE_URL}}")
    if edge_cases:
        scenario.test_data.extend(f"Edge case to cover separately: {case}" for case in edge_cases[:5])
    spec_content = render_scenario_markdown(scenario)

    # Generate filename
    safe_name = re.sub(r"[^\w\s-]", "", flow_title)
    safe_name = re.sub(r"[-\s]+", "_", safe_name)
    safe_name = safe_name.lower().strip("_")
    filename = f"{safe_name}.md"

    return spec_content, filename


# =============================================================================
# Native Pipeline Flow Generation
# =============================================================================


def _requires_authentication(url: str) -> bool:
    """Check if URL pattern typically requires authentication."""
    auth_patterns = [
        "/user/",
        "/admin/",
        "/dashboard",
        "/account/",
        "/my_",
        "/settings",
        "/profile",
        "/billing",
        "/itinerary",
        "/trips",
        "/bookings",
    ]
    return any(pattern in url.lower() for pattern in auth_patterns)


def _detect_login_url(target_url: str) -> str:
    """Detect login URL based on target domain."""
    from urllib.parse import urlparse

    parsed = urlparse(target_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    # Map domains to login URLs
    login_url_map = {
        "myapp.example.com": "/users/sign_in",
        "pre.myapp.example.com": "/users/sign_in",
    }

    for domain_pattern, login_path in login_url_map.items():
        if domain_pattern in parsed.netloc:
            return f"{base}{login_path}"

    # Default: assume /login
    return f"{base}/login"


def _is_login_page(url: str) -> bool:
    """Check if URL is a login page itself."""
    login_patterns = ["/login", "/signin", "/sign_in", "/sign-in", "/auth"]
    return any(pattern in url.lower() for pattern in login_patterns)


def _extract_domain_name(url: str) -> str:
    """Extract a clean domain name from URL for folder naming."""
    import re
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        # Remove common prefixes
        hostname = re.sub(r"^(www\.|pre\.|staging\.|dev\.|test\.)", "", hostname)
        # Get the main domain part (before TLD)
        parts = hostname.split(".")
        if len(parts) >= 2:
            return parts[0]  # e.g., 'myapp' from 'myapp.example.com'
        return hostname or "unknown"
    except Exception as e:
        logger.debug(f"URL parse failed for hostname extraction: {e}")
        return "unknown"


def _slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    import re

    # Convert to lowercase
    slug = text.lower()
    # Replace spaces and underscores with hyphens
    slug = re.sub(r"[\s_]+", "-", slug)
    # Remove special characters
    slug = re.sub(r"[^\w\-]", "", slug)
    # Remove multiple consecutive hyphens
    slug = re.sub(r"-+", "-", slug)
    # Trim hyphens from ends
    slug = slug.strip("-")
    # Limit length
    return slug[:50] if len(slug) > 50 else slug


# ========== Flow Spec Generation Job Tracking ==========
_flow_spec_jobs: dict[str, dict] = {}
MAX_FLOW_SPEC_JOBS = 100


def _cleanup_flow_spec_jobs():
    """Remove completed/failed jobs older than 1 hour, enforce cap."""
    import time as _time

    now = _time.time()
    to_remove = []
    for job_id, job in _flow_spec_jobs.items():
        if job["status"] in ("completed", "failed"):
            completed_at = job.get("completed_at", 0)
            if now - completed_at > 3600:
                to_remove.append(job_id)
    for job_id in to_remove:
        del _flow_spec_jobs[job_id]
    if len(_flow_spec_jobs) > MAX_FLOW_SPEC_JOBS:
        evictable = sorted(
            [(jid, j) for jid, j in _flow_spec_jobs.items() if j["status"] != "running"],
            key=lambda x: x[1].get("started_at", 0),
        )
        for job_id, _ in evictable[: len(_flow_spec_jobs) - MAX_FLOW_SPEC_JOBS]:
            del _flow_spec_jobs[job_id]


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
    """Background task: run Native Planner to generate spec for a flow."""
    import os
    import sys
    from datetime import datetime
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from load_env import setup_claude_env
    from workflows.native_planner import NativePlanner

    try:
        setup_claude_env()
        project_root = Path(__file__).parent.parent.parent
        flows_file = Path(flows_file_path)
        spec_run_dir = RUNS_DIR / spec_agent_run_id if spec_agent_run_id else None
        if spec_run_dir:
            await asyncio.to_thread(spec_run_dir.mkdir, parents=True, exist_ok=True)
            storage_state_path = _resolve_agent_browser_auth_storage_path(
                run_id=spec_agent_run_id,
                project_id=run_project_id or run_config.get("project_id"),
                config=run_config,
                run_dir=spec_run_dir,
            )
            mcp_runtime = await asyncio.to_thread(
                _prepare_spec_generation_mcp_config,
                spec_run_dir,
                storage_state_path,
            )
            if spec_agent_run_id:
                _update_agent_run_progress(
                    spec_agent_run_id,
                    {
                        "phase": "browser_setup",
                        "message": "Prepared browser MCP runtime for spec generation.",
                        "has_browser_tools": True,
                        **_spec_generation_auth_metadata(run_config),
                        **mcp_runtime,
                    },
                )

        _flow_spec_jobs[job_id]["message"] = "Preparing flow context..."
        if spec_agent_run_id:
            _update_agent_run_progress(
                spec_agent_run_id,
                {
                    "phase": "preparing",
                    "message": "Preparing flow context...",
                    "has_browser_tools": True,
                    **browser_runtime_status(),
                },
            )

        # Extract flow context
        flow_title = flow.get("title", "Unnamed Flow")
        entry_point = flow.get("entry_point") or (flow.get("pages", [""])[0] if flow.get("pages") else "")
        exit_point = flow.get("exit_point", "")
        happy_path = flow.get("happy_path", "")
        edge_cases = flow.get("edge_cases", [])
        test_ideas = flow.get("test_ideas", [])

        if not entry_point:
            raise ValueError("Flow must have an entry_point or at least one page")

        # Resolve relative entry_point against exploration run's base URL
        if entry_point.startswith("/"):
            base_url = run_config.get("url", "")
            if base_url:
                from urllib.parse import urlparse

                parsed = urlparse(base_url)
                base_origin = f"{parsed.scheme}://{parsed.netloc}"
                entry_point = f"{base_origin}{entry_point}"
                logger.info(f"Resolved relative entry_point to: {entry_point}")

        # Detect if authentication is needed
        requires_auth = _requires_authentication(entry_point)
        if _is_login_page(entry_point):
            requires_auth = False

        credentials = None
        login_url = None
        if requires_auth:
            credentials = {"username": os.getenv("LOGIN_USERNAME", ""), "password": os.getenv("LOGIN_PASSWORD", "")}
            login_url = _detect_login_url(entry_point)
            if not credentials.get("username") or not credentials.get("password"):
                logger.warning("Auth required but credentials not set in environment")

        flow_context = f"""## Flow: {flow_title}

### Description
{happy_path if happy_path else f"Test the {flow_title} user flow."}

### Target URL
{entry_point}

### Expected End State
{exit_point if exit_point else "Flow completes successfully"}

### Edge Cases to Consider
{chr(10).join(f"- {ec}" for ec in edge_cases[:5]) if edge_cases else "- None specified"}

### Test Ideas
{chr(10).join(f"- {idea}" for idea in test_ideas[:5]) if test_ideas else "- Test the happy path"}
"""
        auth_metadata = _spec_generation_auth_metadata(run_config)
        if auth_metadata.get("browser_auth_session_id") or auth_metadata.get("use_project_default_browser_auth"):
            session_name = auth_metadata.get("browser_auth_session_name") or auth_metadata.get("browser_auth_session_id") or "selected session"
            flow_context += (
                "\n## Browser Authentication Context\n"
                f"The browser starts authenticated with saved session `{session_name}`. "
                "Do not generate login steps unless the scenario explicitly tests login, logout, or authentication failure.\n"
            )

        # Run Native Planner
        _flow_spec_jobs[job_id]["message"] = "Running Native Planner (browser exploration)..."
        logger.info(f"Starting Native Planner for flow: {flow_title}")
        if spec_run_dir and not await asyncio.to_thread((spec_run_dir / ".mcp.json").exists):
            raise RuntimeError(f"Spec generation setup failed: missing browser MCP config at {spec_run_dir / '.mcp.json'}")

        domain_name = _extract_domain_name(entry_point)
        flow_slug = _slugify(flow_title)
        folder_name = f"explorer-{domain_name}-{flow_slug}"

        effective_project_id = run_project_id if run_project_id else folder_name

        def _on_planner_task_enqueued(agent_task_id: str) -> None:
            _flow_spec_jobs[job_id]["agent_task_id"] = agent_task_id
            if spec_agent_run_id:
                _update_agent_run_progress(spec_agent_run_id, {"agent_task_id": agent_task_id})

        def _on_planner_tool_use(tool_name: str, tool_input: dict[str, Any]) -> None:
            _flow_spec_jobs[job_id]["message"] = f"Using {_short_tool_name(tool_name)}..."
            if not spec_agent_run_id:
                return
            runtime = browser_runtime_status()
            is_browser_action = str(tool_name).startswith("mcp__playwright")
            _update_agent_run_progress(
                spec_agent_run_id,
                {
                    "phase": "tool_use",
                    "message": f"Using {_short_tool_name(tool_name)}",
                    "last_tool": tool_name,
                    "last_tool_input": tool_input,
                    "has_browser_tools": True,
                    **runtime,
                },
            )
            _record_agent_run_event(
                spec_agent_run_id,
                event_type="browser_action" if is_browser_action else "tool_call",
                message=f"Using {_short_tool_name(tool_name)}.",
                payload={
                    "tool_name": tool_name,
                    "tool_label": _short_tool_name(tool_name),
                    "tool_input": tool_input,
                    "source_run_id": run_id,
                    "source_flow_id": flow_id,
                },
            )

        def _on_planner_progress(progress: dict[str, Any]) -> None:
            if not spec_agent_run_id:
                return
            last_tool = progress.get("last_tool")
            _update_agent_run_progress(
                spec_agent_run_id,
                {
                    **progress,
                    "phase": progress.get("phase") or "running",
                    "message": f"Using {_short_tool_name(str(last_tool))}" if last_tool else "Native Planner is exploring the browser",
                    "has_browser_tools": True,
                    **browser_runtime_status(),
                },
            )

        planner = NativePlanner(
            project_id=effective_project_id,
            on_tool_use=_on_planner_tool_use,
            on_progress=_on_planner_progress,
            on_task_enqueued=_on_planner_task_enqueued,
            owner_type="agent_run" if spec_agent_run_id else None,
            owner_id=spec_agent_run_id,
            owner_label=f"Spec generation {flow_title}" if spec_agent_run_id else None,
            session_dir=spec_run_dir,
            cwd=spec_run_dir,
        )
        output_dir = project_root / "specs" / folder_name

        spec_path = await planner.generate_spec_from_flow_context(
            flow_title=flow_title,
            flow_context=flow_context,
            target_url=entry_point,
            login_url=login_url,
            credentials=credentials,
            output_dir=output_dir,
        )

        spec_exists = await asyncio.to_thread(spec_path.exists)
        spec_content = await asyncio.to_thread(spec_path.read_text) if spec_exists else None

        if not spec_content:
            raise RuntimeError("Native Planner failed to generate spec")

        logger.info(f"Native Planner created spec: {spec_path}")

        # Register spec in database
        _flow_spec_jobs[job_id]["message"] = "Registering spec..."
        if spec_agent_run_id:
            _update_agent_run_progress(
                spec_agent_run_id,
                {
                    "phase": "registering",
                    "message": "Registering generated spec...",
                    "has_browser_tools": True,
                    **browser_runtime_status(),
                },
            )
        try:
            from sqlmodel import Session as SyncSession

            with SyncSession(engine) as db_session:
                spec_name = str(spec_path.relative_to(project_root / "specs"))
                existing_meta = get_db_spec_metadata(db_session, spec_name, effective_project_id)
                if not existing_meta:
                    meta = DBSpecMetadata(spec_name=spec_name, project_id=effective_project_id, tags_json="[]")
                    db_session.add(meta)
                db_session.commit()
                logger.info(f"Registered spec in DB: {spec_name} (project: {effective_project_id})")
        except Exception as e:
            logger.warning(f"Failed to register spec in DB: {e}")

        logger.info(f"Spec generation complete for: {flow_title}")

        # Cache result in flows.json
        generated_at = datetime.now().isoformat()
        flow["generated_test"] = {
            "spec_file": str(spec_path),
            "spec_content": spec_content,
            "test_file": None,
            "test_code": None,
            "generated_at": generated_at,
            "validated": False,
            "requires_auth": requires_auth,
            "pipeline": "native_planner_generator",
        }

        for i, f in enumerate(flows):
            if f.get("id") == flow.get("id"):
                flows[i] = flow
                break

        updated_json = json.dumps({"flows": flows}, indent=2)
        await asyncio.to_thread(flows_file.write_text, updated_json)

        import time as _time

        _flow_spec_jobs[job_id].update(
            {
                "status": "completed",
                "message": "Spec generation complete",
                "completed_at": _time.time(),
                "result": {
                    "status": "success",
                    "spec_file": str(spec_path),
                    "spec_content": spec_content,
                    "test_file": None,
                    "test_code": None,
                    "validated": False,
                    "flow_title": flow_title,
                    "requires_auth": requires_auth,
                    "pipeline": "native_planner_generator",
                    "cached": False,
                    "generated_at": generated_at,
                },
            }
        )
        if spec_agent_run_id:
            with Session(engine) as db_session:
                spec_run = db_session.get(AgentRun, spec_agent_run_id)
                if spec_run:
                    spec_run.status = "completed"
                    spec_run.completed_at = datetime.utcnow()
                    spec_run.result = {
                        "summary": f"Generated spec for {flow_title}",
                        "spec_file": str(spec_path),
                        "spec_content": spec_content,
                        "source_run_id": run_id,
                        "source_flow_id": flow_id,
                        "pipeline": "native_planner_generator",
                    }
                    spec_run.progress = {
                        **(spec_run.progress or {}),
                        "phase": "completed",
                        "status": "completed",
                        "message": "Spec generation complete",
                        "has_browser_tools": True,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    db_session.add(spec_run)
                    db_session.commit()
            _record_agent_run_event(
                spec_agent_run_id,
                event_type="completed",
                message="Spec generation complete.",
                payload={"spec_file": str(spec_path), "source_run_id": run_id, "source_flow_id": flow_id},
            )

    except Exception as e:
        import time as _time

        logger.error(f"Flow spec generation failed: {e}", exc_info=True)
        _flow_spec_jobs[job_id].update(
            {
                "status": "failed",
                "message": str(e),
                "completed_at": _time.time(),
            }
        )
        if spec_agent_run_id:
            with Session(engine) as db_session:
                spec_run = db_session.get(AgentRun, spec_agent_run_id)
                if spec_run:
                    spec_run.status = "failed"
                    spec_run.completed_at = datetime.utcnow()
                    spec_run.result = {"error": str(e), "source_run_id": run_id, "source_flow_id": flow_id}
                    spec_run.progress = {
                        **(spec_run.progress or {}),
                        "phase": "failed",
                        "status": "failed",
                        "message": str(e),
                        "has_browser_tools": True,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    db_session.add(spec_run)
                    db_session.commit()
            _record_agent_run_event(
                spec_agent_run_id,
                event_type="failed",
                level="error",
                message=str(e),
                payload={"source_run_id": run_id, "source_flow_id": flow_id},
            )


# NOTE: Status endpoint must be defined BEFORE /{run_id} routes to avoid path conflicts
async def get_flow_spec_job_status(job_id: str):
    """Get status of a flow spec generation job."""
    job = _flow_spec_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    response = {
        "job_id": job_id,
        "status": job["status"],
        "message": job.get("message"),
        "agent_run_id": job.get("agent_run_id"),
        "agent_task_id": job.get("agent_task_id"),
        "result": job.get("result"),
    }
    agent_run_id = job.get("agent_run_id")
    if agent_run_id:
        with Session(engine) as db_session:
            spec_run = db_session.get(AgentRun, agent_run_id)
            if spec_run:
                response["agent_run"] = _serialize_agent_run(spec_run, db_session)
    return response


async def generate_report_item_spec(
    run_id: str,
    item_id: str,
    item_type: str | None = Query(default=None, description="finding or test_idea"),
    project_id: str = Query(..., description="Project ID for verification"),
    request_body: GenerateReportItemSpecRequest | None = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: Session = Depends(get_session),
):
    """Generate a browser-backed spec from a custom agent finding or test idea."""
    import time as _time

    source_run = _get_agent_report_run(session, run_id, project_id)

    result = source_run.result or {}
    report = result.get("structured_report") if isinstance(result, dict) else None
    if not isinstance(report, dict):
        raise HTTPException(status_code=400, detail="This run does not have a structured report")

    normalized_type = (item_type or "").strip().lower()
    candidates: list[tuple[str, dict[str, Any]]] = []
    if normalized_type in ("", "finding", "findings"):
        candidates.extend(("finding", item) for item in report.get("findings") or [] if isinstance(item, dict))
    if normalized_type in ("", "test_idea", "test_ideas", "test idea"):
        candidates.extend(("test_idea", item) for item in report.get("test_ideas") or [] if isinstance(item, dict))

    matched = next(((kind, item) for kind, item in candidates if str(item.get("id")) == item_id), None)
    if not matched:
        raise HTTPException(status_code=404, detail=f"Report item {item_id} not found")

    kind, item = matched
    base_url = str(source_run.config.get("url") or "").strip()
    target_url = str(item.get("page") or base_url or "").strip()
    if not target_url:
        raise HTTPException(status_code=400, detail="This report item has no page URL to explore")

    title = str(item.get("title") or item_id)
    steps = item.get("steps") if isinstance(item.get("steps"), list) else []
    happy_path = "\n".join(str(step) for step in steps) if steps else str(item.get("description") or title)
    evidence = str(item.get("evidence") or item.get("expected") or "").strip()

    flow = {
        "id": item_id,
        "title": title,
        "entry_point": target_url,
        "exit_point": target_url,
        "pages": [target_url],
        "happy_path": happy_path,
        "edge_cases": [evidence] if evidence and kind == "finding" else [],
        "test_ideas": [evidence] if evidence and kind == "test_idea" else [f"Create a regression spec for {item_id}"],
    }

    _cleanup_flow_spec_jobs()
    job_id = f"reportspec-{run_id}-{item_id}-{uuid.uuid4().hex[:8]}"
    spec_agent_run_id = job_id
    spec_run_dir = RUNS_DIR / spec_agent_run_id
    await asyncio.to_thread(spec_run_dir.mkdir, parents=True, exist_ok=True)
    flows_file = spec_run_dir / "source-flow.json"

    source_config = source_run.config or {}
    run_project_id = source_run.project_id or project_id or source_config.get("project_id")
    inherited_run_config = _build_spec_generation_source_config(
        source_config,
        target_url=base_url or target_url,
        project_id=run_project_id,
    )
    inherited_run_config, browser_auth_inherited = _apply_report_spec_browser_auth_request(
        inherited_run_config,
        request_body,
    )
    auth_metadata = _spec_generation_auth_metadata(inherited_run_config, inherited=browser_auth_inherited)
    spec_agent_run = AgentRun(
        id=spec_agent_run_id,
        agent_type="spec_generation",
        runtime="claude_sdk",
        status="running",
        started_at=datetime.utcnow(),
        project_id=run_project_id,
    )
    spec_agent_run.config = {
        "source": "custom_agent_report",
        "source_run_id": run_id,
        "source_item_id": item_id,
        "source_item_type": kind,
        "flow_title": title,
        "project_id": run_project_id,
        "url": target_url,
        "source_url": inherited_run_config.get("url"),
        "allowed_tools": [],
        **{key: inherited_run_config[key] for key in ("auth", "browser_auth") if key in inherited_run_config},
        **auth_metadata,
    }
    spec_agent_run.progress = {
        "phase": "queued",
        "status": "running",
        "message": "Starting Native Planner spec generation...",
        "has_browser_tools": True,
        **auth_metadata,
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.add(spec_agent_run)
    session.commit()
    _record_agent_run_event(
        spec_agent_run_id,
        event_type="started",
        message="Started Native Planner spec generation.",
        payload={"source_run_id": run_id, "source_item_id": item_id, "source_item_type": kind},
        session=session,
    )

    _flow_spec_jobs[job_id] = {
        "status": "running",
        "message": "Starting spec generation...",
        "started_at": _time.time(),
        "run_id": run_id,
        "flow_id": item_id,
        "agent_run_id": spec_agent_run_id,
    }

    try:
        storage_state_path = _resolve_agent_browser_auth_storage_path(
            run_id=spec_agent_run_id,
            project_id=run_project_id,
            config=inherited_run_config,
            run_dir=spec_run_dir,
        )
        mcp_runtime = await asyncio.to_thread(
            _prepare_spec_generation_mcp_config,
            spec_run_dir,
            storage_state_path,
        )
        session.refresh(spec_agent_run)
        spec_agent_run.config = {
            **(spec_agent_run.config or {}),
            "allowed_tools": get_agent_allowed_tools("playwright-test-planner", mcp_config_dir=spec_run_dir),
        }
        spec_agent_run.progress = {
            **(spec_agent_run.progress or {}),
            "phase": "queued",
            "status": "running",
            "message": "Starting Native Planner spec generation...",
            "has_browser_tools": True,
            **auth_metadata,
            **mcp_runtime,
            "updated_at": datetime.utcnow().isoformat(),
        }
        session.add(spec_agent_run)
        session.commit()
    except RuntimeError as exc:
        import time as _time

        message = str(exc)
        failure_metadata: dict[str, Any] = {}
        if isinstance(exc, AgentBrowserAuthResolutionError):
            action_message = (
                "Selected browser auth session is revoked or invalid. "
                "Choose an active session or generate without auth."
            )
            failure_metadata = {
                "browser_auth_failure": True,
                "browser_auth_error": message,
                "message": action_message,
            }
            if exc.browser_auth_session_id:
                failure_metadata["browser_auth_session_id"] = exc.browser_auth_session_id
            message = action_message
        session.refresh(spec_agent_run)
        spec_agent_run.status = "failed"
        spec_agent_run.completed_at = datetime.utcnow()
        spec_agent_run.result = {
            "error": message,
            "source_run_id": run_id,
            "source_item_id": item_id,
            **failure_metadata,
        }
        spec_agent_run.progress = {
            **(spec_agent_run.progress or {}),
            "phase": "failed",
            "status": "failed",
            "message": message,
            "has_browser_tools": True,
            **auth_metadata,
            **failure_metadata,
            "updated_at": datetime.utcnow().isoformat(),
        }
        session.add(spec_agent_run)
        session.commit()
        _flow_spec_jobs[job_id].update({"status": "failed", "message": message, "completed_at": _time.time()})
        _record_agent_run_event(
            spec_agent_run_id,
            event_type="failed",
            level="error",
            message=message,
            payload={"source_run_id": run_id, "source_item_id": item_id, "source_item_type": kind},
            session=session,
        )
        return {
            "status": "failed",
            "job_id": job_id,
            "agent_run_id": spec_agent_run_id,
            "message": message,
        }

    background_tasks.add_task(
        _run_flow_spec_generation,
        job_id=job_id,
        run_id=run_id,
        flow_id=item_id,
        flow=flow,
        flows=[flow],
        flows_file_path=str(flows_file),
        run_project_id=run_project_id,
        run_config=inherited_run_config,
        spec_agent_run_id=spec_agent_run_id,
    )

    return {
        "status": "running",
        "job_id": job_id,
        "agent_run_id": spec_agent_run_id,
        "message": "Spec generation started. Poll for status.",
    }


async def generate_flow_test(
    run_id: str,
    flow_id: str,
    force_regenerate: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    request_body: GenerateFlowTestRequest | None = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: Session = Depends(get_session),
):
    """
    Generate a validated test for a flow using Native Planner + Generator pipeline.

    Returns immediately with a job_id for polling. Cached results are returned inline.
    """
    import time as _time
    from pathlib import Path

    # Verify exploration run belongs to project
    _verify_exploration_run_project(run_id, project_id, session)

    flows_file = RUNS_DIR / run_id / "flows.json"

    if not await asyncio.to_thread(flows_file.exists):
        raise HTTPException(status_code=404, detail=f"Flows file not found for run {run_id}")

    try:
        raw = await asyncio.to_thread(flows_file.read_text)
        data = json.loads(raw)

        flows = data.get("flows", [])

        # Get project_id from parent exploration run for proper isolation
        exploration_run = session.get(AgentRun, run_id)
        run_config = json.loads(exploration_run.config_json) if exploration_run and exploration_run.config_json else {}
        run_project_id = exploration_run.project_id or project_id or run_config.get("project_id")

        # Find the requested flow
        flow = next((f for f in flows if f.get("id") == flow_id), None)

        if not flow and flow_id.startswith("flow_"):
            try:
                index = int(flow_id.split("_")[1]) - 1
                if 0 <= index < len(flows):
                    flow = flows[index]
            except (ValueError, IndexError):
                pass

        if not flow:
            raise HTTPException(status_code=404, detail=f"Flow {flow_id} not found")

        inherited_run_config = _build_spec_generation_source_config(
            run_config,
            target_url=flow.get("entry_point") or "",
            project_id=run_project_id,
        )
        inherited_run_config, _ = _apply_report_spec_browser_auth_request(inherited_run_config, request_body)

        # Check for cached result (unless force_regenerate)
        if not force_regenerate and "generated_test" in flow:
            cached = flow["generated_test"]
            spec_file = cached.get("spec_file")
            if spec_file and Path(spec_file).exists():
                return {
                    "status": "success",
                    "cached": True,
                    "spec_file": spec_file,
                    "spec_content": cached.get("spec_content"),
                    "test_file": cached.get("test_file"),
                    "test_code": cached.get("test_code"),
                    "validated": cached.get("validated", False),
                    "flow_title": flow.get("title", "Unnamed Flow"),
                    "requires_auth": cached.get("requires_auth", False),
                    "pipeline": cached.get("pipeline", "native_planner_generator"),
                    "generated_at": cached.get("generated_at"),
                }

        # Fire-and-return: launch background generation
        _cleanup_flow_spec_jobs()
        job_id = f"flowspec-{run_id}-{flow_id}-{uuid.uuid4().hex[:8]}"
        spec_agent_run_id = job_id

        spec_run_dir = RUNS_DIR / spec_agent_run_id
        await asyncio.to_thread(spec_run_dir.mkdir, parents=True, exist_ok=True)
        auth_metadata = _spec_generation_auth_metadata(inherited_run_config)
        spec_agent_run = AgentRun(
            id=spec_agent_run_id,
            agent_type="spec_generation",
            runtime="claude_sdk",
            status="running",
            started_at=datetime.utcnow(),
            project_id=run_project_id,
        )
        spec_agent_run.config = {
            "source": "exploratory_flow",
            "source_run_id": run_id,
            "source_flow_id": flow_id,
            "flow_title": flow.get("title", "Unnamed Flow"),
            "project_id": run_project_id,
            "url": flow.get("entry_point") or inherited_run_config.get("url"),
            "source_url": inherited_run_config.get("url"),
            "allowed_tools": [],
            **{key: inherited_run_config[key] for key in ("auth", "browser_auth") if key in inherited_run_config},
            **auth_metadata,
        }
        spec_agent_run.progress = {
            "phase": "queued",
            "status": "running",
            "message": "Starting Native Planner spec generation...",
            "has_browser_tools": True,
            **auth_metadata,
            "updated_at": datetime.utcnow().isoformat(),
        }
        session.add(spec_agent_run)
        session.commit()
        _record_agent_run_event(
            spec_agent_run_id,
            event_type="started",
            message="Started Native Planner spec generation.",
            payload={"source_run_id": run_id, "source_flow_id": flow_id, "flow_title": flow.get("title")},
            session=session,
        )

        _flow_spec_jobs[job_id] = {
            "status": "running",
            "message": "Starting spec generation...",
            "started_at": _time.time(),
            "run_id": run_id,
            "flow_id": flow_id,
            "agent_run_id": spec_agent_run_id,
        }

        try:
            storage_state_path = _resolve_agent_browser_auth_storage_path(
                run_id=spec_agent_run_id,
                project_id=run_project_id,
                config=inherited_run_config,
                run_dir=spec_run_dir,
            )
            mcp_runtime = await asyncio.to_thread(
                _prepare_spec_generation_mcp_config,
                spec_run_dir,
                storage_state_path,
            )
            session.refresh(spec_agent_run)
            spec_agent_run.config = {
                **(spec_agent_run.config or {}),
                "allowed_tools": get_agent_allowed_tools("playwright-test-planner", mcp_config_dir=spec_run_dir),
            }
            spec_agent_run.progress = {
                **(spec_agent_run.progress or {}),
                "phase": "queued",
                "status": "running",
                "message": "Starting Native Planner spec generation...",
                "has_browser_tools": True,
                **auth_metadata,
                **mcp_runtime,
                "updated_at": datetime.utcnow().isoformat(),
            }
            session.add(spec_agent_run)
            session.commit()
        except RuntimeError as exc:
            message = str(exc)
            session.refresh(spec_agent_run)
            spec_agent_run.status = "failed"
            spec_agent_run.completed_at = datetime.utcnow()
            spec_agent_run.result = {"error": message, "source_run_id": run_id, "source_flow_id": flow_id}
            spec_agent_run.progress = {
                **(spec_agent_run.progress or {}),
                "phase": "failed",
                "status": "failed",
                "message": message,
                "has_browser_tools": True,
                **auth_metadata,
                "updated_at": datetime.utcnow().isoformat(),
            }
            session.add(spec_agent_run)
            session.commit()
            _flow_spec_jobs[job_id].update({"status": "failed", "message": message, "completed_at": _time.time()})
            _record_agent_run_event(
                spec_agent_run_id,
                event_type="failed",
                level="error",
                message=message,
                payload={"source_run_id": run_id, "source_flow_id": flow_id, "flow_title": flow.get("title")},
                session=session,
            )
            return {
                "status": "failed",
                "job_id": job_id,
                "agent_run_id": spec_agent_run_id,
                "message": message,
            }

        background_tasks.add_task(
            _run_flow_spec_generation,
            job_id=job_id,
            run_id=run_id,
            flow_id=flow_id,
            flow=flow,
            flows=flows,
            flows_file_path=str(flows_file),
            run_project_id=run_project_id,
            run_config=inherited_run_config,
            spec_agent_run_id=spec_agent_run_id,
        )

        return {
            "status": "running",
            "job_id": job_id,
            "agent_run_id": spec_agent_run_id,
            "message": "Spec generation started. Poll for status.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating test: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


async def list_sessions():
    """List saved authentication sessions."""
    from agents.auth_handler import AuthHandler

    auth_handler = AuthHandler()
    sessions = auth_handler.list_sessions()

    return {"sessions": sessions}


async def create_session(session_id: str, cookies: list[dict[str, Any]], storage: dict[str, Any]):
    """
    Save an authentication session for future use.

    This allows you to capture a logged-in session and reuse it
    for future explorations.
    """
    from agents.auth_handler import AuthHandler

    auth_handler = AuthHandler()
    result = await auth_handler.save_session(session_id, cookies, storage)

    if result.get("success"):
        return result
    else:
        raise HTTPException(status_code=400, detail=result.get("error"))


async def delete_session(session_id: str):
    """Delete a saved authentication session."""
    from agents.auth_handler import AuthHandler

    auth_handler = AuthHandler()
    if auth_handler.delete_session(session_id):
        return {"status": "deleted", "session_id": session_id}
    else:
        raise HTTPException(status_code=404, detail="Session not found")


agent_routes.register_agent_routes(sys.modules[__name__])
app.include_router(agent_routes.router)  # Agent queue, run, definition, report, and exploratory endpoints


# ========= Database Backup API =========


@app.post("/api/backup")
async def create_backup():
    """Trigger a manual database backup.

    Requires PostgreSQL database. For SQLite, use file-level backup.
    Returns the backup status and file path.
    """
    from .db import get_database_type

    db_type = get_database_type()

    if db_type == "sqlite":
        # For SQLite, create a simple file copy
        data_dir = Path(__file__).resolve().parent.parent / "data"
        db_file = data_dir / "playwright_agent.db"

        if not db_file.exists():
            raise HTTPException(status_code=404, detail="SQLite database not found")

        backup_dir = data_dir / "backups"
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"backup_{timestamp}.db"

        try:
            import shutil

            shutil.copy2(db_file, backup_file)
            backup_size = backup_file.stat().st_size

            # Rotate old backups (keep last 30)
            backups = sorted(backup_dir.glob("backup_*.db"))
            while len(backups) > 30:
                oldest = backups.pop(0)
                oldest.unlink()
                logger.info(f"Rotated old backup: {oldest.name}")

            return {
                "status": "success",
                "database_type": "sqlite",
                "backup_file": str(backup_file),
                "backup_size_bytes": backup_size,
                "timestamp": timestamp,
            }
        except Exception as e:
            logger.error(f"SQLite backup failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

    else:
        # For PostgreSQL, use pg_dump via subprocess
        try:
            backup_dir = Path("/backups") if Path("/backups").exists() else BASE_DIR / "backups"
            backup_dir.mkdir(exist_ok=True)

            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup_file = backup_dir / f"backup_{timestamp}.sql.gz"

            # Get connection parameters from DATABASE_URL
            import os
            from urllib.parse import urlparse

            db_url = os.environ.get("DATABASE_URL", "")
            parsed = urlparse(db_url)

            env = os.environ.copy()
            env["PGPASSWORD"] = parsed.password or ""

            result = subprocess.run(
                [
                    "pg_dump",
                    "-h",
                    parsed.hostname or "localhost",
                    "-p",
                    str(parsed.port or 5432),
                    "-U",
                    parsed.username or "playwright",
                    "-d",
                    parsed.path.lstrip("/") or "playwright_agent",
                    "--no-owner",
                    "--no-privileges",
                ],
                capture_output=True,
                env=env,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                error_msg = result.stderr.decode()
                logger.error(f"pg_dump failed: {error_msg}")
                raise HTTPException(status_code=500, detail=f"pg_dump failed: {error_msg}")

            # Compress and save
            import gzip

            with gzip.open(backup_file, "wb") as f:
                f.write(result.stdout)

            backup_size = backup_file.stat().st_size

            return {
                "status": "success",
                "database_type": "postgresql",
                "backup_file": str(backup_file),
                "backup_size_bytes": backup_size,
                "timestamp": timestamp,
            }

        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="Backup timed out after 5 minutes")
        except FileNotFoundError:
            raise HTTPException(
                status_code=500, detail="pg_dump not found. Backup must be run from a container with PostgreSQL tools."
            )
        except Exception as e:
            logger.error(f"PostgreSQL backup failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/backup/status")
async def get_backup_status():
    """Get the status of database backups including recent backups and retention policy."""
    from .db import get_database_type

    db_type = get_database_type()

    if db_type == "sqlite":
        backup_dir = Path(__file__).resolve().parent.parent / "data" / "backups"
    else:
        backup_dir = Path("/backups") if Path("/backups").exists() else BASE_DIR / "backups"

    if not backup_dir.exists():
        return {
            "database_type": db_type,
            "backup_dir": str(backup_dir),
            "backup_count": 0,
            "total_size_bytes": 0,
            "recent_backups": [],
            "retention_days": 30,
        }

    pattern = "backup_*.db" if db_type == "sqlite" else "backup_*.sql.gz"
    backups = sorted(backup_dir.glob(pattern), reverse=True)

    total_size = sum(b.stat().st_size for b in backups)

    recent_backups = []
    for backup in backups[:10]:  # Last 10 backups
        stat = backup.stat()
        recent_backups.append(
            {
                "filename": backup.name,
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )

    return {
        "database_type": db_type,
        "backup_dir": str(backup_dir),
        "backup_count": len(backups),
        "total_size_bytes": total_size,
        "recent_backups": recent_backups,
        "retention_days": 30,
    }
