import asyncio
import json
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.services.agent_queue import AgentQueue, AgentTask, AgentTaskStatus
from orchestrator.services.agent_worker import AgentWorker, BrowserObservationRecorder, _event_tool_uses
from orchestrator.utils.agent_runner import AgentRunner
from orchestrator.utils import browser_cleanup


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

    def sadd(self, key, value):
        self.redis.sets.setdefault(key, set()).add(value)

    def srem(self, key, value):
        self.redis.sets.setdefault(key, set()).discard(value)

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

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

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

    async def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    async def lpop(self, key):
        values = self.lists.get(key, [])
        return values.pop(0) if values else None

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    async def blpop(self, key, timeout=0):
        value = await self.lpop(key)
        return (key, value) if value else None

    async def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    async def smembers(self, key):
        return set(self.sets.get(key, set()))

    async def srem(self, key, value):
        self.sets.setdefault(key, set()).discard(value)

    async def sismember(self, key, value):
        return value in self.sets.get(key, set())

    async def set(self, key, value, ex=None):
        self.values[key] = value

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)

    async def exists(self, key):
        return 1 if key in self.values else 0

    async def scan_iter(self, pattern):
        prefix = pattern.rstrip("*")
        for key in list(self.values):
            if key.startswith(prefix):
                yield key


class _MemoryQueue(AgentQueue):
    def __init__(self, redis):
        self._redis = redis
        self._worker_id = "memory-worker"

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
        owner_type="autopilot",
        owner_id="autopilot-test",
        owner_label="AutoPilot test",
        browser_slot_parent_owner_type="test_run",
        browser_slot_parent_run_id="run-parent",
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
    assert restored.owner_type == "autopilot"
    assert restored.owner_id == "autopilot-test"
    assert restored.owner_label == "AutoPilot test"
    assert restored.browser_slot_parent_owner_type == "test_run"
    assert restored.browser_slot_parent_run_id == "run-parent"
    assert restored.telemetry["worker_id"] == "worker-1"
    assert restored.telemetry["tool_calls"] == 4
    assert restored.telemetry["interactions"] == 2
    assert restored.telemetry["assistant_messages"] == 3
    assert restored.telemetry["error_type"] == "timeout"


def test_agent_worker_detects_browser_capable_tasks():
    worker = AgentWorker.__new__(AgentWorker)

    assert worker._task_requires_browser_slot(
        AgentTask(id="agent-browser-owner", prompt="run", owner_type="autonomous_work_item")
    )
    assert worker._task_requires_browser_slot(
        AgentTask(id="agent-browser-tool", prompt="run", allowed_tools=["browser_navigate"], tools=["browser_click"])
    )
    assert not worker._task_requires_browser_slot(
        AgentTask(id="agent-no-tools", prompt="run", allowed_tools=["Read"], tools=[])
    )


def test_agent_worker_detects_parent_test_run_browser_slot():
    worker = AgentWorker.__new__(AgentWorker)

    task = AgentTask(
        id="agent-child",
        prompt="run",
        allowed_tools=["mcp__playwright-test__browser_snapshot"],
        browser_slot_parent_owner_type="test_run",
        browser_slot_parent_run_id="run-123",
    )

    assert worker._parent_test_run_slot_id(task) == "run-123"


def test_agent_runner_uses_parent_test_run_as_queue_owner(monkeypatch):
    monkeypatch.setenv("BROWSER_SLOT_PARENT_OWNER_TYPE", "test_run")
    monkeypatch.setenv("BROWSER_SLOT_PARENT_RUN_ID", "run-123")
    runner = AgentRunner(owner_type=None, owner_id=None)

    assert runner._queue_owner_metadata() == (
        "test_run",
        "run-123",
        "Test run run-123",
        "test_run",
        "run-123",
    )


@pytest.mark.asyncio
async def test_agent_worker_reuses_active_parent_test_run_slot():
    worker = AgentWorker.__new__(AgentWorker)
    task = AgentTask(
        id="agent-child",
        prompt="run",
        browser_slot_parent_owner_type="test_run",
        browser_slot_parent_run_id="run-123",
    )

    class _Pool:
        async def is_running(self, request_id):
            return request_id == "run-123"

    assert await worker._can_reuse_parent_browser_slot(task, _Pool()) is True


