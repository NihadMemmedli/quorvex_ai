import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from logging_config import get_logger
from utils.playwright_mcp import browser_runtime_status

from . import run_files, spec_files
from .db import engine, get_session
from .models import BulkRunRequest, CreateBatchResponse, TestRun
from .models_db import TestRun as DBTestRun

logger = get_logger(__name__)
router = APIRouter()

BASE_DIR = spec_files.BASE_DIR
SPECS_DIR = spec_files.SPECS_DIR
RUNS_DIR = spec_files.RUNS_DIR


def _base_dir() -> Path:
    return getattr(_runtime(), "BASE_DIR", BASE_DIR)


def _specs_dir() -> Path:
    return getattr(_runtime(), "SPECS_DIR", SPECS_DIR)


def _runs_dir() -> Path:
    return getattr(_runtime(), "RUNS_DIR", RUNS_DIR)


def _utcnow() -> datetime:
    return _runtime().datetime.utcnow()


class PaginatedRunsResponse(BaseModel):
    runs: list[TestRun]
    total: int
    limit: int
    offset: int
    has_more: bool


class ProgressUpdate(BaseModel):
    """Request model for updating run progress."""

    stage: str
    message: str | None = None
    healing_attempt: int | None = None


class AgenticSummaryUpdate(BaseModel):
    """Request model for updating compact agentic QA summary."""

    summary: dict[str, Any]


class RunRequest(BaseModel):
    """Request model for creating a test run."""

    spec_name: str
    browser: str | None = "chromium"
    target: str | None = "browser"
    platform: str | None = "ios"
    appium_server_url: str | None = None
    capabilities_file: str | None = None
    hybrid: bool | None = False
    max_iterations: int | None = 20
    project_id: str | None = None
    model_tier: str | None = None
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False

    # Legacy fields kept for request compatibility.
    ralph: bool | None = False
    native_healer: bool | None = False
    native_generator: bool | None = False


def _runtime():
    from . import main as main_runtime

    return main_runtime


def _read_text_if_exists(path_value: str | None) -> str:
    if not path_value:
        return ""
    try:
        path = Path(path_value)
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8")
    except Exception:
        return ""
    return ""


def _validate_bulk_test_data_refs(
    session: Session,
    *,
    project_id: str | None,
    spec_names: list[str],
    shared_refs: list[str] | None,
    refs_by_spec: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    from orchestrator.services import batch_executor
    from orchestrator.services.test_data_resolver import (
        extract_test_data_refs_from_sources,
        resolve_test_data_refs,
    )

    runtime = _runtime()
    explicit_shared_refs = runtime._normalize_request_test_data_refs(shared_refs)
    explicit_by_spec = refs_by_spec or {}
    resolved_by_spec: dict[str, list[str]] = {}
    refs_to_validate: list[str] = []

    for spec_name in spec_names:
        spec_path = batch_executor.SPECS_DIR / spec_name
        code_path = batch_executor._get_try_code_path(spec_name, spec_path) if spec_path.exists() else None
        explicit_refs = explicit_by_spec.get(spec_name, explicit_shared_refs)
        spec_refs = extract_test_data_refs_from_sources(
            refs=explicit_refs,
            markdown=_read_text_if_exists(str(spec_path)),
            generated_code=_read_text_if_exists(code_path),
        )
        resolved_by_spec[spec_name] = spec_refs
        refs_to_validate.extend(spec_refs)

    refs_to_validate = extract_test_data_refs_from_sources(refs=refs_to_validate)
    if refs_to_validate and not project_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "test_data_project_required",
                "message": "Project test data selection requires a project",
                "refs": refs_to_validate,
            },
        )
    if not refs_to_validate:
        return resolved_by_spec

    resolved = resolve_test_data_refs(
        session,
        project_id=project_id or "default",
        refs=refs_to_validate,
        render_as="json",
        decrypt_sensitive=False,
    )
    missing = resolved.get("missing") or []
    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "test_data_refs_unresolved",
                "message": "Some selected or required test data refs are unavailable",
                "missing_test_data": missing,
            },
        )
    return resolved_by_spec


def _is_login_specific_spec(spec_name: str, spec_content: str) -> bool:
    haystack = f"{spec_name}\n{spec_content[:1000]}".lower()
    return bool(re.search(r"\b(log\s*in|login|sign\s*in|signin|sign-in|logout|log\s*out|sign\s*out)\b", haystack))


