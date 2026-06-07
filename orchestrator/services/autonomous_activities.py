"""Temporal activities for persistent autonomous testing missions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shlex
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ValidationError
from pydantic import Field as PydanticField
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import (
    ApplicationMap,
    AutonomousAgentWorkItem,
    AutonomousApproval,
    AutonomousFinding,
    AutonomousMission,
    AutonomousMissionRun,
    AutonomousTestProposal,
    CoverageGap,
    ExecutionSettings,
    ExplorationSession,
    Project,
    Requirement,
    RtmEntry,
    RtmSnapshot,
)
from orchestrator.services.autonomous_events import (
    create_autonomous_agent_event,
    emit_mission_event,
    emit_work_item_status_event,
)
from orchestrator.services.browser_auth_sessions import BrowserAuthSessionError, resolve_browser_auth_for_run
from orchestrator.utils.json_utils import extract_json_from_markdown
from orchestrator.utils.string_utils import slugify

logger = logging.getLogger(__name__)

MAX_PROPOSALS_PER_ITERATION = 5
VALID_TEST_TYPES = {"e2e", "api", "regression", "security", "accessibility", "unit"}
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3
DEFAULT_MAX_PENDING_APPROVALS = 25
DEFAULT_MAX_PARALLEL_AGENTS = 2
DEFAULT_WORK_ITEM_BATCH_SIZE = 7
DEFAULT_WORK_ITEM_STALE_MINUTES = 45
WORK_ITEM_ACTIVE_STATUSES = {"queued", "running"}
WORK_ITEM_TERMINAL_STATUSES = {"completed", "failed", "blocked", "cancelled"}
WHOLE_APP_TEAM_ROLES = (
    "surface_mapper",
    "explorer",
    "requirements_analyst",
    "rtm_mapper",
    "spec_writer",
    "regression_scout",
    "flake_triager",
)
REVISION_METADATA_KEYS = (
    "revision_of_work_item_id",
    "reviewer_work_item_id",
    "review_reason",
    "revision_attempt",
)
STRUCTURED_AGENT_ARTIFACT_KEYS = (
    "requirements",
    "rtm_candidates",
    "test_proposals",
    "bugs",
    "findings",
    "app_map_updates",
)
LOW_RISK_LEVELS = {"low", "info"}
PROPOSAL_VALIDATION_TIMEOUT_SECONDS = 120
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPOSITORY_ROOT / "runs"


class StructuredRequirementArtifact(BaseModel):
    title: str
    description: str | None = None
    category: str = "other"
    priority: str = "medium"
    acceptance_criteria: list[str] = PydanticField(default_factory=list)
    truth_state: str = "candidate_requirement"
    confidence: float = 0.7
    uncertainty_reason: str | None = None


class StructuredRtmCandidateArtifact(BaseModel):
    requirement_id: int | None = None
    requirement_code: str | None = None
    test_spec_name: str
    test_spec_path: str | None = None
    mapping_type: str = "suggested"
    confidence: float = 0.7
    coverage_notes: str | None = None
    gap_notes: str | None = None
    allow_candidate: bool = False


class StructuredTestProposalArtifact(BaseModel):
    title: str
    rationale: str
    target_url: str | None = None
    route: str | None = None
    test_type: str = "e2e"
    risk_level: str = "medium"
    requirement_ids: list[int] = PydanticField(default_factory=list)


class StructuredBugArtifact(BaseModel):
    title: str
    description: str
    severity: str = "medium"
    target_url: str | None = None
    route: str | None = None
    action: str | None = None
    observed_failure: str | None = None
    expected_behavior: str | None = None
    evidence: dict[str, Any] = PydanticField(default_factory=dict)


class StructuredAppMapUpdateArtifact(BaseModel):
    url: str
    page_title: str | None = None
    linked_urls: list[str] = PydanticField(default_factory=list)
    elements: dict[str, Any] = PydanticField(default_factory=dict)
    forms: list[dict[str, Any]] = PydanticField(default_factory=list)
    api_endpoints: list[dict[str, Any]] = PydanticField(default_factory=list)


class StructuredAgentContract(BaseModel):
    summary: str = ""
    requirements: list[StructuredRequirementArtifact] = PydanticField(default_factory=list)
    rtm_candidates: list[StructuredRtmCandidateArtifact] = PydanticField(default_factory=list)
    test_proposals: list[StructuredTestProposalArtifact] = PydanticField(default_factory=list)
    bugs: list[StructuredBugArtifact] = PydanticField(default_factory=list)
    findings: list[StructuredBugArtifact] = PydanticField(default_factory=list)
    app_map_updates: list[StructuredAppMapUpdateArtifact] = PydanticField(default_factory=list)
    blockers: list[str] = PydanticField(default_factory=list)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _requirement_truth_state(requirement: Requirement) -> str:
    return str(getattr(requirement, "truth_state", None) or "candidate_requirement")


def _requirement_generation_warning(requirement: Requirement) -> str | None:
    truth_state = _requirement_truth_state(requirement)
    if truth_state == "confirmed_requirement":
        return None
    if truth_state == "rejected_requirement":
        return "This requirement was rejected; generated tests should be reviewed before use."
    if truth_state == "stale_requirement":
        return "This requirement was marked stale; generated tests may not match the current application."
    if truth_state == "observed_behavior":
        return "This is observed behavior, not a confirmed requirement. Avoid encoding a bug as expected behavior."
    if truth_state == "candidate_requirement":
        return "This candidate requirement has not been confirmed by a human reviewer."
    return "This requirement is not confirmed; generated tests should be reviewed before use."


def _work_item_review_decision(item: AutonomousAgentWorkItem) -> str:
    result = item.result or {}
    return str(result.get("review_decision") or "none")


def _work_item_revision_metadata(item: AutonomousAgentWorkItem) -> dict[str, Any]:
    result = item.result or {}
    progress = item.progress or {}
    metadata: dict[str, Any] = {}
    for key in REVISION_METADATA_KEYS:
        value = progress.get(key) if progress.get(key) is not None else result.get(key)
        if value is not None:
            metadata[key] = value
    return metadata


def _normalize_fingerprint_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(_normalize_fingerprint_value(item) for item in value)
    if isinstance(value, dict):
        return " ".join(
            f"{_normalize_fingerprint_value(key)} {_normalize_fingerprint_value(value[key])}"
            for key in sorted(value)
        )
    text = str(value).lower()
    text = re.sub(r"https?://[^/\s]+", "", text)
    text = re.sub(r"[^a-z0-9/._ -]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _stable_dedupe_hash(*parts: Any, length: int = 32) -> str:
    raw = "|".join(_normalize_fingerprint_value(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def _requirement_fingerprint(row: dict[str, Any]) -> str:
    return _stable_dedupe_hash(
        "requirement",
        row.get("category") or "other",
        row.get("title"),
        row.get("acceptance_criteria") or row.get("criteria") or [],
    )


def _spec_fingerprint(row: dict[str, Any], requirement_ids: list[int] | None = None) -> str:
    route = row.get("route") or _route_from_url(row.get("target_url"))
    return _stable_dedupe_hash(
        "spec",
        row.get("test_type") or "e2e",
        route or row.get("target_url"),
        requirement_ids or row.get("requirement_ids") or row.get("requirements") or [],
        row.get("scenario") or row.get("title") or row.get("intent"),
    )


def _bug_fingerprint(row: dict[str, Any]) -> str:
    return _stable_dedupe_hash(
        "bug",
        row.get("route") or _route_from_url(row.get("target_url")) or row.get("url"),
        row.get("action") or row.get("steps") or row.get("reproduction_steps"),
        row.get("observed_failure") or row.get("actual") or row.get("description"),
        row.get("error") or row.get("error_message"),
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _as_text_list(value: Any) -> list[str]:
    return [str(item).strip() for item in _as_list(value) if str(item or "").strip()]


def _as_float(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _as_int_list(value: Any) -> list[int]:
    ids: list[int] = []
    for item in _as_list(value):
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _extract_structured_agent_output(output: str) -> dict[str, Any] | None:
    contract, _, _ = _extract_structured_agent_contract(output)
    return contract


def _extract_structured_agent_contract(output: str) -> tuple[dict[str, Any] | None, list[str], bool]:
    if not output.strip():
        return None, [], False
    try:
        parsed = extract_json_from_markdown(output)
    except Exception:
        match = re.search(r"\{.*\}", output, re.DOTALL)
        if not match:
            return None, [], False
        try:
            parsed = json.loads(match.group(0))
        except Exception as exc:
            return None, [f"Invalid JSON: {exc}"], True
    if isinstance(parsed, list):
        parsed = {"findings": parsed}
    if not isinstance(parsed, dict):
        return None, ["Structured output must be a JSON object."], True
    if not any(key in parsed for key in STRUCTURED_AGENT_ARTIFACT_KEYS):
        return None, [], False
    try:
        if hasattr(StructuredAgentContract, "model_validate"):
            contract = StructuredAgentContract.model_validate(parsed)
            return contract.model_dump(exclude_none=True), [], True
        contract = StructuredAgentContract.parse_obj(parsed)
        return contract.dict(exclude_none=True), [], True
    except ValidationError as exc:
        errors = []
        for error in exc.errors()[:12]:
            loc = ".".join(str(part) for part in error.get("loc", ())) or "root"
            errors.append(f"{loc}: {error.get('msg', 'invalid value')}")
        return None, errors or ["Structured output failed schema validation."], True


def _next_requirement_code(session: Session, project_id: str | None) -> str:
    requirements = session.exec(select(Requirement).where(Requirement.project_id == project_id)).all()
    highest = 0
    for requirement in requirements:
        match = re.search(r"REQ-(\d+)", requirement.req_code or "", re.IGNORECASE)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"REQ-{highest + 1:03d}"


def _resolve_requirement_ids(
    session: Session,
    project_id: str | None,
    row: dict[str, Any],
) -> list[int]:
    ids = _as_int_list(row.get("requirement_ids") or row.get("requirement_id"))
    code = str(row.get("requirement_code") or "").strip()
    title = str(row.get("requirement_title") or row.get("title") or "").strip()
    if code:
        requirement = session.exec(
            select(Requirement).where(Requirement.project_id == project_id, Requirement.req_code == code)
        ).first()
        if requirement and requirement.id is not None:
            ids.append(requirement.id)
    if title:
        fingerprint = _requirement_fingerprint({"title": title, "category": row.get("category"), "acceptance_criteria": []})
        for requirement in session.exec(select(Requirement).where(Requirement.project_id == project_id)).all():
            existing_fingerprint = _requirement_fingerprint(
                {
                    "title": requirement.title,
                    "category": requirement.category,
                    "acceptance_criteria": requirement.acceptance_criteria,
                }
            )
            if existing_fingerprint == fingerprint and requirement.id is not None:
                ids.append(requirement.id)
            elif (
                _normalize_fingerprint_value(requirement.title) == _normalize_fingerprint_value(title)
                and requirement.id is not None
            ):
                ids.append(requirement.id)
    seen: set[int] = set()
    return [req_id for req_id in ids if not (req_id in seen or seen.add(req_id))]


def _artifact_source_metadata(
    item: AutonomousAgentWorkItem,
    *,
    artifact_type: str,
    fingerprint: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "work_item_id": item.id,
        "role": item.role,
        "artifact_type": artifact_type,
        "artifact_fingerprint": fingerprint,
        **_work_item_revision_metadata(item),
    }
    if extra:
        metadata.update(extra)
    return metadata


def _is_revision_work_item(item: AutonomousAgentWorkItem) -> bool:
    metadata = _work_item_revision_metadata(item)
    return bool(metadata.get("revision_of_work_item_id"))


def _queued_work_item_sort_key(item: AutonomousAgentWorkItem) -> tuple[int, int, datetime]:
    return (
        0 if _is_revision_work_item(item) else 1,
        item.priority,
        item.created_at,
    )


def _mission_snapshot(mission: AutonomousMission) -> dict[str, Any]:
    return {
        "id": mission.id,
        "project_id": mission.project_id,
        "mission_type": mission.mission_type,
        "status": mission.status,
        "target_urls": mission.target_urls,
        "schedule_cron": mission.schedule_cron,
        "timezone": mission.timezone,
        "max_iterations": mission.max_iterations,
        "max_runtime_minutes": mission.max_runtime_minutes,
        "max_llm_budget_usd": mission.max_llm_budget_usd,
        "budget_used_usd": mission.budget_used_usd,
        "approval_policy": mission.approval_policy,
        "autonomy_level": mission.autonomy_level,
        "total_runs": mission.total_runs,
        "health_status": mission.health_status,
        "paused_reason": mission.paused_reason,
        "consecutive_failures": mission.consecutive_failures,
        "config": mission.config,
    }


def load_mission_policy(mission_id: str) -> dict[str, Any]:
    """Load mission state for deterministic workflow decisions."""
    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        if not mission:
            raise ValueError(f"Autonomous mission not found: {mission_id}")
        return _mission_snapshot(mission)


def create_mission_run(payload: dict[str, Any]) -> str:
    """Create a mission run row for one Temporal iteration."""
    mission_id = payload["mission_id"]
    workflow_id = payload.get("workflow_id")
    trigger_type = payload.get("trigger_type", "temporal")
    iteration_index = payload.get("iteration_index")
    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        if not mission:
            raise ValueError(f"Autonomous mission not found: {mission_id}")

        if iteration_index is not None:
            raw_run_key = f"{mission_id}|{workflow_id or ''}|{iteration_index}"
            run_id = f"amrun-{hashlib.sha256(raw_run_key.encode('utf-8')).hexdigest()[:12]}"
            existing = session.get(AutonomousMissionRun, run_id)
            if existing:
                return existing.id
        else:
            run_id = f"amrun-{uuid.uuid4().hex[:12]}"
        now = _utcnow()
        run = AutonomousMissionRun(
            id=run_id,
            mission_id=mission.id,
            project_id=mission.project_id,
            workflow_id=workflow_id,
            mission_type=mission.mission_type,
            trigger_type=trigger_type,
            status="running",
            current_stage="planning",
            started_at=now,
            updated_at=now,
        )
        previous_baseline = _latest_memory_baseline_for_mission(session, mission, exclude_run_id=run_id)
        current_baseline = _capture_memory_baseline_for_mission(mission)
        run.checkpoint = {
            "stage": "planning",
            "updated_at": now.isoformat(),
            "memory_baseline_before": current_baseline,
            "previous_memory_baseline": previous_baseline,
        }
        mission.status = "running"
        mission.health_status = "healthy"
        mission.paused_reason = None
        mission.current_stage = "planning"
        mission.next_action = "Planning the next mission iteration."
        mission.last_heartbeat_at = now
        mission.latest_workflow_id = workflow_id
        mission.latest_run_id = run_id
        mission.last_run_at = now
        mission.total_runs += 1
        mission.last_error = None
        mission.updated_at = now
        session.add(run)
        session.add(mission)
        session.commit()
        return run_id


def execute_mission_iteration(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one bounded autonomous mission iteration.

    The first implementation intentionally records internal, approval-gated
    findings from existing project truth. Follow-up activities can add direct
    AutoPilot, regression, and bug-report execution without changing workflow
    state semantics.
    """
    mission_id = payload["mission_id"]
    run_id = payload["run_id"]
    workflow_id = payload.get("workflow_id")

    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        run = session.get(AutonomousMissionRun, run_id)
        if not mission or not run:
            raise ValueError(f"Autonomous mission/run not found: {mission_id}/{run_id}")

        now = _utcnow()
        checkpoint = run.checkpoint
        checkpoint.update({"stage": "analyzing", "updated_at": now.isoformat()})
        run.current_stage = "analyzing"
        run.checkpoint = checkpoint
        run.updated_at = now
        mission.current_stage = "analyzing"
        mission.next_action = "Analyzing project coverage and prior findings."
        mission.last_heartbeat_at = now
        mission.health_status = "healthy"
        session.add(run)
        session.add(mission)
        session.commit()

        summary: dict[str, Any] = {
            "workflow_id": workflow_id,
            "mission_type": mission.mission_type,
            "target_urls": mission.target_urls,
            "findings_created": 0,
            "approvals_created": 0,
            "test_proposals_created": 0,
            "work_items_created": 0,
            "work_items_enqueued": 0,
            "work_items_completed": 0,
            "work_items_blocked": 0,
            "stale_recovered_count": 0,
            "notes": [],
        }

        if _whole_app_team_enabled(mission):
            _update_run_checkpoint(session, mission, run, "team_supervising")
            team_summary = _run_parallel_team_supervisor(session, mission, run)
            for key in (
                "work_items_created",
                "work_items_enqueued",
                "work_items_completed",
                "work_items_blocked",
                "stale_recovered_count",
            ):
                summary[key] += int(team_summary.get(key, 0) or 0)
            if team_summary.get("findings_created"):
                summary["findings_created"] += int(team_summary["findings_created"])
            summary["team"] = team_summary
            summary["notes"].append(
                f"Team supervisor active: {team_summary.get('active_count', 0)} active, "
                f"{team_summary.get('completed_count', 0)} completed, "
                f"{team_summary.get('blocked_count', 0)} blocked work item(s)."
            )

        if mission.mission_type in {"coverage", "mixed", "exploration"}:
            exploration_summary = _inspect_prior_mission_exploration(session, mission, run)
            summary["exploration"] = exploration_summary
            if exploration_summary.get("waiting"):
                summary["notes"].append(
                    f"Waiting for exploration session {exploration_summary.get('session_id')} to finish before computing memory delta."
                )
                return summary
            if exploration_summary.get("status") == "failed":
                summary["notes"].append(
                    f"Prior exploration session {exploration_summary.get('session_id')} failed; continuing with existing memory."
                )

            _update_run_checkpoint(session, mission, run, "memory_delta_review")
            memory_summary = _create_memory_delta_artifacts(session, mission, run)
            summary["memory_delta"] = memory_summary
            summary["findings_created"] += memory_summary["findings_created"]
            summary["test_proposals_created"] += memory_summary["test_proposals_created"]
            if memory_summary["change_count"]:
                summary["notes"].append(
                    f"Compared browser memory with the prior run and found {memory_summary['change_count']} changed item(s)."
                )
            else:
                summary["notes"].append("Browser memory did not change compared with the prior mission baseline.")

            _update_run_checkpoint(session, mission, run, "coverage_gap_review")
            coverage_summary = _create_coverage_gap_artifacts(session, mission, run)
            summary["findings_created"] += coverage_summary["findings_created"]
            summary["approvals_created"] += coverage_summary["approvals_created"]
            summary["test_proposals_created"] += coverage_summary["test_proposals_created"]
            if coverage_summary["test_proposals_created"]:
                summary["notes"].append(
                    f"Generated {coverage_summary['test_proposals_created']} pending test proposal(s) from coverage gaps."
                )
            else:
                summary["notes"].append("No unresolved coverage gaps were available for this project.")

            queued = _queue_mission_exploration(session, mission, run)
            summary["exploration"] = {**summary.get("exploration", {}), **queued}
            if queued.get("session_id"):
                summary["notes"].append(f"Queued exploration session {queued['session_id']} for the next memory comparison.")

        approved_finding_count = _create_proposals_for_approved_findings(session, mission, run)
        summary["test_proposals_created"] += approved_finding_count
        if approved_finding_count:
            summary["notes"].append(f"Generated {approved_finding_count} pending test proposal(s) from approved findings.")

        materialization_summary = _auto_materialize_low_risk_proposals(session, mission, run)
        summary["auto_materialization"] = materialization_summary
        if materialization_summary["materialized"]:
            summary["notes"].append(
                f"Auto-materialized {materialization_summary['materialized']} low-risk proposal(s) by mission policy."
            )
        if materialization_summary["validated"]:
            summary["notes"].append(
                f"Validated {materialization_summary['validated']} materialized proposal(s) after writing files."
            )

        if mission.mission_type in {"regression", "mixed"}:
            _update_run_checkpoint(session, mission, run, "regression_watch_ready")
            summary["notes"].append("Regression mission ledger is ready; existing batch execution can be attached as a next activity.")

        if mission.mission_type in {"flake_triage", "mixed"}:
            _update_run_checkpoint(session, mission, run, "flake_triage_ready")
            summary["notes"].append("Flake triage will use parsed Playwright JSON retries and historical TestExecutionHistory.")

        if mission.mission_type not in {"coverage", "exploration", "regression", "flake_triage", "mixed"}:
            summary["notes"].append(f"Unknown mission type '{mission.mission_type}' recorded without execution.")

        return summary


