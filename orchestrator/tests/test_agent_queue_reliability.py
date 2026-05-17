import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.services.agent_queue import AgentQueue, AgentTask, AgentTaskStatus


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
