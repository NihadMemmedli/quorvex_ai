"""
Auto Pilot API Router

Provides endpoints for controlling and monitoring end-to-end Auto Pilot
pipeline sessions that orchestrate: exploration -> requirements ->
test ideas -> spec generation -> test generation -> reporting.

Background Task Management:
- Running pipelines tracked in-memory with asyncio.Tasks
- Pipeline state persisted in DB for crash recovery
- Resume support for pipelines interrupted by server restarts
- Reactive mode with mid-execution question/answer flow
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .db import engine, get_session
from .middleware.auth import get_current_user_optional
from .models_db import (
    AutoPilotPhase,
    AutoPilotQuestion,
    AutoPilotSession,
    AutoPilotSpecTask,
    AutoPilotTestTask,
    TestRun,
)

logger = logging.getLogger(__name__)

# ========== Configuration ==========

MAX_TRACKED_PIPELINES = 5
MAX_ACTIVE_SESSIONS_PER_USER = 2

router = APIRouter(prefix="/autopilot", tags=["autopilot"])


# ========== Background Task Storage ==========
# Track running pipelines: session_id -> (asyncio.Task, AutoPilotPipeline, user_key)
_running_pipelines: dict[str, tuple[asyncio.Task, Any, str]] = {}

# Phase definitions in execution order
PHASE_DEFINITIONS = [
    ("exploration", 0),
    ("requirements", 1),
    ("test_ideas", 2),
    ("spec_generation", 3),
    ("test_generation", 4),
    ("reporting", 5),
]


# ========== Pydantic Request/Response Models ==========


class AutoPilotStartRequest(BaseModel):
    """Request to start an Auto Pilot pipeline session."""

    entry_urls: list[str] = Field(..., min_length=1, description="URLs to explore")
    project_id: str = Field(default="default")
    login_url: str | None = None
    credentials: dict | None = None
    test_data: dict | None = None
    instructions: str | None = None
    strategy: str = Field(default="goal_directed")
    max_interactions: int = Field(default=50, ge=1, le=200)
    max_depth: int = Field(default=10, ge=1, le=50)
    timeout_minutes: int = Field(default=30, ge=1, le=120)
    reactive_mode: bool = Field(default=True, description="Ask questions at checkpoints")
    auto_continue_hours: int = Field(default=24, ge=1, le=168)
    priority_threshold: str = Field(default="low")
    max_specs: int = Field(default=50, ge=1, le=200)
    parallel_generation: int = Field(default=2, ge=1, le=5)
    hybrid_healing: bool = Field(default=False)


class AutoPilotSessionResponse(BaseModel):
    """Response model for an Auto Pilot session."""

    id: str
    project_id: str | None
    entry_urls: list[str]
    status: str
    current_phase: str | None
    current_phase_progress: float
    overall_progress: float
    phases_completed: list[str]
    total_pages_discovered: int
    total_flows_discovered: int
    total_requirements_generated: int
    total_specs_generated: int
    total_tests_generated: int
    total_tests_passed: int
    total_tests_failed: int
    coverage_percentage: float
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    instructions: str | None
    config: dict
    can_resume: bool = False
    resume_reason: str | None = None
    failed_phase: str | None = None


class AutoPilotPhaseResponse(BaseModel):
    """Response model for an Auto Pilot phase."""

    id: int
    session_id: str
    phase_name: str
    phase_order: int
    status: str
    progress: float
    current_step: str | None
    items_total: int
    items_completed: int
    result_summary: dict
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None


class AutoPilotQuestionResponse(BaseModel):
    """Response model for a pipeline question."""

    id: int
    session_id: str
    phase_name: str
    question_type: str
    question_text: str
    context: dict
    suggested_answers: list[str]
    default_answer: str | None
    status: str
    answer_text: str | None
    answered_at: datetime | None
    auto_continue_at: datetime | None
    created_at: datetime


class AnswerQuestionRequest(BaseModel):
    """Request to answer a pipeline question."""

    question_id: int
    answer_text: str


class SpecTaskResponse(BaseModel):
    """Response model for a spec generation task."""

    id: int
    session_id: str
    requirement_id: int | None
    requirement_title: str | None
    priority: str
    status: str
    spec_name: str | None
    spec_path: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class TestTaskResponse(BaseModel):
    """Response model for a test generation task."""

    id: int
    session_id: str
    spec_task_id: int | None
    spec_name: str | None
    spec_path: str | None = None
    run_id: str | None
    status: str
    current_stage: str | None
    generation_mode: str | None
    healing_attempt: int
    test_path: str | None
    passed: bool | None
    error_summary: str | None
    artifact_count: int = 0
    log_available: bool = False
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class TestTaskArtifactResponse(BaseModel):
    """Artifact metadata for an Auto Pilot test task."""

    name: str
    path: str
    type: str


class TestTaskDetailResponse(TestTaskResponse):
    """Detailed response model for a test generation task."""

    run_dir: str | None = None
    pipeline_error: dict[str, Any] | None = None
    agentic_summary: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    artifacts: list[TestTaskArtifactResponse] = Field(default_factory=list)
    report_url: str | None = None
    log_excerpt: str | None = None


# ========== Helper Functions ==========


RUNS_DIR = Path("runs")


def _get_user_key(user, request: Request) -> str:
    """Get a unique key for the user (user ID or IP address)."""
    if user:
        return f"user:{user.id}"
    return f"ip:{request.client.host}" if request.client else "ip:unknown"


def _sweep_done_tasks():
    """Remove completed tasks from _running_pipelines."""
    done_keys = [k for k, (task, _, _) in _running_pipelines.items() if task.done()]
    for k in done_keys:
        _running_pipelines.pop(k, None)
    if done_keys:
        logger.debug(f"Swept {len(done_keys)} completed Auto Pilot tasks")


def _count_user_active_sessions(user_key: str) -> int:
    """Count active (non-done) sessions for a user."""
    return sum(1 for _, (task, _, uk) in _running_pipelines.items() if uk == user_key and not task.done())


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    """Read a JSON artifact, returning None when it is absent or invalid."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {"value": data}
    except Exception as exc:
        logger.debug(f"Unable to read JSON artifact {path}: {exc}")
        return None


