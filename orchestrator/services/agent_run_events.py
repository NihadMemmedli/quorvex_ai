"""Durable event helpers for agent run observability."""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import AgentRun, AgentRunEvent

logger = logging.getLogger(__name__)

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
            lower_key = key_text.lower()
            if lower_key in SENSITIVE_KEYS or any(part in lower_key for part in SENSITIVE_KEYS):
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


def safe_event_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
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


def _next_sequence(session: Session, run_id: str) -> int:
    current = session.exec(select(func.max(AgentRunEvent.sequence)).where(AgentRunEvent.run_id == run_id)).one()
    return int(current or 0) + 1


def create_agent_run_event(
    *,
    run_id: str,
    project_id: str | None = None,
    agent_task_id: str | None = None,
    temporal_workflow_id: str | None = None,
    temporal_run_id: str | None = None,
    event_type: str,
    message: str,
    level: str = "info",
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    session: Session | None = None,
) -> AgentRunEvent | None:
    """Persist one compact agent run event."""

    db = session or Session(engine)
    should_close = session is None
    try:
        run = db.get(AgentRun, run_id)
        if not run:
            return None
        if idempotency_key:
            existing = db.exec(
                select(AgentRunEvent).where(
                    AgentRunEvent.run_id == run_id,
                    AgentRunEvent.idempotency_key == idempotency_key,
                )
            ).first()
            if existing:
                return existing
        event: AgentRunEvent | None = None
        for attempt in range(5):
            event = AgentRunEvent(
                id=f"arevt-{uuid.uuid4().hex[:12]}",
                project_id=project_id if project_id is not None else run.project_id,
                run_id=run_id,
                agent_task_id=agent_task_id or run.agent_task_id,
                temporal_workflow_id=temporal_workflow_id or run.temporal_workflow_id,
                temporal_run_id=temporal_run_id or run.temporal_run_id,
                sequence=_next_sequence(db, run_id),
                event_type=event_type,
                level=level,
                message=_compact_text(message, MAX_MESSAGE_CHARS),
                idempotency_key=idempotency_key,
                created_at=_utcnow(),
            )
            event.payload = safe_event_payload(payload)
            db.add(event)
            try:
                db.commit()
                db.refresh(event)
                break
            except IntegrityError as exc:
                db.rollback()
                if idempotency_key:
                    existing = db.exec(
                        select(AgentRunEvent).where(
                            AgentRunEvent.run_id == run_id,
                            AgentRunEvent.idempotency_key == idempotency_key,
                        )
                    ).first()
                    if existing:
                        return existing
                if attempt >= 4:
                    logger.warning("Failed to allocate unique event sequence for run %s: %s", run_id, exc)
                    raise
        if event is None:
            return None
        try:
            from orchestrator.services.agent_trace import record_span_for_event

            record_span_for_event(event, session=db)
            db.refresh(event)
        except Exception as exc:
            logger.debug("Failed to record trace span for agent event %s: %s", event.id, exc)
        return event
    finally:
        if should_close:
            db.close()


def create_event_for_agent_task(
    agent_task_id: str,
    *,
    event_type: str,
    message: str,
    level: str = "info",
    payload: dict[str, Any] | None = None,
    run_id: str | None = None,
    idempotency_key: str | None = None,
) -> AgentRunEvent | None:
    """Resolve an agent task to its AgentRun and persist an event."""

    with Session(engine) as session:
        run = session.get(AgentRun, run_id) if run_id else None
        if run is None:
            run = session.exec(select(AgentRun).where(AgentRun.agent_task_id == agent_task_id)).first()
        if not run:
            return None
        return create_agent_run_event(
            run_id=run.id,
            project_id=run.project_id,
            agent_task_id=agent_task_id,
            event_type=event_type,
            level=level,
            message=message,
            payload=payload,
            idempotency_key=idempotency_key,
            session=session,
        )


def event_to_response(event: AgentRunEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "project_id": event.project_id,
        "run_id": event.run_id,
        "agent_task_id": event.agent_task_id,
        "temporal_workflow_id": event.temporal_workflow_id,
        "temporal_run_id": event.temporal_run_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "level": event.level,
        "message": event.message,
        "payload": event.payload,
        "idempotency_key": event.idempotency_key,
        "created_at": event.created_at.isoformat(),
    }


def list_agent_run_events(
    *,
    run_id: str,
    after_sequence: int = 0,
    event_type: str | None = None,
    level: str | None = None,
    limit: int = 200,
    session: Session | None = None,
) -> list[AgentRunEvent]:
    db = session or Session(engine)
    should_close = session is None
    try:
        statement = select(AgentRunEvent).where(
            AgentRunEvent.run_id == run_id,
            AgentRunEvent.sequence > after_sequence,
        )
        if event_type:
            statement = statement.where(AgentRunEvent.event_type == event_type)
        if level:
            statement = statement.where(AgentRunEvent.level == level)
        return db.exec(
            statement.order_by(col(AgentRunEvent.sequence).asc()).limit(max(1, min(limit, 500)))
        ).all()
    finally:
        if should_close:
            db.close()