@pytest.mark.asyncio
async def test_agent_worker_does_not_reuse_inactive_parent_test_run_slot():
    worker = AgentWorker.__new__(AgentWorker)
    task = AgentTask(
        id="agent-child",
        prompt="run",
        browser_slot_parent_owner_type="test_run",
        browser_slot_parent_run_id="run-123",
    )

    class _Pool:
        async def is_running(self, request_id):
            return False

    assert await worker._can_reuse_parent_browser_slot(task, _Pool()) is False


def test_autopilot_process_tree_matches_session_root_and_cleanup_descendants(monkeypatch):
    current_pid = 999
    processes = {
        current_pid: browser_cleanup.ProcessInfo(
            pid=current_pid,
            ppid=1,
            comm="claude",
            args="claude --session autopilot_2026-05-25_16-33-34",
        ),
        101: browser_cleanup.ProcessInfo(
            pid=101,
            ppid=1,
            comm="claude",
            args="claude --session autopilot_2026-05-25_16-33-34",
        ),
        102: browser_cleanup.ProcessInfo(
            pid=102,
            ppid=101,
            comm="node",
            args="node playwright-mcp",
        ),
        103: browser_cleanup.ProcessInfo(
            pid=103,
            ppid=102,
            comm="chromium",
            args="/usr/bin/chromium --type=renderer",
        ),
        104: browser_cleanup.ProcessInfo(
            pid=104,
            ppid=101,
            comm="python",
            args="python unrelated-child.py",
        ),
        201: browser_cleanup.ProcessInfo(
            pid=201,
            ppid=1,
            comm="chromium",
            args="/usr/bin/chromium --remote-debugging-port=9222",
        ),
    }

    monkeypatch.setattr(browser_cleanup, "_process_table", lambda: processes)
    monkeypatch.setattr(browser_cleanup.os, "getpid", lambda: current_pid)

    assert browser_cleanup.find_autopilot_process_tree("autopilot_2026-05-25_16-33-34") == {
        101,
        102,
        103,
    }


def test_test_run_process_tree_matches_run_root_and_cleanup_descendants(monkeypatch):
    current_pid = 999
    run_id = "2026-05-30_07-23-08"
    processes = {
        current_pid: browser_cleanup.ProcessInfo(
            pid=current_pid,
            ppid=1,
            comm="python",
            args=f"python unrelated.py {run_id}",
        ),
        101: browser_cleanup.ProcessInfo(
            pid=101,
            ppid=1,
            comm="claude",
            args=f"claude --mcp-config /app/runs/{run_id}/.mcp.json",
        ),
        102: browser_cleanup.ProcessInfo(
            pid=102,
            ppid=101,
            comm="node",
            args="node playwright run-test-mcp-server",
        ),
        103: browser_cleanup.ProcessInfo(
            pid=103,
            ppid=102,
            comm="chromium",
            args="/usr/bin/chromium --type=renderer",
        ),
        104: browser_cleanup.ProcessInfo(
            pid=104,
            ppid=101,
            comm="ffmpeg",
            args="ffmpeg -f x11grab :99",
        ),
        105: browser_cleanup.ProcessInfo(
            pid=105,
            ppid=101,
            comm="python",
            args="python unrelated-child.py",
        ),
        201: browser_cleanup.ProcessInfo(
            pid=201,
            ppid=1,
            comm="claude",
            args="claude --mcp-config /app/runs/2026-05-30_07-32-00/.mcp.json",
        ),
    }

    monkeypatch.setattr(browser_cleanup, "_process_table", lambda: processes)
    monkeypatch.setattr(browser_cleanup.os, "getpid", lambda: current_pid)

    assert browser_cleanup.find_test_run_process_tree(run_id) == {101, 102, 103, 104}