def _fallback_task_run_dir(task: AutoPilotTestTask) -> Path | None:
    if task.run_id:
        return RUNS_DIR / task.run_id
    if task.spec_name:
        return RUNS_DIR / "autopilot" / task.session_id / Path(task.spec_name).stem
    return None


def _collect_task_artifacts(run_dir: Path | None) -> list[TestTaskArtifactResponse]:
    if not run_dir or not run_dir.exists():
        return []

    artifacts: list[TestTaskArtifactResponse] = []
    for f in run_dir.glob("**/*"):
        if not f.is_file():
            continue
        suffix = f.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webm", ".mp4", ".zip", ".json", ".txt"}:
            continue
        try:
            rel_path = f.relative_to(RUNS_DIR)
        except ValueError:
            continue
        artifact_type = "file"
        if suffix in {".png", ".jpg", ".jpeg"}:
            artifact_type = "image"
        elif suffix in {".webm", ".mp4"}:
            artifact_type = "video"
        elif suffix == ".json":
            artifact_type = "json"
        elif suffix == ".txt":
            artifact_type = "text"
        artifacts.append(
            TestTaskArtifactResponse(
                name=f.name,
                path=f"/artifacts/{rel_path}",
                type=artifact_type,
            )
        )
    return artifacts


def _task_artifact_summary(task: AutoPilotTestTask) -> tuple[int, bool]:
    run_dir = _fallback_task_run_dir(task)
    if not run_dir or not run_dir.exists():
        return 0, False
    artifacts = _collect_task_artifacts(run_dir)
    return len(artifacts), (run_dir / "execution.log").exists()


def _get_failed_phase(session: Session, session_id: str) -> str | None:
    """Return the most recent failed phase name for a session."""
    stmt = (
        select(AutoPilotPhase)
        .where(AutoPilotPhase.session_id == session_id)
        .where(AutoPilotPhase.status == "failed")
        .order_by(AutoPilotPhase.completed_at.desc(), AutoPilotPhase.phase_order.desc())
    )
    phase = session.exec(stmt).first()
    return phase.phase_name if phase else None


def _get_resume_metadata(
    ap_session: AutoPilotSession,
    session: Session | None = None,
) -> tuple[bool, str | None, str | None]:
    """Classify whether persisted Auto Pilot state can be resumed."""
    owns_session = session is None
    db = session or Session(engine)
    try:
        failed_phase = _get_failed_phase(db, ap_session.id)
        if ap_session.status == "failed" and not failed_phase:
            failed_phase = ap_session.current_phase
        active_entry = _running_pipelines.get(ap_session.id)
        task_active = bool(active_entry and not active_entry[0].done())

        if ap_session.status in ("completed", "cancelled"):
            return False, None, failed_phase
        if ap_session.status == "paused":
            failed_phase = failed_phase or ap_session.current_phase
            return True, "Session is paused", failed_phase
        if ap_session.status == "awaiting_input":
            return True, "Session is waiting for checkpoint input", failed_phase
        if ap_session.status in ("pending", "running") and not task_active:
            return True, "Pipeline is not active in memory", failed_phase
        if ap_session.status == "failed" and failed_phase:
            return True, f"Retry failed phase: {failed_phase.replace('_', ' ')}", failed_phase
        return False, None, failed_phase
    finally:
        if owns_session:
            db.close()


def _session_to_response(
    ap_session: AutoPilotSession,
    session: Session | None = None,
) -> AutoPilotSessionResponse:
    """Convert a DB session model to the API response model."""
    can_resume, resume_reason, failed_phase = _get_resume_metadata(ap_session, session)
    return AutoPilotSessionResponse(
        id=ap_session.id,
        project_id=ap_session.project_id,
        entry_urls=ap_session.entry_urls,
        status=ap_session.status,
        current_phase=ap_session.current_phase,
        current_phase_progress=ap_session.current_phase_progress,
        overall_progress=ap_session.overall_progress,
        phases_completed=ap_session.phases_completed,
        total_pages_discovered=ap_session.total_pages_discovered,
        total_flows_discovered=ap_session.total_flows_discovered,
        total_requirements_generated=ap_session.total_requirements_generated,
        total_specs_generated=ap_session.total_specs_generated,
        total_tests_generated=ap_session.total_tests_generated,
        total_tests_passed=ap_session.total_tests_passed,
        total_tests_failed=ap_session.total_tests_failed,
        coverage_percentage=ap_session.coverage_percentage,
        error_message=ap_session.error_message,
        created_at=ap_session.created_at,
        started_at=ap_session.started_at,
        completed_at=ap_session.completed_at,
        instructions=ap_session.instructions,
        config=ap_session.config,
        can_resume=can_resume,
        resume_reason=resume_reason,
        failed_phase=failed_phase,
    )


