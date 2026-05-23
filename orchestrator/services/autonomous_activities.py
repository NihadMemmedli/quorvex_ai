"""Temporal activities for persistent autonomous testing missions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import (
    AutonomousAgentWorkItem,
    AutonomousApproval,
    AutonomousFinding,
    AutonomousMission,
    AutonomousMissionRun,
    AutonomousTestProposal,
    CoverageGap,
    ExplorationSession,
    Requirement,
)
from orchestrator.services.autonomous_events import emit_work_item_status_event
from orchestrator.utils.string_utils import slugify

logger = logging.getLogger(__name__)

MAX_PROPOSALS_PER_ITERATION = 5
VALID_TEST_TYPES = {"e2e", "api", "regression", "security", "accessibility", "unit"}
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3
DEFAULT_MAX_PENDING_APPROVALS = 25
DEFAULT_MAX_PARALLEL_AGENTS = 2
DEFAULT_WORK_ITEM_BATCH_SIZE = 7
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
            "notes": [],
        }

        if _whole_app_team_enabled(mission):
            _update_run_checkpoint(session, mission, run, "team_supervising")
            team_summary = _run_parallel_team_supervisor(session, mission, run)
            for key in ("work_items_created", "work_items_enqueued", "work_items_completed", "work_items_blocked"):
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
    return max(1, min(configured, 12))


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
        "findings_created": 0,
        "active_count": 0,
        "completed_count": 0,
        "blocked_count": 0,
    }
    summary["work_items_completed"] = _sync_agent_work_items(session, mission)
    if summary["work_items_completed"]:
        summary["findings_created"] = _create_findings_from_completed_work_items(session, mission, run)

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
            )
            item.progress = {"phase": "created", "message": "Waiting for an available agent worker."}
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
    return f"""You are the {item.role} agent in a Quorvex autonomous QA team.

Mission: {mission.name}
Objective: {item.objective}
Target surfaces: {', '.join(surfaces or ['project data and known app artifacts'])}
{revision_note}

Work only by inspecting the app/project through available tools. Do not write repository files.
Return a concise report with these sections:
- summary
- findings
- requirements
- rtm_candidates
- test_proposals
- blockers

Every proposed file or repository change must be a proposal only. The human approval flow will materialize files later.
"""


def _allowed_tools_for_work_item(item: AutonomousAgentWorkItem) -> list[str]:
    try:
        from orchestrator.utils.agent_tool_allowlists import get_agent_allowed_tools

        allowed = get_agent_allowed_tools(item.role)
        if allowed:
            return allowed
    except Exception:
        logger.debug("Could not resolve autonomous role tool profile for %s", item.role, exc_info=True)
    return ["Glob", "Grep", "Read", "LS"]


def _enqueue_agent_work_item(
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
    item.updated_at = now
    item.progress = {"phase": "queued", "message": "Agent task has been queued.", "agent_task_id": task_id}
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
            completed_count += 1
            session.add(item)
            emit_work_item_status_event(item, "Agent completed this assignment.", event_type="complete")
        elif task.status in {AgentTaskStatus.FAILED, AgentTaskStatus.TIMEOUT, AgentTaskStatus.CANCELLED}:
            item.status = "cancelled" if task.status == AgentTaskStatus.CANCELLED else "failed"
            item.error_message = task.error or f"Agent task {task.status.value}"
            item.completed_at = task.completed_at or now
            item.progress = {"phase": item.status, "message": item.error_message}
            item.updated_at = now
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
    with Session(engine) as session:
        run = session.get(AutonomousMissionRun, run_id)
        if not run:
            return
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


def fail_mission_run(payload: dict[str, Any]) -> None:
    run_id = payload.get("run_id")
    mission_id = payload.get("mission_id")
    error = payload.get("error") or "Autonomous mission failed"
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