def test_test_run_ids_are_extracted_from_cleanup_processes(monkeypatch):
    processes = {
        101: browser_cleanup.ProcessInfo(
            pid=101,
            ppid=1,
            comm="claude",
            args="claude --mcp-config /app/runs/2026-05-30_07-23-08/.mcp.json",
        ),
        102: browser_cleanup.ProcessInfo(
            pid=102,
            ppid=1,
            comm="python",
            args="python /app/orchestrator/cli.py /app/runs/2026-05-30_07-32-00/spec.md",
        ),
        103: browser_cleanup.ProcessInfo(
            pid=103,
            ppid=1,
            comm="python",
            args="python unrelated.py 2026-05-30_07-40-00",
        ),
    }

    monkeypatch.setattr(browser_cleanup, "_process_table", lambda: processes)

    assert browser_cleanup.find_test_run_ids_in_processes() == {
        "2026-05-30_07-23-08",
        "2026-05-30_07-32-00",
    }


def test_autopilot_session_ids_are_extracted_only_from_cleanup_processes(monkeypatch):
    processes = {
        101: browser_cleanup.ProcessInfo(
            pid=101,
            ppid=1,
            comm="claude",
            args="claude --session autopilot_2026-05-25_16-33-34",
        ),
        102: browser_cleanup.ProcessInfo(
            pid=102,
            ppid=1,
            comm="node",
            args="node /tmp/autopilot_2026-05-25_16-44-10/playwright-mcp",
        ),
        103: browser_cleanup.ProcessInfo(
            pid=103,
            ppid=1,
            comm="python",
            args="python mentions autopilot_2026-05-25_16-55-00",
        ),
    }

    monkeypatch.setattr(browser_cleanup, "_process_table", lambda: processes)

    assert browser_cleanup.find_autopilot_session_ids_in_processes() == {
        "autopilot_2026-05-25_16-33-34",
        "autopilot_2026-05-25_16-44-10",
    }


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
async def test_wait_for_result_keeps_queued_task_when_workers_are_busy():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-busy-queued", prompt="inspect", status=AgentTaskStatus.QUEUED
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    async def worker_count():
        return 2

    async def queue_length():
        return 4

    async def running_count():
        return 2

    queue.worker_count = worker_count
    queue.queue_length = queue_length
    queue.running_count = running_count

    with pytest.raises(asyncio.TimeoutError):
        await queue.wait_for_result(
            task.id, timeout=0.05, poll_interval=0.001, queued_timeout=0.01
        )

    assert await queue.get_task(task.id) is not None


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
    task = AgentTask(
        id="agent-complete", prompt="inspect", status=AgentTaskStatus.COMPLETED
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))

    assert await queue.pause_task(task.id) is False
    assert await queue.resume_task(task.id) is False


@pytest.mark.asyncio
async def test_cancel_paused_queued_task_clears_pause_and_queue():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-paused-queued", prompt="inspect", status=AgentTaskStatus.QUEUED
    )
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
async def test_cancel_running_task_sets_cancel_requested_and_keeps_worker_membership():
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
    assert cancelled.status == AgentTaskStatus.CANCEL_REQUESTED
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is True
    assert await queue.is_cancelled(task.id) is True


@pytest.mark.asyncio
async def test_cancel_tasks_for_test_run_cancels_owner_and_parent_tasks():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    owned = AgentTask(
        id="agent-owned",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        owner_type="test_run",
        owner_id="run-123",
    )
    parented = AgentTask(
        id="agent-parented",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
        browser_slot_parent_owner_type="test_run",
        browser_slot_parent_run_id="run-123",
    )
    unrelated = AgentTask(
        id="agent-unrelated",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        owner_type="test_run",
        owner_id="run-456",
    )
    for task in (owned, parented, unrelated):
        await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, owned.id)
    await redis.rpush(queue.QUEUE_KEY, unrelated.id)
    await redis.sadd(queue.RUNNING_KEY, parented.id)

    summary = await queue.cancel_tasks_for_test_run("run-123")

    assert summary["matched"] == 2
    assert summary["cancelled"] == 2
    assert set(summary["task_ids"]) == {"agent-owned", "agent-parented"}
    assert (await queue.get_task(owned.id)).status == AgentTaskStatus.CANCELLED
    assert (await queue.get_task(parented.id)).status == AgentTaskStatus.CANCEL_REQUESTED
    assert (await queue.get_task(unrelated.id)).status == AgentTaskStatus.QUEUED
    assert redis.lists[queue.QUEUE_KEY] == [unrelated.id]
    assert await redis.sismember(queue.RUNNING_KEY, parented.id) is True