def _update_run_checkpoint(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    stage: str,
    extra: dict[str, Any] | None = None,
) -> None:
    now = _utcnow()
    checkpoint = run.checkpoint
    checkpoint.update({"stage": stage, "updated_at": now.isoformat()})
    if extra:
        checkpoint.update(extra)
    run.current_stage = stage
    run.checkpoint = checkpoint
    run.updated_at = now
    mission.current_stage = stage
    mission.last_heartbeat_at = now
    mission.next_action = _stage_next_action(stage)
    session.add(run)
    session.add(mission)
    session.commit()


def _stage_next_action(stage: str) -> str:
    return {
        "team_supervising": "Coordinating the autonomous agent team and collecting child results.",
        "exploration_queued": "Exploration is queued; the next mission iteration will compare the updated app memory.",
        "waiting_for_exploration": "Waiting for the queued exploration session to complete.",
        "memory_delta_review": "Comparing durable browser memory with the previous mission run.",
        "coverage_gap_review": "Reviewing unresolved coverage gaps for proposal candidates.",
        "regression_watch_ready": "Regression watch is ready for deeper execution hooks.",
        "flake_triage_ready": "Flake triage is ready for retry-history analysis.",
        "sleeping": "Waiting for the next scheduled mission run.",
    }.get(stage, f"Mission stage: {stage.replace('_', ' ')}.")


def _mission_exploration_enabled(mission: AutonomousMission) -> bool:
    config = mission.config or {}
    return bool(config.get("exploration_enabled", True))


def _prior_exploration_session(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
) -> ExplorationSession | None:
    runs = session.exec(
        select(AutonomousMissionRun)
        .where(AutonomousMissionRun.mission_id == mission.id)
        .where(AutonomousMissionRun.id != run.id)
        .order_by(col(AutonomousMissionRun.created_at).desc())
        .limit(8)
    ).all()
    for prior_run in runs:
        session_id = prior_run.checkpoint.get("exploration_session_id")
        if not session_id:
            continue
        exploration = session.get(ExplorationSession, session_id)
        if exploration:
            return exploration
    return None


def _inspect_prior_mission_exploration(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
) -> dict[str, Any]:
    if not _mission_exploration_enabled(mission):
        return {"enabled": False}
    prior = _prior_exploration_session(session, mission, run)
    if not prior:
        return {"enabled": True, "status": "none"}
    result = {
        "enabled": True,
        "session_id": prior.id,
        "status": prior.status,
        "completed_at": prior.completed_at.isoformat() if prior.completed_at else None,
        "pages_discovered": prior.pages_discovered,
        "flows_discovered": prior.flows_discovered,
    }
    if prior.status in {"pending", "queued", "running"}:
        _update_run_checkpoint(
            session,
            mission,
            run,
            "waiting_for_exploration",
            {"waiting_on_exploration_session_id": prior.id, "exploration_status": prior.status},
        )
        result["waiting"] = True
    return result


def _queue_mission_exploration(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
) -> dict[str, Any]:
    if not _mission_exploration_enabled(mission):
        return {"enabled": False, "queued": False}
    checkpoint = run.checkpoint
    existing_session_id = checkpoint.get("exploration_session_id")
    if existing_session_id:
        existing = session.get(ExplorationSession, existing_session_id)
        return {
            "enabled": True,
            "queued": False,
            "session_id": existing_session_id,
            "status": existing.status if existing else "unknown",
        }
    target_url = _default_target_url(mission)
    config = mission.config or {}
    session_id = f"autoexplore-{mission.id}-{run.id}"
    now = _utcnow()
    safety_policy = {
        "environment": str(config.get("environment") or "staging"),
        "allowed_domains": config.get("allowed_domains") or [],
        "allowed_routes": config.get("allowed_routes") or [],
        "blocked_routes": config.get("blocked_routes") or [],
        "read_only": bool(config.get("read_only", False)),
        "approval_required_for_risky_actions": True,
        "blocked_action_terms": config.get("blocked_action_terms") or [],
        "approval_required_terms": config.get("approval_required_terms") or [],
        "credential_scope": str(config.get("credential_scope") or "project"),
        "write_policy": str(config.get("write_policy") or "proposals_only"),
        "destructive_action_policy": str(config.get("destructive_action_policy") or "pause_for_approval"),
    }
    exploration = ExplorationSession(
        id=session_id,
        project_id=mission.project_id,
        entry_url=target_url,
        status="queued",
        strategy=str(config.get("exploration_strategy") or "goal_directed"),
        config_json=json.dumps(
            {
                "autonomous_mission_id": mission.id,
                "autonomous_run_id": run.id,
                "timeout_minutes": _config_int(config, "exploration_timeout_minutes", min(mission.max_runtime_minutes, 30)),
                "max_interactions": _config_int(config, "max_interactions", 50),
                "max_depth": _config_int(config, "max_depth", 10),
                "focus_areas": config.get("focus_areas") or [],
                "exclude_patterns": config.get("exclude_patterns") or [],
                "safety_policy": safety_policy,
            }
        ),
        created_at=now,
    )
    session.add(exploration)
    checkpoint["exploration_session_id"] = session_id
    checkpoint["exploration_status"] = "queued"
    run.checkpoint = checkpoint
    session.add(run)
    session.commit()

    try:
        from orchestrator.api.exploration import ExplorationStartRequest, launch_exploration_background

        request = ExplorationStartRequest(
            entry_url=target_url,
            project_id=mission.project_id or "default",
            strategy=exploration.strategy,
            max_interactions=_config_int(config, "max_interactions", 50),
            max_depth=_config_int(config, "max_depth", 10),
            timeout_minutes=_config_int(config, "exploration_timeout_minutes", min(mission.max_runtime_minutes, 30)),
            exclude_patterns=[str(item) for item in config.get("exclude_patterns", [])],
            focus_areas=[str(item) for item in config.get("focus_areas", [])],
            additional_instructions=str(config.get("exploration_instructions") or ""),
            safety_policy=safety_policy,
        )
        launch_exploration_background(session_id, request, user_key=f"autonomous:{mission.id}", track=False)
        _update_run_checkpoint(
            session,
            mission,
            run,
            "exploration_queued",
            {"exploration_session_id": session_id, "exploration_status": "queued"},
        )
    except Exception as exc:
        exploration.status = "failed"
        exploration.error_message = f"Unable to launch autonomous exploration: {exc}"
        exploration.completed_at = _utcnow()
        checkpoint = run.checkpoint
        checkpoint["exploration_status"] = "failed"
        checkpoint["exploration_error"] = str(exc)
        run.checkpoint = checkpoint
        session.add(exploration)
        session.add(run)
        session.commit()
        logger.warning("Unable to launch autonomous exploration %s: %s", session_id, exc)
        return {"enabled": True, "queued": False, "session_id": session_id, "status": "failed", "error": str(exc)}

    return {"enabled": True, "queued": True, "session_id": session_id, "status": "queued"}


def _capture_memory_baseline_for_mission(mission: AutonomousMission) -> dict[str, Any] | None:
    try:
        from orchestrator.memory.browser_memory import get_exploration_memory_service

        limit = max(25, min(_config_int(mission.config, "memory_baseline_limit", 500), 2000))
        return get_exploration_memory_service(project_id=mission.project_id or "default").capture_memory_baseline(
            limit=limit
        )
    except Exception as exc:
        logger.debug("Unable to capture browser memory baseline for mission %s: %s", mission.id, exc)
        return None


def _latest_memory_baseline_for_mission(
    session: Session,
    mission: AutonomousMission,
    *,
    exclude_run_id: str | None = None,
) -> dict[str, Any] | None:
    statement = (
        select(AutonomousMissionRun)
        .where(AutonomousMissionRun.mission_id == mission.id)
        .order_by(col(AutonomousMissionRun.created_at).desc())
        .limit(10)
    )
    for prior_run in session.exec(statement).all():
        if prior_run.id == exclude_run_id:
            continue
        checkpoint = prior_run.checkpoint
        baseline = checkpoint.get("memory_baseline_after") or checkpoint.get("memory_baseline_before")
        if isinstance(baseline, dict) and baseline.get("states") is not None:
            return baseline
    return None


def _create_memory_delta_artifacts(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "change_count": 0,
        "findings_created": 0,
        "test_proposals_created": 0,
        "delta_summary": {},
        "has_previous_baseline": False,
    }
    checkpoint = run.checkpoint
    previous_baseline = checkpoint.get("previous_memory_baseline") or _latest_memory_baseline_for_mission(
        session, mission, exclude_run_id=run.id
    )
    current_baseline = _capture_memory_baseline_for_mission(mission)
    checkpoint["memory_baseline_after"] = current_baseline

    if not previous_baseline or not current_baseline:
        checkpoint["memory_delta"] = {"summary": summary["delta_summary"], "reason": "missing_baseline"}
        run.checkpoint = checkpoint
        session.add(run)
        session.commit()
        return summary

    try:
        from orchestrator.memory.browser_memory import get_exploration_memory_service

        delta = get_exploration_memory_service(project_id=mission.project_id or "default").compute_memory_delta(
            baseline=previous_baseline,
            limit=max(25, min(_config_int(mission.config, "memory_baseline_limit", 500), 2000)),
        )
    except Exception as exc:
        logger.debug("Unable to compute browser memory delta for mission %s: %s", mission.id, exc)
        checkpoint["memory_delta"] = {"summary": summary["delta_summary"], "error": str(exc)}
        run.checkpoint = checkpoint
        session.add(run)
        session.commit()
        return summary

    delta_summary = delta.get("summary") or {}
    change_count = sum(
        int(delta_summary.get(key, 0) or 0)
        for key in (
            "new_page_states",
            "changed_page_states",
            "removed_page_states",
            "new_elements",
            "changed_elements",
            "removed_elements",
            "locator_drift",
        )
    )
    summary["change_count"] = change_count
    summary["delta_summary"] = delta_summary
    summary["has_previous_baseline"] = True
    checkpoint["memory_delta"] = delta
    run.checkpoint = checkpoint
    session.add(run)

    if change_count:
        created, proposals = _create_findings_from_memory_delta(session, mission, run, delta)
        summary["findings_created"] = created
        summary["test_proposals_created"] = proposals
        if created:
            mission.total_findings += created
            session.add(mission)
    session.commit()
    return summary


def _create_findings_from_memory_delta(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    delta: dict[str, Any],
) -> tuple[int, int]:
    candidates = _memory_delta_finding_candidates(delta)[:MAX_PROPOSALS_PER_ITERATION]
    created = 0
    proposals = 0
    now = _utcnow()
    for candidate in candidates:
        raw_key = "|".join(
            [
                str(mission.project_id or "default"),
                "memory_delta",
                str(candidate.get("kind")),
                str(candidate.get("page_key") or candidate.get("element_key") or ""),
                str(candidate.get("signature") or ""),
            ]
        )
        dedupe_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:32]
        existing = session.exec(
            select(AutonomousFinding).where(
                AutonomousFinding.project_id == mission.project_id,
                AutonomousFinding.dedupe_key == dedupe_key,
            )
        ).first()
        if existing:
            continue

        finding = AutonomousFinding(
            id=f"amfind-{uuid.uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            finding_type="memory_delta",
            severity=candidate.get("risk_level") or candidate.get("severity", "medium"),
            title=candidate["title"],
            description=candidate["description"],
            status="awaiting_approval",
            confidence=float(candidate.get("confidence", 0.78) or 0.78),
            dedupe_key=dedupe_key,
            evidence_json=json.dumps(candidate),
            source_type="browser_memory_delta",
            source_id=str(candidate.get("page_key") or candidate.get("element_key") or run.id),
            approval_required=True,
            created_at=now,
            updated_at=now,
        )
        session.add(finding)
        created += 1
        proposal = _create_test_proposal(
            session,
            mission,
            run,
            source_type="memory_delta",
            source_id=dedupe_key,
            title=candidate["title"],
            rationale=candidate["description"],
            target_url=candidate.get("url") or _default_target_url(mission),
            risk_level=candidate.get("severity", "medium"),
            finding_id=finding.id,
            source_metadata={"memory_delta": candidate},
        )
        if proposal:
            proposals += 1
    return created, proposals


