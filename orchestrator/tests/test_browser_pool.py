"""
Unit tests for BrowserResourcePool.

Tests the unified browser resource pool that limits ALL browser operations
to MAX_BROWSER_INSTANCES concurrent browsers.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.services.agent_queue import AgentTask, AgentTaskStatus
from orchestrator.services.browser_pool import InMemoryBrowserPool, OperationType, RedisBrowserResourcePool, SlotStatus


class _FakeRedis:
    def __init__(self):
        self.values = {}
        self.sets = {}
        self.lists = {}
        self.hashes = {}

    async def ping(self):
        return True

    async def set(self, key, value, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def smembers(self, key):
        return set(self.sets.get(key, set()))

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def srem(self, key, value):
        self.sets.setdefault(key, set()).discard(value)

    async def delete(self, key):
        self.values.pop(key, None)
        self.hashes.pop(key, None)

    async def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        if end == -1:
            end = len(values) - 1
        return values[start : end + 1]

    async def lrem(self, key, count, value):
        values = self.lists.get(key, [])
        before = len(values)
        self.lists[key] = [item for item in values if item != value]
        return before - len(self.lists[key])


@pytest.fixture
def pool():
    """Create a fresh pool for each test."""
    # Reset singleton for testing
    InMemoryBrowserPool._instance = None
    InMemoryBrowserPool._lock = None
    return InMemoryBrowserPool(max_browsers=2)


@pytest.mark.asyncio
async def test_pool_initialization(pool):
    """Test that pool initializes correctly."""
    await pool._initialize()

    assert pool.max_browsers == 2
    assert pool._initialized is True
    assert len(pool._running) == 0
    assert len(pool._queue) == 0


@pytest.mark.asyncio
async def test_acquire_and_release(pool):
    """Test basic acquire and release flow."""
    await pool._initialize()

    # Acquire a slot
    acquired = await pool.acquire("req1", OperationType.TEST_RUN, timeout=1)
    assert acquired is True
    assert "req1" in pool._running
    assert pool._slots["req1"].status == SlotStatus.RUNNING

    # Release the slot
    await pool.release("req1", success=True)
    assert "req1" not in pool._running
    assert pool._slots["req1"].status == SlotStatus.COMPLETED


@pytest.mark.asyncio
async def test_max_concurrent_limit(pool):
    """Test that max concurrent browsers are enforced."""
    await pool._initialize()

    # Acquire 2 slots (the max)
    assert await pool.acquire("req1", OperationType.TEST_RUN, timeout=1)
    assert await pool.acquire("req2", OperationType.EXPLORATION, timeout=1)

    # 3rd should timeout because we only wait 0.1s
    acquired = await pool.acquire("req3", OperationType.AGENT, timeout=0.1)
    assert acquired is False
    assert pool._slots["req3"].status == SlotStatus.CANCELLED

    # Release one
    await pool.release("req1")

    # Now 3rd should work
    assert await pool.acquire("req4", OperationType.AGENT, timeout=1)


@pytest.mark.asyncio
async def test_context_manager(pool):
    """Test browser_slot context manager."""
    await pool._initialize()

    async with pool.browser_slot("req1", OperationType.TEST_RUN, timeout=1) as acquired:
        assert acquired is True
        assert "req1" in pool._running

    # After context, should be released
    assert "req1" not in pool._running
    assert pool._slots["req1"].status == SlotStatus.COMPLETED


@pytest.mark.asyncio
async def test_context_manager_exception(pool):
    """Test that context manager releases on exception."""
    await pool._initialize()

    with pytest.raises(ValueError):
        async with pool.browser_slot("req1", OperationType.TEST_RUN, timeout=1) as acquired:
            assert acquired is True
            raise ValueError("Test error")

    # Should still be released
    assert "req1" not in pool._running
    assert pool._slots["req1"].status == SlotStatus.FAILED
    assert pool._slots["req1"].error == "Test error"


@pytest.mark.asyncio
async def test_queue_position(pool):
    """Test queue position tracking."""
    await pool._initialize()

    # Fill up slots
    await pool.acquire("req1", OperationType.TEST_RUN, timeout=1)
    await pool.acquire("req2", OperationType.TEST_RUN, timeout=1)

    # Add to queue (will timeout but be queued first)
    task3 = asyncio.create_task(pool.acquire("req3", OperationType.TEST_RUN, timeout=0.5))
    task4 = asyncio.create_task(pool.acquire("req4", OperationType.TEST_RUN, timeout=0.5))

    # Give time for queue to fill
    await asyncio.sleep(0.1)

    # Check queue positions
    assert await pool.get_queue_position("req3") == 1
    assert await pool.get_queue_position("req4") == 2

    # Wait for timeouts
    await task3
    await task4


@pytest.mark.asyncio
async def test_get_status(pool):
    """Test status reporting."""
    await pool._initialize()

    await pool.acquire("req1", OperationType.TEST_RUN, timeout=1)
    await pool.acquire("req2", OperationType.EXPLORATION, timeout=1)

    status = await pool.get_status()

    assert status["max_browsers"] == 2
    assert status["running"] == 2
    assert status["queued"] == 0
    assert status["available"] == 0
    assert status["by_type"]["test_run"] == 1
    assert status["by_type"]["exploration"] == 1


@pytest.mark.asyncio
async def test_cleanup_stale(pool):
    """Test stale slot cleanup."""
    await pool._initialize()

    # Acquire a slot
    await pool.acquire("req1", OperationType.TEST_RUN, timeout=1)

    # Manually set started_at to be old
    pool._slots["req1"].started_at = datetime.now(timezone.utc) - timedelta(hours=2)

    # Cleanup with 60 minute threshold
    cleaned = await pool.cleanup_stale(max_age_minutes=60)

    assert "req1" in cleaned
    assert "req1" not in pool._running
    assert pool._slots["req1"].status == SlotStatus.FAILED


@pytest.mark.asyncio
async def test_operation_types_tracked():
    """Test that different operation types are tracked separately."""
    InMemoryBrowserPool._instance = None
    InMemoryBrowserPool._lock = None
    pool = InMemoryBrowserPool(max_browsers=5)
    await pool._initialize()

    # Acquire different types
    await pool.acquire("test1", OperationType.TEST_RUN, timeout=1)
    await pool.acquire("explore1", OperationType.EXPLORATION, timeout=1)
    await pool.acquire("agent1", OperationType.AGENT, timeout=1)
    await pool.acquire("prd1", OperationType.PRD, timeout=1)
    await pool.acquire("auth1", OperationType.BROWSER_AUTH, timeout=1)

    status = await pool.get_status()

    assert status["by_type"]["test_run"] == 1
    assert status["by_type"]["exploration"] == 1
    assert status["by_type"]["agent"] == 1
    assert status["by_type"]["prd"] == 1
    assert status["by_type"]["browser_auth"] == 1
    assert "security" in status["by_type"]
    assert "autonomous" in status["by_type"]
    assert status["running"] == 5
    assert status["available"] == 0


@pytest.mark.asyncio
async def test_fifo_waiter_acquires_after_release():
    InMemoryBrowserPool._instance = None
    InMemoryBrowserPool._lock = None
    pool = InMemoryBrowserPool(max_browsers=1)
    await pool._initialize()

    assert await pool.acquire("running", OperationType.TEST_RUN, timeout=1)
    first_waiter = asyncio.create_task(pool.acquire("queued-first", OperationType.SECURITY, timeout=1))
    second_waiter = asyncio.create_task(pool.acquire("queued-second", OperationType.BROWSER_AUTH, timeout=1))
    await asyncio.sleep(0.1)

    assert await pool.get_queue_position("queued-first") == 1
    assert await pool.get_queue_position("queued-second") == 2

    await pool.release("running")
    assert await first_waiter is True
    assert await pool.is_running("queued-first") is True
    assert not second_waiter.done()

    await pool.release("queued-first")
    assert await second_waiter is True
    assert await pool.is_running("queued-second") is True


@pytest.mark.asyncio
async def test_update_max_browsers():
    """Test dynamic update of max browsers (UI parallelism setting)."""
    InMemoryBrowserPool._instance = None
    InMemoryBrowserPool._lock = None
    pool = InMemoryBrowserPool(max_browsers=3)
    await pool._initialize()

    # Fill up to original limit
    await pool.acquire("req1", OperationType.TEST_RUN, timeout=1)
    await pool.acquire("req2", OperationType.TEST_RUN, timeout=1)
    await pool.acquire("req3", OperationType.TEST_RUN, timeout=1)

    assert pool.max_browsers == 3
    assert len(pool._running) == 3

    # Increase limit - should work immediately
    await pool.update_max_browsers(5)
    assert pool.max_browsers == 5

    # Now we can acquire more
    await pool.acquire("req4", OperationType.TEST_RUN, timeout=1)
    assert len(pool._running) == 4

    # Decrease limit - existing ops continue, new ones wait
    await pool.update_max_browsers(2)
    assert pool.max_browsers == 2

    # Status should still show 4 running (existing ops grandfathered)
    status = await pool.get_status()
    assert status["running"] == 4
    assert status["max_browsers"] == 2

    # Release some
    await pool.release("req1")
    await pool.release("req2")
    await pool.release("req3")

    assert len(pool._running) == 1


@pytest.mark.asyncio
async def test_update_max_browsers_invalid():
    """Test that invalid max_browsers values are ignored."""
    InMemoryBrowserPool._instance = None
    InMemoryBrowserPool._lock = None
    pool = InMemoryBrowserPool(max_browsers=5)
    await pool._initialize()

    # Invalid value should be ignored
    await pool.update_max_browsers(0)
    assert pool.max_browsers == 5

    await pool.update_max_browsers(-1)
    assert pool.max_browsers == 5


@pytest.mark.asyncio
async def test_redis_pool_uses_shared_max_browsers():
    """Redis-backed pools should read the same shared concurrency limit."""
    redis = _FakeRedis()
    pool_a = RedisBrowserResourcePool("redis://test", max_browsers=2)
    pool_a.redis = redis
    pool_b = RedisBrowserResourcePool("redis://test", max_browsers=5)
    pool_b.redis = redis

    await pool_a.update_max_browsers(3)

    status = await pool_b.get_status()
    assert status["max_browsers"] == 3
    assert pool_b.max_browsers == 3


@pytest.mark.asyncio
async def test_redis_cleanup_preserves_stale_active_owner(monkeypatch):
    """Redis cleanup should not free an old slot while its owner is active."""
    redis = _FakeRedis()
    pool = RedisBrowserResourcePool("redis://test", max_browsers=1)
    pool.redis = redis
    request_id = "run-active"
    redis.sets["browser_pool:running"] = {request_id}
    redis.hashes[f"browser_pool:info:{request_id}"] = {
        "type": OperationType.TEST_RUN.value,
        "desc": "active run",
        "start": (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(),
        "max_dur": "60",
    }

    async def _active_owner(_request_id, _info):
        return True

    monkeypatch.setattr(pool, "_slot_owner_is_active", _active_owner)

    cleaned = await pool.cleanup_stale(max_age_minutes=1)

    assert cleaned == []
    assert request_id in redis.sets["browser_pool:running"]


@pytest.mark.asyncio
async def test_redis_cleanup_removes_inactive_owner_before_age_limit(monkeypatch):
    """Redis cleanup should free a slot when its logical owner no longer exists."""
    redis = _FakeRedis()
    pool = RedisBrowserResourcePool("redis://test", max_browsers=1)
    pool.redis = redis
    request_id = "agent:agent-old"
    redis.sets["browser_pool:running"] = {request_id}
    redis.hashes[f"browser_pool:info:{request_id}"] = {
        "type": OperationType.AGENT.value,
        "desc": "old agent",
        "start": datetime.now(timezone.utc).isoformat(),
        "max_dur": "7200",
    }

    async def _inactive_owner(_request_id, _info):
        return False

    monkeypatch.setattr(pool, "_slot_owner_is_active", _inactive_owner)

    cleaned = await pool.cleanup_stale(max_age_minutes=60)

    assert cleaned == [request_id]
    assert request_id not in redis.sets["browser_pool:running"]


@pytest.mark.asyncio
async def test_redis_cleanup_removes_running_agent_slot_when_worker_heartbeat_lost(monkeypatch):
    """Redis cleanup should fail a running agent task when its worker heartbeat is gone."""
    import orchestrator.services.agent_queue as agent_queue_module

    redis = _FakeRedis()
    pool = RedisBrowserResourcePool("redis://test", max_browsers=1)
    pool.redis = redis
    task = AgentTask(
        id="agent-stale",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-dead",
        started_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5),
    )
    request_id = f"agent:{task.id}"
    redis.sets["browser_pool:running"] = {request_id}
    redis.hashes[f"browser_pool:info:{request_id}"] = {
        "type": OperationType.AGENT.value,
        "desc": "stale agent",
        "start": datetime.now(timezone.utc).isoformat(),
        "max_dur": "7200",
    }

    class _Queue:
        failed = False

        async def connect(self):
            return None

        async def get_task(self, task_id):
            return task if task_id == task.id else None

        async def check_heartbeat(self, task_id):
            return True

        async def check_worker_heartbeat(self, worker_id):
            return False

        async def fail_stale_running_task(self, task_id, error):
            self.failed = True
            task.status = AgentTaskStatus.FAILED
            task.error = error
            return True

    queue = _Queue()
    monkeypatch.setattr(agent_queue_module, "get_agent_queue", lambda: queue)

    cleaned = await pool.cleanup_stale(max_age_minutes=60)

    assert cleaned == [request_id]
    assert request_id not in redis.sets["browser_pool:running"]
    assert queue.failed is True
    assert task.error == "Stale agent task lost worker heartbeat"


@pytest.mark.asyncio
async def test_redis_cleanup_removes_stale_queued_agent_request(monkeypatch):
    """Redis cleanup should remove dead queued agent browser requests from the head of the queue."""
    redis = _FakeRedis()
    pool = RedisBrowserResourcePool("redis://test", max_browsers=1)
    pool.redis = redis
    redis.lists["browser_pool:queue"] = ["agent:agent-missing", "agent:agent-live"]

    async def _owner_state(request_id, _info):
        if request_id == "agent:agent-missing":
            return False
        if request_id == "agent:agent-live":
            return True
        return None

    monkeypatch.setattr(pool, "_slot_owner_is_active", _owner_state)

    cleaned = await pool.cleanup_stale(max_age_minutes=60)

    assert cleaned == ["agent:agent-missing"]
    assert redis.lists["browser_pool:queue"] == ["agent:agent-live"]


@pytest.mark.asyncio
async def test_redis_cleanup_removes_inactive_prd_generation_slot(monkeypatch):
    """Redis cleanup should free PRD generation browser slots whose generation is terminal or gone."""
    redis = _FakeRedis()
    pool = RedisBrowserResourcePool("redis://test", max_browsers=1)
    pool.redis = redis
    request_id = "gen_20"
    redis.sets["browser_pool:running"] = {request_id}
    redis.hashes[f"browser_pool:info:{request_id}"] = {
        "type": OperationType.PRD.value,
        "desc": "old PRD generation",
        "start": datetime.now(timezone.utc).isoformat(),
        "max_dur": "7200",
    }

    async def _inactive_owner(_request_id, _info):
        return False

    monkeypatch.setattr(pool, "_slot_owner_is_active", _inactive_owner)

    cleaned = await pool.cleanup_stale(max_age_minutes=60)

    assert cleaned == [request_id]
    assert request_id not in redis.sets["browser_pool:running"]


@pytest.mark.asyncio
async def test_redis_cleanup_preserves_running_agent_slot_with_fresh_heartbeats(monkeypatch):
    """Redis cleanup should keep running agent slots when task and worker heartbeats are fresh."""
    import orchestrator.services.agent_queue as agent_queue_module

    redis = _FakeRedis()
    pool = RedisBrowserResourcePool("redis://test", max_browsers=1)
    pool.redis = redis
    task = AgentTask(
        id="agent-fresh",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-alive",
        started_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5),
    )
    request_id = f"agent:{task.id}"
    redis.sets["browser_pool:running"] = {request_id}
    redis.hashes[f"browser_pool:info:{request_id}"] = {
        "type": OperationType.AGENT.value,
        "desc": "fresh agent",
        "start": (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(),
        "max_dur": "60",
    }

    class _Queue:
        failed = False

        async def connect(self):
            return None

        async def get_task(self, task_id):
            return task if task_id == task.id else None

        async def check_heartbeat(self, task_id):
            return True

        async def check_worker_heartbeat(self, worker_id):
            return True

        async def fail_stale_running_task(self, task_id, error):
            self.failed = True
            return True

    queue = _Queue()
    monkeypatch.setattr(agent_queue_module, "get_agent_queue", lambda: queue)

    cleaned = await pool.cleanup_stale(max_age_minutes=1)

    assert cleaned == []
    assert request_id in redis.sets["browser_pool:running"]
    assert queue.failed is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
