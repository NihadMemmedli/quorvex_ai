"""Utilities for reading Claude SDK and stream-json events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedToolUse:
    id: str | None
    name: str
    input: dict[str, Any]
    index: int | None = None


@dataclass(frozen=True)
class ParsedToolResult:
    tool_use_id: str | None
    content: Any
    is_error: bool


@dataclass(frozen=True)
class ParsedInputJsonDelta:
    index: int | None
    tool_use_id: str | None
    partial_json: str


@dataclass(frozen=True)
class ParsedContentBlockStop:
    index: int | None
    tool_use_id: str | None


STREAM_EVENT_TYPES = {
    "content_block_start",
    "content_block_delta",
    "content_block_stop",
    "message_delta",
}


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
    for stream_event in _stream_event_payloads(event):
        items.extend(_stream_event_tool_use_items(stream_event))
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
                index=_optional_int(_field(item, "index", None)),
            )
        )
    return parsed


def event_tool_results(event: Any) -> list[ParsedToolResult]:
    items: list[Any] = []
    if event_type(event) == "tool_result":
        items.append(event)
    for stream_event in _stream_event_payloads(event):
        items.extend(_stream_event_tool_result_items(stream_event))
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

    for stream_event in _stream_event_payloads(event):
        texts = _stream_event_text_blocks(stream_event)
        if texts:
            return texts

    texts: list[str] = []
    for item in event_content_items(event):
        if _field(item, "type", None) == "text":
            text = _field(item, "text", "")
            if text:
                texts.append(str(text))
    return texts


def event_input_json_deltas(event: Any) -> list[ParsedInputJsonDelta]:
    parsed: list[ParsedInputJsonDelta] = []
    for stream_event in _stream_event_payloads(event):
        if str(_field(stream_event, "type", "") or "") != "content_block_delta":
            continue
        delta = _field(stream_event, "delta", None)
        if _field(delta, "type", None) != "input_json_delta":
            continue
        partial_json = _field(delta, "partial_json", None)
        if partial_json is None:
            continue
        parsed.append(
            ParsedInputJsonDelta(
                index=_optional_int(_field(stream_event, "index", None)),
                tool_use_id=_optional_str(
                    _field(delta, "id", None)
                    or _field(delta, "tool_use_id", None)
                    or _field(_field(stream_event, "content_block", None), "id", None)
                ),
                partial_json=str(partial_json),
            )
        )
    return parsed


def event_content_block_stops(event: Any) -> list[ParsedContentBlockStop]:
    parsed: list[ParsedContentBlockStop] = []
    for stream_event in _stream_event_payloads(event):
        if str(_field(stream_event, "type", "") or "") != "content_block_stop":
            continue
        block = _field(stream_event, "content_block", None)
        parsed.append(
            ParsedContentBlockStop(
                index=_optional_int(_field(stream_event, "index", None)),
                tool_use_id=_optional_str(
                    _field(stream_event, "id", None)
                    or _field(stream_event, "tool_use_id", None)
                    or _field(block, "id", None)
                ),
            )
        )
    return parsed


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
    value = getattr(item, name, default)
    if name == "type" and value == default:
        return _inferred_sdk_type(item, default)
    return value


def _inferred_sdk_type(item: Any, default: Any = None) -> Any:
    class_name = item.__class__.__name__
    type_by_class = {
        "AssistantMessage": "assistant",
        "UserMessage": "user",
        "SystemMessage": "system",
        "ResultMessage": "result",
        "StreamEvent": "stream_event",
        "HookEventMessage": "hook_event",
        "TextBlock": "text",
        "ThinkingBlock": "thinking",
        "ToolUseBlock": "tool_use",
        "ToolResultBlock": "tool_result",
        "ServerToolUseBlock": "tool_use",
        "ServerToolResultBlock": "tool_result",
    }
    return type_by_class.get(class_name, default)


def _stream_event_payload(event: Any) -> Any:
    payloads = _stream_event_payloads(event)
    return payloads[0] if payloads else None


def _stream_event_payloads(event: Any) -> list[Any]:
    if event_type(event) in STREAM_EVENT_TYPES:
        return [event]

    payloads: list[Any] = []
    for name in ("event", "stream_event", "data", "payload"):
        value = _field(event, name, None)
        if value is not None and event_type(value) in STREAM_EVENT_TYPES:
            payloads.append(value)
    if payloads:
        return payloads

    if event_type(event) != "stream_event":
        return []
    for name in ("event", "stream_event", "data", "payload"):
        value = _field(event, name, None)
        if value is not None:
            return [value]
    return []


def _stream_event_text_blocks(stream_event: Any) -> list[str]:
    stream_type = str(_field(stream_event, "type", "") or "")
    delta = _field(stream_event, "delta", None)
    if stream_type == "content_block_delta" and delta is not None:
        delta_type = str(_field(delta, "type", "") or "")
        if delta_type in {"text_delta", "thinking_delta"}:
            text = _field(delta, "text", None)
            if text:
                return [str(text)]

    block = _field(stream_event, "content_block", None)
    if stream_type == "content_block_start" and _field(block, "type", None) == "text":
        text = _field(block, "text", None)
        if text:
            return [str(text)]
    return []


def _stream_event_tool_use_items(stream_event: Any) -> list[Any]:
    stream_type = str(_field(stream_event, "type", "") or "")
    block = _field(stream_event, "content_block", None)
    if stream_type == "content_block_start" and _field(block, "type", None) == "tool_use":
        return [_with_stream_index(block, _field(stream_event, "index", None))]

    delta = _field(stream_event, "delta", None)
    if stream_type == "content_block_delta" and _field(delta, "type", None) == "tool_use":
        return [delta]

    # Some SDK/proxy payloads already carry a partial tool-use block directly.
    if _field(stream_event, "type", None) == "tool_use":
        return [stream_event]
    return []


def _stream_event_tool_result_items(stream_event: Any) -> list[Any]:
    stream_type = str(_field(stream_event, "type", "") or "")
    block = _field(stream_event, "content_block", None)
    if stream_type == "content_block_start" and _field(block, "type", None) == "tool_result":
        return [block]
    if _field(stream_event, "type", None) == "tool_result":
        return [stream_event]
    return []


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _with_stream_index(item: Any, index: Any) -> Any:
    if _optional_int(index) is None:
        return item
    if isinstance(item, dict):
        merged = dict(item)
        merged.setdefault("index", _optional_int(index))
        return merged
    return item


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
    if _inferred_sdk_type(value) is not None:
        return True
    return hasattr(value, "type") or hasattr(value, "content") or hasattr(value, "message")
