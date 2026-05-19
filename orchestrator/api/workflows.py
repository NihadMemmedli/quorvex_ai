"""Custom workflow definition and execution endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from .db import get_session
from .middleware.auth import get_current_user_optional
from .middleware.permissions import ProjectRole, check_project_access
from .models_db import WorkflowDefinition, WorkflowRun, WorkflowRunStep
from orchestrator.services.workflow_runner import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    create_workflow_run_steps,
    duplicate_workflow_definition_record,
    launch_workflow_run,
    reset_workflow_run_for_step_retry,
    validate_workflow_steps,
    workflow_step_catalog,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowStepSpec(BaseModel):
    key: str | None = None
    type: str
    label: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    continue_on_error: bool = False


class WorkflowDefinitionRequest(BaseModel):
    name: str
    description: str = ""
    project_id: str | None = None
    steps: list[WorkflowStepSpec]


class WorkflowDefinitionUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    steps: list[WorkflowStepSpec] | None = None
    status: str | None = None


class WorkflowRunRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    triggered_by: str | None = None
    start_step_key: str | None = None


def _step_to_dict(step: WorkflowRunStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "run_id": step.run_id,
        "definition_id": step.definition_id,
        "step_order": step.step_order,
        "step_key": step.step_key,
        "step_type": step.step_type,
        "label": step.label,
        "status": step.status,
        "continue_on_error": step.continue_on_error,
        "input": step.input,
        "output": step.output,
        "error_message": step.error_message,
        "external_kind": step.external_kind,
        "external_id": step.external_id,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "completed_at": step.completed_at.isoformat() if step.completed_at else None,
        "updated_at": step.updated_at.isoformat() if step.updated_at else None,
    }


def _definition_to_dict(definition: WorkflowDefinition) -> dict[str, Any]:
    return {
        "id": definition.id,
        "project_id": definition.project_id,
        "name": definition.name,
        "description": definition.description,
        "steps": definition.steps,
        "status": definition.status,
        "created_by": definition.created_by,
        "created_at": definition.created_at.isoformat(),
        "updated_at": definition.updated_at.isoformat(),
    }


def _run_to_dict(run: WorkflowRun, session: Session, *, include_steps: bool = True) -> dict[str, Any]:
    payload = {
        "id": run.id,
        "definition_id": run.definition_id,
        "project_id": run.project_id,
        "status": run.status,
        "current_step_index": run.current_step_index,
        "progress": run.progress,
        "inputs": run.inputs,
        "context": run.context,
        "result": run.result,
        "error_message": run.error_message,
        "triggered_by": run.triggered_by,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "updated_at": run.updated_at.isoformat(),
    }
    definition = session.get(WorkflowDefinition, run.definition_id)
    if definition:
        payload["definition"] = {
            "id": definition.id,
            "name": definition.name,
            "description": definition.description,
        }
    if include_steps:
        steps = session.exec(
            select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id).order_by(WorkflowRunStep.step_order)
        ).all()
        payload["steps"] = [_step_to_dict(step) for step in steps]
    return payload


async def _ensure_write_access(project_id: str | None, user: Any, session: Session) -> None:
    if project_id:
        await check_project_access(project_id, user, [ProjectRole.ADMIN, ProjectRole.EDITOR], session)


def _get_definition_or_404(definition_id: str, project_id: str | None, session: Session) -> WorkflowDefinition:
    definition = session.get(WorkflowDefinition, definition_id)
    if not definition or definition.status == "archived":
        raise HTTPException(status_code=404, detail="Workflow definition not found")
    if project_id:
        if project_id == "default":
            if definition.project_id not in (None, "default"):
                raise HTTPException(status_code=404, detail="Workflow definition not found")
        elif definition.project_id != project_id:
            raise HTTPException(status_code=404, detail="Workflow definition not found")
    return definition


@router.get("/catalog")
def get_workflow_catalog():
    return {"steps": workflow_step_catalog()}


@router.get("")
def get_workflow_overview(
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    active_statuses = {"queued", "running", "awaiting_input", "paused"}
    definitions_stmt = select(WorkflowDefinition).where(WorkflowDefinition.status == "active")
    runs_stmt = select(WorkflowRun)
    if project_id:
        definitions_stmt = definitions_stmt.where(WorkflowDefinition.project_id == project_id)
        runs_stmt = runs_stmt.where(WorkflowRun.project_id == project_id)
    definitions = session.exec(definitions_stmt).all()
    runs = session.exec(runs_stmt).all()
    return {
        "definitions": len(definitions),
        "runs": len(runs),
        "active_runs": len([run for run in runs if run.status in active_statuses]),
        "failed_runs": len([run for run in runs if run.status == "failed"]),
        "completed_runs": len([run for run in runs if run.status == "completed"]),
    }


@router.get("/definitions")
def list_workflow_definitions(
    project_id: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    session: Session = Depends(get_session),
):
    stmt = select(WorkflowDefinition).order_by(WorkflowDefinition.updated_at.desc())
    if not include_archived:
        stmt = stmt.where(WorkflowDefinition.status == "active")
    if project_id:
        if project_id == "default":
            stmt = stmt.where((WorkflowDefinition.project_id == project_id) | (WorkflowDefinition.project_id == None))
        else:
            stmt = stmt.where(WorkflowDefinition.project_id == project_id)
    return [_definition_to_dict(item) for item in session.exec(stmt).all()]


@router.post("/definitions")
async def create_workflow_definition(
    request: WorkflowDefinitionRequest,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    await _ensure_write_access(request.project_id, user, session)
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Workflow name is required")
    try:
        steps = validate_workflow_steps([step.model_dump() for step in request.steps])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    definition = WorkflowDefinition(
        project_id=request.project_id,
        name=request.name.strip(),
        description=request.description.strip(),
        created_by=getattr(user, "id", None),
    )
    definition.steps = steps
    session.add(definition)
    session.commit()
    session.refresh(definition)
    return _definition_to_dict(definition)


@router.get("/definitions/{definition_id}")
def get_workflow_definition(
    definition_id: str,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    return _definition_to_dict(_get_definition_or_404(definition_id, project_id, session))


@router.post("/definitions/{definition_id}/duplicate")
async def duplicate_workflow_definition(
    definition_id: str,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    await _ensure_write_access(definition.project_id, user, session)
    clone = duplicate_workflow_definition_record(definition, created_by=getattr(user, "id", None))
    session.add(clone)
    session.commit()
    session.refresh(clone)
    return _definition_to_dict(clone)


@router.get("/definitions/{definition_id}/runs")
def list_definition_runs(
    definition_id: str,
    project_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    stmt = (
        select(WorkflowRun)
        .where(WorkflowRun.definition_id == definition.id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(limit)
    )
    return [_run_to_dict(run, session, include_steps=False) for run in session.exec(stmt).all()]


@router.put("/definitions/{definition_id}")
async def update_workflow_definition(
    definition_id: str,
    request: WorkflowDefinitionUpdateRequest,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    await _ensure_write_access(definition.project_id, user, session)

    if request.name is not None:
        if not request.name.strip():
            raise HTTPException(status_code=400, detail="Workflow name is required")
        definition.name = request.name.strip()
    if request.description is not None:
        definition.description = request.description.strip()
    if request.steps is not None:
        try:
            definition.steps = validate_workflow_steps([step.model_dump() for step in request.steps])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if request.status is not None:
        if request.status not in {"active", "archived"}:
            raise HTTPException(status_code=400, detail="Invalid workflow status")
        definition.status = request.status
    definition.updated_at = datetime.utcnow()
    session.add(definition)
    session.commit()
    session.refresh(definition)
    return _definition_to_dict(definition)


@router.delete("/definitions/{definition_id}")
async def archive_workflow_definition(
    definition_id: str,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    await _ensure_write_access(definition.project_id, user, session)
    definition.status = "archived"
    definition.updated_at = datetime.utcnow()
    session.add(definition)
    session.commit()
    return {"status": "archived", "id": definition.id}


@router.post("/definitions/{definition_id}/runs")
async def start_workflow_run(
    definition_id: str,
    request: WorkflowRunRequest,
    background_tasks: BackgroundTasks,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    await _ensure_write_access(definition.project_id, user, session)
    if request.start_step_key and not any(step.get("key") == request.start_step_key for step in definition.steps):
        raise HTTPException(status_code=400, detail=f"Workflow step not found: {request.start_step_key}")
    active_count = session.exec(
        select(WorkflowRun)
        .where(WorkflowRun.project_id == definition.project_id)
        .where(WorkflowRun.status.in_(list(ACTIVE_STATUSES)))
    ).all()
    if len(active_count) >= 10:
        raise HTTPException(status_code=429, detail="Too many active workflow runs for this project")

    run = WorkflowRun(
        definition_id=definition.id,
        workflow_id=definition.id,
        project_id=definition.project_id,
        status="queued",
        triggered_by=request.triggered_by or getattr(user, "id", None) or "ui",
    )
    run.inputs = request.inputs
    session.add(run)
    session.commit()
    session.refresh(run)
    try:
        create_workflow_run_steps(session, definition, run, start_step_key=request.start_step_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(launch_workflow_run, run.id)
    return {"run_id": run.id, "status": run.status, "definition_id": definition.id}


@router.get("/runs")
def list_workflow_runs(
    project_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    stmt = select(WorkflowRun).order_by(WorkflowRun.created_at.desc())
    if project_id:
        stmt = stmt.where(WorkflowRun.project_id == project_id)
    if status:
        stmt = stmt.where(WorkflowRun.status == status)
    runs = session.exec(stmt.limit(limit)).all()
    return [_run_to_dict(run, session, include_steps=False) for run in runs]


@router.get("/runs/{run_id}")
def get_workflow_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return _run_to_dict(run, session)


@router.get("/runs/{run_id}/steps")
def list_workflow_run_steps(run_id: str, session: Session = Depends(get_session)):
    if not session.get(WorkflowRun, run_id):
        raise HTTPException(status_code=404, detail="Workflow run not found")
    steps = session.exec(
        select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id).order_by(WorkflowRunStep.step_order)
    ).all()
    return [_step_to_dict(step) for step in steps]


@router.post("/runs/{run_id}/steps/{step_id}/retry")
def retry_workflow_run_step(run_id: str, step_id: int, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    step = session.get(WorkflowRunStep, step_id)
    if not step or step.run_id != run_id:
        raise HTTPException(status_code=404, detail="Workflow run step not found")
    try:
        reset_workflow_run_for_step_retry(session, run, step)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background_tasks.add_task(launch_workflow_run, run.id)
    return {"run_id": run.id, "step_id": step.id, "status": "queued"}


@router.post("/runs/{run_id}/pause")
def pause_workflow_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Cannot pause a terminal workflow run")
    run.status = "paused"
    run.updated_at = datetime.utcnow()
    session.add(run)
    session.commit()
    return {"run_id": run.id, "status": run.status}


@router.post("/runs/{run_id}/resume")
def resume_workflow_run(run_id: str, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Cannot resume a terminal workflow run")
    if run.status == "awaiting_input":
        steps = session.exec(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id)).all()
        for step in steps:
            if step.status == "awaiting_input":
                step.status = "completed"
                step.completed_at = datetime.utcnow()
                step.updated_at = datetime.utcnow()
                session.add(step)
    run.status = "queued"
    run.updated_at = datetime.utcnow()
    session.add(run)
    session.commit()
    background_tasks.add_task(launch_workflow_run, run.id)
    return {"run_id": run.id, "status": "running"}


@router.post("/runs/{run_id}/cancel")
def cancel_workflow_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Workflow run is already terminal")
    run.status = "cancelled"
    run.completed_at = datetime.utcnow()
    run.updated_at = datetime.utcnow()
    steps = session.exec(
        select(WorkflowRunStep)
        .where(WorkflowRunStep.run_id == run_id)
        .where(WorkflowRunStep.status.in_(["pending", "running", "awaiting_input", "paused"]))
    ).all()
    for step in steps:
        step.status = "cancelled"
        step.completed_at = datetime.utcnow()
        step.updated_at = datetime.utcnow()
        session.add(step)
    session.add(run)
    session.commit()
    return {"run_id": run.id, "status": run.status}
