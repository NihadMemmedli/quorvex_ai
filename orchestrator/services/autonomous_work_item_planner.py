"""Work-item planning helpers for autonomous mission activities."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlmodel import Session, col, select

from orchestrator.api.models_db import (
    AutonomousAgentWorkItem,
    AutonomousFinding,
    AutonomousMission,
    AutonomousMissionRun,
    Requirement,
    RtmEntry,
)
from orchestrator.services import autonomous_activities as facade
from orchestrator.services import autonomous_shared as shared


def _plan_whole_app_work_items(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
) -> int:
    """Create bounded, idempotent work items from canonical app state."""
    config = mission.config or {}
    limit = max(1, min(facade._config_int(config, "planner_batch_size", shared.DEFAULT_WORK_ITEM_BATCH_SIZE), 20))
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
        if requirement.id is None or facade._requirement_truth_state(requirement) == "rejected_requirement":
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
        if facade._planner_work_item_exists(session, mission.id, planner_key):
            continue
        objective = (
            f"Close RTM coverage for {requirement.req_code}: {requirement.title}. "
            "Inspect existing specs and propose missing automated coverage without writing files."
        )
        if facade._create_planned_work_item(
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
        if facade._planner_work_item_exists(session, mission.id, planner_key):
            continue
        evidence = finding.evidence
        objective = (
            f"Review finding '{finding.title}' and map it to affected routes, requirements, and a regression proposal. "
            "Do not duplicate existing proposals."
        )
        if facade._create_planned_work_item(
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

    for frontier in facade._frontier_planner_items(session, mission, limit=max(0, limit - created)):
        if created >= limit:
            break
        frontier_id = str(frontier.get("id") or "")
        if not frontier_id:
            continue
        planner_key = f"frontier:{frontier_id}"
        if facade._planner_work_item_exists(session, mission.id, planner_key):
            continue
        url = str(frontier.get("url") or frontier.get("state_url") or frontier.get("url_template") or "")
        action = str(frontier.get("action_type") or frontier.get("action") or "explore")
        objective = (
            f"Explore browser-memory frontier item {frontier_id}: {action}. "
            "Record app map updates, requirements, bugs, and test proposals as structured JSON."
        )
        if facade._create_planned_work_item(
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
    candidates = session.exec(
        select(AutonomousAgentWorkItem).where(AutonomousAgentWorkItem.mission_id == mission_id)
    ).all()
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
        facade.logger.debug("Unable to load browser frontier work for autonomous planner.", exc_info=True)
        return []
