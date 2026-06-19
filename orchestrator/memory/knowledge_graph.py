"""SQL-backed relationship graph for curated agent memories."""

from __future__ import annotations

import json
import logging
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import or_
from sqlmodel import Session, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import AgentMemory, MemoryGraphEdge, MemoryGraphNode
from orchestrator.utils.json_utils import extract_json_from_markdown

from .agent_memory import _scan_memory_content

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"https?://[^\s\"'<>),]+")
SELECTOR_PATTERN = re.compile(r"\b(getByRole|getByText|getByLabel|locator|selector|data-testid|aria-label)\b", re.I)
PLAYWRIGHT_LOCATOR_PATTERN = re.compile(
    r"(getByRole\([^)]+\)|getByText\([^)]+\)|getByLabel\([^)]+\)|getByTestId\([^)]+\)|locator\([^)]+\)|data-testid[=:][\w.-]+|aria-label[=:][^,\s]+)",
    re.I,
)
TOPIC_PATTERN = re.compile(
    r"\b("
    r"login|checkout|auth|authentication|dashboard|selector|playwright|healer|planner|generator|"
    r"custom agent|memory|browser|regression|api|workflow|frontier|coverage|credential|environment"
    r")\b",
    re.I,
)
CAUSE_PATTERN = re.compile(r"\b(?:root cause|failed because|failure pattern|caused by|because)\b[:\s-]*(.{12,180})", re.I)
FIX_PATTERN = re.compile(r"\b(?:known fix|fix is|fix:|fixed by|resolved by|workaround|instead use|use getbyrole|use locator)\b[:\s-]*(.{12,180})", re.I)
CONTRADICTION_PATTERN = re.compile(
    r"\b(?:do not use|don't use|no longer|not true|instead of|deprecated|changed from|replaced|avoid)\b.{0,180}",
    re.I,
)
SUPERSEDES_PATTERN = re.compile(r"\b(?:now use|replaced by|changed to|instead use|supersedes|new default)\b.{0,180}", re.I)
VOLATILE_TOKEN_PATTERN = re.compile(
    r"\b([0-9a-f]{8,}|[0-9]{3,}|run_[\w-]+|tmp[\w.-]*|/[^,\s]+)\b",
    re.I,
)

VALID_NODE_TYPES = {"memory", "entity", "topic", "workflow", "failure", "selector", "page", "agent"}
VALID_RELATIONSHIPS = {
    "supports",
    "contradicts",
    "supersedes",
    "caused_by",
    "fixes",
    "mentions",
    "belongs_to",
    "related_to",
    "observed_on",
}
RISKY_LLM_RELATIONSHIPS = {"contradicts", "supersedes", "caused_by"}
MAX_EXTRACTED_ENTITIES = 12
LLM_ENTITY_RESERVE = 4


@dataclass(frozen=True)
class ExtractedEntity:
    node_type: str
    label: str
    entity_key: str
    relationship_type: str = "mentions"
    weight: float = 0.65
    rule: str = "heuristic"
    evidence: str | None = None
    polarity: str = "neutral"
    status: str = "active"


@dataclass(frozen=True)
class LLMExtractionDecision:
    enabled: bool
    reason: str
    forced: bool = False


@dataclass(frozen=True)
class ExtractedRelationship:
    target_node_id: str
    relationship_type: str
    weight: float
    rule: str
    evidence: str | None = None
    polarity: str = "neutral"


