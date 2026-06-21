from types import SimpleNamespace

from orchestrator.services import agent_prompt_runtime
from orchestrator.services.agent_prompt_runtime import (
    build_autopilot_retry_kwargs,
    create_agent_runner,
    optional_env_float,
)


class FakeAgentRunner:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _source(**overrides):
    data = {
        "on_tool_use": lambda *_args: None,
        "on_progress": lambda *_args: None,
        "on_task_enqueued": lambda *_args: None,
        "owner_type": None,
        "owner_id": None,
        "owner_label": None,
        "model_tier": "tool_deep",
        "env_vars": {"PROJECT_ID": "default"},
        "cwd": "/tmp/run",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_optional_env_float(monkeypatch):
    monkeypatch.delenv("GENERATOR_MAX_BUDGET_USD", raising=False)
    assert optional_env_float("GENERATOR_MAX_BUDGET_USD") is None

    monkeypatch.setenv("GENERATOR_MAX_BUDGET_USD", "1.25")
    assert optional_env_float("GENERATOR_MAX_BUDGET_USD") == 1.25


def test_build_autopilot_retry_kwargs_uses_owner_defaults_for_autopilot():
    source = _source(owner_type="autopilot", owner_id="session-123")

    kwargs = build_autopilot_retry_kwargs(
        source,
        owner_type=source.owner_type,
        owner_id=source.owner_id,
        default_agent_kind="test_generation",
    )

    assert kwargs["autopilot_retry_enabled"] is True
    assert kwargs["autopilot_session_id"] == "session-123"
    assert kwargs["autopilot_agent_kind"] == "test_generation"


def test_build_autopilot_retry_kwargs_preserves_explicit_overrides():
    source = _source(
        owner_type="autopilot",
        owner_id="owner-session",
        autopilot_retry_enabled=False,
        autopilot_session_id="explicit-session",
        autopilot_agent_kind="custom-kind",
        autopilot_stable_key="stable-key",
    )

    kwargs = build_autopilot_retry_kwargs(
        source,
        owner_type=source.owner_type,
        owner_id=source.owner_id,
        default_agent_kind="test_generation",
    )

    assert kwargs["autopilot_retry_enabled"] is True
    assert kwargs["autopilot_session_id"] == "explicit-session"
    assert kwargs["autopilot_agent_kind"] == "custom-kind"
    assert kwargs["autopilot_stable_key"] == "stable-key"


def test_create_agent_runner_preserves_schema_retry_options(monkeypatch):
    monkeypatch.setattr(agent_prompt_runtime, "AgentRunner", FakeAgentRunner)
    source = _source(owner_type="autopilot", owner_id="owner-session")

    runner = create_agent_runner(
        source,
        timeout_seconds=180,
        allowed_tools=[],
        tools=[],
        log_tools=False,
        memory_agent_type="NativeGenerator",
        memory_source_type="spec",
        memory_stage="native_generator_schema_retry",
        inject_memory=False,
        capture_memory=False,
        requires_live_browser=False,
        force_direct_execution=True,
        autopilot_agent_kind="test_generation_schema_retry",
        include_tool_use_callback=False,
    )

    assert runner.kwargs["allowed_tools"] == []
    assert runner.kwargs["tools"] == []
    assert runner.kwargs["log_tools"] is False
    assert runner.kwargs["on_tool_use"] is None
    assert runner.kwargs["capture_memory"] is False
    assert runner.kwargs["force_direct_execution"] is True
    assert runner.kwargs["autopilot_retry_enabled"] is True
    assert runner.kwargs["autopilot_session_id"] == "owner-session"


def test_create_agent_runner_applies_tool_config_and_budget(monkeypatch):
    monkeypatch.setattr(agent_prompt_runtime, "AgentRunner", FakeAgentRunner)
    monkeypatch.setenv("HEALER_MAX_BUDGET_USD", "2.5")
    source = _source(autopilot_retry_enabled=True, autopilot_session_id="healer-session")
    tool_config = {
        "allowed_tools": ["Read"],
        "tools": {"browser": "enabled"},
        "disallowed_tools": ["Write"],
    }

    runner = create_agent_runner(
        source,
        timeout_seconds=300,
        tool_config=tool_config,
        allowed_tools=tool_config["allowed_tools"] or [],
        log_tools=True,
        max_budget_env="HEALER_MAX_BUDGET_USD",
        memory_agent_type="NativeHealer",
        memory_source_type="test_file",
        memory_stage="native_healer",
        inject_memory=False,
        preserve_browser_on_failure=True,
        autopilot_agent_kind="test_generation_healer",
        enable_autopilot_for_owner=False,
    )

    assert runner.kwargs["allowed_tools"] == ["Read"]
    assert runner.kwargs["tools"] == {"browser": "enabled"}
    assert runner.kwargs["disallowed_tools"] == ["Write"]
    assert runner.kwargs["max_budget_usd"] == 2.5
    assert runner.kwargs["preserve_browser_on_failure"] is True
    assert runner.kwargs["autopilot_retry_enabled"] is True
    assert runner.kwargs["autopilot_session_id"] == "healer-session"