def _memory_delta_finding_candidates(delta: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    page_states = delta.get("page_states") or {}
    for item in page_states.get("new", []) or []:
        current = item.get("current") or {}
        candidates.append(_classified_memory_delta_candidate(
            {
                "kind": "new_page_state",
                "page_key": item.get("page_key"),
                "signature": current.get("state_key"),
                "url": current.get("url"),
                "title": f"New app surface discovered: {current.get('url') or item.get('page_key')}",
                "description": "Browser memory discovered a page state that was not present in the previous mission baseline.",
                "current": current,
            }
        ))
    for item in page_states.get("changed", []) or []:
        current = item.get("current") or {}
        candidates.append(_classified_memory_delta_candidate(
            {
                "kind": "changed_page_state",
                "page_key": item.get("page_key"),
                "signature": current.get("state_key") or current.get("exact_hash"),
                "url": current.get("url"),
                "title": f"Known app surface changed: {current.get('url') or item.get('page_key')}",
                "description": "Browser memory detected a changed page state. Review whether existing coverage should be updated.",
                "changed_fields": item.get("changed_fields") or {},
                "baseline": item.get("baseline") or {},
                "current": current,
            }
        ))
    for item in page_states.get("removed", []) or []:
        baseline = item.get("baseline") or {}
        candidates.append(_classified_memory_delta_candidate(
            {
                "kind": "removed_page_state",
                "page_key": item.get("page_key"),
                "signature": baseline.get("state_key") or baseline.get("exact_hash"),
                "url": baseline.get("url"),
                "title": f"Previously known app surface disappeared: {baseline.get('url') or item.get('page_key')}",
                "description": "Browser memory no longer sees a page state from the previous mission baseline.",
                "baseline": baseline,
            }
        ))
    elements = delta.get("elements") or {}
    for bucket, kind in (
        ("new", "new_element"),
        ("changed", "changed_element"),
        ("removed", "removed_element"),
    ):
        for item in elements.get(bucket, []) or []:
            current = item.get("current") or {}
            baseline = item.get("baseline") or {}
            element = current or baseline
            candidates.append(_classified_memory_delta_candidate(
                {
                    "kind": kind,
                    "element_key": item.get("element_key") or element.get("logical_key") or element.get("id"),
                    "signature": element.get("locator_signature") or element.get("logical_key"),
                    "url": element.get("state_url"),
                    "title": _element_change_title(kind, element),
                    "description": _element_change_description(kind),
                    "changed_fields": item.get("changed_fields") or {},
                    "baseline": baseline,
                    "current": current,
                }
            ))
    for item in (delta.get("elements") or {}).get("locator_drift", []) or []:
        current = item.get("current") or {}
        candidates.append(_classified_memory_delta_candidate(
            {
                "kind": "locator_drift",
                "element_key": current.get("logical_key") or current.get("id"),
                "signature": current.get("locator_signature"),
                "url": current.get("state_url"),
                "title": f"Locator drift detected for {current.get('name') or current.get('role') or 'element'}",
                "description": "Browser memory detected that the best locator changed or became less stable.",
                "drift": item.get("drift") or {},
                "baseline": item.get("baseline") or {},
                "current": current,
            }
        ))
    severity_order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    return sorted(candidates, key=lambda item: severity_order.get(str(item.get("risk_level")), 9))


def _classified_memory_delta_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    kind = str(candidate.get("kind") or "memory_delta")
    mapping = {
        "new_page_state": ("new_page", "medium", "coverage_gap_candidate", 0.82),
        "changed_page_state": ("changed_page", "high", "regression_candidate", 0.84),
        "removed_page_state": ("removed_page", "medium", "regression_candidate", 0.76),
        "new_element": ("new_element", "medium", "coverage_gap_candidate", 0.78),
        "changed_element": ("changed_element", "medium", "regression_candidate", 0.78),
        "removed_element": ("removed_element", "medium", "regression_candidate", 0.72),
        "locator_drift": ("locator_drift", "medium", "selector_maintenance", 0.86),
    }
    change_type, risk_level, test_value, confidence = mapping.get(kind, ("memory_delta", "low", "informational", 0.7))
    uncertainty_reason = None
    if confidence < 0.8:
        uncertainty_reason = "Review needed because browser memory changed, but intended product behavior is not confirmed."
    if change_type == "removed_page":
        uncertainty_reason = "The page may be intentionally removed, gated by auth, or unreachable during this run."
    if change_type == "removed_element":
        uncertainty_reason = "The element may be intentionally removed, hidden by state, or renamed."

    candidate["change_type"] = change_type
    candidate["risk_level"] = risk_level
    candidate["severity"] = risk_level
    candidate["test_value"] = test_value
    candidate["confidence"] = confidence
    candidate["uncertainty_reason"] = uncertainty_reason
    return candidate


def _element_change_title(kind: str, element: dict[str, Any]) -> str:
    label = element.get("name") or element.get("role") or element.get("logical_key") or "element"
    if kind == "new_element":
        return f"New interactive element discovered: {label}"
    if kind == "removed_element":
        return f"Previously known element disappeared: {label}"
    return f"Known element changed: {label}"


def _element_change_description(kind: str) -> str:
    if kind == "new_element":
        return "Browser memory discovered an element that was not present in the previous mission baseline."
    if kind == "removed_element":
        return "Browser memory no longer sees an element from the previous mission baseline."
    return "Browser memory detected changed element attributes. Review whether coverage or selectors should be updated."


def _whole_app_team_enabled(mission: AutonomousMission) -> bool:
    config = mission.config or {}
    return bool(
        config.get("whole_app_team")
        or config.get("team_mode") == "whole_app"
        or config.get("mission_template") == "whole_app_team"
    )


def _team_roles(mission: AutonomousMission) -> list[str]:
    config = mission.config or {}
    roles = config.get("roles")
    if isinstance(roles, list):
        selected = [str(role).strip() for role in roles if str(role).strip()]
        if selected:
            return selected[:12]
    return list(WHOLE_APP_TEAM_ROLES)


def _max_parallel_agents(mission: AutonomousMission) -> int:
    configured = _config_int(mission.config, "max_parallel_agents", DEFAULT_MAX_PARALLEL_AGENTS)
    global_limit = DEFAULT_MAX_PARALLEL_AGENTS
    try:
        with Session(engine) as session:
            settings = session.get(ExecutionSettings, 1)
            if settings:
                global_limit = settings.parallelism
    except Exception as exc:
        logger.debug("Failed to read execution settings for autonomous parallelism: %s", exc)
    return max(1, min(configured, global_limit, 12))


def _run_parallel_team_supervisor(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
) -> dict[str, Any]:
    summary = {
        "roles": _team_roles(mission),
        "max_parallel_agents": _max_parallel_agents(mission),
        "work_items_created": 0,
        "work_items_enqueued": 0,
        "work_items_completed": 0,
        "work_items_blocked": 0,
        "stale_recovered_count": 0,
        "findings_created": 0,
        "planner_created": 0,
        "active_count": 0,
        "completed_count": 0,
        "blocked_count": 0,
    }
    summary["work_items_completed"] = _sync_agent_work_items(session, mission)
    summary["stale_recovered_count"] = _recover_stale_work_items(session, mission, run)
    summary["work_items_created"] += summary["stale_recovered_count"]
    if summary["work_items_completed"]:
        summary["findings_created"] = _create_findings_from_completed_work_items(session, mission, run)
    summary["planner_created"] = _plan_whole_app_work_items(session, mission, run)
    summary["work_items_created"] += summary["planner_created"]

    existing = session.exec(
        select(AutonomousAgentWorkItem).where(AutonomousAgentWorkItem.mission_id == mission.id)
    ).all()
    if not existing:
        for index, role in enumerate(summary["roles"]):
            item = AutonomousAgentWorkItem(
                id=f"amwork-{uuid.uuid4().hex[:12]}",
                mission_id=mission.id,
                run_id=run.id,
                project_id=mission.project_id,
                role=role,
                objective=_role_objective(role, mission),
                assigned_surface_json=json.dumps(_role_surface(role, mission)),
                status="queued",
                priority=10 + index,
                planner_key=f"bootstrap:{role}",
            )
            item.progress = {
                "phase": "created",
                "message": "Waiting for an available agent worker.",
                "planner_key": item.planner_key,
            }
            session.add(item)
            summary["work_items_created"] += 1
        session.commit()

    running_count = _count_work_items(session, mission.id, {"running"})
    available_slots = max(0, summary["max_parallel_agents"] - running_count)
    if available_slots:
        queued_candidates = session.exec(
            select(AutonomousAgentWorkItem)
            .where(
                AutonomousAgentWorkItem.mission_id == mission.id,
                AutonomousAgentWorkItem.status == "queued",
                AutonomousAgentWorkItem.agent_task_id == None,  # noqa: E711
            )
            .order_by(col(AutonomousAgentWorkItem.priority).asc(), col(AutonomousAgentWorkItem.created_at).asc())
        ).all()
        pending = sorted(queued_candidates, key=_queued_work_item_sort_key)[: min(DEFAULT_WORK_ITEM_BATCH_SIZE, available_slots)]
        for item in pending:
            if _enqueue_agent_work_item(session, mission, item):
                summary["work_items_enqueued"] += 1
            else:
                summary["work_items_blocked"] += 1

    summary["active_count"] = _count_work_items(session, mission.id, WORK_ITEM_ACTIVE_STATUSES)
    summary["running_count"] = _count_work_items(session, mission.id, {"running"})
    summary["completed_count"] = _count_work_items(session, mission.id, {"completed"})
    summary["blocked_count"] = _count_work_items(session, mission.id, {"blocked", "failed"})
    _update_mission_team_progress(session, mission)
    return summary


def _recover_stale_work_items(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
) -> int:
    now = _utcnow()
    stale_after = now - timedelta(
        minutes=max(5, _config_int(mission.config, "work_item_stale_minutes", DEFAULT_WORK_ITEM_STALE_MINUTES))
    )
    running_items = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission.id,
            AutonomousAgentWorkItem.status == "running",
        )
    ).all()
    created = 0
    for item in running_items:
        if not _work_item_is_stale(item, now=now, stale_after=stale_after):
            continue
        task_state = _agent_task_recovery_state(str(item.agent_task_id or ""))
        if task_state in {"running", "paused"}:
            item.lease_until = now + timedelta(minutes=30)
            item.last_heartbeat_at = now
            item.updated_at = now
            session.add(item)
            continue
        if _active_recovery_work_item_exists(session, mission.id, item.id):
            continue
        reason = task_state if task_state != "unknown" else _stale_work_item_reason(item, now=now, stale_after=stale_after)
        replacement = _create_recovery_work_item(session, mission, run, item, reason=reason)
        if not replacement:
            continue
        item.status = "failed"
        item.error_message = f"Recovered stale autonomous work item: {reason}"
        item.completed_at = now
        item.updated_at = now
        item.recovery_reason = reason
        item.progress = {
            **item.progress,
            "phase": "recovered",
            "message": item.error_message,
            "recovery_reason": reason,
            "recovery_work_item_id": replacement.id,
        }
        item.result = {
            **item.result,
            "recovery_reason": reason,
            "recovery_work_item_id": replacement.id,
            "recovered_at": now.isoformat(),
        }
        session.add(item)
        emit_work_item_status_event(item, item.error_message, event_type="error")
        created += 1
    if created:
        session.commit()
    return created


def _work_item_is_stale(item: AutonomousAgentWorkItem, *, now: datetime, stale_after: datetime) -> bool:
    if item.lease_until and item.lease_until <= now:
        return True
    if item.last_heartbeat_at and item.last_heartbeat_at <= stale_after:
        return True
    if not item.last_heartbeat_at and item.updated_at <= stale_after:
        return True
    return False


def _stale_work_item_reason(item: AutonomousAgentWorkItem, *, now: datetime, stale_after: datetime) -> str:
    if item.lease_until and item.lease_until <= now:
        return "lease_expired"
    if item.last_heartbeat_at and item.last_heartbeat_at <= stale_after:
        return "heartbeat_stale"
    return "updated_at_stale"


def _agent_task_recovery_state(task_id: str) -> str:
    if not task_id:
        return "missing_agent_task"
    try:
        from orchestrator.services.agent_queue import AgentTaskStatus, get_agent_queue

        async def _load() -> str:
            queue = get_agent_queue()
            await queue.connect()
            try:
                task = await queue.get_task(task_id)
            finally:
                await queue.disconnect()
            if not task:
                return "missing_agent_task"
            if task.status == AgentTaskStatus.COMPLETED:
                return "completed_out_of_band"
            if task.status == AgentTaskStatus.FAILED:
                return "agent_task_failed"
            if task.status == AgentTaskStatus.TIMEOUT:
                return "agent_task_timeout"
            if task.status == AgentTaskStatus.CANCELLED:
                return "agent_task_cancelled"
            if task.status == AgentTaskStatus.PAUSED:
                return "paused"
            return "running"

        return asyncio.run(_load())
    except Exception:
        logger.debug("Unable to inspect agent task %s during recovery.", task_id, exc_info=True)
        return "unknown"


def _active_recovery_work_item_exists(session: Session, mission_id: str, stale_item_id: str) -> bool:
    items = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission_id,
            col(AutonomousAgentWorkItem.status).in_(("queued", "running")),
        )
    ).all()
    return any((item.progress or {}).get("recovered_from_work_item_id") == stale_item_id for item in items)


def _create_recovery_work_item(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    stale_item: AutonomousAgentWorkItem,
    *,
    reason: str,
) -> AutonomousAgentWorkItem | None:
    progress = stale_item.progress or {}
    recovery_count = int(stale_item.recovery_count or progress.get("recovery_count") or 0) + 1
    replacement = AutonomousAgentWorkItem(
        id=f"amwork-{uuid.uuid4().hex[:12]}",
        mission_id=mission.id,
        run_id=run.id,
        project_id=mission.project_id,
        role=stale_item.role,
        planner_key=stale_item.planner_key or progress.get("planner_key"),
        objective=stale_item.objective,
        assigned_surface_json=stale_item.assigned_surface_json,
        status="queued",
        priority=max(1, int(stale_item.priority or 50) - 1),
        recovery_count=recovery_count,
        recovery_reason=reason,
    )
    replacement.progress = {
        **progress,
        "phase": "created",
        "message": "Recovered from a stale autonomous work item.",
        "planner_key": replacement.planner_key,
        "recovered_from_work_item_id": stale_item.id,
        "recovery_reason": reason,
        "recovery_count": recovery_count,
    }
    session.add(replacement)
    return replacement


def _plan_whole_app_work_items(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
) -> int:
    """Create bounded, idempotent work items from canonical app state."""
    config = mission.config or {}
    limit = max(1, min(_config_int(config, "planner_batch_size", DEFAULT_WORK_ITEM_BATCH_SIZE), 20))
    created = 0

    requirements = session.exec(
        select(Requirement)
        .where(Requirement.project_id == mission.project_id)
        .order_by(col(Requirement.updated_at).desc())
        .limit(100)
    ).all()
    for requirement in requirements:
        if created >= limit:
            break
        if requirement.id is None or _requirement_truth_state(requirement) == "rejected_requirement":
            continue
        mappings = session.exec(
            select(RtmEntry).where(
                RtmEntry.project_id == mission.project_id,
                RtmEntry.requirement_id == requirement.id,
            )
        ).all()
        if any(entry.mapping_type == "full" for entry in mappings):
            continue
        planner_key = f"rtm_gap:{requirement.id}:{requirement.canonical_key or requirement.req_code}"
        if _planner_work_item_exists(session, mission.id, planner_key):
            continue
        objective = (
            f"Close RTM coverage for {requirement.req_code}: {requirement.title}. "
            "Inspect existing specs and propose missing automated coverage without writing files."
        )
        if _create_planned_work_item(
            session,
            mission,
            run,
            planner_key=planner_key,
            role="spec_writer",
            objective=objective,
            priority=18,
            surfaces=[],
            metadata={"requirement_id": requirement.id, "requirement_code": requirement.req_code},
        ):
            created += 1

    findings = session.exec(
        select(AutonomousFinding)
        .where(
            AutonomousFinding.project_id == mission.project_id,
            col(AutonomousFinding.status).in_(("open", "awaiting_approval", "approved")),
        )
        .order_by(col(AutonomousFinding.updated_at).desc())
        .limit(50)
    ).all()
    for finding in findings:
        if created >= limit:
            break
        planner_key = f"finding_followup:{finding.id}:{finding.dedupe_key}"
        if _planner_work_item_exists(session, mission.id, planner_key):
            continue
        evidence = finding.evidence
        objective = (
            f"Review finding '{finding.title}' and map it to affected routes, requirements, and a regression proposal. "
            "Do not duplicate existing proposals."
        )
        if _create_planned_work_item(
            session,
            mission,
            run,
            planner_key=planner_key,
            role="regression_scout",
            objective=objective,
            priority=24 if finding.severity in {"critical", "high"} else 34,
            surfaces=[str(evidence.get("target_url") or evidence.get("url") or "")],
            metadata={"finding_id": finding.id, "finding_type": finding.finding_type},
        ):
            created += 1

    for frontier in _frontier_planner_items(session, mission, limit=max(0, limit - created)):
        if created >= limit:
            break
        frontier_id = str(frontier.get("id") or "")
        if not frontier_id:
            continue
        planner_key = f"frontier:{frontier_id}"
        if _planner_work_item_exists(session, mission.id, planner_key):
            continue
        url = str(frontier.get("url") or frontier.get("state_url") or frontier.get("url_template") or "")
        action = str(frontier.get("action_type") or frontier.get("action") or "explore")
        objective = (
            f"Explore browser-memory frontier item {frontier_id}: {action}. "
            "Record app map updates, requirements, bugs, and test proposals as structured JSON."
        )
        if _create_planned_work_item(
            session,
            mission,
            run,
            planner_key=planner_key,
            role="explorer",
            objective=objective,
            priority=28,
            surfaces=[url] if url else mission.target_urls,
            metadata={"frontier_item": frontier},
        ):
            created += 1

    if created:
        session.commit()
    return created


def _planner_work_item_exists(session: Session, mission_id: str, planner_key: str) -> bool:
    if not planner_key:
        return False
    direct = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission_id,
            AutonomousAgentWorkItem.planner_key == planner_key,
        )
    ).first()
    if direct:
        return True
    candidates = session.exec(select(AutonomousAgentWorkItem).where(AutonomousAgentWorkItem.mission_id == mission_id)).all()
    return any((candidate.progress or {}).get("planner_key") == planner_key for candidate in candidates)


def _create_planned_work_item(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    *,
    planner_key: str,
    role: str,
    objective: str,
    priority: int,
    surfaces: list[str],
    metadata: dict[str, Any],
) -> AutonomousAgentWorkItem | None:
    item = AutonomousAgentWorkItem(
        id=f"amwork-{uuid.uuid4().hex[:12]}",
        mission_id=mission.id,
        run_id=run.id,
        project_id=mission.project_id,
        role=role,
        planner_key=planner_key,
        objective=objective,
        assigned_surface_json=json.dumps([surface for surface in surfaces if surface]),
        status="queued",
        priority=priority,
    )
    item.progress = {
        "phase": "created",
        "message": "Planner created this work item from canonical app state.",
        "planner_key": planner_key,
        **metadata,
    }
    session.add(item)
    return item


def _frontier_planner_items(session: Session, mission: AutonomousMission, *, limit: int) -> list[dict[str, Any]]:
    if limit <= 0 or not mission.project_id:
        return []
    try:
        from orchestrator.memory.browser_memory import get_exploration_memory_service

        service = get_exploration_memory_service(session=session, project_id=mission.project_id)
        return service.get_frontier_work(
            query=" ".join(mission.target_urls or []),
            limit=limit,
            risk_max=str((mission.config or {}).get("frontier_risk_max") or "medium"),
            db=session,
        )
    except Exception:
        logger.debug("Unable to load browser frontier work for autonomous planner.", exc_info=True)
        return []


def _count_work_items(session: Session, mission_id: str, statuses: set[str]) -> int:
    if not statuses:
        return 0
    return len(
        session.exec(
            select(AutonomousAgentWorkItem).where(
                AutonomousAgentWorkItem.mission_id == mission_id,
                col(AutonomousAgentWorkItem.status).in_(tuple(statuses)),
            )
        ).all()
    )


def _role_surface(role: str, mission: AutonomousMission) -> list[str]:
    target_urls = mission.target_urls or ["http://localhost:3000"]
    if role in {"requirements_analyst", "rtm_mapper", "spec_writer", "flake_triager"}:
        return []
    return target_urls


