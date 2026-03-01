"""
Unified Browser Resource Pool.

Provides a single point of control for all browser operations,
ensuring no more than MAX_BROWSER_INSTANCES run concurrently.

This replaces the fragmented resource management (QUEUE_MANAGER + ResourceManager)
with a single, robust queue that limits ALL browser operations to a configurable
maximum (default: 5).

Usage:
    from services.browser_pool import get_browser_pool, OperationType

    pool = await get_browser_pool()

    # Context manager (recommended)
    async with pool.browser_slot(
        request_id="run_123",
        operation_type=OperationType.TEST_RUN,
        description="Test: login spec"
    ) as acquired:
        if acquired:
            # Run browser operation
            pass

    # Manual acquire/release
    if await pool.acquire("run_123", OperationType.TEST_RUN):
        try:
            # Run browser operation
            pass
        finally:
            await pool.release("run_123")

Configuration:
    MAX_BROWSER_INSTANCES: Maximum concurrent browsers (default: 5)
    BROWSER_SLOT_TIMEOUT: Max wait time in seconds (default: 3600 = 1 hour)
"""

import asyncio
import logging
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

try:
    import redis.asyncio as redis
except ImportError:
    redis = None  # Handle missing dependency gracefully

logger = logging.getLogger(__name__)


class OperationType(str, Enum):
    """Types of operations that require browser resources."""

    TEST_RUN = "test_run"
    EXPLORATION = "exploration"
    AGENT = "agent"
    PRD = "prd"
    AUTOPILOT = "autopilot"
    COVERAGE = "coverage"


