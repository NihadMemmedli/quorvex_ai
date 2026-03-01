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
import json
import re
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func
from sqlmodel import Session, select
from starlette.requests import Request
from starlette.responses import JSONResponse

from logging_config import get_logger, request_id_var, setup_logging
from services.browser_pool import AbstractBrowserPool, get_browser_pool
from services.browser_pool import OperationType as BrowserOpType
from services.resource_manager import ResourceManager, ResourceType, get_resource_manager
from utils.project_utils import derive_project_id_from_url

from . import (
    analytics,
    api_testing,
    auth,
    autopilot,
    chat,
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
    regression,
    requirements,
    rtm,
    scheduling,
    security_testing,
    settings,
    testrail,
    users,
)
from .db import engine, get_database_type, get_session, init_db, is_parallel_mode_available
from .middleware.rate_limit import limiter, rate_limit_exceeded_handler
from .models import (
    BulkRunRequest,
    ClearQueueRequest,
    ClearQueueResponse,
    CreateBatchResponse,
    CreateFolderRequest,
    CreateFolderResponse,
    CreateSpecRequest,
    ExecutionSettingsResponse,
    FolderNode,
    FolderTreeResponse,
    MovedItemInfo,
    MoveSpecRequest,
    MoveSpecResponse,
    QueueStatusResponse,
    RenameRequest,
    RenameResponse,
    TestRun,
    UpdateExecutionSettingsRequest,
    UpdateGeneratedCodeRequest,
    UpdateMetadataRequest,
    UpdateSpecRequest,
)
from .models_db import AgentRun, ExplorationSession, RegressionBatch, TestrailCaseMapping
from .models_db import ExecutionSettings as DBExecutionSettings
from .models_db import SpecMetadata as DBSpecMetadata
from .models_db import TestRun as DBTestRun
from .process_manager import ProcessManager, get_process_manager

# Initialize logging
setup_logging(level="INFO", console=True)
logger = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = BASE_DIR / "specs"
RUNS_DIR = BASE_DIR / "runs"
METADATA_FILE = SPECS_DIR / "spec-metadata.json"

# Spec info cache: path -> (mtime, spec_info_dict)
_spec_info_cache: dict[str, tuple] = {}
_MAX_SPEC_CACHE_SIZE = 5000

# Code path cache: spec_name -> (code_path, timestamp)
# Maps spec names to their generated test file paths
# TTL-based to handle file changes without restart
_code_path_cache: dict[str, tuple] = {}
_CODE_PATH_CACHE_TTL = 300  # 5 minutes
_MAX_CODE_CACHE_SIZE = 200

# Background task handles for graceful shutdown
_BACKGROUND_TASKS: list[asyncio.Task] = []


class SpecCache:
    """Cache for spec metadata list, invalidated when specs directory changes."""

    def __init__(self, specs_dir: Path):
        self._specs_dir = specs_dir
        self._cache: list[dict] | None = None
        self._last_mtime: float = 0
        self._lock = asyncio.Lock()

    def _get_dir_mtime(self) -> float:
        """Get the latest mtime of the specs directory tree."""
        try:
            max_mtime = self._specs_dir.stat().st_mtime
            for p in self._specs_dir.rglob("*.md"):
                max_mtime = max(max_mtime, p.stat().st_mtime)
            return max_mtime
        except OSError:
            return 0

    def invalidate(self):
        """Force cache invalidation."""
        self._cache = None
        self._last_mtime = 0

    async def get_specs(self, builder_fn) -> list[dict]:
        """Get cached spec list, rebuilding if directory changed."""
        current_mtime = self._get_dir_mtime()
        if self._cache is not None and current_mtime == self._last_mtime:
            return self._cache

        async with self._lock:
            # Double-check after acquiring lock
            current_mtime = self._get_dir_mtime()
            if self._cache is not None and current_mtime == self._last_mtime:
                return self._cache

            self._cache = builder_fn()
            self._last_mtime = current_mtime
            return self._cache


_spec_cache = SpecCache(SPECS_DIR)


def get_try_code_path_fast(spec_path: Path) -> str | None:
    """Fast code path check - only checks filename patterns without scanning runs."""
    stem = spec_path.stem
    stem_slug = stem.replace("_", "-")

    # Build candidates list - check both generated and templates folders
    candidates = [
        f"tests/generated/{stem}.spec.ts",
        f"tests/generated/{stem_slug}.spec.ts",
        f"tests/templates/{stem}.spec.ts",
        f"tests/templates/{stem_slug}.spec.ts",
        f"tests/{stem}.spec.ts",
    ]

    for c in candidates:
        if (BASE_DIR / c).exists():
            return str(BASE_DIR / c)
    return None


def get_cached_spec_info(spec_path: Path) -> dict:
    """Get spec info with caching based on file modification time."""
    from utils.spec_detector import SpecDetector

    path_str = str(spec_path)
    try:
        current_mtime = spec_path.stat().st_mtime
    except OSError:
        current_mtime = 0

    # Check cache
    if path_str in _spec_info_cache:
        cached_mtime, cached_info = _spec_info_cache[path_str]
        if cached_mtime == current_mtime:
            return cached_info

    # Cache miss or stale - compute fresh
    try:
        spec_info = SpecDetector.get_spec_info(spec_path)
        result = {
            "type": spec_info["type"],
            "test_count": spec_info["test_count"],
            "categories": spec_info["categories"],
        }
    except Exception:
        result = {"type": "standard", "test_count": 1, "categories": []}

    # Update cache (trim if exceeds max size)
    if len(_spec_info_cache) >= _MAX_SPEC_CACHE_SIZE:
        # Evict oldest half by insertion order
        keys = list(_spec_info_cache.keys())
        for k in keys[: len(keys) // 2]:
            del _spec_info_cache[k]
    _spec_info_cache[path_str] = (current_mtime, result)
    return result


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
app.include_router(memory.router)
app.include_router(prd.router)
app.include_router(regression.router)
app.include_router(projects.router)
app.include_router(exploration.router)
app.include_router(requirements.router)
app.include_router(rtm.router)
app.include_router(testrail.router)  # TestRail integration
app.include_router(jira.router)  # Jira integration
app.include_router(scheduling.router)  # Cron scheduling
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
app.mount("/artifacts", StaticFiles(directory=RUNS_DIR), name="artifacts")

# CORS Configuration - restrict origins in production
# Set ALLOWED_ORIGINS env var with comma-separated URLs (e.g., "https://app.company.com,http://localhost:3000")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

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
            orphaned_running = [r for r in running if not is_process_active(r.id)]

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
                    PROCESS_MANAGER
                    and r.id in PROCESS_MANAGER._asyncio_tasks
                    and not PROCESS_MANAGER._asyncio_tasks[r.id].done()
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
        if METADATA_FILE.exists():
            try:
                meta_dict = json.loads(METADATA_FILE.read_text())
                for spec_name, data in meta_dict.items():
                    if session.get(DBSpecMetadata, spec_name):
                        continue

                    meta = DBSpecMetadata(
                        spec_name=spec_name,
                        tags_json=json.dumps(data.get("tags", [])),
                        description=data.get("description"),
                        author=data.get("author"),
                    )
                    # lastModified
                    lm = data.get("lastModified")
                    if lm:
                        try:
                            meta.last_modified = datetime.fromisoformat(lm)
                        except ValueError:
                            logger.warning(f"Invalid lastModified date format for {spec_name}: {lm}")

                    session.add(meta)
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON in metadata file {METADATA_FILE}: {e}")
            except OSError as e:
                logger.warning(f"Cannot read metadata file {METADATA_FILE}: {e}")

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
        from orchestrator.services.scheduler import init_scheduler, restore_schedules_from_db

        init_scheduler(engine)
        await restore_schedules_from_db()
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


@app.get("/health")
def health():
    """Enhanced health check with dependency status."""
    checks = {}

    # Database check - actual query test (SELECT 1)
    try:
        from sqlalchemy import text as sa_text

        with Session(engine) as session:
            session.exec(sa_text("SELECT 1"))
            checks["database"] = {"status": "ok", "type": get_database_type()}
    except Exception as e:
        checks["database"] = {"status": "error", "error": str(e)}

    # Filesystem check with disk space
    try:
        if RUNS_DIR.exists() and os.access(RUNS_DIR, os.W_OK):
            import shutil as _shutil

            disk = _shutil.disk_usage(str(RUNS_DIR))
            disk_pct = round((disk.used / disk.total) * 100, 1)
            fs_status = "ok"
            if disk_pct >= 95:
                fs_status = "critical"
            elif disk_pct >= 90:
                fs_status = "warning"
            checks["filesystem"] = {
                "status": fs_status,
                "runs_dir": str(RUNS_DIR),
                "disk_used_pct": disk_pct,
                "disk_free_gb": round(disk.free / (1024**3), 1),
            }
        else:
            checks["filesystem"] = {"status": "error", "error": "runs directory not writable"}
    except Exception as e:
        checks["filesystem"] = {"status": "error", "error": str(e)}

    # Redis check
    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE

        if REDIS_AVAILABLE:
            checks["redis"] = {"status": "ok", "configured": True}
        else:
            checks["redis"] = {"status": "ok", "configured": False}
    except Exception:
        checks["redis"] = {"status": "ok", "configured": False}

    # Process manager check
    checks["processes"] = {
        "status": "ok",
        "active_count": get_active_process_count(),
        "process_manager": PROCESS_MANAGER is not None,
    }

    # Overall status
    critical_checks = ["database", "filesystem"]
    has_critical = any(checks.get(k, {}).get("status") == "error" for k in critical_checks)
    has_warning = any(c.get("status") in ("warning", "critical") for c in checks.values())
    overall_status = "unhealthy" if has_critical else "degraded" if has_warning else "healthy"

    return {"status": overall_status, "checks": checks, "version": "1.0.0"}


# ========= Resource Management =========


@app.get("/api/browser-pool/status")
async def get_browser_pool_status():
    """Get current unified browser pool status.

    This is the primary endpoint for monitoring browser resource usage.
    The browser pool limits ALL browser operations (test runs, explorations,
    agents, PRD processing) to MAX_BROWSER_INSTANCES concurrent browsers.

    Returns:
        - max_browsers: Maximum concurrent browsers allowed
        - running: Number of browsers currently running
        - queued: Number of requests waiting for a browser slot
        - available: Number of slots available immediately
        - running_requests: List of request IDs currently running
        - queued_requests: List of request IDs in queue (FIFO order)
        - by_type: Breakdown of running requests by operation type
    """
    pool = BROWSER_POOL or await get_browser_pool()
    return await pool.get_status()


@app.get("/api/browser-pool/recent")
async def get_browser_pool_recent(limit: int = 50):
    """Get recent browser slot activity for monitoring.

    Returns the most recent slot requests with timing information,
    useful for debugging and performance monitoring.

    Args:
        limit: Maximum number of slots to return (default: 50)
    """
    pool = BROWSER_POOL or await get_browser_pool()
    return {"recent_slots": await pool.get_recent_slots(limit), "current_status": await pool.get_status()}


@app.post("/api/browser-pool/cleanup")
async def cleanup_browser_pool():
    """Force cleanup of stale browser slots.

    Releases any slots held by operations that have exceeded their timeout
    (default: 60 minutes). Also cleans up old completed slot records.

    This is automatically done on startup but can be triggered manually.
    """
    pool = BROWSER_POOL or await get_browser_pool()

    stale_cleaned = await pool.cleanup_stale(max_age_minutes=60)
    old_cleaned = await pool.cleanup_old_completed(max_age_hours=24)

    return {
        "status": "success",
        "stale_slots_cleaned": stale_cleaned,
        "old_records_cleaned": old_cleaned,
        "current_status": await pool.get_status(),
    }


@app.get("/api/resources/status")
async def get_resource_status():
    """Get current resource usage status for all managed resources.

    DEPRECATED: Use /api/browser-pool/status instead for unified browser management.

    Returns the status of agent, exploration, and PRD processing queues
    from the legacy ResourceManager (kept for backward compatibility).
    """
    resource_manager = await get_resource_manager()
    legacy_status = resource_manager.get_full_status()

    # Add browser pool status for transition period
    pool = BROWSER_POOL or await get_browser_pool()
    browser_pool_status = await pool.get_status()

    return {
        **legacy_status,
        "browser_pool": browser_pool_status,
        "_note": "Legacy resource_manager is deprecated. Use /api/browser-pool/status for unified browser management.",
    }


@app.get("/api/agents/queue-status")
async def get_agent_queue_status():
    """Get current agent queue status.

    Returns detailed information about browser slot usage for agents
    from the unified browser pool.
    """
    pool = BROWSER_POOL or await get_browser_pool()
    status = await pool.get_status()

    # Filter to show agent-specific info
    agent_running = status["by_type"].get("agent", 0)

    return {
        "active": agent_running,
        "max": status["max_browsers"],
        "queued": status["queued"],
        "available": status["available"],
        "pool_status": {"total_running": status["running"], "by_type": status["by_type"]},
    }


@app.post("/api/agents/queue-flush")
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


@app.get("/api/key-rotation/status")
async def get_key_rotation_status():
    """Get API key rotation status — shows available/cooled-down keys."""
    try:
        from orchestrator.services.api_key_rotator import get_api_key_rotator

        rotator = get_api_key_rotator()
        return rotator.get_status()
    except ImportError:
        return {"total_keys": 0, "available_keys": 0, "keys": [], "error": "Rotator not available"}


@app.post("/api/resources/cleanup")
async def cleanup_stale_resources():
    """Force cleanup of stale resource slots.

    Cleans up both the legacy ResourceManager and the unified BrowserResourcePool.
    """
    resource_manager = await get_resource_manager()
    legacy_cleaned = await resource_manager.cleanup_stale_slots()

    pool = BROWSER_POOL or await get_browser_pool()
    pool_cleaned = await pool.cleanup_stale(max_age_minutes=60)

    return {
        "status": "success",
        "legacy_cleaned": legacy_cleaned,
        "browser_pool_cleaned": pool_cleaned,
        "message": f"Cleaned {len(legacy_cleaned)} legacy slots, {len(pool_cleaned)} browser pool slots",
    }


# ========= Execution Settings =========


@app.get("/execution-settings", response_model=ExecutionSettingsResponse)
def get_execution_settings(session: Session = Depends(get_session)):
    """Get current execution settings including database type detection."""
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
        database_type=get_database_type(),
        parallel_mode_available=is_parallel_mode_available(),
    )