def _role_objective(role: str, mission: AutonomousMission) -> str:
    target_text = ", ".join(mission.target_urls or ["the configured application"])
    objectives = {
        "surface_mapper": f"Map the reachable web application surface for {target_text}: routes, menus, forms, auth boundaries, and major flows.",
        "explorer": f"Explore high-value user journeys in {target_text}, looking for broken flows, missing states, and untested paths.",
        "requirements_analyst": "Write or refine functional requirements from exploration evidence, grouped by feature and priority.",
        "rtm_mapper": "Map requirements to existing specs/tests and identify critical RTM gaps that need proposals.",
        "spec_writer": "Draft approval-gated test specs for the highest-value uncovered requirements without writing repository files.",
        "regression_scout": "Review recent runs and important app paths to propose recurring regression coverage.",
        "flake_triager": "Review unstable or timing-sensitive tests and propose flake triage findings.",
    }
    return objectives.get(role, f"Perform autonomous QA work for role {role} on {target_text}.")


def _agent_prompt_for_work_item(mission: AutonomousMission, item: AutonomousAgentWorkItem) -> str:
    surfaces = item.assigned_surface or mission.target_urls
    revision_context = item.progress or {}
    context_bundle = _work_item_context_bundle(mission, item)
    context_note = ""
    if context_bundle:
        context_note = f"""
Canonical context bundle:
{_compact_json(context_bundle, max_chars=7000)}
"""
    revision_note = ""
    if revision_context.get("revision_of_work_item_id"):
        revision_note = f"""
Revision request:
- revise work item: {revision_context.get("revision_of_work_item_id")}
- reviewer work item: {revision_context.get("reviewer_work_item_id") or 'human/manual review'}
- reviewer reason: {revision_context.get("review_reason") or 'No reason provided'}
- revision attempt: {revision_context.get("revision_attempt") or 1}
Address the reviewer feedback directly and explain what changed from the prior output.
"""
    hermes_note = ""
    if str((mission.config or {}).get("runtime") or "").lower() in {"hermes", "hermes-agent", "hermes_agent"}:
        max_children = _config_int(mission.config, "hermes_max_concurrent_children", 3)
        max_depth = _config_int(mission.config, "hermes_max_spawn_depth", 1)
        hermes_note = f"""
Hermes delegation policy:
- You may delegate bounded subtasks to subagents when it improves coverage or parallelism.
- Give each subagent all context it needs; subagents do not inherit this full prompt automatically.
- Use at most {max_children} concurrent child agents and do not exceed delegation depth {max_depth}.
- Aggregate subagent findings into the required final JSON shape.
"""
    return f"""You are the {item.role} agent in a Quorvex autonomous QA team.

Mission: {mission.name}
Objective: {item.objective}
Target surfaces: {', '.join(surfaces or ['project data and known app artifacts'])}
{context_note}
{revision_note}
{hermes_note}

Work only by inspecting the app/project through available tools. Do not write repository files.
Return JSON only, preferably in a ```json fenced block, with this exact top-level shape:
{{
  "summary": "short factual summary",
  "requirements": [
    {{
      "title": "requirement title",
      "description": "what the product should do",
      "category": "authentication|navigation|crud|validation|checkout|other",
      "priority": "low|medium|high|critical",
      "acceptance_criteria": ["observable criterion"],
      "truth_state": "candidate_requirement",
      "confidence": 0.0,
      "uncertainty_reason": "why this is candidate/uncertain"
    }}
  ],
  "rtm_candidates": [
    {{
      "requirement_id": 0,
      "requirement_code": "REQ-001",
      "test_spec_name": "existing-or-proposed spec name",
      "test_spec_path": "path if known",
      "mapping_type": "full|partial|suggested",
      "confidence": 0.0,
      "coverage_notes": "covered behavior",
      "gap_notes": "remaining gap",
      "allow_candidate": false
    }}
  ],
  "test_proposals": [
    {{
      "title": "test proposal title",
      "rationale": "why this test matters",
      "target_url": "absolute URL if known",
      "route": "/route if known",
      "test_type": "e2e|api|regression|security|accessibility|unit",
      "risk_level": "low|medium|high|critical",
      "requirement_ids": []
    }}
  ],
  "bugs": [
    {{
      "title": "bug title",
      "description": "observed problem",
      "severity": "low|medium|high|critical",
      "target_url": "absolute URL if known",
      "route": "/route if known",
      "action": "user action",
      "observed_failure": "what happened",
      "expected_behavior": "what should happen",
      "evidence": {{}}
    }}
  ],
  "app_map_updates": [
    {{
      "url": "absolute URL",
      "page_title": "page title",
      "linked_urls": [],
      "elements": {{}},
      "forms": [],
      "api_endpoints": []
    }}
  ],
  "blockers": []
}}

Every proposed file or repository change must be a proposal only. The human approval flow will materialize files later.
"""


def _work_item_context_bundle(mission: AutonomousMission, item: AutonomousAgentWorkItem) -> dict[str, Any]:
    bundle: dict[str, Any] = {}
    try:
        from orchestrator.memory.unified import get_unified_memory_service

        bundle["memory"] = get_unified_memory_service().build_bundle(
            query=item.objective,
            project_id=mission.project_id,
            agent_type=item.role,
            limit=8,
            include_review_required=True,
            include_usage=False,
        )
    except Exception:
        logger.debug("Unable to build autonomous work item memory context.", exc_info=True)

    try:
        requirements = []
        with Session(engine) as context_session:
            for requirement in context_session.exec(
                select(Requirement)
                .where(Requirement.project_id == mission.project_id)
                .order_by(col(Requirement.updated_at).desc())
                .limit(12)
            ).all():
                requirements.append(
                    {
                        "id": requirement.id,
                        "req_code": requirement.req_code,
                        "title": requirement.title,
                        "truth_state": _requirement_truth_state(requirement),
                        "priority": requirement.priority,
                    }
                )
            open_proposals = context_session.exec(
                select(AutonomousTestProposal)
                .where(
                    AutonomousTestProposal.project_id == mission.project_id,
                    col(AutonomousTestProposal.approval_status).in_(("pending", "approved", "materialized")),
                )
                .order_by(col(AutonomousTestProposal.updated_at).desc())
                .limit(12)
            ).all()
            bundle["canonical"] = {
                "requirements": requirements,
                "active_test_proposals": [
                    {
                        "id": proposal.id,
                        "title": proposal.title,
                        "status": proposal.approval_status,
                        "validation_status": proposal.validation_status,
                        "path": proposal.materialized_file_path or proposal.suggested_file_path,
                    }
                    for proposal in open_proposals
                ],
            }
    except Exception:
        logger.debug("Unable to build autonomous canonical context.", exc_info=True)
    return bundle


def _compact_json(value: Any, *, max_chars: int) -> str:
    text = json.dumps(value, default=str, sort_keys=True)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _allowed_tools_for_work_item(
    item: AutonomousAgentWorkItem,
    *,
    mcp_config_dir: Path | str | None = None,
) -> list[str]:
    try:
        from orchestrator.utils.agent_tool_allowlists import get_agent_allowed_tools

        allowed = get_agent_allowed_tools(item.role, mcp_config_dir=mcp_config_dir)
        if allowed:
            return allowed
    except Exception:
        logger.debug("Could not resolve autonomous role tool profile for %s", item.role, exc_info=True)
    return ["Glob", "Grep", "Read", "LS"]


def _short_tool_name(tool_name: str | None) -> str:
    if not tool_name:
        return "tool"
    text = str(tool_name)
    if "__" in text:
        return text.split("__")[-1]
    return text


def _is_browser_tool(tool_name: str | None) -> bool:
    short_name = _short_tool_name(tool_name)
    text = str(tool_name or "")
    return short_name.startswith("browser_") or "__browser_" in text


def _autonomous_work_item_run_dir(mission: AutonomousMission, item: AutonomousAgentWorkItem) -> Path:
    return RUNS_DIR / "autonomous" / mission.id / item.id


def _prepare_autonomous_work_item_runtime(mission: AutonomousMission, item: AutonomousAgentWorkItem) -> tuple[Path, dict[str, Any]]:
    run_dir = _autonomous_work_item_run_dir(mission, item)
    run_dir.mkdir(parents=True, exist_ok=True)
    runtime: dict[str, Any] = {}
    try:
        from orchestrator.utils.playwright_mcp import browser_runtime_status, write_playwright_mcp_config

        mission_config = mission.config
        storage_state_path = None
        if mission_config.get("browser_auth_session_id") or mission_config.get("use_project_default_browser_auth"):
            try:
                with Session(engine) as db_session:
                    resolved = resolve_browser_auth_for_run(
                        db_session,
                        mission.project_id,
                        run_dir=run_dir,
                        browser_auth_session_id=mission_config.get("browser_auth_session_id"),
                        use_default=bool(mission_config.get("use_project_default_browser_auth")),
                    )
                storage_state_path = resolved.storage_state_path if resolved else None
            except BrowserAuthSessionError as exc:
                raise RuntimeError(f"{exc}. Refresh browser auth session.") from exc
        write_playwright_mcp_config(
            run_dir=run_dir,
            server_name="playwright",
            project_root=REPOSITORY_ROOT,
            storage_state_path=storage_state_path,
        )
        runtime = browser_runtime_status()
    except RuntimeError:
        raise
    except Exception:
        logger.debug("Could not prepare autonomous work item browser runtime", exc_info=True)
    return run_dir, runtime


def _enqueue_agent_work_item(
    session: Session,
    mission: AutonomousMission,
    item: AutonomousAgentWorkItem,
) -> bool:
    return _execute_agent_work_item_direct(session, mission, item)


def _execute_agent_work_item_direct(
    session: Session,
    mission: AutonomousMission,
    item: AutonomousAgentWorkItem,
) -> bool:
    """Execute one autonomous work item inside the Temporal activity worker."""
    now = _utcnow()
    current_item = session.get(AutonomousAgentWorkItem, item.id)
    current_mission = session.get(AutonomousMission, mission.id)
    if not current_item or current_item.status == "cancelled" or (current_mission and current_mission.status == "cancelled"):
        return False
    timeout_seconds = max(300, min(mission.max_runtime_minutes * 60, 7200))
    run_dir, browser_runtime = _prepare_autonomous_work_item_runtime(mission, item)
    allowed_tools = _allowed_tools_for_work_item(item, mcp_config_dir=run_dir)
    has_browser_tools = any(_is_browser_tool(tool) for tool in allowed_tools)
    item.agent_task_id = None
    item.status = "running"
    item.attempt_count += 1
    item.started_at = item.started_at or now
    item.lease_until = now + timedelta(seconds=timeout_seconds)
    item.last_heartbeat_at = now
    item.updated_at = now
    item.progress = {
        **item.progress,
        "phase": "running",
        "message": "Agent work item is running in a Temporal activity.",
        "runtime": str((mission.config or {}).get("runtime") or "claude_sdk"),
        "has_browser_tools": has_browser_tools,
        **browser_runtime,
    }
    session.add(item)
    session.commit()
    emit_work_item_status_event(
        item,
        "Agent work item started in Temporal activity.",
        event_type="lifecycle",
    )

    try:
        from orchestrator.services.agent_runtimes import AgentRuntimeContext, get_agent_runtime, normalize_agent_runtime

        runtime_name = normalize_agent_runtime((mission.config or {}).get("runtime"))
        last_progress_signature: tuple[str, str, str] | None = None
        last_assistant_message: str | None = None

        def _emit_event(event_type: str, message: str, *, level: str = "info", payload: dict[str, Any] | None = None) -> None:
            try:
                create_autonomous_agent_event(
                    project_id=item.project_id,
                    mission_id=item.mission_id,
                    run_id=item.run_id,
                    work_item_id=item.id,
                    agent_task_id=item.agent_task_id,
                    event_type=event_type,
                    level=level,
                    message=message,
                    payload=payload,
                )
            except Exception:
                logger.debug("Failed to persist autonomous work item event", exc_info=True)

        def _on_tool_use(tool_name: str, tool_input: dict[str, Any]) -> None:
            short_name = _short_tool_name(tool_name)
            payload = {
                "status": "started",
                "tool_name": tool_name,
                "short_name": short_name,
                "tool_input": tool_input,
                "runtime": runtime_name,
            }
            _emit_event("tool_call", f"Tool started: {short_name}", payload=payload)
            if _is_browser_tool(tool_name):
                _emit_event("browser_action", f"Browser action: {short_name}", payload=payload)

        def _on_progress(progress: dict[str, Any]) -> None:
            nonlocal last_progress_signature, last_assistant_message
            try:
                current = session.get(AutonomousAgentWorkItem, item.id)
                if not current or current.status != "running":
                    return
                heartbeat_at = _utcnow()
                last_tool = progress.get("last_tool")
                progress_payload = {
                    **progress,
                    "runtime": runtime_name,
                    "has_browser_tools": has_browser_tools,
                    **browser_runtime,
                }
                current.progress = {
                    **(current.progress or {}),
                    **{key: value for key, value in progress_payload.items() if value is not None},
                    "runtime": runtime_name,
                    "phase": progress.get("phase") or "running",
                    "message": progress.get("message") or "Agent is running.",
                    "last_event_at": heartbeat_at.isoformat(),
                }
                current.last_heartbeat_at = heartbeat_at
                current.lease_until = heartbeat_at + timedelta(seconds=timeout_seconds)
                current.updated_at = heartbeat_at
                session.add(current)
                session.commit()
                phase = str(progress.get("phase") or "running")
                message = str(progress.get("message") or "Agent is running.")
                signature = (phase, message, str(last_tool or ""))
                if signature != last_progress_signature:
                    last_progress_signature = signature
                    _emit_event(
                        "progress",
                        message,
                        payload={
                            **progress_payload,
                            "phase": phase,
                            "status": current.status,
                            "work_item_progress": current.progress,
                        },
                    )
                if phase == "tool_result" and last_tool:
                    short_name = _short_tool_name(str(last_tool))
                    payload = {
                        **progress_payload,
                        "status": "completed",
                        "tool_name": str(last_tool),
                        "short_name": short_name,
                    }
                    _emit_event("tool_call", f"Tool completed: {short_name}", payload=payload)
                    if _is_browser_tool(str(last_tool)):
                        _emit_event("browser_action", f"Browser action completed: {short_name}", payload=payload)
                elif (
                    message
                    and message != last_assistant_message
                    and phase not in {"tool_use", "tool_result"}
                    and message not in {"Agent is running.", "Agent work item is running in a Temporal activity."}
                ):
                    last_assistant_message = message
                    _emit_event(
                        "assistant_output",
                        message,
                        payload={"preview": message, "phase": phase, "runtime": runtime_name},
                    )
            except Exception:
                logger.debug("Failed to persist autonomous work item progress", exc_info=True)

        def _on_task_enqueued(task_id: str) -> None:
            try:
                current = session.get(AutonomousAgentWorkItem, item.id)
                if not current:
                    return
                current.agent_task_id = task_id
                current.progress = {
                    **(current.progress or {}),
                    "runtime": runtime_name,
                    "agent_task_id": task_id,
                    "hermes_run_id": task_id if runtime_name == "hermes" else None,
                    "phase": "queued" if runtime_name == "hermes" else "running",
                    "message": "Hermes run started." if runtime_name == "hermes" else "Agent task started.",
                    "has_browser_tools": has_browser_tools,
                    **browser_runtime,
                }
                current.updated_at = _utcnow()
                session.add(current)
                session.commit()
                _emit_event(
                    "lifecycle",
                    current.progress["message"],
                    payload={"agent_task_id": task_id, "runtime": runtime_name, **browser_runtime},
                )
            except Exception:
                logger.debug("Failed to persist autonomous task id", exc_info=True)

        def _is_cancelled() -> bool:
            with Session(engine) as check_session:
                current = check_session.get(AutonomousAgentWorkItem, item.id)
                current_mission = check_session.get(AutonomousMission, mission.id)
                return (
                    not current
                    or current.status == "cancelled"
                    or bool(current_mission and current_mission.status == "cancelled")
                )

        async def _run_agent():
            runtime = get_agent_runtime(runtime_name)
            return await runtime.run(
                _agent_prompt_for_work_item(mission, item),
                AgentRuntimeContext(
                    timeout_seconds=timeout_seconds,
                    allowed_tools=allowed_tools,
                    tools=list(allowed_tools),
                    max_budget_usd=mission.max_llm_budget_usd,
                    on_task_enqueued=_on_task_enqueued,
                    on_tool_use=_on_tool_use,
                    on_progress=_on_progress,
                    session_dir=run_dir,
                    cwd=run_dir,
                    owner_type="autonomous_work_item",
                    owner_id=item.id,
                    owner_label=f"{mission.name}: {item.role}",
                    memory_project_id=mission.project_id,
                    memory_agent_type=item.role,
                    memory_source_type="autonomous_work_item",
                    memory_source_id=item.id,
                    memory_stage="autonomous_mission",
                    model=(mission.config or {}).get("model"),
                    model_tier=(mission.config or {}).get("model_tier") or "tool_deep",
                    agent_name=item.role,
                    hermes_conversation=item.id,
                    metadata={
                        "mission_id": mission.id,
                        "mission_run_id": item.run_id,
                        "role": item.role,
                        "planner_key": item.planner_key,
                    },
                    is_cancelled=_is_cancelled,
                ),
            )

        result = asyncio.run(_run_agent())
    except Exception as exc:
        now = _utcnow()
        session.expire_all()
        item = session.get(AutonomousAgentWorkItem, item.id) or item
        current_mission = session.get(AutonomousMission, mission.id)
        if item.status == "cancelled" or (current_mission and current_mission.status == "cancelled"):
            item.status = "cancelled"
            item.error_message = item.error_message or "Mission cancelled"
            item.completed_at = item.completed_at or now
            item.updated_at = now
            item.last_heartbeat_at = now
            item.progress = {**(item.progress or {}), "phase": "cancelled", "message": item.error_message, **browser_runtime}
            session.add(item)
            session.commit()
            emit_work_item_status_event(item, item.error_message, event_type="lifecycle")
            return False
        item.status = "failed"
        item.error_message = str(exc)
        item.completed_at = now
        item.updated_at = now
        item.last_heartbeat_at = now
        item.progress = {"phase": "failed", "message": item.error_message, **browser_runtime}
        session.add(item)
        session.commit()
        emit_work_item_status_event(item, item.error_message, event_type="error")
        logger.warning("Failed to execute autonomous work item %s: %s", item.id, exc)
        return False

    now = _utcnow()
    session.expire_all()
    item = session.get(AutonomousAgentWorkItem, item.id) or item
    current_mission = session.get(AutonomousMission, mission.id) or mission
    if item.status == "cancelled" or current_mission.status == "cancelled" or getattr(result, "cancelled", False):
        item.status = "cancelled"
        item.error_message = item.error_message or "Agent work item cancelled"
        item.completed_at = item.completed_at or now
        item.updated_at = now
        item.last_heartbeat_at = now
        item.result = {
            **(item.result or {}),
            "output": getattr(result, "output", "") or "",
            "telemetry": {
                "runtime": str((mission.config or {}).get("runtime") or "claude_sdk"),
                "tool_calls": len(getattr(result, "tool_calls", []) or []),
                "messages_received": getattr(result, "messages_received", 0),
                "text_blocks_received": getattr(result, "text_blocks_received", 0),
                "duration_seconds": getattr(result, "duration_seconds", 0.0),
                "cancelled": True,
            },
        }
        item.progress = {**(item.progress or {}), "phase": "cancelled", "message": item.error_message, **browser_runtime}
        session.add(item)
        session.commit()
        emit_work_item_status_event(item, item.error_message, event_type="lifecycle")
        return False
    telemetry = {
        "runtime": str((mission.config or {}).get("runtime") or "claude_sdk"),
        "tool_calls": len(result.tool_calls),
        "messages_received": result.messages_received,
        "text_blocks_received": result.text_blocks_received,
        "duration_seconds": result.duration_seconds,
        "timed_out": result.timed_out,
        "total_cost_usd": result.total_cost_usd,
        "stop_reason": result.stop_reason,
    }
    if result.success:
        item.status = "completed"
        item.completed_at = now
        item.result = {
            "output": result.output or "",
            "telemetry": telemetry,
        }
        item.artifacts = [
            {
                "type": "agent_report",
                "label": f"{item.role} report",
                "content": result.output or "",
            }
        ]
        item.progress = {"phase": "completed", "message": "Agent completed this assignment.", **browser_runtime}
        item.budget_used_usd = float(result.total_cost_usd or 0.0)
        item.updated_at = now
        item.last_heartbeat_at = now
        mission.budget_used_usd += item.budget_used_usd
        mission.updated_at = now
        session.add(item)
        session.add(mission)
        session.commit()
        if result.output:
            create_autonomous_agent_event(
                project_id=item.project_id,
                mission_id=item.mission_id,
                run_id=item.run_id,
                work_item_id=item.id,
                agent_task_id=item.agent_task_id,
                event_type="assistant_output",
                message=result.output,
                payload={"preview": result.output[:1000], "runtime": runtime_name},
            )
        emit_work_item_status_event(item, "Agent completed this assignment.", event_type="complete")
        return True

    item.status = "failed"
    item.error_message = result.error or "Agent work item failed"
    item.completed_at = now
    item.result = {"output": result.output or "", "telemetry": telemetry, "error": item.error_message}
    item.progress = {"phase": "failed", "message": item.error_message, **browser_runtime}
    item.updated_at = now
    item.last_heartbeat_at = now
    item.budget_used_usd = float(result.total_cost_usd or 0.0)
    session.add(item)
    session.commit()
    if result.output:
        create_autonomous_agent_event(
            project_id=item.project_id,
            mission_id=item.mission_id,
            run_id=item.run_id,
            work_item_id=item.id,
            agent_task_id=item.agent_task_id,
            event_type="assistant_output",
            message=result.output,
            level="warning",
            payload={"preview": result.output[:1000], "runtime": telemetry["runtime"]},
        )
    emit_work_item_status_event(item, item.error_message, event_type="error")
    return False