def _phase_to_response(phase: AutoPilotPhase) -> AutoPilotPhaseResponse:
    """Convert a DB phase model to the API response model."""
    return AutoPilotPhaseResponse(
        id=phase.id,
        session_id=phase.session_id,
        phase_name=phase.phase_name,
        phase_order=phase.phase_order,
        status=phase.status,
        progress=phase.progress,
        current_step=phase.current_step,
        items_total=phase.items_total,
        items_completed=phase.items_completed,
        result_summary=phase.result_summary,
        error_message=phase.error_message,
        started_at=phase.started_at,
        completed_at=phase.completed_at,
    )


def _question_to_response(q: AutoPilotQuestion) -> AutoPilotQuestionResponse:
    """Convert a DB question model to the API response model."""
    return AutoPilotQuestionResponse(
        id=q.id,
        session_id=q.session_id,
        phase_name=q.phase_name,
        question_type=q.question_type,
        question_text=q.question_text,
        context=q.context,
        suggested_answers=q.suggested_answers,
        default_answer=q.default_answer,
        status=q.status,
        answer_text=q.answer_text,
        answered_at=q.answered_at,
        auto_continue_at=q.auto_continue_at,
        created_at=q.created_at,
    )


def _spec_task_to_response(t: AutoPilotSpecTask) -> SpecTaskResponse:
    """Convert a DB spec task model to the API response model."""
    return SpecTaskResponse(
        id=t.id,
        session_id=t.session_id,
        requirement_id=t.requirement_id,
        requirement_title=t.requirement_title,
        priority=t.priority,
        status=t.status,
        spec_name=t.spec_name,
        spec_path=t.spec_path,
        error_message=t.error_message,
        created_at=t.created_at,
        completed_at=t.completed_at,
    )


def _test_task_to_response(t: AutoPilotTestTask) -> TestTaskResponse:
    """Convert a DB test task model to the API response model."""
    generation_mode = None
    if t.current_stage and "conservative" in t.current_stage:
        generation_mode = "conservative_smoke"
    elif t.current_stage == "native_e2e":
        generation_mode = "native_e2e"
    elif t.test_path:
        generation_mode = "native_e2e"

    artifact_count, log_available = _task_artifact_summary(t)

    return TestTaskResponse(
        id=t.id,
        session_id=t.session_id,
        spec_task_id=t.spec_task_id,
        spec_name=t.spec_name,
        spec_path=t.spec_path,
        run_id=t.run_id,
        status=t.status,
        current_stage=t.current_stage,
        generation_mode=generation_mode,
        healing_attempt=t.healing_attempt,
        test_path=t.test_path,
        passed=t.passed,
        error_summary=t.error_summary,
        artifact_count=artifact_count,
        log_available=log_available,
        created_at=t.created_at,
        started_at=t.started_at,
        completed_at=t.completed_at,
    )


def _test_task_to_detail(t: AutoPilotTestTask) -> TestTaskDetailResponse:
    """Convert a DB test task model and run artifacts to a detailed response."""
    base = _test_task_to_response(t).model_dump()
    run_dir = _fallback_task_run_dir(t)
    artifacts = _collect_task_artifacts(run_dir)
    pipeline_error = _safe_read_json(run_dir / "pipeline_error.json") if run_dir else None
    agentic_summary = _safe_read_json(run_dir / "agentic_summary.json") if run_dir else None
    validation = _safe_read_json(run_dir / "validation.json") if run_dir else None
    report_url = None
    log_excerpt = None

    if run_dir and run_dir.exists():
        report_index = run_dir / "report" / "index.html"
        if report_index.exists():
            try:
                rel_report = report_index.relative_to(RUNS_DIR)
                report_url = f"/artifacts/{rel_report}"
            except ValueError:
                report_url = None

        log_path = run_dir / "execution.log"
        if log_path.exists():
            try:
                log_text = log_path.read_text(errors="replace")
                log_excerpt = log_text[-8000:]
            except Exception as exc:
                logger.debug(f"Unable to read Auto Pilot task log {log_path}: {exc}")

    return TestTaskDetailResponse(
        **base,
        run_dir=str(run_dir) if run_dir else None,
        pipeline_error=pipeline_error,
        agentic_summary=agentic_summary,
        validation=validation,
        artifacts=artifacts,
        report_url=report_url,
        log_excerpt=log_excerpt,
    )


# ========== Background Pipeline Execution ==========


