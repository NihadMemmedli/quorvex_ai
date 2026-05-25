"""
Memory and Coverage API endpoints

Provides access to:
- Test patterns stored in memory
- Coverage statistics
- Similar test suggestions
- Coverage gaps
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlmodel import Session, select

from orchestrator.api.db import get_session
from orchestrator.api.middleware.auth import get_current_user_optional
from orchestrator.api.models_db import ChatConversation, ChatMessage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])


# ========= Request/Response Models =========


class PatternSummary(BaseModel):
    """Summary of a test pattern"""

    id: str
    action: str
    target: str
    success_rate: float
    avg_duration: float
    test_name: str


class SimilarTestsRequest(BaseModel):
    """Request for finding similar tests"""

    description: str
    n_results: int = 5
    min_success_rate: float = 0.5
    project_id: str | None = None


class CoverageSummary(BaseModel):
    """Coverage summary"""

    total_patterns: int
    graph_stats: dict[str, Any]
    url: str | None = None


class CoverageGap(BaseModel):
    """A coverage gap"""

    type: str
    element_id: str | None = None
    element_type: str | None = None
    selector: dict[str, Any] | None = None
    text: str | None = None
    url: str | None = None
    description: str
    priority: str


class TestSuggestion(BaseModel):
    """A test idea/suggestion"""

    description: str
    type: str
    priority: str
    gap: dict[str, Any] | None = None
    title: str | None = None
    source_flow: str | None = None
    source_requirement: str | None = None
    source_api_endpoint: str | None = None
    suggested_steps: list[str] = Field(default_factory=list)
    expected_outcomes: list[str] = Field(default_factory=list)
    spec_readiness: str | None = None
    confidence: float | None = None


class SelectorInfo(BaseModel):
    """Selector information"""

    selector_type: str
    selector_value: str
    success_rate: float
    avg_duration: float
    usage_count: int


class AgentMemoryCreateRequest(BaseModel):
    kind: str
    content: str
    project_id: str | None = None
    user_id: str | None = None
    memory_type: str | None = None
    scope: str | None = None
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    confidence: float = 0.7
    importance: float = 0.5
    source_type: str | None = "manual"
    source_id: str | None = None
    agent_type: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    supersedes_id: str | None = None
    review_required: bool = False
    last_verified_at: datetime | None = None
    extra_data: dict[str, Any] = Field(default_factory=dict)


class AgentMemoryUpdateRequest(BaseModel):
    kind: str | None = None
    content: str | None = None
    memory_type: str | None = None
    scope: str | None = None
    summary: str | None = None
    tags: list[str] | None = None
    confidence: float | None = None
    importance: float | None = None
    source_type: str | None = None
    source_id: str | None = None
    agent_type: str | None = None
    status: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    supersedes_id: str | None = None
    review_required: bool | None = None
    last_verified_at: datetime | None = None
    extra_data: dict[str, Any] | None = None


class AgentMemoryConsolidateRequest(BaseModel):
    text: str
    project_id: str | None = None
    user_id: str | None = None
    source_type: str | None = "manual_consolidation"
    source_id: str | None = None
    agent_type: str | None = None
    use_llm: bool = False
    review_required: bool | None = None


class MemoryInjectionFeedbackRequest(BaseModel):
    rating: str
    comment: str | None = None


class MemoryRepairRequest(BaseModel):
    project_id: str | None = None
    action: str
    dry_run: bool = True


class AgentMemoryResponse(BaseModel):
    id: str
    project_id: str | None = None
    user_id: str | None = None
    kind: str
    memory_type: str
    scope: str
    content: str
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    confidence: float
    importance: float
    source_type: str | None = None
    source_id: str | None = None
    agent_type: str | None = None
    status: str
    valid_from: str | None = None
    valid_until: str | None = None
    supersedes_id: str | None = None
    review_required: bool = False
    last_verified_at: str | None = None
    created_at: str
    updated_at: str
    last_used_at: str | None = None
    use_count: int


class StaleMemoryVerifyRequest(BaseModel):
    project_id: str | None = None
    older_than_days: int = Field(default=30, ge=1, le=3650)
    limit: int = Field(default=50, ge=1, le=200)


class SessionRecallMessage(BaseModel):
    id: int
    role: str
    content: str
    tool_name: str | None = None
    created_at: str
    anchor: bool = False


class SessionRecallResult(BaseModel):
    conversation_id: str
    title: str
    project_id: str | None = None
    updated_at: str
    match_message_id: int | None = None
    snippet: str | None = None
    messages: list[SessionRecallMessage] = Field(default_factory=list)
    bookend_start: list[SessionRecallMessage] = Field(default_factory=list)
    bookend_end: list[SessionRecallMessage] = Field(default_factory=list)
    messages_before: int = 0
    messages_after: int = 0


class BrowserMemoryBundleResponse(BaseModel):
    project_id: str
    states: list[dict[str, Any]] = Field(default_factory=list)
    elements: list[dict[str, Any]] = Field(default_factory=list)
    frontier: list[dict[str, Any]] = Field(default_factory=list)


class BrowserFrontierClaimRequest(BaseModel):
    project_id: str = "default"
    worker_id: str
    query: str = ""
    limit: int = Field(default=5, ge=1, le=50)
    lease_seconds: int = Field(default=900, ge=30, le=86_400)
    risk_max: str = Field(default="medium")
    url_scope: str | None = None


class BrowserFrontierFailRequest(BaseModel):
    project_id: str = "default"
    error: str
    retry_after_seconds: int = Field(default=300, ge=30, le=86_400)
    max_attempts: int = Field(default=3, ge=1, le=20)


class BrowserFrontierCompleteRequest(BaseModel):
    project_id: str = "default"
    transition_id: str | None = None
    outcome: str | None = None


class BrowserFrontierSkipRequest(BaseModel):
    project_id: str = "default"
    reason: str


# ========= Endpoints =========

from orchestrator.memory import get_memory_manager
from orchestrator.memory.agent_memory import get_agent_memory_service
from orchestrator.memory.browser_memory import get_exploration_memory_service
from orchestrator.memory.config import get_config

# ========= Endpoints =========


def _get_manager(project_id: str | None = None):
    """Get memory manager instance with proper context"""
    return get_memory_manager(project_id=project_id)


def _agent_memory_response(memory) -> AgentMemoryResponse:
    return AgentMemoryResponse(
        id=memory.id,
        project_id=memory.project_id,
        user_id=memory.user_id,
        kind=memory.kind,
        memory_type=memory.memory_type or "semantic",
        scope=memory.scope or "project",
        content=memory.content,
        summary=memory.summary,
        tags=memory.tags or [],
        confidence=memory.confidence,
        importance=memory.importance,
        source_type=memory.source_type,
        source_id=memory.source_id,
        agent_type=memory.agent_type,
        status=memory.status,
        valid_from=memory.valid_from.isoformat() if memory.valid_from else None,
        valid_until=memory.valid_until.isoformat() if memory.valid_until else None,
        supersedes_id=memory.supersedes_id,
        review_required=memory.review_required,
        last_verified_at=memory.last_verified_at.isoformat() if memory.last_verified_at else None,
        created_at=memory.created_at.isoformat(),
        updated_at=memory.updated_at.isoformat(),
        last_used_at=memory.last_used_at.isoformat() if memory.last_used_at else None,
        use_count=memory.use_count,
    )


def _snippet(content: str, query: str, radius: int = 80) -> str:
    if not content:
        return ""
    idx = content.lower().find(query.lower())
    if idx < 0:
        return content[: radius * 2].strip()
    start = max(0, idx - radius)
    end = min(len(content), idx + len(query) + radius)
    return f"{'...' if start else ''}{content[start:end].strip()}{'...' if end < len(content) else ''}"


def _shape_recall_message(message: ChatMessage, *, anchor_id: int | None = None) -> SessionRecallMessage:
    return SessionRecallMessage(
        id=int(message.id or 0),
        role=message.role,
        content=message.content or "",
        tool_name=message.tool_name,
        created_at=message.created_at.isoformat(),
        anchor=bool(anchor_id is not None and message.id == anchor_id),
    )


def _conversation_guard(session: Session, conversation_id: str, user) -> ChatConversation:
    conversation = session.get(ChatConversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if user and conversation.user_id and conversation.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")
    return conversation


@router.get("/patterns", response_model=list[PatternSummary])
async def list_patterns(
    project_id: str | None = Query("demo", description="Project ID for isolation"),
    limit: int = Query(100, description="Maximum patterns to return"),
) -> list[PatternSummary]:
    """
    List all stored test patterns.

    Returns a list of test patterns that have been stored in memory.
    """
    try:
        manager = get_memory_manager(project_id)
        all_patterns = manager.vector_store.get_all_patterns()

        results = []
        for pattern in all_patterns[:limit]:
            metadata = pattern.get("metadata", {})
            results.append(
                PatternSummary(
                    id=pattern.get("id", ""),
                    action=metadata.get("action", "unknown"),
                    target=metadata.get("target", "unknown"),
                    success_rate=metadata.get("success_rate", 0),
                    avg_duration=metadata.get("avg_duration", 0),
                    test_name=metadata.get("test_name", "unknown"),
                )
            )

        return results

    except Exception as e:
        logger.error(f"Failed to list patterns: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/similar", response_model=list[PatternSummary])
async def find_similar_tests(request: SimilarTestsRequest) -> list[PatternSummary]:
    """
    Find similar tests based on description.

    Uses semantic search to find test patterns similar to the given description.
    """
    try:
        manager = _get_manager(request.project_id)

        similar = manager.find_similar_tests(
            description=request.description, n_results=request.n_results, min_success_rate=request.min_success_rate
        )

        results = []
        for sim in similar:
            metadata = sim.get("metadata", {})
            results.append(
                PatternSummary(
                    id=sim.get("id", ""),
                    action=metadata.get("action", "unknown"),
                    target=metadata.get("target", "unknown"),
                    success_rate=metadata.get("success_rate", 0),
                    avg_duration=metadata.get("avg_duration", 0),
                    test_name=metadata.get("test_name", "unknown"),
                )
            )

        return results

    except Exception as e:
        logger.error(f"Failed to find similar tests: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/selectors", response_model=list[SelectorInfo])
async def get_successful_selectors(
    element_description: str = Query(..., description="Description of the element"),
    action: str | None = Query(None, description="Action type filter"),
    min_success_rate: float = Query(0.7, description="Minimum success rate"),
    project_id: str | None = Query("demo", description="Project ID for isolation"),
) -> list[SelectorInfo]:
    """
    Get successful selectors for a similar element.

    Returns selectors that have worked well for similar elements in the past.
    """
    try:
        manager = get_memory_manager(project_id)

        selectors = manager.get_successful_selectors(
            element_description=element_description, action=action, min_success_rate=min_success_rate
        )

        results = []
        for sel in selectors:
            metadata = sel.get("metadata", {})
            results.append(
                SelectorInfo(
                    selector_type=metadata.get("selector_type", "unknown"),
                    selector_value=metadata.get("selector_value", ""),
                    success_rate=metadata.get("success_rate", 0),
                    avg_duration=metadata.get("avg_duration", 0),
                    usage_count=metadata.get("success_count", 0) + metadata.get("failure_count", 0),
                )
            )

        return results

    except Exception as e:
        logger.error(f"Failed to get selectors: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/coverage/summary", response_model=CoverageSummary)
async def get_coverage_summary(
    url: str | None = Query(None, description="Filter by URL"),
    project_id: str | None = Query("demo", description="Project ID for isolation"),
) -> CoverageSummary:
    """
    Get coverage summary.

    Returns overall coverage statistics.
    """
    try:
        manager = get_memory_manager(project_id)

        summary = manager.get_coverage_summary(url=url)

        return CoverageSummary(
            total_patterns=summary.get("total_patterns", 0), graph_stats=summary.get("graph_stats", {}), url=url
        )

    except Exception as e:
        logger.error(f"Failed to get coverage summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/coverage/gaps", response_model=list[CoverageGap])
async def get_coverage_gaps(
    url: str | None = Query(None, description="Filter by URL"),
    max_results: int = Query(20, description="Maximum results to return"),
    project_id: str | None = Query("demo", description="Project ID for isolation"),
) -> list[CoverageGap]:
    """
    Get coverage gaps.

    Returns elements and flows that haven't been tested yet.
    """
    try:
        manager = get_memory_manager(project_id)

        gaps = manager.get_coverage_gaps(url=url, max_results=max_results)

        results = []
        for gap in gaps:
            results.append(
                CoverageGap(
                    type=gap.get("type", "unknown"),
                    element_id=gap.get("element_id"),
                    element_type=gap.get("element_type"),
                    selector=gap.get("selector"),
                    text=gap.get("text"),
                    url=gap.get("url"),
                    description=gap.get("description", ""),
                    priority=gap.get("priority", "medium"),
                )
            )

        return results

    except Exception as e:
        logger.error(f"Failed to get coverage gaps: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/coverage/suggestions", response_model=list[TestSuggestion])
async def get_test_suggestions(
    url: str | None = Query(None, description="Base URL for context"),
    feature: str | None = Query(None, description="Feature name for context"),
    max_suggestions: int = Query(10, description="Maximum suggestions to return"),
    project_id: str | None = Query("demo", description="Project ID for isolation"),
) -> list[TestSuggestion]:
    """
    Get test suggestions based on coverage gaps.

    Suggests new tests that could improve coverage.
    """
    try:
        manager = get_memory_manager(project_id)

        context: dict[str, Any] = {}
        if url:
            context["url"] = url
        if feature:
            context["feature"] = feature

        suggestions = manager.suggest_test_ideas(context=context, max_suggestions=max_suggestions)

        results = []
        for suggestion in suggestions:
            results.append(
                TestSuggestion(
                    description=suggestion.get("description", ""),
                    type=suggestion.get("type", "coverage"),
                    priority=suggestion.get("priority", "medium"),
                    gap=suggestion.get("gap"),
                    title=suggestion.get("title"),
                    source_flow=suggestion.get("source_flow"),
                    source_requirement=suggestion.get("source_requirement"),
                    source_api_endpoint=suggestion.get("source_api_endpoint"),
                    suggested_steps=suggestion.get("suggested_steps", []),
                    expected_outcomes=suggestion.get("expected_outcomes", []),
                    spec_readiness=suggestion.get("spec_readiness"),
                    confidence=suggestion.get("confidence"),
                )
            )

        return results

    except Exception as e:
        logger.error(f"Failed to get test suggestions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/graph/stats")
async def get_graph_stats(
    project_id: str | None = Query("demo", description="Project ID for isolation"),
) -> dict[str, Any]:
    """
    Get application graph statistics.

    Returns information about discovered pages, elements, and flows.
    """
    try:
        manager = get_memory_manager(project_id)

        stats = manager.graph_store.get_graph_stats()

        return {
            "page_count": stats.get("page_count", 0),
            "element_count": stats.get("element_count", 0),
            "flow_count": stats.get("flow_count", 0),
            "total_nodes": stats.get("total_nodes", 0),
            "total_edges": stats.get("total_edges", 0),
        }

    except Exception as e:
        logger.error(f"Failed to get graph stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/graph/pages")
async def get_pages(
    project_id: str | None = Query("demo", description="Project ID for isolation"),
) -> list[dict[str, Any]]:
    """
    Get all discovered pages.

    Returns list of pages that have been discovered.
    """
    try:
        manager = get_memory_manager(project_id)

        pages = []
        for node in manager.graph_store.graph.nodes():
            attrs = manager.graph_store.graph.nodes[node]
            if attrs.get("type") == "page":
                pages.append({"id": node, "url": attrs.get("url", ""), "title": attrs.get("title", "")})

        return pages

    except Exception as e:
        logger.error(f"Failed to get pages: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/graph/flows")
async def get_flows(
    project_id: str | None = Query("demo", description="Project ID for isolation"),
) -> list[dict[str, Any]]:
    """
    Get all discovered flows.

    Returns list of user flows that have been discovered.
    """
    try:
        manager = get_memory_manager(project_id)

        return manager.graph_store.get_all_flows()

    except Exception as e:
        logger.error(f"Failed to get flows: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/graph/knowledge")
async def get_knowledge_graph(
    project_id: str | None = Query(None, description="Project ID for isolation"),
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    """Get the SQL-backed agent memory knowledge graph."""
    try:
        from orchestrator.memory.knowledge_graph import get_memory_knowledge_graph_service

        return get_memory_knowledge_graph_service().graph_summary(project_id=project_id, limit=limit)
    except Exception as e:
        logger.error(f"Failed to get memory knowledge graph: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/graph/memory/{memory_id}")
async def get_memory_knowledge_graph(
    memory_id: str,
    project_id: str | None = Query(None, description="Project ID guard"),
) -> dict[str, Any]:
    """Get graph nodes and edges connected to one agent memory."""
    try:
        from orchestrator.memory.knowledge_graph import get_memory_knowledge_graph_service

        graph = get_memory_knowledge_graph_service().graph_for_memory(memory_id, project_id=project_id)
        if not graph["nodes"]:
            raise HTTPException(status_code=404, detail="Memory graph node not found")
        return graph
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get memory graph for memory {memory_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/graph/review")
async def list_graph_review_edges(
    project_id: str | None = Query(None, description="Project ID guard"),
    relationship_type: str | None = Query(None, description="Optional relationship type filter"),
    limit: int = Query(100, ge=1, le=200),
) -> dict[str, Any]:
    """List LLM-inferred graph edges waiting for human review."""
    try:
        from orchestrator.memory.knowledge_graph import get_memory_knowledge_graph_service

        return get_memory_knowledge_graph_service().review_edges(
            project_id=project_id,
            relationship_type=relationship_type,
            status="pending_review",
            limit=limit,
        )
    except Exception as e:
        logger.error(f"Failed to list graph review edges: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/graph/review/{edge_id}/approve")
async def approve_graph_review_edge(
    edge_id: str,
    project_id: str | None = Query(None, description="Project ID guard"),
) -> dict[str, Any]:
    """Approve a pending LLM-inferred graph edge so it can affect retrieval."""
    try:
        from orchestrator.memory.knowledge_graph import get_memory_knowledge_graph_service

        edge = get_memory_knowledge_graph_service().set_review_edge_status(
            edge_id,
            status="active",
            project_id=project_id,
        )
        if not edge:
            raise HTTPException(status_code=404, detail="Graph edge not found")
        return edge
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to approve graph review edge {edge_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/graph/review/{edge_id}/reject")
async def reject_graph_review_edge(
    edge_id: str,
    project_id: str | None = Query(None, description="Project ID guard"),
) -> dict[str, Any]:
    """Reject a pending LLM-inferred graph edge and keep it out of active retrieval."""
    try:
        from orchestrator.memory.knowledge_graph import get_memory_knowledge_graph_service

        edge = get_memory_knowledge_graph_service().set_review_edge_status(
            edge_id,
            status="rejected",
            project_id=project_id,
        )
        if not edge:
            raise HTTPException(status_code=404, detail="Graph edge not found")
        return edge
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reject graph review edge {edge_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/graph/rebuild")
async def rebuild_knowledge_graph(
    project_id: str | None = Query(None, description="Project ID for isolation"),
    include_review_required: bool = Query(False, description="Include review-required memories"),
    use_llm: bool = Query(False, description="Use optional gated LLM relationship extraction"),
) -> dict[str, int]:
    """Rebuild derived graph nodes and relationships from approved agent memories."""
    try:
        from orchestrator.memory.knowledge_graph import get_memory_knowledge_graph_service

        return get_memory_knowledge_graph_service().rebuild(
            project_id=project_id,
            include_review_required=include_review_required,
            use_llm=use_llm,
        )
    except Exception as e:
        logger.error(f"Failed to rebuild memory knowledge graph: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stats")
async def get_memory_stats(
    project_id: str | None = Query("demo", description="Project ID for isolation"),
) -> dict[str, Any]:
    """
    Get overall memory system statistics.

    Returns stats about stored patterns, coverage, and system health.
    """
    try:
        manager = get_memory_manager(project_id)

        # Get pattern counts
        all_patterns = manager.vector_store.get_all_patterns()

        # Calculate success rate stats
        success_rates = [p.get("metadata", {}).get("success_rate", 0) for p in all_patterns]
        avg_success_rate = sum(success_rates) / len(success_rates) if success_rates else 0

        # Get action breakdown
        actions = {}
        for pattern in all_patterns:
            action = pattern.get("metadata", {}).get("action", "unknown")
            actions[action] = actions.get(action, 0) + 1

        return {
            "total_patterns": len(all_patterns),
            "avg_success_rate": round(avg_success_rate * 100, 1),
            "action_breakdown": actions,
            "project_id": project_id or manager.config.project_id or "default",
        }

    except Exception as e:
        logger.error(f"Failed to get memory stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/agent", response_model=list[AgentMemoryResponse])
async def list_agent_memories(
    q: str | None = Query(None, description="Optional search query"),
    project_id: str | None = Query(None, description="Project ID for isolation"),
    user_id: str | None = Query(None, description="Optional user scope"),
    kind: list[str] | None = Query(None, description="Memory kind filter"),
    memory_type: list[str] | None = Query(None, description="Memory type filter"),
    scope: str | None = Query(None, description="Memory scope filter"),
    agent_type: str | None = Query(None, description="Agent type filter"),
    limit: int = Query(25, ge=1, le=100),
) -> list[AgentMemoryResponse]:
    """List or search curated agent working memories."""
    try:
        service = get_agent_memory_service()
        memories = service.search(
            query=q,
            project_id=project_id,
            user_id=user_id,
            agent_type=agent_type,
            kinds=kind,
            memory_types=memory_type,
            scope=scope,
            limit=limit,
            min_confidence=0.0,
        )
        return [_agent_memory_response(memory) for memory in memories]
    except Exception as e:
        logger.error(f"Failed to list agent memories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/agent/context")
async def get_agent_memory_context(
    q: str = Query("", description="Task/query text for retrieval"),
    project_id: str | None = Query(None, description="Project ID for isolation"),
    user_id: str | None = Query(None, description="Optional user scope"),
    agent_type: str | None = Query(None, description="Agent type filter"),
    limit: int = Query(8, ge=1, le=12),
) -> dict[str, Any]:
    """Return formatted agent memory context for prompt injection."""
    try:
        from orchestrator.memory.context_builder import MemoryContextBuilder

        service = get_agent_memory_service()
        builder = MemoryContextBuilder(service=service)
        bundle = builder.build_bundle(
            query=q,
            project_id=project_id,
            user_id=user_id,
            agent_type=agent_type,
            limit=limit,
        )
        context = builder.format_prompt_context(bundle)
        memories = []
        for section in bundle.sections:
            memories.extend(section.items)
        unified = bundle.unified or {}
        return {
            "context": context,
            "bundle": bundle.to_dict(),
            "memories": memories,
            "ranking": unified.get("ranking", {}),
            "score_breakdown": (unified.get("ranking") or {}).get("selected_items", []),
            "warnings": (unified.get("diagnostics") or {}).get("warnings", []),
        }
    except Exception as e:
        logger.error(f"Failed to get agent memory context: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/context-preview")
async def get_memory_context_preview(
    q: str = Query("", description="Task/query text for retrieval"),
    project_id: str | None = Query(None, description="Project ID for isolation"),
    user_id: str | None = Query(None, description="Optional user scope"),
    agent_type: str | None = Query(None, description="Agent type filter"),
    limit: int = Query(8, ge=1, le=12),
) -> dict[str, Any]:
    """Preview the exact memory context that would be injected into a prompt."""
    return await get_agent_memory_context(
        q=q,
        project_id=project_id,
        user_id=user_id,
        agent_type=agent_type,
        limit=limit,
    )


@router.get("/context")
async def get_unified_memory_context(
    q: str = Query("", description="Task/query text for retrieval"),
    project_id: str | None = Query(None, description="Project ID for isolation"),
    user_id: str | None = Query(None, description="Optional user scope"),
    agent_type: str | None = Query(None, description="Agent type filter"),
    limit: int = Query(8, ge=1, le=25),
) -> dict[str, Any]:
    """Return the unified structured memory bundle used by agents and planners."""
    try:
        from orchestrator.memory.unified import get_unified_memory_service

        bundle = get_unified_memory_service().build_bundle(
            query=q,
            project_id=project_id,
            user_id=user_id,
            agent_type=agent_type,
            limit=limit,
        )
        return bundle
    except Exception as e:
        logger.error(f"Failed to get unified memory context: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/injections")
async def list_memory_injections(
    project_id: str | None = Query(None, description="Project ID for isolation"),
    stage: str | None = Query(None, description="Optional stage filter"),
    actor_type: str | None = Query(None, description="Optional actor type filter"),
    outcome: str | None = Query(None, description="Optional outcome filter"),
    source_type: str | None = Query(None, description="Optional source type filter"),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """List recent memory injection telemetry records."""
    try:
        from orchestrator.api.models_db import MemoryInjectionEvent
        from orchestrator.memory.feedback import get_memory_feedback_service

        statement = select(MemoryInjectionEvent)
        if project_id:
            statement = statement.where(MemoryInjectionEvent.project_id == project_id)
        if stage:
            statement = statement.where(MemoryInjectionEvent.stage == stage)
        if actor_type:
            statement = statement.where(MemoryInjectionEvent.actor_type == actor_type)
        if outcome:
            statement = statement.where(MemoryInjectionEvent.outcome == outcome)
        if source_type:
            statement = statement.where(MemoryInjectionEvent.source_type == source_type)
        rows = session.exec(statement.order_by(MemoryInjectionEvent.created_at.desc()).limit(limit)).all()
        feedback_summary = get_memory_feedback_service(session).feedback_summary_for_injections([row.id for row in rows])
        return [
            {
                "id": row.id,
                "project_id": row.project_id,
                "actor_type": row.actor_type,
                "stage": row.stage,
                "source_type": row.source_type,
                "source_id": row.source_id,
                "query": row.query,
                "memory_ids": row.memory_ids,
                "context_preview": row.context_preview,
                "outcome": row.outcome,
                "extra_data": row.extra_data or {},
                "feedback": feedback_summary.get(row.id, {"total": 0, "positive": 0, "negative": 0}),
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Failed to list memory injections: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/injections/{injection_event_id}/feedback")
async def submit_memory_injection_feedback(
    injection_event_id: str,
    request: MemoryInjectionFeedbackRequest,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
) -> dict[str, Any]:
    """Apply feedback from one injection event to all injected memories."""
    try:
        from orchestrator.memory.feedback import get_memory_feedback_service

        return get_memory_feedback_service(session).apply_feedback_to_injection(
            injection_event_id,
            rating=request.rating,
            user_id=user.id if user else None,
            comment=request.comment,
            source="manual_dashboard",
        )
    except ValueError as e:
        raise HTTPException(status_code=400 if "Rating" in str(e) else 404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to submit memory injection feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/feedback")
async def get_memory_feedback(
    project_id: str | None = Query(None, description="Project ID for isolation"),
    memory_id: list[str] | None = Query(None, description="Memory IDs to inspect"),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Return aggregate feedback stats for selected memories."""
    try:
        from orchestrator.memory.feedback import get_memory_feedback_service

        stats = get_memory_feedback_service(session).get_memory_feedback_stats(
            project_id=project_id,
            memory_ids=memory_id or [],
        )
        return {
            "items": {
                key: {
                    "positive_feedback_count": value.positive_feedback_count,
                    "negative_feedback_count": value.negative_feedback_count,
                    "feedback_score": value.feedback_score,
                    "last_feedback_at": value.last_feedback_at.isoformat() if value.last_feedback_at else None,
                }
                for key, value in stats.items()
            }
        }
    except Exception as e:
        logger.error(f"Failed to get memory feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/agent", response_model=AgentMemoryResponse)
