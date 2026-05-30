import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.workflows.native_healer import NativeHealer


@pytest.mark.asyncio
async def test_native_healer_uses_agent_runner_with_tool_deep(monkeypatch):
    captured = {}

    class FakeResult:
        output = "healed"
        messages_received = 2
        tool_calls = ["test_run"]
        duration_seconds = 0.2
        timed_out = False
        success = True
        error = None

    class FakeRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self, prompt):
            captured["prompt"] = prompt
            return FakeResult()

    monkeypatch.setattr("orchestrator.workflows.native_healer.AgentRunner", FakeRunner)

    healer = NativeHealer(
        on_tool_use=lambda *_args: None,
        on_progress=lambda *_args: None,
        on_task_enqueued=lambda *_args: None,
        owner_type="test_run",
        owner_id="run-1",
        owner_label="Run 1",
        model_tier="tool_deep",
    )

    output = await healer._query_healer_agent("fix this", timeout_seconds=123)

    assert output == "healed"
    assert captured["timeout_seconds"] == 123
    assert captured["model_tier"] == "tool_deep"
    assert captured["owner_type"] == "test_run"
    assert captured["owner_id"] == "run-1"
    assert captured["memory_agent_type"] == "NativeHealer"
    assert captured["inject_memory"] is False
    assert "test_run" in ",".join(captured["allowed_tools"])
