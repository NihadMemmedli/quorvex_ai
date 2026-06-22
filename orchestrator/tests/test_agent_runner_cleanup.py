import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.utils import agent_runner as agent_runner_module
from orchestrator.utils.agent_runner import (
    AgentRunner,
    NativeSetupSeedFileError,
    _validate_native_setup_seed_file,
)


class _FakeClaudeAgentOptions:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _patch_runner_runtime(monkeypatch, *, query_impl, killed_calls: list[set[int]]):
    monkeypatch.setattr(agent_runner_module, "AGENT_QUEUE_AVAILABLE", False)
    monkeypatch.setattr(agent_runner_module, "query", query_impl)
    monkeypatch.setattr(
        agent_runner_module, "ClaudeAgentOptions", _FakeClaudeAgentOptions
    )
    monkeypatch.setattr(
        AgentRunner, "_apply_active_ai_settings", staticmethod(lambda *_args: None)
    )
    monkeypatch.setattr(
        AgentRunner,
        "_validate_mcp_config_for_allowed_tools",
        lambda self, cwd=None: None,
    )
    monkeypatch.setattr(agent_runner_module, "snapshot_child_pids", lambda: {101})

    def fake_kill(before_pids, grace_seconds=2.0):
        killed_calls.append(set(before_pids))
        return 1

    monkeypatch.setattr(agent_runner_module, "kill_new_children", fake_kill)


def test_native_generator_setup_defaults_missing_run_local_seed_file():
    tool_input = {}

    assert (
        _validate_native_setup_seed_file(
            "mcp__playwright-test__generator_setup_page",
            tool_input,
        )
        is True
    )
    assert tool_input == {"seedFile": "tests/seed.spec.ts"}

    _validate_native_setup_seed_file(
        "mcp__playwright-test__generator_setup_page",
        {"seedFile": "tests/seed.spec.ts"},
    )


def test_native_generator_setup_rejects_wrong_run_local_seed_file():
    with pytest.raises(NativeSetupSeedFileError, match="generator_setup_page"):
        _validate_native_setup_seed_file(
            "mcp__playwright-test__generator_setup_page",
            {"seedFile": "tests/not-seed.spec.ts"},
        )


@pytest.mark.asyncio
async def test_agent_runner_preserves_browser_children_after_failed_debug_run(
    monkeypatch,
):
    killed_calls: list[set[int]] = []

    async def failing_query(*_args, **_kwargs):
        if False:
            yield None
        raise RuntimeError("debug failed")

    _patch_runner_runtime(
        monkeypatch, query_impl=failing_query, killed_calls=killed_calls
    )
    runner = AgentRunner(
        allowed_tools=["mcp__playwright-test__test_debug"],
        preserve_browser_on_failure=True,
        inject_memory=False,
        capture_memory=False,
    )

    result = await runner.run("debug failed test")

    assert result.success is False
    assert result.error == "debug failed"
    assert killed_calls == []


@pytest.mark.asyncio
async def test_agent_runner_preserves_browser_children_after_timed_out_debug_run(
    monkeypatch,
):
    killed_calls: list[set[int]] = []

    async def hanging_query(*_args, **_kwargs):
        await asyncio.sleep(1)
        if False:
            yield None

    _patch_runner_runtime(
        monkeypatch, query_impl=hanging_query, killed_calls=killed_calls
    )
    runner = AgentRunner(
        timeout_seconds=0.01,
        allowed_tools=["mcp__playwright-test__test_debug"],
        preserve_browser_on_failure=True,
        inject_memory=False,
        capture_memory=False,
    )

    result = await runner.run("debug timed out test")

    assert result.timed_out is True
    assert killed_calls == []


@pytest.mark.asyncio
async def test_agent_runner_cleans_browser_children_after_success_with_preserve_flag(
    monkeypatch,
):
    killed_calls: list[set[int]] = []

    async def successful_query(*_args, **_kwargs):
        yield SimpleNamespace(type="text", text="ok")

    _patch_runner_runtime(
        monkeypatch, query_impl=successful_query, killed_calls=killed_calls
    )
    runner = AgentRunner(
        allowed_tools=["mcp__playwright-test__test_debug"],
        preserve_browser_on_failure=True,
        inject_memory=False,
        capture_memory=False,
    )

    result = await runner.run("debug passing test")

    assert result.success is True
    assert killed_calls == [{101}]


@pytest.mark.asyncio
async def test_agent_runner_cleans_browser_children_after_cancelled_run(
    monkeypatch,
):
    killed_calls: list[set[int]] = []
    checks = 0

    def is_cancelled():
        nonlocal checks
        checks += 1
        return checks > 1

    async def streaming_query(*_args, **_kwargs):
        yield SimpleNamespace(type="text", text="partial")

    _patch_runner_runtime(
        monkeypatch, query_impl=streaming_query, killed_calls=killed_calls
    )
    runner = AgentRunner(
        allowed_tools=["mcp__playwright-test__test_debug"],
        preserve_browser_on_failure=True,
        inject_memory=False,
        capture_memory=False,
        is_cancelled=is_cancelled,
    )

    result = await runner.run("debug cancelled test")

    assert result.cancelled is True
    assert killed_calls == [{101}]


@pytest.mark.asyncio
async def test_agent_runner_cleans_non_browser_children_after_failure_with_preserve_flag(
    monkeypatch,
):
    killed_calls: list[set[int]] = []

    async def failing_query(*_args, **_kwargs):
        if False:
            yield None
        raise RuntimeError("text agent failed")

    _patch_runner_runtime(
        monkeypatch, query_impl=failing_query, killed_calls=killed_calls
    )
    runner = AgentRunner(
        allowed_tools=["Read"],
        preserve_browser_on_failure=True,
        inject_memory=False,
        capture_memory=False,
    )

    result = await runner.run("summarize")

    assert result.success is False
    assert killed_calls == [{101}]
