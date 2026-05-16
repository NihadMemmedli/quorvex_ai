"""Least-privilege tool profiles for Claude agents.

Profiles intentionally describe tool *roles* rather than call sites. Workflow
code should ask for a named profile and let the helper apply the active MCP
server prefix from the current `.mcp.json`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from orchestrator.utils.agent_runner import build_allowed_tools
except ImportError:  # Support scripts that import from `utils.*`.
    from utils.agent_runner import build_allowed_tools


@dataclass(frozen=True)
class AgentToolProfile:
    """Tool profile before MCP server prefixing."""

    base_tools: tuple[str, ...] = ()
    playwright_mcp_tools: tuple[str, ...] = ()


EXPLORER_MCP_TOOLS: tuple[str, ...] = (
    "browser_click",
    "browser_close",
    "browser_console_messages",
    "browser_drag",
    "browser_evaluate",
    "browser_file_upload",
    "browser_handle_dialog",
    "browser_hover",
    "browser_navigate",
    "browser_navigate_back",
    "browser_network_requests",
    "browser_press_key",
    "browser_select_option",
    "browser_snapshot",
    "browser_take_screenshot",
    "browser_type",
    "browser_wait_for",
)

PLANNER_MCP_TOOLS: tuple[str, ...] = EXPLORER_MCP_TOOLS + (
    "planner_setup_page",
    "planner_save_plan",
)

GENERATOR_MCP_TOOLS: tuple[str, ...] = (
    "browser_click",
    "browser_close",
    "browser_drag",
    "browser_evaluate",
    "browser_file_upload",
    "browser_handle_dialog",
    "browser_hover",
    "browser_navigate",
    "browser_press_key",
    "browser_select_option",
    "browser_snapshot",
    "browser_type",
    "browser_verify_element_visible",
    "browser_verify_list_visible",
    "browser_verify_text_visible",
    "browser_verify_value",
    "browser_wait_for",
    "generator_read_log",
    "generator_setup_page",
    "generator_write_test",
)

HEALER_MCP_TOOLS: tuple[str, ...] = (
    "browser_close",
    "browser_console_messages",
    "browser_evaluate",
    "browser_generate_locator",
    "browser_handle_dialog",
    "browser_network_requests",
    "browser_resume",
    "browser_snapshot",
    "browser_start_tracing",
    "browser_stop_tracing",
    "test_list",
    "test_run",
)

TEST_VALIDATOR_MCP_TOOLS: tuple[str, ...] = (
    "browser_close",
    "browser_console_messages",
    "browser_evaluate",
    "browser_generate_locator",
    "browser_handle_dialog",
    "browser_navigate",
    "browser_network_requests",
    "browser_snapshot",
    "browser_wait_for",
    "test_run",
)

TEST_OPERATOR_MCP_TOOLS: tuple[str, ...] = (
    "browser_click",
    "browser_drag",
    "browser_file_upload",
    "browser_handle_dialog",
    "browser_hover",
    "browser_navigate",
    "browser_navigate_back",
    "browser_press_key",
    "browser_select_option",
    "browser_snapshot",
    "browser_take_screenshot",
    "browser_type",
    "browser_wait_for",
)


AGENT_TOOL_PROFILES: dict[str, AgentToolProfile] = {
    "app-explorer": AgentToolProfile(("Glob", "Grep", "Read", "LS"), EXPLORER_MCP_TOOLS),
    "api-explorer": AgentToolProfile(("Glob", "Grep", "Read", "LS"), EXPLORER_MCP_TOOLS),
    "playwright-test-planner": AgentToolProfile(("Glob", "Grep", "Read", "LS"), PLANNER_MCP_TOOLS),
    "playwright-test-generator": AgentToolProfile(("Glob", "Grep", "Read", "LS"), GENERATOR_MCP_TOOLS),
    "playwright-test-healer": AgentToolProfile(
        ("Glob", "Grep", "Read", "LS", "Edit", "MultiEdit", "Write"),
        HEALER_MCP_TOOLS,
    ),
    "test-validator": AgentToolProfile(("Read", "Write", "Bash"), TEST_VALIDATOR_MCP_TOOLS),
    "test-operator": AgentToolProfile((), TEST_OPERATOR_MCP_TOOLS),
    "playwright-skill-executor": AgentToolProfile(("Read", "Write", "Bash", "Glob", "Grep"), ()),
    "text-analysis": AgentToolProfile((), ()),
}

AGENT_CLASS_PROFILE_ALIASES: dict[str, str] = {
    "ExploratoryAgent": "app-explorer",
    "SpecWriterAgent": "app-explorer",
    "SpecSynthesisAgent": "text-analysis",
    "PrerequisitesAgent": "text-analysis",
}


def normalize_agent_profile_name(agent_name: str | None) -> str | None:
    """Resolve class names and loose agent names to profile keys."""
    if not agent_name:
        return None
    if agent_name in AGENT_TOOL_PROFILES:
        return agent_name
    if agent_name in AGENT_CLASS_PROFILE_ALIASES:
        return AGENT_CLASS_PROFILE_ALIASES[agent_name]
    normalized = agent_name.replace("_", "-").lower()
    return normalized if normalized in AGENT_TOOL_PROFILES else None


def get_agent_allowed_tools(agent_name: str | None) -> list[str] | None:
    """Return an explicitly prefixed allowlist for a known agent profile."""
    profile_name = normalize_agent_profile_name(agent_name)
    if profile_name is None:
        return None
    profile = AGENT_TOOL_PROFILES[profile_name]
    return build_allowed_tools(list(profile.base_tools), list(profile.playwright_mcp_tools))


def get_agent_tool_config(agent_name: str | None) -> dict[str, Any]:
    """Return SDK/CLI tool config for a known agent profile.

    `allowed_tools` controls approval. `tools` controls availability. Keeping
    them equal prevents known agents from seeing broader tools than they can use.
    Unknown agents return an empty config so legacy fallback behavior is
    preserved by callers that still need it.
    """
    allowed_tools = get_agent_allowed_tools(agent_name)
    if allowed_tools is None:
        return {}
    return {"allowed_tools": allowed_tools, "tools": list(allowed_tools)}
