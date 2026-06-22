#!/usr/bin/env python3
"""FastMCP server for intentional custom-agent run notes."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

NOTE_TYPES = {
    "observation",
    "decision",
    "finding",
    "evidence",
    "diagnosis",
    "attempted_fix",
    "validation",
    "blocker",
    "handoff",
    "verifier_note",
    "reporter_note",
}
LEVELS = {"info", "warning", "error"}

mcp = FastMCP(
    "quorvex-agent",
    instructions=(
        "Record durable notes for a Quorvex agent run. Use this for meaningful observations, "
        "findings, decisions, blockers, and handoff notes, not routine tool activity."
    ),
)


def _text(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[: limit - 18].rstrip()}... [truncated]"


def _tags(value: list[str] | None) -> list[str]:
    if not value:
        return []
    tags: list[str] = []
    for item in value[:12]:
        tag = _text(item, limit=40)
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _confidence(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be a number between 0 and 1") from exc
    if numeric < 0 or numeric > 1:
        raise ValueError("confidence must be between 0 and 1")
    return numeric


def _run_id() -> str:
    run_id = os.environ.get("QUORVEX_AGENT_RUN_ID", "").strip()
    if not run_id:
        raise RuntimeError("QUORVEX_AGENT_RUN_ID is required for quorvex_record_note")
    return run_id


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
)
def quorvex_record_note(
    title: str,
    body: str | None = None,
    note_type: str = "observation",
    level: str = "info",
    tags: list[str] | None = None,
    actionable: bool = False,
    confidence: float | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    """Persist an intentional note for the current custom agent run."""
    normalized_title = _text(title, limit=240)
    if not normalized_title:
        raise ValueError("title is required")
    normalized_type = note_type if note_type in NOTE_TYPES else "observation"
    normalized_level = level if level in LEVELS else "info"
    normalized_body = _text(body, limit=6000) if body else None
    normalized_url = _text(url, limit=1000) if url else None
    normalized_confidence = _confidence(confidence)

    from orchestrator.services.agent_native_runs import commit_agent_run_note

    note = commit_agent_run_note(
        run_id=_run_id(),
        phase=f"agent_note:{normalized_type}",
        tool_use_id=f"quorvex_record_note:{uuid.uuid4().hex[:12]}",
        note_type=normalized_type,
        level=normalized_level,
        title=normalized_title,
        body=normalized_body,
        source="agent",
        tags=_tags(tags),
        actionable=bool(actionable),
        confidence=normalized_confidence,
        url=normalized_url,
        payload={
            "source_tool": "quorvex_record_note",
            "actionable": bool(actionable),
        },
    )
    if note is None:
        return {
            "status": "skipped",
            "reason": "agent run not found or native notes disabled",
            "type": normalized_type,
            "title": normalized_title,
        }
    return {
        "status": "recorded",
        "id": note.id,
        "sequence": note.sequence,
        "type": note.note_type,
        "title": note.title,
    }


def _run_cli(argv: list[str]) -> int:
    if argv and argv[0] == "record-note":
        payload = json.loads(sys.stdin.read() or "{}")
        result = quorvex_record_note(**payload)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    print("Usage: python tools/agent_note_mcp/server.py record-note < payload.json", file=sys.stderr)
    return 2


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(_run_cli(sys.argv[1:]))
    mcp.run(transport="stdio")
