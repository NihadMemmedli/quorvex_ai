"""Unified memory retrieval for agents, chat, planners, and exploration."""

from __future__ import annotations

import re
from typing import Any

from orchestrator.api.models_db import AgentMemory

from .agent_memory import get_agent_memory_service


URL_PATTERN = re.compile(r"https?://[^\s\"'<>),]+")


def _agent_memory_item(memory: AgentMemory) -> dict[str, Any]:
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
    }


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
        }

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
                bundle["agent_memories"][memory_type] = [_agent_memory_item(memory) for memory in memories]
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

        return bundle

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


def get_unified_memory_service(agent_service=None) -> UnifiedMemoryService:
    return UnifiedMemoryService(agent_service=agent_service)
