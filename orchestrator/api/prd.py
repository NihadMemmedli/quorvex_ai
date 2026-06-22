"""
PRD Management API Router

Resource Management:
- PRD processing is limited by ResourceManager to prevent resource exhaustion
- Default max concurrent PRD processing: 3 (configurable via MAX_CONCURRENT_PRD env var)
- Requests are queued when all slots are in use
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlmodel import Session, select

from .db import engine
from .models_db import PrdGenerationEvent, PrdGenerationResult, Project, Requirement, SpecMetadata, get_spec_metadata

# Import resource managers - using relative import since we're in orchestrator/api
sys.path.insert(0, str(Path(__file__).parent.parent))
from orchestrator.services.browser_auth_sessions import BrowserAuthSessionError, resolve_browser_auth_for_run
from orchestrator.utils.playwright_mcp import (
    browser_runtime_status,
    live_browser_display_diagnostics,
    prepare_run_playwright_config_content,
    write_playwright_test_mcp_config,
)
from services.browser_pool import OperationType as BrowserOpType
from services.browser_pool import get_browser_pool

logger = logging.getLogger(__name__)


class TeeWriter:
    """Duplicates writes to both original stream and a file."""

    def __init__(self, original_stream, log_file):
        self.original_stream = original_stream
        self.log_file = log_file
        self.encoding = getattr(original_stream, "encoding", "utf-8") or "utf-8"

    def write(self, data):
        # Write to original stream
        if self.original_stream:
            self.original_stream.write(data)
            self.original_stream.flush()
        # Write to log file
        if self.log_file:
            self.log_file.write(data)
            self.log_file.flush()

    def flush(self):
        if self.original_stream:
            self.original_stream.flush()
        if self.log_file:
            self.log_file.flush()

    def fileno(self):
        # Return the original stream's fileno for compatibility
        if self.original_stream:
            return self.original_stream.fileno()
        raise OSError("No original stream available")


@contextmanager
def capture_output_to_file(log_path: Path):
    """Context manager that captures stdout/stderr to a file while also printing to console."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    with open(log_path, "w", encoding="utf-8") as log_file:
        tee_stdout = TeeWriter(original_stdout, log_file)
        tee_stderr = TeeWriter(original_stderr, log_file)

        sys.stdout = tee_stdout
        sys.stderr = tee_stderr

        try:
            yield log_file
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr


# Track running background generation tasks
_running_generations: dict[int, asyncio.Task] = {}

# Base directory (project root, one level up from orchestrator/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = BASE_DIR / "runs"

router = APIRouter(prefix="/api/prd", tags=["prd"])
ACTIVE_GENERATION_STATUSES = {"pending", "queued", "running"}
QUEUE_TERMINAL_FAILURE_STATUSES = {"failed", "timeout"}
QUEUE_TERMINAL_CANCEL_STATUSES = {"cancelled"}
PRD_QUEUE_STALE_GRACE_SECONDS = int(os.environ.get("PRD_QUEUE_STALE_GRACE_SECONDS", "300"))


class FeatureResponse(BaseModel):
    name: str
    slug: str
    requirements: list[str]
    content: str | None = None
    merged_from: list[str] | None = None  # Track consolidated sub-features


class PRDResponse(BaseModel):
    project: str
    features: list[FeatureResponse]
    total_chunks: int
    config: dict | None = None  # Processing configuration used


class GenerateRequest(BaseModel):
    feature: str | None = None
    target_url: str | None = None  # URL for live browser exploration
    login_url: str | None = None  # URL for login page
    credentials: dict | None = None  # {username: str, password: str}
    test_data_refs: list[str] = []
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False


class HealRequest(BaseModel):
    test_path: str
    error_log: str


class GenerationStatusResponse(BaseModel):
    id: int
    prd_project: str
    feature_name: str
    status: str
    target_url: str | None = None
    live_browser_requested: bool = False
    current_stage: str | None = None
    stage_message: str | None = None
    spec_path: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    events_count: int = 0
    latest_event: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = []
    latest_image: dict[str, Any] | None = None
    vnc_url: str | None = None
    browser_runtime: str | None = None
    live_view_available: bool | None = None
    browser_activity_seen: bool = False
    browser_active: bool = False
    browser_last_tool: str | None = None
    suspected_browser_dialog_block: bool = False
    runtime_message: str | None = None
    display_diagnostics: dict[str, Any] | None = None
    agent_task_id: str | None = None
    agent_task_status: str | None = None
    agent_worker_id: str | None = None
    last_heartbeat_at: datetime | None = None
    agent_queue_health: dict[str, Any] | None = None
    queue_telemetry: dict[str, Any] | None = None


class PrdGenerationEventResponse(BaseModel):
    id: int
    generation_id: int
    sequence: int
    role: str
    event_type: str
    level: str
    message: str
    payload: dict[str, Any] = {}
    created_at: datetime


class PrdArtifactResponse(BaseModel):
    name: str
    path: str
    type: str
    modified_at: datetime | None = None


class ImportedRequirementResponse(BaseModel):
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
    created_at: datetime
    updated_at: datetime


class ImportRequirementsResponse(BaseModel):
    created: int
    skipped: int
    total: int
    requirements: list[ImportedRequirementResponse]


def _next_requirement_number(requirements: list[Requirement]) -> int:
    highest = 0
    for requirement in requirements:
        try:
            _, number = requirement.req_code.split("-", 1)
            highest = max(highest, int(number))
        except (AttributeError, ValueError):
            continue
    return highest + 1


def _imported_requirement_to_response(requirement: Requirement) -> ImportedRequirementResponse:
    return ImportedRequirementResponse(
        id=requirement.id,
        req_code=requirement.req_code,
        title=requirement.title,
        description=requirement.description,
        category=requirement.category,
        priority=requirement.priority,
        status=requirement.status,
        truth_state=requirement.truth_state,
        source_type=requirement.source_type,
        confidence=requirement.confidence,
        created_at=requirement.created_at,
        updated_at=requirement.updated_at,
    )


def _is_stale_empty_prd_metadata(meta: dict[str, Any]) -> bool:
    features = meta.get("features")
    try:
        total_chunks = int(meta.get("total_chunks", 0) or 0)
    except (TypeError, ValueError):
        total_chunks = 0
    return isinstance(features, list) and len(features) == 0 and total_chunks == 0


def _generation_project_filter(project_id: str):
    if project_id == "default":
        return or_(PrdGenerationResult.project_id == None, PrdGenerationResult.project_id == "default")
    return PrdGenerationResult.project_id == project_id


def _get_generation_for_project(session: Session, generation_id: int, project_id: str) -> PrdGenerationResult:
    gen = session.exec(
        select(PrdGenerationResult).where(
            PrdGenerationResult.id == generation_id,
            _generation_project_filter(project_id),
        )
    ).first()
    if not gen:
        raise HTTPException(status_code=404, detail="Generation not found")
    return gen


@router.post("/upload", response_model=PRDResponse)
async def upload_prd(
    file: UploadFile = File(...),
    project: str | None = None,
    target_features: int = 15,  # User-configurable target feature count
    tenant_project_id: str | None = None,  # Tenant project association for multi-project isolation
):
    """
    Upload and process a PDF PRD.

    If PRD processing slots are full, the request will wait for a slot
    to become available.

    Args:
        file: PDF file to upload
        project: Optional project name (defaults to filename)
        target_features: Target number of high-level features to extract (default: 15)
        tenant_project_id: Optional tenant project ID for multi-project isolation
    """
    safe_filename = Path(file.filename).name
    extension = Path(safe_filename).suffix.lower()
    if extension != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Validate target_features range
    if target_features < 5 or target_features > 50:
        raise HTTPException(status_code=400, detail="target_features must be between 5 and 50")

    # Generate a unique request ID for resource tracking
    import uuid

    request_id = f"prd_{uuid.uuid4().hex[:8]}"

    # Use unified browser pool for slot management
    pool = await get_browser_pool()
    pool_status = await pool.get_status()

    if pool_status["available"] == 0:
        logger.info(f"Browser slot not available, queuing PRD request {request_id}")

    temp_path: Path | None = None

    # Block if a load test is running
    from orchestrator.services.load_test_lock import check_system_available

    await check_system_available("PRD processing")

    try:
        async with pool.browser_slot(
            request_id=request_id, operation_type=BrowserOpType.PRD, description=f"PRD: {file.filename}"
        ) as acquired:
            if not acquired:
                raise HTTPException(status_code=503, detail="Timeout waiting for browser slot")

            logger.info(f"Browser slot acquired for PRD request {request_id}")

            temp_dir = BASE_DIR / "prds" / "uploads"
            temp_path = temp_dir / f"{request_id}-{safe_filename}"
            try:
                temp_dir.mkdir(parents=True, exist_ok=True)
                with open(temp_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
            except OSError as e:
                logger.error(f"Unable to store uploaded PRD in {temp_dir}: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"PRD upload storage is not writable. Verify {temp_dir} exists and is writable.",
                )

            from orchestrator.workflows.prd_processor import PRDProcessingError, PRDProcessor

            processor = PRDProcessor()
            # Use filename stem if project not provided
            project_name = project or Path(file.filename).stem.replace(" ", "-").lower()

            # Run processing in thread pool to avoid blocking async loop
            # (MinerU is CPU heavy)
            loop = asyncio.get_event_loop()

            # Create wrapper function to pass target_feature_count
            def process_with_config():
                return processor.process_prd(str(temp_path), project_name, target_feature_count=target_features)

            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, process_with_config),
                    timeout=600,  # 10 minutes maximum
                )

                if not result.get("features"):
                    raise PRDProcessingError(
                        "PRD extraction returned zero features. Check Settings provider credentials/model access "
                        "and retry with a requirements-focused PDF.",
                        status_code=502,
                    )

                # Add tenant_project_id to metadata if provided
                if tenant_project_id:
                    metadata_path = BASE_DIR / "prds" / project_name / "metadata.json"
                    if metadata_path.exists():
                        meta = import_json(metadata_path)
                        meta["tenant_project_id"] = tenant_project_id
                        with open(metadata_path, "w") as f:
                            json.dump(meta, f, indent=2)

                return result
            except asyncio.TimeoutError:
                raise HTTPException(
                    status_code=504,
                    detail="PRD processing timed out after 10 minutes. Please try a smaller document or contact support.",
                )
            except PRDProcessingError as exc:
                raise HTTPException(status_code=exc.status_code, detail=str(exc))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload PRD: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        if temp_path and temp_path.exists():
            os.remove(temp_path)


