"""
Redis-based queue for agent execution tasks.

This module provides a queue for distributing agent execution tasks to a separate
worker process that runs outside of uvicorn's context, solving the subprocess I/O
issues that occur when spawning the Claude CLI from within uvicorn workers.

Architecture:
    API (uvicorn) → Redis Queue → Agent Worker (supervisord)
                  ← Results ←

The worker runs as a separate supervisord program, giving it a clean process
environment without uvicorn's event loop modifications.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

try:
    import redis.asyncio as aioredis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class AgentTaskStatus(str, Enum):
    """Status of an agent task."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class AgentTask:
    """Represents an agent execution task."""

    id: str
    prompt: str
    system_prompt: str | None = None
    timeout_seconds: int = 1800
    status: AgentTaskStatus = AgentTaskStatus.QUEUED
    worker_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: str | None = None
    error: str | None = None
    # Metadata for tracking
    agent_type: str | None = None
    operation_type: str | None = None
    cwd: str | None = None  # Working directory for CLI execution
    env_vars: dict[str, str] | None = None  # API credentials to pass to worker

    def to_dict(self) -> dict:
        """Convert to dictionary for Redis storage."""
        return {
            "id": self.id,
            "prompt": self.prompt,
            "system_prompt": self.system_prompt,
            "timeout_seconds": self.timeout_seconds,
            "status": self.status.value,
            "worker_id": self.worker_id,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
            "agent_type": self.agent_type,
            "operation_type": self.operation_type,
            "cwd": self.cwd,
            "env_vars": self.env_vars,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentTask":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            prompt=data["prompt"],
            system_prompt=data.get("system_prompt"),
            timeout_seconds=data.get("timeout_seconds", 1800),
            status=AgentTaskStatus(data.get("status", "queued")),
            worker_id=data.get("worker_id"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            result=data.get("result"),
            error=data.get("error"),
            agent_type=data.get("agent_type"),
            operation_type=data.get("operation_type"),
            cwd=data.get("cwd"),
            env_vars=data.get("env_vars"),
        )


class AgentQueue:
    """
    Redis-based queue for agent task execution.

    Used to offload agent execution from uvicorn workers to a separate
    process with a clean environment.
    """

    # Redis key prefixes
    QUEUE_KEY = "playwright:agents:queue"
    RUNNING_KEY = "playwright:agents:running"
    TASKS_KEY = "playwright:agents:tasks"
    RESULTS_KEY = "playwright:agents:results"
    CHANNEL_KEY = "playwright:agents:notifications"
    HEARTBEAT_PREFIX = "playwright:agents:heartbeat:"
    CANCEL_PREFIX = "playwright:agents:cancel:"
    WORKER_HEARTBEAT_PREFIX = "playwright:agents:worker_alive:"
    WORKER_HEARTBEAT_TTL_SECONDS = 30

    def __init__(self, redis_url: str | None = None):
        """Initialize the agent queue."""
        if not REDIS_AVAILABLE:
            raise ImportError("redis package not installed. Run: pip install redis[hiredis]")

        self.redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self._redis: aioredis.Redis | None = None
        self._worker_id = os.environ.get("AGENT_WORKER_ID", f"agent-worker-{uuid.uuid4().hex[:8]}")
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
            await self._redis.ping()
            logger.info(f"AgentQueue connected to Redis: {self.redis_url}")

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
                logger.warning("AgentQueue Redis connection lost, reconnecting...")
                try:
                    await self._redis.close()
                except Exception:
                    pass
                self._redis = None

        await self.connect()
        self._last_ping_time = time.monotonic()
        return self._redis

    # ==========================================
    # Producer Methods (API/uvicorn)
    # ==========================================

    async def enqueue_task(
        self,
        prompt: str,
        system_prompt: str | None = None,
        timeout_seconds: int = 1800,
        agent_type: str | None = None,
        operation_type: str | None = None,
        cwd: str | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> str:
        """
        Add an agent task to the queue.

        Args:
            prompt: The prompt to send to the agent
            system_prompt: Optional system prompt
            timeout_seconds: Execution timeout
            agent_type: Type of agent (explorer, planner, etc.)
            operation_type: Type of operation (exploration, prd, etc.)
            cwd: Working directory for CLI execution (defaults to project root)
            env_vars: API credentials to pass to worker process

        Returns:
            Task ID for tracking
        """
        redis = await self._ensure_connected()

        task = AgentTask(
            id=f"agent-{uuid.uuid4().hex[:12]}",
            prompt=prompt,
            system_prompt=system_prompt,
            timeout_seconds=timeout_seconds,
            agent_type=agent_type,
            operation_type=operation_type,
            cwd=cwd,
            env_vars=env_vars,
        )

        # Atomic store + enqueue
        async with redis.pipeline(transaction=True) as pipe:
            pipe.hset(self.TASKS_KEY, task.id, json.dumps(task.to_dict()))
            pipe.rpush(self.QUEUE_KEY, task.id)
            await pipe.execute()

        logger.info(f"Enqueued agent task {task.id} (type={agent_type}, op={operation_type})")
        return task.id

    async def get_task(self, task_id: str) -> AgentTask | None:
        """Get task details by ID."""
        redis = await self._ensure_connected()
        task_data = await redis.hget(self.TASKS_KEY, task_id)
        if task_data:
            return AgentTask.from_dict(json.loads(task_data))
        return None

    async def update_heartbeat(self, task_id: str, progress: dict[str, Any] | None = None) -> None:
        """Update the heartbeat timestamp for a running task.

        Args:
            task_id: Task ID
            progress: Optional progress dict (e.g. tool_calls count, last_tool name)
        """
        redis = await self._ensure_connected()
        heartbeat_data = json.dumps(
            {
                "ts": datetime.utcnow().isoformat(),
                "progress": progress or {},
            }
        )
        await redis.set(
            f"{self.HEARTBEAT_PREFIX}{task_id}",
            heartbeat_data,
            ex=120,  # Expire after 2 minutes if not refreshed
        )

    async def check_heartbeat(self, task_id: str, max_stale_seconds: int = 120) -> bool:
        """Check if a task's heartbeat is still fresh.

        Returns True if heartbeat is fresh (worker is alive), False if stale.
        Handles both legacy (bare timestamp string) and new (JSON dict) formats.
        """
        redis = await self._ensure_connected()
        heartbeat = await redis.get(f"{self.HEARTBEAT_PREFIX}{task_id}")
        if not heartbeat:
            return False
        try:
            # Try JSON format first (new)
            try:
                data = json.loads(heartbeat)
                ts_str = data.get("ts", heartbeat)
            except (json.JSONDecodeError, TypeError):
                ts_str = heartbeat  # Legacy: bare timestamp string
            last_beat = datetime.fromisoformat(ts_str)
            age = (datetime.utcnow() - last_beat).total_seconds()
            return age < max_stale_seconds
        except (ValueError, TypeError):
            return False

    async def get_task_progress(self, task_id: str) -> dict[str, Any] | None:
        """Get live progress data from a task's heartbeat.

        Returns the progress dict if available, or None.
        """
        redis = await self._ensure_connected()
        heartbeat = await redis.get(f"{self.HEARTBEAT_PREFIX}{task_id}")
        if not heartbeat:
            return None
        try:
            data = json.loads(heartbeat)
            return data.get("progress")
        except (json.JSONDecodeError, TypeError):
            return None

    async def update_worker_heartbeat(self, worker_id: str) -> None:
        """Update worker-level heartbeat to signal the worker process is alive.

        Called periodically by the worker's main loop (not tied to any specific task).
        """
        redis = await self._ensure_connected()
        await redis.set(
            f"{self.WORKER_HEARTBEAT_PREFIX}{worker_id}",
            datetime.utcnow().isoformat(),
            ex=self.WORKER_HEARTBEAT_TTL_SECONDS,
        )

    async def worker_count(self) -> int:
        """Count alive workers by counting active worker heartbeat keys."""
        redis = await self._ensure_connected()
        count = 0
        async for _ in redis.scan_iter(f"{self.WORKER_HEARTBEAT_PREFIX}*"):
            count += 1
        return count

    async def wait_for_result(
        self,
        task_id: str,
        timeout: float = 1800.0,
        poll_interval: float = 0.5,
        queued_timeout: float = 120.0,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> str | None:
        """
        Wait for a task to complete and return result.

        Monitors worker heartbeat to detect dead workers early rather than
        waiting for the full timeout.  Also detects tasks stuck in QUEUED
        state when no workers are alive to pick them up.

        NOTE: Uses polling instead of Redis pub/sub subscription for reliability.
        See submit_result() for the complementary publish that is kept for future use.

        Args:
            task_id: Task ID to wait for
            timeout: Maximum wait time in seconds
            poll_interval: Poll interval in seconds
            queued_timeout: Max seconds to stay in QUEUED before failing (default 120)
            on_progress: Optional callback receiving progress dicts during RUNNING

        Returns:
            Task result string or None if timeout/failed
        """
        redis = await self._ensure_connected()
        start_time = datetime.utcnow()
        stale_heartbeat_checks = 0
        queued_warning_logged = False
        last_progress_log = 0.0  # timestamp of last progress log

        while (datetime.utcnow() - start_time).total_seconds() < timeout:
            task = await self.get_task(task_id)
            if task:
                if task.status == AgentTaskStatus.COMPLETED:
                    return task.result
                elif task.status in (AgentTaskStatus.FAILED, AgentTaskStatus.TIMEOUT, AgentTaskStatus.CANCELLED):
                    error_msg = task.error or f"Task {task.status.value}"
                    raise RuntimeError(error_msg)

                elapsed = (datetime.utcnow() - start_time).total_seconds()

                # --- QUEUED state monitoring ---
                if task.status == AgentTaskStatus.QUEUED:
                    if elapsed >= 30 and not queued_warning_logged:
                        workers = await self.worker_count()
                        queue_len = await self.queue_length()
                        running = await self.running_count()
                        logger.warning(
                            f"Task {task_id} still QUEUED after 30s — "
                            f"workers_alive={workers}, queue_depth={queue_len}, running={running}"
                        )
                        queued_warning_logged = True

                    if elapsed >= queued_timeout:
                        workers = await self.worker_count()
                        queue_len = await self.queue_length()
                        running = await self.running_count()
                        # Cancel the stuck task
                        await self.cancel_task(task_id)
                        if workers == 0:
                            raise RuntimeError(
                                f"Task stuck in QUEUED for {elapsed:.0f}s — no agent workers are alive. "
                                f"Check that the agent_worker process is running (supervisord)."
                            )
                        else:
                            raise RuntimeError(
                                f"Task stuck in QUEUED for {elapsed:.0f}s — "
                                f"{workers} worker(s) alive but all busy "
                                f"(running={running}, queue_depth={queue_len}). "
                                f"Try again later or scale up workers."
                            )

                # --- RUNNING state monitoring ---
                if task.status == AgentTaskStatus.RUNNING:
                    # Log progress every 30s
                    if elapsed - last_progress_log >= 30:
                        progress = await self.get_task_progress(task_id)
                        if progress:
                            tool_calls = progress.get("tool_calls", 0)
                            last_tool = progress.get("last_tool", "")
                            interactions = progress.get("interactions", 0)
                            # Strip MCP prefix for readability
                            short_tool = last_tool.rsplit("__", 1)[-1] if "__" in last_tool else last_tool
                            logger.info(
                                f"Task {task_id} progress: {tool_calls} tool calls, "
                                f"{interactions} interactions, last_tool={short_tool}"
                            )
                            if on_progress:
                                try:
                                    on_progress(progress)
                                except Exception:
                                    pass
                        last_progress_log = elapsed

                    # Check heartbeat (after initial grace period)
                    if elapsed > 60:
                        is_alive = await self.check_heartbeat(task_id)
                        if not is_alive:
                            stale_heartbeat_checks += 1
                            # Require 5 consecutive stale checks (~7.5s) to avoid false positives
                            if stale_heartbeat_checks >= 5:
                                # Final re-check: worker may have submitted results between stale checks
                                final_task = await self.get_task(task_id)
                                if final_task and final_task.status == AgentTaskStatus.COMPLETED:
                                    return final_task.result
                                elif final_task and final_task.status in (
                                    AgentTaskStatus.FAILED,
                                    AgentTaskStatus.TIMEOUT,
                                    AgentTaskStatus.CANCELLED,
                                ):
                                    error_msg = final_task.error or f"Task {final_task.status.value}"
                                    raise RuntimeError(error_msg)

                                logger.warning(
                                    f"Task {task_id} worker appears dead (no heartbeat after {stale_heartbeat_checks} checks). Marking as failed."
                                )
                                task.status = AgentTaskStatus.FAILED
                                task.completed_at = datetime.utcnow()
                                task.error = "Worker heartbeat lost - worker may have crashed"
                                await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                                await redis.srem(self.RUNNING_KEY, task_id)
                                raise RuntimeError(task.error)
                        else:
                            stale_heartbeat_checks = 0

            await asyncio.sleep(poll_interval)

        # Timeout - cancel the task
        await self.cancel_task(task_id)
        raise asyncio.TimeoutError(f"Agent task timed out after {timeout}s")

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a queued or running task."""
        redis = await self._ensure_connected()

        # Remove from queue if still queued
        await redis.lrem(self.QUEUE_KEY, 0, task_id)

        task = await self.get_task(task_id)
        if task and task.status in (AgentTaskStatus.QUEUED, AgentTaskStatus.RUNNING):
            task.status = AgentTaskStatus.CANCELLED
            task.completed_at = datetime.utcnow()
            task.error = "Task cancelled"
            await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
            await redis.srem(self.RUNNING_KEY, task_id)
            # Set cancel flag for worker to detect
            await redis.set(f"{self.CANCEL_PREFIX}{task_id}", "1", ex=3600)
            logger.info(f"Cancelled agent task {task_id}")
            return True
        return False

    async def is_cancelled(self, task_id: str) -> bool:
        """Check if a task has been cancelled."""
        redis = await self._ensure_connected()
        return await redis.exists(f"{self.CANCEL_PREFIX}{task_id}") > 0

    # ==========================================
    # Consumer Methods (Agent Worker)
    # ==========================================

    async def dequeue_task(self, timeout: int = 30) -> AgentTask | None:
        """
        Get the next task from the queue (blocking).

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            AgentTask or None if timeout
        """
        redis = await self._ensure_connected()

        # Blocking pop from list (FIFO)
        result = await redis.blpop(self.QUEUE_KEY, timeout=timeout)

        if result:
            _, task_id = result

            try:
                # Get and update task data
                task_data = await redis.hget(self.TASKS_KEY, task_id)
                if task_data:
                    task = AgentTask.from_dict(json.loads(task_data))
                    task.status = AgentTaskStatus.RUNNING
                    task.worker_id = self._worker_id
                    task.started_at = datetime.utcnow()

                    # Use pipeline for atomic state transition
                    async with redis.pipeline(transaction=True) as pipe:
                        pipe.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                        pipe.sadd(self.RUNNING_KEY, task_id)
                        await pipe.execute()

                    logger.info(f"Worker {self._worker_id} dequeued task {task_id}")
                    return task
                else:
                    logger.warning(f"Task {task_id} dequeued but not found in hash")
                    return None
            except Exception as e:
                logger.error(f"Failed after dequeue for {task_id}: {e}. Re-pushing to queue.")
                try:
                    await redis.lpush(self.QUEUE_KEY, task_id)
                except Exception as re_err:
                    logger.error(f"Failed to re-push task {task_id}: {re_err}")
                return None

        return None

    async def submit_result(
        self,
        task_id: str,
        result: str,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """
        Submit result for a completed task.

        Args:
            task_id: Task ID
            result: Agent output text
            success: Whether execution succeeded
            error: Error message if failed
        """
        redis = await self._ensure_connected()

        task_data = await redis.hget(self.TASKS_KEY, task_id)
        if task_data:
            task = AgentTask.from_dict(json.loads(task_data))

            # Don't overwrite CANCELLED status
            if task.status == AgentTaskStatus.CANCELLED:
                logger.info(
                    f"Task {task_id} was cancelled, not overwriting with {'completed' if success else 'failed'}"
                )
                await redis.srem(self.RUNNING_KEY, task_id)
                return

            task.status = AgentTaskStatus.COMPLETED if success else AgentTaskStatus.FAILED
            task.completed_at = datetime.utcnow()
            task.result = result
            task.error = error

            # Atomic state transition with retry
            for attempt in range(1, 4):
                try:
                    async with redis.pipeline(transaction=True) as pipe:
                        pipe.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                        pipe.srem(self.RUNNING_KEY, task_id)
                        pipe.delete(f"{self.CANCEL_PREFIX}{task_id}")
                        await pipe.execute()
                    break
                except Exception as e:
                    if attempt < 3:
                        logger.warning(f"submit_result attempt {attempt} failed for {task_id}: {e}")
                        await asyncio.sleep(0.5 * attempt)
                        redis = await self._ensure_connected()
                    else:
                        logger.error(f"submit_result failed after 3 attempts: {e}")
                        raise

            # Non-critical notification
            try:
                await redis.publish(f"{self.CHANNEL_KEY}:{task_id}", "done")
            except Exception:
                pass

            logger.info(f"Task {task_id} {'completed' if success else 'failed'}")

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

    async def get_metrics(self) -> dict:
        """Get queue metrics."""
        return {
            "queue_length": await self.queue_length(),
            "running": await self.running_count(),
            "workers_alive": await self.worker_count(),
        }

    async def get_worker_health(self) -> dict:
        """Check if any agent worker is alive using worker-level heartbeats."""
        try:
            redis = await self._ensure_connected()
            running_ids = await redis.smembers(self.RUNNING_KEY)

            # Count worker-level heartbeats (most reliable signal)
            worker_alive_count = await self.worker_count()

            # Also count task-level heartbeats for running tasks
            alive_task_count = 0
            for task_id in running_ids:
                if await self.check_heartbeat(task_id):
                    alive_task_count += 1

            return {
                "workers_alive": worker_alive_count > 0,
                "worker_count": worker_alive_count,
                "running_tasks": len(running_ids),
                "alive_tasks": alive_task_count,
            }
        except Exception as e:
            logger.warning(f"Failed to check worker health: {e}")
            return {
                "workers_alive": False,
                "worker_count": 0,
                "running_tasks": 0,
                "alive_tasks": 0,
                "error": str(e),
            }

    async def cleanup_orphaned_tasks(self) -> int:
        """Clean up all 'running' tasks on startup.

        Called during application startup to clear tasks orphaned by a
        previous container/process that died without completing them.
        Any task marked 'running' at startup is guaranteed orphaned because
        no worker from the previous run is alive to complete it.

        Returns:
            Number of tasks cleaned up
        """
        redis = await self._ensure_connected()
        running_ids = await redis.smembers(self.RUNNING_KEY)
        cleaned = 0

        for task_id in running_ids:
            task = await self.get_task(task_id)
            if task and task.status == AgentTaskStatus.RUNNING:
                task.status = AgentTaskStatus.FAILED
                task.completed_at = datetime.utcnow()
                task.error = "Orphaned task cleaned up on startup — previous worker died"
                await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                await redis.srem(self.RUNNING_KEY, task_id)
                await redis.delete(f"{self.HEARTBEAT_PREFIX}{task_id}")
                cleaned += 1
                logger.warning(f"Cleaned orphaned task {task_id} (started={task.started_at})")

        if cleaned:
            logger.info(f"Startup cleanup: cleared {cleaned} orphaned running tasks")
        return cleaned

    async def flush_queue(self) -> dict:
        """Flush the entire agent queue — cancel queued tasks, fail running ones.

        Returns summary of what was cleaned.
        """
        redis = await self._ensure_connected()
        now = datetime.utcnow()
        queued_cancelled = 0
        running_failed = 0

        # Cancel all queued tasks
        while True:
            task_id = await redis.lpop(self.QUEUE_KEY)
            if not task_id:
                break
            task = await self.get_task(task_id)
            if task:
                task.status = AgentTaskStatus.CANCELLED
                task.completed_at = now
                task.error = "Queue flushed by admin"
                await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                queued_cancelled += 1

        # Fail all running tasks
        running_ids = await redis.smembers(self.RUNNING_KEY)
        for task_id in running_ids:
            task = await self.get_task(task_id)
            if task:
                task.status = AgentTaskStatus.FAILED
                task.completed_at = now
                task.error = "Queue flushed by admin"
                await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
            await redis.srem(self.RUNNING_KEY, task_id)
            await redis.delete(f"{self.HEARTBEAT_PREFIX}{task_id}")
            running_failed += 1

        logger.info(f"Queue flushed: {queued_cancelled} queued cancelled, {running_failed} running failed")
        return {
            "queued_cancelled": queued_cancelled,
            "running_failed": running_failed,
        }

    async def cleanup_stale_tasks(self, max_age_minutes: int = 45) -> int:
        """Clean up tasks running too long and orphaned queued tasks.

        Default 45 min, provides buffer above 30-min agent timeout.
        Also detects tasks in QUEUED status that are missing from the queue list.
        """
        redis = await self._ensure_connected()
        cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        cleaned = 0

        # Clean up stale running tasks
        running_ids = await redis.smembers(self.RUNNING_KEY)
        for task_id in running_ids:
            task = await self.get_task(task_id)
            if task and task.started_at and task.started_at < cutoff:
                task.status = AgentTaskStatus.TIMEOUT
                task.completed_at = datetime.utcnow()
                task.error = f"Task timed out after {max_age_minutes} minutes (stale cleanup)"

                await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                await redis.srem(self.RUNNING_KEY, task_id)
                # Also clean up heartbeat key
                await redis.delete(f"{self.HEARTBEAT_PREFIX}{task_id}")
                cleaned += 1
                logger.warning(f"Cleaned up stale task {task_id}")

        # Detect orphaned queued tasks (in QUEUED status but missing from queue list)
        all_tasks = await redis.hgetall(self.TASKS_KEY)
        queue_members = await redis.lrange(self.QUEUE_KEY, 0, -1)
        queue_set = set(queue_members)

        for task_id, task_data_str in all_tasks.items():
            try:
                task_data = json.loads(task_data_str)
                if task_data.get("status") == "queued" and task_id not in queue_set:
                    created = task_data.get("created_at")
                    if created:
                        created_dt = datetime.fromisoformat(created)
                        age_minutes = (datetime.utcnow() - created_dt).total_seconds() / 60
                        if age_minutes > 5:  # Grace period of 5 minutes
                            task = AgentTask.from_dict(task_data)
                            task.status = AgentTaskStatus.FAILED
                            task.completed_at = datetime.utcnow()
                            task.error = "Orphaned task: found in QUEUED state but missing from queue list"
                            await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                            cleaned += 1
                            logger.warning(f"Cleaned orphaned queued task {task_id} (age: {age_minutes:.0f}m)")
            except (json.JSONDecodeError, ValueError):
                continue

        return cleaned

    async def cleanup_completed_tasks(self, max_age_hours: int = 24) -> int:
        """Remove completed/failed/cancelled/timeout tasks older than max_age_hours from Redis."""
        redis = await self._ensure_connected()
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        removed = 0

        all_tasks = await redis.hgetall(self.TASKS_KEY)
        for task_id, task_data_str in all_tasks.items():
            try:
                task_data = json.loads(task_data_str)
                status = task_data.get("status")
                if status in ("completed", "failed", "timeout", "cancelled"):
                    completed_at = task_data.get("completed_at")
                    if completed_at:
                        completed_dt = datetime.fromisoformat(completed_at)
                        if completed_dt < cutoff:
                            await redis.hdel(self.TASKS_KEY, task_id)
                            await redis.delete(f"{self.HEARTBEAT_PREFIX}{task_id}")
                            removed += 1
            except (json.JSONDecodeError, ValueError):
                continue

        if removed:
            logger.info(f"Cleaned up {removed} completed tasks older than {max_age_hours}h")
        return removed

    async def start_cleanup_loop(self, interval_seconds: int = 300):
        """Run cleanup_stale_tasks() and cleanup_completed_tasks() periodically.

        Args:
            interval_seconds: How often to run cleanup (default: 5 minutes)
        """
        logger.info(f"Starting agent queue cleanup loop (every {interval_seconds}s)")
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                cleaned = await self.cleanup_stale_tasks()
                if cleaned > 0:
                    logger.info(f"Cleanup loop: cleaned {cleaned} stale agent tasks")
                removed = await self.cleanup_completed_tasks(max_age_hours=24)
                if removed > 0:
                    logger.info(f"Cleanup loop: removed {removed} old completed tasks")
            except asyncio.CancelledError:
                logger.info("Cleanup loop cancelled")
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}", exc_info=True)
                await asyncio.sleep(30)  # Back off on error


# Singleton instance
_queue_instance: AgentQueue | None = None


def get_agent_queue() -> AgentQueue:
    """Get or create the singleton AgentQueue instance."""
    global _queue_instance
    if _queue_instance is None:
        _queue_instance = AgentQueue()
    return _queue_instance


# Check if agent queue should be used
def should_use_agent_queue() -> bool:
    """Check if Redis is available and agent queue mode is enabled."""
    if not REDIS_AVAILABLE:
        return False
    # Enable by default if Redis URL is set
    redis_url = os.environ.get("REDIS_URL", "")
    use_queue = os.environ.get("USE_AGENT_QUEUE", "true").lower() == "true"
    return bool(redis_url) and use_queue