class SlotStatus(str, Enum):
    """Status of a browser slot request."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BrowserSlot:
    """Tracks a single browser slot request."""

    request_id: str
    operation_type: OperationType
    description: str = ""
    status: SlotStatus = SlotStatus.QUEUED
    queued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    max_operation_duration: int | None = None  # seconds; None = use global default


class AbstractBrowserPool:
    """Interface for browser resource pools."""

    async def update_max_browsers(self, new_max: int): ...
    async def acquire(
        self,
        request_id: str,
        operation_type: OperationType,
        description: str = "",
        timeout: float | None = None,
        max_operation_duration: int | None = None,
    ) -> bool: ...
    async def release(self, request_id: str, success: bool = True, error: str | None = None): ...
    async def get_queue_position(self, request_id: str) -> int | None: ...
    async def is_running(self, request_id: str) -> bool: ...
    def get_slot(self, request_id: str) -> BrowserSlot | None: ...
    async def get_status(self) -> dict: ...
    async def cleanup_stale(self, max_age_minutes: int = 60) -> list[str]: ...
    async def cleanup_old_completed(self, max_age_hours: int = 24) -> int: ...
    async def get_recent_slots(self, limit: int = 50) -> list[dict]: ...

    @asynccontextmanager
    async def browser_slot(
        self,
        request_id: str,
        operation_type: OperationType,
        description: str = "",
        timeout: float | None = None,
        max_operation_duration: int | None = None,
    ):
        """
        Context manager for browser slot acquisition.

        Automatically releases the slot on exit, even if an exception occurs.
        """
        acquired = False
        try:
            acquired = await self.acquire(request_id, operation_type, description, timeout, max_operation_duration)
            yield acquired
        except Exception as e:
            if acquired:
                await self.release(request_id, success=False, error=str(e))
            raise
        else:
            if acquired:
                await self.release(request_id, success=True)


class InMemoryBrowserPool(AbstractBrowserPool):
    """
    Singleton pool managing all browser instances.

    Features:
    - Hard limit on concurrent browsers (default: 5)
    - FIFO queue for waiting requests
    - Automatic cleanup on errors via context manager
    - Queue position tracking
    - Crash recovery via stale slot cleanup
    - Operation type tracking for monitoring

    All browser operations (test runs, explorations, agents, PRD processing)
    must acquire a slot from this pool before starting.
    """

    _instance: Optional["InMemoryBrowserPool"] = None
    _lock: asyncio.Lock = None

    def __init__(self, max_browsers: int = None):
        """Initialize the pool (use get_instance() for singleton)."""
        if max_browsers is None:
            from orchestrator.config import settings as app_settings

            max_browsers = app_settings.max_browser_instances
        self.max_browsers = max_browsers
        self._slots: dict[str, BrowserSlot] = {}
        self._queue: list[str] = []  # Request IDs in queue order
        self._running: set = set()  # Currently running request IDs
        self._initialized = False
        self._slots_lock: asyncio.Lock | None = None
        self._waiters: deque = deque()  # deque of (request_id, asyncio.Event) for FIFO ordering

    @classmethod
    async def get_instance(cls, max_browsers: int = None) -> "InMemoryBrowserPool":
        """Get or create singleton instance.

        Args:
            max_browsers: Optional override for max browsers (used on first init).
                         If pool already exists, use update_max_browsers() instead.
        """
        if cls._lock is None:
            cls._lock = asyncio.Lock()

        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls(max_browsers=max_browsers)
                await cls._instance._initialize()
            return cls._instance

    @classmethod
    def get_instance_sync(cls) -> Optional["InMemoryBrowserPool"]:
        """Get existing instance synchronously (may be None if not initialized)."""
        return cls._instance

    async def _initialize(self):
        """Initialize internal state."""
        if self._initialized:
            return

        self._slots_lock = asyncio.Lock()
        self._initialized = True

        logger.info(f"InMemoryBrowserPool initialized: max_browsers={self.max_browsers}")

    async def update_max_browsers(self, new_max: int):
        """
        Update the maximum number of concurrent browsers.

        This is called when the UI parallelism setting changes.
        The change takes effect for new acquisitions - they will check
        against max_browsers before trying to acquire the semaphore.

        Note: Currently running operations will continue until they release
        their slots. If reducing max_browsers below current running count,
        new acquisitions will wait until enough slots are released.

        Args:
            new_max: New maximum concurrent browsers (must be >= 1)
        """
        if new_max < 1:
            logger.warning(f"Invalid max_browsers value: {new_max}, ignoring")
            return

        if new_max == self.max_browsers:
            return

        old_max = self.max_browsers
        self.max_browsers = new_max

        logger.info(
            f"InMemoryBrowserPool updated: max_browsers {old_max} -> {new_max} "
            f"(currently running: {len(self._running)})"
        )

    async def acquire(
        self,
        request_id: str,
        operation_type: OperationType,
        description: str = "",
        timeout: float | None = None,
        max_operation_duration: int | None = None,
    ) -> bool:
        """
        Acquire a browser slot. Blocks until slot available or timeout.
        Uses explicit FIFO ordering via a deque of Events.

        Args:
            request_id: Unique identifier for this request
            operation_type: Type of operation (test_run, exploration, etc.)
            description: Human-readable description
            timeout: Max seconds to wait (None = wait forever, use BROWSER_SLOT_TIMEOUT env)

        Returns:
            True if slot acquired, False if timeout/cancelled
        """
        if timeout is None:
            from orchestrator.config import settings as app_settings

            timeout = float(app_settings.browser_slot_timeout)

        slot = BrowserSlot(
            request_id=request_id,
            operation_type=operation_type,
            description=description,
            max_operation_duration=max_operation_duration,
        )

        async with self._slots_lock:
            self._slots[request_id] = slot
            self._queue.append(request_id)

            # Check if we can acquire immediately
            if len(self._running) < self.max_browsers and self._queue[0] == request_id:
                self._queue.remove(request_id)
                self._running.add(request_id)
                slot.status = SlotStatus.RUNNING
                slot.started_at = datetime.now(timezone.utc)
                logger.info(
                    f"[{request_id}] Acquired browser slot immediately "
                    f"(type={operation_type.value}, "
                    f"running={len(self._running)}/{self.max_browsers})"
                )
                return True

        # Need to wait - create event and add to waiters deque
        event = asyncio.Event()
        self._waiters.append((request_id, event))

        logger.info(
            f"[{request_id}] Queued for browser slot "
            f"(type={operation_type.value}, position={len(self._queue)}, "
            f"running={len(self._running)}/{self.max_browsers})"
        )

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            # Event was set by _notify_next_waiter - slot is acquired
            logger.info(
                f"[{request_id}] Acquired browser slot "
                f"(type={operation_type.value}, "
                f"running={len(self._running)}/{self.max_browsers})"
            )
            return True

        except asyncio.TimeoutError:
            # Remove from waiters and queue atomically under lock
            async with self._slots_lock:
                self._waiters = deque((r, e) for r, e in self._waiters if r != request_id)
                if request_id in self._queue:
                    self._queue.remove(request_id)
                slot = self._slots.get(request_id)
                if slot:
                    slot.status = SlotStatus.CANCELLED
                    slot.error = f"Timeout waiting for browser slot ({timeout}s)"
                    slot.completed_at = datetime.now(timezone.utc)
            logger.warning(f"[{request_id}] Timeout waiting for browser slot after {timeout}s")
            return False

        except asyncio.CancelledError:
            async with self._slots_lock:
                self._waiters = deque((r, e) for r, e in self._waiters if r != request_id)
                if request_id in self._queue:
                    self._queue.remove(request_id)
                slot = self._slots.get(request_id)
                if slot:
                    slot.status = SlotStatus.CANCELLED
                    slot.error = "Request cancelled"
                    slot.completed_at = datetime.now(timezone.utc)
            logger.info(f"[{request_id}] Cancelled while waiting for browser slot")
            raise

    async def release(self, request_id: str, success: bool = True, error: str | None = None):
        """
        Release a browser slot.

        Args:
            request_id: The request ID that was acquired
            success: Whether the operation succeeded
            error: Optional error message if failed
        """
        async with self._slots_lock:
            slot = self._slots.get(request_id)
            if not slot:
                logger.warning(f"[{request_id}] Unknown request ID in release")
                return

            slot.completed_at = datetime.now(timezone.utc)
            slot.status = SlotStatus.COMPLETED if success else SlotStatus.FAILED
            slot.error = error

            was_running = request_id in self._running
            if was_running:
                self._running.discard(request_id)

        if was_running:
            # Wake the next waiter in FIFO order
            await self._notify_next_waiter()

        logger.info(
            f"[{request_id}] Released browser slot "
            f"(success={success}, running={len(self._running)}/{self.max_browsers})"
        )

    async def _notify_next_waiter(self):
        """Wake the next eligible waiter in FIFO order."""
        async with self._slots_lock:
            while self._waiters and len(self._running) < self.max_browsers:
                req_id, event = self._waiters.popleft()
                # Check the request is still in queue (not timed out/cancelled)
                if req_id in self._queue:
                    self._queue.remove(req_id)
                    self._running.add(req_id)
                    slot = self._slots.get(req_id)
                    if slot:
                        slot.status = SlotStatus.RUNNING
                        slot.started_at = datetime.now(timezone.utc)
                    event.set()
                    return
                # If request was already removed (timeout/cancel), skip to next

    @asynccontextmanager
    async def browser_slot(
        self,
        request_id: str,
        operation_type: OperationType,
        description: str = "",
        timeout: float | None = None,
        max_operation_duration: int | None = None,
    ):
        """
        Context manager for browser slot acquisition.

        Automatically releases the slot on exit, even if an exception occurs.

        Yields:
            True if slot was acquired, False if timeout
        """
        # Inherited from AbstractBrowserPool but kept for compatibility/docs
        async with super().browser_slot(
            request_id, operation_type, description, timeout, max_operation_duration
        ) as acquired:
            yield acquired

    async def get_queue_position(self, request_id: str) -> int | None:
        """
        Get position in queue (1-based).

        Returns:
            Position in queue (1 = next), or None if not queued
        """
        try:
            return self._queue.index(request_id) + 1
        except ValueError:
            return None

    async def is_running(self, request_id: str) -> bool:
        """Check if a request is currently running."""
        return request_id in self._running

    def get_slot(self, request_id: str) -> BrowserSlot | None:
        """Get slot info for a request."""
        return self._slots.get(request_id)

    async def get_status(self) -> dict:
        """
        Get current pool status.

        Returns:
            Dictionary with:
            - max_browsers: Maximum concurrent browsers
            - running: Number of browsers currently running
            - queued: Number of requests waiting in queue
            - available: Number of slots available immediately
            - running_requests: List of running request IDs
            - queued_requests: List of queued request IDs
            - by_type: Breakdown of running requests by operation type
        """
        by_type = {op_type.value: 0 for op_type in OperationType}
        for request_id in self._running:
            slot = self._slots.get(request_id)
            if slot:
                by_type[slot.operation_type.value] += 1

        return {
            "max_browsers": self.max_browsers,
            "running": len(self._running),
            "queued": len(self._queue),
            "available": max(0, self.max_browsers - len(self._running)),
            "running_requests": list(self._running),
            "queued_requests": list(self._queue),
            "by_type": by_type,
        }

    async def cleanup_stale(self, max_age_minutes: int = 60) -> list[str]:
        """
        Clean up slots that have been running too long (likely crashed).

        Uses per-slot max_operation_duration if set, otherwise falls back
        to max_age_minutes * 60 seconds.

        This should be called periodically (e.g., on startup, every 10 minutes).

        Args:
            max_age_minutes: Default maximum age in minutes before a slot is considered stale

        Returns:
            List of request IDs that were cleaned up
        """
        now = datetime.now(timezone.utc)
        stale_ids = []

        async with self._slots_lock:
            for request_id, slot in list(self._slots.items()):
                if slot.status != SlotStatus.RUNNING or not slot.started_at:
                    continue
                elapsed = (now - slot.started_at).total_seconds()
                limit = slot.max_operation_duration if slot.max_operation_duration else max_age_minutes * 60
                if elapsed > limit:
                    stale_ids.append(request_id)

        for request_id in stale_ids:
            slot = self._slots.get(request_id)
            elapsed = int((now - slot.started_at).total_seconds()) if slot and slot.started_at else 0
            limit = slot.max_operation_duration if slot and slot.max_operation_duration else max_age_minutes * 60
            logger.warning(f"[{request_id}] Operation timeout: ran {elapsed}s, limit {limit}s")
            await self.release(request_id, success=False, error=f"Operation timeout after {elapsed}s (limit: {limit}s)")

        if stale_ids:
            logger.info(f"Cleaned up {len(stale_ids)} timed-out browser slots")

        return stale_ids

    async def cleanup_old_completed(self, max_age_hours: int = 24) -> int:
        """
        Remove completed slot records older than max_age_hours.

        This prevents memory growth from accumulating slot records.

        Args:
            max_age_hours: Maximum age in hours for completed slots

        Returns:
            Number of slots cleaned up
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        removed_count = 0

        async with self._slots_lock:
            to_remove = []
            for request_id, slot in self._slots.items():
                if (
                    slot.status in (SlotStatus.COMPLETED, SlotStatus.FAILED, SlotStatus.CANCELLED)
                    and slot.completed_at
                    and slot.completed_at < cutoff
                ):
                    to_remove.append(request_id)

            for request_id in to_remove:
                del self._slots[request_id]
                removed_count += 1

        if removed_count > 0:
            logger.debug(f"Removed {removed_count} old completed slot records")

        return removed_count

    async def get_recent_slots(self, limit: int = 50) -> list[dict]:
        """
        Get recent slot activity for monitoring.

        Args:
            limit: Maximum number of slots to return

        Returns:
            List of slot info dictionaries, sorted by most recent first
        """
        slots = []
        for _request_id, slot in self._slots.items():
            slots.append(
                {
                    "request_id": slot.request_id,
                    "operation_type": slot.operation_type.value,
                    "description": slot.description,
                    "status": slot.status.value,
                    "queued_at": slot.queued_at.isoformat() if slot.queued_at else None,
                    "started_at": slot.started_at.isoformat() if slot.started_at else None,
                    "completed_at": slot.completed_at.isoformat() if slot.completed_at else None,
                    "error": slot.error,
                    "max_operation_duration": slot.max_operation_duration,
                    "wait_time_seconds": (
                        (slot.started_at - slot.queued_at).total_seconds()
                        if slot.started_at and slot.queued_at
                        else None
                    ),
                    "run_time_seconds": (
                        (slot.completed_at - slot.started_at).total_seconds()
                        if slot.completed_at and slot.started_at
                        else None
                    ),
                }
            )

        # Sort by most recent activity first
        slots.sort(key=lambda s: s["completed_at"] or s["started_at"] or s["queued_at"] or "", reverse=True)

        return slots[:limit]


