"""Persistence helpers for AutoPilot live checklist rows."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

TERMINAL_STATUSES = {"completed", "passed", "failed", "error", "skipped", "cancelled", "answered", "auto_continued"}


def _next_sequence(db: Session, session_id: str) -> int:
    from orchestrator.api.models_db import AutoPilotChecklistItem

    max_sequence = db.exec(
        select(func.max(AutoPilotChecklistItem.sequence)).where(
            AutoPilotChecklistItem.session_id == session_id
        )
    ).one()
    return int(max_sequence or 0) + 10


def _clamp_progress(value: float | int | None) -> float:
    try:
        numeric = float(value if value is not None else 0)
    except (TypeError, ValueError):
        return 0.0
    if numeric > 1:
        numeric = numeric / 100
    return max(0.0, min(1.0, numeric))


def _merge_metadata(existing_json: str | None, incoming: dict[str, Any] | None) -> str:
    try:
        existing = json.loads(existing_json or "{}")
        if not isinstance(existing, dict):
            existing = {}
    except json.JSONDecodeError:
        existing = {}
    if incoming:
        existing.update({key: value for key, value in incoming.items() if value is not None})
    return json.dumps(existing, default=str)


def upsert_checklist_item(
    *,
    session_id: str,
    source_type: str,
    source_id: str,
    title: str,
    kind: str = "task",
    phase_name: str | None = None,
    detail: str | None = None,
    status: str = "running",
    progress: float | int | None = None,
    items_completed: int | None = None,
    items_total: int | None = None,
    metadata: dict[str, Any] | None = None,
    sequence: int | None = None,
) -> Any:
    """Create or update a stable checklist row for a session."""
    from orchestrator.api.db import engine
    from orchestrator.api.models_db import AutoPilotChecklistItem

    now = datetime.utcnow()
    with Session(engine) as db:
        stmt = (
            select(AutoPilotChecklistItem)
            .where(AutoPilotChecklistItem.session_id == session_id)
            .where(AutoPilotChecklistItem.source_type == source_type)
            .where(AutoPilotChecklistItem.source_id == source_id)
        )
        item = db.exec(stmt).first()
        if not item:
            item = AutoPilotChecklistItem(
                session_id=session_id,
                sequence=sequence if sequence is not None else _next_sequence(db, session_id),
                kind=kind,
                phase_name=phase_name,
                title=title,
                source_type=source_type,
                source_id=source_id,
                created_at=now,
            )
        else:
            if sequence is not None:
                item.sequence = sequence
            item.kind = kind or item.kind
            item.title = title or item.title
            if phase_name is not None:
                item.phase_name = phase_name

        if detail is not None:
            item.detail = detail[:2000]
        item.status = status
        if progress is not None:
            item.progress = _clamp_progress(progress)
        elif items_total:
            item.progress = _clamp_progress((items_completed or 0) / max(items_total, 1))
        if items_completed is not None:
            item.items_completed = max(0, int(items_completed))
        if items_total is not None:
            item.items_total = max(0, int(items_total))
        item.metadata_json = _merge_metadata(item.metadata_json, metadata)
        item.updated_at = now
        if status in TERMINAL_STATUSES:
            item.completed_at = item.completed_at or now
        else:
            item.completed_at = None
        db.add(item)
        db.commit()
        db.refresh(item)
        return item


def complete_checklist_item(
    *,
    session_id: str,
    source_type: str,
    source_id: str,
    title: str,
    kind: str = "task",
    phase_name: str | None = None,
    detail: str | None = None,
    items_completed: int | None = None,
    items_total: int | None = None,
    metadata: dict[str, Any] | None = None,
    status: str = "completed",
) -> Any:
    total = items_total if items_total is not None else items_completed
    return upsert_checklist_item(
        session_id=session_id,
        source_type=source_type,
        source_id=source_id,
        title=title,
        kind=kind,
        phase_name=phase_name,
        detail=detail,
        status=status,
        progress=1.0,
        items_completed=items_completed if items_completed is not None else total,
        items_total=total,
        metadata=metadata,
    )


def fail_checklist_item(
    *,
    session_id: str,
    source_type: str,
    source_id: str,
    title: str,
    kind: str = "task",
    phase_name: str | None = None,
    detail: str | None = None,
    metadata: dict[str, Any] | None = None,
    status: str = "failed",
) -> Any:
    return upsert_checklist_item(
        session_id=session_id,
        source_type=source_type,
        source_id=source_id,
        title=title,
        kind=kind,
        phase_name=phase_name,
        detail=detail,
        status=status,
        metadata=metadata,
    )


def append_checklist_item(
    *,
    session_id: str,
    title: str,
    kind: str = "event",
    phase_name: str | None = None,
    detail: str | None = None,
    status: str = "completed",
    progress: float | int | None = None,
    items_completed: int | None = None,
    items_total: int | None = None,
    source_type: str = "event",
    source_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    sequence: int | None = None,
) -> Any:
    return upsert_checklist_item(
        session_id=session_id,
        source_type=source_type,
        source_id=source_id or f"event:{uuid.uuid4().hex}",
        title=title,
        kind=kind,
        phase_name=phase_name,
        detail=detail,
        status=status,
        progress=progress,
        items_completed=items_completed,
        items_total=items_total,
        metadata=metadata,
        sequence=sequence,
    )
