"""
Requirements API Router

Provides CRUD endpoints for requirements management and
integration with exploration-based requirements generation.
"""

import asyncio
import logging
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/requirements", tags=["requirements"])

# ========== In-Memory Job Tracking ==========
_req_gen_jobs: dict[str, dict] = {}
_bulk_gen_jobs: dict[str, dict] = {}
_req_spec_jobs: dict[str, dict] = {}
MAX_TRACKED_JOBS = 50


def _cleanup_old_req_jobs():
    """Remove completed/failed jobs older than 1 hour."""
    now = time.time()
    for job_store in (_req_gen_jobs, _bulk_gen_jobs, _req_spec_jobs):
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


def _ensure_job_project(job_project_id: str | None, project_id: str) -> None:
    if job_project_id != project_id:
        raise HTTPException(status_code=404, detail="Job not found")


# ========== Pydantic Models ==========


class RequirementCreate(BaseModel):
    """Request to create a requirement."""

    title: str = Field(..., min_length=1)
    description: str | None = None
    category: str = Field(default="other")
    priority: str = Field(default="medium")
    acceptance_criteria: list[str] = Field(default_factory=list)
    truth_state: str = Field(default="candidate_requirement")
    source_type: str = Field(default="manual")
    confidence: float = Field(default=0.9, ge=0, le=1)
    uncertainty_reason: str | None = None


class RequirementUpdate(BaseModel):
    """Request to update a requirement."""

    title: str | None = None
    description: str | None = None
    category: str | None = None
    priority: str | None = None
    status: str | None = None
    truth_state: str | None = None
    source_type: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    uncertainty_reason: str | None = None
    acceptance_criteria: list[str] | None = None


class RequirementTruthDecisionRequest(BaseModel):
    """Human decision for requirement truth state."""

    user: str | None = None
    comment: str | None = None


class RequirementReviewDecision(BaseModel):
    """Bulk human decision for one requirement."""

    req_id: int
    decision: str = Field(pattern="^(confirm|confirmed|approve|approved|reject|rejected|stale|mark_stale)$")
    user: str | None = None
    comment: str | None = None


class RequirementReviewDecisionsRequest(BaseModel):
    """Bulk review decisions for requirement truth state."""

    user: str | None = None
    comment: str | None = None
    decisions: list[RequirementReviewDecision] = Field(..., min_length=1, max_length=200)


class RequirementResponse(BaseModel):
    """Response model for a requirement."""

    id: int
    req_code: str
    title: str
    description: str | None
    category: str
    priority: str
    status: str
    truth_state: str
    source_type: str
    confidence: float
    uncertainty_reason: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    acceptance_criteria: list[str]
    source_session_id: str | None
    created_at: datetime
    updated_at: datetime


class RequirementReviewDecisionsResponse(BaseModel):
    """Bulk requirement review result."""

    updated: int
    requirements: list[RequirementResponse]
    errors: list[dict]


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
    mode: str = Field(default="single_agent", pattern="^(single_agent|multi_agent)$")
    max_agents: int = Field(default=3, ge=1, le=6)
    browser_verification: str = Field(default="off", pattern="^(off|selected)$")


class GenerateRequirementsResponse(BaseModel):
    """Response from requirements generation."""

    total_requirements: int
    by_category: dict
    by_priority: dict
    requirements: list[RequirementResponse]


def _requirement_truth_state(requirement) -> str:
    stored = getattr(requirement, "truth_state", None)
    if stored:
        return str(stored)
    status = str(getattr(requirement, "status", "") or "").lower()
    if status in {"approved", "implemented", "tested", "confirmed"}:
        return "confirmed_requirement"
    if status in {"observed", "observed_behavior"}:
        return "observed_behavior"
    if getattr(requirement, "source_session_id", None):
        return "candidate_requirement"
    return "manual_requirement"


def _requirement_confidence(requirement) -> float:
    stored = getattr(requirement, "confidence", None)
    if stored is not None:
        try:
            return max(0.0, min(float(stored), 1.0))
        except (TypeError, ValueError):
            pass
    truth_state = _requirement_truth_state(requirement)
    if truth_state == "confirmed_requirement":
        return 1.0
    if truth_state == "manual_requirement":
        return 0.9
    if truth_state == "candidate_requirement":
        return 0.7
    return 0.5


def _requirement_source_type(requirement) -> str:
    stored = getattr(requirement, "source_type", None)
    if stored:
        return str(stored)
    if getattr(requirement, "source_session_id", None):
        return "app_observation"
    if _requirement_truth_state(requirement) == "confirmed_requirement":
        return "human_approval"
    return "manual_entry"


def _requirement_uncertainty_reason(requirement) -> str | None:
    stored = getattr(requirement, "uncertainty_reason", None)
    if stored:
        return str(stored)
    truth_state = _requirement_truth_state(requirement)
    if truth_state == "candidate_requirement":
        return "Generated from observed app behavior and awaiting human confirmation."
    if truth_state == "observed_behavior":
        return "Records current behavior only; it has not been promoted to an intended requirement."
    return None


def _requirement_generation_warning(requirement) -> str | None:
    truth_state = _requirement_truth_state(requirement)
    if truth_state == "confirmed_requirement":
        return None
    if truth_state == "rejected_requirement":
        return "This requirement was rejected; generated specs should be reviewed before use."
    if truth_state == "stale_requirement":
        return "This requirement was marked stale; generated specs may not match the current application."
    if truth_state == "observed_behavior":
        return "This is observed behavior, not a confirmed requirement. Avoid encoding a bug as expected behavior."
    if truth_state == "candidate_requirement":
        return "This candidate requirement has not been confirmed by a human reviewer."
    return "This requirement is not confirmed; generated specs should be reviewed before use."


def _requirement_to_response(requirement) -> RequirementResponse:
    return RequirementResponse(
        id=requirement.id,
        req_code=requirement.req_code,
        title=requirement.title,
        description=requirement.description,
        category=requirement.category,
        priority=requirement.priority,
        status=requirement.status,
        truth_state=_requirement_truth_state(requirement),
        source_type=_requirement_source_type(requirement),
        confidence=_requirement_confidence(requirement),
        uncertainty_reason=_requirement_uncertainty_reason(requirement),
        confirmed_by=getattr(requirement, "confirmed_by", None),
        confirmed_at=getattr(requirement, "confirmed_at", None),
        rejected_by=getattr(requirement, "rejected_by", None),
        rejected_at=getattr(requirement, "rejected_at", None),
        acceptance_criteria=requirement.acceptance_criteria,
        source_session_id=requirement.source_session_id,
        created_at=requirement.created_at,
        updated_at=requirement.updated_at,
    )


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
    browser_auth_session_id: str | None = Field(None, description="Saved browser auth session ID")
    use_project_default_browser_auth: bool = Field(False, description="Use the project default browser auth session")
    test_data_refs: list[str] = Field(default_factory=list, description="Explicit project test data refs")
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
    truth_state: str | None = None
    generation_warning: str | None = None
    generation_allowed: bool = True


class SpecStatusResponse(BaseModel):
    """Response for spec status check."""

    has_spec: bool
    spec_path: str | None = None
    spec_name: str | None = None
    rtm_entry_id: int | None = None
    generated_at: str | None = None
    truth_state: str | None = None
    generation_warning: str | None = None
    generation_allowed: bool = True


