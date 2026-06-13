"""Unified memory retrieval for agents, chat, planners, and exploration."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from orchestrator.api.models_db import AgentMemory

from .agent_memory import get_agent_memory_service

URL_PATTERN = re.compile(r"https?://[^\s\"'<>),]+")


def _agent_memory_item(
    memory: AgentMemory,
    *,
    score: float | None = None,
    score_breakdown: dict[str, Any] | None = None,
    retrieval_reason: str | None = None,
    staleness_warning: str | None = None,
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
        "score": round(float(score), 3) if score is not None else None,
        "score_breakdown": score_breakdown or {},
        "retrieval_reason": retrieval_reason,
        "staleness_warning": staleness_warning,
        "source_trace": {
            "source_type": memory.source_type,
            "source_id": memory.source_id,
            "agent_type": memory.agent_type,
            "scope": memory.scope or "project",
        },
    }


def _query_terms(query: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", query.lower()) if term}


def _memory_text(memory: AgentMemory) -> str:
    return " ".join(
        str(part or "")
        for part in [
            memory.kind,
            memory.memory_type,
            memory.summary,
            memory.content,
            " ".join(memory.tags or []),
            memory.source_type,
            memory.agent_type,
        ]
    )


def _memory_staleness(memory: AgentMemory, *, now: datetime, stale_after_days: int = 30) -> tuple[float, str | None]:
    reference = memory.last_verified_at or memory.updated_at or memory.created_at
    if not reference:
        return 0.0, None
    age_days = max(0, (now - reference).days)
    if memory.last_verified_at is None and (memory.importance or 0) >= 0.75:
        return -0.12, "High-importance memory has not been verified."
    if age_days > stale_after_days * 3:
        return -0.18, f"Memory was last checked more than {stale_after_days * 3} days ago."
    if age_days > stale_after_days:
        return -0.08, f"Memory was last checked more than {stale_after_days} days ago."
    return 0.04, None


class UnifiedMemoryService:
    """Build one bounded, typed memory bundle from all backing stores."""

    def __init__(self, agent_service=None):
        self.agent_service = agent_service or get_agent_memory_service()

    def build_bundle(
        self,
        *,
        query: str,
        project_id: str | None = None,
        user_id: str | None = None,
        agent_type: str | None = None,
        limit: int = 8,
        include_review_required: bool = False,
        include_usage: bool = True,
    ) -> dict[str, Any]:
        query = query or ""
        limit = max(1, min(limit, 25))
        per_section = max(2, min(5, limit))
        bundle: dict[str, Any] = {
            "query": query,
            "project_id": project_id,
            "agent_memories": {
                "semantic": [],
                "episodic": [],
                "procedural": [],
            },
            "browser_memory": {"states": [], "elements": [], "frontier": []},
            "graph_context": {},
            "memory_graph": {"related_memories": [], "relationships": [], "explanations": []},
            "selector_patterns": [],
            "coverage_gaps": [],
            "retrieved_knowledge": {
                "items": [],
                "citations": [],
                "warnings": [],
                "diagnostics": {"retriever": "unified_memory_v1"},
            },
            "ranking": {"selected_items": [], "rejected_candidates": [], "score_summary": {}},
            "diagnostics": {"warnings": [], "candidate_count": 0},
        }

        all_ranked_items: list[dict[str, Any]] = []
        rejected_candidates: list[dict[str, Any]] = []
        for memory_type in ("semantic", "episodic", "procedural"):
            try:
                memories = self.agent_service.search(
                    query=query,
                    project_id=project_id,
                    user_id=user_id,
                    agent_type=agent_type,
                    memory_types=[memory_type],
                    limit=per_section,
                    record_usage=include_usage,
                    include_review_required=include_review_required,
                )
                scored = self._score_memories(
                    memories,
                    query=query,
                    project_id=project_id,
                    user_id=user_id,
                    agent_type=agent_type,
                    memory_type=memory_type,
                )
                bundle["agent_memories"][memory_type] = [item["memory"] for item in scored["selected"]]
                all_ranked_items.extend(scored["selected"])
                rejected_candidates.extend(scored["rejected"])
            except Exception:
                bundle["agent_memories"][memory_type] = []

        primary_ids = [
            item.get("id")
            for items in bundle["agent_memories"].values()
            for item in items
            if item.get("id")
        ]
        if primary_ids and project_id:
            bundle["memory_graph"] = self._memory_graph_context(
                memory_ids=primary_ids,
                project_id=project_id,
                limit=min(8, limit),
            )

        if project_id:
            bundle["graph_context"] = self._graph_context(query=query, project_id=project_id)
            bundle["coverage_gaps"] = bundle["graph_context"].get("coverage_gaps", [])
            bundle["browser_memory"] = self._browser_memory(query=query, project_id=project_id, limit=limit)
            bundle["selector_patterns"] = self._selector_patterns(
                query=query,
                project_id=project_id,
                limit=min(5, limit),
            )

        selected_items = [
            {
                "id": item["memory"]["id"],
                "kind": item["memory"]["kind"],
                "memory_type": item["memory"]["memory_type"],
                "score": item["memory"]["score"],
                "retrieval_reason": item["memory"].get("retrieval_reason"),
                "score_breakdown": item["memory"].get("score_breakdown") or {},
                "staleness_warning": item["memory"].get("staleness_warning"),
            }
            for item in sorted(all_ranked_items, key=lambda row: row["score"], reverse=True)
        ]
        warnings = [
            item["memory"]["staleness_warning"]
            for item in all_ranked_items
            if item["memory"].get("staleness_warning")
        ]
        bundle["ranking"] = {
            "selected_items": selected_items,
            "rejected_candidates": rejected_candidates,
            "score_summary": {
                "selected_count": len(selected_items),
                "candidate_count": len(selected_items) + len(rejected_candidates),
                "top_score": selected_items[0]["score"] if selected_items else None,
                "avg_score": round(sum(float(item["score"] or 0) for item in selected_items) / len(selected_items), 3)
                if selected_items
                else 0,
            },
        }
        bundle["diagnostics"] = {
            "warnings": list(dict.fromkeys(warnings)),
            "candidate_count": len(selected_items) + len(rejected_candidates),
            "selected_count": len(selected_items),
        }
        bundle["retrieved_knowledge"] = self._retrieved_knowledge(bundle, limit=limit)
        return bundle

    def _score_memories(
        self,
        memories: list[AgentMemory],
        *,
        query: str,
        project_id: str | None,
        user_id: str | None,
        agent_type: str | None,
        memory_type: str,
    ) -> dict[str, list[dict[str, Any]]]:
        if not memories:
            return {"selected": [], "rejected": []}
        terms = _query_terms(query)
        now = datetime.utcnow()
        try:
            from .feedback import get_memory_feedback_service

            feedback_service = get_memory_feedback_service()
            feedback_stats = feedback_service.get_memory_feedback_stats(
                project_id=project_id,
                memory_ids=[memory.id for memory in memories],
            )
        except Exception:
            feedback_service = None
            feedback_stats = {}

        selected: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for position, memory in enumerate(memories):
            text_terms = _query_terms(_memory_text(memory))
            overlap = len(terms & text_terms)
            lexical = min(0.22, overlap * 0.035)
            confidence = float(memory.confidence or 0.0) * 0.22
            importance = float(memory.importance or 0.0) * 0.18
            recency_penalty, staleness_warning = _memory_staleness(memory, now=now)
            feedback_stats_item = feedback_stats.get(memory.id)
            feedback = (
                feedback_service.feedback_adjustment(feedback_stats_item)
                if feedback_service
                else 0.0
            )
            scope_bonus = 0.06 if project_id and memory.project_id == project_id else 0.02 if memory.scope == "global" else 0.0
            agent_bonus = 0.04 if agent_type and memory.agent_type == agent_type else 0.0
            vector_position = max(0.0, 0.12 - (position * 0.015))
            review_penalty = -0.5 if memory.review_required else 0.0
            status_penalty = -0.5 if memory.status != "active" else 0.0
            score = (
                0.25
                + lexical
                + confidence
                + importance
                + recency_penalty
                + feedback
                + scope_bonus
                + agent_bonus
                + vector_position
                + review_penalty
                + status_penalty
            )
            score = max(0.0, min(1.0, score))
            reason_parts = []
            if overlap:
                reason_parts.append(f"{overlap} query term match{'es' if overlap != 1 else ''}")
            if memory.project_id == project_id and project_id:
                reason_parts.append("project scoped")
            if feedback:
                reason_parts.append("feedback adjusted")
            if not reason_parts:
                reason_parts.append(f"{memory_type} fallback")
            score_breakdown = {
                "lexical": round(lexical, 3),
                "confidence": round(confidence, 3),
                "importance": round(importance, 3),
                "freshness": round(recency_penalty, 3),
                "feedback": round(feedback, 3),
                "scope": round(scope_bonus, 3),
                "agent": round(agent_bonus, 3),
                "vector_position": round(vector_position, 3),
                "penalties": round(review_penalty + status_penalty, 3),
            }
            item = {
                "score": score,
                "memory": _agent_memory_item(
                    memory,
                    score=score,
                    score_breakdown=score_breakdown,
                    retrieval_reason=", ".join(reason_parts),
                    staleness_warning=staleness_warning,
                ),
            }
            if score <= 0 or memory.review_required or memory.status != "active":
                rejected.append(
                    {
                        "id": memory.id,
                        "reason": "not injectable" if memory.review_required or memory.status != "active" else "low score",
                        "score": round(score, 3),
                    }
                )
            else:
                selected.append(item)

        selected.sort(key=lambda row: row["score"], reverse=True)
        return {"selected": selected, "rejected": rejected}

    def _memory_graph_context(self, *, memory_ids: list[str], project_id: str, limit: int) -> dict[str, Any]:
        try:
            from .knowledge_graph import get_memory_knowledge_graph_service

            service = get_memory_knowledge_graph_service()
            related = service.get_related_memories(memory_ids, project_id=project_id, limit=limit)
            return {
                "related_memories": related,
                "relationships": [
                    {
                        "memory_id": item.get("id"),
                        "reason": item.get("graph_reason"),
                        "score": item.get("graph_score"),
                    }
                    for item in related
                ],
                "explanations": service.explain_context(memory_ids, project_id=project_id),
            }
        except Exception:
            return {"related_memories": [], "relationships": [], "explanations": []}

    def _graph_context(self, *, query: str, project_id: str) -> dict[str, Any]:
        try:
            from .manager import get_memory_manager

            manager = get_memory_manager(project_id=project_id)
            graph = manager.graph_store
            stats = graph.get_graph_stats()
            flows = graph.get_all_flows()[:5]
            gaps = manager.get_coverage_gaps(max_results=8)
            urls = [url.rstrip(".,;:!?") for url in URL_PATTERN.findall(query or "")]
            navigation_paths = []
            if len(urls) >= 2:
                path = manager.find_navigation_path(urls[0], urls[-1])
                if path:
                    navigation_paths.append({"from": urls[0], "to": urls[-1], "path": path})
            return {
                "stats": stats,
                "flows": flows,
                "coverage_gaps": gaps,
                "navigation_paths": navigation_paths,
            }
        except Exception:
            return {}

    def _browser_memory(self, *, query: str, project_id: str, limit: int) -> dict[str, Any]:
        try:
            from .browser_memory import get_exploration_memory_service

            return get_exploration_memory_service(project_id=project_id).get_memory_bundle(
                query=query,
                limit=max(4, min(10, limit)),
            )
        except Exception:
            return {"states": [], "elements": [], "frontier": []}

    def _selector_patterns(self, *, query: str, project_id: str, limit: int) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        try:
            from .manager import get_memory_manager

            manager = get_memory_manager(project_id=project_id)
            patterns = manager.find_similar_tests(
                description=query[:1000],
                n_results=limit,
                min_success_rate=0.6,
            )
            items = []
            for pattern in patterns:
                metadata = pattern.get("metadata", {})
                items.append(
                    {
                        "id": pattern.get("id", ""),
                        "document": pattern.get("document"),
                        "distance": pattern.get("distance"),
                        "test_name": metadata.get("test_name"),
                        "action": metadata.get("action"),
                        "target": metadata.get("target"),
                        "selector_type": metadata.get("selector_type"),
                        "selector_value": metadata.get("selector_value"),
                        "playwright_selector": metadata.get("playwright_selector"),
                        "page_url": metadata.get("page_url"),
                        "success_rate": metadata.get("success_rate", 0),
                        "avg_duration": metadata.get("avg_duration", 0),
                    }
                )
            return items
        except Exception:
            return []

    def _retrieved_knowledge(self, bundle: dict[str, Any], *, limit: int) -> dict[str, Any]:
        """Shape existing unified retrieval into a citation-ready section.

        AgenticRagService performs broader orchestration for the API/tool path.
        This compact section lets the existing prompt builder expose typed
        citations without a recursive dependency on that service.
        """

        items: list[dict[str, Any]] = []
        warnings: list[str] = []
        for memory_type, memories in (bundle.get("agent_memories") or {}).items():
            for memory in memories or []:
                warning = memory.get("staleness_warning")
                if warning:
                    warnings.append(warning)
                items.append(
                    {
                        "id": memory.get("id"),
                        "source": "agent_memories",
                        "title": f"{memory.get('kind')} ({memory_type})",
                        "summary": memory.get("summary"),
                        "score": memory.get("score"),
                        "freshness": memory.get("last_verified_at") or memory.get("updated_at"),
                        "warning": warning,
                        "reason": memory.get("retrieval_reason"),
                        "metadata": {
                            "memory_type": memory_type,
                            "source_type": memory.get("source_type"),
                            "source_id": memory.get("source_id"),
                        },
                    }
                )
        for pattern in bundle.get("selector_patterns") or []:
            selector = pattern.get("playwright_selector") or pattern.get("selector_value") or ""
            items.append(
                {
                    "id": pattern.get("id") or selector,
                    "source": "selector_patterns",
                    "title": f"Selector pattern: {pattern.get('test_name') or pattern.get('action') or 'test'}",
                    "summary": f"{pattern.get('action') or 'action'} {pattern.get('target') or ''}: {selector}",
                    "score": None if pattern.get("distance") is None else round(max(0.0, 1.0 - float(pattern["distance"])), 3),
                    "freshness": None,
                    "warning": "Validate selector against the live page before using it.",
                    "reason": "similar successful test pattern",
                    "metadata": {"distance": pattern.get("distance"), "page_url": pattern.get("page_url")},
                }
            )
        for gap in bundle.get("coverage_gaps") or []:
            items.append(
                {
                    "id": gap.get("id") or gap.get("element_id") or gap.get("description"),
                    "source": "coverage_gaps",
                    "title": f"Coverage gap: {gap.get('priority') or 'medium'}",
                    "summary": gap.get("description") or str(gap),
                    "score": 0.65 if gap.get("priority") in {"high", "critical"} else 0.5,
                    "freshness": None,
                    "warning": None,
                    "reason": "coverage gap",
                    "metadata": {"url": gap.get("url"), "type": gap.get("type")},
                }
            )

        def score(item: dict[str, Any]) -> float:
            return float(item.get("score") or 0.45)

        selected = sorted(items, key=score, reverse=True)[: max(1, min(limit, 12))]
        citations = []
        for index, item in enumerate(selected, start=1):
            item["citation_label"] = f"M{index}"
            citations.append(
                {
                    "label": item["citation_label"],
                    "id": item.get("id"),
                    "source": item.get("source"),
                    "title": item.get("title"),
                    "score": item.get("score"),
                }
            )
        return {
            "items": selected,
            "citations": citations,
            "warnings": list(dict.fromkeys(warnings)),
            "diagnostics": {
                "retriever": "unified_memory_v1",
                "candidate_count": len(items),
                "selected_count": len(selected),
            },
        }


def get_unified_memory_service(agent_service=None) -> UnifiedMemoryService:
    return UnifiedMemoryService(agent_service=agent_service)
