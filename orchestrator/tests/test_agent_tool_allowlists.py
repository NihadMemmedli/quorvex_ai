import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.agents.base_agent import BaseAgent
from orchestrator.utils.agent_tool_allowlists import AGENT_TOOL_PROFILES, get_agent_allowed_tools


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
    assert "mcp__playwright-test__browser_start_tracing" in tools
    assert "mcp__playwright-test__browser_resume" in tools


def test_agent_allowlist_uses_root_playwright_prefix(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright")
    monkeypatch.chdir(tmp_path)

    tools = get_agent_allowed_tools("app-explorer")

    assert {"Glob", "Grep", "Read", "LS"} <= set(tools)
    assert "mcp__playwright__browser_snapshot" in tools
    assert "mcp__playwright__browser_network_requests" in tools


def test_known_profiles_do_not_grant_wildcards(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright-test")
    monkeypatch.chdir(tmp_path)

    for profile_name in AGENT_TOOL_PROFILES:
        tools = get_agent_allowed_tools(profile_name)
        assert "*" not in tools
        assert not any(tool == "mcp__*__*" for tool in tools)


def test_base_agent_known_profile_uses_explicit_tools(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright-test")
    monkeypatch.chdir(tmp_path)

    agent = BaseAgent()
    agent.agent_tool_profile = "test-validator"

    config = agent._resolved_tool_config()

    assert config["allowed_tools"] == config["tools"]
    assert "mcp__playwright-test__test_run" in config["allowed_tools"]
    assert "*" not in config["allowed_tools"]


def test_base_agent_unknown_profile_keeps_legacy_fallback():
    agent = BaseAgent()

    assert agent._resolved_tool_config()["allowed_tools"] == ["*"]


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
        assert "test_debug" not in text, path