@dataclass
class RequirementSpecGenerationContext:
    requirement: Any
    truth_state: str
    generation_warning: str | None
    target_url: str
    flow_context: str
    auth_context: dict[str, Any] | None
    planner_session_dir: Path | None
    specs_dir: Path
    spec_name: str
    mcp_runtime: dict[str, Any]
    browser_auth_metadata: dict[str, Any]


def _dump_model(model: BaseModel) -> dict[str, Any]:
    dump = getattr(model, "model_dump", None)
    if callable(dump):
        return dump()
    return model.dict()


def _requirement_browser_auth_metadata(
    request: GenerateSpecFromRequirementRequest,
    auth_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    requested_browser_auth_session_id = (request.browser_auth_session_id or "").strip()
    if requested_browser_auth_session_id:
        metadata["browser_auth_session_id"] = requested_browser_auth_session_id
    if request.use_project_default_browser_auth:
        metadata["use_project_default_browser_auth"] = True
    if auth_context:
        if auth_context.get("browser_auth_session_id"):
            metadata["browser_auth_session_id"] = auth_context["browser_auth_session_id"]
        if auth_context.get("browser_auth_session_name"):
            metadata["browser_auth_session_name"] = auth_context["browser_auth_session_name"]
        if auth_context.get("use_project_default_browser_auth"):
            metadata["use_project_default_browser_auth"] = True
        if auth_context.get("storage_state_attached"):
            metadata["storage_state_attached"] = True
    return metadata


async def _cached_requirement_spec_response(
    req_id: int,
    request: GenerateSpecFromRequirementRequest,
    project_id: str,
    requirement: Any,
    truth_state: str,
    generation_warning: str | None,
) -> GenerateSpecFromRequirementResponse | None:
    if request.force_regenerate:
        return None

    status = await get_spec_status(req_id, project_id)
    if not status.has_spec:
        return None

    spec_path = Path(status.spec_path) if status.spec_path else None
    if not spec_path or not spec_path.exists():
        return None

    from orchestrator.api.db import get_session
    from orchestrator.api.models_db import SpecMetadata as DBSpecMetadata
    from orchestrator.api.models_db import get_spec_metadata

    specs_base_dir = Path(__file__).resolve().parent.parent.parent / "specs"
    try:
        relative_spec_name = str(spec_path.relative_to(specs_base_dir))
        with next(get_session()) as db:
            existing_meta = get_spec_metadata(db, relative_spec_name, project_id)
            if not existing_meta:
                meta = DBSpecMetadata(spec_name=relative_spec_name, project_id=project_id, tags_json="[]")
                db.add(meta)
                db.commit()
                logger.info(
                    f"Registered existing spec in DBSpecMetadata: {relative_spec_name} -> project_id={project_id}"
                )
    except ValueError:
        logger.warning(f"Spec path {spec_path} is not under specs directory, skipping DBSpecMetadata registration")

    return GenerateSpecFromRequirementResponse(
        status="cached",
        spec_path=str(spec_path),
        spec_name=status.spec_name or spec_path.name,
        spec_content=spec_path.read_text(),
        requirement_id=req_id,
        requirement_code=requirement.req_code,
        rtm_entry_id=status.rtm_entry_id or 0,
        generated_at=status.generated_at or datetime.utcnow().isoformat(),
        cached=True,
        truth_state=truth_state,
        generation_warning=generation_warning,
        generation_allowed=True,
    )


async def _prepare_requirement_spec_generation(
    req_id: int,
    request: GenerateSpecFromRequirementRequest,
    project_id: str,
    *,
    planner_session_dir: Path | None = None,
    prepare_mcp: bool = False,
) -> RequirementSpecGenerationContext:
    from orchestrator.memory.exploration_store import get_exploration_store
    from orchestrator.api.db import get_session
    from utils.string_utils import slugify

    store = get_exploration_store(project_id=project_id)

    requirement = store.get_requirement(req_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    truth_state = _requirement_truth_state(requirement)
    generation_warning = _requirement_generation_warning(requirement)
    project_root = Path(__file__).resolve().parent.parent.parent

    base_url_origin = None
    if requirement.source_session_id:
        try:
            source_session = store.get_session(requirement.source_session_id)
            if source_session and source_session.entry_url:
                from urllib.parse import urlparse

                parsed = urlparse(source_session.entry_url)
                base_url_origin = f"{parsed.scheme}://{parsed.netloc}"
                logger.info(f"Resolved base URL origin from exploration session: {base_url_origin}")
        except Exception as e:
            logger.warning(f"Could not resolve exploration session URL: {e}")

    target_url = request.target_url
    if target_url and target_url.startswith("/") and base_url_origin:
        target_url = f"{base_url_origin}{target_url}"
        logger.info(f"Resolved relative target_url to absolute: {target_url}")

    credential_keys = []
    try:
        from api.credentials import list_project_credentials

        with next(get_session()) as db_session:
            creds = list_project_credentials(project_id, db_session, include_env=True)
            credential_keys = [c["key"] for c in creds]
    except Exception as e:
        logger.warning(f"Could not load project credentials: {e}")

    test_data_markdown = ""
    if request.test_data_refs:
        try:
            from orchestrator.services.test_data_resolver import resolve_test_data_refs

            with next(get_session()) as db_session:
                resolved = resolve_test_data_refs(
                    db_session,
                    project_id=project_id,
                    refs=request.test_data_refs,
                    render_as="markdown",
                    decrypt_sensitive=True,
                )
            missing_test_data = resolved.get("missing") or []
            if missing_test_data:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "test_data_refs_unresolved",
                        "message": "Some selected test data refs are unavailable",
                        "missing_test_data": missing_test_data,
                    },
                )
            test_data_markdown = resolved.get("markdown") or ""
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "test_data_refs_unresolved",
                    "message": f"Could not resolve selected test data refs: {e}",
                    "refs": request.test_data_refs,
                },
            ) from e

    auth_context = None
    storage_state_path = None
    requested_browser_auth_session_id = (request.browser_auth_session_id or "").strip() or None
    needs_browser_auth = requested_browser_auth_session_id or request.use_project_default_browser_auth
    if needs_browser_auth:
        try:
            from orchestrator.services.browser_auth_sessions import (
                BrowserAuthSessionError,
                resolve_browser_auth_for_run,
            )

            if planner_session_dir is None:
                planner_session_dir = project_root / "runs" / f"requirements-generate-spec-{uuid.uuid4().hex}"
            await asyncio.to_thread(planner_session_dir.mkdir, parents=True, exist_ok=True)
            with next(get_session()) as db_session:
                resolved_auth = resolve_browser_auth_for_run(
                    db_session,
                    project_id,
                    run_dir=planner_session_dir,
                    browser_auth_session_id=requested_browser_auth_session_id,
                    use_default=bool(request.use_project_default_browser_auth),
                )
            if not resolved_auth:
                raise BrowserAuthSessionError("Browser auth session was not found")
            storage_state_path = resolved_auth.storage_state_path
            auth_context = {
                "mode": "project_default" if request.use_project_default_browser_auth else "session",
                "storage_state_attached": True,
                "requested_browser_auth_session_id": requested_browser_auth_session_id,
                "browser_auth_session_id": resolved_auth.session_id,
                "browser_auth_session_name": resolved_auth.session_name,
                "use_project_default_browser_auth": bool(request.use_project_default_browser_auth),
            }
        except BrowserAuthSessionError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    mcp_runtime: dict[str, Any] = {}
    if prepare_mcp or needs_browser_auth:
        from orchestrator.utils.playwright_mcp import write_playwright_mcp_config

        if planner_session_dir is None:
            planner_session_dir = project_root / "runs" / f"requirements-generate-spec-{uuid.uuid4().hex}"
        await asyncio.to_thread(planner_session_dir.mkdir, parents=True, exist_ok=True)
        mcp_runtime = await asyncio.to_thread(
            write_playwright_mcp_config,
            run_dir=planner_session_dir,
            server_name="playwright-test",
            project_root=project_root,
            storage_state_path=storage_state_path,
        )
        logger.info("Prepared browser MCP runtime for requirement spec generation: %s", mcp_runtime)

    flow_context = _build_flow_context_from_requirement(
        requirement,
        base_url_origin=base_url_origin,
        credential_keys=credential_keys,
        test_data_markdown=test_data_markdown,
    )

    from orchestrator.api.models_db import Project as _Project

    folder_name = project_id
    try:
        with next(get_session()) as db:
            project = db.get(_Project, project_id)
            if project and project.name:
                folder_name = slugify(project.name)
    except Exception:
        pass

    specs_dir = project_root / "specs" / "requirements" / folder_name
    await asyncio.to_thread(specs_dir.mkdir, parents=True, exist_ok=True)
    req_slug = slugify(requirement.title)
    spec_name = f"{requirement.req_code.lower()}-{req_slug}.md"

    return RequirementSpecGenerationContext(
        requirement=requirement,
        truth_state=truth_state,
        generation_warning=generation_warning,
        target_url=target_url,
        flow_context=flow_context,
        auth_context=auth_context,
        planner_session_dir=planner_session_dir,
        specs_dir=specs_dir,
        spec_name=spec_name,
        mcp_runtime=mcp_runtime,
        browser_auth_metadata=_requirement_browser_auth_metadata(request, auth_context),
    )