async def create_agent_memory(request: AgentMemoryCreateRequest) -> AgentMemoryResponse:
    """Create a curated agent working memory."""
    try:
        memory = get_agent_memory_service().create_memory(
            kind=request.kind,
            content=request.content,
            project_id=request.project_id,
            user_id=request.user_id,
            memory_type=request.memory_type,
            scope=request.scope,
            summary=request.summary,
            tags=request.tags,
            confidence=request.confidence,
            importance=request.importance,
            source_type=request.source_type,
            source_id=request.source_id,
            agent_type=request.agent_type,
            valid_from=request.valid_from,
            valid_until=request.valid_until,
            supersedes_id=request.supersedes_id,
            review_required=request.review_required,
            last_verified_at=request.last_verified_at,
            extra_data=request.extra_data,
        )
        if memory is None:
            raise HTTPException(status_code=400, detail="Memory was empty, disabled, or fully redacted")
        return _agent_memory_response(memory)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create agent memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/agent/{memory_id}", response_model=AgentMemoryResponse)
async def update_agent_memory(
    memory_id: str,
    request: AgentMemoryUpdateRequest,
    project_id: str | None = Query(None, description="Project ID guard"),
) -> AgentMemoryResponse:
    """Update curated agent memory metadata or content."""
    try:
        updates = request.model_dump(exclude_unset=True)
        memory = get_agent_memory_service().update_memory(memory_id, project_id=project_id, **updates)
        if not memory:
            raise HTTPException(status_code=404, detail="Memory not found")
        return _agent_memory_response(memory)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update agent memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/agent/consolidate", response_model=list[AgentMemoryResponse])