@app.put("/execution-settings", response_model=ExecutionSettingsResponse)
async def update_execution_settings(request: UpdateExecutionSettingsRequest, session: Session = Depends(get_session)):
    """Update execution settings.

    Validates that parallelism > 1 requires PostgreSQL database.
    """
    global QUEUE_MANAGER

    settings = session.get(DBExecutionSettings, 1)
    if not settings:
        settings = DBExecutionSettings(id=1)

    # Validate parallelism constraint
    new_parallelism = request.parallelism if request.parallelism is not None else settings.parallelism
    if new_parallelism > 1 and not is_parallel_mode_available():
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="Parallelism > 1 requires PostgreSQL database. SQLite has write locking issues that prevent concurrent test execution.",
        )

    # Update fields
    if request.parallelism is not None:
        settings.parallelism = max(1, min(10, request.parallelism))  # Clamp to 1-10

    if request.parallel_mode_enabled is not None:
        # Can only enable parallel mode if parallelism > 1 and database supports it
        if request.parallel_mode_enabled and settings.parallelism <= 1:
            settings.parallel_mode_enabled = False
        elif request.parallel_mode_enabled and not is_parallel_mode_available():
            from fastapi import HTTPException

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

    # Reload QueueManager with new settings (legacy)
    if QUEUE_MANAGER:
        await QUEUE_MANAGER.reload_settings()

    # Update unified browser pool with new parallelism setting
    if BROWSER_POOL and request.parallelism is not None:
        await BROWSER_POOL.update_max_browsers(settings.parallelism)
        logger.info(f"Browser pool updated to max_browsers={settings.parallelism}")

    return ExecutionSettingsResponse(
        parallelism=settings.parallelism,
        parallel_mode_enabled=settings.parallel_mode_enabled,
        headless_in_parallel=settings.headless_in_parallel,
        memory_enabled=settings.memory_enabled,
        database_type=get_database_type(),
        parallel_mode_available=is_parallel_mode_available(),
    )


@app.get("/queue-status", response_model=QueueStatusResponse)
async def get_queue_status():
    """Get current queue status with running and queued counts."""
    global QUEUE_MANAGER

    if QUEUE_MANAGER is None:
        QUEUE_MANAGER = await QueueManager.get_instance()

    status = QUEUE_MANAGER.get_queue_status()

    # Add agent worker health if Redis agent queue is available
    agent_health = None
    try:
        from orchestrator.services.agent_queue import get_agent_queue, should_use_agent_queue

        if should_use_agent_queue():
            queue = get_agent_queue()
            agent_health = await queue.get_worker_health()
    except Exception as e:
        logger.debug(f"Could not fetch agent worker health: {e}")

    return QueueStatusResponse(**status, agent_worker_health=agent_health)


@app.post("/queue/clear", response_model=ClearQueueResponse)
def clear_queue(request: ClearQueueRequest, session: Session = Depends(get_session)):
    """Clear stuck queue entries.

    Marks orphaned running and/or queued entries as 'stopped'.
    Only clears 'running' entries that are not actively tracked (orphaned).
    """
    cleared_runs = []

    # Clear queued entries
    if request.include_queued:
        queued = session.exec(select(DBTestRun).where(DBTestRun.status == "queued")).all()
        for run in queued:
            # Cancel the backing asyncio task (waiting for browser slot)
            if PROCESS_MANAGER:
                PROCESS_MANAGER.stop(run.id)
            run.status = "stopped"
            run.queue_position = None
            session.add(run)
            cleared_runs.append(run.id)

            # Update status.txt file too
            run_dir = RUNS_DIR / run.id
            if run_dir.exists():
                (run_dir / "status.txt").write_text("stopped")

    # Clear orphaned running entries (in DB but no active process)
    if request.include_running:
        running = session.exec(select(DBTestRun).where(DBTestRun.status.in_(["running", "in_progress"]))).all()
        for run in running:
            # Only clear if not actively tracked (orphaned)
            if not is_process_active(run.id):
                # Cancel the backing asyncio task if it exists
                if PROCESS_MANAGER:
                    PROCESS_MANAGER.stop(run.id)
                run.status = "stopped"
                run.queue_position = None
                session.add(run)
                cleared_runs.append(run.id)

                # Update status.txt file too
                run_dir = RUNS_DIR / run.id
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


@app.post("/stop-all")
async def stop_all_jobs():
    """Global emergency stop: kill all running processes, cancel all background
    pipelines/explorations, and mark every active DB entry as stopped/cancelled."""

    stopped_processes = 0
    cancelled_autopilot = 0
    cancelled_explorations = 0
    cleaned_db_entries = 0

    # 1. Stop all active processes via ProcessManager
    for run_id in list_active_process_ids():
        try:
            if PROCESS_MANAGER:
                PROCESS_MANAGER.stop(run_id)
            else:
                proc = get_process(run_id)
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
    clear_all_processes()

    # 2. Cancel all autopilot running pipelines
    for _sid, (task, pipeline, _) in list(autopilot._running_pipelines.items()):
        try:
            pipeline.cancel()
        except Exception:
            pass
        task.cancel()
        cancelled_autopilot += 1
    autopilot._running_pipelines.clear()

    # 3. Cancel all exploration sessions
    for _sid, (task, _) in list(exploration._running_explorations.items()):
        task.cancel()
        cancelled_explorations += 1
    exploration._running_explorations.clear()

    # 4. Mark ALL active DB entries as stopped/cancelled
    batch_ids_to_update = set()
    with Session(engine) as session:
        active_runs = session.exec(
            select(DBTestRun).where(DBTestRun.status.in_(["running", "in_progress", "queued"]))
        ).all()

        now = datetime.utcnow()
        for run in active_runs:
            run.status = "stopped" if run.status in ("running", "in_progress") else "cancelled"
            run.completed_at = now
            run.queue_position = None
            session.add(run)
            cleaned_db_entries += 1

            # Write status.txt
            run_dir = RUNS_DIR / run.id
            if run_dir.exists():
                (run_dir / "status.txt").write_text(run.status)

            if run.batch_id:
                batch_ids_to_update.add(run.batch_id)

        session.commit()

    # 5. Update batch stats for affected batches
    for batch_id in batch_ids_to_update:
        try:
            update_batch_stats(batch_id)
        except Exception as e:
            logger.error(f"stop-all: Failed to update batch {batch_id}: {e}")

    logger.warning(
        f"stop-all: stopped_processes={stopped_processes}, "
        f"cancelled_autopilot={cancelled_autopilot}, "
        f"cancelled_explorations={cancelled_explorations}, "
        f"cleaned_db_entries={cleaned_db_entries}"
    )

    return {
        "stopped_processes": stopped_processes,
        "cancelled_autopilot": cancelled_autopilot,
        "cancelled_explorations": cancelled_explorations,
        "cleaned_db_entries": cleaned_db_entries,
    }


@app.get("/debug-imports")
def debug_imports():
    """Debug endpoint to check sys.path and test imports"""
    import sys
    from pathlib import Path

    # Test the import that's failing
    import_result = {"success": False, "error": None}
    try:
        import_result["success"] = True
    except Exception as e:
        import_result["error"] = str(e)

    # Get sys.path info
    orchestrator_dir = Path(__file__).resolve().parent.parent
    return {
        "sys.path_first_5": sys.path[:5],
        "orchestrator_dir": str(orchestrator_dir),
        "orchestrator_in_path": str(orchestrator_dir) in sys.path,
        "utils_exists": (orchestrator_dir / "utils" / "json_utils.py").exists(),
        "import_test": import_result,
        "current_dir": str(Path.cwd()),
    }


# ========= Specs =========


@app.get("/specs/list")
def list_specs_lightweight(
    project_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str | None = None,
    tags: str | None = None,
    automated_only: bool = False,
    session: Session = Depends(get_session),
):
    """Lightweight spec listing with server-side pagination and filtering.

    Performance optimizations:
    - No file content loaded (saves ~80% response size)
    - Fast filename-based code path check (avoids scanning all run directories)
    - Cached spec type detection (avoids re-parsing files)
    - Server-side search, tag filtering, and automated-only filtering
    - Paginated response with summary stats

    Query params:
    - limit: Page size (1-200, default 50)
    - offset: Pagination offset (default 0)
    - search: Case-insensitive name search
    - tags: Comma-separated tag filter (matches specs with any of the given tags)
    - automated_only: Only return specs with generated code
    """
    # Get spec names for this project if filtering
    project_spec_names = None
    excluded_spec_names = set()  # Specs explicitly assigned to other projects

    if project_id:
        if project_id == "default":
            # For default project: get specs explicitly assigned to OTHER projects (to exclude them)
            other_project_query = select(DBSpecMetadata.spec_name).where(
                (DBSpecMetadata.project_id != None) & (DBSpecMetadata.project_id != "default")
            )
            excluded_spec_names = set(session.exec(other_project_query).all())
            # project_spec_names stays None = don't filter by inclusion, use exclusion instead
        else:
            # For other projects: only include specs explicitly assigned to this project
            query = select(DBSpecMetadata.spec_name).where(DBSpecMetadata.project_id == project_id)
            project_spec_names = set(session.exec(query).all())

    # Parse tag filter
    tag_filter = set()
    if tags:
        tag_filter = {t.strip() for t in tags.split(",") if t.strip()}

    # Pre-fetch all metadata for tag lookup (single DB query)
    metadata_by_name: dict[str, list] = {}
    if tag_filter:
        meta_query = select(DBSpecMetadata.spec_name, DBSpecMetadata.tags_json)
        if project_id:
            if project_id == "default":
                meta_query = meta_query.where(
                    (DBSpecMetadata.project_id == project_id) | (DBSpecMetadata.project_id == None)
                )
            else:
                meta_query = meta_query.where(DBSpecMetadata.project_id == project_id)
        for row in session.exec(meta_query).all():
            try:
                parsed_tags = json.loads(row[1]) if row[1] else []
            except (json.JSONDecodeError, TypeError):
                parsed_tags = []
            metadata_by_name[row[0]] = parsed_tags

    search_lower = search.lower().strip() if search else None

    # Collect all matching specs with early filtering
    matching_specs = []
    total_all = 0  # Total non-template specs (unfiltered)
    automated_count = 0  # Automated count across all non-template specs
    all_tags_set: set = set()

    if SPECS_DIR.exists():
        for f in SPECS_DIR.glob("**/*.md"):
            name = str(f.relative_to(SPECS_DIR))

            # Skip templates — they're loaded separately for the Templates tab
            if name.startswith("templates/"):
                continue

            # Apply project filter if specified
            if project_spec_names is not None and name not in project_spec_names:
                continue

            # For default project: exclude specs explicitly assigned to other projects
            if name in excluded_spec_names:
                continue

            # Fast code path check - only checks filename patterns
            code_path = get_try_code_path_fast(f)
            is_automated = bool(code_path)

            # Count totals before applying user filters
            total_all += 1
            if is_automated:
                automated_count += 1

            # Collect tags from metadata for summary (need all tags even for non-matching specs)
            spec_tags = metadata_by_name.get(name, []) if metadata_by_name else []

            # If we didn't pre-fetch metadata (no tag filter), we still need tags for summary
            # We'll collect them from DB after the loop to avoid N+1 queries
            # For now, skip tag collection during iteration if no tag filter

            # Apply search filter
            if search_lower and search_lower not in name.lower():
                continue

            # Apply tag filter
            if tag_filter:
                if not spec_tags or not tag_filter.intersection(spec_tags):
                    continue

            # Apply automated-only filter
            if automated_only and not is_automated:
                continue

            # Cached spec info detection
            spec_info = get_cached_spec_info(f)

            matching_specs.append(
                {
                    "name": name,
                    "path": str(f.absolute()),
                    "is_automated": is_automated,
                    "code_path": code_path,
                    "spec_type": spec_info["type"],
                    "test_count": spec_info["test_count"],
                    "categories": spec_info["categories"],
                }
            )

    # Collect all unique tags for summary (single DB query)
    all_tags_query = select(DBSpecMetadata.tags_json)
    if project_id:
        if project_id == "default":
            all_tags_query = all_tags_query.where(
                (DBSpecMetadata.project_id == project_id) | (DBSpecMetadata.project_id == None)
            )
        else:
            all_tags_query = all_tags_query.where(DBSpecMetadata.project_id == project_id)
    for tags_json_val in session.exec(all_tags_query).all():
        if tags_json_val:
            try:
                tag_list = json.loads(tags_json_val)
                if isinstance(tag_list, list):
                    all_tags_set.update(tag_list)
            except (json.JSONDecodeError, TypeError):
                pass

    # Sort by name for consistent pagination
    matching_specs.sort(key=lambda s: s["name"].lower())

    total = len(matching_specs)
    paginated = matching_specs[offset : offset + limit]
    has_more = (offset + limit) < total

    return {
        "items": paginated,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "summary": {"total_all": total_all, "automated_count": automated_count, "all_tags": sorted(all_tags_set)},
    }


# Folder tree cache: (project_filter_key, specs_mtime) -> (tree, total, timestamp)
import time as time_module

_folder_tree_cache: dict[str, tuple] = {}
_FOLDER_TREE_CACHE_TTL = 60  # 60 seconds


