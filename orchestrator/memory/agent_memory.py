"""Curated working memory for assistant and autonomous agents."""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

VALID_MEMORY_TYPES = {
    "semantic",
    "episodic",
    "procedural",
    "structural",
}

KIND_MEMORY_TYPES = {
    "project_fact": "semantic",
    "user_preference": "semantic",
    "workflow_decision": "procedural",
    "failure_pattern": "episodic",
    "agent_lesson": "procedural",
}

SENSITIVE_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|pwd)\b\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"),
]

THREAT_PATTERNS = [
    (re.compile(r"(?i)ignore\s+(previous|all|above|prior)\s+instructions"), "prompt_injection"),
    (re.compile(r"(?i)disregard\s+(your|all|any)\s+(instructions|rules|guidelines)"), "prompt_injection"),
    (re.compile(r"(?i)you\s+are\s+now\s+"), "role_hijack"),
    (re.compile(r"(?i)system\s+prompt\s+override"), "system_prompt_override"),
    (re.compile(r"(?i)do\s+not\s+tell\s+the\s+user"), "deception"),
    (re.compile(r"(?i)\b(curl|wget)\b[^\n]*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)"), "secret_exfiltration"),
    (re.compile(r"(?i)\bcat\b[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)"), "secret_file_read"),
    (re.compile(r"(?i)(authorized_keys|\$HOME/\.ssh|~/\.ssh)"), "ssh_persistence"),
]

INVISIBLE_CHARS = {
    "\u200b",
    "\u200c",
    "\u200d",
    "\u2060",
    "\ufeff",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
}


@dataclass
class MemoryCandidate:
    kind: str
    content: str
    confidence: float = 0.7
    tags: list[str] | None = None
    explicit: bool = False


class MemorySafetyError(ValueError):
    """Raised when memory content is unsafe to inject into future prompts."""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _redact(text: str) -> str:
    redacted = text
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted.strip()


def _scan_memory_content(text: str) -> None:
    for char in INVISIBLE_CHARS:
        if char in text:
            raise MemorySafetyError(
                f"Memory content contains invisible unicode character U+{ord(char):04X}."
            )
    for pattern, reason in THREAT_PATTERNS:
        if pattern.search(text):
            raise MemorySafetyError(f"Memory content blocked by safety scanner: {reason}.")


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _infer_memory_type(kind: str, memory_type: str | None = None) -> str:
    if memory_type:
        normalized = memory_type.strip().lower()
        if normalized in VALID_MEMORY_TYPES:
            return normalized
        raise ValueError(f"Unsupported agent memory type: {memory_type}")
    return KIND_MEMORY_TYPES.get(kind, "semantic")


def _infer_scope(project_id: str | None = None, user_id: str | None = None, scope: str | None = None) -> str:
    if scope:
        normalized = scope.strip().lower()
        if normalized in {"global", "project", "user", "agent"}:
            return normalized
        raise ValueError(f"Unsupported agent memory scope: {scope}")
    if user_id:
        return "user"
    if project_id:
        return "project"
    return "global"


