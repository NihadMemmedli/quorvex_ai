import json
import sys
import uuid
from datetime import datetime
from importlib import import_module
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from orchestrator.services.agent_runtimes import normalize_agent_runtime

from .db import get_session
from .middleware.auth import get_current_user_optional
from .models_db import AgentDefinition, AgentRun

router = APIRouter()


def _is_valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


class AgentDefinitionRequest(BaseModel):
    name: str
    description: str = ""
    system_prompt: str
    runtime: str | None = None
    model: str | None = None
    model_tier: str | None = None
    timeout_seconds: int = 1800
    tool_ids: list[str] = []
    test_data_refs: list[str] = []
    project_id: str | None = None


class AgentDefinitionUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    runtime: str | None = None
    model: str | None = None
    model_tier: str | None = None
    timeout_seconds: int | None = None
    tool_ids: list[str] | None = None
    test_data_refs: list[str] | None = None
    status: str | None = None


class CustomAgentRunRequest(BaseModel):
    prompt: str
    url: str | None = None
    config: dict[str, Any] | None = None
    test_data_refs: list[str] = []
    project_id: str | None = None
    runtime: str | None = None
    model_tier: str | None = None
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False


def _runtime() -> Any:
    return sys.modules.get("orchestrator.api.main") or sys.modules.get("api.main") or import_module("orchestrator.api.main")


@router.get("/api/agents/tools/catalog")
def list_agent_tool_catalog(session: Session = Depends(get_session)):
    rt = _runtime()
    tools = rt._sync_agent_tool_catalog(session)
    serialized = [rt._serialize_agent_tool(tool) for tool in tools]
    categories: dict[str, list[dict[str, Any]]] = {}
    for tool in serialized:
        categories.setdefault(tool["category"], []).append(tool)
    return {"tools": serialized, "categories": categories}


@router.get("/api/agents/definitions")
def list_agent_definitions(
    project_id: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    session: Session = Depends(get_session),
):
    rt = _runtime()
    tools = rt._sync_agent_tool_catalog(session)
    tools_by_id = {tool.id: tool for tool in tools}
    statement = select(AgentDefinition).order_by(AgentDefinition.updated_at.desc())
    if not include_archived:
        statement = statement.where(AgentDefinition.status == "active")
    if project_id:
        if project_id == "default":
            statement = statement.where((AgentDefinition.project_id == project_id) | (AgentDefinition.project_id == None))
        else:
            statement = statement.where(AgentDefinition.project_id == project_id)
    return [rt._serialize_agent_definition(item, tools_by_id) for item in session.exec(statement).all()]


