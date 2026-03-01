"""
Process Manager for reliable process tracking and termination.

Handles:
- Process group management for proper child termination
- Persistent PID file tracking for server restart recovery
- Clean process termination with SIGTERM/SIGKILL fallback
- Orphan process cleanup
"""

import asyncio
import json
import logging
import os
import signal
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProcessInfo:
    """Information about a tracked process."""

    run_id: str
    pid: int
    pgid: int  # Process group ID
    started_at: str
    spec_name: str = ""
    batch_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProcessInfo":
        return cls(**data)


@dataclass
class QueuedRunInfo:
    """Information about a queued but not-yet-running test run."""

    run_id: str
    spec_path: str
    spec_name: str
    queued_at: str
    batch_id: str | None = None
    browser: str = "chromium"
    hybrid: bool = False
    max_iterations: int = 20
    project_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QueuedRunInfo":
        return cls(**data)


class ProcessManager:
    """
    Manages test execution processes with persistent tracking.

    Features:
    - Creates process groups for proper child termination
    - Persists process info to disk for restart recovery
    - Cleans up orphaned processes on startup
    - Handles graceful shutdown with SIGTERM/SIGKILL fallback
    """

    def __init__(self, data_dir: Path = None):
        """
        Initialize ProcessManager.

        Args:
            data_dir: Directory for PID files (default: data/processes)
        """
        if data_dir is None:
            data_dir = Path(__file__).parent.parent.parent / "data" / "processes"

        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # In-memory process tracking (for active processes)
        self._processes: dict[str, ProcessInfo] = {}
        self._asyncio_tasks: dict[str, asyncio.Task] = {}  # Track queued tasks
        self._queued_runs: dict[str, QueuedRunInfo] = {}  # Track queued runs for persistence

        # Queue state file for restart recovery
        self._queue_state_file = self.data_dir / "queue_state.json"

        logger.info(f"ProcessManager initialized with data_dir: {self.data_dir}")

    def register(
        self, run_id: str, pid: int, pgid: int, spec_name: str = "", batch_id: str | None = None
    ) -> ProcessInfo:
        """
        Register a running process for tracking.

        Args:
            run_id: Unique run identifier
            pid: Process ID
            pgid: Process group ID
            spec_name: Name of the spec being run
            batch_id: Optional batch ID for regression runs

        Returns:
            ProcessInfo object
        """
        info = ProcessInfo(
            run_id=run_id,
            pid=pid,
            pgid=pgid,
            started_at=datetime.utcnow().isoformat(),
            spec_name=spec_name,
            batch_id=batch_id,
        )

        # Store in memory
        self._processes[run_id] = info

        # Persist to disk
        self._write_pid_file(run_id, info)

        logger.info(f"Registered process: run_id={run_id}, pid={pid}, pgid={pgid}")
        return info

    def register_task(self, run_id: str, task: asyncio.Task) -> None:
        """
        Register a queued asyncio task for cancellation support.

        Args:
            run_id: Unique run identifier
            task: The asyncio Task to track
        """
        self._asyncio_tasks[run_id] = task
        logger.debug(f"Registered asyncio task for run_id={run_id}")

    def unregister_task(self, run_id: str) -> None:
        """
        Remove an asyncio task from tracking.

        Args:
            run_id: Unique run identifier
        """
        if run_id in self._asyncio_tasks:
            del self._asyncio_tasks[run_id]
            logger.debug(f"Unregistered asyncio task for run_id={run_id}")

    def unregister(self, run_id: str) -> None:
        """
        Remove a process from tracking.

        Args:
            run_id: Unique run identifier
        """
        # Remove from memory
        if run_id in self._processes:
            del self._processes[run_id]

        # Remove from disk
        self._remove_pid_file(run_id)

        # Also remove any associated task
        self.unregister_task(run_id)

        logger.info(f"Unregistered process: run_id={run_id}")

    def stop(self, run_id: str, timeout: int = 5) -> bool:
        """
        Stop a running process and all its children.

        First tries SIGTERM, then SIGKILL if process doesn't exit.

        Args:
            run_id: Unique run identifier
            timeout: Seconds to wait after SIGTERM before SIGKILL

        Returns:
            True if process was stopped, False if not found
        """
        # Log the caller so we can trace what triggered the stop
        import traceback

        caller_stack = "".join(traceback.format_stack(limit=5)[:-1])
        logger.info(f"ProcessManager.stop() called for run_id={run_id}\n{caller_stack}")

        # Check if it's a queued task (not yet running)
        if run_id in self._asyncio_tasks:
            task = self._asyncio_tasks[run_id]
            if not task.done():
                task.cancel()
                logger.info(f"Cancelled queued task: run_id={run_id}")
            self.unregister_task(run_id)
            return True

        # Get process info
        info = self._processes.get(run_id)
        if not info:
            # Try to load from disk (server might have restarted)
            info = self._read_pid_file(run_id)

        if not info:
            logger.warning(f"Process not found: run_id={run_id}")
            return False

        return self._terminate_process_group(info.pgid, info.pid, timeout)

    def _terminate_process_group(self, pgid: int, pid: int, timeout: int = 5) -> bool:
        """
        Terminate an entire process group.

        Args:
            pgid: Process group ID
            pid: Main process ID (fallback)
            timeout: Seconds to wait before SIGKILL

        Returns:
            True if terminated successfully
        """
        try:
            # Send SIGTERM to process group
            logger.info(f"Sending SIGTERM to process group {pgid}")
            os.killpg(pgid, signal.SIGTERM)

            # Wait for graceful shutdown
            for _ in range(timeout * 10):  # Check every 100ms
                time.sleep(0.1)
                if not self._process_exists(pid):
                    logger.info(f"Process group {pgid} terminated gracefully")
                    return True

            # Force kill if still running
            logger.warning(f"Process group {pgid} didn't terminate, sending SIGKILL")
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # Already dead

            # Wait a bit more
            time.sleep(0.5)

            if not self._process_exists(pid):
                logger.info(f"Process group {pgid} force killed")
                return True

            logger.error(f"Failed to kill process group {pgid}")
            return False

        except ProcessLookupError:
            logger.info(f"Process group {pgid} already terminated")
            return True
        except PermissionError:
            logger.error(f"Permission denied killing process group {pgid}")
            return False
        except Exception as e:
            logger.error(f"Error terminating process group {pgid}: {e}")
            return False

    def _process_exists(self, pid: int) -> bool:
        """Check if a process is still running."""
        try:
            os.kill(pid, 0)  # Signal 0 checks if process exists
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def is_running(self, run_id: str) -> bool:
        """
        Check if a run has an active process.

        Args:
            run_id: Unique run identifier

        Returns:
            True if process is running
        """
        # Check queued tasks first
        if run_id in self._asyncio_tasks:
            task = self._asyncio_tasks[run_id]
            return not task.done()

        # Check running processes
        info = self._processes.get(run_id)
        if not info:
            info = self._read_pid_file(run_id)

        if not info:
            return False

        return self._process_exists(info.pid)

    def get_process_info(self, run_id: str) -> ProcessInfo | None:
        """
        Get process info for a run.

        Args:
            run_id: Unique run identifier

        Returns:
            ProcessInfo or None
        """
        info = self._processes.get(run_id)
        if not info:
            info = self._read_pid_file(run_id)
        return info

    def get_all_active(self) -> dict[str, ProcessInfo]:
        """
        Get all actively running processes.

        Returns:
            Dict mapping run_id to ProcessInfo for running processes
        """
        active = {}

        # Check all tracked processes
        for run_id, info in list(self._processes.items()):
            if self._process_exists(info.pid):
                active[run_id] = info

        return active

    def cleanup_orphans(self) -> int:
        """Clean up orphaned processes from previous server instances.

        Only kills processes that have PID files on disk but are NOT tracked
        in memory (i.e., not registered by the current server instance).
        Safe to call at startup when self._processes is empty.

        Returns:
            Number of orphans cleaned up
        """
        cleaned = 0

        logger.info("Cleaning up orphaned processes...")

        for pid_file in self.data_dir.glob("*.json"):
            if pid_file.name == "queue_state.json":
                continue
            try:
                info = self._read_pid_file_from_path(pid_file)
                if not info:
                    pid_file.unlink()
                    continue

                # Skip processes registered by THIS server instance
                if info.run_id in self._processes:
                    continue

                if self._process_exists(info.pid):
                    logger.warning(f"Found orphaned process: run_id={info.run_id}, pid={info.pid}")
                    if self._terminate_process_group(info.pgid, info.pid, timeout=3):
                        cleaned += 1

                # Remove stale PID file (only for non-active processes)
                pid_file.unlink()

            except Exception as e:
                logger.error(f"Error processing PID file {pid_file}: {e}")

        logger.info(f"Cleaned up {cleaned} orphaned processes")
        return cleaned

    def cleanup_stale_pid_files(self) -> int:
        """Remove PID files for processes that are no longer running.

        Unlike cleanup_orphans(), this NEVER kills processes — it only
        removes stale PID files left behind by processes that already exited.
        Safe to call periodically during normal operation.

        Returns:
            Number of stale PID files removed
        """
        cleaned = 0
        for pid_file in self.data_dir.glob("*.json"):
            if pid_file.name == "queue_state.json":
                continue
            try:
                info = self._read_pid_file_from_path(pid_file)
                if not info:
                    pid_file.unlink()
                    cleaned += 1
                    continue

                # Skip processes still in memory (actively tracked)
                if info.run_id in self._processes:
                    continue

                # Only remove file if process is dead
                if not self._process_exists(info.pid):
                    pid_file.unlink()
                    cleaned += 1
                    logger.debug(f"Removed stale PID file for {info.run_id}")
            except Exception as e:
                logger.error(f"Error cleaning PID file {pid_file}: {e}")
        return cleaned

    def shutdown_all(self, timeout: int = 10) -> int:
        """
        Gracefully shut down all tracked processes.

        Args:
            timeout: Seconds to wait for graceful shutdown

        Returns:
            Number of processes stopped
        """
        stopped = 0

        logger.info("Shutting down all processes...")

        # Cancel all queued tasks first
        for run_id, task in list(self._asyncio_tasks.items()):
            if not task.done():
                task.cancel()
                logger.info(f"Cancelled queued task: run_id={run_id}")
                stopped += 1

        # Stop all running processes
        for run_id in list(self._processes.keys()):
            if self.stop(run_id, timeout=timeout):
                stopped += 1

        logger.info(f"Shut down {stopped} processes")
        return stopped

    # --- PID File Management ---

    def _get_pid_file_path(self, run_id: str) -> Path:
        """Get PID file path for a run."""
        # Sanitize run_id for filesystem
        safe_id = run_id.replace("/", "_").replace("\\", "_")
        return self.data_dir / f"{safe_id}.json"

    def _write_pid_file(self, run_id: str, info: ProcessInfo) -> None:
        """Write process info to PID file."""
        try:
            path = self._get_pid_file_path(run_id)
            path.write_text(json.dumps(info.to_dict(), indent=2))
        except Exception as e:
            logger.error(f"Failed to write PID file for {run_id}: {e}")

    def _read_pid_file(self, run_id: str) -> ProcessInfo | None:
        """Read process info from PID file."""
        try:
            path = self._get_pid_file_path(run_id)
            if path.exists():
                return self._read_pid_file_from_path(path)
        except Exception as e:
            logger.error(f"Failed to read PID file for {run_id}: {e}")
        return None

    def _read_pid_file_from_path(self, path: Path) -> ProcessInfo | None:
        """Read process info from a specific PID file path."""
        try:
            data = json.loads(path.read_text())
            return ProcessInfo.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to read PID file {path}: {e}")
        return None

    def _remove_pid_file(self, run_id: str) -> None:
        """Remove PID file for a run."""
        try:
            path = self._get_pid_file_path(run_id)
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.error(f"Failed to remove PID file for {run_id}: {e}")

    # --- Queue State Persistence ---

    def queue_run(
        self,
        run_id: str,
        spec_path: str,
        spec_name: str,
        batch_id: str | None = None,
        browser: str = "chromium",
        hybrid: bool = False,
        max_iterations: int = 20,
        project_id: str | None = None,
    ) -> QueuedRunInfo:
        """
        Register a run as queued (not yet started).

        This allows the queue state to be persisted and recovered after server restart.

        Args:
            run_id: Unique run identifier
            spec_path: Path to the spec file
            spec_name: Name of the spec
            batch_id: Optional batch ID
            browser: Browser to use
            hybrid: Whether hybrid healing is enabled
            max_iterations: Max healing iterations
            project_id: Project ID for isolation

        Returns:
            QueuedRunInfo object
        """
        info = QueuedRunInfo(
            run_id=run_id,
            spec_path=spec_path,
            spec_name=spec_name,
            queued_at=datetime.utcnow().isoformat(),
            batch_id=batch_id,
            browser=browser,
            hybrid=hybrid,
            max_iterations=max_iterations,
            project_id=project_id,
        )

        self._queued_runs[run_id] = info
        self._persist_queue_state()

        logger.info(f"Queued run: run_id={run_id}, spec={spec_name}")
        return info

    def dequeue_run(self, run_id: str) -> QueuedRunInfo | None:
        """
        Remove a run from the queue (either because it started or was cancelled).

        Args:
            run_id: Unique run identifier

        Returns:
            QueuedRunInfo if found, None otherwise
        """
        info = self._queued_runs.pop(run_id, None)
        if info:
            self._persist_queue_state()
            logger.info(f"Dequeued run: run_id={run_id}")
        return info

    def get_queued_run(self, run_id: str) -> QueuedRunInfo | None:
        """Get info for a queued run."""
        return self._queued_runs.get(run_id)

    def get_all_queued(self) -> dict[str, QueuedRunInfo]:
        """Get all queued runs."""
        return dict(self._queued_runs)

    def _persist_queue_state(self) -> None:
        """Persist queue state to disk for restart recovery."""
        try:
            state = {run_id: info.to_dict() for run_id, info in self._queued_runs.items()}
            self._queue_state_file.write_text(json.dumps(state, indent=2))
            logger.debug(f"Persisted queue state: {len(state)} runs")
        except Exception as e:
            logger.error(f"Failed to persist queue state: {e}")

    def load_queue_state(self) -> dict[str, QueuedRunInfo]:
        """
        Load queue state from disk.

        This should be called on server startup to recover any queued runs.

        Returns:
            Dict of queued runs
        """
        if not self._queue_state_file.exists():
            logger.info("No queue state file found")
            return {}

        try:
            state = json.loads(self._queue_state_file.read_text())
            self._queued_runs = {run_id: QueuedRunInfo.from_dict(data) for run_id, data in state.items()}
            logger.info(f"Loaded queue state: {len(self._queued_runs)} runs")
            return dict(self._queued_runs)
        except Exception as e:
            logger.error(f"Failed to load queue state: {e}")
            return {}

    def clear_queue_state(self) -> int:
        """
        Clear all queued runs (e.g., after recovery or manual reset).

        Returns:
            Number of runs cleared
        """
        count = len(self._queued_runs)
        self._queued_runs.clear()

        try:
            if self._queue_state_file.exists():
                self._queue_state_file.unlink()
        except Exception as e:
            logger.error(f"Failed to remove queue state file: {e}")

        logger.info(f"Cleared queue state: {count} runs")
        return count


# Global singleton instance
_process_manager: ProcessManager | None = None


def get_process_manager() -> ProcessManager:
    """Get the global ProcessManager instance."""
    global _process_manager
    if _process_manager is None:
        _process_manager = ProcessManager()
    return _process_manager
