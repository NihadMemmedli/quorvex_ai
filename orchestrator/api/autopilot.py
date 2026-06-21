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
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from orchestrator.services.browser_auth_sessions import (
    BrowserAuthSessionError,
    ensure_browser_auth_session_usable,
    resolve_browser_auth_session_row,
)
from orchestrator.services.test_data_resolver import resolve_test_data_refs
from orchestrator.utils.playwright_mcp import browser_runtime_status, live_browser_display_diagnostics

from .db import engine, get_session
from .middleware.auth import get_current_user_optional
from .models_db import (
    AutoPilotChecklistItem,
    AutoPilotPhase,
    AutoPilotQuestion,
    AutoPilotSession,
    AutoPilotSpecTask,
    AutoPilotTestTask,
    TestRun,
)
from .project_filters import apply_project_filter

logger = logging.getLogger(__name__)

# ========== Configuration ==========

MAX_TRACKED_PIPELINES = 5
MAX_ACTIVE_SESSIONS_PER_USER = 2
AUTOPILOT_STALE_LIVE_SECONDS = 120

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

ACTIVE_TEST_TASK_STATUSES = {"pending", "running"}


# ========== Pydantic Request/Response Models ==========


class AutoPilotStartRequest(BaseModel):
    """Request to start an Auto Pilot pipeline session."""

    entry_urls: list[str] = Field(..., min_length=1, description="URLs to explore")
    project_id: str = Field(default="default")
    login_url: str | None = None
    credentials: dict | None = None
    test_data: dict | None = None
    test_data_refs: list[str] = Field(default_factory=list)
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False
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
    requirements_mode: str = Field(default="single_agent", pattern="^(single_agent|multi_agent)$")
    requirements_max_agents: int = Field(default=3, ge=1, le=6)
    requirements_browser_verification: str = Field(default="off", pattern="^(off|selected)$")


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
    temporal_workflow_id: str | None = None
    temporal_run_id: str | None = None
    temporal: dict[str, Any] | None = None
    can_resume: bool = False
    resume_reason: str | None = None
    failed_phase: str | None = None


class AutoPilotTemporalSummaryResponse(BaseModel):
    total_activities: int = 0
    failed_activities: int = 0
    retry_count: int = 0
    last_failure: str | None = None
    last_workflow_task_failure: str | None = None


class AutoPilotTemporalResponse(BaseModel):
    temporal_workflow_id: str | None = None
    temporal_run_id: str | None = None
    temporal_ui_url: str | None = None
    temporal_ui_workflow_url: str | None = None
    temporal_namespace: str | None = None
    task_queue: str | None = None
    workflow_type: str = "AutoPilotWorkflow"
    available: bool = False
    workflow_status: str | None = None
    activities: list[dict[str, Any]] = Field(default_factory=list)
    workflow_task_failures: list[dict[str, Any]] = Field(default_factory=list)
    task_queue_status: dict[str, Any] = Field(default_factory=dict)
    summary: AutoPilotTemporalSummaryResponse = Field(default_factory=AutoPilotTemporalSummaryResponse)
    error: str | None = None


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


class AutoPilotChecklistItemResponse(BaseModel):
    id: int
    session_id: str
    sequence: int
    kind: str
    phase_name: str | None
    title: str
    detail: str | None
    status: str
    progress: float
    items_completed: int
    items_total: int
    source_type: str | None
    source_id: str | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class AutoPilotChecklistSummaryResponse(BaseModel):
    total: int = 0
    pending: int = 0
    running: int = 0
    waiting: int = 0
    completed: int = 0
    failed: int = 0
    runtime_failed: int = 0
    runtime_stale: int = 0
    spec_not_automatable: int = 0
    planner_contract_failed: int = 0
    skipped: int = 0


class AutoPilotChecklistResponse(BaseModel):
    items: list[AutoPilotChecklistItemResponse]
    summary: AutoPilotChecklistSummaryResponse


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


class AutoPilotLiveArtifactResponse(BaseModel):
    """Live browser artifact metadata for an Auto Pilot session."""

    name: str
    path: str
    type: str
    modified_at: datetime | None = None


class AutoPilotLiveResponse(BaseModel):
    """Current live browser/progress state for an Auto Pilot session."""

    active: bool = False
    phase: str | None = None
    activity_label: str | None = None
    status: str | None = None
    message: str | None = None
    exploration_session_id: str | None = None
    test_task_id: int | None = None
    run_id: str | None = None
    spec_name: str | None = None
    current_stage: str | None = None
    activity_kind: str | None = None
    agent_task_id: str | None = None
    last_tool: str | None = None
    last_tool_label: str | None = None
    tool_calls: int = 0
    browser_tool_calls: int = 0
    interactions: int = 0
    capture_count: int = 0
    latest_capture_at: str | None = None
    activity_source: str | None = None
    recent_tools: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[AutoPilotLiveArtifactResponse] = Field(default_factory=list)
    latest_image: AutoPilotLiveArtifactResponse | None = None
    subagents: list[dict[str, Any]] = Field(default_factory=list)
    items_total: int = 0
    items_completed: int = 0
    requirements_generated: int = 0
    verification_status: str | None = None
    updated_at: str | None = None
    browser_runtime: str | None = None
    live_view_available: bool = False
    runtime_message: str | None = None
    vnc_url: str | None = None
    display_diagnostics: dict[str, Any] | None = None


class AutoPilotEvidenceArtifactResponse(AutoPilotLiveArtifactResponse):
    """Artifact metadata with optional inline diagnostic preview."""

    content_excerpt: str | None = None


class AutoPilotEvidenceResponse(BaseModel):
    """Aggregated failure and artifact evidence for an Auto Pilot session."""

    session_id: str
    status: str
    current_phase: str | None = None
    error_message: str | None = None
    failed_phase: AutoPilotPhaseResponse | None = None
    temporal: AutoPilotTemporalResponse
    live: AutoPilotLiveResponse
    artifacts: list[AutoPilotEvidenceArtifactResponse] = Field(default_factory=list)
    latest_image: AutoPilotEvidenceArtifactResponse | None = None
    videos: list[AutoPilotEvidenceArtifactResponse] = Field(default_factory=list)
    diagnostics: list[AutoPilotEvidenceArtifactResponse] = Field(default_factory=list)


# ========== Helper Functions ==========


RUNS_DIR = Path("runs")


def _current_autopilot_runtime(live: dict[str, Any]) -> dict[str, Any]:
    """Describe whether the current AutoPilot browser can be shown through VNC."""
    if live.get("browser_runtime") or live.get("live_view_available") is not None:
        runtime = browser_runtime_status()
        merged = {
            **runtime,
            "browser_runtime": live.get("browser_runtime") or runtime["browser_runtime"],
            "live_view_available": bool(live.get("live_view_available")),
            "runtime_message": live.get("runtime_message") or runtime["runtime_message"],
            "vnc_url": live.get("vnc_url") or runtime.get("vnc_url"),
            "display_diagnostics": live.get("display_diagnostics") or runtime.get("display_diagnostics"),
        }
        return _augment_active_autopilot_runtime(live, merged)
    try:
        from orchestrator.services.agent_queue import should_use_agent_queue

        if should_use_agent_queue() and live.get("agent_task_id"):
            return {
                "browser_runtime": "headless_worker",
                "live_view_available": False,
                "runtime_message": "AutoPilot browser tools are delegated to an agent worker outside the VNC display.",
                "vnc_url": live.get("vnc_url"),
                "display_diagnostics": live.get("display_diagnostics"),
            }
    except Exception:
        pass
    runtime = browser_runtime_status()
    return _augment_active_autopilot_runtime(live, {
        **runtime,
        "vnc_url": live.get("vnc_url") or runtime.get("vnc_url"),
        "display_diagnostics": live.get("display_diagnostics") or runtime.get("display_diagnostics"),
    })


