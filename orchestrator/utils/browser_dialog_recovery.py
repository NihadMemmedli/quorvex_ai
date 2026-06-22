"""Structured telemetry helpers for browser dialog recovery evidence."""

from __future__ import annotations

import re

BROWSER_DIALOG_AUTO_ACCEPTED_RE = re.compile(
    r"\[quorvex\]\s+Browser dialog auto-accepted\s+type=(?P<dialog_type>[^\s]+)"
    r"(?:\s+message=(?P<message>.*))?$"
)

BROWSER_DIALOG_AUTO_ACCEPTED_MARKER = "[quorvex] Browser dialog auto-accepted"


def playwright_dialog_auto_accept_handler(indent: str = "  ") -> str:
    """Return a Playwright page dialog handler with standard telemetry."""
    return "\n".join(
        [
            f"{indent}page.on('dialog', async dialog => {{",
            f"{indent}  const type = dialog.type();",
            f"{indent}  const message = String(dialog.message() || '').replace(/[\\r\\n\\t]+/g, ' ').slice(0, 240);",
            f"{indent}  await dialog.accept();",
            f"{indent}  console.log(`[quorvex] Browser dialog auto-accepted type=${{type}} message=${{message}}`);",
            f"{indent}}});",
        ]
    )


def _sanitize_dialog_value(value: object, *, limit: int) -> str:
    sanitized = re.sub(r"[\r\n\t]+", " ", str(value or "")).strip()
    return sanitized[:limit]


def parse_browser_dialog_recovery_console_line(line: object) -> dict[str, object] | None:
    """Parse a generated browser-dialog recovery console line into safe telemetry."""
    match = BROWSER_DIALOG_AUTO_ACCEPTED_RE.search(str(line or ""))
    if not match:
        return None

    dialog_type = _sanitize_dialog_value(match.group("dialog_type"), limit=40) or "unknown"
    message = _sanitize_dialog_value(match.group("message") or "", limit=120)
    return {
        "browser_dialog_recovered": True,
        "dialog_recovery_attempted": True,
        "dialog_recovery_result": "auto_accepted",
        "dialog_recovery_dialog_type": dialog_type,
        "dialog_recovery_message": message,
    }


def browser_dialog_recovery_telemetry_from_text(text: object) -> dict[str, object] | None:
    """Return first browser dialog recovery marker found in tool output text."""
    for line in str(text or "").splitlines():
        telemetry = parse_browser_dialog_recovery_console_line(line)
        if telemetry:
            return telemetry
    return None