def _build_folder_tree(
    specs_dir: Path,
    project_spec_names: set | None = None,
    excluded_spec_names: set | None = None,
    cache_key: str | None = None,
) -> tuple[list[FolderNode], int]:
    """Build folder tree with automated spec counts using O(n) algorithm.

    Args:
        specs_dir: Base specs directory
        project_spec_names: If provided, only count specs whose names are in this set (inclusion filter)
        excluded_spec_names: If provided, exclude specs whose names are in this set (exclusion filter)
        cache_key: Optional key for caching (e.g., project_id)

    Returns (folder_nodes, total_automated_specs)
    """
    global _folder_tree_cache

    # Check cache if cache_key provided
    if cache_key:
        if cache_key in _folder_tree_cache:
            cached_tree, cached_total, cached_time = _folder_tree_cache[cache_key]
            if time_module.time() - cached_time < _FOLDER_TREE_CACHE_TTL:
                return cached_tree, cached_total

    # First pass: collect all automated specs and their folders
    folder_counts: dict[str, int] = {}
    total_specs = 0

    if specs_dir.exists():
        for f in specs_dir.glob("**/*.md"):
            code_path = get_try_code_path_fast(f)
            if not code_path:
                continue

            # Get relative spec name for project filtering
            spec_name = str(f.relative_to(specs_dir))

            # If inclusion filtering is enabled, skip specs not in the set
            if project_spec_names is not None and spec_name not in project_spec_names:
                continue

            # If exclusion filtering is enabled, skip specs in the excluded set
            if excluded_spec_names and spec_name in excluded_spec_names:
                continue

            total_specs += 1
            rel_path = f.relative_to(specs_dir)

            # Count for each parent folder
            parts = list(rel_path.parts[:-1])  # Exclude filename
            for i in range(len(parts)):
                folder_path = "/".join(parts[: i + 1])
                folder_counts[folder_path] = folder_counts.get(folder_path, 0) + 1

    # O(n) tree construction using parent lookup
    # Step 1: Build parent->children mapping in single pass
    children_by_parent: dict[str, list[str]] = {}  # parent_path -> [child_paths]

    for folder_path in folder_counts:
        # Find parent path
        if "/" in folder_path:
            parent_path = folder_path.rsplit("/", 1)[0]
        else:
            parent_path = ""  # Root level

        if parent_path not in children_by_parent:
            children_by_parent[parent_path] = []
        children_by_parent[parent_path].append(folder_path)

    # Step 2: Build nodes recursively using the children lookup
    def build_node(folder_path: str) -> FolderNode:
        name = folder_path.rsplit("/", 1)[-1] if "/" in folder_path else folder_path
        child_paths = children_by_parent.get(folder_path, [])
        children = [build_node(cp) for cp in sorted(child_paths, key=str.lower)]
        return FolderNode(name=name, path=folder_path, spec_count=folder_counts.get(folder_path, 0), children=children)

    # Build root nodes (those with parent "")
    root_paths = children_by_parent.get("", [])
    root_nodes = [build_node(rp) for rp in sorted(root_paths, key=str.lower)]

    # Update cache
    if cache_key:
        _folder_tree_cache[cache_key] = (root_nodes, total_specs, time_module.time())

    return root_nodes, total_specs


@app.get("/specs/folders", response_model=FolderTreeResponse)
def get_spec_folders(project_id: str | None = None, session: Session = Depends(get_session)):
    """Return folder tree structure with automated test counts.

    Only includes folders containing automated specs (with .spec.ts files).
    Optionally filtered by project_id to show only folders with specs from that project.
    """
    # Get project-filtered spec names if filtering
    project_spec_names = None
    excluded_spec_names = set()

    if project_id:
        if project_id == "default":
            # For default project: get specs explicitly assigned to OTHER projects (to exclude them)
            other_project_query = select(DBSpecMetadata.spec_name).where(
                (DBSpecMetadata.project_id != None) & (DBSpecMetadata.project_id != "default")
            )
            excluded_spec_names = set(session.exec(other_project_query).all())
            # project_spec_names stays None = don't filter by inclusion, use exclusion instead
        else:
            # For other projects: only include specs explicitly assigned to this project
            query = select(DBSpecMetadata.spec_name).where(DBSpecMetadata.project_id == project_id)
            project_spec_names = set(session.exec(query).all())

    # Use project_id as cache key (or "all" if no filter)
    cache_key = f"folder_tree_{project_id or 'all'}"
    folders, total_specs = _build_folder_tree(SPECS_DIR, project_spec_names, excluded_spec_names, cache_key)
    return FolderTreeResponse(folders=folders, total_specs=total_specs)


