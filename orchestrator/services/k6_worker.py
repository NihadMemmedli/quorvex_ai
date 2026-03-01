#!/usr/bin/env python3
"""
K6 Worker Service

This worker runs as a separate process (or container), polling Redis for K6 load
test tasks and executing them using the existing load_test_runner module.

Key features:
- Runs outside uvicorn's event loop context
- Calls run_load_test() directly (no Claude CLI involved)
- Streams execution logs to Redis for real-time viewing
- Supports cancellation via Redis cancel keys
- Heartbeat to signal liveness

Usage:
    python -m orchestrator.services.k6_worker
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# Setup logging early
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("k6_worker")

# Add project root to path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from orchestrator.load_env import setup_claude_env
from orchestrator.services.k6_queue import K6Queue, K6Task, get_k6_queue


class K6Worker:
    """Worker that executes K6 load test tasks from Redis queue."""

    def __init__(self):
        self.queue: K6Queue | None = None
        import socket

        hostname = socket.gethostname()
        self.worker_id = f"k6-worker-{hostname}"
        self.running = False
        self.cwd = str(project_root)
        self._current_k6_pid: int | None = None
        self._current_run_id: str | None = None

        # Setup environment
        setup_claude_env()

    async def _worker_heartbeat_loop(self):
        """Send periodic worker-level heartbeats to signal liveness."""
        try:
            while self.running:
                await self.queue.update_worker_heartbeat(self.worker_id)
                await asyncio.sleep(15)  # Every 15s, TTL is 30s
        except asyncio.CancelledError:
            pass

    async def start(self):
        """Start the worker loop."""
        logger.info(f"Starting K6 worker: {self.worker_id}")
        logger.info(f"  Working directory: {self.cwd}")
        logger.info(f"  Project root: {project_root}")

        self.queue = get_k6_queue()
        await self.queue.connect()

        self.running = True
        consecutive_empty = 0

        # Start continuous worker heartbeat
        await self.queue.update_worker_heartbeat(self.worker_id)
        heartbeat_task = asyncio.create_task(self._worker_heartbeat_loop())
        logger.info(f"Worker heartbeat started (id={self.worker_id})")

        try:
            while self.running:
                try:
                    # Dequeue task (blocking for up to 10 seconds)
                    task = await self.queue.dequeue_task(timeout=10)

                    if task:
                        consecutive_empty = 0
                        logger.info(f"Processing K6 task {task.id} (run_id={task.run_id}, spec={task.spec_name})")
                        await self._execute_task(task)
                    else:
                        consecutive_empty += 1
                        if consecutive_empty % 30 == 0:  # Log every 5 minutes
                            metrics = await self.queue.get_metrics()
                            logger.debug(f"Queue idle, metrics: {metrics}")

                except asyncio.CancelledError:
                    logger.info("Worker cancelled")
                    break
                except Exception as e:
                    logger.error(f"Worker error: {e}", exc_info=True)
                    await asyncio.sleep(5)  # Back off on error
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        await self.queue.disconnect()
        logger.info("K6 worker stopped")

    async def stop(self):
        """Stop the worker gracefully."""
        logger.info("Stop requested, finishing current task...")
        self.running = False

        # If a K6 process is running, send SIGTERM
        if self._current_k6_pid:
            try:
                os.killpg(os.getpgid(self._current_k6_pid), signal.SIGTERM)
                logger.info(f"Sent SIGTERM to K6 process {self._current_k6_pid}")
            except (ProcessLookupError, OSError):
                pass

    async def _heartbeat_loop(self, task_id: str, interval: int = 60):
        """Send periodic heartbeat updates for a running task."""
        try:
            while True:
                await self.queue.update_heartbeat(task_id)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    async def _cancel_monitor(self, run_id: str, check_interval: float = 2.0):
        """Monitor for cancellation requests and kill K6 if cancelled."""
        try:
            while True:
                await asyncio.sleep(check_interval)
                if await self.queue.check_cancelled(run_id):
                    logger.info(f"Cancellation detected for run {run_id}")
                    if self._current_k6_pid:
                        try:
                            os.killpg(os.getpgid(self._current_k6_pid), signal.SIGTERM)
                            logger.info(f"Sent SIGTERM to K6 process {self._current_k6_pid}")
                        except (ProcessLookupError, OSError):
                            pass
                    return
        except asyncio.CancelledError:
            pass

    async def _log_streamer(self, run_id: str, log_path: Path, poll_interval: float = 1.0):
        """Stream log file contents to Redis as they appear."""
        try:
            # Wait for log file to exist
            for _ in range(30):
                if log_path.exists():
                    break
                await asyncio.sleep(1.0)

            if not log_path.exists():
                return

            with open(log_path, errors="replace") as f:
                while True:
                    line = f.readline()
                    if line:
                        line = line.rstrip("\n")
                        if line:
                            await self.queue.append_log(run_id, line)
                    else:
                        await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            # Flush remaining lines on cancel
            try:
                if log_path.exists():
                    with open(log_path, errors="replace") as f:
                        for line in f:
                            line = line.rstrip("\n")
                            if line:
                                await self.queue.append_log(run_id, line)
            except Exception:
                pass

    async def _execute_task(self, task: K6Task):
        """Execute a K6 load test task."""
        # Start heartbeat
        heartbeat = asyncio.create_task(self._heartbeat_loop(task.id))
        await self.queue.update_heartbeat(task.id)

        # Start cancel monitor
        cancel_monitor = asyncio.create_task(self._cancel_monitor(task.run_id))

        # Log file path for streaming (segment-specific subdirectory if segmented)
        runs_dir = project_root / "runs" / "load"
        if task.execution_segment:
            seg_safe = task.execution_segment.replace("/", "_").replace(":", "-")
            log_path = runs_dir / task.run_id / f"seg-{seg_safe}" / "execution.log"
        else:
            log_path = runs_dir / task.run_id / "execution.log"

        # Start log streamer
        log_streamer = asyncio.create_task(self._log_streamer(task.run_id, log_path))

        self._current_run_id = task.run_id

        try:
            result = await self._run_k6(task)

            # Check if it was cancelled
            if await self.queue.check_cancelled(task.run_id):
                result["status"] = "cancelled"
                result["error"] = "Cancelled by user"

            await self.queue.submit_result(task.id, result)

            # Update DB record (skip for segmented tasks - API-side aggregation handles it)
            if not task.execution_segment:
                self._update_db(task.run_id, result)

        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}", exc_info=True)
            error_result = {
                "status": "failed",
                "error": str(e),
                "run_dir": str(runs_dir / task.run_id),
            }
            await self.queue.submit_result(task.id, error_result)
            if not task.execution_segment:
                self._update_db(task.run_id, error_result)

        finally:
            self._current_k6_pid = None
            self._current_run_id = None

            # Cancel background tasks
            for bg_task in [heartbeat, cancel_monitor, log_streamer]:
                bg_task.cancel()
                try:
                    await bg_task
                except asyncio.CancelledError:
                    pass

    async def _run_k6(self, task: K6Task) -> dict:
        """Run K6 load test via load_test_runner.run_load_test()."""
        loop = asyncio.get_event_loop()

        def _run_sync():
            sys.path.insert(0, str(project_root / "orchestrator"))
            from workflows.load_test_runner import run_load_test

            def _pid_callback(pid):
                self._current_k6_pid = pid

            return run_load_test(
                run_id=task.run_id,
                script_path=task.script_path,
                vus=task.vus,
                duration=task.duration,
                pid_callback=_pid_callback,
                execution_segment=task.execution_segment,
            )

        result = await loop.run_in_executor(None, _run_sync)
        return result

    def _update_db(self, run_id: str, result: dict):
        """Update the LoadTestRun DB record with results."""
        try:
            sys.path.insert(0, str(project_root / "orchestrator"))
            from workflows.load_test_runner import update_db_record

            update_db_record(run_id, result)
        except Exception as e:
            logger.error(f"Failed to update DB for run {run_id}: {e}")


async def main():
    """Main entry point."""
    worker = K6Worker()

    # Handle shutdown signals
    def handle_signal(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        asyncio.get_event_loop().create_task(worker.stop())

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
