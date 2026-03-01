"""
Exploration API Router

Provides endpoints for controlling and monitoring AI-powered
application exploration sessions.

Resource Management:
- Browser slots are managed by BrowserResourcePool (unified across all operations)
- Per-user concurrent exploration limit: MAX_EXPLORATIONS_PER_USER (default: 2)
- Rate limiting on start/stop endpoints prevents API abuse
- Circuit breaker pattern prevents wasting slots on unreachable targets
"""

import asyncio
import logging
import os

# Import workflows - deferred to avoid circular imports
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from .db import get_session
from .middleware.auth import get_current_user_optional
from .middleware.rate_limit import API_LIMITS, limiter
from .models_db import DiscoveredApiEndpoint, ExplorationSession

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.browser_pool import OperationType as BrowserOpType
from services.browser_pool import get_browser_pool

# Import MCP health checker
from utils.mcp_health import verify_mcp_environment

logger = logging.getLogger(__name__)

# ========== Configuration ==========
from orchestrator.config import settings as app_settings

MAX_EXPLORATIONS_PER_USER = app_settings.max_explorations_per_user
MAX_TRACKED_EXPLORATIONS = 100  # Hard cap on _running_explorations dict size

router = APIRouter(prefix="/exploration", tags=["exploration"])


# ========== Pydantic Models ==========


class ExplorationStartRequest(BaseModel):
    """Request to start an exploration session."""

    entry_url: str = Field(..., description="URL to start exploration from")
    project_id: str = Field(default="default", description="Project ID")
    strategy: str = Field(default="goal_directed", description="Exploration strategy")
    max_interactions: int = Field(default=50, ge=1, le=200)
    max_depth: int = Field(default=10, ge=1, le=50)
    timeout_minutes: int = Field(default=30, ge=1, le=120)
    login_url: str | None = None
    credentials: dict | None = None  # {username, password, username_var, password_var}
    exclude_patterns: list[str] = Field(default_factory=list)
    focus_areas: list[str] = Field(default_factory=list)
    additional_instructions: str | None = None  # Custom instructions for AI


class ExplorationSessionResponse(BaseModel):
    """Response model for exploration session."""

    id: str
    project_id: str | None
    entry_url: str
    status: str
    strategy: str
    pages_discovered: int
    flows_discovered: int
    elements_discovered: int
    api_endpoints_discovered: int
    issues_discovered: int = 0
    progress_data: str | None = None
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: int | None
    error_message: str | None
    created_at: datetime


class FlowResponse(BaseModel):
    """Response model for a discovered flow."""

    id: int
    flow_name: str
    flow_category: str
    description: str | None
    start_url: str
    end_url: str
    step_count: int
    is_success_path: bool
    preconditions: list[str]
    postconditions: list[str]


class ApiEndpointResponse(BaseModel):
    """Response model for a discovered API endpoint."""

    id: int
    method: str
    url: str
    response_status: int | None
    triggered_by_action: str | None
    call_count: int


class PageSummary(BaseModel):
    """Page discovered via transitions."""

    url: str
    page_type: str | None = None
    visit_count: int = 1
    first_seen_sequence: int = 0
    actions_performed: list[str] = Field(default_factory=list)


class ElementSummary(BaseModel):
    """Element discovered via transitions."""

    element_ref: str | None = None
    element_role: str | None = None
    element_name: str | None = None
    action_type: str
    action_value: str | None = None
    page_url: str
    occurrence_count: int = 1


class FlowStepResponse(BaseModel):
    """Step detail within a flow."""

    id: int
    step_number: int
    action_type: str
    action_description: str
    element_ref: str | None = None
    element_role: str | None = None
    element_name: str | None = None
    value: str | None = None


class FlowDetailResponse(BaseModel):
    """Flow with full step details."""

    id: int
    flow_name: str
    flow_category: str
    description: str | None = None
    start_url: str
    end_url: str
    step_count: int
    is_success_path: bool
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    steps: list[FlowStepResponse] = Field(default_factory=list)


class ApiEndpointDetailResponse(BaseModel):
    """Full API endpoint details."""

    id: int
    method: str
    url: str
    response_status: int | None = None
    triggered_by_action: str | None = None
    call_count: int
    request_headers: dict | None = None
    request_body_sample: str | None = None
    response_body_sample: str | None = None
    first_seen: datetime | None = None


class IssueResponse(BaseModel):
    """Response model for a discovered issue."""

    id: int
    issue_type: str
    severity: str
    url: str
    description: str
    element: str | None = None
    evidence: str | None = None
    created_at: datetime


class ExplorationFullDetailsResponse(BaseModel):
    """Combined full details for all 5 categories."""

    session: ExplorationSessionResponse
    pages: list[PageSummary] = Field(default_factory=list)
    flows: list[FlowDetailResponse] = Field(default_factory=list)
    elements: list[ElementSummary] = Field(default_factory=list)
    api_endpoints: list[ApiEndpointDetailResponse] = Field(default_factory=list)
    issues: list[IssueResponse] = Field(default_factory=list)


class FlowUpdateRequest(BaseModel):
    """Partial update for a flow."""

    flow_name: str | None = None
    flow_category: str | None = None
    description: str | None = None
    start_url: str | None = None
    end_url: str | None = None
    is_success_path: bool | None = None
    preconditions: list[str] | None = None
    postconditions: list[str] | None = None


class ApiEndpointUpdateRequest(BaseModel):
    """Partial update for an API endpoint."""

    method: str | None = None
    url: str | None = None
    response_status: int | None = None
    triggered_by_action: str | None = None
    request_body_sample: str | None = None
    response_body_sample: str | None = None


class ExplorationResultsResponse(BaseModel):
    """Full exploration results."""

    session: ExplorationSessionResponse
    flows: list[FlowResponse]
    api_endpoints: list[ApiEndpointResponse]


# ========== Background Task Storage ==========
# Track running exploration tasks: session_id -> (asyncio.Task, user_key)
_running_explorations: dict[str, tuple[asyncio.Task, str]] = {}

# ========== Circuit Breaker State ==========
# domain -> list of failure timestamps
_domain_failures: dict[str, list[float]] = defaultdict(list)
CIRCUIT_BREAKER_THRESHOLD = 3  # failures before tripping
CIRCUIT_BREAKER_WINDOW = 600  # 10 minutes

# ========== Spec/Test Generation Job Tracking ==========
_spec_gen_jobs: dict[str, dict] = {}
MAX_SPEC_GEN_JOBS = 50


def _cleanup_spec_gen_jobs():
    """Remove completed/failed jobs older than 1 hour, enforce cap."""
    now = time.time()
    to_remove = []
    for job_id, job in _spec_gen_jobs.items():
        if job["status"] in ("completed", "failed"):
            completed_at = job.get("completed_at", 0)
            if now - completed_at > 3600:
                to_remove.append(job_id)
    for job_id in to_remove:
        del _spec_gen_jobs[job_id]
    # Enforce hard cap - never evict running jobs
    if len(_spec_gen_jobs) > MAX_SPEC_GEN_JOBS:
        evictable = sorted(
            [(jid, j) for jid, j in _spec_gen_jobs.items() if j["status"] != "running"],
            key=lambda x: x[1].get("started_at", 0),
        )
        for job_id, _ in evictable[: len(_spec_gen_jobs) - MAX_SPEC_GEN_JOBS]:
            del _spec_gen_jobs[job_id]