def _utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


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
        memory_type: str | None = None,
        scope: str | None = None,
        summary: str | None = None,
        tags: list[str] | None = None,
        confidence: float = 0.7,
        importance: float = 0.5,
        source_type: str | None = None,
        source_id: str | None = None,
        agent_type: str | None = None,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        supersedes_id: str | None = None,
        review_required: bool = False,
        last_verified_at: datetime | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> AgentMemory | None:
        if not get_config().memory_enabled:
            return None
        if kind not in VALID_KINDS:
            raise ValueError(f"Unsupported agent memory kind: {kind}")
        resolved_memory_type = _infer_memory_type(kind, memory_type)
        resolved_scope = _infer_scope(project_id=project_id, user_id=user_id, scope=scope)

        _scan_memory_content(content)
        if summary:
            _scan_memory_content(summary)
        content = _clip(_redact(content), 1200)
        if len(content) < 12 or content == "[REDACTED]":
            return None

        summary = _clip(_redact(summary or content), 220)
        tags = sorted({tag.strip().lower() for tag in tags or [] if tag and tag.strip()})[:12]
        now = datetime.utcnow()
        normalized = _normalize(content)
        confidence = max(0.0, min(1.0, confidence))
        importance = max(0.0, min(1.0, importance))
        valid_from = _utc_naive(valid_from)
        valid_until = _utc_naive(valid_until)
        last_verified_at = _utc_naive(last_verified_at)
        if valid_from and valid_until and valid_until < valid_from:
            raise ValueError("valid_until must be after valid_from")

        owns_session = self.session is None
        with self._session() as session:
            if supersedes_id:
                superseded = session.get(AgentMemory, supersedes_id)
                if superseded and (not project_id or superseded.project_id == project_id):
                    superseded.status = "superseded"
                    superseded.updated_at = now
                    session.add(superseded)

            candidates = session.exec(
                select(AgentMemory)
                .where(AgentMemory.kind == kind)
                .where(AgentMemory.status == "active")
                .where(AgentMemory.project_id == project_id)
                .where(AgentMemory.user_id == user_id)
                .where(AgentMemory.memory_type == resolved_memory_type)
            ).all()

            existing = next((memory for memory in candidates if _normalize(memory.content) == normalized), None)
            if existing:
                existing.summary = summary
                existing.tags = sorted(set((existing.tags or []) + tags))[:12]
                existing.confidence = max(existing.confidence or 0, confidence)
                existing.importance = max(existing.importance or 0, importance)
                existing.scope = resolved_scope
                existing.source_type = source_type or existing.source_type
                existing.source_id = source_id or existing.source_id
                existing.agent_type = agent_type or existing.agent_type
                existing.valid_from = valid_from or existing.valid_from
                existing.valid_until = valid_until or existing.valid_until
                existing.supersedes_id = supersedes_id or existing.supersedes_id
                existing.review_required = review_required or existing.review_required
                existing.last_verified_at = last_verified_at or existing.last_verified_at
                existing.updated_at = now
                session.add(existing)
                session.commit()
                session.refresh(existing)
                self._index_memory(existing)
                self._sync_knowledge_graph(existing)
                return existing

            memory = AgentMemory(
                project_id=project_id,
                user_id=user_id,
                kind=kind,
                memory_type=resolved_memory_type,
                scope=resolved_scope,
                content=content,
                summary=summary,
                tags=tags,
                confidence=confidence,
                importance=importance,
                source_type=source_type,
                source_id=source_id,
                agent_type=agent_type,
                valid_from=valid_from,
                valid_until=valid_until,
                supersedes_id=supersedes_id,
                review_required=review_required,
                last_verified_at=last_verified_at,
                extra_data=extra_data or {},
                created_at=now,
                updated_at=now,
            )
            session.add(memory)
            session.commit()
            session.refresh(memory)
            self._index_memory(memory)
            self._sync_knowledge_graph(memory)
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
                review_required=not candidate.explicit,
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
                explicit = bool(re.search(r"\b(remember that|remember this|please remember)\b", low))
                candidates.append(MemoryCandidate("user_preference", line, 0.86, ["preference"], explicit=explicit))
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
            deduped.append(
                MemoryCandidate(candidate.kind, content, candidate.confidence, candidate.tags, candidate.explicit)
            )
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
        memory_types: list[str] | None = None,
        scope: str | None = None,
        limit: int = 8,
        min_confidence: float = 0.55,
        record_usage: bool = False,
        include_review_required: bool = True,
    ) -> list[AgentMemory]:
        if not get_config().memory_enabled:
            return []

        limit = max(1, min(limit, 25))
        now = datetime.utcnow()
        resolved_memory_types = None
        if memory_types:
            resolved_memory_types = [_infer_memory_type("", item) for item in memory_types]
        resolved_scope = _infer_scope(scope=scope) if scope else None
        memory_ids: list[str] = []
        if query:
            try:
                from .vector_store import get_vector_store

                stores = [project_id or "default"]
                if project_id:
                    stores.append("default")
                seen_store_ids: set[str] = set()
                for store_project_id in stores:
                    if store_project_id in seen_store_ids:
                        continue
                    seen_store_ids.add(store_project_id)
                    filters: dict[str, Any] = {"status": "active"}
                    if resolved_scope:
                        filters["scope"] = resolved_scope
                    hits = get_vector_store(project_id=store_project_id).search_agent_memories(
                        query=query,
                        n_results=limit * 3,
                        filters=filters,
                    )
                    for hit in hits:
                        memory_id = hit["id"]
                        if memory_id not in memory_ids:
                            memory_ids.append(memory_id)
            except Exception as exc:
                logger.debug("Agent memory vector search failed, falling back to SQL: %s", exc)

        with self._session() as session:
            statement = select(AgentMemory).where(AgentMemory.status == "active")
            statement = statement.where(AgentMemory.confidence >= min_confidence)
            statement = statement.where(or_(AgentMemory.valid_from.is_(None), AgentMemory.valid_from <= now))
            statement = statement.where(or_(AgentMemory.valid_until.is_(None), AgentMemory.valid_until >= now))
            if not include_review_required:
                statement = statement.where(AgentMemory.review_required.is_(False))
            if scope:
                if project_id:
                    statement = statement.where(or_(AgentMemory.project_id == project_id, AgentMemory.project_id.is_(None)))
                elif user_id:
                    statement = statement.where(or_(AgentMemory.user_id == user_id, AgentMemory.user_id.is_(None)))
            elif project_id and user_id:
                statement = statement.where(
                    or_(
                        AgentMemory.scope == "global",
                        AgentMemory.project_id == project_id,
                        AgentMemory.user_id == user_id,
                    )
                )
            elif project_id:
                statement = statement.where(or_(AgentMemory.scope == "global", AgentMemory.project_id == project_id))
            elif user_id:
                statement = statement.where(or_(AgentMemory.scope == "global", AgentMemory.user_id == user_id))
            if user_id:
                statement = statement.where(or_(AgentMemory.user_id == user_id, AgentMemory.user_id.is_(None)))
            if agent_type:
                statement = statement.where(or_(AgentMemory.agent_type == agent_type, AgentMemory.agent_type.is_(None)))
            if kinds:
                statement = statement.where(AgentMemory.kind.in_(kinds))
            if resolved_memory_types:
                statement = statement.where(AgentMemory.memory_type.in_(resolved_memory_types))
            if resolved_scope:
                statement = statement.where(AgentMemory.scope == resolved_scope)

            if memory_ids:
                rows = session.exec(statement.where(AgentMemory.id.in_(memory_ids))).all()
                by_id = {memory.id: memory for memory in rows}
                memories = [by_id[memory_id] for memory_id in memory_ids if memory_id in by_id]
                if len(memories) < limit:
                    missing = limit - len(memories)
                    seen_ids = {memory.id for memory in memories}
                    fallback = session.exec(
                        statement.where(AgentMemory.id.notin_(seen_ids))
                        .order_by(
                            AgentMemory.importance.desc(),
                            AgentMemory.confidence.desc(),
                            AgentMemory.use_count.desc(),
                            AgentMemory.updated_at.desc(),
                        )
                        .limit(missing)
                    ).all()
                    memories.extend(fallback)
            else:
                memories = session.exec(
                    statement.order_by(
                        AgentMemory.importance.desc(),
                        AgentMemory.confidence.desc(),
                        AgentMemory.use_count.desc(),
                        AgentMemory.updated_at.desc(),
                    ).limit(limit)
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
        from .context_builder import MemoryContextBuilder

        return MemoryContextBuilder(service=self).build_prompt_context(
            query=query,
            project_id=project_id,
            user_id=user_id,
            agent_type=agent_type,
            limit=limit,
        )

    def update_memory(self, memory_id: str, *, project_id: str | None = None, **updates: Any) -> AgentMemory | None:
        allowed = {
            "kind",
            "content",
            "memory_type",
            "scope",
            "summary",
            "tags",
            "confidence",
            "importance",
            "source_type",
            "source_id",
            "agent_type",
            "valid_from",
            "valid_until",
            "supersedes_id",
            "review_required",
            "last_verified_at",
            "extra_data",
            "status",
        }
        updates = {key: value for key, value in updates.items() if key in allowed and value is not None}
        if not updates:
            with self._session() as session:
                memory = session.get(AgentMemory, memory_id)
                if not memory or (project_id and memory.project_id != project_id):
                    return None
                session.expunge(memory)
                return memory

        with self._session() as session:
            memory = session.get(AgentMemory, memory_id)
            if not memory or (project_id and memory.project_id != project_id):
                return None
            if "kind" in updates and updates["kind"] not in VALID_KINDS:
                raise ValueError(f"Unsupported agent memory kind: {updates['kind']}")
            if "memory_type" in updates:
                updates["memory_type"] = _infer_memory_type("", updates["memory_type"])
            elif "kind" in updates:
                updates["memory_type"] = _infer_memory_type(updates["kind"], None)
            if "scope" in updates:
                updates["scope"] = _infer_scope(scope=updates["scope"])
            if "content" in updates:
                _scan_memory_content(updates["content"])
                updates["content"] = _clip(_redact(updates["content"]), 1200)
                if len(updates["content"]) < 12 or updates["content"] == "[REDACTED]":
                    raise ValueError("Memory content is empty or fully redacted")
            if "summary" in updates:
                _scan_memory_content(updates["summary"])
                updates["summary"] = _clip(_redact(updates["summary"]), 220)
            if "tags" in updates:
                updates["tags"] = sorted({tag.strip().lower() for tag in updates["tags"] or [] if tag and tag.strip()})[:12]
            if "confidence" in updates:
                updates["confidence"] = max(0.0, min(1.0, float(updates["confidence"])))
            if "importance" in updates:
                updates["importance"] = max(0.0, min(1.0, float(updates["importance"])))
            for key in ("valid_from", "valid_until", "last_verified_at"):
                if key in updates:
                    updates[key] = _utc_naive(updates[key])
            valid_from = updates.get("valid_from", memory.valid_from)
            valid_until = updates.get("valid_until", memory.valid_until)
            if valid_from and valid_until and valid_until < valid_from:
                raise ValueError("valid_until must be after valid_from")
            for key, value in updates.items():
                setattr(memory, key, value)
            memory.updated_at = datetime.utcnow()
            session.add(memory)
            session.commit()
            session.refresh(memory)
            self._index_memory(memory)
            self._sync_knowledge_graph(memory)
            session.expunge(memory)
            return memory

    def approve(self, memory_id: str, *, project_id: str | None = None) -> AgentMemory | None:
        return self.update_memory(
            memory_id,
            project_id=project_id,
            review_required=False,
            status="active",
            last_verified_at=datetime.utcnow(),
        )

    def verify(self, memory_id: str, *, project_id: str | None = None) -> AgentMemory | None:
        return self.update_memory(memory_id, project_id=project_id, last_verified_at=datetime.utcnow())

    def verify_stale(
        self,
        *,
        project_id: str | None = None,
        older_than_days: int = 30,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Best-effort verification pass for stale memories.

        This does not pretend to prove all facts. It verifies URL-backed memories
        against the application graph when possible and otherwise marks stale
        high-impact memories for human review instead of injecting them blindly.
        """

        cutoff = datetime.utcnow() - timedelta(days=max(1, older_than_days))
        limit = max(1, min(limit, 200))
        stats = {"checked": 0, "verified": 0, "review_required": 0, "confidence_reduced": 0}
        updated: list[AgentMemory] = []

        with self._session() as session:
            statement = select(AgentMemory).where(AgentMemory.status == "active")
            statement = statement.where(
                or_(AgentMemory.last_verified_at.is_(None), AgentMemory.last_verified_at < cutoff)
            )
            if project_id:
                statement = statement.where(AgentMemory.project_id == project_id)
            memories = session.exec(
                statement.order_by(AgentMemory.importance.desc(), AgentMemory.updated_at.asc()).limit(limit)
            ).all()

            known_urls = self._known_project_urls(project_id)
            now = datetime.utcnow()
            for memory in memories:
                stats["checked"] += 1
                content = f"{memory.content}\n{memory.summary or ''}"
                urls = re.findall(r"https?://[^\s\"'<>),]+", content)
                if urls and known_urls:
                    if any(url.rstrip(".,;:!?") in known_urls for url in urls):
                        memory.last_verified_at = now
                        stats["verified"] += 1
                    else:
                        memory.review_required = True
                        memory.confidence = max(0.25, float(memory.confidence or 0.7) - 0.15)
                        stats["review_required"] += 1
                        stats["confidence_reduced"] += 1
                elif memory.importance >= 0.75 or memory.confidence < 0.65:
                    memory.review_required = True
                    stats["review_required"] += 1
                else:
                    memory.last_verified_at = now
                    stats["verified"] += 1
                memory.updated_at = now
                session.add(memory)

            session.commit()
            for memory in memories:
                session.refresh(memory)
                session.expunge(memory)
                updated.append(memory)

        stats["memories"] = updated
        return stats

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
        try:
            from .knowledge_graph import get_memory_knowledge_graph_service

            get_memory_knowledge_graph_service().mark_memory_deleted(memory_id, project_id=project_id)
        except Exception:
            logger.debug("Failed to mark memory deleted in knowledge graph", exc_info=True)
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
            self._sync_knowledge_graph(memory)
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
                "memory_type": memory.memory_type or "semantic",
                "scope": memory.scope or "project",
                "status": memory.status,
                "confidence": float(memory.confidence or 0),
                "importance": float(memory.importance or 0),
                "agent_type": memory.agent_type or "",
            }
            get_vector_store(project_id=memory.project_id or "default").add_agent_memory(memory.id, text, metadata)
        except Exception:
            logger.debug("Failed to index agent memory", exc_info=True)

    def _sync_knowledge_graph(self, memory: AgentMemory) -> None:
        try:
            from .knowledge_graph import get_memory_knowledge_graph_service

            get_memory_knowledge_graph_service().upsert_memory_graph(memory)
        except Exception:
            logger.debug("Failed to sync agent memory knowledge graph", exc_info=True)

    def _known_project_urls(self, project_id: str | None) -> set[str]:
        if not project_id:
            return set()
        try:
            from .manager import get_memory_manager

            graph = get_memory_manager(project_id=project_id).graph_store.graph
            urls = set()
            for node in graph.nodes():
                attrs = graph.nodes[node]
                if attrs.get("type") == "page" and attrs.get("url"):
                    urls.add(str(attrs["url"]).rstrip(".,;:!?"))
            return urls
        except Exception:
            return set()


def get_agent_memory_service(session: Session | None = None) -> AgentMemoryService:
    return AgentMemoryService(session=session)
