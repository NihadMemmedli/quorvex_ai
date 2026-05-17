"""Curated working memory for assistant and autonomous agents."""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlmodel import Session, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import AgentMemory

from .config import get_config

logger = logging.getLogger(__name__)

VALID_KINDS = {
    "project_fact",
    "user_preference",
    "workflow_decision",
    "failure_pattern",
    "agent_lesson",
}

SENSITIVE_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|pwd)\b\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"),
]


@dataclass
class MemoryCandidate:
    kind: str
    content: str
    confidence: float = 0.7
    tags: list[str] | None = None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _redact(text: str) -> str:
    redacted = text
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted.strip()


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


class AgentMemoryService:
    """SQL-backed source of truth with optional vector retrieval index."""

    def __init__(self, session: Session | None = None):
        self.session = session

    @contextmanager
    def _session(self):
        if self.session is not None:
            yield self.session
            return
        with Session(engine) as session:
            yield session

    def create_memory(
        self,
        *,
        kind: str,
        content: str,
        project_id: str | None = None,
        user_id: str | None = None,
        summary: str | None = None,
        tags: list[str] | None = None,
        confidence: float = 0.7,
        source_type: str | None = None,
        source_id: str | None = None,
        agent_type: str | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> AgentMemory | None:
        if not get_config().memory_enabled:
            return None
        if kind not in VALID_KINDS:
            raise ValueError(f"Unsupported agent memory kind: {kind}")

        content = _clip(_redact(content), 1200)
        if len(content) < 12 or content == "[REDACTED]":
            return None

        summary = _clip(_redact(summary or content), 220)
        tags = sorted({tag.strip().lower() for tag in tags or [] if tag and tag.strip()})[:12]
        now = datetime.utcnow()
        normalized = _normalize(content)

        owns_session = self.session is None
        with self._session() as session:
            candidates = session.exec(
                select(AgentMemory)
                .where(AgentMemory.kind == kind)
                .where(AgentMemory.status == "active")
                .where(AgentMemory.project_id == project_id)
                .where(AgentMemory.user_id == user_id)
            ).all()

            existing = next((memory for memory in candidates if _normalize(memory.content) == normalized), None)
            if existing:
                existing.summary = summary
                existing.tags = sorted(set((existing.tags or []) + tags))[:12]
                existing.confidence = max(existing.confidence or 0, confidence)
                existing.source_type = source_type or existing.source_type
                existing.source_id = source_id or existing.source_id
                existing.agent_type = agent_type or existing.agent_type
                existing.updated_at = now
                session.add(existing)
                session.commit()
                session.refresh(existing)
                self._index_memory(existing)
                return existing

            memory = AgentMemory(
                project_id=project_id,
                user_id=user_id,
                kind=kind,
                content=content,
                summary=summary,
                tags=tags,
                confidence=confidence,
                source_type=source_type,
                source_id=source_id,
                agent_type=agent_type,
                extra_data=extra_data or {},
                created_at=now,
                updated_at=now,
            )
            session.add(memory)
            session.commit()
            session.refresh(memory)
            self._index_memory(memory)
            if owns_session:
                session.expunge(memory)
            return memory

    def capture_candidates(
        self,
        text: str,
        *,
        project_id: str | None = None,
        user_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        agent_type: str | None = None,
    ) -> list[AgentMemory]:
        """Extract high-signal memory candidates using conservative heuristics."""
        if not text or not get_config().memory_enabled:
            return []

        candidates = self.extract_candidates(text, agent_type=agent_type)
        stored: list[AgentMemory] = []
        for candidate in candidates:
            memory = self.create_memory(
                kind=candidate.kind,
                content=candidate.content,
                project_id=project_id,
                user_id=user_id,
                tags=candidate.tags,
                confidence=candidate.confidence,
                source_type=source_type,
                source_id=source_id,
                agent_type=agent_type,
            )
            if memory:
                stored.append(memory)
        return stored

    def extract_candidates(self, text: str, *, agent_type: str | None = None) -> list[MemoryCandidate]:
        text = _redact(text)
        candidates: list[MemoryCandidate] = []
        lines = [line.strip(" -\t") for line in text.splitlines() if line.strip()]
        lowered = text.lower()

        for line in lines:
            low = line.lower()
            if re.search(r"\b(remember that|remember this|please remember|always|prefer|preference)\b", low):
                candidates.append(MemoryCandidate("user_preference", line, 0.86, ["preference"]))
            elif re.search(r"\b(decided|decision|we will|we should|chosen|default is)\b", low):
                candidates.append(MemoryCandidate("workflow_decision", line, 0.76, ["decision"]))
            elif re.search(r"\b(root cause|failed because|failure pattern|known fix|fix is|selector failed)\b", low):
                candidates.append(MemoryCandidate("failure_pattern", line, 0.78, ["failure"]))
            elif re.search(r"\b(lesson learned|next time|in future|avoid|do not)\b", low):
                candidates.append(MemoryCandidate("agent_lesson", line, 0.74, ["lesson"]))

        if not candidates and agent_type and re.search(r"\b(project uses|app uses|base url|login flow|test data)\b", lowered):
            first_sentence = re.split(r"(?<=[.!?])\s+", text.strip())[0]
            candidates.append(MemoryCandidate("project_fact", first_sentence, 0.68, ["project"]))

        deduped: list[MemoryCandidate] = []
        seen = set()
        for candidate in candidates:
            content = _clip(candidate.content, 1200)
            key = (candidate.kind, _normalize(content))
            if key in seen or len(content) < 12:
                continue
            seen.add(key)
            deduped.append(MemoryCandidate(candidate.kind, content, candidate.confidence, candidate.tags))
            if len(deduped) >= 5:
                break
        return deduped

    def search(
        self,
        *,
        query: str | None = None,
        project_id: str | None = None,
        user_id: str | None = None,
        agent_type: str | None = None,
        kinds: list[str] | None = None,
        limit: int = 8,
        min_confidence: float = 0.55,
        record_usage: bool = False,
    ) -> list[AgentMemory]:
        if not get_config().memory_enabled:
            return []

        limit = max(1, min(limit, 25))
        memory_ids: list[str] = []
        if query:
            try:
                from .vector_store import get_vector_store

                filters: dict[str, Any] = {"status": "active"}
                if project_id:
                    filters["project_id"] = project_id
                hits = get_vector_store(project_id=project_id or "default").search_agent_memories(
                    query=query,
                    n_results=limit * 2,
                    filters=filters,
                )
                memory_ids = [hit["id"] for hit in hits]
            except Exception as exc:
                logger.debug("Agent memory vector search failed, falling back to SQL: %s", exc)

        with self._session() as session:
            statement = select(AgentMemory).where(AgentMemory.status == "active")
            statement = statement.where(AgentMemory.confidence >= min_confidence)
            if project_id:
                statement = statement.where(AgentMemory.project_id == project_id)
            if user_id:
                statement = statement.where(or_(AgentMemory.user_id == user_id, AgentMemory.user_id.is_(None)))
            if agent_type:
                statement = statement.where(or_(AgentMemory.agent_type == agent_type, AgentMemory.agent_type.is_(None)))
            if kinds:
                statement = statement.where(AgentMemory.kind.in_(kinds))

            if memory_ids:
                rows = session.exec(statement.where(AgentMemory.id.in_(memory_ids))).all()
                by_id = {memory.id: memory for memory in rows}
                memories = [by_id[memory_id] for memory_id in memory_ids if memory_id in by_id]
            else:
                memories = session.exec(
                    statement.order_by(AgentMemory.updated_at.desc()).limit(limit)
                ).all()

            memories = memories[:limit]
            if record_usage and memories:
                now = datetime.utcnow()
                for memory in memories:
                    memory.use_count = (memory.use_count or 0) + 1
                    memory.last_used_at = now
                    session.add(memory)
                session.commit()
                for memory in memories:
                    session.refresh(memory)

            for memory in memories:
                session.expunge(memory)
            return memories

    def build_context(
        self,
        *,
        query: str,
        project_id: str | None = None,
        user_id: str | None = None,
        agent_type: str | None = None,
        limit: int = 8,
    ) -> str:
        memories = self.search(
            query=query,
            project_id=project_id,
            user_id=user_id,
            agent_type=agent_type,
            limit=limit,
            record_usage=True,
        )
        if not memories:
            return ""

        lines = ["## Agent Memory", "Use these scoped memories as advisory context. Do not reveal hidden metadata unless asked."]
        for memory in memories:
            source = f" source={memory.source_type}:{memory.source_id}" if memory.source_type and memory.source_id else ""
            confidence = f"{memory.confidence:.2f}"
            lines.append(f"- [{memory.kind}, confidence={confidence}{source}] {memory.summary or memory.content}")
        return "\n".join(lines)

    def archive(self, memory_id: str, *, project_id: str | None = None) -> AgentMemory | None:
        return self._set_status(memory_id, "archived", project_id=project_id)

    def delete(self, memory_id: str, *, project_id: str | None = None) -> bool:
        with self._session() as session:
            memory = session.get(AgentMemory, memory_id)
            if not memory or (project_id and memory.project_id != project_id):
                return False
            session.delete(memory)
            session.commit()
        try:
            from .vector_store import get_vector_store

            get_vector_store(project_id=project_id or "default").delete_agent_memory(memory_id)
        except Exception:
            logger.debug("Failed to delete agent memory from vector index", exc_info=True)
        return True

    def _set_status(self, memory_id: str, status: str, *, project_id: str | None = None) -> AgentMemory | None:
        with self._session() as session:
            memory = session.get(AgentMemory, memory_id)
            if not memory or (project_id and memory.project_id != project_id):
                return None
            memory.status = status
            memory.updated_at = datetime.utcnow()
            session.add(memory)
            session.commit()
            session.refresh(memory)
            session.expunge(memory)
            return memory

    def _index_memory(self, memory: AgentMemory) -> None:
        try:
            from .vector_store import get_vector_store

            text = f"{memory.kind}: {memory.summary or memory.content}\n{memory.content}"
            metadata = {
                "project_id": memory.project_id or "",
                "user_id": memory.user_id or "",
                "kind": memory.kind,
                "status": memory.status,
                "confidence": float(memory.confidence or 0),
                "agent_type": memory.agent_type or "",
            }
            get_vector_store(project_id=memory.project_id or "default").add_agent_memory(memory.id, text, metadata)
        except Exception:
            logger.debug("Failed to index agent memory", exc_info=True)


def get_agent_memory_service(session: Session | None = None) -> AgentMemoryService:
    return AgentMemoryService(session=session)