def _build_config_from_session(ap_session) -> "AutoPilotConfig":  # noqa: F821
    """Build an AutoPilotConfig from a DB AutoPilotSession."""
    from orchestrator.workflows.autopilot_pipeline import AutoPilotConfig

    cfg = ap_session.config  # dict from JSON property
    return AutoPilotConfig(
        entry_urls=ap_session.entry_urls,
        project_id=ap_session.project_id or "default",
        login_url=ap_session.login_url,
        credentials=ap_session.credentials,
        test_data=ap_session.test_data,
        instructions=ap_session.instructions,
        strategy=cfg.get("strategy", "goal_directed"),
        max_interactions=cfg.get("max_interactions", 50),
        max_depth=cfg.get("max_depth", 10),
        timeout_minutes=cfg.get("timeout_minutes", 30),
        reactive_mode=cfg.get("reactive_mode", True),
        auto_continue_hours=cfg.get("auto_continue_hours", 24),
        priority_threshold=cfg.get("priority_threshold", "low"),
        max_specs=cfg.get("max_specs", 50),
        parallel_generation=cfg.get("parallel_generation", 2),
        hybrid_healing=cfg.get("hybrid_healing", False),
    )


async def _run_pipeline_background(pipeline, session_id: str):
    """Run the Auto Pilot pipeline in the background.

    Updates the session status in DB on completion or failure.
    Removes itself from _running_pipelines when done.
    """
    try:
        # Load config from DB session
        with Session(engine) as db:
            ap_session = db.get(AutoPilotSession, session_id)
            if not ap_session:
                raise RuntimeError(f"Session {session_id} not found in DB")
            config = _build_config_from_session(ap_session)

        result = await pipeline.run(config)
        logger.info(f"Auto Pilot {session_id} completed: {result}")
    except asyncio.CancelledError:
        logger.info(f"Auto Pilot {session_id} background task cancelled")
        with Session(engine) as db:
            sess = db.get(AutoPilotSession, session_id)
            if sess and sess.status not in ("cancelled", "completed", "paused"):
                sess.status = "cancelled"
                sess.completed_at = datetime.utcnow()
                db.add(sess)
                db.commit()
        raise
    except Exception as e:
        logger.error(f"Auto Pilot {session_id} failed: {e}", exc_info=True)
        with Session(engine) as db:
            sess = db.get(AutoPilotSession, session_id)
            if sess and sess.status not in ("cancelled", "completed"):
                sess.status = "failed"
                sess.error_message = str(e)[:500]
                sess.completed_at = datetime.utcnow()
                db.add(sess)
                db.commit()
    finally:
        _running_pipelines.pop(session_id, None)


def _reset_resumable_state(db: Session, ap_session: AutoPilotSession, failed_phase: str | None) -> None:
    """Prepare persisted rows before recreating a pipeline task."""
    now = datetime.utcnow()
    original_status = ap_session.status
    resume_phase = failed_phase or (ap_session.current_phase if original_status == "paused" else None)
    ap_session.status = "running"
    ap_session.completed_at = None
    ap_session.error_message = None
    if resume_phase:
        ap_session.current_phase = resume_phase
    completed = [phase for phase in ap_session.phases_completed if phase != resume_phase]
    ap_session.phases_completed = completed
    db.add(ap_session)

    if resume_phase:
        stmt = (
            select(AutoPilotPhase)
            .where(AutoPilotPhase.session_id == ap_session.id)
            .where(AutoPilotPhase.phase_name == resume_phase)
        )
        phase = db.exec(stmt).first()
        if phase:
            phase.status = "pending"
            phase.error_message = None
            phase.completed_at = None
            phase.current_step = f"Waiting to resume {resume_phase.replace('_', ' ')}"
            phase.progress = 0.0
            db.add(phase)

    if resume_phase == "spec_generation":
        stmt = (
            select(AutoPilotSpecTask)
            .where(AutoPilotSpecTask.session_id == ap_session.id)
            .where(AutoPilotSpecTask.status.in_(["pending", "generating", "failed"]))
        )
        for task in db.exec(stmt).all():
            task.status = "pending"
            task.error_message = None
            task.completed_at = None
            db.add(task)
        ap_session.total_specs_generated = 0
        db.add(ap_session)

    if resume_phase == "test_generation":
        stmt = (
            select(AutoPilotTestTask)
            .where(AutoPilotTestTask.session_id == ap_session.id)
            .where(AutoPilotTestTask.status.in_(["pending", "running", "paused", "failed", "error"]))
        )
        for task in db.exec(stmt).all():
            task.status = "pending"
            task.error_summary = None
            task.started_at = None
            task.completed_at = None
            task.passed = None
            db.add(task)
            if task.run_id:
                run = db.get(TestRun, task.run_id)
                if run:
                    run.status = "pending"
                    run.current_stage = "pending"
                    run.stage_message = "Waiting to resume Auto Pilot test generation"
                    run.error_message = None
                    run.completed_at = None
                    db.add(run)

    stmt = (
        select(AutoPilotQuestion)
        .where(AutoPilotQuestion.session_id == ap_session.id)
        .where(AutoPilotQuestion.status == "pending")
    )
    for question in db.exec(stmt).all():
        if original_status != "awaiting_input":
            question.status = "skipped"
            db.add(question)

    ap_session.started_at = ap_session.started_at or now
    db.add(ap_session)
    db.commit()


def _launch_pipeline(session_id: str, project_id: str | None, user_key: str):
    """Create and track a new background pipeline task."""
    from orchestrator.workflows.autopilot_pipeline import AutoPilotPipeline

    pipeline = AutoPilotPipeline(session_id, project_id or "default")
    task = asyncio.create_task(_run_pipeline_background(pipeline, session_id))
    _running_pipelines[session_id] = (task, pipeline, user_key)
    return pipeline