def _enqueue_agent_work_item_legacy(
    session: Session,
    mission: AutonomousMission,
    item: AutonomousAgentWorkItem,
) -> bool:
    try:
        from orchestrator.services.agent_queue import get_agent_queue

        async def _enqueue() -> str:
            queue = get_agent_queue()
            await queue.connect()
            try:
                return await queue.enqueue_task(
                    prompt=_agent_prompt_for_work_item(mission, item),
                    timeout_seconds=max(300, min(mission.max_runtime_minutes * 60, 7200)),
                    agent_type=item.role,
                    operation_type="autonomous_mission",
                    allowed_tools=_allowed_tools_for_work_item(item),
                    max_budget_usd=mission.max_llm_budget_usd,
                    owner_type="autonomous_work_item",
                    owner_id=item.id,
                    owner_label=f"{mission.name}: {item.role}",
                )
            finally:
                await queue.disconnect()

        task_id = asyncio.run(_enqueue())
    except Exception as exc:
        now = _utcnow()
        item.status = "blocked"
        item.error_message = f"Unable to enqueue agent task: {exc}"
        item.completed_at = now
        item.updated_at = now
        item.progress = {"phase": "blocked", "message": item.error_message}
        session.add(item)
        session.commit()
        logger.warning("Failed to enqueue autonomous work item %s: %s", item.id, exc)
        return False

    now = _utcnow()
    item.agent_task_id = task_id
    item.status = "running"
    item.attempt_count += 1
    item.started_at = item.started_at or now
    item.lease_until = now + timedelta(seconds=max(300, min(mission.max_runtime_minutes * 60, 7200)))
    item.last_heartbeat_at = now
    item.updated_at = now
    item.progress = {
        **item.progress,
        "phase": "queued",
        "message": "Agent task has been queued.",
        "agent_task_id": task_id,
    }
    session.add(item)
    session.commit()
    emit_work_item_status_event(item, "Agent task queued for autonomous work item.", event_type="lifecycle")
    return True


def _sync_agent_work_items(session: Session, mission: AutonomousMission) -> int:
    running_items = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission.id,
            AutonomousAgentWorkItem.status == "running",
            AutonomousAgentWorkItem.agent_task_id != None,  # noqa: E711
        )
    ).all()
    if not running_items:
        return 0
    try:
        from orchestrator.services.agent_queue import AgentTaskStatus, get_agent_queue

        async def _load_tasks(task_ids: list[str]):
            queue = get_agent_queue()
            await queue.connect()
            try:
                tasks = [await queue.get_task(task_id) for task_id in task_ids]
                progress = {task_id: await queue.get_task_progress(task_id) for task_id in task_ids}
                return tasks, progress
            finally:
                await queue.disconnect()

        tasks, progress_by_id = asyncio.run(_load_tasks([str(item.agent_task_id) for item in running_items if item.agent_task_id]))
        task_by_id = {task.id: task for task in tasks if task}
    except Exception as exc:
        logger.debug("Unable to sync autonomous agent work items: %s", exc)
        return 0

    completed_count = 0
    now = _utcnow()
    for item in running_items:
        task = task_by_id.get(str(item.agent_task_id))
        if not task:
            continue
        live_progress = progress_by_id.get(str(item.agent_task_id)) or {}
        telemetry = task.telemetry or {}
        if task.status == AgentTaskStatus.PAUSED:
            item.progress = {
                **item.progress,
                "phase": "paused",
                "message": "Agent is paused.",
                **{key: value for key, value in live_progress.items() if value is not None},
                "last_event_at": now.isoformat(),
            }
            item.updated_at = now
            item.last_heartbeat_at = now
            session.add(item)
            continue
        if task.status.value == "running":
            item.progress = {
                **item.progress,
                "phase": "running",
                "message": "Agent is running.",
                "tool_calls": telemetry.get("tool_calls"),
                "last_tool": telemetry.get("last_tool"),
                **{key: value for key, value in live_progress.items() if value is not None},
                "last_event_at": now.isoformat(),
            }
            item.updated_at = now
            item.last_heartbeat_at = now
            item.lease_until = now + timedelta(minutes=30)
            session.add(item)
            continue
        if task.status == AgentTaskStatus.COMPLETED:
            item.status = "completed"
            item.completed_at = task.completed_at or now
            item.result = {
                "output": task.result or "",
                "telemetry": telemetry,
            }
            item.artifacts = [{"type": "agent_report", "label": f"{item.role} report", "content": task.result or ""}]
            item.progress = {"phase": "completed", "message": "Agent completed this assignment."}
            item.budget_used_usd = float(telemetry.get("total_cost_usd") or 0.0)
            item.updated_at = now
            item.last_heartbeat_at = now
            completed_count += 1
            session.add(item)
            emit_work_item_status_event(item, "Agent completed this assignment.", event_type="complete")
        elif task.status in {AgentTaskStatus.FAILED, AgentTaskStatus.TIMEOUT, AgentTaskStatus.CANCELLED}:
            item.status = "cancelled" if task.status == AgentTaskStatus.CANCELLED else "failed"
            item.error_message = task.error or f"Agent task {task.status.value}"
            item.completed_at = task.completed_at or now
            item.progress = {"phase": item.status, "message": item.error_message}
            item.updated_at = now
            item.last_heartbeat_at = now
            session.add(item)
            emit_work_item_status_event(item, item.error_message, event_type="error")
    if completed_count:
        mission.budget_used_usd += sum(item.budget_used_usd for item in running_items if item.status == "completed")
        mission.updated_at = now
        session.add(mission)
    session.commit()
    return completed_count


def _create_findings_from_completed_work_items(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
) -> int:
    created = 0
    items = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission.id,
            AutonomousAgentWorkItem.status == "completed",
        )
    ).all()
    for item in items:
        if _work_item_review_decision(item) in {"rejected", "needs_revision"}:
            continue
        result = item.result or {}
        output = str(result.get("output") or "").strip()
        if not output:
            continue
        structured, validation_errors, saw_structured_output = _extract_structured_agent_contract(output)
        if saw_structured_output and validation_errors:
            _create_contract_revision_work_item(session, mission, run, item, validation_errors)
            continue
        if structured:
            merge_summary = _merge_structured_work_item_artifacts(session, mission, run, item, structured)
            item.result = {**item.result, "structured_merge": merge_summary}
            session.add(item)
            session.commit()
            created += int(merge_summary.get("findings_created", 0) or 0)
            if any(
                int(merge_summary.get(key, 0) or 0)
                for key in (
                    "requirements_created",
                    "requirements_reused",
                    "rtm_entries_created",
                    "rtm_entries_reused",
                    "test_proposals_created",
                    "findings_reused",
                    "app_map_updates",
                )
            ):
                continue
        dedupe_key = hashlib.sha256(f"{mission.project_id}|work_item|{item.id}|finding".encode()).hexdigest()[:32]
        existing = session.exec(
            select(AutonomousFinding).where(
                AutonomousFinding.project_id == mission.project_id,
                AutonomousFinding.dedupe_key == dedupe_key,
            )
        ).first()
        if existing:
            continue
        title = f"{_title_case(item.role)} agent report"
        evidence = {
            "work_item_id": item.id,
            "role": item.role,
            "assigned_surface": item.assigned_surface,
            **_work_item_revision_metadata(item),
        }
        finding = AutonomousFinding(
            id=f"amfind-{uuid.uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            finding_type="exploration" if item.role in {"surface_mapper", "explorer"} else "coverage_gap",
            severity="medium",
            title=title,
            description=output[:8000],
            status="open",
            confidence=0.75,
            dedupe_key=dedupe_key,
            source_type="autonomous_work_item",
            source_id=item.id,
            approval_required=True,
        )
        finding.evidence = evidence
        session.add(finding)
        created += 1
    if created:
        mission.total_findings += created
        session.add(mission)
        session.commit()
    return created


def _create_contract_revision_work_item(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    item: AutonomousAgentWorkItem,
    validation_errors: list[str],
) -> AutonomousAgentWorkItem | None:
    existing = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission.id,
            col(AutonomousAgentWorkItem.status).in_(("queued", "running", "completed")),
        )
    ).all()
    for candidate in existing:
        progress = candidate.progress
        if progress.get("revision_of_work_item_id") == item.id and progress.get("review_reason") == "structured_contract_validation":
            item.result = {
                **item.result,
                "review_decision": "needs_revision",
                "revision_work_item_id": candidate.id,
                "validation_errors": validation_errors,
            }
            session.add(item)
            session.commit()
            return candidate

    attempt = int((item.progress or {}).get("revision_attempt") or 0) + 1
    revision = AutonomousAgentWorkItem(
        id=f"amwork-{uuid.uuid4().hex[:12]}",
        mission_id=mission.id,
        run_id=run.id,
        project_id=mission.project_id,
        role=item.role,
        objective=(
            f"Revise the structured JSON output for work item {item.id}. "
            "Return only contract-valid JSON and preserve any valid discoveries."
        ),
        assigned_surface_json=item.assigned_surface_json,
        status="queued",
        priority=max(1, int(item.priority or 50) - 5),
    )
    revision.progress = {
        "phase": "created",
        "message": "Queued because the previous agent output did not match the structured contract.",
        "revision_of_work_item_id": item.id,
        "reviewer_work_item_id": item.id,
        "review_reason": "structured_contract_validation",
        "validation_errors": validation_errors[:20],
        "revision_attempt": attempt,
    }
    item.result = {
        **item.result,
        "review_decision": "needs_revision",
        "revision_work_item_id": revision.id,
        "validation_errors": validation_errors,
    }
    session.add(item)
    session.add(revision)
    session.commit()
    return revision


def _merge_structured_work_item_artifacts(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    item: AutonomousAgentWorkItem,
    contract: dict[str, Any],
) -> dict[str, int]:
    summary = {
        "requirements_created": 0,
        "requirements_reused": 0,
        "rtm_entries_created": 0,
        "rtm_entries_reused": 0,
        "test_proposals_created": 0,
        "findings_created": 0,
        "findings_reused": 0,
        "app_map_updates": 0,
        "rtm_snapshots_created": 0,
    }

    for row in _dict_rows(contract.get("app_map_updates")):
        if _merge_app_map_update(session, mission, row):
            summary["app_map_updates"] += 1

    requirement_id_by_fingerprint: dict[str, int] = {}
    for row in _dict_rows(contract.get("requirements")):
        requirement, created, fingerprint = _merge_requirement_artifact(session, mission, item, row)
        if not requirement or requirement.id is None:
            continue
        requirement_id_by_fingerprint[fingerprint] = requirement.id
        if created:
            summary["requirements_created"] += 1
        else:
            summary["requirements_reused"] += 1

    for row in _dict_rows(contract.get("rtm_candidates")):
        if not _resolve_requirement_ids(session, mission.project_id, row) and len(requirement_id_by_fingerprint) == 1:
            row = {**row, "requirement_id": next(iter(requirement_id_by_fingerprint.values()))}
        created = _merge_rtm_candidate(session, mission, row)
        if created is True:
            summary["rtm_entries_created"] += 1
        elif created is False:
            summary["rtm_entries_reused"] += 1

    for row in _dict_rows(contract.get("test_proposals")):
        requirement_ids = _resolve_requirement_ids(session, mission.project_id, row)
        if not requirement_ids and row.get("requirement_fingerprint"):
            req_id = requirement_id_by_fingerprint.get(str(row["requirement_fingerprint"]))
            if req_id:
                requirement_ids = [req_id]
        if not requirement_ids and len(requirement_id_by_fingerprint) == 1:
            requirement_ids = [next(iter(requirement_id_by_fingerprint.values()))]
        proposal = _merge_test_proposal_artifact(session, mission, run, item, row, requirement_ids=requirement_ids)
        if proposal:
            summary["test_proposals_created"] += 1

    for row in _dict_rows(contract.get("bugs")) + _dict_rows(contract.get("findings")):
        finding, created = _merge_bug_or_finding_artifact(session, mission, run, item, row)
        if not finding:
            continue
        if created:
            summary["findings_created"] += 1
        else:
            summary["findings_reused"] += 1

    if summary["rtm_entries_created"]:
        _create_rtm_snapshot(session, mission, source_work_item_id=item.id)
        summary["rtm_snapshots_created"] = 1

    session.commit()
    return summary


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in _as_list(value) if isinstance(row, dict)]


def _merge_app_map_update(session: Session, mission: AutonomousMission, row: dict[str, Any]) -> bool:
    url = str(row.get("url") or row.get("target_url") or "").strip()
    if not url:
        return False
    surface_key = _stable_dedupe_hash("surface", mission.project_id or "default", _route_from_url(url) or url)
    existing = session.exec(
        select(ApplicationMap).where(
            ApplicationMap.project_id == mission.project_id,
            ApplicationMap.app_surface_key == surface_key,
        )
    ).first()
    if not existing:
        existing = session.exec(select(ApplicationMap).where(ApplicationMap.url == url)).first()
    now = _utcnow()
    if existing:
        existing.project_id = existing.project_id or mission.project_id
        existing.app_surface_key = existing.app_surface_key or surface_key
        existing.page_title = str(row.get("page_title") or row.get("title") or existing.page_title or "") or None
        existing.linked_urls = _as_text_list(row.get("linked_urls")) or existing.linked_urls
        if isinstance(row.get("elements"), dict):
            existing.elements = row["elements"]
        forms = row.get("forms")
        if isinstance(forms, list):
            existing.forms = [form for form in forms if isinstance(form, dict)]
        endpoints = row.get("api_endpoints")
        if isinstance(endpoints, list):
            existing.api_endpoints = [endpoint for endpoint in endpoints if isinstance(endpoint, dict)]
        existing.last_crawled = now
        session.add(existing)
        return True
    app_map = ApplicationMap(
        project_id=mission.project_id,
        app_surface_key=surface_key,
        url=url,
        page_title=str(row.get("page_title") or row.get("title") or "") or None,
        linked_urls=_as_text_list(row.get("linked_urls")) or None,
        elements=row.get("elements") if isinstance(row.get("elements"), dict) else None,
        forms=[form for form in _as_list(row.get("forms")) if isinstance(form, dict)] or None,
        api_endpoints=[endpoint for endpoint in _as_list(row.get("api_endpoints")) if isinstance(endpoint, dict)] or None,
        last_crawled=now,
    )
    session.add(app_map)
    return True