class RedisBrowserResourcePool(AbstractBrowserPool):
    """
    Redis-backed browser resource pool for horizontal scaling.

    Uses Redis List for queue and Set for running instances.
    """

    _instance: Optional["RedisBrowserResourcePool"] = None
    _lock: asyncio.Lock = None

    def __init__(self, redis_url: str, max_browsers: int = None):
        self.redis_url = redis_url
        if max_browsers is None:
            from orchestrator.config import settings as app_settings

            max_browsers = app_settings.max_browser_instances
        self.max_browsers = max_browsers
        self.redis: redis.Redis | None = None
        self._local_slots: dict[str, BrowserSlot] = {}  # Local cache of own slots
        self._key_prefix = "browser_pool"
        self._last_ping_time: float = 0.0
        self._ping_interval: float = 5.0

    @classmethod
    async def get_instance(cls, redis_url: str, max_browsers: int = None) -> "RedisBrowserResourcePool":
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls(redis_url, max_browsers)
                await cls._instance._initialize()
            return cls._instance

    async def _initialize(self):
        if not self.redis:
            self.redis = redis.from_url(
                self.redis_url,
                decode_responses=True,
                retry_on_error=[ConnectionError, TimeoutError],
                health_check_interval=30,
            )
            try:
                await self.redis.ping()
                self._last_ping_time = time.monotonic()
                logger.info(f"RedisBrowserResourcePool connected to {self.redis_url}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise

    async def _ensure_connected(self) -> redis.Redis:
        """Ensure Redis is connected and return client, with auto-reconnect."""
        now = time.monotonic()
        if self.redis is not None and (now - self._last_ping_time) < self._ping_interval:
            return self.redis

        if self.redis is not None:
            try:
                await asyncio.wait_for(self.redis.ping(), timeout=2.0)
                self._last_ping_time = now
                return self.redis
            except Exception:
                logger.warning("RedisBrowserResourcePool connection lost, reconnecting...")
                try:
                    await self.redis.close()
                except Exception:
                    pass
                self.redis = None

        await self._initialize()
        self._last_ping_time = time.monotonic()
        return self.redis

    async def update_max_browsers(self, new_max: int):
        self.max_browsers = new_max
        # In Redis, we just update local config. Actual limit logic checks this value.
        # Ideally, this should be stored in Redis too for global config, but env var/deployment usually controls it.
        logger.info(f"RedisBrowserResourcePool updated max_browsers to {new_max}")

    async def acquire(
        self,
        request_id: str,
        operation_type: OperationType,
        description: str = "",
        timeout: float | None = None,
        max_operation_duration: int | None = None,
    ) -> bool:
        if timeout is None:
            from orchestrator.config import settings as app_settings

            timeout = float(app_settings.browser_slot_timeout)

        r = await self._ensure_connected()

        # Create local slot record
        slot = BrowserSlot(
            request_id=request_id,
            operation_type=operation_type,
            description=description,
            max_operation_duration=max_operation_duration,
        )
        self._local_slots[request_id] = slot

        # Push to Redis Queue
        await r.rpush(f"{self._key_prefix}:queue", request_id)

        start_time = datetime.now(timezone.utc)

        logger.info(f"[{request_id}] Queued in Redis (timeout={timeout}s)")

        try:
            # Polling loop (simple but effective for low concurrency)
            # A more advanced version would use BLPOP on a notify list, but we need condition (queue head AND capacity)
            while (datetime.now(timezone.utc) - start_time).total_seconds() < timeout:
                # 1. Check if we are at the head of the queue
                # 2. Check if capacity available

                # Transactional check/acquire
                r = await self._ensure_connected()
                async with r.pipeline(transaction=True) as pipe:
                    while True:
                        try:
                            # Watch keys
                            await pipe.watch(f"{self._key_prefix}:queue", f"{self._key_prefix}:running")

                            queue = await pipe.lrange(f"{self._key_prefix}:queue", 0, 0)
                            running_count = await pipe.scard(f"{self._key_prefix}:running")

                            if not queue or queue[0] != request_id:
                                # Not at head, wait
                                await pipe.unwatch()
                                break

                            if running_count >= self.max_browsers:
                                # No capacity, wait
                                await pipe.unwatch()
                                break

                            # Try to acquire
                            pipe.multi()
                            pipe.lpop(f"{self._key_prefix}:queue")
                            pipe.sadd(f"{self._key_prefix}:running", request_id)
                            # Add metadata
                            pipe.hset(
                                f"{self._key_prefix}:info:{request_id}",
                                mapping={
                                    "type": operation_type.value,
                                    "desc": description,
                                    "start": datetime.now(timezone.utc).isoformat(),
                                    "max_dur": str(max_operation_duration or ""),
                                },
                            )
                            # Set expiration on info to avoid zombies if crash
                            pipe.expire(f"{self._key_prefix}:info:{request_id}", 86400)

                            await pipe.execute()

                            # Success!
                            slot.status = SlotStatus.RUNNING
                            slot.started_at = datetime.now(timezone.utc)
                            logger.info(f"[{request_id}] Acquired Redis slot")
                            return True

                        except redis.WatchError:
                            # Retry immediately
                            continue
                        except Exception as e:
                            logger.error(f"Redis acquire mechanism error: {e}")
                            await pipe.unwatch()
                            break

                await asyncio.sleep(0.5)  # Poll interval

            raise asyncio.TimeoutError()

        except asyncio.TimeoutError:
            slot.status = SlotStatus.CANCELLED
            slot.error = f"Timeout waiting for slot ({timeout}s)"
            # Cleanup from queue
            r = await self._ensure_connected()
            await r.lrem(f"{self._key_prefix}:queue", 0, request_id)
            logger.warning(f"[{request_id}] Redis acquire timeout")
            return False

        except asyncio.CancelledError:
            slot.status = SlotStatus.CANCELLED
            slot.error = "Request cancelled"
            r = await self._ensure_connected()
            await r.lrem(f"{self._key_prefix}:queue", 0, request_id)
            raise

    async def release(self, request_id: str, success: bool = True, error: str | None = None):
        slot = self._local_slots.get(request_id)
        if slot:
            slot.completed_at = datetime.now(timezone.utc)
            slot.status = SlotStatus.COMPLETED if success else SlotStatus.FAILED
            slot.error = error

        r = await self._ensure_connected()
        await r.srem(f"{self._key_prefix}:running", request_id)
        await r.delete(f"{self._key_prefix}:info:{request_id}")
        logger.info(f"[{request_id}] Released Redis slot")

    async def get_queue_position(self, request_id: str) -> int | None:
        """Get the queues position for a request (1-indexed)."""
        r = await self._ensure_connected()
        queue = await r.lrange(f"{self._key_prefix}:queue", 0, -1)
        for i, req in enumerate(queue):
            if req == request_id:
                return i + 1
        return None

    async def is_running(self, request_id: str) -> bool:
        r = await self._ensure_connected()
        return await r.sismember(f"{self._key_prefix}:running", request_id)

    def get_slot(self, request_id: str) -> BrowserSlot | None:
        return self._local_slots.get(request_id)

    async def get_status(self) -> dict:
        r = await self._ensure_connected()
        running_set = await r.smembers(f"{self._key_prefix}:running")
        queue = await r.lrange(f"{self._key_prefix}:queue", 0, -1)

        running_count = len(running_set)
        queue_len = len(queue)

        # Get types for running requests
        by_type = {}
        # This part is a bit expensive (N lookups). Limit to logging/debug usage.
        # Use pipeline for efficiency.
        if running_count > 0:
            async with r.pipeline() as pipe:
                for req_id in running_set:
                    pipe.hget(f"{self._key_prefix}:info:{req_id}", "type")
                types = await pipe.execute()
                for t in types:
                    if t:
                        by_type[t] = by_type.get(t, 0) + 1

        return {
            "max_browsers": self.max_browsers,
            "running": running_count,
            "queued": queue_len,
            "available": max(0, self.max_browsers - running_count),
            "running_requests": list(running_set),
            "queued_requests": queue,
            "by_type": by_type,
        }

    async def cleanup_stale(self, max_age_minutes: int = 60) -> list[str]:
        """Clean up stale running slots from Redis."""
        r = await self._ensure_connected()
        now = datetime.now(timezone.utc)
        stale_ids = []

        running_set = await r.smembers(f"{self._key_prefix}:running")

        for request_id in running_set:
            info = await r.hgetall(f"{self._key_prefix}:info:{request_id}")
            if not info:
                # No info hash means the slot is orphaned (info expired or was never set)
                stale_ids.append(request_id)
                continue

            start_str = info.get("start")
            if start_str:
                try:
                    start_time = datetime.fromisoformat(start_str)
                    if start_time.tzinfo is None:
                        start_time = start_time.replace(tzinfo=timezone.utc)
                    elapsed = (now - start_time).total_seconds()
                    max_dur_str = info.get("max_dur", "")
                    limit = int(max_dur_str) if max_dur_str else max_age_minutes * 60
                    if elapsed > limit:
                        stale_ids.append(request_id)
                except (ValueError, TypeError):
                    stale_ids.append(request_id)
            else:
                stale_ids.append(request_id)

        for request_id in stale_ids:
            await r.srem(f"{self._key_prefix}:running", request_id)
            await r.delete(f"{self._key_prefix}:info:{request_id}")
            # Update local slot cache if present
            slot = self._local_slots.get(request_id)
            if slot:
                slot.status = SlotStatus.FAILED
                slot.completed_at = now
                slot.error = "Stale slot cleaned up"
            logger.warning(f"[{request_id}] Cleaned up stale Redis browser slot")

        if stale_ids:
            logger.info(f"Cleaned up {len(stale_ids)} stale Redis browser slots")

        return stale_ids

    async def cleanup_old_completed(self, max_age_hours: int = 24) -> int:
        """Remove old completed local slot records to prevent memory growth."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        removed = 0
        to_remove = []
        for request_id, slot in self._local_slots.items():
            if (
                slot.status in (SlotStatus.COMPLETED, SlotStatus.FAILED, SlotStatus.CANCELLED)
                and slot.completed_at
                and slot.completed_at < cutoff
            ):
                to_remove.append(request_id)
        for request_id in to_remove:
            del self._local_slots[request_id]
            removed += 1
        if removed > 0:
            logger.debug(f"Removed {removed} old completed Redis browser slot records")
        return removed

    async def get_recent_slots(self, limit: int = 50) -> list[dict]:
        """
        Get recent slot activity from local cache.
        TODO: Implement global Redis-based history if needed.
        """
        slots = []
        for _request_id, slot in self._local_slots.items():
            slots.append(
                {
                    "request_id": slot.request_id,
                    "operation_type": slot.operation_type.value,
                    "description": slot.description,
                    "status": slot.status.value,
                    "queued_at": slot.queued_at.isoformat() if slot.queued_at else None,
                    "started_at": slot.started_at.isoformat() if slot.started_at else None,
                    "completed_at": slot.completed_at.isoformat() if slot.completed_at else None,
                    "error": slot.error,
                    "max_operation_duration": slot.max_operation_duration,
                    "wait_time_seconds": (
                        (slot.started_at - slot.queued_at).total_seconds()
                        if slot.started_at and slot.queued_at
                        else None
                    ),
                    "run_time_seconds": (
                        (slot.completed_at - slot.started_at).total_seconds()
                        if slot.completed_at and slot.started_at
                        else None
                    ),
                }
            )

        # Sort by most recent activity first
        slots.sort(key=lambda s: s["completed_at"] or s["started_at"] or s["queued_at"] or "", reverse=True)

        return slots[:limit]


# Factory
_global_pool: AbstractBrowserPool | None = None


async def get_browser_pool(max_browsers: int = None) -> AbstractBrowserPool:
    """Get the singleton browser pool instance (InMemory or Redis)."""
    global _global_pool

    if _global_pool:
        # Update max if provided
        if max_browsers:
            await _global_pool.update_max_browsers(max_browsers)
        return _global_pool

    # Check configuration
    from orchestrator.config import settings as app_settings

    redis_url = app_settings.redis_url
    pool_type = os.environ.get("BROWSER_POOL_TYPE", "in_memory")

    if pool_type == "redis" and redis_url:
        try:
            if redis is None:
                raise ImportError("redis package not installed")
            _global_pool = await RedisBrowserResourcePool.get_instance(redis_url, max_browsers)
            logger.info("Using RedisBrowserResourcePool")
        except Exception as e:
            logger.error(f"Failed to init Redis pool: {e}. Falling back to InMemory.")
            _global_pool = await InMemoryBrowserPool.get_instance(max_browsers)
    else:
        _global_pool = await InMemoryBrowserPool.get_instance(max_browsers)
        logger.info("Using InMemoryBrowserPool")

    return _global_pool
