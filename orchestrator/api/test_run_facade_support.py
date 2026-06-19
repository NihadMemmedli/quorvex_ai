"""Facade setup for legacy test-run helpers exposed from main."""

from __future__ import annotations

import asyncio
import functools
import subprocess
import threading
from collections.abc import Callable
from typing import Any

from services.browser_pool import AbstractBrowserPool
from services.resource_manager import ResourceManager

from . import (
    startup_diagnostics_support,
    test_run_batch_watchdog_support,
    test_run_cleanup_support,
    test_run_maintenance_loop_support,
    test_run_process_registry_support,
    test_run_queue_manager_support,
    test_run_read_model_support,
    test_run_runtime_support,
    test_run_schedule_watchdog_support,
)
from .process_manager import ProcessManager

RuntimeFactory = Callable[[], Any]


def _handle_task_exception(runtime: Any, task: asyncio.Task) -> None:
    """Log exceptions from completed tasks to prevent silent failures."""
    try:
        exc = task.exception()
        if exc:
            runtime.logger.error(f"Task {task.get_name()} failed with unhandled exception: {exc}")
    except asyncio.CancelledError:
        # Task was cancelled, not an error
        pass
    except asyncio.InvalidStateError:
        # Task not done yet, shouldn't happen in done callback
        pass


def _build_task_exception_handler(runtime_factory: RuntimeFactory) -> Callable[[asyncio.Task], None]:
    def task_exception_handler(task: asyncio.Task) -> None:
        _handle_task_exception(runtime_factory(), task)

    task_exception_handler.__name__ = "_task_exception_handler"
    return task_exception_handler


