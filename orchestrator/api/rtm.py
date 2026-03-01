"""
RTM (Requirements Traceability Matrix) API Router

Provides endpoints for generating, querying, and exporting
the Requirements Traceability Matrix.
"""

import logging
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rtm", tags=["rtm"])

# ========== In-Memory Job Tracking ==========
_rtm_gen_jobs: dict[str, dict] = {}
MAX_TRACKED_JOBS = 50


def _cleanup_old_rtm_jobs():
    """Remove completed/failed jobs older than 1 hour."""
    now = time.time()
    to_remove = []
    for job_id, job in _rtm_gen_jobs.items():
        if job["status"] in ("completed", "failed"):
            completed_at = job.get("completed_at", 0)
            if now - completed_at > 3600:
                to_remove.append(job_id)
    for job_id in to_remove:
        del _rtm_gen_jobs[job_id]
    if len(_rtm_gen_jobs) > MAX_TRACKED_JOBS:
        evictable = sorted(
            [(jid, j) for jid, j in _rtm_gen_jobs.items() if j["status"] != "running"],
            key=lambda x: x[1].get("started_at", 0),
        )
        for job_id, _ in evictable[: len(_rtm_gen_jobs) - MAX_TRACKED_JOBS]:
            del _rtm_gen_jobs[job_id]


# ========== Pydantic Models ==========


class RtmEntryResponse(BaseModel):
    """Response model for an RTM entry."""

    id: int
    requirement_id: int
    requirement_code: str
    requirement_title: str
    test_spec_name: str
    test_spec_path: str | None
    mapping_type: str
    confidence: float
    coverage_notes: str | None
    gap_notes: str | None


class RtmRequirementResponse(BaseModel):
    """Requirement with its test mappings."""

    id: int
    code: str
    title: str
    description: str | None
    category: str
    priority: str
    status: str
    acceptance_criteria: list[str]
    tests: list[dict]
    coverage_status: str  # covered, partial, uncovered, suggested


class RtmFullResponse(BaseModel):
    """Full RTM response."""

    requirements: list[RtmRequirementResponse]
    summary: dict


class RtmCoverageStats(BaseModel):
    """RTM coverage statistics."""

    total_requirements: int
    covered: int
    partial: int
    uncovered: int
    coverage_percentage: float


class PaginatedRtmResponse(BaseModel):
    """Paginated RTM response with summary stats."""

    items: list[RtmRequirementResponse]
    total: int
    limit: int
    offset: int
    has_more: bool
    summary: RtmCoverageStats


class RtmGapResponse(BaseModel):
    """Coverage gap information."""

    requirement_id: int
    requirement_code: str
    title: str
    category: str
    priority: str
    suggested_test: dict


class GenerateRtmRequest(BaseModel):
    """Request to generate RTM."""

    specs_paths: list[str] | None = None
    use_ai_matching: bool = True


class RtmSnapshotResponse(BaseModel):
    """RTM snapshot response."""

    id: int
    snapshot_name: str | None
    total_requirements: int
    covered_requirements: int
    partial_requirements: int
    uncovered_requirements: int
    coverage_percentage: float
    created_at: datetime


class RtmTrendPoint(BaseModel):
    """Coverage trend data point from snapshots."""

    snapshot_id: int | None = None
    snapshot_name: str | None = None
    total_requirements: int
    covered: int
    partial: int
    uncovered: int
    coverage_percentage: float
    created_at: datetime


class RtmSnapshotDetailResponse(RtmSnapshotResponse):
    """Snapshot with full RTM data."""

    data: dict | None = None


class CreateRtmEntryRequest(BaseModel):
    """Request to create an RTM entry manually."""

    requirement_id: int = Field(..., description="ID of the requirement to link")
    test_spec_name: str = Field(..., description="Name of the test spec file")
    test_spec_path: str | None = Field(None, description="Full path to the spec file")
    mapping_type: str = Field(default="full", description="Type of mapping: full, partial, suggested")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score 0-1")
    coverage_notes: str | None = Field(None, description="Notes about what is covered")


# ========== API Endpoints ==========


