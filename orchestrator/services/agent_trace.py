"""Deep redacted trace helpers for agent run observability."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_
from sqlmodel import Session, col, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import AgentRun, AgentRunEvent, AgentTraceSnapshot, AgentTraceSpan, MemoryInjectionEvent
from orchestrator.services.agent_run_events import _compact_text, safe_event_payload
from orchestrator.utils.agent_runner import build_safe_tool_input_metadata

TRACE_TEXT_PREVIEW_CHARS = 2400
TRACE_JSON_PREVIEW_CHARS = 6000
REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"


def _utcnow() -> datetime:
    return datetime.utcnow()


def _hash_text(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, indent=2, sort_keys=True, default=str, ensure_ascii=False)
    except Exception:
        return str(value)


def _redacted_value(value: Any) -> Any:
    if isinstance(value, dict):
        return safe_event_payload(value)
    return safe_event_payload({"value": value}).get("value")


def _redacted_text(value: str | None, limit: int = TRACE_TEXT_PREVIEW_CHARS) -> str:
    if not value:
        return ""
    safe = safe_event_payload({"text": value}).get("text", "")
    return _compact_text(str(safe), limit)


def _redacted_artifact_text(value: str | None) -> str:
    if not value:
        return ""
    redacted = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", value)
    redacted = re.sub(
        r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|refresh[_-]?token)"
        r"(\s*[:=]\s*)([^\s,;}\]]+)",
        lambda match: f"{match.group(1)}{match.group(2)}[redacted]",
        redacted,
    )
    return redacted


def _write_trace_artifact(run_id: str, filename: str, payload: dict[str, Any]) -> str:
    trace_dir = RUNS_DIR / run_id / "trace"
    trace_dir.mkdir(parents=True, exist_ok=True)
    path = trace_dir / filename
    path.write_text(_safe_json(payload), encoding="utf-8")
    return f"/artifacts/{run_id}/trace/{filename}"


def _next_attempt(session: Session, run_id: str) -> int:
    current = session.exec(select(func.max(AgentTraceSnapshot.attempt)).where(AgentTraceSnapshot.run_id == run_id)).one()
    return int(current or 0) + 1


def _next_span_sequence(session: Session, trace_id: str) -> int:
    current = session.exec(select(func.max(AgentTraceSpan.sequence)).where(AgentTraceSpan.trace_id == trace_id)).one()
    return int(current or 0) + 1


def _normalize_tools(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [str(key) for key in value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _normalize_test_data_refs(config: dict[str, Any] | None, explicit: list[Any] | None = None) -> list[str]:
    refs: list[str] = []
    for item in explicit or []:
        if item is not None and str(item) not in refs:
            refs.append(str(item))
    if isinstance(config, dict):
        for item in config.get("test_data_refs") or []:
            if item is not None and str(item) not in refs:
                refs.append(str(item))
        custom_config = config.get("custom_config") if isinstance(config.get("custom_config"), dict) else {}
        for item in custom_config.get("test_data_refs") or []:
            if item is not None and str(item) not in refs:
                refs.append(str(item))
    return refs


def ensure_trace_snapshot(
    *,
    run_id: str,
    prompt: str | None = None,
    context: str | None = None,
    memory_context: str | None = None,
    runtime: str | None = None,
    model: str | None = None,
    model_tier: str | None = None,
    allowed_tools: Any = None,
    runtime_diagnostics: dict[str, Any] | None = None,
    test_data_refs: list[Any] | None = None,
    agent_task_id: str | None = None,
    session: Session | None = None,
) -> AgentTraceSnapshot | None:
    """Create the run's redacted trace snapshot if needed, then fill missing metadata.

    The first call creates attempt 1. Later calls keep the same trace ID and update
    fields that were not available at creation time, such as an external task ID.
    """

    db = session or Session(engine)
    should_close = session is None
    try:
        run = db.get(AgentRun, run_id)
        if not run:
            return None
        snapshot = db.exec(
            select(AgentTraceSnapshot)
            .where(AgentTraceSnapshot.run_id == run_id)
            .order_by(col(AgentTraceSnapshot.attempt).desc())
            .limit(1)
        ).first()
        now = _utcnow()
        config = run.config if isinstance(run.config, dict) else {}
        redacted_prompt = _redacted_text(prompt)
        redacted_context = _redacted_text(context)
        redacted_memory = _redacted_text(memory_context)
        prompt_artifact_path = None
        context_artifact_path = None
        if prompt is not None:
            prompt_artifact_path = _write_trace_artifact(
                run_id,
                "final_prompt.redacted.json",
                {
                    "run_id": run_id,
                    "redacted_prompt": _redacted_artifact_text(prompt),
                    "prompt_hash": _hash_text(prompt),
                    "size_bytes": len(prompt.encode("utf-8", errors="replace")),
                    "captured_at": now.isoformat(),
                },
            )
        if context is not None or memory_context is not None:
            context_artifact_path = _write_trace_artifact(
                run_id,
                "context.redacted.json",
                {
                    "run_id": run_id,
                    "redacted_context": _redacted_artifact_text(context),
                    "redacted_memory_context": _redacted_artifact_text(memory_context),
                    "context_hash": _hash_text(context),
                    "memory_block_hash": _hash_text(memory_context),
                    "captured_at": now.isoformat(),
                },
            )

        if snapshot is None:
            snapshot = AgentTraceSnapshot(
                project_id=run.project_id,
                run_id=run_id,
                agent_task_id=agent_task_id or run.agent_task_id,
                attempt=_next_attempt(db, run_id),
                runtime=runtime or getattr(run, "runtime", None) or config.get("runtime") or "claude_sdk",
                model=model or config.get("model"),
                model_tier=model_tier or config.get("model_tier"),
                prompt_hash=_hash_text(prompt),
                context_hash=_hash_text(context),
                memory_block_hash=_hash_text(memory_context),
                prompt_preview=redacted_prompt,
                memory_preview=redacted_memory or redacted_context,
                prompt_artifact_path=prompt_artifact_path,
                context_artifact_path=context_artifact_path,
                runtime_diagnostics=safe_event_payload(runtime_diagnostics or {}),
                created_at=now,
                updated_at=now,
            )
            snapshot.allowed_tools = _normalize_tools(allowed_tools or config.get("allowed_tools"))
            snapshot.test_data_refs = _normalize_test_data_refs(config, test_data_refs)
            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)
            record_trace_span(
                trace_id=snapshot.id,
                run_id=run_id,
                span_type="prompt_build",
                name="Prompt build",
                message="Final agent prompt/context snapshot captured.",
                payload={
                    "prompt_hash": snapshot.prompt_hash,
                    "context_hash": snapshot.context_hash,
                    "memory_block_hash": snapshot.memory_block_hash,
                    "prompt_artifact_path": snapshot.prompt_artifact_path,
                    "context_artifact_path": snapshot.context_artifact_path,
                },
                session=db,
            )
            db.refresh(snapshot)
            return snapshot

        changed = False
        if agent_task_id and snapshot.agent_task_id != agent_task_id:
            snapshot.agent_task_id = agent_task_id
            changed = True
        for attr, value in {
            "runtime": runtime,
            "model": model,
            "model_tier": model_tier,
            "prompt_hash": _hash_text(prompt),
            "context_hash": _hash_text(context),
            "memory_block_hash": _hash_text(memory_context),
            "prompt_artifact_path": prompt_artifact_path,
            "context_artifact_path": context_artifact_path,
        }.items():
            if value and not getattr(snapshot, attr):
                setattr(snapshot, attr, value)
                changed = True
        if redacted_prompt and not snapshot.prompt_preview:
            snapshot.prompt_preview = redacted_prompt
            changed = True
        if (redacted_memory or redacted_context) and not snapshot.memory_preview:
            snapshot.memory_preview = redacted_memory or redacted_context
            changed = True
        tools = _normalize_tools(allowed_tools or config.get("allowed_tools"))
        if tools and not snapshot.allowed_tools:
            snapshot.allowed_tools = tools
            changed = True
        refs = _normalize_test_data_refs(config, test_data_refs)
        if refs and not snapshot.test_data_refs:
            snapshot.test_data_refs = refs
            changed = True
        if runtime_diagnostics and not snapshot.runtime_diagnostics:
            snapshot.runtime_diagnostics = safe_event_payload(runtime_diagnostics)
            changed = True
        if changed:
            snapshot.updated_at = now
            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)
        return snapshot
    finally:
        if should_close:
            db.close()


def record_trace_span(
    *,
    run_id: str,
    span_type: str,
    name: str,
    message: str = "",
    trace_id: str | None = None,
    parent_span_id: str | None = None,
    agent_run_event_id: str | None = None,
    level: str = "info",
    tool_name: str | None = None,
    success: bool | None = None,
    duration_ms: float | None = None,
    input_preview: Any = None,
    output_preview: Any = None,
    payload: dict[str, Any] | None = None,
    artifact_path: str | None = None,
    content_hash: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    session: Session | None = None,
) -> AgentTraceSpan | None:
    db = session or Session(engine)
    should_close = session is None
    try:
        run = db.get(AgentRun, run_id)
        if not run:
            return None
        snapshot = db.get(AgentTraceSnapshot, trace_id) if trace_id else None
        if snapshot is None:
            snapshot = ensure_trace_snapshot(run_id=run_id, session=db)
        if snapshot is None:
            return None
        safe_payload = safe_event_payload(payload or {})
        span = AgentTraceSpan(
            id=f"atspan-{uuid.uuid4().hex[:12]}",
            trace_id=snapshot.id,
            project_id=run.project_id,
            run_id=run_id,
            parent_span_id=parent_span_id,
            agent_run_event_id=agent_run_event_id,
            sequence=_next_span_sequence(db, snapshot.id),
            span_type=span_type,
            name=_compact_text(name, 300),
            level=level,
            message=_compact_text(message or "", 4000),
            tool_name=tool_name,
            success=success,
            duration_ms=duration_ms,
            content_hash=content_hash,
            input_preview=_redacted_value(input_preview) if input_preview is not None else None,
            output_preview=_redacted_value(output_preview) if output_preview is not None else None,
            artifact_path=artifact_path,
            started_at=started_at,
            ended_at=ended_at,
            created_at=_utcnow(),
        )
        span.payload = safe_payload
        db.add(span)
        db.commit()
        db.refresh(span)
        return span
    finally:
        if should_close:
            db.close()


def record_span_for_event(event: AgentRunEvent, session: Session | None = None) -> AgentTraceSpan | None:
    span_type = {
        "tool_call": "tool_call",
        "browser_action": "tool_call",
        "complete": "completion",
        "error": "completion",
        "cancel": "completion",
        "created": "hook_event",
        "temporal_scheduled": "hook_event",
        "temporal_start_failed": "hook_event",
        "recovery": "hook_event",
    }.get(event.event_type, "provider_event")
    payload = event.payload
    tool_name = payload.get("tool_name") if isinstance(payload, dict) else None
    input_preview = payload.get("tool_input") if isinstance(payload, dict) else None
    return record_trace_span(
        run_id=event.run_id,
        span_type=span_type,
        name=event.event_type.replace("_", " ").title(),
        message=event.message,
        agent_run_event_id=event.id,
        level=event.level,
        tool_name=str(tool_name) if tool_name else None,
        input_preview=input_preview,
        payload={"event_payload": payload, "event_sequence": event.sequence},
        started_at=event.created_at,
        session=session,
    )


def record_tool_result_spans(run_id: str, tool_calls: list[Any], session: Session | None = None) -> None:
    for call in tool_calls or []:
        name = getattr(call, "name", None) if not isinstance(call, dict) else call.get("name")
        if not name:
            continue
        call_input = getattr(call, "input", None) if not isinstance(call, dict) else call.get("input")
        metadata = build_safe_tool_input_metadata(call_input if isinstance(call_input, dict) else None)
        success = getattr(call, "success", None) if not isinstance(call, dict) else call.get("success")
        error = getattr(call, "error", None) if not isinstance(call, dict) else call.get("error")
        duration_ms = getattr(call, "duration_ms", None) if not isinstance(call, dict) else call.get("duration_ms")
        timestamp = getattr(call, "timestamp", None) if not isinstance(call, dict) else call.get("timestamp")
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp)
            except ValueError:
                timestamp = None
        record_trace_span(
            run_id=run_id,
            span_type="tool_result",
            name=f"{str(name).rsplit('__', 1)[-1]} result",
            message="Tool completed." if success is not False else f"Tool failed: {error}",
            level="info" if success is not False else "error",
            tool_name=str(name),
            success=bool(success) if success is not None else None,
            duration_ms=float(duration_ms) if duration_ms is not None else None,
            input_preview=metadata.get("input_preview"),
            output_preview={"error": error} if error else {"success": success},
            content_hash=metadata.get("content_hash"),
            started_at=timestamp if isinstance(timestamp, datetime) else None,
            payload={
                "input_length": metadata.get("input_length"),
                "input_content_length": metadata.get("input_content_length"),
            },
            session=session,
        )


def serialize_snapshot(snapshot: AgentTraceSnapshot | None) -> dict[str, Any] | None:
    if not snapshot:
        return None
    return {
        "id": snapshot.id,
        "trace_id": snapshot.id,
        "project_id": snapshot.project_id,
        "run_id": snapshot.run_id,
        "agent_task_id": snapshot.agent_task_id,
        "attempt": snapshot.attempt,
        "runtime": snapshot.runtime,
        "model": snapshot.model,
        "model_tier": snapshot.model_tier,
        "allowed_tools": snapshot.allowed_tools,
        "prompt_hash": snapshot.prompt_hash,
        "context_hash": snapshot.context_hash,
        "memory_block_hash": snapshot.memory_block_hash,
        "prompt_preview": snapshot.prompt_preview,
        "memory_preview": snapshot.memory_preview,
        "prompt_artifact_path": snapshot.prompt_artifact_path,
        "context_artifact_path": snapshot.context_artifact_path,
        "test_data_refs": snapshot.test_data_refs,
        "runtime_diagnostics": snapshot.runtime_diagnostics or {},
        "created_at": snapshot.created_at.isoformat(),
        "updated_at": snapshot.updated_at.isoformat(),
    }


def serialize_span(span: AgentTraceSpan) -> dict[str, Any]:
    return {
        "id": span.id,
        "trace_id": span.trace_id,
        "project_id": span.project_id,
        "run_id": span.run_id,
        "parent_span_id": span.parent_span_id,
        "agent_run_event_id": span.agent_run_event_id,
        "autonomous_mission_id": span.autonomous_mission_id,
        "autonomous_work_item_id": span.autonomous_work_item_id,
        "sequence": span.sequence,
        "span_type": span.span_type,
        "name": span.name,
        "level": span.level,
        "message": span.message,
        "tool_name": span.tool_name,
        "success": span.success,
        "duration_ms": span.duration_ms,
        "content_hash": span.content_hash,
        "input_preview": span.input_preview,
        "output_preview": span.output_preview,
        "artifact_path": span.artifact_path,
        "payload": span.payload,
        "started_at": span.started_at.isoformat() if span.started_at else None,
        "ended_at": span.ended_at.isoformat() if span.ended_at else None,
        "created_at": span.created_at.isoformat(),
    }


def list_trace_spans(
    *,
    run_id: str,
    trace_id: str | None = None,
    span_type: str | None = None,
    level: str | None = None,
    tool: str | None = None,
    q: str | None = None,
    after_sequence: int = 0,
    before_sequence: int | None = None,
    limit: int = 200,
    session: Session | None = None,
) -> list[AgentTraceSpan]:
    db = session or Session(engine)
    should_close = session is None
    try:
        statement = select(AgentTraceSpan).where(AgentTraceSpan.run_id == run_id, AgentTraceSpan.sequence > after_sequence)
        if trace_id:
            statement = statement.where(AgentTraceSpan.trace_id == trace_id)
        if span_type:
            statement = statement.where(AgentTraceSpan.span_type == span_type)
        if level:
            statement = statement.where(AgentTraceSpan.level == level)
        if tool:
            statement = statement.where(AgentTraceSpan.tool_name == tool)
        if before_sequence is not None:
            statement = statement.where(AgentTraceSpan.sequence <= before_sequence)
        if q:
            pattern = f"%{q}%"
            statement = statement.where(
                or_(
                    AgentTraceSpan.name.like(pattern),
                    AgentTraceSpan.message.like(pattern),
                    AgentTraceSpan.tool_name.like(pattern),
                    AgentTraceSpan.payload_json.like(pattern),
                )
            )
        return db.exec(statement.order_by(col(AgentTraceSpan.sequence).asc()).limit(max(1, min(limit, 500)))).all()
    finally:
        if should_close:
            db.close()


def _serialize_memory_injection(event: MemoryInjectionEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "project_id": event.project_id,
        "actor_type": event.actor_type,
        "stage": event.stage,
        "source_type": event.source_type,
        "source_id": event.source_id,
        "query": _redacted_text(event.query, 1000),
        "memory_ids": event.memory_ids,
        "context_preview": _redacted_text(event.context_preview, 2000),
        "outcome": event.outcome,
        "extra_data": safe_event_payload(event.extra_data or {}),
        "created_at": event.created_at.isoformat(),
    }


async def trace_bundle_for_run(
    *,
    run: AgentRun,
    session: Session,
    include_temporal: bool = True,
) -> dict[str, Any]:
    from orchestrator.services.agent_run_events import event_to_response

    snapshot = ensure_trace_snapshot(run_id=run.id, session=session)
    spans = list_trace_spans(run_id=run.id, limit=500, session=session)
    events = session.exec(
        select(AgentRunEvent).where(AgentRunEvent.run_id == run.id).order_by(col(AgentRunEvent.sequence).asc()).limit(500)
    ).all()
    memory_statement = select(MemoryInjectionEvent)
    if run.project_id:
        memory_statement = memory_statement.where(
            (MemoryInjectionEvent.project_id == run.project_id) | (MemoryInjectionEvent.project_id == None)
        )
    candidates = session.exec(memory_statement.order_by(MemoryInjectionEvent.created_at.desc()).limit(500)).all()

    def _memory_links_run(event: MemoryInjectionEvent) -> bool:
        extra = event.extra_data or {}
        return (
            event.source_id == run.id
            or extra.get("agent_run_id") == run.id
            or extra.get("owner_id") == run.id
            or extra.get("run_id") == run.id
            or bool(snapshot and extra.get("trace_id") == snapshot.id)
        )

    memory_rows = [event for event in candidates if _memory_links_run(event)][:200]
    temporal: dict[str, Any] | None = None
    if include_temporal:
        try:
            from orchestrator.api.main import _agent_run_temporal_payload

            temporal = await _agent_run_temporal_payload(run)
        except Exception as exc:
            temporal = {"error": f"Temporal diagnostics unavailable: {exc}"}

    artifacts = []
    if snapshot:
        for label, path in [
            ("Redacted prompt", snapshot.prompt_artifact_path),
            ("Redacted context", snapshot.context_artifact_path),
        ]:
            if path:
                artifacts.append({"name": label, "path": path, "type": "trace"})
    artifacts.extend(
        [
            {"name": span.name, "path": span.artifact_path, "type": span.span_type}
            for span in spans
            if span.artifact_path
        ]
    )

    return {
        "snapshot": serialize_snapshot(snapshot),
        "spans": [serialize_span(span) for span in spans],
        "events": [event_to_response(event) for event in events],
        "memory_injections": [_serialize_memory_injection(row) for row in memory_rows],
        "artifacts": artifacts,
        "temporal": temporal,
        "correlation": {
            "run_id": run.id,
            "trace_id": snapshot.id if snapshot else None,
            "agent_task_id": run.agent_task_id,
            "temporal_workflow_id": run.temporal_workflow_id,
            "temporal_run_id": run.temporal_run_id,
            "project_id": run.project_id,
        },
    }