@router.post("/api/agents/definitions")
async def create_agent_definition(
    request: AgentDefinitionRequest,
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    rt = _runtime()
    await rt._ensure_agent_write_access(request.project_id, current_user, session)
    rt._resolve_agent_tools(request.tool_ids, session)
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Agent name is required")
    if not request.system_prompt.strip():
        raise HTTPException(status_code=400, detail="System prompt is required")

    definition = AgentDefinition(
        project_id=request.project_id,
        name=request.name.strip(),
        description=request.description.strip(),
        system_prompt=request.system_prompt.strip(),
        runtime=normalize_agent_runtime(request.runtime),
        model=request.model,
        model_tier=request.model_tier,
        timeout_seconds=max(60, min(int(request.timeout_seconds or 1800), 7200)),
        status="active",
    )
    definition.tool_ids = request.tool_ids
    definition.test_data_refs = request.test_data_refs
    session.add(definition)
    session.commit()
    session.refresh(definition)
    return rt._serialize_agent_definition(definition)


@router.get("/api/agents/definitions/{definition_id}")
def get_agent_definition(
    definition_id: str,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    rt = _runtime()
    tools = rt._sync_agent_tool_catalog(session)
    tools_by_id = {tool.id: tool for tool in tools}
    return rt._serialize_agent_definition(rt._get_agent_definition_or_404(definition_id, project_id, session), tools_by_id)


@router.put("/api/agents/definitions/{definition_id}")
async def update_agent_definition(
    definition_id: str,
    request: AgentDefinitionUpdateRequest,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    rt = _runtime()
    definition = rt._get_agent_definition_or_404(definition_id, project_id, session)
    await rt._ensure_agent_write_access(definition.project_id, current_user, session)

    if request.tool_ids is not None:
        rt._resolve_agent_tools(request.tool_ids, session)
        definition.tool_ids = request.tool_ids
    if request.test_data_refs is not None:
        definition.test_data_refs = request.test_data_refs
    if request.name is not None:
        if not request.name.strip():
            raise HTTPException(status_code=400, detail="Agent name is required")
        definition.name = request.name.strip()
    if request.description is not None:
        definition.description = request.description.strip()
    if request.system_prompt is not None:
        if not request.system_prompt.strip():
            raise HTTPException(status_code=400, detail="System prompt is required")
        definition.system_prompt = request.system_prompt.strip()
    if request.runtime is not None:
        definition.runtime = normalize_agent_runtime(request.runtime)
    if request.model is not None:
        definition.model = request.model
    if request.model_tier is not None:
        definition.model_tier = request.model_tier
    if request.timeout_seconds is not None:
        definition.timeout_seconds = max(60, min(int(request.timeout_seconds), 7200))
    if request.status is not None:
        if request.status not in {"active", "archived"}:
            raise HTTPException(status_code=400, detail="Invalid status")
        definition.status = request.status
    definition.updated_at = datetime.utcnow()
    session.add(definition)
    session.commit()
    session.refresh(definition)
    return rt._serialize_agent_definition(definition)


@router.delete("/api/agents/definitions/{definition_id}")
async def archive_agent_definition(
    definition_id: str,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    rt = _runtime()
    definition = rt._get_agent_definition_or_404(definition_id, project_id, session)
    await rt._ensure_agent_write_access(definition.project_id, current_user, session)
    definition.status = "archived"
    definition.updated_at = datetime.utcnow()
    session.add(definition)
    session.commit()
    return {"status": "archived", "id": definition.id}


@router.post("/api/agents/definitions/{definition_id}/runs")
async def run_agent_definition(
    definition_id: str,
    request: CustomAgentRunRequest,
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    rt = _runtime()
    definition = rt._get_agent_definition_or_404(definition_id, request.project_id, session)
    await rt._ensure_agent_write_access(definition.project_id, current_user, session)
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required")

    allowed_tools, selected_tools = rt._resolve_agent_tools(definition.tool_ids, session)
    target_url = (request.url or "").strip()
    has_browser_tools = rt._custom_agent_uses_browser_tools(allowed_tools)
    if has_browser_tools and not _is_valid_http_url(target_url):
        raise HTTPException(
            status_code=400,
            detail="Custom agents with browser tools require a valid http(s) Target URL.",
        )

    resource_manager = await rt.get_resource_manager()
    agent_status = resource_manager.get_agent_status()
    initial_status = "queued"
    queue_position = None if initial_status == "running" else agent_status.queued + 1

    run_id = str(uuid.uuid4())
    run_project_id = definition.project_id or request.project_id
    run_test_data_refs = [
        *getattr(definition, "test_data_refs", []),
        *request.test_data_refs,
        *(
            (request.config or {}).get("test_data_refs", [])
            if isinstance((request.config or {}).get("test_data_refs", []), list)
            else []
        ),
    ]
    run_config = {
        "agent_definition_id": definition.id,
        "agent_name": definition.name,
        "prompt": request.prompt.strip(),
        "url": target_url or None,
        "project_id": run_project_id,
        "custom_config": request.config or {},
        "test_data_refs": run_test_data_refs,
        "system_prompt": definition.system_prompt,
        "timeout_seconds": definition.timeout_seconds,
        "runtime": normalize_agent_runtime(request.runtime or definition.runtime),
        "model": definition.model,
        "model_tier": request.model_tier
        or ((request.config or {}).get("model_tier") if isinstance(request.config, dict) else None)
        or getattr(definition, "model_tier", None),
        "browser_auth_session_id": request.browser_auth_session_id
        or ((request.config or {}).get("browser_auth_session_id") if isinstance(request.config, dict) else None),
        "use_project_default_browser_auth": bool(
            request.use_project_default_browser_auth
            or ((request.config or {}).get("use_project_default_browser_auth") if isinstance(request.config, dict) else False)
        ),
        "tool_ids": definition.tool_ids,
        "allowed_tools": allowed_tools,
        "selected_tools": selected_tools,
    }
    runtime = normalize_agent_runtime(run_config.get("runtime"))
    browser_metadata = rt.browser_runtime_status() if has_browser_tools else {}
    run = AgentRun(
        id=run_id,
        agent_type="custom",
        runtime=runtime,
        config_json=json.dumps(run_config),
        status=initial_status,
        project_id=run_project_id,
    )
    run.progress = {
        **browser_metadata,
        "phase": "queued",
        "status": initial_status,
        "runtime": runtime,
        "has_browser_tools": has_browser_tools,
        "message": "Custom agent run is queued for Temporal.",
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.add(run)
    session.commit()
    rt._record_agent_run_event(
        run_id,
        event_type="created",
        message=f"Custom agent run created with status {initial_status}.",
        payload={
            "agent_type": "custom",
            "agent_definition_id": definition.id,
            "runtime": runtime,
            "status": initial_status,
            "queue_position": queue_position,
        },
        session=session,
    )
    from orchestrator.services.agent_native_runs import commit_agent_run_note

    commit_agent_run_note(
        run_id=run_id,
        phase="created",
        note_type="handoff",
        title="Custom agent run accepted",
        body="Saved custom agent run queued for Temporal execution.",
        source="launcher",
        tags=["queued", "custom"],
        payload={
            "status": initial_status,
            "runtime": runtime,
            "agent_definition_id": definition.id,
            "queue_position": queue_position,
        },
        session=session,
    )

    await rt._start_agent_run_temporal_or_fail(run, session)
    session.refresh(run)

    response = {
        "status": initial_status,
        "run_id": run_id,
        "agent_definition_id": definition.id,
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
        "agent_runtime": runtime,
        "browser_runtime": browser_metadata.get("browser_runtime", "temporal_worker"),
        "live_view_available": bool(browser_metadata.get("live_view_available")),
        "vnc_url": browser_metadata.get("vnc_url"),
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
