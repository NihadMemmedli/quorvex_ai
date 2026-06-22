"""Native shadow-write helpers for AgentRun state, notes, and evidence."""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import (
    AgentRun,
    AgentRunEvent,
    AgentRunEvidence,
    AgentRunNote,
    AgentRunTaskContract,
)
from orchestrator.services.agent_run_events import create_agent_run_event, safe_event_payload

NATIVE_NOTE_TYPES = {
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
DEFAULT_NATIVE_RUN_TYPES = {"custom", "exploratory", "spec_generation"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _native_run_types() -> set[str]:
    raw = os.environ.get(
        "QUORVEX_NATIVE_AGENT_RUN_TYPES",
        "custom,exploratory,spec_generation",
    )
    values = {item.strip().lower() for item in raw.split(",") if item.strip()}
    return values or DEFAULT_NATIVE_RUN_TYPES


def native_shadow_writes_enabled(agent_type: str | None) -> bool:
    if str(agent_type or "").lower() not in _native_run_types():
        return False
    return _env_bool("QUORVEX_NATIVE_AGENT_RUN_SHADOW", True) or _env_bool(
        "QUORVEX_NATIVE_AGENT_RUNS_ENABLED",
        False,
    )


def native_read_model_enabled(agent_type: str | None) -> bool:
    return str(agent_type or "").lower() in _native_run_types() and _env_bool(
        "QUORVEX_NATIVE_AGENT_RUN_READ_MODEL",
        False,
    )


def _utcnow() -> datetime:
    return datetime.utcnow()


def _stable_key(*parts: Any) -> str:
    material = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"arn-{digest}"


def _json_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _compact(value: Any, limit: int = 800) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 18].rstrip()}... [truncated]"


def serialize_agent_run_note(note: AgentRunNote) -> dict[str, Any]:
    return {
        "id": note.id,
        "project_id": note.project_id,
        "run_id": note.run_id,
        "agent_task_id": note.agent_task_id,
        "sequence": note.sequence,
        "note_type": note.note_type,
        "level": note.level,
        "title": note.title,
        "body": note.body,
        "source": note.source,
        "tags": note.tags,
        "confidence": note.confidence,
        "url": note.url,
        "tool_name": note.tool_name,
        "artifact_path": note.artifact_path,
        "actionable": note.actionable,
        "related_event_sequence": note.related_event_sequence,
        "related_trace_span_id": note.related_trace_span_id,
        "payload": note.payload,
        "created_at": note.created_at.isoformat(),
    }


def list_agent_run_notes(
    *,
    run_id: str,
    after_sequence: int = 0,
    limit: int = 100,
    session: Session | None = None,
) -> list[AgentRunNote]:
    db = session or Session(engine)
    should_close = session is None
    try:
        return db.exec(
            select(AgentRunNote)
            .where(AgentRunNote.run_id == run_id, AgentRunNote.sequence > after_sequence)
            .order_by(col(AgentRunNote.sequence).asc())
            .limit(max(1, min(limit, 500)))
        ).all()
    finally:
        if should_close:
            db.close()


def ensure_agent_run_task_contract(
    *,
    run: AgentRun,
    session: Session,
    source: str = "runtime",
) -> AgentRunTaskContract | None:
    if not native_shadow_writes_enabled(run.agent_type):
        return None
    existing = session.exec(select(AgentRunTaskContract).where(AgentRunTaskContract.run_id == run.id)).first()
    if existing:
        return existing
    config = run.config or {}
    objective = (
        str(config.get("prompt") or config.get("task") or config.get("objective") or "").strip()
        or f"{run.agent_type} agent run"
    )
    contract = AgentRunTaskContract(
        id=f"arcontract-{uuid.uuid4().hex[:12]}",
        project_id=run.project_id,
        run_id=run.id,
        objective=objective,
        scope=str(config.get("scope") or config.get("url") or "").strip() or None,
        source=source,
        created_at=_utcnow(),
    )
    contract.success_criteria = _json_list(config.get("success_criteria"))
    contract.allowed_tools = _json_list(config.get("allowed_tools"))
    contract.output_expectations = _json_dict(config.get("output_expectations")) or {
        "legacy_projection": "result_json.structured_report",
        "native_shadow": True,
    }
    session.add(contract)
    try:
        session.commit()
        session.refresh(contract)
    except IntegrityError:
        session.rollback()
        return session.exec(select(AgentRunTaskContract).where(AgentRunTaskContract.run_id == run.id)).first()
    return contract


