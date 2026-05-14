import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.services.agent_queue import AgentTask


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