async def _execute_requirement_spec_generation(
    req_id: int,
    request: GenerateSpecFromRequirementRequest,
    project_id: str,
    context: RequirementSpecGenerationContext,
    *,
    job_id: str | None = None,
    agent_run_id: str | None = None,
) -> GenerateSpecFromRequirementResponse:
    from orchestrator.memory.exploration_store import get_exploration_store
    from orchestrator.api.db import get_session
    from orchestrator.api.models_db import AgentRun, SpecMetadata as DBSpecMetadata
    from orchestrator.api.models_db import get_spec_metadata
    from orchestrator.utils.playwright_mcp import browser_runtime_status
    from workflows.native_planner import NativePlanner

    project_root = Path(__file__).resolve().parent.parent.parent
    store = get_exploration_store(project_id=project_id)
    browser_tool_calls = 0

    def _set_job_message(message: str) -> None:
        if job_id and job_id in _req_spec_jobs:
            _req_spec_jobs[job_id]["message"] = message

    def _update_agent_progress(patch: dict[str, Any]) -> None:
        if not agent_run_id:
            return
        from orchestrator.api import main as main_api

        runtime = browser_runtime_status()
        main_api._update_agent_run_progress(
            agent_run_id,
            {
                "status": "running",
                "has_browser_tools": True,
                **runtime,
                **patch,
            },
        )

    def _record_event(event_type: str, message: str, payload: dict[str, Any], level: str = "info") -> None:
        if not agent_run_id:
            return
        from orchestrator.api import main as main_api

        main_api._record_agent_run_event(
            agent_run_id,
            event_type=event_type,
            level=level,
            message=message,
            payload=payload,
        )

    def _on_planner_task_enqueued(agent_task_id: str) -> None:
        if job_id and job_id in _req_spec_jobs:
            _req_spec_jobs[job_id]["agent_task_id"] = agent_task_id
        _update_agent_progress({"agent_task_id": agent_task_id})

    def _on_planner_tool_use(tool_name: str, tool_input: dict[str, Any]) -> None:
        nonlocal browser_tool_calls
        browser_tool_calls += 1
        from orchestrator.api import main as main_api

        tool_label = main_api._short_tool_name(tool_name)
        _set_job_message(f"Using {tool_label}...")
        _update_agent_progress(
            {
                "phase": "tool_use",
                "message": f"Using {tool_label}",
                "last_tool": tool_name,
                "last_tool_input": tool_input,
                "browser_tool_calls": browser_tool_calls,
            }
        )
        _record_event(
            "browser_action" if str(tool_name).startswith("mcp__playwright") else "tool_call",
            f"Using {tool_label}.",
            {
                "tool_name": tool_name,
                "tool_label": tool_label,
                "tool_input": tool_input,
                "requirement_id": req_id,
                "requirement_code": context.requirement.req_code,
            },
        )

    def _on_planner_progress(progress: dict[str, Any]) -> None:
        from orchestrator.api import main as main_api

        last_tool = progress.get("last_tool")
        message = progress.get("message")
        if not message and last_tool:
            message = f"Using {main_api._short_tool_name(str(last_tool))}"
        _update_agent_progress(
            {
                **progress,
                "phase": progress.get("phase") or "running",
                "message": message or "Native Planner is exploring the browser",
                "browser_tool_calls": progress.get("browser_tool_calls", browser_tool_calls),
            }
        )

    _set_job_message("Running Native Planner (browser exploration)...")
    _update_agent_progress(
        {
            "phase": "running",
            "message": "Running Native Planner (browser exploration)...",
            "browser_tool_calls": browser_tool_calls,
        }
    )

    planner = NativePlanner(
        project_id=project_id,
        on_tool_use=_on_planner_tool_use if agent_run_id else None,
        on_progress=_on_planner_progress if agent_run_id else None,
        on_task_enqueued=_on_planner_task_enqueued if agent_run_id else None,
        owner_type="agent_run" if agent_run_id else None,
        owner_id=agent_run_id,
        owner_label=f"Requirement spec {context.requirement.req_code}" if agent_run_id else None,
        session_dir=context.planner_session_dir,
        cwd=context.planner_session_dir,
    )
    spec_path = await planner.generate_spec_from_flow_context(
        flow_title=f"{context.requirement.req_code}: {context.requirement.title}",
        flow_context=context.flow_context,
        target_url=context.target_url,
        login_url=request.login_url,
        credentials=request.credentials,
        auth_context=context.auth_context,
        output_dir=context.specs_dir,
    )

    spec_content = await asyncio.to_thread(spec_path.read_text) if await asyncio.to_thread(spec_path.exists) else ""

    specs_base_dir = project_root / "specs"
    relative_spec_name = str(spec_path.relative_to(specs_base_dir))
    with next(get_session()) as db:
        existing = get_spec_metadata(db, relative_spec_name, project_id)
        if not existing:
            meta = DBSpecMetadata(spec_name=relative_spec_name, project_id=project_id, tags_json="[]")
            db.add(meta)
            logger.info(f"Registered spec in DBSpecMetadata: {relative_spec_name} -> project_id={project_id}")
        db.commit()

    logger.info(
        f"Creating RTM entry: req_id={req_id}, spec_name={context.spec_name}, spec_path={spec_path}, project_id={project_id}"
    )
    rtm_entry = store.store_rtm_entry(
        requirement_id=req_id,
        test_spec_name=context.spec_name,
        test_spec_path=str(spec_path),
        mapping_type="full",
        confidence=1.0,
        coverage_notes=f"Auto-generated from requirement {context.requirement.req_code}",
    )
    logger.info(f"RTM entry created successfully: id={rtm_entry.id}, requirement_id={rtm_entry.requirement_id}")

    response = GenerateSpecFromRequirementResponse(
        status="generated",
        spec_path=str(spec_path),
        spec_name=context.spec_name,
        spec_content=spec_content,
        requirement_id=req_id,
        requirement_code=context.requirement.req_code,
        rtm_entry_id=rtm_entry.id,
        generated_at=datetime.utcnow().isoformat(),
        cached=False,
        truth_state=context.truth_state,
        generation_warning=context.generation_warning,
        generation_allowed=True,
    )

    if agent_run_id:
        with next(get_session()) as db:
            run = db.get(AgentRun, agent_run_id)
            if run:
                run.status = "completed"
                run.completed_at = datetime.utcnow()
                run.result = {
                    "summary": f"Generated spec for {context.requirement.req_code}",
                    "spec_path": str(spec_path),
                    "spec_name": context.spec_name,
                    "spec_content": spec_content,
                    "requirement_id": req_id,
                    "requirement_code": context.requirement.req_code,
                    "rtm_entry_id": rtm_entry.id,
                    "pipeline": "native_planner_generator",
                }
                run.progress = {
                    **(run.progress or {}),
                    "phase": "completed",
                    "status": "completed",
                    "message": "Spec generation complete",
                    "has_browser_tools": True,
                    "browser_tool_calls": browser_tool_calls,
                    **browser_runtime_status(),
                    "updated_at": datetime.utcnow().isoformat(),
                }
                db.add(run)
                db.commit()
        _record_event(
            "completed",
            "Spec generation complete.",
            {"spec_path": str(spec_path), "requirement_id": req_id, "requirement_code": context.requirement.req_code},
        )

    return response