# ========== Helper Functions ==========


def _get_user_key(user, request: Request) -> str:
    """Get a unique key for the user (user ID or IP address)."""
    if user:
        return f"user:{user.id}"
    return f"ip:{request.client.host}" if request.client else "ip:unknown"


def _sweep_done_tasks():
    """Remove completed tasks from _running_explorations."""
    done_keys = [k for k, (task, _) in _running_explorations.items() if task.done()]
    for k in done_keys:
        _running_explorations.pop(k, None)
    if done_keys:
        logger.debug(f"Swept {len(done_keys)} completed exploration tasks")


def _count_user_explorations(user_key: str) -> int:
    """Count running explorations for a given user."""
    return sum(1 for _, (task, uk) in _running_explorations.items() if uk == user_key and not task.done())


def _check_circuit_breaker(url: str) -> str | None:
    """Check if the circuit breaker is tripped for this domain.

    Returns error message if tripped, None if OK.
    """
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.hostname or url
    now = time.monotonic()

    # Prune old failures outside the window
    _domain_failures[domain] = [t for t in _domain_failures[domain] if now - t < CIRCUIT_BREAKER_WINDOW]

    if len(_domain_failures[domain]) >= CIRCUIT_BREAKER_THRESHOLD:
        return (
            f"Circuit breaker open for {domain}: "
            f"{len(_domain_failures[domain])} failures in last "
            f"{CIRCUIT_BREAKER_WINDOW // 60} minutes. "
            f"Please verify the target is reachable and try again later."
        )
    return None


def _record_domain_failure(url: str):
    """Record a connectivity failure for circuit breaker tracking."""
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.hostname or url
    _domain_failures[domain].append(time.monotonic())


def _build_exploratory_agent_config(
    request_body: ExplorationStartRequest,
    run_id: str,
) -> dict:
    """Map ExplorationStartRequest fields to ExploratoryAgent config dict."""
    config: dict[str, Any] = {
        "url": request_body.entry_url,
        "time_limit_minutes": request_body.timeout_minutes,
        "run_id": run_id,
        "project_id": request_body.project_id,
    }

    # Build auth config
    if request_body.credentials:
        creds = request_body.credentials
        # Resolve env-var indirection (username_var / password_var)
        username = creds.get("username") or os.environ.get(creds.get("username_var", ""), "")
        password = creds.get("password") or os.environ.get(creds.get("password_var", ""), "")
        config["auth"] = {
            "type": "credentials",
            "credentials": {"username": username, "password": password},
            "login_url": request_body.login_url or "/login",
        }
    else:
        config["auth"] = {"type": "none"}

    # Build textual instructions from strategy/depth/interaction/custom fields
    parts: list[str] = []
    if request_body.additional_instructions:
        parts.append(request_body.additional_instructions)
    if request_body.strategy and request_body.strategy != "goal_directed":
        parts.append(f"Use a '{request_body.strategy}' exploration strategy.")
    if request_body.max_depth and request_body.max_depth != 10:
        parts.append(f"Limit exploration depth to {request_body.max_depth} levels.")
    if request_body.max_interactions and request_body.max_interactions != 50:
        parts.append(f"Aim for up to {request_body.max_interactions} interactions.")
    config["instructions"] = " ".join(parts) if parts else ""

    if request_body.exclude_patterns:
        config["excluded_patterns"] = request_body.exclude_patterns
    if request_body.focus_areas:
        config["focus_areas"] = request_body.focus_areas

    return config


def _bridge_action_trace_to_transitions(
    action_trace: list[dict],
    entry_url: str,
    store,
    session_id: str,
) -> None:
    """Convert ExploratoryAgent action_trace entries into DiscoveredTransition DB records."""
    current_url = entry_url

    for idx, action in enumerate(action_trace):
        act_type = (action.get("action") or "unknown").lower()
        target = action.get("target") or ""
        action.get("outcome") or "ok"

        before_url = current_url
        after_url = current_url

        # navigate actions change the current URL
        if act_type == "navigate" and target and target.startswith("http"):
            after_url = target
            current_url = target

        try:
            store.store_transition(
                session_id=session_id,
                sequence_number=idx + 1,
                action_type=act_type,
                action_target={"element": target} if target else {},
                action_value=None,
                before_url=before_url,
                after_url=after_url,
                transition_type="navigation" if before_url != after_url else "interaction",
                before_page_type=None,
                after_page_type=None,
            )
        except Exception as te:
            logger.warning(f"Failed to bridge transition {idx}: {te}")


def _bridge_flows_to_db(
    run_id: str,
    entry_url: str,
    store,
    session_id: str,
) -> int:
    """Read ExploratoryAgent flows.json and store as DiscoveredFlow + FlowStep records.

    Returns the number of flows bridged.
    """
    import json as json_mod

    # ExploratoryAgent writes to runs/{run_id}/flows.json
    project_root = Path(__file__).resolve().parent.parent.parent
    candidates = [
        project_root / "runs" / run_id / "flows.json",
        Path("/app/runs") / run_id / "flows.json",
    ]

    flows_data: list[dict] = []
    for path in candidates:
        if path.exists():
            try:
                raw = json_mod.loads(path.read_text())
                flows_data = raw.get("flows", raw) if isinstance(raw, dict) else raw
            except Exception as e:
                logger.warning(f"Failed to read flows.json at {path}: {e}")
            break

    if not flows_data:
        return 0

    # Category inference keywords
    CATEGORY_KEYWORDS = {
        "authentication": ["login", "logout", "sign in", "sign up", "register", "auth", "password"],
        "navigation": ["navigate", "menu", "sidebar", "breadcrumb", "tab"],
        "form": ["form", "submit", "input", "field", "fill", "validation"],
        "search": ["search", "filter", "query", "find"],
        "crud": ["create", "read", "update", "delete", "edit", "add", "remove"],
        "checkout": ["cart", "checkout", "payment", "order", "purchase"],
    }

    def _infer_category(title: str) -> str:
        title_lower = title.lower()
        for cat, keywords in CATEGORY_KEYWORDS.items():
            if any(kw in title_lower for kw in keywords):
                return cat
        return "general"

    count = 0
    for flow in flows_data:
        title = flow.get("title") or flow.get("name") or f"Flow {count + 1}"
        category = _infer_category(title)
        happy_path = flow.get("happy_path") or ""
        pages = flow.get("pages") or []
        entry_point = flow.get("entry_point") or (pages[0] if pages else entry_url)
        exit_point = flow.get("exit_point") or (pages[-1] if pages else entry_url)

        # Build steps from happy_path text or pages list
        steps: list[dict] = []
        if happy_path:
            # Split happy_path description into pseudo-steps
            for _i, sentence in enumerate(happy_path.split(". ")):
                sentence = sentence.strip().rstrip(".")
                if sentence:
                    steps.append(
                        {
                            "action": "step",
                            "element": sentence,
                        }
                    )
        elif pages:
            for _i, page in enumerate(pages):
                steps.append(
                    {
                        "action": "navigate",
                        "element": f"Navigate to {page}",
                    }
                )

        try:
            store.store_flow(
                session_id=session_id,
                flow_name=title,
                flow_category=category,
                start_url=entry_point if entry_point.startswith("http") else entry_url,
                end_url=exit_point if exit_point.startswith("http") else entry_url,
                step_count=flow.get("steps_count") or len(steps) or len(pages),
                is_success_path=True,
                description=happy_path[:500] if happy_path else None,
                preconditions=[],
                postconditions=[],
                steps=steps,
            )
            count += 1
        except Exception as fe:
            logger.warning(f"Failed to bridge flow '{title}': {fe}")

    return count