async def consolidate_agent_memory(request: AgentMemoryConsolidateRequest) -> list[AgentMemoryResponse]:
    """Extract and store high-signal memories from a larger text block."""
    try:
        from orchestrator.memory.consolidation import MemoryConsolidationService

        result = await MemoryConsolidationService(get_agent_memory_service()).consolidate_text(
            request.text,
            project_id=request.project_id,
            user_id=request.user_id,
            source_type=request.source_type,
            source_id=request.source_id,
            agent_type=request.agent_type,
            use_llm=request.use_llm,
            review_required=request.review_required,
        )
        return [_agent_memory_response(memory) for memory in result.stored]
    except Exception as e:
        logger.error(f"Failed to consolidate agent memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/agent/verify-stale")
async def verify_stale_agent_memories(request: StaleMemoryVerifyRequest) -> dict[str, Any]:
    """Run a stale-memory verification pass for one project or all projects."""
    try:
        result = get_agent_memory_service().verify_stale(
            project_id=request.project_id,
            older_than_days=request.older_than_days,
            limit=request.limit,
        )
        memories = result.pop("memories", [])
        return {
            **result,
            "memories": [_agent_memory_response(memory).model_dump() for memory in memories],
        }
    except Exception as e:
        logger.error(f"Failed to verify stale memories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/agent/{memory_id}/approve", response_model=AgentMemoryResponse)
