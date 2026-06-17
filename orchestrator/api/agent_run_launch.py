import json
import sys
import uuid
from datetime import datetime
from importlib import import_module
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from orchestrator.services.agent_runtimes import normalize_agent_runtime
from utils.playwright_mcp import browser_runtime_status

from . import agent_run_runtime
from .db import get_session
from .models_db import AgentRun

router = APIRouter(tags=["agent-run-launch"])


class AgentRunRequest(BaseModel):
    agent_type: str
    config: dict[str, Any]
    project_id: str | None = None
    runtime: str | None = None
    model_tier: str | None = None
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False


def _runtime() -> Any:
    return (
        sys.modules.get("orchestrator.api.main")
        or sys.modules.get("api.main")
        or import_module("orchestrator.api.main")
    )


@router.post("/api/agents/runs")
async def run_agent(request: AgentRunRequest, session: Session = Depends(get_session)):
    """Run an autonomous agent through a durable Temporal workflow."""
    runtime_module = _runtime()

    # Check resource availability
    resource_manager = await runtime_module.get_resource_manager()
    agent_status = resource_manager.get_agent_status()

    # Determine initial status based on slot availability
    initial_status = "queued"
    queue_position = None if initial_status == "running" else agent_status.queued + 1

    # Create DB Record
    run_id = str(uuid.uuid4())
    runtime = normalize_agent_runtime(request.runtime or request.config.get("runtime"))
    run_config = {**request.config, "runtime": runtime}
    if request.project_id and not run_config.get("project_id"):
        run_config["project_id"] = request.project_id
    if request.model_tier:
        run_config["model_tier"] = request.model_tier
    if request.browser_auth_session_id:
        run_config["browser_auth_session_id"] = request.browser_auth_session_id
    if request.use_project_default_browser_auth:
        run_config["use_project_default_browser_auth"] = True
    browser_metadata = browser_runtime_status() if agent_run_runtime.agent_run_has_browser_tools(request.agent_type, run_config) else {}
    run = AgentRun(
        id=run_id,
        agent_type=request.agent_type,
        runtime=runtime,
        config_json=json.dumps(run_config),
        status=initial_status,
        project_id=request.project_id,  # Project isolation
    )
    run.progress = {
        **browser_metadata,
        "phase": "queued",
        "status": initial_status,
        "runtime": runtime,
        "message": "Agent run is queued for Temporal.",
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.add(run)
    session.commit()
    agent_run_runtime.record_agent_run_event(
        run_id,
        event_type="created",
        message=f"Agent run created with status {initial_status}.",
        payload={
            "agent_type": request.agent_type,
            "runtime": runtime,
            "status": initial_status,
            "queue_position": queue_position,
        },
        session=session,
    )

    await runtime_module._start_agent_run_temporal_or_fail(run, session)
    session.refresh(run)

    response = {
        "status": initial_status,
        "run_id": run_id,
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
        "browser_runtime": browser_metadata.get("browser_runtime", "temporal_worker"),
        "live_view_available": bool(browser_metadata.get("live_view_available")),
        "vnc_url": browser_metadata.get("vnc_url"),
        "agent_runtime": runtime,
        "agent_slots": {
            "active": agent_status.active,
            "max": agent_status.max_slots,
            "queued": agent_status.queued + (1 if initial_status == "queued" else 0),
        },
    }

    if queue_position:
        response["queue_position"] = queue_position
        response["message"] = f"Request queued at position {queue_position}. Will start when a slot becomes available."

    return response
