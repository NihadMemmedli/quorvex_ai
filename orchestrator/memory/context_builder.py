"""Prompt-ready memory context assembly.

The builder keeps memory retrieval typed and bounded so prompts receive useful
context without treating stale memory as stronger than live observations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from orchestrator.api.models_db import AgentMemory
from orchestrator.utils.token_budget import estimate_tokens

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
    unified: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "project_id": self.project_id,
            "sections": [
                {"name": section.name, "guidance": section.guidance, "items": section.items}
                for section in self.sections
            ],
            "graph": self.graph or {},
            "unified": self.unified or {},
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


def _item_value_score(item: dict[str, Any]) -> float:
    """Rank memories by retrieval score, importance, confidence, and provenance quality."""
    score = float(item.get("score") or item.get("rank_score") or item.get("priority_score") or 0)
    importance = float(item.get("importance") or 0)
    confidence = float(item.get("confidence") or item.get("success_rate") or 0)
    freshness_bonus = 0.05 if item.get("last_verified_at") or item.get("last_seen_at") else 0.0
    review_penalty = -0.2 if item.get("review_required") else 0.0
    return score + (importance * 0.35) + (confidence * 0.25) + freshness_bonus + review_penalty


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
        try:
            from .unified import UnifiedMemoryService

            unified = UnifiedMemoryService(agent_service=self.service).build_bundle(
                query=query,
                project_id=project_id,
                user_id=user_id,
                agent_type=agent_type,
                limit=limit,
                include_review_required=False,
            )
        except Exception:
            unified = {
                "agent_memories": {"semantic": [], "episodic": [], "procedural": []},
                "browser_memory": {"states": [], "elements": [], "frontier": []},
                "graph_context": {},
                "memory_graph": {"related_memories": [], "relationships": [], "explanations": []},
                "selector_patterns": [],
                "coverage_gaps": [],
            }

        bundle = MemoryContextBundle(query=query, project_id=project_id, unified=unified)

        section_specs = [
            (
                "Semantic Memory",
                "semantic",
                "Stable facts and preferences. Use as advisory context unless live state or the user contradicts it.",
            ),
            (
                "Episodic Memory",
                "episodic",
                "Past runs, failures, and fixes. Prefer recent high-confidence examples, but revalidate before acting.",
            ),
            (
                "Procedural Memory",
                "procedural",
                "Reusable workflow decisions and agent lessons. Treat as operating guidance for this project.",
            ),
        ]

        seen: set[str] = set()
        agent_memories = unified.get("agent_memories") or {}
        for name, memory_type, guidance in section_specs:
            items = [item for item in agent_memories.get(memory_type, []) if item.get("id") not in seen]
            seen.update(str(item.get("id")) for item in items)
            if items:
                bundle.sections.append(MemoryContextSection(name=name, guidance=guidance, items=items))

        related_memories = (unified.get("memory_graph") or {}).get("related_memories") or []
        related_items = [item for item in related_memories if item.get("id") not in seen]
        if related_items:
            seen.update(str(item.get("id")) for item in related_items)
            bundle.sections.append(
                MemoryContextSection(
                    name="Related Memory Graph",
                    guidance=(
                        "Graph-expanded memories connected by shared entities, pages, workflows, failures, "
                        "or selector relationships. Use these as supporting context, not primary evidence."
                    ),
                    items=related_items[: min(5, limit)],
                )
            )

        if include_graph:
            graph = unified.get("graph_context") or {}
            if graph:
                bundle.graph = graph

        selector_patterns = unified.get("selector_patterns") or []
        if selector_patterns:
            bundle.sections.append(
                MemoryContextSection(
                    name="Selector Pattern Memory",
                    guidance=(
                        "Previously successful selector/action patterns. Use as hints only, then validate "
                        "against the live page before generating or executing code."
                    ),
                    items=selector_patterns[: min(5, limit)],
                )
            )

        browser_bundle = unified.get("browser_memory") or {}
        browser_memory: list[dict[str, Any]] = []
        for state in browser_bundle.get("states", [])[:4]:
            browser_memory.append({"type": "state", **state})
        for element in browser_bundle.get("elements", [])[:8]:
            browser_memory.append({"type": "element", **element})
        for frontier in browser_bundle.get("frontier", [])[:4]:
            browser_memory.append({"type": "frontier", **frontier})
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

        retrieved_knowledge = (bundle.unified or {}).get("retrieved_knowledge") or {}
        retrieved_items = retrieved_knowledge.get("items") or []
        if retrieved_items:
            lines.append("")
            lines.append("### Retrieved Knowledge")
            lines.append(
                "Use these cited retrieval results as advisory evidence only. Prefer current files, live browser state, "
                "and explicit user instruction when they conflict."
            )
            for item in retrieved_items:
                label = item.get("citation_label") or item.get("id") or "M?"
                score = "" if item.get("score") is None else f", score={float(item.get('score') or 0):.2f}"
                freshness = f", freshness={item.get('freshness')}" if item.get("freshness") else ""
                warning = f", warning={_clip_line(str(item.get('warning')), 90)}" if item.get("warning") else ""
                reason = f", reason={_clip_line(str(item.get('reason')), 90)}" if item.get("reason") else ""
                lines.append(
                    "- "
                    f"[{label}, source={item.get('source')}{score}{freshness}{reason}{warning}] "
                    f"{_clip_line(str(item.get('summary') or item.get('title') or ''))}"
                )

        for section in bundle.sections:
            lines.append("")
            lines.append(f"### {section.name}")
            lines.append(section.guidance)
            if section.name == "Browser Exploration Memory":
                lines.append(
                    "Use frontier items as prioritized candidates, not commands. Prefer stable role/label locators; "
                    "if the locator is missing or the live page differs, rediscover with browser_snapshot."
                )
            for item in sorted(section.items, key=_item_value_score, reverse=True):
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
                            f"source={item.get('state_source_fidelity', 'unknown')}; "
                            f"provenance=state:{item.get('state_id')} element:{item.get('element_id')}"
                        )
                    continue
                if section.name == "Selector Pattern Memory":
                    selector = item.get("playwright_selector") or item.get("selector_value") or ""
                    lines.append(
                        "- "
                        f"{item.get('action') or 'action'} {_clip_line(str(item.get('target') or ''))}: "
                        f"{_clip_line(str(selector), 180)} "
                        f"(success={float(item.get('success_rate') or 0):.0%}, "
                        f"test={_clip_line(str(item.get('test_name') or ''), 80)})"
                    )
                    continue
                source = ""
                if item.get("source_type") and item.get("source_id"):
                    source = f", source={item['source_type']}:{item['source_id']}"
                graph_reason = ""
                if item.get("graph_reason"):
                    graph_reason = f", graph={_clip_line(str(item['graph_reason']), 90)}"
                score = ""
                if item.get("score") is not None:
                    score = f", score={float(item['score']):.2f}"
                reason = ""
                if item.get("retrieval_reason"):
                    reason = f", reason={_clip_line(str(item['retrieval_reason']), 90)}"
                stale = ""
                if item.get("staleness_warning"):
                    stale = f", warning={_clip_line(str(item['staleness_warning']), 90)}"
                lines.append(
                    "- "
                    f"[{item['kind']}, confidence={item['confidence']:.2f}, importance={item['importance']:.2f}{score}{source}{graph_reason}{reason}{stale}] "
                    f"{_clip_line(item.get('summary') or '')}"
                )

        if len(lines) <= 2:
            return ""

        text = "\n".join(lines)
        if estimate_tokens(text) <= token_budget:
            if bundle.unified is not None:
                bundle.unified.setdefault("formatting", {})["context_tokens_estimated"] = estimate_tokens(text)
                bundle.unified.setdefault("formatting", {})["context_line_omissions"] = 0
            return text

        selected: list[str] = []
        used = 0
        omitted = 0
        item_selected = False
        minimum_budget = max(1, token_budget)
        for line in lines:
            line_tokens = estimate_tokens(line + "\n")
            is_boundary = line.startswith("##") or line.startswith("###") or line in {
                "Memory is advisory and scoped. Live browser observations and explicit user instructions outrank stored memory.",
            }
            is_item = line.startswith("- ")
            if selected and used + line_tokens > minimum_budget and is_item and not item_selected:
                selected.append(line)
                used += line_tokens
                item_selected = True
                continue
            if selected and used + line_tokens > minimum_budget and not is_boundary:
                omitted += 1
                continue
            if used + line_tokens > minimum_budget and not selected:
                selected.append(_clip_line(line, max(120, int(token_budget * 3.5))))
                used = estimate_tokens(selected[-1])
                continue
            if used + line_tokens <= minimum_budget or is_boundary:
                selected.append(line)
                used += line_tokens
                if is_item:
                    item_selected = True
            else:
                omitted += 1
        if omitted:
            selected.append(f"... omitted {omitted} lower-priority memory/context line(s) to fit budget.")
        formatted = "\n".join(selected).rstrip()
        if bundle.unified is not None:
            bundle.unified.setdefault("formatting", {})["context_tokens_estimated"] = estimate_tokens(formatted)
            bundle.unified.setdefault("formatting", {})["context_line_omissions"] = omitted
            bundle.unified.setdefault("formatting", {})["context_budget_tokens"] = token_budget
        return formatted

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