@pytest.mark.asyncio
async def test_cancel_requested_task_becomes_cancelled_when_worker_submits_cancel_result():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id="agent-running-cancel-result",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)

    assert await queue.cancel_task(task.id) is True
    await queue.submit_result(task.id, "", success=False, error="Task cancelled")

    cancelled = await queue.get_task(task.id)
    assert cancelled.status == AgentTaskStatus.CANCELLED
    assert cancelled.error == "Task cancelled"
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is False


@pytest.mark.asyncio
async def test_cleanup_times_out_running_task_by_task_timeout():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    started_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10)
    task = AgentTask(
        id="agent-timeout",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=started_at,
        timeout_seconds=60,
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)

    counts = await queue.cleanup_orphaned_and_stale_tasks()

    cleaned = await queue.get_task(task.id)
    assert counts["timed_out"] == 1
    assert cleaned.status == AgentTaskStatus.TIMEOUT
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is False
    assert await queue.is_cancelled(task.id) is True


@pytest.mark.asyncio
async def test_cleanup_cancels_task_when_owner_is_terminal():
    redis = _MemoryRedis()

    class OwnerTerminalQueue(_MemoryQueue):
        async def _get_owner_state(self, task):
            return {
                "type": task.owner_type,
                "id": task.owner_id,
                "label": task.owner_label,
                "status": "failed",
                "terminal": True,
            }

    queue = OwnerTerminalQueue(redis)
    task = AgentTask(
        id="agent-terminal-owner",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        started_at=datetime.now(UTC).replace(tzinfo=None),
        owner_type="autopilot",
        owner_id="autopilot-failed",
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)
    await queue.update_heartbeat(task.id)

    counts = await queue.cleanup_orphaned_and_stale_tasks()

    cleaned = await queue.get_task(task.id)
    assert counts["terminal_owner"] == 1
    assert cleaned.status == AgentTaskStatus.FAILED
    assert await redis.sismember(queue.RUNNING_KEY, task.id) is False
    assert await queue.is_cancelled(task.id) is True


@pytest.mark.asyncio
async def test_cleanup_fails_queued_task_missing_from_queue_list():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10)
    task = AgentTask(
        id="agent-orphaned-queued",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        created_at=created_at,
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))

    counts = await queue.cleanup_orphaned_and_stale_tasks()

    cleaned = await queue.get_task(task.id)
    assert counts["orphaned_queued"] == 1
    assert cleaned.status == AgentTaskStatus.FAILED
    assert await queue.is_cancelled(task.id) is True


