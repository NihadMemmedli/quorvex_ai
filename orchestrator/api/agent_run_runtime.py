from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session

from logging_config import get_logger
from utils.playwright_mcp import browser_live_worker_enabled

from .models_db import AgentRun

logger = get_logger(__name__)


def record_agent_run_event(
    run_id: str,
    *,
    event_type: str,
    message: str,
    level: str = "info",
    payload: dict[str, Any] | None = None,
    agent_task_id: str | None = None,
    session: Session | None = None,
) -> None:
    try:
        from orchestrator.services.agent_run_events import create_agent_run_event

        create_agent_run_event(
            run_id=run_id,
            agent_task_id=agent_task_id,
            event_type=event_type,
            level=level,
            message=message,
            payload=payload or {},
            session=session,
        )
    except Exception as exc:
        logger.debug("Failed to record agent run event for %s: %s", run_id, exc)


def custom_agent_uses_browser_tools(allowed_tools: list[Any]) -> bool:
    """Return whether selected custom-agent tools require Playwright Chromium."""
    return any(
        str(tool).startswith("mcp__playwright") or str(tool).startswith("browser_")
        for tool in allowed_tools
    )


def custom_agent_browser_runs_via_queue() -> bool:
    """Return whether browser execution will be delegated to an agent worker."""
    if browser_live_worker_enabled():
        return True
    try:
        from orchestrator.services.agent_queue import should_use_agent_queue

        return should_use_agent_queue()
    except Exception as exc:
        logger.debug("Could not determine custom agent queue mode: %s", exc)
        return False


def agent_run_has_browser_tools(agent_type: str, config: dict[str, Any]) -> bool:
    """Return whether this agent run will need a Playwright browser."""
    if agent_type == "custom":
        return custom_agent_uses_browser_tools(config.get("allowed_tools") or [])
    return agent_type in ("exploratory", "spec_generation")


async def start_agent_run_temporal_or_fail(
    run: AgentRun,
    session: Session,
    *,
    workflow_attempt: int | None = None,
) -> None:
    from orchestrator.config import settings as app_settings
    from orchestrator.services.temporal_client import (
        TemporalUnavailableError,
        describe_temporal_task_queue,
        start_agent_run_workflow,
    )

    task_queue = app_settings.temporal_workflow_task_queue
    if agent_run_has_browser_tools(run.agent_type, run.config) and browser_live_worker_enabled():
        task_queue = app_settings.temporal_browser_workflow_task_queue

    task_queue_status: dict[str, Any] = {}
    try:
        task_queue_status = await describe_temporal_task_queue(task_queue)
    except Exception as exc:
        task_queue_status = {"status": "unknown", "error": str(exc)}

    try:
        if workflow_attempt:
            temporal = await start_agent_run_workflow(run.id, task_queue=task_queue, attempt=workflow_attempt)
        else:
            temporal = await start_agent_run_workflow(run.id, task_queue=task_queue)
    except TemporalUnavailableError as exc:
        run.status = "failed"
        run.completed_at = datetime.utcnow()
        run.result = {"error": f"Failed to start Temporal workflow: {exc}"}
        run.progress = {
            **(run.progress or {}),
            "phase": "failed",
            "status": "failed",
            "message": str(exc),
            "updated_at": datetime.utcnow().isoformat(),
        }
        session.add(run)
        session.commit()
        record_agent_run_event(
            run.id,
            event_type="temporal_start_failed",
            level="error",
            message=f"Failed to start Temporal workflow: {exc}",
            payload={"temporal_error": str(exc)},
            session=session,
        )
        raise HTTPException(status_code=503, detail=f"Temporal is required for agent runs: {exc}") from exc

    run.temporal_workflow_id = temporal.workflow_id
    run.temporal_run_id = temporal.run_id
    run.progress = {
        **(run.progress or {}),
        "task_queue": task_queue,
        "task_queue_status": task_queue_status,
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.add(run)
    session.commit()
    record_agent_run_event(
        run.id,
        event_type="temporal_scheduled",
        message="Agent Temporal workflow scheduled.",
        payload={
            "workflow_id": temporal.workflow_id,
            "temporal_run_id": temporal.run_id,
            "attempt": workflow_attempt,
            "task_queue": task_queue,
            "task_queue_status": task_queue_status,
        },
        session=session,
    )