def _augment_active_autopilot_runtime(live: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    active_statuses = {"queued", "pending", "running", "in_progress", "tool_use", "starting"}
    if str(live.get("status") or "").lower() not in active_statuses and not live.get("active"):
        return runtime
    if not runtime.get("live_view_available") or runtime.get("browser_runtime") != "vnc":
        return runtime

    runtime = dict(runtime)
    diagnostics = runtime.get("display_diagnostics") or live_browser_display_diagnostics()
    runtime["display_diagnostics"] = diagnostics
    if diagnostics.get("browser_window_count") in (0, None):
        runtime["runtime_message"] = "VNC is connected; waiting for Playwright to launch a visible browser window."
    return runtime


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


def _parse_live_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _active_pipeline_entry(session_id: str):
    entry = _running_pipelines.get(session_id)
    if entry and not entry[0].done():
        return entry
    return None


def _live_browser_pool_request_ids(live: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Return exact and prefix browser-pool request ids for the persisted live state."""
    exact: set[str] = set()
    prefixes: set[str] = set()
    exploration_session_id = live.get("exploration_session_id")
    if exploration_session_id:
        exact.add(f"autopilot_{exploration_session_id}")

    test_task_id = live.get("test_task_id")
    if test_task_id is not None:
        prefixes.add(f"autopilot_test_{test_task_id}_")

    return exact, prefixes


def _active_test_task_stmt(session_id: str):
    return (
        select(AutoPilotTestTask)
        .where(AutoPilotTestTask.session_id == session_id)
        .where(AutoPilotTestTask.status.in_(list(ACTIVE_TEST_TASK_STATUSES)))
    )


def _active_test_task_ids(db: Session, session_id: str) -> list[int]:
    tasks = db.exec(_active_test_task_stmt(session_id)).all()
    return [int(task.id) for task in tasks if task.id is not None]


def _has_active_test_tasks(db: Session, session_id: str) -> bool:
    return bool(_active_test_task_ids(db, session_id))


def _active_test_task_ids_for_session(session_id: str) -> list[int]:
    try:
        with Session(engine) as db:
            return _active_test_task_ids(db, session_id)
    except Exception as exc:
        logger.debug("Unable to inspect AutoPilot test-task liveness for %s: %s", session_id, exc)
        return []


async def _has_active_test_task_browser_pool_slot(session_id: str) -> bool:
    test_task_ids = _active_test_task_ids_for_session(session_id)
    if not test_task_ids:
        return False

    prefixes = [f"autopilot_test_{test_task_id}_" for test_task_id in test_task_ids]
    try:
        from orchestrator.services.browser_pool import get_browser_pool

        pool = await get_browser_pool()
        status = await pool.get_status()
    except Exception as exc:
        logger.debug("Unable to inspect AutoPilot test-task browser pool liveness: %s", exc)
        return False

    running_requests = [str(item) for item in status.get("running_requests") or []]
    return any(request_id.startswith(prefix) for request_id in running_requests for prefix in prefixes)


async def _has_active_browser_pool_slot(live: dict[str, Any]) -> bool:
    exact, prefixes = _live_browser_pool_request_ids(live)
    if not exact and not prefixes:
        return False

    try:
        from orchestrator.services.browser_pool import get_browser_pool

        pool = await get_browser_pool()
        for request_id in exact:
            if await pool.is_running(request_id):
                return True

        status = await pool.get_status()
    except Exception as exc:
        logger.debug("Unable to inspect AutoPilot browser pool liveness: %s", exc)
        return False

    running_requests = [str(item) for item in status.get("running_requests") or []]
    if exact.intersection(running_requests):
        return True
    return any(request_id.startswith(prefix) for request_id in running_requests for prefix in prefixes)


def _has_recent_live_artifact_progress(live: dict[str, Any], now: datetime | None = None) -> bool:
    exploration_session_id = live.get("exploration_session_id")
    run_id = live.get("run_id")
    if not exploration_session_id and not run_id:
        return False

    artifacts = _collect_live_artifacts(
        exploration_session_id=str(exploration_session_id) if exploration_session_id else None,
        run_id=str(run_id) if run_id else None,
    )
    artifact_times = [artifact.modified_at for artifact in artifacts if artifact.modified_at]
    if not artifact_times:
        return False

    latest_artifact_at = max(artifact_times)
    live_updated_at = _parse_live_timestamp(live.get("updated_at"))
    if live_updated_at and latest_artifact_at > live_updated_at:
        return True

    now = now or datetime.utcnow()
    return (now - latest_artifact_at).total_seconds() < AUTOPILOT_STALE_LIVE_SECONDS


async def _temporal_workflow_blocks_stale_reconcile(ap_session: AutoPilotSession) -> bool:
    """Temporal-owned AutoPilot sessions should not be failed by read-side stale polling."""
    if not ap_session.temporal_workflow_id:
        return False
    try:
        from orchestrator.services.temporal_client import describe_autopilot_workflow

        payload = await describe_autopilot_workflow(ap_session.temporal_workflow_id)
        status = str(payload.get("workflow_status") or "").upper()
        if status in {"RUNNING", "PENDING"}:
            return True
        if not status:
            return True
    except Exception as exc:
        logger.debug(
            "Preserving AutoPilot %s during stale reconcile because Temporal status is unavailable: %s",
            ap_session.id,
            exc,
        )
        return True
    return False


def _session_process_cleanup(session_id: str) -> dict[str, Any]:
    try:
        from orchestrator.utils.browser_cleanup import kill_autopilot_process_tree

        return kill_autopilot_process_tree(session_id)
    except Exception as exc:
        logger.warning("Failed AutoPilot process cleanup for %s: %s", session_id, exc)
        return {"session_id": session_id, "matched": 0, "terminated": 0, "killed": 0, "pids": [], "error": str(exc)}


async def _session_process_cleanup_async(session_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_session_process_cleanup, session_id)


def _is_stale_live_browser(ap_session: AutoPilotSession, now: datetime | None = None) -> bool:
    if ap_session.status not in {"pending", "running", "awaiting_input", "paused"}:
        return False
    if ap_session.status == "awaiting_input":
        return False
    if ap_session.temporal_workflow_id:
        return False
    live = dict((ap_session.config or {}).get("live_browser") or {})
    if not live.get("active"):
        return False
    if live.get("activity_kind") == "analysis":
        return False
    if live.get("agent_task_id"):
        return False
    if find_session_processes(ap_session.id):
        return False

    updated_at = _parse_live_timestamp(live.get("updated_at"))
    if not updated_at:
        return False
    now = now or datetime.utcnow()
    age_seconds = (now - updated_at).total_seconds()
    if age_seconds < AUTOPILOT_STALE_LIVE_SECONDS:
        return False
    if _has_recent_live_artifact_progress(live, now):
        return False
    if _active_test_task_ids_for_session(ap_session.id):
        return False

    return str(live.get("status") or "").lower() in {"starting", "running", "queued", "tool_use"} or bool(
        live.get("message")
    )


async def _live_agent_task_is_stale(live: dict[str, Any]) -> bool:
    task_id = live.get("agent_task_id")
    if not task_id:
        return False
    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE, get_agent_queue

        if not REDIS_AVAILABLE:
            return False
        queue = get_agent_queue()
        await queue.connect()
        task = await queue.get_task(str(task_id))
        if not task:
            return True
        status = task.status.value
        if status in {"completed", "failed", "timeout", "cancelled"}:
            return True
        if status in {"running", "paused", "cancel_requested"}:
            return not await queue.check_heartbeat(str(task_id), max_stale_seconds=120)
        return False
    except Exception as exc:
        logger.debug("Unable to inspect AutoPilot live agent task %s: %s", task_id, exc)
        return False


async def _is_stale_live_browser_async(
    ap_session: AutoPilotSession,
    now: datetime | None = None,
) -> bool:
    if ap_session.status not in {"pending", "running", "awaiting_input", "paused"}:
        return False
    if ap_session.status == "awaiting_input":
        return False
    live = dict((ap_session.config or {}).get("live_browser") or {})
    if not live.get("active"):
        return False
    if live.get("activity_kind") == "analysis":
        return False
    if find_session_processes(ap_session.id):
        return False

    updated_at = _parse_live_timestamp(live.get("updated_at"))
    if not updated_at:
        return False
    now = now or datetime.utcnow()
    if (now - updated_at).total_seconds() < AUTOPILOT_STALE_LIVE_SECONDS:
        return False
    if _has_recent_live_artifact_progress(live, now):
        return False
    if await _has_active_test_task_browser_pool_slot(ap_session.id):
        return False
    if _active_test_task_ids_for_session(ap_session.id):
        return False
    if await _has_active_browser_pool_slot(live):
        return False
    if await _temporal_workflow_blocks_stale_reconcile(ap_session):
        return False

    if live.get("agent_task_id"):
        return await _live_agent_task_is_stale(live)
    return str(live.get("status") or "").lower() in {"starting", "running", "queued", "tool_use"} or bool(
        live.get("message")
    )


def find_session_processes(session_id: str) -> list[int]:
    try:
        from orchestrator.utils.browser_cleanup import find_autopilot_process_tree

        return sorted(find_autopilot_process_tree(session_id))
    except Exception as exc:
        logger.debug("Failed to inspect AutoPilot processes for %s: %s", session_id, exc)
        return []


def _mark_session_interrupted(
    db: Session,
    ap_session: AutoPilotSession,
    reason: str,
    *,
    cleanup: dict[str, Any] | None = None,
) -> bool:
    if ap_session.status not in {"pending", "running", "awaiting_input", "paused"}:
        return False
    if _has_active_test_tasks(db, ap_session.id):
        logger.info(
            "Preserving AutoPilot %s during stale interrupt because active test-generation tasks exist.",
            ap_session.id,
        )
        return False

    entry = _running_pipelines.pop(ap_session.id, None)
    if entry and not entry[0].done():
        try:
            entry[1].cancel()
        except Exception as exc:
            logger.debug("Failed to signal stale AutoPilot pipeline %s: %s", ap_session.id, exc)
        entry[0].cancel()

    now = datetime.utcnow()
    config = dict(ap_session.config or {})
    live = dict(config.get("live_browser") or {})
    live.update(
        {
            "active": False,
            "status": "interrupted",
            "message": reason,
            "cleanup": cleanup or {},
            "updated_at": now.isoformat(),
        }
    )
    config["live_browser"] = live
    ap_session.config = config
    ap_session.status = "failed"
    ap_session.error_message = reason
    ap_session.completed_at = now
    db.add(ap_session)

    stmt = (
        select(AutoPilotPhase)
        .where(AutoPilotPhase.session_id == ap_session.id)
        .where(AutoPilotPhase.status.in_(["running", "pending", "paused"]))
    )
    for phase in db.exec(stmt).all():
        if phase.status in {"running", "paused"}:
            phase.status = "failed"
            phase.error_message = reason
            phase.completed_at = now
            db.add(phase)
        elif phase.status == "pending":
            phase.status = "cancelled"
            phase.error_message = reason
            phase.completed_at = now
            db.add(phase)

    return True


def _reconcile_stale_session(db: Session, ap_session: AutoPilotSession) -> bool:
    if not _is_stale_live_browser(ap_session):
        return False
    cleanup = _session_process_cleanup(ap_session.id)
    reason = "AutoPilot runtime became stale: no active browser slot, agent task, or owned browser process was found."
    changed = _mark_session_interrupted(db, ap_session, reason, cleanup=cleanup)
    if changed:
        db.commit()
        logger.warning("Reconciled stale AutoPilot session %s: %s", ap_session.id, cleanup)
    return changed


async def _reconcile_stale_session_async(db: Session, ap_session: AutoPilotSession) -> bool:
    if not await _is_stale_live_browser_async(ap_session):
        return False
    cleanup = await _session_process_cleanup_async(ap_session.id)
    reason = "AutoPilot runtime became stale: no active browser slot, agent task, or owned browser process was found."
    changed = _mark_session_interrupted(db, ap_session, reason, cleanup=cleanup)
    if changed:
        db.commit()
        logger.warning("Reconciled stale AutoPilot session %s: %s", ap_session.id, cleanup)
    return changed


def _count_user_active_sessions(user_key: str) -> int:
    """Count active (non-done) sessions for a user."""
    return sum(1 for _, (task, _, uk) in _running_pipelines.items() if uk == user_key and not task.done())


def _count_user_active_sessions_db(user_key: str) -> int:
    """Count active AutoPilot sessions for a user across Temporal and legacy runtimes."""
    with Session(engine) as db:
        stmt = (
            select(AutoPilotSession)
            .where(AutoPilotSession.triggered_by == user_key)
            .where(AutoPilotSession.status.in_(["pending", "running", "awaiting_input", "paused"]))
        )
        return len(db.exec(stmt).all())


async def _start_autopilot_temporal_or_fail(ap_session: AutoPilotSession, db: Session) -> None:
    from orchestrator.config import settings as app_settings
    from orchestrator.services.temporal_client import TemporalUnavailableError, start_autopilot_workflow

    task_queue = app_settings.temporal_browser_workflow_task_queue
    try:
        temporal = await start_autopilot_workflow(ap_session.id, task_queue=task_queue)
    except TemporalUnavailableError as exc:
        ap_session.status = "failed"
        ap_session.error_message = f"Failed to start Temporal workflow: {exc}"
        ap_session.completed_at = datetime.utcnow()
        config = dict(ap_session.config or {})
        config["live_browser"] = {
            **dict(config.get("live_browser") or {}),
            "active": False,
            "status": "failed",
            "message": str(exc),
            "updated_at": datetime.utcnow().isoformat(),
        }
        ap_session.config = config
        db.add(ap_session)
        db.commit()
        raise HTTPException(status_code=503, detail=f"Temporal is required for AutoPilot: {exc}") from exc

    ap_session.temporal_workflow_id = temporal.workflow_id
    ap_session.temporal_run_id = temporal.run_id
    db.add(ap_session)
    db.commit()


async def _signal_autopilot_temporal(ap_session: AutoPilotSession, signal_name: str, *args) -> bool:
    """Best-effort signal for Temporal-backed AutoPilot sessions."""
    if not ap_session.temporal_workflow_id:
        return False
    try:
        from orchestrator.services.temporal_client import signal_autopilot_workflow

        await signal_autopilot_workflow(ap_session.temporal_workflow_id, signal_name, *args)
        return True
    except Exception as exc:
        logger.warning("Failed to signal AutoPilot workflow %s: %s", ap_session.temporal_workflow_id, exc)
        return False


async def _autopilot_temporal_payload(ap_session: AutoPilotSession) -> dict[str, Any]:
    from orchestrator.config import settings as app_settings
    from orchestrator.services.temporal_client import TemporalUnavailableError, get_autopilot_temporal_diagnostics

    workflow_url = None
    if app_settings.temporal_ui_url and ap_session.temporal_workflow_id:
        workflow_url = (
            f"{app_settings.temporal_ui_url.rstrip('/')}/namespaces/"
            f"{app_settings.temporal_namespace}/workflows/{ap_session.temporal_workflow_id}"
        )
        if ap_session.temporal_run_id:
            workflow_url = f"{workflow_url}/{ap_session.temporal_run_id}/history"
    payload: dict[str, Any] = {
        "temporal_workflow_id": ap_session.temporal_workflow_id,
        "temporal_run_id": ap_session.temporal_run_id,
        "temporal_ui_url": app_settings.temporal_ui_url,
        "temporal_ui_workflow_url": workflow_url,
        "temporal_namespace": app_settings.temporal_namespace,
        "task_queue": app_settings.temporal_browser_workflow_task_queue,
        "workflow_type": "AutoPilotWorkflow",
        "available": False,
        "workflow_status": None,
        "activities": [],
        "workflow_task_failures": [],
        "task_queue_status": {},
        "summary": {
            "total_activities": 0,
            "failed_activities": 0,
            "retry_count": 0,
            "last_failure": None,
            "last_workflow_task_failure": None,
        },
        "error": None,
    }
    if not ap_session.temporal_workflow_id:
        payload["error"] = "No Temporal workflow id recorded for this AutoPilot session."
        return payload
    try:
        return {
            **payload,
            **await get_autopilot_temporal_diagnostics(
                ap_session.temporal_workflow_id,
                ap_session.temporal_run_id,
            ),
        }
    except TemporalUnavailableError as exc:
        payload["error"] = str(exc)
    except Exception as exc:
        payload["error"] = f"Temporal diagnostics unavailable: {exc}"
    return payload


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


def _safe_read_json_value(path: Path) -> Any:
    """Read any JSON artifact shape, returning None when it is absent or invalid."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
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


def _collect_live_artifacts(
    exploration_session_id: str | None = None,
    run_id: str | None = None,
) -> list[AutoPilotLiveArtifactResponse]:
    suffix_types = {
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".webm": "video",
        ".mp4": "video",
    }
    artifacts: list[AutoPilotLiveArtifactResponse] = []
    seen: set[str] = set()
    for root, session_dir in _live_artifact_dirs(
        exploration_session_id=exploration_session_id,
        run_id=run_id,
    ):
        if not session_dir.exists():
            continue
        for path in session_dir.glob("**/*"):
            if not path.is_file():
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
                modified_at = datetime.utcfromtimestamp(path.stat().st_mtime)
            except (OSError, ValueError):
                continue
            artifacts.append(
                AutoPilotLiveArtifactResponse(
                    name=path.name,
                    path=f"/artifacts/{rel_path}",
                    type=artifact_type,
                    modified_at=modified_at,
                )
            )

    return sorted(
        artifacts,
        key=lambda item: (
            item.type != "image",
            -(item.modified_at.timestamp() if item.modified_at else 0),
            item.name,
        ),
    )


def _live_artifact_dirs(
    *,
    exploration_session_id: str | None = None,
    run_id: str | None = None,
) -> list[tuple[Path, Path]]:
    runs_roots = [RUNS_DIR, Path("/app/runs")]
    session_dirs: list[tuple[Path, Path]] = []
    seen: set[str] = set()
    for root in runs_roots:
        candidates: list[Path] = []
        if exploration_session_id:
            candidates.extend(
                [
                    root / exploration_session_id,
                    root / "explorations" / exploration_session_id,
                ]
            )
        if run_id:
            candidates.append(root / run_id)
        for session_dir in candidates:
            key = str(session_dir)
            if key in seen:
                continue
            seen.add(key)
            session_dirs.append((root, session_dir))
    return session_dirs


def _collect_autopilot_artifacts(
    *,
    exploration_session_ids: list[str] | None = None,
    run_ids: list[str] | None = None,
    include_diagnostics: bool = False,
) -> list[AutoPilotEvidenceArtifactResponse]:
    suffix_types = {
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".webm": "video",
        ".mp4": "video",
        ".json": "json",
        ".jsonl": "json",
        ".txt": "text",
        ".log": "text",
        ".yaml": "yaml",
        ".yml": "yaml",
    }
    allowed_types = {"image", "video", "json", "text", "yaml"} if include_diagnostics else {"image", "video"}
    runs_roots = [RUNS_DIR, Path("/app/runs")]
    session_dirs: list[tuple[Path, Path]] = []
    for root in runs_roots:
        for exploration_session_id in exploration_session_ids or []:
            if exploration_session_id:
                session_dirs.extend(
                    [
                        (root, root / exploration_session_id),
                        (root, root / "explorations" / exploration_session_id),
                    ]
                )
        for run_id in run_ids or []:
            if run_id:
                session_dirs.append((root, root / run_id))

    artifacts: list[AutoPilotEvidenceArtifactResponse] = []
    seen: set[str] = set()
    for root, session_dir in session_dirs:
        if not session_dir.exists():
            continue
        for path in session_dir.glob("**/*"):
            if not path.is_file():
                continue
            artifact_type = suffix_types.get(path.suffix.lower())
            if artifact_type not in allowed_types:
                continue
            try:
                resolved = str(path.resolve())
                if resolved in seen:
                    continue
                seen.add(resolved)
                rel_path = path.relative_to(root)
                modified_at = datetime.utcfromtimestamp(path.stat().st_mtime)
            except (OSError, ValueError):
                continue
            excerpt = None
            if artifact_type in {"json", "text", "yaml"}:
                try:
                    excerpt = path.read_text(errors="replace")[:4000]
                except OSError:
                    excerpt = None
            artifacts.append(
                AutoPilotEvidenceArtifactResponse(
                    name=path.name,
                    path=f"/artifacts/{rel_path}",
                    type=artifact_type,
                    modified_at=modified_at,
                    content_excerpt=excerpt,
                )
            )

    return sorted(
        artifacts,
        key=lambda item: (
            item.type not in {"image", "video"},
            item.type != "image",
            -(item.modified_at.timestamp() if item.modified_at else 0),
            item.name,
        ),
    )


def _live_response_from_state(
    ap_session: AutoPilotSession,
    live: dict[str, Any],
    artifacts: list[AutoPilotLiveArtifactResponse],
    *,
    phase: str | None,
    exploration_session_id: Any = None,
    run_id: Any = None,
    numeric_test_task_id: int | None = None,
) -> AutoPilotLiveResponse:
    latest_image = next((artifact for artifact in artifacts if artifact.type == "image"), None)
    live = _merge_artifact_live_progress(live, artifacts)
    session_allows_live = ap_session.status in ("running", "awaiting_input")
    runtime = _current_autopilot_runtime(live)

    return AutoPilotLiveResponse(
        active=bool(live.get("active")) and session_allows_live,
        phase=str(phase) if phase else None,
        activity_label=live.get("activity_label"),
        status=live.get("status"),
        message=live.get("message") or ap_session.error_message,
        exploration_session_id=str(exploration_session_id) if exploration_session_id else None,
        test_task_id=numeric_test_task_id,
        run_id=str(run_id) if run_id else None,
        spec_name=live.get("spec_name"),
        current_stage=live.get("current_stage"),
        activity_kind=live.get("activity_kind"),
        agent_task_id=live.get("agent_task_id"),
        last_tool=live.get("last_tool"),
        last_tool_label=live.get("last_tool_label"),
        tool_calls=_safe_int(live.get("tool_calls")),
        browser_tool_calls=_safe_int(live.get("browser_tool_calls")),
        interactions=_safe_int(live.get("interactions")),
        capture_count=_safe_int(live.get("capture_count")),
        latest_capture_at=live.get("latest_capture_at"),
        activity_source=live.get("activity_source"),
        recent_tools=list(live.get("recent_tools") or []),
        artifacts=artifacts,
        latest_image=latest_image,
        subagents=list(live.get("subagents") or []),
        items_total=_safe_int(live.get("items_total")),
        items_completed=_safe_int(live.get("items_completed")),
        requirements_generated=_safe_int(live.get("requirements_generated")),
        verification_status=live.get("verification_status"),
        updated_at=live.get("updated_at"),
        browser_runtime=str(runtime["browser_runtime"]),
        live_view_available=bool(runtime["live_view_available"]),
        runtime_message=runtime["runtime_message"],
        vnc_url=runtime.get("vnc_url"),
        display_diagnostics=runtime.get("display_diagnostics"),
    )


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _short_tool_label(tool_name: str | None) -> str:
    if not tool_name:
        return ""
    if "__" in tool_name:
        return tool_name.rsplit("__", 1)[-1].replace("_", " ")
    return tool_name.replace("_", " ")


def _is_browser_tool_name(tool_name: str | None) -> bool:
    name = str(tool_name or "")
    short_name = name.rsplit("__", 1)[-1] if "__" in name else name
    return "__browser_" in name or short_name.startswith("browser_")


def _tool_name_from_record(record: Any) -> str:
    if not isinstance(record, dict):
        return ""
    for key in ("name", "tool_name", "tool"):
        value = record.get(key)
        if value:
            return str(value)
    short_name = record.get("short_name")
    return str(short_name) if short_name else ""


def _telemetry_from_tool_calls_artifact(path: Path) -> dict[str, Any]:
    raw = _safe_read_json_value(path)
    if isinstance(raw, dict):
        records = raw.get("tool_call_records") or raw.get("tool_calls") or raw.get("calls") or []
    else:
        records = raw
    if not isinstance(records, list):
        return {}

    tool_names = [_tool_name_from_record(record) for record in records]
    tool_names = [name for name in tool_names if name]
    if not records and not tool_names:
        return {}

    browser_count = sum(1 for name in tool_names if _is_browser_tool_name(name))
    last_tool = tool_names[-1] if tool_names else ""
    recent_tools: list[dict[str, Any]] = []
    for record, name in zip(records[-12:], tool_names[-12:], strict=False):
        at = record.get("at") or record.get("timestamp") or record.get("started_at") if isinstance(record, dict) else None
        recent_tools.append(
            {
                "name": name,
                "label": _short_tool_label(name),
                "at": at or datetime.utcnow().isoformat(),
                "source": "tool_calls_json",
                "artifact": str(path),
            }
        )

    return {
        "tool_calls": len(records),
        "browser_tool_calls": browser_count,
        "interactions": browser_count or len(records),
        "last_tool": last_tool,
        "last_tool_label": _short_tool_label(last_tool),
        "recent_tools": recent_tools,
        "activity_source": "tool_artifact_recovery",
    }


def _telemetry_from_summary_artifact(path: Path) -> dict[str, Any]:
    raw = _safe_read_json_value(path)
    if not isinstance(raw, dict):
        return {}
    summary = raw.get("agentStats") if isinstance(raw.get("agentStats"), dict) else raw
    if not isinstance(summary, dict):
        return {}

    telemetry = {
        "tool_calls": _safe_int(summary.get("tool_calls")),
        "browser_tool_calls": _safe_int(
            summary.get("browser_tool_calls"),
            _safe_int(summary.get("successful_browser_tool_calls")),
        ),
        "interactions": _safe_int(summary.get("interactions")),
    }
    if telemetry["interactions"] <= 0:
        telemetry["interactions"] = telemetry["browser_tool_calls"] or telemetry["tool_calls"]

    last_tool = str(summary.get("last_tool") or "")
    tool_names = summary.get("tool_names")
    if not last_tool and isinstance(tool_names, list) and tool_names:
        last_tool = str(tool_names[-1] or "")
    if last_tool:
        telemetry["last_tool"] = last_tool
        telemetry["last_tool_label"] = str(summary.get("last_tool_label") or _short_tool_label(last_tool))

    recent_tools = summary.get("recent_tools")
    if isinstance(recent_tools, list):
        telemetry["recent_tools"] = recent_tools[-12:]
    if any(_safe_int(telemetry.get(key)) > 0 for key in ("tool_calls", "browser_tool_calls", "interactions")) or last_tool:
        telemetry["activity_source"] = "tool_artifact_recovery"
        return telemetry
    return {}


def _merge_recovered_tool_telemetry(live: dict[str, Any], recovered: dict[str, Any]) -> dict[str, Any]:
    if not recovered:
        return live
    merged = dict(live)
    increased = False
    for key in ("tool_calls", "browser_tool_calls", "interactions"):
        existing = _safe_int(merged.get(key))
        candidate = _safe_int(recovered.get(key))
        if candidate > existing:
            merged[key] = candidate
            increased = True

    recovered_tool_calls = _safe_int(recovered.get("tool_calls"))
    existing_tool_calls = _safe_int(merged.get("tool_calls"))
    if recovered.get("last_tool") and (
        not merged.get("last_tool")
        or recovered_tool_calls >= existing_tool_calls
    ):
        merged["last_tool"] = recovered["last_tool"]
        merged["last_tool_label"] = recovered.get("last_tool_label") or _short_tool_label(recovered["last_tool"])
        increased = True

    recovered_recent = recovered.get("recent_tools")
    if isinstance(recovered_recent, list) and recovered_recent:
        existing_recent = list(merged.get("recent_tools") or [])
        existing_names = [item.get("name") for item in existing_recent if isinstance(item, dict)]
        for item in recovered_recent:
            if not isinstance(item, dict):
                continue
            if item.get("name") and item.get("name") == (existing_names[-1] if existing_names else None):
                continue
            existing_recent.append(item)
            existing_names.append(item.get("name"))
        merged["recent_tools"] = existing_recent[-12:]
        increased = True

    if increased and merged.get("activity_source") not in {"real_tool_progress", "agent_queue_progress"}:
        merged["activity_source"] = recovered.get("activity_source") or "tool_artifact_recovery"
    return merged


def _recover_live_tool_progress(
    live: dict[str, Any],
    *,
    exploration_session_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Recover live counters from persisted agent artifacts without lowering real telemetry."""
    merged = dict(live)
    for _, session_dir in _live_artifact_dirs(
        exploration_session_id=exploration_session_id,
        run_id=run_id,
    ):
        if not session_dir.exists():
            continue
        for artifact_name in ("tool_calls.json", "agent_summary.json", "summary.json"):
            path = session_dir / artifact_name
            recovered = (
                _telemetry_from_tool_calls_artifact(path)
                if artifact_name == "tool_calls.json"
                else _telemetry_from_summary_artifact(path)
            )
            merged = _merge_recovered_tool_telemetry(merged, recovered)
    return merged


def _merge_artifact_live_progress(
    live: dict[str, Any],
    artifacts: list[AutoPilotLiveArtifactResponse],
) -> dict[str, Any]:
    """Attach browser capture evidence with a conservative activity fallback."""
    if not artifacts:
        return live

    image_artifacts = [artifact for artifact in artifacts if artifact.type == "image"]
    if not image_artifacts:
        return live

    merged = dict(live)
    image_count = len(image_artifacts)
    latest = image_artifacts[0]
    latest_at = latest.modified_at.isoformat() if latest.modified_at else None

    merged["capture_count"] = max(_safe_int(merged.get("capture_count")), image_count)
    if latest_at:
        merged["latest_capture_at"] = latest_at

    has_tool_progress = any(
        _safe_int(merged.get(key)) > 0 for key in ("tool_calls", "browser_tool_calls", "interactions")
    ) or bool(merged.get("last_tool"))
    if not has_tool_progress:
        merged["browser_tool_calls"] = max(_safe_int(merged.get("browser_tool_calls")), image_count)
        merged["interactions"] = max(_safe_int(merged.get("interactions")), image_count)
        merged["activity_source"] = "capture_activity_fallback"

    live_updated_at = _parse_live_timestamp(merged.get("updated_at"))
    if latest.modified_at and (not live_updated_at or latest.modified_at > live_updated_at):
        merged["updated_at"] = latest.modified_at.isoformat()
        if not merged.get("message") or str(merged.get("message")) == "Browser slot acquired":
            merged["message"] = "Latest browser capture available."

    return merged


async def _merge_live_agent_progress(live: dict[str, Any]) -> dict[str, Any]:
    """Fill live state from Redis heartbeat telemetry when DB progress lags."""
    task_id = live.get("agent_task_id")
    if not task_id:
        return live

    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE, get_agent_queue

        if not REDIS_AVAILABLE:
            return live

        queue = get_agent_queue()
        await queue.connect()
        progress = await queue.get_task_progress(str(task_id)) or {}
        task = await queue.get_task(str(task_id))
        telemetry = task.telemetry if task and isinstance(task.telemetry, dict) else {}
    except Exception as exc:
        logger.debug("Unable to read live AutoPilot agent progress for %s: %s", task_id, exc)
        return live

    source = progress or telemetry
    if not source:
        return live

    merged = dict(live)
    task_status = str(getattr(getattr(task, "status", None), "value", getattr(task, "status", "")) or "")
    task_is_terminal = task_status in {"completed", "failed", "timeout", "cancelled"}
    for key in ("tool_calls", "browser_tool_calls", "interactions"):
        merged[key] = max(_safe_int(merged.get(key)), _safe_int(source.get(key)))

    last_tool = str(source.get("last_tool") or merged.get("last_tool") or "")
    has_source_progress = any(_safe_int(source.get(key)) > 0 for key in ("tool_calls", "browser_tool_calls", "interactions"))
    if has_source_progress or source.get("last_tool"):
        merged["activity_source"] = "agent_queue_progress"
    if last_tool and (
        not merged.get("last_tool")
        or _safe_int(source.get("tool_calls")) >= _safe_int(merged.get("tool_calls"))
    ):
        label = str(source.get("last_tool_label") or _short_tool_label(last_tool))
        merged["last_tool"] = last_tool
        merged["last_tool_label"] = label
        recent_tools = list(merged.get("recent_tools") or [])
        if not recent_tools or recent_tools[-1].get("name") != last_tool:
            recent_tools.append(
                {
                    "name": last_tool,
                    "label": label,
                    "at": source.get("updated_at") or datetime.utcnow().isoformat(),
                }
            )
            merged["recent_tools"] = recent_tools[-12:]

    if source.get("phase") and not source.get("status") and not task_is_terminal:
        merged["status"] = source["phase"]

    for key in ("status", "message", "current_stage", "activity_label", "updated_at"):
        if task_is_terminal and key in {"status", "message"}:
            continue
        if source.get(key):
            merged[key] = source[key]

    if task_is_terminal:
        merged["status"] = task_status
        if getattr(task, "error", None):
            merged["message"] = task.error
        if getattr(task, "completed_at", None):
            merged["updated_at"] = task.completed_at.isoformat()

    return merged


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


def _summary_int(summary: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = summary.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _derive_session_stats(ap_session: AutoPilotSession, session: Session | None) -> dict[str, Any]:
    """Return session stats, deriving fallbacks from detail rows when aggregates are stale."""

    stats: dict[str, Any] = {
        "total_pages_discovered": ap_session.total_pages_discovered,
        "total_flows_discovered": ap_session.total_flows_discovered,
        "total_requirements_generated": ap_session.total_requirements_generated,
        "total_specs_generated": ap_session.total_specs_generated,
        "total_tests_generated": ap_session.total_tests_generated,
        "total_tests_passed": ap_session.total_tests_passed,
        "total_tests_failed": ap_session.total_tests_failed,
        "coverage_percentage": ap_session.coverage_percentage,
    }
    if session is None:
        return stats

    phases = session.exec(select(AutoPilotPhase).where(AutoPilotPhase.session_id == ap_session.id)).all()
    for phase in phases:
        summary = phase.result_summary
        if phase.phase_name == "exploration":
            stats["total_pages_discovered"] = max(
                stats["total_pages_discovered"],
                _summary_int(summary, "pages_discovered", "total_pages", "pages"),
            )
            stats["total_flows_discovered"] = max(
                stats["total_flows_discovered"],
                _summary_int(summary, "flows_discovered", "total_flows", "flows"),
            )
        elif phase.phase_name == "requirements":
            stats["total_requirements_generated"] = max(
                stats["total_requirements_generated"],
                _summary_int(summary, "requirements_generated", "total_requirements", "requirements"),
            )

    spec_tasks = session.exec(select(AutoPilotSpecTask).where(AutoPilotSpecTask.session_id == ap_session.id)).all()
    test_tasks = session.exec(select(AutoPilotTestTask).where(AutoPilotTestTask.session_id == ap_session.id)).all()
    completed_specs = [task for task in spec_tasks if task.status == "completed"]
    generated_tests = [task for task in test_tasks if task.status in {"passed", "failed", "error", "completed"}]
    passed_tests = [task for task in test_tasks if task.passed is True or task.status == "passed"]
    failed_tests = [
        task
        for task in test_tasks
        if task.passed is False or task.status in {"failed", "error"}
    ]

    stats["total_requirements_generated"] = max(
        stats["total_requirements_generated"],
        len({task.requirement_id for task in spec_tasks if task.requirement_id is not None}),
    )
    stats["total_specs_generated"] = max(stats["total_specs_generated"], len(completed_specs))
    stats["total_tests_generated"] = max(stats["total_tests_generated"], len(generated_tests))
    stats["total_tests_passed"] = max(stats["total_tests_passed"], len(passed_tests))
    stats["total_tests_failed"] = max(stats["total_tests_failed"], len(failed_tests))
    if stats["coverage_percentage"] <= 0 and stats["total_specs_generated"]:
        stats["coverage_percentage"] = min(
            100.0,
            round((stats["total_tests_passed"] / stats["total_specs_generated"]) * 100, 1),
        )
    return stats


def _session_to_response(
    ap_session: AutoPilotSession,
    session: Session | None = None,
    temporal: dict[str, Any] | None = None,
) -> AutoPilotSessionResponse:
    """Convert a DB session model to the API response model."""
    if session is not None:
        _reconcile_stale_session(session, ap_session)
    derived_stats = _derive_session_stats(ap_session, session)
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
        total_pages_discovered=derived_stats["total_pages_discovered"],
        total_flows_discovered=derived_stats["total_flows_discovered"],
        total_requirements_generated=derived_stats["total_requirements_generated"],
        total_specs_generated=derived_stats["total_specs_generated"],
        total_tests_generated=derived_stats["total_tests_generated"],
        total_tests_passed=derived_stats["total_tests_passed"],
        total_tests_failed=derived_stats["total_tests_failed"],
        coverage_percentage=derived_stats["coverage_percentage"],
        error_message=ap_session.error_message,
        created_at=ap_session.created_at,
        started_at=ap_session.started_at,
        completed_at=ap_session.completed_at,
        instructions=ap_session.instructions,
        config=ap_session.config,
        temporal_workflow_id=ap_session.temporal_workflow_id,
        temporal_run_id=ap_session.temporal_run_id,
        temporal=temporal,
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


def _checklist_item_to_response(item: AutoPilotChecklistItem) -> AutoPilotChecklistItemResponse:
    return AutoPilotChecklistItemResponse(
        id=item.id,
        session_id=item.session_id,
        sequence=item.sequence,
        kind=item.kind,
        phase_name=item.phase_name,
        title=item.title,
        detail=item.detail,
        status=item.status,
        progress=item.progress,
        items_completed=item.items_completed,
        items_total=item.items_total,
        source_type=item.source_type,
        source_id=item.source_id,
        metadata=item.metadata_dict,
        created_at=item.created_at,
        updated_at=item.updated_at,
        completed_at=item.completed_at,
    )


def _checklist_summary(items: list[AutoPilotChecklistItemResponse]) -> AutoPilotChecklistSummaryResponse:
    summary = AutoPilotChecklistSummaryResponse(total=len(items))
    direct_statuses = {
        "pending",
        "running",
        "waiting",
        "completed",
        "failed",
        "runtime_failed",
        "runtime_stale",
        "spec_not_automatable",
        "planner_contract_failed",
        "skipped",
    }
    for item in items:
        if item.status in direct_statuses:
            setattr(summary, item.status, getattr(summary, item.status) + 1)
        elif item.status in {"queued", "tool_use", "generating"}:
            summary.running += 1
        elif item.status in {"passed", "answered", "auto_continued"}:
            summary.completed += 1
        elif item.status in {"error", "cancelled"}:
            summary.failed += 1
    return summary


def _load_checklist_response(db: Session, session_id: str) -> AutoPilotChecklistResponse:
    try:
        from orchestrator.services.autopilot_agent_reliability import reconcile_autopilot_agent_attempts

        reconcile_autopilot_agent_attempts(session_id)
    except Exception as exc:
        logger.debug("Unable to reconcile AutoPilot agent attempts for %s: %s", session_id, exc)
    stmt = (
        select(AutoPilotChecklistItem)
        .where(AutoPilotChecklistItem.session_id == session_id)
        .order_by(AutoPilotChecklistItem.sequence, AutoPilotChecklistItem.id)
    )
    items = [_checklist_item_to_response(item) for item in db.exec(stmt).all()]
    return AutoPilotChecklistResponse(items=items, summary=_checklist_summary(items))


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
        test_data_refs=list(cfg.get("test_data_refs") or []),
        browser_auth_session_id=cfg.get("browser_auth_session_id"),
        use_project_default_browser_auth=bool(cfg.get("use_project_default_browser_auth", False)),
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
        requirements_mode=cfg.get("requirements_mode", "single_agent"),
        requirements_max_agents=cfg.get("requirements_max_agents", 3),
        requirements_browser_verification=cfg.get("requirements_browser_verification", "off"),
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
            .where(
                AutoPilotTestTask.status.in_(
                    [
                        "pending",
                        "running",
                        "paused",
                        "failed",
                        "error",
                        "runtime_failed",
                        "runtime_stale",
                        "spec_not_automatable",
                        "planner_contract_failed",
                    ]
                )
            )
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
    active_for_user = max(_count_user_active_sessions(user_key), _count_user_active_sessions_db(user_key))
    if active_for_user >= MAX_ACTIVE_SESSIONS_PER_USER:
        raise HTTPException(
            status_code=429,
            detail=f"You already have {active_for_user} active Auto Pilot sessions. Maximum is {MAX_ACTIVE_SESSIONS_PER_USER}.",
        )

    # Validate entry URLs
    if not request_body.entry_urls:
        raise HTTPException(status_code=422, detail="At least one entry URL is required.")
    session_id = f"autopilot_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"

    test_data_refs = [str(ref).strip() for ref in request_body.test_data_refs if str(ref).strip()]
    browser_auth_session_id = (request_body.browser_auth_session_id or "").strip() or None
    use_project_default_browser_auth = bool(request_body.use_project_default_browser_auth)
    if browser_auth_session_id and use_project_default_browser_auth:
        raise HTTPException(
            status_code=400,
            detail="Choose either a specific browser auth session or the project default, not both.",
        )

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
        "requirements_mode": request_body.requirements_mode,
        "requirements_max_agents": request_body.requirements_max_agents,
        "requirements_browser_verification": request_body.requirements_browser_verification,
        "has_credentials": bool(request_body.credentials),
        "has_login_url": bool(request_body.login_url),
        "test_data_refs": test_data_refs,
        "browser_auth_session_id": browser_auth_session_id,
        "use_project_default_browser_auth": use_project_default_browser_auth,
    }

    # Create session in DB
    with Session(engine) as db:
        if test_data_refs:
            resolved_test_data = resolve_test_data_refs(
                db,
                project_id=request_body.project_id,
                refs=test_data_refs,
                render_as="json",
            )
            missing_refs = resolved_test_data.get("missing") or []
            if missing_refs:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "Selected test data refs are unavailable.",
                        "missing_test_data_refs": missing_refs,
                    },
                )

        if browser_auth_session_id or use_project_default_browser_auth:
            try:
                browser_auth_row = resolve_browser_auth_session_row(
                    db,
                    request_body.project_id,
                    browser_auth_session_id=browser_auth_session_id,
                    use_default=use_project_default_browser_auth,
                )
                if not browser_auth_row:
                    raise BrowserAuthSessionError("Project default browser auth session was not found")
                ensure_browser_auth_session_usable(browser_auth_row)
                config["browser_auth_session_id"] = browser_auth_row.id if browser_auth_session_id else None
                config["browser_auth_session_name"] = browser_auth_row.name
            except BrowserAuthSessionError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        db.refresh(ap_session)

        await _start_autopilot_temporal_or_fail(ap_session, db)
        db.refresh(ap_session)

        start_response = {
            "session_id": session_id,
            "status": "pending",
            "message": f"Auto Pilot started. Poll progress at GET /autopilot/{session_id}",
            "entry_urls": list(request_body.entry_urls),
            "phases": [name for name, _ in PHASE_DEFINITIONS],
            "temporal_workflow_id": ap_session.temporal_workflow_id,
            "temporal_run_id": ap_session.temporal_run_id,
        }

    logger.info(f"Auto Pilot session {session_id} started for {len(request_body.entry_urls)} URL(s)")

    return start_response


@router.get("/sessions", response_model=list[AutoPilotSessionResponse])
async def list_sessions(
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    """List all Auto Pilot sessions, newest first."""
    stmt = select(AutoPilotSession).order_by(AutoPilotSession.created_at.desc())

    stmt = apply_project_filter(stmt, AutoPilotSession, project_id)
    if status:
        stmt = stmt.where(AutoPilotSession.status == status)

    sessions = session.exec(stmt).all()
    return [_session_to_response(s, session) for s in sessions]


@router.get("/temporal/health", response_model=dict)
async def get_autopilot_temporal_health():
    """Get Temporal readiness for AutoPilot browser workflows."""
    from orchestrator.services.temporal_client import check_autopilot_temporal_health

    return await check_autopilot_temporal_health()


@router.post("/recover-orphans", response_model=dict)
async def recover_orphaned_autopilot_runtime(
    session: Session = Depends(get_session),
):
    """Clean AutoPilot-owned orphan processes and reconcile stale running sessions."""
    try:
        from orchestrator.utils.browser_cleanup import find_autopilot_session_ids_in_processes
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AutoPilot cleanup unavailable: {exc}") from exc

    process_session_ids = find_autopilot_session_ids_in_processes()
    candidate_ids = set(process_session_ids)
    active_statuses = {"pending", "running", "awaiting_input", "paused"}
    stmt = select(AutoPilotSession).where(
        AutoPilotSession.status.in_(["pending", "running", "awaiting_input", "paused", "failed", "cancelled"])
    )
    db_sessions = {item.id: item for item in session.exec(stmt).all()}
    candidate_ids.update(db_sessions.keys())

    cleanup_results: list[dict[str, Any]] = []
    reconciled: list[str] = []
    for session_id in sorted(candidate_ids):
        ap_session = db_sessions.get(session_id) or session.get(AutoPilotSession, session_id)
        should_cleanup = False
        if ap_session is None:
            should_cleanup = session_id in process_session_ids
        elif ap_session.status not in active_statuses:
            should_cleanup = session_id in process_session_ids
        elif await _is_stale_live_browser_async(ap_session):
            should_cleanup = True

        cleanup: dict[str, Any] | None = None
        if should_cleanup:
            cleanup = await _session_process_cleanup_async(session_id)
            cleanup_results.append(cleanup)

        if ap_session and ap_session.status in active_statuses and await _is_stale_live_browser_async(ap_session):
            reason = "AutoPilot runtime was recovered after stale live browser state."
            if _mark_session_interrupted(session, ap_session, reason, cleanup=cleanup):
                reconciled.append(session_id)

    if reconciled:
        session.commit()

    killed = sum(int(item.get("killed") or 0) for item in cleanup_results)
    terminated = sum(int(item.get("terminated") or 0) for item in cleanup_results)
    matched = sum(int(item.get("matched") or 0) for item in cleanup_results)
    return {
        "status": "ok",
        "matched_processes": matched,
        "terminated_processes": terminated,
        "killed_processes": killed,
        "reconciled_sessions": reconciled,
        "cleanup": cleanup_results,
    }


@router.get("/{session_id}", response_model=AutoPilotSessionResponse)
async def get_session_detail(
    session_id: str,
    session: Session = Depends(get_session),
):
    """Get Auto Pilot session status and summary."""
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")
    temporal = await _autopilot_temporal_payload(ap_session)
    return _session_to_response(ap_session, session, temporal=temporal)


@router.get("/{session_id}/temporal", response_model=AutoPilotTemporalResponse)
async def get_session_temporal(
    session_id: str,
    session: Session = Depends(get_session),
):
    """Get Temporal workflow diagnostics for an AutoPilot session."""
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")
    return await _autopilot_temporal_payload(ap_session)


@router.get("/{session_id}/live", response_model=AutoPilotLiveResponse)
async def get_live_browser_state(
    session_id: str,
    session: Session = Depends(get_session),
):
    """Get current live browser state for an Auto Pilot session."""
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")

    await _reconcile_stale_session_async(session, ap_session)
    live = await _merge_live_agent_progress(dict((ap_session.config or {}).get("live_browser") or {}))
    phase = live.get("phase") or ap_session.current_phase
    exploration_session_id = live.get("exploration_session_id")
    run_id = live.get("run_id")
    test_task_id = live.get("test_task_id")
    numeric_test_task_id: int | None = None
    if test_task_id:
        try:
            numeric_test_task_id = int(test_task_id)
        except (TypeError, ValueError):
            numeric_test_task_id = None

    if numeric_test_task_id and not run_id:
        task = session.get(AutoPilotTestTask, numeric_test_task_id)
        if task and task.session_id == session_id:
            run_id = task.run_id

    live = _recover_live_tool_progress(
        live,
        exploration_session_id=str(exploration_session_id) if exploration_session_id else None,
        run_id=str(run_id) if run_id else None,
    )
    artifacts = _collect_live_artifacts(
        exploration_session_id=str(exploration_session_id) if exploration_session_id else None,
        run_id=str(run_id) if run_id else None,
    )
    return _live_response_from_state(
        ap_session,
        live,
        artifacts,
        phase=phase,
        exploration_session_id=exploration_session_id,
        run_id=run_id,
        numeric_test_task_id=numeric_test_task_id,
    )


@router.get("/{session_id}/evidence", response_model=AutoPilotEvidenceResponse)
async def get_session_evidence(
    session_id: str,
    session: Session = Depends(get_session),
):
    """Get failure evidence and captured artifacts for an Auto Pilot session."""
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")

    await _reconcile_stale_session_async(session, ap_session)
    live = await _merge_live_agent_progress(dict((ap_session.config or {}).get("live_browser") or {}))
    phase = live.get("phase") or ap_session.current_phase

    failed_phase_row = session.exec(
        select(AutoPilotPhase)
        .where(AutoPilotPhase.session_id == session_id)
        .where(AutoPilotPhase.status == "failed")
        .order_by(AutoPilotPhase.completed_at.desc(), AutoPilotPhase.phase_order.desc())
    ).first()

    exploration_ids: list[str] = []
    for value in [
        live.get("exploration_session_id"),
        *list(ap_session.exploration_session_ids or []),
    ]:
        if value and str(value) not in exploration_ids:
            exploration_ids.append(str(value))

    run_ids: list[str] = []
    live_run_id = live.get("run_id")
    if live_run_id:
        run_ids.append(str(live_run_id))
    test_task_id = live.get("test_task_id")
    numeric_test_task_id: int | None = None
    if test_task_id:
        try:
            numeric_test_task_id = int(test_task_id)
        except (TypeError, ValueError):
            numeric_test_task_id = None
    if numeric_test_task_id:
        task = session.get(AutoPilotTestTask, numeric_test_task_id)
        if task and task.session_id == session_id and task.run_id and task.run_id not in run_ids:
            run_ids.append(task.run_id)
    live = _recover_live_tool_progress(
        live,
        exploration_session_id=str(live.get("exploration_session_id")) if live.get("exploration_session_id") else None,
        run_id=str(run_ids[0]) if run_ids else None,
    )

    tasks = session.exec(select(AutoPilotTestTask).where(AutoPilotTestTask.session_id == session_id)).all()
    for task in tasks:
        if task.run_id and task.run_id not in run_ids:
            run_ids.append(task.run_id)

    evidence_artifacts = _collect_autopilot_artifacts(
        exploration_session_ids=exploration_ids,
        run_ids=run_ids,
        include_diagnostics=True,
    )
    live_artifacts = [
        AutoPilotLiveArtifactResponse(
            name=artifact.name,
            path=artifact.path,
            type=artifact.type,
            modified_at=artifact.modified_at,
        )
        for artifact in evidence_artifacts
        if artifact.type in {"image", "video"}
    ]
    live_response = _live_response_from_state(
        ap_session,
        live,
        live_artifacts,
        phase=phase,
        exploration_session_id=exploration_ids[0] if exploration_ids else None,
        run_id=run_ids[0] if run_ids else None,
        numeric_test_task_id=numeric_test_task_id,
    )
    temporal = await _autopilot_temporal_payload(ap_session)
    latest_image = next((artifact for artifact in evidence_artifacts if artifact.type == "image"), None)
    videos = [artifact for artifact in evidence_artifacts if artifact.type == "video"]
    diagnostics = [artifact for artifact in evidence_artifacts if artifact.type in {"json", "text", "yaml"}]

    return AutoPilotEvidenceResponse(
        session_id=session_id,
        status=ap_session.status,
        current_phase=ap_session.current_phase,
        error_message=ap_session.error_message,
        failed_phase=_phase_to_response(failed_phase_row) if failed_phase_row else None,
        temporal=temporal,
        live=live_response,
        artifacts=evidence_artifacts,
        latest_image=latest_image,
        videos=videos,
        diagnostics=diagnostics,
    )


async def _cancel_live_agent_task(ap_session: AutoPilotSession, reason: str) -> dict[str, Any]:
    """Cancel any Redis agent task linked to this session's live browser state."""
    config = dict(ap_session.config or {})
    live = dict(config.get("live_browser") or {})
    task_id = live.get("agent_task_id")
    result: dict[str, Any] = {
        "agent_task_cancel": "not_found",
        "agent_task_cleanup": None,
        "cleanup": None,
    }

    if task_id:
        try:
            from orchestrator.services.agent_queue import REDIS_AVAILABLE, get_agent_queue, should_use_agent_queue

            if REDIS_AVAILABLE and should_use_agent_queue():
                queue = get_agent_queue()
                await queue.connect()
                before = await queue.get_task(str(task_id))
                cancelled = await queue.cancel_task(str(task_id))
                after = await queue.get_task(str(task_id))
                if cancelled and after:
                    status = after.status.value
                    if status == "cancel_requested":
                        result["agent_task_cancel"] = "running_cancel_requested"
                    elif status == "cancelled":
                        result["agent_task_cancel"] = "cancelled"
                    elif status in {"completed", "failed", "timeout"}:
                        result["agent_task_cancel"] = f"already_{status}"
                    else:
                        result["agent_task_cancel"] = status
                elif before and before.status.value in {"completed", "failed", "timeout", "cancelled"}:
                    result["agent_task_cancel"] = "already_terminal"
                result["agent_task_cleanup"] = await queue.cleanup_orphaned_and_stale_tasks()
        except Exception as exc:
            logger.warning("Failed to cancel AutoPilot agent task %s for %s: %s", task_id, ap_session.id, exc)
            result["agent_task_cancel"] = "error"
            result["error"] = str(exc)

    result["cleanup"] = await _session_process_cleanup_async(ap_session.id)

    if live:
        live.update(
            {
                "active": False,
                "status": reason,
                "message": f"Auto Pilot {reason}",
                "cleanup": result["cleanup"],
                "updated_at": datetime.utcnow().isoformat(),
            }
        )
        config["live_browser"] = live
        ap_session.config = config
    return result


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


@router.get("/{session_id}/checklist", response_model=AutoPilotChecklistResponse)
async def get_session_checklist(
    session_id: str,
    session: Session = Depends(get_session),
):
    """Get persisted live checklist rows for an AutoPilot session."""
    ap_session = session.get(AutoPilotSession, session_id)
    if not ap_session:
        raise HTTPException(status_code=404, detail="Auto Pilot session not found")
    return _load_checklist_response(session, session_id)


def _sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.get("/{session_id}/checklist/stream")
async def stream_session_checklist(
    session_id: str,
):
    """Stream persisted checklist row changes while an AutoPilot session is active."""
    terminal_statuses = {"completed", "failed", "cancelled"}

    async def event_generator():
        seen: dict[int, str] = {}
        heartbeat_counter = 0
        while True:
            with Session(engine) as db:
                ap_session = db.get(AutoPilotSession, session_id)
                if not ap_session:
                    yield _sse_event("error", {"detail": "Auto Pilot session not found"})
                    return
                payload = _load_checklist_response(db, session_id)
                changed = []
                for item in payload.items:
                    updated = item.updated_at.isoformat()
                    if seen.get(item.id) != updated:
                        seen[item.id] = updated
                        changed.append(item)

                for item in changed:
                    yield _sse_event("checklist", item.model_dump(mode="json"))

                if ap_session.status in terminal_statuses:
                    yield _sse_event("complete", {"session_id": session_id, "status": ap_session.status})
                    return

            heartbeat_counter += 1
            if heartbeat_counter >= 10:
                heartbeat_counter = 0
                yield _sse_event("heartbeat", {"session_id": session_id, "ts": datetime.utcnow().isoformat()})
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


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
    try:
        from orchestrator.services.autopilot_checklist import complete_checklist_item

        complete_checklist_item(
            session_id=session_id,
            source_type="question",
            source_id=str(question.id),
            title=f"Question: {question.question_type.replace('_', ' ')}",
            kind="question",
            phase_name=question.phase_name,
            detail=body.answer_text,
            status="answered",
            metadata={"answer_text": body.answer_text},
        )
    except Exception as exc:
        logger.debug("Unable to update AutoPilot question checklist row: %s", exc)

    # Notify running pipeline if it exists
    entry = _running_pipelines.get(session_id)
    if entry and not entry[0].done():
        _, pipeline, _ = entry
        try:
            pipeline.answer_question(body.question_id, body.answer_text)
            logger.info(f"Forwarded answer to pipeline {session_id} for question {body.question_id}")
        except Exception as e:
            logger.warning(f"Could not forward answer to pipeline: {e}")
    elif ap_session.temporal_workflow_id:
        logger.info("Stored answer for Temporal-backed AutoPilot %s question %s", session_id, body.question_id)
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

    await _cancel_live_agent_task(ap_session, "paused")

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

    await _signal_autopilot_temporal(ap_session, "pause", "manual_pause")

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
    if ap_session.temporal_workflow_id:
        _reset_resumable_state(session, ap_session, failed_phase)
        await _signal_autopilot_temporal(ap_session, "resume")
        logger.info("Signalled Temporal AutoPilot resume for %s", session_id)
    elif ap_session.status == "paused":
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
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
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

    cancel_result = await _cancel_live_agent_task(ap_session, "cancelled")
    await _signal_autopilot_temporal(ap_session, "cancel", "manual_cancel")
    session.add(ap_session)
    session.commit()

    logger.info(f"Auto Pilot {session_id} cancelled")
    return {"status": "cancelled", "session_id": session_id, **cancel_result}


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
                if ap_session.temporal_workflow_id:
                    logger.info(
                        "AutoPilot %s is managed by Temporal workflow %s; skipping in-memory resume",
                        ap_session.id,
                        ap_session.temporal_workflow_id,
                    )
                    continue
                cleanup = await _session_process_cleanup_async(ap_session.id)
                if await _is_stale_live_browser_async(ap_session):
                    reason = "AutoPilot runtime was stale during backend startup recovery."
                    if _mark_session_interrupted(db, ap_session, reason, cleanup=cleanup):
                        db.commit()
                        logger.warning(
                            "Marked stale AutoPilot %s failed during startup recovery: %s",
                            ap_session.id,
                            cleanup,
                        )
                    continue
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
