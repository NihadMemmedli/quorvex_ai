import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.utils import agent_runner as agent_runner_module
from orchestrator.utils.agent_runner import AgentRunner


class _FakeClaudeAgentOptions:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _patch_runner_runtime(monkeypatch, events):
    async def fake_query(*_args, **_kwargs):
        for event in events:
            yield event

    monkeypatch.setattr(agent_runner_module, "AGENT_QUEUE_AVAILABLE", False)
    monkeypatch.setattr(agent_runner_module, "query", fake_query)
    monkeypatch.setattr(agent_runner_module, "ClaudeAgentOptions", _FakeClaudeAgentOptions)
    monkeypatch.setattr(
        AgentRunner,
        "_apply_active_ai_settings",
        staticmethod(lambda *_args: None),
    )
    monkeypatch.setattr(
        AgentRunner,
        "_validate_mcp_config_for_allowed_tools",
        lambda self, cwd=None: None,
    )
    monkeypatch.setattr(agent_runner_module, "snapshot_child_pids", lambda: set())
    monkeypatch.setattr(agent_runner_module, "kill_new_children", lambda *_args, **_kwargs: 0)


def _text_events(count: int):
    return [{"type": "text", "text": f"message {index}"} for index in range(count)]


def _tool_use_event(name: str = "mcp__playwright-test__browser_snapshot"):
    return {
        "type": "stream_event",
        "event": {
            "type": "content_block_start",
            "content_block": {
                "type": "tool_use",
                "id": "toolu_snapshot",
                "name": name,
                "input": {},
            },
        },
    }


def test_console_verbosity_uses_env_fallback(monkeypatch):
    monkeypatch.setenv("AGENT_RUNNER_CONSOLE_VERBOSITY", "tools")

    runner = AgentRunner(
        allowed_tools=[],
        inject_memory=False,
        capture_memory=False,
    )

    assert runner.console_verbosity == "tools"


async def _run_with_events(monkeypatch, events, *, console_verbosity: str, log_tools: bool = True):
    _patch_runner_runtime(monkeypatch, events)
    runner = AgentRunner(
        allowed_tools=[],
        log_tools=log_tools,
        inject_memory=False,
        capture_memory=False,
        console_verbosity=console_verbosity,
    )
    return await runner.run("test prompt")


@pytest.mark.asyncio
async def test_summary_suppresses_message_count_console_progress(monkeypatch, capsys):
    await _run_with_events(monkeypatch, _text_events(50), console_verbosity="summary")

    output = capsys.readouterr().out

    assert "First message received" not in output
    assert "50 messages (" not in output
    assert "Agent completed: 50 messages" in output


@pytest.mark.asyncio
async def test_summary_does_not_emit_info_agent_progress_logs(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=agent_runner_module.logger.name)

    await _run_with_events(monkeypatch, _text_events(50), console_verbosity="summary")

    assert not [
        record
        for record in caplog.records
        if record.levelno == logging.INFO and "Agent progress:" in record.getMessage()
    ]


@pytest.mark.asyncio
async def test_tools_mode_emits_tool_trace_but_not_message_count_chatter(monkeypatch, capsys):
    await _run_with_events(
        monkeypatch,
        [_tool_use_event(), *_text_events(50)],
        console_verbosity="tools",
    )

    output = capsys.readouterr().out

    assert "browser_snapshot..." in output
    assert "First message received" not in output
    assert "50 messages (" not in output


@pytest.mark.asyncio
async def test_debug_preserves_message_count_console_progress(monkeypatch, capsys):
    await _run_with_events(monkeypatch, _text_events(50), console_verbosity="debug")

    output = capsys.readouterr().out

    assert "First message received" in output
    assert "50 messages (" in output


@pytest.mark.asyncio
async def test_quiet_suppresses_non_error_console_progress(monkeypatch, capsys):
    await _run_with_events(
        monkeypatch,
        [_tool_use_event(), *_text_events(2)],
        console_verbosity="quiet",
    )

    output = capsys.readouterr().out

    assert "browser_snapshot..." not in output
    assert "First message received" not in output
    assert "Agent completed: 3 messages" in output