def _count_pages_and_elements(
    action_trace: list[dict],
    entry_url: str,
) -> tuple:
    """Count unique pages and unique elements from action_trace.

    Returns (pages_count, elements_count).
    """
    pages = {entry_url}
    elements = set()

    for action in action_trace:
        act_type = (action.get("action") or "").lower()
        target = action.get("target") or ""
        if not target:
            continue

        if act_type == "navigate" and target.startswith("http"):
            pages.add(target)
        elif act_type in ("click", "fill", "select", "check", "uncheck", "hover", "submit"):
            elements.add(target)

    return len(pages), len(elements)


async def _check_target_connectivity(url: str) -> str | None:
    """Quick connectivity check to the target URL.

    Returns error message if unreachable, None if OK.
    """
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5.0),
            follow_redirects=True,
            verify=False,  # Don't fail on self-signed certs
        ) as client:
            response = await client.head(url)
            if response.status_code >= 500:
                _record_domain_failure(url)
                return f"Target returned {response.status_code}. Site may be down."
    except httpx.ConnectError:
        _record_domain_failure(url)
        return f"Cannot connect to {url}. Please verify the URL is correct and the site is running."
    except httpx.TimeoutException:
        _record_domain_failure(url)
        return f"Connection to {url} timed out (5s). Site may be slow or unreachable."
    except Exception as e:
        # Don't fail on other errors (e.g. SSL issues) - let the explorer handle them
        logger.warning(f"Connectivity check warning for {url}: {e}")
    return None


# ========== API Endpoints ==========


@router.get("/health", response_model=dict)
async def check_exploration_health():
    """
    Check if the exploration environment is healthy.

    Runs pre-flight checks for:
    - Playwright MCP server availability
    - Display configuration (for headed mode)
    - MCP configuration

    Returns health status and any errors/warnings.
    """
    status = await verify_mcp_environment()

    200 if status["ready"] else 503

    return {
        "ready": status["ready"],
        "errors": status["errors"],
        "warnings": status["warnings"],
        "checks": status["checks"],
    }


