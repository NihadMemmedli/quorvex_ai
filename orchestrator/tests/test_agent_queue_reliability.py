import json
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.services.agent_queue import AgentQueue, AgentTask, AgentTaskStatus
from orchestrator.services.agent_worker import AgentWorker


class _MemoryPipeline:
    def __init__(self, redis):
        self.redis = redis

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def hset(self, key, field, value):
        self.redis.hashes.setdefault(key, {})[field] = value

    def rpush(self, key, value):
        self.redis.lists.setdefault(key, []).append(value)

    def set(self, key, value, ex=None):
        self.redis.values[key] = value

    def delete(self, key):
        self.redis.values.pop(key, None)

    async def execute(self):
        return True


class _MemoryRedis:
    def __init__(self):
        self.hashes = {}
        self.lists = {}
        self.sets = {}
        self.values = {}

    def pipeline(self, transaction=True):
        return _MemoryPipeline(self)

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    async def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    async def lrem(self, key, count, value):
        values = self.lists.get(key, [])
        before = len(values)
        self.lists[key] = [item for item in values if item != value]
        return before - len(self.lists[key])

    async def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    async def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    async def srem(self, key, value):
        self.sets.setdefault(key, set()).discard(value)

    async def sismember(self, key, value):
        return value in self.sets.get(key, set())

    async def set(self, key, value, ex=None):
        self.values[key] = value

    async def delete(self, key):
        self.values.pop(key, None)

    async def exists(self, key):
        return 1 if key in self.values else 0


class _MemoryQueue(AgentQueue):
    def __init__(self, redis):
        self._redis = redis

    async def _ensure_connected(self):
        return self._redis


def test_agent_task_round_trips_execution_telemetry():
    task = AgentTask(
        id="agent-test",
        prompt="inspect the app",
        created_at=datetime.now(UTC).replace(tzinfo=None),
        allowed_tools=["Read"],
        tools=["Read"],
        disallowed_tools=["Bash"],
        permission_mode="dontAsk",
        strict_mcp_config=True,
        max_budget_usd=0.25,
        task_budget={"total": 25000},
        include_hook_events=True,
        telemetry={
            "worker_id": "worker-1",
            "tool_calls": 4,
            "interactions": 2,
            "assistant_messages": 3,
            "error_type": "timeout",
        },
    )

    restored = AgentTask.from_dict(task.to_dict())

    assert restored.allowed_tools == ["Read"]
    assert restored.tools == ["Read"]
    assert restored.disallowed_tools == ["Bash"]
    assert restored.permission_mode == "dontAsk"
    assert restored.strict_mcp_config is True
    assert restored.max_budget_usd == 0.25
    assert restored.task_budget == {"total": 25000}
    assert restored.include_hook_events is True
    assert restored.telemetry["worker_id"] == "worker-1"
    assert restored.telemetry["tool_calls"] == 4
    assert restored.telemetry["interactions"] == 2
    assert restored.telemetry["assistant_messages"] == 3
    assert restored.telemetry["error_type"] == "timeout"


@pytest.mark.asyncio
async def test_pause_and_resume_queued_task_requeues_after_resume():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(id="agent-queued", prompt="inspect", status=AgentTaskStatus.QUEUED)
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    assert await queue.pause_task(task.id) is True
    paused = await queue.get_task(task.id)
    assert paused.status == AgentTaskStatus.PAUSED
    assert redis.lists[queue.QUEUE_KEY] == []
    assert await queue.is_paused(task.id) is True

    assert await queue.resume_task(task.id) is True
    resumed = await queue.get_task(task.id)
    assert resumed.status == AgentTaskStatus.QUEUED
    assert redis.lists[queue.QUEUE_KEY] == [task.id]
    assert await queue.is_paused(task.id) is False


