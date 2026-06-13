"""Bounded agentic retrieval over Quorvex memory sources.

This module is intentionally read-only. Durable memory writes stay in
AgentMemoryService; this layer plans, routes, ranks, cites, and reports
diagnostics for prompt/context assembly.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_
from sqlmodel import Session, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import (
    AgentRun,
    Requirement,
    RtmEntry,
    SpecMetadata,
    TestRun,
)
from orchestrator.utils.token_budget import estimate_tokens

from .agent_memory import MemorySafetyError, _redact, _scan_memory_content
from .unified import get_unified_memory_service

SOURCE_ALIASES = {
    "agent_memory": "agent_memories",
    "memories": "agent_memories",
    "memory": "agent_memories",
    "selectors": "selector_patterns",
    "selector": "selector_patterns",
    "browser": "browser_memory",
    "graph": "graph_context",
    "coverage": "coverage_gaps",
    "prd": "prd_chunks",
    "requirements": "requirements",
    "requirement": "requirements",
    "rtm": "rtm",
    "runs": "run_summaries",
    "run": "run_summaries",
    "spec": "specs",
    "specs": "specs",
}

ALLOWED_SOURCES = {
    "agent_memories",
    "selector_patterns",
    "browser_memory",
    "graph_context",
    "coverage_gaps",
    "prd_chunks",
    "requirements",
    "rtm",
    "run_summaries",
    "specs",
}

DEFAULT_SOURCES_BY_INTENT = {
    "debugging": ["agent_memories", "run_summaries", "selector_patterns", "browser_memory", "graph_context"],
    "test_generation": [
        "agent_memories",
        "selector_patterns",
        "browser_memory",
        "requirements",
        "rtm",
        "specs",
        "prd_chunks",
    ],
    "coverage_planning": ["coverage_gaps", "requirements", "rtm", "selector_patterns", "browser_memory", "graph_context"],
    "requirements": ["requirements", "rtm", "prd_chunks", "specs"],
    "selectors": ["selector_patterns", "browser_memory", "agent_memories"],
    "general": ["agent_memories", "selector_patterns", "browser_memory", "graph_context"],
}

TRUTHY_VALUES = {"1", "true", "yes", "on"}
QUERY_TERM_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}", re.I)


@dataclass
class AgenticRagRequest:
    query: str
    intent: str | None = None
    sources: list[str] | None = None
    project_id: str | None = None
    user_id: str | None = None
    url: str | None = None
    spec_name: str | None = None
    run_id: str | None = None
    agent_type: str | None = None
    max_items: int = 8
    include_debug: bool = False


@dataclass
class EvidenceItem:
    id: str
    source: str
    title: str
    content: str
    score: float
    citation_label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    selected_reason: str = ""
    rejected_reason: str | None = None


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in TRUTHY_VALUES


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _clip(text: Any, limit: int = 420) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    return normalized if len(normalized) <= limit else normalized[: limit - 3].rstrip() + "..."


def _terms(text: str) -> set[str]:
    return {match.group(0).lower() for match in QUERY_TERM_RE.finditer(text or "")}


def _lexical_score(query: str, text: str) -> float:
    query_terms = _terms(query)
    if not query_terms:
        return 0.0
    text_terms = _terms(text)
    return min(0.28, (len(query_terms & text_terms) / max(3, len(query_terms))) * 0.28)


def _safe_text(text: Any, *, limit: int = 900) -> tuple[str | None, str | None]:
    value = _clip(_redact(str(text or "")), limit)
    if not value:
        return None, "empty"
    try:
        _scan_memory_content(value)
    except MemorySafetyError as exc:
        return None, str(exc)
    return value, None


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


class AgenticRagService:
    """Plan and execute deterministic multi-source retrieval."""

    def __init__(self, unified_service=None):
        self.unified_service = unified_service or get_unified_memory_service()

    @property
    def enabled(self) -> bool:
        return _env_bool("AGENTIC_RAG_ENABLED", True)

    @property
    def max_subqueries(self) -> int:
        return _env_int("AGENTIC_RAG_MAX_SUBQUERIES", 4, minimum=1, maximum=8)

    @property
    def timeout_ms(self) -> int:
        return _env_int("AGENTIC_RAG_TIMEOUT_MS", 2500, minimum=250, maximum=30_000)

    @property
    def debug_default(self) -> bool:
        return _env_bool("AGENTIC_RAG_DEBUG", False)

    def retrieve(self, request: AgenticRagRequest) -> dict[str, Any]:
        started = time.monotonic()
        query = _clip(request.query, 2000)
        max_items = max(1, min(int(request.max_items or 8), 25))
        include_debug = request.include_debug or self.debug_default
        intent = self.classify_intent(query, request.intent)
        sources = self.route_sources(intent=intent, requested_sources=request.sources)
        subqueries = self.decompose_query(query, intent=intent, request=request)
        diagnostics: dict[str, Any] = {
            "retriever": "agentic_rag_v1",
            "enabled": self.enabled,
            "intent": intent,
            "sources": sources,
            "query_plan": subqueries,
            "latencies_ms": {},
            "source_errors": {},
            "selected_count": 0,
            "rejected_count": 0,
            "fallback_reason": None,
            "token_budget": 1200,
        }
        if not self.enabled:
            diagnostics["fallback_reason"] = "agentic_rag_disabled"
            return self._response(query, [], [], diagnostics, include_debug=include_debug)

        candidates: list[EvidenceItem] = []
        rejected: list[EvidenceItem] = []
        seen_keys: set[tuple[str, str]] = set()
        deadline = started + (self.timeout_ms / 1000)
        for source in sources:
            if time.monotonic() > deadline:
                diagnostics["fallback_reason"] = "timeout"
                break
            source_started = time.monotonic()
            try:
                source_items: list[EvidenceItem] = []
                for subquery in subqueries:
                    if time.monotonic() > deadline:
                        diagnostics["fallback_reason"] = "timeout"
                        break
                    source_items.extend(self._retrieve_source(source, subquery, request))
                diagnostics["latencies_ms"][source] = round((time.monotonic() - source_started) * 1000, 2)
                for item in source_items:
                    key = (item.source, item.id)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    safe_content, unsafe_reason = _safe_text(item.content)
                    if unsafe_reason:
                        item.rejected_reason = unsafe_reason
                        rejected.append(item)
                        continue
                    item.content = safe_content or ""
                    item.score = self._rerank_score(item, query=query, intent=intent)
                    if item.score <= 0.05:
                        item.rejected_reason = "low score"
                        rejected.append(item)
                    else:
                        candidates.append(item)
            except Exception as exc:
                diagnostics["source_errors"][source] = str(exc)
                continue

        selected = sorted(candidates, key=lambda item: item.score, reverse=True)[:max_items]
        for index, item in enumerate(selected, start=1):
            item.citation_label = f"K{index}"
        diagnostics["selected_count"] = len(selected)
        diagnostics["rejected_count"] = len(rejected) + max(0, len(candidates) - len(selected))
        diagnostics["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
        diagnostics["chunk_ids"] = [item.id for item in selected]
        if not selected and not diagnostics.get("fallback_reason"):
            diagnostics["fallback_reason"] = "empty_retrieval"
        return self._response(query, selected, rejected, diagnostics, include_debug=include_debug)

    def classify_intent(self, query: str, explicit_intent: str | None = None) -> str:
        raw = (explicit_intent or "").strip().lower().replace("-", "_")
        if raw in DEFAULT_SOURCES_BY_INTENT:
            return raw
        lowered = query.lower()
        if re.search(r"\b(fail|failed|error|debug|flake|heal|root cause|regression)\b", lowered):
            return "debugging"
        if re.search(r"\b(selector|locator|getbyrole|getbylabel|data-testid)\b", lowered):
            return "selectors"
        if re.search(r"\b(coverage|gap|untested|not covered|what should i test next)\b", lowered):
            return "coverage_planning"
        if re.search(r"\b(requirement|rtm|prd|acceptance criteria|traceability)\b", lowered):
            return "requirements"
        if re.search(r"\b(write|create|generate|plan).{0,40}\b(test|spec|playwright)\b", lowered):
            return "test_generation"
        return "general"

    def route_sources(self, *, intent: str, requested_sources: list[str] | None = None) -> list[str]:
        if requested_sources:
            routed: list[str] = []
            invalid = []
            for source in requested_sources:
                normalized = SOURCE_ALIASES.get(str(source).strip().lower(), str(source).strip().lower())
                if normalized in ALLOWED_SOURCES and normalized not in routed:
                    routed.append(normalized)
                else:
                    invalid.append(str(source))
            if invalid:
                raise ValueError(f"Unsupported agentic RAG source(s): {', '.join(invalid)}")
            return routed
        return list(DEFAULT_SOURCES_BY_INTENT.get(intent, DEFAULT_SOURCES_BY_INTENT["general"]))

    def decompose_query(self, query: str, *, intent: str, request: AgenticRagRequest) -> list[str]:
        parts = [query]
        if request.url:
            parts.append(f"{query} url {request.url}")
        if request.spec_name:
            parts.append(f"{query} spec {request.spec_name}")
        if request.run_id:
            parts.append(f"{query} run {request.run_id}")
        if intent == "debugging":
            parts.extend([f"{query} failure pattern root cause", f"{query} prior fix selector drift"])
        elif intent == "test_generation":
            parts.extend([f"{query} proven selectors similar spec", f"{query} requirement acceptance criteria"])
        elif intent == "coverage_planning":
            parts.extend([f"{query} coverage gaps untested flows", f"{query} uncovered requirements"])
        elif intent == "selectors":
            parts.append(f"{query} locator selector getByRole")
        unique: list[str] = []
        for part in parts:
            clipped = _clip(part, 500)
            if clipped and clipped not in unique:
                unique.append(clipped)
            if len(unique) >= self.max_subqueries:
                break
        return unique

    def _retrieve_source(self, source: str, query: str, request: AgenticRagRequest) -> list[EvidenceItem]:
        if source in {"agent_memories", "selector_patterns", "browser_memory", "graph_context", "coverage_gaps"}:
            return self._retrieve_from_unified(source, query, request)
        if source == "prd_chunks":
            return self._retrieve_prd_chunks(query, request)
        if source == "requirements":
            return self._retrieve_requirements(query, request)
        if source == "rtm":
            return self._retrieve_rtm(query, request)
        if source == "run_summaries":
            return self._retrieve_run_summaries(query, request)
        if source == "specs":
            return self._retrieve_specs(query, request)
        return []

    def _retrieve_from_unified(self, source: str, query: str, request: AgenticRagRequest) -> list[EvidenceItem]:
        bundle = self.unified_service.build_bundle(
            query=query,
            project_id=request.project_id,
            user_id=request.user_id,
            agent_type=request.agent_type,
            limit=max(4, min(request.max_items, 12)),
            include_review_required=False,
        )
        items: list[EvidenceItem] = []
        if source == "agent_memories":
            for memory_type, memories in (bundle.get("agent_memories") or {}).items():
                for memory in memories or []:
                    items.append(
                        EvidenceItem(
                            id=str(memory.get("id")),
                            source=source,
                            title=f"{memory.get('kind')} ({memory_type})",
                            content=memory.get("summary") or "",
                            score=float(memory.get("score") or 0.4),
                            metadata={
                                "memory_type": memory_type,
                                "source_type": memory.get("source_type"),
                                "source_id": memory.get("source_id"),
                                "confidence": memory.get("confidence"),
                                "importance": memory.get("importance"),
                                "updated_at": memory.get("updated_at"),
                                "score_breakdown": memory.get("score_breakdown") or {},
                            },
                            warnings=[memory.get("staleness_warning")] if memory.get("staleness_warning") else [],
                            selected_reason=memory.get("retrieval_reason") or "agent memory match",
                        )
                    )
        elif source == "selector_patterns":
            for pattern in bundle.get("selector_patterns") or []:
                selector = pattern.get("playwright_selector") or pattern.get("selector_value") or ""
                content = f"{pattern.get('action') or 'action'} {pattern.get('target') or ''}: {selector}"
                distance = pattern.get("distance")
                score = 0.62 if distance is None else max(0.1, min(0.9, 1.0 - float(distance)))
                items.append(
                    EvidenceItem(
                        id=str(pattern.get("id") or selector or content),
                        source=source,
                        title=f"Selector pattern: {pattern.get('test_name') or pattern.get('action') or 'test'}",
                        content=content,
                        score=score,
                        metadata=pattern,
                        selected_reason="similar successful test pattern",
                    )
                )
        elif source == "browser_memory":
            browser = bundle.get("browser_memory") or {}
            for state in browser.get("states", []) or []:
                items.append(
                    EvidenceItem(
                        id=str(state.get("id") or state.get("state_key") or state.get("url")),
                        source=source,
                        title=f"Browser state: {state.get('state_key') or state.get('url')}",
                        content=state.get("url") or state.get("title") or "",
                        score=float(state.get("rank_score") or state.get("priority_score") or 0.45),
                        metadata=state,
                        selected_reason="remembered browser state",
                    )
                )
            for element in browser.get("elements", []) or []:
                locator = element.get("best_locator") or {}
                content = f"{element.get('role') or 'element'} {element.get('name') or ''}: {locator.get('locator') or ''}"
                items.append(
                    EvidenceItem(
                        id=str(element.get("id") or content),
                        source=source,
                        title=f"Browser element: {element.get('name') or element.get('role') or 'element'}",
                        content=content,
                        score=float(locator.get("score") or 0.42),
                        metadata=element,
                        selected_reason="remembered browser element",
                    )
                )
            for frontier in browser.get("frontier", []) or []:
                content = f"{frontier.get('action_type') or 'action'} {frontier.get('name') or frontier.get('text') or ''}"
                items.append(
                    EvidenceItem(
                        id=str(frontier.get("id") or content),
                        source=source,
                        title=f"Frontier: {frontier.get('action_type') or 'action'}",
                        content=content,
                        score=float(frontier.get("rank_score") or frontier.get("priority_score") or 0.4),
                        metadata=frontier,
                        warnings=["Validate against the live browser before acting."],
                        selected_reason="unexplored or prioritized browser frontier",
                    )
                )
        elif source == "graph_context":
            graph = bundle.get("graph_context") or {}
            for flow in graph.get("flows", []) or []:
                title = flow.get("name") or flow.get("title") or flow.get("id") or "flow"
                items.append(
                    EvidenceItem(
                        id=f"flow:{title}",
                        source=source,
                        title=f"Known flow: {title}",
                        content=str(flow),
                        score=0.45,
                        metadata=flow,
                        selected_reason="application graph flow",
                    )
                )
            stats = graph.get("stats") or {}
            if stats:
                items.append(
                    EvidenceItem(
                        id="graph:stats",
                        source=source,
                        title="Application graph stats",
                        content=str(stats),
                        score=0.35,
                        metadata=stats,
                        selected_reason="application graph summary",
                    )
                )
        elif source == "coverage_gaps":
            for gap in bundle.get("coverage_gaps") or []:
                items.append(
                    EvidenceItem(
                        id=str(gap.get("id") or gap.get("element_id") or gap.get("description")),
                        source=source,
                        title=f"Coverage gap: {gap.get('priority') or 'medium'}",
                        content=gap.get("description") or str(gap),
                        score=0.65 if gap.get("priority") in {"high", "critical"} else 0.5,
                        metadata=gap,
                        selected_reason="coverage gap",
                    )
                )
        return items

    def _retrieve_prd_chunks(self, query: str, request: AgenticRagRequest) -> list[EvidenceItem]:
        from .vector_store import get_vector_store

        hits = get_vector_store(project_id=request.project_id or "default").search_prd_context(
            query,
            project_id=request.project_id,
            n_results=max(3, min(request.max_items, 10)),
        )
        items = []
        for hit in hits:
            metadata = hit.get("metadata") or {}
            if request.project_id and metadata.get("project_id") and metadata.get("project_id") != request.project_id:
                continue
            distance = hit.get("distance")
            score = 0.62 if distance is None else max(0.08, min(0.92, 1.0 - float(distance)))
            title = metadata.get("feature") or metadata.get("section") or "PRD chunk"
            items.append(
                EvidenceItem(
                    id=str(hit.get("id")),
                    source="prd_chunks",
                    title=str(title),
                    content=hit.get("content") or "",
                    score=score,
                    metadata={**metadata, "distance": distance},
                    selected_reason="PRD vector match",
                )
            )
        return items

    def _retrieve_requirements(self, query: str, request: AgenticRagRequest) -> list[EvidenceItem]:
        terms = _terms(query)
        with Session(engine) as session:
            statement = select(Requirement)
            if request.project_id:
                statement = statement.where(Requirement.project_id == request.project_id)
            rows = session.exec(statement.order_by(Requirement.updated_at.desc()).limit(200)).all()
        items: list[EvidenceItem] = []
        for req in rows:
            text = " ".join(
                [
                    req.req_code,
                    req.title,
                    req.description or "",
                    req.category,
                    req.priority,
                    " ".join(req.acceptance_criteria),
                ]
            )
            if terms and not (_terms(text) & terms):
                continue
            warnings = []
            if req.truth_state in {"rejected", "stale"}:
                warnings.append(f"Requirement truth state is {req.truth_state}.")
            score = 0.5 + (0.12 if req.priority in {"high", "critical"} else 0) + float(req.confidence or 0) * 0.18
            items.append(
                EvidenceItem(
                    id=f"requirement:{req.id}",
                    source="requirements",
                    title=f"{req.req_code}: {req.title}",
                    content=text,
                    score=score,
                    metadata={
                        "requirement_id": req.id,
                        "req_code": req.req_code,
                        "priority": req.priority,
                        "status": req.status,
                        "truth_state": req.truth_state,
                        "updated_at": _iso(req.updated_at),
                    },
                    warnings=warnings,
                    selected_reason="requirement match",
                )
            )
        return items[: max(3, min(request.max_items, 12))]

    def _retrieve_rtm(self, query: str, request: AgenticRagRequest) -> list[EvidenceItem]:
        terms = _terms(query)
        with Session(engine) as session:
            statement = select(RtmEntry)
            if request.project_id:
                statement = statement.where(RtmEntry.project_id == request.project_id)
            if request.spec_name:
                statement = statement.where(RtmEntry.test_spec_name == request.spec_name)
            rows = session.exec(statement.order_by(RtmEntry.updated_at.desc()).limit(100)).all()
        items: list[EvidenceItem] = []
        for entry in rows:
            text = " ".join(
                [
                    entry.test_spec_name,
                    entry.mapping_type,
                    entry.coverage_notes or "",
                    entry.gap_notes or "",
                ]
            )
            if terms and not (_terms(text) & terms):
                continue
            score = 0.54 + float(entry.confidence or 0) * 0.22
            if entry.gap_notes:
                score += 0.08
            items.append(
                EvidenceItem(
                    id=f"rtm:{entry.id}",
                    source="rtm",
                    title=f"RTM mapping: {entry.test_spec_name}",
                    content=text,
                    score=score,
                    metadata={
                        "rtm_entry_id": entry.id,
                        "requirement_id": entry.requirement_id,
                        "mapping_type": entry.mapping_type,
                        "confidence": entry.confidence,
                        "updated_at": _iso(entry.updated_at),
                    },
                    selected_reason="RTM mapping match",
                )
            )
        return items[: max(3, min(request.max_items, 12))]

    def _retrieve_run_summaries(self, query: str, request: AgenticRagRequest) -> list[EvidenceItem]:
        terms = _terms(query)
        with Session(engine) as session:
            statement = select(TestRun)
            if request.project_id:
                statement = statement.where(TestRun.project_id == request.project_id)
            if request.run_id:
                statement = statement.where(TestRun.id == request.run_id)
            if request.spec_name:
                statement = statement.where(TestRun.spec_name == request.spec_name)
            rows = session.exec(statement.order_by(TestRun.created_at.desc()).limit(50)).all()
            agent_statement = select(AgentRun)
            if request.project_id:
                agent_statement = agent_statement.where(AgentRun.project_id == request.project_id)
            if request.run_id:
                agent_statement = agent_statement.where(AgentRun.id == request.run_id)
            agent_rows = session.exec(agent_statement.order_by(AgentRun.created_at.desc()).limit(20)).all()
        items: list[EvidenceItem] = []
        for run in rows:
            summary = run.agentic_summary or {}
            text = " ".join(
                [
                    run.id,
                    run.spec_name,
                    run.status,
                    run.test_name or "",
                    run.error_message or "",
                    run.current_stage or "",
                    str(summary),
                ]
            )
            if terms and not (_terms(text) & terms):
                continue
            score = 0.7 if run.status in {"failed", "error"} else 0.46
            items.append(
                EvidenceItem(
                    id=f"run:{run.id}",
                    source="run_summaries",
                    title=f"Test run {run.id}: {run.status}",
                    content=text,
                    score=score,
                    metadata={
                        "run_id": run.id,
                        "spec_name": run.spec_name,
                        "status": run.status,
                        "created_at": _iso(run.created_at),
                    },
                    selected_reason="recent test run summary",
                )
            )
        for run in agent_rows:
            result = run.result or {}
            text = " ".join([run.id, run.agent_type, run.status, str(result)[:800]])
            if terms and not (_terms(text) & terms):
                continue
            items.append(
                EvidenceItem(
                    id=f"agent-run:{run.id}",
                    source="run_summaries",
                    title=f"Agent run {run.id}: {run.status}",
                    content=text,
                    score=0.58,
                    metadata={
                        "agent_run_id": run.id,
                        "agent_type": run.agent_type,
                        "status": run.status,
                        "created_at": _iso(run.created_at),
                    },
                    selected_reason="recent agent run summary",
                )
            )
        return items[: max(3, min(request.max_items, 12))]

    def _retrieve_specs(self, query: str, request: AgenticRagRequest) -> list[EvidenceItem]:
        terms = _terms(query)
        with Session(engine) as session:
            statement = select(SpecMetadata)
            if request.project_id:
                statement = statement.where(or_(SpecMetadata.project_id == request.project_id, SpecMetadata.project_id.is_(None)))
            if request.spec_name:
                statement = statement.where(SpecMetadata.spec_name == request.spec_name)
            rows = session.exec(statement.limit(200)).all()
        items = []
        for spec in rows:
            text = " ".join([spec.spec_name, spec.description or "", " ".join(spec.tags)])
            if terms and not (_terms(text) & terms):
                continue
            items.append(
                EvidenceItem(
                    id=f"spec:{spec.spec_name}",
                    source="specs",
                    title=f"Spec: {spec.spec_name}",
                    content=text,
                    score=0.48,
                    metadata={
                        "spec_name": spec.spec_name,
                        "tags": spec.tags,
                        "last_modified": _iso(spec.last_modified),
                    },
                    selected_reason="similar spec metadata",
                )
            )
        return items[: max(3, min(request.max_items, 12))]

    def _rerank_score(self, item: EvidenceItem, *, query: str, intent: str) -> float:
        source_bonus = {
            "agent_memories": 0.06,
            "selector_patterns": 0.1 if intent in {"selectors", "test_generation", "debugging"} else 0.04,
            "coverage_gaps": 0.12 if intent == "coverage_planning" else 0.04,
            "requirements": 0.1 if intent in {"requirements", "test_generation", "coverage_planning"} else 0.02,
            "rtm": 0.08 if intent in {"requirements", "coverage_planning"} else 0.02,
            "run_summaries": 0.1 if intent == "debugging" else 0.02,
            "prd_chunks": 0.08 if intent in {"requirements", "test_generation"} else 0.02,
            "browser_memory": 0.05,
            "graph_context": 0.03,
            "specs": 0.04,
        }.get(item.source, 0.0)
        warning_penalty = min(0.18, len([w for w in item.warnings if w]) * 0.06)
        lexical = _lexical_score(query, f"{item.title} {item.content}")
        score = float(item.score or 0) + source_bonus + lexical - warning_penalty
        item.selected_reason = item.selected_reason or "ranked evidence"
        return round(max(0.0, min(1.0, score)), 3)

    def _response(
        self,
        query: str,
        selected: list[EvidenceItem],
        rejected: list[EvidenceItem],
        diagnostics: dict[str, Any],
        *,
        include_debug: bool,
    ) -> dict[str, Any]:
        lines = [
            "## Retrieved Knowledge",
            "Retrieved content is advisory. Live browser state, current files/specs, and explicit user instruction outrank memory.",
        ]
        citations = []
        warnings: list[str] = []
        for item in selected:
            warning_text = f" warning={'; '.join(w for w in item.warnings if w)}" if item.warnings else ""
            lines.append(
                f"- [{item.citation_label}] {item.title} "
                f"(source={item.source}, score={item.score:.2f}, reason={_clip(item.selected_reason, 80)}{warning_text}): "
                f"{_clip(item.content, 320)}"
            )
            citations.append(
                {
                    "label": item.citation_label,
                    "id": item.id,
                    "source": item.source,
                    "title": item.title,
                    "score": item.score,
                    "reason": item.selected_reason,
                    "metadata": item.metadata,
                    "warnings": [w for w in item.warnings if w],
                }
            )
            warnings.extend(w for w in item.warnings if w)
        if len(lines) == 2:
            lines.append("- No grounded memory context was found for this query.")
        answer_context = "\n".join(lines)
        debug = {
            **diagnostics,
            "rejected_candidates": [
                {"id": item.id, "source": item.source, "reason": item.rejected_reason, "score": item.score}
                for item in rejected[:25]
            ],
            "context_tokens_estimated": estimate_tokens(answer_context),
        }
        return {
            "query": query,
            "answer_context": answer_context,
            "citations": citations,
            "gaps": self._gaps(selected, diagnostics),
            "recommended_next_tools": self._recommended_next_tools(diagnostics.get("intent"), selected),
            "warnings": list(dict.fromkeys(warnings)),
            "debug": debug if include_debug else {},
        }

    def _gaps(self, selected: list[EvidenceItem], diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
        gaps = []
        if diagnostics.get("fallback_reason"):
            gaps.append({"type": "retrieval", "message": diagnostics["fallback_reason"]})
        sources_with_hits = {item.source for item in selected}
        for source in diagnostics.get("sources") or []:
            if source not in sources_with_hits:
                gaps.append({"type": "source_empty", "source": source, "message": f"No selected evidence from {source}."})
        return gaps[:8]

    def _recommended_next_tools(self, intent: str | None, selected: list[EvidenceItem]) -> list[str]:
        if intent == "debugging":
            return ["analyzeUiTestRunArtifacts", "getRunLogs", "getProvenSelectors"]
        if intent == "test_generation":
            return ["getSpecContent", "createTestSpec", "getProvenSelectors"]
        if intent == "coverage_planning":
            return ["planUiTestCoverage", "getRTMGaps", "getCoverageGaps"]
        if intent == "requirements":
            return ["getRTMSummary", "getRTMGaps", "listRequirements"]
        if any(item.source == "browser_memory" for item in selected):
            return ["startExplorerAgent", "getCoverageGaps"]
        return ["searchMemory", "getTestSuggestions"]


def get_agentic_rag_service(unified_service=None) -> AgenticRagService:
    return AgenticRagService(unified_service=unified_service)