# ========== API Endpoints ==========


@router.post("/start", response_model=dict)
async def start_autopilot(
    request_body: AutoPilotStartRequest,
    request: Request,
    user=Depends(get_current_user_optional),
):
    """
    Start a new Auto Pilot pipeline session.

    Runs exploration, requirements extraction, test idea generation, spec generation,
    test generation, and reporting in sequence as background tasks.
    Use GET /autopilot/{session_id} to poll progress.
    """
    _sweep_done_tasks()

    user_key = _get_user_key(user, request)

    # Per-user concurrency limit
    active_for_user = _count_user_active_sessions(user_key)
    if active_for_user >= MAX_ACTIVE_SESSIONS_PER_USER:
        raise HTTPException(
            status_code=429,
            detail=f"You already have {active_for_user} active Auto Pilot sessions. Maximum is {MAX_ACTIVE_SESSIONS_PER_USER}.",
        )

    # Hard cap on tracked pipelines (memory safety)
    if len(_running_pipelines) >= MAX_TRACKED_PIPELINES:
        logger.error(f"Auto Pilot tracking dict at hard cap ({MAX_TRACKED_PIPELINES})")
        raise HTTPException(
            status_code=503,
            detail="System at maximum Auto Pilot capacity. Please try again later.",
        )

    # Validate entry URLs
    if not request_body.entry_urls:
        raise HTTPException(status_code=422, detail="At least one entry URL is required.")
    session_id = f"autopilot_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"

    # Build config dict for storage
    config = {
        "strategy": request_body.strategy,
        "max_interactions": request_body.max_interactions,
        "max_depth": request_body.max_depth,
        "timeout_minutes": request_body.timeout_minutes,
        "reactive_mode": request_body.reactive_mode,
        "auto_continue_hours": request_body.auto_continue_hours,
        "priority_threshold": request_body.priority_threshold,
        "max_specs": request_body.max_specs,
        "parallel_generation": request_body.parallel_generation,
        "hybrid_healing": request_body.hybrid_healing,
        "has_credentials": bool(request_body.credentials),
        "has_login_url": bool(request_body.login_url),
    }

    # Create session in DB
    with Session(engine) as db:
        ap_session = AutoPilotSession(
            id=session_id,
            project_id=request_body.project_id,
            status="pending",
            instructions=request_body.instructions,
            login_url=request_body.login_url,
            triggered_by=user_key,
        )
        ap_session.entry_urls = request_body.entry_urls
        ap_session.credentials = request_body.credentials or {}
        ap_session.test_data = request_body.test_data or {}
        ap_session.config = config
        db.add(ap_session)
        db.flush()  # Ensure session row exists before inserting phases (FK constraint)

        # Create phase records
        for phase_name, phase_order in PHASE_DEFINITIONS:
            phase = AutoPilotPhase(
                session_id=session_id,
                phase_name=phase_name,
                phase_order=phase_order,
                status="pending",
            )
            db.add(phase)

        db.commit()

    # Instantiate the pipeline and launch background task
    _launch_pipeline(session_id, request_body.project_id, user_key)

    logger.info(f"Auto Pilot session {session_id} started for {len(request_body.entry_urls)} URL(s)")

    return {
        "session_id": session_id,
        "status": "pending",
        "message": f"Auto Pilot started. Poll progress at GET /autopilot/{session_id}",
        "entry_urls": request_body.entry_urls,
        "phases": [name for name, _ in PHASE_DEFINITIONS],
    }