@router.get("/runs")
def list_runs(
    session: Session = Depends(get_session),
    limit: int = 20,
    offset: int = 0,
    project_id: str | None = None,
    status: str | None = Query(None, description="Filter by status (passed, failed, error, stopped, running)"),
    search: str | None = Query(None, description="Search by test name"),
):
    """List runs with pagination support."""
    limit = min(limit, 100)

    base_query = select(DBTestRun)
    if project_id:
        base_query = base_query.where(DBTestRun.project_id == project_id)

    count_query = select(func.count()).select_from(DBTestRun)
    if project_id:
        count_query = count_query.where(DBTestRun.project_id == project_id)

    if status:
        status_map = {
            "passed": ["completed", "passed", "success"],
            "failed": ["failed", "failure"],
            "running": ["running", "in_progress"],
            "error": ["error"],
            "stopped": ["stopped"],
            "queued": ["queued"],
            "pending": ["pending"],
        }
        status_values = status_map.get(status.lower(), [status])
        base_query = base_query.where(DBTestRun.status.in_(status_values))
        count_query = count_query.where(DBTestRun.status.in_(status_values))

    if search:
        base_query = base_query.where(DBTestRun.test_name.ilike(f"%{search}%"))
        count_query = count_query.where(DBTestRun.test_name.ilike(f"%{search}%"))

    total = session.exec(count_query).one()
    statement = base_query.order_by(DBTestRun.created_at.desc()).offset(offset).limit(limit)
    runs_db = session.exec(statement).all()

    runtime = _runtime()
    results = []
    for r in runs_db:
        timestamp = r.created_at.strftime("%Y-%m-%d_%H-%M-%S")
        canStop = runtime.is_process_active(r.id) or (
            bool(r.temporal_workflow_id) and r.status in ("queued", "running", "in_progress")
        )

        results.append(
            TestRun(
                id=r.id,
                timestamp=timestamp,
                status=r.status,
                test_name=r.test_name,
                spec_name=r.spec_name,
                steps_completed=r.steps_completed,
                total_steps=r.total_steps,
                browser=r.browser,
                canStop=canStop,
                queue_position=r.queue_position,
                queued_at=r.queued_at.isoformat() if r.queued_at else None,
                started_at=r.started_at.isoformat() if r.started_at else None,
                completed_at=r.completed_at.isoformat() if r.completed_at else None,
                batch_id=r.batch_id,
                temporal_workflow_id=r.temporal_workflow_id,
                temporal_run_id=r.temporal_run_id,
                error_message=r.error_message,
                current_stage=r.current_stage,
                stage_started_at=r.stage_started_at.isoformat() if r.stage_started_at else None,
                stage_message=r.stage_message,
                healing_attempt=r.healing_attempt,
                agentic_summary=r.agentic_summary,
                browser_auth=r.browser_auth,
            )
        )

    return PaginatedRunsResponse(
        runs=results, total=total, limit=limit, offset=offset, has_more=(offset + limit) < total
    )


