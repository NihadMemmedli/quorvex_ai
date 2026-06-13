"""Shared prompt policy for recovering from browser beforeunload dialogs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

BROWSER_DIALOG_RECOVERY_TITLE = "## Browser Dialog Recovery"

BROWSER_DIALOG_RECOVERY_POLICY = """## Browser Dialog Recovery
When a "Leave site?", unsaved changes, or beforeunload dialog appears:
- Immediately call `browser_handle_dialog` with `accept: true` to accept Leave and continue navigation.
- After handling it, call `browser_snapshot` or `browser_take_screenshot` to verify page state.
- Preserve draft data only if the user explicitly requested it.
"""


def _tool_names(source: Any) -> Iterable[str]:
    if source is None:
        return ()
    if isinstance(source, str):
        return (source,)
    if isinstance(source, dict):
        names: list[str] = []
        for key, value in source.items():
            names.append(str(key))
            names.append(str(value))
        return names
    if isinstance(source, Iterable):
        return (str(item) for item in source)
    return (str(source),)


def _is_dialog_tool(tool_name: str) -> bool:
    name = tool_name.strip()
    return (
        name == "*"
        or name == "browser_dialog"
        or name == "browser_handle_dialog"
        or name.endswith("__browser_handle_dialog")
    )


def has_browser_dialog_tool(
    *tool_sources: Any,
    disallowed_tools: list[str] | tuple[str, ...] | None = None,
) -> bool:
    """Return True when available tools include browser dialog handling."""

    disallowed = {str(tool).strip() for tool in (disallowed_tools or [])}
    if any(_is_dialog_tool(tool) for tool in disallowed):
        return False
    return any(_is_dialog_tool(tool) for source in tool_sources for tool in _tool_names(source))


def browser_dialog_recovery_policy_for_tools(
    *tool_sources: Any,
    disallowed_tools: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Return the recovery policy only for agents that can handle browser dialogs."""

    if not has_browser_dialog_tool(*tool_sources, disallowed_tools=disallowed_tools):
        return ""
    return BROWSER_DIALOG_RECOVERY_POLICY


def append_browser_dialog_recovery_policy(
    text: str,
    *tool_sources: Any,
    disallowed_tools: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Append the shared dialog policy to text when applicable and not already present."""

    policy = browser_dialog_recovery_policy_for_tools(
        *tool_sources,
        disallowed_tools=disallowed_tools,
    )
    if not policy or BROWSER_DIALOG_RECOVERY_TITLE in text:
        return text
    return f"{text.rstrip()}\n\n{policy}".rstrip()