def _note_from_existing(session: Session, run_id: str, idempotency_key: str) -> AgentRunNote | None:
    return session.exec(
        select(AgentRunNote).where(
            AgentRunNote.run_id == run_id,
            AgentRunNote.idempotency_key == idempotency_key,
        )
    ).first()


def _evidence_counts(session: Session, run_id: str) -> dict[str, int]:
    rows = session.exec(
        select(AgentRunEvidence.evidence_type, func.count(AgentRunEvidence.id))
        .where(AgentRunEvidence.run_id == run_id)
        .group_by(AgentRunEvidence.evidence_type)
    ).all()
    return {str(kind or "unknown"): int(count or 0) for kind, count in rows}


def _live_notes_tail(session: Session, run_id: str, limit: int = 5) -> list[dict[str, Any]]:
    rows = session.exec(
        select(AgentRunNote)
        .where(AgentRunNote.run_id == run_id)
        .order_by(col(AgentRunNote.sequence).desc())
        .limit(limit)
    ).all()
    return [serialize_agent_run_note(note) for note in reversed(rows)]


def _update_native_progress(
    *,
    session: Session,
    run: AgentRun,
    phase: str,
    event_id: str | None,
    event_sequence: int | None,
    note: AgentRunNote | None,
) -> None:
    now = _utcnow()
    progress = dict(run.progress or {})
    progress.update(
        {
            "current_state": {
                "phase": phase,
                "status": run.status,
                "title": note.title if note else None,
                "source": note.source if note else None,
                "updated_at": now.isoformat(),
            },
            "live_notes_tail": _live_notes_tail(session, run.id),
            "evidence_counts": _evidence_counts(session, run.id),
            "last_step_id": event_id,
            "last_event_sequence": event_sequence,
            "updated_at": now.isoformat(),
        }
    )
    run.progress = progress
    state = dict(run.state or {})
    state.update(
        {
            "current_state": progress["current_state"],
            "evidence_counts": progress["evidence_counts"],
            "last_step_id": event_id,
            "last_event_sequence": event_sequence,
            "updated_at": now.isoformat(),
        }
    )
    run.state = state
    run.updated_at = now
    session.add(run)
    session.commit()


def _refresh_progress_for_existing_note(
    *,
    session: Session,
    run: AgentRun,
    phase: str,
    note: AgentRunNote,
) -> AgentRunNote:
    event_id: str | None = None
    if note.related_event_sequence is not None:
        event = session.exec(
            select(AgentRunEvent.id).where(
                AgentRunEvent.run_id == run.id,
                AgentRunEvent.sequence == note.related_event_sequence,
            )
        ).first()
        event_id = str(event) if event is not None else None
    refreshed_run = session.get(AgentRun, run.id) or run
    _update_native_progress(
        session=session,
        run=refreshed_run,
        phase=phase,
        event_id=event_id,
        event_sequence=note.related_event_sequence,
        note=note,
    )
    session.refresh(note)
    session.expunge(note)
    return note