@app.get("/specs/automated")
def list_automated_specs(
    tags: str | None = None,
    folder: str | None = None,
    project_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    """List only automated specs (with generated .spec.ts files).

    Returns specs with metadata for regression testing.

    Query parameters:
    - tags: Comma-separated tag filter (OR logic)
    - folder: Filter by folder path prefix
    - project_id: Filter by project ID
    - limit: Page size (default 50, max 100)
    - offset: Starting position for pagination
    """
    # Clamp limit
    limit = min(max(1, limit), 100)
    offset = max(0, offset)

    # Batch fetch all last runs in a single query instead of N+1 queries
    # Uses subquery to get the latest run for each spec
    from sqlalchemy import text

    last_runs_query = text("""
        SELECT t1.spec_name, t1.id, t1.status, t1.created_at
        FROM testrun t1
        INNER JOIN (
            SELECT spec_name, MAX(created_at) as max_created_at
            FROM testrun
            GROUP BY spec_name
        ) t2 ON t1.spec_name = t2.spec_name AND t1.created_at = t2.max_created_at
    """)

    last_runs_results = session.exec(last_runs_query).all()
    last_runs_map: dict[str, dict] = {
        row[0]: {"id": row[1], "status": row[2], "created_at": row[3]} for row in last_runs_results
    }

    # Batch fetch all spec metadata in a single query (safety cap at 10000)
    all_meta = session.exec(select(DBSpecMetadata).limit(10000)).all()
    meta_map: dict[str, DBSpecMetadata] = {m.spec_name: m for m in all_meta}

    all_specs = []
    tag_filter = tags.split(",") if tags else []

    if SPECS_DIR.exists():
        for f in SPECS_DIR.glob("**/*.md"):
            # Fast code path check - only include automated specs
            code_path = get_try_code_path_fast(f)
            if not code_path:
                continue

            name = str(f.relative_to(SPECS_DIR))

            # Apply folder filter if specified
            if folder:
                if not name.startswith(folder + "/"):
                    continue

            # Get metadata from pre-fetched map (O(1) lookup instead of DB query)
            meta = meta_map.get(name)
            spec_tags = meta.tags if meta else []

            # Apply project filter if specified
            # Specs with null project_id are treated as belonging to the "default" project
            if project_id:
                spec_project_id = meta.project_id if meta else None
                # Include specs that either match the project_id OR have no project (null) when filtering for default
                if spec_project_id != project_id:
                    if not (project_id == "default" and spec_project_id is None):
                        continue

            # Apply tag filter (OR logic) if specified
            if tag_filter and not any(tag in spec_tags for tag in tag_filter):
                continue

            # Cached spec info detection
            spec_info = get_cached_spec_info(f)

            # Get last run from pre-fetched map (O(1) lookup instead of DB query)
            last_run = last_runs_map.get(name)

            all_specs.append(
                {
                    "name": name,
                    "path": str(f.absolute()),
                    "code_path": code_path,
                    "spec_type": spec_info["type"],
                    "test_count": spec_info["test_count"],
                    "categories": spec_info["categories"],
                    "tags": spec_tags,
                    "last_run_status": last_run["status"] if last_run else None,
                    "last_run_id": last_run["id"] if last_run else None,
                    "last_run_at": last_run["created_at"].isoformat() if last_run else None,
                }
            )

    # Sort by name for consistent pagination
    all_specs.sort(key=lambda x: x["name"].lower())

    # Apply pagination
    total = len(all_specs)
    paginated_specs = all_specs[offset : offset + limit]
    has_more = offset + limit < total

    return {
        "specs": paginated_specs,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "filtered_folder": folder,
        "filtered_by_tags": tag_filter if tag_filter else None,
        "filtered_by_project": project_id,
    }


@app.get("/specs")
def list_specs(
    limit: int = Query(default=50, ge=1, le=200, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    project_id: str | None = Query(default=None, description="Project ID filter"),
    session: Session = Depends(get_session),
):
    """
    Paginated spec listing with metadata only (no content).

    For backward compatibility, returns specs array.
    Content removed to prevent memory issues at scale (100k+ specs).
    Use GET /specs/{name}/content to fetch individual spec content.
    """
    all_specs = []

    # Get project-filtered spec names if filtering by non-default project
    project_spec_names = None
    excluded_spec_names = set()

    if project_id:
        if project_id == "default":
            # For default project: exclude specs assigned to other projects
            other_project_query = select(DBSpecMetadata.spec_name).where(
                (DBSpecMetadata.project_id != None) & (DBSpecMetadata.project_id != "default")
            )
            excluded_spec_names = set(session.exec(other_project_query).all())
        else:
            # For other projects: only include specs explicitly assigned
            query = select(DBSpecMetadata.spec_name).where(DBSpecMetadata.project_id == project_id)
            project_spec_names = set(session.exec(query).all())

    if SPECS_DIR.exists():
        for f in SPECS_DIR.glob("**/*.md"):
            name = str(f.relative_to(SPECS_DIR))

            # Apply project filter
            if project_spec_names is not None and name not in project_spec_names:
                continue
            if name in excluded_spec_names:
                continue

            # Fast code path check - no run scanning
            code_path = get_try_code_path_fast(f)

            # Cached spec info detection
            spec_info = get_cached_spec_info(f)

            all_specs.append(
                {
                    "name": name,
                    "path": str(f.absolute()),
                    "is_automated": bool(code_path),
                    "code_path": code_path,
                    "spec_type": spec_info["type"],
                    "test_count": spec_info["test_count"],
                    "categories": spec_info["categories"],
                }
            )

    # Sort for consistent pagination
    all_specs.sort(key=lambda x: x["name"].lower())

    # Apply pagination
    total = len(all_specs)
    paginated = all_specs[offset : offset + limit]

    return {"specs": paginated, "total": total, "limit": limit, "offset": offset, "has_more": offset + limit < total}


@app.get("/specs/{name:path}/generated-code")
def get_generated_code(
    name: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    """Get the generated test code for a spec."""
    spec_path = SPECS_DIR / name
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail="Spec not found")

    # Filter by project_id if provided
    if project_id:
        meta = session.get(DBSpecMetadata, name)
        if meta and meta.project_id:
            if project_id == "default":
                if meta.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Spec not found")
            elif meta.project_id != project_id:
                raise HTTPException(status_code=404, detail="Spec not found")

    code_path = get_try_code_path(name, spec_path)
    if not code_path or not Path(code_path).exists():
        raise HTTPException(status_code=404, detail="No generated test found")

    code_file = Path(code_path)
    return {
        "code_path": str(code_file.relative_to(BASE_DIR)),
        "content": code_file.read_text(),
        "last_modified": code_file.stat().st_mtime,
    }


@app.put("/specs/{name:path}/generated-code")
def update_generated_code(
    name: str,
    request: UpdateGeneratedCodeRequest,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """Update the generated test code for a spec."""
    spec_path = SPECS_DIR / name
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail="Spec not found")

    # Verify project ownership if project_id is provided
    if project_id:
        meta = session.get(DBSpecMetadata, name)
        if meta and meta.project_id:
            # If spec has a project_id, it must match (unless checking default project with legacy data)
            if project_id == "default":
                if meta.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Spec not found")
            elif meta.project_id != project_id:
                raise HTTPException(status_code=404, detail="Spec not found")

    code_path = get_try_code_path(name, spec_path)
    if not code_path or not Path(code_path).exists():
        raise HTTPException(status_code=404, detail="No generated test found")

    Path(code_path).write_text(request.content)
    return {"status": "updated", "code_path": code_path}


@app.get("/specs/{name:path}")
def get_spec(
    name: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    f = SPECS_DIR / name
    if not f.exists():
        raise HTTPException(status_code=404, detail="Spec not found")

    # Filter by project_id if provided
    if project_id:
        meta = session.get(DBSpecMetadata, name)
        if meta and meta.project_id:
            if project_id == "default":
                if meta.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Spec not found")
            elif meta.project_id != project_id:
                raise HTTPException(status_code=404, detail="Spec not found")

    code_path = get_try_code_path(name, f)
    return {
        "name": str(f.relative_to(SPECS_DIR)),
        "path": str(f.absolute()),
        "content": f.read_text(),
        "is_automated": bool(code_path),
        "code_path": code_path,
    }


@app.post("/specs")
def create_spec(request: CreateSpecRequest, session: Session = Depends(get_session)):
    name = request.name
    if not name.endswith(".md"):
        name += ".md"
    f = SPECS_DIR / name
    if f.exists():
        raise HTTPException(status_code=400, detail="Spec already exists")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(request.content)

    # Register spec in database with project association
    if request.project_id:
        existing = session.get(DBSpecMetadata, name)
        if not existing:
            meta = DBSpecMetadata(spec_name=name, project_id=request.project_id, tags_json="[]")
            session.add(meta)
        else:
            existing.project_id = request.project_id
        session.commit()

    _spec_cache.invalidate()
    return {"status": "created", "path": str(f.absolute())}


@app.put("/specs/{name:path}")
def update_spec(
    name: str,
    request: UpdateSpecRequest,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    f = SPECS_DIR / name
    if not f.exists():
        raise HTTPException(status_code=404, detail="Spec not found")

    # Verify project ownership if project_id is provided
    if project_id:
        meta = session.get(DBSpecMetadata, name)
        if meta and meta.project_id:
            if project_id == "default":
                if meta.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Spec not found")
            elif meta.project_id != project_id:
                raise HTTPException(status_code=404, detail="Spec not found")

    f.write_text(request.content)
    _spec_cache.invalidate()
    return {"status": "updated", "path": str(f.absolute())}


@app.delete("/specs/folder/{folder_path:path}")
def delete_folder(
    folder_path: str,
    delete_generated_tests: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """Delete a folder and all specs inside it."""
    import shutil

    folder = SPECS_DIR / folder_path
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")

    deleted_specs = []
    deleted_tests = []

    # Collect all spec files in folder recursively
    spec_files = list(folder.glob("**/*.md"))

    # If project_id is provided, verify all specs in folder belong to project
    if project_id:
        for spec_path in spec_files:
            spec_name = str(spec_path.relative_to(SPECS_DIR))
            meta = session.get(DBSpecMetadata, spec_name)
            if meta and meta.project_id:
                if project_id == "default":
                    if meta.project_id not in (None, "default"):
                        raise HTTPException(
                            status_code=403, detail="Folder contains specs from other projects. Cannot delete."
                        )
                elif meta.project_id != project_id:
                    raise HTTPException(
                        status_code=403, detail="Folder contains specs from other projects. Cannot delete."
                    )

    for spec_path in spec_files:
        spec_name = str(spec_path.relative_to(SPECS_DIR))
        deleted_specs.append(spec_name)

        # Optionally delete generated tests
        if delete_generated_tests:
            code_path = get_try_code_path_fast(spec_path)
            if code_path and Path(code_path).exists():
                Path(code_path).unlink()
                deleted_tests.append(code_path)

        # Delete metadata from DB
        meta = session.get(DBSpecMetadata, spec_name)
        if meta:
            session.delete(meta)

        # Clear cache
        _spec_info_cache.pop(str(spec_path), None)

    session.commit()

    # Delete folder and all contents
    shutil.rmtree(folder)

    _spec_cache.invalidate()
    return {"status": "deleted", "folder": folder_path, "deleted_specs": deleted_specs, "deleted_tests": deleted_tests}


@app.delete("/specs/{name:path}")
def delete_spec(
    name: str,
    delete_generated_test: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """Delete a spec file and optionally its generated test."""
    spec_path = SPECS_DIR / name
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail="Spec not found")

    # Verify project ownership if project_id is provided
    if project_id:
        meta = session.get(DBSpecMetadata, name)
        if meta and meta.project_id:
            if project_id == "default":
                if meta.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Spec not found")
            elif meta.project_id != project_id:
                raise HTTPException(status_code=404, detail="Spec not found")

    code_path = get_try_code_path_fast(spec_path)
    deleted_files = [str(spec_path)]

    # Delete spec file
    spec_path.unlink()

    # Optionally delete generated test
    if delete_generated_test and code_path:
        code_file = Path(code_path)
        if code_file.exists():
            code_file.unlink()
            deleted_files.append(code_path)

    # Delete metadata from DB
    meta = session.get(DBSpecMetadata, name)
    if meta:
        session.delete(meta)
        session.commit()

    # Clear cache
    _spec_info_cache.pop(str(spec_path), None)
    _spec_cache.invalidate()

    return {"status": "deleted", "deleted_files": deleted_files}


@app.post("/specs/move", response_model=MoveSpecResponse)
def move_spec(request: MoveSpecRequest, session: Session = Depends(get_session)):
    """Move a spec file or folder to a new location.

    Moves specs and their associated generated test files.
    Updates database metadata entries accordingly.

    Args:
        request: MoveSpecRequest with source_path, destination_folder, is_folder flag

    Returns:
        MoveSpecResponse with details of moved specs and tests
    """
    source = SPECS_DIR / request.source_path
    is_template = request.source_path.startswith("templates/")

    # Validate source exists
    if request.is_folder:
        if not source.exists() or not source.is_dir():
            raise HTTPException(status_code=404, detail=f"Source folder not found: {request.source_path}")
    else:
        if not source.exists() or not source.is_file():
            raise HTTPException(status_code=404, detail=f"Source spec not found: {request.source_path}")

    # For templates, destination must also be within templates/ or be root (which means templates/)
    if is_template:
        if request.destination_folder:
            if not request.destination_folder.startswith("templates/"):
                raise HTTPException(status_code=400, detail="Cannot move templates outside of templates folder")
            dest_folder = SPECS_DIR / request.destination_folder
        else:
            # Empty destination for templates means templates/ root
            dest_folder = SPECS_DIR / "templates"
    else:
        # For regular specs, prevent moving into templates
        if request.destination_folder.startswith("templates/"):
            raise HTTPException(status_code=400, detail="Cannot move specs into templates folder")
        dest_folder = SPECS_DIR / request.destination_folder if request.destination_folder else SPECS_DIR

    # Prevent moving folder into itself
    if request.is_folder:
        source_abs = source.resolve()
        dest_abs = dest_folder.resolve()
        if str(dest_abs).startswith(str(source_abs)):
            raise HTTPException(status_code=400, detail="Cannot move a folder into itself")

    # Create destination folder if it doesn't exist
    dest_folder.mkdir(parents=True, exist_ok=True)

    # Determine new path
    source_name = source.name
    new_path = dest_folder / source_name

    # Check for conflicts
    if new_path.exists():
        raise HTTPException(status_code=409, detail=f"Destination already exists: {new_path.relative_to(SPECS_DIR)}")

    moved_specs: list[MovedItemInfo] = []
    moved_tests: list[MovedItemInfo] = []

    if request.is_folder:
        # Collect all spec files in folder before moving
        spec_files = list(source.glob("**/*.md"))

        # Verify project ownership if project_id is provided
        if request.project_id:
            for spec_path in spec_files:
                spec_name = str(spec_path.relative_to(SPECS_DIR))
                meta = session.get(DBSpecMetadata, spec_name)
                if meta and meta.project_id:
                    if request.project_id == "default":
                        if meta.project_id not in (None, "default"):
                            raise HTTPException(status_code=403, detail="Folder contains specs from other projects")
                    elif meta.project_id != request.project_id:
                        raise HTTPException(status_code=403, detail="Folder contains specs from other projects")

        # Move the folder
        shutil.move(str(source), str(new_path))

        # Update metadata for all specs in the moved folder
        for spec_path in spec_files:
            old_spec_name = str(spec_path.relative_to(SPECS_DIR))
            # Calculate new spec name
            relative_to_source = spec_path.relative_to(source)
            new_spec_path = new_path / relative_to_source
            new_spec_name = str(new_spec_path.relative_to(SPECS_DIR))

            moved_specs.append(MovedItemInfo(old_path=old_spec_name, new_path=new_spec_name))

            # Update DB metadata (delete old, create new if exists)
            old_meta = session.get(DBSpecMetadata, old_spec_name)
            if old_meta:
                # Copy metadata to new key
                new_meta = DBSpecMetadata(
                    spec_name=new_spec_name,
                    tags_json=old_meta.tags_json,
                    description=old_meta.description,
                    author=old_meta.author,
                    last_modified=old_meta.last_modified,
                    project_id=old_meta.project_id,
                )
                session.delete(old_meta)
                session.add(new_meta)

            # Move associated generated test if exists
            old_code_path = get_try_code_path_fast(spec_path)
            if old_code_path:
                old_code_file = Path(old_code_path)
                if old_code_file.exists():
                    # Generate new test path based on new spec name
                    new_stem = new_spec_path.stem.replace("_", "-")
                    new_code_path = BASE_DIR / "tests" / "generated" / f"{new_stem}.spec.ts"
                    new_code_path.parent.mkdir(parents=True, exist_ok=True)
                    if not new_code_path.exists():
                        shutil.move(str(old_code_file), str(new_code_path))
                        moved_tests.append(MovedItemInfo(old_path=str(old_code_file), new_path=str(new_code_path)))

            # Clear cache for old path
            _spec_info_cache.pop(str(spec_path), None)

    else:
        # Single file move
        old_spec_name = request.source_path
        new_spec_name = str(new_path.relative_to(SPECS_DIR))

        # Verify project ownership if project_id is provided
        if request.project_id:
            meta = session.get(DBSpecMetadata, old_spec_name)
            if meta and meta.project_id:
                if request.project_id == "default":
                    if meta.project_id not in (None, "default"):
                        raise HTTPException(status_code=404, detail="Spec not found")
                elif meta.project_id != request.project_id:
                    raise HTTPException(status_code=404, detail="Spec not found")

        # Move the file
        shutil.move(str(source), str(new_path))
        moved_specs.append(MovedItemInfo(old_path=old_spec_name, new_path=new_spec_name))

        # Update DB metadata
        old_meta = session.get(DBSpecMetadata, old_spec_name)
        if old_meta:
            new_meta = DBSpecMetadata(
                spec_name=new_spec_name,
                tags_json=old_meta.tags_json,
                description=old_meta.description,
                author=old_meta.author,
                last_modified=old_meta.last_modified,
                project_id=old_meta.project_id,
            )
            session.delete(old_meta)
            session.add(new_meta)

        # Move associated generated test if exists
        old_code_path = get_try_code_path_fast(source)
        if old_code_path:
            old_code_file = Path(old_code_path)
            if old_code_file.exists():
                # Generate new test path based on new spec name
                new_stem = new_path.stem.replace("_", "-")
                new_code_path = BASE_DIR / "tests" / "generated" / f"{new_stem}.spec.ts"
                new_code_path.parent.mkdir(parents=True, exist_ok=True)
                if not new_code_path.exists():
                    shutil.move(str(old_code_file), str(new_code_path))
                    moved_tests.append(MovedItemInfo(old_path=str(old_code_file), new_path=str(new_code_path)))

        # Clear cache
        _spec_info_cache.pop(str(source), None)

    session.commit()
    _spec_cache.invalidate()

    return MoveSpecResponse(
        status="moved",
        old_path=request.source_path,
        new_path=str(new_path.relative_to(SPECS_DIR)),
        moved_specs=moved_specs,
        moved_tests=moved_tests,
    )


@app.post("/specs/rename", response_model=RenameResponse)
def rename_spec(request: RenameRequest, session: Session = Depends(get_session)):
    """Rename a spec file or folder in-place.

    Unlike move, rename keeps the item in the same parent directory but changes its name.
    Also updates TestRun.spec_name and TestrailCaseMapping.spec_name cross-references.

    Args:
        request: RenameRequest with old_path, new_name, is_folder flag

    Returns:
        RenameResponse with details of renamed specs and tests
    """
    # Validate new_name format: lowercase alphanumeric, hyphens, underscores, dots
    name_pattern = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
    if not name_pattern.match(request.new_name):
        raise HTTPException(
            status_code=400, detail="Name must be lowercase alphanumeric with hyphens, underscores, or dots only"
        )

    source = SPECS_DIR / request.old_path

    # Validate source exists
    if request.is_folder:
        if not source.exists() or not source.is_dir():
            raise HTTPException(status_code=404, detail=f"Source folder not found: {request.old_path}")
    else:
        if not source.exists() or not source.is_file():
            raise HTTPException(status_code=404, detail=f"Source spec not found: {request.old_path}")
        # Ensure new_name ends with .md for files
        if not request.new_name.endswith(".md"):
            request.new_name = request.new_name + ".md"

    # Compute new path (same parent, different name)
    new_path = source.parent / request.new_name

    # Check destination doesn't already exist
    if new_path.exists():
        raise HTTPException(status_code=409, detail=f"Already exists: {new_path.relative_to(SPECS_DIR)}")

    renamed_specs: list[MovedItemInfo] = []
    renamed_tests: list[MovedItemInfo] = []

    if request.is_folder:
        # Collect all spec files in folder before renaming
        spec_files = list(source.glob("**/*.md"))

        # Verify project ownership if project_id is provided
        if request.project_id:
            for spec_path in spec_files:
                spec_name = str(spec_path.relative_to(SPECS_DIR))
                meta = session.get(DBSpecMetadata, spec_name)
                if meta and meta.project_id:
                    if request.project_id == "default":
                        if meta.project_id not in (None, "default"):
                            raise HTTPException(status_code=403, detail="Folder contains specs from other projects")
                    elif meta.project_id != request.project_id:
                        raise HTTPException(status_code=403, detail="Folder contains specs from other projects")

        # Rename the folder
        shutil.move(str(source), str(new_path))

        # Update metadata and cross-references for all specs
        for spec_path in spec_files:
            old_spec_name = str(spec_path.relative_to(SPECS_DIR))
            relative_to_source = spec_path.relative_to(source)
            new_spec_path = new_path / relative_to_source
            new_spec_name = str(new_spec_path.relative_to(SPECS_DIR))

            renamed_specs.append(MovedItemInfo(old_path=old_spec_name, new_path=new_spec_name))

            # Update DB metadata (delete old, create new)
            old_meta = session.get(DBSpecMetadata, old_spec_name)
            if old_meta:
                new_meta = DBSpecMetadata(
                    spec_name=new_spec_name,
                    tags_json=old_meta.tags_json,
                    description=old_meta.description,
                    author=old_meta.author,
                    last_modified=old_meta.last_modified,
                    project_id=old_meta.project_id,
                )
                session.delete(old_meta)
                session.add(new_meta)

            # Update TestRun references
            runs_to_update = session.exec(select(DBTestRun).where(DBTestRun.spec_name == old_spec_name)).all()
            for run in runs_to_update:
                run.spec_name = new_spec_name
                session.add(run)

            # Update TestrailCaseMapping references
            mappings_to_update = session.exec(
                select(TestrailCaseMapping).where(TestrailCaseMapping.spec_name == old_spec_name)
            ).all()
            for mapping in mappings_to_update:
                mapping.spec_name = new_spec_name
                session.add(mapping)

            # Move associated generated test if exists
            old_code_path = get_try_code_path_fast(spec_path)
            if old_code_path:
                old_code_file = Path(old_code_path)
                if old_code_file.exists():
                    new_stem = new_spec_path.stem.replace("_", "-")
                    new_code_path = BASE_DIR / "tests" / "generated" / f"{new_stem}.spec.ts"
                    new_code_path.parent.mkdir(parents=True, exist_ok=True)
                    if not new_code_path.exists():
                        shutil.move(str(old_code_file), str(new_code_path))
                        renamed_tests.append(MovedItemInfo(old_path=str(old_code_file), new_path=str(new_code_path)))

            # Clear cache
            _spec_info_cache.pop(str(spec_path), None)

    else:
        # Single file rename
        old_spec_name = request.old_path
        new_spec_name = str(new_path.relative_to(SPECS_DIR))

        # Verify project ownership
        if request.project_id:
            meta = session.get(DBSpecMetadata, old_spec_name)
            if meta and meta.project_id:
                if request.project_id == "default":
                    if meta.project_id not in (None, "default"):
                        raise HTTPException(status_code=404, detail="Spec not found")
                elif meta.project_id != request.project_id:
                    raise HTTPException(status_code=404, detail="Spec not found")

        # Rename the file
        shutil.move(str(source), str(new_path))
        renamed_specs.append(MovedItemInfo(old_path=old_spec_name, new_path=new_spec_name))

        # Update DB metadata
        old_meta = session.get(DBSpecMetadata, old_spec_name)
        if old_meta:
            new_meta = DBSpecMetadata(
                spec_name=new_spec_name,
                tags_json=old_meta.tags_json,
                description=old_meta.description,
                author=old_meta.author,
                last_modified=old_meta.last_modified,
                project_id=old_meta.project_id,
            )
            session.delete(old_meta)
            session.add(new_meta)

        # Update TestRun references
        runs_to_update = session.exec(select(DBTestRun).where(DBTestRun.spec_name == old_spec_name)).all()
        for run in runs_to_update:
            run.spec_name = new_spec_name
            session.add(run)

        # Update TestrailCaseMapping references
        mappings_to_update = session.exec(
            select(TestrailCaseMapping).where(TestrailCaseMapping.spec_name == old_spec_name)
        ).all()
        for mapping in mappings_to_update:
            mapping.spec_name = new_spec_name
            session.add(mapping)

        # Move associated generated test if exists
        old_code_path = get_try_code_path_fast(source)
        if old_code_path:
            old_code_file = Path(old_code_path)
            if old_code_file.exists():
                new_stem = new_path.stem.replace("_", "-")
                new_code_path = BASE_DIR / "tests" / "generated" / f"{new_stem}.spec.ts"
                new_code_path.parent.mkdir(parents=True, exist_ok=True)
                if not new_code_path.exists():
                    shutil.move(str(old_code_file), str(new_code_path))
                    renamed_tests.append(MovedItemInfo(old_path=str(old_code_file), new_path=str(new_code_path)))

        # Clear cache
        _spec_info_cache.pop(str(source), None)

    session.commit()
    _spec_cache.invalidate()

    return RenameResponse(
        status="renamed",
        old_path=request.old_path,
        new_path=str(new_path.relative_to(SPECS_DIR)),
        renamed_specs=renamed_specs,
        renamed_tests=renamed_tests,
    )


@app.post("/specs/create-folder", response_model=CreateFolderResponse)
def create_folder(request: CreateFolderRequest):
    """Create an empty folder in the specs directory.

    Args:
        request: CreateFolderRequest with folder_name and optional parent_path

    Returns:
        CreateFolderResponse with created path
    """
    # Validate folder name format
    name_pattern = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
    if not name_pattern.match(request.folder_name):
        raise HTTPException(
            status_code=400, detail="Folder name must be lowercase alphanumeric with hyphens or underscores only"
        )

    # Resolve target path
    if request.parent_path:
        parent = SPECS_DIR / request.parent_path
        if not parent.exists() or not parent.is_dir():
            raise HTTPException(status_code=404, detail=f"Parent folder not found: {request.parent_path}")
    else:
        parent = SPECS_DIR

    target = parent / request.folder_name

    # Check target doesn't already exist
    if target.exists():
        raise HTTPException(status_code=409, detail=f"Folder already exists: {target.relative_to(SPECS_DIR)}")

    target.mkdir(parents=False, exist_ok=False)

    return CreateFolderResponse(status="created", path=str(target.relative_to(SPECS_DIR)))


@app.post("/specs/register-folder")
def register_folder_specs(folder: str, project_id: str, session: Session = Depends(get_session)):
    """
    Register all specs in a folder to a project.

    This endpoint is useful for migrating existing unregistered specs
    (created before project support) to a specific project.

    Args:
        folder: Folder path relative to specs directory (e.g., "explorer-my-auth-flow")
        project_id: Project ID to associate specs with

    Returns:
        Count and list of registered spec names
    """
    folder_path = SPECS_DIR / folder
    if not folder_path.exists():
        raise HTTPException(status_code=404, detail=f"Folder not found: {folder}")

    if not folder_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a folder: {folder}")

    # Verify project exists (unless it's "default")
    if project_id and project_id != "default":
        from orchestrator.api.models_db import Project

        project = session.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    registered = []
    updated = []

    for f in folder_path.glob("**/*.md"):
        spec_name = str(f.relative_to(SPECS_DIR))
        existing = session.get(DBSpecMetadata, spec_name)

        if not existing:
            # Create new metadata record
            meta = DBSpecMetadata(spec_name=spec_name, project_id=project_id, tags_json="[]")
            session.add(meta)
            registered.append(spec_name)
        else:
            # Update existing record if project changed
            if existing.project_id != project_id:
                existing.project_id = project_id
                updated.append(spec_name)

    session.commit()

    return {
        "registered": len(registered),
        "updated": len(updated),
        "specs": registered + updated,
        "folder": folder,
        "project_id": project_id,
    }


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
        meta = session.get(DBSpecMetadata, spec_name)
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


# ========= PRD Spec Detection & Splitting =========


class SpecInfoResponse(BaseModel):
    name: str
    type: str  # "standard", "prd", or "template"
    test_count: int
    categories: list[str]
    test_cases: list[dict[str, Any]]


class SplitSpecRequest(BaseModel):
    spec_name: str
    output_dir: str | None = None
    project_id: str | None = None  # Project to assign split specs to
    mode: str | None = "individual"  # "individual" or "grouped"


class SplitSpecResponse(BaseModel):
    count: int
    files: list[str]
    output_dir: str
    groups: list[dict[str, Any]] | None = None  # AI grouping suggestions


@app.get("/specs/{name:path}/info", response_model=SpecInfoResponse)
def get_spec_info(name: str):
    """Get information about a spec, including PRD detection."""
    from utils.spec_detector import SpecDetector

    spec_path = SPECS_DIR / name
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail="Spec not found")

    info = SpecDetector.get_spec_info(spec_path)

    return SpecInfoResponse(
        name=name,
        type=info["type"],
        test_count=info["test_count"],
        categories=info["categories"],
        test_cases=info["test_cases"],
    )


@app.post("/specs/split", response_model=SplitSpecResponse)
def split_prd_spec(request: SplitSpecRequest, session: Session = Depends(get_session)):
    """Split a multi-test spec (PRD, Native Plan, or multi-test) into individual test specs."""
    from utils.prd_spec_splitter import PRDSpecSplitter
    from utils.spec_detector import SpecDetector, SpecType

    spec_path = SPECS_DIR / request.spec_name
    if not spec_path.exists():
        raise HTTPException(status_code=404, detail="Spec not found")

    # Verify it's a splittable spec
    spec_type = SpecDetector.detect_spec_type(spec_path)
    is_splittable = spec_type in (SpecType.PRD, SpecType.NATIVE_PLAN, SpecType.STANDARD_MULTI)

    # Also allow STANDARD specs that have TC patterns (AI will handle extraction)
    if not is_splittable:
        content = spec_path.read_text()
        pattern_count = SpecDetector.count_test_patterns(content)
        if pattern_count < 2:
            raise HTTPException(status_code=400, detail=f"Spec is not a multi-test spec (detected type: {spec_type})")

    # Determine output directory
    if request.output_dir:
        output_dir = SPECS_DIR / request.output_dir
    else:
        output_dir = None  # Will use default

    # Split the spec
    try:
        split_files, groups = PRDSpecSplitter.split_spec(spec_path, output_dir, mode=request.mode or "individual")

        # Convert paths to relative names
        file_names = [str(f.relative_to(SPECS_DIR)) for f in split_files]

        # Assign split specs to project if specified
        if request.project_id and file_names:
            for spec_name in file_names:
                # Create or update spec metadata with project assignment
                existing = session.exec(select(DBSpecMetadata).where(DBSpecMetadata.spec_name == spec_name)).first()

                if existing:
                    existing.project_id = request.project_id
                else:
                    new_metadata = DBSpecMetadata(spec_name=spec_name, project_id=request.project_id)
                    session.add(new_metadata)

            session.commit()

        return SplitSpecResponse(
            count=len(split_files),
            files=file_names,
            output_dir=str(split_files[0].parent.relative_to(SPECS_DIR)) if split_files else "",
            groups=groups,
        )
    except Exception as e:
        logger.error(f"Failed to split spec: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ========= Runs =========


class PaginatedRunsResponse(BaseModel):
    runs: list[TestRun]
    total: int
    limit: int
    offset: int
    has_more: bool


@app.get("/runs")
def list_runs(
    session: Session = Depends(get_session),
    limit: int = 20,
    offset: int = 0,
    project_id: str | None = None,
    status: str | None = Query(None, description="Filter by status (passed, failed, error, stopped, running)"),
    search: str | None = Query(None, description="Search by test name"),
):
    """List runs with pagination support.

    Args:
        limit: Number of runs to return (default 20, max 100)
        offset: Number of runs to skip (for pagination)
        project_id: Optional project ID to filter runs
        status: Optional status filter
        search: Optional test name search

    Returns:
        PaginatedRunsResponse with runs array and pagination metadata
    """
    # Cap limit to prevent abuse
    limit = min(limit, 100)

    # Build base query with optional project filter
    base_query = select(DBTestRun)
    if project_id:
        base_query = base_query.where(DBTestRun.project_id == project_id)

    # Get total count efficiently using SQL COUNT
    count_query = select(func.count()).select_from(DBTestRun)
    if project_id:
        count_query = count_query.where(DBTestRun.project_id == project_id)

    # Apply status filter
    if status:
        status_map = {
            "passed": ["completed", "passed", "success"],
            "failed": ["failed", "failure"],
            "running": ["running", "in_progress"],
            "error": ["error"],
            "stopped": ["stopped"],
            "queued": ["queued"],
            "pending": ["pending"],
        }
        status_values = status_map.get(status.lower(), [status])
        base_query = base_query.where(DBTestRun.status.in_(status_values))
        count_query = count_query.where(DBTestRun.status.in_(status_values))

    # Apply search filter
    if search:
        base_query = base_query.where(DBTestRun.test_name.ilike(f"%{search}%"))
        count_query = count_query.where(DBTestRun.test_name.ilike(f"%{search}%"))

    total = session.exec(count_query).one()

    # Fetch paginated runs from DB
    statement = base_query.order_by(DBTestRun.created_at.desc()).offset(offset).limit(limit)
    runs_db = session.exec(statement).all()

    # Convert to API model
    results = []
    for r in runs_db:
        # Format timestamp as YYYY-MM-DD_HH-MM-SS to match frontend expectation
        timestamp = r.created_at.strftime("%Y-%m-%d_%H-%M-%S")

        # Check if this run actually has an active process
        canStop = is_process_active(r.id)

        # Format timestamps
        queued_at = r.queued_at.isoformat() if r.queued_at else None
        started_at = r.started_at.isoformat() if r.started_at else None
        completed_at = r.completed_at.isoformat() if r.completed_at else None
        stage_started_at = r.stage_started_at.isoformat() if r.stage_started_at else None

        results.append(
            TestRun(
                id=r.id,
                timestamp=timestamp,
                status=r.status,
                test_name=r.test_name,
                spec_name=r.spec_name,
                steps_completed=r.steps_completed,
                total_steps=r.total_steps,
                browser=r.browser,
                canStop=canStop,
                queue_position=r.queue_position,
                queued_at=queued_at,
                started_at=started_at,
                completed_at=completed_at,
                batch_id=r.batch_id,
                error_message=r.error_message,
                current_stage=r.current_stage,
                stage_started_at=stage_started_at,
                stage_message=r.stage_message,
                healing_attempt=r.healing_attempt,
            )
        )

    return PaginatedRunsResponse(
        runs=results, total=total, limit=limit, offset=offset, has_more=(offset + limit) < total
    )


@app.get("/runs/{id}")
def get_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    run_db = session.get(DBTestRun, id)
    # If not in DB, it might be a very old run or filesystem issue, but we sync on startup.
    # So we trust DB for existence.
    if not run_db:
        raise HTTPException(status_code=404, detail="Run not found")

    # Filter by project_id if provided
    if project_id:
        if run_db.project_id:
            if project_id == "default":
                if run_db.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Run not found")
            elif run_db.project_id != project_id:
                raise HTTPException(status_code=404, detail="Run not found")

    run_dir = RUNS_DIR / id
    # If directory is missing, we only have DB info
    if not run_dir.exists():
        return {
            "id": id,
            "status": run_db.status,
            "spec_name": run_db.spec_name,
            "test_name": run_db.test_name,
            "note": "Files missing",
        }

    # Load file details
    plan_file = run_dir / "plan.json"
    run_file = run_dir / "run.json"
    export_file = run_dir / "export.json"
    export_file = run_dir / "export.json"
    validation_file = run_dir / "validation.json"

    data = {"id": id, "spec_name": run_db.spec_name, "test_name": run_db.test_name}

    # Check runtime status if not completed
    if run_db.status in ["running", "pending"] and not is_process_active(id):
        # If it's supposedly running but not in our memory, it might have died or server restarted
        # We can't easily know unless we check the process, but the process dict is memory-only.
        # For now, trust DB, but UI might want to know if it's "live".
        pass

    if plan_file.exists():
        data["plan"] = json.loads(plan_file.read_text())
    if run_file.exists():
        data["run"] = json.loads(run_file.read_text())
    if export_file.exists():
        export_data = json.loads(export_file.read_text())
        data["export"] = export_data
        test_path_str = export_data.get("testFilePath")
        if test_path_str:
            test_path = BASE_DIR / test_path_str
            if test_path.exists():
                data["generated_code"] = test_path.read_text()
            else:
                test_path = run_dir / test_path_str
                if test_path.exists():
                    data["generated_code"] = test_path.read_text()
    if validation_file.exists():
        data["validation"] = json.loads(validation_file.read_text())

    # Compute effective status considering validation result
    effective_status = "unknown"
    if data.get("validation", {}).get("status") == "success":
        effective_status = "passed"
    elif data.get("validation", {}).get("status") == "failed":
        effective_status = "failed"
    elif data.get("run", {}).get("finalState"):
        effective_status = data["run"]["finalState"]
    elif run_db and run_db.status:
        effective_status = run_db.status
    data["effective_status"] = effective_status

    execution_log = run_dir / "execution.log"
    if execution_log.exists():
        data["log"] = execution_log.read_text()

    artifacts = []
    for f in run_dir.glob("**/*"):
        if f.is_file() and f.suffix.lower() in [".png", ".jpg", ".jpeg", ".webm", ".mp4"]:
            try:
                rel_path = f.relative_to(RUNS_DIR)
                artifacts.append(
                    {
                        "name": f.name,
                        "path": f"/artifacts/{rel_path}",
                        "type": "image" if f.suffix.lower() in [".png", ".jpg", ".jpeg"] else "video",
                    }
                )
            except ValueError:
                continue
    data["artifacts"] = artifacts

    report_index = run_dir / "report" / "index.html"
    if report_index.exists():
        data["report_url"] = f"/artifacts/{id}/report/index.html"

    return data


@app.delete("/runs/{id}", status_code=204)
def delete_run(id: str, session: Session = Depends(get_session)):
    """Delete a test run and its artifacts."""
    run_db = session.get(DBTestRun, id)
    if not run_db:
        raise HTTPException(status_code=404, detail="Run not found")

    # Don't allow deleting active runs
    if run_db.status in ("running", "in_progress", "queued", "pending"):
        raise HTTPException(status_code=409, detail="Cannot delete an active run")

    session.delete(run_db)
    session.commit()

    return Response(status_code=204)


# ========= Progress Tracking Endpoints =========


class ProgressUpdate(BaseModel):
    """Request model for updating run progress."""

    stage: str  # "planning", "generating", "testing", "healing"
    message: str | None = None
    healing_attempt: int | None = None


@app.post("/runs/{id}/progress")
def update_run_progress(id: str, update: ProgressUpdate, session: Session = Depends(get_session)):
    """Update run progress - called by CLI to report stage transitions.

    This endpoint is called by the CLI/pipeline to report real-time progress:
    - Stage transitions (planning -> generating -> testing -> healing)
    - Detailed status messages
    - Healing attempt numbers

    The frontend polls this data to show progress during execution.
    """
    run = session.get(DBTestRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Update stage information
    run.current_stage = update.stage
    run.stage_started_at = datetime.utcnow()
    if update.message:
        run.stage_message = update.message
    if update.healing_attempt is not None:
        run.healing_attempt = update.healing_attempt

    session.add(run)
    session.commit()

    logger.debug(f"Progress update for {id}: stage={update.stage}, message={update.message}")

    return {"status": "updated", "run_id": id, "current_stage": run.current_stage, "stage_message": run.stage_message}


@app.get("/runs/{id}/log/stream")
async def stream_run_log(id: str, session: Session = Depends(get_session)):
    """Stream execution log in real-time using Server-Sent Events (SSE).

    This endpoint streams the execution.log file content as new lines are written.
    The frontend uses EventSource to receive updates in real-time.

    Response format (SSE):
        data: {"log": "new log content..."}
        data: {"status": "complete", "final_status": "passed"}
    """
    from fastapi.responses import StreamingResponse

    run = session.get(DBTestRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    run_dir = RUNS_DIR / id
    log_file = run_dir / "execution.log"

    def _read_log_from_position(log_path, position):
        """Read log file from a given position. Returns (content, new_position)."""
        if not log_path.exists():
            return "", position
        with open(log_path) as f:
            f.seek(position)
            content = f.read()
            return content, f.tell()

    async def generate():
        last_position = 0
        consecutive_no_change = 0

        try:
            while True:
                try:
                    # Check if run completed
                    with Session(engine) as check_session:
                        current_run = check_session.get(DBTestRun, id)
                        if current_run and current_run.status in ["passed", "failed", "stopped", "cancelled", "error"]:
                            # Send any remaining log content
                            remaining, _ = await asyncio.to_thread(_read_log_from_position, log_file, last_position)
                            if remaining:
                                yield f"data: {json.dumps({'log': remaining})}\n\n"

                            # Send completion event
                            yield f"data: {json.dumps({'status': 'complete', 'final_status': current_run.status})}\n\n"
                            break

                    # Read new log content
                    new_content, new_position = await asyncio.to_thread(
                        _read_log_from_position, log_file, last_position
                    )
                    if new_content:
                        yield f"data: {json.dumps({'log': new_content})}\n\n"
                        last_position = new_position
                        consecutive_no_change = 0
                    else:
                        consecutive_no_change += 1

                    # Timeout after 10 minutes of no activity
                    if consecutive_no_change > 600:  # 600 * 1s = 10 minutes
                        yield f"data: {json.dumps({'status': 'timeout', 'message': 'Stream timed out after 10 minutes of no activity'})}\n\n"
                        break

                    await asyncio.sleep(1)

                except Exception as e:
                    logger.error(f"Error streaming log for {id}: {e}")
                    yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
                    break
        except (asyncio.CancelledError, GeneratorExit):
            pass  # Client disconnected
        finally:
            logger.debug(f"Log stream ended for run {id}")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
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
            batch.stopped = sum(1 for r in runs if r.status == "stopped")
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

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update batch stats for {batch_id}: {e}", exc_info=True)
            raise


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
                    r for r in stuck_runs if r.started_at is not None or (r.queued_at and r.queued_at < cutoff)
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
        from orchestrator.services.scheduler import cleanup_stale_executions

        await cleanup_stale_executions()
    except Exception as e:
        logger.debug(f"Stale execution cleanup on startup: {e}")

    while True:
        try:
            await asyncio.sleep(30)

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
):
    """Execute the native pipeline (default) with optional hybrid healing mode.

    Native pipeline is always used. The only choice is healing mode:
    - hybrid=False: Native Healer (3 attempts using test_debug)
    - hybrid=True: Native + Ralph (3 attempts + up to 17 more)

    Process groups are used to ensure all child processes can be terminated together.
    """
    global PROCESS_MANAGER

    cmd = [sys.executable, "orchestrator/cli.py", spec_path, "--run-dir", run_dir, "--browser", browser]
    if try_code_path:
        cmd.extend(["--try-code", try_code_path])
    if hybrid:
        cmd.extend(["--hybrid", "--max-iterations", str(max_iterations)])

    run_dir_path = Path(run_dir)

    # Write run-specific .mcp.json BEFORE subprocess starts
    # This ensures each parallel run has its own isolated MCP config
    mcp_output_dir = run_dir_path / "mcp-output"
    mcp_output_dir.mkdir(parents=True, exist_ok=True)

    # Create MCP config for the test runner
    mcp_args = ["playwright", "run-test-mcp-server"]
    if headless:
        mcp_args.append("--headless")

    mcp_config = {"mcpServers": {"playwright-test": {"command": "npx", "args": mcp_args}}}
    run_mcp_config_path = run_dir_path / ".mcp.json"
    with open(run_mcp_config_path, "w") as f:
        json.dump(mcp_config, f, indent=2)

    logger.info(f"Created MCP config for run {run_id} (headless={headless})")

    # Copy .claude/ agents directory to run directory for isolation
    # This ensures agent configs are local to each run
    claude_src = BASE_DIR / ".claude"
    claude_dst = run_dir_path / ".claude"
    if claude_src.exists() and not claude_dst.exists():
        shutil.copytree(claude_src, claude_dst, dirs_exist_ok=True)

    # Copy Playwright config to run directory with absolute paths
    # The workflow scripts change to CLAUDE_CONFIG_DIR for MCP config isolation,
    # but Playwright needs its config file in the current directory with correct paths
    playwright_config_src = BASE_DIR / "playwright.config.ts"
    playwright_config_dst = run_dir_path / "playwright.config.ts"
    if playwright_config_src.exists() and not playwright_config_dst.exists():
        config_content = playwright_config_src.read_text()
        # Convert relative paths to absolute paths so Playwright finds tests from run directory
        config_content = config_content.replace(
            "testDir: './tests/generated'", f"testDir: '{BASE_DIR}/tests/generated'"
        )
        config_content = config_content.replace(
            'testDir: "./tests/generated"', f'testDir: "{BASE_DIR}/tests/generated"'
        )
        # Also fix outputDir to use run directory for test results
        config_content = config_content.replace(
            "outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || './test-results'",
            f"outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || '{run_dir_path}/test-results'",
        )
        playwright_config_dst.write_text(config_content)

    # Copy seed file to run directory for generator_setup_page
    # The MCP server runs from the run directory, so it needs the seed file locally
    # This is required because generator_setup_page looks for seed files relative to cwd
    seed_src = BASE_DIR / "tests" / "seed.spec.ts"
    seed_dst = run_dir_path / "tests" / "seed.spec.ts"
    if seed_src.exists():
        seed_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(seed_src, seed_dst)
        logger.debug(f"Copied seed file to run directory: {seed_dst}")

    # Set up environment with headless, memory, and config directory settings
    env = os.environ.copy()
    env["HEADLESS"] = "true" if headless else "false"
    env["PLAYWRIGHT_HEADLESS"] = "true" if headless else "false"
    env["MEMORY_ENABLED"] = "true" if memory_enabled else "false"
    # Tell workflows to use run-specific config directory
    env["CLAUDE_CONFIG_DIR"] = str(run_dir_path)
    # Pass project_id for credentials and memory isolation
    if project_id:
        env["PROJECT_ID"] = project_id
        env["MEMORY_PROJECT_ID"] = project_id

    log_file = Path(run_dir) / "execution.log"
    with open(log_file, "w") as f:
        # Use Popen with start_new_session=True to create a new process group
        # This allows terminating all child processes (browser, node, etc.) together
        process = subprocess.Popen(
            cmd,
            cwd=BASE_DIR,
            stdout=f,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,  # Creates new process group for clean termination
        )

        # Get process group ID for termination
        try:
            pgid = os.getpgid(process.pid)
        except (ProcessLookupError, OSError):
            pgid = process.pid  # Fallback to PID if pgid fails

        # Store process handle in memory (thread-safe)
        register_process(run_id, process)

        # Register with ProcessManager for persistent tracking
        if PROCESS_MANAGER:
            PROCESS_MANAGER.register(run_id=run_id, pid=process.pid, pgid=pgid, spec_name=spec_name, batch_id=batch_id)

        logger.info(f"Started process for {run_id}: pid={process.pid}, pgid={pgid}")

        try:
            # Wait with timeout to prevent indefinite hangs
            # 1 hour max per run (planning + generation + healing)
            process.wait(timeout=3600)
        except subprocess.TimeoutExpired:
            logger.warning(f"Process for {run_id} timed out after 3600s, killing process group")
            import signal as _signal

            try:
                os.killpg(os.getpgid(process.pid), _signal.SIGKILL)
            except (ProcessLookupError, OSError):
                try:
                    process.kill()
                except (ProcessLookupError, OSError):
                    pass
            process.wait(timeout=10)  # Wait for kill to take effect
        finally:
            # Cleanup from memory (thread-safe)
            unregister_process(run_id)

            # Cleanup from ProcessManager
            if PROCESS_MANAGER:
                PROCESS_MANAGER.unregister(run_id)

            logger.info(f"Process completed for {run_id}: exit_code={process.returncode}")


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
):
    """Async wrapper for execute_run_task with unified browser queue management.

    Uses BrowserResourcePool to limit concurrent browser operations across
    ALL operation types (test runs, explorations, agents, PRD).

    Note: BROWSER_POOL is initialized at startup in startup_event().
    """
    # Get execution settings for this run
    headless = False
    memory_enabled = True
    with Session(engine) as session:
        settings = session.get(DBExecutionSettings, 1)
        if settings:
            # Always respect headless setting (user can force headless for any run)
            headless = settings.headless_in_parallel
            memory_enabled = settings.memory_enabled

    # Use unified browser pool for slot management
    pool = BROWSER_POOL or await get_browser_pool()

    # Block if a load test is running
    from orchestrator.services.load_test_lock import check_system_available

    await check_system_available("test run")

    try:
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

            # Update status to 'running' and set started_at
            # Guard: check if the run was stopped/cancelled while waiting in queue
            with Session(engine) as session:
                run = session.get(DBTestRun, run_id)
                if run:
                    if run.status in ("stopped", "cancelled"):
                        logger.info(f"Run {run_id} was {run.status} while queued. Aborting.")
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
            )

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
                                if not run.error_message and error_data.get("error"):
                                    error_msg = error_data["error"][:500]
                                    stage = error_data.get("stage", "")
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

            # Update batch stats after run completion
            if batch_id:
                update_batch_stats(batch_id)

    except asyncio.CancelledError:
        # Task was cancelled while waiting or running
        logger.info(f"Run {run_id} cancelled")
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


class RunRequest(BaseModel):
    """Request model for creating a test run.

    Native pipeline is always used. The only choice is healing mode:
    - hybrid=False: Native Healer (3 attempts using test_debug)
    - hybrid=True: Hybrid (Native 3 attempts + Ralph up to 17 more)

    Legacy fields (ralph, native_healer, native_generator) are kept for
    backward compatibility but are mapped to the new behavior.
    """

    spec_name: str
    browser: str | None = "chromium"
    hybrid: bool | None = False  # Default: Native Healer only
    max_iterations: int | None = 20  # Only used with hybrid=True
    project_id: str | None = None  # Project to associate run with

    # Legacy fields - kept for backward compatibility
    ralph: bool | None = False
    native_healer: bool | None = False
    native_generator: bool | None = False


def get_try_code_path(spec_name: str, spec_path: Path) -> str | None:
    """
    Get the generated test file path for a spec.

    Uses a TTL-based cache to avoid expensive filesystem scans.
    Falls back to run directory scanning only on cache miss.
    """
    global _code_path_cache

    # Check cache first
    if spec_name in _code_path_cache:
        cached_path, cached_time = _code_path_cache[spec_name]
        if time_module.time() - cached_time < _CODE_PATH_CACHE_TTL:
            # Verify file still exists
            if cached_path and Path(cached_path).exists():
                return cached_path
            # Fall through to recompute if file doesn't exist

    # Try fast path first (filename patterns only)
    try_code_path = get_try_code_path_fast(spec_path)

    # If fast path found a file, cache and return
    if try_code_path:
        if len(_code_path_cache) >= _MAX_CODE_CACHE_SIZE:
            keys = list(_code_path_cache.keys())
            for k in keys[: len(keys) // 2]:
                del _code_path_cache[k]
        _code_path_cache[spec_name] = (try_code_path, time_module.time())
        return try_code_path

    # Fall back to slow path: scan run directories
    spec_test_name = None
    if spec_path.exists():
        content = spec_path.read_text()
        for line in content.split("\n"):
            if line.startswith("# "):
                spec_test_name = line.replace("# ", "").replace("Test:", "").strip()
                break

    # Search previous runs - limit to recent runs for performance
    if RUNS_DIR.exists():
        run_dirs = sorted(
            [d for d in RUNS_DIR.iterdir() if d.is_dir()], key=lambda x: os.path.getmtime(x), reverse=True
        )[:100]  # Limit to 100 most recent runs for performance

        for r_dir in run_dirs:
            plan_file = r_dir / "plan.json"
            export_file = r_dir / "export.json"
            if plan_file.exists() and export_file.exists():
                try:
                    plan = json.loads(plan_file.read_text())
                    match = False
                    if plan.get("specFileName") == spec_name:
                        match = True
                    elif spec_test_name and plan.get("testName"):
                        t1 = plan.get("testName").lower().strip()
                        t2 = spec_test_name.lower().strip()
                        if t1 == t2 or t1 in t2 or t2 in t1:
                            match = True
                    if match:
                        export = json.loads(export_file.read_text())
                        path_str = export.get("testFilePath")
                        if path_str:
                            candidate = BASE_DIR / path_str
                            if not candidate.exists():
                                candidate = r_dir / path_str
                            if candidate.exists():
                                try_code_path = str(candidate)
                                break
                except json.JSONDecodeError as e:
                    logger.debug(f"Invalid JSON in {plan_file} or {export_file}: {e}")
                except OSError as e:
                    logger.debug(f"Cannot read {plan_file} or {export_file}: {e}")
            if try_code_path:
                break

    # If still not found, check additional patterns using test name
    if not try_code_path and spec_test_name:
        import re

        test_slug = re.sub(r"[^a-z0-9]+", "-", spec_test_name.lower()).strip("-")
        candidates = [
            f"tests/templates/{test_slug}.spec.ts",
            f"tests/generated/{test_slug}.spec.ts",
        ]
        for c in candidates:
            if (BASE_DIR / c).exists():
                try_code_path = str(BASE_DIR / c)
                break

    # Cache the result (even if None, to avoid repeated scans)
    if len(_code_path_cache) >= _MAX_CODE_CACHE_SIZE:
        keys = list(_code_path_cache.keys())
        for k in keys[: len(keys) // 2]:
            del _code_path_cache[k]
    _code_path_cache[spec_name] = (try_code_path, time_module.time())
    return try_code_path


def invalidate_code_path_cache(spec_name: str | None = None):
    """Invalidate code path cache for a spec or all specs.

    Call this after test generation completes to ensure fresh lookups.
    """
    global _code_path_cache
    if spec_name:
        _code_path_cache.pop(spec_name, None)
    else:
        _code_path_cache.clear()


@app.post("/runs")
async def create_run(request: RunRequest, session: Session = Depends(get_session)):
    """Create a new test run.

    Always uses the Native Pipeline (browser exploration at every stage).
    Healing mode is controlled by the `hybrid` flag:
    - hybrid=False: Native Healer only (3 attempts)
    - hybrid=True: Native + Ralph (3 + up to 17 more attempts)
    """
    global PROCESS_MANAGER

    spec_path = SPECS_DIR / request.spec_name
    if not spec_path.exists():
        # Try appending .md extension
        if not request.spec_name.endswith(".md"):
            candidate = SPECS_DIR / (request.spec_name + ".md")
            if candidate.exists():
                spec_path = candidate
                request.spec_name = request.spec_name + ".md"

        # If still not found, try to find spec by slug matching
        # (handles case where AI passes human-friendly name like "Navigate from Homepage")
        if not spec_path.exists():
            import re as _re

            slug = _re.sub(r"[^a-z0-9]+", "-", request.spec_name.lower()).strip("-")
            for pattern in [f"**/{slug}.md", f"**/{slug}*.md"]:
                matches = list(SPECS_DIR.glob(pattern))
                if matches:
                    spec_path = matches[0]
                    request.spec_name = str(spec_path.relative_to(SPECS_DIR))
                    break

        # Last resort: search DB for a run with matching test_name and reuse its spec_name
        if not spec_path.exists():
            matching_run = session.exec(
                select(DBTestRun)
                .where(DBTestRun.test_name == request.spec_name)
                .order_by(DBTestRun.created_at.desc())
                .limit(1)
            ).first()
            if matching_run and matching_run.spec_name:
                candidate = SPECS_DIR / matching_run.spec_name
                if candidate.exists():
                    spec_path = candidate
                    request.spec_name = matching_run.spec_name

        if not spec_path.exists():
            raise HTTPException(status_code=404, detail=f"Spec not found: {request.spec_name}")

    run_id = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    spec_content = await asyncio.to_thread(spec_path.read_text)
    await asyncio.to_thread((run_dir / "spec.md").write_text, spec_content)
    await asyncio.to_thread((run_dir / "status.txt").write_text, "queued")  # Start as queued

    try_code_path = get_try_code_path(request.spec_name, spec_path)

    # Determine queue position (count only, no need to fetch all rows)
    queued_count = session.exec(select(func.count()).select_from(DBTestRun).where(DBTestRun.status == "queued")).one()
    queue_position = queued_count + 1

    # Create DB Entry with queue info
    now = datetime.utcnow()
    run = DBTestRun(
        id=run_id,
        spec_name=request.spec_name,
        test_name=request.spec_name,
        status="queued",
        browser=request.browser or "chromium",
        queued_at=now,
        queue_position=queue_position,
        project_id=request.project_id,
    )
    session.add(run)
    session.commit()

    # Map legacy flags to new behavior
    # ralph or native_healer alone -> now just uses default native healer
    # hybrid mode is explicit
    hybrid_mode = request.hybrid or request.ralph or False
    max_iterations = request.max_iterations or 20

    # Create asyncio task for parallel execution
    task = asyncio.create_task(
        execute_run_task_wrapper(
            str(spec_path),
            str(run_dir),
            run_id,
            try_code_path,
            request.browser,
            hybrid_mode,
            max_iterations,
            batch_id=None,
            spec_name=request.spec_name,
            project_id=request.project_id,
        )
    )
    task.add_done_callback(_task_exception_handler)

    # Register task with ProcessManager for cancellation support
    if PROCESS_MANAGER:
        PROCESS_MANAGER.register_task(run_id, task)

    return {
        "id": run_id,
        "status": "queued",
        "queue_position": queue_position,
        "mode": "hybrid" if hybrid_mode else "native",  # Always native pipeline
        "hybrid_mode": hybrid_mode,
        "max_iterations": max_iterations if hybrid_mode else None,
    }


@app.post("/runs/{id}/stop")
def stop_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """Stop a running or queued test task.

    For running processes:
    - Uses ProcessManager to terminate the entire process group (including child processes)
    - Sends SIGTERM first, then SIGKILL if needed

    For queued tasks:
    - Cancels the asyncio task waiting in queue
    """
    global PROCESS_MANAGER

    # Verify project ownership if project_id is provided
    run = session.get(DBTestRun, id)
    if project_id and run:
        if run.project_id:
            if project_id == "default":
                if run.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Run not found")
            elif run.project_id != project_id:
                raise HTTPException(status_code=404, detail="Run not found")

    # Check if run is queued (waiting in semaphore)
    if run and run.status == "queued":
        # Try to cancel via ProcessManager (handles asyncio task cancellation)
        if PROCESS_MANAGER and PROCESS_MANAGER.stop(id):
            logger.info(f"Cancelled queued run {id}")

        # Update DB status
        run.status = "cancelled"
        run.queue_position = None
        run.completed_at = datetime.utcnow()
        session.add(run)
        session.commit()

        # Update status file
        run_dir = RUNS_DIR / id
        if run_dir.exists():
            (run_dir / "status.txt").write_text("cancelled")

        # Update batch stats if part of a batch
        if run.batch_id:
            update_batch_stats(run.batch_id)

        return {"status": "cancelled", "id": id, "message": "Run was cancelled from queue"}

    # Check if run is actively running
    process = get_process(id)
    if process:
        logger.info(f"Stopping run {id} (PID {process.pid})...")

        # Use ProcessManager for proper process group termination
        if PROCESS_MANAGER:
            stopped = PROCESS_MANAGER.stop(id, timeout=5)
            if stopped:
                logger.info(f"Successfully stopped process group for {id}")
            else:
                logger.warning(f"ProcessManager failed to stop {id}, falling back to terminate()")
                process.terminate()
        else:
            # Fallback to simple terminate
            process.terminate()

        # Update DB status immediately
        if run:
            run.status = "stopped"
            run.completed_at = datetime.utcnow()
            session.add(run)
            session.commit()

            # Update status file
            run_dir = RUNS_DIR / id
            if run_dir.exists():
                (run_dir / "status.txt").write_text("stopped")

            # Update batch stats if part of a batch
            if run.batch_id:
                update_batch_stats(run.batch_id)

        return {"status": "stopped", "id": id}

    # Check if run exists but is not active (maybe completed or failed)
    if run:
        if run.status in ["passed", "failed", "stopped", "cancelled", "error"]:
            return {"status": "already_completed", "id": id, "current_status": run.status}

    return {"status": "not_running", "message": "Run is not currently active or queued"}


@app.post("/runs/bulk", response_model=CreateBatchResponse)
async def create_bulk_run(request: BulkRunRequest, session: Session = Depends(get_session)):
    """Create multiple test runs in bulk as a regression batch.

    Always uses Native Pipeline. Healing mode controlled by hybrid flag.
    Tests run in parallel up to the configured parallelism limit.

    Returns a batch_id that can be used to track all runs as a group.

    Supports regression testing:
    - automated_only=True: Only run specs with generated .spec.ts files
    - tags: Filter specs by tags (OR logic - matches ANY selected tag)
    """
    from orchestrator.services.batch_executor import BatchConfig, create_regression_batch

    hybrid_mode = request.hybrid or request.ralph or False
    max_iterations = request.max_iterations or 20

    config = BatchConfig(
        project_id=request.project_id,
        browser=request.browser,
        hybrid_mode=hybrid_mode,
        max_iterations=max_iterations,
        tags=request.tags,
        automated_only=request.automated_only or False,
        spec_names=request.spec_names,
    )

    try:
        result = create_regression_batch(config, session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Start all tasks in parallel using asyncio.create_task
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

    return CreateBatchResponse(
        batch_id=result.batch_id,
        run_ids=result.run_ids,
        count=len(result.run_ids),
        mode="hybrid" if hybrid_mode else "native",
        max_iterations=max_iterations if hybrid_mode else None,
    )


# ========= Metadata =========


@app.get("/spec-metadata")
def get_all_metadata(
    project_id: str | None = None,
    limit: int = Query(default=1000, ge=1, le=5000, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Items to skip"),
    session: Session = Depends(get_session),
):
    # Build query with optional project filter
    query = select(DBSpecMetadata)
    if project_id:
        if project_id == "default":
            query = query.where((DBSpecMetadata.project_id == project_id) | (DBSpecMetadata.project_id == None))
        else:
            query = query.where(DBSpecMetadata.project_id == project_id)

    # Safety cap: apply limit/offset to prevent unbounded result sets
    metas = session.exec(query.offset(offset).limit(limit)).all()
    # Convert list to dict keyed by spec_name to match original API
    result = {}
    for m in metas:
        result[m.spec_name] = {
            "tags": m.tags,
            "description": m.description,
            "author": m.author,
            "lastModified": m.last_modified.isoformat() if m.last_modified else None,
        }
    return result


@app.get("/spec-metadata/{spec_name:path}")
def get_spec_metadata(
    spec_name: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    m = session.get(DBSpecMetadata, spec_name)
    if not m:
        return {"tags": [], "description": None, "author": None, "lastModified": None}

    # Filter by project_id if provided
    if project_id:
        if m.project_id:
            if project_id == "default":
                if m.project_id not in (None, "default"):
                    return {"tags": [], "description": None, "author": None, "lastModified": None}
            elif m.project_id != project_id:
                return {"tags": [], "description": None, "author": None, "lastModified": None}

    return {
        "tags": m.tags,
        "description": m.description,
        "author": m.author,
        "lastModified": m.last_modified.isoformat() if m.last_modified else None,
    }


@app.put("/spec-metadata/{spec_name:path}")
def update_spec_metadata(spec_name: str, request: UpdateMetadataRequest, session: Session = Depends(get_session)):
    m = session.get(DBSpecMetadata, spec_name)
    if not m:
        m = DBSpecMetadata(spec_name=spec_name)

    if request.tags is not None:
        m.tags = request.tags
    if request.description is not None:
        m.description = request.description
    if request.author is not None:
        m.author = request.author
    if request.project_id is not None:
        m.project_id = request.project_id

    m.last_modified = datetime.utcnow()

    session.add(m)
    session.commit()
    session.refresh(m)

    return {
        "status": "success",
        "metadata": {
            "tags": m.tags,
            "description": m.description,
            "author": m.author,
            "lastModified": m.last_modified.isoformat(),
            "project_id": m.project_id,
        },
    }


# ========= Agents =========


class AgentRunRequest(BaseModel):
    agent_type: str  # "exploratory", "writer", or "spec-synthesis"
    config: dict[str, Any]
    project_id: str | None = None  # Project isolation


class ExploratoryRunRequest(BaseModel):
    """Enhanced exploratory testing request."""

    url: str
    time_limit_minutes: int = 15
    instructions: str = ""
    auth: dict[str, Any] | None = None  # {"type": "credentials|session|none", ...}
    test_data: dict[str, Any] | None = None
    focus_areas: list[str] | None = None
    excluded_patterns: list[str] | None = None
    project_id: str | None = None  # Project to associate generated specs with


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


async def execute_agent_background(run_id: str, agent_type: str, config: dict):
    """Execute an agent in the background with unified browser pool management.

    Uses BrowserResourcePool to limit concurrent browser operations across
    ALL operation types (test runs, explorations, agents, PRD).
    """
    from sqlmodel import Session

    from .db import engine
    from .models_db import AgentRun

    # Use unified browser pool for slot management
    pool = BROWSER_POOL or await get_browser_pool()

    # Block if a load test is running
    from orchestrator.services.load_test_lock import check_system_available

    await check_system_available("agent run")

    try:
        async with pool.browser_slot(
            request_id=run_id, operation_type=BrowserOpType.AGENT, description=f"Agent: {agent_type}"
        ) as acquired:
            if not acquired:
                # Timeout waiting for slot
                logger.warning(f"Agent {run_id} failed to acquire browser slot (timeout)")
                with Session(engine) as session:
                    run = session.get(AgentRun, run_id)
                    if run:
                        run.status = "failed"
                        run.result = {"error": "Timeout waiting for browser slot"}
                        session.add(run)
                        session.commit()
                return

            # Update status to "running" now that we have a slot
            with Session(engine) as session:
                run = session.get(AgentRun, run_id)
                if run and run.status == "queued":
                    run.status = "running"
                    session.add(run)
                    session.commit()

            logger.info(f"Browser slot acquired for agent {run_id}")

            # Use relative imports since server runs from orchestrator/ directory
            from agents.exploratory_agent import ExploratoryAgent
            from agents.spec_synthesis_agent import SpecSynthesisAgent
            from agents.spec_writer_agent import SpecWriterAgent

            result = {}
            if agent_type == "exploratory":
                agent = ExploratoryAgent()

                # Inject project_id from URL if not present
                if "project_id" not in config:
                    config["project_id"] = derive_project_id_from_url(config.get("url"))

                # Pass run_id to agent for file storage
                config["run_id"] = run_id
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
                result = await agent.run(config)
            elif agent_type == "spec-synthesis":
                agent = SpecSynthesisAgent()
                result = await agent.run(config)

            # Update DB success
            with Session(engine) as session:
                run = session.get(AgentRun, run_id)
                if run:
                    run.status = "completed"
                    run.result = result
                    session.add(run)
                    session.commit()

    except asyncio.CancelledError:
        logger.info(f"Agent {run_id} cancelled")
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            if run:
                run.status = "cancelled"
                session.add(run)
                session.commit()
        raise

    except Exception as e:
        import traceback

        traceback.print_exc()
        logger.error(f"Agent {run_id} failed with exception: {e}")
        # Update DB failure
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            if run:
                run.status = "failed"
                run.result = {"error": str(e)}
                session.add(run)
                session.commit()


@app.post("/api/agents/runs")
async def run_agent(
    request: AgentRunRequest, background_tasks: BackgroundTasks, session: Session = Depends(get_session)
):
    """Run an autonomous agent in background.

    If agent slots are full, the request is queued and will be executed
    when a slot becomes available. The response includes queue position
    if the request is queued.
    """
    # Check resource availability
    resource_manager = await get_resource_manager()
    agent_status = resource_manager.get_agent_status()

    # Determine initial status based on slot availability
    initial_status = "running" if resource_manager.is_slot_available(ResourceType.AGENT) else "queued"
    queue_position = None if initial_status == "running" else agent_status.queued + 1

    # Create DB Record
    run_id = str(uuid.uuid4())
    run = AgentRun(
        id=run_id,
        agent_type=request.agent_type,
        config_json=json.dumps(request.config),
        status=initial_status,
        project_id=request.project_id,  # Project isolation
    )
    session.add(run)
    session.commit()

    # Start Background Task (it will wait for slot if needed)
    background_tasks.add_task(execute_agent_background, run_id, request.agent_type, request.config)

    response = {
        "status": initial_status,
        "run_id": run_id,
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


@app.get("/api/agents/runs")
def list_agent_runs(
    project_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=500, description="Max items to return"),
    offset: int = Query(default=0, ge=0, description="Items to skip"),
    session: Session = Depends(get_session),
):
    statement = select(AgentRun).order_by(AgentRun.created_at.desc())
    # Apply project filter if provided
    if project_id:
        if project_id == "default":
            # Default project includes legacy runs (NULL project_id) for backward compatibility
            statement = statement.where((AgentRun.project_id == project_id) | (AgentRun.project_id == None))
        else:
            statement = statement.where(AgentRun.project_id == project_id)

    # Safety cap: apply limit/offset to prevent unbounded result sets
    runs = session.exec(statement.offset(offset).limit(limit)).all()
    # Manually serialize to handle properties
    return [
        {
            "id": r.id,
            "agent_type": r.agent_type,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
            "config": r.config,
            "project_id": r.project_id,
            # Don't send full result in list view if it's huge
            "summary": r.result.get("summary") if r.result else None,
        }
        for r in runs
    ]


@app.get("/api/agents/runs/{id}")
def get_agent_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    r = session.get(AgentRun, id)
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")

    # Filter by project_id if provided
    if project_id:
        if r.project_id:
            if project_id == "default":
                if r.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Run not found")
            elif r.project_id != project_id:
                raise HTTPException(status_code=404, detail="Run not found")

    return {
        "id": r.id,
        "agent_type": r.agent_type,
        "status": r.status,
        "created_at": r.created_at.isoformat(),
        "config": r.config,
        "result": r.result,
        "project_id": r.project_id,
    }


# ========= Enhanced Exploratory Testing Endpoints =========


@app.post("/api/agents/exploratory")
async def run_exploratory_agent(
    request: ExploratoryRunRequest, background_tasks: BackgroundTasks, session: Session = Depends(get_session)
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
        config_json=json.dumps(config),
        status="running",
        project_id=request.project_id,  # Project isolation in DB field
    )
    session.add(run)
    session.commit()

    # Start background task
    background_tasks.add_task(execute_agent_background, run_id, "exploratory", config)

    return {
        "run_id": run_id,
        "status": "started",
        "auth": auth_result.get("type", "none"),
        "project_id": request.project_id,
    }


@app.post("/api/agents/exploratory/{run_id}/synthesize")
async def synthesize_specs(run_id: str, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    """
    Generate .md test specs from exploration results.

    Takes the exploration results and synthesizes them into
    production-ready .md specs that work with the existing pipeline.
    """
    # Get exploration run
    exploration_run = session.get(AgentRun, run_id)
    if not exploration_run:
        raise HTTPException(status_code=404, detail="Exploration run not found")

    if exploration_run.status != "completed":
        raise HTTPException(status_code=400, detail="Exploration must be completed before synthesis")

    exploration_result = exploration_run.result
    if not exploration_result:
        raise HTTPException(status_code=400, detail="No exploration results found")

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
    }

    synthesis_run = AgentRun(
        id=synthesis_run_id,
        agent_type="spec-synthesis",
        config_json=json.dumps(synthesis_config),
        status="running",
        project_id=exploration_project_id,  # Project isolation in DB field
    )
    session.add(synthesis_run)
    session.commit()

    # Start background task
    background_tasks.add_task(execute_agent_background, synthesis_run_id, "spec-synthesis", synthesis_config)

    return {"synthesis_run_id": synthesis_run_id, "exploration_run_id": run_id, "status": "started"}


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


@app.get("/api/agents/exploratory/{run_id}/specs")
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


@app.get("/api/agents/exploratory/{run_id}/flows/{flow_id}")
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


@app.put("/api/agents/exploratory/{run_id}/flows/{flow_id}")
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


@app.delete("/api/agents/exploratory/{run_id}/flows/{flow_id}")
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


@app.post("/api/agents/exploratory/{run_id}/analyze-prerequisites")
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


@app.post("/api/agents/exploratory/{run_id}/flows/{flow_id}/spec")
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

            for category in ["happy_path", "edge_cases"]:
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

Generate a COMPREHENSIVE .md test spec for the following discovered user flow.

{flow_desc}
{prereq_section}
{produces_section}

REQUIREMENTS:
1. Follow this EXACT format:
   ```markdown
   # Test: [Feature Name]

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

2. CRITICAL RULES:
   - **ALWAYS include Prerequisites section** - even if minimal
   - **Setup steps come FIRST** in the Steps section
   - Parse the happy_path description into specific, actionable steps
   - Don't use placeholders like "Complete step X" - use actual actions
   - Include specific URLs and element descriptions based on the flow
   - Use placeholders `{{{{VAR_NAME}}}}` for secrets/passwords
   - If authentication is required, include login steps at the beginning
   - If data requirements exist, mention them in Prerequisites

OUTPUT FORMAT (return ONLY JSON):
```json
{{
  "specs": {{
    "happy_path": {{
      "{flow_title.lower().replace(" ", "_").replace("/", "_")}.md": "# Test: {flow_title}\\n\\n## Description\\n...\\n\\n## Prerequisites\\n...\\n\\n## Steps\\n..."
    }}
  }},
  "summary": "Generated test spec for {flow_title}"
}}
```

Now generate the test spec."""


def _generate_fallback_spec(flow: dict[str, Any], base_url: str) -> tuple[str, str]:
    """Generate a basic spec as fallback when agent fails."""
    import re

    flow_title = flow.get("title", "Unnamed Flow")
    happy_path = flow.get("happy_path", "")
    pages = flow.get("pages", [])
    entry = flow.get("entry_point", "")
    exit_point = flow.get("exit_point", "")

    # Get prerequisites (if analyzed)
    prerequisites = flow.get("prerequisites", {})

    # Build prerequisites section
    prereq_lines = []
    if prerequisites:
        auth = prerequisites.get("authentication", {})
        if auth.get("required"):
            prereq_lines.append(f"- Authentication: Required ({auth.get('user_type', 'standard user')})")
        else:
            prereq_lines.append("- Authentication: Not required")

        data_reqs = prerequisites.get("data_requirements", [])
        if data_reqs:
            for req in data_reqs:
                prereq_lines.append(f"- Data: {req.get('description', req.get('entity', 'unknown'))}")

        prior_flows = prerequisites.get("prior_flows", [])
        if prior_flows:
            prereq_lines.append(f"- Prior flows: {', '.join(prior_flows)}")

    if not prereq_lines:
        prereq_lines.append("- None identified")

    prereq_text = chr(10).join(prereq_lines)

    # Parse happy path into steps
    steps = []
    step_num = 1

    # Add setup steps from prerequisites first
    setup_steps = prerequisites.get("setup_steps", [])
    for setup_step in setup_steps:
        steps.append(f"{step_num}. {setup_step}")
        step_num += 1

    # Entry point (only if no setup steps included navigation)
    if not any("navigate" in s.lower() for s in setup_steps):
        if entry:
            steps.append(f"{step_num}. Navigate to {{{{BASE_URL}}}}{entry}")
            step_num += 1
        elif pages:
            steps.append(f"{step_num}. Navigate to {pages[0]}")
            step_num += 1

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
                    steps.append(f"{step_num}. {action}")
                    step_num += 1

    # Exit point
    if exit_point:
        steps.append(f"{step_num}. Verify arrival at {{{{BASE_URL}}}}{exit_point}")
    else:
        steps.append(f"{step_num}. Verify successful completion")

    # Build spec content
    spec_content = f"""# Test: {flow_title}

## Description
{happy_path}

## Prerequisites
{prereq_text}

## Steps
{chr(10).join(steps)}

## Expected Outcome
- User successfully completes the {flow_title}
- All pages load correctly
- No errors are displayed

## Test Data
- Base URL: {{{{BASE_URL}}}}
"""

    # Add edge cases if available
    edge_cases = flow.get("edge_cases", [])
    if edge_cases:
        spec_content += "\n## Edge Cases\n"
        for case in edge_cases[:5]:
            spec_content += f"- {case}\n"

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

        _flow_spec_jobs[job_id]["message"] = "Preparing flow context..."

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

        # Run Native Planner
        _flow_spec_jobs[job_id]["message"] = "Running Native Planner (browser exploration)..."
        logger.info(f"Starting Native Planner for flow: {flow_title}")

        domain_name = _extract_domain_name(entry_point)
        flow_slug = _slugify(flow_title)
        folder_name = f"explorer-{domain_name}-{flow_slug}"

        effective_project_id = run_project_id if run_project_id else folder_name

        planner = NativePlanner(project_id=effective_project_id)
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
        try:
            from sqlmodel import Session as SyncSession

            from .db import engine

            with SyncSession(engine) as db_session:
                spec_name = str(spec_path.relative_to(project_root / "specs"))
                existing_meta = db_session.get(DBSpecMetadata, spec_name)
                if not existing_meta:
                    meta = DBSpecMetadata(spec_name=spec_name, project_id=effective_project_id, tags_json="[]")
                    db_session.add(meta)
                else:
                    existing_meta.project_id = effective_project_id
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


# NOTE: Status endpoint must be defined BEFORE /{run_id} routes to avoid path conflicts
@app.get("/api/agents/exploratory/flow-spec-jobs/{job_id}")
async def get_flow_spec_job_status(job_id: str):
    """Get status of a flow spec generation job."""
    job = _flow_spec_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "message": job.get("message"),
        "result": job.get("result"),
    }


@app.post("/api/agents/exploratory/{run_id}/flows/{flow_id}/generate")
async def generate_flow_test(
    run_id: str,
    flow_id: str,
    force_regenerate: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
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

    # Get project root
    project_root = Path(__file__).parent.parent.parent
    flows_file = project_root / "runs" / run_id / "flows.json"

    if not await asyncio.to_thread(flows_file.exists):
        raise HTTPException(status_code=404, detail=f"Flows file not found for run {run_id}")

    try:
        raw = await asyncio.to_thread(flows_file.read_text)
        data = json.loads(raw)

        flows = data.get("flows", [])

        # Get project_id from parent exploration run for proper isolation
        exploration_run = session.get(AgentRun, run_id)
        run_config = json.loads(exploration_run.config_json) if exploration_run and exploration_run.config_json else {}
        run_project_id = run_config.get("project_id")

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

        _flow_spec_jobs[job_id] = {
            "status": "running",
            "message": "Starting spec generation...",
            "started_at": _time.time(),
            "run_id": run_id,
            "flow_id": flow_id,
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
            run_config=run_config,
        )

        return {
            "status": "running",
            "job_id": job_id,
            "message": "Spec generation started. Poll for status.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating test: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/agents/sessions")
async def list_sessions():
    """List saved authentication sessions."""
    from agents.auth_handler import AuthHandler

    auth_handler = AuthHandler()
    sessions = auth_handler.list_sessions()

    return {"sessions": sessions}


@app.post("/api/agents/sessions/{session_id}")
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


@app.delete("/api/agents/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a saved authentication session."""
    from agents.auth_handler import AuthHandler

    auth_handler = AuthHandler()
    if auth_handler.delete_session(session_id):
        return {"status": "deleted", "session_id": session_id}
    else:
        raise HTTPException(status_code=404, detail="Session not found")


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
