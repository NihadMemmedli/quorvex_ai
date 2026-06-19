"""FastAPI application wiring helpers."""

from __future__ import annotations

import logging
import time as time_module
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from logging_config import request_id_var

from .middleware.rate_limit import limiter, rate_limit_exceeded_handler

logger = logging.getLogger(__name__)


def _runtime_logger(runtime: Any | None) -> logging.Logger:
    return getattr(runtime, "logger", logger)


def _request_runtime(request: Request) -> Any | None:
    return getattr(request.app.state, "app_wiring_runtime", None)


async def global_exception_handler(request: Request, exc: Exception):
    runtime = _request_runtime(request)
    app_logger = _runtime_logger(runtime)
    req_id = request_id_var.get("")
    app_logger.error(f"Unhandled exception [req={req_id}]: {exc}", exc_info=True)

    # Include CORS headers so browsers can read the error response
    origin = request.headers.get("origin", "")
    headers = {}
    if runtime is not None and origin in runtime.ALLOWED_ORIGINS:
        headers["access-control-allow-origin"] = origin
        headers["access-control-allow-credentials"] = "true"
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": req_id},
        headers=headers,
    )


class RequestLoggingMiddlewareHTTP(BaseHTTPMiddleware):
    """HTTP middleware wrapper for request logging."""

    async def dispatch(self, request, call_next):
        app_logger = _runtime_logger(_request_runtime(request))
        request_id = str(uuid.uuid4())[:8]
        start_time = time_module.time()

        # Log request (skip noisy endpoints)
        path = request.url.path
        if not path.startswith("/health") and not path.startswith("/artifacts"):
            app_logger.info(f"[{request_id}] --> {request.method} {path}")

        try:
            response = await call_next(request)

            # Log response (skip noisy endpoints)
            if not path.startswith("/health") and not path.startswith("/artifacts"):
                duration_ms = (time_module.time() - start_time) * 1000
                log_level = (
                    "info" if response.status_code < 400 else "warning" if response.status_code < 500 else "error"
                )
                getattr(app_logger, log_level)(f"[{request_id}] <-- {response.status_code} in {duration_ms:.1f}ms")

            # Add request ID header
            response.headers["X-Request-ID"] = request_id
            return response

        except Exception as e:
            duration_ms = (time_module.time() - start_time) * 1000
            app_logger.error(f"[{request_id}] <-- ERROR in {duration_ms:.1f}ms: {e}")
            raise


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


def _include_core_routers(runtime: Any, app: FastAPI) -> None:
    app.include_router(runtime.auth.router)  # Auth endpoints first
    app.include_router(runtime.users.router)  # User management (superuser only)
    app.include_router(runtime.dashboard.router)
    app.include_router(runtime.settings.router)
    app.include_router(runtime.specs.router)
    app.include_router(runtime.memory.router)
    app.include_router(runtime.prd.router)
    app.include_router(runtime.regression.router)
    app.include_router(runtime.projects.router)
    app.include_router(runtime.test_data.router)
    app.include_router(runtime.browser_auth_sessions.router)
    app.include_router(runtime.recordings.router)
    app.include_router(runtime.exploration.router)
    app.include_router(runtime.requirements.router)
    app.include_router(runtime.rtm.router)
    app.include_router(runtime.testrail.router)  # TestRail integration
    app.include_router(runtime.testrail_files.router)  # Legacy TestRail file import/export
    app.include_router(runtime.jira.router)  # Jira integration
    app.include_router(runtime.scheduling.router)  # Cron scheduling
    app.include_router(runtime.ci_control.router)  # Provider-neutral CI/CD control center
    app.include_router(runtime.gitlab_ci.router)  # GitLab CI/CD integration
    app.include_router(runtime.github_ci.router)  # GitHub Actions integration
    app.include_router(runtime.api_testing.router)  # API testing endpoints
    app.include_router(runtime.load_testing.router)  # Load testing endpoints
    app.include_router(runtime.security_testing.router)  # Security testing endpoints
    app.include_router(runtime.database_testing.router)  # Database testing endpoints
    app.include_router(runtime.llm_testing.router)  # LLM/AI testing endpoints
    app.include_router(runtime.analytics.router)  # Analytics dashboard
    app.include_router(runtime.health.router)  # Storage health endpoints
    app.include_router(runtime.chat.router)  # AI assistant chat endpoints
    app.include_router(runtime.autopilot.router)  # Auto Pilot pipeline endpoints
    app.include_router(runtime.autonomous.router)  # Persistent autonomous testing missions
    app.include_router(runtime.runs.router)  # Test run lifecycle endpoints
    app.include_router(runtime.runtime_ops.router)  # Operational runtime, queue, health, and debug endpoints
    app.include_router(runtime.agent_queue_ops.router)  # Legacy agent queue operation endpoints
    app.include_router(runtime.workflows.router)  # Custom workflow endpoints
    app.include_router(runtime.backup_control.router)  # Database backup control endpoints
    app.include_router(runtime.agent_sessions.router)  # Legacy agent authentication session endpoints


def _include_agent_routers(runtime: Any, app: FastAPI) -> None:
    app.include_router(runtime.agent_definitions.router)  # Custom agent tool catalog and definition endpoints
    app.include_router(runtime.agent_run_launch.router)  # Agent run launch endpoint
    app.include_router(runtime.agent_run_observability.router)  # Read-only agent run visibility endpoints
    app.include_router(runtime.agent_coding_patch.router)  # Coding agent patch review endpoints
    app.include_router(runtime.agent_run_control.router)  # Agent run pause, resume, cancel, and retry endpoints
    app.include_router(runtime.agent_reports.router)  # Custom agent report retrieval, editing, search, and import endpoints
    app.include_router(runtime.agent_exploratory.router)  # Exploratory agent and spec generation endpoints


def configure_app(runtime: Any, app: FastAPI) -> None:
    app.state.app_wiring_runtime = runtime

    # Add rate limiter state to app
    app.state.limiter = limiter

    # Add rate limit exception handler
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_exception_handler(Exception, global_exception_handler)

    _include_core_routers(runtime, app)
    app.mount("/artifacts", StaticFiles(directory=runtime.RUNS_DIR), name="artifacts")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.add_middleware(RequestLoggingMiddlewareHTTP)
    app.add_middleware(RequestSizeLimitMiddleware)

    _include_agent_routers(runtime, app)
