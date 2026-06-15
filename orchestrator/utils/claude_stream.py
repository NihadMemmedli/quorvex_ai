"""Utilities for reading Claude SDK and stream-json events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedToolUse:
    id: str | None
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ParsedToolResult:
    tool_use_id: str | None
    content: Any
    is_error: bool


def event_type(event: Any) -> str:
    value = _field(event, "type", "unknown")
    return str(value or "unknown")


def event_content_items(event: Any) -> list[Any]:
    """Return top-level content blocks from SDK objects and JSON events."""
    content = _field(event, "content", None)
    if content is None:
        content = _field(_field(event, "message", None), "content", None)
    if isinstance(content, (list, tuple)):
        return list(content)
    if content is None or isinstance(content, str):
        return []
    return [content]


def event_tool_uses(event: Any) -> list[ParsedToolUse]:
    items: list[Any] = []
    if event_type(event) == "tool_use":
        items.append(event)
    for content in event_content_items(event):
        items.extend(_iter_items_by_type(content, "tool_use"))

    parsed: list[ParsedToolUse] = []
    for item in items:
        name = str(_field(item, "name", "") or "")
        if not name:
            continue
        raw_input = _field(item, "input", None)
        parsed.append(
            ParsedToolUse(
                id=_optional_str(_field(item, "id", None)),
                name=name,
                input=dict(raw_input) if isinstance(raw_input, dict) else {},
            )
        )
    return parsed


def event_tool_results(event: Any) -> list[ParsedToolResult]:
    items: list[Any] = []
    if event_type(event) == "tool_result":
        items.append(event)
    for content in event_content_items(event):
        items.extend(_iter_items_by_type(content, "tool_result"))

    parsed: list[ParsedToolResult] = []
    for item in items:
        parsed.append(
            ParsedToolResult(
                tool_use_id=_optional_str(_field(item, "tool_use_id", None)),
                content=_field(item, "content", None),
                is_error=bool(_field(item, "is_error", False) or _field(item, "error", False)),
            )
        )
    return parsed


def event_text_blocks(event: Any) -> list[str]:
    """Return assistant/top-level text blocks without descending into tool results."""
    if event_type(event) == "text":
        text = _field(event, "text", "")
        return [str(text)] if text else []

    texts: list[str] = []
    for item in event_content_items(event):
        if _field(item, "type", None) == "text":
            text = _field(item, "text", "")
            if text:
                texts.append(str(text))
    return texts


def tool_result_text(content: Any) -> str:
    """Extract text from common Claude tool_result content shapes."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if content.get("type") == "text":
            return str(content.get("text") or "")
        if content.get("type") == "tool_result":
            return tool_result_text(content.get("content"))
        for key in ("content", "text", "result"):
            if key in content:
                text = tool_result_text(content.get(key))
                if text:
                    return text
        return ""
    if isinstance(content, (list, tuple)):
        parts = [tool_result_text(item) for item in content]
        return "\n".join(part for part in parts if part)
    return str(content)


def _field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _iter_items_by_type(value: Any, item_type: str):
    if isinstance(value, dict):
        if value.get("type") == item_type:
            yield value
        for key, child in value.items():
            if key == "input":
                continue
            if isinstance(child, (dict, list, tuple)) or _is_sdk_block(child):
                yield from _iter_items_by_type(child, item_type)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_items_by_type(child, item_type)
    elif _is_sdk_block(value):
        if _field(value, "type", None) == item_type:
            yield value
        for child_name in ("message", "content", "result"):
            child = _field(value, child_name, None)
            if child is not None:
                yield from _iter_items_by_type(child, item_type)


def _is_sdk_block(value: Any) -> bool:
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return False
    return hasattr(value, "type") or hasattr(value, "content") or hasattr(value, "message")