@pytest.mark.asyncio
async def test_cleanup_cancels_stale_ownerless_queued_task_in_queue_list():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=90)
    task = AgentTask(
        id="agent-stale-ownerless",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        created_at=created_at,
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    counts = await queue.cleanup_orphaned_and_stale_tasks(max_age_minutes=45)

    cleaned = await queue.get_task(task.id)
    assert counts["stale_ownerless_queued"] == 1
    assert cleaned.status == AgentTaskStatus.CANCELLED
    assert redis.lists[queue.QUEUE_KEY] == []
    assert await queue.is_cancelled(task.id) is True


@pytest.mark.asyncio
async def test_cleanup_keeps_fresh_ownerless_queued_task():
    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
    task = AgentTask(
        id="agent-fresh-ownerless",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        created_at=created_at,
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    counts = await queue.cleanup_orphaned_and_stale_tasks(max_age_minutes=45)

    kept = await queue.get_task(task.id)
    assert counts["stale_ownerless_queued"] == 0
    assert kept.status == AgentTaskStatus.QUEUED
    assert redis.lists[queue.QUEUE_KEY] == [task.id]


@pytest.mark.asyncio
async def test_dequeue_skips_stale_ownerless_task_before_valid_agent_run():
    redis = _MemoryRedis()

    class ValidOwnerQueue(_MemoryQueue):
        async def _get_owner_state(self, task):
            if task.owner_id == "run-1":
                return {
                    "type": task.owner_type,
                    "id": task.owner_id,
                    "label": task.owner_label,
                    "status": "running",
                    "terminal": False,
                }
            return await super()._get_owner_state(task)

    queue = ValidOwnerQueue(redis)
    stale = AgentTask(
        id="agent-old-ownerless",
        prompt="old",
        status=AgentTaskStatus.QUEUED,
        created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=90),
    )
    valid = AgentTask(
        id="agent-linked-run",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        owner_type="agent_run",
        owner_id="run-1",
    )
    await redis.hset(queue.TASKS_KEY, stale.id, json.dumps(stale.to_dict()))
    await redis.hset(queue.TASKS_KEY, valid.id, json.dumps(valid.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, stale.id)
    await redis.rpush(queue.QUEUE_KEY, valid.id)

    skipped = await queue.dequeue_task(timeout=1)

    cleaned = await queue.get_task(stale.id)
    kept = await queue.get_task(valid.id)
    assert skipped is None
    assert cleaned.status == AgentTaskStatus.CANCELLED
    assert kept.status == AgentTaskStatus.QUEUED
    assert redis.lists[queue.QUEUE_KEY] == [valid.id]

    dequeued = await queue.dequeue_task(timeout=1)
    assert dequeued.id == valid.id
    assert dequeued.status == AgentTaskStatus.RUNNING
    assert await redis.sismember(queue.RUNNING_KEY, valid.id) is True


@pytest.mark.asyncio
async def test_dequeue_terminalizes_queued_task_with_terminal_owner():
    redis = _MemoryRedis()

    class OwnerTerminalQueue(_MemoryQueue):
        async def _get_owner_state(self, task):
            return {
                "type": task.owner_type,
                "id": task.owner_id,
                "label": task.owner_label,
                "status": "failed",
                "terminal": True,
            }

    queue = OwnerTerminalQueue(redis)
    task = AgentTask(
        id="agent-terminal-owner-queued",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        owner_type="agent_run",
        owner_id="run-failed",
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.rpush(queue.QUEUE_KEY, task.id)

    assert await queue.dequeue_task(timeout=1) is None
    cleaned = await queue.get_task(task.id)
    assert cleaned.status == AgentTaskStatus.FAILED
    assert redis.lists[queue.QUEUE_KEY] == []


def test_worker_effective_elapsed_excludes_paused_duration():
    worker = AgentWorker.__new__(AgentWorker)
    worker._pause_lock = threading.Lock()
    worker._paused_task_ids = set()
    worker._pause_started_at = {}
    worker._paused_duration_seconds = {"agent-running": 25.0}

    start = time.time() - 40.0
    elapsed = worker._effective_elapsed_seconds("agent-running", start)

    assert 14.0 <= elapsed <= 16.0


def test_worker_extracts_nested_tool_use_stream_items():
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "text",
                    "text": "Inspecting the page",
                },
                {
                    "type": "tool_result",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_nested",
                            "name": "mcp__playwright-test__browser_snapshot",
                            "input": {},
                        }
                    ],
                },
            ],
        },
    }

    assert [item["name"] for item in _event_tool_uses(event)] == [
        "mcp__playwright-test__browser_snapshot"
    ]


def test_worker_telemetry_preserves_execution_tool_counts():
    worker = AgentWorker.__new__(AgentWorker)
    worker.worker_id = "worker-1"
    worker._progress_lock = threading.RLock()
    worker._current_progress = {
        "tool_calls": 0,
        "browser_tool_calls": 0,
        "interactions": 0,
        "last_tool": "",
        "tool_names": [],
        "chars": 120,
    }
    worker._last_execution_telemetry = {
        "tool_calls": 3,
        "browser_tool_calls": 2,
        "interactions": 1,
        "last_tool": "mcp__playwright-test__browser_click",
        "tool_names": [
            "mcp__playwright-test__browser_navigate",
            "mcp__playwright-test__browser_snapshot",
            "mcp__playwright-test__browser_click",
        ],
    }
    task = AgentTask(
        id="task-1",
        prompt="prompt",
        agent_type="AgentRunner",
        operation_type="run",
        allowed_tools=["mcp__playwright-test__browser_click"],
        tools=["mcp__playwright-test__browser_click"],
    )

    telemetry = worker._build_task_telemetry(task, attempt=1)

    assert telemetry["tool_calls"] == 3
    assert telemetry["browser_tool_calls"] == 2
    assert telemetry["interactions"] == 1
    assert telemetry["last_tool"] == "mcp__playwright-test__browser_click"
    assert telemetry["tool_names"][-1] == "mcp__playwright-test__browser_click"


