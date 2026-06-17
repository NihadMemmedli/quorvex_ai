import sys
from importlib import import_module
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from .db import get_session

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
    return await _runtime().run_agent(request, session=session)
