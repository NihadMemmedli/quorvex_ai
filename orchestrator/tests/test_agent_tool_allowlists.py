import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.agents.base_agent import BaseAgent
from orchestrator.utils.agent_tool_allowlists import AGENT_TOOL_PROFILES, get_agent_allowed_tools


def _agent_profile_name(agent_file: Path) -> str:
    text = agent_file.read_text()
    match = re.match(r"^---\n(?P<frontmatter>.*?)\n---\n", text, re.DOTALL)
    if not match:
        return agent_file.stem
    name_match = re.search(r"^name:\s*(?P<name>[^\n]+?)\s*$", match.group("frontmatter"), re.MULTILINE)
    return name_match.group("name").strip("\"'") if name_match else agent_file.stem


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
    assert "mcp__playwright__planner_setup_page" not in tools


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
    assert "mcp__playwright-test__browser_navigate" in tools
    assert "mcp__playwright-test__browser_snapshot" in tools
    assert "Glob" not in tools
    assert "Grep" not in tools
    assert "Read" not in tools
    assert "LS" not in tools
    assert "mcp__playwright-test__browser_evaluate" not in tools
    assert "mcp__playwright-test__browser_network_requests" not in tools


def test_known_profiles_do_not_grant_wildcards(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright-test")
    monkeypatch.chdir(tmp_path)

    for profile_name in AGENT_TOOL_PROFILES:
        tools = get_agent_allowed_tools(profile_name)
        assert "*" not in tools
        assert not any(tool == "mcp__*__*" for tool in tools)


def test_pr5_static_analysis_profiles_are_least_privilege(tmp_path, monkeypatch):
    _write_mcp_config(tmp_path, "playwright-test")
    monkeypatch.chdir(tmp_path)

    read_only_profiles = [
        "security-analyzer",
        "bug-report-generator",
        "database-analyzer",
        "load-test-analyzer",
        "test-coverage-analyzer",
    ]
    for profile_name in read_only_profiles:
        assert get_agent_allowed_tools(profile_name) == ["Glob", "Grep", "Read", "LS"]

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
