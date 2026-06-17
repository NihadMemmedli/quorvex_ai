import sys
from importlib import import_module
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session

from .db import get_session

router = APIRouter(tags=["agent-exploratory"])


class ExploratoryRunRequest(BaseModel):
    """Enhanced exploratory testing request."""

    url: str
    time_limit_minutes: int = 15
    instructions: str = ""
    auth: dict[str, Any] | None = None
    test_data: dict[str, Any] | None = None
    test_data_refs: list[str] | None = None
    focus_areas: list[str] | None = None
    excluded_patterns: list[str] | None = None
    project_id: str | None = None
    runtime: str | None = None
    model_tier: str | None = "tool_deep"
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False
    advanced_tools: bool = False
    record_video: bool = False


class GenerateReportItemSpecRequest(BaseModel):
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False
    skip_browser_auth: bool = False
    inherit_browser_auth: bool = False


class GenerateFlowTestRequest(BaseModel):
    browser_auth_session_id: str | None = None
    use_project_default_browser_auth: bool = False
    skip_browser_auth: bool = False
    inherit_browser_auth: bool = True


class FlowUpdateRequest(BaseModel):
    """Partial update request for a discovered flow."""

    title: str | None = None
    pages: list[str] | None = None
    happy_path: str | None = None
    edge_cases: list[str] | None = None
    test_ideas: list[str] | None = None
    entry_point: str | None = None
    exit_point: str | None = None
    complexity: str | None = None


def _runtime() -> Any:
    return (
        sys.modules.get("orchestrator.api.main")
        or sys.modules.get("api.main")
        or import_module("orchestrator.api.main")
    )


@router.post("/api/agents/exploratory")
async def run_exploratory_agent(
    request: ExploratoryRunRequest,
    session: Session = Depends(get_session),
):
    return await _runtime().run_exploratory_agent(request, session=session)


@router.post("/api/agents/exploratory/{run_id}/synthesize")
async def synthesize_specs(run_id: str, session: Session = Depends(get_session)):
    return await _runtime().synthesize_specs(run_id, session=session)


@router.get("/api/agents/exploratory/{run_id}/specs")
async def get_exploration_specs(
    run_id: str,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await _runtime().get_exploration_specs(run_id, project_id=project_id, session=session)


@router.get("/api/agents/exploratory/{run_id}/flows/{flow_id}")
async def get_flow_details(
    run_id: str,
    flow_id: str,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await _runtime().get_flow_details(run_id, flow_id, project_id=project_id, session=session)


@router.put("/api/agents/exploratory/{run_id}/flows/{flow_id}")
async def update_flow(
    run_id: str,
    flow_id: str,
    request: FlowUpdateRequest,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await _runtime().update_flow(run_id, flow_id, request, project_id=project_id, session=session)


@router.delete("/api/agents/exploratory/{run_id}/flows/{flow_id}")
async def delete_flow(
    run_id: str,
    flow_id: str,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await _runtime().delete_flow(run_id, flow_id, project_id=project_id, session=session)


@router.post("/api/agents/exploratory/{run_id}/analyze-prerequisites")
async def analyze_prerequisites(
    run_id: str,
    force_reanalyze: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await _runtime().analyze_prerequisites(
        run_id,
        force_reanalyze=force_reanalyze,
        project_id=project_id,
        session=session,
    )


@router.post("/api/agents/exploratory/{run_id}/flows/{flow_id}/spec")
async def generate_flow_spec(
    run_id: str,
    flow_id: str,
    force_regenerate: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    return await _runtime().generate_flow_spec(
        run_id,
        flow_id,
        force_regenerate=force_regenerate,
        project_id=project_id,
        session=session,
    )


@router.get("/api/agents/exploratory/flow-spec-jobs/{job_id}")
async def get_flow_spec_job_status(job_id: str):
    return await _runtime().get_flow_spec_job_status(job_id)


@router.post("/api/agents/runs/{run_id}/report-items/{item_id}/generate-spec")
async def generate_report_item_spec(
    run_id: str,
    item_id: str,
    item_type: str | None = Query(default=None, description="finding or test_idea"),
    project_id: str = Query(..., description="Project ID for verification"),
    request_body: GenerateReportItemSpecRequest | None = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: Session = Depends(get_session),
):
    return await _runtime().generate_report_item_spec(
        run_id,
        item_id,
        item_type=item_type,
        project_id=project_id,
        request_body=request_body,
        background_tasks=background_tasks,
        session=session,
    )


@router.post("/api/agents/exploratory/{run_id}/flows/{flow_id}/generate")
async def generate_flow_test(
    run_id: str,
    flow_id: str,
    force_regenerate: bool = False,
    project_id: str | None = Query(default=None, description="Project ID for verification"),
    request_body: GenerateFlowTestRequest | None = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    session: Session = Depends(get_session),
):
    return await _runtime().generate_flow_test(
        run_id,
        flow_id,
        force_regenerate=force_regenerate,
        project_id=project_id,
        request_body=request_body,
        background_tasks=background_tasks,
        session=session,
    )