async def _run_requirement_spec_generation_job(
    job_id: str,
    req_id: int,
    request: GenerateSpecFromRequirementRequest,
    project_id: str,
    context: RequirementSpecGenerationContext,
    agent_run_id: str,
) -> None:
    from orchestrator.api.db import get_session
    from orchestrator.api.models_db import AgentRun
    from orchestrator.utils.playwright_mcp import browser_runtime_status

    try:
        result = await _execute_requirement_spec_generation(
            req_id,
            request,
            project_id,
            context,
            job_id=job_id,
            agent_run_id=agent_run_id,
        )
        _req_spec_jobs[job_id].update(
            {
                "status": "completed",
                "message": "Spec generation complete",
                "completed_at": time.time(),
                "result": _dump_model(result),
            }
        )
    except Exception as exc:
        message = str(exc)
        logger.error(f"Requirement spec generation job failed: {message}", exc_info=True)
        _req_spec_jobs[job_id].update(
            {
                "status": "failed",
                "message": message,
                "completed_at": time.time(),
            }
        )
        with next(get_session()) as db:
            run = db.get(AgentRun, agent_run_id)
            if run:
                run.status = "failed"
                run.completed_at = datetime.utcnow()
                run.result = {
                    "error": message,
                    "requirement_id": req_id,
                    "requirement_code": getattr(context.requirement, "req_code", None),
                }
                run.progress = {
                    **(run.progress or {}),
                    "phase": "failed",
                    "status": "failed",
                    "message": message,
                    "has_browser_tools": True,
                    **browser_runtime_status(),
                    "updated_at": datetime.utcnow().isoformat(),
                }
                db.add(run)
                db.commit()
        try:
            from orchestrator.api import main as main_api

            main_api._record_agent_run_event(
                agent_run_id,
                event_type="failed",
                level="error",
                message=message,
                payload={"requirement_id": req_id, "requirement_code": getattr(context.requirement, "req_code", None)},
            )
        except Exception as event_exc:
            logger.debug("Failed to record requirement spec failure event: %s", event_exc)


# ========== API Endpoints ==========

# NOTE: Specific GET routes must be defined BEFORE the parameterized /{req_id} route
# to avoid FastAPI matching "duplicates", "stats", etc. as req_id values.