def _clip(text: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."


def _entity_key(node_type: str, label: str) -> str:
    normalized = re.sub(r"[^a-z0-9:/._-]+", "-", str(label or "").strip().lower()).strip("-")
    normalized = normalized[:180] or "unknown"
    return f"{node_type}:{normalized}"


def _memory_item(
    memory: AgentMemory,
    *,
    reason: str | None = None,
    score: float | None = None,
    base_score: float | None = None,
    feedback_score: float = 0.0,
    feedback_adjustment: float = 0.0,
    positive_feedback_count: int = 0,
    negative_feedback_count: int = 0,
) -> dict[str, Any]:
    return {
        "id": memory.id,
        "kind": memory.kind,
        "memory_type": memory.memory_type or "semantic",
        "scope": memory.scope or "project",
        "summary": memory.summary or memory.content,
        "confidence": round(float(memory.confidence or 0), 3),
        "importance": round(float(memory.importance or 0), 3),
        "source_type": memory.source_type,
        "source_id": memory.source_id,
        "review_required": bool(memory.review_required),
        "last_verified_at": memory.last_verified_at.isoformat() if memory.last_verified_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
        "graph_reason": reason,
        "base_graph_score": round(float(base_score if base_score is not None else score or 0), 3) if score is not None or base_score is not None else None,
        "graph_score": round(float(score or 0), 3) if score is not None else None,
        "feedback_score": round(float(feedback_score or 0), 3),
        "feedback_adjustment": round(float(feedback_adjustment or 0), 3),
        "positive_feedback_count": int(positive_feedback_count or 0),
        "negative_feedback_count": int(negative_feedback_count or 0),
    }


def normalize_route_entity(url: str) -> str:
    parsed = urlparse(url.rstrip(".,;:!?"))
    path = parsed.path or "/"
    parts = []
    for part in path.strip("/").split("/"):
        if not part:
            continue
        if re.fullmatch(r"\d+|[0-9a-f]{8,}|[A-Za-z0-9_-]{16,}", part):
            parts.append("{id}")
        else:
            parts.append(part.lower())
    normalized_path = "/" + "/".join(parts) if parts else "/"
    host = parsed.netloc.lower()
    return f"{parsed.scheme.lower()}://{host}{normalized_path}" if host else normalized_path


def normalize_selector_entity(text: str) -> str:
    return _clip(re.sub(r"\s+", " ", text.strip()), 140)


def normalize_error_entity(text: str) -> str:
    return _clip(VOLATILE_TOKEN_PATTERN.sub("{var}", re.sub(r"\s+", " ", text.strip())), 140)


class MemoryKnowledgeGraphService:
    """Derived relationship graph that explains and expands memory retrieval."""

    def __init__(self, session: Session | None = None):
        self.session = session

    @contextmanager
    def _session(self):
        if self.session is not None:
            yield self.session
            return
        with Session(engine) as session:
            yield session

    def upsert_memory_graph(self, memory: AgentMemory, *, use_llm: bool = False) -> dict[str, int]:
        if not memory or not memory.id:
            return {"nodes": 0, "edges": 0}

        with self._session() as session:
            memory_node = self._upsert_node(
                session,
                project_id=memory.project_id,
                node_type="memory",
                entity_key=f"memory:{memory.id}",
                label=_clip(memory.summary or memory.content, 220),
                memory_id=memory.id,
                confidence=float(memory.confidence or 0.7),
                status=memory.status or "active",
                extra_data={
                    "kind": memory.kind,
                    "memory_type": memory.memory_type or "semantic",
                    "scope": memory.scope or "project",
                    "review_required": bool(memory.review_required),
                    "importance": float(memory.importance or 0.5),
                },
            )

            nodes_changed = 1
            edges_changed = 0
            if memory.status != "active" or memory.review_required:
                self._set_memory_edges_status(session, memory_node.id, "inactive")
                session.commit()
                return {"nodes": nodes_changed, "edges": edges_changed}

            entities = self.extract_entities(memory, use_llm=use_llm)
            for entity in entities:
                entity_node = self._upsert_node(
                    session,
                    project_id=memory.project_id,
                    node_type=entity.node_type,
                    entity_key=entity.entity_key,
                    label=entity.label,
                    confidence=max(0.25, min(1.0, float(memory.confidence or 0.7) * entity.weight)),
                    status="active",
                    extra_data={
                        "source_memory_id": memory.id,
                        "extractor": "llm" if entity.rule.startswith("llm") else "heuristic",
                        "rule": entity.rule,
                        "evidence": entity.evidence,
                        "polarity": entity.polarity,
                    },
                )
                nodes_changed += 1
                self._upsert_edge(
                    session,
                    project_id=memory.project_id,
                    source_node_id=memory_node.id,
                    target_node_id=entity_node.id,
                    relationship_type=entity.relationship_type,
                    weight=entity.weight,
                    evidence_memory_id=memory.id,
                    status=entity.status,
                    extra_data={
                        "extractor": "llm" if entity.rule.startswith("llm") else "heuristic",
                        "rule": entity.rule,
                        "evidence": entity.evidence,
                        "polarity": entity.polarity,
                        "review_required": entity.status == "pending_review",
                    },
                )
                edges_changed += 1

            if memory.supersedes_id:
                target = self._memory_node(session, memory.supersedes_id, memory.project_id)
                if target:
                    self._upsert_edge(
                        session,
                        project_id=memory.project_id,
                        source_node_id=memory_node.id,
                        target_node_id=target.id,
                        relationship_type="supersedes",
                        weight=0.95,
                        evidence_memory_id=memory.id,
                        extra_data={
                            "extractor": "heuristic",
                            "rule": "explicit_supersedes_id",
                            "evidence": memory.supersedes_id,
                            "polarity": "negative",
                        },
                    )
                    edges_changed += 1

            edges_changed += self._upsert_cross_memory_relationships(
                session,
                memory=memory,
                memory_node=memory_node,
                entities=entities,
            )

            session.commit()
            return {"nodes": nodes_changed, "edges": edges_changed}

    def extract_entities(self, memory: AgentMemory, *, use_llm: bool = False) -> list[ExtractedEntity]:
        text = f"{memory.summary or ''}\n{memory.content or ''}"
        heuristic_entities: list[ExtractedEntity] = []

        for tag in memory.tags or []:
            label = _clip(tag, 80)
            if label:
                heuristic_entities.append(ExtractedEntity("topic", label, _entity_key("topic", label), "belongs_to", 0.75, "tag", label))

        for url in URL_PATTERN.findall(text):
            clean = url.rstrip(".,;:!?")
            route = normalize_route_entity(clean)
            heuristic_entities.append(ExtractedEntity("page", clean, _entity_key("page", clean), "observed_on", 0.8, "url_exact", clean))
            if route != clean:
                heuristic_entities.append(ExtractedEntity("page", route, _entity_key("page", route), "observed_on", 0.72, "url_route", clean))

        for match in TOPIC_PATTERN.findall(text):
            label = _clip(match, 80).lower()
            heuristic_entities.append(ExtractedEntity("topic", label, _entity_key("topic", label), "mentions", 0.62, "topic_keyword", label))

        if memory.agent_type:
            label = _clip(memory.agent_type, 80)
            heuristic_entities.append(ExtractedEntity("agent", label, _entity_key("agent", label), "belongs_to", 0.6, "agent_type", label))

        if memory.kind == "workflow_decision":
            label = _clip(memory.summary or memory.content, 120)
            heuristic_entities.append(ExtractedEntity("workflow", label, _entity_key("workflow", label), "belongs_to", 0.72, "kind_workflow", label))

        if memory.kind == "failure_pattern":
            label = _clip(memory.summary or memory.content, 120)
            heuristic_entities.append(ExtractedEntity("failure", normalize_error_entity(label), _entity_key("failure", normalize_error_entity(label)), "belongs_to", 0.8, "kind_failure", label, "negative"))

        if SELECTOR_PATTERN.search(text):
            selector_matches = PLAYWRIGHT_LOCATOR_PATTERN.findall(text)
            if selector_matches:
                for selector in selector_matches[:5]:
                    label = normalize_selector_entity(selector)
                    heuristic_entities.append(ExtractedEntity("selector", label, _entity_key("selector", label), "mentions", 0.78, "selector_syntax", selector))
            else:
                label = _clip(memory.summary or memory.content, 120)
                heuristic_entities.append(ExtractedEntity("selector", label, _entity_key("selector", label), "mentions", 0.7, "selector_keyword", label))

        for match in CAUSE_PATTERN.findall(text):
            label = normalize_error_entity(match)
            heuristic_entities.append(ExtractedEntity("failure", label, _entity_key("failure", label), "caused_by", 0.78, "cause_phrase", match, "negative"))

        for match in FIX_PATTERN.findall(text):
            label = _clip(match, 120)
            heuristic_entities.append(ExtractedEntity("entity", label, _entity_key("fix", label), "fixes", 0.78, "fix_phrase", match, "positive"))

        for match in CONTRADICTION_PATTERN.findall(text):
            label = _clip(match, 120)
            heuristic_entities.append(ExtractedEntity("entity", label, _entity_key("contradiction", label), "contradicts", 0.82, "contradiction_phrase", match, "negative"))

        if float(memory.confidence or 0.0) >= 0.75:
            for match in SUPERSEDES_PATTERN.findall(text):
                label = _clip(match, 120)
                heuristic_entities.append(ExtractedEntity("entity", label, _entity_key("supersedes", label), "supersedes", 0.84, "supersedes_phrase", match, "negative"))

        llm_entities: list[ExtractedEntity] = []
        decision = self.llm_extraction_decision(memory, force=use_llm)
        if decision.enabled:
            try:
                llm_entities = self._extract_with_llm(memory)
            except Exception as exc:
                logger.debug("LLM memory graph extraction failed; using heuristics only: %s", exc)

        return self._dedupe_entities(heuristic_entities, llm_entities)

    def _dedupe_entities(
        self,
        heuristic_entities: list[ExtractedEntity],
        llm_entities: list[ExtractedEntity],
    ) -> list[ExtractedEntity]:
        deduped: list[ExtractedEntity] = []
        seen: set[tuple[str, str, str]] = set()

        def add(entity: ExtractedEntity) -> bool:
            if entity.node_type not in VALID_NODE_TYPES or entity.relationship_type not in VALID_RELATIONSHIPS:
                return False
            key = (entity.node_type, entity.entity_key, entity.relationship_type)
            if key in seen:
                return False
            seen.add(key)
            deduped.append(entity)
            return True

        llm_budget = min(LLM_ENTITY_RESERVE, len(llm_entities))
        heuristic_budget = MAX_EXTRACTED_ENTITIES - llm_budget
        for entity in heuristic_entities:
            if len(deduped) >= heuristic_budget:
                break
            add(entity)
        for entity in llm_entities:
            if len(deduped) >= MAX_EXTRACTED_ENTITIES:
                break
            add(entity)
        for entity in heuristic_entities:
            if len(deduped) >= MAX_EXTRACTED_ENTITIES:
                break
            add(entity)
        return deduped

    def get_related_memories(
        self,
        memory_ids: list[str],
        *,
        project_id: str | None = None,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        memory_ids = [memory_id for memory_id in dict.fromkeys(memory_ids or []) if memory_id]
        if not memory_ids:
            return []
        limit = max(1, min(limit, 25))

        with self._session() as session:
            source_nodes = session.exec(
                select(MemoryGraphNode)
                .where(MemoryGraphNode.node_type == "memory")
                .where(MemoryGraphNode.memory_id.in_(memory_ids))
                .where(MemoryGraphNode.status == "active")
            ).all()
            if project_id:
                source_nodes = [node for node in source_nodes if node.project_id == project_id]
            source_node_ids = {node.id for node in source_nodes}
            if not source_node_ids:
                return []

            entity_edges = session.exec(
                select(MemoryGraphEdge)
                .where(MemoryGraphEdge.source_node_id.in_(source_node_ids))
                .where(MemoryGraphEdge.status == "active")
            ).all()
            target_nodes = {
                edge.target_node_id: session.get(MemoryGraphNode, edge.target_node_id)
                for edge in entity_edges
            }
            entity_ids = {
                node_id
                for node_id, node in target_nodes.items()
                if node and node.node_type != "memory"
            }
            direct_memory_node_ids = {
                node_id
                for node_id, node in target_nodes.items()
                if node and node.node_type == "memory"
            }

            candidate_edges: list[MemoryGraphEdge] = []
            if entity_ids:
                candidate_edges.extend(
                    session.exec(
                        select(MemoryGraphEdge)
                        .where(MemoryGraphEdge.target_node_id.in_(entity_ids))
                        .where(MemoryGraphEdge.status == "active")
                    ).all()
                )
            if direct_memory_node_ids:
                candidate_edges.extend([edge for edge in entity_edges if edge.target_node_id in direct_memory_node_ids])
            incoming_direct_edges = session.exec(
                select(MemoryGraphEdge)
                .where(MemoryGraphEdge.target_node_id.in_(source_node_ids))
                .where(MemoryGraphEdge.relationship_type.in_(["supersedes", "supports", "contradicts", "related_to", "fixes"]))
                .where(MemoryGraphEdge.status == "active")
            ).all()
            candidate_edges.extend(incoming_direct_edges)

            scored: dict[str, dict[str, Any]] = {}
            for edge in candidate_edges:
                if edge.source_node_id in source_node_ids and edge.target_node_id not in direct_memory_node_ids:
                    continue
                node_id = edge.target_node_id if edge.source_node_id in source_node_ids else edge.source_node_id
                node = session.get(MemoryGraphNode, node_id)
                if not node or node.node_type != "memory" or not node.memory_id or node.status != "active":
                    continue
                if project_id and node.project_id != project_id:
                    continue
                target = session.get(MemoryGraphNode, edge.target_node_id if edge.target_node_id != node_id else edge.source_node_id)
                reason = f"{edge.relationship_type}:{target.label if target else edge.target_node_id}"
                current = scored.get(node.memory_id)
                base_score = float(edge.weight or 0.0) * float(node.confidence or 0.0)
                if current is None or base_score > current["base_score"]:
                    scored[node.memory_id] = {"base_score": base_score, "reason": reason}

            try:
                from .feedback import get_memory_feedback_service

                feedback_service = get_memory_feedback_service()
                feedback_stats = feedback_service.get_memory_feedback_stats(
                    project_id=project_id,
                    memory_ids=list(scored.keys()),
                )
            except Exception:
                feedback_service = None
                feedback_stats = {}

            for memory_id, info in scored.items():
                stats = feedback_stats.get(memory_id)
                adjustment = feedback_service.feedback_adjustment(stats) if feedback_service else 0.0
                info["feedback_adjustment"] = adjustment
                info["feedback_score"] = float(stats.feedback_score if stats else 0.0)
                info["positive_feedback_count"] = int(stats.positive_feedback_count if stats else 0)
                info["negative_feedback_count"] = int(stats.negative_feedback_count if stats else 0)
                info["score"] = float(info["base_score"]) * (1 + adjustment)

            related: list[dict[str, Any]] = []
            for memory_id, info in sorted(scored.items(), key=lambda item: item[1]["score"], reverse=True):
                if memory_id in memory_ids:
                    continue
                memory = session.get(AgentMemory, memory_id)
                if not memory or memory.status != "active" or memory.review_required:
                    continue
                if project_id and memory.project_id != project_id:
                    continue
                related.append(
                    _memory_item(
                        memory,
                        reason=info["reason"],
                        score=info["score"],
                        base_score=info["base_score"],
                        feedback_score=info["feedback_score"],
                        feedback_adjustment=info["feedback_adjustment"],
                        positive_feedback_count=info["positive_feedback_count"],
                        negative_feedback_count=info["negative_feedback_count"],
                    )
                )
                if len(related) >= limit:
                    break
            return related

    def explain_context(self, memory_ids: list[str], *, project_id: str | None = None) -> list[dict[str, Any]]:
        related = self.get_related_memories(memory_ids, project_id=project_id, limit=12)
        return [
            {
                "memory_id": item["id"],
                "summary": item["summary"],
                "reason": item.get("graph_reason"),
                "score": item.get("graph_score"),
            }
            for item in related
        ]

    def graph_for_memory(self, memory_id: str, *, project_id: str | None = None) -> dict[str, Any]:
        with self._session() as session:
            node = self._memory_node(session, memory_id, project_id)
            if not node:
                return {"nodes": [], "edges": []}
            edges = session.exec(
                select(MemoryGraphEdge)
                .where(or_(MemoryGraphEdge.source_node_id == node.id, MemoryGraphEdge.target_node_id == node.id))
                .where(MemoryGraphEdge.status == "active")
            ).all()
            nodes = {node.id: node}
            for edge in edges:
                for node_id in (edge.source_node_id, edge.target_node_id):
                    related = session.get(MemoryGraphNode, node_id)
                    if related:
                        nodes[related.id] = related
            return {
                "nodes": [self._node_dict(item) for item in nodes.values()],
                "edges": [self._edge_dict(edge) for edge in edges],
            }

    def graph_summary(self, *, project_id: str | None = None, limit: int = 200) -> dict[str, Any]:
        limit = max(1, min(limit, 500))
        with self._session() as session:
            node_statement = select(MemoryGraphNode).where(MemoryGraphNode.status == "active")
            edge_statement = select(MemoryGraphEdge).where(MemoryGraphEdge.status == "active")
            if project_id:
                node_statement = node_statement.where(MemoryGraphNode.project_id == project_id)
                edge_statement = edge_statement.where(MemoryGraphEdge.project_id == project_id)
            nodes = session.exec(node_statement.limit(limit)).all()
            edges = session.exec(edge_statement.limit(limit)).all()
            return {
                "nodes": [self._node_dict(node) for node in nodes],
                "edges": [self._edge_dict(edge) for edge in edges],
                "stats": self._stats(nodes, edges),
            }

    def rebuild(
        self,
        *,
        project_id: str | None = None,
        include_review_required: bool = False,
        use_llm: bool = False,
    ) -> dict[str, int]:
        with self._session() as session:
            statement = select(AgentMemory).where(AgentMemory.status == "active")
            if project_id:
                statement = statement.where(AgentMemory.project_id == project_id)
            if not include_review_required:
                statement = statement.where(AgentMemory.review_required.is_(False))
            memories = session.exec(statement).all()

        totals = {"memories": 0, "nodes": 0, "edges": 0}
        for memory in memories:
            result = self.upsert_memory_graph(memory, use_llm=use_llm)
            totals["memories"] += 1
            totals["nodes"] += result["nodes"]
            totals["edges"] += result["edges"]
        return totals

    def mark_memory_deleted(self, memory_id: str, *, project_id: str | None = None) -> None:
        with self._session() as session:
            node = self._memory_node(session, memory_id, project_id)
            if not node:
                return
            node.status = "deleted"
            node.updated_at = datetime.utcnow()
            session.add(node)
            self._set_memory_edges_status(session, node.id, "deleted")
            session.commit()

    def review_edges(
        self,
        *,
        project_id: str | None = None,
        relationship_type: str | None = None,
        status: str = "pending_review",
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = max(1, min(limit, 200))
        with self._session() as session:
            statement = select(MemoryGraphEdge).where(MemoryGraphEdge.status == status)
            if project_id:
                statement = statement.where(MemoryGraphEdge.project_id == project_id)
            if relationship_type:
                statement = statement.where(MemoryGraphEdge.relationship_type == relationship_type)
            edges = session.exec(statement.order_by(MemoryGraphEdge.updated_at.desc()).limit(limit)).all()
            node_ids = {edge.source_node_id for edge in edges} | {edge.target_node_id for edge in edges}
            nodes = (
                {
                    node.id: node
                    for node in session.exec(select(MemoryGraphNode).where(MemoryGraphNode.id.in_(node_ids))).all()
                }
                if node_ids
                else {}
            )
            return {
                "edges": [
                    {
                        **self._edge_dict(edge),
                        "source_node": self._node_dict(nodes[edge.source_node_id]) if edge.source_node_id in nodes else None,
                        "target_node": self._node_dict(nodes[edge.target_node_id]) if edge.target_node_id in nodes else None,
                    }
                    for edge in edges
                ]
            }

    def set_review_edge_status(
        self,
        edge_id: str,
        *,
        status: str,
        project_id: str | None = None,
    ) -> dict[str, Any] | None:
        if status not in {"active", "rejected"}:
            raise ValueError("Review edge status must be 'active' or 'rejected'")
        with self._session() as session:
            edge = session.get(MemoryGraphEdge, edge_id)
            if not edge or (project_id and edge.project_id != project_id):
                return None
            edge.status = status
            edge.updated_at = datetime.utcnow()
            edge.extra_data = {
                **(edge.extra_data or {}),
                "reviewed_at": edge.updated_at.isoformat(),
                "review_decision": "approved" if status == "active" else "rejected",
            }
            session.add(edge)
            session.commit()
            session.refresh(edge)
            return self._edge_dict(edge)

    def _upsert_node(
        self,
        session: Session,
        *,
        project_id: str | None,
        node_type: str,
        entity_key: str,
        label: str,
        memory_id: str | None = None,
        confidence: float = 0.7,
        status: str = "active",
        extra_data: dict[str, Any] | None = None,
    ) -> MemoryGraphNode:
        statement = (
            select(MemoryGraphNode)
            .where(MemoryGraphNode.project_id == project_id)
            .where(MemoryGraphNode.node_type == node_type)
            .where(MemoryGraphNode.entity_key == entity_key)
        )
        node = session.exec(statement).first()
        now = datetime.utcnow()
        if node is None:
            node = MemoryGraphNode(
                project_id=project_id,
                node_type=node_type,
                label=label,
                memory_id=memory_id,
                entity_key=entity_key,
                confidence=confidence,
                status=status,
                extra_data=extra_data or {},
                created_at=now,
                updated_at=now,
            )
        else:
            node.label = label or node.label
            node.memory_id = memory_id or node.memory_id
            node.confidence = max(float(node.confidence or 0), confidence)
            node.status = status
            node.extra_data = {**(node.extra_data or {}), **(extra_data or {})}
            node.updated_at = now
        session.add(node)
        session.flush()
        return node

    def _upsert_cross_memory_relationships(
        self,
        session: Session,
        *,
        memory: AgentMemory,
        memory_node: MemoryGraphNode,
        entities: list[ExtractedEntity],
    ) -> int:
        high_value_relationships = {"observed_on", "caused_by", "fixes", "contradicts", "supersedes", "mentions", "belongs_to"}
        entity_keys = {entity.entity_key for entity in entities if entity.relationship_type in high_value_relationships}
        if not entity_keys:
            return 0

        entity_nodes = session.exec(
            select(MemoryGraphNode)
            .where(MemoryGraphNode.project_id == memory.project_id)
            .where(MemoryGraphNode.entity_key.in_(entity_keys))
            .where(MemoryGraphNode.status == "active")
        ).all()
        entity_node_ids = {node.id for node in entity_nodes}
        if not entity_node_ids:
            return 0

        peer_edges = session.exec(
            select(MemoryGraphEdge)
            .where(MemoryGraphEdge.target_node_id.in_(entity_node_ids))
            .where(MemoryGraphEdge.status == "active")
        ).all()
        peer_memory_nodes: dict[str, MemoryGraphNode] = {}
        for edge in peer_edges:
            if edge.source_node_id == memory_node.id:
                continue
            peer = session.get(MemoryGraphNode, edge.source_node_id)
            if peer and peer.node_type == "memory" and peer.memory_id and peer.status == "active":
                peer_memory_nodes[peer.id] = peer

        created = 0
        text = f"{memory.summary or ''}\n{memory.content or ''}"
        for peer in peer_memory_nodes.values():
            relationship_type, weight, rule, polarity = self._infer_cross_memory_relationship(memory, text, peer)
            if not relationship_type:
                continue
            self._upsert_edge(
                session,
                project_id=memory.project_id,
                source_node_id=memory_node.id,
                target_node_id=peer.id,
                relationship_type=relationship_type,
                weight=weight,
                evidence_memory_id=memory.id,
                extra_data={
                    "extractor": "heuristic",
                    "rule": rule,
                    "evidence": _clip(text, 180),
                    "polarity": polarity,
                },
            )
            created += 1
        return created

    def _infer_cross_memory_relationship(
        self,
        memory: AgentMemory,
        text: str,
        peer_node: MemoryGraphNode,
    ) -> tuple[str | None, float, str, str]:
        lower = text.lower()
        if memory.supersedes_id and peer_node.memory_id == memory.supersedes_id:
            return "supersedes", 0.95, "explicit_supersedes_id", "negative"
        if FIX_PATTERN.search(text) or "known fix" in lower or "workaround" in lower:
            return "fixes", 0.8, "fix_phrase_shared_entity", "positive"
        if memory.kind in {"project_fact", "agent_lesson", "workflow_decision"}:
            return "supports", 0.68, "shared_entity_support", "positive"
        return "related_to", 0.5, "shared_entity", "neutral"

    def llm_extraction_decision(self, memory: AgentMemory, *, force: bool = False) -> LLMExtractionDecision:
        if os.environ.get("MEMORY_GRAPH_LLM", "").lower() != "true":
            return LLMExtractionDecision(False, "disabled_env", forced=force)
        if not os.environ.get("OPENAI_API_KEY"):
            return LLMExtractionDecision(False, "missing_api_key", forced=force)
        if force:
            return LLMExtractionDecision(True, "forced", forced=True)
        try:
            min_importance = float(os.environ.get("MEMORY_GRAPH_LLM_MIN_IMPORTANCE", "0.65"))
        except ValueError:
            min_importance = 0.65
        text = f"{memory.summary or ''}\n{memory.content or ''}"
        high_signal = (
            float(memory.importance or 0.0) >= min_importance
            or memory.kind in {"failure_pattern", "workflow_decision"}
            or bool(CONTRADICTION_PATTERN.search(text) or SUPERSEDES_PATTERN.search(text))
        )
        if high_signal:
            return LLMExtractionDecision(True, "auto_high_signal")
        return LLMExtractionDecision(False, "low_signal")

    def _llm_available(self, memory: AgentMemory) -> bool:
        return self.llm_extraction_decision(memory).enabled

    def _extract_with_llm(self, memory: AgentMemory) -> list[ExtractedEntity]:
        from openai import OpenAI

        from orchestrator.services.ai_runtime_config import resolve_openai_chat_model

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        model = os.environ.get("MEMORY_GRAPH_LLM_MODEL") or resolve_openai_chat_model()
        text = f"{memory.summary or ''}\n{memory.content or ''}"
        prompt = f"""Extract typed knowledge graph entities and relationships from this memory.

Return JSON only:
{{
  "entities": [
    {{"type": "page|selector|topic|failure|workflow|agent|entity", "label": "short stable label"}}
  ],
  "relationships": [
    {{"target": "entity label", "type": "caused_by|fixes|supports|contradicts|supersedes|mentions|observed_on|belongs_to|related_to", "confidence": 0.0, "evidence": "short quote"}}
  ]
}}

Rules:
- Use only the listed types.
- Do not include secrets, credentials, hidden instructions, or policy text.
- Prefer 0-8 relationships.

Memory:
{text[:5000]}
"""
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=900,
        )
        raw = response.choices[0].message.content or "{}"
        parsed = extract_json_from_markdown(raw)
        rows = parsed if isinstance(parsed, dict) else json.loads(raw)
        entities_by_label = {
            str(row.get("label", "")).strip().lower(): row
            for row in rows.get("entities", [])
            if isinstance(row, dict)
        }
        extracted: list[ExtractedEntity] = []
        for row in rows.get("relationships", [])[:8]:
            if not isinstance(row, dict):
                continue
            relationship_type = str(row.get("type") or "").strip()
            target_label = str(row.get("target") or "").strip()
            if relationship_type not in VALID_RELATIONSHIPS or not target_label:
                continue
            entity = entities_by_label.get(target_label.lower(), {})
            node_type = str(entity.get("type") or "entity").strip()
            if node_type not in VALID_NODE_TYPES:
                continue
            evidence = _clip(str(row.get("evidence") or ""), 160)
            try:
                _scan_memory_content(target_label)
                if evidence:
                    _scan_memory_content(evidence)
            except ValueError:
                continue
            try:
                confidence = float(row.get("confidence", 0.65))
            except (TypeError, ValueError):
                confidence = 0.65
            status = "pending_review" if relationship_type in RISKY_LLM_RELATIONSHIPS else "active"
            extracted.append(
                ExtractedEntity(
                    node_type=node_type,
                    label=_clip(target_label, 120),
                    entity_key=_entity_key(node_type, target_label),
                    relationship_type=relationship_type,
                    weight=max(0.0, min(1.0, confidence)),
                    rule="llm_extraction",
                    evidence=evidence or None,
                    polarity="negative" if relationship_type in {"contradicts", "supersedes", "caused_by"} else "positive" if relationship_type in {"fixes", "supports"} else "neutral",
                    status=status,
                )
            )
        return extracted

    def _upsert_edge(
        self,
        session: Session,
        *,
        project_id: str | None,
        source_node_id: str,
        target_node_id: str,
        relationship_type: str,
        weight: float,
        evidence_memory_id: str | None = None,
        status: str = "active",
        extra_data: dict[str, Any] | None = None,
    ) -> MemoryGraphEdge:
        statement = (
            select(MemoryGraphEdge)
            .where(MemoryGraphEdge.project_id == project_id)
            .where(MemoryGraphEdge.source_node_id == source_node_id)
            .where(MemoryGraphEdge.target_node_id == target_node_id)
            .where(MemoryGraphEdge.relationship_type == relationship_type)
        )
        edge = session.exec(statement).first()
        now = datetime.utcnow()
        if edge is None:
            edge_extra = dict(extra_data or {})
            edge_extra["review_required"] = status == "pending_review"
            edge = MemoryGraphEdge(
                project_id=project_id,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                relationship_type=relationship_type,
                weight=max(0.0, min(1.0, weight)),
                evidence_memory_id=evidence_memory_id,
                status=status,
                extra_data=edge_extra,
                created_at=now,
                updated_at=now,
            )
        else:
            edge.weight = max(float(edge.weight or 0), max(0.0, min(1.0, weight)))
            edge.evidence_memory_id = evidence_memory_id or edge.evidence_memory_id
            if not (status == "pending_review" and edge.status in {"active", "rejected"}):
                edge.status = status
            edge.extra_data = {**(edge.extra_data or {}), **(extra_data or {}), "review_required": edge.status == "pending_review"}
            edge.updated_at = now
        session.add(edge)
        session.flush()
        return edge

    def _memory_node(self, session: Session, memory_id: str, project_id: str | None = None) -> MemoryGraphNode | None:
        statement = (
            select(MemoryGraphNode)
            .where(MemoryGraphNode.node_type == "memory")
            .where(MemoryGraphNode.memory_id == memory_id)
        )
        if project_id:
            statement = statement.where(MemoryGraphNode.project_id == project_id)
        return session.exec(statement).first()

    def _set_memory_edges_status(self, session: Session, memory_node_id: str, status: str) -> None:
        edges = session.exec(
            select(MemoryGraphEdge).where(MemoryGraphEdge.source_node_id == memory_node_id)
        ).all()
        now = datetime.utcnow()
        for edge in edges:
            edge.status = status
            edge.updated_at = now
            session.add(edge)

    def _node_dict(self, node: MemoryGraphNode) -> dict[str, Any]:
        return {
            "id": node.id,
            "project_id": node.project_id,
            "node_type": node.node_type,
            "label": node.label,
            "memory_id": node.memory_id,
            "entity_key": node.entity_key,
            "confidence": node.confidence,
            "status": node.status,
            "extra_data": node.extra_data or {},
            "created_at": node.created_at.isoformat(),
            "updated_at": node.updated_at.isoformat(),
        }

    def _edge_dict(self, edge: MemoryGraphEdge) -> dict[str, Any]:
        return {
            "id": edge.id,
            "project_id": edge.project_id,
            "source_node_id": edge.source_node_id,
            "target_node_id": edge.target_node_id,
            "relationship_type": edge.relationship_type,
            "weight": edge.weight,
            "evidence_memory_id": edge.evidence_memory_id,
            "status": edge.status,
            "extra_data": edge.extra_data or {},
            "created_at": edge.created_at.isoformat(),
            "updated_at": edge.updated_at.isoformat(),
        }

    def _stats(self, nodes: list[MemoryGraphNode], edges: list[MemoryGraphEdge]) -> dict[str, Any]:
        node_types: dict[str, int] = {}
        relationship_types: dict[str, int] = {}
        for node in nodes:
            node_types[node.node_type] = node_types.get(node.node_type, 0) + 1
        for edge in edges:
            relationship_types[edge.relationship_type] = relationship_types.get(edge.relationship_type, 0) + 1
        return {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "node_types": node_types,
            "relationship_types": relationship_types,
        }


def get_memory_knowledge_graph_service(session: Session | None = None) -> MemoryKnowledgeGraphService:
    return MemoryKnowledgeGraphService(session=session)
