"""
Requirements API Router

Provides CRUD endpoints for requirements management and
integration with exploration-based requirements generation.
"""

import logging
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/requirements", tags=["requirements"])

# ========== In-Memory Job Tracking ==========
_req_gen_jobs: dict[str, dict] = {}
_bulk_gen_jobs: dict[str, dict] = {}
MAX_TRACKED_JOBS = 50


def _cleanup_old_req_jobs():
    """Remove completed/failed jobs older than 1 hour."""
    now = time.time()
    for job_store in (_req_gen_jobs, _bulk_gen_jobs):
        to_remove = []
        for job_id, job in job_store.items():
            if job["status"] in ("completed", "failed"):
                completed_at = job.get("completed_at", 0)
                if now - completed_at > 3600:
                    to_remove.append(job_id)
        for job_id in to_remove:
            del job_store[job_id]
        if len(job_store) > MAX_TRACKED_JOBS:
            evictable = sorted(
                [(jid, j) for jid, j in job_store.items() if j["status"] != "running"],
                key=lambda x: x[1].get("started_at", 0),
            )
            for job_id, _ in evictable[: len(job_store) - MAX_TRACKED_JOBS]:
                del job_store[job_id]


# ========== Pydantic Models ==========


class RequirementCreate(BaseModel):
    """Request to create a requirement."""

    title: str = Field(..., min_length=1)
    description: str | None = None
    category: str = Field(default="other")
    priority: str = Field(default="medium")
    acceptance_criteria: list[str] = Field(default_factory=list)


class RequirementUpdate(BaseModel):
    """Request to update a requirement."""

    title: str | None = None
    description: str | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    acceptance_criteria: list[str] | None = None


class RequirementResponse(BaseModel):
    """Response model for a requirement."""

    id: int
    req_code: str
    title: str
    description: str | None
    category: str
    priority: str
    status: str
    acceptance_criteria: list[str]
    source_session_id: str | None
    created_at: datetime
    updated_at: datetime