async def approve_agent_memory(
    memory_id: str,
    project_id: str | None = Query(None, description="Project ID guard"),
) -> AgentMemoryResponse:
    """Approve a review-required memory for future prompt injection."""
    try:
        memory = get_agent_memory_service().approve(memory_id, project_id=project_id)
        if not memory:
            raise HTTPException(status_code=404, detail="Memory not found")
        return _agent_memory_response(memory)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to approve agent memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/agent/{memory_id}/verify", response_model=AgentMemoryResponse)
async def verify_agent_memory(
    memory_id: str,
    project_id: str | None = Query(None, description="Project ID guard"),
) -> AgentMemoryResponse:
    """Mark a memory as verified without changing its content."""
    try:
        memory = get_agent_memory_service().verify(memory_id, project_id=project_id)
        if not memory:
            raise HTTPException(status_code=404, detail="Memory not found")
        return _agent_memory_response(memory)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to verify agent memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/agent/{memory_id}/archive", response_model=AgentMemoryResponse)
async def archive_agent_memory(
    memory_id: str,
    project_id: str | None = Query(None, description="Project ID guard"),
) -> AgentMemoryResponse:
    """Archive an agent memory without deleting its audit trail."""
    try:
        memory = get_agent_memory_service().archive(memory_id, project_id=project_id)
        if not memory:
            raise HTTPException(status_code=404, detail="Memory not found")
        return _agent_memory_response(memory)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to archive agent memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/agent/{memory_id}")