def test_browser_observation_recorder_persists_snapshot_result(tmp_path):
    class FakeState:
        def __init__(self, state_id):
            self.id = state_id

    class FakeService:
        def __init__(self):
            self.states = []
            self.transitions = []

        def upsert_page_state(self, **kwargs):
            state = FakeState(f"state-{len(self.states) + 1}")
            self.states.append({**kwargs, "state": state})
            return state

        def record_transition(self, **kwargs):
            self.transitions.append(kwargs)

    service = FakeService()
    recorder = BrowserObservationRecorder(
        session_id="explore-1",
        cwd=str(tmp_path),
        service_factory=lambda: service,
    )

    recorder.observe_event(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_snapshot",
                        "name": "mcp__playwright-test__browser_snapshot",
                        "input": {},
                    }
                ]
            },
        }
    )
    recorder.observe_event(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_snapshot",
                        "content": [
                            {
                                "type": "text",
                                "text": 'Page title: Login\nhttps://example.test/login\n- button "Sign in"',
                            }
                        ],
                    }
                ]
            },
        }
    )

    assert len(service.states) == 1
    assert service.states[0]["session_id"] == "explore-1"
    assert service.states[0]["url"] == "https://example.test/login"
    assert service.states[0]["title"] == "Login"
    assert recorder.telemetry()["browser_memory_snapshots"] == 1
    assert (tmp_path / "browser-memory-observations.jsonl").exists()


def test_browser_observation_recorder_pairs_interaction_with_next_snapshot(tmp_path):
    class FakeState:
        def __init__(self, state_id):
            self.id = state_id

    class FakeService:
        def __init__(self):
            self.states = []
            self.transitions = []

        def upsert_page_state(self, **kwargs):
            state = FakeState(f"state-{len(self.states) + 1}")
            self.states.append({**kwargs, "state": state})
            return state

        def record_transition(self, **kwargs):
            self.transitions.append(kwargs)

    service = FakeService()
    recorder = BrowserObservationRecorder(
        session_id="explore-1",
        cwd=str(tmp_path),
        service_factory=lambda: service,
    )

    def event_tool_use(tool_id, name, tool_input=None):
        recorder.observe_event(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": f"mcp__playwright-test__{name}",
                            "input": tool_input or {},
                        }
                    ]
                },
            }
        )

    def event_tool_result(tool_id, text):
        recorder.observe_event(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": text,
                        }
                    ]
                },
            }
        )

    event_tool_use("s1", "browser_snapshot")
    event_tool_result("s1", 'https://example.test\n- button "Open menu"')
    event_tool_use("c1", "browser_click", {"element": "Open menu"})
    event_tool_result("c1", "Clicked")
    event_tool_use("s2", "browser_snapshot")
    event_tool_result("s2", 'https://example.test\n- menuitem "Settings"')

    assert len(service.states) == 2
    assert len(service.transitions) == 1
    assert service.transitions[0]["from_state"].id == "state-1"
    assert service.transitions[0]["to_state"].id == "state-2"
    assert service.transitions[0]["action_type"] == "click"
    assert service.transitions[0]["target"] == "Open menu"
    assert recorder.telemetry()["browser_memory_transitions"] == 1


def test_browser_observation_recorder_ignores_malformed_result_without_raising(
    tmp_path,
):
    recorder = BrowserObservationRecorder(
        session_id="explore-1",
        cwd=str(tmp_path),
        service_factory=lambda: (_ for _ in ()).throw(
            AssertionError("service should not be called")
        ),
    )

    recorder.observe_event(
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "content": "orphan"}]},
        }
    )

    assert recorder.telemetry()["browser_memory_snapshots"] == 0
    assert recorder.telemetry()["browser_memory_transitions"] == 0


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
            "owner_type": None,
            "owner_id": None,
            "owner_label": None,
            "owner_status": None,
            "owner_terminal": False,
            "orphaned": False,
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