@router.get("/sessions", response_model=list[AutoPilotSessionResponse])
async def list_sessions(
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    """List all Auto Pilot sessions, newest first."""
    stmt = select(AutoPilotSession).order_by(AutoPilotSession.created_at.desc())

    if project_id:
        stmt = stmt.where(AutoPilotSession.project_id == project_id)
    if status:
        stmt = stmt.where(AutoPilotSession.status == status)

    sessions = session.exec(stmt).all()
    return [_session_to_response(s, session) for s in sessions]


@router.get("/{session_id}", response_model=AutoPilotSessionResponse)
async def get_session_detail(
    session_id: str,
    session: Session = Depends(get_session),
):
    """Get Auto Pilot session status and summary."""
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")
    return _session_to_response(ap_session, session)


@router.get("/{session_id}/phases", response_model=list[AutoPilotPhaseResponse])
async def get_session_phases(
    session_id: str,
    session: Session = Depends(get_session),
):
    """Get all phases for an Auto Pilot session, ordered by execution sequence."""
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")

    stmt = select(AutoPilotPhase).where(AutoPilotPhase.session_id == session_id).order_by(AutoPilotPhase.phase_order)
    phases = session.exec(stmt).all()
    return [_phase_to_response(p) for p in phases]


@router.get("/{session_id}/questions", response_model=list[AutoPilotQuestionResponse])
async def get_session_questions(
    session_id: str,
    status: str | None = Query(default=None, description="Filter by question status"),
    session: Session = Depends(get_session),
):
    """Get questions for an Auto Pilot session."""
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")

    stmt = (
        select(AutoPilotQuestion)
        .where(AutoPilotQuestion.session_id == session_id)
        .order_by(AutoPilotQuestion.created_at.desc())
    )
    if status:
        stmt = stmt.where(AutoPilotQuestion.status == status)

    questions = session.exec(stmt).all()
    return [_question_to_response(q) for q in questions]


@router.post("/{session_id}/answer", response_model=dict)
async def answer_question(
    session_id: str,
    body: AnswerQuestionRequest,
    session: Session = Depends(get_session),
):
    """Answer a question posed by the pipeline during execution.

    Updates the question record in the DB and notifies the running
    pipeline so it can resume with the user's answer.
    """
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")

    question = session.get(AutoPilotQuestion, body.question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    if question.session_id != session_id:
        raise HTTPException(status_code=400, detail="Question does not belong to this session")
    if question.status in ("answered", "auto_continued"):
        return {
            "status": "already_resolved",
            "question_status": question.status,
            "question_id": body.question_id,
            "session_id": session_id,
            "answer_text": question.answer_text,
        }
    if question.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Question already resolved (status: {question.status})",
        )

    # Update question in DB
    question.answer_text = body.answer_text
    question.answered_at = datetime.utcnow()
    question.status = "answered"
    session.add(question)
    session.commit()

    # Notify running pipeline if it exists
    entry = _running_pipelines.get(session_id)
    if entry and not entry[0].done():
        _, pipeline, _ = entry
        try:
            pipeline.answer_question(body.question_id, body.answer_text)
            logger.info(f"Forwarded answer to pipeline {session_id} for question {body.question_id}")
        except Exception as e:
            logger.warning(f"Could not forward answer to pipeline: {e}")
    else:
        can_resume, resume_reason, failed_phase = _get_resume_metadata(ap_session, session)
        if can_resume and len(_running_pipelines) < MAX_TRACKED_PIPELINES:
            _reset_resumable_state(session, ap_session, failed_phase)
            _launch_pipeline(session_id, ap_session.project_id, ap_session.triggered_by or "system")
            logger.info(f"Recreated pipeline for answered Auto Pilot checkpoint {session_id}: {resume_reason}")

    return {
        "status": "answered",
        "question_status": "answered",
        "question_id": body.question_id,
        "session_id": session_id,
        "answer_text": body.answer_text,
    }


@router.get("/{session_id}/spec-tasks", response_model=list[SpecTaskResponse])
async def get_spec_tasks(
    session_id: str,
    status: str | None = Query(default=None, description="Filter by task status"),
    session: Session = Depends(get_session),
):
    """Get spec generation tasks for an Auto Pilot session."""
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")

    stmt = (
        select(AutoPilotSpecTask)
        .where(AutoPilotSpecTask.session_id == session_id)
        .order_by(AutoPilotSpecTask.created_at)
    )
    if status:
        stmt = stmt.where(AutoPilotSpecTask.status == status)

    tasks = session.exec(stmt).all()
    return [_spec_task_to_response(t) for t in tasks]


@router.get("/{session_id}/test-tasks", response_model=list[TestTaskResponse])
async def get_test_tasks(
    session_id: str,
    status: str | None = Query(default=None, description="Filter by task status"),
    session: Session = Depends(get_session),
):
    """Get test generation tasks for an Auto Pilot session."""
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")

    stmt = (
        select(AutoPilotTestTask)
        .where(AutoPilotTestTask.session_id == session_id)
        .order_by(AutoPilotTestTask.created_at)
    )
    if status:
        stmt = stmt.where(AutoPilotTestTask.status == status)

    tasks = session.exec(stmt).all()
    return [_test_task_to_response(t) for t in tasks]


@router.get("/{session_id}/test-tasks/{task_id}", response_model=TestTaskDetailResponse)
async def get_test_task_detail(
    session_id: str,
    task_id: int,
    session: Session = Depends(get_session),
):
    """Get a detailed test-generation task view with failure artifacts."""
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")

    test_task = session.get(AutoPilotTestTask, task_id)
    if not test_task or test_task.session_id != session_id:
        raise HTTPException(status_code=404, detail="Test task not found in this session")

    return _test_task_to_detail(test_task)


@router.post("/{session_id}/pause", response_model=dict)
async def pause_session(
    session_id: str,
    session: Session = Depends(get_session),
):
    """Pause a running Auto Pilot session.

    Active test-generation tasks are marked paused and restarted cleanly
    when the session is resumed.
    """
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")

    if ap_session.status not in ("running", "awaiting_input"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot pause session with status '{ap_session.status}'",
        )

    entry = _running_pipelines.get(session_id)
    if entry:
        task, pipeline, _ = entry
        try:
            pipeline.pause()
        except Exception as e:
            logger.warning(f"Error pausing pipeline {session_id}: {e}")
        task.cancel()

    now = datetime.utcnow()
    ap_session.status = "paused"
    ap_session.completed_at = None
    session.add(ap_session)

    phase_stmt = (
        select(AutoPilotPhase)
        .where(AutoPilotPhase.session_id == session_id)
        .where(AutoPilotPhase.phase_name == ap_session.current_phase)
    )
    phase = session.exec(phase_stmt).first()
    if phase and phase.status in ("pending", "running"):
        phase.status = "paused"
        phase.current_step = "Paused by user"
        session.add(phase)

    test_stmt = (
        select(AutoPilotTestTask)
        .where(AutoPilotTestTask.session_id == session_id)
        .where(AutoPilotTestTask.status.in_(["pending", "running"]))
    )
    paused_tasks = session.exec(test_stmt).all()
    for test_task in paused_tasks:
        test_task.status = "paused"
        test_task.error_summary = "Paused by user"
        test_task.completed_at = now
        session.add(test_task)
        if test_task.run_id:
            run = session.get(TestRun, test_task.run_id)
            if run:
                run.status = "paused"
                run.current_stage = "paused"
                run.stage_message = "Paused by user"
                run.error_message = None
                run.completed_at = now
                session.add(run)

    session.commit()

    logger.info(f"Auto Pilot {session_id} paused")
    return {"status": "paused", "session_id": session_id, "paused_test_tasks": len(paused_tasks)}


@router.post("/{session_id}/resume", response_model=dict)
async def resume_session(
    session_id: str,
    request: Request,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    """Resume a paused Auto Pilot session.

    If the server restarted and the pipeline is no longer in memory,
    a new pipeline instance is created and resumed from DB state.
    """
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")

    can_resume, resume_reason, failed_phase = _get_resume_metadata(ap_session, session)
    if not can_resume:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot resume session with status '{ap_session.status}'",
        )

    _sweep_done_tasks()

    entry = _running_pipelines.get(session_id)
    if ap_session.status == "paused":
        if entry and not entry[0].done():
            entry[0].cancel()
            _running_pipelines.pop(session_id, None)
        if len(_running_pipelines) >= MAX_TRACKED_PIPELINES:
            raise HTTPException(
                status_code=503,
                detail="System at maximum Auto Pilot capacity. Please try again later.",
            )
        user_key = _get_user_key(user, request)
        _reset_resumable_state(session, ap_session, failed_phase)
        _launch_pipeline(session_id, ap_session.project_id, user_key)
        logger.info(f"Recreated paused pipeline for {session_id}")
    elif entry and not entry[0].done():
        # Pipeline still in memory -- just resume it
        _, pipeline, _ = entry
        try:
            pipeline.resume()
        except Exception as e:
            logger.warning(f"Error resuming in-memory pipeline {session_id}: {e}")
    else:
        # Pipeline lost (server restart) -- recreate from DB state
        if len(_running_pipelines) >= MAX_TRACKED_PIPELINES:
            raise HTTPException(
                status_code=503,
                detail="System at maximum Auto Pilot capacity. Please try again later.",
            )

        user_key = _get_user_key(user, request)
        _reset_resumable_state(session, ap_session, failed_phase)
        _launch_pipeline(session_id, ap_session.project_id, user_key)
        logger.info(f"Recreated pipeline for {session_id} after server restart")

    if ap_session.status != "running":
        ap_session.status = "running"
        ap_session.completed_at = None
        ap_session.error_message = None
        session.add(ap_session)
        session.commit()

    logger.info(f"Auto Pilot {session_id} resumed: {resume_reason}")
    return {"status": "running", "session_id": session_id, "resume_reason": resume_reason}


@router.post("/{session_id}/cancel", response_model=dict)
async def cancel_session(
    session_id: str,
    session: Session = Depends(get_session),
):
    """Cancel a running or paused Auto Pilot session.

    Cancels the background task, marks the session and any in-progress
    phases/tasks as cancelled or failed.
    """
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")

    terminal_statuses = ("completed", "failed", "cancelled")
    if ap_session.status in terminal_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"Session already in terminal state '{ap_session.status}'",
        )

    # Cancel the background task
    entry = _running_pipelines.get(session_id)
    if entry:
        task, pipeline, _ = entry
        try:
            pipeline.cancel()
        except Exception as e:
            logger.warning(f"Error calling pipeline.cancel() for {session_id}: {e}")
        task.cancel()
        _running_pipelines.pop(session_id, None)

    # Update session
    now = datetime.utcnow()
    ap_session.status = "cancelled"
    ap_session.completed_at = now
    session.add(ap_session)

    # Mark running phases as failed
    stmt = (
        select(AutoPilotPhase)
        .where(AutoPilotPhase.session_id == session_id)
        .where(AutoPilotPhase.status.in_(["running", "pending", "paused"]))
    )
    running_phases = session.exec(stmt).all()
    for phase in running_phases:
        phase.status = "cancelled" if phase.status == "pending" else "failed"
        phase.error_message = "Session cancelled by user"
        phase.completed_at = now
        session.add(phase)

    # Mark running spec tasks as failed
    stmt = (
        select(AutoPilotSpecTask)
        .where(AutoPilotSpecTask.session_id == session_id)
        .where(AutoPilotSpecTask.status.in_(["pending", "generating"]))
    )
    running_spec_tasks = session.exec(stmt).all()
    for t in running_spec_tasks:
        t.status = "failed"
        t.error_message = "Session cancelled"
        t.completed_at = now
        session.add(t)

    # Mark running test tasks as failed
    stmt = (
        select(AutoPilotTestTask)
        .where(AutoPilotTestTask.session_id == session_id)
        .where(AutoPilotTestTask.status.in_(["pending", "running", "paused"]))
    )
    running_test_tasks = session.exec(stmt).all()
    for t in running_test_tasks:
        t.status = "error"
        t.error_summary = "Session cancelled"
        t.completed_at = now
        session.add(t)
        if t.run_id:
            run = session.get(TestRun, t.run_id)
            if run:
                run.status = "error"
                run.current_stage = "cancelled"
                run.stage_message = "Session cancelled"
                run.error_message = "Session cancelled"
                run.completed_at = now
                session.add(run)

    # Skip pending questions
    stmt = (
        select(AutoPilotQuestion)
        .where(AutoPilotQuestion.session_id == session_id)
        .where(AutoPilotQuestion.status == "pending")
    )
    pending_questions = session.exec(stmt).all()
    for q in pending_questions:
        q.status = "skipped"
        session.add(q)

    session.commit()

    logger.info(f"Auto Pilot {session_id} cancelled")
    return {"status": "cancelled", "session_id": session_id}


