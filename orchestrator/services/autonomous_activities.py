"""Temporal activities for persistent autonomous testing missions."""

from __future__ import annotations

import hashlib
import asyncio
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
)
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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
        run.current_stage = "analyzing"
        run.checkpoint = {"stage": "analyzing", "updated_at": now.isoformat()}
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
    checkpoint = {"stage": stage, "updated_at": now.isoformat()}
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
        "coverage_gap_review": "Reviewing unresolved coverage gaps for proposal candidates.",
        "regression_watch_ready": "Regression watch is ready for deeper execution hooks.",
        "flake_triage_ready": "Flake triage is ready for retry-history analysis.",
        "sleeping": "Waiting for the next scheduled mission run.",
    }.get(stage, f"Mission stage: {stage.replace('_', ' ')}.")


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
        pending = session.exec(
            select(AutonomousAgentWorkItem)
            .where(
                AutonomousAgentWorkItem.mission_id == mission.id,
                AutonomousAgentWorkItem.status == "queued",
                AutonomousAgentWorkItem.agent_task_id == None,  # noqa: E711
            )
            .order_by(col(AutonomousAgentWorkItem.priority).asc(), col(AutonomousAgentWorkItem.created_at).asc())
            .limit(min(DEFAULT_WORK_ITEM_BATCH_SIZE, available_slots))
        ).all()
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
    return f"""You are the {item.role} agent in a Quorvex autonomous QA team.

Mission: {mission.name}
Objective: {item.objective}
Target surfaces: {', '.join(surfaces or ['project data and known app artifacts'])}

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
                    allowed_tools=["*"],
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
                return [await queue.get_task(task_id) for task_id in task_ids]
            finally:
                await queue.disconnect()

        tasks = asyncio.run(_load_tasks([str(item.agent_task_id) for item in running_items if item.agent_task_id]))
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
        telemetry = task.telemetry or {}
        if task.status.value == "running":
            item.progress = {
                **item.progress,
                "phase": "running",
                "message": "Agent is running.",
                "tool_calls": telemetry.get("tool_calls"),
                "last_tool": telemetry.get("last_tool"),
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
        elif task.status in {AgentTaskStatus.FAILED, AgentTaskStatus.TIMEOUT, AgentTaskStatus.CANCELLED}:
            item.status = "cancelled" if task.status == AgentTaskStatus.CANCELLED else "failed"
            item.error_message = task.error or f"Agent task {task.status.value}"
            item.completed_at = task.completed_at or now
            item.progress = {"phase": item.status, "message": item.error_message}
            item.updated_at = now
            session.add(item)
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
        result = item.result or {}
        output = str(result.get("output") or "").strip()
        if not output:
            continue
        dedupe_key = hashlib.sha256(f"{mission.project_id}|work_item|{item.id}|finding".encode("utf-8")).hexdigest()[:32]
        existing = session.exec(
            select(AutonomousFinding).where(
                AutonomousFinding.project_id == mission.project_id,
                AutonomousFinding.dedupe_key == dedupe_key,
            )
        ).first()
        if existing:
            continue
        title = f"{_title_case(item.role)} agent report"
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
        finding.evidence = {"work_item_id": item.id, "role": item.role, "assigned_surface": item.assigned_surface}
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
            source_metadata={
                "finding_type": finding.finding_type,
                "confidence": finding.confidence,
                "evidence": evidence,
            },
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
