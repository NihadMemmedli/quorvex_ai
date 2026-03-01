"""
Redis-based queue for K6 load test execution tasks.

This module provides a distributed queue for offloading K6 load test execution
to dedicated worker containers, following the same pattern as agent_queue.py.

Architecture:
    API (uvicorn) -> Redis Queue -> K6 Worker (container/process)
                  <- Results <-

Redis key layout:
    playwright:k6:queue           - FIFO list of task IDs
    playwright:k6:tasks           - hash: task_id -> JSON task data
    playwright:k6:results         - hash: task_id -> JSON result data
    playwright:k6:running         - set of currently running task IDs
    playwright:k6:cancel:<run_id> - key set to "1" when cancelled
    playwright:k6:logs:<run_id>   - list of log lines (TTL 2h)
    playwright:k6:heartbeat:<id> - heartbeat key with 120s TTL
"""

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

try:
    import redis.asyncio as aioredis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class K6TaskStatus(str, Enum):
    """Status of a K6 load test task."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class K6Task:
    """Represents a K6 load test execution task."""

    id: str
    run_id: str
    script_path: str
    vus: int | None = None
    duration: str | None = None
    spec_name: str | None = None
    project_id: str | None = "default"
    status: K6TaskStatus = K6TaskStatus.QUEUED
    worker_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    # Execution segment fields for distributed load testing
    execution_segment: str | None = None  # e.g., "0:1/3"
    segment_index: int | None = None  # 0, 1, 2, ...
    parent_run_id: str | None = None  # links segments to parent run

    def to_dict(self) -> dict:
        """Convert to dictionary for Redis storage."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "script_path": self.script_path,
            "vus": self.vus,
            "duration": self.duration,
            "spec_name": self.spec_name,
            "project_id": self.project_id,
            "status": self.status.value,
            "worker_id": self.worker_id,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "execution_segment": self.execution_segment,
            "segment_index": self.segment_index,
            "parent_run_id": self.parent_run_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "K6Task":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            run_id=data["run_id"],
            script_path=data["script_path"],
            vus=data.get("vus"),
            duration=data.get("duration"),
            spec_name=data.get("spec_name"),
            project_id=data.get("project_id", "default"),
            status=K6TaskStatus(data.get("status", "queued")),
            worker_id=data.get("worker_id"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            error=data.get("error"),
            execution_segment=data.get("execution_segment"),
            segment_index=data.get("segment_index"),
            parent_run_id=data.get("parent_run_id"),
        )