class PaginatedRequirementsResponse(BaseModel):
    """Paginated response for requirements list."""

    items: list[RequirementResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


class GenerateRequirementsRequest(BaseModel):
    """Request to generate requirements from exploration."""

    exploration_session_id: str


class GenerateRequirementsResponse(BaseModel):
    """Response from requirements generation."""

    total_requirements: int
    by_category: dict
    by_priority: dict
    requirements: list[RequirementResponse]


# ========== Deduplication Models ==========


class CheckDuplicateRequest(BaseModel):
    """Request to check for duplicate requirements."""

    title: str = Field(..., min_length=1)
    description: str | None = None


class DuplicateMatchResponse(BaseModel):
    """A potential duplicate match."""

    requirement_id: int
    req_code: str
    title: str
    description: str | None
    acceptance_criteria: list[str]
    similarity: float


class CheckDuplicateResponse(BaseModel):
    """Response from duplicate check."""

    has_exact_match: bool
    exact_match: RequirementResponse | None = None
    near_matches: list[DuplicateMatchResponse]
    recommendation: str  # "create", "update_existing", "review_matches"


class DuplicateGroupResponse(BaseModel):
    """A group of duplicate requirements."""

    canonical_id: int
    canonical_code: str
    canonical_title: str
    duplicates: list[DuplicateMatchResponse]
    merged_criteria: list[str]


class FindDuplicatesResponse(BaseModel):
    """Response from finding duplicate groups."""

    groups: list[DuplicateGroupResponse]
    total_duplicates: int
    mode: str  # "semantic" (AI embeddings) or "exact" (title matching fallback)


class MergeRequest(BaseModel):
    """Request to merge duplicate requirements."""

    canonical_id: int
    duplicate_ids: list[int]
    merge_acceptance_criteria: bool = True


class MergeResponse(BaseModel):
    """Response from merging requirements."""

    canonical: RequirementResponse
    merged_count: int
    deleted_ids: list[int]


# ========== Spec Generation Models ==========


class GenerateSpecFromRequirementRequest(BaseModel):
    """Request to generate spec from a requirement."""

    target_url: str = Field(..., description="URL of the application to test")
    login_url: str | None = Field(None, description="URL for login page if auth required")
    credentials: dict[str, str] | None = Field(None, description="Credentials with username/password keys")
    force_regenerate: bool = Field(False, description="Force regeneration even if spec exists")


class GenerateSpecFromRequirementResponse(BaseModel):
    """Response from spec generation."""

    status: str
    spec_path: str
    spec_name: str
    spec_content: str
    requirement_id: int
    requirement_code: str
    rtm_entry_id: int
    generated_at: str
    cached: bool = False


class SpecStatusResponse(BaseModel):
    """Response for spec status check."""

    has_spec: bool
    spec_path: str | None = None
    spec_name: str | None = None
    rtm_entry_id: int | None = None
    generated_at: str | None = None


# ========== API Endpoints ==========

# NOTE: Specific GET routes must be defined BEFORE the parameterized /{req_id} route
# to avoid FastAPI matching "duplicates", "stats", etc. as req_id values.


@router.get("", response_model=PaginatedRequirementsResponse)
async def list_requirements(
    project_id: str = Query(default="default"),
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """
    List requirements for a project with pagination.

    Args:
        project_id: Project ID to filter by
        category: Filter by category
        status: Filter by status
        priority: Filter by priority
        search: Search term for title (case-insensitive)
        limit: Maximum number of items to return (1-200, default 50)
        offset: Number of items to skip (default 0)

    Returns:
        Paginated response with items, total count, and pagination metadata
    """
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    requirements, total = store.get_requirements_paginated(
        category=category, status=status, priority=priority, search=search, limit=limit, offset=offset
    )

    items = [
        RequirementResponse(
            id=r.id,
            req_code=r.req_code,
            title=r.title,
            description=r.description,
            category=r.category,
            priority=r.priority,
            status=r.status,
            acceptance_criteria=r.acceptance_criteria,
            source_session_id=r.source_session_id,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in requirements
    ]

    return PaginatedRequirementsResponse(
        items=items, total=total, limit=limit, offset=offset, has_more=(offset + len(items)) < total
    )


@router.get("/duplicates", response_model=FindDuplicatesResponse)
async def find_duplicates(
    project_id: str = Query(default="default"), similarity_threshold: float = Query(default=0.85, ge=0.5, le=1.0)
):
    """
    Find groups of duplicate requirements using semantic similarity.

    Returns groups of requirements that appear to be duplicates,
    with a suggested canonical requirement and merged acceptance criteria.
    """
    from memory.exploration_store import get_exploration_store
    from services.requirement_dedup import get_deduplication_service

    store = get_exploration_store(project_id=project_id)
    dedup_service = get_deduplication_service(project_id=project_id)

    # Get all requirements
    requirements = store.get_requirements()
    req_dicts = [
        {
            "id": r.id,
            "req_code": r.req_code,
            "title": r.title,
            "description": r.description,
            "acceptance_criteria": r.acceptance_criteria,
            "title_embedding": r.title_embedding,
        }
        for r in requirements
    ]

    # Check if embeddings are available
    embedding_client = dedup_service._get_embedding_client()
    mode = "semantic" if embedding_client else "exact"

    # Find duplicate groups
    groups = dedup_service.find_duplicate_groups(requirements=req_dicts, threshold=similarity_threshold)

    # Build response
    group_responses = []
    total_duplicates = 0

    for group in groups:
        dup_responses = [
            DuplicateMatchResponse(
                requirement_id=d.requirement_id,
                req_code=d.req_code,
                title=d.title,
                description=d.description,
                acceptance_criteria=d.acceptance_criteria,
                similarity=round(d.similarity, 3),
            )
            for d in group.duplicates
        ]

        total_duplicates += len(group.duplicates)

        group_responses.append(
            DuplicateGroupResponse(
                canonical_id=group.canonical_id,
                canonical_code=group.canonical_code,
                canonical_title=group.canonical_title,
                duplicates=dup_responses,
                merged_criteria=group.merged_criteria,
            )
        )

    return FindDuplicatesResponse(groups=group_responses, total_duplicates=total_duplicates, mode=mode)


@router.get("/categories/list")
async def list_categories(project_id: str = Query(default="default")):
    """List all requirement categories in use."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    requirements = store.get_requirements()
    categories = {}

    for r in requirements:
        if r.category not in categories:
            categories[r.category] = 0
        categories[r.category] += 1

    return {"categories": [{"name": cat, "count": count} for cat, count in sorted(categories.items())]}


@router.get("/stats")
async def get_requirements_stats(project_id: str = Query(default="default")):
    """Get requirements statistics."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    requirements = store.get_requirements()

    by_category = {}
    by_priority = {}
    by_status = {}

    for r in requirements:
        by_category[r.category] = by_category.get(r.category, 0) + 1
        by_priority[r.priority] = by_priority.get(r.priority, 0) + 1
        by_status[r.status] = by_status.get(r.status, 0) + 1

    return {"total": len(requirements), "by_category": by_category, "by_priority": by_priority, "by_status": by_status}


# ========== Health Check Endpoint ==========


class RequirementsHealthResponse(BaseModel):
    """Health check response for requirements generation."""

    status: str
    anthropic_token_set: bool
    openai_token_set: bool
    database_connected: bool
    claude_sdk_available: bool
    errors: list[str] = Field(default_factory=list)


@router.get("/health", response_model=RequirementsHealthResponse)
async def check_requirements_health():
    """
    Check health of requirements generation system.

    Verifies:
    - ANTHROPIC_AUTH_TOKEN is set
    - OPENAI_API_KEY is set (for embeddings)
    - Database is connected
    - Claude SDK can be imported
    """
    import os

    errors = []

    # Check Anthropic token
    anthropic_token_set = bool(os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if not anthropic_token_set:
        errors.append("ANTHROPIC_AUTH_TOKEN not set - AI generation will fail")

    # Check OpenAI key (for embeddings)
    openai_token_set = bool(os.environ.get("OPENAI_API_KEY"))
    if not openai_token_set:
        errors.append("OPENAI_API_KEY not set - semantic deduplication will be disabled")

    # Check database connectivity
    database_connected = False
    try:
        from sqlalchemy import text

        from api.db import get_session

        with next(get_session()) as db:
            db.execute(text("SELECT 1"))
            database_connected = True
    except Exception as e:
        errors.append(f"Database connection failed: {str(e)}")

    # Check Claude SDK
    claude_sdk_available = False
    try:
        import claude_agent_sdk  # noqa: F401

        claude_sdk_available = True
    except ImportError as e:
        errors.append(f"Claude SDK import failed: {str(e)}")

    # Determine overall status
    if anthropic_token_set and database_connected and claude_sdk_available:
        status = "healthy"
    elif not anthropic_token_set or not claude_sdk_available:
        status = "unhealthy"
    else:
        status = "degraded"

    return RequirementsHealthResponse(
        status=status,
        anthropic_token_set=anthropic_token_set,
        openai_token_set=openai_token_set,
        database_connected=database_connected,
        claude_sdk_available=claude_sdk_available,
        errors=errors,
    )


# Parameterized route must come AFTER specific routes
@router.get("/{req_id}", response_model=RequirementResponse)
async def get_requirement(req_id: int, project_id: str = Query(default="default")):
    """Get a specific requirement by ID."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    requirement = store.get_requirement(req_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    return RequirementResponse(
        id=requirement.id,
        req_code=requirement.req_code,
        title=requirement.title,
        description=requirement.description,
        category=requirement.category,
        priority=requirement.priority,
        status=requirement.status,
        acceptance_criteria=requirement.acceptance_criteria,
        source_session_id=requirement.source_session_id,
        created_at=requirement.created_at,
        updated_at=requirement.updated_at,
    )


@router.post("", response_model=RequirementResponse)
async def create_requirement(request: RequirementCreate, project_id: str = Query(default="default")):
    """Create a new requirement manually."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    req_code = store.get_next_requirement_code()

    requirement = store.store_requirement(
        req_code=req_code,
        title=request.title,
        description=request.description,
        category=request.category,
        priority=request.priority,
        acceptance_criteria=request.acceptance_criteria,
    )

    return RequirementResponse(
        id=requirement.id,
        req_code=requirement.req_code,
        title=requirement.title,
        description=requirement.description,
        category=requirement.category,
        priority=requirement.priority,
        status=requirement.status,
        acceptance_criteria=requirement.acceptance_criteria,
        source_session_id=requirement.source_session_id,
        created_at=requirement.created_at,
        updated_at=requirement.updated_at,
    )


class BulkRequirementCreate(BaseModel):
    """Request to bulk create requirements."""

    items: list[RequirementCreate] = Field(..., min_length=1, max_length=500)


class BulkCreateResponse(BaseModel):
    """Response from bulk requirement creation."""

    created: int
    requirements: list[RequirementResponse]


@router.post("/bulk", response_model=BulkCreateResponse)
async def bulk_create_requirements(request: BulkRequirementCreate, project_id: str = Query(default="default")):
    """Bulk create multiple requirements in a single request."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    created_reqs = []
    for item in request.items:
        req_code = store.get_next_requirement_code()
        requirement = store.store_requirement(
            req_code=req_code,
            title=item.title,
            description=item.description,
            category=item.category,
            priority=item.priority,
            acceptance_criteria=item.acceptance_criteria,
        )
        created_reqs.append(
            RequirementResponse(
                id=requirement.id,
                req_code=requirement.req_code,
                title=requirement.title,
                description=requirement.description,
                category=requirement.category,
                priority=requirement.priority,
                status=requirement.status,
                acceptance_criteria=requirement.acceptance_criteria,
                source_session_id=requirement.source_session_id,
                created_at=requirement.created_at,
                updated_at=requirement.updated_at,
            )
        )

    return BulkCreateResponse(created=len(created_reqs), requirements=created_reqs)


@router.put("/{req_id}", response_model=RequirementResponse)
async def update_requirement(req_id: int, request: RequirementUpdate, project_id: str = Query(default="default")):
    """Update an existing requirement."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    # Build update dict from non-None fields
    updates = {k: v for k, v in request.dict().items() if v is not None}

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    requirement = store.update_requirement(req_id, **updates)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    return RequirementResponse(
        id=requirement.id,
        req_code=requirement.req_code,
        title=requirement.title,
        description=requirement.description,
        category=requirement.category,
        priority=requirement.priority,
        status=requirement.status,
        acceptance_criteria=requirement.acceptance_criteria,
        source_session_id=requirement.source_session_id,
        created_at=requirement.created_at,
        updated_at=requirement.updated_at,
    )


@router.delete("/{req_id}")
async def delete_requirement(req_id: int, project_id: str = Query(default="default")):
    """Delete a requirement."""
    from sqlmodel import select

    from api.db import get_session
    from api.models_db import Requirement, RequirementSource, RtmEntry

    with next(get_session()) as db:
        requirement = db.get(Requirement, req_id)
        if not requirement:
            raise HTTPException(status_code=404, detail="Requirement not found")

        # Delete related RTM entries
        rtm_entries = db.exec(select(RtmEntry).where(RtmEntry.requirement_id == req_id)).all()
        for entry in rtm_entries:
            db.delete(entry)

        # Delete related sources
        sources = db.exec(select(RequirementSource).where(RequirementSource.requirement_id == req_id)).all()
        for source in sources:
            db.delete(source)

        # Flush source deletes before requirement delete to avoid FK violation
        db.flush()

        # Delete the requirement
        db.delete(requirement)
        db.commit()

    return {"status": "deleted", "requirement_id": req_id}


async def _run_requirements_generation(job_id: str, project_id: str, session_id: str):
    """Background task for requirements generation."""
    import traceback

    from workflows.requirements_generator import RequirementsGenerator

    _req_gen_jobs[job_id]["status"] = "running"
    _req_gen_jobs[job_id]["started_at"] = time.time()

    try:
        generator = RequirementsGenerator(project_id=project_id)
        result = await generator.generate_from_exploration(exploration_session_id=session_id)

        logger.info(f"Requirements generation completed: {result.total_requirements} requirements generated")

        # Build response data
        from memory.exploration_store import get_exploration_store

        store = get_exploration_store(project_id=project_id)
        requirements = store.get_requirements()

        _req_gen_jobs[job_id]["status"] = "completed"
        _req_gen_jobs[job_id]["completed_at"] = time.time()
        _req_gen_jobs[job_id]["result"] = {
            "total_requirements": result.total_requirements,
            "by_category": result.by_category,
            "by_priority": result.by_priority,
            "requirements": [
                {
                    "id": r.id,
                    "req_code": r.req_code,
                    "title": r.title,
                    "description": r.description,
                    "category": r.category,
                    "priority": r.priority,
                    "status": r.status,
                    "acceptance_criteria": r.acceptance_criteria,
                    "source_session_id": r.source_session_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in requirements
            ],
        }
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        logger.error(f"Requirements generation failed: {error_type}: {error_msg}")
        logger.error(f"Stack trace:\n{traceback.format_exc()}")
        _req_gen_jobs[job_id]["status"] = "failed"
        _req_gen_jobs[job_id]["completed_at"] = time.time()
        _req_gen_jobs[job_id]["error"] = f"{error_type}: {error_msg}"


@router.post("/generate")
async def generate_requirements(
    request: GenerateRequirementsRequest, background_tasks: BackgroundTasks, project_id: str = Query(default="default")
):
    """
    Generate requirements from an exploration session (async).

    Returns a job_id immediately. Poll GET /requirements/generate-jobs/{job_id}
    for status and results.
    """
    _cleanup_old_req_jobs()

    job_id = str(uuid.uuid4())
    _req_gen_jobs[job_id] = {
        "status": "queued",
        "project_id": project_id,
        "session_id": request.exploration_session_id,
        "created_at": time.time(),
    }

    logger.info(
        f"Requirements generation queued: job_id={job_id}, session_id={request.exploration_session_id}, project_id={project_id}"
    )

    background_tasks.add_task(_run_requirements_generation, job_id, project_id, request.exploration_session_id)

    return {"job_id": job_id, "status": "queued"}


@router.get("/generate-jobs/{job_id}")
async def get_generate_job_status(job_id: str):
    """Poll requirements generation job status."""
    job = _req_gen_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    response = {
        "job_id": job_id,
        "status": job["status"],
        "project_id": job.get("project_id"),
        "session_id": job.get("session_id"),
    }

    if job["status"] == "completed":
        response["result"] = job.get("result")
    elif job["status"] == "failed":
        response["error"] = job.get("error")

    return response


# ========== Bulk Spec Generation ==========


class BulkGenerateSpecsRequest(BaseModel):
    """Request to bulk-generate specs for uncovered requirements."""

    target_url: str = Field(..., description="URL of the application to test")
    login_url: str | None = Field(None, description="URL for login page if auth required")
    credentials: dict[str, str] | None = Field(None, description="Credentials with username/password keys")


class BulkGenerateSpecsResultItem(BaseModel):
    """Result for a single requirement in bulk generation."""

    req_code: str
    req_id: int
    status: str  # "generated", "failed", "skipped"
    spec_name: str | None = None
    error: str | None = None


class BulkGenerateSpecsJobResponse(BaseModel):
    """Response for bulk generation job status."""

    job_id: str
    status: str
    total: int
    completed: int
    failed: int
    results: list[BulkGenerateSpecsResultItem]
    error: str | None = None


async def _run_bulk_spec_generation(
    job_id: str, project_id: str, target_url: str, login_url: str | None, credentials: dict[str, str] | None
):
    """Background task for bulk spec generation."""
    import traceback

    from sqlmodel import select

    from api.db import get_session
    from api.models_db import RtmEntry
    from memory.exploration_store import get_exploration_store

    _bulk_gen_jobs[job_id]["status"] = "running"
    _bulk_gen_jobs[job_id]["started_at"] = time.time()

    try:
        store = get_exploration_store(project_id=project_id)

        # Get all requirements for the project
        all_requirements = store.get_requirements()

        # Get all RTM entries to find covered requirements
        with next(get_session()) as db:
            rtm_query = select(RtmEntry).where(RtmEntry.project_id == project_id)
            rtm_entries = db.exec(rtm_query).all()
            covered_req_ids = {entry.requirement_id for entry in rtm_entries}

        # Find uncovered requirements
        uncovered = [r for r in all_requirements if r.id not in covered_req_ids]

        _bulk_gen_jobs[job_id]["total"] = len(uncovered)

        if not uncovered:
            _bulk_gen_jobs[job_id]["status"] = "completed"
            _bulk_gen_jobs[job_id]["completed_at"] = time.time()
            return

        # Generate specs for each uncovered requirement
        for req in uncovered:
            try:
                spec_request = GenerateSpecFromRequirementRequest(
                    target_url=target_url, login_url=login_url, credentials=credentials, force_regenerate=False
                )

                result = await generate_spec_from_requirement(
                    req_id=req.id, request=spec_request, project_id=project_id
                )

                _bulk_gen_jobs[job_id]["completed"] += 1
                _bulk_gen_jobs[job_id]["results"].append(
                    {
                        "req_code": req.req_code,
                        "req_id": req.id,
                        "status": result.status,
                        "spec_name": result.spec_name,
                        "error": None,
                    }
                )
            except Exception as e:
                _bulk_gen_jobs[job_id]["failed"] += 1
                _bulk_gen_jobs[job_id]["results"].append(
                    {"req_code": req.req_code, "req_id": req.id, "status": "failed", "spec_name": None, "error": str(e)}
                )
                logger.warning(f"Bulk spec generation failed for {req.req_code}: {e}")

        _bulk_gen_jobs[job_id]["status"] = "completed"
        _bulk_gen_jobs[job_id]["completed_at"] = time.time()

    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        logger.error(f"Bulk spec generation failed: {error_type}: {error_msg}")
        logger.error(f"Stack trace:\n{traceback.format_exc()}")
        _bulk_gen_jobs[job_id]["status"] = "failed"
        _bulk_gen_jobs[job_id]["completed_at"] = time.time()
        _bulk_gen_jobs[job_id]["error"] = f"{error_type}: {error_msg}"


@router.post("/bulk-generate-specs")
async def bulk_generate_specs(
    request: BulkGenerateSpecsRequest, background_tasks: BackgroundTasks, project_id: str = Query(default="default")
):
    """
    Generate specs for all uncovered requirements (async).

    Finds requirements without RTM entries and generates test specs for each.
    Returns a job_id immediately. Poll GET /requirements/bulk-generate-jobs/{job_id}.
    """
    _cleanup_old_req_jobs()

    job_id = str(uuid.uuid4())
    _bulk_gen_jobs[job_id] = {
        "status": "queued",
        "project_id": project_id,
        "target_url": request.target_url,
        "created_at": time.time(),
        "total": 0,
        "completed": 0,
        "failed": 0,
        "results": [],
        "error": None,
    }

    logger.info(f"Bulk spec generation queued: job_id={job_id}, project_id={project_id}")

    background_tasks.add_task(
        _run_bulk_spec_generation, job_id, project_id, request.target_url, request.login_url, request.credentials
    )

    return {"job_id": job_id, "status": "queued"}


@router.get("/bulk-generate-jobs/{job_id}")
async def get_bulk_generate_job_status(job_id: str):
    """Poll bulk spec generation job status."""
    job = _bulk_gen_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        "status": job["status"],
        "total": job.get("total", 0),
        "completed": job.get("completed", 0),
        "failed": job.get("failed", 0),
        "results": job.get("results", []),
        "error": job.get("error"),
    }


@router.post("/check-duplicate", response_model=CheckDuplicateResponse)
async def check_duplicate(request: CheckDuplicateRequest, project_id: str = Query(default="default")):
    """
    Check if a requirement title/description matches existing requirements.

    Returns exact matches and semantically similar requirements to help
    prevent duplicate creation.
    """
    from memory.exploration_store import get_exploration_store
    from services.requirement_dedup import get_deduplication_service

    store = get_exploration_store(project_id=project_id)
    dedup_service = get_deduplication_service(project_id=project_id)

    # Get all existing requirements
    existing_reqs = store.get_requirements()
    existing_dicts = [
        {
            "id": r.id,
            "req_code": r.req_code,
            "title": r.title,
            "description": r.description,
            "acceptance_criteria": r.acceptance_criteria,
            "title_embedding": r.title_embedding,
        }
        for r in existing_reqs
    ]

    # Check for duplicates
    exact_match, near_matches = dedup_service.check_duplicate(
        title=request.title, description=request.description, existing_requirements=existing_dicts
    )

    # Get recommendation
    recommendation = dedup_service.get_recommendation(exact_match, near_matches)

    # Build response
    exact_match_response = None
    if exact_match:
        # Get full requirement for response
        req = store.get_requirement(exact_match.get("id"))
        if req:
            exact_match_response = RequirementResponse(
                id=req.id,
                req_code=req.req_code,
                title=req.title,
                description=req.description,
                category=req.category,
                priority=req.priority,
                status=req.status,
                acceptance_criteria=req.acceptance_criteria,
                source_session_id=req.source_session_id,
                created_at=req.created_at,
                updated_at=req.updated_at,
            )

    near_matches_response = [
        DuplicateMatchResponse(
            requirement_id=m.requirement_id,
            req_code=m.req_code,
            title=m.title,
            description=m.description,
            acceptance_criteria=m.acceptance_criteria,
            similarity=round(m.similarity, 3),
        )
        for m in near_matches
    ]

    return CheckDuplicateResponse(
        has_exact_match=exact_match is not None,
        exact_match=exact_match_response,
        near_matches=near_matches_response,
        recommendation=recommendation,
    )


@router.post("/merge", response_model=MergeResponse)
async def merge_requirements(request: MergeRequest, project_id: str = Query(default="default")):
    """
    Merge duplicate requirements into a canonical one.

    - Merges unique acceptance criteria into the canonical requirement
    - Updates RTM entries to point to the canonical requirement
    - Deletes RequirementSource entries for duplicates
    - Deletes the duplicate requirements
    """
    from sqlmodel import select

    from api.db import get_session
    from api.models_db import Requirement, RequirementSource, RtmEntry
    from services.requirement_dedup import get_deduplication_service

    dedup_service = get_deduplication_service(project_id=project_id)

    with next(get_session()) as db:
        # Get canonical requirement
        canonical = db.get(Requirement, request.canonical_id)
        if not canonical:
            raise HTTPException(status_code=404, detail="Canonical requirement not found")

        if canonical.project_id != project_id:
            raise HTTPException(status_code=403, detail="Canonical requirement belongs to different project")

        # Get duplicate requirements
        duplicates = []
        for dup_id in request.duplicate_ids:
            dup = db.get(Requirement, dup_id)
            if not dup:
                raise HTTPException(status_code=404, detail=f"Duplicate requirement {dup_id} not found")
            if dup.project_id != project_id:
                raise HTTPException(status_code=403, detail=f"Requirement {dup_id} belongs to different project")
            if dup_id == request.canonical_id:
                raise HTTPException(status_code=400, detail="Cannot merge canonical with itself")
            duplicates.append(dup)

        # Merge acceptance criteria if requested
        if request.merge_acceptance_criteria:
            all_criteria = list(canonical.acceptance_criteria)
            for dup in duplicates:
                all_criteria.extend(dup.acceptance_criteria)

            merged_criteria = dedup_service.merge_acceptance_criteria_from_list(all_criteria)
            canonical.acceptance_criteria_json = __import__("json").dumps(merged_criteria)

        canonical.updated_at = datetime.utcnow()

        deleted_ids = []
        for dup in duplicates:
            # Update RTM entries to point to canonical
            rtm_entries = db.exec(select(RtmEntry).where(RtmEntry.requirement_id == dup.id)).all()
            for entry in rtm_entries:
                entry.requirement_id = canonical.id
                entry.updated_at = datetime.utcnow()

            # Delete RequirementSource entries for duplicate
            sources = db.exec(select(RequirementSource).where(RequirementSource.requirement_id == dup.id)).all()
            for source in sources:
                db.delete(source)

            # Flush source deletes before requirement delete to avoid FK violation
            db.flush()

            # Delete the duplicate requirement
            db.delete(dup)
            deleted_ids.append(dup.id)

        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error(f"Failed to merge requirements: {exc}")
            raise HTTPException(status_code=500, detail=f"Merge failed: {exc}")
        db.refresh(canonical)

        return MergeResponse(
            canonical=RequirementResponse(
                id=canonical.id,
                req_code=canonical.req_code,
                title=canonical.title,
                description=canonical.description,
                category=canonical.category,
                priority=canonical.priority,
                status=canonical.status,
                acceptance_criteria=canonical.acceptance_criteria,
                source_session_id=canonical.source_session_id,
                created_at=canonical.created_at,
                updated_at=canonical.updated_at,
            ),
            merged_count=len(deleted_ids),
            deleted_ids=deleted_ids,
        )


# ========== Spec Generation Endpoints ==========


@router.get("/{req_id}/spec-status", response_model=SpecStatusResponse)
async def get_spec_status(req_id: int, project_id: str = Query(default="default")):
    """
    Check if a spec has been generated for this requirement.

    Returns information about existing spec and RTM entry if any.
    """
    from sqlmodel import select

    from api.db import get_session
    from api.models_db import RtmEntry
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    # Get the requirement
    requirement = store.get_requirement(req_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    # Check for RTM entries linked to this requirement
    with next(get_session()) as db:
        query = select(RtmEntry).where(RtmEntry.project_id == project_id, RtmEntry.requirement_id == req_id)
        entries = db.exec(query).all()

        if entries:
            # Return the first entry (most recent)
            entry = entries[0]
            return SpecStatusResponse(
                has_spec=True,
                spec_path=entry.test_spec_path,
                spec_name=entry.test_spec_name,
                rtm_entry_id=entry.id,
                generated_at=entry.created_at.isoformat() if entry.created_at else None,
            )

    return SpecStatusResponse(has_spec=False)


@router.post("/{req_id}/generate-spec", response_model=GenerateSpecFromRequirementResponse)
async def generate_spec_from_requirement(
    req_id: int, request: GenerateSpecFromRequirementRequest, project_id: str = Query(default="default")
):
    """
    Generate a test spec from a requirement using AI browser exploration.

    Uses NativePlanner to explore the application and generate a spec
    based on the requirement's title, description, and acceptance criteria.
    Automatically creates an RTM entry linking the spec to the requirement.
    """
    from memory.exploration_store import get_exploration_store
    from utils.string_utils import slugify
    from workflows.native_planner import NativePlanner

    store = get_exploration_store(project_id=project_id)

    # Get the requirement
    requirement = store.get_requirement(req_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    # Check if spec already exists (unless force_regenerate)
    if not request.force_regenerate:
        status = await get_spec_status(req_id, project_id)
        if status.has_spec:
            # Return existing spec info
            spec_path = Path(status.spec_path) if status.spec_path else None
            if spec_path and spec_path.exists():
                # Ensure spec is registered in DBSpecMetadata for this project
                from api.db import get_session
                from api.models_db import SpecMetadata as DBSpecMetadata

                specs_base_dir = Path(__file__).resolve().parent.parent.parent / "specs"
                try:
                    relative_spec_name = str(spec_path.relative_to(specs_base_dir))
                    with next(get_session()) as db:
                        existing_meta = db.get(DBSpecMetadata, relative_spec_name)
                        if not existing_meta:
                            meta = DBSpecMetadata(spec_name=relative_spec_name, project_id=project_id, tags_json="[]")
                            db.add(meta)
                            db.commit()
                            logger.info(
                                f"Registered existing spec in DBSpecMetadata: {relative_spec_name} -> project_id={project_id}"
                            )
                        elif existing_meta.project_id != project_id:
                            existing_meta.project_id = project_id
                            db.commit()
                            logger.info(
                                f"Updated existing spec project_id in DBSpecMetadata: {relative_spec_name} -> project_id={project_id}"
                            )
                except ValueError:
                    # spec_path is not under specs_base_dir, skip registration
                    logger.warning(
                        f"Spec path {spec_path} is not under specs directory, skipping DBSpecMetadata registration"
                    )

                return GenerateSpecFromRequirementResponse(
                    status="cached",
                    spec_path=str(spec_path),
                    spec_name=status.spec_name,
                    spec_content=spec_path.read_text(),
                    requirement_id=req_id,
                    requirement_code=requirement.req_code,
                    rtm_entry_id=status.rtm_entry_id,
                    generated_at=status.generated_at,
                    cached=True,
                )

    # Resolve base URL from exploration session if available
    base_url_origin = None
    if requirement.source_session_id:
        try:
            session = store.get_session(requirement.source_session_id)
            if session and session.entry_url:
                from urllib.parse import urlparse

                parsed = urlparse(session.entry_url)
                base_url_origin = f"{parsed.scheme}://{parsed.netloc}"
                logger.info(f"Resolved base URL origin from exploration session: {base_url_origin}")
        except Exception as e:
            logger.warning(f"Could not resolve exploration session URL: {e}")

    # Resolve relative target_url against exploration base URL
    target_url = request.target_url
    if target_url and target_url.startswith("/") and base_url_origin:
        target_url = f"{base_url_origin}{target_url}"
        logger.info(f"Resolved relative target_url to absolute: {target_url}")

    # Collect available credential keys for the project
    credential_keys = []
    try:
        from api.credentials import list_project_credentials
        from api.db import get_session

        with next(get_session()) as db_session:
            creds = list_project_credentials(project_id, db_session, include_env=True)
            credential_keys = [c["key"] for c in creds]
    except Exception as e:
        logger.warning(f"Could not load project credentials: {e}")

    # Build flow context from requirement
    flow_context = _build_flow_context_from_requirement(
        requirement, base_url_origin=base_url_origin, credential_keys=credential_keys
    )

    # Determine output directory - use project name slug instead of UUID
    from api.db import get_session as _get_session
    from api.models_db import Project as _Project

    _folder_name = project_id
    try:
        with next(_get_session()) as _db:
            _project = _db.get(_Project, project_id)
            if _project and _project.name:
                _folder_name = slugify(_project.name)
    except Exception:
        pass  # Fall back to project_id if lookup fails

    specs_dir = Path(__file__).resolve().parent.parent.parent / "specs" / "requirements" / _folder_name
    specs_dir.mkdir(parents=True, exist_ok=True)

    # Generate spec name
    req_slug = slugify(requirement.title)
    spec_name = f"{requirement.req_code.lower()}-{req_slug}.md"

    # Initialize planner and generate spec
    try:
        planner = NativePlanner(project_id=project_id)
        spec_path = await planner.generate_spec_from_flow_context(
            flow_title=f"{requirement.req_code}: {requirement.title}",
            flow_context=flow_context,
            target_url=target_url,
            login_url=request.login_url,
            credentials=request.credentials,
            output_dir=specs_dir,
        )

        # Read the generated spec content
        spec_content = spec_path.read_text() if spec_path.exists() else ""

        # Register spec in DBSpecMetadata for project filtering
        from api.db import get_session
        from api.models_db import SpecMetadata as DBSpecMetadata

        # Calculate relative spec name (relative to specs/ directory)
        specs_base_dir = Path(__file__).resolve().parent.parent.parent / "specs"
        relative_spec_name = str(spec_path.relative_to(specs_base_dir))

        with next(get_session()) as db:
            existing = db.get(DBSpecMetadata, relative_spec_name)
            if not existing:
                meta = DBSpecMetadata(spec_name=relative_spec_name, project_id=project_id, tags_json="[]")
                db.add(meta)
                logger.info(f"Registered spec in DBSpecMetadata: {relative_spec_name} -> project_id={project_id}")
            else:
                existing.project_id = project_id
                logger.info(
                    f"Updated spec project_id in DBSpecMetadata: {relative_spec_name} -> project_id={project_id}"
                )
            db.commit()

        # Create RTM entry
        logger.info(
            f"Creating RTM entry: req_id={req_id}, spec_name={spec_name}, spec_path={spec_path}, project_id={project_id}"
        )
        rtm_entry = store.store_rtm_entry(
            requirement_id=req_id,
            test_spec_name=spec_name,
            test_spec_path=str(spec_path),
            mapping_type="full",
            confidence=1.0,
            coverage_notes=f"Auto-generated from requirement {requirement.req_code}",
        )
        logger.info(f"RTM entry created successfully: id={rtm_entry.id}, requirement_id={rtm_entry.requirement_id}")

        return GenerateSpecFromRequirementResponse(
            status="generated",
            spec_path=str(spec_path),
            spec_name=spec_name,
            spec_content=spec_content,
            requirement_id=req_id,
            requirement_code=requirement.req_code,
            rtm_entry_id=rtm_entry.id,
            generated_at=datetime.utcnow().isoformat(),
            cached=False,
        )

    except Exception as e:
        logger.error(f"Spec generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


def _build_flow_context_from_requirement(requirement, base_url_origin: str = None, credential_keys: list = None) -> str:
    """
    Build a context string from requirement for NativePlanner.

    Combines title, description, and acceptance criteria into a
    format suitable for AI-based spec generation.
    """
    context_parts = []

    # Title
    context_parts.append(f"## Requirement: {requirement.req_code}")
    context_parts.append(f"**Title:** {requirement.title}")

    # Base URL from exploration
    if base_url_origin:
        context_parts.append(f"\n**Application Base URL:** {base_url_origin}")
        context_parts.append(
            "IMPORTANT: All navigation steps MUST use absolute URLs starting with this base URL. "
            "For example, use `Navigate to " + base_url_origin + "/path` instead of `Navigate to /path`."
        )

    # Available credentials
    if credential_keys:
        context_parts.append("\n**Available Credentials:**")
        context_parts.append("The following credential placeholders are available for use in test steps:")
        for key in credential_keys:
            context_parts.append(f"- `{{{{{key}}}}}`")
        context_parts.append('Use these placeholders in steps like: Enter "{{LOGIN_USERNAME}}" into the username field')
        context_parts.append("NEVER use hardcoded credentials. Always use the {{PLACEHOLDER}} syntax.")

    # Description
    if requirement.description:
        context_parts.append(f"\n**Description:**\n{requirement.description}")

    # Acceptance Criteria
    if requirement.acceptance_criteria:
        context_parts.append("\n**Acceptance Criteria:**")
        for i, criterion in enumerate(requirement.acceptance_criteria, 1):
            context_parts.append(f"{i}. {criterion}")

    # Priority and Category
    context_parts.append(f"\n**Priority:** {requirement.priority}")
    context_parts.append(f"**Category:** {requirement.category}")

    # Test guidance
    context_parts.append("\n## Test Generation Guidance")
    context_parts.append("Generate test cases that verify:")
    context_parts.append("- All acceptance criteria are met")
    context_parts.append("- The happy path works correctly")
    context_parts.append("- Error scenarios are handled appropriately")
    context_parts.append("- Edge cases are considered based on the requirement")

    return "\n".join(context_parts)
