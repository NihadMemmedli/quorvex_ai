"""Active test-run process registry support for helpers exposed from main."""

from __future__ import annotations

from typing import Any


def register_process(runtime: Any, run_id: str, proc: Any) -> None:
    """Thread-safe registration of an active process."""
    with runtime._processes_lock:
        runtime.ACTIVE_PROCESSES[run_id] = proc


def unregister_process(runtime: Any, run_id: str) -> Any | None:
    """Thread-safe removal of an active process. Returns the process if found."""
    with runtime._processes_lock:
        return runtime.ACTIVE_PROCESSES.pop(run_id, None)


def get_process(runtime: Any, run_id: str) -> Any | None:
    """Thread-safe retrieval of an active process."""
    with runtime._processes_lock:
        return runtime.ACTIVE_PROCESSES.get(run_id)


def is_process_active(runtime: Any, run_id: str) -> bool:
    """Thread-safe check if a process is active."""
    with runtime._processes_lock:
        return run_id in runtime.ACTIVE_PROCESSES


def get_active_process_count(runtime: Any) -> int:
    """Thread-safe count of active processes."""
    with runtime._processes_lock:
        return len(runtime.ACTIVE_PROCESSES)


def list_active_process_ids(runtime: Any) -> list:
    """Thread-safe list of active process IDs."""
    with runtime._processes_lock:
        return list(runtime.ACTIVE_PROCESSES.keys())


def clear_all_processes(runtime: Any) -> dict:
    """Thread-safe clear of all processes. Returns the old dict."""
    with runtime._processes_lock:
        old = dict(runtime.ACTIVE_PROCESSES)
        runtime.ACTIVE_PROCESSES.clear()
        return old
