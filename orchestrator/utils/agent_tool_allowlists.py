"""Tool profiles for Claude agents.

Profiles intentionally describe tool *roles* rather than call sites. Workflow
code should ask for a named profile and let the helper apply the active MCP
server prefix from the current `.mcp.json`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from orchestrator.utils.agent_runner import build_allowed_tools, build_mcp_allowed_tools
except ImportError:  # Support scripts that import from `utils.*`.
    from utils.agent_runner import build_allowed_tools, build_mcp_allowed_tools


@dataclass(frozen=True)
class AgentToolProfile:
    """Tool profile before MCP server prefixing."""

    base_tools: tuple[str, ...] = ()
    playwright_mcp_tools: tuple[str, ...] = ()
    disallowed_playwright_mcp_tools: tuple[str, ...] = ()


BROWSER_MCP_TOOLS: tuple[str, ...] = (
    "browser_click",
    "browser_console_messages",
    "browser_drag",
    "browser_evaluate",
    "browser_file_upload",
    "browser_fill_form",
    "browser_generate_locator",
    "browser_handle_dialog",
    "browser_hover",
    "browser_navigate",
    "browser_navigate_back",
    "browser_network_requests",
    "browser_press_key",
    "browser_resume",
    "browser_resize",
    "browser_run_code",
    "browser_select_option",
    "browser_snapshot",
    "browser_start_tracing",
    "browser_start_video",
    "browser_stop_tracing",
    "browser_stop_video",
    "browser_take_screenshot",
    "browser_type",
    "browser_verify_element_visible",
    "browser_verify_list_visible",
    "browser_verify_text_visible",
    "browser_verify_value",
    "browser_video_chapter",
    "browser_wait_for",
)

OBSERVE_BROWSER_MCP_TOOLS: tuple[str, ...] = (
    "browser_snapshot",
    "browser_take_screenshot",
    "browser_console_messages",
    "browser_network_requests",
    "browser_wait_for",
    "browser_resize",
)

INTERACT_BROWSER_MCP_TOOLS: tuple[str, ...] = OBSERVE_BROWSER_MCP_TOOLS + (
    "browser_navigate",
    "browser_navigate_back",
    "browser_click",
    "browser_type",
    "browser_fill_form",
    "browser_select_option",
    "browser_press_key",
    "browser_hover",
    "browser_handle_dialog",
)

TEST_AUTHORING_BROWSER_MCP_TOOLS: tuple[str, ...] = INTERACT_BROWSER_MCP_TOOLS + (
    "browser_generate_locator",
    "browser_verify_element_visible",
    "browser_verify_list_visible",
    "browser_verify_text_visible",
    "browser_verify_value",
)

DEBUG_BROWSER_MCP_TOOLS: tuple[str, ...] = TEST_AUTHORING_BROWSER_MCP_TOOLS + (
    "browser_evaluate",
    "browser_resume",
    "browser_start_tracing",
    "browser_stop_tracing",
)

ADVANCED_DEBUG_BROWSER_MCP_TOOLS: tuple[str, ...] = DEBUG_BROWSER_MCP_TOOLS + (
    "browser_run_code",
)

EXPLORER_BASIC_MCP_TOOLS: tuple[str, ...] = INTERACT_BROWSER_MCP_TOOLS

EXPLORER_ADVANCED_MCP_TOOLS: tuple[str, ...] = ADVANCED_DEBUG_BROWSER_MCP_TOOLS

EXPLORER_MCP_TOOLS: tuple[str, ...] = EXPLORER_BASIC_MCP_TOOLS

PLANNER_MCP_TOOLS: tuple[str, ...] = TEST_AUTHORING_BROWSER_MCP_TOOLS + (
    "planner_setup_page",
    "planner_save_plan",
    "generator_write_test",
    "test_debug",
    "test_run",
)

PRD_LIVE_PLANNER_MCP_TOOLS: tuple[str, ...] = TEST_AUTHORING_BROWSER_MCP_TOOLS + (
    "planner_setup_page",
    "planner_save_plan",
    "generator_write_test",
    "test_debug",
    "test_run",
)

PRD_LIVE_PLANNER_DISALLOWED_MCP_TOOLS: tuple[str, ...] = ()

GENERATOR_MCP_TOOLS: tuple[str, ...] = DEBUG_BROWSER_MCP_TOOLS + (
    "generator_read_log",
    "generator_setup_page",
    "generator_write_test",
    "test_debug",
    "test_run",
)

GENERATOR_DISALLOWED_MCP_TOOLS: tuple[str, ...] = ()

HEALER_MCP_TOOLS: tuple[str, ...] = DEBUG_BROWSER_MCP_TOOLS + (
    "test_debug",
    "test_list",
    "test_run",
)

NOTE_MCP_TOOLS: tuple[str, ...] = ("quorvex_record_note",)

TEST_VALIDATOR_MCP_TOOLS: tuple[str, ...] = DEBUG_BROWSER_MCP_TOOLS + (
    "test_run",
)

TEST_OPERATOR_MCP_TOOLS: tuple[str, ...] = INTERACT_BROWSER_MCP_TOOLS


AGENT_TOOL_PROFILES: dict[str, AgentToolProfile] = {
    "app-explorer": AgentToolProfile(("Glob", "Grep", "Read", "LS"), EXPLORER_BASIC_MCP_TOOLS),
    "app-explorer-basic": AgentToolProfile(("Glob", "Grep", "Read", "LS"), EXPLORER_BASIC_MCP_TOOLS),
    "app-explorer-advanced": AgentToolProfile(("Glob", "Grep", "Read", "LS"), EXPLORER_ADVANCED_MCP_TOOLS),
    "api-explorer": AgentToolProfile(("Glob", "Grep", "Read", "LS"), EXPLORER_MCP_TOOLS),
    "playwright-test-planner": AgentToolProfile(("Glob", "Grep", "Read", "LS"), PLANNER_MCP_TOOLS),
    "prd-only-planner": AgentToolProfile((), ()),
    "prd-live-planner": AgentToolProfile(
        (),
        PRD_LIVE_PLANNER_MCP_TOOLS,
        PRD_LIVE_PLANNER_DISALLOWED_MCP_TOOLS,
    ),
    "playwright-test-generator": AgentToolProfile(
        ("Glob", "Grep", "Read", "LS"),
        GENERATOR_MCP_TOOLS,
        GENERATOR_DISALLOWED_MCP_TOOLS,
    ),
    "playwright-test-healer": AgentToolProfile(
        ("Glob", "Grep", "Read", "LS", "Edit", "MultiEdit", "Write"),
        HEALER_MCP_TOOLS,
    ),
    "test-validator": AgentToolProfile(("Read", "Write", "Bash"), TEST_VALIDATOR_MCP_TOOLS),
    "test-operator": AgentToolProfile((), TEST_OPERATOR_MCP_TOOLS),
    "playwright-skill-executor": AgentToolProfile(("Read", "Write", "Bash", "Glob", "Grep"), ()),
    "api-test-generator": AgentToolProfile(("Glob", "Grep", "Read", "LS", "Write"), ()),
    "bug-report-generator": AgentToolProfile(("Glob", "Grep", "Read", "LS"), ()),
    "database-analyzer": AgentToolProfile(("Glob", "Grep", "Read", "LS"), ()),
    "llm-evaluator": AgentToolProfile((), ()),
    "load-test-analyzer": AgentToolProfile(("Glob", "Grep", "Read", "LS"), ()),
    "load-test-generator": AgentToolProfile(("Glob", "Grep", "Read", "LS", "Write"), ()),
    "security-analyzer": AgentToolProfile(("Glob", "Grep", "Read", "LS"), ()),
    "test-agent": AgentToolProfile(("Read",), ()),
    "test-coverage-analyzer": AgentToolProfile(("Glob", "Grep", "Read", "LS"), EXPLORER_MCP_TOOLS),
    "test-exporter": AgentToolProfile(("Write",), ()),
    "test-planner": AgentToolProfile(("Read",), ()),
    "text-analysis": AgentToolProfile((), ()),
    # Autonomous mission roles are intentionally proposal-only. They can inspect
    # project/app state but repository writes happen only through approval APIs.
    "surface-mapper": AgentToolProfile(("Glob", "Grep", "Read", "LS"), EXPLORER_MCP_TOOLS),
    "explorer": AgentToolProfile(("Glob", "Grep", "Read", "LS"), EXPLORER_MCP_TOOLS),
    "requirements-analyst": AgentToolProfile(("Glob", "Grep", "Read", "LS"), ()),
    "rtm-mapper": AgentToolProfile(("Glob", "Grep", "Read", "LS"), ()),
    "spec-writer": AgentToolProfile(("Glob", "Grep", "Read", "LS"), ()),
    "regression-scout": AgentToolProfile(("Glob", "Grep", "Read", "LS"), TEST_VALIDATOR_MCP_TOOLS),
    "flake-triager": AgentToolProfile(("Glob", "Grep", "Read", "LS"), TEST_VALIDATOR_MCP_TOOLS),
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


def get_agent_allowed_tools(
    agent_name: str | None,
    *,
    mcp_config_dir: Path | str | None = None,
    mcp_config_path: Path | str | None = None,
) -> list[str] | None:
    """Return an explicitly prefixed allowlist for a known agent profile."""
    profile_name = normalize_agent_profile_name(agent_name)
    if profile_name is None:
        return None
    profile = AGENT_TOOL_PROFILES[profile_name]
    allowed_tools = build_allowed_tools(
        list(profile.base_tools),
        list(profile.playwright_mcp_tools),
        mcp_config_dir=mcp_config_dir,
        mcp_config_path=mcp_config_path,
    )
    if profile_name in {"playwright-test-planner", "playwright-test-healer"}:
        note_tools = build_mcp_allowed_tools(
            "quorvex-agent",
            [],
            list(NOTE_MCP_TOOLS),
            mcp_config_dir=mcp_config_dir,
            mcp_config_path=mcp_config_path,
        )
        if note_tools and note_tools[0].startswith("mcp__quorvex-agent__"):
            allowed_tools.extend(note_tools)
    return allowed_tools


def get_agent_tool_config(
    agent_name: str | None,
    *,
    mcp_config_dir: Path | str | None = None,
    mcp_config_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return SDK/CLI tool config for a known agent profile.

    `allowed_tools` controls approval. `tools` controls availability. Keeping
    them equal prevents known agents from seeing broader tools than they can use.
    Unknown agents return an empty config so legacy fallback behavior is
    preserved by callers that still need it.
    """
    allowed_tools = get_agent_allowed_tools(
        agent_name,
        mcp_config_dir=mcp_config_dir,
        mcp_config_path=mcp_config_path,
    )
    if allowed_tools is None:
        return {}
    profile_name = normalize_agent_profile_name(agent_name)
    profile = AGENT_TOOL_PROFILES[profile_name] if profile_name else AgentToolProfile()
    disallowed_tools = build_allowed_tools(
        [],
        list(profile.disallowed_playwright_mcp_tools),
        mcp_config_dir=mcp_config_dir,
        mcp_config_path=mcp_config_path,
    )
    return {
        "allowed_tools": allowed_tools,
        "tools": list(allowed_tools),
        "disallowed_tools": disallowed_tools,
    }