@router.get("", response_model=PaginatedRequirementsResponse)
async def list_requirements(
    project_id: str = Query(default="default"),
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    truth_state: str | None = Query(default=None),
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
    from orchestrator.memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    requirements, total = store.get_requirements_paginated(
        category=category,
        status=status,
        truth_state=truth_state,
        priority=priority,
        search=search,
        limit=limit,
        offset=offset,
    )

    items = [_requirement_to_response(r) for r in requirements]

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
    from orchestrator.memory.exploration_store import get_exploration_store
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
    from orchestrator.memory.exploration_store import get_exploration_store

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
    from orchestrator.memory.exploration_store import get_exploration_store

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
    - Claude authentication is configured
    - OPENAI_API_KEY is set (for embeddings)
    - Database is connected
    - Claude SDK can be imported
    """
    import os

    errors = []

    # Check runtime AI auth. Claude Code subscription auth in Docker uses
    # CLAUDE_CODE_OAUTH_TOKEN; direct provider calls prefer QUORVEX_LLM_*.
    anthropic_token_set = bool(
        os.environ.get("QUORVEX_LLM_API_KEY")
        or os.environ.get("QUORVEX_LLM_API_KEYS")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    )
    if not anthropic_token_set:
        errors.append("Runtime AI auth not set - AI generation will fail")

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
async def get_requirement(req_id: int, project_id: str = Query(...)):
    """Get a specific requirement by ID."""
    from orchestrator.memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    requirement = store.get_requirement(req_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    return _requirement_to_response(requirement)


@router.post("", response_model=RequirementResponse)
async def create_requirement(request: RequirementCreate, project_id: str = Query(...)):
    """Create a new requirement manually."""
    from orchestrator.memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    req_code = store.get_next_requirement_code()

    requirement = store.store_requirement(
        req_code=req_code,
        title=request.title,
        description=request.description,
        category=request.category,
        priority=request.priority,
        acceptance_criteria=request.acceptance_criteria,
        truth_state=request.truth_state,
        source_type=request.source_type,
        confidence=request.confidence,
        uncertainty_reason=request.uncertainty_reason,
    )

    return _requirement_to_response(requirement)


class BulkRequirementCreate(BaseModel):
    """Request to bulk create requirements."""

    items: list[RequirementCreate] = Field(..., min_length=1, max_length=500)


class BulkCreateResponse(BaseModel):
    """Response from bulk requirement creation."""

    created: int
    requirements: list[RequirementResponse]


@router.post("/bulk", response_model=BulkCreateResponse)
async def bulk_create_requirements(request: BulkRequirementCreate, project_id: str = Query(...)):
    """Bulk create multiple requirements in a single request."""
    from orchestrator.memory.exploration_store import get_exploration_store

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
            truth_state=item.truth_state,
            source_type=item.source_type,
            confidence=item.confidence,
            uncertainty_reason=item.uncertainty_reason,
        )
        created_reqs.append(_requirement_to_response(requirement))

    return BulkCreateResponse(created=len(created_reqs), requirements=created_reqs)


@router.put("/{req_id}", response_model=RequirementResponse)
async def update_requirement(req_id: int, request: RequirementUpdate, project_id: str = Query(...)):
    """Update an existing requirement."""
    from orchestrator.memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    # Build update dict from non-None fields
    updates = {k: v for k, v in request.dict().items() if v is not None}

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    requirement = store.update_requirement(req_id, **updates)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    return _requirement_to_response(requirement)


def _update_requirement_truth_decision(
    req_id: int,
    *,
    project_id: str,
    truth_state: str,
    status: str,
    actor: str | None,
    comment: str | None,
):
    from sqlmodel import select

    from orchestrator.api.db import get_session
    from orchestrator.api.models_db import (
        AutonomousFinding,
        AutonomousMission,
        AutonomousTestProposal,
        Requirement,
    )
    from orchestrator.services.autonomous_events import create_autonomous_agent_event

    with next(get_session()) as db:
        requirement = db.get(Requirement, req_id)
        if not requirement or requirement.project_id != project_id:
            raise HTTPException(status_code=404, detail="Requirement not found")

        now = datetime.utcnow()
        requirement.truth_state = truth_state
        requirement.status = status
        requirement.confidence = 1.0 if truth_state == "confirmed_requirement" else max(float(requirement.confidence or 0.7), 0.6)
        requirement.uncertainty_reason = comment if truth_state != "confirmed_requirement" else None
        requirement.updated_at = now
        if truth_state == "confirmed_requirement":
            requirement.confirmed_by = actor
            requirement.confirmed_at = now
            requirement.rejected_by = None
            requirement.rejected_at = None
            requirement.source_type = "human_approval"
        elif truth_state == "rejected_requirement":
            requirement.rejected_by = actor
            requirement.rejected_at = now
        db.add(requirement)

        affected_finding_ids: list[str] = []
        affected_proposal_ids: list[str] = []
        affected_mission_ids: set[str] = set()
        propagation = {
            "requirement_id": requirement.id,
            "requirement_code": requirement.req_code,
            "truth_state": truth_state,
            "status": status,
            "actor": actor,
            "comment": comment,
            "propagated_at": now.isoformat(),
        }

        findings = db.exec(select(AutonomousFinding).where(AutonomousFinding.project_id == project_id)).all()
        for finding in findings:
            evidence = dict(finding.evidence or {})
            try:
                linked_requirement_id = int(evidence.get("requirement_id"))
            except (TypeError, ValueError):
                continue
            if linked_requirement_id != req_id:
                continue
            evidence["requirement_review"] = propagation
            if truth_state == "confirmed_requirement":
                evidence["requirement_truth_state"] = truth_state
                evidence.pop("generation_warning", None)
            elif truth_state == "rejected_requirement":
                evidence["requirement_truth_state"] = truth_state
                evidence["generation_warning"] = "Linked requirement was rejected by human review."
                if finding.status in {"open", "awaiting_approval"}:
                    finding.status = "rejected"
            else:
                evidence["requirement_truth_state"] = truth_state
                evidence["generation_warning"] = "Linked requirement was marked stale by human review."
            finding.evidence = evidence
            finding.updated_at = now
            db.add(finding)
            affected_finding_ids.append(finding.id)
            if finding.mission_id:
                affected_mission_ids.add(finding.mission_id)

        proposals = db.exec(select(AutonomousTestProposal).where(AutonomousTestProposal.project_id == project_id)).all()
        for proposal in proposals:
            metadata = dict(proposal.source_metadata or {})
            try:
                linked_requirement_id = int(metadata.get("requirement_id"))
            except (TypeError, ValueError):
                linked_requirement_id = None
            if linked_requirement_id != req_id and proposal.finding_id not in affected_finding_ids:
                continue
            metadata["requirement_review"] = propagation
            metadata["requirement_id"] = requirement.id
            metadata["requirement_code"] = requirement.req_code
            metadata["requirement_truth_state"] = truth_state
            metadata["generation_allowed"] = True
            if truth_state == "confirmed_requirement":
                metadata["generation_warning"] = None
            elif truth_state == "rejected_requirement":
                metadata["generation_warning"] = "Linked requirement was rejected by human review."
                if proposal.approval_status == "pending":
                    proposal.approval_status = "rejected"
                    proposal.rejected_at = now
                    proposal.rejected_by = actor
            else:
                metadata["generation_warning"] = "Linked requirement was marked stale by human review."
            proposal.source_metadata = metadata
            proposal.updated_at = now
            db.add(proposal)
            affected_proposal_ids.append(proposal.id)
            if proposal.mission_id:
                affected_mission_ids.add(proposal.mission_id)

        db.commit()
        for mission_id in affected_mission_ids:
            mission = db.get(AutonomousMission, mission_id)
            if not mission:
                continue
            create_autonomous_agent_event(
                project_id=project_id,
                mission_id=mission.id,
                run_id=mission.latest_run_id,
                event_type="requirement_propagation",
                message=f"Requirement {requirement.req_code} marked {truth_state.replace('_', ' ')} and propagated to autonomous artifacts.",
                payload={
                    "requirement_id": requirement.id,
                    "requirement_code": requirement.req_code,
                    "truth_state": truth_state,
                    "finding_ids": affected_finding_ids,
                    "proposal_ids": affected_proposal_ids,
                    "finding_count": len(affected_finding_ids),
                    "proposal_count": len(affected_proposal_ids),
                    "actor": actor,
                    "comment": comment,
                },
                session=db,
            )
        db.refresh(requirement)
        return requirement


@router.post("/review/decisions", response_model=RequirementReviewDecisionsResponse)
async def review_requirement_decisions(
    request: RequirementReviewDecisionsRequest,
    project_id: str = Query(...),
):
    """Apply multiple human truth-state decisions to requirements."""

    updated: list[RequirementResponse] = []
    errors: list[dict] = []
    for decision in request.decisions:
        actor = decision.user or request.user
        comment = decision.comment if decision.comment is not None else request.comment
        normalized = decision.decision.lower()
        try:
            if normalized in {"confirm", "confirmed", "approve", "approved"}:
                requirement = _update_requirement_truth_decision(
                    decision.req_id,
                    project_id=project_id,
                    truth_state="confirmed_requirement",
                    status="confirmed",
                    actor=actor,
                    comment=comment,
                )
            elif normalized in {"reject", "rejected"}:
                requirement = _update_requirement_truth_decision(
                    decision.req_id,
                    project_id=project_id,
                    truth_state="rejected_requirement",
                    status="rejected",
                    actor=actor,
                    comment=comment or "Rejected by human review.",
                )
            else:
                requirement = _update_requirement_truth_decision(
                    decision.req_id,
                    project_id=project_id,
                    truth_state="stale_requirement",
                    status="stale",
                    actor=actor,
                    comment=comment or "Marked stale by human review.",
                )
            updated.append(_requirement_to_response(requirement))
        except HTTPException as exc:
            errors.append({"req_id": decision.req_id, "error": exc.detail, "status_code": exc.status_code})
        except Exception as exc:
            logger.exception("Requirement review decision failed for %s", decision.req_id)
            errors.append({"req_id": decision.req_id, "error": str(exc), "status_code": 500})

    return RequirementReviewDecisionsResponse(updated=len(updated), requirements=updated, errors=errors)


@router.post("/{req_id}/confirm", response_model=RequirementResponse)
async def confirm_requirement(
    req_id: int,
    request: RequirementTruthDecisionRequest | None = None,
    project_id: str = Query(...),
):
    payload = request or RequirementTruthDecisionRequest()
    requirement = _update_requirement_truth_decision(
        req_id,
        project_id=project_id,
        truth_state="confirmed_requirement",
        status="confirmed",
        actor=payload.user,
        comment=payload.comment,
    )
    return _requirement_to_response(requirement)


@router.post("/{req_id}/reject", response_model=RequirementResponse)
async def reject_requirement(
    req_id: int,
    request: RequirementTruthDecisionRequest | None = None,
    project_id: str = Query(...),
):
    payload = request or RequirementTruthDecisionRequest()
    requirement = _update_requirement_truth_decision(
        req_id,
        project_id=project_id,
        truth_state="rejected_requirement",
        status="rejected",
        actor=payload.user,
        comment=payload.comment or "Rejected by human review.",
    )
    return _requirement_to_response(requirement)


@router.post("/{req_id}/mark-stale", response_model=RequirementResponse)
async def mark_requirement_stale(
    req_id: int,
    request: RequirementTruthDecisionRequest | None = None,
    project_id: str = Query(...),
):
    payload = request or RequirementTruthDecisionRequest()
    requirement = _update_requirement_truth_decision(
        req_id,
        project_id=project_id,
        truth_state="stale_requirement",
        status="stale",
        actor=payload.user,
        comment=payload.comment or "Marked stale by human review.",
    )
    return _requirement_to_response(requirement)


@router.delete("/{req_id}")
async def delete_requirement(req_id: int, project_id: str = Query(...)):
    """Delete a requirement."""
    from sqlmodel import select

    from api.db import get_session
    from api.models_db import Requirement, RequirementSource, RtmEntry

    with next(get_session()) as db:
        requirement = db.get(Requirement, req_id)
        if not requirement or requirement.project_id != project_id:
            raise HTTPException(status_code=404, detail="Requirement not found")

        # Delete related RTM entries
        rtm_entries = db.exec(
            select(RtmEntry).where(
                RtmEntry.requirement_id == req_id,
                RtmEntry.project_id == project_id,
            )
        ).all()
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


async def _run_requirements_generation(
    job_id: str,
    project_id: str,
    session_id: str,
    mode: str = "single_agent",
    max_agents: int = 3,
    browser_verification: str = "off",
):
    """Background task for requirements generation."""
    import traceback

    from orchestrator.services.domain_jobs import update_domain_job
    from workflows.requirements_generator import RequirementsGenerator

    job_state = _req_gen_jobs.setdefault(
        job_id,
        {
            "status": "queued",
            "project_id": project_id,
            "session_id": session_id,
            "created_at": time.time(),
        },
    )
    job_state["status"] = "running"
    job_state["started_at"] = time.time()
    update_domain_job(job_id, status="running", started=True)

    try:
        generator = RequirementsGenerator(project_id=project_id)
        result = await generator.generate_from_exploration(
            exploration_session_id=session_id,
            mode=mode,
            max_agents=max_agents,
            browser_verification=browser_verification,
        )

        logger.info(f"Requirements generation completed: {result.total_requirements} requirements generated")

        # Build response data
        from orchestrator.memory.exploration_store import get_exploration_store

        store = get_exploration_store(project_id=project_id)
        requirements = store.get_requirements()

        result_payload = {
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
                    "truth_state": _requirement_truth_state(r),
                    "source_type": _requirement_source_type(r),
                    "confidence": _requirement_confidence(r),
                    "uncertainty_reason": _requirement_uncertainty_reason(r),
                    "acceptance_criteria": r.acceptance_criteria,
                    "source_session_id": r.source_session_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in requirements
            ],
        }
        if mode != "single_agent" or browser_verification != "off":
            result_payload["generation"] = {
                "mode": result.telemetry.mode,
                "subagents": result.telemetry.subagents,
                "items_total": result.telemetry.evidence_packets,
                "requirements_generated": result.telemetry.requirements_generated,
                "verification_status": result.telemetry.verification_status,
            }
        job_state["status"] = "completed"
        job_state["completed_at"] = time.time()
        job_state["result"] = result_payload
        update_domain_job(job_id, status="completed", result=result_payload, completed=True)
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        logger.error(f"Requirements generation failed: {error_type}: {error_msg}")
        logger.error(f"Stack trace:\n{traceback.format_exc()}")
        job_state["status"] = "failed"
        job_state["completed_at"] = time.time()
        job_state["error"] = f"{error_type}: {error_msg}"
        update_domain_job(job_id, status="failed", error=job_state["error"], completed=True)


@router.post("/generate")
async def generate_requirements(
    request: GenerateRequirementsRequest, project_id: str = Query(...)
):
    """
    Generate requirements from an exploration session (async).

    Returns a job_id immediately. Poll GET /requirements/generate-jobs/{job_id}
    for status and results.
    """
    _cleanup_old_req_jobs()

    job_id = str(uuid.uuid4())
    from orchestrator.services.domain_jobs import create_domain_job

    create_domain_job(
        job_id=job_id,
        job_type="requirements_generate",
        project_id=project_id,
        payload={
            "project_id": project_id,
            "session_id": request.exploration_session_id,
            "mode": request.mode,
            "max_agents": request.max_agents,
            "browser_verification": request.browser_verification,
        },
    )
    _req_gen_jobs[job_id] = {
        "status": "queued",
        "project_id": project_id,
        "session_id": request.exploration_session_id,
        "mode": request.mode,
        "max_agents": request.max_agents,
        "browser_verification": request.browser_verification,
        "created_at": time.time(),
    }

    logger.info(
        f"Requirements generation queued: job_id={job_id}, session_id={request.exploration_session_id}, project_id={project_id}"
    )

    try:
        from orchestrator.services.domain_jobs import update_domain_job
        from orchestrator.services.temporal_client import start_domain_job_workflow

        temporal = await start_domain_job_workflow(
            "requirements_generate",
            job_id,
            {
                "project_id": project_id,
                "session_id": request.exploration_session_id,
                "mode": request.mode,
                "max_agents": request.max_agents,
                "browser_verification": request.browser_verification,
            },
        )
        _req_gen_jobs[job_id]["temporal_workflow_id"] = temporal.workflow_id
        _req_gen_jobs[job_id]["temporal_run_id"] = temporal.run_id
        update_domain_job(
            job_id,
            temporal_workflow_id=temporal.workflow_id,
            temporal_run_id=temporal.run_id,
        )
    except Exception as exc:
        _req_gen_jobs[job_id]["status"] = "failed"
        _req_gen_jobs[job_id]["completed_at"] = time.time()
        _req_gen_jobs[job_id]["error"] = f"Temporal start failed: {exc}"
        update_domain_job(job_id, status="failed", error=_req_gen_jobs[job_id]["error"], completed=True)
        raise HTTPException(status_code=503, detail=f"Temporal is required for requirements generation: {exc}") from exc

    return {
        "job_id": job_id,
        "status": "queued",
        "temporal_workflow_id": _req_gen_jobs[job_id].get("temporal_workflow_id"),
        "temporal_run_id": _req_gen_jobs[job_id].get("temporal_run_id"),
    }


@router.get("/generate-jobs/{job_id}")
async def get_generate_job_status(job_id: str, project_id: str = Query(...)):
    """Poll requirements generation job status."""
    from orchestrator.services.domain_jobs import domain_job_to_dict, get_domain_job

    durable_job = get_domain_job(job_id)
    if durable_job and durable_job.job_type == "requirements_generate":
        _ensure_job_project(durable_job.project_id, project_id)
        return domain_job_to_dict(durable_job)

    job = _req_gen_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _ensure_job_project(job.get("project_id"), project_id)

    response = {
        "job_id": job_id,
        "status": job["status"],
        "project_id": job.get("project_id"),
        "session_id": job.get("session_id"),
        "temporal_workflow_id": job.get("temporal_workflow_id"),
        "temporal_run_id": job.get("temporal_run_id"),
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
    from orchestrator.memory.exploration_store import get_exploration_store
    from orchestrator.services.domain_jobs import update_domain_job

    job_state = _bulk_gen_jobs.setdefault(
        job_id,
        {
            "status": "queued",
            "project_id": project_id,
            "target_url": target_url,
            "created_at": time.time(),
            "total": 0,
            "completed": 0,
            "failed": 0,
            "results": [],
            "error": None,
        },
    )
    job_state["status"] = "running"
    job_state["started_at"] = time.time()
    update_domain_job(
        job_id,
        status="running",
        progress={
            "total": job_state.get("total", 0),
            "completed": job_state.get("completed", 0),
            "failed": job_state.get("failed", 0),
            "results": job_state.get("results", []),
            "error": job_state.get("error"),
        },
        started=True,
    )

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

        job_state["total"] = len(uncovered)
        update_domain_job(
            job_id,
            progress={
                "total": job_state["total"],
                "completed": job_state["completed"],
                "failed": job_state["failed"],
                "results": job_state["results"],
                "error": job_state.get("error"),
            },
        )

        if not uncovered:
            job_state["status"] = "completed"
            job_state["completed_at"] = time.time()
            result_payload = {
                "total": job_state["total"],
                "completed": job_state["completed"],
                "failed": job_state["failed"],
                "results": job_state["results"],
            }
            update_domain_job(job_id, status="completed", progress=result_payload, result=result_payload, completed=True)
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

                job_state["completed"] += 1
                job_state["results"].append(
                    {
                        "req_code": req.req_code,
                        "req_id": req.id,
                        "status": result.status,
                        "spec_name": result.spec_name,
                        "error": None,
                    }
                )
            except Exception as e:
                job_state["failed"] += 1
                job_state["results"].append(
                    {"req_code": req.req_code, "req_id": req.id, "status": "failed", "spec_name": None, "error": str(e)}
                )
                logger.warning(f"Bulk spec generation failed for {req.req_code}: {e}")
            update_domain_job(
                job_id,
                progress={
                    "total": job_state["total"],
                    "completed": job_state["completed"],
                    "failed": job_state["failed"],
                    "results": job_state["results"],
                    "error": job_state.get("error"),
                },
            )

        job_state["status"] = "completed"
        job_state["completed_at"] = time.time()
        result_payload = {
            "total": job_state["total"],
            "completed": job_state["completed"],
            "failed": job_state["failed"],
            "results": job_state["results"],
        }
        update_domain_job(job_id, status="completed", progress=result_payload, result=result_payload, completed=True)

    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        logger.error(f"Bulk spec generation failed: {error_type}: {error_msg}")
        logger.error(f"Stack trace:\n{traceback.format_exc()}")
        job_state["status"] = "failed"
        job_state["completed_at"] = time.time()
        job_state["error"] = f"{error_type}: {error_msg}"
        update_domain_job(
            job_id,
            status="failed",
            progress={
                "total": job_state.get("total", 0),
                "completed": job_state.get("completed", 0),
                "failed": job_state.get("failed", 0),
                "results": job_state.get("results", []),
                "error": job_state.get("error"),
            },
            error=job_state["error"],
            completed=True,
        )


@router.post("/bulk-generate-specs")
async def bulk_generate_specs(
    request: BulkGenerateSpecsRequest, project_id: str = Query(...)
):
    """
    Generate specs for all uncovered requirements (async).

    Finds requirements without RTM entries and generates test specs for each.
    Returns a job_id immediately. Poll GET /requirements/bulk-generate-jobs/{job_id}.
    """
    _cleanup_old_req_jobs()

    job_id = str(uuid.uuid4())
    from orchestrator.services.domain_jobs import create_domain_job

    create_domain_job(
        job_id=job_id,
        job_type="requirements_bulk_generate",
        project_id=project_id,
        payload={
            "project_id": project_id,
            "target_url": request.target_url,
            "login_url": request.login_url,
            "credentials": request.credentials,
        },
        progress={"total": 0, "completed": 0, "failed": 0, "results": [], "error": None},
    )
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

    try:
        from orchestrator.services.domain_jobs import update_domain_job
        from orchestrator.services.temporal_client import start_domain_job_workflow

        temporal = await start_domain_job_workflow(
            "requirements_bulk_generate",
            job_id,
            {
                "project_id": project_id,
                "target_url": request.target_url,
                "login_url": request.login_url,
                "credentials": request.credentials,
            },
        )
        _bulk_gen_jobs[job_id]["temporal_workflow_id"] = temporal.workflow_id
        _bulk_gen_jobs[job_id]["temporal_run_id"] = temporal.run_id
        update_domain_job(
            job_id,
            temporal_workflow_id=temporal.workflow_id,
            temporal_run_id=temporal.run_id,
        )
    except Exception as exc:
        _bulk_gen_jobs[job_id]["status"] = "failed"
        _bulk_gen_jobs[job_id]["completed_at"] = time.time()
        _bulk_gen_jobs[job_id]["error"] = f"Temporal start failed: {exc}"
        update_domain_job(job_id, status="failed", error=_bulk_gen_jobs[job_id]["error"], completed=True)
        raise HTTPException(status_code=503, detail=f"Temporal is required for bulk spec generation: {exc}") from exc

    return {
        "job_id": job_id,
        "status": "queued",
        "temporal_workflow_id": _bulk_gen_jobs[job_id].get("temporal_workflow_id"),
        "temporal_run_id": _bulk_gen_jobs[job_id].get("temporal_run_id"),
    }


@router.get("/bulk-generate-jobs/{job_id}")
async def get_bulk_generate_job_status(job_id: str, project_id: str = Query(...)):
    """Poll bulk spec generation job status."""
    from orchestrator.services.domain_jobs import domain_job_to_dict, get_domain_job

    durable_job = get_domain_job(job_id)
    if durable_job and durable_job.job_type == "requirements_bulk_generate":
        _ensure_job_project(durable_job.project_id, project_id)
        response = domain_job_to_dict(durable_job)
        response.setdefault("total", 0)
        response.setdefault("completed", 0)
        response.setdefault("failed", 0)
        response.setdefault("results", [])
        response.setdefault("error", None)
        return response

    job = _bulk_gen_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _ensure_job_project(job.get("project_id"), project_id)

    return {
        "job_id": job_id,
        "status": job["status"],
        "total": job.get("total", 0),
        "completed": job.get("completed", 0),
        "failed": job.get("failed", 0),
        "results": job.get("results", []),
        "error": job.get("error"),
        "temporal_workflow_id": job.get("temporal_workflow_id"),
        "temporal_run_id": job.get("temporal_run_id"),
    }


@router.post("/check-duplicate", response_model=CheckDuplicateResponse)
async def check_duplicate(request: CheckDuplicateRequest, project_id: str = Query(default="default")):
    """
    Check if a requirement title/description matches existing requirements.

    Returns exact matches and semantically similar requirements to help
    prevent duplicate creation.
    """
    from orchestrator.memory.exploration_store import get_exploration_store
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
            exact_match_response = _requirement_to_response(req)

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
async def merge_requirements(request: MergeRequest, project_id: str = Query(...)):
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
            raise HTTPException(status_code=404, detail="Canonical requirement not found")

        # Get duplicate requirements
        duplicates = []
        for dup_id in request.duplicate_ids:
            dup = db.get(Requirement, dup_id)
            if not dup:
                raise HTTPException(status_code=404, detail=f"Duplicate requirement {dup_id} not found")
            if dup.project_id != project_id:
                raise HTTPException(status_code=404, detail=f"Duplicate requirement {dup_id} not found")
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
            canonical=_requirement_to_response(canonical),
            merged_count=len(deleted_ids),
            deleted_ids=deleted_ids,
        )


# ========== Spec Generation Endpoints ==========


@router.get("/{req_id}/spec-status", response_model=SpecStatusResponse)
async def get_spec_status(req_id: int, project_id: str = Query(...)):
    """
    Check if a spec has been generated for this requirement.

    Returns information about existing spec and RTM entry if any.
    """
    from sqlmodel import select

    from orchestrator.memory.exploration_store import get_exploration_store
    from orchestrator.api.db import get_session
    from orchestrator.api.models_db import RtmEntry

    store = get_exploration_store(project_id=project_id)

    # Get the requirement
    requirement = store.get_requirement(req_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")
    truth_state = _requirement_truth_state(requirement)
    generation_warning = _requirement_generation_warning(requirement)

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
                truth_state=truth_state,
                generation_warning=generation_warning,
                generation_allowed=True,
            )

    return SpecStatusResponse(
        has_spec=False,
        truth_state=truth_state,
        generation_warning=generation_warning,
        generation_allowed=True,
    )


@router.post("/{req_id}/generate-spec-jobs")
async def start_generate_spec_job(
    req_id: int,
    request: GenerateSpecFromRequirementRequest,
    background_tasks: BackgroundTasks,
    project_id: str = Query(...),
):
    """Start async browser-backed spec generation for the RTM/requirements modal."""
    from orchestrator.memory.exploration_store import get_exploration_store
    from orchestrator.api.db import get_session
    from orchestrator.api.models_db import AgentRun
    from orchestrator.utils.agent_tool_allowlists import get_agent_allowed_tools
    from orchestrator.utils.playwright_mcp import browser_runtime_status

    _cleanup_old_req_jobs()

    store = get_exploration_store(project_id=project_id)
    requirement = store.get_requirement(req_id)
    if not requirement:
        raise HTTPException(status_code=404, detail="Requirement not found")

    truth_state = _requirement_truth_state(requirement)
    generation_warning = _requirement_generation_warning(requirement)
    cached = await _cached_requirement_spec_response(req_id, request, project_id, requirement, truth_state, generation_warning)
    if cached:
        return {"status": "cached", "result": _dump_model(cached)}

    job_id = f"reqspec-{req_id}-{uuid.uuid4().hex[:8]}"
    agent_run_id = job_id
    run_dir = Path(__file__).resolve().parent.parent.parent / "runs" / agent_run_id

    context = await _prepare_requirement_spec_generation(
        req_id,
        request,
        project_id,
        planner_session_dir=run_dir,
        prepare_mcp=True,
    )
    browser_metadata = browser_runtime_status()
    allowed_tools = get_agent_allowed_tools("playwright-test-planner", mcp_config_dir=run_dir)

    agent_run = AgentRun(
        id=agent_run_id,
        agent_type="spec_generation",
        runtime="claude_sdk",
        status="running",
        started_at=datetime.utcnow(),
        project_id=project_id,
    )
    agent_run.config = {
        "source": "requirement",
        "requirement_id": req_id,
        "requirement_code": context.requirement.req_code,
        "flow_title": context.requirement.title,
        "project_id": project_id,
        "url": context.target_url,
        "target_url": context.target_url,
        "login_url": request.login_url,
        "test_data_refs": request.test_data_refs,
        "allowed_tools": allowed_tools,
        **context.browser_auth_metadata,
    }
    agent_run.progress = {
        "phase": "queued",
        "status": "running",
        "message": "Starting Native Planner spec generation...",
        "has_browser_tools": True,
        "browser_tool_calls": 0,
        **browser_metadata,
        **context.browser_auth_metadata,
        **context.mcp_runtime,
        "updated_at": datetime.utcnow().isoformat(),
    }
    with next(get_session()) as db:
        db.add(agent_run)
        db.commit()

    try:
        from orchestrator.api import main as main_api

        main_api._record_agent_run_event(
            agent_run_id,
            event_type="started",
            message="Started Native Planner spec generation.",
            payload={"requirement_id": req_id, "requirement_code": context.requirement.req_code},
        )
    except Exception as exc:
        logger.debug("Failed to record requirement spec start event: %s", exc)

    _req_spec_jobs[job_id] = {
        "status": "running",
        "message": "Spec generation started. Poll for status.",
        "started_at": time.time(),
        "requirement_id": req_id,
        "project_id": project_id,
        "agent_run_id": agent_run_id,
    }

    background_tasks.add_task(
        _run_requirement_spec_generation_job,
        job_id,
        req_id,
        request,
        project_id,
        context,
        agent_run_id,
    )

    return {
        "status": "running",
        "job_id": job_id,
        "agent_run_id": agent_run_id,
        "message": "Spec generation started. Poll for status.",
    }


@router.get("/generate-spec-jobs/{job_id}")
async def get_generate_spec_job_status(job_id: str, project_id: str = Query(...)):
    """Poll async requirement spec generation status."""
    from orchestrator.api.db import get_session
    from orchestrator.api.models_db import AgentRun

    job = _req_spec_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _ensure_job_project(job.get("project_id"), project_id)

    response = {
        "job_id": job_id,
        "status": job.get("status"),
        "message": job.get("message"),
        "agent_run_id": job.get("agent_run_id"),
        "agent_task_id": job.get("agent_task_id"),
        "result": job.get("result"),
    }
    agent_run_id = job.get("agent_run_id")
    if agent_run_id:
        with next(get_session()) as db:
            agent_run = db.get(AgentRun, agent_run_id)
            if agent_run:
                try:
                    from orchestrator.api import main as main_api

                    response["agent_run"] = main_api._serialize_agent_run(agent_run, db)
                except Exception as exc:
                    logger.debug("Failed to serialize requirement spec AgentRun %s: %s", agent_run_id, exc)
                    response["agent_run"] = {
                        "id": agent_run.id,
                        "agent_type": agent_run.agent_type,
                        "status": agent_run.status,
                        "config": agent_run.config,
                        "progress": agent_run.progress,
                        "result": agent_run.result,
                        "agent_task_id": agent_run.agent_task_id,
                    }
                response["agent_task_id"] = response.get("agent_task_id") or agent_run.agent_task_id
    return response


@router.post("/{req_id}/generate-spec", response_model=GenerateSpecFromRequirementResponse)
async def generate_spec_from_requirement(
    req_id: int, request: GenerateSpecFromRequirementRequest, project_id: str = Query(...)
):
    """
    Generate a test spec from a requirement using AI browser exploration.

    This compatibility endpoint remains synchronous. The RTM modal uses
    /requirements/{req_id}/generate-spec-jobs for live browser visibility.
    """
    try:
        from orchestrator.memory.exploration_store import get_exploration_store

        store = get_exploration_store(project_id=project_id)
        requirement = store.get_requirement(req_id)
        if not requirement:
            raise HTTPException(status_code=404, detail="Requirement not found")
        truth_state = _requirement_truth_state(requirement)
        generation_warning = _requirement_generation_warning(requirement)
        cached = await _cached_requirement_spec_response(
            req_id,
            request,
            project_id,
            requirement,
            truth_state,
            generation_warning,
        )
        if cached:
            return cached
        context = await _prepare_requirement_spec_generation(req_id, request, project_id)
        return await _execute_requirement_spec_generation(req_id, request, project_id, context)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Spec generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


def _build_flow_context_from_requirement(
    requirement,
    base_url_origin: str = None,
    credential_keys: list = None,
    test_data_markdown: str = "",
) -> str:
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

    if test_data_markdown:
        context_parts.append("")
        context_parts.append(test_data_markdown)

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
