"""
Memory and Coverage API endpoints

Provides access to:
- Test patterns stored in memory
- Coverage statistics
- Similar test suggestions
- Coverage gaps
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

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


class SelectorInfo(BaseModel):
    """Selector information"""

    selector_type: str
    selector_value: str
    success_rate: float
    avg_duration: float
    usage_count: int


# ========= Endpoints =========

from orchestrator.memory import get_memory_manager

# ========= Endpoints =========


def _get_manager(project_id: str | None = None):
    """Get memory manager instance with proper context"""
    import os

    # Ensure API key is set if missing (required for embeddings)
    if not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "dummy-key-for-api"

    return get_memory_manager(project_id=project_id)


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


@router.get("/projects")
async def list_projects() -> dict[str, Any]:
    """
    List all projects that have data in memory.

    Returns a list of project_ids that have stored patterns.
    """
    try:
        import os

        os.environ.setdefault("OPENAI_API_KEY", "dummy-key-for-api")

        # Use the shared ChromaDB client from vector_store
        from pathlib import Path

        from orchestrator.memory.vector_store import _get_chroma_client

        project_root = Path(__file__).parent.parent.parent
        chroma_path = project_root / "data" / "chromadb"

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