def _merge_requirement_artifact(
    session: Session,
    mission: AutonomousMission,
    item: AutonomousAgentWorkItem,
    row: dict[str, Any],
) -> tuple[Requirement | None, bool, str]:
    title = str(row.get("title") or "").strip()
    if not title:
        return None, False, ""
    category = str(row.get("category") or "other").strip() or "other"
    criteria = _as_text_list(row.get("acceptance_criteria") or row.get("criteria"))
    fingerprint = _requirement_fingerprint({"title": title, "category": category, "acceptance_criteria": criteria})
    existing_by_key = session.exec(
        select(Requirement).where(Requirement.project_id == mission.project_id, Requirement.canonical_key == fingerprint)
    ).first()
    candidates = [existing_by_key] if existing_by_key else session.exec(
        select(Requirement).where(Requirement.project_id == mission.project_id)
    ).all()
    for requirement in candidates:
        if not requirement:
            continue
        existing_fingerprint = _requirement_fingerprint(
            {
                "title": requirement.title,
                "category": requirement.category,
                "acceptance_criteria": requirement.acceptance_criteria,
            }
        )
        if existing_fingerprint != fingerprint:
            continue
        existing_criteria = requirement.acceptance_criteria
        merged_criteria = sorted({*existing_criteria, *criteria})
        if merged_criteria != existing_criteria:
            requirement.acceptance_criteria = merged_criteria
        if row.get("description") and not requirement.description:
            requirement.description = str(row.get("description"))
        requirement.canonical_key = requirement.canonical_key or fingerprint
        requirement.confidence = max(float(requirement.confidence or 0), _as_float(row.get("confidence"), 0.7))
        requirement.updated_at = _utcnow()
        session.add(requirement)
        return requirement, False, fingerprint

    truth_state = str(row.get("truth_state") or "candidate_requirement")
    if truth_state not in {"candidate_requirement", "confirmed_requirement", "manual_requirement", "observed_behavior"}:
        truth_state = "candidate_requirement"
    now = _utcnow()
    requirement = Requirement(
        project_id=mission.project_id,
        req_code=_next_requirement_code(session, mission.project_id),
        title=title,
        description=str(row.get("description") or "") or None,
        category=category,
        priority=_normalize_risk(str(row.get("priority") or "medium")),
        status="confirmed" if truth_state == "confirmed_requirement" else "draft",
        canonical_key=fingerprint,
        truth_state=truth_state,
        source_type="autonomous_agent",
        confidence=_as_float(row.get("confidence"), 0.7),
        uncertainty_reason=str(
            row.get("uncertainty_reason") or "Generated from autonomous agent evidence and awaiting human review."
        ),
        acceptance_criteria_json=json.dumps(criteria),
        created_at=now,
        updated_at=now,
    )
    session.add(requirement)
    session.flush()
    return requirement, True, fingerprint


def _merge_rtm_candidate(
    session: Session,
    mission: AutonomousMission,
    row: dict[str, Any],
) -> bool | None:
    requirement_ids = _resolve_requirement_ids(session, mission.project_id, row)
    if not requirement_ids:
        return None
    test_spec_name = str(row.get("test_spec_name") or row.get("spec_name") or row.get("suggested_file_path") or "").strip()
    if not test_spec_name:
        return None
    created_any = False
    reused_any = False
    for requirement_id in requirement_ids:
        requirement = session.get(Requirement, requirement_id)
        if not requirement or requirement.project_id != mission.project_id:
            continue
        allow_candidate = bool(row.get("allow_candidate") or row.get("accepted_candidate"))
        if _requirement_truth_state(requirement) != "confirmed_requirement" and not allow_candidate:
            continue
        dedupe_key = _stable_dedupe_hash(
            mission.project_id or "default",
            "rtm",
            requirement_id,
            test_spec_name,
            row.get("test_spec_path") or row.get("spec_path"),
        )
        existing = session.exec(
            select(RtmEntry).where(
                RtmEntry.project_id == mission.project_id,
                RtmEntry.dedupe_key == dedupe_key,
            )
        ).first()
        if not existing:
            existing = session.exec(
                select(RtmEntry).where(
                    RtmEntry.project_id == mission.project_id,
                    RtmEntry.requirement_id == requirement_id,
                    RtmEntry.test_spec_name == test_spec_name,
                )
            ).first()
        now = _utcnow()
        if existing:
            existing.dedupe_key = existing.dedupe_key or dedupe_key
            existing.mapping_type = str(row.get("mapping_type") or existing.mapping_type or "suggested")
            existing.test_spec_path = str(row.get("test_spec_path") or row.get("spec_path") or existing.test_spec_path or "") or None
            existing.confidence = max(float(existing.confidence or 0), _as_float(row.get("confidence"), 0.7))
            existing.coverage_notes = str(row.get("coverage_notes") or existing.coverage_notes or "") or None
            existing.gap_notes = str(row.get("gap_notes") or existing.gap_notes or "") or None
            existing.updated_at = now
            session.add(existing)
            reused_any = True
            continue
        entry = RtmEntry(
            project_id=mission.project_id,
            requirement_id=requirement_id,
            test_spec_name=test_spec_name,
            test_spec_path=str(row.get("test_spec_path") or row.get("spec_path") or "") or None,
            mapping_type=str(row.get("mapping_type") or "suggested"),
            dedupe_key=dedupe_key,
            confidence=_as_float(row.get("confidence"), 0.7),
            coverage_notes=str(row.get("coverage_notes") or "") or None,
            gap_notes=str(row.get("gap_notes") or "") or None,
            created_at=now,
            updated_at=now,
        )
        session.add(entry)
        created_any = True
    if created_any:
        return True
    if reused_any:
        return False
    return None


def _merge_test_proposal_artifact(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    item: AutonomousAgentWorkItem,
    row: dict[str, Any],
    *,
    requirement_ids: list[int],
) -> AutonomousTestProposal | None:
    title = str(row.get("title") or row.get("scenario") or "").strip()
    rationale = str(row.get("rationale") or row.get("description") or title).strip()
    if not title or not rationale:
        return None
    target_url = str(row.get("target_url") or row.get("url") or "").strip() or _default_target_url(mission)
    if row.get("route") and not row.get("target_url"):
        target_url = _url_for_route(_default_target_url(mission), str(row["route"]))
    fingerprint = _spec_fingerprint(row, requirement_ids=requirement_ids)
    metadata = _artifact_source_metadata(
        item,
        artifact_type="test_proposal",
        fingerprint=fingerprint,
        extra={
            "requirement_ids": requirement_ids,
            "route": row.get("route") or _route_from_url(target_url),
            "agent_rationale": rationale,
        },
    )
    if requirement_ids:
        metadata["requirement_id"] = requirement_ids[0]
    return _create_test_proposal(
        session,
        mission,
        run,
        source_type="autonomous_structured_spec",
        source_id=fingerprint,
        title=title,
        rationale=rationale,
        target_url=target_url,
        risk_level=str(row.get("risk_level") or row.get("severity") or "medium"),
        source_metadata=metadata,
    )


def _merge_bug_or_finding_artifact(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    item: AutonomousAgentWorkItem,
    row: dict[str, Any],
) -> tuple[AutonomousFinding | None, bool]:
    title = str(row.get("title") or "").strip()
    description = str(row.get("description") or row.get("observed_failure") or "").strip()
    if not title or not description:
        return None, False
    kind = "bug" if row.get("observed_failure") or row.get("expected_behavior") else str(row.get("finding_type") or "coverage_gap")
    fingerprint = _bug_fingerprint(row) if kind == "bug" else _stable_dedupe_hash(
        "finding",
        kind,
        row.get("route") or row.get("target_url") or row.get("url"),
        title,
        description,
    )
    dedupe_key = _stable_dedupe_hash(mission.project_id or "default", kind, fingerprint)
    existing = session.exec(
        select(AutonomousFinding).where(
            AutonomousFinding.project_id == mission.project_id,
            AutonomousFinding.dedupe_key == dedupe_key,
        )
    ).first()
    if existing:
        return existing, False
    now = _utcnow()
    evidence = _artifact_source_metadata(
        item,
        artifact_type=kind,
        fingerprint=fingerprint,
        extra={
            "target_url": row.get("target_url") or row.get("url"),
            "route": row.get("route") or _route_from_url(row.get("target_url") or row.get("url")),
            "action": row.get("action"),
            "observed_failure": row.get("observed_failure"),
            "expected_behavior": row.get("expected_behavior"),
            "evidence": row.get("evidence") if isinstance(row.get("evidence"), dict) else {},
        },
    )
    finding = AutonomousFinding(
        id=f"amfind-{uuid.uuid4().hex[:12]}",
        mission_id=mission.id,
        run_id=run.id,
        project_id=mission.project_id,
        finding_type=kind,
        severity=_normalize_risk(str(row.get("severity") or row.get("risk_level") or "medium")),
        title=title,
        description=description,
        status="awaiting_approval" if kind == "bug" else "open",
        confidence=_as_float(row.get("confidence"), 0.75),
        dedupe_key=dedupe_key,
        evidence_json=json.dumps(evidence),
        source_type="autonomous_work_item",
        source_id=item.id,
        approval_required=True,
        created_at=now,
        updated_at=now,
    )
    session.add(finding)
    return finding, True


def _create_rtm_snapshot(session: Session, mission: AutonomousMission, *, source_work_item_id: str) -> None:
    requirements = session.exec(select(Requirement).where(Requirement.project_id == mission.project_id)).all()
    entries = session.exec(select(RtmEntry).where(RtmEntry.project_id == mission.project_id)).all()
    entries_by_requirement: dict[int, list[RtmEntry]] = {}
    for entry in entries:
        entries_by_requirement.setdefault(entry.requirement_id, []).append(entry)
    covered = 0
    partial = 0
    uncovered = 0
    rows = []
    for requirement in requirements:
        req_entries = entries_by_requirement.get(requirement.id or -1, [])
        if any(entry.mapping_type == "full" for entry in req_entries):
            covered += 1
            status = "covered"
        elif req_entries:
            partial += 1
            status = "partial"
        else:
            uncovered += 1
            status = "uncovered"
        rows.append(
            {
                "requirement_id": requirement.id,
                "req_code": requirement.req_code,
                "title": requirement.title,
                "status": status,
                "entries": [entry.test_spec_name for entry in req_entries],
            }
        )
    total = len(requirements)
    snapshot = RtmSnapshot(
        project_id=mission.project_id,
        snapshot_name=f"autonomous-{mission.id}-{source_work_item_id}",
        total_requirements=total,
        covered_requirements=covered,
        partial_requirements=partial,
        uncovered_requirements=uncovered,
        coverage_percentage=round((covered / total) * 100, 2) if total else 0.0,
        snapshot_data_json=json.dumps({"source_work_item_id": source_work_item_id, "rows": rows[:500]}),
        created_at=_utcnow(),
    )
    session.add(snapshot)


def _url_for_route(base_url: str, route: str) -> str:
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        return route
    path = route if route.startswith("/") else f"/{route}"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _update_mission_team_progress(session: Session, mission: AutonomousMission) -> None:
    mission.current_stage = "team_supervising"
    mission.next_action = _stage_next_action("team_supervising")
    mission.last_heartbeat_at = _utcnow()
    mission.updated_at = mission.last_heartbeat_at
    session.add(mission)
    session.commit()


def _create_coverage_gap_artifacts(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
) -> dict[str, int]:
    summary = {"findings_created": 0, "approvals_created": 0, "test_proposals_created": 0}
    statement = (
        select(CoverageGap)
        .where(CoverageGap.resolved == False)  # noqa: E712
        .order_by(CoverageGap.created_at.desc())
        .limit(MAX_PROPOSALS_PER_ITERATION)
    )
    gaps = session.exec(statement).all()
    gaps = [gap for gap in gaps if _coverage_gap_matches_mission(gap, mission)]
    if not gaps:
        return summary

    for gap in gaps:
        raw_key = f"{mission.project_id}|coverage_gap|{gap.id}|{gap.description}|{gap.url or ''}"
        dedupe_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:32]
        finding = session.exec(
            select(AutonomousFinding).where(
                AutonomousFinding.project_id == mission.project_id,
                AutonomousFinding.dedupe_key == dedupe_key,
            )
        ).first()
        approval: AutonomousApproval | None = None
        now = _utcnow()
        if not finding:
            finding_id = f"amfind-{uuid.uuid4().hex[:12]}"
            title = gap.description[:120] if gap.description else "Autonomous coverage gap"
            evidence = {
                "coverage_gap_id": gap.id,
                "url": gap.url,
                "suggested_test": gap.suggested_test,
                "extra_data": gap.extra_data or {},
            }
            finding = AutonomousFinding(
                id=finding_id,
                mission_id=mission.id,
                run_id=run.id,
                project_id=mission.project_id,
                finding_type="coverage_gap",
                severity=gap.severity or "medium",
                title=title,
                description=gap.suggested_test or gap.description,
                status="awaiting_approval",
                confidence=0.72,
                dedupe_key=dedupe_key,
                evidence_json=json.dumps(evidence),
                source_type="coverage_gap",
                source_id=str(gap.id),
                approval_required=True,
                created_at=now,
                updated_at=now,
            )
            approval = AutonomousApproval(
                id=f"amappr-{uuid.uuid4().hex[:12]}",
                mission_id=mission.id,
                run_id=run.id,
                finding_id=finding_id,
                project_id=mission.project_id,
                action_type="persist_test",
                status="pending",
                requested_payload_json=json.dumps(
                    {
                        "finding_id": finding_id,
                        "action": "Review the generated test proposal for this coverage gap.",
                        "suggested_test": gap.suggested_test,
                        "approval_policy": mission.approval_policy,
                    }
                ),
                requested_at=now,
            )
            mission.total_findings += 1
            summary["findings_created"] += 1
            summary["approvals_created"] += 1
            session.add(finding)
            session.add(approval)

        proposal = _create_test_proposal(
            session,
            mission,
            run,
            source_type="coverage_gap",
            source_id=str(gap.id),
            title=gap.description or "Autonomous coverage gap",
            rationale=gap.suggested_test or gap.description,
            target_url=gap.url or _default_target_url(mission),
            risk_level=gap.severity or "medium",
            finding_id=finding.id if finding else None,
            coverage_gap_id=gap.id,
            approval_id=approval.id if approval else None,
            source_metadata={"gap_type": gap.gap_type, "extra_data": gap.extra_data or {}},
        )
        if proposal:
            summary["test_proposals_created"] += 1
            if approval:
                approval.requested_payload = {
                    **approval.requested_payload,
                    "proposal_id": proposal.id,
                    "suggested_file_path": proposal.suggested_file_path,
                    "test_type": proposal.test_type,
                }

    session.add(mission)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return {"findings_created": 0, "approvals_created": 0, "test_proposals_created": 0}
    return summary


def _create_proposals_for_approved_findings(session: Session, mission: AutonomousMission, run: AutonomousMissionRun) -> int:
    findings = session.exec(
        select(AutonomousFinding)
        .where(
            AutonomousFinding.project_id == mission.project_id,
            AutonomousFinding.status == "approved",
        )
        .order_by(col(AutonomousFinding.updated_at).desc())
        .limit(MAX_PROPOSALS_PER_ITERATION)
    ).all()
    created = 0
    for finding in findings:
        evidence = finding.evidence
        source_metadata: dict[str, Any] = {
            "finding_type": finding.finding_type,
            "confidence": finding.confidence,
            "evidence": evidence,
        }
        for key in ("work_item_id", *REVISION_METADATA_KEYS):
            if evidence.get(key) is not None:
                source_metadata[key] = evidence.get(key)
        requirement_id = evidence.get("requirement_id")
        if requirement_id is not None:
            try:
                requirement = session.get(Requirement, int(requirement_id))
            except (TypeError, ValueError):
                requirement = None
            if requirement:
                warning = _requirement_generation_warning(requirement)
                source_metadata.update(
                    {
                        "requirement_id": requirement.id,
                        "requirement_code": requirement.req_code,
                        "requirement_truth_state": _requirement_truth_state(requirement),
                        "generation_allowed": True,
                        "generation_warning": warning,
                    }
                )
        proposal = _create_test_proposal(
            session,
            mission,
            run,
            source_type="autonomous_finding",
            source_id=finding.id,
            title=finding.title,
            rationale=finding.description,
            target_url=str(evidence.get("url") or _default_target_url(mission)),
            risk_level=finding.severity or "medium",
            finding_id=finding.id,
            coverage_gap_id=_as_int(evidence.get("coverage_gap_id")),
            source_metadata=source_metadata,
        )
        if proposal:
            created += 1
    if created:
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return 0
    return created


