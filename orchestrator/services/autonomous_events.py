"""Durable event helpers for autonomous mission observability."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import AutonomousAgentEvent, AutonomousAgentWorkItem, AutonomousMission

MAX_MESSAGE_CHARS = 4000
MAX_PAYLOAD_JSON_CHARS = 12000
MAX_TEXT_PAYLOAD_CHARS = 6000
SENSITIVE_KEYS = {"authorization", "cookie", "password", "secret", "token", "api_key", "apikey", "refresh_token"}


def _utcnow() -> datetime:
    return datetime.utcnow()


def _compact_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 24].rstrip()}... [truncated {len(value) - limit} chars]"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in SENSITIVE_KEYS or any(part in key_text.lower() for part in SENSITIVE_KEYS):
                redacted[key_text] = "[redacted]"
            else:
                redacted[key_text] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value[:80]]
    if isinstance(value, str):
        compact = _compact_text(value, MAX_TEXT_PAYLOAD_CHARS)
        compact = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", compact)
        return compact
    return value


def _safe_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    safe = _redact(payload or {})
    try:
        encoded = json.dumps(safe)
    except (TypeError, ValueError):
        safe = {"value": str(safe)}
        encoded = json.dumps(safe)
    if len(encoded) <= MAX_PAYLOAD_JSON_CHARS:
        return safe
    return {
        "truncated": True,
        "preview": _compact_text(encoded, MAX_PAYLOAD_JSON_CHARS),
    }


def _next_sequence(session: Session, mission_id: str) -> int:
    current = session.exec(
        select(func.max(AutonomousAgentEvent.sequence)).where(AutonomousAgentEvent.mission_id == mission_id)
    ).one()
    return int(current or 0) + 1


def create_autonomous_agent_event(
    *,
    mission_id: str,
    project_id: str | None = None,
    run_id: str | None = None,
    work_item_id: str | None = None,
    agent_task_id: str | None = None,
    event_type: str,
    message: str,
    level: str = "info",
    payload: dict[str, Any] | None = None,
    session: Session | None = None,
) -> AutonomousAgentEvent:
    """Persist one compact autonomous mission event."""

    db = session or Session(engine)
    should_close = session is None
    try:
        event = AutonomousAgentEvent(
            id=f"amevt-{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            mission_id=mission_id,
            run_id=run_id,
            work_item_id=work_item_id,
            agent_task_id=agent_task_id,
            sequence=_next_sequence(db, mission_id),
            event_type=event_type,
            level=level,
            message=_compact_text(message, MAX_MESSAGE_CHARS),
            created_at=_utcnow(),
        )
        event.payload = _safe_payload(payload)
        db.add(event)
        db.commit()
        db.refresh(event)
        return event
    finally:
        if should_close:
            db.close()


def create_event_for_work_item(
    work_item_id: str,
    *,
    event_type: str,
    message: str,
    level: str = "info",
    payload: dict[str, Any] | None = None,
    agent_task_id: str | None = None,
) -> AutonomousAgentEvent | None:
    """Resolve a work item and persist an event for it."""

    with Session(engine) as session:
        item = session.get(AutonomousAgentWorkItem, work_item_id)
        if not item:
            return None
        return create_autonomous_agent_event(
            project_id=item.project_id,
            mission_id=item.mission_id,
            run_id=item.run_id,
            work_item_id=item.id,
            agent_task_id=agent_task_id or item.agent_task_id,
            event_type=event_type,
            level=level,
            message=message,
            payload=payload,
            session=session,
        )


def event_to_response(event: AutonomousAgentEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "project_id": event.project_id,
        "mission_id": event.mission_id,
        "run_id": event.run_id,
        "work_item_id": event.work_item_id,
        "agent_task_id": event.agent_task_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "level": event.level,
        "message": event.message,
        "payload": event.payload,
        "created_at": event.created_at.isoformat(),
    }


def list_events(
    *,
    project_id: str,
    mission_id: str | None = None,
    work_item_id: str | None = None,
    after_sequence: int = 0,
    limit: int = 200,
    session: Session | None = None,
) -> list[AutonomousAgentEvent]:
    db = session or Session(engine)
    should_close = session is None
    try:
        statement = select(AutonomousAgentEvent).where(
            AutonomousAgentEvent.project_id == project_id,
            AutonomousAgentEvent.sequence > after_sequence,
        )
        if mission_id:
            statement = statement.where(AutonomousAgentEvent.mission_id == mission_id)
        if work_item_id:
            statement = statement.where(AutonomousAgentEvent.work_item_id == work_item_id)
        return db.exec(
            statement.order_by(col(AutonomousAgentEvent.sequence).asc()).limit(max(1, min(limit, 500)))
        ).all()
    finally:
        if should_close:
            db.close()


def emit_work_item_status_event(
    item: AutonomousAgentWorkItem,
    message: str,
    *,
    event_type: str = "status",
    payload: dict[str, Any] | None = None,
) -> None:
    create_autonomous_agent_event(
        project_id=item.project_id,
        mission_id=item.mission_id,
        run_id=item.run_id,
        work_item_id=item.id,
        agent_task_id=item.agent_task_id,
        event_type=event_type,
        message=message,
        payload={"status": item.status, "progress": item.progress, **(payload or {})},
    )


def emit_mission_event(mission: AutonomousMission, message: str, *, event_type: str, payload: dict[str, Any] | None = None) -> None:
    create_autonomous_agent_event(
        project_id=mission.project_id,
        mission_id=mission.id,
        run_id=mission.latest_run_id,
        event_type=event_type,
        message=message,
        payload=payload,
    )