@pytest.mark.asyncio
async def test_pause_and_resume_running_task_keeps_worker_ownership():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-running",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)

    assert await queue.pause_task(task.id) is True
    paused = await queue.get_task(task.id)
    assert paused.status == AgentTaskStatus.PAUSED
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is True

    assert await queue.resume_task(task.id) is True
    resumed = await queue.get_task(task.id)
    assert resumed.status == AgentTaskStatus.RUNNING
    assert redis.lists.get(queue.QUEUE_KEY, []) == []
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is True


@pytest.mark.asyncio
async def test_pause_resume_reject_terminal_task():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(id="agent-complete", prompt="inspect", status=AgentTaskStatus.COMPLETED)
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))

    assert await queue.pause_task(task.id) is False
    assert await queue.resume_task(task.id) is False


@pytest.mark.asyncio
async def test_cancel_paused_queued_task_clears_pause_and_queue():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(id="agent-paused-queued", prompt="inspect", status=AgentTaskStatus.QUEUED)
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    assert await queue.pause_task(task.id) is True
    assert await queue.is_paused(task.id) is True

    assert await queue.cancel_task(task.id) is True
    cancelled = await queue.get_task(task.id)
    assert cancelled.status == AgentTaskStatus.CANCELLED
    assert redis.lists[queue.QUEUE_KEY] == []
    assert await queue.is_paused(task.id) is False
    assert await queue.is_cancelled(task.id) is True


@pytest.mark.asyncio
async def test_cancel_running_task_sets_cancel_flag_and_removes_running_membership():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-running-cancel",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)

    assert await queue.cancel_task(task.id) is True
    cancelled = await queue.get_task(task.id)
    assert cancelled.status == AgentTaskStatus.CANCELLED
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is False
    assert await queue.is_cancelled(task.id) is True


def test_worker_effective_elapsed_excludes_paused_duration():
    worker = AgentWorker.__new__(AgentWorker)
    worker._pause_lock = threading.Lock()
    worker._paused_task_ids = set()
    worker._pause_started_at = {}
    worker._paused_duration_seconds = {"agent-running": 25.0}

    start = time.time() - 40.0
    elapsed = worker._effective_elapsed_seconds("agent-running", start)

    assert 14.0 <= elapsed <= 16.0


@pytest.mark.asyncio
async def test_running_task_summaries_are_sanitized():
    started_at = datetime.now(UTC).replace(tzinfo=None)
    task = AgentTask(
        id="agent-running",
        prompt="secret user prompt",
        system_prompt="secret system prompt",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        agent_type="AgentRunner",
        operation_type="run",
        cwd="/tmp/project",
        env_vars={"ANTHROPIC_API_KEY": "secret"},
        started_at=started_at,
    )

    class FakeRedis:
        async def smembers(self, _key):
            return {"agent-running"}

    class FakeQueue(AgentQueue):
        def __init__(self):
            pass

        async def _ensure_connected(self):
            return FakeRedis()

        async def get_task(self, task_id: str):
            return task if task_id == "agent-running" else None

        async def get_task_progress(self, task_id: str):
            assert task_id == "agent-running"
            return {
                "activity_label": "Exploring https://example.test",
                "tool_calls": 3,
                "last_tool": "mcp__playwright-test__browser_snapshot",
                "last_tool_input": {"password": "secret"},
            }

        async def check_heartbeat(self, task_id: str, max_stale_seconds: int = 120):
            assert task_id == "agent-running"
            return True

    summaries = await FakeQueue().get_running_task_summaries()

    assert summaries == [
        {
            "id": "agent-running",
            "status": "running",
            "worker_id": "worker-1",
            "agent_type": "AgentRunner",
            "operation_type": "run",
            "created_at": task.created_at.isoformat(),
            "started_at": started_at.isoformat(),
            "timeout_seconds": 1800,
            "heartbeat_alive": True,
            "progress": {
                "activity_label": "Exploring https://example.test",
                "tool_calls": 3,
                "last_tool": "mcp__playwright-test__browser_snapshot",
            },
        }
    ]
    assert "prompt" not in summaries[0]
    assert "system_prompt" not in summaries[0]
    assert "env_vars" not in summaries[0]
    assert "last_tool_input" not in summaries[0]["progress"]