@router.get("/runs/{id}")
async def get_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    runtime = _runtime()
    run_db = session.get(DBTestRun, id)
    if not run_db:
        raise HTTPException(status_code=404, detail="Run not found")

    if project_id:
        if run_db.project_id:
            if project_id == "default":
                if run_db.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Run not found")
            elif run_db.project_id != project_id:
                raise HTTPException(status_code=404, detail="Run not found")

    runs_dir = _runs_dir()
    run_dir = runs_dir / id
    browser_metadata = run_files.load_run_browser_metadata(run_dir)
    if not run_dir.exists():
        browser_metadata = run_files.augment_active_browser_metadata(browser_metadata, run_db.status)
        payload = {
            "id": id,
            "status": run_db.status,
            "effective_status": run_db.status or "unknown",
            "spec_name": run_db.spec_name,
            "test_name": run_db.test_name,
            "agentic_summary": run_db.agentic_summary,
            "browser_auth": run_db.browser_auth,
            "current_stage": run_db.current_stage,
            "stage_started_at": run_db.stage_started_at.isoformat() if run_db.stage_started_at else None,
            "stage_message": run_db.stage_message,
            "error_message": run_db.error_message,
            "healing_attempt": run_db.healing_attempt,
            "queue_position": run_db.queue_position,
            "queued_at": run_db.queued_at.isoformat() if run_db.queued_at else None,
            "started_at": run_db.started_at.isoformat() if run_db.started_at else None,
            "completed_at": run_db.completed_at.isoformat() if run_db.completed_at else None,
            "temporal_workflow_id": run_db.temporal_workflow_id,
            "temporal_run_id": run_db.temporal_run_id,
            "browser_runtime": browser_metadata.get("browser_runtime"),
            "live_view_available": bool(browser_metadata.get("live_view_available")),
            "runtime_message": browser_metadata.get("runtime_message"),
            "vnc_url": browser_metadata.get("vnc_url"),
            "display_diagnostics": browser_metadata.get("display_diagnostics"),
            "note": "Files missing",
        }
        payload.update(await run_files.compose_test_run_log_payload(run_db, run_dir))
        return payload

    plan_file = run_dir / "plan.json"
    run_file = run_dir / "run.json"
    export_file = run_dir / "export.json"
    validation_file = run_dir / "validation.json"
    pipeline_error = run_files._read_json_if_exists(run_dir / "pipeline_error.json")
    pipeline_error_message = run_files._pipeline_error_message(pipeline_error)

    data = {
        "id": id,
        "status": run_db.status,
        "spec_name": run_db.spec_name,
        "test_name": run_db.test_name,
        "agentic_summary": run_db.agentic_summary,
        "browser_auth": run_db.browser_auth,
        "current_stage": run_db.current_stage,
        "stage_started_at": run_db.stage_started_at.isoformat() if run_db.stage_started_at else None,
        "stage_message": run_db.stage_message,
        "error_message": run_db.error_message or pipeline_error_message,
        "healing_attempt": run_db.healing_attempt,
        "queue_position": run_db.queue_position,
        "queued_at": run_db.queued_at.isoformat() if run_db.queued_at else None,
        "started_at": run_db.started_at.isoformat() if run_db.started_at else None,
        "completed_at": run_db.completed_at.isoformat() if run_db.completed_at else None,
        "temporal_workflow_id": run_db.temporal_workflow_id,
        "temporal_run_id": run_db.temporal_run_id,
        "browser_runtime": browser_metadata.get("browser_runtime"),
        "live_view_available": bool(browser_metadata.get("live_view_available")),
        "runtime_message": browser_metadata.get("runtime_message"),
        "vnc_url": browser_metadata.get("vnc_url"),
    }

    if run_db.status in ["running", "pending"] and not runtime.is_process_active(id):
        pass

    if plan_file.exists():
        data["plan"] = json.loads(plan_file.read_text())
    if run_file.exists():
        data["run"] = json.loads(run_file.read_text())
    if export_file.exists():
        export_data = json.loads(export_file.read_text())
        data["export"] = export_data
        test_path_str = export_data.get("testFilePath")
        if test_path_str:
            test_path = _base_dir() / test_path_str
            if test_path.exists():
                data["generated_code"] = test_path.read_text()
            else:
                test_path = run_dir / test_path_str
                if test_path.exists():
                    data["generated_code"] = test_path.read_text()
    if validation_file.exists():
        data["validation"] = json.loads(validation_file.read_text())
    healing_attempts_file = run_dir / "healing_attempts.json"
    if healing_attempts_file.exists():
        data["healing_attempts"] = json.loads(healing_attempts_file.read_text())
    failure_evidence_file = run_dir / "failure_evidence_packet.json"
    if failure_evidence_file.exists():
        data["failure_evidence"] = json.loads(failure_evidence_file.read_text())

    run_status = str(run_db.status or "")
    validation_status = data.get("validation", {}).get("status")
    run_final_state = data.get("run", {}).get("finalState")
    run_is_active = run_status.lower() in run_files.ACTIVE_RUN_STATUSES
    run_is_finalized = run_files._is_terminal_run_status(run_status) or bool(run_db.completed_at)
    effective_status = run_status or "unknown"
    if run_is_active:
        effective_status = run_status
    elif run_is_finalized:
        if validation_status == "success":
            effective_status = "passed"
        elif validation_status == "failed":
            effective_status = "failed"
        elif run_final_state:
            effective_status = run_final_state
    elif run_final_state:
        effective_status = run_final_state
    data["effective_status"] = effective_status
    browser_metadata = run_files.augment_active_browser_metadata(browser_metadata, effective_status)
    data.update(
        {
            "browser_runtime": browser_metadata.get("browser_runtime"),
            "live_view_available": bool(browser_metadata.get("live_view_available")),
            "runtime_message": browser_metadata.get("runtime_message"),
            "vnc_url": browser_metadata.get("vnc_url"),
            "display_diagnostics": browser_metadata.get("display_diagnostics"),
        }
    )

    data.update(await run_files.compose_test_run_log_payload(run_db, run_dir))

    artifacts = []
    diagnostic_artifacts = []
    for f in run_dir.glob("**/*"):
        if not f.is_file():
            continue
        try:
            rel_path = f.relative_to(runs_dir)
        except ValueError:
            continue
        if f.suffix.lower() in [".png", ".jpg", ".jpeg", ".webm", ".mp4"]:
            try:
                artifacts.append(
                    {
                        "name": f.name,
                        "path": f"/artifacts/{rel_path}",
                        "type": "image" if f.suffix.lower() in [".png", ".jpg", ".jpeg"] else "video",
                        "modified_at": datetime.utcfromtimestamp(f.stat().st_mtime).isoformat(),
                    }
                )
            except OSError:
                continue
        elif (
            f.name
            in {
                "healing_attempts.json",
                "validation.json",
                "agentic_summary.json",
                "failure_evidence_packet.json",
            }
            or f.name.startswith("failure_evidence_packet_attempt_")
            or f.name == "error-context.md"
        ):
            try:
                diagnostic_artifacts.append(
                    {
                        "name": f.name,
                        "path": f"/artifacts/{rel_path}",
                        "type": "json" if f.suffix.lower() == ".json" else "text",
                        "modified_at": datetime.utcfromtimestamp(f.stat().st_mtime).isoformat(),
                    }
                )
            except OSError:
                continue
    data["artifacts"] = artifacts
    data["diagnostic_artifacts"] = diagnostic_artifacts

    report_index = run_dir / "report" / "index.html"
    if report_index.exists():
        data["report_url"] = f"/artifacts/{id}/report/index.html"

    return data