@router.get("/projects")
async def list_projects(project_id: str | None = None):
    """List available PRD projects, optionally filtered by tenant project"""
    prds_dir = BASE_DIR / "prds"
    projects = []
    if prds_dir.exists():
        for d in prds_dir.iterdir():
            if d.is_dir() and (d / "metadata.json").exists():
                try:
                    meta = import_json(d / "metadata.json")
                    prd_tenant = meta.get("tenant_project_id")

                    # Filter by tenant project if specified
                    if project_id:
                        if project_id == "default":
                            # Include PRDs with no tenant or "default" tenant
                            if prd_tenant and prd_tenant != "default":
                                continue
                        else:
                            if prd_tenant != project_id:
                                continue

                    projects.append(
                        {
                            "project": d.name,
                            "processed_at": meta.get("processed_at"),
                            "total_chunks": meta.get("total_chunks", 0),
                            "feature_count": len(meta.get("features", [])),
                            "status": "stale" if _is_stale_empty_prd_metadata(meta) else "ready",
                            "message": (
                                "Previous PRD analysis produced no features. Re-upload the PDF to retry."
                                if _is_stale_empty_prd_metadata(meta)
                                else None
                            ),
                        }
                    )
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON in PRD metadata {d / 'metadata.json'}: {e}")
                except OSError as e:
                    logger.warning(f"Cannot read PRD metadata {d / 'metadata.json'}: {e}")
    # Sort by time desc
    projects.sort(key=lambda x: x.get("processed_at") or "", reverse=True)
    return projects


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    """Delete a PRD project and all its associated data"""
    project_dir = BASE_DIR / "prds" / project_id

    if not project_dir.exists():
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        shutil.rmtree(project_dir)
        return {"status": "success", "message": f"Project '{project_id}' deleted successfully"}
    except Exception as e:
        logger.error(f"Failed to delete PRD project '{project_id}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{project_id}/features")
async def get_features(project_id: str, include_context: bool = False):
    """
    List discovered features for a PRD project.

    Args:
        project_id: The project identifier
        include_context: If True, include context-only features (Full Document Context, etc.)
                        Default is False to show only testable features.
    """
    metadata_path = BASE_DIR / "prds" / project_id / "metadata.json"
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="PRD project not found")

    try:
        data = import_json(metadata_path)
        if _is_stale_empty_prd_metadata(data):
            raise HTTPException(
                status_code=409,
                detail="Previous PRD analysis produced no features. Re-upload the PDF to retry.",
            )
        features = data.get("features", [])

        # Filter out context-only features (no requirements) unless explicitly requested
        if not include_context:
            features = [f for f in features if f.get("requirements") and len(f["requirements"]) > 0]

        return {"features": features, "total": len(features), "config": data.get("config", {})}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get features for PRD project: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/{prd_project_id}/import-requirements", response_model=ImportRequirementsResponse)
