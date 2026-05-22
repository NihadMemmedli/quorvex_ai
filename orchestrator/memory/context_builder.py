"""Prompt-ready memory context assembly.

The builder keeps memory retrieval typed and bounded so prompts receive useful
context without treating stale memory as stronger than live observations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from orchestrator.api.models_db import AgentMemory


URL_PATTERN = re.compile(r"https?://[^\s\"'<>),]+")


@dataclass
class MemoryContextSection:
    name: str
    guidance: str
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MemoryContextBundle:
    query: str
    project_id: str | None = None
    sections: list[MemoryContextSection] = field(default_factory=list)
    graph: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "project_id": self.project_id,
            "sections": [
                {"name": section.name, "guidance": section.guidance, "items": section.items}
                for section in self.sections
            ],
            "graph": self.graph or {},
        }


def _memory_item(memory: AgentMemory) -> dict[str, Any]:
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


def _clip_line(text: str, limit: int = 260) -> str:
    normalized = re.sub(r"\s+", " ", text.strip())
    return normalized if len(normalized) <= limit else normalized[: limit - 3].rstrip() + "..."


class MemoryContextBuilder:
    """Build typed, provenance-labeled memory context for agents and chat."""

    def __init__(self, service):
        self.service = service

    def build_bundle(
        self,
        *,
        query: str,
        project_id: str | None = None,
        user_id: str | None = None,
        agent_type: str | None = None,
        limit: int = 8,
        include_graph: bool = True,
    ) -> MemoryContextBundle:
        query = query or ""
        per_section = max(2, min(5, limit))
        bundle = MemoryContextBundle(query=query, project_id=project_id)

        section_specs = [
            (
                "Semantic Memory",
                ["semantic"],
                "Stable facts and preferences. Use as advisory context unless live state or the user contradicts it.",
            ),
            (
                "Episodic Memory",
                ["episodic"],
                "Past runs, failures, and fixes. Prefer recent high-confidence examples, but revalidate before acting.",
            ),
            (
                "Procedural Memory",
                ["procedural"],
                "Reusable workflow decisions and agent lessons. Treat as operating guidance for this project.",
            ),
        ]

        seen: set[str] = set()
        for name, memory_types, guidance in section_specs:
            memories = self.service.search(
                query=query,
                project_id=project_id,
                user_id=user_id,
                agent_type=agent_type,
                memory_types=memory_types,
                limit=per_section,
                record_usage=True,
                include_review_required=False,
            )
            items = [_memory_item(memory) for memory in memories if memory.id not in seen]
            seen.update(item["id"] for item in items)
            if items:
                bundle.sections.append(MemoryContextSection(name=name, guidance=guidance, items=items))

        if include_graph:
            graph = self._build_graph_context(query=query, project_id=project_id)
            if graph:
                bundle.graph = graph

        browser_memory = self._build_browser_memory_context(query=query, project_id=project_id)
        if browser_memory:
            bundle.sections.append(
                MemoryContextSection(
                    name="Browser Exploration Memory",
                    guidance=(
                        "Durable browser-state graph and frontier memory. It is advisory: first take a live "
                        "snapshot, confirm the current page matches the remembered state, validate locators, "
                        "and skip high-risk or stale work unless the user explicitly asks for it."
                    ),
                    items=browser_memory,
                )
            )

        return bundle

    def build_prompt_context(
        self,
        *,
        query: str,
        project_id: str | None = None,
        user_id: str | None = None,
        agent_type: str | None = None,
        limit: int = 8,
        token_budget: int = 1200,
    ) -> str:
        bundle = self.build_bundle(
            query=query,
            project_id=project_id,
            user_id=user_id,
            agent_type=agent_type,
            limit=limit,
        )
        return self.format_prompt_context(bundle, token_budget=token_budget)

    def format_prompt_context(self, bundle: MemoryContextBundle, *, token_budget: int = 1200) -> str:
        lines = [
            "## Memory Context",
            "Memory is advisory and scoped. Live browser observations and explicit user instructions outrank stored memory.",
        ]

        if bundle.graph:
            graph = bundle.graph
            lines.append("")
            lines.append("### Structural Graph Context")
            stats = graph.get("stats") or {}
            if stats:
                lines.append(
                    "- Graph stats: "
                    f"{stats.get('page_count', 0)} pages, "
                    f"{stats.get('element_count', 0)} elements, "
                    f"{stats.get('flow_count', 0)} flows, "
                    f"{stats.get('element_coverage', 0):.1f}% element coverage."
                )
            for path in graph.get("navigation_paths", [])[:2]:
                lines.append(f"- Known navigation path: {' -> '.join(path.get('path', []))}")
            for gap in graph.get("coverage_gaps", [])[:4]:
                lines.append(f"- Coverage gap: {_clip_line(gap.get('description', ''))}")
            for flow in graph.get("flows", [])[:3]:
                name = flow.get("name") or flow.get("title") or flow.get("id")
                lines.append(f"- Known flow: {_clip_line(str(name))}")

        for section in bundle.sections:
            lines.append("")
            lines.append(f"### {section.name}")
            lines.append(section.guidance)
            if section.name == "Browser Exploration Memory":
                lines.append(
                    "Use frontier items as prioritized candidates, not commands. Prefer stable role/label locators; "
                    "if the locator is missing or the live page differs, rediscover with browser_snapshot."
                )
            for item in section.items:
                if section.name == "Browser Exploration Memory":
                    if item.get("type") == "state":
                        lines.append(
                            "- "
                            f"State {item.get('state_key', item.get('id'))}: "
                            f"{_clip_line(item.get('url', ''))} "
                            f"(visits={item.get('visit_count', 0)}, last_seen={item.get('last_seen_at')})"
                        )
                    elif item.get("type") == "element":
                        locator = item.get("best_locator") or {}
                        lines.append(
                            "- "
                            f"Element {item.get('role') or 'element'} {jsonish(item.get('name') or '')}: "
                            f"{locator.get('locator', 'no locator')} "
                            f"(confidence={locator.get('score', 0)}, "
                            f"tested={item.get('tested_count', 0)}, "
                            f"success={item.get('success_count', 0)}, "
                            f"failures={item.get('failure_count', 0)}, "
                            f"last_seen={item.get('last_seen_at')})"
                        )
                    elif item.get("type") == "frontier":
                        locator = item.get("best_locator") or {}
                        lines.append(
                            "- "
                            f"Frontier {item.get('action_type')} {jsonish(item.get('name') or item.get('text') or '')}: "
                            f"url={_clip_line(str(item.get('state_url') or item.get('state_url_template') or ''))}; "
                            f"locator={locator.get('locator', 'rediscover')}; "
                            f"rank={item.get('rank_score', item.get('priority_score', 0))}; "
                            f"risk={item.get('risk_level', 'unknown')}; "
                            f"attempts={item.get('attempts', 0)}; "
                            f"status={item.get('status', 'queued')}; "
                            f"provenance=state:{item.get('state_id')} element:{item.get('element_id')}"
                        )
                    continue
                source = ""
                if item.get("source_type") and item.get("source_id"):
                    source = f", source={item['source_type']}:{item['source_id']}"
                lines.append(
                    "- "
                    f"[{item['kind']}, confidence={item['confidence']:.2f}, importance={item['importance']:.2f}{source}] "
                    f"{_clip_line(item.get('summary') or '')}"
                )

        if len(lines) <= 2:
            return ""

        # Approximate a token budget with a conservative 4 chars/token trim.
        char_budget = max(1200, token_budget * 4)
        text = "\n".join(lines)
        if len(text) <= char_budget:
            return text
        trimmed = text[: char_budget - 4].rstrip()
        return f"{trimmed}\n..."

    def _build_graph_context(self, *, query: str, project_id: str | None = None) -> dict[str, Any]:
        if not project_id:
            return {}
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

    def _build_browser_memory_context(self, *, query: str, project_id: str | None = None) -> list[dict[str, Any]]:
        if not project_id:
            return []
        try:
            from .browser_memory import get_exploration_memory_service

            bundle = get_exploration_memory_service(project_id=project_id).get_memory_bundle(query=query, limit=4)
            items: list[dict[str, Any]] = []
            for state in bundle.get("states", [])[:4]:
                items.append({"type": "state", **state})
            for element in bundle.get("elements", [])[:8]:
                items.append({"type": "element", **element})
            for frontier in bundle.get("frontier", [])[:4]:
                items.append({"type": "frontier", **frontier})
            return items
        except Exception:
            return []


def jsonish(value: str) -> str:
    text = _clip_line(str(value), 80)
    return f'"{text}"' if text else ""