@router.post("/{session_id}/test-tasks/{task_id}/stop", response_model=dict)
async def stop_test_task(
    session_id: str,
    task_id: int,
    session: Session = Depends(get_session),
):
    """Stop an individual test generation task within an Auto Pilot session."""
    from .models_db import AutoPilotTestTask

    # Verify session exists
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")

    # Verify task exists and belongs to session
    test_task = session.get(AutoPilotTestTask, task_id)
    if not test_task or test_task.session_id != session_id:
        raise HTTPException(status_code=404, detail="Test task not found in this session")

    if test_task.status not in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"Task already in terminal state '{test_task.status}'",
        )

    # Try to cancel the asyncio task via the pipeline
    entry = _running_pipelines.get(session_id)
    if entry:
        _, pipeline, _ = entry
        try:
            pipeline.cancel_test_task(task_id)
        except Exception as e:
            logger.warning(f"Error cancelling test task {task_id}: {e}")

    # Update DB
    now = datetime.utcnow()
    test_task.status = "error"
    test_task.error_summary = "Stopped by user"
    test_task.completed_at = now
    session.add(test_task)
    if test_task.run_id:
        run = session.get(TestRun, test_task.run_id)
        if run:
            run.status = "error"
            run.current_stage = "stopped"
            run.stage_message = "Stopped by user"
            run.error_message = "Stopped by user"
            run.completed_at = now
            session.add(run)
    session.commit()

    logger.info(f"Test task {task_id} in session {session_id} stopped by user")

    return {
        "status": "stopped",
        "task_id": task_id,
        "session_id": session_id,
        "message": f"Test task {task_id} stopped",
    }


