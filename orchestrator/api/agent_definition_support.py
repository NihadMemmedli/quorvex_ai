"""Support helpers for custom agent definitions and selectable tools."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from . import agent_tool_catalog_support
from .middleware.permissions import ProjectRole, check_project_access
from .models_db import AgentDefinition, AgentToolDefinition


def _sync_agent_tool_catalog(session: Session) -> list[AgentToolDefinition]:
    """Upsert the built-in selectable tool catalog."""
    now = datetime.utcnow()
    for item in agent_tool_catalog_support.AGENT_TOOL_CATALOG:
        tool = session.get(AgentToolDefinition, item["id"])
        if not tool:
            tool = AgentToolDefinition(id=item["id"], tool_name=item["tool_name"])
        tool.label = item["label"]
        tool.description = item["description"]
        tool.category = item["category"]
        tool.tool_name = item["tool_name"]
        tool.risk = item["risk"]
        tool.enabled = True
        tool.requires_mcp_server = item.get("requires_mcp_server")
        tool.updated_at = now
        session.add(tool)
    session.commit()
    return session.exec(
        select(AgentToolDefinition)
        .where(AgentToolDefinition.enabled == True)
        .order_by(AgentToolDefinition.category, AgentToolDefinition.label)
    ).all()


def _serialize_agent_tool(tool: AgentToolDefinition) -> dict[str, Any]:
    return {
        "id": tool.id,
        "label": tool.label,
        "description": tool.description,
        "category": tool.category,
        "tool_name": tool.tool_name,
        "risk": tool.risk,
        "enabled": tool.enabled,
        "requires_mcp_server": tool.requires_mcp_server,
    }


def _serialize_agent_definition(
    definition: AgentDefinition,
    tools_by_id: dict[str, AgentToolDefinition] | None = None,
) -> dict[str, Any]:
    selected_tools: list[dict[str, Any]] = []
    if tools_by_id is not None:
        selected_tools = [
            _serialize_agent_tool(tools_by_id[tool_id]) for tool_id in definition.tool_ids if tool_id in tools_by_id
        ]
    risk_level = "low"
    if selected_tools:
        risk_level = max(
            (str(tool.get("risk") or "low") for tool in selected_tools),
            key=lambda risk: agent_tool_catalog_support.AGENT_RISK_ORDER.get(risk, 0),
        )
    return {
        "id": definition.id,
        "project_id": definition.project_id,
        "name": definition.name,
        "description": definition.description,
        "system_prompt": definition.system_prompt,
        "runtime": getattr(definition, "runtime", "claude_sdk") or "claude_sdk",
        "model": definition.model,
        "model_tier": getattr(definition, "model_tier", None),
        "timeout_seconds": definition.timeout_seconds,
        "tool_ids": definition.tool_ids,
        "test_data_refs": getattr(definition, "test_data_refs", []),
        "tools": selected_tools,
        "risk_level": risk_level,
        "status": definition.status,
        "created_at": definition.created_at.isoformat(),
        "updated_at": definition.updated_at.isoformat(),
    }


def _get_agent_definition_or_404(
    definition_id: str,
    project_id: str | None,
    session: Session,
) -> AgentDefinition:
    definition = session.get(AgentDefinition, definition_id)
    if not definition or definition.status == "archived":
        raise HTTPException(status_code=404, detail="Agent definition not found")
    if project_id:
        if project_id == "default":
            if definition.project_id not in (None, "default"):
                raise HTTPException(status_code=404, detail="Agent definition not found")
        elif definition.project_id != project_id:
            raise HTTPException(status_code=404, detail="Agent definition not found")
    return definition


async def _ensure_agent_write_access(project_id: str | None, current_user: Any, session: Session) -> None:
    if project_id:
        await check_project_access(
            project_id,
            current_user,
            [ProjectRole.ADMIN, ProjectRole.EDITOR],
            session,
        )


def _resolve_agent_tools(tool_ids: list[str], session: Session) -> tuple[list[str], list[dict[str, Any]]]:
    _sync_agent_tool_catalog(session)
    if not tool_ids:
        raise HTTPException(status_code=400, detail="Select at least one tool for this agent")

    tools: list[AgentToolDefinition] = []
    unknown: list[str] = []
    for tool_id in tool_ids:
        tool = session.get(AgentToolDefinition, tool_id)
        if not tool or not tool.enabled:
            unknown.append(tool_id)
        else:
            tools.append(tool)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown or disabled tools: {', '.join(unknown)}")

    allowed_tools = sorted({tool.tool_name for tool in tools})
    return allowed_tools, [_serialize_agent_tool(tool) for tool in tools]
