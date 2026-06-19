import sys
from datetime import datetime
from importlib import import_module
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from orchestrator.services.coding_agent import (
    CODING_ARTIFACT_PATCH,
    DEFAULT_REPO_ROOT,
    apply_patch_to_repo,
    validate_patch_for_repo,
)

from .db import get_session
from .middleware.auth import get_current_user_optional
from .models_db import AgentRun

router = APIRouter(tags=["agent-coding-patch"])


def _runtime() -> Any:
    return (
        sys.modules.get("orchestrator.api.main")
        or sys.modules.get("api.main")
        or import_module("orchestrator.api.main")
    )


@router.get("/api/agents/runs/{id}/coding/diff")
def get_coding_agent_diff(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    rt = _runtime()
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rt._filter_agent_run_project(run, project_id)
    if run.agent_type != "coding":
        raise HTTPException(status_code=400, detail="Run is not a coding agent run")

    patch_text = rt._read_run_text_artifact(id, CODING_ARTIFACT_PATCH)
    if not patch_text:
        raise HTTPException(status_code=404, detail="Coding patch artifact not found")
    try:
        validation = validate_patch_for_repo(patch_text, DEFAULT_REPO_ROOT)
        valid = True
        validation_error = None
        affected_files = list(validation.paths)
    except Exception as exc:
        valid = False
        validation_error = str(exc)
        affected_files = []
    return {
        "run_id": id,
        "status": run.status,
        "valid": valid,
        "validation_error": validation_error,
        "affected_files": affected_files,
        "diff": patch_text,
        "summary": rt._read_run_text_artifact(id, "summary.md", max_chars=20000),
        "review": rt._read_run_text_artifact(id, "review.md", max_chars=20000),
    }


@router.post("/api/agents/runs/{id}/coding/reject")
async def reject_coding_agent_diff(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    rt = _runtime()
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rt._filter_agent_run_project(run, project_id)
    if run.agent_type != "coding":
        raise HTTPException(status_code=400, detail="Run is not a coding agent run")
    await rt._ensure_agent_write_access(run.project_id, current_user, session)

    existing_result = run.result if isinstance(run.result, dict) else {}
    run.result = {**existing_result, "patch_status": "rejected", "patch_rejected_at": datetime.utcnow().isoformat()}
    run.progress = {
        **(run.progress or {}),
        "phase": "rejected",
        "status": run.status,
        "message": "Coding agent patch rejected.",
        "patch_status": "rejected",
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.add(run)
    session.commit()
    rt._record_agent_run_event(
        id,
        event_type="coding_patch_rejected",
        message="Coding agent patch rejected.",
        payload={"status": run.status, "patch_status": "rejected"},
        agent_task_id=run.agent_task_id,
        session=session,
    )
    return {"status": "rejected", "run_id": id}


@router.post("/api/agents/runs/{id}/coding/apply")
async def apply_coding_agent_diff(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    rt = _runtime()
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rt._filter_agent_run_project(run, project_id)
    if run.agent_type != "coding":
        raise HTTPException(status_code=400, detail="Run is not a coding agent run")
    if run.status not in {"completed", rt.AGENT_PARTIAL_STATUS}:
        raise HTTPException(status_code=409, detail="Coding run must be completed before applying a patch")
    await rt._ensure_agent_write_access(run.project_id, current_user, session)

    existing_result = run.result if isinstance(run.result, dict) else {}
    if existing_result.get("patch_status") == "applied":
        raise HTTPException(status_code=409, detail="Coding patch has already been applied")
    if existing_result.get("patch_status") == "rejected":
        raise HTTPException(status_code=409, detail="Coding patch has been rejected")

    patch_text = rt._read_run_text_artifact(id, CODING_ARTIFACT_PATCH)
    if not patch_text:
        raise HTTPException(status_code=404, detail="Coding patch artifact not found")
    try:
        apply_result = apply_patch_to_repo(patch_text, DEFAULT_REPO_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    applied_at = datetime.utcnow().isoformat()
    run.result = {
        **existing_result,
        "patch_status": "applied",
        "patch_applied_at": applied_at,
        "applied_files": apply_result.get("affected_files") or [],
    }
    run.progress = {
        **(run.progress or {}),
        "phase": "applied",
        "status": run.status,
        "message": "Coding agent patch applied.",
        "patch_status": "applied",
        "affected_files": apply_result.get("affected_files") or [],
        "updated_at": applied_at,
    }
    session.add(run)
    session.commit()
    rt._record_agent_run_event(
        id,
        event_type="coding_patch_applied",
        message="Coding agent patch applied.",
        payload={
            "status": run.status,
            "patch_status": "applied",
            "affected_files": apply_result.get("affected_files") or [],
        },
        agent_task_id=run.agent_task_id,
        session=session,
    )
    return {"status": "applied", "run_id": id, "affected_files": apply_result.get("affected_files") or []}