async def import_requirements(
    prd_project_id: str,
    project_id: str | None = Query(default=None),
    tenant_project_id: str | None = Query(default=None),
):
    """Import extracted PRD feature requirements into the project requirements table."""
    project_id = project_id if isinstance(project_id, str) else None
    tenant_project_id = tenant_project_id if isinstance(tenant_project_id, str) else None

    metadata_path = BASE_DIR / "prds" / prd_project_id / "metadata.json"
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="PRD project metadata not found")

    try:
        data = import_json(metadata_path)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="PRD metadata is invalid JSON")
    except OSError as exc:
        logger.error("Failed to read PRD metadata for %s: %s", prd_project_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to read PRD metadata")

    target_project_id = project_id or tenant_project_id or data.get("tenant_project_id")
    if not target_project_id:
        raise HTTPException(status_code=422, detail="project_id is required")

    extracted: list[tuple[str, str]] = []
    for feature in data.get("features", []):
        if not isinstance(feature, dict):
            continue
        feature_name = str(feature.get("name") or feature.get("slug") or "Unnamed feature")
        for requirement_text in feature.get("requirements") or []:
            title = str(requirement_text or "").strip()
            if title:
                extracted.append((feature_name, title))

    if not extracted:
        return ImportRequirementsResponse(created=0, skipped=0, total=0, requirements=[])

    with Session(engine) as session:
        if target_project_id and not session.get(Project, target_project_id):
            raise HTTPException(status_code=404, detail=f"Target project '{target_project_id}' not found")

        existing_requirements = list(
            session.exec(select(Requirement).where(Requirement.project_id == target_project_id)).all()
        )
        existing_titles = {requirement.title for requirement in existing_requirements}
        next_number = _next_requirement_number(existing_requirements)
        created_requirements: list[Requirement] = []
        skipped = 0

        for feature_name, title in extracted:
            if title in existing_titles:
                skipped += 1
                continue

            now = datetime.utcnow()
            requirement = Requirement(
                project_id=target_project_id,
                req_code=f"REQ-{next_number:03d}",
                title=title,
                description=f"Imported from PRD project '{prd_project_id}', feature '{feature_name}'.",
                category="prd",
                priority="medium",
                status="draft",
                truth_state="candidate_requirement",
                source_type="prd",
                confidence=0.85,
                acceptance_criteria_json="[]",
                created_at=now,
                updated_at=now,
            )
            session.add(requirement)
            created_requirements.append(requirement)
            existing_titles.add(title)
            next_number += 1

        session.commit()
        for requirement in created_requirements:
            session.refresh(requirement)

        return ImportRequirementsResponse(
            created=len(created_requirements),
            skipped=skipped,
            total=len(extracted),
            requirements=[_imported_requirement_to_response(requirement) for requirement in created_requirements],
        )


def import_json(path: Path):
    import json

    return json.loads(path.read_text())


SENSITIVE_PAYLOAD_KEYS = ("password", "token", "secret", "credential", "api_key", "authorization", "cookie")


def _generation_run_id(generation_id: int) -> str:
    return f"prd-generation-{generation_id}"


def _generation_run_dir(generation_id: int) -> Path:
    return RUNS_DIR / _generation_run_id(generation_id)


def _normalize_target_url(target_url: str | None) -> str | None:
    if not target_url:
        return None
    stripped = target_url.strip()
    return stripped or None


def _prepare_prd_generation_mcp_workspace(
    session_dir: Path,
    *,
    headless: bool = True,
    base_dir: Path | None = None,
    storage_state_path: Path | str | None = None,
) -> dict[str, Any]:
    """Create run-local Playwright Test MCP config for PRD planner generation."""
    base_dir = base_dir or BASE_DIR
    session_dir.mkdir(parents=True, exist_ok=True)

    playwright_config_src = base_dir / "playwright.config.ts"
    playwright_config_dst = session_dir / "playwright.config.ts"
    if playwright_config_src.exists():
        config_content = prepare_run_playwright_config_content(
            playwright_config_src.read_text(),
            base_dir=base_dir,
            run_dir=session_dir,
            headless=headless,
            storage_state_path=storage_state_path,
        )
        playwright_config_dst.write_text(config_content)

    return write_playwright_test_mcp_config(
        run_dir=session_dir,
        server_name="playwright-test",
        config_path=playwright_config_dst,
        headless=headless,
        storage_state_path=storage_state_path,
    )


def _redact_payload(value: Any, depth: int = 0) -> Any:
    """Keep event payloads useful while avoiding secrets and huge blobs."""
    if depth > 4:
        return "<truncated>"
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if any(marker in key_text.lower() for marker in SENSITIVE_PAYLOAD_KEYS):
                redacted[key_text] = "<redacted>"
            else:
                redacted[key_text] = _redact_payload(item, depth + 1)
        return redacted
    if isinstance(value, list):
        return [_redact_payload(item, depth + 1) for item in value[:30]]
    if isinstance(value, str):
        return value if len(value) <= 1200 else value[:1200] + "...<truncated>"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _event_to_response(event: PrdGenerationEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "generation_id": event.generation_id,
        "sequence": event.sequence,
        "role": event.role,
        "event_type": event.event_type,
        "level": event.level,
        "message": event.message,
        "payload": event.payload,
        "created_at": event.created_at,
    }


def _append_generation_event(
    generation_id: int,
    *,
    role: str,
    event_type: str,
    message: str,
    level: str = "info",
    payload: dict[str, Any] | None = None,
) -> PrdGenerationEvent | None:
    """Append one ordered structured event for a generation."""
    try:
        with Session(engine) as session:
            gen = session.get(PrdGenerationResult, generation_id)
            if not gen:
                return None
            max_sequence = session.exec(
                select(func.max(PrdGenerationEvent.sequence)).where(PrdGenerationEvent.generation_id == generation_id)
            ).one()
            event = PrdGenerationEvent(
                generation_id=generation_id,
                sequence=int(max_sequence or 0) + 1,
                role=role,
                event_type=event_type,
                level=level,
                message=message,
            )
            event.payload = _redact_payload(payload or {})
            session.add(event)
            session.commit()
            session.refresh(event)
            return event
    except Exception as exc:
        logger.debug("Failed to append PRD generation event %s: %s", generation_id, exc)
        return None


def _short_tool_name(tool_name: str) -> str:
    return tool_name.split("__")[-1] if "__" in tool_name else tool_name


def _tool_role(tool_name: str) -> str:
    short_name = _short_tool_name(tool_name)
    if short_name.startswith("browser_") or short_name in {"planner_setup_page"}:
        return "browser_agent"
    if short_name in {"planner_save_plan", "save_plan"}:
        return "spec_writer"
    return "playwright_planner"


def _collect_generation_artifacts(generation_id: int, log_path: str | None = None) -> list[dict[str, Any]]:
    suffix_types = {
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".webm": "video",
        ".mp4": "video",
        ".log": "log",
        ".txt": "log",
        ".json": "log",
        ".jsonl": "log",
    }
    session_dirs = [(RUNS_DIR, _generation_run_dir(generation_id)), (Path("/app/runs"), Path("/app/runs") / _generation_run_id(generation_id))]
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()

    for root, session_dir in session_dirs:
        if not session_dir.exists():
            continue
        for path in session_dir.glob("**/*"):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            artifact_type = suffix_types.get(path.suffix.lower())
            if not artifact_type:
                continue
            try:
                resolved = str(path.resolve())
                if resolved in seen:
                    continue
                seen.add(resolved)
                rel_path = path.relative_to(root)
                modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            except (OSError, ValueError):
                continue
            artifacts.append(
                {
                    "name": path.name,
                    "path": f"/artifacts/{rel_path.as_posix()}",
                    "type": artifact_type,
                    "modified_at": modified_at,
                }
            )

    if log_path:
        path = Path(log_path)
        try:
            if path.exists() and str(path.resolve()) not in seen:
                rel_path = path.relative_to(RUNS_DIR)
                artifacts.append(
                    {
                        "name": path.name,
                        "path": f"/artifacts/{rel_path.as_posix()}",
                        "type": "log",
                        "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
                    }
                )
        except (OSError, ValueError):
            pass

    return sorted(
        artifacts,
        key=lambda item: (
            item["type"] != "image",
            -(item["modified_at"].timestamp() if item.get("modified_at") else 0),
            item["name"],
        ),
    )


def _latest_image_artifact(artifacts: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((artifact for artifact in artifacts if artifact.get("type") == "image"), None)


LIVE_BROWSER_ACTIVITY_TOOLS = {
    "planner_setup_page",
    "browser_navigate",
    "browser_snapshot",
    "browser_take_screenshot",
}

LIVE_PLANNER_FORBIDDEN_TOOLS = {"Read", "Glob", "Grep", "LS"}


def _derive_browser_activity(events: list[PrdGenerationEvent], latest_image: dict[str, Any] | None) -> tuple[bool, str | None]:
    browser_last_tool: str | None = None
    browser_activity_seen = bool(latest_image)
    for event in events:
        payload = event.payload or {}
        tool_name = str(payload.get("tool_label") or payload.get("last_tool") or payload.get("tool_name") or "")
        short_name = _short_tool_name(tool_name) if tool_name else ""
        if short_name:
            browser_last_tool = short_name
        if short_name in LIVE_BROWSER_ACTIVITY_TOOLS:
            browser_activity_seen = True
    return browser_activity_seen, browser_last_tool


def _enrich_display_diagnostics(diagnostics: dict[str, Any] | None) -> dict[str, Any] | None:
    if diagnostics is None:
        return None
    enriched = dict(diagnostics)
    process_count = int(enriched.get("browser_process_count") or 0)
    raw_window_count = enriched.get("browser_window_count")
    window_count = int(raw_window_count or 0) if raw_window_count is not None else 0
    enriched["browser_process_seen"] = bool(enriched.get("browser_process_seen", process_count > 0))
    enriched["browser_window_seen"] = bool(enriched.get("browser_window_seen", window_count > 0))
    enriched["browser_process_count"] = process_count
    if raw_window_count is not None:
        enriched["browser_window_count"] = window_count
    enriched.setdefault("probed_at", datetime.now(timezone.utc).isoformat())
    return enriched


def _parse_queue_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text = str(value).strip()
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _active_generation_status(status: str | None) -> bool:
    return str(status or "").lower() in ACTIVE_GENERATION_STATUSES


def _persist_generation_agent_task_id(generation_id: int, agent_task_id: str) -> None:
    with Session(engine) as session:
        gen = session.get(PrdGenerationResult, generation_id)
        if not gen:
            return
        gen.agent_task_id = agent_task_id
        session.add(gen)
        session.commit()


def _generation_status_response(gen: PrdGenerationResult) -> GenerationStatusResponse:
    artifacts = _collect_generation_artifacts(gen.id, gen.log_path) if gen.id else []
    latest_image = _latest_image_artifact(artifacts)
    target_url = _normalize_target_url(getattr(gen, "target_url", None))
    live_browser_requested = bool(target_url)
    queue_telemetry = gen.queue_telemetry if hasattr(gen, "queue_telemetry") else {}
    runtime = browser_runtime_status()
    if not live_browser_requested:
        runtime = {
            "browser_runtime": "prd_only",
            "live_view_available": False,
            "runtime_message": "PRD-only generation. Live browser validation requires a Target URL.",
            "display_diagnostics": None,
        }
    elif gen.status in {"pending", "queued", "running"}:
        runtime["display_diagnostics"] = live_browser_display_diagnostics()
    runtime["display_diagnostics"] = _enrich_display_diagnostics(runtime.get("display_diagnostics"))
    with Session(engine) as session:
        events_count = session.exec(
            select(func.count(PrdGenerationEvent.id)).where(PrdGenerationEvent.generation_id == gen.id)
        ).one()
        events = session.exec(
            select(PrdGenerationEvent)
            .where(PrdGenerationEvent.generation_id == gen.id)
            .order_by(PrdGenerationEvent.sequence)
        ).all()
        latest = session.exec(
            select(PrdGenerationEvent)
            .where(PrdGenerationEvent.generation_id == gen.id)
            .order_by(PrdGenerationEvent.sequence.desc())
            .limit(1)
        ).first()
    browser_activity_seen, browser_last_tool = _derive_browser_activity(events, latest_image)
    diagnostics = runtime.get("display_diagnostics") or {}
    browser_active = bool(
        live_browser_requested
        and runtime.get("live_view_available")
        and browser_activity_seen
        and diagnostics.get("browser_process_seen")
        and diagnostics.get("browser_window_seen")
    )
    return GenerationStatusResponse(
        id=gen.id,
        prd_project=gen.prd_project,
        feature_name=gen.feature_name,
        status=gen.status,
        target_url=target_url,
        live_browser_requested=live_browser_requested,
        current_stage=gen.current_stage,
        stage_message=gen.stage_message,
        spec_path=gen.spec_path,
        error_message=gen.error_message,
        created_at=gen.created_at,
        started_at=gen.started_at,
        completed_at=gen.completed_at,
        events_count=int(events_count or 0),
        latest_event=_event_to_response(latest) if latest else None,
        artifacts=artifacts,
        latest_image=latest_image,
        vnc_url=runtime.get("vnc_url"),
        browser_runtime=runtime.get("browser_runtime"),
        live_view_available=runtime.get("live_view_available"),
        browser_activity_seen=browser_activity_seen,
        browser_active=browser_active,
        browser_last_tool=browser_last_tool,
        suspected_browser_dialog_block=bool(queue_telemetry.get("suspected_browser_dialog_block")),
        runtime_message=queue_telemetry.get("runtime_message") or runtime.get("runtime_message"),
        display_diagnostics=runtime.get("display_diagnostics"),
        agent_task_id=getattr(gen, "agent_task_id", None),
        agent_task_status=queue_telemetry.get("agent_task_status"),
        agent_worker_id=getattr(gen, "agent_worker_id", None),
        last_heartbeat_at=getattr(gen, "last_heartbeat_at", None),
        agent_queue_health=queue_telemetry.get("agent_queue_health"),
        queue_telemetry=queue_telemetry,
    )


def _generation_agent_task_id(generation_id: int) -> str | None:
    with Session(engine) as session:
        gen = session.get(PrdGenerationResult, generation_id)
        if gen and getattr(gen, "agent_task_id", None):
            return str(gen.agent_task_id)
        event = session.exec(
            select(PrdGenerationEvent)
            .where(PrdGenerationEvent.generation_id == generation_id)
            .where(PrdGenerationEvent.event_type == "task_enqueued")
            .order_by(PrdGenerationEvent.sequence.desc())
            .limit(1)
        ).first()
    if not event:
        return None
    task_id = (event.payload or {}).get("agent_task_id")
    return str(task_id) if task_id else None


async def _queue_heartbeat_snapshot(queue: Any, task_id: str) -> tuple[datetime | None, dict[str, Any] | None]:
    heartbeat: dict[str, Any] | None = None
    if hasattr(queue, "get_task_heartbeat"):
        heartbeat = await queue.get_task_heartbeat(task_id)
    if heartbeat:
        return _parse_queue_datetime(heartbeat.get("ts")), heartbeat.get("progress") if isinstance(heartbeat.get("progress"), dict) else None
    progress = await queue.get_task_progress(task_id) if hasattr(queue, "get_task_progress") else None
    return None, progress if isinstance(progress, dict) else None


def _progress_stage_message(progress: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not progress:
        return None, None
    stage = str(progress.get("phase") or progress.get("current_stage") or "invoking_agent")
    message = progress.get("message") or progress.get("activity_label")
    last_tool = progress.get("last_tool") or progress.get("last_tool_label")
    if not message and last_tool:
        message = f"Using {_short_tool_name(str(last_tool))}..."
    return stage, str(message) if message else None


async def _reconcile_generation_with_queue(generation_id: int) -> None:
    """Make the PRD generation row reflect the durable queue task state."""
    with Session(engine) as session:
        gen = session.get(PrdGenerationResult, generation_id)
        if not gen:
            return
        task_id = gen.agent_task_id or _generation_agent_task_id(generation_id)
        if task_id and not gen.agent_task_id:
            gen.agent_task_id = task_id
            session.add(gen)
            session.commit()
        if not task_id or not _active_generation_status(gen.status):
            return

    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE, get_agent_queue, should_use_agent_queue

        if not REDIS_AVAILABLE or not should_use_agent_queue():
            return

        queue = get_agent_queue()
        await queue.connect()
        task = await queue.get_task(task_id)
        health = await queue.get_worker_health()
        heartbeat_at, progress = await _queue_heartbeat_snapshot(queue, task_id)
        heartbeat_alive = await queue.check_heartbeat(task_id) if task else False
    except Exception as exc:
        logger.debug("Failed to reconcile PRD generation %s with agent queue: %s", generation_id, exc)
        return

    terminal_event: tuple[str, str, str, dict[str, Any]] | None = None
    status_value = task.status.value if task else "missing"
    task_telemetry = task.telemetry if task and isinstance(task.telemetry, dict) else {}
    runtime_message: str | None = None

    with Session(engine) as session:
        gen = session.get(PrdGenerationResult, generation_id)
        if not gen or not _active_generation_status(gen.status):
            return

        now = datetime.now(timezone.utc)
        worker_id = task.worker_id if task else None
        stage, message = _progress_stage_message(progress)

        telemetry = {
            "agent_task_id": task_id,
            "agent_task_status": status_value,
            "agent_worker_id": worker_id,
            "agent_queue_health": health,
            "heartbeat_alive": heartbeat_alive,
            "last_heartbeat_at": heartbeat_at.isoformat() if heartbeat_at else None,
            "progress": progress or {},
            "task_telemetry": task_telemetry,
        }

        if task:
            gen.agent_worker_id = worker_id
            if heartbeat_at:
                gen.last_heartbeat_at = heartbeat_at

            if status_value in QUEUE_TERMINAL_FAILURE_STATUSES:
                error = task.error or f"Agent task {status_value}"
                gen.status = "failed"
                gen.current_stage = "error"
                gen.stage_message = "Generation failed"
                gen.error_message = error
                gen.completed_at = now
                terminal_event = (
                    "validator",
                    "failed",
                    error,
                    {"queue_status": status_value, "agent_task_id": task_id, "task_telemetry": task_telemetry},
                )
            elif status_value in QUEUE_TERMINAL_CANCEL_STATUSES:
                message_text = task.error or "Generation cancelled"
                gen.status = "cancelled"
                gen.current_stage = "cancelled"
                gen.stage_message = message_text
                gen.completed_at = now
                terminal_event = (
                    "orchestrator",
                    "cancelled",
                    message_text,
                    {"queue_status": status_value, "agent_task_id": task_id, "task_telemetry": task_telemetry},
                )
            elif status_value in {"running", "cancel_requested", "paused"}:
                stale_reference = heartbeat_at or task.started_at or task.created_at
                stale_seconds = (now - _parse_queue_datetime(stale_reference)).total_seconds() if stale_reference else 0
                if heartbeat_alive:
                    gen.status = "running"
                    gen.current_stage = stage or gen.current_stage or "invoking_agent"
                    gen.stage_message = message or gen.stage_message or "Agent task is running."
                elif stale_seconds > PRD_QUEUE_STALE_GRACE_SECONDS:
                    error = f"Agent task heartbeat was stale for {int(stale_seconds)} seconds."
                    gen.status = "failed"
                    gen.current_stage = "error"
                    gen.stage_message = "Generation failed"
                    gen.error_message = error
                    gen.completed_at = now
                    telemetry["stale_seconds"] = stale_seconds
                    terminal_event = (
                        "validator",
                        "failed",
                        error,
                        {"queue_status": status_value, "agent_task_id": task_id, "stale_seconds": stale_seconds},
                    )
                else:
                    gen.status = "running"
                    gen.current_stage = "agent_reconnecting"
                    gen.stage_message = "Waiting for agent heartbeat to recover..."
                    runtime_message = gen.stage_message
            elif status_value == "queued":
                gen.status = "queued"
                gen.current_stage = "waiting"
                gen.stage_message = message or gen.stage_message or "Waiting for an agent worker..."
                worker_count = int(health.get("worker_count") or 0)
                live_worker_count = int(health.get("live_browser_worker_count") or 0)
                if task.requires_live_browser and worker_count > 0 and live_worker_count == 0:
                    runtime_message = (
                        "No live-browser-capable agent worker is available. Restart the dashboard stack so "
                        "agent_worker runs with DISPLAY=:99, or start a worker that advertises live_browser=true."
                    )
                elif task.requires_live_browser and worker_count == 0:
                    runtime_message = (
                        "No agent workers are available to pick up this live browser generation. "
                        "Check the agent_worker supervisor process."
                    )
            elif status_value == "completed":
                gen.status = "running"
                gen.current_stage = gen.current_stage or "saving_spec"
                gen.stage_message = gen.stage_message or "Planner completed; finalizing generated spec..."
        else:
            age_reference = _parse_queue_datetime(gen.started_at or gen.created_at) or now
            age_seconds = (now - age_reference).total_seconds()
            telemetry["missing_task_age_seconds"] = age_seconds
            if age_seconds > PRD_QUEUE_STALE_GRACE_SECONDS:
                error = f"Agent task {task_id} is no longer present in the queue."
                gen.status = "failed"
                gen.current_stage = "error"
                gen.stage_message = "Generation failed"
                gen.error_message = error
                gen.completed_at = now
                terminal_event = (
                    "validator",
                    "failed",
                    error,
                    {"queue_status": "missing", "agent_task_id": task_id, "age_seconds": age_seconds},
                )

        if runtime_message:
            telemetry["runtime_message"] = runtime_message
        gen.queue_telemetry = telemetry
        session.add(gen)
        session.commit()

    if terminal_event:
        role, event_type, event_message, payload = terminal_event
        _append_generation_event(
            generation_id,
            role=role,
            event_type=event_type,
            level="error" if event_type == "failed" else "warning",
            message=event_message,
            payload=payload,
        )
        if event_type == "failed":
            try:
                await queue.fail_stale_running_task(task_id, event_message)
            except Exception:
                pass


async def _generation_status_response_with_queue(gen: PrdGenerationResult) -> GenerationStatusResponse:
    if gen.id:
        await _reconcile_generation_with_queue(gen.id)
        with Session(engine) as session:
            fresh_gen = session.get(PrdGenerationResult, gen.id)
            if fresh_gen:
                gen = fresh_gen

    response = _generation_status_response(gen)
    if not response.live_browser_requested or response.status not in {"pending", "queued", "running"}:
        return response

    task_id = response.agent_task_id or _generation_agent_task_id(response.id)
    if not task_id:
        return response

    response.agent_task_id = task_id
    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE, get_agent_queue, should_use_agent_queue

        if not REDIS_AVAILABLE or not should_use_agent_queue():
            return response

        queue = get_agent_queue()
        await queue.connect()
        task = await queue.get_task(task_id)
        health = await queue.get_worker_health()
        response.agent_queue_health = health
        if task:
            response.agent_task_status = task.status.value
            response.agent_worker_id = task.worker_id
            worker_count = int(health.get("worker_count") or 0)
            live_worker_count = int(health.get("live_browser_worker_count") or 0)
            if task.requires_live_browser and task.status.value == "queued" and worker_count > 0 and live_worker_count == 0:
                response.runtime_message = (
                    "No live-browser-capable agent worker is available. Restart the dashboard stack so "
                    "agent_worker runs with DISPLAY=:99, or start a worker that advertises live_browser=true."
                )
            elif task.requires_live_browser and task.status.value == "queued" and worker_count == 0:
                response.runtime_message = (
                    "No agent workers are available to pick up this live browser generation. "
                    "Check the agent_worker supervisor process."
                )
            elif task.requires_live_browser and task.status.value == "running":
                progress = await queue.get_task_progress(task_id) or {}
                tool_calls = int(progress.get("tool_calls") or 0)
                if tool_calls == 0 and not response.browser_activity_seen:
                    response.runtime_message = (
                        f"Planner task is running on {task.worker_id or 'an agent worker'}; "
                        "waiting for the first browser action."
                    )
    except Exception as exc:
        logger.debug("Failed to enrich PRD generation %s with agent queue state: %s", response.id, exc)
    return response


def _update_generation_status(generation_id: int, status: str, stage: str, message: str):
    """Update generation status in database"""
    with Session(engine) as session:
        gen = session.get(PrdGenerationResult, generation_id)
        if gen:
            gen.status = status
            gen.current_stage = stage
            gen.stage_message = message
            if status == "running" and not gen.started_at:
                gen.started_at = datetime.now(timezone.utc)
            session.add(gen)
            session.commit()


def _update_generation_progress(
    generation_id: int,
    status: str,
    stage: str,
    message: str,
    *,
    role: str,
    event_type: str = "stage",
    level: str = "info",
    payload: dict[str, Any] | None = None,
):
    _update_generation_status(generation_id, status, stage, message)
    _append_generation_event(
        generation_id,
        role=role,
        event_type=event_type,
        level=level,
        message=message,
        payload={"status": status, "stage": stage, **(payload or {})},
    )


def _complete_generation(generation_id: int, spec_path: str):
    """Mark generation as completed successfully"""
    with Session(engine) as session:
        gen = session.get(PrdGenerationResult, generation_id)
        if gen:
            gen.status = "completed"
            gen.current_stage = "complete"
            gen.stage_message = "Spec generated successfully"
            gen.spec_path = spec_path
            gen.completed_at = datetime.now(timezone.utc)

            # Register spec in SpecMetadata with project_id for proper project association
            # spec_name must be the relative path from specs/ dir (e.g., "prd-project/feature.md")
            # to match how _count_all_specs_for_project looks up specs
            if gen.project_id and spec_path:
                spec_path_obj = Path(spec_path)
                specs_dir = BASE_DIR / "specs"
                try:
                    # Get relative path from specs directory
                    spec_name = str(spec_path_obj.relative_to(specs_dir))
                except ValueError:
                    # If not under specs dir, use the full path as fallback
                    spec_name = spec_path

                existing = get_spec_metadata(session, spec_name, gen.project_id)
                if not existing:
                    spec_meta = SpecMetadata(
                        spec_name=spec_name,
                        project_id=gen.project_id,
                        description=f"Generated from PRD: {gen.prd_project} / {gen.feature_name}",
                    )
                    session.add(spec_meta)
                    session.add(existing)

            session.add(gen)
            session.commit()
    _append_generation_event(
        generation_id,
        role="validator",
        event_type="completed",
        message="Generation completed successfully.",
        payload={"spec_path": spec_path},
    )


def _fail_generation(generation_id: int, error: str, payload: dict[str, Any] | None = None):
    """Mark generation as failed"""
    with Session(engine) as session:
        gen = session.get(PrdGenerationResult, generation_id)
        if gen:
            gen.status = "failed"
            gen.current_stage = "error"
            gen.stage_message = "Generation failed"
            gen.error_message = error
            gen.completed_at = datetime.now(timezone.utc)
            session.add(gen)
            session.commit()
    _append_generation_event(
        generation_id,
        role="validator",
        event_type="failed",
        level="error",
        message=error,
        payload={"error": error, **(payload or {})},
    )


def _set_generation_log_path(generation_id: int, log_path: str):
    """Set the log path for a generation"""
    with Session(engine) as session:
        gen = session.get(PrdGenerationResult, generation_id)
        if gen:
            gen.log_path = log_path
            session.add(gen)
            session.commit()


def _cancel_generation(generation_id: int, message: str = "Cancelled by user"):
    """Mark generation as cancelled"""
    with Session(engine) as session:
        gen = session.get(PrdGenerationResult, generation_id)
        if gen:
            gen.status = "cancelled"
            gen.current_stage = "cancelled"
            gen.stage_message = message
            gen.completed_at = datetime.now(timezone.utc)
            session.add(gen)
            session.commit()
    _append_generation_event(
        generation_id,
        role="orchestrator",
        event_type="cancelled",
        level="warning",
        message=message,
    )


async def _run_generation_task(
    generation_id: int,
    project_id: str,
    feature_name: str,
    target_url: str | None,
    login_url: str | None,
    credentials: dict | None,
    test_data_refs: list[str] | None,
    log_path: Path,
    browser_project_id: str | None = None,
    browser_auth_session_id: str | None = None,
    use_project_default_browser_auth: bool = False,
):
    """Background task that runs the actual generation.

    Live-browser runs rely on the queued worker to acquire browser capacity.
    PRD-only runs use no browser slot and no Playwright MCP workspace.

    Args:
        generation_id: The database ID for tracking this generation
        project_id: PRD project identifier
        feature_name: Name of the feature to generate spec for
        target_url: Optional URL for live browser validation
        login_url: Optional login page URL
        credentials: Optional login credentials
        log_path: Path to the log file (already created by caller)
    """
    # Use generation_id as the resource request ID
    request_id = f"gen_{generation_id}"
    target_url = _normalize_target_url(target_url)
    live_browser_requested = bool(target_url)
    from orchestrator.workflows.native_planner import NativePlanner, SpecGenerationError

    try:
        _update_generation_progress(
            generation_id,
            "queued",
            "waiting",
            "Waiting for a live-browser-capable planner worker..."
            if live_browser_requested
            else "Waiting for PRD-only planner execution...",
            role="orchestrator",
            event_type="queued",
            payload={"request_id": request_id, "live_browser_requested": live_browser_requested},
        )

        # Block if a load test is running
        from orchestrator.services.load_test_lock import check_system_available

        _append_generation_event(
            generation_id,
            role="orchestrator",
            event_type="resource_check",
            message="Checking system availability for PRD generation.",
        )
        await check_system_available("PRD generation")

        session_dir = _generation_run_dir(generation_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        auth_context: dict[str, Any] = {
            "storage_state_attached": False,
            "browser_auth_session_id": None,
            "browser_auth_session_name": None,
            "use_project_default_browser_auth": bool(use_project_default_browser_auth),
        }
        if live_browser_requested:
            storage_state_path = None
            if browser_auth_session_id or use_project_default_browser_auth:
                try:
                    with Session(engine) as db_session:
                        resolved = resolve_browser_auth_for_run(
                            db_session,
                            browser_project_id,
                            run_dir=session_dir,
                            browser_auth_session_id=browser_auth_session_id,
                            use_default=use_project_default_browser_auth,
                        )
                    storage_state_path = resolved.storage_state_path if resolved else None
                    if resolved:
                        auth_context.update(
                            {
                                "storage_state_attached": True,
                                "browser_auth_session_id": resolved.session_id,
                                "browser_auth_session_name": resolved.session_name,
                                "project_default_used": bool(use_project_default_browser_auth),
                            }
                        )
                except BrowserAuthSessionError as exc:
                    raise RuntimeError(f"{exc}. Refresh browser auth session.") from exc
            runtime = _prepare_prd_generation_mcp_workspace(
                session_dir,
                headless=False,
                storage_state_path=storage_state_path,
            )
        else:
            runtime = {
                "browser_runtime": "prd_only",
                "live_view_available": False,
                "runtime_message": "PRD-only generation. Live browser validation requires a Target URL.",
            }
        runtime["live_browser_requested"] = live_browser_requested
        _update_generation_progress(
            generation_id,
            "running",
            "workspace_ready",
            "Preparing headed planner workspace..."
            if live_browser_requested
            else "Planner will run from PRD context only.",
            role="orchestrator",
            event_type="workspace",
            payload=runtime,
        )

        def _on_planner_task_enqueued(agent_task_id: str) -> None:
            _persist_generation_agent_task_id(generation_id, agent_task_id)
            _append_generation_event(
                generation_id,
                role="playwright_planner",
                event_type="task_enqueued",
                message="Planner task enqueued.",
                payload={"agent_task_id": agent_task_id},
            )

        def _on_planner_tool_use(tool_name: str, tool_input: dict[str, Any]) -> None:
            short_name = _short_tool_name(tool_name)
            role = _tool_role(tool_name)
            is_profile_violation = live_browser_requested and short_name in LIVE_PLANNER_FORBIDDEN_TOOLS
            _append_generation_event(
                generation_id,
                role=role,
                event_type="planner_profile_violation"
                if is_profile_violation
                else "browser_action" if role == "browser_agent" else "tool_call",
                level="error" if is_profile_violation else "info",
                message=(
                    f"Planner profile violation: live PRD planner used {short_name}."
                    if is_profile_violation
                    else f"Using {short_name}."
                ),
                payload={
                    "tool_name": tool_name,
                    "tool_label": short_name,
                    "tool_input": tool_input,
                    "live_browser_requested": live_browser_requested,
                    "forbidden_for_live_prd_planner": is_profile_violation,
                },
            )
            _update_generation_status(
                generation_id,
                "running",
                "invoking_agent",
                f"Planner profile violation: {short_name}"
                if is_profile_violation
                else f"Using {short_name}...",
            )

        def _on_planner_progress(progress: dict[str, Any]) -> None:
            last_tool = progress.get("last_tool")
            short_last_tool = _short_tool_name(str(last_tool)) if last_tool else None
            is_profile_violation = bool(
                live_browser_requested and short_last_tool in LIVE_PLANNER_FORBIDDEN_TOOLS
            )
            message = (
                f"Planner profile violation: {short_last_tool}"
                if is_profile_violation
                else f"Using {short_last_tool}..."
                if last_tool
                else str(progress.get("message") or "Planner is exploring the application...")
            )
            _append_generation_event(
                generation_id,
                role="playwright_planner",
                event_type="planner_profile_violation" if is_profile_violation else "progress",
                level="error" if is_profile_violation else "info",
                message=message,
                payload={
                    **progress,
                    "tool_label": short_last_tool,
                    "live_browser_requested": live_browser_requested,
                    "forbidden_for_live_prd_planner": is_profile_violation,
                },
            )
            _update_generation_status(
                generation_id,
                "running",
                str(progress.get("phase") or "invoking_agent"),
                message,
            )

        with capture_output_to_file(log_path):
            # NOTE: print() calls here are intentional - capture_output_to_file()
            # redirects stdout to the log file for real-time streaming to the UI.
            # Do NOT replace with logger.info().
            print(f"[{datetime.now(timezone.utc).isoformat()}] Starting generation for feature: {feature_name}")
            print(f"[{datetime.now(timezone.utc).isoformat()}] Project: {project_id}")
            print(
                f"[{datetime.now(timezone.utc).isoformat()}] Live browser validation: "
                f"{'enabled' if live_browser_requested else 'disabled (PRD-only)'}"
            )
            if target_url:
                print(f"[{datetime.now(timezone.utc).isoformat()}] Target URL: {target_url}")
            print("-" * 60)

            _update_generation_progress(
                generation_id,
                "running",
                "initializing",
                "Setting up generation environment...",
                role="orchestrator",
            )
            print(f"[{datetime.now(timezone.utc).isoformat()}] Setting up generation environment...")

            planner = NativePlanner(
                project_id=project_id,
                on_tool_use=_on_planner_tool_use,
                on_progress=_on_planner_progress,
                on_task_enqueued=_on_planner_task_enqueued,
                owner_type="prd_generation",
                owner_id=str(generation_id),
                owner_label=f"PRD generation {feature_name}",
                session_dir=session_dir,
                cwd=session_dir,
            )

            _update_generation_progress(
                generation_id,
                "running",
                "retrieving_context",
                "Retrieving PRD context...",
                role="context_retriever",
            )
            print(f"[{datetime.now(timezone.utc).isoformat()}] Retrieving PRD context...")

            # Small delay to ensure status update is visible
            await asyncio.sleep(0.5)

            _update_generation_progress(
                generation_id,
                "running",
                "invoking_agent",
                "Invoking Playwright agent...",
                role="playwright_planner",
                payload=browser_runtime_status(),
            )
            print(f"[{datetime.now(timezone.utc).isoformat()}] Invoking Playwright agent...")
            print("-" * 60)
            test_data_markdown = ""
            if test_data_refs:
                try:
                    from orchestrator.services.test_data_resolver import resolve_test_data_refs

                    with Session(engine) as db_session:
                        resolved = resolve_test_data_refs(
                            db_session,
                            project_id=browser_project_id or "default",
                            refs=[str(ref) for ref in test_data_refs],
                            render_as="markdown",
                            decrypt_sensitive=True,
                        )
                        missing = resolved.get("missing") or []
                        if missing:
                            raise RuntimeError(
                                "missing refs: "
                                + ", ".join(str(item.get("ref") or item) for item in missing)
                            )
                        test_data_markdown = resolved.get("markdown") or ""
                except Exception as exc:
                    raise RuntimeError(
                        f"Unable to resolve PRD test_data_refs before generation: {exc}"
                    ) from exc

            path = await planner.generate_spec_for_feature(
                feature_name=feature_name,
                prd_project=project_id,
                target_url=target_url,
                login_url=login_url,
                credentials=credentials,
                auth_context=auth_context,
                additional_context=test_data_markdown,
            )

            print("-" * 60)
            _update_generation_progress(
                generation_id,
                "running",
                "saving_spec",
                "Saving generated spec...",
                role="spec_writer",
                payload={"spec_path": str(path)},
            )
            print(f"[{datetime.now(timezone.utc).isoformat()}] Saving generated spec to: {path}")

            _complete_generation(generation_id, str(path))
            print(f"[{datetime.now(timezone.utc).isoformat()}] Generation completed successfully!")

    except asyncio.CancelledError:
        logger.info(f"Generation {generation_id} was cancelled by user")
        # Log cancellation to file
        with open(log_path, "a") as f:
            f.write(f"\n[{datetime.now(timezone.utc).isoformat()}] CANCELLED: Generation stopped by user\n")
        _cancel_generation(generation_id, "Cancelled by user")
        raise  # Re-raise to properly handle task cancellation
    except SpecGenerationError as e:
        logger.warning(f"Spec generation failed for {project_id}/{feature_name}: {e}")
        diagnostics = getattr(e, "diagnostics", {}) or {}
        # Log error to file as well
        with open(log_path, "a") as f:
            f.write(f"\n[{datetime.now(timezone.utc).isoformat()}] ERROR: {str(e)}\n")
            if diagnostics:
                f.write(f"[{datetime.now(timezone.utc).isoformat()}] DIAGNOSTICS: {json.dumps(diagnostics, sort_keys=True)}\n")
        _fail_generation(generation_id, str(e), payload=diagnostics)
    except Exception as e:
        logger.error(f"Unexpected error generating plan for {project_id}/{feature_name}: {e}")
        # Log error to file as well
        with open(log_path, "a") as f:
            f.write(f"\n[{datetime.now(timezone.utc).isoformat()}] ERROR: {str(e)}\n")
        _fail_generation(generation_id, str(e))
    finally:
        # Clean up from running tasks dict
        if generation_id in _running_generations:
            del _running_generations[generation_id]


@router.post("/{project_id}/generate-plan")
async def generate_plan(project_id: str, request: GenerateRequest, background_tasks: BackgroundTasks):
    """
    Generate test plan (spec) for a feature or all features using Hybrid Mode.

    For single feature generation, returns immediately with generation_id for polling.
    For all features, still runs synchronously (legacy behavior).
    """
    request.target_url = _normalize_target_url(request.target_url)
    live_browser_requested = bool(request.target_url)
    if request.feature:
        # Read tenant_project_id from PRD metadata for project association
        tenant_project_id = None
        metadata_path = BASE_DIR / "prds" / project_id / "metadata.json"
        if metadata_path.exists():
            try:
                meta = import_json(metadata_path)
                tenant_project_id = meta.get("tenant_project_id")
            except Exception as e:
                logger.warning(f"Could not read tenant_project_id from metadata: {e}")

        # Single feature: Create record and start background task
        with Session(engine) as session:
            gen_result = PrdGenerationResult(
                prd_project=project_id,
                feature_name=request.feature,
                status="pending",
                current_stage="queued",
                stage_message="Generation queued with live browser validation..."
                if live_browser_requested
                else "Generation queued in PRD-only mode...",
                project_id=tenant_project_id,  # Link to tenant project for proper isolation
                target_url=request.target_url,
                live_browser_requested=live_browser_requested,
            )
            session.add(gen_result)
            session.commit()
            session.refresh(gen_result)
            generation_id = gen_result.id

        # BEFORE starting task: Set up log file so SSE can connect immediately
        log_dir = _generation_run_dir(generation_id)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "generation.log"

        # Write initial message so SSE has something to read immediately
        with open(log_path, "w") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] Generation queued for: {request.feature}\n")
            if live_browser_requested:
                f.write(f"[{datetime.now(timezone.utc).isoformat()}] Target URL: {request.target_url}\n")
            else:
                f.write(
                    f"[{datetime.now(timezone.utc).isoformat()}] PRD-only mode: no live browser view will be opened.\n"
                )

        # Set log_path in DB BEFORE task starts (fixes race condition)
        _set_generation_log_path(generation_id, str(log_path))
        _append_generation_event(
            generation_id,
            role="orchestrator",
            event_type="created",
            message=f"Generation queued for {request.feature}.",
            payload={
                "prd_project": project_id,
                "feature_name": request.feature,
                "target_url": request.target_url,
                "live_browser_requested": live_browser_requested,
                "browser_auth_session_id": request.browser_auth_session_id,
                "use_project_default_browser_auth": request.use_project_default_browser_auth,
                "test_data_refs": request.test_data_refs,
                "log_path": str(log_path),
            },
        )

        # NOW start the task, passing log_path
        task = asyncio.create_task(
            _run_generation_task(
                generation_id=generation_id,
                project_id=project_id,
                feature_name=request.feature,
                target_url=request.target_url,
                login_url=request.login_url,
                credentials=request.credentials,
                test_data_refs=request.test_data_refs,
                log_path=log_path,
                browser_project_id=tenant_project_id,
                browser_auth_session_id=request.browser_auth_session_id,
                use_project_default_browser_auth=request.use_project_default_browser_auth,
            )
        )
        _running_generations[generation_id] = task

        initial_runtime = browser_runtime_status() if live_browser_requested else {}
        return {
            "status": "started",
            "generation_id": generation_id,
            "target_url": request.target_url,
            "live_browser_requested": live_browser_requested,
            "live_view_available": bool(initial_runtime.get("live_view_available")) and live_browser_requested,
            "browser_activity_seen": False,
            "browser_active": False,
            "browser_last_tool": None,
            "suspected_browser_dialog_block": False,
            "runtime_message": initial_runtime.get("runtime_message")
            if live_browser_requested
            else "PRD-only generation. Provide a Target URL to enable live browser validation.",
            "message": "Generation started in background. Poll /api/prd/generation/{generation_id} for status.",
        }
    else:
        # All features: Run synchronously (legacy behavior)
        from orchestrator.workflows.native_planner import NativePlanner, SpecGenerationError

        planner = NativePlanner(project_id=project_id)
        try:
            paths = await planner.generate_all_specs(prd_project=project_id, target_url=request.target_url)
            return {"status": "success", "spec_paths": [str(p) for p in paths]}
        except SpecGenerationError as e:
            logger.warning(f"Spec generation failed for {project_id}: {e}")
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            logger.error(f"Unexpected error generating plan for {project_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/generation/{generation_id}", response_model=GenerationStatusResponse)
async def get_generation_status(generation_id: int, project_id: str = Query(...)):
    """Get status of a generation task (for polling)"""
    with Session(engine) as session:
        gen = _get_generation_for_project(session, generation_id, project_id)
        return await _generation_status_response_with_queue(gen)


@router.get("/generation/{generation_id}/events", response_model=list[PrdGenerationEventResponse])
async def list_generation_events(
    generation_id: int,
    project_id: str = Query(...),
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    """List structured generation events after a sequence number."""
    with Session(engine) as session:
        _get_generation_for_project(session, generation_id, project_id)
        events = session.exec(
            select(PrdGenerationEvent)
            .where(PrdGenerationEvent.generation_id == generation_id)
            .where(PrdGenerationEvent.sequence > after_sequence)
            .order_by(PrdGenerationEvent.sequence)
            .limit(limit)
        ).all()
        return [_event_to_response(event) for event in events]


@router.get("/generation/{generation_id}/events/stream")
async def stream_generation_events(
    generation_id: int,
    project_id: str = Query(...),
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Stream structured generation events via SSE."""
    with Session(engine) as session:
        _get_generation_for_project(session, generation_id, project_id)

    async def generate():
        last_sequence = after_sequence
        try:
            yield f"data: {json.dumps({'status': 'connected', 'after_sequence': after_sequence})}\n\n"
            while True:
                with Session(engine) as check_session:
                    current_gen = check_session.exec(
                        select(PrdGenerationResult).where(
                            PrdGenerationResult.id == generation_id,
                            _generation_project_filter(project_id),
                        )
                    ).first()
                    if not current_gen:
                        yield f"data: {json.dumps({'status': 'error', 'message': 'Generation not found'})}\n\n"
                        break
                    events = check_session.exec(
                        select(PrdGenerationEvent)
                        .where(PrdGenerationEvent.generation_id == generation_id)
                        .where(PrdGenerationEvent.sequence > last_sequence)
                        .order_by(PrdGenerationEvent.sequence)
                        .limit(limit)
                    ).all()
                    for event in events:
                        last_sequence = max(last_sequence, event.sequence)
                        yield f"data: {json.dumps({'event': _event_to_response(event)}, default=str)}\n\n"
                    if current_gen.status in ["completed", "failed", "cancelled"]:
                        yield f"data: {json.dumps({'status': 'complete', 'final_status': current_gen.status, 'last_sequence': last_sequence})}\n\n"
                        break
                await asyncio.sleep(1)
        except (asyncio.CancelledError, GeneratorExit):
            pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/generation/{generation_id}/stop")
async def stop_generation(generation_id: int, project_id: str = Query(...)):
    """Stop a running generation task.

    Cancels the asyncio task and updates the database status to 'cancelled'.
    """
    # 1. Validate generation exists
    with Session(engine) as session:
        gen = _get_generation_for_project(session, generation_id, project_id)
        agent_task_id = gen.agent_task_id or _generation_agent_task_id(generation_id)

        # 2. Check if it's actually running
        if gen.status not in ["pending", "queued", "running"]:
            raise HTTPException(status_code=400, detail=f"Generation is not running (status: {gen.status})")

    # 3. Cancel asyncio task if it exists
    task = _running_generations.get(generation_id)
    if task and not task.done():
        task.cancel()
        try:
            # Wait briefly for task to acknowledge cancellation
            await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass  # Expected - task was cancelled

    # 4. Cancel persisted queue task if the generation was handed to the worker
    queue_cancel_result = None
    if agent_task_id:
        try:
            from orchestrator.services.agent_cancellation import cancel_agent_task_id

            queue_cancel_result = await cancel_agent_task_id(agent_task_id, runtime="queue")
        except Exception as exc:
            logger.warning("Failed to cancel PRD generation queue task %s: %s", agent_task_id, exc)

    # 5. Update DB status (in case task didn't handle it)
    _cancel_generation(generation_id, "Cancelled by user")
    if queue_cancel_result:
        _append_generation_event(
            generation_id,
            role="orchestrator",
            event_type="queue_cancelled",
            level="warning",
            message="Cancellation was forwarded to the agent queue.",
            payload=queue_cancel_result,
        )

    # 6. Append cancellation message to log file
    with Session(engine) as session:
        gen = session.exec(
            select(PrdGenerationResult).where(
                PrdGenerationResult.id == generation_id,
                _generation_project_filter(project_id),
            )
        ).first()
        if gen and gen.log_path:
            log_path = Path(gen.log_path)
            if log_path.exists():
                with open(log_path, "a") as f:
                    f.write(f"\n[{datetime.now(timezone.utc).isoformat()}] STOPPED: Generation cancelled by user\n")

    logger.info(f"Generation {generation_id} stopped by user")
    return {"status": "cancelled", "generation_id": generation_id, "agent_task_id": agent_task_id}


@router.get("/generation/{generation_id}/log/stream")
async def stream_generation_log(generation_id: int, project_id: str = Query(...)):
    """Stream generation log in real-time using Server-Sent Events (SSE).

    This endpoint streams the generation.log file content as new lines are written.
    The frontend uses EventSource to receive updates in real-time.

    Response format (SSE):
        data: {"status": "connected"}  -- Initial connection confirmation
        data: {"status": "waiting", "message": "Starting..."}  -- While waiting for log file
        data: {"log": "new log content..."}  -- Log content as it's written
        data: {"status": "complete", "final_status": "completed"}  -- Generation finished
    """
    with Session(engine) as session:
        _get_generation_for_project(session, generation_id, project_id)

    async def generate():
        last_position = 0
        consecutive_no_change = 0
        log_path = None  # Will be set once available from database
        try:
            # Send connection confirmation immediately
            yield f"data: {json.dumps({'status': 'connected'})}\n\n"

            while True:
                try:
                    # Check database for current status and log_path
                    with Session(engine) as check_session:
                        current_gen = check_session.exec(
                            select(PrdGenerationResult).where(
                                PrdGenerationResult.id == generation_id,
                                _generation_project_filter(project_id),
                            )
                        ).first()
                        if not current_gen:
                            yield f"data: {json.dumps({'status': 'error', 'message': 'Generation not found'})}\n\n"
                            break

                        # Update log_path if not set yet (race condition fix)
                        if log_path is None and current_gen.log_path:
                            log_path = Path(current_gen.log_path)

                        if current_gen.status in ["completed", "failed", "cancelled"]:
                            # Send any remaining log content
                            if log_path and log_path.exists():
                                with open(log_path) as f:
                                    f.seek(last_position)
                                    remaining = f.read()
                                    if remaining:
                                        yield f"data: {json.dumps({'log': remaining})}\n\n"

                            # Send completion event
                            yield f"data: {json.dumps({'status': 'complete', 'final_status': current_gen.status})}\n\n"
                            break

                    # Read new log content
                    if log_path and log_path.exists():
                        with open(log_path) as f:
                            f.seek(last_position)
                            new_content = f.read()
                            if new_content:
                                yield f"data: {json.dumps({'log': new_content})}\n\n"
                                last_position = f.tell()
                                consecutive_no_change = 0
                            else:
                                consecutive_no_change += 1
                                # Send keepalive every 5 seconds of no content
                                if consecutive_no_change % 5 == 0:
                                    yield f"data: {json.dumps({'status': 'waiting', 'message': 'Processing...'})}\n\n"
                    else:
                        consecutive_no_change += 1
                        # Send waiting status while log file doesn't exist yet
                        if consecutive_no_change <= 3:
                            yield f"data: {json.dumps({'status': 'waiting', 'message': 'Starting...'})}\n\n"
                        elif consecutive_no_change % 5 == 0:
                            yield f"data: {json.dumps({'status': 'waiting', 'message': 'Waiting for agent...'})}\n\n"

                    # Long PRD planning runs can be quiet while the worker is still alive.
                    # Keep the SSE open and let backend generation status remain the source of truth.
                    if consecutive_no_change > 600:  # 600 * 1s = 10 minutes
                        yield f"data: {json.dumps({'status': 'reconnecting', 'message': 'No new log output; generation status is still being polled.'})}\n\n"
                        consecutive_no_change = 0

                    await asyncio.sleep(1)

                except Exception as e:
                    logger.error(f"Error streaming log for generation {generation_id}: {e}")
                    yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
                    break
        except (asyncio.CancelledError, GeneratorExit):
            pass  # Client disconnected
        finally:
            logger.debug(f"Log stream ended for generation {generation_id}")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/{prd_project_id}/generations")
async def list_generations(prd_project_id: str, project_id: str = Query(...), limit: int = 50):
    """List generation results for a PRD project (for loading history)"""
    with Session(engine) as session:
        statement = (
            select(PrdGenerationResult)
            .where(PrdGenerationResult.prd_project == prd_project_id)
            .where(_generation_project_filter(project_id))
            .order_by(PrdGenerationResult.created_at.desc())
            .limit(limit)
        )
        results = session.exec(statement).all()
        return [await _generation_status_response_with_queue(gen) for gen in results]


class GenerateTestRequest(BaseModel):
    spec_path: str
    target_url: str | None = None


@router.post("/generate-test")
async def generate_test(request: GenerateTestRequest):
    """Generate Playwright test from spec using live browser validation"""
    from orchestrator.workflows.native_generator import NativeGenerator

    generator = NativeGenerator()
    try:
        path = await generator.generate_test(spec_path=request.spec_path, target_url=request.target_url)
        # Verify it exists
        if not path.exists():
            return {"status": "failed", "message": "Test file not created"}

        return {"status": "success", "test_path": str(path), "code": path.read_text()}
    except Exception as e:
        logger.error(f"Failed to generate test: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/heal-test")
async def heal_test(request: HealRequest):
    """Heal a failing test"""
    from orchestrator.workflows.native_healer import NativeHealer

    healer = NativeHealer()
    try:
        fixed_code = await healer.heal_test(request.test_path, request.error_log)
        if fixed_code:
            return {"status": "success", "code": fixed_code}
        else:
            return {"status": "failed", "message": "Could not heal test"}
    except Exception as e:
        logger.error(f"Failed to heal test: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


class RunTestRequest(BaseModel):
    test_path: str
    heal: bool = True
    max_attempts: int = 3


@router.post("/run-test")
async def run_test(request: RunTestRequest):
    """
    Run a generated Playwright test file with optional self-healing.

    If the test fails and heal=True, attempts to heal and retry up to max_attempts times.
    """
    test_path = Path(request.test_path)

    # Handle relative paths
    if not test_path.is_absolute():
        test_path = BASE_DIR / request.test_path

    if not test_path.exists():
        raise HTTPException(status_code=404, detail=f"Test file not found: {request.test_path}")

    from orchestrator.workflows.native_healer import NativeHealer

    healer = NativeHealer()
    attempts = 0
    last_error = ""
    healed = False

    while attempts < request.max_attempts:
        attempts += 1
        logger.info(f"Running test (attempt {attempts}/{request.max_attempts}): {test_path.name}")

        # Run the test with Playwright
        try:
            result = subprocess.run(
                ["npx", "playwright", "test", str(test_path), "--reporter=json"],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            # Check if test passed
            if result.returncode == 0:
                logger.info(f"Test passed on attempt {attempts}")
                return {
                    "status": "passed",
                    "passed": True,
                    "attempts": attempts,
                    "healed": healed,
                    "test_path": str(test_path),
                }

            # Test failed - capture error
            last_error = result.stdout + "\n" + result.stderr
            logger.warning(f"Test failed on attempt {attempts}")

            # Attempt to heal if enabled and not last attempt
            if request.heal and attempts < request.max_attempts:
                logger.info("Attempting to heal...")
                try:
                    fixed_code = await healer.heal_test(str(test_path), last_error)
                    if fixed_code:
                        healed = True
                        logger.info("Test healed, retrying...")
                    else:
                        logger.warning("Healing did not produce changes")
                except Exception as heal_error:
                    logger.warning(f"Healing failed: {heal_error}")

        except subprocess.TimeoutExpired:
            last_error = "Test execution timed out after 5 minutes"
            logger.warning(f"Timeout on attempt {attempts}")
        except Exception as e:
            last_error = str(e)
            logger.error(f"Error on attempt {attempts}: {e}")

    # All attempts exhausted
    return {
        "status": "failed",
        "passed": False,
        "attempts": attempts,
        "healed": healed,
        "error_log": last_error[-5000:] if last_error else None,  # Truncate long errors
        "test_path": str(test_path),
    }


class RequirementTextRequest(BaseModel):
    text: str


def _load_metadata(project_id: str) -> dict:
    """Load metadata.json for a PRD project."""
    metadata_path = BASE_DIR / "prds" / project_id / "metadata.json"
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="PRD project not found")
    return import_json(metadata_path)


def _save_metadata(project_id: str, data: dict):
    """Atomically save metadata.json for a PRD project."""
    import tempfile

    metadata_path = BASE_DIR / "prds" / project_id / "metadata.json"
    # Write to temp file then atomically replace
    fd, tmp_path = tempfile.mkstemp(dir=metadata_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, metadata_path)
    except Exception:
        # Clean up temp file on failure
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _get_feature(data: dict, feature_slug: str) -> dict:
    """Find a feature by slug in metadata."""
    for f in data.get("features", []):
        if f.get("slug") == feature_slug:
            return f
    raise HTTPException(status_code=404, detail=f"Feature '{feature_slug}' not found")


@router.post("/{project_id}/features/{feature_slug}/requirements")
async def add_requirement(project_id: str, feature_slug: str, body: RequirementTextRequest):
    """Add a requirement to a feature."""
    data = _load_metadata(project_id)
    feature = _get_feature(data, feature_slug)
    if "requirements" not in feature:
        feature["requirements"] = []
    feature["requirements"].append(body.text)
    _save_metadata(project_id, data)
    return {"status": "ok", "requirements": feature["requirements"]}


@router.put("/{project_id}/features/{feature_slug}/requirements/{req_index}")
async def edit_requirement(project_id: str, feature_slug: str, req_index: int, body: RequirementTextRequest):
    """Edit a requirement by index."""
    data = _load_metadata(project_id)
    feature = _get_feature(data, feature_slug)
    reqs = feature.get("requirements", [])
    if req_index < 0 or req_index >= len(reqs):
        raise HTTPException(status_code=404, detail=f"Requirement index {req_index} out of range")
    reqs[req_index] = body.text
    _save_metadata(project_id, data)
    return {"status": "ok", "requirements": reqs}


@router.delete("/{project_id}/features/{feature_slug}/requirements/{req_index}")
async def delete_requirement(project_id: str, feature_slug: str, req_index: int):
    """Delete a requirement by index."""
    data = _load_metadata(project_id)
    feature = _get_feature(data, feature_slug)
    reqs = feature.get("requirements", [])
    if req_index < 0 or req_index >= len(reqs):
        raise HTTPException(status_code=404, detail=f"Requirement index {req_index} out of range")
    reqs.pop(req_index)
    _save_metadata(project_id, data)
    return {"status": "ok", "requirements": reqs}


@router.get("/queue/status")
async def get_prd_queue_status():
    """Get current PRD processing queue status.

    Returns information about browser slot usage from the unified pool.
    Note: Uses BrowserResourcePool which manages ALL browser operations.
    """
    pool = await get_browser_pool()
    status = await pool.get_status()

    # Filter to show PRD-specific info while showing overall pool status
    prd_running = status["by_type"].get("prd", 0)

    return {
        "active": prd_running,
        "max": status["max_browsers"],
        "queued": status["queued"],
        "available": status["available"],
        "pool_status": {"total_running": status["running"], "by_type": status["by_type"]},
    }
