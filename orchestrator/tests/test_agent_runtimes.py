import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.services.agent_runtimes import AgentRuntimeContext, get_agent_runtime, normalize_agent_runtime
from orchestrator.services.agent_runtimes.hermes import HermesRuntime


def test_normalize_agent_runtime_defaults_and_aliases(monkeypatch):
    monkeypatch.delenv("QUORVEX_AGENT_RUNTIME", raising=False)

    assert normalize_agent_runtime(None) == "claude_sdk"
    assert normalize_agent_runtime("claude") == "claude_sdk"
    assert normalize_agent_runtime("claude-agent-sdk") == "claude_sdk"
    assert normalize_agent_runtime("hermes-agent") == "hermes"
    assert normalize_agent_runtime("unknown") == "claude_sdk"


def test_runtime_resolver_returns_hermes_adapter():
    assert isinstance(get_agent_runtime("hermes"), HermesRuntime)


@pytest.mark.asyncio
async def test_hermes_runtime_maps_run_events(tmp_path, monkeypatch):
    from orchestrator.api import settings as settings_api

    monkeypatch.setattr(settings_api, "ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("QUORVEX_SETTINGS_ENV_FILE", raising=False)
    monkeypatch.setenv("HERMES_ENABLED", "true")
    progress: list[dict] = []
    tools: list[tuple[str, dict]] = []

    class FakeHermesClient:
        async def create_run(self, payload, timeout_seconds):
            assert payload["input"] == "inspect app"
            assert timeout_seconds == 60
            return {"run_id": "hrun-1", "status": "started"}

        async def iter_events(self, run_id):
            assert run_id == "hrun-1"
            yield {"event": "hermes.tool.progress", "tool_name": "terminal", "input": {"command": "pwd"}}
            yield {"event": "lifecycle", "status": "completed"}

        async def get_run(self, run_id):
            assert run_id == "hrun-1"
            return {
                "status": "completed",
                "output": "Done",
                "usage": {"total_tokens": 12, "total_cost_usd": 0.01},
            }

    runtime = HermesRuntime(client=FakeHermesClient())
    result = await runtime.run(
        "inspect app",
        AgentRuntimeContext(
            timeout_seconds=60,
            owner_id="run-1",
            on_progress=progress.append,
            on_tool_use=lambda name, payload: tools.append((name, payload)),
        ),
    )

    assert result.success is True
    assert result.output == "Done"
    assert result.session_id == "hrun-1"
    assert result.total_cost_usd == 0.01
    assert [call.name for call in result.tool_calls] == ["terminal"]
    assert tools == [("terminal", {"command": "pwd"})]
    assert any(item.get("hermes_run_id") == "hrun-1" for item in progress)


@pytest.mark.asyncio
async def test_hermes_runtime_uses_persisted_enabled_setting(tmp_path, monkeypatch):
    from orchestrator.api import settings as settings_api

    env_file = tmp_path / "runtime.env"
    env_file.write_text("HERMES_ENABLED=true\nHERMES_MODEL=persisted-hermes\n")
    monkeypatch.setenv("QUORVEX_SETTINGS_ENV_FILE", str(env_file))
    monkeypatch.delenv("HERMES_ENABLED", raising=False)

    class FakeHermesClient:
        async def create_run(self, payload, timeout_seconds):
            assert payload["model"] == "persisted-hermes"
            return {"run_id": "hrun-persisted"}

        async def iter_events(self, run_id):
            yield {"event": "lifecycle", "status": "completed"}

        async def get_run(self, run_id):
            return {"status": "completed", "output": "Persisted settings worked"}

    runtime = HermesRuntime(client=FakeHermesClient())
    result = await runtime.run("inspect app", AgentRuntimeContext(timeout_seconds=60, owner_id="run-1"))

    assert result.success is True
    assert result.output == "Persisted settings worked"


@pytest.mark.asyncio
async def test_hermes_runtime_rejects_when_persisted_and_env_disabled(tmp_path, monkeypatch):
    env_file = tmp_path / "runtime.env"
    env_file.write_text("HERMES_ENABLED=false\n")
    monkeypatch.setenv("QUORVEX_SETTINGS_ENV_FILE", str(env_file))
    monkeypatch.delenv("HERMES_ENABLED", raising=False)

    runtime = HermesRuntime(client=object())
    result = await runtime.run("inspect app", AgentRuntimeContext(timeout_seconds=60, owner_id="run-1"))

    assert result.success is False
    assert result.error == "Hermes runtime is disabled. Set HERMES_ENABLED=true."


@pytest.mark.asyncio
async def test_hermes_runtime_stops_run_when_cancelled(tmp_path, monkeypatch):
    from orchestrator.api import settings as settings_api

    monkeypatch.setattr(settings_api, "ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("QUORVEX_SETTINGS_ENV_FILE", raising=False)
    monkeypatch.setenv("HERMES_ENABLED", "true")
    checks = 0
    stopped: list[str] = []

    class FakeHermesClient:
        async def create_run(self, payload, timeout_seconds):
            return {"run_id": "hrun-cancel"}

        async def iter_events(self, run_id):
            yield {"event": "message", "output": "partial evidence"}
            yield {"event": "message", "output": "should not finish"}

        async def stop_run(self, run_id):
            stopped.append(run_id)
            return {"status": "stopping"}

        async def get_run(self, run_id):
            return {"status": "completed", "output": "late success"}

    def is_cancelled():
        nonlocal checks
        checks += 1
        return checks > 2

    runtime = HermesRuntime(client=FakeHermesClient())
    result = await runtime.run(
        "inspect app",
        AgentRuntimeContext(timeout_seconds=60, owner_id="run-1", is_cancelled=is_cancelled),
    )

    assert result.success is False
    assert result.cancelled is True
    assert result.output == "partial evidence"
    assert stopped == ["hrun-cancel"]
