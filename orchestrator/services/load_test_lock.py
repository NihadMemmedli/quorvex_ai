"""
Load Test Exclusive Lock

Ensures only one load test runs at a time and pauses browser operations
(test runs, explorations, agents, PRD processing) during active load tests.

Uses Redis with in-memory fallback for dev mode.
"""

import json
import logging
import threading
import time

from fastapi import HTTPException

logger = logging.getLogger(__name__)

REDIS_KEY = "playwright:loadtest:active"
LOCK_TTL_SECONDS = 7200  # 2 hours - auto-expire on crash

# In-memory fallback for non-Redis environments
_local_lock = threading.Lock()
_local_active: dict | None = None


def _get_redis():
    """Get Redis client if available."""
    try:
        from orchestrator.services.k6_queue import get_k6_queue

        queue = get_k6_queue()
        if queue._redis:
            return queue._redis
    except Exception:
        pass
    return None


async def acquire(run_id: str, vus: int | None = None, duration: str | None = None) -> bool:
    """Acquire exclusive load test lock. Returns True if acquired, False if already held."""
    global _local_active

    metadata = json.dumps(
        {
            "run_id": run_id,
            "started_at": time.time(),
            "vus": vus,
            "duration": duration,
        }
    )

    redis = _get_redis()
    if redis:
        try:
            # SET NX = only set if not exists
            acquired = await redis.set(REDIS_KEY, metadata, nx=True, ex=LOCK_TTL_SECONDS)
            return bool(acquired)
        except Exception as e:
            logger.warning(f"Redis lock acquire failed, using local fallback: {e}")

    # In-memory fallback
    with _local_lock:
        if _local_active is not None:
            return False
        _local_active = json.loads(metadata)
        return True


async def release(run_id: str) -> bool:
    """Release the load test lock. Only releases if held by the given run_id."""
    global _local_active

    redis = _get_redis()
    if redis:
        try:
            current = await redis.get(REDIS_KEY)
            if current:
                data = json.loads(current)
                if data.get("run_id") == run_id:
                    await redis.delete(REDIS_KEY)
                    return True
            return False
        except Exception as e:
            logger.warning(f"Redis lock release failed, using local fallback: {e}")

    # In-memory fallback
    with _local_lock:
        if _local_active and _local_active.get("run_id") == run_id:
            _local_active = None
            return True
        return False


def release_sync(run_id: str) -> bool:
    """Synchronous lock release for use in thread pool executors (no event loop needed)."""
    global _local_active

    with _local_lock:
        if _local_active and _local_active.get("run_id") == run_id:
            _local_active = None
            logger.info(f"Load test lock released synchronously for run {run_id}")
            return True
    return False


async def force_release() -> dict | None:
    """Force-release the load test lock regardless of run_id ownership.

    Returns the lock info that was cleared, or None if no lock was held.
    Use this as a last resort when the lock is stuck with no associated running process.
    """
    global _local_active

    released_info = None

    redis = _get_redis()
    if redis:
        try:
            data = await redis.get(REDIS_KEY)
            if data:
                released_info = json.loads(data)
                await redis.delete(REDIS_KEY)
                logger.warning(f"Force-released load test lock: {released_info}")
                return released_info
            return None
        except Exception as e:
            logger.warning(f"Redis force-release failed, using local fallback: {e}")

    # In-memory fallback
    with _local_lock:
        if _local_active is not None:
            released_info = dict(_local_active)
            _local_active = None
            logger.warning(f"Force-released local load test lock: {released_info}")
            return released_info
        return None


async def is_active() -> bool:
    """Check if a load test is currently active."""
    redis = _get_redis()
    if redis:
        try:
            return bool(await redis.exists(REDIS_KEY))
        except Exception:
            pass
    return _local_active is not None


async def get_active_info() -> dict | None:
    """Get metadata about the active load test, or None."""
    redis = _get_redis()
    if redis:
        try:
            data = await redis.get(REDIS_KEY)
            if data:
                return json.loads(data)
        except Exception:
            pass
    return _local_active


async def check_system_available(operation_name: str = "operation"):
    """Raise HTTPException(409) if a load test is active.

    Call this before acquiring browser slots in test runs, explorations,
    agent runs, and PRD processing endpoints.
    """
    info = await get_active_info()
    if info:
        run_id = info.get("run_id", "unknown")
        vus = info.get("vus", "?")
        raise HTTPException(
            status_code=409,
            detail=f"Load test {run_id} in progress ({vus} VUs) — {operation_name} paused until completion",
        )
