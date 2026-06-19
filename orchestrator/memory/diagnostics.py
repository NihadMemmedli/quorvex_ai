"""Operational diagnostics for the memory system."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from orchestrator.api import db as db_module
from orchestrator.api.models_db import (
    AgentMemory,
    BrowserElement,
    BrowserFrontierItem,
    BrowserPageState,
    MemoryGraphEdge,
    MemoryGraphNode,
    MemoryInjectionEvent,
)

from .config import get_config
from .manager import get_memory_manager


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _health(status: str, message: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"status": status, "message": message, "details": details or {}}


class MemoryDiagnosticsService:
    """Summarize whether memory is present, coherent, and being injected."""

    def run(self, *, project_id: str | None = None, stale_days: int = 30) -> dict[str, Any]:
        config = get_config()
        stale_cutoff = datetime.utcnow() - timedelta(days=max(1, stale_days))
        with Session(db_module.engine) as session:
            agent_memories = self._agent_memories(session, project_id)
            injections = self._injections(session, project_id)
            graph_nodes = self._graph_nodes(session, project_id)
            graph_edges = self._graph_edges(session, project_id)
            browser_states = self._browser_states(session, project_id)
            browser_elements = self._browser_elements(session, project_id)
            browser_frontier = self._browser_frontier(session, project_id)

            memory_ids = {memory.id for memory in agent_memories}
            graph_memory_ids = {
                node.memory_id for node in graph_nodes if node.node_type == "memory" and node.memory_id
            }
            injection_memory_ids = self._injection_memory_ids(injections)

            missing_injection_ids = sorted(injection_memory_ids - memory_ids)
            graph_without_memory = sorted(graph_memory_ids - memory_ids)
            stale_high_impact = [
                memory
                for memory in agent_memories
                if memory.status == "active"
                and not memory.review_required
                and (memory.importance or 0) >= 0.75
                and (memory.last_verified_at is None or memory.last_verified_at < stale_cutoff)
            ]

            selector_stats = self._selector_stats(project_id)
            checks = [
                _health("healthy" if config.memory_enabled else "broken", "Memory runtime enabled" if config.memory_enabled else "MEMORY_ENABLED is false"),
                _health(
                    "healthy" if agent_memories else "warning",
                    "Curated agent memory is available" if agent_memories else "No curated agent memories for this project",
                    details={"count": len(agent_memories)},
                ),
                _health(
                    "healthy" if browser_states else "warning",
                    "Browser exploration memory is available" if browser_states else "No browser exploration memory for this project",
                    details={"states": len(browser_states), "elements": len(browser_elements), "frontier": len(browser_frontier)},
                ),
                _health(
                    "healthy" if not missing_injection_ids else "warning",
                    "Injection references point to existing memories" if not missing_injection_ids else "Some injection events reference missing memories",
                    details={"missing_memory_ids": missing_injection_ids[:25], "missing_count": len(missing_injection_ids)},
                ),
                _health(
                    "healthy" if not graph_without_memory else "warning",
                    "Graph memory nodes have backing memories" if not graph_without_memory else "Some graph memory nodes have no backing AgentMemory row",
                    details={"memory_ids": graph_without_memory[:25], "count": len(graph_without_memory)},
                ),
                _health(
                    "healthy" if not stale_high_impact else "warning",
                    "No stale high-importance memories found" if not stale_high_impact else "High-importance memories need verification",
                    details={"count": len(stale_high_impact), "memory_ids": [memory.id for memory in stale_high_impact[:25]]},
                ),
            ]

            return {
                "project_id": project_id,
                "memory_enabled": config.memory_enabled,
                "embedding_model": config.embedding_model,
                "persist_directory": config.persist_directory,
                "generated_at": datetime.utcnow().isoformat(),
                "overall_status": self._overall_status(checks),
                "checks": checks,
                "agent_memory": self._agent_memory_summary(agent_memories),
                "browser_memory": {
                    "states": len(browser_states),
                    "elements": len(browser_elements),
                    "frontier": len(browser_frontier),
                    "frontier_by_status": dict(Counter(item.status for item in browser_frontier)),
                },
                "selector_patterns": selector_stats,
                "graph": {
                    "nodes": len(graph_nodes),
                    "edges": len(graph_edges),
                    "node_types": dict(Counter(node.node_type for node in graph_nodes)),
                    "edge_statuses": dict(Counter(edge.status for edge in graph_edges)),
                    "memory_nodes_without_backing_memory": graph_without_memory[:50],
                },
                "injections": self._injection_summary(injections, missing_injection_ids),
                "stale_memory": {
                    "older_than_days": stale_days,
                    "high_impact_count": len(stale_high_impact),
                    "items": [
                        {
                            "id": memory.id,
                            "summary": memory.summary or memory.content,
                            "importance": memory.importance,
                            "last_verified_at": _iso(memory.last_verified_at),
                            "updated_at": _iso(memory.updated_at),
                        }
                        for memory in stale_high_impact[:25]
                    ],
                },
                "recommended_actions": self._recommended_actions(
                    agent_memories=agent_memories,
                    browser_states=browser_states,
                    missing_injection_ids=missing_injection_ids,
                    graph_without_memory=graph_without_memory,
                    stale_high_impact=stale_high_impact,
                ),
            }

    def _agent_memories(self, session: Session, project_id: str | None) -> list[AgentMemory]:
        statement = select(AgentMemory)
        if project_id:
            statement = statement.where(AgentMemory.project_id == project_id)
        return list(session.exec(statement).all())

    def _injections(self, session: Session, project_id: str | None) -> list[MemoryInjectionEvent]:
        statement = select(MemoryInjectionEvent)
        if project_id:
            statement = statement.where(MemoryInjectionEvent.project_id == project_id)
        return list(session.exec(statement).all())

    def _graph_nodes(self, session: Session, project_id: str | None) -> list[MemoryGraphNode]:
        statement = select(MemoryGraphNode)
        if project_id:
            statement = statement.where(MemoryGraphNode.project_id == project_id)
        return list(session.exec(statement).all())

    def _graph_edges(self, session: Session, project_id: str | None) -> list[MemoryGraphEdge]:
        statement = select(MemoryGraphEdge)
        if project_id:
            statement = statement.where(MemoryGraphEdge.project_id == project_id)
        return list(session.exec(statement).all())

    def _browser_states(self, session: Session, project_id: str | None) -> list[BrowserPageState]:
        statement = select(BrowserPageState)
        if project_id:
            statement = statement.where(BrowserPageState.project_id == project_id)
        return list(session.exec(statement).all())

    def _browser_elements(self, session: Session, project_id: str | None) -> list[BrowserElement]:
        statement = select(BrowserElement)
        if project_id:
            statement = statement.where(BrowserElement.project_id == project_id)
        return list(session.exec(statement).all())

    def _browser_frontier(self, session: Session, project_id: str | None) -> list[BrowserFrontierItem]:
        statement = select(BrowserFrontierItem)
        if project_id:
            statement = statement.where(BrowserFrontierItem.project_id == project_id)
        return list(session.exec(statement).all())

    def _selector_stats(self, project_id: str | None) -> dict[str, Any]:
        try:
            manager = get_memory_manager(project_id or "default")
            patterns = manager.vector_store.get_all_patterns()
        except Exception:
            patterns = []
        rates = [float(pattern.get("metadata", {}).get("success_rate") or 0) for pattern in patterns]
        return {
            "patterns": len(patterns),
            "avg_success_rate": round(sum(rates) / len(rates), 3) if rates else 0,
            "actions": dict(Counter(str(pattern.get("metadata", {}).get("action") or "unknown") for pattern in patterns)),
        }

    def _agent_memory_summary(self, memories: list[AgentMemory]) -> dict[str, Any]:
        by_kind = Counter(memory.kind for memory in memories)
        by_type = Counter(memory.memory_type or "semantic" for memory in memories)
        by_status = Counter(memory.status for memory in memories)
        by_source = Counter(memory.source_type or "unknown" for memory in memories)
        return {
            "total": len(memories),
            "ready": sum(1 for memory in memories if memory.status == "active" and not memory.review_required),
            "review_required": sum(1 for memory in memories if memory.review_required),
            "archived_or_inactive": sum(1 for memory in memories if memory.status != "active"),
            "by_kind": dict(by_kind),
            "by_type": dict(by_type),
            "by_status": dict(by_status),
            "by_source": dict(by_source),
        }

    def _injection_memory_ids(self, injections: list[MemoryInjectionEvent]) -> set[str]:
        ids: set[str] = set()
        for event in injections:
            ids.update(event.memory_ids)
            extra = event.extra_data or {}
            graph_ids = extra.get("graph_expanded_memory_ids")
            if isinstance(graph_ids, list):
                ids.update(str(memory_id) for memory_id in graph_ids if memory_id)
        return ids

    def _injection_summary(
        self,
        injections: list[MemoryInjectionEvent],
        missing_memory_ids: list[str],
    ) -> dict[str, Any]:
        by_stage = Counter(event.stage for event in injections)
        by_outcome = Counter(event.outcome for event in injections)
        last_by_stage: dict[str, str] = {}
        for event in sorted(injections, key=lambda row: row.created_at or datetime.min):
            last_by_stage[event.stage] = _iso(event.created_at) or ""
        return {
            "total": len(injections),
            "by_stage": dict(by_stage),
            "by_outcome": dict(by_outcome),
            "last_by_stage": last_by_stage,
            "missing_memory_ids": missing_memory_ids[:50],
            "missing_memory_count": len(missing_memory_ids),
        }

    def _recommended_actions(
        self,
        *,
        agent_memories: list[AgentMemory],
        browser_states: list[BrowserPageState],
        missing_injection_ids: list[str],
        graph_without_memory: list[str],
        stale_high_impact: list[AgentMemory],
    ) -> list[str]:
        actions = []
        if not agent_memories and browser_states:
            actions.append("Consolidate recent exploration and agent output into curated agent memories.")
        if not agent_memories:
            actions.append("Create at least one reviewed project_fact or agent_lesson before relying on prompt injection.")
        if missing_injection_ids:
            actions.append("Rebuild or prune memory injection telemetry that references missing memories.")
        if graph_without_memory:
            actions.append("Rebuild the memory knowledge graph for this project.")
        if stale_high_impact:
            actions.append("Run stale-memory verification and review high-importance memories.")
        return actions

    def _overall_status(self, checks: list[dict[str, Any]]) -> str:
        statuses = {check["status"] for check in checks}
        if "broken" in statuses:
            return "broken"
        if "warning" in statuses:
            return "warning"
        return "healthy"


def get_memory_diagnostics_service() -> MemoryDiagnosticsService:
    return MemoryDiagnosticsService()
