"""Autonomous testing mission API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from orchestrator.services.autonomous_activities import (
    autonomous_health_diagnostics,
    backfill_autonomous_canonical_state,
    monitor_autonomous_project,
    recover_autonomous_project_stale_work,
)
from orchestrator.services.autonomous_events import (
    create_autonomous_agent_event,
    emit_mission_event,
    emit_work_item_status_event,
    event_to_response,
    list_events,
)
from orchestrator.services.autonomous_proposal_review import AutonomousProposalReviewService

from .db import engine, get_session
from .middleware.auth import get_current_user, get_current_user_optional
from .middleware.permissions import EDIT_ROLES, VIEW_ROLES, check_project_access
from .models_auth import User
from .models_db import (
    AutonomousAgentEvent,
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
APPROVAL_POLICIES = {"approval_required", "auto_materialize_low_risk"}
TEST_PROPOSAL_STATUSES = {"pending", "approved", "rejected", "materialized"}
TEST_PROPOSAL_TYPES = {"e2e", "api", "regression", "security", "accessibility", "unit"}
WORK_ITEM_REVIEW_DECISIONS = {"accepted", "rejected", "needs_revision"}
REVISION_PRIORITY_BOOST = 5


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


class FindingDecisionRequest(BaseModel):
    comment: str | None = None
    reviewer: str | None = None


class WorkItemReviewDecisionRequest(BaseModel):
    comment: str | None = None
    reviewer: str | None = None
    target_work_item_id: str | None = None


class TestProposalMaterializeRequest(BaseModel):
    file_path: str | None = None
    overwrite: bool = False
    override_blocking_duplicate: bool = False
    override_reason: str | None = None
    comment: str | None = None


class ProposalReviewRefreshRequest(BaseModel):
    mission_id: str | None = None
    status: str | None = None
    stale_only: bool = False
    duplicate_only: bool = False
    limit: int = Field(default=200, ge=1, le=500)


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
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported approval_policy: {req.approval_policy}. Supported policies: {sorted(APPROVAL_POLICIES)}",
        )
    _validate_mission_safety_config(req.target_urls, req.config)
    if req.schedule_cron:
        try:
            from orchestrator.services.scheduler import get_next_n_run_times

            get_next_n_run_times(req.schedule_cron, req.timezone, count=1)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_mission_update(req: AutonomousMissionUpdateRequest, mission: AutonomousMission) -> None:
    schedule_cron = req.schedule_cron if req.schedule_cron is not None else mission.schedule_cron
    timezone = req.timezone if req.timezone is not None else mission.timezone
    target_urls = req.target_urls if req.target_urls is not None else mission.target_urls
    config = req.config if req.config is not None else mission.config
    _validate_mission_safety_config(target_urls, config)
    if schedule_cron:
        try:
            from orchestrator.services.scheduler import get_next_n_run_times

            get_next_n_run_times(schedule_cron, timezone or "UTC", count=1)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def _mission_to_response(mission: AutonomousMission, session: Session | None = None) -> dict[str, Any]:
    team_summary = _team_summary_for_mission(mission, session)
    monitor_summary = (mission.config or {}).get("autonomous_monitor") or {}
    pending_revision_count = int(team_summary.get("pending_revision_count") or 0)
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
        "next_action": _derive_next_action(
            mission,
            0,
            mission.health_status or "healthy",
            pending_revision_count=pending_revision_count,
        ),
        "total_runs": mission.total_runs,
        "total_findings": mission.total_findings,
        "team_summary": team_summary,
        "monitor_summary": monitor_summary,
        "last_monitor_at": monitor_summary.get("last_monitor_at"),
        "diagnostics_status": monitor_summary.get("diagnostics_status"),
        "stale_running_count": monitor_summary.get("stale_running_count"),
        "failed_validation_count": monitor_summary.get("failed_validation_count"),
        "duplicate_canonical_count": monitor_summary.get("duplicate_canonical_count"),
        "unmapped_confirmed_requirement_count": monitor_summary.get("unmapped_confirmed_requirement_count"),
        "validation_artifact_count": monitor_summary.get("validation_artifact_count"),
        "active_work_items": _recent_work_items_for_mission(mission.id, {"queued", "running"}, session, limit=8),
        "blocked_work_items": _recent_work_items_for_mission(mission.id, {"failed", "blocked"}, session, limit=8),
        "coverage_summary": _coverage_summary_for_project(mission.project_id, session),
        "safety_summary": _mission_safety_summary(mission),
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


def _app_change_to_response(
    finding: AutonomousFinding,
    *,
    run: AutonomousMissionRun | None,
    proposal: AutonomousTestProposal | None,
    session: Session,
) -> dict[str, Any]:
    evidence = finding.evidence or {}
    kind = str(evidence.get("kind") or "memory_delta")
    change_type = str(evidence.get("change_type") or kind)
    current = evidence.get("current") if isinstance(evidence.get("current"), dict) else {}
    baseline = evidence.get("baseline") if isinstance(evidence.get("baseline"), dict) else {}
    requirement = None
    requirement_id = evidence.get("requirement_id")
    if requirement_id is not None:
        try:
            requirement_obj = session.get(Requirement, int(requirement_id))
            if requirement_obj:
                requirement = {
                    "id": requirement_obj.id,
                    "req_code": requirement_obj.req_code,
                    "title": requirement_obj.title,
                    "truth_state": getattr(requirement_obj, "truth_state", None),
                    "source_type": getattr(requirement_obj, "source_type", None),
                    "confidence": getattr(requirement_obj, "confidence", None),
                    "uncertainty_reason": getattr(requirement_obj, "uncertainty_reason", None),
                }
        except (TypeError, ValueError):
            requirement = None
    return {
        "id": finding.id,
        "kind": kind,
        "change_type": change_type,
        "mission_id": finding.mission_id,
        "run_id": finding.run_id,
        "run": _run_to_response(run) if run else None,
        "title": finding.title,
        "description": finding.description,
        "severity": finding.severity,
        "risk_level": evidence.get("risk_level") or finding.severity,
        "test_value": evidence.get("test_value") or "informational",
        "uncertainty_reason": evidence.get("uncertainty_reason"),
        "status": finding.status,
        "confidence": finding.confidence,
        "url": evidence.get("url") or current.get("url") or baseline.get("url"),
        "page_key": evidence.get("page_key"),
        "element_key": evidence.get("element_key"),
        "requirement_id": requirement_id,
        "requirement": requirement,
        "before": baseline,
        "after": current,
        "changed_fields": evidence.get("changed_fields") or evidence.get("drift") or {},
        "finding": _finding_to_response(finding),
        "proposal": _proposal_to_response(proposal, session) if proposal else None,
        "created_at": finding.created_at.isoformat(),
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


def _proposal_to_response(proposal: AutonomousTestProposal, session: Session | None = None) -> dict[str, Any]:
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
        "review_context": _proposal_review_context(proposal, session),
        "materialized_file_path": proposal.materialized_file_path,
        "materialization_result": proposal.materialization_result,
        "validation_status": proposal.validation_status,
        "validation_result": proposal.validation_result,
        "validation_artifacts": proposal.validation_artifacts,
        "validation_log_path": proposal.validation_log_path,
        "validation_trace_path": proposal.validation_trace_path,
        "validated_at": proposal.validated_at.isoformat() if proposal.validated_at else None,
        "approved_by": proposal.approved_by,
        "approved_at": proposal.approved_at.isoformat() if proposal.approved_at else None,
        "rejected_by": proposal.rejected_by,
        "rejected_at": proposal.rejected_at.isoformat() if proposal.rejected_at else None,
        "materialized_by": proposal.materialized_by,
        "materialized_at": proposal.materialized_at.isoformat() if proposal.materialized_at else None,
        "created_at": proposal.created_at.isoformat(),
        "updated_at": proposal.updated_at.isoformat(),
    }


def _normalize_domain(value: str) -> str:
    text = value.strip().lower()
    if not text:
        return ""
    parsed = urlparse(text if "://" in text else f"https://{text}")
    return (parsed.netloc or parsed.path).split("@")[-1].split(":")[0]


def _validate_mission_safety_config(target_urls: list[str], config: dict[str, Any] | None) -> None:
    cfg = config or {}
    allowed_domains = [_normalize_domain(str(item)) for item in cfg.get("allowed_domains", []) if str(item).strip()]
    allowed_domains = [domain for domain in allowed_domains if domain]
    allowed_routes = [str(item).strip() for item in cfg.get("allowed_routes", []) if str(item).strip()]
    blocked_routes = [str(item).strip() for item in cfg.get("blocked_routes", []) if str(item).strip()]
    for raw_url in target_urls:
        parsed = urlparse(str(raw_url))
        if not parsed.scheme or not parsed.netloc:
            raise HTTPException(status_code=400, detail=f"Target URL must be absolute: {raw_url}")
        target_domain = _normalize_domain(parsed.netloc)
        if allowed_domains and target_domain not in allowed_domains and not any(
            target_domain.endswith(f".{domain}") for domain in allowed_domains
        ):
            raise HTTPException(
                status_code=400,
                detail=f"Target URL domain {target_domain} is outside the allowed autonomous mission domains",
            )
        path = parsed.path or "/"
        if allowed_routes and not any(_route_matches(path, route) for route in allowed_routes):
            raise HTTPException(status_code=400, detail=f"Target URL route {path} is outside the allowed mission routes")
        if blocked_routes and any(_route_matches(path, route) for route in blocked_routes):
            raise HTTPException(status_code=400, detail=f"Target URL route {path} is blocked by the mission policy")


def _route_matches(path: str, route: str) -> bool:
    normalized_path = "/" + str(path or "/").lstrip("/")
    normalized_route = "/" + str(route or "").strip().lstrip("/")
    normalized_path = re.sub(r"/{2,}", "/", normalized_path)
    normalized_route = re.sub(r"/{2,}", "/", normalized_route)
    return normalized_path == normalized_route or normalized_path.startswith(normalized_route.rstrip("/") + "/")


def _mission_safety_summary(mission: AutonomousMission) -> dict[str, Any]:
    config = mission.config
    allowed_domains = config.get("allowed_domains")
    if not isinstance(allowed_domains, list) or not allowed_domains:
        allowed_domains = sorted({_normalize_domain(urlparse(url).netloc) for url in mission.target_urls if urlparse(url).netloc})
    allowed_routes = config.get("allowed_routes") if isinstance(config.get("allowed_routes"), list) else []
    blocked_routes = config.get("blocked_routes") if isinstance(config.get("blocked_routes"), list) else []
    approval_required_terms = (
        config.get("approval_required_terms") if isinstance(config.get("approval_required_terms"), list) else []
    )
    blocked_action_terms = config.get("blocked_action_terms") if isinstance(config.get("blocked_action_terms"), list) else []
    return {
        "environment": str(config.get("environment") or "staging"),
        "allowed_domains": [domain for domain in allowed_domains if domain],
        "allowed_routes": [str(route) for route in allowed_routes if str(route).strip()],
        "blocked_routes": [str(route) for route in blocked_routes if str(route).strip()],
        "read_only": bool(config.get("read_only", False)),
        "tool_profile": str(config.get("tool_profile") or "role_based"),
        "credential_scope": str(config.get("credential_scope") or "project"),
        "write_policy": str(config.get("write_policy") or "proposals_only"),
        "destructive_action_policy": str(config.get("destructive_action_policy") or "pause_for_approval"),
        "approval_required_terms": [str(term) for term in approval_required_terms if str(term).strip()],
        "blocked_action_terms": [str(term) for term in blocked_action_terms if str(term).strip()],
        "approval_policy": mission.approval_policy,
    }


def _proposal_review_context(proposal: AutonomousTestProposal, session: Session | None = None) -> dict[str, Any]:
    db, should_close = _with_session(session)
    try:
        return AutonomousProposalReviewService(db, base_dir=BASE_DIR).build_review_context(proposal)
    finally:
        if should_close:
            db.close()


def _linked_requirement_for_proposal(
    proposal: AutonomousTestProposal,
    finding: AutonomousFinding | None,
    session: Session,
) -> Requirement | None:
    requirement_id = None
    source_metadata = proposal.source_metadata or {}
    if source_metadata.get("requirement_id") is not None:
        requirement_id = source_metadata.get("requirement_id")
    elif finding and finding.evidence.get("requirement_id") is not None:
        requirement_id = finding.evidence.get("requirement_id")
    if requirement_id is None:
        return None
    try:
        return session.get(Requirement, int(requirement_id))
    except (TypeError, ValueError):
        return None


def _requirement_audit_response(requirement: Requirement | None) -> dict[str, Any] | None:
    if not requirement:
        return None
    return {
        "id": requirement.id,
        "req_code": requirement.req_code,
        "title": requirement.title,
        "truth_state": getattr(requirement, "truth_state", None),
        "source_type": getattr(requirement, "source_type", None),
        "confidence": getattr(requirement, "confidence", None),
        "uncertainty_reason": getattr(requirement, "uncertainty_reason", None),
        "confirmed_by": getattr(requirement, "confirmed_by", None),
        "confirmed_at": requirement.confirmed_at.isoformat() if getattr(requirement, "confirmed_at", None) else None,
        "rejected_by": getattr(requirement, "rejected_by", None),
        "rejected_at": requirement.rejected_at.isoformat() if getattr(requirement, "rejected_at", None) else None,
    }


def _work_item_revision_parent_id(item: AutonomousAgentWorkItem) -> str | None:
    result = item.result or {}
    progress = item.progress or {}
    parent_id = result.get("revision_of_work_item_id") or progress.get("revision_of_work_item_id")
    return str(parent_id) if parent_id else None


def _revision_chain_for_work_item(
    source_item: AutonomousAgentWorkItem | None,
    session: Session,
) -> list[dict[str, Any]]:
    if not source_item:
        return []
    items = session.exec(
        select(AutonomousAgentWorkItem).where(AutonomousAgentWorkItem.mission_id == source_item.mission_id)
    ).all()
    by_id = {item.id: item for item in items}
    chain: list[AutonomousAgentWorkItem] = []
    seen: set[str] = set()

    current: AutonomousAgentWorkItem | None = source_item
    while current and current.id not in seen:
        chain.insert(0, current)
        seen.add(current.id)
        current = by_id.get(_work_item_revision_parent_id(current) or "")

    changed = True
    while changed and len(chain) < 20:
        changed = False
        tail = chain[-1]
        children = [
            item
            for item in items
            if item.id not in seen and _work_item_revision_parent_id(item) == tail.id
        ]
        if children:
            child = sorted(children, key=lambda item: item.created_at)[0]
            chain.append(child)
            seen.add(child.id)
            changed = True
    return [_work_item_to_response(item) for item in chain]


def _source_work_item_for_proposal(
    proposal: AutonomousTestProposal,
    finding: AutonomousFinding | None,
    session: Session,
) -> AutonomousAgentWorkItem | None:
    candidate_id = None
    if proposal.source_type == "autonomous_work_item":
        candidate_id = proposal.source_id
    source_metadata = proposal.source_metadata or {}
    candidate_id = candidate_id or source_metadata.get("work_item_id")
    if not candidate_id and finding:
        evidence = finding.evidence or {}
        if finding.source_type == "autonomous_work_item":
            candidate_id = finding.source_id
        candidate_id = candidate_id or evidence.get("work_item_id")
    if not candidate_id:
        return None
    return session.get(AutonomousAgentWorkItem, str(candidate_id))


def _proposal_audit_response(proposal: AutonomousTestProposal, session: Session) -> dict[str, Any]:
    mission = session.get(AutonomousMission, proposal.mission_id)
    run = session.get(AutonomousMissionRun, proposal.run_id) if proposal.run_id else None
    finding = session.get(AutonomousFinding, proposal.finding_id) if proposal.finding_id else None
    approval = session.get(AutonomousApproval, proposal.approval_id) if proposal.approval_id else None
    source_work_item = _source_work_item_for_proposal(proposal, finding, session)
    linked_requirement = _linked_requirement_for_proposal(proposal, finding, session)
    events = list_events(
        project_id=str(proposal.project_id),
        mission_id=proposal.mission_id,
        limit=500,
        session=session,
    )
    source_work_item_id = proposal.source_id if proposal.source_type == "autonomous_work_item" else None
    relevant_events = [
        event
        for event in events
        if not source_work_item_id
        or event.work_item_id == source_work_item_id
        or event.work_item_id == (source_work_item.id if source_work_item else None)
        or event.run_id == proposal.run_id
        or event.event_type in {"review", "finding_review", "requirement_propagation"}
    ]
    review_events = [
        _event_to_response(event)
        for event in relevant_events
        if event.event_type in {"review", "finding_review", "requirement_propagation"}
    ]
    timeline: list[dict[str, Any]] = [
        {
            "type": "proposal_created",
            "at": proposal.created_at.isoformat(),
            "message": "Generated test proposal created.",
            "payload": {
                "status": proposal.approval_status,
                "source_type": proposal.source_type,
                "source_id": proposal.source_id,
                "suggested_file_path": proposal.suggested_file_path,
            },
        }
    ]
    if approval:
        timeline.append(
            {
                "type": "approval_requested",
                "at": approval.requested_at.isoformat(),
                "message": f"Approval requested for {approval.action_type}.",
                "payload": approval.requested_payload,
            }
        )
        if approval.decided_at:
            timeline.append(
                {
                    "type": f"approval_{approval.status}",
                    "at": approval.decided_at.isoformat(),
                    "message": f"Approval was {approval.status}.",
                    "payload": {"decided_by": approval.decided_by, "response": approval.response},
                }
            )
    if proposal.approved_at:
        timeline.append(
            {
                "type": "proposal_approved",
                "at": proposal.approved_at.isoformat(),
                "message": "Proposal approved.",
                "payload": {"approved_by": proposal.approved_by},
            }
        )
    if proposal.rejected_at:
        timeline.append(
            {
                "type": "proposal_rejected",
                "at": proposal.rejected_at.isoformat(),
                "message": "Proposal rejected.",
                "payload": {"rejected_by": proposal.rejected_by},
            }
        )
    if proposal.materialized_at:
        timeline.append(
            {
                "type": "proposal_materialized",
                "at": proposal.materialized_at.isoformat(),
                "message": "Proposal materialized into a repository file.",
                "payload": proposal.materialization_result,
            }
        )
    for event in relevant_events[-120:]:
        timeline.append(
            {
                "type": f"agent_{event.event_type}",
                "at": event.created_at.isoformat(),
                "message": event.message,
                "payload": {
                    "sequence": event.sequence,
                    "level": event.level,
                    "work_item_id": event.work_item_id,
                    "agent_task_id": event.agent_task_id,
                    "payload": event.payload,
                },
            }
        )
    timeline.sort(key=lambda item: item["at"] or "")
    return {
        "proposal": _proposal_to_response(proposal, session),
        "mission": _mission_to_response(mission, session) if mission else None,
        "run": _run_to_response(run) if run else None,
        "finding": _finding_to_response(finding) if finding else None,
        "approval": _approval_to_response(approval) if approval else None,
        "source_work_item": _work_item_to_response(source_work_item) if source_work_item else None,
        "revision_chain": _revision_chain_for_work_item(source_work_item, session),
        "linked_requirement": _requirement_audit_response(linked_requirement),
        "review_events": review_events,
        "timeline": timeline,
    }


def _work_item_to_response(item: AutonomousAgentWorkItem) -> dict[str, Any]:
    result = item.result or {}
    progress = item.progress or {}
    revision_of_work_item_id = _work_item_revision_parent_id(item)
    revision_work_item_id = result.get("revision_work_item_id") or progress.get("revision_work_item_id")
    revision_attempt = result.get("revision_attempt") or progress.get("revision_attempt")
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
        "planner_key": item.planner_key or progress.get("planner_key"),
        "progress": item.progress,
        "artifacts": item.artifacts,
        "result": result,
        "is_revision": bool(revision_of_work_item_id),
        "revision_of_work_item_id": revision_of_work_item_id,
        "revision_work_item_id": revision_work_item_id,
        "revision_attempt": revision_attempt,
        "review_decision": result.get("review_decision") or "none",
        "review_reason": result.get("review_reason"),
        "reviewed_by": result.get("reviewed_by"),
        "reviewed_at": result.get("reviewed_at"),
        "reviewed_role": result.get("reviewed_role"),
        "reviewed_work_item_id": result.get("reviewed_work_item_id"),
        "blocked_reason": item.error_message,
        "error_message": item.error_message,
        "attempt_count": item.attempt_count,
        "lease_until": item.lease_until.isoformat() if item.lease_until else None,
        "last_heartbeat_at": item.last_heartbeat_at.isoformat() if item.last_heartbeat_at else None,
        "recovery_count": item.recovery_count,
        "recovery_reason": item.recovery_reason or progress.get("recovery_reason"),
        "budget_used_usd": item.budget_used_usd,
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def _compact_preview(value: Any, limit: int = 260) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _work_item_output_preview(item: AutonomousAgentWorkItem) -> str:
    result = item.result or {}
    output = result.get("output") or result.get("summary") or result.get("message")
    if output:
        return _compact_preview(output)
    for artifact in item.artifacts:
        content = artifact.get("content") or artifact.get("summary")
        if content:
            return _compact_preview(content)
    return ""


def _work_item_timeline_response(
    item: AutonomousAgentWorkItem,
    events: list[AutonomousAgentEvent],
) -> dict[str, Any]:
    latest_event = events[-1] if events else None
    latest_output = next((event for event in reversed(events) if event.event_type == "assistant_output"), None)
    artifacts = item.artifacts
    primary_artifact = artifacts[0] if artifacts else None
    return {
        **_work_item_to_response(item),
        "latest_event": _event_to_response(latest_event) if latest_event else None,
        "latest_output": _compact_preview(latest_output.message) if latest_output else _work_item_output_preview(item),
        "output_preview": _work_item_output_preview(item),
        "artifacts_count": len(artifacts),
        "primary_artifact_label": primary_artifact.get("label") if isinstance(primary_artifact, dict) else None,
        "can_retry": item.status in {"failed", "blocked", "cancelled"},
        "can_cancel": item.status in {"queued", "running"},
    }


def _event_to_response(event: AutonomousAgentEvent) -> dict[str, Any]:
    return event_to_response(event)


def _with_session(session: Session | None):
    if session is not None:
        return session, False
    return Session(engine), True


def _team_summary_for_mission(mission: AutonomousMission, session: Session | None = None) -> dict[str, Any]:
    db, should_close = _with_session(session)
    try:
        items = db.exec(select(AutonomousAgentWorkItem).where(AutonomousAgentWorkItem.mission_id == mission.id)).all()
        proposals = db.exec(select(AutonomousTestProposal).where(AutonomousTestProposal.mission_id == mission.id)).all()
    finally:
        if should_close:
            db.close()
    by_status: dict[str, int] = {}
    by_role: dict[str, dict[str, Any]] = {}
    revision_count = 0
    pending_revision_count = 0
    accepted_revision_count = 0
    needs_revision_work_item_ids: set[str] = set()
    stale_recovered_count = 0
    for item in items:
        result = item.result or {}
        progress = item.progress or {}
        if item.recovery_count or progress.get("recovered_from_work_item_id"):
            stale_recovered_count += 1
        is_revision = bool(_work_item_revision_parent_id(item))
        if is_revision:
            revision_count += 1
            if item.status in {"queued", "running"}:
                pending_revision_count += 1
            if item.status == "completed" and result.get("review_decision") == "accepted":
                accepted_revision_count += 1
        if result.get("review_decision") == "needs_revision" and result.get("revision_work_item_id"):
            needs_revision_work_item_ids.add(str(result["revision_work_item_id"]))
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
    validation_failed_count = sum(1 for proposal in proposals if proposal.validation_status == "failed")
    auto_materialized_count = sum(1 for proposal in proposals if proposal.materialized_by == "autonomous_policy")
    return {
        "enabled": bool(config.get("whole_app_team") or config.get("team_mode") == "whole_app" or items),
        "roles": configured_roles or [role["role"] for role in by_role.values()],
        "max_parallel_agents": config.get("max_parallel_agents", 2),
        "total": len(items),
        "active_count": sum(by_status.get(status, 0) for status in ("queued", "running")),
        "completed_count": by_status.get("completed", 0),
        "blocked_count": sum(by_status.get(status, 0) for status in ("failed", "blocked", "cancelled")),
        "revision_count": revision_count,
        "pending_revision_count": pending_revision_count,
        "accepted_revision_count": accepted_revision_count,
        "needs_revision_count": len(needs_revision_work_item_ids),
        "revision_attention": pending_revision_count > 0,
        "stale_recovered_count": stale_recovered_count,
        "validation_failed_count": validation_failed_count,
        "auto_materialized_count": auto_materialized_count,
        "planner_created_count": sum(1 for item in items if item.planner_key),
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
    emit_mission_event(mission, "Mission created.", event_type="lifecycle", payload={"status": mission.status})
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

    team_summary = _team_summary_for_mission(mission, session)
    pending_revision_count = int(team_summary.get("pending_revision_count") or 0)
    health_status = _derive_health_status(mission, pending_approval_count=len(pending_approvals), temporal_status=temporal_status)
    return {
        "mission": {**_mission_to_response(mission, session), "health_status": health_status, "team_summary": team_summary},
        "temporal": temporal_status,
        "latest_run": _run_to_response(latest_run) if latest_run else None,
        "blocking_approvals": [_approval_to_response(approval) for approval in pending_approvals[:10]],
        "pending_approval_count": len(pending_approvals),
        "worker_available": temporal_status["available"],
        "next_action": _derive_next_action(
            mission,
            len(pending_approvals),
            health_status,
            temporal_status,
            pending_revision_count=pending_revision_count,
        ),
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
    emit_mission_event(mission, "Mission updated.", event_type="lifecycle", payload={"status": mission.status})
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
    emit_mission_event(mission, "Mission started.", event_type="lifecycle", payload={"workflow_id": mission.latest_workflow_id})
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
    emit_mission_event(mission, "Mission paused.", event_type="pause", payload={"paused_reason": mission.paused_reason})
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
        emit_mission_event(mission, "Mission resumed.", event_type="resume", payload={"workflow_id": mission.latest_workflow_id})
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
    emit_mission_event(mission, "Mission cancelled.", event_type="lifecycle", payload={"status": mission.status})
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


@router.get("/{project_id}/diagnostics")
def get_autonomous_diagnostics(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    _require_project(project_id, session)
    return autonomous_health_diagnostics(session, project_id=project_id)


@router.post("/{project_id}/diagnostics/backfill")
async def backfill_autonomous_diagnostics(
    project_id: str,
    dry_run: bool = Query(default=True),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    summary = backfill_autonomous_canonical_state(session, project_id=project_id, dry_run=dry_run)
    return {"project_id": project_id, "summary": summary, "diagnostics": autonomous_health_diagnostics(session, project_id=project_id)}


@router.post("/{project_id}/diagnostics/recover")
async def recover_autonomous_diagnostics(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    recovery = recover_autonomous_project_stale_work(session, project_id)
    return {"project_id": project_id, "recovery": recovery, "diagnostics": autonomous_health_diagnostics(session, project_id=project_id)}


@router.post("/{project_id}/diagnostics/monitor")
async def monitor_autonomous_diagnostics(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    return monitor_autonomous_project(session, project_id)


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


@router.post("/{project_id}/findings/{finding_id}/approve")
async def approve_finding(
    project_id: str,
    finding_id: str,
    req: FindingDecisionRequest | None = None,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    return _decide_finding(project_id, finding_id, "approved", req, session, current_user)


@router.post("/{project_id}/findings/{finding_id}/reject")
async def reject_finding(
    project_id: str,
    finding_id: str,
    req: FindingDecisionRequest | None = None,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    return _decide_finding(project_id, finding_id, "rejected", req, session, current_user)


@router.post("/{project_id}/findings/{finding_id}/resolve")
async def resolve_finding(
    project_id: str,
    finding_id: str,
    req: FindingDecisionRequest | None = None,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    return _decide_finding(project_id, finding_id, "resolved", req, session, current_user)


@router.get("/{project_id}/missions/{mission_id}/app-changes")
def list_mission_app_changes(
    project_id: str,
    mission_id: str,
    status: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    _get_project_mission(project_id, mission_id, session)
    statement = select(AutonomousFinding).where(
        AutonomousFinding.mission_id == mission_id,
        AutonomousFinding.finding_type == "memory_delta",
    )
    if status:
        statement = statement.where(AutonomousFinding.status == status)
    if run_id:
        statement = statement.where(AutonomousFinding.run_id == run_id)
    findings = session.exec(statement.order_by(col(AutonomousFinding.created_at).desc()).limit(limit)).all()
    run_ids = {finding.run_id for finding in findings if finding.run_id}
    runs = {run.id: run for run in session.exec(select(AutonomousMissionRun).where(col(AutonomousMissionRun.id).in_(run_ids))).all()} if run_ids else {}
    proposals = session.exec(
        select(AutonomousTestProposal).where(
            AutonomousTestProposal.project_id == project_id,
            col(AutonomousTestProposal.finding_id).in_([finding.id for finding in findings] or ["__none__"]),
        )
    ).all()
    proposal_by_finding = {proposal.finding_id: proposal for proposal in proposals if proposal.finding_id}
    changes = [
        _app_change_to_response(
            finding,
            run=runs.get(str(finding.run_id)),
            proposal=proposal_by_finding.get(finding.id),
            session=session,
        )
        for finding in findings
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for change in changes:
        grouped.setdefault(change["change_type"], []).append(change)
    return {"items": changes, "grouped": grouped, "count": len(changes)}


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


@router.get("/{project_id}/missions/{mission_id}/team-timeline")
def get_mission_team_timeline(
    project_id: str,
    mission_id: str,
    limit: int = Query(default=100, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    _get_project_mission(project_id, mission_id, session)
    items = session.exec(
        select(AutonomousAgentWorkItem)
        .where(AutonomousAgentWorkItem.mission_id == mission_id)
        .order_by(col(AutonomousAgentWorkItem.priority).asc(), col(AutonomousAgentWorkItem.created_at).asc())
        .limit(limit)
    ).all()
    events = list_events(project_id=project_id, mission_id=mission_id, limit=500, session=session)
    events_by_item: dict[str, list[AutonomousAgentEvent]] = {}
    mission_events: list[AutonomousAgentEvent] = []
    for event in events:
        if event.work_item_id:
            events_by_item.setdefault(event.work_item_id, []).append(event)
        else:
            mission_events.append(event)

    timeline = [_work_item_timeline_response(item, events_by_item.get(item.id, [])) for item in items]
    by_role: dict[str, list[dict[str, Any]]] = {}
    for item in timeline:
        by_role.setdefault(str(item.get("role") or "agent"), []).append(item)
    status_counts: dict[str, int] = {}
    for item in items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1

    return {
        "mission_id": mission_id,
        "project_id": project_id,
        "count": len(timeline),
        "status_counts": status_counts,
        "items": timeline,
        "by_role": by_role,
        "mission_events": [_event_to_response(event) for event in mission_events[-25:]],
    }


@router.get("/{project_id}/missions/{mission_id}/events")
async def list_mission_events(
    project_id: str,
    mission_id: str,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    _get_project_mission(project_id, mission_id, session)
    await _require_project_view(project_id, current_user, session)
    events = list_events(
        project_id=project_id,
        mission_id=mission_id,
        after_sequence=after_sequence,
        limit=limit,
        session=session,
    )
    return [_event_to_response(event) for event in events]


@router.get("/{project_id}/missions/{mission_id}/events/stream")
async def stream_mission_events(
    project_id: str,
    mission_id: str,
    after_sequence: int = Query(default=0, ge=0),
    current_user: User | None = Depends(get_current_user_optional),
):
    with Session(engine) as session:
        _get_project_mission(project_id, mission_id, session)
        await _require_project_view(project_id, current_user, session)

    return _event_stream_response(project_id=project_id, mission_id=mission_id, after_sequence=after_sequence)


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


@router.get("/{project_id}/work-items/{work_item_id}/events")
async def list_work_item_events(
    project_id: str,
    work_item_id: str,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    item = _get_project_work_item(project_id, work_item_id, session)
    await _require_project_view(project_id, current_user, session)
    events = list_events(
        project_id=project_id,
        mission_id=item.mission_id,
        work_item_id=item.id,
        after_sequence=after_sequence,
        limit=limit,
        session=session,
    )
    return [_event_to_response(event) for event in events]


@router.get("/{project_id}/work-items/{work_item_id}/events/stream")
async def stream_work_item_events(
    project_id: str,
    work_item_id: str,
    after_sequence: int = Query(default=0, ge=0),
    current_user: User | None = Depends(get_current_user_optional),
):
    with Session(engine) as session:
        item = _get_project_work_item(project_id, work_item_id, session)
        mission_id = item.mission_id
        await _require_project_view(project_id, current_user, session)

    return _event_stream_response(
        project_id=project_id,
        mission_id=mission_id,
        work_item_id=work_item_id,
        after_sequence=after_sequence,
    )


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
    emit_work_item_status_event(item, "Work item retry requested.", event_type="lifecycle")
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
    emit_work_item_status_event(item, "Work item cancelled by user.", event_type="lifecycle")
    return _work_item_to_response(item)


@router.post("/{project_id}/work-items/{work_item_id}/accept")
async def accept_work_item(
    project_id: str,
    work_item_id: str,
    req: WorkItemReviewDecisionRequest | None = None,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    return _decide_work_item_review(project_id, work_item_id, "accepted", req, session, current_user)


@router.post("/{project_id}/work-items/{work_item_id}/reject")
async def reject_work_item(
    project_id: str,
    work_item_id: str,
    req: WorkItemReviewDecisionRequest | None = None,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    return _decide_work_item_review(project_id, work_item_id, "rejected", req, session, current_user)


@router.post("/{project_id}/work-items/{work_item_id}/needs-revision")
async def request_work_item_revision(
    project_id: str,
    work_item_id: str,
    req: WorkItemReviewDecisionRequest | None = None,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    return _decide_work_item_review(project_id, work_item_id, "needs_revision", req, session, current_user)


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
    return [_proposal_to_response(proposal, session) for proposal in proposals]


@router.get("/{project_id}/proposals/{proposal_id}")
def get_test_proposal(
    project_id: str,
    proposal_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    proposal = _get_project_proposal(project_id, proposal_id, session)
    return _proposal_to_response(proposal, session)


@router.get("/{project_id}/proposals/{proposal_id}/audit")
async def get_test_proposal_audit(
    project_id: str,
    proposal_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_project_view(project_id, current_user, session)
    proposal = _get_project_proposal(project_id, proposal_id, session)
    return _proposal_audit_response(proposal, session)


@router.get("/{project_id}/proposal-review")
async def get_proposal_review_queue(
    project_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_project_view(project_id, current_user, session)
    return AutonomousProposalReviewService(session, base_dir=BASE_DIR).proposal_review_queue(project_id, limit=limit)


@router.post("/{project_id}/proposals/{proposal_id}/refresh-review")
async def refresh_test_proposal_review(
    project_id: str,
    proposal_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    proposal = _get_project_proposal(project_id, proposal_id, session)
    AutonomousProposalReviewService(session, base_dir=BASE_DIR).refresh_review(proposal)
    return _proposal_to_response(proposal, session)


@router.post("/{project_id}/proposals/refresh-reviews")
async def refresh_test_proposal_reviews(
    project_id: str,
    req: ProposalReviewRefreshRequest | None = None,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user),
):
    await _require_project_edit(project_id, current_user, session)
    payload = req or ProposalReviewRefreshRequest()
    if payload.status and payload.status not in TEST_PROPOSAL_STATUSES:
        raise HTTPException(status_code=400, detail=f"Unsupported proposal status: {payload.status}")
    result = AutonomousProposalReviewService(session, base_dir=BASE_DIR).refresh_reviews(
        project_id,
        mission_id=payload.mission_id,
        status=payload.status,
        stale_only=payload.stale_only,
        duplicate_only=payload.duplicate_only,
        limit=payload.limit,
    )
    return {
        "counts": result.counts,
        "proposals": [_proposal_to_response(proposal, session) for proposal in result.proposals],
    }


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
        return _proposal_to_response(proposal, session)
    if proposal.approval_status != "approved":
        raise HTTPException(status_code=409, detail="Approve the proposal before materializing it")

    review_context = AutonomousProposalReviewService(session, base_dir=BASE_DIR).build_review_context(proposal)
    duplicate_review = review_context.get("duplicate") or {}
    if duplicate_review.get("blocking") and not (req and req.override_blocking_duplicate and req.override_reason):
        raise HTTPException(
            status_code=409,
            detail="Blocking duplicate review must be overridden with a reason before materializing this proposal",
        )

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
        "override_blocking_duplicate": bool(req.override_blocking_duplicate) if req else False,
        "override_reason": req.override_reason if req else None,
        "comment": req.comment if req else None,
    }
    proposal.updated_at = now
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return _proposal_to_response(proposal, session)


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


def _get_project_finding(project_id: str, finding_id: str, session: Session) -> AutonomousFinding:
    _require_project(project_id, session)
    finding = session.get(AutonomousFinding, finding_id)
    if not finding or finding.project_id != project_id:
        raise HTTPException(status_code=404, detail="Autonomous finding not found")
    return finding


def _get_project_work_item(project_id: str, work_item_id: str, session: Session) -> AutonomousAgentWorkItem:
    _require_project(project_id, session)
    item = session.get(AutonomousAgentWorkItem, work_item_id)
    if not item or item.project_id != project_id:
        raise HTTPException(status_code=404, detail="Autonomous work item not found")
    return item


async def _require_project_edit(project_id: str, current_user: User | None, session: Session) -> None:
    await check_project_access(project_id, current_user, EDIT_ROLES, session)


async def _require_project_view(project_id: str, current_user: User | None, session: Session) -> None:
    await check_project_access(project_id, current_user, VIEW_ROLES, session)


def _event_stream_response(
    *,
    project_id: str,
    mission_id: str,
    work_item_id: str | None = None,
    after_sequence: int = 0,
) -> StreamingResponse:
    async def generate():
        last_sequence = after_sequence
        heartbeat_ticks = 0
        yield f"data: {json.dumps({'status': 'connected'})}\n\n"
        try:
            while True:
                with Session(engine) as session:
                    events = list_events(
                        project_id=project_id,
                        mission_id=mission_id,
                        work_item_id=work_item_id,
                        after_sequence=last_sequence,
                        limit=100,
                        session=session,
                    )
                    for event in events:
                        last_sequence = max(last_sequence, event.sequence)
                        yield f"data: {json.dumps({'event': _event_to_response(event)})}\n\n"

                    terminal_status: str | None = None
                    if work_item_id:
                        item = session.get(AutonomousAgentWorkItem, work_item_id)
                        if not item:
                            yield f"data: {json.dumps({'status': 'error', 'message': 'Work item not found'})}\n\n"
                            break
                        if item.status in {"completed", "failed", "blocked", "cancelled"}:
                            terminal_status = item.status
                    else:
                        mission = session.get(AutonomousMission, mission_id)
                        if not mission:
                            yield f"data: {json.dumps({'status': 'error', 'message': 'Mission not found'})}\n\n"
                            break
                        if mission.status in {"completed", "cancelled", "error", "paused"}:
                            terminal_status = mission.status

                    if terminal_status:
                        yield f"data: {json.dumps({'status': 'complete', 'final_status': terminal_status, 'last_sequence': last_sequence})}\n\n"
                        break

                heartbeat_ticks += 1
                if heartbeat_ticks >= 5:
                    heartbeat_ticks = 0
                    yield f"data: {json.dumps({'status': 'heartbeat', 'last_sequence': last_sequence})}\n\n"
                await asyncio.sleep(1)
        except (asyncio.CancelledError, GeneratorExit):
            pass
        except Exception as exc:
            logger.error("Autonomous event stream failed for %s: %s", mission_id, exc, exc_info=True)
            yield f"data: {json.dumps({'status': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    *,
    pending_revision_count: int = 0,
) -> str | None:
    if pending_approval_count >= _max_pending_approvals(mission):
        return "Review pending approvals before the mission creates more proposals."
    if mission.paused_reason:
        return mission.next_action or mission.paused_reason.replace("_", " ")
    if health_status == "offline":
        return temporal_status.get("error") if temporal_status else "Temporal worker is not reachable."
    if pending_revision_count > 0:
        plural = "s" if pending_revision_count != 1 else ""
        return f"{pending_revision_count} revision follow-up{plural} queued or running before new exploratory work."
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
    for item in items:
        emit_work_item_status_event(item, "Mission cancellation stopped this assignment.", event_type="lifecycle")


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
    for item in items:
        emit_work_item_status_event(item, "Work item paused with mission.", event_type="pause")


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
    for item in items:
        emit_work_item_status_event(item, "Work item resumed with mission.", event_type="resume")


def _decision_actor(req: FindingDecisionRequest | WorkItemReviewDecisionRequest | None, current_user: User | None) -> str | None:
    if req and req.reviewer:
        return req.reviewer
    return str(current_user.id) if current_user else None


def _decide_finding(
    project_id: str,
    finding_id: str,
    decision: str,
    req: FindingDecisionRequest | None,
    session: Session,
    current_user: User | None,
) -> dict[str, Any]:
    if decision not in {"approved", "rejected", "resolved"}:
        raise HTTPException(status_code=400, detail=f"Unsupported finding decision: {decision}")
    if decision in {"rejected", "resolved"} and not (req and req.comment and req.comment.strip()):
        raise HTTPException(status_code=400, detail=f"{decision.replace('_', ' ').title()} findings require a comment")

    finding = _get_project_finding(project_id, finding_id, session)
    now = datetime.utcnow()
    actor = _decision_actor(req, current_user)
    comment = req.comment.strip() if req and req.comment else None

    evidence = dict(finding.evidence or {})
    evidence["review"] = {
        "decision": decision,
        "comment": comment,
        "reviewer": actor,
        "reviewed_at": now.isoformat(),
    }
    finding.status = decision
    finding.evidence = evidence
    finding.updated_at = now
    session.add(finding)

    if decision in {"rejected", "resolved"}:
        linked_proposals = session.exec(
            select(AutonomousTestProposal).where(
                AutonomousTestProposal.project_id == project_id,
                AutonomousTestProposal.finding_id == finding.id,
                AutonomousTestProposal.approval_status == "pending",
            )
        ).all()
        for proposal in linked_proposals:
            proposal.approval_status = "rejected"
            proposal.rejected_at = now
            proposal.rejected_by = actor
            proposal.updated_at = now
            session.add(proposal)

    session.commit()
    session.refresh(finding)
    mission = session.get(AutonomousMission, finding.mission_id)
    if mission:
        emit_mission_event(
            mission,
            f"Finding {decision}.",
            event_type="finding_review",
            payload={"finding_id": finding.id, "decision": decision, "comment": comment},
        )
    return _finding_to_response(finding)


def _apply_work_item_review(
    item: AutonomousAgentWorkItem,
    *,
    decision: str,
    reason: str | None,
    actor: str | None,
    reviewed_at: str,
    reviewed_role: str | None,
    reviewed_work_item_id: str | None,
) -> None:
    item.result = {
        **(item.result or {}),
        "review_decision": decision,
        "review_reason": reason,
        "reviewed_by": actor,
        "reviewed_at": reviewed_at,
        "reviewed_role": reviewed_role,
        "reviewed_work_item_id": reviewed_work_item_id,
    }
    item.updated_at = datetime.utcnow()


def _revision_attempt_for_work_item(
    session: Session,
    item: AutonomousAgentWorkItem,
) -> int:
    mission_items = session.exec(
        select(AutonomousAgentWorkItem).where(AutonomousAgentWorkItem.mission_id == item.mission_id)
    ).all()
    attempts = [
        candidate
        for candidate in mission_items
        if _work_item_revision_parent_id(candidate) == item.id
    ]
    return len(attempts) + 1


def _create_revision_work_item(
    session: Session,
    *,
    original: AutonomousAgentWorkItem,
    reviewer: AutonomousAgentWorkItem,
    decision: str,
    reason: str | None,
    actor: str | None,
    reviewed_at: str,
) -> AutonomousAgentWorkItem:
    attempt = _revision_attempt_for_work_item(session, original)
    revision = AutonomousAgentWorkItem(
        id=f"amwork-{uuid.uuid4().hex[:12]}",
        mission_id=original.mission_id,
        run_id=original.run_id,
        project_id=original.project_id,
        role=original.role,
        objective=original.objective,
        status="queued",
        priority=max(0, original.priority - REVISION_PRIORITY_BOOST),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    revision.assigned_surface = original.assigned_surface
    revision.progress = {
        "phase": "queued",
        "message": "Revision requested by reviewer; mission supervisor will enqueue this follow-up assignment.",
        "revision_of_work_item_id": original.id,
        "reviewer_work_item_id": reviewer.id if reviewer.id != original.id else None,
        "review_reason": reason,
        "review_decision": decision,
        "reviewed_by": actor,
        "reviewed_at": reviewed_at,
        "revision_attempt": attempt,
        "original_priority": original.priority,
        "revision_priority_boost": REVISION_PRIORITY_BOOST,
    }
    revision.result = {
        "revision_of_work_item_id": original.id,
        "reviewer_work_item_id": reviewer.id if reviewer.id != original.id else None,
        "review_reason": reason,
        "review_decision": "pending",
        "revision_attempt": attempt,
        "original_priority": original.priority,
        "revision_priority_boost": REVISION_PRIORITY_BOOST,
    }
    session.add(revision)
    return revision


def _decide_work_item_review(
    project_id: str,
    work_item_id: str,
    decision: str,
    req: WorkItemReviewDecisionRequest | None,
    session: Session,
    current_user: User | None,
) -> dict[str, Any]:
    if decision not in WORK_ITEM_REVIEW_DECISIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported work item review decision: {decision}")
    if decision in {"rejected", "needs_revision"} and not (req and req.comment and req.comment.strip()):
        raise HTTPException(status_code=400, detail=f"{decision.replace('_', ' ').title()} requires a reason")

    item = _get_project_work_item(project_id, work_item_id, session)
    if item.status != "completed":
        raise HTTPException(status_code=409, detail="Only completed work items can be reviewed")

    target = item
    if req and req.target_work_item_id:
        target = _get_project_work_item(project_id, req.target_work_item_id, session)
        if target.mission_id != item.mission_id:
            raise HTTPException(status_code=400, detail="Target work item must belong to the same mission")

    now = datetime.utcnow()
    reviewed_at = now.isoformat()
    actor = _decision_actor(req, current_user)
    reason = req.comment.strip() if req and req.comment else None

    _apply_work_item_review(
        item,
        decision=decision,
        reason=reason,
        actor=actor,
        reviewed_at=reviewed_at,
        reviewed_role=target.role if target.id != item.id else None,
        reviewed_work_item_id=target.id if target.id != item.id else None,
    )
    session.add(item)

    if target.id != item.id:
        _apply_work_item_review(
            target,
            decision=decision,
            reason=reason,
            actor=actor or item.role,
            reviewed_at=reviewed_at,
            reviewed_role=item.role,
            reviewed_work_item_id=item.id,
        )
        session.add(target)

    revision_item: AutonomousAgentWorkItem | None = None
    if decision == "needs_revision":
        revision_item = _create_revision_work_item(
            session,
            original=target,
            reviewer=item,
            decision=decision,
            reason=reason,
            actor=actor,
            reviewed_at=reviewed_at,
        )
        target.result = {
            **(target.result or {}),
            "revision_work_item_id": revision_item.id,
            "revision_attempt": revision_item.result.get("revision_attempt"),
        }
        if item.id != target.id:
            item.result = {
                **(item.result or {}),
                "revision_work_item_id": revision_item.id,
                "revision_attempt": revision_item.result.get("revision_attempt"),
            }
        session.add(target)
        session.add(item)

    session.commit()
    session.refresh(item)
    if target.id != item.id:
        session.refresh(target)
    if revision_item:
        session.refresh(revision_item)

    payload = {
        "decision": decision,
        "reason": reason,
        "reviewer": actor,
        "target_work_item_id": target.id if target.id != item.id else None,
        "revision_work_item_id": revision_item.id if revision_item else None,
    }
    create_autonomous_agent_event(
        project_id=item.project_id,
        mission_id=item.mission_id,
        run_id=item.run_id,
        work_item_id=item.id,
        agent_task_id=item.agent_task_id,
        event_type="review",
        message=f"Work item review decision: {decision}.",
        payload=payload,
    )
    if target.id != item.id:
        create_autonomous_agent_event(
            project_id=target.project_id,
            mission_id=target.mission_id,
            run_id=target.run_id,
            work_item_id=target.id,
            agent_task_id=target.agent_task_id,
            event_type="review",
            message=f"Reviewed by {item.role}: {decision}.",
            payload={**payload, "reviewer_work_item_id": item.id, "reviewer_role": item.role},
        )
    if revision_item:
        create_autonomous_agent_event(
            project_id=revision_item.project_id,
            mission_id=revision_item.mission_id,
            run_id=revision_item.run_id,
            work_item_id=revision_item.id,
            event_type="revision",
            message="Revision follow-up work item created from reviewer feedback.",
            payload={
                **payload,
                "revision_of_work_item_id": target.id,
                "reviewer_work_item_id": item.id,
                "revision_attempt": revision_item.result.get("revision_attempt"),
            },
        )

    events = list_events(project_id=project_id, mission_id=item.mission_id, work_item_id=item.id, limit=50)
    response = _work_item_timeline_response(item, events)
    if revision_item:
        response["revision_work_item"] = _work_item_to_response(revision_item)
    return response


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
    return _proposal_to_response(proposal, session)


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
