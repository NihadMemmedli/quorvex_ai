"""Team scheduling helpers for autonomous mission activities."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session, col, select

from orchestrator.api.models_db import (
    AutonomousAgentWorkItem,
    AutonomousMission,
    AutonomousMissionRun,
    ExecutionSettings,
)
from orchestrator.services import autonomous_activities as facade
from orchestrator.services import autonomous_shared as shared


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
    return list(shared.WHOLE_APP_TEAM_ROLES)


def _max_parallel_agents(mission: AutonomousMission) -> int:
    configured = facade._config_int(mission.config, "max_parallel_agents", shared.DEFAULT_MAX_PARALLEL_AGENTS)
    global_limit = shared.DEFAULT_MAX_PARALLEL_AGENTS
    try:
        with Session(facade.engine) as session:
            settings = session.get(ExecutionSettings, 1)
            if settings:
                global_limit = settings.parallelism
    except Exception as exc:
        facade.logger.debug("Failed to read execution settings for autonomous parallelism: %s", exc)
    return max(1, min(configured, global_limit, 12))


def _run_parallel_team_supervisor(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
) -> dict[str, Any]:
    summary = {
        "roles": facade._team_roles(mission),
        "max_parallel_agents": facade._max_parallel_agents(mission),
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
    summary["work_items_completed"] = facade._sync_agent_work_items(session, mission)
    summary["stale_recovered_count"] = facade._recover_stale_work_items(session, mission, run)
    summary["work_items_created"] += summary["stale_recovered_count"]
    if summary["work_items_completed"]:
        summary["findings_created"] = facade._create_findings_from_completed_work_items(session, mission, run)
    summary["planner_created"] = facade._plan_whole_app_work_items(session, mission, run)
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
                objective=facade._role_objective(role, mission),
                assigned_surface_json=json.dumps(facade._role_surface(role, mission)),
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

    running_count = facade._count_work_items(session, mission.id, {"running"})
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
        pending = sorted(queued_candidates, key=facade._queued_work_item_sort_key)[
            : min(shared.DEFAULT_WORK_ITEM_BATCH_SIZE, available_slots)
        ]
        for item in pending:
            if facade._enqueue_agent_work_item(session, mission, item):
                summary["work_items_enqueued"] += 1
            else:
                summary["work_items_blocked"] += 1

    summary["active_count"] = facade._count_work_items(session, mission.id, shared.WORK_ITEM_ACTIVE_STATUSES)
    summary["running_count"] = facade._count_work_items(session, mission.id, {"running"})
    summary["completed_count"] = facade._count_work_items(session, mission.id, {"completed"})
    summary["blocked_count"] = facade._count_work_items(session, mission.id, {"blocked", "failed"})
    facade._update_mission_team_progress(session, mission)
    return summary


def _is_revision_work_item(item: AutonomousAgentWorkItem) -> bool:
    metadata = facade._work_item_revision_metadata(item)
    return bool(metadata.get("revision_of_work_item_id"))


def _queued_work_item_sort_key(item: AutonomousAgentWorkItem) -> tuple[int, int, datetime]:
    return (
        0 if facade._is_revision_work_item(item) else 1,
        item.priority,
        item.created_at,
    )


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


def _update_mission_team_progress(session: Session, mission: AutonomousMission) -> None:
    mission.current_stage = "team_supervising"
    mission.next_action = facade._stage_next_action("team_supervising")
    mission.last_heartbeat_at = shared._utcnow()
    mission.updated_at = mission.last_heartbeat_at
    session.add(mission)
    session.commit()