def _auto_materialize_low_risk_proposals(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
) -> dict[str, int]:
    summary = {"materialized": 0, "validated": 0, "validation_failed": 0, "skipped": 0}
    if mission.approval_policy != "auto_materialize_low_risk":
        return summary

    proposals = session.exec(
        select(AutonomousTestProposal)
        .where(
            AutonomousTestProposal.project_id == mission.project_id,
            col(AutonomousTestProposal.approval_status).in_(("pending", "approved")),
            AutonomousTestProposal.materialized_file_path == None,  # noqa: E711
        )
        .order_by(col(AutonomousTestProposal.created_at).asc())
        .limit(MAX_PROPOSALS_PER_ITERATION)
    ).all()
    for proposal in proposals:
        if _normalize_risk(proposal.risk_level) not in LOW_RISK_LEVELS:
            summary["skipped"] += 1
            continue
        review_context = _proposal_review_context_for_policy(session, proposal)
        duplicate = review_context.get("duplicate") if isinstance(review_context, dict) else {}
        if isinstance(duplicate, dict) and duplicate.get("blocking"):
            proposal.validation_status = "blocked"
            proposal.validation_result = {
                "reason": "blocking_duplicate",
                "review_context": review_context,
            }
            proposal.updated_at = _utcnow()
            session.add(proposal)
            summary["skipped"] += 1
            continue
        try:
            relative_path = _validate_materialize_path_for_policy(proposal.suggested_file_path, proposal.test_type)
        except ValueError as exc:
            proposal.validation_status = "blocked"
            proposal.validation_result = {"reason": "invalid_path", "error": str(exc)}
            proposal.updated_at = _utcnow()
            session.add(proposal)
            summary["skipped"] += 1
            continue
        target = (REPOSITORY_ROOT / relative_path).resolve()
        try:
            target.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError:
            proposal.validation_status = "blocked"
            proposal.validation_result = {"reason": "path_escape", "path": relative_path}
            proposal.updated_at = _utcnow()
            session.add(proposal)
            summary["skipped"] += 1
            continue
        if target.exists():
            proposal.validation_status = "blocked"
            proposal.validation_result = {"reason": "file_exists", "path": relative_path}
            proposal.updated_at = _utcnow()
            session.add(proposal)
            summary["skipped"] += 1
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as temp_file:
            temp_file.write(proposal.generated_spec_content)
            temp_path = Path(temp_file.name)
        temp_path.replace(target)

        now = _utcnow()
        proposal.approval_status = "materialized"
        proposal.approved_at = proposal.approved_at or now
        proposal.materialized_at = now
        proposal.materialized_by = "autonomous_policy"
        proposal.materialized_file_path = relative_path
        proposal.materialization_result = {
            "file_path": relative_path,
            "policy": mission.approval_policy,
            "run_id": run.id,
            "risk_level": proposal.risk_level,
            "review_context": review_context,
        }
        proposal.updated_at = now
        session.add(proposal)
        session.flush()
        summary["materialized"] += 1

        validation = _validate_materialized_proposal(proposal)
        proposal.validation_status = str(validation.get("status") or "failed")
        proposal.validation_result = validation
        proposal.validation_artifacts = [item for item in _as_list(validation.get("artifacts")) if isinstance(item, dict)]
        proposal.validation_log_path = str(validation.get("log_path") or "") or None
        proposal.validation_trace_path = str(validation.get("trace_path") or "") or None
        proposal.validated_at = _utcnow()
        proposal.updated_at = proposal.validated_at
        session.add(proposal)
        if proposal.validation_status == "passed":
            summary["validated"] += 1
        else:
            summary["validation_failed"] += 1
            _create_validation_failure_work_item(session, mission, run, proposal, validation)

    session.commit()
    return summary


def _proposal_review_context_for_policy(session: Session, proposal: AutonomousTestProposal) -> dict[str, Any]:
    try:
        from orchestrator.services.autonomous_proposal_review import AutonomousProposalReviewService

        return AutonomousProposalReviewService(session, base_dir=REPOSITORY_ROOT).build_review_context(proposal)
    except Exception:
        logger.debug("Unable to build proposal review context before auto-materialization.", exc_info=True)
        return {}


def _validate_materialize_path_for_policy(requested_path: str, test_type: str) -> str:
    normalized = str(requested_path or "").replace("\\", "/").strip().lstrip("/")
    if not normalized or normalized.startswith("../") or "/../" in normalized:
        raise ValueError("Materialization path must stay inside the repository.")
    suffixes = {
        "api": (".spec.ts", ".test.ts", ".py"),
        "unit": (".spec.ts", ".test.ts", ".py"),
        "e2e": (".spec.ts", ".test.ts"),
        "regression": (".spec.ts", ".test.ts"),
        "security": (".spec.ts", ".test.ts", ".py"),
        "accessibility": (".spec.ts", ".test.ts"),
    }.get(test_type, (".spec.ts", ".test.ts", ".py"))
    if not normalized.endswith(suffixes):
        raise ValueError(f"Unsupported generated test extension for {test_type}: {normalized}")
    if not normalized.startswith(("tests/", "orchestrator/tests/", "web/tests/", "e2e/")):
        raise ValueError("Auto-materialized tests must be written under an approved test directory.")
    return normalized


def _validate_materialized_proposal(proposal: AutonomousTestProposal) -> dict[str, Any]:
    relative_path = proposal.materialized_file_path
    if not relative_path:
        return {"status": "not_run", "reason": "proposal has no materialized file"}
    path = (REPOSITORY_ROOT / relative_path).resolve()
    if not path.exists():
        return {"status": "failed", "reason": "materialized file is missing", "path": relative_path}

    artifact_dir = _validation_artifact_dir(proposal)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = artifact_dir / "stdout.log"
    stderr_path = artifact_dir / "stderr.log"
    metadata_path = artifact_dir / "metadata.json"
    playwright_output_dir = artifact_dir / "playwright-output"
    base_url = _validation_base_url(proposal)
    server_process: subprocess.Popen[str] | None = None
    server_info: dict[str, Any] = {"base_url": base_url}
    if path.suffix == ".py":
        command = ["python", "-m", "pytest", relative_path, "-q"]
    elif relative_path.endswith((".spec.ts", ".test.ts")):
        package_json = REPOSITORY_ROOT / "package.json"
        web_package_json = REPOSITORY_ROOT / "web" / "package.json"
        if package_json.exists():
            command = ["npx", "playwright", "test", relative_path]
        elif web_package_json.exists():
            command = ["npm", "--prefix", "web", "exec", "playwright", "test", str(Path("..") / relative_path)]
        else:
            return {"status": "not_run", "reason": "no Node package found for Playwright validation", "path": relative_path}
        command.extend(["--trace", "retain-on-failure", "--output", str(playwright_output_dir)])
    else:
        return {"status": "not_run", "reason": "no validator for file type", "path": relative_path}

    started_at = _utcnow()
    try:
        if relative_path.endswith((".spec.ts", ".test.ts")):
            server_process, server_info = _ensure_validation_server(base_url)
        env = os.environ.copy()
        if base_url:
            env.setdefault("PLAYWRIGHT_BASE_URL", base_url)
            env.setdefault("BASE_URL", base_url)
        completed = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=PROPOSAL_VALIDATION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        result = {
            "status": "failed",
            "reason": "validation_timeout",
            "command": command,
            "stdout": stdout[-4000:],
            "stderr": stderr[-4000:],
            "base_url": base_url,
            "server": server_info,
        }
        return _finalize_validation_artifacts(
            proposal=proposal,
            artifact_dir=artifact_dir,
            metadata_path=metadata_path,
            result=result,
            started_at=started_at,
            completed_at=_utcnow(),
        )
    finally:
        _stop_validation_server(server_process)
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    result = {
        "status": "passed" if completed.returncode == 0 else "failed",
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
        "base_url": base_url,
        "server": server_info,
    }
    return _finalize_validation_artifacts(
        proposal=proposal,
        artifact_dir=artifact_dir,
        metadata_path=metadata_path,
        result=result,
        started_at=started_at,
        completed_at=_utcnow(),
    )


def _validation_artifact_dir(proposal: AutonomousTestProposal) -> Path:
    safe_id = slugify(proposal.id or f"proposal-{uuid.uuid4().hex}")
    stamp = _utcnow().strftime("%Y%m%d%H%M%S")
    return RUNS_DIR / "autonomous_validation" / safe_id / stamp