@router.get("", response_model=PaginatedRtmResponse)
async def get_rtm(
    project_id: str = Query(default="default"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    coverage_status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    priority: str | None = Query(default=None),
):
    """Get paginated Requirements Traceability Matrix."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    items, total = store.get_rtm_paginated(
        limit=limit, offset=offset, search=search, coverage_status=coverage_status, category=category, priority=priority
    )
    stats = store.get_rtm_coverage_stats_fast()

    return PaginatedRtmResponse(
        items=[
            RtmRequirementResponse(
                id=r["requirement"]["id"],
                code=r["requirement"]["code"],
                title=r["requirement"]["title"],
                description=r["requirement"]["description"],
                category=r["requirement"]["category"],
                priority=r["requirement"]["priority"],
                status=r["requirement"]["status"],
                acceptance_criteria=r["requirement"]["acceptance_criteria"],
                tests=r["tests"],
                coverage_status=r["coverage_status"],
            )
            for r in items
        ],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
        summary=RtmCoverageStats(
            total_requirements=stats["total_requirements"],
            covered=stats["covered"],
            partial=stats["partial"],
            uncovered=stats["uncovered"],
            coverage_percentage=stats["coverage_percentage"],
        ),
    )


async def _run_rtm_generation(job_id: str, project_id: str, specs_paths: list[str] | None, use_ai_matching: bool):
    """Background task for RTM generation."""
    import traceback

    from workflows.rtm_generator import RtmGenerator

    _rtm_gen_jobs[job_id]["status"] = "running"
    _rtm_gen_jobs[job_id]["started_at"] = time.time()

    try:
        generator = RtmGenerator(project_id=project_id)
        result = await generator.generate_rtm(specs_paths=specs_paths, use_ai_matching=use_ai_matching)

        _rtm_gen_jobs[job_id]["status"] = "completed"
        _rtm_gen_jobs[job_id]["completed_at"] = time.time()
        _rtm_gen_jobs[job_id]["result"] = {
            "status": "generated",
            "total_requirements": result.total_requirements,
            "covered": result.covered_requirements,
            "partial": result.partial_requirements,
            "uncovered": result.uncovered_requirements,
            "coverage_percentage": result.coverage_percentage,
            "mappings_created": len(result.mappings),
            "gaps_found": len(result.gaps),
        }
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        logger.error(f"Failed to generate RTM: {error_type}: {error_msg}")
        logger.error(f"Stack trace:\n{traceback.format_exc()}")
        _rtm_gen_jobs[job_id]["status"] = "failed"
        _rtm_gen_jobs[job_id]["completed_at"] = time.time()
        _rtm_gen_jobs[job_id]["error"] = f"{error_type}: {error_msg}"


@router.post("/generate")
async def generate_rtm(
    request: GenerateRtmRequest, background_tasks: BackgroundTasks, project_id: str = Query(default="default")
):
    """
    Generate or refresh the RTM (async).

    Returns a job_id immediately. Poll GET /rtm/generate-jobs/{job_id}
    for status and results.
    """
    _cleanup_old_rtm_jobs()

    job_id = str(uuid.uuid4())
    _rtm_gen_jobs[job_id] = {
        "status": "queued",
        "project_id": project_id,
        "created_at": time.time(),
    }

    logger.info(f"RTM generation queued: job_id={job_id}, project_id={project_id}")

    background_tasks.add_task(_run_rtm_generation, job_id, project_id, request.specs_paths, request.use_ai_matching)

    return {"job_id": job_id, "status": "queued"}


@router.get("/generate-jobs/{job_id}")
async def get_rtm_generate_job_status(job_id: str):
    """Poll RTM generation job status."""
    job = _rtm_gen_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    response = {
        "job_id": job_id,
        "status": job["status"],
        "project_id": job.get("project_id"),
    }

    if job["status"] == "completed":
        response["result"] = job.get("result")
    elif job["status"] == "failed":
        response["error"] = job.get("error")

    return response


@router.get("/coverage", response_model=RtmCoverageStats)
async def get_coverage(project_id: str = Query(default="default")):
    """Get RTM coverage statistics."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    stats = store.get_rtm_coverage_stats_fast()

    return RtmCoverageStats(
        total_requirements=stats["total_requirements"],
        covered=stats["covered"],
        partial=stats["partial"],
        uncovered=stats["uncovered"],
        coverage_percentage=stats["coverage_percentage"],
    )


@router.get("/gaps", response_model=list[RtmGapResponse])
async def get_coverage_gaps(
    project_id: str = Query(default="default"),
    priority: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Get requirements without test coverage (gaps)."""
    from memory.exploration_store import get_exploration_store
    from workflows.rtm_generator import RtmGenerator

    store = get_exploration_store(project_id=project_id)
    generator = RtmGenerator(project_id=project_id)

    # Use paginated query filtered to uncovered requirements
    items, total = store.get_rtm_paginated(limit=limit, offset=offset, coverage_status="uncovered", priority=priority)

    gaps = []
    for entry in items:
        req = entry["requirement"]

        class MockReq:
            def __init__(self, data):
                self.req_code = data["code"]
                self.title = data["title"]
                self.acceptance_criteria = data["acceptance_criteria"]
                self.priority = data["priority"]

        suggested = generator._suggest_test_for_requirement(MockReq(req))

        gaps.append(
            RtmGapResponse(
                requirement_id=req["id"],
                requirement_code=req["code"],
                title=req["title"],
                category=req["category"],
                priority=req["priority"],
                suggested_test=suggested,
            )
        )

    # Sort by priority
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    gaps.sort(key=lambda g: priority_order.get(g.priority, 99))

    return gaps


@router.get("/export/{format}")
async def export_rtm(format: str, project_id: str = Query(default="default")):
    """
    Export RTM in the specified format.

    Supported formats: markdown, csv, html
    """
    from workflows.rtm_generator import RtmGenerator

    if format not in ["markdown", "csv", "html"]:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")

    generator = RtmGenerator(project_id=project_id)

    try:
        content = generator.export_rtm(format=format)

        # Set appropriate content type
        content_types = {"markdown": "text/markdown", "csv": "text/csv", "html": "text/html"}

        return Response(
            content=content,
            media_type=content_types[format],
            headers={"Content-Disposition": f"attachment; filename=rtm.{format if format != 'markdown' else 'md'}"},
        )
    except Exception as e:
        logger.error(f"Failed to export RTM: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/snapshot", response_model=RtmSnapshotResponse)
async def create_snapshot(project_id: str = Query(default="default"), name: str | None = Query(default=None)):
    """Create a snapshot of the current RTM for historical tracking."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    snapshot = store.create_rtm_snapshot(snapshot_name=name)

    return RtmSnapshotResponse(
        id=snapshot.id,
        snapshot_name=snapshot.snapshot_name,
        total_requirements=snapshot.total_requirements,
        covered_requirements=snapshot.covered_requirements,
        partial_requirements=snapshot.partial_requirements,
        uncovered_requirements=snapshot.uncovered_requirements,
        coverage_percentage=snapshot.coverage_percentage,
        created_at=snapshot.created_at,
    )


@router.get("/snapshots", response_model=list[RtmSnapshotResponse])
async def list_snapshots(project_id: str = Query(default="default"), limit: int = Query(default=20, ge=1, le=100)):
    """List RTM snapshots."""
    from sqlmodel import col, select

    from api.db import get_session
    from api.models_db import RtmSnapshot

    with next(get_session()) as db:
        query = (
            select(RtmSnapshot)
            .where(RtmSnapshot.project_id == project_id)
            .order_by(col(RtmSnapshot.created_at).desc())
            .limit(limit)
        )

        snapshots = db.exec(query).all()

        return [
            RtmSnapshotResponse(
                id=s.id,
                snapshot_name=s.snapshot_name,
                total_requirements=s.total_requirements,
                covered_requirements=s.covered_requirements,
                partial_requirements=s.partial_requirements,
                uncovered_requirements=s.uncovered_requirements,
                coverage_percentage=s.coverage_percentage,
                created_at=s.created_at,
            )
            for s in snapshots
        ]


@router.get("/trend", response_model=list[RtmTrendPoint])
async def get_coverage_trend(project_id: str = Query(default="default"), limit: int = Query(default=20, ge=1, le=100)):
    """Get coverage trend data from snapshots for charting."""
    from sqlmodel import col, select

    from api.db import get_session
    from api.models_db import RtmSnapshot
    from memory.exploration_store import get_exploration_store

    points = []

    with next(get_session()) as db:
        query = (
            select(RtmSnapshot)
            .where(RtmSnapshot.project_id == project_id)
            .order_by(col(RtmSnapshot.created_at).asc())
            .limit(limit)
        )

        snapshots = db.exec(query).all()

        for s in snapshots:
            points.append(
                RtmTrendPoint(
                    snapshot_id=s.id,
                    snapshot_name=s.snapshot_name,
                    total_requirements=s.total_requirements,
                    covered=s.covered_requirements,
                    partial=s.partial_requirements,
                    uncovered=s.uncovered_requirements,
                    coverage_percentage=s.coverage_percentage,
                    created_at=s.created_at,
                )
            )

    # Append current live stats as the last point
    try:
        store = get_exploration_store(project_id=project_id)
        stats = store.get_rtm_coverage_stats_fast()
        points.append(
            RtmTrendPoint(
                snapshot_id=None,
                snapshot_name="Current",
                total_requirements=stats["total_requirements"],
                covered=stats["covered"],
                partial=stats["partial"],
                uncovered=stats["uncovered"],
                coverage_percentage=stats["coverage_percentage"],
                created_at=datetime.utcnow(),
            )
        )
    except Exception as e:
        logger.warning(f"Could not append live stats to trend: {e}")

    return points


@router.get("/snapshot/{snapshot_id}", response_model=RtmSnapshotDetailResponse)
async def get_snapshot_detail(snapshot_id: int, project_id: str = Query(default="default")):
    """Get full snapshot detail including the RTM data at that point in time."""
    import json

    from api.db import get_session
    from api.models_db import RtmSnapshot

    with next(get_session()) as db:
        snapshot = db.get(RtmSnapshot, snapshot_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="Snapshot not found")

        if snapshot.project_id != project_id:
            raise HTTPException(status_code=403, detail="Snapshot belongs to different project")

        # Parse the stored JSON data
        try:
            data = json.loads(snapshot.snapshot_data_json) if snapshot.snapshot_data_json else None
        except json.JSONDecodeError:
            data = None

        return RtmSnapshotDetailResponse(
            id=snapshot.id,
            snapshot_name=snapshot.snapshot_name,
            total_requirements=snapshot.total_requirements,
            covered_requirements=snapshot.covered_requirements,
            partial_requirements=snapshot.partial_requirements,
            uncovered_requirements=snapshot.uncovered_requirements,
            coverage_percentage=snapshot.coverage_percentage,
            created_at=snapshot.created_at,
            data=data,
        )


@router.get("/requirement/{req_id}/tests", response_model=list[RtmEntryResponse])
async def get_requirement_tests(req_id: int, project_id: str = Query(default="default")):
    """Get all tests mapped to a specific requirement."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    requirement = store.get_requirement(req_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    entries = store.get_rtm_entries(requirement_id=req_id)

    return [
        RtmEntryResponse(
            id=e.id,
            requirement_id=requirement.id,
            requirement_code=requirement.req_code,
            requirement_title=requirement.title,
            test_spec_name=e.test_spec_name,
            test_spec_path=e.test_spec_path,
            mapping_type=e.mapping_type,
            confidence=e.confidence,
            coverage_notes=e.coverage_notes,
            gap_notes=e.gap_notes,
        )
        for e in entries
    ]


@router.get("/test/{test_name}/requirements")
async def get_test_requirements(test_name: str, project_id: str = Query(default="default")):
    """Get all requirements covered by a specific test."""
    from sqlmodel import select

    from api.db import get_session
    from api.models_db import Requirement, RtmEntry

    with next(get_session()) as db:
        query = select(RtmEntry).where(RtmEntry.project_id == project_id, RtmEntry.test_spec_name == test_name)

        entries = db.exec(query).all()

        results = []
        for entry in entries:
            req = db.get(Requirement, entry.requirement_id)
            if req:
                results.append(
                    {
                        "entry_id": entry.id,
                        "requirement": {
                            "id": req.id,
                            "code": req.req_code,
                            "title": req.title,
                            "category": req.category,
                            "priority": req.priority,
                        },
                        "mapping_type": entry.mapping_type,
                        "confidence": entry.confidence,
                    }
                )

        return {"test_name": test_name, "requirements": results}


@router.post("/entry", response_model=RtmEntryResponse)
async def create_rtm_entry(request: CreateRtmEntryRequest, project_id: str = Query(default="default")):
    """
    Create an RTM entry to link a requirement to a test spec.

    Use this endpoint when manually creating a spec to establish
    the traceability link between the requirement and the test.
    """
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    # Verify requirement exists
    requirement = store.get_requirement(request.requirement_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    # Create RTM entry
    entry = store.store_rtm_entry(
        requirement_id=request.requirement_id,
        test_spec_name=request.test_spec_name,
        test_spec_path=request.test_spec_path,
        mapping_type=request.mapping_type,
        confidence=request.confidence,
        coverage_notes=request.coverage_notes,
    )

    return RtmEntryResponse(
        id=entry.id,
        requirement_id=requirement.id,
        requirement_code=requirement.req_code,
        requirement_title=requirement.title,
        test_spec_name=entry.test_spec_name,
        test_spec_path=entry.test_spec_path,
        mapping_type=entry.mapping_type,
        confidence=entry.confidence,
        coverage_notes=entry.coverage_notes,
        gap_notes=entry.gap_notes,
    )


@router.delete("/entry/{entry_id}")
async def delete_rtm_entry(entry_id: int, project_id: str = Query(default="default")):
    """Delete an RTM entry."""
    from api.db import get_session
    from api.models_db import RtmEntry

    with next(get_session()) as db:
        entry = db.get(RtmEntry, entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="RTM entry not found")

        if entry.project_id != project_id:
            raise HTTPException(status_code=403, detail="RTM entry belongs to different project")

        db.delete(entry)
        db.commit()

    return {"status": "deleted", "entry_id": entry_id}