def commit_agent_run_note(
    *,
    run_id: str,
    phase: str,
    title: str,
    body: str | None = None,
    note_type: str = "observation",
    level: str = "info",
    source: str = "runtime",
    tags: list[str] | None = None,
    confidence: float | None = None,
    url: str | None = None,
    tool_name: str | None = None,
    artifact_path: str | None = None,
    actionable: bool = False,
    related_trace_span_id: str | None = None,
    agent_task_id: str | None = None,
    tool_use_id: str | None = None,
    payload: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    session: Session | None = None,
) -> AgentRunNote | None:
    db = session or Session(engine)
    should_close = session is None
    try:
        run = db.get(AgentRun, run_id)
        if not run or not native_shadow_writes_enabled(run.agent_type):
            return None
        ensure_agent_run_task_contract(run=run, session=db, source=source)
        idempotency_key = _stable_key(run_id, agent_task_id or run.agent_task_id, tool_use_id, phase)
        existing = _note_from_existing(db, run_id, idempotency_key)
        if existing:
            return _refresh_progress_for_existing_note(session=db, run=run, phase=phase, note=existing)

        normalized_type = note_type if note_type in NATIVE_NOTE_TYPES else "observation"
        safe_payload = safe_event_payload(
            {
                **(payload or {}),
                "note_type": normalized_type,
                "title": title,
                "body": body,
                "source": source,
                "tags": tags or [],
                "confidence": confidence,
                "url": url,
                "tool_name": tool_name,
                "artifact_path": artifact_path,
                "related_trace_span_id": related_trace_span_id,
            }
        )
        event = create_agent_run_event(
            run_id=run_id,
            project_id=run.project_id,
            agent_task_id=agent_task_id or run.agent_task_id,
            event_type="agent_note",
            level=level,
            message=_compact(title, 1000),
            payload=safe_payload,
            idempotency_key=idempotency_key,
            session=db,
        )
        event_sequence = event.sequence if event is not None else None
        note = AgentRunNote(
            id=f"arnote-{uuid.uuid4().hex[:12]}",
            project_id=run.project_id,
            run_id=run_id,
            agent_task_id=agent_task_id or run.agent_task_id,
            sequence=event_sequence or 0,
            note_type=normalized_type,
            level=level,
            title=_compact(title, 1200),
            body=_compact(body, 6000) if body else None,
            source=source,
            confidence=confidence,
            url=url,
            tool_name=tool_name,
            artifact_path=artifact_path,
            actionable=bool(actionable),
            related_event_sequence=event_sequence,
            related_trace_span_id=related_trace_span_id,
            idempotency_key=idempotency_key,
            created_at=_utcnow(),
        )
        note.tags = tags or []
        note.payload = safe_payload
        db.add(note)
        try:
            db.commit()
            db.refresh(note)
        except IntegrityError:
            db.rollback()
            existing = _note_from_existing(db, run_id, idempotency_key)
            if existing:
                refreshed_run = db.get(AgentRun, run_id) or run
                return _refresh_progress_for_existing_note(session=db, run=refreshed_run, phase=phase, note=existing)
            raise

        for index, item in enumerate(evidence or []):
            if not isinstance(item, dict):
                continue
            stable_key = str(item.get("stable_key") or _stable_key(idempotency_key, "evidence", index))
            row = AgentRunEvidence(
                id=f"arev-{uuid.uuid4().hex[:12]}",
                project_id=run.project_id,
                run_id=run_id,
                note_id=note.id,
                evidence_type=str(item.get("evidence_type") or item.get("type") or "artifact"),
                title=str(item.get("title") or item.get("name") or "") or None,
                summary=str(item.get("summary") or item.get("description") or "") or None,
                stable_key=stable_key,
                artifact_path=item.get("artifact_path") or item.get("path"),
                url=item.get("url"),
                tool_name=item.get("tool_name") or tool_name,
                trace_span_id=item.get("trace_span_id") or related_trace_span_id,
                event_sequence=event_sequence,
                created_at=_utcnow(),
            )
            row.payload = safe_event_payload(item)
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()

        refreshed_run = db.get(AgentRun, run_id) or run
        _update_native_progress(
            session=db,
            run=refreshed_run,
            phase=phase,
            event_id=event.id if event else None,
            event_sequence=event_sequence,
            note=note,
        )
        db.refresh(note)
        db.expunge(note)
        return note
    finally:
        if should_close:
            db.close()