@router.delete("/runs/{id}", status_code=204)
def delete_run(id: str, session: Session = Depends(get_session)):
    """Delete a test run and its artifacts."""
    run_db = session.get(DBTestRun, id)
    if not run_db:
        raise HTTPException(status_code=404, detail="Run not found")

    if run_db.status in ("running", "in_progress", "queued", "pending"):
        raise HTTPException(status_code=409, detail="Cannot delete an active run")

    session.delete(run_db)
    session.commit()

    return Response(status_code=204)


@router.post("/runs/{id}/progress")
def update_run_progress(id: str, update: ProgressUpdate, session: Session = Depends(get_session)):
    """Update run progress - called by CLI to report stage transitions."""
    run = session.get(DBTestRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    run.current_stage = update.stage
    run.stage_started_at = _utcnow()
    if update.message:
        run.stage_message = update.message
    if update.healing_attempt is not None:
        run.healing_attempt = update.healing_attempt

    session.add(run)
    session.commit()

    logger.debug(f"Progress update for {id}: stage={update.stage}, message={update.message}")

    return {"status": "updated", "run_id": id, "current_stage": run.current_stage, "stage_message": run.stage_message}


@router.post("/runs/{id}/agentic-summary")
def update_run_agentic_summary(id: str, update: AgenticSummaryUpdate, session: Session = Depends(get_session)):
    """Update compact Agentic QA summary for a run."""
    run = session.get(DBTestRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    run.agentic_summary = update.summary
    total_cost = (update.summary.get("costs") or {}).get("total_usd")
    try:
        run.total_cost_usd = float(total_cost) if total_cost is not None else None
    except (TypeError, ValueError):
        run.total_cost_usd = None
    session.add(run)
    session.commit()

    return {"status": "updated", "run_id": id, "agentic_summary": run.agentic_summary}


@router.get("/runs/{id}/log/stream")
async def stream_run_log(id: str, session: Session = Depends(get_session)):
    """Stream execution log in real-time using Server-Sent Events (SSE)."""
    run = session.get(DBTestRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    run_dir = _runs_dir() / id
    log_file = run_dir / "execution.log"

    def _read_log_from_position(log_path, position):
        if not log_path.exists():
            return "", position
        with open(log_path) as f:
            f.seek(position)
            content = f.read()
            return content, f.tell()

    async def generate():
        last_position = 0
        consecutive_no_change = 0

        try:
            while True:
                try:
                    with Session(engine) as check_session:
                        current_run = check_session.get(DBTestRun, id)
                        if current_run and current_run.status in ["passed", "failed", "stopped", "cancelled", "error"]:
                            remaining, _ = await asyncio.to_thread(_read_log_from_position, log_file, last_position)
                            if remaining:
                                yield f"data: {json.dumps({'log': remaining})}\n\n"

                            yield f"data: {json.dumps({'status': 'complete', 'final_status': current_run.status})}\n\n"
                            break

                    new_content, new_position = await asyncio.to_thread(
                        _read_log_from_position, log_file, last_position
                    )
                    if new_content:
                        yield f"data: {json.dumps({'log': new_content})}\n\n"
                        last_position = new_position
                        consecutive_no_change = 0
                    else:
                        consecutive_no_change += 1

                    if consecutive_no_change > 600:
                        yield f"data: {json.dumps({'status': 'timeout', 'message': 'Stream timed out after 10 minutes of no activity'})}\n\n"
                        break

                    await asyncio.sleep(1)

                except Exception as e:
                    logger.error(f"Error streaming log for {id}: {e}")
                    yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
                    break
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            logger.debug(f"Log stream ended for run {id}")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/runs/{id}/events/stream")
async def stream_run_events(id: str, request: Request, session: Session = Depends(get_session)):
    """Stream typed run status and diagnostic frames separately from raw log bytes."""
    run = session.get(DBTestRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    async def generate():
        last_status_payload: str | None = None
        last_health_payload: str | None = None
        idle_ticks = 0

        while True:
            if await request.is_disconnected():
                break

            try:
                with Session(engine) as check_session:
                    current_run = check_session.get(DBTestRun, id)
                    if not current_run:
                        yield f"event: error\ndata: {json.dumps({'message': 'Run not found'})}\n\n"
                        break

                    run_dir = _runs_dir() / id
                    payload = await run_files.compose_test_run_log_payload(current_run, run_dir)
                    status_payload = {
                        "run_id": id,
                        "status": current_run.status,
                        "current_stage": current_run.current_stage,
                        "stage_started_at": current_run.stage_started_at.isoformat()
                        if current_run.stage_started_at
                        else None,
                        "stage_message": current_run.stage_message,
                        "temporal_workflow_id": current_run.temporal_workflow_id,
                        "temporal_run_id": current_run.temporal_run_id,
                    }
                    health_payload = {
                        "run_id": id,
                        "health": payload.get("health") or {},
                        "diagnostics": {
                            "temporal": (payload.get("diagnostics") or {}).get("temporal"),
                            "browser_pool": (payload.get("diagnostics") or {}).get("browser_pool"),
                            "agent_progress": (payload.get("diagnostics") or {}).get("agent_progress"),
                        },
                        "blocker_message": payload.get("blocker_message"),
                    }

                    serialized_status = json.dumps(status_payload, sort_keys=True)
                    serialized_health = json.dumps(health_payload, sort_keys=True)
                    emitted = False
                    if serialized_status != last_status_payload:
                        yield f"event: status\ndata: {serialized_status}\n\n"
                        last_status_payload = serialized_status
                        emitted = True
                    if serialized_health != last_health_payload:
                        yield f"event: diagnostic\ndata: {serialized_health}\n\n"
                        last_health_payload = serialized_health
                        emitted = True

                    if emitted:
                        idle_ticks = 0
                    else:
                        idle_ticks += 1
                        if idle_ticks >= 5:
                            yield f": heartbeat {datetime.utcnow().isoformat()}\n\n"
                            idle_ticks = 0

                    if current_run.status in ["passed", "failed", "stopped", "cancelled", "error"]:
                        yield f"event: complete\ndata: {json.dumps({'run_id': id, 'status': current_run.status})}\n\n"
                        break

            except Exception as e:
                logger.error(f"Error streaming diagnostics for {id}: {e}")
                yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
                break

            await asyncio.sleep(3)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs")
async def create_run(request: RunRequest, session: Session = Depends(get_session)):
    """Create a new test run."""
    runtime = _runtime()

    specs_dir = _specs_dir()
    runs_dir = _runs_dir()
    spec_path = specs_dir / request.spec_name
    if not spec_path.exists():
        if not request.spec_name.endswith(".md"):
            candidate = specs_dir / (request.spec_name + ".md")
            if candidate.exists():
                spec_path = candidate
                request.spec_name = request.spec_name + ".md"

        if not spec_path.exists():
            slug = re.sub(r"[^a-z0-9]+", "-", request.spec_name.lower()).strip("-")
            for pattern in [f"**/{slug}.md", f"**/{slug}*.md"]:
                matches = list(specs_dir.glob(pattern))
                if matches:
                    spec_path = matches[0]
                    request.spec_name = str(spec_path.relative_to(specs_dir))
                    break

        if not spec_path.exists():
            matching_run = session.exec(
                select(DBTestRun)
                .where(DBTestRun.test_name == request.spec_name)
                .order_by(DBTestRun.created_at.desc())
                .limit(1)
            ).first()
            if matching_run and matching_run.spec_name:
                candidate = specs_dir / matching_run.spec_name
                if candidate.exists():
                    spec_path = candidate
                    request.spec_name = matching_run.spec_name

        if not spec_path.exists():
            raise HTTPException(status_code=404, detail=f"Spec not found: {request.spec_name}")

    now = _utcnow()
    run_id = now.strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    spec_content = await asyncio.to_thread(spec_path.read_text)
    await asyncio.to_thread((run_dir / "spec.md").write_text, spec_content)
    await asyncio.to_thread((run_dir / "status.txt").write_text, "queued")

    try_code_path = runtime.get_try_code_path(request.spec_name, spec_path)
    queued_count = session.exec(select(func.count()).select_from(DBTestRun).where(DBTestRun.status == "queued")).one()
    queue_position = queued_count + 1

    target = (request.target or "browser").lower()
    if target not in ("browser", "mobile"):
        raise HTTPException(status_code=400, detail="target must be 'browser' or 'mobile'")
    platform = (request.platform or "ios").lower()
    if target == "mobile" and platform not in ("ios", "android"):
        raise HTTPException(status_code=400, detail="platform must be 'ios' or 'android'")

    storage_state_path = None
    browser_auth_intent: dict[str, Any] = {
        "mode": "none",
        "requested_browser_auth_session_id": None,
        "browser_auth_session_id": None,
        "browser_auth_session_name": None,
        "use_project_default_browser_auth": False,
        "project_default_used": False,
        "storage_state_attached": False,
    }
    if target == "browser":
        requested_browser_auth_session_id = request.browser_auth_session_id
        requested_project_default_auth = bool(request.use_project_default_browser_auth)
        auth_conflict_warning: str | None = None
        if runtime._has_browser_auth_selection(
            browser_auth_session_id=requested_browser_auth_session_id,
            use_project_default_browser_auth=requested_project_default_auth,
        ) and _is_login_specific_spec(request.spec_name, spec_content):
            auth_conflict_warning = (
                "Selected browser auth was ignored because this spec appears to test login/logout."
            )
            requested_browser_auth_session_id = None
            requested_project_default_auth = False
        try:
            storage_state_path, browser_auth_intent = runtime._resolve_browser_auth_storage_state_for_run(
                session,
                request.project_id,
                run_dir=run_dir,
                browser_auth_session_id=requested_browser_auth_session_id,
                use_project_default_browser_auth=requested_project_default_auth,
            )
        except HTTPException:
            await asyncio.to_thread((run_dir / "status.txt").write_text, "error")
            raise
        if auth_conflict_warning:
            browser_auth_intent["auth_conflict_warning"] = auth_conflict_warning
            browser_auth_intent["requested_browser_auth_session_id"] = (
                request.browser_auth_session_id or ""
            ).strip() or None
            browser_auth_intent["use_project_default_browser_auth"] = bool(request.use_project_default_browser_auth)

    run = DBTestRun(
        id=run_id,
        spec_name=request.spec_name,
        test_name=request.spec_name,
        status="queued",
        browser=f"mobile-{platform}" if target == "mobile" else (request.browser or "chromium"),
        test_type="mobile" if target == "mobile" else "browser",
        queued_at=now,
        queue_position=queue_position,
        project_id=request.project_id,
        browser_auth=browser_auth_intent,
    )
    session.add(run)
    session.commit()

    if target == "mobile":
        from orchestrator.config import settings as app_settings

        payload = {
            "target": "mobile",
            "spec_path": str(spec_path),
            "run_dir": str(run_dir),
            "platform": platform,
            "appium_server_url": request.appium_server_url,
            "capabilities_file": request.capabilities_file,
            "batch_id": None,
            "spec_name": request.spec_name,
            "project_id": request.project_id,
        }
        await runtime._start_test_run_temporal_or_fail(
            run,
            payload,
            session,
            task_queue=app_settings.temporal_workflow_task_queue,
        )

        return {
            "id": run_id,
            "status": "queued",
            "queue_position": queue_position,
            "mode": "mobile",
            "platform": platform,
            "temporal_workflow_id": run.temporal_workflow_id,
            "temporal_run_id": run.temporal_run_id,
        }

    hybrid_mode = request.hybrid or request.ralph or False
    max_iterations = request.max_iterations or 20

    payload = {
        "target": "browser",
        "spec_path": str(spec_path),
        "run_dir": str(run_dir),
        "try_code_path": try_code_path,
        "browser": request.browser,
        "hybrid": hybrid_mode,
        "max_iterations": max_iterations,
        "batch_id": None,
        "spec_name": request.spec_name,
        "project_id": request.project_id,
        "model_tier": request.model_tier,
    }
    if storage_state_path:
        payload["storage_state_path"] = storage_state_path
    payload["browser_auth_context"] = browser_auth_intent
    from orchestrator.config import settings as app_settings

    planned_runtime = dict(browser_runtime_status())
    planned_headless = not bool(planned_runtime.get("live_view_available"))
    run_files.write_run_browser_metadata(
        run_dir,
        run_files.build_run_browser_metadata(
            headless=planned_headless,
            phase="scheduled",
            task_queue=app_settings.temporal_browser_workflow_task_queue,
        ),
    )
    await runtime._start_test_run_temporal_or_fail(run, payload, session)

    return {
        "id": run_id,
        "status": "queued",
        "queue_position": queue_position,
        "mode": "hybrid" if hybrid_mode else "native",
        "hybrid_mode": hybrid_mode,
        "max_iterations": max_iterations if hybrid_mode else None,
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
        "browser_auth": browser_auth_intent,
    }


@router.get("/api/mobile-testing/health")
def mobile_testing_health(
    platform: str = Query(default="ios"),
    appium_server_url: str | None = Query(default=None),
    capabilities_file: str | None = Query(default=None),
    require_server: bool = Query(default=True),
):
    """Check local Appium/mobile prerequisites before running mobile tests."""
    from orchestrator.workflows.mobile_appium import AppiumPreflightChecker, MobileAppiumConfig

    config = MobileAppiumConfig.from_env(
        platform=platform,
        appium_server_url=appium_server_url,
        capabilities_file=capabilities_file,
    )
    result = AppiumPreflightChecker(config).run(require_server=require_server)
    return result.to_dict()


@router.post("/runs/{id}/stop")
async def stop_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """Stop a running or queued test task."""
    runtime = _runtime()

    run = session.get(DBTestRun, id)
    if project_id and run:
        if run.project_id:
            if project_id == "default":
                if run.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Run not found")
            elif run.project_id != project_id:
                raise HTTPException(status_code=404, detail="Run not found")

    if run and run.temporal_workflow_id and run.status not in ["passed", "failed", "stopped", "cancelled", "error", "completed"]:
        await runtime._signal_test_run_temporal(run, "stop", "manual_stop")
        cleanup = await runtime._cleanup_test_run_runtime(id, "manual temporal stop")
        run.status = "stopped"
        run.queue_position = None
        run.completed_at = _utcnow()
        run.stage_message = "Stop requested"
        session.add(run)
        session.commit()
        run_dir = _runs_dir() / id
        if run_dir.exists():
            (run_dir / "status.txt").write_text("stopped")
        if run.batch_id:
            runtime.update_batch_stats(run.batch_id)
        return {
            "status": "stopped",
            "id": id,
            "temporal_workflow_id": run.temporal_workflow_id,
            "temporal_run_id": run.temporal_run_id,
            "message": "Temporal stop requested",
            "cleanup": cleanup,
        }

    if run and run.status == "queued":
        if runtime.PROCESS_MANAGER and runtime.PROCESS_MANAGER.stop(id):
            logger.info(f"Cancelled queued run {id}")

        run.status = "cancelled"
        run.queue_position = None
        run.completed_at = _utcnow()
        session.add(run)
        session.commit()

        run_dir = _runs_dir() / id
        if run_dir.exists():
            (run_dir / "status.txt").write_text("cancelled")

        if run.batch_id:
            runtime.update_batch_stats(run.batch_id)

        cleanup = await runtime._cleanup_test_run_runtime(id, "queued run cancelled")

        return {"status": "cancelled", "id": id, "message": "Run was cancelled from queue", "cleanup": cleanup}

    process = runtime.get_process(id)
    if process:
        logger.info(f"Stopping run {id} (PID {process.pid})...")

        if runtime.PROCESS_MANAGER:
            stopped = runtime.PROCESS_MANAGER.stop(id, timeout=5)
            if stopped:
                logger.info(f"Successfully stopped process group for {id}")
            else:
                logger.warning(f"ProcessManager failed to stop {id}, falling back to terminate()")
                process.terminate()
        else:
            process.terminate()

        if run:
            run.status = "stopped"
            run.completed_at = _utcnow()
            session.add(run)
            session.commit()

            run_dir = _runs_dir() / id
            if run_dir.exists():
                (run_dir / "status.txt").write_text("stopped")

            if run.batch_id:
                runtime.update_batch_stats(run.batch_id)

        cleanup = await runtime._cleanup_test_run_runtime(id, "running run stopped")

        return {"status": "stopped", "id": id, "cleanup": cleanup}

    if run:
        if run.status in ["passed", "failed", "stopped", "cancelled", "error"]:
            return {"status": "already_completed", "id": id, "current_status": run.status}

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return {"status": "not_running", "message": "Run is not currently active or queued"}


@router.post("/runs/bulk", response_model=CreateBatchResponse)
async def create_bulk_run(request: BulkRunRequest, session: Session = Depends(get_session)):
    """Create multiple test runs in bulk as a regression batch."""
    from orchestrator.services.batch_executor import BatchConfig, create_regression_batch, select_regression_specs

    runtime = _runtime()
    hybrid_mode = request.hybrid or request.ralph or False
    max_iterations = request.max_iterations or 20

    runtime._validate_browser_auth_selection_for_project(
        session,
        request.project_id,
        browser_auth_session_id=request.browser_auth_session_id,
        use_project_default_browser_auth=bool(request.use_project_default_browser_auth),
    )

    config = BatchConfig(
        project_id=request.project_id,
        browser=request.browser,
        hybrid_mode=hybrid_mode,
        max_iterations=max_iterations,
        tags=request.tags,
        automated_only=request.automated_only or False,
        spec_names=request.spec_names,
        test_data_refs=runtime._normalize_request_test_data_refs(request.test_data_refs),
        test_data_refs_by_spec=request.test_data_refs_by_spec,
    )

    try:
        selected_spec_names = select_regression_specs(config, session)
        resolved_refs_by_spec = _validate_bulk_test_data_refs(
            session,
            project_id=request.project_id,
            spec_names=selected_spec_names,
            shared_refs=request.test_data_refs,
            refs_by_spec=request.test_data_refs_by_spec,
        )
        config.test_data_refs_by_spec = resolved_refs_by_spec
        result = create_regression_batch(config, session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    from orchestrator.config import settings as app_settings

    for task_args in result.tasks_to_start:
        run = session.get(DBTestRun, task_args["run_id"])
        if not run:
            continue
        requested_browser_auth_session_id = request.browser_auth_session_id
        requested_project_default_auth = bool(request.use_project_default_browser_auth)
        auth_conflict_warning: str | None = None
        try:
            task_spec_content = Path(task_args["spec_path"]).read_text(encoding="utf-8")
        except Exception:
            task_spec_content = ""
        if runtime._has_browser_auth_selection(
            browser_auth_session_id=requested_browser_auth_session_id,
            use_project_default_browser_auth=requested_project_default_auth,
        ) and _is_login_specific_spec(task_args["spec_name"], task_spec_content):
            auth_conflict_warning = (
                "Selected browser auth was ignored because this spec appears to test login/logout."
            )
            requested_browser_auth_session_id = None
            requested_project_default_auth = False
        storage_state_path, browser_auth_intent = runtime._resolve_browser_auth_storage_state_for_run(
            session,
            task_args["project_id"],
            run_dir=Path(task_args["run_dir"]),
            browser_auth_session_id=requested_browser_auth_session_id,
            use_project_default_browser_auth=requested_project_default_auth,
        )
        if auth_conflict_warning:
            browser_auth_intent["auth_conflict_warning"] = auth_conflict_warning
            browser_auth_intent["requested_browser_auth_session_id"] = (
                request.browser_auth_session_id or ""
            ).strip() or None
            browser_auth_intent["use_project_default_browser_auth"] = bool(request.use_project_default_browser_auth)
        task_test_data_refs = runtime._normalize_request_test_data_refs(task_args.get("test_data_refs") or [])
        if task_test_data_refs:
            browser_auth_intent["test_data_refs"] = task_test_data_refs
        run.browser_auth = browser_auth_intent
        session.add(run)
        session.commit()
        payload = {
            "target": "browser",
            "spec_path": task_args["spec_path"],
            "run_dir": task_args["run_dir"],
            "try_code_path": task_args["try_code_path"],
            "browser": task_args["browser"],
            "hybrid": task_args["hybrid"],
            "max_iterations": task_args["max_iterations"],
            "batch_id": task_args["batch_id"],
            "spec_name": task_args["spec_name"],
            "project_id": task_args["project_id"],
            "model_tier": request.model_tier,
            "test_data_refs": task_test_data_refs,
        }
        if storage_state_path:
            payload["storage_state_path"] = storage_state_path
        payload["browser_auth_context"] = browser_auth_intent
        planned_runtime = dict(browser_runtime_status())
        planned_headless = not bool(planned_runtime.get("live_view_available"))
        run_files.write_run_browser_metadata(
            Path(task_args["run_dir"]),
            run_files.build_run_browser_metadata(
                headless=planned_headless,
                phase="scheduled",
                task_queue=app_settings.temporal_browser_workflow_task_queue,
            ),
        )
        await runtime._start_test_run_temporal_or_fail(run, payload, session)

    return CreateBatchResponse(
        batch_id=result.batch_id,
        run_ids=result.run_ids,
        count=len(result.run_ids),
        mode="hybrid" if hybrid_mode else "native",
        max_iterations=max_iterations if hybrid_mode else None,
    )
