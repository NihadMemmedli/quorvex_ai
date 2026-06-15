import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.services.agent_runtimes import AgentRuntimeContext, get_agent_runtime, normalize_agent_runtime
from orchestrator.services.agent_runtimes.claude import ClaudeAgentSdkRuntime


def test_normalize_agent_runtime_defaults_and_aliases(monkeypatch):
    monkeypatch.delenv("QUORVEX_AGENT_RUNTIME", raising=False)

    assert normalize_agent_runtime(None) == "claude_sdk"
    assert normalize_agent_runtime("claude") == "claude_sdk"
    assert normalize_agent_runtime("claude-agent-sdk") == "claude_sdk"
    assert normalize_agent_runtime("hermes") == "claude_sdk"
    assert normalize_agent_runtime("hermes-agent") == "claude_sdk"
    assert normalize_agent_runtime("hermes_agent") == "claude_sdk"
    assert normalize_agent_runtime("unknown") == "claude_sdk"


def test_runtime_resolver_coerces_legacy_hermes_to_claude_sdk():
    assert isinstance(get_agent_runtime("hermes"), ClaudeAgentSdkRuntime)


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

    hooks = {"PreToolUse": []}
    agents = {
        "read-only-reviewer": {
            "description": "Read-only reviewer",
            "prompt": "Review using read-only tools.",
            "tools": ["Read", "Grep", "Glob"],
        }
    }
    plugins = [{"type": "local", "path": "./.claude/plugins/reviewer"}]
    session_store = object()

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
            hooks=hooks,
            agents=agents,
            skills=["playwright"],
            plugins=plugins,
            session_store=session_store,
            fork_session=True,
            tool_search_policy="force",
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
    assert captured["hooks"] is hooks
    assert captured["agents"] is agents
    assert captured["skills"] == ["playwright"]
    assert captured["plugins"] is plugins
    assert captured["session_store"] is session_store
    assert captured["fork_session"] is True
    assert captured["tool_search_policy"] == "force"
    assert captured["tool_permission_guard"] is permission_guard
