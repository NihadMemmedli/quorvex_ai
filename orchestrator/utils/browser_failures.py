"""Shared browser runtime failure classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_BROWSER_DEAD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("browser_tool_timeout", re.compile(r"\bbrowser\b.*\b(?:timeout|timed\s+out)|\b(?:timeout|timed\s+out)\b.*\bbrowser\b", re.I | re.S)),
    ("browser_session_closed", re.compile(r"\bbrowser\b.*\bclosed|\bsession\b.*\bclosed", re.I | re.S)),
    ("browser_connection_closed", re.compile(r"\bconnection\b.*\bclosed|\bwebsocket\b.*\bclosed|\bpipe\b.*\bclosed", re.I | re.S)),
    ("browser_page_closed", re.compile(r"\b(?:page|context|target)\b.*\bclosed\b", re.I | re.S)),
    ("browser_mcp_eof", re.compile(r"\b(?:mcp|model context protocol)\b.*\b(?:eof|end of file|connection reset|broken pipe)\b", re.I | re.S)),
)


@dataclass(frozen=True)
class BrowserFailureClassification:
    """Normalized browser failure details for terminal retry decisions."""

    error_type: str
    message: str
    last_tool: str | None = None
    browser_session_usable: bool = False
    retryable_failure: bool = True
    requires_fresh_browser: bool = True

    def telemetry(self) -> dict[str, Any]:
        return {
            "phase": "browser_session_failed",
            "browser_session_usable": self.browser_session_usable,
            "retryable_failure": self.retryable_failure,
            "requires_fresh_browser": self.requires_fresh_browser,
            "last_browser_error": self.message,
            "last_tool": self.last_tool,
            "error_type": self.error_type,
            "failure_category": self.error_type,
        }


class BrowserSessionFailedError(RuntimeError):
    """Raised when a browser-owning agent run cannot safely continue."""

    def __init__(self, classification: BrowserFailureClassification):
        self.classification = classification
        super().__init__(classification.message)

    def telemetry(self) -> dict[str, Any]:
        return self.classification.telemetry()


def classify_browser_failure(
    error: Any,
    *,
    tool_name: str | None = None,
    error_type: str | None = None,
) -> BrowserFailureClassification | None:
    """Return browser-dead classification for timeout/closed/MCP EOF style errors."""

    explicit_type = str(error_type or "").strip()
    text = str(error or "").strip()
    lowered_type = explicit_type.lower()
    if lowered_type in {
        "browser_tool_timeout",
        "browser_session_closed",
        "browser_connection_closed",
        "browser_page_closed",
        "browser_mcp_eof",
    }:
        return BrowserFailureClassification(
            error_type=lowered_type,
            message=text or lowered_type,
            last_tool=tool_name,
        )

    if not text:
        return None
    for classified_type, pattern in _BROWSER_DEAD_PATTERNS:
        if pattern.search(text):
            return BrowserFailureClassification(
                error_type=classified_type,
                message=text,
                last_tool=tool_name,
            )
    return None


def browser_failure_telemetry(
    error: Any,
    *,
    tool_name: str | None = None,
    error_type: str | None = None,
) -> dict[str, Any]:
    classification = classify_browser_failure(error, tool_name=tool_name, error_type=error_type)
    return classification.telemetry() if classification else {}