def configure_test_run_facade(runtime_factory: RuntimeFactory, namespace: dict[str, Any]) -> None:
    """Populate main-module compatibility exports for test-run runtime helpers."""
    runtime = runtime_factory()
    queue_manager_class = test_run_queue_manager_support.QueueManager

    namespace.update(
        {
            # Limit concurrent test executions
            "EXECUTION_SEMAPHORE": None,
            # Track active processes: run_id -> subprocess.Popen object
            # NOTE: This is now also backed by ProcessManager for persistence
            # Protected by _processes_lock for thread safety (accessed from both event loop and thread pool)
            "ACTIVE_PROCESSES": {},
            "_processes_lock": threading.Lock(),
            "register_process": functools.partial(
                test_run_process_registry_support.register_process,
                runtime,
            ),
            "unregister_process": functools.partial(
                test_run_process_registry_support.unregister_process,
                runtime,
            ),
            "get_process": functools.partial(
                test_run_process_registry_support.get_process,
                runtime,
            ),
            "is_process_active": functools.partial(
                test_run_process_registry_support.is_process_active,
                runtime,
            ),
            "get_active_process_count": functools.partial(
                test_run_process_registry_support.get_active_process_count,
                runtime,
            ),
            "list_active_process_ids": functools.partial(
                test_run_process_registry_support.list_active_process_ids,
                runtime,
            ),
            "clear_all_processes": functools.partial(
                test_run_process_registry_support.clear_all_processes,
                runtime,
            ),
            # Process manager for persistent tracking and graceful termination
            "PROCESS_MANAGER": None,
            "QueueManager": queue_manager_class,
            # Global queue manager instance
            "QUEUE_MANAGER": None,
            # Global resource manager instance for agent/exploration/PRD concurrency
            # DEPRECATED: Use BROWSER_POOL instead for unified browser management
            "RESOURCE_MANAGER": None,
            # Unified browser resource pool - limits ALL browser operations to MAX_BROWSER_INSTANCES (default: 5)
            "BROWSER_POOL": None,
            "cleanup_orphaned_runs": functools.partial(
                test_run_cleanup_support.cleanup_orphaned_runs,
                runtime,
            ),
            "_cleanup_test_run_runtime": functools.partial(
                test_run_cleanup_support.cleanup_test_run_runtime,
                runtime,
            ),
            "cleanup_terminal_test_run_processes": functools.partial(
                test_run_cleanup_support.cleanup_terminal_test_run_processes,
                runtime,
            ),
            "sync_data_from_files": functools.partial(
                test_run_read_model_support.sync_data_from_files,
                runtime,
            ),
            "update_batch_stats": functools.partial(
                test_run_batch_watchdog_support.update_batch_stats,
                runtime,
            ),
            "_finalize_quality_gate_for_batch_safe": functools.partial(
                test_run_batch_watchdog_support._finalize_quality_gate_for_batch_safe,
                runtime,
            ),
            "_quality_gate_finalizer_loop": functools.partial(
                test_run_batch_watchdog_support._quality_gate_finalizer_loop,
                runtime,
            ),
            "_batch_watchdog": functools.partial(
                test_run_batch_watchdog_support._batch_watchdog,
                runtime,
            ),
            "_queue_watchdog": functools.partial(
                test_run_batch_watchdog_support._queue_watchdog,
                runtime,
            ),
            "_exploration_cleanup_loop": functools.partial(
                test_run_maintenance_loop_support._exploration_cleanup_loop,
                runtime,
            ),
            "_browser_pool_cleanup_loop": functools.partial(
                test_run_maintenance_loop_support._browser_pool_cleanup_loop,
                runtime,
            ),
            "_infrastructure_maintenance_loop": functools.partial(
                test_run_maintenance_loop_support._infrastructure_maintenance_loop,
                runtime,
            ),
            "_schedule_execution_watchdog": functools.partial(
                test_run_schedule_watchdog_support._schedule_execution_watchdog,
                runtime,
            ),
            "_run_db_maintenance": functools.partial(
                test_run_maintenance_loop_support._run_db_maintenance,
                runtime,
            ),
            "_log_startup_diagnostics": functools.partial(
                startup_diagnostics_support._log_startup_diagnostics,
                runtime,
            ),
            "_STARTUP_IMPORT_FAILURE_MESSAGE": test_run_runtime_support._STARTUP_IMPORT_FAILURE_MESSAGE,
            "_record_startup_import_failure": functools.partial(
                test_run_runtime_support.record_startup_import_failure,
                runtime,
            ),
            "_run_test_cli_subprocess_with_retry": functools.partial(
                test_run_runtime_support.run_test_cli_subprocess_with_retry,
                runtime,
            ),
            "execute_run_task": functools.partial(
                test_run_runtime_support.execute_run_task,
                runtime,
            ),
            "_task_exception_handler": _build_task_exception_handler(runtime_factory),
            "execute_run_task_wrapper": functools.partial(
                test_run_runtime_support.execute_run_task_wrapper,
                runtime,
            ),
            "execute_mobile_run_task": functools.partial(
                test_run_runtime_support.execute_mobile_run_task,
                runtime,
            ),
            "execute_mobile_run_task_wrapper": functools.partial(
                test_run_runtime_support.execute_mobile_run_task_wrapper,
                runtime,
            ),
            "_start_test_run_temporal_or_fail": functools.partial(
                test_run_runtime_support.start_test_run_temporal_or_fail,
                runtime,
            ),
            "_signal_test_run_temporal": functools.partial(
                test_run_runtime_support.signal_test_run_temporal,
                runtime,
            ),
            "_has_browser_auth_selection": functools.partial(
                test_run_runtime_support.has_browser_auth_selection,
                runtime,
            ),
            "_validate_browser_auth_selection_for_project": functools.partial(
                test_run_runtime_support.validate_browser_auth_selection_for_project,
                runtime,
            ),
            "_resolve_browser_auth_storage_state_for_run": functools.partial(
                test_run_runtime_support.resolve_browser_auth_storage_state_for_run,
                runtime,
            ),
            "_normalize_request_test_data_refs": functools.partial(
                test_run_runtime_support.normalize_request_test_data_refs,
                runtime,
            ),
        }
    )

    test_run_queue_manager_support.configure_runtime(runtime_factory)

    annotations = namespace.setdefault("__annotations__", {})
    annotations.update(
        {
            "EXECUTION_SEMAPHORE": asyncio.Semaphore | None,
            "ACTIVE_PROCESSES": dict[str, subprocess.Popen],
            "PROCESS_MANAGER": ProcessManager | None,
            "QUEUE_MANAGER": queue_manager_class | None,
            "RESOURCE_MANAGER": ResourceManager | None,
            "BROWSER_POOL": AbstractBrowserPool | None,
        }
    )
