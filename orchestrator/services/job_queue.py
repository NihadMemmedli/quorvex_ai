"""
Redis-based job queue for distributed Playwright test execution.

This module provides a job queue for distributing test execution across
multiple browser worker containers, enabling horizontal scaling and
crash isolation.

Architecture:
    Backend (orchestrator) → Redis Queue → Browser Workers (N replicas)
                          ← Results ←

Usage:
    # In orchestrator
    queue = JobQueue()
    job_id = await queue.enqueue_test("spec.md", {"project": "chromium"})
    result = await queue.wait_for_result(job_id, timeout=300)

    # In browser worker
    queue = JobQueue()
    while True:
        job = await queue.dequeue_test(timeout=30)
        if job:
            result = run_test(job)
            await queue.submit_result(job["id"], result)
"""

import asyncio
import json
import logging
import os
import time
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


class JobStatus(str, Enum):
    """Status of a test job in the queue."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class TestJob:
    """Represents a test execution job."""

    id: str
    spec_path: str
    config: dict = field(default_factory=dict)
    status: JobStatus = JobStatus.QUEUED
    worker_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for Redis storage."""
        return {
            "id": self.id,
            "spec_path": self.spec_path,
            "config": self.config,
            "status": self.status.value,
            "worker_id": self.worker_id,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TestJob":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            spec_path=data["spec_path"],
            config=data.get("config", {}),
            status=JobStatus(data.get("status", "queued")),
            worker_id=data.get("worker_id"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            result=data.get("result"),
            error=data.get("error"),
        )


class JobQueue:
    """
    Redis-based job queue for distributed test execution.

    Supports:
    - Enqueueing test jobs with configuration
    - Distributed dequeue with atomic pop
    - Result submission and retrieval
    - Job status tracking
    - Queue metrics for auto-scaling (HPA)
    """

    # Redis key prefixes
    QUEUE_KEY = "playwright:jobs:queue"
    RUNNING_KEY = "playwright:jobs:running"
    JOBS_KEY = "playwright:jobs:data"
    RESULTS_KEY = "playwright:jobs:results"
    METRICS_KEY = "playwright:jobs:metrics"

    def __init__(self, redis_url: str | None = None):
        """
        Initialize the job queue.

        Args:
            redis_url: Redis connection URL. Defaults to REDIS_URL env var or localhost.
        """
        if not REDIS_AVAILABLE:
            raise ImportError("redis package not installed. Run: pip install redis[hiredis]")

        self.redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self._redis: aioredis.Redis | None = None
        self._worker_id = os.environ.get("WORKER_ID", f"worker-{uuid.uuid4().hex[:8]}")
        self._last_ping_time: float = 0.0
        self._ping_interval: float = 5.0

    async def connect(self) -> None:
        """Establish Redis connection."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                retry_on_error=[ConnectionError, TimeoutError],
                health_check_interval=30,
            )
            # Test connection
            await self._redis.ping()
            logger.info(f"JobQueue connected to Redis: {self.redis_url}")

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
        """Ensure Redis is connected and return client, with auto-reconnect."""
        now = time.monotonic()
        if self._redis is not None and (now - self._last_ping_time) < self._ping_interval:
            return self._redis

        if self._redis is not None:
            try:
                await asyncio.wait_for(self._redis.ping(), timeout=2.0)
                self._last_ping_time = now
                return self._redis
            except Exception:
                logger.warning("JobQueue Redis connection lost, reconnecting...")
                try:
                    await self._redis.close()
                except Exception:
                    pass
                self._redis = None

        await self.connect()
        self._last_ping_time = time.monotonic()
        return self._redis

    # ==========================================
    # Producer Methods (Backend/Orchestrator)
    # ==========================================

    async def enqueue_test(
        self,
        spec_path: str,
        config: dict | None = None,
        priority: int = 0,
    ) -> str:
        """
        Add a test job to the queue.

        Args:
            spec_path: Path to the test specification file
            config: Test configuration (project, timeout, etc.)
            priority: Job priority (higher = processed first)

        Returns:
            Job ID for tracking
        """
        redis = await self._ensure_connected()

        job = TestJob(
            id=f"job-{uuid.uuid4().hex[:12]}",
            spec_path=spec_path,
            config=config or {},
        )

        # Store job data
        await redis.hset(self.JOBS_KEY, job.id, json.dumps(job.to_dict()))

        # Add to queue (use sorted set for priority)
        score = -priority + (datetime.utcnow().timestamp() / 1e10)  # Negative priority for ZPOPMIN
        await redis.zadd(self.QUEUE_KEY, {job.id: score})

        # Update metrics
        await self._update_metrics("enqueued", 1)

        logger.info(f"Enqueued job {job.id} for {spec_path}")
        return job.id

    async def enqueue_batch(
        self,
        specs: list[tuple[str, dict]],
        priority: int = 0,
    ) -> list[str]:
        """
        Add multiple test jobs to the queue.

        Args:
            specs: List of (spec_path, config) tuples
            priority: Job priority for all jobs

        Returns:
            List of job IDs
        """
        job_ids = []
        for spec_path, config in specs:
            job_id = await self.enqueue_test(spec_path, config, priority)
            job_ids.append(job_id)
        return job_ids

    async def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a queued job.

        Args:
            job_id: Job ID to cancel

        Returns:
            True if job was cancelled, False if already running/completed
        """
        redis = await self._ensure_connected()

        # Remove from queue
        removed = await redis.zrem(self.QUEUE_KEY, job_id)

        if removed:
            # Update job status
            job_data = await redis.hget(self.JOBS_KEY, job_id)
            if job_data:
                job = TestJob.from_dict(json.loads(job_data))
                job.status = JobStatus.CANCELLED
                job.completed_at = datetime.utcnow()
                await redis.hset(self.JOBS_KEY, job_id, json.dumps(job.to_dict()))

            await self._update_metrics("cancelled", 1)
            logger.info(f"Cancelled job {job_id}")
            return True

        return False

    async def get_job(self, job_id: str) -> TestJob | None:
        """Get job details by ID."""
        redis = await self._ensure_connected()
        job_data = await redis.hget(self.JOBS_KEY, job_id)
        if job_data:
            return TestJob.from_dict(json.loads(job_data))
        return None

    async def wait_for_result(
        self,
        job_id: str,
        timeout: float = 300.0,
        poll_interval: float = 1.0,
    ) -> dict:
        """
        Wait for a job to complete and return result.

        Args:
            job_id: Job ID to wait for
            timeout: Maximum wait time in seconds
            poll_interval: Poll interval in seconds

        Returns:
            Job result dict on success

        Raises:
            asyncio.TimeoutError: If timeout expires
            RuntimeError: If job is cancelled or fails
        """
        await self._ensure_connected()
        start_time = datetime.utcnow()

        while (datetime.utcnow() - start_time).total_seconds() < timeout:
            job = await self.get_job(job_id)
            if job:
                if job.status == JobStatus.COMPLETED:
                    return {
                        "status": job.status.value,
                        "result": job.result,
                        "error": job.error,
                        "duration": (job.completed_at - job.started_at).total_seconds()
                        if job.started_at and job.completed_at
                        else None,
                    }
                elif job.status == JobStatus.CANCELLED:
                    raise RuntimeError(f"Job {job_id} was cancelled")
                elif job.status in (JobStatus.FAILED, JobStatus.TIMEOUT):
                    error_msg = job.error or f"Job {job.status.value}"
                    raise RuntimeError(error_msg)
            await asyncio.sleep(poll_interval)

        raise asyncio.TimeoutError(f"Job {job_id} timed out after {timeout}s")

    # ==========================================
    # Consumer Methods (Browser Workers)
    # ==========================================

    async def dequeue_test(self, timeout: int = 30) -> TestJob | None:
        """
        Get the next test job from the queue (blocking).

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            TestJob or None if timeout
        """
        redis = await self._ensure_connected()

        # Atomic pop from sorted set
        result = await redis.bzpopmin(self.QUEUE_KEY, timeout=timeout)

        if result:
            _, job_id, _ = result

            # Get and update job data
            job_data = await redis.hget(self.JOBS_KEY, job_id)
            if job_data:
                job = TestJob.from_dict(json.loads(job_data))
                job.status = JobStatus.RUNNING
                job.worker_id = self._worker_id
                job.started_at = datetime.utcnow()

                # Use pipeline for atomic state transition
                async with redis.pipeline(transaction=True) as pipe:
                    pipe.hset(self.JOBS_KEY, job_id, json.dumps(job.to_dict()))
                    pipe.sadd(self.RUNNING_KEY, job_id)
                    await pipe.execute()

                await self._update_metrics("dequeued", 1)
                logger.info(f"Worker {self._worker_id} dequeued job {job_id}")

                return job

        return None

    async def submit_result(
        self,
        job_id: str,
        result: dict,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """
        Submit result for a completed job.

        Args:
            job_id: Job ID
            result: Test result data
            success: Whether test passed
            error: Error message if failed
        """
        redis = await self._ensure_connected()

        # Get and update job
        job_data = await redis.hget(self.JOBS_KEY, job_id)
        if job_data:
            job = TestJob.from_dict(json.loads(job_data))
            job.status = JobStatus.COMPLETED if success else JobStatus.FAILED
            job.completed_at = datetime.utcnow()
            job.result = result
            job.error = error

            # Update job and remove from running set
            await redis.hset(self.JOBS_KEY, job_id, json.dumps(job.to_dict()))
            await redis.srem(self.RUNNING_KEY, job_id)

            # Store result separately for quick lookup
            await redis.hset(
                self.RESULTS_KEY,
                job_id,
                json.dumps(
                    {
                        "success": success,
                        "result": result,
                        "error": error,
                    }
                ),
            )

            metric = "completed" if success else "failed"
            await self._update_metrics(metric, 1)

            logger.info(f"Job {job_id} {'completed' if success else 'failed'}")

    # ==========================================
    # Metrics Methods (for HPA/monitoring)
    # ==========================================

    async def queue_length(self) -> int:
        """Get current queue length (pending jobs)."""
        redis = await self._ensure_connected()
        return await redis.zcard(self.QUEUE_KEY)

    async def running_count(self) -> int:
        """Get count of currently running jobs."""
        redis = await self._ensure_connected()
        return await redis.scard(self.RUNNING_KEY)

    async def get_metrics(self) -> dict:
        """
        Get queue metrics for monitoring/auto-scaling.

        Returns dict with:
            - queue_length: Pending jobs
            - running: Currently executing jobs
            - completed: Total completed jobs
            - failed: Total failed jobs
            - enqueued: Total enqueued jobs
        """
        redis = await self._ensure_connected()

        queue_length = await self.queue_length()
        running = await self.running_count()

        metrics_data = await redis.hgetall(self.METRICS_KEY)

        return {
            "queue_length": queue_length,
            "running": running,
            "enqueued": int(metrics_data.get("enqueued", 0)),
            "dequeued": int(metrics_data.get("dequeued", 0)),
            "completed": int(metrics_data.get("completed", 0)),
            "failed": int(metrics_data.get("failed", 0)),
            "cancelled": int(metrics_data.get("cancelled", 0)),
        }

    async def _update_metrics(self, metric: str, value: int) -> None:
        """Increment a metric counter."""
        redis = await self._ensure_connected()
        await redis.hincrby(self.METRICS_KEY, metric, value)

    # ==========================================
    # Maintenance Methods
    # ==========================================

    async def cleanup_stale_jobs(self, max_age_minutes: int = 60) -> int:
        """
        Clean up jobs that have been running too long (likely crashed workers).

        Args:
            max_age_minutes: Maximum job running time before considered stale

        Returns:
            Number of jobs cleaned up
        """
        redis = await self._ensure_connected()
        cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        cleaned = 0

        # Get all running jobs
        running_ids = await redis.smembers(self.RUNNING_KEY)

        for job_id in running_ids:
            job = await self.get_job(job_id)
            if job and job.started_at and job.started_at < cutoff:
                # Mark as timeout and remove from running
                job.status = JobStatus.TIMEOUT
                job.completed_at = datetime.utcnow()
                job.error = f"Job timed out after {max_age_minutes} minutes"

                await redis.hset(self.JOBS_KEY, job_id, json.dumps(job.to_dict()))
                await redis.srem(self.RUNNING_KEY, job_id)

                await self._update_metrics("timeout", 1)
                cleaned += 1
                logger.warning(f"Cleaned up stale job {job_id}")

        return cleaned

    async def cleanup_completed_jobs(self, max_age_hours: int = 24) -> int:
        """Remove completed/failed/cancelled/timeout jobs older than max_age_hours."""
        redis = await self._ensure_connected()
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        removed = 0

        all_jobs = await redis.hgetall(self.JOBS_KEY)
        for job_id, job_data_str in all_jobs.items():
            try:
                job_data = json.loads(job_data_str)
                status = job_data.get("status")
                if status in ("completed", "failed", "timeout", "cancelled"):
                    completed_at = job_data.get("completed_at")
                    if completed_at:
                        completed_dt = datetime.fromisoformat(completed_at)
                        if completed_dt < cutoff:
                            await redis.hdel(self.JOBS_KEY, job_id)
                            await redis.hdel(self.RESULTS_KEY, job_id)
                            removed += 1
            except (json.JSONDecodeError, ValueError):
                continue

        if removed:
            logger.info(f"Cleaned up {removed} completed jobs older than {max_age_hours}h")
        return removed

    async def start_cleanup_loop(self, interval_seconds: int = 300):
        """Run cleanup_stale_jobs() and cleanup_completed_jobs() periodically."""
        logger.info(f"Starting job queue cleanup loop (every {interval_seconds}s)")
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                cleaned = await self.cleanup_stale_jobs()
                if cleaned > 0:
                    logger.info(f"Job cleanup loop: cleaned {cleaned} stale jobs")
                removed = await self.cleanup_completed_jobs(max_age_hours=24)
                if removed > 0:
                    logger.info(f"Job cleanup loop: removed {removed} old completed jobs")
            except asyncio.CancelledError:
                logger.info("Job cleanup loop cancelled")
                break
            except Exception as e:
                logger.error(f"Job cleanup loop error: {e}", exc_info=True)
                await asyncio.sleep(30)

    async def clear_all(self) -> None:
        """Clear all queue data (for testing)."""
        redis = await self._ensure_connected()
        await redis.delete(
            self.QUEUE_KEY,
            self.RUNNING_KEY,
            self.JOBS_KEY,
            self.RESULTS_KEY,
            self.METRICS_KEY,
        )
        logger.info("Cleared all job queue data")


# Singleton instance
_queue_instance: JobQueue | None = None


def get_job_queue() -> JobQueue:
    """Get or create the singleton JobQueue instance."""
    global _queue_instance
    if _queue_instance is None:
        _queue_instance = JobQueue()
    return _queue_instance
