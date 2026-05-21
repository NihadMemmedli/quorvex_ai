"""Autonomous testing mission API."""

from __future__ import annotations

import json
import logging
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from .db import engine, get_session
from .middleware.auth import get_current_user, get_current_user_optional
from .middleware.permissions import EDIT_ROLES, check_project_access
from .models_auth import User
from .models_db import (
    AutonomousAgentWorkItem,
    AutonomousApproval,
    AutonomousFinding,
    AutonomousMission,
    AutonomousMissionRun,
    AutonomousTestProposal,
    Project,
    Requirement,
    RtmEntry,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/autonomous", tags=["autonomous"])
BASE_DIR = Path(__file__).resolve().parent.parent.parent

MISSION_TYPES = {"coverage", "exploration", "regression", "flake_triage", "mixed"}
AUTONOMY_LEVELS = {"draft_validate"}
APPROVAL_POLICIES = {"approval_required"}
TEST_PROPOSAL_STATUSES = {"pending", "approved", "rejected", "materialized"}
TEST_PROPOSAL_TYPES = {"e2e", "api", "regression", "security", "accessibility", "unit"}


class AutonomousMissionCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    mission_type: str = "mixed"
    target_urls: list[str] = Field(default_factory=list)
    schedule_cron: str | None = None
    timezone: str = "UTC"
    max_runtime_minutes: int = Field(default=60, ge=1, le=1440)
    max_iterations: int = Field(default=0, ge=0, le=100000)
    max_llm_budget_usd: float | None = Field(default=None, ge=0)
    autonomy_level: str = "draft_validate"
    approval_policy: str = "approval_required"
    config: dict[str, Any] = Field(default_factory=dict)


class AutonomousMissionUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    target_urls: list[str] | None = None
    schedule_cron: str | None = None
    timezone: str | None = None
    max_runtime_minutes: int | None = Field(default=None, ge=1, le=1440)
    max_iterations: int | None = Field(default=None, ge=0, le=100000)
    max_llm_budget_usd: float | None = Field(default=None, ge=0)
    config: dict[str, Any] | None = None


class ApprovalDecisionRequest(BaseModel):
    comment: str | None = None


class TestProposalDecisionRequest(BaseModel):
    comment: str | None = None


class TestProposalMaterializeRequest(BaseModel):
    file_path: str | None = None
    overwrite: bool = False
    comment: str | None = None


def _require_project(project_id: str, session: Session) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _validate_mission_input(req: AutonomousMissionCreateRequest) -> None:
    if req.mission_type not in MISSION_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported mission_type: {req.mission_type}")
    if req.autonomy_level not in AUTONOMY_LEVELS:
        raise HTTPException(status_code=400, detail="Only draft_validate autonomy is supported in v1")
    if req.approval_policy not in APPROVAL_POLICIES:
        raise HTTPException(status_code=400, detail="Only approval_required policy is supported in v1")
    if req.schedule_cron:
        try:
            from orchestrator.services.scheduler import get_next_n_run_times

            get_next_n_run_times(req.schedule_cron, req.timezone, count=1)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_mission_update(req: AutonomousMissionUpdateRequest, mission: AutonomousMission) -> None:
    schedule_cron = req.schedule_cron if req.schedule_cron is not None else mission.schedule_cron
    timezone = req.timezone if req.timezone is not None else mission.timezone
    if schedule_cron:
        try:
            from orchestrator.services.scheduler import get_next_n_run_times

            get_next_n_run_times(schedule_cron, timezone or "UTC", count=1)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def _mission_to_response(mission: AutonomousMission, session: Session | None = None) -> dict[str, Any]:
    return {
        "id": mission.id,
        "project_id": mission.project_id,
        "name": mission.name,
        "description": mission.description,
        "mission_type": mission.mission_type,
        "status": mission.status,
        "target_urls": mission.target_urls,
        "schedule_cron": mission.schedule_cron,
        "timezone": mission.timezone,
        "autonomy_level": mission.autonomy_level,
        "approval_policy": mission.approval_policy,
        "max_runtime_minutes": mission.max_runtime_minutes,
        "max_iterations": mission.max_iterations,
        "max_llm_budget_usd": mission.max_llm_budget_usd,
        "budget_used_usd": mission.budget_used_usd,
        "latest_workflow_id": mission.latest_workflow_id,
        "latest_run_id": mission.latest_run_id,
        "last_run_at": mission.last_run_at.isoformat() if mission.last_run_at else None,
        "next_run_at": mission.next_run_at.isoformat() if mission.next_run_at else None,
        "last_error": mission.last_error,
        "health_status": mission.health_status,
        "paused_reason": mission.paused_reason,
        "consecutive_failures": mission.consecutive_failures,
        "last_heartbeat_at": mission.last_heartbeat_at.isoformat() if mission.last_heartbeat_at else None,
        "current_stage": mission.current_stage,
        "next_action": mission.next_action,
        "total_runs": mission.total_runs,
        "total_findings": mission.total_findings,
        "team_summary": _team_summary_for_mission(mission, session),
        "active_work_items": _recent_work_items_for_mission(mission.id, {"queued", "running"}, session, limit=8),
        "blocked_work_items": _recent_work_items_for_mission(mission.id, {"failed", "blocked"}, session, limit=8),
        "coverage_summary": _coverage_summary_for_project(mission.project_id, session),
        "created_by": mission.created_by,
        "created_at": mission.created_at.isoformat(),
        "updated_at": mission.updated_at.isoformat(),
    }


def _run_to_response(run: AutonomousMissionRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "mission_id": run.mission_id,
        "project_id": run.project_id,
        "workflow_id": run.workflow_id,
        "mission_type": run.mission_type,
        "trigger_type": run.trigger_type,
        "status": run.status,
        "current_stage": run.current_stage,
        "summary": run.summary,
        "artifacts": run.artifacts,
        "error_message": run.error_message,
        "budget_used_usd": run.budget_used_usd,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


def _finding_to_response(finding: AutonomousFinding) -> dict[str, Any]:
    return {
        "id": finding.id,
        "mission_id": finding.mission_id,
        "run_id": finding.run_id,
        "project_id": finding.project_id,
        "finding_type": finding.finding_type,
        "severity": finding.severity,
        "title": finding.title,
        "description": finding.description,
        "status": finding.status,
        "confidence": finding.confidence,
        "dedupe_key": finding.dedupe_key,
        "evidence": finding.evidence,
        "source_type": finding.source_type,
        "source_id": finding.source_id,
        "approval_required": finding.approval_required,
        "external_issue_url": finding.external_issue_url,
        "created_at": finding.created_at.isoformat(),
        "updated_at": finding.updated_at.isoformat(),
    }


def _approval_to_response(approval: AutonomousApproval) -> dict[str, Any]:
    return {
        "id": approval.id,
        "mission_id": approval.mission_id,
        "run_id": approval.run_id,
        "finding_id": approval.finding_id,
        "project_id": approval.project_id,
        "action_type": approval.action_type,
        "status": approval.status,
        "requested_payload": approval.requested_payload,
        "response": approval.response,
        "decided_by": approval.decided_by,
        "requested_at": approval.requested_at.isoformat(),
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
    }


def _proposal_to_response(proposal: AutonomousTestProposal) -> dict[str, Any]:
    return {
        "id": proposal.id,
        "mission_id": proposal.mission_id,
        "run_id": proposal.run_id,
        "project_id": proposal.project_id,
        "finding_id": proposal.finding_id,
        "coverage_gap_id": proposal.coverage_gap_id,
        "approval_id": proposal.approval_id,
        "title": proposal.title,
        "target_url": proposal.target_url,
        "route": proposal.route,
        "test_type": proposal.test_type,
        "rationale": proposal.rationale,
        "generated_spec_content": proposal.generated_spec_content,
        "suggested_file_path": proposal.suggested_file_path,
        "risk_level": proposal.risk_level,
        "approval_status": proposal.approval_status,
        "source_type": proposal.source_type,
        "source_id": proposal.source_id,
        "source_metadata": proposal.source_metadata,
        "materialized_file_path": proposal.materialized_file_path,
        "materialization_result": proposal.materialization_result,
        "approved_by": proposal.approved_by,
        "approved_at": proposal.approved_at.isoformat() if proposal.approved_at else None,
        "rejected_by": proposal.rejected_by,
        "rejected_at": proposal.rejected_at.isoformat() if proposal.rejected_at else None,
        "materialized_by": proposal.materialized_by,
        "materialized_at": proposal.materialized_at.isoformat() if proposal.materialized_at else None,
        "created_at": proposal.created_at.isoformat(),
        "updated_at": proposal.updated_at.isoformat(),
    }


def _work_item_to_response(item: AutonomousAgentWorkItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "mission_id": item.mission_id,
        "run_id": item.run_id,
        "project_id": item.project_id,
        "role": item.role,
        "lane": item.role,
        "title": item.role.replace("_", " ").title(),
        "objective": item.objective,
        "summary": item.objective,
        "assigned_surface": item.assigned_surface,
        "status": item.status,
        "priority": item.priority,
        "owner_agent": item.role,
        "agent_task_id": item.agent_task_id,
        "progress": item.progress,
        "artifacts": item.artifacts,
        "result": item.result,
        "blocked_reason": item.error_message,
        "error_message": item.error_message,
        "attempt_count": item.attempt_count,
        "budget_used_usd": item.budget_used_usd,
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def _with_session(session: Session | None):
    if session is not None:
        return session, False
    return Session(engine), True


def _team_summary_for_mission(mission: AutonomousMission, session: Session | None = None) -> dict[str, Any]:
    db, should_close = _with_session(session)
    try:
        items = db.exec(select(AutonomousAgentWorkItem).where(AutonomousAgentWorkItem.mission_id == mission.id)).all()
    finally:
        if should_close:
            db.close()
    by_status: dict[str, int] = {}
    by_role: dict[str, dict[str, Any]] = {}
    for item in items:
        by_status[item.status] = by_status.get(item.status, 0) + 1
        role = by_role.setdefault(item.role, {"role": item.role, "total": 0, "active": 0, "completed": 0, "blocked": 0})
        role["total"] += 1
        if item.status in {"queued", "running"}:
            role["active"] += 1
        elif item.status == "completed":
            role["completed"] += 1
        elif item.status in {"failed", "blocked", "cancelled"}:
            role["blocked"] += 1
    config = mission.config
    configured_roles = config.get("roles") if isinstance(config.get("roles"), list) else []
    return {
        "enabled": bool(config.get("whole_app_team") or config.get("team_mode") == "whole_app" or items),
        "roles": configured_roles or [role["role"] for role in by_role.values()],
        "max_parallel_agents": config.get("max_parallel_agents", 2),
        "total": len(items),
        "active_count": sum(by_status.get(status, 0) for status in ("queued", "running")),
        "completed_count": by_status.get("completed", 0),
        "blocked_count": sum(by_status.get(status, 0) for status in ("failed", "blocked", "cancelled")),
        "by_status": by_status,
        "lanes": list(by_role.values()),
    }


def _recent_work_items_for_mission(
    mission_id: str,
    statuses: set[str] | None = None,
    session: Session | None = None,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    db, should_close = _with_session(session)
    try:
        statement = select(AutonomousAgentWorkItem).where(AutonomousAgentWorkItem.mission_id == mission_id)
        if statuses:
            statement = statement.where(col(AutonomousAgentWorkItem.status).in_(tuple(statuses)))
        items = db.exec(statement.order_by(col(AutonomousAgentWorkItem.updated_at).desc()).limit(limit)).all()
        return [_work_item_to_response(item) for item in items]
    finally:
        if should_close:
            db.close()


def _coverage_summary_for_project(project_id: str | None, session: Session | None = None) -> dict[str, Any]:
    if not project_id:
        return {"total_requirements": 0, "covered": 0, "partial": 0, "uncovered": 0, "coverage_percentage": 0.0}
    db, should_close = _with_session(session)
    try:
        requirements = db.exec(select(Requirement).where(Requirement.project_id == project_id)).all()
        entries = db.exec(select(RtmEntry).where(RtmEntry.project_id == project_id)).all()
    finally:
        if should_close:
            db.close()
    total = len(requirements)
    if total == 0:
        return {"total_requirements": 0, "covered": 0, "partial": 0, "uncovered": 0, "coverage_percentage": 0.0}
    mapping_by_requirement: dict[int, set[str]] = {}
    for entry in entries:
        mapping_by_requirement.setdefault(entry.requirement_id, set()).add(entry.mapping_type)
    covered = 0
    partial = 0
    for requirement in requirements:
        mappings = mapping_by_requirement.get(int(requirement.id or 0), set())
        if "full" in mappings:
            covered += 1
        elif mappings:
            partial += 1
    uncovered = max(0, total - covered - partial)
    return {
        "total_requirements": total,
        "covered": covered,
        "partial": partial,
        "uncovered": uncovered,
        "coverage_percentage": round(((covered + partial * 0.5) / total) * 100, 1),
    }


@router.get("/{project_id}/missions")
def list_missions(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    _require_project(project_id, session)
    missions = session.exec(
        select(AutonomousMission)
        .where(AutonomousMission.project_id == project_id)
        .order_by(col(AutonomousMission.created_at).desc())
    ).all()
    return [_mission_to_response(mission, session) for mission in missions]


@router.post("/{project_id}/missions")
async def create_mission(
    project_id: str,
    req: AutonomousMissionCreateRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    _require_project(project_id, session)
    await _require_project_edit(project_id, current_user, session)
    _validate_mission_input(req)

    mission = AutonomousMission(
        id=f"am-{uuid.uuid4().hex[:12]}",
        project_id=project_id,
        name=req.name.strip(),
        description=req.description,
        mission_type=req.mission_type,
        target_urls_json=json.dumps(req.target_urls),
        schedule_cron=req.schedule_cron,
        timezone=req.timezone,
        autonomy_level=req.autonomy_level,
        approval_policy=req.approval_policy,
        max_runtime_minutes=req.max_runtime_minutes,
        max_iterations=req.max_iterations,
        max_llm_budget_usd=req.max_llm_budget_usd,
        config_json=json.dumps(req.config),
        status="paused",
        health_status="healthy",
        paused_reason="created_paused",
        current_stage="created",
        next_action="Start the mission when the target URLs are ready.",
        created_by=str(current_user.id) if current_user else None,
    )
    session.add(mission)
    session.commit()
    session.refresh(mission)
    return _mission_to_response(mission, session)


@router.get("/{project_id}/missions/{mission_id}")
def get_mission(
    project_id: str,
    mission_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    mission = _get_project_mission(project_id, mission_id, session)
    return _mission_to_response(mission, session)


@router.get("/{project_id}/missions/{mission_id}/status")
async def get_mission_status(
    project_id: str,
    mission_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    mission = _get_project_mission(project_id, mission_id, session)
    pending_approvals = session.exec(
        select(AutonomousApproval).where(
            AutonomousApproval.mission_id == mission_id,
            AutonomousApproval.status == "pending",
        )
    ).all()
    latest_run = session.get(AutonomousMissionRun, mission.latest_run_id) if mission.latest_run_id else None

    temporal_status: dict[str, Any] = {"available": False, "workflow_status": None, "error": None}
    if mission.latest_workflow_id:
        try:
            from orchestrator.services.temporal_client import (
                TemporalUnavailableError,
                describe_autonomous_mission_workflow,
            )

            temporal_status = await describe_autonomous_mission_workflow(mission.latest_workflow_id)
        except TemporalUnavailableError as exc:
            temporal_status["error"] = str(exc)

    health_status = _derive_health_status(mission, pending_approval_count=len(pending_approvals), temporal_status=temporal_status)
    return {
        "mission": {**_mission_to_response(mission, session), "health_status": health_status},
        "temporal": temporal_status,
        "latest_run": _run_to_response(latest_run) if latest_run else None,
        "blocking_approvals": [_approval_to_response(approval) for approval in pending_approvals[:10]],
        "pending_approval_count": len(pending_approvals),
        "worker_available": temporal_status["available"],
        "next_action": _derive_next_action(mission, len(pending_approvals), health_status, temporal_status),
    }


@router.patch("/{project_id}/missions/{mission_id}")
async def update_mission(
    project_id: str,
    mission_id: str,
    req: AutonomousMissionUpdateRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    mission = _get_project_mission(project_id, mission_id, session)
    await _require_project_edit(project_id, current_user, session)
    if mission.status == "running":
        raise HTTPException(status_code=409, detail="Pause the mission before editing it")
    _validate_mission_update(req, mission)

    for field in ("name", "description", "schedule_cron", "timezone", "max_runtime_minutes", "max_iterations", "max_llm_budget_usd"):
        value = getattr(req, field)
        if value is not None:
            setattr(mission, field, value)
    if req.target_urls is not None:
        mission.target_urls = req.target_urls
    if req.config is not None:
        mission.config = req.config
    mission.updated_at = datetime.utcnow()
    session.add(mission)
    session.commit()
    session.refresh(mission)
    return _mission_to_response(mission, session)


@router.delete("/{project_id}/missions/{mission_id}")
async def delete_mission(
    project_id: str,
    mission_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    mission = _get_project_mission(project_id, mission_id, session)
    await _require_project_edit(project_id, current_user, session)
    if mission.status == "running":
        await _signal_mission(mission, "cancel")
    for proposal in session.exec(select(AutonomousTestProposal).where(AutonomousTestProposal.mission_id == mission_id)).all():
        session.delete(proposal)
    for approval in session.exec(select(AutonomousApproval).where(AutonomousApproval.mission_id == mission_id)).all():
        session.delete(approval)
    for finding in session.exec(select(AutonomousFinding).where(AutonomousFinding.mission_id == mission_id)).all():
        session.delete(finding)
    for run in session.exec(select(AutonomousMissionRun).where(AutonomousMissionRun.mission_id == mission_id)).all():
        session.delete(run)
    session.delete(mission)
    session.commit()
    return {"status": "deleted", "mission_id": mission_id}


@router.post("/{project_id}/missions/{mission_id}/start")
async def start_mission(
    project_id: str,
    mission_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    from orchestrator.services.temporal_client import TemporalUnavailableError, start_autonomous_mission_workflow

    mission = _get_project_mission(project_id, mission_id, session)
    await _require_project_edit(project_id, current_user, session)
    if mission.status == "running":
        return _mission_to_response(mission, session)

    try:
        started = await start_autonomous_mission_workflow(mission.id)
    except TemporalUnavailableError as exc:
        mission.status = "error"
        mission.last_error = str(exc)
        mission.updated_at = datetime.utcnow()
        session.add(mission)
        session.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    mission.status = "running"
    mission.latest_workflow_id = started.workflow_id
    mission.last_error = None
    mission.health_status = "healthy"
    mission.paused_reason = None
    mission.current_stage = "starting"
    mission.next_action = "Mission is starting on the Temporal worker."
    mission.last_heartbeat_at = datetime.utcnow()
    mission.updated_at = datetime.utcnow()
    session.add(mission)
    session.commit()
    session.refresh(mission)
    return _mission_to_response(mission, session)


@router.post("/{project_id}/missions/{mission_id}/pause")
async def pause_mission(
    project_id: str,
    mission_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    mission = _get_project_mission(project_id, mission_id, session)
    await _require_project_edit(project_id, current_user, session)
    await _signal_mission(mission, "pause")
    await _pause_mission_work_items(mission.id, session)
    mission.status = "paused"
    mission.health_status = "blocked"
    mission.paused_reason = "manual_pause"
    mission.current_stage = "paused"
    mission.next_action = "Resume the mission when you want it to continue."
    mission.updated_at = datetime.utcnow()
    session.add(mission)
    session.commit()
    session.refresh(mission)
    return _mission_to_response(mission, session)


@router.post("/{project_id}/missions/{mission_id}/resume")
async def resume_mission(
    project_id: str,
    mission_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    mission = _get_project_mission(project_id, mission_id, session)
    await _require_project_edit(project_id, current_user, session)
    if mission.latest_workflow_id:
        await _signal_mission(mission, "resume")
        await _resume_mission_work_items(mission.id, session)
        mission.status = "running"
        mission.health_status = "healthy"
        mission.paused_reason = None
        mission.current_stage = "resuming"
        mission.next_action = "Mission is resuming."
        mission.last_heartbeat_at = datetime.utcnow()
        mission.updated_at = datetime.utcnow()
        session.add(mission)
        session.commit()
        session.refresh(mission)
        return _mission_to_response(mission, session)
    return await start_mission(project_id, mission_id, session, current_user)


@router.post("/{project_id}/missions/{mission_id}/cancel")
async def cancel_mission(
    project_id: str,
    mission_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    mission = _get_project_mission(project_id, mission_id, session)
    await _require_project_edit(project_id, current_user, session)
    await _signal_mission(mission, "cancel")
    await _cancel_mission_work_items(mission.id, session)
    mission.status = "cancelled"
    mission.health_status = "blocked"
    mission.paused_reason = "cancelled"
    mission.current_stage = "cancelled"
    mission.next_action = None
    mission.updated_at = datetime.utcnow()
    session.add(mission)
    session.commit()
    session.refresh(mission)
    return _mission_to_response(mission, session)


@router.get("/{project_id}/missions/{mission_id}/runs")
def list_mission_runs(
    project_id: str,
    mission_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    _get_project_mission(project_id, mission_id, session)
    runs = session.exec(
        select(AutonomousMissionRun)
        .where(AutonomousMissionRun.mission_id == mission_id)
        .order_by(col(AutonomousMissionRun.created_at).desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [_run_to_response(run) for run in runs]


@router.get("/{project_id}/missions/{mission_id}/findings")
def list_mission_findings(
    project_id: str,
    mission_id: str,
    status: str | None = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    _get_project_mission(project_id, mission_id, session)
    statement = select(AutonomousFinding).where(AutonomousFinding.mission_id == mission_id)
    if status:
        statement = statement.where(AutonomousFinding.status == status)
    findings = session.exec(statement.order_by(col(AutonomousFinding.created_at).desc())).all()
    return [_finding_to_response(finding) for finding in findings]


@router.get("/{project_id}/missions/{mission_id}/work-items")
def list_mission_work_items(
    project_id: str,
    mission_id: str,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    _get_project_mission(project_id, mission_id, session)
    statement = select(AutonomousAgentWorkItem).where(AutonomousAgentWorkItem.mission_id == mission_id)
    if status:
        statement = statement.where(AutonomousAgentWorkItem.status == status)
    items = session.exec(
        statement.order_by(col(AutonomousAgentWorkItem.updated_at).desc()).offset(offset).limit(limit)
    ).all()
    return [_work_item_to_response(item) for item in items]


@router.get("/{project_id}/work-items")
def list_project_work_items(
    project_id: str,
    status: str | None = Query(default=None),
    mission_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    _require_project(project_id, session)
    statement = select(AutonomousAgentWorkItem).where(AutonomousAgentWorkItem.project_id == project_id)
    if status:
        statement = statement.where(AutonomousAgentWorkItem.status == status)
    if mission_id:
        statement = statement.where(AutonomousAgentWorkItem.mission_id == mission_id)
    items = session.exec(
        statement.order_by(col(AutonomousAgentWorkItem.updated_at).desc()).offset(offset).limit(limit)
    ).all()
    return [_work_item_to_response(item) for item in items]


@router.post("/{project_id}/work-items/{work_item_id}/retry")
async def retry_work_item(
    project_id: str,
    work_item_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    item = _get_project_work_item(project_id, work_item_id, session)
    if item.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Work item is already active")
    now = datetime.utcnow()
    item.status = "queued"
    item.agent_task_id = None
    item.error_message = None
    item.completed_at = None
    item.progress = {"phase": "queued", "message": "Retry requested; mission supervisor will enqueue this assignment."}
    item.updated_at = now
    session.add(item)
    session.commit()
    session.refresh(item)
    return _work_item_to_response(item)


@router.post("/{project_id}/work-items/{work_item_id}/cancel")
async def cancel_work_item(
    project_id: str,
    work_item_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    item = _get_project_work_item(project_id, work_item_id, session)
    if item.agent_task_id:
        await _cancel_agent_task(item.agent_task_id)
    now = datetime.utcnow()
    item.status = "cancelled"
    item.error_message = "Cancelled by user"
    item.completed_at = now
    item.progress = {"phase": "cancelled", "message": "Work item was cancelled."}
    item.updated_at = now
    session.add(item)
    session.commit()
    session.refresh(item)
    return _work_item_to_response(item)


@router.get("/{project_id}/approvals")
def list_approvals(
    project_id: str,
    status: str | None = Query(default="pending"),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    _require_project(project_id, session)
    statement = select(AutonomousApproval).where(AutonomousApproval.project_id == project_id)
    if status:
        statement = statement.where(AutonomousApproval.status == status)
    approvals = session.exec(statement.order_by(col(AutonomousApproval.requested_at).desc())).all()
    return [_approval_to_response(approval) for approval in approvals]


@router.get("/{project_id}/proposals")
def list_test_proposals(
    project_id: str,
    status: str | None = Query(default=None),
    mission_id: str | None = Query(default=None),
    test_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    _require_project(project_id, session)
    if status and status not in TEST_PROPOSAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Unsupported proposal status: {status}")
    if test_type and test_type not in TEST_PROPOSAL_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported test_type: {test_type}")
    statement = select(AutonomousTestProposal).where(AutonomousTestProposal.project_id == project_id)
    if status:
        statement = statement.where(AutonomousTestProposal.approval_status == status)
    if mission_id:
        statement = statement.where(AutonomousTestProposal.mission_id == mission_id)
    if test_type:
        statement = statement.where(AutonomousTestProposal.test_type == test_type)
    proposals = session.exec(
        statement.order_by(col(AutonomousTestProposal.created_at).desc()).offset(offset).limit(limit)
    ).all()
    return [_proposal_to_response(proposal) for proposal in proposals]


@router.get("/{project_id}/proposals/{proposal_id}")
def get_test_proposal(
    project_id: str,
    proposal_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    proposal = _get_project_proposal(project_id, proposal_id, session)
    return _proposal_to_response(proposal)


@router.post("/{project_id}/proposals/{proposal_id}/approve")
async def approve_test_proposal(
    project_id: str,
    proposal_id: str,
    req: TestProposalDecisionRequest | None = None,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    return _decide_test_proposal(project_id, proposal_id, "approved", req, session, current_user)


@router.post("/{project_id}/proposals/{proposal_id}/reject")
async def reject_test_proposal(
    project_id: str,
    proposal_id: str,
    req: TestProposalDecisionRequest | None = None,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    return _decide_test_proposal(project_id, proposal_id, "rejected", req, session, current_user)


@router.post("/{project_id}/proposals/{proposal_id}/materialize")
async def materialize_test_proposal(
    project_id: str,
    proposal_id: str,
    req: TestProposalMaterializeRequest | None = None,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    proposal = _get_project_proposal(project_id, proposal_id, session)
    if proposal.approval_status == "materialized":
        return _proposal_to_response(proposal)
    if proposal.approval_status != "approved":
        raise HTTPException(status_code=409, detail="Approve the proposal before materializing it")

    requested_path = req.file_path if req and req.file_path else proposal.suggested_file_path
    relative_path = _validate_materialize_path(requested_path, proposal.test_type)
    target = (BASE_DIR / relative_path).resolve()
    try:
        target.relative_to(BASE_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Materialization path must stay inside the repository") from exc
    if target.exists() and not (req and req.overwrite):
        raise HTTPException(status_code=409, detail=f"File already exists: {relative_path}")

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as temp_file:
        temp_file.write(proposal.generated_spec_content)
        temp_path = Path(temp_file.name)
    temp_path.replace(target)

    now = datetime.utcnow()
    proposal.approval_status = "materialized"
    proposal.materialized_file_path = relative_path
    proposal.materialized_at = now
    proposal.materialized_by = str(current_user.id) if current_user else None
    proposal.materialization_result = {
        "file_path": relative_path,
        "overwrite": bool(req.overwrite) if req else False,
        "comment": req.comment if req else None,
    }
    proposal.updated_at = now
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return _proposal_to_response(proposal)


@router.post("/{project_id}/approvals/{approval_id}/approve")
async def approve_action(
    project_id: str,
    approval_id: str,
    req: ApprovalDecisionRequest | None = None,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    return _decide_approval(project_id, approval_id, "approved", req, session, current_user)


@router.post("/{project_id}/approvals/{approval_id}/reject")
async def reject_action(
    project_id: str,
    approval_id: str,
    req: ApprovalDecisionRequest | None = None,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    return _decide_approval(project_id, approval_id, "rejected", req, session, current_user)


def _get_project_mission(project_id: str, mission_id: str, session: Session) -> AutonomousMission:
    _require_project(project_id, session)
    mission = session.get(AutonomousMission, mission_id)
    if not mission or mission.project_id != project_id:
        raise HTTPException(status_code=404, detail="Autonomous mission not found")
    return mission


def _get_project_proposal(project_id: str, proposal_id: str, session: Session) -> AutonomousTestProposal:
    _require_project(project_id, session)
    proposal = session.get(AutonomousTestProposal, proposal_id)
    if not proposal or proposal.project_id != project_id:
        raise HTTPException(status_code=404, detail="Autonomous test proposal not found")
    return proposal


def _get_project_work_item(project_id: str, work_item_id: str, session: Session) -> AutonomousAgentWorkItem:
    _require_project(project_id, session)
    item = session.get(AutonomousAgentWorkItem, work_item_id)
    if not item or item.project_id != project_id:
        raise HTTPException(status_code=404, detail="Autonomous work item not found")
    return item


async def _require_project_edit(project_id: str, current_user: User | None, session: Session) -> None:
    await check_project_access(project_id, current_user, EDIT_ROLES, session)


def _derive_health_status(
    mission: AutonomousMission,
    *,
    pending_approval_count: int,
    temporal_status: dict[str, Any] | None = None,
) -> str:
    if mission.status in {"cancelled", "completed"}:
        return "blocked"
    if mission.status in {"error"} or mission.consecutive_failures >= _max_consecutive_failures(mission):
        return "degraded"
    if mission.status == "paused" or pending_approval_count >= _max_pending_approvals(mission):
        return "blocked"
    if mission.status == "running" and temporal_status and not temporal_status.get("available"):
        return "offline"
    return mission.health_status or "healthy"


def _derive_next_action(
    mission: AutonomousMission,
    pending_approval_count: int,
    health_status: str,
    temporal_status: dict[str, Any] | None = None,
) -> str | None:
    if pending_approval_count >= _max_pending_approvals(mission):
        return "Review pending approvals before the mission creates more proposals."
    if mission.paused_reason:
        return mission.next_action or mission.paused_reason.replace("_", " ")
    if health_status == "offline":
        return temporal_status.get("error") if temporal_status else "Temporal worker is not reachable."
    if mission.next_action:
        return mission.next_action
    if mission.next_run_at:
        return "Waiting for the next scheduled run."
    return None


def _max_pending_approvals(mission: AutonomousMission) -> int:
    value = mission.config.get("max_pending_approvals", 25)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 25


def _max_consecutive_failures(mission: AutonomousMission) -> int:
    value = mission.config.get("max_consecutive_failures", 3)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 3


async def _signal_mission(mission: AutonomousMission, signal_name: str) -> None:
    if not mission.latest_workflow_id:
        return
    try:
        from orchestrator.services.temporal_client import TemporalUnavailableError, signal_autonomous_mission_workflow

        await signal_autonomous_mission_workflow(mission.latest_workflow_id, signal_name)
    except TemporalUnavailableError as exc:
        logger.warning("Could not signal Temporal workflow %s: %s", mission.latest_workflow_id, exc)


async def _cancel_agent_task(task_id: str) -> None:
    try:
        from orchestrator.services.agent_queue import get_agent_queue

        queue = get_agent_queue()
        await queue.connect()
        try:
            await queue.cancel_task(task_id)
        finally:
            await queue.disconnect()
    except Exception as exc:
        logger.warning("Could not cancel autonomous agent task %s: %s", task_id, exc)


async def _pause_agent_task(task_id: str) -> None:
    try:
        from orchestrator.services.agent_queue import get_agent_queue

        queue = get_agent_queue()
        await queue.connect()
        try:
            await queue.pause_task(task_id)
        finally:
            await queue.disconnect()
    except Exception as exc:
        logger.warning("Could not pause autonomous agent task %s: %s", task_id, exc)


async def _resume_agent_task(task_id: str) -> None:
    try:
        from orchestrator.services.agent_queue import get_agent_queue

        queue = get_agent_queue()
        await queue.connect()
        try:
            await queue.resume_task(task_id)
        finally:
            await queue.disconnect()
    except Exception as exc:
        logger.warning("Could not resume autonomous agent task %s: %s", task_id, exc)


async def _cancel_mission_work_items(mission_id: str, session: Session) -> None:
    items = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission_id,
            col(AutonomousAgentWorkItem.status).in_(("queued", "running")),
        )
    ).all()
    now = datetime.utcnow()
    for item in items:
        if item.agent_task_id:
            await _cancel_agent_task(item.agent_task_id)
        item.status = "cancelled"
        item.error_message = "Mission cancelled"
        item.completed_at = now
        item.updated_at = now
        item.progress = {"phase": "cancelled", "message": "Mission cancellation stopped this assignment."}
        session.add(item)
    session.commit()


async def _pause_mission_work_items(mission_id: str, session: Session) -> None:
    items = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission_id,
            col(AutonomousAgentWorkItem.status).in_(("queued", "running")),
        )
    ).all()
    now = datetime.utcnow()
    for item in items:
        if item.agent_task_id:
            await _pause_agent_task(item.agent_task_id)
        item.progress = {**item.progress, "phase": "paused", "message": "Mission is paused."}
        item.updated_at = now
        session.add(item)
    session.commit()


async def _resume_mission_work_items(mission_id: str, session: Session) -> None:
    items = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission_id,
            col(AutonomousAgentWorkItem.status).in_(("queued", "running")),
        )
    ).all()
    now = datetime.utcnow()
    for item in items:
        if item.agent_task_id:
            await _resume_agent_task(item.agent_task_id)
        item.progress = {**item.progress, "phase": "running", "message": "Mission is running."}
        item.updated_at = now
        session.add(item)
    session.commit()


def _decide_approval(
    project_id: str,
    approval_id: str,
    decision: str,
    req: ApprovalDecisionRequest | None,
    session: Session,
    current_user: User | None,
) -> dict[str, Any]:
    _require_project(project_id, session)
    approval = session.get(AutonomousApproval, approval_id)
    if not approval or approval.project_id != project_id:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="Approval has already been decided")

    now = datetime.utcnow()
    actor = str(current_user.id) if current_user else None
    approval.status = decision
    approval.decided_at = now
    approval.decided_by = str(current_user.id) if current_user else None
    approval.response = {"comment": req.comment if req else None}

    if approval.finding_id:
        _sync_finding_decision(session, project_id, approval.finding_id, decision, now)
    proposal_id = approval.requested_payload.get("proposal_id")
    if proposal_id:
        proposal = session.get(AutonomousTestProposal, str(proposal_id))
        if proposal and proposal.project_id == project_id and proposal.approval_status == "pending":
            proposal.approval_status = decision
            proposal.updated_at = now
            if decision == "approved":
                proposal.approved_at = now
                proposal.approved_by = actor
            else:
                proposal.rejected_at = now
                proposal.rejected_by = actor
            session.add(proposal)

    session.add(approval)
    session.commit()
    session.refresh(approval)
    return _approval_to_response(approval)


def _decide_test_proposal(
    project_id: str,
    proposal_id: str,
    decision: str,
    req: TestProposalDecisionRequest | None,
    session: Session,
    current_user: User | None,
) -> dict[str, Any]:
    proposal = _get_project_proposal(project_id, proposal_id, session)
    if proposal.approval_status != "pending":
        raise HTTPException(status_code=409, detail="Proposal has already been decided")

    now = datetime.utcnow()
    actor = str(current_user.id) if current_user else None
    proposal.approval_status = decision
    proposal.updated_at = now
    if decision == "approved":
        proposal.approved_at = now
        proposal.approved_by = actor
    else:
        proposal.rejected_at = now
        proposal.rejected_by = actor

    if proposal.approval_id:
        approval = session.get(AutonomousApproval, proposal.approval_id)
        if approval and approval.project_id == project_id and approval.status == "pending":
            approval.status = decision
            approval.decided_at = now
            approval.decided_by = actor
            approval.response = {"comment": req.comment if req else None, "proposal_id": proposal.id}
            session.add(approval)
    if proposal.finding_id:
        _sync_finding_decision(session, project_id, proposal.finding_id, decision, now)

    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return _proposal_to_response(proposal)


def _validate_materialize_path(raw_path: str, test_type: str) -> str:
    if test_type not in TEST_PROPOSAL_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported proposal test_type: {test_type}")
    candidate = raw_path.strip()
    if not candidate:
        raise HTTPException(status_code=400, detail="Materialization path is required")
    if len(candidate) > 180:
        raise HTTPException(status_code=400, detail="Materialization path is too long")
    if "\n" in candidate or "\r" in candidate or "\\" in candidate:
        raise HTTPException(status_code=400, detail="Materialization path contains unsafe characters")
    if re.search(r"[;&|`$<>]", candidate):
        raise HTTPException(status_code=400, detail="Materialization path contains unsafe characters")

    path = Path(candidate)
    if path.is_absolute() or ".." in path.parts:
        raise HTTPException(status_code=400, detail="Materialization path must be repo-relative")
    normalized = path.as_posix()
    if test_type in {"api", "unit"}:
        if not normalized.startswith("orchestrator/tests/generated/") or not normalized.endswith(".py"):
            raise HTTPException(
                status_code=400,
                detail="Pytest proposals must materialize under orchestrator/tests/generated/*.py",
            )
    elif not normalized.startswith("tests/generated/") or not normalized.endswith(".spec.ts"):
        raise HTTPException(
            status_code=400,
            detail="Playwright proposals must materialize under tests/generated/*.spec.ts",
        )
    return normalized


def _sync_finding_decision(
    session: Session,
    project_id: str,
    finding_id: str,
    decision: str,
    decided_at: datetime,
) -> None:
    finding = session.get(AutonomousFinding, finding_id)
    if finding and finding.project_id == project_id:
        finding.status = decision
        finding.updated_at = decided_at
        session.add(finding)
