"""Telemetry for memory context injection and outcomes."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlmodel import Session

from orchestrator.api.db import engine
from orchestrator.api.models_db import MemoryInjectionEvent


def _memory_ids_from_bundle(bundle: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    if "unified" in bundle and isinstance(bundle.get("unified"), dict):
        bundle = bundle["unified"]
    agent_memories = bundle.get("agent_memories") or {}
    for items in agent_memories.values():
        for item in items or []:
            memory_id = item.get("id")
            if memory_id and memory_id not in ids:
                ids.append(str(memory_id))
    return ids


def _graph_memory_ids_from_bundle(bundle: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    if "unified" in bundle and isinstance(bundle.get("unified"), dict):
        bundle = bundle["unified"]
    memory_graph = bundle.get("memory_graph") or {}
    for item in memory_graph.get("related_memories", []) or []:
        memory_id = item.get("id")
        if memory_id and memory_id not in ids:
            ids.append(str(memory_id))
    return ids


def record_memory_injection(
    *,
    project_id: str | None = None,
    actor_type: str,
    stage: str,
    query: str = "",
    bundle: dict[str, Any] | None = None,
    context_text: str = "",
    source_type: str | None = None,
    source_id: str | None = None,
    conversation_id: str | None = None,
    message_index: int | None = None,
    outcome: str = "injected",
    extra_data: dict[str, Any] | None = None,
) -> MemoryInjectionEvent | None:
    """Best-effort durable record of what memory was injected into a prompt."""

    try:
        bundle = bundle or {}
        memory_ids = _memory_ids_from_bundle(bundle)
        graph_memory_ids = [memory_id for memory_id in _graph_memory_ids_from_bundle(bundle) if memory_id not in memory_ids]
        event_extra = dict(extra_data or {})
        if conversation_id:
            event_extra["conversation_id"] = conversation_id
        if message_index is not None:
            event_extra["message_index"] = message_index
        if graph_memory_ids:
            event_extra["graph_expanded_memory_ids"] = graph_memory_ids
        event = MemoryInjectionEvent(
            project_id=project_id,
            actor_type=actor_type,
            stage=stage,
            source_type=source_type,
            source_id=source_id,
            query=query[:1000],
            memory_ids_json=json.dumps(memory_ids),
            context_preview=(context_text or "")[:2000],
            outcome=outcome,
            extra_data=event_extra,
            created_at=datetime.utcnow(),
        )
        with Session(engine) as session:
            session.add(event)
            session.commit()
            session.refresh(event)
            session.expunge(event)
        return event
    except Exception:
        return None
