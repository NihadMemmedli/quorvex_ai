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

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from .db import engine
from .models_db import PrdGenerationResult, SpecMetadata

# Import resource managers - using relative import since we're in orchestrator/api
sys.path.insert(0, str(Path(__file__).parent.parent))
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

from orchestrator.workflows.native_generator import NativeGenerator
from orchestrator.workflows.native_healer import NativeHealer
from orchestrator.workflows.native_planner import NativePlanner, SpecGenerationError
from orchestrator.workflows.prd_processor import PRDProcessor

# Base directory (project root, one level up from orchestrator/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

router = APIRouter(prefix="/api/prd", tags=["prd"])


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


class HealRequest(BaseModel):
    test_path: str
    error_log: str


class GenerationStatusResponse(BaseModel):
    id: int
    prd_project: str
    feature_name: str
    status: str
    current_stage: str | None = None
    stage_message: str | None = None
    spec_path: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


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
    extension = Path(file.filename).suffix.lower()
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

    temp_dir = Path("temp_uploads")
    temp_dir.mkdir(exist_ok=True)
    temp_path = temp_dir / file.filename

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

            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

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

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload PRD: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        if temp_path.exists():
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
        features = data.get("features", [])

        # Filter out context-only features (no requirements) unless explicitly requested
        if not include_context:
            features = [f for f in features if f.get("requirements") and len(f["requirements"]) > 0]

        return {"features": features, "total": len(features), "config": data.get("config", {})}
    except Exception as e:
        logger.error(f"Failed to get features for PRD project: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


def import_json(path: Path):
    import json

    return json.loads(path.read_text())


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

                existing = session.exec(select(SpecMetadata).where(SpecMetadata.spec_name == spec_name)).first()
                if not existing:
                    spec_meta = SpecMetadata(
                        spec_name=spec_name,
                        project_id=gen.project_id,
                        description=f"Generated from PRD: {gen.prd_project} / {gen.feature_name}",
                    )
                    session.add(spec_meta)
                elif existing.project_id != gen.project_id:
                    # Update project_id if spec exists but with wrong project
                    existing.project_id = gen.project_id
                    session.add(existing)

            session.add(gen)
            session.commit()


def _fail_generation(generation_id: int, error: str):
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


async def _run_generation_task(
    generation_id: int,
    project_id: str,
    feature_name: str,
    target_url: str | None,
    login_url: str | None,
    credentials: dict | None,
    log_path: Path,
):
    """Background task that runs the actual generation.

    This task uses browser automation, so it acquires a browser slot from
    the unified BrowserResourcePool.

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
    pool = await get_browser_pool()

    try:
        _update_generation_status(generation_id, "queued", "waiting", "Waiting for available browser slot...")

        # Block if a load test is running
        from orchestrator.services.load_test_lock import check_system_available

        await check_system_available("PRD generation")

        async with pool.browser_slot(
            request_id=request_id, operation_type=BrowserOpType.PRD, description=f"PRD Generate: {feature_name}"
        ) as acquired:
            if not acquired:
                logger.error(f"Timeout waiting for browser slot for generation {generation_id}")
                _fail_generation(generation_id, "Timeout waiting for browser slot")
                return

            logger.info(f"Browser slot acquired for generation {generation_id}")

            with capture_output_to_file(log_path):
                # NOTE: print() calls here are intentional - capture_output_to_file()
                # redirects stdout to the log file for real-time streaming to the UI.
                # Do NOT replace with logger.info().
                print(f"[{datetime.now(timezone.utc).isoformat()}] Starting generation for feature: {feature_name}")
                print(f"[{datetime.now(timezone.utc).isoformat()}] Project: {project_id}")
                print("-" * 60)

                _update_generation_status(
                    generation_id, "running", "initializing", "Setting up generation environment..."
                )
                print(f"[{datetime.now(timezone.utc).isoformat()}] Setting up generation environment...")

                planner = NativePlanner(project_id=project_id)

                _update_generation_status(generation_id, "running", "retrieving_context", "Retrieving PRD context...")
                print(f"[{datetime.now(timezone.utc).isoformat()}] Retrieving PRD context...")

                # Small delay to ensure status update is visible
                await asyncio.sleep(0.5)

                _update_generation_status(generation_id, "running", "invoking_agent", "Invoking Playwright agent...")
                print(f"[{datetime.now(timezone.utc).isoformat()}] Invoking Playwright agent...")
                print("-" * 60)

                path = await planner.generate_spec_for_feature(
                    feature_name=feature_name,
                    prd_project=project_id,
                    target_url=target_url,
                    login_url=login_url,
                    credentials=credentials,
                )

                print("-" * 60)
                _update_generation_status(generation_id, "running", "saving_spec", "Saving generated spec...")
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
        # Log error to file as well
        with open(log_path, "a") as f:
            f.write(f"\n[{datetime.now(timezone.utc).isoformat()}] ERROR: {str(e)}\n")
        _fail_generation(generation_id, str(e))
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
                stage_message="Generation queued...",
                project_id=tenant_project_id,  # Link to tenant project for proper isolation
            )
            session.add(gen_result)
            session.commit()
            session.refresh(gen_result)
            generation_id = gen_result.id

        # BEFORE starting task: Set up log file so SSE can connect immediately
        log_dir = BASE_DIR / "prds" / project_id / "generations" / str(generation_id)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "generation.log"

        # Write initial message so SSE has something to read immediately
        with open(log_path, "w") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] Generation queued for: {request.feature}\n")

        # Set log_path in DB BEFORE task starts (fixes race condition)
        _set_generation_log_path(generation_id, str(log_path))

        # NOW start the task, passing log_path
        task = asyncio.create_task(
            _run_generation_task(
                generation_id=generation_id,
                project_id=project_id,
                feature_name=request.feature,
                target_url=request.target_url,
                login_url=request.login_url,
                credentials=request.credentials,
                log_path=log_path,
            )
        )
        _running_generations[generation_id] = task

        return {
            "status": "started",
            "generation_id": generation_id,
            "message": "Generation started in background. Poll /api/prd/generation/{generation_id} for status.",
        }
    else:
        # All features: Run synchronously (legacy behavior)
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
async def get_generation_status(generation_id: int):
    """Get status of a generation task (for polling)"""
    with Session(engine) as session:
        gen = session.get(PrdGenerationResult, generation_id)
        if not gen:
            raise HTTPException(status_code=404, detail="Generation not found")
        return GenerationStatusResponse(
            id=gen.id,
            prd_project=gen.prd_project,
            feature_name=gen.feature_name,
            status=gen.status,
            current_stage=gen.current_stage,
            stage_message=gen.stage_message,
            spec_path=gen.spec_path,
            error_message=gen.error_message,
            created_at=gen.created_at,
            started_at=gen.started_at,
            completed_at=gen.completed_at,
        )


@router.post("/generation/{generation_id}/stop")
async def stop_generation(generation_id: int):
    """Stop a running generation task.

    Cancels the asyncio task and updates the database status to 'cancelled'.
    """
    # 1. Validate generation exists
    with Session(engine) as session:
        gen = session.get(PrdGenerationResult, generation_id)
        if not gen:
            raise HTTPException(status_code=404, detail="Generation not found")

        # 2. Check if it's actually running
        if gen.status not in ["pending", "running"]:
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

    # 4. Update DB status (in case task didn't handle it)
    _cancel_generation(generation_id, "Cancelled by user")

    # 5. Append cancellation message to log file
    with Session(engine) as session:
        gen = session.get(PrdGenerationResult, generation_id)
        if gen and gen.log_path:
            log_path = Path(gen.log_path)
            if log_path.exists():
                with open(log_path, "a") as f:
                    f.write(f"\n[{datetime.now(timezone.utc).isoformat()}] STOPPED: Generation cancelled by user\n")

    logger.info(f"Generation {generation_id} stopped by user")
    return {"status": "cancelled", "generation_id": generation_id}


@router.get("/generation/{generation_id}/log/stream")
async def stream_generation_log(generation_id: int):
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
        gen = session.get(PrdGenerationResult, generation_id)
        if not gen:
            raise HTTPException(status_code=404, detail="Generation not found")

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
                        current_gen = check_session.get(PrdGenerationResult, generation_id)
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

                    # Timeout after 10 minutes of no activity
                    if consecutive_no_change > 600:  # 600 * 1s = 10 minutes
                        yield f"data: {json.dumps({'status': 'timeout', 'message': 'Stream timed out after 10 minutes of no activity'})}\n\n"
                        break

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


@router.get("/{project_id}/generations")
async def list_generations(project_id: str, limit: int = 50):
    """List generation results for a PRD project (for loading history)"""
    with Session(engine) as session:
        statement = (
            select(PrdGenerationResult)
            .where(PrdGenerationResult.prd_project == project_id)
            .order_by(PrdGenerationResult.created_at.desc())
            .limit(limit)
        )
        results = session.exec(statement).all()
        return [
            GenerationStatusResponse(
                id=gen.id,
                prd_project=gen.prd_project,
                feature_name=gen.feature_name,
                status=gen.status,
                current_stage=gen.current_stage,
                stage_message=gen.stage_message,
                spec_path=gen.spec_path,
                error_message=gen.error_message,
                created_at=gen.created_at,
                started_at=gen.started_at,
                completed_at=gen.completed_at,
            )
            for gen in results
        ]


class GenerateTestRequest(BaseModel):
    spec_path: str
    target_url: str | None = None


@router.post("/generate-test")
async def generate_test(request: GenerateTestRequest):
    """Generate Playwright test from spec using live browser validation"""
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