@router.post("/start", response_model=dict)
@limiter.limit(API_LIMITS["start_exploration"])
async def start_exploration(
    request_body: ExplorationStartRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user_optional),
):
    """
    Start a new exploration session.

    The exploration runs in the background. Use GET /exploration/{id}
    to check progress and results.

    Limits:
    - Per-user: MAX_EXPLORATIONS_PER_USER concurrent explorations (default: 2)
    - Rate: 5 requests/minute
    - Global: bounded by BrowserResourcePool slots
    """
    from agents.exploratory_agent import ExploratoryAgent

    # Sweep completed tasks before any checks
    _sweep_done_tasks()

    # Hard cap on tracked explorations (memory safety)
    if len(_running_explorations) >= MAX_TRACKED_EXPLORATIONS:
        logger.error(f"Exploration tracking dict at hard cap ({MAX_TRACKED_EXPLORATIONS})")
        raise HTTPException(status_code=503, detail="System at maximum exploration capacity. Please try again later.")

    # Per-user concurrent exploration limit
    user_key = _get_user_key(user, request)
    user_running = _count_user_explorations(user_key)
    if user_running >= MAX_EXPLORATIONS_PER_USER:
        raise HTTPException(
            status_code=429,
            detail=(
                f"You have {user_running} running exploration(s). "
                f"Maximum per user: {MAX_EXPLORATIONS_PER_USER}. "
                f"Please wait for a running exploration to complete or stop one."
            ),
        )

    # Circuit breaker check
    cb_error = _check_circuit_breaker(request_body.entry_url)
    if cb_error:
        raise HTTPException(status_code=429, detail=cb_error)

    # Quick connectivity check (fail fast instead of holding browser slot)
    conn_error = await _check_target_connectivity(request_body.entry_url)
    if conn_error:
        raise HTTPException(status_code=422, detail=conn_error)

    # Pre-flight health check
    logger.info("Running pre-flight health checks...")
    env_status = await verify_mcp_environment()

    if not env_status["ready"]:
        logger.error(f"Environment not ready: {env_status['errors']}")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Environment not ready for exploration",
                "issues": env_status["errors"],
                "warnings": env_status["warnings"],
            },
        )

    if env_status["warnings"]:
        logger.warning(f"Environment warnings: {env_status['warnings']}")

    # Check browser pool availability (unified resource management)
    pool = await get_browser_pool()
    pool_status = await pool.get_status()

    # Determine initial status based on slot availability
    slot_available = pool_status["available"] > 0
    initial_status = "running" if slot_available else "queued"
    queue_position = None if slot_available else pool_status["queued"] + 1

    # Generate session ID
    session_id = f"explore_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"

    # Create session in database
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=request_body.project_id)

    store.create_session(
        session_id=session_id,
        entry_url=request_body.entry_url,
        strategy=request_body.strategy,
        config={
            "max_interactions": request_body.max_interactions,
            "max_depth": request_body.max_depth,
            "timeout_minutes": request_body.timeout_minutes,
            "has_credentials": bool(request_body.credentials),
            "exclude_patterns": request_body.exclude_patterns,
            "focus_areas": request_body.focus_areas,
            "additional_instructions": request_body.additional_instructions,
        },
    )

    # Set initial status to queued if slots are full
    if initial_status == "queued":
        store.update_session_status(session_id, "queued")

    # Write initial "queued" phase so frontend shows progress immediately
    store.update_session_progress(
        session_id,
        {
            "phase": "queued",
            "message": "Waiting for browser slot...",
            "step": 0,
            "max_steps": request_body.max_interactions,
            "last_action": "",
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

    # Run exploration in background using unified browser pool
    async def run_exploration():
        pool = await get_browser_pool()

        # Block if a load test is running
        from orchestrator.services.load_test_lock import check_system_available

        await check_system_available("exploration")

        try:
            async with pool.browser_slot(
                request_id=session_id,
                operation_type=BrowserOpType.EXPLORATION,
                description=f"Explore: {request_body.entry_url}",
            ) as acquired:
                if not acquired:
                    # Timeout waiting for slot
                    logger.warning(f"Exploration {session_id} failed to acquire browser slot (timeout)")
                    store.update_session_status(session_id, "failed", "Timeout waiting for browser slot")
                    return

                logger.info(f"Browser slot acquired for exploration {session_id}")

                # Update status to running now that we have a slot
                store.update_session_status(session_id, "running")
                store.update_session_progress(
                    session_id,
                    {
                        "phase": "starting",
                        "message": "Browser slot acquired, starting agent...",
                        "step": 0,
                        "max_steps": request_body.max_interactions,
                        "last_action": "",
                        "updated_at": datetime.utcnow().isoformat(),
                    },
                )

                # Shared state for progress tracking
                _agent_task_id = [None]  # mutable container for closure

                def _on_task_enqueued(task_id: str):
                    _agent_task_id[0] = task_id
                    logger.info(f"Exploration {session_id}: agent task enqueued as {task_id}")
                    store.update_session_progress(
                        session_id,
                        {
                            "phase": "enqueued",
                            "message": "Agent task queued, waiting for worker...",
                            "step": 0,
                            "max_steps": request_body.max_interactions,
                            "last_action": "",
                            "updated_at": datetime.utcnow().isoformat(),
                        },
                    )

                async def _poll_progress():
                    """Poll agent heartbeat progress and write to DB."""
                    try:
                        from orchestrator.services.agent_queue import get_agent_queue

                        queue = get_agent_queue()
                        await queue.connect()
                        # Wait for task_id to be set
                        for _ in range(60):  # up to 30s
                            if _agent_task_id[0]:
                                break
                            await asyncio.sleep(0.5)
                        if not _agent_task_id[0]:
                            return
                        tid = _agent_task_id[0]
                        while True:
                            await asyncio.sleep(5)
                            progress = await queue.get_task_progress(tid)
                            if progress:
                                # Detect retry state from worker heartbeat
                                if progress.get("retry_attempt"):
                                    progress_with_meta = {
                                        "phase": "retrying",
                                        "message": f"Rate limited, retrying (attempt {progress['retry_attempt']})...",
                                        "step": 0,
                                        "max_steps": request_body.max_interactions,
                                        "last_action": "",
                                        "updated_at": datetime.utcnow().isoformat(),
                                    }
                                else:
                                    progress_with_meta = {
                                        "phase": "running",
                                        "step": progress.get("interactions", progress.get("tool_calls", 0)),
                                        "max_steps": request_body.max_interactions,
                                        "last_action": progress.get("last_tool", ""),
                                        "updated_at": datetime.utcnow().isoformat(),
                                    }
                                store.update_session_progress(session_id, progress_with_meta)
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logger.debug(f"Progress polling error (non-fatal): {e}")

                progress_task = asyncio.create_task(_poll_progress())

                # --- ExploratoryAgent execution ---
                agent = ExploratoryAgent()
                agent.on_task_enqueued = _on_task_enqueued

                ea_config = _build_exploratory_agent_config(request_body, run_id=session_id)
                ea_result = await agent.run(ea_config)

                # Stop progress polling and clear progress data
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass
                store.clear_session_progress(session_id)

                # --- Bridge ExploratoryAgent output to ExplorationSession DB tables ---
                action_trace = ea_result.get("action_trace", [])
                parsing_failed = ea_result.get("parsing_failed", False)
                total_flows = ea_result.get("total_flows_discovered", 0)

                # Bridge action_trace → DiscoveredTransition records
                _bridge_action_trace_to_transitions(action_trace, request_body.entry_url, store, session_id)

                # Bridge flows.json → DiscoveredFlow + FlowStep records
                flows_count = _bridge_flows_to_db(session_id, request_body.entry_url, store, session_id)
                # If no flows from file, use the total from EA result
                if flows_count == 0:
                    flows_count = total_flows

                # Count pages and elements from trace
                pages_count, elements_count = _count_pages_and_elements(action_trace, request_body.entry_url)

                # Safety net: detect zero-output explorations
                has_no_structured_data = flows_count == 0 and elements_count == 0 and len(action_trace) == 0
                if has_no_structured_data and not parsing_failed:
                    # Check if timeout produced partial results
                    if ea_result.get("termination_reason") == "timeout":
                        final_status = "completed"
                        error_msg = None
                    else:
                        final_status = "failed"
                        error_msg = (
                            "Exploration completed but discovered zero flows, elements, and actions. "
                            "The agent may have encountered issues with the target site."
                        )
                elif parsing_failed and flows_count == 0 and len(action_trace) == 0:
                    final_status = "failed"
                    error_msg = "Exploration completed but result parsing failed and no structured data recovered."
                else:
                    final_status = "completed"
                    error_msg = None

                # Update session with results
                store.update_session_status(session_id, final_status, error_msg)
                store.update_session_counts(
                    session_id,
                    pages=pages_count,
                    flows=flows_count,
                    elements=elements_count,
                    api_endpoints=0,  # ExploratoryAgent doesn't capture API endpoints
                )

        except asyncio.CancelledError:
            logger.info(f"Exploration {session_id} cancelled")
            store.update_session_status(session_id, "cancelled")
            raise

        except Exception as e:
            logger.error(f"Exploration failed for session {session_id}: {e}")
            store.update_session_status(session_id, "failed", str(e))

        finally:
            # Remove from tracking
            _running_explorations.pop(session_id, None)

    # Track the task with user key
    task = asyncio.create_task(run_exploration())
    _running_explorations[session_id] = (task, user_key)

    response = {
        "session_id": session_id,
        "status": initial_status,
        "message": f"Exploration started. Check progress at GET /exploration/{session_id}",
        "browser_pool": {
            "running": pool_status["running"],
            "max": pool_status["max_browsers"],
            "queued": pool_status["queued"] + (1 if initial_status == "queued" else 0),
            "available": pool_status["available"],
        },
    }

    if queue_position:
        response["queue_position"] = queue_position
        response["message"] = (
            f"Exploration queued at position {queue_position}. Will start when a slot becomes available."
        )

    return response


# ========== Spec/Test Generation Job Polling ==========
# NOTE: These must be defined BEFORE /{session_id} routes to avoid path conflicts


@router.get("/spec-gen-jobs", response_model=list)
async def list_spec_gen_jobs(
    session_id: str | None = Query(None, description="Filter by session ID"),
):
    """List all spec/test generation jobs, optionally filtered by session_id."""
    _cleanup_spec_gen_jobs()
    jobs = []
    for jid, job in _spec_gen_jobs.items():
        if session_id and job.get("session_id") != session_id:
            continue
        jobs.append(
            {
                "job_id": jid,
                "status": job["status"],
                "type": job.get("type"),
                "session_id": job.get("session_id"),
                "message": job.get("message"),
                "result": job.get("result"),
                "endpoint_count": job.get("endpoint_count"),
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
            }
        )
    return jobs


@router.get("/spec-gen-jobs/{job_id}", response_model=dict)
async def get_spec_gen_job(job_id: str):
    """Get status of a spec/test generation job."""
    job = _spec_gen_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "type": job.get("type"),
        "session_id": job.get("session_id"),
        "message": job.get("message"),
        "result": job.get("result"),
        "endpoint_count": job.get("endpoint_count"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
    }


@router.get("/{session_id}", response_model=ExplorationSessionResponse)
async def get_exploration_session(session_id: str, project_id: str = Query(default="default")):
    """Get exploration session status and summary."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return ExplorationSessionResponse(
        id=session.id,
        project_id=session.project_id,
        entry_url=session.entry_url,
        status=session.status,
        strategy=session.strategy,
        pages_discovered=session.pages_discovered,
        flows_discovered=session.flows_discovered,
        elements_discovered=session.elements_discovered,
        api_endpoints_discovered=session.api_endpoints_discovered,
        issues_discovered=getattr(session, "issues_discovered", 0) or 0,
        progress_data=getattr(session, "progress_data", None),
        started_at=session.started_at,
        completed_at=session.completed_at,
        duration_seconds=session.duration_seconds,
        error_message=session.error_message,
        created_at=session.created_at,
    )


@router.get("/{session_id}/results", response_model=ExplorationResultsResponse)
async def get_exploration_results(session_id: str, project_id: str = Query(default="default")):
    """Get full exploration results including flows and API endpoints."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    flows = store.get_session_flows(session_id)
    api_endpoints = store.get_session_api_endpoints(session_id)

    return ExplorationResultsResponse(
        session=ExplorationSessionResponse(
            id=session.id,
            project_id=session.project_id,
            entry_url=session.entry_url,
            status=session.status,
            strategy=session.strategy,
            pages_discovered=session.pages_discovered,
            flows_discovered=session.flows_discovered,
            elements_discovered=session.elements_discovered,
            api_endpoints_discovered=session.api_endpoints_discovered,
            issues_discovered=getattr(session, "issues_discovered", 0) or 0,
            progress_data=getattr(session, "progress_data", None),
            started_at=session.started_at,
            completed_at=session.completed_at,
            duration_seconds=session.duration_seconds,
            error_message=session.error_message,
            created_at=session.created_at,
        ),
        flows=[
            FlowResponse(
                id=f.id,
                flow_name=f.flow_name,
                flow_category=f.flow_category,
                description=f.description,
                start_url=f.start_url,
                end_url=f.end_url,
                step_count=f.step_count,
                is_success_path=f.is_success_path,
                preconditions=f.preconditions,
                postconditions=f.postconditions,
            )
            for f in flows
        ],
        api_endpoints=[
            ApiEndpointResponse(
                id=e.id,
                method=e.method,
                url=e.url,
                response_status=e.response_status,
                triggered_by_action=e.triggered_by_action,
                call_count=e.call_count,
            )
            for e in api_endpoints
        ],
    )


@router.post("/{session_id}/stop")
@limiter.limit(API_LIMITS["stop_exploration"])
async def stop_exploration(session_id: str, request: Request, project_id: str = Query(default="default")):
    """Stop a running exploration session."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.status not in ("running", "queued"):
        raise HTTPException(status_code=400, detail=f"Session is not running (status: {session.status})")

    # Cancel the background task if it exists
    entry = _running_explorations.get(session_id)
    if entry:
        task, _ = entry
        task.cancel()
        _running_explorations.pop(session_id, None)

    store.update_session_status(session_id, "stopped")

    return {"status": "stopped", "session_id": session_id}


@router.get("", response_model=list[ExplorationSessionResponse])
async def list_explorations(
    project_id: str = Query(default="default"),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
):
    """List exploration sessions."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    sessions = store.list_sessions(status=status, limit=limit)

    return [
        ExplorationSessionResponse(
            id=s.id,
            project_id=s.project_id,
            entry_url=s.entry_url,
            status=s.status,
            strategy=s.strategy,
            pages_discovered=s.pages_discovered,
            flows_discovered=s.flows_discovered,
            elements_discovered=s.elements_discovered,
            api_endpoints_discovered=s.api_endpoints_discovered,
            issues_discovered=getattr(s, "issues_discovered", 0) or 0,
            progress_data=getattr(s, "progress_data", None),
            started_at=s.started_at,
            completed_at=s.completed_at,
            duration_seconds=s.duration_seconds,
            error_message=s.error_message,
            created_at=s.created_at,
        )
        for s in sessions
    ]


@router.get("/{session_id}/flows", response_model=list[FlowResponse])
async def get_exploration_flows(
    session_id: str, project_id: str = Query(default="default"), category: str | None = Query(default=None)
):
    """Get flows discovered in an exploration session."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    flows = store.get_session_flows(session_id)

    if category:
        flows = [f for f in flows if f.flow_category == category]

    return [
        FlowResponse(
            id=f.id,
            flow_name=f.flow_name,
            flow_category=f.flow_category,
            description=f.description,
            start_url=f.start_url,
            end_url=f.end_url,
            step_count=f.step_count,
            is_success_path=f.is_success_path,
            preconditions=f.preconditions,
            postconditions=f.postconditions,
        )
        for f in flows
    ]


@router.get("/{session_id}/apis", response_model=list[ApiEndpointResponse])
async def get_exploration_apis(session_id: str, project_id: str = Query(default="default")):
    """Get API endpoints discovered in an exploration session."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    endpoints = store.get_session_api_endpoints(session_id)

    return [
        ApiEndpointResponse(
            id=e.id,
            method=e.method,
            url=e.url,
            response_status=e.response_status,
            triggered_by_action=e.triggered_by_action,
            call_count=e.call_count,
        )
        for e in endpoints
    ]


@router.get("/{session_id}/issues", response_model=list[IssueResponse])
async def get_exploration_issues(
    session_id: str, project_id: str = Query(default="default"), severity: str | None = Query(default=None)
):
    """Get issues discovered in an exploration session."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    issues = store.get_session_issues(session_id)

    if severity:
        issues = [i for i in issues if i.severity == severity]

    return [
        IssueResponse(
            id=i.id,
            issue_type=i.issue_type,
            severity=i.severity,
            url=i.url,
            description=i.description,
            element=i.element,
            evidence=i.evidence,
            created_at=i.created_at,
        )
        for i in issues
    ]


def _derive_pages_and_elements(transitions) -> tuple:
    """Derive unique pages and elements from transitions."""
    pages_map = {}  # url -> PageSummary data
    elements_map = {}  # (ref_or_name, action_type, page_url) -> ElementSummary data

    for t in transitions:
        # Process before_url
        if t.before_url and t.before_url not in pages_map:
            pages_map[t.before_url] = {
                "url": t.before_url,
                "page_type": t.before_page_type,
                "visit_count": 0,
                "first_seen_sequence": t.sequence_number,
                "actions": set(),
            }
        if t.before_url and t.before_url in pages_map:
            pages_map[t.before_url]["visit_count"] += 1
            pages_map[t.before_url]["actions"].add(t.action_type)

        # Process after_url (if different)
        if t.after_url and t.after_url not in pages_map:
            pages_map[t.after_url] = {
                "url": t.after_url,
                "page_type": t.after_page_type,
                "visit_count": 0,
                "first_seen_sequence": t.sequence_number,
                "actions": set(),
            }

        # Process elements
        target = t.action_target  # uses the property that parses JSON
        el_ref = target.get("ref")
        el_role = target.get("role")
        el_name = target.get("name") or target.get("element")
        el_key = (el_ref or el_name or f"seq_{t.sequence_number}", t.action_type, t.before_url)

        if el_key not in elements_map:
            elements_map[el_key] = {
                "element_ref": el_ref,
                "element_role": el_role,
                "element_name": el_name,
                "action_type": t.action_type,
                "action_value": t.action_value,
                "page_url": t.before_url,
                "occurrence_count": 0,
            }
        elements_map[el_key]["occurrence_count"] += 1

    pages = [
        PageSummary(
            url=p["url"],
            page_type=p["page_type"],
            visit_count=p["visit_count"],
            first_seen_sequence=p["first_seen_sequence"],
            actions_performed=sorted(p["actions"]),
        )
        for p in sorted(pages_map.values(), key=lambda x: x["first_seen_sequence"])
    ]

    elements = [
        ElementSummary(
            element_ref=e["element_ref"],
            element_role=e["element_role"],
            element_name=e["element_name"],
            action_type=e["action_type"],
            action_value=e["action_value"],
            page_url=e["page_url"],
            occurrence_count=e["occurrence_count"],
        )
        for e in sorted(elements_map.values(), key=lambda x: x["occurrence_count"], reverse=True)
    ]

    return pages, elements


def _get_exploration_file(session_id: str, filename: str) -> Path | None:
    """Resolve path to an exploration JSON file (local dev + Docker).

    Searches both the legacy AppExplorer path (runs/explorations/{id}/)
    and the ExploratoryAgent path (runs/{id}/).
    """
    project_root = Path(__file__).resolve().parent.parent.parent
    candidates = [
        # Legacy AppExplorer path
        project_root / "runs" / "explorations" / session_id / filename,
        Path("/app/runs/explorations") / session_id / filename,
        # ExploratoryAgent path (saves to runs/{run_id}/)
        project_root / "runs" / session_id / filename,
        Path("/app/runs") / session_id / filename,
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _load_flows_from_json(session_id: str) -> list[FlowDetailResponse]:
    """Fallback: load flows from flows.json when DB records are missing."""
    import json as json_mod

    json_path = _get_exploration_file(session_id, "flows.json")
    if not json_path:
        return []

    try:
        raw = json_mod.loads(json_path.read_text())
        # Handle both {"flows": [...]} (ExploratoryAgent) and [...] (legacy) formats
        data = raw.get("flows", raw) if isinstance(raw, dict) else raw
        if not isinstance(data, list):
            data = []
        flows = []
        for idx, f in enumerate(data):
            raw_steps = f.get("steps") or []
            steps = []
            for step_idx, s in enumerate(raw_steps):
                if isinstance(s, dict):
                    steps.append(
                        FlowStepResponse(
                            id=-(idx * 1000 + step_idx + 1),
                            step_number=s.get("stepNumber", step_idx + 1),
                            action_type=s.get("actionType") or s.get("action_type") or s.get("type") or "unknown",
                            action_description=s.get("actionDescription")
                            or s.get("action_description")
                            or s.get("description")
                            or str(s),
                            element_ref=s.get("elementRef") or s.get("element_ref"),
                            element_role=s.get("elementRole") or s.get("element_role"),
                            element_name=s.get("elementName") or s.get("element_name"),
                            value=s.get("value"),
                        )
                    )
                elif isinstance(s, str):
                    steps.append(
                        FlowStepResponse(
                            id=-(idx * 1000 + step_idx + 1),
                            step_number=step_idx + 1,
                            action_type="step",
                            action_description=s,
                        )
                    )

            flows.append(
                FlowDetailResponse(
                    id=-(idx + 1),
                    flow_name=f.get("name") or f.get("title") or "Unnamed Flow",
                    flow_category=f.get("category") or "unknown",
                    description=f.get("outcome") or f.get("description") or f.get("happy_path"),
                    start_url=f.get("startUrl") or f.get("start_url") or f.get("entry_point") or "",
                    end_url=f.get("endUrl") or f.get("end_url") or f.get("exit_point") or "",
                    step_count=len(steps),
                    is_success_path=f.get("isSuccessPath", True),
                    preconditions=f.get("preconditions") or [],
                    postconditions=f.get("postconditions") or [],
                    steps=steps,
                )
            )
        return flows
    except Exception as e:
        logger.warning(f"Failed to read flows.json for {session_id}: {e}")
        return []


def _load_api_endpoints_from_json(session_id: str) -> list[ApiEndpointDetailResponse]:
    """Fallback: load API endpoints from api_endpoints.json when DB records are missing."""
    import json as json_mod

    json_path = _get_exploration_file(session_id, "api_endpoints.json")
    if not json_path:
        return []

    try:
        data = json_mod.loads(json_path.read_text())
        endpoints = []
        for idx, e in enumerate(data):
            # Parse status defensively
            raw_status = e.get("status")
            status = None
            if raw_status is not None:
                try:
                    status = int(raw_status)
                except (ValueError, TypeError):
                    pass

            endpoints.append(
                ApiEndpointDetailResponse(
                    id=-(idx + 1),
                    method=e.get("method") or "GET",
                    url=e.get("url") or "",
                    response_status=status,
                    triggered_by_action=e.get("triggered_by"),
                    call_count=e.get("call_count", 1),
                    request_headers=e.get("request_headers"),
                    request_body_sample=e.get("request_body"),
                    response_body_sample=e.get("response_body"),
                )
            )
        return endpoints
    except Exception as e:
        logger.warning(f"Failed to read api_endpoints.json for {session_id}: {e}")
        return []


def _derive_pages_and_elements_from_json(session_id: str) -> tuple:
    """Fallback: derive pages and elements from transitions.json file for legacy sessions."""
    import json as json_mod

    json_path = _get_exploration_file(session_id, "transitions.json")
    if not json_path:
        return [], []

    try:
        data = json_mod.loads(json_path.read_text())
        pages_map = {}
        elements_map = {}

        for t in data:
            before_url = t.get("before", {}).get("url", "")
            after_url = t.get("after", {}).get("url", "")
            before_type = t.get("before", {}).get("pageType")
            after_type = t.get("after", {}).get("pageType")
            action = t.get("action", {})
            action_type = action.get("type", "unknown")
            action_elem = action.get("element", {}) or {}
            action_value = action.get("value")
            seq = t.get("sequence", 0)

            # Pages
            if before_url and before_url not in pages_map:
                pages_map[before_url] = {
                    "url": before_url,
                    "page_type": before_type,
                    "visit_count": 0,
                    "first_seen_sequence": seq,
                    "actions": set(),
                }
            if before_url and before_url in pages_map:
                pages_map[before_url]["visit_count"] += 1
                pages_map[before_url]["actions"].add(action_type)
            if after_url and after_url not in pages_map:
                pages_map[after_url] = {
                    "url": after_url,
                    "page_type": after_type,
                    "visit_count": 0,
                    "first_seen_sequence": seq,
                    "actions": set(),
                }

            # Elements
            el_name = action_elem.get("name") or action_elem.get("element")
            el_ref = action_elem.get("ref")
            el_role = action_elem.get("role")
            el_key = (el_ref or el_name or f"seq_{seq}", action_type, before_url)
            if el_key not in elements_map:
                elements_map[el_key] = {
                    "element_ref": el_ref,
                    "element_role": el_role,
                    "element_name": el_name,
                    "action_type": action_type,
                    "action_value": action_value,
                    "page_url": before_url,
                    "occurrence_count": 0,
                }
            elements_map[el_key]["occurrence_count"] += 1

            # Also add key elements from before/after state
            for elem_name in t.get("before", {}).get("keyElements", []):
                ek = (elem_name, "present", before_url)
                if ek not in elements_map:
                    elements_map[ek] = {
                        "element_ref": None,
                        "element_role": None,
                        "element_name": elem_name,
                        "action_type": "present",
                        "action_value": None,
                        "page_url": before_url,
                        "occurrence_count": 0,
                    }
                elements_map[ek]["occurrence_count"] += 1

            for elem_name in t.get("after", {}).get("keyElements", []):
                ek = (elem_name, "present", after_url)
                if ek not in elements_map:
                    elements_map[ek] = {
                        "element_ref": None,
                        "element_role": None,
                        "element_name": elem_name,
                        "action_type": "present",
                        "action_value": None,
                        "page_url": after_url,
                        "occurrence_count": 0,
                    }
                elements_map[ek]["occurrence_count"] += 1

        pages = [
            PageSummary(
                url=p["url"],
                page_type=p["page_type"],
                visit_count=p["visit_count"],
                first_seen_sequence=p["first_seen_sequence"],
                actions_performed=sorted(p["actions"]),
            )
            for p in sorted(pages_map.values(), key=lambda x: x["first_seen_sequence"])
        ]
        elements = [
            ElementSummary(
                element_ref=e["element_ref"],
                element_role=e["element_role"],
                element_name=e["element_name"],
                action_type=e["action_type"],
                action_value=e["action_value"],
                page_url=e["page_url"],
                occurrence_count=e["occurrence_count"],
            )
            for e in sorted(elements_map.values(), key=lambda x: x["occurrence_count"], reverse=True)
        ]
        return pages, elements
    except Exception as e:
        logger.warning(f"Failed to read transitions.json for {session_id}: {e}")
        return [], []


@router.get("/{session_id}/details", response_model=ExplorationFullDetailsResponse)
async def get_exploration_details(session_id: str, project_id: str = Query(default="default")):
    """Get full exploration details with pages, flows, elements, and API endpoints."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get transitions to derive pages and elements
    transitions = store.get_session_transitions(session_id)
    if transitions:
        pages, elements = _derive_pages_and_elements(transitions)
    else:
        # Fallback: read from transitions.json file for legacy sessions
        pages, elements = _derive_pages_and_elements_from_json(session_id)

    # Get flows with steps
    flows = store.get_session_flows(session_id)
    flow_details = []
    for f in flows:
        steps = store.get_flow_steps(f.id)
        flow_details.append(
            FlowDetailResponse(
                id=f.id,
                flow_name=f.flow_name,
                flow_category=f.flow_category,
                description=f.description,
                start_url=f.start_url,
                end_url=f.end_url,
                step_count=f.step_count,
                is_success_path=f.is_success_path,
                preconditions=f.preconditions,
                postconditions=f.postconditions,
                steps=[
                    FlowStepResponse(
                        id=s.id,
                        step_number=s.step_number,
                        action_type=s.action_type,
                        action_description=s.action_description,
                        element_ref=s.element_ref,
                        element_role=s.element_role,
                        element_name=s.element_name,
                        value=s.value,
                    )
                    for s in steps
                ],
            )
        )

    # Fallback: if DB returned no flows but session recorded some, try JSON file
    if not flow_details and (session.flows_discovered or 0) > 0:
        flow_details = _load_flows_from_json(session_id)

    # Get API endpoints with full details
    api_endpoints = store.get_session_api_endpoints(session_id)

    # Fallback: if DB returned no API endpoints but session recorded some, try JSON file
    api_endpoint_details = [
        ApiEndpointDetailResponse(
            id=e.id,
            method=e.method,
            url=e.url,
            response_status=e.response_status,
            triggered_by_action=e.triggered_by_action,
            call_count=e.call_count,
            request_headers=e.request_headers,
            request_body_sample=e.request_body_sample,
            response_body_sample=e.response_body_sample,
            first_seen=e.first_seen,
        )
        for e in api_endpoints
    ]
    if not api_endpoint_details and (session.api_endpoints_discovered or 0) > 0:
        api_endpoint_details = _load_api_endpoints_from_json(session_id)

    # Get issues
    issues = store.get_session_issues(session_id)

    return ExplorationFullDetailsResponse(
        session=ExplorationSessionResponse(
            id=session.id,
            project_id=session.project_id,
            entry_url=session.entry_url,
            status=session.status,
            strategy=session.strategy,
            pages_discovered=session.pages_discovered,
            flows_discovered=session.flows_discovered,
            elements_discovered=session.elements_discovered,
            api_endpoints_discovered=session.api_endpoints_discovered,
            issues_discovered=getattr(session, "issues_discovered", 0) or 0,
            progress_data=getattr(session, "progress_data", None),
            started_at=session.started_at,
            completed_at=session.completed_at,
            duration_seconds=session.duration_seconds,
            error_message=session.error_message,
            created_at=session.created_at,
        ),
        pages=pages,
        flows=flow_details,
        elements=elements,
        api_endpoints=api_endpoint_details,
        issues=[
            IssueResponse(
                id=i.id,
                issue_type=i.issue_type,
                severity=i.severity,
                url=i.url,
                description=i.description,
                element=i.element,
                evidence=i.evidence,
                created_at=i.created_at,
            )
            for i in issues
        ],
    )


@router.put("/{session_id}/flows/{flow_id}")
async def update_exploration_flow(
    session_id: str, flow_id: int, body: FlowUpdateRequest, project_id: str = Query(default="default")
):
    """Update a discovered flow's metadata."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated = store.update_flow(flow_id, session_id, **update_data)
    if not updated:
        raise HTTPException(status_code=404, detail="Flow not found or session mismatch")

    return {
        "status": "updated",
        "flow": {
            "id": updated.id,
            "flow_name": updated.flow_name,
            "flow_category": updated.flow_category,
            "description": updated.description,
            "start_url": updated.start_url,
            "end_url": updated.end_url,
            "step_count": updated.step_count,
            "is_success_path": updated.is_success_path,
            "preconditions": updated.preconditions,
            "postconditions": updated.postconditions,
        },
    }


@router.delete("/{session_id}/flows/{flow_id}")
async def delete_exploration_flow(session_id: str, flow_id: int, project_id: str = Query(default="default")):
    """Delete a discovered flow and its steps."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    deleted = store.delete_flow(flow_id, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Flow not found or session mismatch")

    return {"status": "deleted", "flow_id": flow_id}


@router.put("/{session_id}/apis/{endpoint_id}")
async def update_exploration_api_endpoint(
    session_id: str, endpoint_id: int, body: ApiEndpointUpdateRequest, project_id: str = Query(default="default")
):
    """Update a discovered API endpoint."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated = store.update_api_endpoint(endpoint_id, session_id, **update_data)
    if not updated:
        raise HTTPException(status_code=404, detail="API endpoint not found or session mismatch")

    return {
        "status": "updated",
        "endpoint": {
            "id": updated.id,
            "method": updated.method,
            "url": updated.url,
            "response_status": updated.response_status,
            "triggered_by_action": updated.triggered_by_action,
            "call_count": updated.call_count,
            "request_headers": updated.request_headers,
            "request_body_sample": updated.request_body_sample,
            "response_body_sample": updated.response_body_sample,
            "first_seen": str(updated.first_seen) if updated.first_seen else None,
        },
    }


@router.delete("/{session_id}/apis/{endpoint_id}")
async def delete_exploration_api_endpoint(
    session_id: str, endpoint_id: int, project_id: str = Query(default="default")
):
    """Delete a discovered API endpoint."""
    from memory.exploration_store import get_exploration_store

    store = get_exploration_store(project_id=project_id)

    deleted = store.delete_api_endpoint(endpoint_id, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="API endpoint not found or session mismatch")

    return {"status": "deleted", "endpoint_id": endpoint_id}


@router.get("/queue/status")
async def get_exploration_queue_status():
    """Get current exploration queue status.

    Returns information about browser slot usage from the unified pool.
    Note: Uses BrowserResourcePool which manages ALL browser operations.
    """
    pool = await get_browser_pool()
    status = await pool.get_status()

    # Filter to show exploration-specific info while showing overall pool status
    exploration_running = status["by_type"].get("exploration", 0)

    return {
        "active": exploration_running,
        "max": status["max_browsers"],
        "queued": status["queued"],
        "available": status["available"],
        "pool_status": {"total_running": status["running"], "by_type": status["by_type"]},
    }


@router.post("/{session_id}/generate-api-specs", response_model=dict)
async def generate_api_specs_from_exploration(
    session_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_user_optional),
):
    """
    Generate markdown API specs from discovered API endpoints.

    Takes the API endpoints captured during exploration and generates
    structured markdown API specification files that can be used as
    input to the API testing pipeline (NativeApiGenerator).

    Returns a job_id for polling progress via GET /exploration/spec-gen-jobs/{job_id}.
    """
    from sqlmodel import select

    _cleanup_spec_gen_jobs()

    # Verify session exists
    exploration = session.get(ExplorationSession, session_id)
    if not exploration:
        raise HTTPException(status_code=404, detail=f"Exploration session not found: {session_id}")

    # Check that endpoints exist
    stmt = select(DiscoveredApiEndpoint).where(DiscoveredApiEndpoint.session_id == session_id)
    endpoints = session.exec(stmt).all()
    if not endpoints:
        raise HTTPException(status_code=400, detail="No API endpoints found for this exploration session")

    project_id = exploration.project_id or "default"
    job_id = f"spec-gen-{session_id}-{uuid.uuid4().hex[:8]}"

    _spec_gen_jobs[job_id] = {
        "status": "running",
        "type": "specs",
        "session_id": session_id,
        "started_at": time.time(),
        "completed_at": None,
        "message": f"Generating API specs from {len(endpoints)} endpoints...",
        "result": None,
        "endpoint_count": len(endpoints),
    }

    # Run generation in background
    async def _generate():
        try:
            from workflows.api_spec_from_exploration import ApiSpecFromExploration

            generator = ApiSpecFromExploration(project_id=project_id)
            results = await generator.generate(session_id=session_id)
            spec_files = [str(p) for p in results]
            logger.info(f"Generated {len(results)} API spec files from exploration {session_id}")
            _spec_gen_jobs[job_id].update(
                {
                    "status": "completed",
                    "message": f"Generated {len(results)} API spec file(s)",
                    "result": {"spec_files": spec_files, "count": len(results)},
                    "completed_at": time.time(),
                }
            )
        except Exception as e:
            logger.error(f"API spec generation failed for {session_id}: {e}")
            _spec_gen_jobs[job_id].update(
                {
                    "status": "failed",
                    "message": str(e),
                    "completed_at": time.time(),
                }
            )

    background_tasks.add_task(_generate)

    return {
        "job_id": job_id,
        "status": "running",
        "session_id": session_id,
        "endpoint_count": len(endpoints),
        "message": f"Generating API specs from {len(endpoints)} discovered endpoints",
    }


@router.post("/{session_id}/generate-api-tests", response_model=dict)
async def generate_api_tests_from_exploration(
    session_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_user_optional),
):
    """
    Generate Playwright API tests from discovered API endpoints.

    Takes the API endpoints captured during exploration and generates
    comprehensive API test suites using the Playwright request fixture.

    Returns a job_id for polling progress via GET /exploration/spec-gen-jobs/{job_id}.
    """
    from sqlmodel import select

    _cleanup_spec_gen_jobs()

    # Verify session exists
    exploration = session.get(ExplorationSession, session_id)
    if not exploration:
        raise HTTPException(status_code=404, detail=f"Exploration session not found: {session_id}")

    # Check that endpoints exist
    stmt = select(DiscoveredApiEndpoint).where(DiscoveredApiEndpoint.session_id == session_id)
    endpoints = session.exec(stmt).all()
    if not endpoints:
        raise HTTPException(status_code=400, detail="No API endpoints found for this exploration session")

    project_id = exploration.project_id or "default"
    job_id = f"test-gen-{session_id}-{uuid.uuid4().hex[:8]}"

    _spec_gen_jobs[job_id] = {
        "status": "running",
        "type": "tests",
        "session_id": session_id,
        "started_at": time.time(),
        "completed_at": None,
        "message": f"Generating API tests from {len(endpoints)} endpoints...",
        "result": None,
        "endpoint_count": len(endpoints),
    }

    # Run generation in background
    async def _generate():
        try:
            from workflows.api_test_from_exploration import ApiTestFromExploration

            generator = ApiTestFromExploration(project_id=project_id)
            results = await generator.generate(session_id=session_id)
            test_files = [str(p) for p in results]
            logger.info(f"Generated {len(results)} API test files from exploration {session_id}")
            _spec_gen_jobs[job_id].update(
                {
                    "status": "completed",
                    "message": f"Generated {len(results)} API test file(s)",
                    "result": {"spec_files": test_files, "count": len(results)},
                    "completed_at": time.time(),
                }
            )
        except Exception as e:
            logger.error(f"API test generation failed for {session_id}: {e}")
            _spec_gen_jobs[job_id].update(
                {
                    "status": "failed",
                    "message": str(e),
                    "completed_at": time.time(),
                }
            )

    background_tasks.add_task(_generate)

    return {
        "job_id": job_id,
        "status": "running",
        "session_id": session_id,
        "endpoint_count": len(endpoints),
        "message": f"Generating API tests from {len(endpoints)} discovered endpoints",
    }
