import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.agents import base_agent as base_agent_module
from orchestrator.agents.base_agent import BaseAgent
from orchestrator.utils.agent_tool_allowlists import (
    AGENT_TOOL_PROFILES,
    get_agent_allowed_tools,
    get_agent_tool_config,
)


def _agent_profile_name(agent_file: Path) -> str:
    text = agent_file.read_text()
    match = re.match(r"^---\n(?P<frontmatter>.*?)\n---\n", text, re.DOTALL)
    if not match:
        return agent_file.stem
    name_match = re.search(r"^name:\s*(?P<name>[^\n]+?)\s*$", match.group("frontmatter"), re.MULTILINE)
    return name_match.group("name").strip("\"'") if name_match else agent_file.stem


def _agent_frontmatter_tools(agent_file: Path) -> list[str]:
    text = agent_file.read_text()
    match = re.match(r"^---\n(?P<frontmatter>.*?)\n---\n", text, re.DOTALL)
    if not match:
        return []
    tools_match = re.search(r"^tools:\s*(?P<tools>[^\n]+?)\s*$", match.group("frontmatter"), re.MULTILINE)
    if not tools_match:
        return []
    return [tool.strip() for tool in tools_match.group("tools").split(",") if tool.strip()]


def _write_mcp_config(tmp_path: Path, server_name: str) -> None:
    (tmp_path / ".mcp.json").write_text(
        f"""
{{
  "mcpServers": {{
    "{server_name}": {{
      "command": "npx",
      "args": ["@playwright/mcp"]
    }}
  }}
}}
"""
    )


