import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.utils.agent_runner import AgentResult, AgentRunner, ToolCall


def test_agent_runner_appends_cost_log(tmp_path):
    log_path = tmp_path / "agent_costs.jsonl"
    runner = AgentRunner(
        allowed_tools=[],
        memory_agent_type="NativeGenerator",
        memory_stage="native_generator",
        env_vars={"AGENT_COST_LOG": str(log_path)},
    )

    runner._append_cost_log(
        AgentResult(
            success=True,
            duration_seconds=2.5,
            total_cost_usd=0.125,
            tool_calls=[
                ToolCall(name="Read", timestamp=datetime.now(timezone.utc)),
                ToolCall(name="Grep", timestamp=datetime.now(timezone.utc)),
            ],
        )
    )

    rows = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert rows == [
        {
            "agent_type": "NativeGenerator",
            "cost_usd": 0.125,
            "duration_seconds": 2.5,
            "stage": "native_generator",
            "timed_out": False,
            "tool_calls": 2,
            "ts": rows[0]["ts"],
        }
    ]
