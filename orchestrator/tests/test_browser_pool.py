"""
Unit tests for BrowserResourcePool.

Tests the unified browser resource pool that limits ALL browser operations
to MAX_BROWSER_INSTANCES concurrent browsers.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration

from services.browser_pool import InMemoryBrowserPool, OperationType, SlotStatus


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

    status = await pool.get_status()

    assert status["by_type"]["test_run"] == 1
    assert status["by_type"]["exploration"] == 1
    assert status["by_type"]["agent"] == 1
    assert status["by_type"]["prd"] == 1
    assert status["running"] == 4
    assert status["available"] == 1


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