@router.delete("/{session_id}", response_model=dict)
async def delete_session(
    session_id: str,
    session: Session = Depends(get_session),
):
    """Delete an Auto Pilot session and all related records.

    Cannot delete a session that is currently running.
    """
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")

    active_statuses = ("pending", "running", "awaiting_input", "paused")
    if ap_session.status in active_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete session with status '{ap_session.status}'. Cancel it first.",
        )

    # Delete child records in dependency order
    # 1. Test tasks
    stmt = select(AutoPilotTestTask).where(AutoPilotTestTask.session_id == session_id)
    for t in session.exec(stmt).all():
        session.delete(t)

    # 2. Spec tasks
    stmt = select(AutoPilotSpecTask).where(AutoPilotSpecTask.session_id == session_id)
    for t in session.exec(stmt).all():
        session.delete(t)

    # 3. Questions
    stmt = select(AutoPilotQuestion).where(AutoPilotQuestion.session_id == session_id)
    for q in session.exec(stmt).all():
        session.delete(q)

    # 4. Phases
    stmt = select(AutoPilotPhase).where(AutoPilotPhase.session_id == session_id)
    for p in session.exec(stmt).all():
        session.delete(p)

    # 5. Session itself
    session.delete(ap_session)
    session.commit()

    logger.info(f"Deleted Auto Pilot session {session_id} and all related records")
    return {"status": "deleted", "session_id": session_id}


# ========== Startup Resume ==========


async def resume_interrupted_sessions() -> int:
    """Resume Auto Pilot sessions that were running when the server stopped.

    Called from main.py during startup. Scans for sessions with status
    'running' or 'awaiting_input' and recreates their pipeline instances.

    Returns the number of sessions resumed.
    """
    count = 0
    with Session(engine) as db:
        stmt = select(AutoPilotSession).where(AutoPilotSession.status.in_(["running", "awaiting_input", "paused"]))
        interrupted = db.exec(stmt).all()

        for ap_session in interrupted:
            try:
                logger.info(f"Resuming interrupted Auto Pilot: {ap_session.id}")
                user_key = ap_session.triggered_by or "system"
                _reset_resumable_state(db, ap_session, _get_failed_phase(db, ap_session.id))
                _launch_pipeline(ap_session.id, ap_session.project_id, user_key)
                count += 1
            except Exception as e:
                logger.error(
                    f"Failed to resume Auto Pilot {ap_session.id}: {e}",
                    exc_info=True,
                )
                # Mark as failed so it does not retry indefinitely
                ap_session.status = "failed"
                ap_session.error_message = f"Failed to resume after restart: {str(e)[:300]}"
                ap_session.completed_at = datetime.utcnow()
                db.add(ap_session)
                db.commit()

    return count