def _finalize_validation_artifacts(
    *,
    proposal: AutonomousTestProposal,
    artifact_dir: Path,
    metadata_path: Path,
    result: dict[str, Any],
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    metadata = {
        "proposal_id": proposal.id,
        "mission_id": proposal.mission_id,
        "project_id": proposal.project_id,
        "status": result.get("status"),
        "command": result.get("command"),
        "base_url": result.get("base_url"),
        "server": result.get("server"),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    metadata_path.write_text(json.dumps(metadata, default=str, indent=2), encoding="utf-8")
    artifacts = _collect_validation_artifacts(artifact_dir)
    log_path = _artifact_url_for_file(artifact_dir / "stdout.log")
    trace = next((artifact for artifact in artifacts if artifact["path"].endswith(".zip") or "trace" in artifact["path"]), None)
    result.update(
        {
            "artifacts": artifacts,
            "log_path": log_path,
            "trace_path": trace["path"] if trace else None,
            "artifact_dir": _artifact_url_for_file(artifact_dir),
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
        }
    )
    return result


def _collect_validation_artifacts(artifact_dir: Path) -> list[dict[str, Any]]:
    if not artifact_dir.exists():
        return []
    artifacts: list[dict[str, Any]] = []
    for path in sorted(item for item in artifact_dir.rglob("*") if item.is_file()):
        label = path.name
        suffix = path.suffix.lower()
        artifact_type = "log" if suffix in {".log", ".txt", ".json"} else "artifact"
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            artifact_type = "image"
        elif suffix in {".webm", ".mp4"}:
            artifact_type = "video"
        elif suffix == ".zip" or "trace" in path.name.lower():
            artifact_type = "trace"
        artifacts.append(
            {
                "label": label,
                "type": artifact_type,
                "path": _artifact_url_for_file(path),
                "size_bytes": path.stat().st_size,
                "created_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            }
        )
    return artifacts[:100]


def _artifact_url_for_file(path: Path) -> str:
    try:
        relative = path.relative_to(RUNS_DIR)
    except ValueError:
        return str(path)
    return f"/artifacts/{relative.as_posix()}"


def _validation_base_url(proposal: AutonomousTestProposal) -> str | None:
    configured = os.environ.get("AUTONOMOUS_VALIDATION_BASE_URL")
    if configured:
        return configured.rstrip("/")
    target_url = str(proposal.target_url or "").strip()
    if target_url:
        return target_url.rstrip("/")
    if (REPOSITORY_ROOT / "web" / "package.json").exists():
        return "http://127.0.0.1:3000"
    return None


def _ensure_validation_server(base_url: str | None) -> tuple[subprocess.Popen[str] | None, dict[str, Any]]:
    if not base_url:
        return None, {"status": "not_needed", "reason": "no_base_url"}
    parsed = urlparse(base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return None, {"status": "not_started", "reason": "non_local_base_url", "base_url": base_url}
    if _url_is_reachable(base_url):
        return None, {"status": "already_running", "base_url": base_url}
    command = _validation_server_command(parsed)
    if not command:
        return None, {"status": "not_started", "reason": "no_dev_server_command", "base_url": base_url}
    process = subprocess.Popen(
        command,
        cwd=REPOSITORY_ROOT,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + float(os.environ.get("AUTONOMOUS_VALIDATION_SERVER_READY_SECONDS", "45"))
    while time.time() < deadline:
        if process.poll() is not None:
            return process, {
                "status": "failed_to_start",
                "base_url": base_url,
                "command": command,
                "returncode": process.returncode,
            }
        if _url_is_reachable(base_url):
            return process, {"status": "started", "base_url": base_url, "command": command, "pid": process.pid}
        time.sleep(0.5)
    return process, {"status": "start_timeout", "base_url": base_url, "command": command, "pid": process.pid}


def _validation_server_command(parsed_url) -> list[str] | None:
    configured = os.environ.get("AUTONOMOUS_VALIDATION_DEV_SERVER_COMMAND")
    if configured:
        return shlex.split(configured)
    web_package_json = REPOSITORY_ROOT / "web" / "package.json"
    if not web_package_json.exists():
        return None
    hostname = parsed_url.hostname or "127.0.0.1"
    port = parsed_url.port or 3000
    return ["npm", "--prefix", "web", "run", "dev", "--", "--hostname", hostname, "--port", str(port)]


def _url_is_reachable(url: str) -> bool:
    try:
        request = Request(url, headers={"User-Agent": "quorvex-autonomous-validator"})
        with urlopen(request, timeout=2) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False


def _stop_validation_server(process: subprocess.Popen[str] | None) -> None:
    if not process or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def _create_validation_failure_work_item(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    proposal: AutonomousTestProposal,
    validation: dict[str, Any],
) -> AutonomousAgentWorkItem | None:
    planner_key = f"proposal_validation_failure:{proposal.id}"
    if _planner_work_item_exists(session, mission.id, planner_key):
        return None
    return _create_planned_work_item(
        session,
        mission,
        run,
        planner_key=planner_key,
        role="spec_writer",
        objective=(
            f"Repair generated test proposal {proposal.id} at {proposal.materialized_file_path}. "
            "Use the validation output to propose a corrected spec; do not write repository files."
        ),
        priority=12,
        surfaces=[proposal.target_url or ""],
        metadata={"proposal_id": proposal.id, "validation": validation},
    )


def autonomous_health_diagnostics(session: Session, project_id: str | None = None) -> dict[str, Any]:
    requirement_statement = select(Requirement)
    rtm_statement = select(RtmEntry)
    work_item_statement = select(AutonomousAgentWorkItem)
    proposal_statement = select(AutonomousTestProposal)
    if project_id:
        requirement_statement = requirement_statement.where(Requirement.project_id == project_id)
        rtm_statement = rtm_statement.where(RtmEntry.project_id == project_id)
        work_item_statement = work_item_statement.where(AutonomousAgentWorkItem.project_id == project_id)
        proposal_statement = proposal_statement.where(AutonomousTestProposal.project_id == project_id)

    requirements = session.exec(requirement_statement).all()
    entries = session.exec(rtm_statement).all()
    work_items = session.exec(work_item_statement).all()
    proposals = session.exec(proposal_statement).all()

    entries_by_requirement: dict[int, list[RtmEntry]] = {}
    for entry in entries:
        entries_by_requirement.setdefault(entry.requirement_id, []).append(entry)

    canonical_counts: dict[str, int] = {}
    for requirement in requirements:
        if requirement.canonical_key:
            canonical_counts[requirement.canonical_key] = canonical_counts.get(requirement.canonical_key, 0) + 1
    now = _utcnow()
    stale_after = now - timedelta(minutes=DEFAULT_WORK_ITEM_STALE_MINUTES)
    stale_work_items = [
        item.id
        for item in work_items
        if item.status == "running" and _work_item_is_stale(item, now=now, stale_after=stale_after)
    ]
    unmapped_requirements = [
        requirement.id
        for requirement in requirements
        if requirement.id is not None and not any(entry.mapping_type == "full" for entry in entries_by_requirement.get(requirement.id, []))
    ]
    diagnostics = {
        "project_id": project_id,
        "requirements": {
            "total": len(requirements),
            "missing_canonical_key": sum(1 for requirement in requirements if not requirement.canonical_key),
            "duplicate_canonical_keys": sum(1 for count in canonical_counts.values() if count > 1),
            "unmapped_full_coverage": len(unmapped_requirements),
            "unmapped_requirement_ids": unmapped_requirements[:100],
        },
        "rtm": {
            "total_entries": len(entries),
            "missing_dedupe_key": sum(1 for entry in entries if not entry.dedupe_key),
        },
        "work_items": {
            "total": len(work_items),
            "stale_running": len(stale_work_items),
            "stale_work_item_ids": stale_work_items[:100],
            "recovered": sum(1 for item in work_items if item.recovery_count or (item.progress or {}).get("recovered_from_work_item_id")),
        },
        "proposals": {
            "total": len(proposals),
            "materialized": sum(1 for proposal in proposals if proposal.approval_status == "materialized"),
            "auto_materialized": sum(1 for proposal in proposals if proposal.materialized_by == "autonomous_policy"),
            "validation_failed": sum(1 for proposal in proposals if proposal.validation_status == "failed"),
            "validation_blocked": sum(1 for proposal in proposals if proposal.validation_status == "blocked"),
            "validation_not_run": sum(1 for proposal in proposals if proposal.validation_status in {"", "not_run", None}),
        },
    }
    diagnostics["status"] = _diagnostics_status(diagnostics)
    return diagnostics


def recover_autonomous_project_stale_work(session: Session, project_id: str) -> dict[str, int]:
    summary = {"missions_checked": 0, "stale_recovered_count": 0}
    missions = session.exec(
        select(AutonomousMission).where(
            AutonomousMission.project_id == project_id,
            col(AutonomousMission.status).in_(("running", "error", "paused")),
        )
    ).all()
    for mission in missions:
        run = _latest_mission_run(session, mission)
        if not run:
            continue
        summary["missions_checked"] += 1
        recovered = _recover_stale_work_items(session, mission, run)
        summary["stale_recovered_count"] += recovered
    return summary


def monitor_autonomous_project(session: Session, project_id: str) -> dict[str, Any]:
    before = autonomous_health_diagnostics(session, project_id=project_id)
    recovery = recover_autonomous_project_stale_work(session, project_id)
    after = autonomous_health_diagnostics(session, project_id=project_id)
    now = _utcnow()
    status = _diagnostics_status(after)
    missions = session.exec(select(AutonomousMission).where(AutonomousMission.project_id == project_id)).all()
    for mission in missions:
        config = mission.config
        config["autonomous_monitor"] = {
            "last_monitor_at": now.isoformat(),
            "diagnostics_status": status,
            "stale_running_count": after["work_items"]["stale_running"],
            "failed_validation_count": after["proposals"]["validation_failed"],
            "duplicate_canonical_count": after["requirements"]["duplicate_canonical_keys"],
            "unmapped_confirmed_requirement_count": after["requirements"]["unmapped_full_coverage"],
            "validation_artifact_count": _validation_artifact_count(session, mission.id),
        }
        mission.config = config
        mission.health_status = "degraded" if status != "healthy" else "healthy"
        mission.last_heartbeat_at = now
        mission.updated_at = now
        session.add(mission)
        if status != "healthy" or recovery["stale_recovered_count"]:
            emit_mission_event(
                mission,
                "Autonomous health monitor completed with attention items.",
                event_type="monitor",
                payload={"status": status, "recovery": recovery, "diagnostics": after},
            )
    session.commit()
    return {
        "project_id": project_id,
        "status": status,
        "recovery": recovery,
        "before": before,
        "diagnostics": after,
        "monitored_at": now.isoformat(),
    }


def _latest_mission_run(session: Session, mission: AutonomousMission) -> AutonomousMissionRun | None:
    if mission.latest_run_id:
        run = session.get(AutonomousMissionRun, mission.latest_run_id)
        if run:
            return run
    return session.exec(
        select(AutonomousMissionRun)
        .where(AutonomousMissionRun.mission_id == mission.id)
        .order_by(col(AutonomousMissionRun.created_at).desc())
        .limit(1)
    ).first()


def _diagnostics_status(diagnostics: dict[str, Any]) -> str:
    if diagnostics["work_items"]["stale_running"] or diagnostics["proposals"]["validation_failed"]:
        return "critical"
    if (
        diagnostics["requirements"]["duplicate_canonical_keys"]
        or diagnostics["requirements"]["missing_canonical_key"]
        or diagnostics["rtm"]["missing_dedupe_key"]
        or diagnostics["proposals"]["validation_blocked"]
    ):
        return "attention"
    return "healthy"


def _validation_artifact_count(session: Session, mission_id: str) -> int:
    proposals = session.exec(select(AutonomousTestProposal).where(AutonomousTestProposal.mission_id == mission_id)).all()
    return sum(len(proposal.validation_artifacts) for proposal in proposals)


def backfill_autonomous_canonical_state(
    session: Session,
    project_id: str | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    summary = {
        "dry_run": dry_run,
        "requirements_backfilled": 0,
        "rtm_entries_backfilled": 0,
        "app_map_backfilled": 0,
        "app_map_ambiguous": 0,
        "requirements_duplicate_skipped": 0,
        "rtm_entries_duplicate_skipped": 0,
    }
    requirement_statement = select(Requirement)
    rtm_statement = select(RtmEntry)
    app_map_statement = select(ApplicationMap)
    if project_id:
        requirement_statement = requirement_statement.where(Requirement.project_id == project_id)
        rtm_statement = rtm_statement.where(RtmEntry.project_id == project_id)
        app_map_statement = app_map_statement.where(ApplicationMap.project_id == project_id)

    requirement_keys = {
        (requirement.project_id, requirement.canonical_key)
        for requirement in session.exec(requirement_statement).all()
        if requirement.canonical_key
    }
    requirements = session.exec(requirement_statement).all()
    for requirement in requirements:
        if requirement.canonical_key:
            continue
        canonical_key = _requirement_fingerprint(
            {
                "title": requirement.title,
                "category": requirement.category,
                "acceptance_criteria": requirement.acceptance_criteria,
            }
        )
        key_tuple = (requirement.project_id, canonical_key)
        if key_tuple in requirement_keys:
            summary["requirements_duplicate_skipped"] += 1
            continue
        requirement_keys.add(key_tuple)
        if dry_run:
            summary["requirements_backfilled"] += 1
            continue
        requirement.canonical_key = canonical_key
        requirement.updated_at = _utcnow()
        session.add(requirement)
        summary["requirements_backfilled"] += 1

    rtm_entries = session.exec(rtm_statement).all()
    rtm_keys = {(entry.project_id, entry.dedupe_key) for entry in rtm_entries if entry.dedupe_key}
    for entry in rtm_entries:
        if entry.dedupe_key:
            continue
        dedupe_key = _stable_dedupe_hash(
            entry.project_id or project_id or "default",
            "rtm",
            entry.requirement_id,
            entry.test_spec_name,
            entry.test_spec_path,
        )
        key_tuple = (entry.project_id, dedupe_key)
        if key_tuple in rtm_keys:
            summary["rtm_entries_duplicate_skipped"] += 1
            continue
        rtm_keys.add(key_tuple)
        if dry_run:
            summary["rtm_entries_backfilled"] += 1
            continue
        entry.dedupe_key = dedupe_key
        entry.updated_at = _utcnow()
        session.add(entry)
        summary["rtm_entries_backfilled"] += 1

    projects = session.exec(select(Project)).all()
    inferred_project_id = project_id or (projects[0].id if len(projects) == 1 else None)
    for app_map in session.exec(app_map_statement).all():
        if not app_map.project_id and inferred_project_id:
            if dry_run:
                summary["app_map_backfilled"] += 1
                continue
            app_map.project_id = inferred_project_id
        if not app_map.project_id:
            summary["app_map_ambiguous"] += 1
            continue
        if not app_map.app_surface_key:
            if dry_run:
                summary["app_map_backfilled"] += 1
                continue
            app_map.app_surface_key = _stable_dedupe_hash(
                "surface",
                app_map.project_id or "default",
                _route_from_url(app_map.url) or app_map.url,
            )
            session.add(app_map)
            summary["app_map_backfilled"] += 1

    if not dry_run:
        session.commit()
    return summary


def _create_test_proposal(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    *,
    source_type: str,
    source_id: str,
    title: str,
    rationale: str | None,
    target_url: str | None,
    risk_level: str,
    finding_id: str | None = None,
    coverage_gap_id: int | None = None,
    approval_id: str | None = None,
    source_metadata: dict[str, Any] | None = None,
) -> AutonomousTestProposal | None:
    test_type = _infer_test_type(source_type, title, rationale or "", target_url)
    route = _route_from_url(target_url)
    proposal_key = f"{mission.project_id}|{source_type}|{source_id}|{test_type}|{target_url or route or ''}"
    dedupe_key = hashlib.sha256(proposal_key.encode("utf-8")).hexdigest()[:32]
    existing = session.exec(
        select(AutonomousTestProposal).where(
            AutonomousTestProposal.project_id == mission.project_id,
            AutonomousTestProposal.dedupe_key == dedupe_key,
        )
    ).first()
    if existing:
        return None

    safe_title = title[:140] if title else "Autonomous test proposal"
    suggested_file_path = _suggested_file_path(test_type, safe_title)
    generated_spec_content = _generate_spec_content(
        test_type=test_type,
        title=safe_title,
        rationale=rationale or safe_title,
        target_url=target_url or _default_target_url(mission),
        route=route,
    )
    now = _utcnow()
    proposal = AutonomousTestProposal(
        id=f"amprop-{uuid.uuid4().hex[:12]}",
        mission_id=mission.id,
        run_id=run.id,
        project_id=mission.project_id,
        finding_id=finding_id,
        coverage_gap_id=coverage_gap_id,
        approval_id=approval_id,
        title=safe_title,
        target_url=target_url,
        route=route,
        test_type=test_type,
        rationale=rationale or safe_title,
        generated_spec_content=generated_spec_content,
        suggested_file_path=suggested_file_path,
        risk_level=_normalize_risk(risk_level),
        approval_status="pending",
        dedupe_key=dedupe_key,
        source_type=source_type,
        source_id=source_id,
        source_metadata_json=json.dumps(source_metadata or {}),
        created_at=now,
        updated_at=now,
    )
    session.add(proposal)
    return proposal


def _infer_test_type(source_type: str, title: str, rationale: str, target_url: str | None) -> str:
    text = f"{source_type} {title} {rationale} {target_url or ''}".lower()
    if "accessibility" in text or "a11y" in text or "aria" in text:
        return "accessibility"
    if "security" in text or "xss" in text or "csrf" in text or "auth" in text:
        return "security"
    if "unit" in text:
        return "unit"
    if "/api/" in text or " endpoint" in text or "http " in text or "json" in text:
        return "api"
    if "regression" in text:
        return "regression"
    return "e2e"


def _generate_spec_content(*, test_type: str, title: str, rationale: str, target_url: str, route: str | None) -> str:
    if test_type in {"api", "unit"}:
        return _generate_pytest_content(title=title, rationale=rationale, target_url=target_url, route=route)
    return _generate_playwright_content(test_type=test_type, title=title, rationale=rationale, target_url=target_url)


def _generate_playwright_content(*, test_type: str, title: str, rationale: str, target_url: str) -> str:
    suite = _title_case(title)
    test_name = f"{test_type} coverage for {title}".strip()
    return f"""import {{ test, expect }} from '@playwright/test';

test.describe({json.dumps(suite)}, () => {{
  test({json.dumps(test_name)}, async ({{ page }}) => {{
    page.on('dialog', async dialog => {{
      await dialog.accept();
    }});

    const response = await page.goto({json.dumps(target_url)}, {{
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    }});

    expect(response, 'navigation response should exist').not.toBeNull();
    expect(response!.status(), 'page should return a non-error HTTP status').toBeLessThan(500);

    await expect(page.locator('body')).toBeVisible();
    const bodyText = (await page.locator('body').innerText()).trim();
    expect(bodyText.length, {json.dumps(rationale[:120] or 'page should render visible content')}).toBeGreaterThan(0);
  }});
}});
"""


def _generate_pytest_content(*, title: str, rationale: str, target_url: str, route: str | None) -> str:
    parsed = urlparse(target_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "http://localhost:8000"
    route_path = route or parsed.path or "/"
    test_name = slugify(title).replace("-", "_") or "autonomous_api_proposal"
    if test_name[0].isdigit():
        test_name = f"autonomous_{test_name}"
    rationale_comment = _python_comment_block("Rationale", rationale)
    return f'''"""Generated autonomous test proposal."""

import os
from urllib import request as urllib_request

{rationale_comment}

def test_{test_name}_responds_successfully():
    base_url = os.environ.get("AUTONOMOUS_API_BASE_URL", {json.dumps(base_url)})
    url = base_url.rstrip("/") + {json.dumps(route_path)}

    with urllib_request.urlopen(url, timeout=30) as response:
        assert response.status < 500
'''


def _python_comment_block(label: str, value: str) -> str:
    lines = str(value or "").splitlines() or [""]
    safe_lines = [line.replace("\r", " ").replace("\t", " ") for line in lines]
    return "\n".join(f"# {label}: {line}" if index == 0 else f"# {line}" for index, line in enumerate(safe_lines))


def _suggested_file_path(test_type: str, title: str) -> str:
    slug = (slugify(title) or "autonomous-test")[:90].strip("-") or "autonomous-test"
    if test_type in {"api", "unit"}:
        return f"orchestrator/tests/generated/test_{slug.replace('-', '_')}.py"
    suffix = ".api.spec.ts" if test_type == "api" else ".spec.ts"
    return f"tests/generated/{slug}{suffix}"


def _route_from_url(target_url: str | None) -> str | None:
    if not target_url:
        return None
    parsed = urlparse(target_url)
    route = parsed.path or "/"
    return f"{route}?{parsed.query}" if parsed.query else route


def _coverage_gap_matches_mission(gap: CoverageGap, mission: AutonomousMission) -> bool:
    target_urls = mission.target_urls
    if not target_urls:
        return True
    if not gap.url:
        return False
    gap_parsed = urlparse(gap.url)
    if not gap_parsed.scheme or not gap_parsed.netloc:
        return False
    for target_url in target_urls:
        target_parsed = urlparse(target_url)
        if not target_parsed.scheme or not target_parsed.netloc:
            continue
        if gap_parsed.netloc != target_parsed.netloc:
            continue
        target_path = (target_parsed.path or "/").rstrip("/")
        gap_path = gap_parsed.path or "/"
        if target_path in {"", "/"} or gap_path == target_path or gap_path.startswith(f"{target_path}/"):
            return True
    return False


def _default_target_url(mission: AutonomousMission) -> str:
    return (mission.target_urls or ["http://localhost:3000"])[0]


def _normalize_risk(value: str | None) -> str:
    normalized = (value or "medium").lower()
    return normalized if normalized in {"critical", "high", "medium", "low", "info"} else "medium"


def _title_case(value: str) -> str:
    return " ".join(word.capitalize() for word in (slugify(value).replace("-", " ").split() or ["Autonomous", "Test"]))


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def complete_mission_run(payload: dict[str, Any]) -> None:
    run_id = payload["run_id"]
    summary = payload.get("summary") or {}
    project_id = None
    with Session(engine) as session:
        run = session.get(AutonomousMissionRun, run_id)
        if not run:
            return
        project_id = run.project_id
        now = _utcnow()
        run.status = "completed"
        run.current_stage = "completed"
        run.summary = summary
        run.completed_at = now
        run.updated_at = now
        mission = session.get(AutonomousMission, run.mission_id)
        if mission:
            mission.status = "running"
            mission.health_status = "healthy"
            mission.paused_reason = None
            mission.consecutive_failures = 0
            mission.current_stage = "idle"
            mission.next_action = "Waiting for the next scheduled mission run."
            mission.last_heartbeat_at = now
            mission.last_error = None
            mission.updated_at = now
            session.add(mission)
        session.add(run)
        session.commit()
    _attribute_autonomous_memory_outcome(
        project_id=project_id,
        run_id=run_id,
        success=True,
        outcome_status="autonomous_mission_completed",
    )


def _attribute_autonomous_memory_outcome(
    *,
    project_id: str | None,
    run_id: str | None,
    success: bool,
    outcome_status: str,
) -> None:
    if os.environ.get("MEMORY_ENABLED", "true").lower() != "true" or not run_id:
        return
    try:
        from orchestrator.memory.effectiveness import get_memory_effectiveness_service

        get_memory_effectiveness_service().attribute_outcome(
            project_id=project_id,
            success=success,
            outcome_status=outcome_status,
            stage="agent_runner",
            run_id=run_id,
        )
    except Exception:
        logger.debug("Autonomous memory outcome attribution skipped", exc_info=True)


def fail_mission_run(payload: dict[str, Any]) -> None:
    run_id = payload.get("run_id")
    mission_id = payload.get("mission_id")
    error = payload.get("error") or "Autonomous mission failed"
    project_id = None
    with Session(engine) as session:
        now = _utcnow()
        if run_id:
            run = session.get(AutonomousMissionRun, run_id)
            if run:
                if run.status == "failed":
                    return
                run.status = "failed"
                run.current_stage = "failed"
                run.error_message = error
                run.completed_at = now
                run.updated_at = now
                project_id = run.project_id
                session.add(run)
        if mission_id:
            mission = session.get(AutonomousMission, mission_id)
            if mission:
                mission.consecutive_failures += 1
                max_failures = _config_int(mission.config, "max_consecutive_failures", DEFAULT_MAX_CONSECUTIVE_FAILURES)
                if mission.consecutive_failures >= max_failures:
                    mission.status = "paused"
                    mission.health_status = "blocked"
                    mission.paused_reason = "consecutive_failures"
                    mission.next_action = "Inspect the latest run error, then resume the mission."
                else:
                    mission.status = "error"
                    mission.health_status = "degraded"
                    mission.paused_reason = None
                    mission.next_action = "The workflow will retry on the next scheduled iteration."
                mission.current_stage = "failed"
                mission.last_heartbeat_at = now
                mission.last_error = error
                mission.updated_at = now
                session.add(mission)
        session.commit()
    _attribute_autonomous_memory_outcome(
        project_id=project_id,
        run_id=run_id,
        success=False,
        outcome_status="autonomous_mission_failed",
    )


def update_mission_status(payload: dict[str, Any]) -> None:
    mission_id = payload["mission_id"]
    status = payload["status"]
    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        if not mission:
            return
        now = _utcnow()
        mission.status = status
        if "health_status" in payload:
            mission.health_status = payload["health_status"]
        if "paused_reason" in payload:
            mission.paused_reason = payload["paused_reason"]
        if "current_stage" in payload:
            mission.current_stage = payload["current_stage"]
        if "next_action" in payload:
            mission.next_action = payload["next_action"]
        mission.last_heartbeat_at = now
        mission.updated_at = now
        session.add(mission)
        session.commit()


def update_mission_heartbeat(payload: dict[str, Any]) -> None:
    mission_id = payload["mission_id"]
    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        if not mission:
            return
        now = _utcnow()
        stage = payload.get("current_stage")
        if stage:
            mission.current_stage = stage
            mission.next_action = payload.get("next_action") or _stage_next_action(stage)
        if payload.get("health_status"):
            mission.health_status = payload["health_status"]
        mission.last_heartbeat_at = now
        mission.updated_at = now
        session.add(mission)
        session.commit()


def compute_next_delay_seconds(mission_id: str) -> int:
    """Return the delay before the next mission iteration."""
    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        if not mission:
            return 0
        if not mission.schedule_cron:
            now_naive = _utcnow()
            delay_seconds = (
                _config_int(mission.config, "loop_delay_seconds", 300)
                if _whole_app_team_enabled(mission)
                else 24 * 60 * 60
            )
            delay_seconds = max(30, min(delay_seconds, 24 * 60 * 60))
            mission.next_run_at = now_naive + timedelta(seconds=delay_seconds)
            mission.current_stage = "sleeping"
            mission.next_action = _stage_next_action("sleeping")
            mission.last_heartbeat_at = now_naive
            mission.updated_at = now_naive
            session.add(mission)
            session.commit()
            return delay_seconds
        try:
            from orchestrator.services.scheduler import get_next_n_run_times

            next_runs = get_next_n_run_times(mission.schedule_cron, mission.timezone, count=1)
            if not next_runs:
                return 24 * 60 * 60
            next_run = next_runs[0]
            now = datetime.now(timezone.utc)
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=timezone.utc)
            mission.next_run_at = next_run.replace(tzinfo=None)
            mission.current_stage = "sleeping"
            mission.next_action = _stage_next_action("sleeping")
            mission.last_heartbeat_at = _utcnow()
            mission.updated_at = mission.last_heartbeat_at
            session.add(mission)
            session.commit()
            return max(1, int((next_run - now).total_seconds()))
        except Exception as exc:
            logger.warning("Failed to compute next autonomous mission delay for %s: %s", mission_id, exc)
            return 24 * 60 * 60


def count_pending_mission_approvals(mission_id: str) -> int:
    with Session(engine) as session:
        return len(
            session.exec(
                select(AutonomousApproval).where(
                    AutonomousApproval.mission_id == mission_id,
                    AutonomousApproval.status == "pending",
                )
            ).all()
        )


def _config_int(config: dict[str, Any], key: str, default: int) -> int:
    try:
        return max(1, int(config.get(key, default)))
    except (TypeError, ValueError):
        return default