async def delete_agent_memory(
    memory_id: str,
    project_id: str | None = Query(None, description="Project ID guard"),
) -> dict[str, bool]:
    """Delete an agent memory and its vector index document."""
    try:
        deleted = get_agent_memory_service().delete(memory_id, project_id=project_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete agent memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/session-recall/recent", response_model=list[SessionRecallResult])
async def browse_session_recall(
    project_id: str | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
) -> list[SessionRecallResult]:
    """Browse recent assistant conversations as on-demand recall."""
    statement = select(ChatConversation).order_by(ChatConversation.updated_at.desc()).limit(limit)
    if project_id:
        statement = statement.where(ChatConversation.project_id == project_id)
    if user:
        statement = statement.where(or_(ChatConversation.user_id == user.id, ChatConversation.user_id.is_(None)))
    conversations = session.exec(statement).all()
    return [
        SessionRecallResult(
            conversation_id=conversation.id,
            title=conversation.title,
            project_id=conversation.project_id,
            updated_at=conversation.updated_at.isoformat(),
            snippet=conversation.summary,
        )
        for conversation in conversations
    ]


@router.get("/session-recall/search", response_model=list[SessionRecallResult])
async def search_session_recall(
    q: str = Query(..., min_length=2),
    project_id: str | None = Query(None),
    limit: int = Query(5, ge=1, le=20),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
) -> list[SessionRecallResult]:
    """Search saved chat messages and return one anchored hit per conversation."""
    conversation_filter = select(ChatConversation.id)
    if project_id:
        conversation_filter = conversation_filter.where(ChatConversation.project_id == project_id)
    if user:
        conversation_filter = conversation_filter.where(
            or_(ChatConversation.user_id == user.id, ChatConversation.user_id.is_(None))
        )
    allowed_ids = session.exec(conversation_filter).all()
    if not allowed_ids:
        return []

    matches = session.exec(
        select(ChatMessage)
        .where(ChatMessage.conversation_id.in_(allowed_ids))
        .where(ChatMessage.content.ilike(f"%{q}%"))
        .where(ChatMessage.role.in_(["user", "assistant"]))
        .order_by(ChatMessage.created_at.desc())
        .limit(limit * 5)
    ).all()

    seen: set[str] = set()
    results: list[SessionRecallResult] = []
    for message in matches:
        if message.conversation_id in seen:
            continue
        conversation = session.get(ChatConversation, message.conversation_id)
        if not conversation:
            continue
        seen.add(message.conversation_id)
        results.append(
            SessionRecallResult(
                conversation_id=conversation.id,
                title=conversation.title,
                project_id=conversation.project_id,
                updated_at=conversation.updated_at.isoformat(),
                match_message_id=message.id,
                snippet=_snippet(message.content or "", q),
                messages=[_shape_recall_message(message, anchor_id=message.id)],
            )
        )
        if len(results) >= limit:
            break
    return results


@router.get("/session-recall/window", response_model=SessionRecallResult)
async def get_session_recall_window(
    conversation_id: str = Query(...),
    around_message_id: int = Query(...),
    window: int = Query(5, ge=1, le=20),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
) -> SessionRecallResult:
    """Return an anchored message window plus start/end bookends for a conversation."""
    conversation = _conversation_guard(session, conversation_id, user)
    anchor = session.get(ChatMessage, around_message_id)
    if not anchor or anchor.conversation_id != conversation_id:
        raise HTTPException(status_code=404, detail="Message not found in conversation")

    before_rows = session.exec(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .where(ChatMessage.id <= around_message_id)
        .order_by(ChatMessage.id.desc())
        .limit(window + 1)
    ).all()
    after_rows = session.exec(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .where(ChatMessage.id > around_message_id)
        .order_by(ChatMessage.id.asc())
        .limit(window)
    ).all()
    window_rows = list(reversed(before_rows)) + list(after_rows)
    messages_before = max(0, len(before_rows) - 1)
    messages_after = len(after_rows)

    first_window_id = window_rows[0].id if window_rows else around_message_id
    last_window_id = window_rows[-1].id if window_rows else around_message_id
    bookend_start = session.exec(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .where(ChatMessage.id < first_window_id)
        .where(ChatMessage.role.in_(["user", "assistant"]))
        .where(ChatMessage.content != "")
        .order_by(ChatMessage.id.asc())
        .limit(3)
    ).all()
    bookend_end_desc = session.exec(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .where(ChatMessage.id > last_window_id)
        .where(ChatMessage.role.in_(["user", "assistant"]))
        .where(ChatMessage.content != "")
        .order_by(ChatMessage.id.desc())
        .limit(3)
    ).all()

    return SessionRecallResult(
        conversation_id=conversation.id,
        title=conversation.title,
        project_id=conversation.project_id,
        updated_at=conversation.updated_at.isoformat(),
        match_message_id=around_message_id,
        messages=[_shape_recall_message(message, anchor_id=around_message_id) for message in window_rows],
        bookend_start=[_shape_recall_message(message) for message in bookend_start],
        bookend_end=[_shape_recall_message(message) for message in reversed(bookend_end_desc)],
        messages_before=messages_before,
        messages_after=messages_after,
    )


@router.get("/health")
async def get_memory_health(project_id: str | None = Query(None)) -> dict[str, Any]:
    """Report memory system health and embedding mode."""
    try:
        manager = get_memory_manager(project_id or "default")
        embedding_client = manager.vector_store.embedding_client
        agent_memories = get_agent_memory_service().search(project_id=project_id, limit=1, min_confidence=0.0)
        return {
            "memory_enabled": get_config().memory_enabled,
            "embedding_model": getattr(embedding_client, "model", "unknown"),
            "embedding_mode": "openai" if getattr(embedding_client, "api_key", None) else "local",
            "project_id": project_id or "default",
            "patterns": len(manager.vector_store.get_all_patterns()),
            "graph": manager.graph_store.get_graph_stats(),
            "agent_memory_available": True,
            "agent_memory_sample_count": len(agent_memories),
        }
    except Exception as e:
        logger.error(f"Failed to get memory health: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/diagnostics")
async def get_memory_diagnostics(
    project_id: str | None = Query(None, description="Project ID for isolation"),
    stale_days: int = Query(30, ge=1, le=3650, description="Age threshold for stale-memory warnings"),
) -> dict[str, Any]:
    """Report operational memory health, gaps, and recommended actions."""
    try:
        from orchestrator.memory.diagnostics import get_memory_diagnostics_service

        return get_memory_diagnostics_service().run(project_id=project_id, stale_days=stale_days)
    except Exception as e:
        logger.error(f"Failed to get memory diagnostics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/effectiveness")
async def get_memory_effectiveness(
    project_id: str | None = Query(None, description="Project ID for isolation"),
    days: int = Query(30, ge=1, le=3650, description="Lookback window"),
    stage: str | None = Query(None, description="Optional memory injection stage"),
) -> dict[str, Any]:
    """Report whether injected memory is associated with successful outcomes."""
    try:
        from orchestrator.memory.effectiveness import get_memory_effectiveness_service

        return get_memory_effectiveness_service().summarize(project_id=project_id, days=days, stage=stage)
    except Exception as e:
        logger.error(f"Failed to get memory effectiveness: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/repair")
async def repair_memory(request: MemoryRepairRequest) -> dict[str, Any]:
    """Run conservative memory repair actions."""
    try:
        from orchestrator.memory.effectiveness import get_memory_repair_service

        return get_memory_repair_service().run(
            project_id=request.project_id,
            action=request.action,
            dry_run=request.dry_run,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to repair memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/browser", response_model=BrowserMemoryBundleResponse)
async def get_browser_memory(
    project_id: str = Query(default="default"),
    query: str = Query(default=""),
    limit: int = Query(default=10, ge=1, le=50),
) -> BrowserMemoryBundleResponse:
    """Inspect durable browser exploration memory for a project."""
    try:
        bundle = get_exploration_memory_service(project_id=project_id).get_memory_bundle(query=query, limit=limit)
        return BrowserMemoryBundleResponse(project_id=project_id, **bundle)
    except Exception as e:
        logger.error(f"Failed to get browser memory: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/browser/frontier")
async def get_browser_frontier(
    project_id: str = Query(default="default"),
    query: str = Query(default=""),
    limit: int = Query(default=10, ge=1, le=50),
    risk_max: str = Query(default="medium"),
    url_scope: str | None = Query(default=None),
    include_leased: bool = Query(default=False),
) -> dict[str, Any]:
    """Inspect ranked browser frontier work for 24/7 exploration agents."""
    try:
        frontier = get_exploration_memory_service(project_id=project_id).get_frontier_work(
            query=query,
            limit=limit,
            risk_max=risk_max,
            url_scope=url_scope,
            include_leased=include_leased,
        )
        return {"project_id": project_id, "frontier": frontier}
    except Exception as e:
        logger.error(f"Failed to get browser frontier: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/browser/frontier/claim")
async def claim_browser_frontier(request: BrowserFrontierClaimRequest) -> dict[str, Any]:
    """Lease ranked frontier items for an exploration worker."""
    try:
        claimed = get_exploration_memory_service(project_id=request.project_id).claim_frontier_items(
            worker_id=request.worker_id,
            limit=request.limit,
            lease_seconds=request.lease_seconds,
            query=request.query,
            risk_max=request.risk_max,
            url_scope=request.url_scope,
        )
        return {"project_id": request.project_id, "worker_id": request.worker_id, "frontier": claimed}
    except Exception as e:
        logger.error(f"Failed to claim browser frontier: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/browser/frontier/{frontier_id}/complete")
async def complete_browser_frontier(frontier_id: str, request: BrowserFrontierCompleteRequest) -> dict[str, Any]:
    """Mark a browser frontier item completed."""
    try:
        item = get_exploration_memory_service(project_id=request.project_id).complete_frontier_item(
            frontier_id,
            transition_id=request.transition_id,
            outcome=request.outcome,
        )
        if not item:
            raise HTTPException(status_code=404, detail="Frontier item not found")
        return {"project_id": request.project_id, "frontier": item}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to complete browser frontier item: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/browser/frontier/{frontier_id}/fail")
async def fail_browser_frontier(frontier_id: str, request: BrowserFrontierFailRequest) -> dict[str, Any]:
    """Mark a browser frontier attempt failed and optionally retry it later."""
    try:
        item = get_exploration_memory_service(project_id=request.project_id).fail_frontier_item(
            frontier_id,
            error=request.error,
            retry_after_seconds=request.retry_after_seconds,
            max_attempts=request.max_attempts,
        )
        if not item:
            raise HTTPException(status_code=404, detail="Frontier item not found")
        return {"project_id": request.project_id, "frontier": item}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fail browser frontier item: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch("/browser/frontier/{frontier_id}/skip")
async def skip_browser_frontier(frontier_id: str, request: BrowserFrontierSkipRequest) -> dict[str, Any]:
    """Mark a browser frontier item skipped because it is stale, risky, or irrelevant."""
    try:
        item = get_exploration_memory_service(project_id=request.project_id).skip_frontier_item(
            frontier_id,
            reason=request.reason,
        )
        if not item:
            raise HTTPException(status_code=404, detail="Frontier item not found")
        return {"project_id": request.project_id, "frontier": item}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to skip browser frontier item: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/projects")
async def list_projects() -> dict[str, Any]:
    """
    List all projects that have data in memory.

    Returns a list of project_ids that have stored patterns.
    """
    try:
        # Use the shared ChromaDB client from vector_store
        from pathlib import Path

        from orchestrator.memory.vector_store import _get_chroma_client

        chroma_path = Path(get_config().persist_directory)

        client = _get_chroma_client(str(chroma_path))

        # Get all collections
        collections = client.list_collections()

        projects = []
        seen_names = set()

        for collection in collections:
            # Extract project_id from collection name
            # Collection names are like: test_automation_{project_id}_test_patterns
            name = collection.name
            if name.startswith("test_automation_") and name.endswith("_test_patterns"):
                # Extract the middle part as project_id
                project_id = name.replace("test_automation_", "").replace("_test_patterns", "")

                # Only add unique project_ids
                if project_id and project_id not in seen_names:
                    count = collection.count()
                    projects.append(
                        {
                            "id": project_id,
                            "name": project_id,  # Use project_id as display name
                            "pattern_count": count,
                        }
                    )
                    seen_names.add(project_id)

        # Sort by pattern count (descending) then by name
        projects.sort(key=lambda p: (-p["pattern_count"], p["name"]))

        return {"projects": projects, "total_projects": len(projects)}

    except Exception as e:
        logger.error(f"Failed to list memory projects: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