def test_agent_allowlist_uses_playwright_test_prefix(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright-test")
    monkeypatch.chdir(tmp_path)

    tools = get_agent_allowed_tools("playwright-test-healer")

    assert "mcp__playwright-test__test_run" in tools
    assert "mcp__playwright-test__test_debug" in tools
    assert "mcp__playwright-test__browser_start_tracing" in tools
    assert "mcp__playwright-test__browser_resume" in tools
    assert "mcp__playwright-test__browser_close" not in tools
    assert "mcp__playwright-test__browser_run_code" not in tools
    assert "mcp__playwright-test__browser_file_upload" not in tools


def test_agent_allowlist_uses_root_playwright_prefix(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright")
    monkeypatch.chdir(tmp_path)

    tools = get_agent_allowed_tools("app-explorer")

    assert {"Glob", "Grep", "Read", "LS"} <= set(tools)
    assert "mcp__playwright__browser_snapshot" in tools
    assert "mcp__playwright__browser_network_requests" in tools
    assert "mcp__playwright__browser_hover" in tools
    assert "mcp__playwright__browser_navigate" in tools
    assert "mcp__playwright__browser_fill_form" in tools
    assert "mcp__playwright__browser_evaluate" not in tools
    assert "mcp__playwright__browser_file_upload" not in tools
    assert "mcp__playwright__browser_drag" not in tools
    assert "mcp__playwright__browser_run_code" not in tools
    assert "mcp__playwright__browser_close" not in tools
    assert "mcp__playwright__browser_start_video" not in tools
    assert "mcp__playwright__browser_stop_video" not in tools
    assert "mcp__playwright__browser_video_chapter" not in tools


def test_advanced_explorer_profile_allows_run_code_escape_hatch_without_media_or_upload(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright")
    monkeypatch.chdir(tmp_path)

    tools = get_agent_allowed_tools("app-explorer-advanced")

    assert "mcp__playwright__browser_snapshot" in tools
    assert "mcp__playwright__browser_evaluate" in tools
    assert "mcp__playwright__browser_hover" in tools
    assert "mcp__playwright__browser_run_code" in tools
    assert "mcp__playwright__browser_file_upload" not in tools
    assert "mcp__playwright__browser_drag" not in tools
    assert "mcp__playwright__browser_close" not in tools
    assert "mcp__playwright__browser_start_video" not in tools
    assert "mcp__playwright__browser_stop_video" not in tools
    assert "mcp__playwright__browser_video_chapter" not in tools


def test_agent_allowlist_can_use_run_local_mcp_config(tmp_path, monkeypatch):
    root_dir = tmp_path / "root"
    run_dir = tmp_path / "run"
    root_dir.mkdir()
    run_dir.mkdir()
    _write_mcp_config(root_dir, "playwright")
    _write_mcp_config(run_dir, "playwright-test")
    monkeypatch.chdir(root_dir)

    tools = get_agent_allowed_tools("playwright-test-planner", mcp_config_dir=run_dir)

    assert "mcp__playwright-test__planner_setup_page" in tools
    assert "mcp__playwright-test__planner_save_plan" in tools
    assert "mcp__playwright-test__generator_write_test" in tools
    assert "mcp__playwright-test__test_debug" in tools
    assert "mcp__playwright-test__test_run" in tools
    assert "mcp__playwright__planner_setup_page" not in tools


def test_planner_and_healer_allow_note_tool_only_when_configured(tmp_path, monkeypatch):
    root_dir = tmp_path / "root"
    run_dir = tmp_path / "run"
    root_dir.mkdir()
    run_dir.mkdir()
    _write_mcp_config(root_dir, "playwright-test")
    (run_dir / ".mcp.json").write_text(
        """
{
  "mcpServers": {
    "playwright-test": {
      "command": "npx",
      "args": ["playwright", "run-test-mcp-server"]
    },
    "quorvex-agent": {
      "command": "python",
      "args": ["tools/agent_note_mcp/server.py"]
    }
  }
}
"""
    )
    monkeypatch.chdir(root_dir)

    root_tools = get_agent_allowed_tools("playwright-test-healer")
    planner_tools = get_agent_allowed_tools("playwright-test-planner", mcp_config_dir=run_dir)
    healer_tools = get_agent_allowed_tools("playwright-test-healer", mcp_config_dir=run_dir)
    generator_tools = get_agent_allowed_tools("playwright-test-generator", mcp_config_dir=run_dir)

    assert "mcp__quorvex-agent__quorvex_record_note" not in root_tools
    assert "mcp__quorvex-agent__quorvex_record_note" in planner_tools
    assert "mcp__quorvex-agent__quorvex_record_note" in healer_tools
    assert "mcp__quorvex-agent__quorvex_record_note" not in generator_tools


def test_prd_only_planner_profile_has_no_tools(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright-test")
    monkeypatch.chdir(tmp_path)

    assert get_agent_allowed_tools("prd-only-planner") == []


def test_prd_live_planner_allows_only_prd_browser_tools(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright-test")
    monkeypatch.chdir(tmp_path)

    tools = set(get_agent_allowed_tools("prd-live-planner"))

    assert "mcp__playwright-test__planner_setup_page" in tools
    assert "mcp__playwright-test__planner_save_plan" in tools
    assert "mcp__playwright-test__generator_write_test" in tools
    assert "mcp__playwright-test__browser_navigate" in tools
    assert "mcp__playwright-test__browser_snapshot" in tools
    assert "mcp__playwright-test__browser_handle_dialog" in tools
    assert "mcp__playwright-test__test_debug" in tools
    assert "mcp__playwright-test__test_run" in tools
    assert "mcp__playwright-test__browser_close" not in tools
    assert "mcp__playwright-test__browser_evaluate" not in tools
    assert "mcp__playwright-test__browser_run_code" not in tools
    assert "Glob" not in tools
    assert "Grep" not in tools
    assert "Read" not in tools
    assert "LS" not in tools
    assert "mcp__playwright-test__browser_console_messages" in tools
    assert "mcp__playwright-test__browser_network_requests" in tools


def test_prd_live_planner_tool_config_keeps_debug_browser_open(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright-test")
    monkeypatch.chdir(tmp_path)

    config = get_agent_tool_config("prd-live-planner")
    allowed_tools = set(config["allowed_tools"])
    visible_tools = set(config["tools"])
    assert "mcp__playwright-test__browser_close" not in allowed_tools
    assert "mcp__playwright-test__browser_close" not in visible_tools
    assert "mcp__playwright-test__browser_handle_dialog" in allowed_tools
    assert "mcp__playwright-test__browser_handle_dialog" in visible_tools
    assert "mcp__playwright-test__browser_run_code" not in allowed_tools
    assert "mcp__playwright-test__browser_evaluate" not in visible_tools


def test_known_profiles_do_not_grant_wildcards(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright-test")
    monkeypatch.chdir(tmp_path)

    for profile_name in AGENT_TOOL_PROFILES:
        tools = get_agent_allowed_tools(profile_name)
        assert "*" not in tools
        assert not any(tool == "mcp__*__*" for tool in tools)


def test_static_analysis_profiles_except_coverage_remain_read_only(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright-test")
    monkeypatch.chdir(tmp_path)

    read_only_profiles = [
        "security-analyzer",
        "bug-report-generator",
        "database-analyzer",
        "load-test-analyzer",
    ]
    for profile_name in read_only_profiles:
        assert get_agent_allowed_tools(profile_name) == ["Glob", "Grep", "Read", "LS"]

    coverage_tools = get_agent_allowed_tools("test-coverage-analyzer")
    assert "mcp__playwright-test__browser_snapshot" in coverage_tools
    assert "mcp__playwright-test__browser_run_code" not in coverage_tools
    assert get_agent_allowed_tools("load-test-generator") == ["Glob", "Grep", "Read", "LS", "Write"]


def test_all_claude_agent_files_have_tool_profiles():
    root = Path(__file__).resolve().parents[2]
    agent_files = sorted(root.joinpath(".claude", "agents").glob("*.md"))

    missing = [
        _agent_profile_name(agent_file)
        for agent_file in agent_files
        if _agent_profile_name(agent_file) not in AGENT_TOOL_PROFILES
    ]

    assert missing == []


def test_static_mcp_agent_frontmatter_matches_runtime_profiles(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright-test")
    monkeypatch.chdir(tmp_path)
    root = Path(__file__).resolve().parents[2]
    checked_profiles = {
        "app-explorer",
        "api-explorer",
        "test-validator",
        "test-operator",
        "test-coverage-analyzer",
        "playwright-test-planner",
        "playwright-test-generator",
        "playwright-test-healer",
    }

    for agent_file in root.joinpath(".claude", "agents").glob("*.md"):
        profile_name = _agent_profile_name(agent_file)
        if profile_name not in checked_profiles:
            continue
        assert _agent_frontmatter_tools(agent_file) == get_agent_allowed_tools(profile_name)


def test_base_agent_known_profile_uses_explicit_tools(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright-test")
    monkeypatch.chdir(tmp_path)

    agent = BaseAgent()
    agent.agent_tool_profile = "test-validator"

    config = agent._resolved_tool_config()

    assert config["allowed_tools"] == config["tools"]
    assert "mcp__playwright-test__test_run" in config["allowed_tools"]
    assert "*" not in config["allowed_tools"]


def test_generator_and_healer_profiles_allow_debug_without_browser_close(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright-test")
    monkeypatch.chdir(tmp_path)

    for profile_name in ("playwright-test-generator", "playwright-test-healer"):
        config = get_agent_tool_config(profile_name)
        allowed_tools = set(config["allowed_tools"])
        visible_tools = set(config["tools"])

        assert "mcp__playwright-test__test_debug" in allowed_tools
        assert "mcp__playwright-test__test_run" in allowed_tools
        assert "mcp__playwright-test__browser_close" not in allowed_tools
        assert "mcp__playwright-test__browser_close" not in visible_tools
        assert "mcp__playwright-test__browser_run_code" not in allowed_tools
        assert "mcp__playwright-test__browser_file_upload" not in allowed_tools


def test_generator_tool_config_allows_script_debug_without_browser_close(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright-test")
    monkeypatch.chdir(tmp_path)

    config = get_agent_tool_config("playwright-test-generator")

    assert "mcp__playwright-test__browser_run_code" not in config["allowed_tools"]
    assert "mcp__playwright-test__browser_run_code" not in config["tools"]
    assert "mcp__playwright-test__browser_close" not in config["allowed_tools"]
    assert "mcp__playwright-test__browser_close" not in config["tools"]
    assert "mcp__playwright-test__browser_evaluate" in config["allowed_tools"]
    assert "mcp__playwright-test__browser_snapshot" in config["allowed_tools"]
    assert "mcp__playwright-test__browser_verify_value" in config["allowed_tools"]


def test_base_agent_unknown_profile_falls_back_to_read_only_tools():
    agent = BaseAgent()
    agent.agent_tool_profile = "unknown-profile"

    config = agent._resolved_tool_config()

    assert config == {
        "allowed_tools": ["Glob", "Grep", "Read", "LS"],
        "tools": ["Glob", "Grep", "Read", "LS"],
    }
    assert agent._resolved_permission_mode() == "dontAsk"


def test_base_agent_explicit_wildcard_is_preserved():
    agent = BaseAgent()
    agent.allowed_tools = ["*"]

    config = agent._resolved_tool_config()

    assert config["allowed_tools"] == ["*"]
    assert config["tools"] is None


def test_base_agent_known_profile_uses_run_local_mcp_config(tmp_path, monkeypatch):
    root_dir = tmp_path / "root"
    run_dir = tmp_path / "run"
    root_dir.mkdir()
    run_dir.mkdir()
    _write_mcp_config(root_dir, "playwright")
    _write_mcp_config(run_dir, "playwright-test")
    monkeypatch.chdir(root_dir)

    agent = BaseAgent()
    agent.agent_tool_profile = "app-explorer"
    agent.agent_cwd = str(run_dir)

    config = agent._resolved_tool_config()

    assert "mcp__playwright-test__browser_navigate" in config["allowed_tools"]
    assert "mcp__playwright__browser_navigate" not in config["allowed_tools"]


@pytest.mark.asyncio
async def test_base_agent_queue_marks_explorer_browser_tasks_live(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright")
    captured: dict = {}

    class FakeQueue:
        async def connect(self):
            return None

        async def get_metrics(self):
            return {"workers_alive": 1, "queue_length": 0, "running": 0}

        async def enqueue_task(self, **kwargs):
            captured.update(kwargs)
            return "agent-task-live"

        async def wait_for_result(self, task_id, timeout, poll_interval, on_progress):
            return "{}"

    monkeypatch.setattr(base_agent_module, "get_agent_queue", lambda: FakeQueue())
    monkeypatch.setattr(
        BaseAgent,
        "_refresh_runtime_settings",
        lambda self: (
            {},
            SimpleNamespace(
                runtime="claude_sdk",
                provider="anthropic_compatible",
                api_key="sk-test",
                base_url="https://api.z.ai/api/anthropic",
                model="glm-5.1",
                tier="tool_deep",
            ),
        ),
    )

    agent = BaseAgent()
    agent.agent_tool_profile = "app-explorer"
    agent.agent_cwd = str(tmp_path)

    await agent._query_agent_via_queue("explore", timeout_seconds=30)

    assert captured["requires_live_browser"] is True
    assert "mcp__playwright__browser_navigate" in captured["allowed_tools"]
    assert captured["cwd"] == str(tmp_path)


def test_base_agent_refreshes_settings_runtime_env(monkeypatch):
    from orchestrator.api import settings as settings_api
    from orchestrator.services import ai_runtime_config

    captured: dict = {}

    def fake_runtime_env_vars():
        return {
            "QUORVEX_AGENT_RUNTIME": "claude_sdk",
            "QUORVEX_LLM_API_KEY": "settings-key",
            "QUORVEX_LLM_BASE_URL": "https://settings.example/anthropic",
            "QUORVEX_LLM_TOOL_DEEP_MODEL": "settings-tool-model",
        }

    def fake_apply_runtime_settings(env_vars):
        captured["applied_settings"] = dict(env_vars)

    def fake_apply_runtime_env_aliases(env_vars, *, tier="standard", model_override=None):
        captured["alias_env_vars"] = dict(env_vars)
        captured["tier"] = tier
        return SimpleNamespace(
            runtime="claude_sdk",
            provider="anthropic_compatible",
            api_key=env_vars["QUORVEX_LLM_API_KEY"],
            base_url=env_vars["QUORVEX_LLM_BASE_URL"],
            model=env_vars["QUORVEX_LLM_TOOL_DEEP_MODEL"],
            tier=tier,
        )

    monkeypatch.delenv("QUORVEX_RUN_MODEL_TIER", raising=False)
    monkeypatch.setattr(settings_api, "runtime_env_vars", fake_runtime_env_vars)
    monkeypatch.setattr(settings_api, "_apply_runtime_settings", fake_apply_runtime_settings)
    monkeypatch.setattr(ai_runtime_config, "apply_runtime_env_aliases", fake_apply_runtime_env_aliases)

    agent = object.__new__(BaseAgent)
    _, selection = agent._refresh_runtime_settings()

    assert captured["applied_settings"]["QUORVEX_LLM_API_KEY"] == "settings-key"
    assert captured["alias_env_vars"]["QUORVEX_LLM_BASE_URL"] == "https://settings.example/anthropic"
    assert captured["tier"] == "tool_deep"
    assert selection.model == "settings-tool-model"
    assert os.environ["QUORVEX_RUN_MODEL_TIER"] == "tool_deep"


@pytest.mark.asyncio
async def test_base_agent_queue_forwards_settings_runtime_env(tmp_path, monkeypatch):
    captured: dict = {}

    class FakeQueue:
        async def connect(self):
            return None

        async def get_metrics(self):
            return {"workers_alive": 1, "queue_length": 0, "running": 0}

        async def enqueue_task(self, **kwargs):
            captured.update(kwargs)
            return "agent-task-env"

        async def wait_for_result(self, task_id, timeout, poll_interval, on_progress):
            return "{}"

    for key in (
        "QUORVEX_LLM_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(base_agent_module, "get_agent_queue", lambda: FakeQueue())
    monkeypatch.setattr(
        BaseAgent,
        "_refresh_runtime_settings",
        lambda self: (
            {
                "QUORVEX_AGENT_RUNTIME": "claude_sdk",
                "QUORVEX_LLM_API_KEY": "settings-key",
                "QUORVEX_LLM_BASE_URL": "https://settings.example/anthropic",
                "QUORVEX_LLM_TOOL_DEEP_MODEL": "settings-tool-model",
            },
            SimpleNamespace(
                runtime="claude_sdk",
                provider="anthropic_compatible",
                api_key="settings-key",
                base_url="https://settings.example/anthropic",
                model="settings-tool-model",
                tier="tool_deep",
            ),
        ),
    )

    agent = BaseAgent()
    agent.agent_cwd = str(tmp_path)

    await agent._query_agent_via_queue("explore", timeout_seconds=30)

    env_vars = captured["env_vars"]
    assert env_vars["QUORVEX_AGENT_RUNTIME"] == "claude_sdk"
    assert env_vars["QUORVEX_LLM_API_KEY"] == "settings-key"
    assert env_vars["ANTHROPIC_AUTH_TOKEN"] == "settings-key"
    assert env_vars["ANTHROPIC_API_KEY"] == "settings-key"
    assert env_vars["ANTHROPIC_BASE_URL"] == "https://settings.example/anthropic"
    assert env_vars["ANTHROPIC_MODEL"] == "settings-tool-model"
    assert env_vars["QUORVEX_RUN_MODEL_TIER"] == "tool_deep"


@pytest.mark.asyncio
async def test_base_agent_queue_fails_fast_without_claude_auth(tmp_path, monkeypatch):
    class FakeQueue:
        async def connect(self):
            return None

        async def get_metrics(self):
            return {"workers_alive": 1, "queue_length": 0, "running": 0}

        async def enqueue_task(self, **kwargs):
            raise AssertionError("queue should not be used without Claude SDK auth")

    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(base_agent_module, "get_agent_queue", lambda: FakeQueue())
    monkeypatch.setattr(
        BaseAgent,
        "_refresh_runtime_settings",
        lambda self: (
            {"QUORVEX_AGENT_RUNTIME": "claude_sdk"},
            SimpleNamespace(
                runtime="claude_sdk",
                provider="anthropic_compatible",
                api_key="",
                base_url="https://api.z.ai/api/anthropic",
                model="glm-5.1",
                tier="tool_deep",
            ),
        ),
    )

    agent = BaseAgent()
    agent.agent_cwd = str(tmp_path)

    with pytest.raises(RuntimeError, match="Claude SDK runtime is not authenticated"):
        await agent._query_agent_via_queue("explore", timeout_seconds=30)


def test_base_agent_unknown_profile_uses_conservative_fallback():
    agent = BaseAgent()

    assert agent._resolved_tool_config()["allowed_tools"] == ["Glob", "Grep", "Read", "LS"]
    assert agent._resolved_permission_mode() == "dontAsk"


def test_no_runtime_agent_wildcard_call_sites():
    root = Path(__file__).resolve().parents[2]
    checked_files = [
        *root.joinpath(".claude", "agents").glob("*.md"),
        *root.joinpath("orchestrator", "workflows").glob("*.py"),
        root / "CLAUDE.md",
    ]

    for path in checked_files:
        text = path.read_text()
        assert 'allowed_tools=["*"]' not in text, path
        assert "mcp__*__*" not in text, path
        if path.name not in {
            "playwright-test-generator.md",
            "playwright-test-planner.md",
            "full_native_pipeline.py",
                "native_generator.py",
                "native_planner.py",
                "native_healer.py",
                "playwright-test-healer.md",
            }:
                assert "test_debug" not in text, path
