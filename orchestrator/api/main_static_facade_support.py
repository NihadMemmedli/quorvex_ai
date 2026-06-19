"""Static compatibility exports for the legacy main module facade."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from . import app_wiring_support, run_files, spec_files, testrail_files

DEFAULT_ALLOWED_ORIGINS = "http://localhost:3000,http://host.docker.internal:3000"


def configure_main_static_facade(namespace: dict[str, Any]) -> None:
    """Populate main-module compatibility exports that do not need runtime factories."""
    namespace.update(
        {
            "BASE_DIR": spec_files.BASE_DIR,
            "SPECS_DIR": spec_files.SPECS_DIR,
            "RUNS_DIR": spec_files.RUNS_DIR,
            "METADATA_FILE": spec_files.METADATA_FILE,
            "MAX_UPLOAD_SIZE_BYTES": testrail_files.MAX_UPLOAD_SIZE_BYTES,
            "ALLOWED_UPLOAD_TYPES": testrail_files.ALLOWED_UPLOAD_TYPES,
            "sync_spec_metadata_from_file": spec_files.sync_spec_metadata_from_file,
            "get_try_code_path_fast": spec_files.get_try_code_path_fast,
            "get_cached_spec_info": spec_files.get_cached_spec_info,
            "get_try_code_path": spec_files.get_try_code_path,
            "invalidate_code_path_cache": spec_files.invalidate_code_path_cache,
            "RUN_BROWSER_METADATA_FILE": run_files.RUN_BROWSER_METADATA_FILE,
            "RUN_SEED_SPEC_RELATIVE_PATH": run_files.RUN_SEED_SPEC_RELATIVE_PATH,
            "RUN_TARGET_URL_PATTERNS": run_files.RUN_TARGET_URL_PATTERNS,
            "REAL_BROWSER_EXECUTABLE_NAMES": run_files.REAL_BROWSER_EXECUTABLE_NAMES,
            "ACTIVE_RUN_STATUSES": run_files.ACTIVE_RUN_STATUSES,
            "_build_run_browser_metadata": run_files.build_run_browser_metadata,
            "_merge_run_browser_metadata": run_files.merge_run_browser_metadata,
            "_write_run_browser_metadata": run_files.write_run_browser_metadata,
            "_load_run_browser_metadata": run_files.load_run_browser_metadata,
            "_extract_run_target_url_from_content": run_files.extract_run_target_url_from_content,
            "_extract_run_target_url": run_files.extract_run_target_url,
            "_write_run_seed_spec": run_files.write_run_seed_spec,
            "_is_real_browser_process_line": run_files.is_real_browser_process_line,
            "_browser_window_lines": run_files.browser_window_lines,
            "_live_browser_display_diagnostics": run_files.live_browser_display_diagnostics_for_run,
            "_augment_active_browser_metadata": run_files.augment_active_browser_metadata,
            "_compose_test_run_log_payload": run_files.compose_test_run_log_payload,
            "_BACKGROUND_TASKS": [],
            "DEFAULT_ALLOWED_ORIGINS": DEFAULT_ALLOWED_ORIGINS,
            "ALLOWED_ORIGINS": os.getenv("ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS).split(","),
            "RequestLoggingMiddlewareHTTP": app_wiring_support.RequestLoggingMiddlewareHTTP,
            "RequestSizeLimitMiddleware": app_wiring_support.RequestSizeLimitMiddleware,
            "BaseHTTPMiddleware": app_wiring_support.BaseHTTPMiddleware,
            "CORSMiddleware": app_wiring_support.CORSMiddleware,
            "JSONResponse": app_wiring_support.JSONResponse,
            "RateLimitExceeded": app_wiring_support.RateLimitExceeded,
            "Request": app_wiring_support.Request,
            "StaticFiles": app_wiring_support.StaticFiles,
            "global_exception_handler": app_wiring_support.global_exception_handler,
            "limiter": app_wiring_support.limiter,
            "rate_limit_exceeded_handler": app_wiring_support.rate_limit_exceeded_handler,
        }
    )

    annotations = namespace.setdefault("__annotations__", {})
    annotations["_BACKGROUND_TASKS"] = list[asyncio.Task]
