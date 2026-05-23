"""Feedback attribution for memory injection and graph scoring."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import (
    AgentMemory,
    MemoryFeedbackAggregate,
    MemoryFeedbackEvent,
    MemoryInjectionEvent,
)

logger = logging.getLogger(__name__)

VALID_FEEDBACK_RATINGS = {"up": 1.0, "down": -1.0}


@dataclass(frozen=True)
class MemoryFeedbackStats:
    memory_id: str
    positive_feedback_count: int = 0
    negative_feedback_count: int = 0
    feedback_score: float = 0.0
    last_feedback_at: datetime | None = None

    @property
    def total_feedback(self) -> int:
        return int(self.positive_feedback_count or 0) + int(self.negative_feedback_count or 0)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _memory_ids_for_injection(event: MemoryInjectionEvent) -> list[str]:
    ids = list(event.memory_ids)
    extra = event.extra_data or {}
    graph_ids = extra.get("graph_expanded_memory_ids")
    if isinstance(graph_ids, list):
        ids.extend(str(memory_id) for memory_id in graph_ids if memory_id)
    return list(dict.fromkeys(ids))


class MemoryFeedbackService:
    """Record feedback signals and expose bounded graph score adjustments."""

    def __init__(self, session: Session | None = None):
        self.session = session

    @contextmanager
    def _session(self):
        if self.session is not None:
            yield self.session
            return
        with Session(engine) as session:
            yield session

    def apply_feedback_to_injection(
        self,
        injection_event_id: str,
        *,
        rating: str,
        user_id: str | None = None,
        comment: str | None = None,
        source: str = "manual_dashboard",
    ) -> dict[str, Any]:
        signal = self._signal_for_rating(rating)
        with self._session() as session:
            event = session.get(MemoryInjectionEvent, injection_event_id)
            if not event:
                raise ValueError("Memory injection event not found")
            memory_ids = _memory_ids_for_injection(event)
            recorded = []
            for memory_id in memory_ids:
                memory = session.get(AgentMemory, memory_id)
                if not memory or (event.project_id and memory.project_id != event.project_id):
                    continue
                feedback = self._upsert_feedback_event(
                    session,
                    memory_id=memory_id,
                    project_id=event.project_id,
                    injection_event_id=event.id,
                    conversation_id=self._extra_string(event.extra_data, "conversation_id"),
                    message_index=self._extra_int(event.extra_data, "message_index"),
                    rating=rating,
                    signal=signal,
                    source=source,
                    comment=comment,
                    user_id=user_id,
                )
                self._recompute_aggregate(session, project_id=event.project_id, memory_id=memory_id)
                recorded.append(feedback)
            session.commit()
            return {
                "injection_event_id": injection_event_id,
                "memory_ids": [item.memory_id for item in recorded],
                "count": len(recorded),
            }

    def record_memory_feedback(
        self,
        *,
        memory_id: str,
        rating: str,
        project_id: str | None = None,
        source: str = "manual_dashboard",
        injection_event_id: str | None = None,
        conversation_id: str | None = None,
        message_index: int | None = None,
        user_id: str | None = None,
        comment: str | None = None,
    ) -> MemoryFeedbackEvent:
        signal = self._signal_for_rating(rating)
        with self._session() as session:
            memory = session.get(AgentMemory, memory_id)
            if not memory or (project_id and memory.project_id != project_id):
                raise ValueError("Memory not found")
            resolved_project_id = project_id if project_id is not None else memory.project_id
            event = self._upsert_feedback_event(
                session,
                memory_id=memory_id,
                project_id=resolved_project_id,
                injection_event_id=injection_event_id,
                conversation_id=conversation_id,
                message_index=message_index,
                rating=rating,
                signal=signal,
                source=source,
                comment=comment,
                user_id=user_id,
            )
            self._recompute_aggregate(session, project_id=resolved_project_id, memory_id=memory_id)
            session.commit()
            session.refresh(event)
            session.expunge(event)
            return event

    def get_memory_feedback_stats(
        self,
        *,
        project_id: str | None = None,
        memory_ids: list[str] | None = None,
    ) -> dict[str, MemoryFeedbackStats]:
        memory_ids = [memory_id for memory_id in dict.fromkeys(memory_ids or []) if memory_id]
        if not memory_ids:
            return {}
        with self._session() as session:
            statement = select(MemoryFeedbackAggregate).where(MemoryFeedbackAggregate.memory_id.in_(memory_ids))
            if project_id:
                statement = statement.where(MemoryFeedbackAggregate.project_id == project_id)
            rows = session.exec(statement).all()
            return {
                row.memory_id: MemoryFeedbackStats(
                    memory_id=row.memory_id,
                    positive_feedback_count=row.positive_feedback_count or 0,
                    negative_feedback_count=row.negative_feedback_count or 0,
                    feedback_score=float(row.feedback_score or 0.0),
                    last_feedback_at=row.last_feedback_at,
                )
                for row in rows
            }

    def feedback_adjustment(self, stats: MemoryFeedbackStats | None) -> float:
        if not stats or stats.total_feedback <= 0:
            return 0.0
        return _clamp(float(stats.feedback_score or 0.0) / max(stats.total_feedback, 3), -0.25, 0.25)

    def feedback_summary_for_injections(
        self,
        injection_event_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        injection_event_ids = [event_id for event_id in dict.fromkeys(injection_event_ids or []) if event_id]
        if not injection_event_ids:
            return {}
        with self._session() as session:
            rows = session.exec(
                select(MemoryFeedbackEvent).where(MemoryFeedbackEvent.injection_event_id.in_(injection_event_ids))
            ).all()
            summary: dict[str, dict[str, Any]] = {}
            for row in rows:
                if not row.injection_event_id:
                    continue
                item = summary.setdefault(
                    row.injection_event_id,
                    {"total": 0, "positive": 0, "negative": 0, "latest_rating": None, "latest_at": None},
                )
                item["total"] += 1
                if row.signal > 0:
                    item["positive"] += 1
                elif row.signal < 0:
                    item["negative"] += 1
                latest_at = row.created_at.isoformat()
                if not item["latest_at"] or latest_at > item["latest_at"]:
                    item["latest_at"] = latest_at
                    item["latest_rating"] = row.rating
            return summary

    def _upsert_feedback_event(
        self,
        session: Session,
        *,
        memory_id: str,
        project_id: str | None,
        injection_event_id: str | None,
        conversation_id: str | None,
        message_index: int | None,
        rating: str,
        signal: float,
        source: str,
        comment: str | None,
        user_id: str | None,
    ) -> MemoryFeedbackEvent:
        statement = (
            select(MemoryFeedbackEvent)
            .where(MemoryFeedbackEvent.memory_id == memory_id)
            .where(MemoryFeedbackEvent.source == source)
        )
        if injection_event_id:
            statement = statement.where(MemoryFeedbackEvent.injection_event_id == injection_event_id)
        if conversation_id:
            statement = statement.where(MemoryFeedbackEvent.conversation_id == conversation_id)
        if message_index is not None:
            statement = statement.where(MemoryFeedbackEvent.message_index == message_index)
        if user_id:
            statement = statement.where(MemoryFeedbackEvent.user_id == user_id)
        existing = session.exec(statement).first()
        now = datetime.utcnow()
        if existing:
            existing.rating = rating
            existing.signal = signal
            existing.comment = comment
            existing.created_at = now
            session.add(existing)
            session.flush()
            return existing
        event = MemoryFeedbackEvent(
            project_id=project_id,
            memory_id=memory_id,
            injection_event_id=injection_event_id,
            conversation_id=conversation_id,
            message_index=message_index,
            rating=rating,
            signal=signal,
            source=source,
            comment=comment,
            user_id=user_id,
            created_at=now,
        )
        session.add(event)
        session.flush()
        return event

    def _recompute_aggregate(self, session: Session, *, project_id: str | None, memory_id: str) -> MemoryFeedbackAggregate:
        project_key = project_id or "__global__"
        rows = session.exec(
            select(MemoryFeedbackEvent)
            .where(MemoryFeedbackEvent.project_id == project_id)
            .where(MemoryFeedbackEvent.memory_id == memory_id)
        ).all()
        positive = sum(1 for row in rows if row.signal > 0)
        negative = sum(1 for row in rows if row.signal < 0)
        score = sum(float(row.signal or 0.0) for row in rows)
        last = max((row.created_at for row in rows), default=None)
        aggregate = session.exec(
            select(MemoryFeedbackAggregate)
            .where(MemoryFeedbackAggregate.project_key == project_key)
            .where(MemoryFeedbackAggregate.memory_id == memory_id)
        ).first()
        now = datetime.utcnow()
        if aggregate is None:
            aggregate = MemoryFeedbackAggregate(
                project_id=project_id,
                project_key=project_key,
                memory_id=memory_id,
                positive_feedback_count=positive,
                negative_feedback_count=negative,
                feedback_score=score,
                last_feedback_at=last,
                updated_at=now,
            )
        else:
            aggregate.project_id = project_id
            aggregate.project_key = project_key
            aggregate.positive_feedback_count = positive
            aggregate.negative_feedback_count = negative
            aggregate.feedback_score = score
            aggregate.last_feedback_at = last
            aggregate.updated_at = now
        session.add(aggregate)
        session.flush()
        return aggregate

    def _signal_for_rating(self, rating: str) -> float:
        normalized = (rating or "").strip().lower()
        if normalized not in VALID_FEEDBACK_RATINGS:
            raise ValueError("Rating must be 'up' or 'down'")
        return VALID_FEEDBACK_RATINGS[normalized]

    def _extra_string(self, extra_data: dict[str, Any] | None, key: str) -> str | None:
        value = (extra_data or {}).get(key)
        return str(value) if value is not None else None

    def _extra_int(self, extra_data: dict[str, Any] | None, key: str) -> int | None:
        value = (extra_data or {}).get(key)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None


def get_memory_feedback_service(session: Session | None = None) -> MemoryFeedbackService:
    return MemoryFeedbackService(session=session)