class K6Queue:
    """
    Redis-based queue for K6 load test execution.

    Used to offload K6 execution from the backend API container to dedicated
    K6 worker containers that have the k6 binary installed.
    """

    # Redis key prefixes
    QUEUE_KEY = "playwright:k6:queue"
    RUNNING_KEY = "playwright:k6:running"
    TASKS_KEY = "playwright:k6:tasks"
    RESULTS_KEY = "playwright:k6:results"
    CANCEL_PREFIX = "playwright:k6:cancel:"
    LOGS_PREFIX = "playwright:k6:logs:"
    HEARTBEAT_PREFIX = "playwright:k6:heartbeat:"
    WORKER_HEARTBEAT_PREFIX = "playwright:k6:worker_alive:"
    SEGMENTS_PREFIX = "playwright:k6:segments:"  # segments:<run_id> -> JSON list of task_ids

    # TTLs
    LOG_TTL_SECONDS = 7200  # 2 hours
    HEARTBEAT_TTL_SECONDS = 120  # 2 minutes
    WORKER_HEARTBEAT_TTL_SECONDS = 30  # 30 seconds

    def __init__(self, redis_url: str | None = None):
        """Initialize the K6 queue."""
        if not REDIS_AVAILABLE:
            raise ImportError("redis package not installed. Run: pip install redis[hiredis]")

        self.redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self._redis: aioredis.Redis | None = None
        self._worker_id = os.environ.get("K6_WORKER_ID", f"k6-worker-{uuid.uuid4().hex[:8]}")

    async def connect(self) -> None:
        """Establish Redis connection."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info(f"K6Queue connected to Redis: {self.redis_url}")

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def health_check(self) -> bool:
        """Check Redis connectivity."""
        try:
            if self._redis:
                await self._redis.ping()
                return True
            return False
        except Exception:
            return False

    async def _ensure_connected(self) -> aioredis.Redis:
        """Ensure Redis is connected and return client."""
        if self._redis is None:
            await self.connect()
        return self._redis

    # ==========================================
    # Producer Methods (API/uvicorn)
    # ==========================================

    async def enqueue_k6_test(
        self,
        run_id: str,
        script_path: str,
        vus: int | None = None,
        duration: str | None = None,
        spec_name: str | None = None,
        project_id: str | None = "default",
    ) -> str:
        """
        Add a K6 load test task to the queue.

        Args:
            run_id: Unique run ID (load-<uuid8>)
            script_path: Path to the K6 .js script
            vus: Virtual users override
            duration: Duration override (e.g., '30s', '1m')
            spec_name: Name of the load test spec
            project_id: Project ID for multi-tenancy

        Returns:
            Task ID for tracking
        """
        redis = await self._ensure_connected()

        task = K6Task(
            id=f"k6-{uuid.uuid4().hex[:12]}",
            run_id=run_id,
            script_path=script_path,
            vus=vus,
            duration=duration,
            spec_name=spec_name,
            project_id=project_id,
        )

        # Store task data
        await redis.hset(self.TASKS_KEY, task.id, json.dumps(task.to_dict()))

        # Add to queue (FIFO)
        await redis.rpush(self.QUEUE_KEY, task.id)

        logger.info(f"Enqueued K6 task {task.id} (run_id={run_id}, spec={spec_name})")
        return task.id

    async def enqueue_segmented_test(
        self,
        run_id: str,
        script_path: str,
        num_segments: int,
        vus: int | None = None,
        duration: str | None = None,
        spec_name: str | None = None,
        project_id: str | None = "default",
    ) -> list[str]:
        """
        Enqueue a load test split across multiple segments for distributed execution.

        Creates N K6Task objects, each with a unique execution segment string.
        K6's --execution-segment flag splits VUs across instances automatically.

        Args:
            run_id: Unique run ID (load-<uuid8>)
            script_path: Path to the K6 .js script
            num_segments: Number of segments (typically = number of workers)
            vus: Virtual users override (K6 distributes based on segment)
            duration: Duration override
            spec_name: Name of the load test spec
            project_id: Project ID for multi-tenancy

        Returns:
            List of task IDs
        """
        redis = await self._ensure_connected()

        # Build execution segment strings: "0:1/N", "1/N:2/N", ..., "(N-1)/N:1"
        segments = []
        for i in range(num_segments):
            if i == 0:
                start = "0"
            else:
                start = f"{i}/{num_segments}"
            if i == num_segments - 1:
                end = "1"
            else:
                end = f"{i + 1}/{num_segments}"
            segments.append(f"{start}:{end}")

        task_ids = []
        for i, segment in enumerate(segments):
            task = K6Task(
                id=f"k6-{uuid.uuid4().hex[:12]}",
                run_id=run_id,
                script_path=script_path,
                vus=vus,
                duration=duration,
                spec_name=spec_name,
                project_id=project_id,
                execution_segment=segment,
                segment_index=i,
                parent_run_id=run_id,
            )

            # Store task data
            await redis.hset(self.TASKS_KEY, task.id, json.dumps(task.to_dict()))
            # Add to queue (FIFO)
            await redis.rpush(self.QUEUE_KEY, task.id)
            task_ids.append(task.id)

        # Store segment group mapping with 24h TTL
        await redis.set(
            f"{self.SEGMENTS_PREFIX}{run_id}",
            json.dumps(task_ids),
            ex=86400,
        )

        logger.info(f"Enqueued segmented K6 test: {num_segments} segments for run_id={run_id} (task_ids={task_ids})")
        return task_ids

    async def get_segment_status(self, run_id: str) -> dict:
        """
        Get aggregated status of all segments for a distributed test run.

        Returns:
            Dict with: total_segments, completed, failed, running, queued, all_done, segments
        """
        redis = await self._ensure_connected()

        # Get task IDs for this run's segments
        segment_json = await redis.get(f"{self.SEGMENTS_PREFIX}{run_id}")
        if not segment_json:
            return {
                "total_segments": 0,
                "completed": 0,
                "failed": 0,
                "running": 0,
                "queued": 0,
                "all_done": False,
                "segments": [],
            }

        task_ids = json.loads(segment_json)
        segments = []
        completed = 0
        failed = 0
        running = 0
        queued = 0

        for task_id in task_ids:
            task = await self.get_task(task_id)
            if not task:
                continue

            seg_info = {
                "task_id": task.id,
                "segment": task.execution_segment,
                "segment_index": task.segment_index,
                "status": task.status.value,
                "worker_id": task.worker_id,
                "error": task.error,
            }
            segments.append(seg_info)

            if task.status == K6TaskStatus.COMPLETED:
                completed += 1
            elif task.status in (K6TaskStatus.FAILED, K6TaskStatus.TIMEOUT, K6TaskStatus.CANCELLED):
                failed += 1
            elif task.status == K6TaskStatus.RUNNING:
                running += 1
            else:
                queued += 1

        total = len(segments)
        all_done = total > 0 and (completed + failed) == total

        return {
            "total_segments": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "queued": queued,
            "all_done": all_done,
            "segments": segments,
        }

    async def get_task(self, task_id: str) -> K6Task | None:
        """Get task details by ID."""
        redis = await self._ensure_connected()
        task_data = await redis.hget(self.TASKS_KEY, task_id)
        if task_data:
            return K6Task.from_dict(json.loads(task_data))
        return None

    async def cancel_task(self, run_id: str) -> bool:
        """Cancel all tasks by run_id. Sets cancel key and updates task status.

        For segmented tests, multiple tasks share the same run_id, so we cancel all of them.

        Args:
            run_id: The load test run ID

        Returns:
            True if any matching task was found and cancelled
        """
        redis = await self._ensure_connected()

        # Set the cancel flag so the worker picks it up
        await redis.set(f"{self.CANCEL_PREFIX}{run_id}", "1", ex=3600)

        found = False
        # Find and update ALL tasks by scanning tasks hash
        all_tasks = await redis.hgetall(self.TASKS_KEY)
        for task_id, task_json in all_tasks.items():
            try:
                task_data = json.loads(task_json)
                if task_data.get("run_id") == run_id:
                    task = K6Task.from_dict(task_data)
                    if task.status in (K6TaskStatus.QUEUED, K6TaskStatus.RUNNING):
                        # Remove from queue if still queued
                        await redis.lrem(self.QUEUE_KEY, 0, task_id)

                        task.status = K6TaskStatus.CANCELLED
                        task.completed_at = datetime.utcnow()
                        task.error = "Cancelled by user"
                        await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                        await redis.srem(self.RUNNING_KEY, task_id)
                        logger.info(f"Cancelled K6 task {task_id} (run_id={run_id})")
                        found = True
            except (json.JSONDecodeError, KeyError):
                continue

        return found

    async def get_logs(self, run_id: str, tail: int = 200) -> list[str]:
        """Get recent log lines for a run.

        Args:
            run_id: The load test run ID
            tail: Number of recent lines to return

        Returns:
            List of log line strings
        """
        redis = await self._ensure_connected()
        key = f"{self.LOGS_PREFIX}{run_id}"

        # Get the last `tail` entries from the list
        total = await redis.llen(key)
        if total == 0:
            return []

        start = max(0, total - tail)
        lines = await redis.lrange(key, start, -1)
        return lines

    # ==========================================
    # Consumer Methods (K6 Worker)
    # ==========================================

    async def dequeue_task(self, timeout: int = 30) -> K6Task | None:
        """
        Get the next task from the queue (blocking).

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            K6Task or None if timeout
        """
        redis = await self._ensure_connected()

        # Blocking pop from list (FIFO)
        result = await redis.blpop(self.QUEUE_KEY, timeout=timeout)

        if result:
            _, task_id = result

            # Get and update task data
            task_data = await redis.hget(self.TASKS_KEY, task_id)
            if task_data:
                task = K6Task.from_dict(json.loads(task_data))
                task.status = K6TaskStatus.RUNNING
                task.worker_id = self._worker_id
                task.started_at = datetime.utcnow()

                await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                await redis.sadd(self.RUNNING_KEY, task_id)

                logger.info(f"Worker {self._worker_id} dequeued K6 task {task_id} (run_id={task.run_id})")
                return task

        return None

    async def submit_result(self, task_id: str, result_dict: dict) -> None:
        """
        Submit result for a completed K6 task.

        Args:
            task_id: Task ID
            result_dict: Result dictionary from run_load_test()
        """
        redis = await self._ensure_connected()

        task_data = await redis.hget(self.TASKS_KEY, task_id)
        if task_data:
            task = K6Task.from_dict(json.loads(task_data))

            status = result_dict.get("status", "failed")
            if status == "completed":
                task.status = K6TaskStatus.COMPLETED
            else:
                task.status = K6TaskStatus.FAILED
                task.error = result_dict.get("error")

            task.completed_at = datetime.utcnow()

            await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
            await redis.hset(self.RESULTS_KEY, task_id, json.dumps(result_dict))
            await redis.srem(self.RUNNING_KEY, task_id)

            # Clean up cancel key if present
            await redis.delete(f"{self.CANCEL_PREFIX}{task.run_id}")

            logger.info(f"K6 task {task_id} {task.status.value} (run_id={task.run_id})")

    async def append_log(self, run_id: str, line: str) -> None:
        """Append a log line for a run.

        Args:
            run_id: The load test run ID
            line: Log line to append
        """
        redis = await self._ensure_connected()
        key = f"{self.LOGS_PREFIX}{run_id}"
        await redis.rpush(key, line)
        await redis.expire(key, self.LOG_TTL_SECONDS)

    async def check_cancelled(self, run_id: str) -> bool:
        """Check if a run has been cancelled (non-blocking).

        Args:
            run_id: The load test run ID

        Returns:
            True if cancellation was requested
        """
        redis = await self._ensure_connected()
        val = await redis.get(f"{self.CANCEL_PREFIX}{run_id}")
        return val == "1"

    async def update_heartbeat(self, task_id: str) -> None:
        """Update the heartbeat timestamp for a running task."""
        redis = await self._ensure_connected()
        await redis.set(
            f"{self.HEARTBEAT_PREFIX}{task_id}",
            datetime.utcnow().isoformat(),
            ex=self.HEARTBEAT_TTL_SECONDS,
        )

    async def update_worker_heartbeat(self, worker_id: str | None = None) -> None:
        """Update worker-level heartbeat to signal the worker is alive."""
        redis = await self._ensure_connected()
        wid = worker_id or self._worker_id
        await redis.set(
            f"{self.WORKER_HEARTBEAT_PREFIX}{wid}",
            datetime.utcnow().isoformat(),
            ex=self.WORKER_HEARTBEAT_TTL_SECONDS,
        )

    # ==========================================
    # Monitoring Methods
    # ==========================================

    async def queue_length(self) -> int:
        """Get current queue length."""
        redis = await self._ensure_connected()
        return await redis.llen(self.QUEUE_KEY)

    async def running_count(self) -> int:
        """Get count of running tasks."""
        redis = await self._ensure_connected()
        return await redis.scard(self.RUNNING_KEY)

    async def worker_count(self) -> int:
        """Count alive workers by counting active worker heartbeat keys."""
        redis = await self._ensure_connected()
        count = 0
        async for _key in redis.scan_iter(f"{self.WORKER_HEARTBEAT_PREFIX}*"):
            count += 1
        return count

    async def get_metrics(self) -> dict:
        """Get queue metrics."""
        return {
            "queue_length": await self.queue_length(),
            "running": await self.running_count(),
            "workers_alive": await self.worker_count(),
        }

    async def cleanup_stale_tasks(self, max_age_minutes: int = 70) -> int:
        """Clean up tasks running too long (default 70 min, above K6 60-min timeout).

        Also removes expired task data older than 24 hours.
        """
        redis = await self._ensure_connected()
        cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        cleaned = 0

        running_ids = await redis.smembers(self.RUNNING_KEY)
        for task_id in running_ids:
            task = await self.get_task(task_id)
            if task and task.started_at and task.started_at < cutoff:
                task.status = K6TaskStatus.TIMEOUT
                task.completed_at = datetime.utcnow()
                task.error = f"Task timed out after {max_age_minutes} minutes (stale cleanup)"

                await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                await redis.srem(self.RUNNING_KEY, task_id)
                await redis.delete(f"{self.HEARTBEAT_PREFIX}{task_id}")
                if task.run_id:
                    await redis.delete(f"{self.CANCEL_PREFIX}{task.run_id}")
                cleaned += 1
                logger.warning(f"Cleaned up stale K6 task {task_id} (run_id={task.run_id})")

        # Clean up old completed/failed task data (older than 24h)
        data_cutoff = datetime.utcnow() - timedelta(hours=24)
        all_tasks = await redis.hgetall(self.TASKS_KEY)
        for task_id, task_json in all_tasks.items():
            try:
                task_data = json.loads(task_json)
                status = task_data.get("status")
                if status in ("completed", "failed", "timeout", "cancelled"):
                    completed_at = task_data.get("completed_at")
                    if completed_at:
                        completed_dt = datetime.fromisoformat(completed_at)
                        if completed_dt < data_cutoff:
                            await redis.hdel(self.TASKS_KEY, task_id)
                            await redis.hdel(self.RESULTS_KEY, task_id)
                            cleaned += 1
            except (json.JSONDecodeError, ValueError, KeyError):
                continue

        return cleaned

    async def start_cleanup_loop(self, interval_seconds: int = 300):
        """Run cleanup_stale_tasks() periodically in the background.

        Args:
            interval_seconds: How often to run cleanup (default: 5 minutes)
        """
        logger.info(f"Starting K6 queue cleanup loop (every {interval_seconds}s)")
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                cleaned = await self.cleanup_stale_tasks()
                if cleaned > 0:
                    logger.info(f"K6 cleanup loop: cleaned {cleaned} stale tasks")
            except asyncio.CancelledError:
                logger.info("K6 cleanup loop cancelled")
                break
            except Exception as e:
                logger.error(f"K6 cleanup loop error: {e}", exc_info=True)
                await asyncio.sleep(30)  # Back off on error


# Singleton instance
_k6_queue_instance: K6Queue | None = None


def get_k6_queue() -> K6Queue:
    """Get or create the singleton K6Queue instance."""
    global _k6_queue_instance
    if _k6_queue_instance is None:
        _k6_queue_instance = K6Queue()
    return _k6_queue_instance


def should_use_k6_queue() -> bool:
    """Check if Redis is available and K6 queue mode is enabled."""
    if not REDIS_AVAILABLE:
        return False
    redis_url = os.environ.get("REDIS_URL", "")
    use_queue = os.environ.get("USE_K6_QUEUE", "true").lower() == "true"
    return bool(redis_url) and use_queue
