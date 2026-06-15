import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.services.agent_runtimes import AgentRuntimeContext, get_agent_runtime, normalize_agent_runtime
from orchestrator.services.agent_runtimes.claude import ClaudeAgentSdkRuntime
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


def test_hermes_payload_adds_browser_dialog_policy_to_instructions():
    payload = HermesRuntime(client=object())._run_payload(
        "inspect app",
        AgentRuntimeContext(
            allowed_tools=["browser_dialog"],
            metadata={"instructions": "Base instructions."},
        ),
    )

    assert payload["instructions"].startswith("Base instructions.")
    assert "## Browser Dialog Recovery" in payload["instructions"]
    assert "Leave site?" in payload["instructions"]
    assert "`accept: true`" in payload["instructions"]


@pytest.mark.asyncio
async def test_claude_runtime_passes_env_vars_to_agent_runner(monkeypatch):
    captured = {}

    class FakeRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self, prompt):
            assert prompt == "inspect"
            from orchestrator.utils.agent_runner import AgentResult

            return AgentResult(success=True, output="ok")

    monkeypatch.setattr(
        "orchestrator.services.agent_runtimes.claude.AgentRunner", FakeRunner
    )

    result = await ClaudeAgentSdkRuntime().run(
        "inspect",
        AgentRuntimeContext(
            env_vars={"TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME": "user@example.com"}
        ),
    )

    assert result.success is True
    assert captured["env_vars"] == {
        "TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME": "user@example.com"
    }


@pytest.mark.asyncio
async def test_claude_runtime_passes_advanced_sdk_options_to_agent_runner(monkeypatch):
    captured = {}

    class FakeRunner:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self, prompt):
            from orchestrator.utils.agent_runner import AgentResult

            return AgentResult(success=True, output=prompt)

    async def permission_guard(tool_name, input_data, context):
        return True

    monkeypatch.setattr(
        "orchestrator.services.agent_runtimes.claude.AgentRunner", FakeRunner
    )

    result = await ClaudeAgentSdkRuntime().run(
        "inspect",
        AgentRuntimeContext(
            cwd="/tmp/work",
            fallback_model="claude-fallback",
            reasoning_budget=4096,
            include_partial_messages=True,
            max_buffer_size=123456,
            betas=["context-1m-2025-08-07"],
            user="operator@example.test",
            permission_prompt_tool_name="permission_prompt",
            enable_file_checkpointing=True,
            sandbox={"enabled": True},
            tool_permission_guard=permission_guard,
        ),
    )

    assert result.success is True
    assert captured["cwd"] == "/tmp/work"
    assert captured["fallback_model"] == "claude-fallback"
    assert captured["reasoning_budget"] == 4096
    assert captured["include_partial_messages"] is True
    assert captured["max_buffer_size"] == 123456
    assert captured["betas"] == ["context-1m-2025-08-07"]
    assert captured["user"] == "operator@example.test"
    assert captured["permission_prompt_tool_name"] == "permission_prompt"
    assert captured["enable_file_checkpointing"] is True
    assert captured["sandbox"] == {"enabled": True}
    assert captured["tool_permission_guard"] is permission_guard


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
async def test_hermes_runtime_uses_shared_memory_augmentation(tmp_path, monkeypatch):
    from orchestrator.api import settings as settings_api
    from orchestrator.memory.prompt_augmentation import PromptAugmentationResult

    monkeypatch.setattr(settings_api, "ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("QUORVEX_SETTINGS_ENV_FILE", raising=False)
    monkeypatch.setenv("HERMES_ENABLED", "true")
    captured = {}

    def fake_augment(prompt, **kwargs):
        assert kwargs["project_id"] == "project-a"
        assert kwargs["runtime"] == "hermes"
        return PromptAugmentationResult(
            prompt=f"## Memory Context\nInjected\n\n---\n\n{prompt}",
            context_text="## Memory Context\nInjected",
            injected=True,
        )

    monkeypatch.setattr(
        "orchestrator.memory.prompt_augmentation.augment_prompt_with_agent_memory",
        fake_augment,
    )

    class FakeHermesClient:
        async def create_run(self, payload, timeout_seconds):
            captured.update(payload)
            return {"run_id": "hrun-memory"}

        async def iter_events(self, run_id):
            yield {"event": "lifecycle", "status": "completed"}

        async def get_run(self, run_id):
            return {"status": "completed", "output": "Done"}

    runtime = HermesRuntime(client=FakeHermesClient())
    result = await runtime.run(
        "inspect app",
        AgentRuntimeContext(timeout_seconds=60, owner_id="run-1", memory_project_id="project-a"),
    )

    assert result.success is True
    assert captured["input"].startswith("## Memory Context")
    assert captured["input"].endswith("inspect app")


@pytest.mark.asyncio
async def test_hermes_runtime_uses_persisted_enabled_setting(tmp_path, monkeypatch):

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
