import sys
from datetime import datetime
from importlib import import_module
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from .db import get_session
from .middleware.auth import get_current_user_optional
from .models_db import AgentRun

router = APIRouter(tags=["agent-run-control"])


def _runtime() -> Any:
    return (
        sys.modules.get("orchestrator.api.main")
        or sys.modules.get("api.main")
        or import_module("orchestrator.api.main")
    )


@router.post("/api/agents/runs/{id}/pause")
async def pause_agent_run(
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
    await rt._ensure_agent_write_access(run.project_id, current_user, session)

    if run.status in rt.AGENT_TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot pause a {run.status} run")
    if run.status == "paused":
        return rt._serialize_agent_run(run, session)

    await rt._signal_agent_run_temporal(run, "pause", "manual_pause")

    rt._mark_agent_run_paused(run)
    session.add(run)
    session.commit()
    session.refresh(run)
    rt._record_agent_run_event(
        run.id,
        event_type="pause",
        message="Agent run paused.",
        payload={"status": run.status, "agent_task_id": run.agent_task_id},
        agent_task_id=run.agent_task_id,
        session=session,
    )
    return rt._serialize_agent_run(run, session)


@router.post("/api/agents/runs/{id}/resume")
async def resume_agent_run(
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
    await rt._ensure_agent_write_access(run.project_id, current_user, session)

    if run.status in rt.AGENT_TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot resume a {run.status} run")
    if run.status != "paused":
        return rt._serialize_agent_run(run, session)

    await rt._signal_agent_run_temporal(run, "resume")

    paused_from = (run.progress or {}).get("paused_from")
    run.status = paused_from if paused_from in {"queued", "running", "pending"} else "queued"
    run.progress = {
        **(run.progress or {}),
        "phase": "resumed",
        "status": run.status,
        "message": "Agent resumed",
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.add(run)
    session.commit()
    session.refresh(run)
    rt._record_agent_run_event(
        run.id,
        event_type="resume",
        message=f"Agent run resumed as {run.status}.",
        payload={"status": run.status, "agent_task_id": run.agent_task_id},
        agent_task_id=run.agent_task_id,
        session=session,
    )
    return rt._serialize_agent_run(run, session)


@router.post("/api/agents/runs/{id}/cancel")
async def cancel_agent_run(
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
    await rt._ensure_agent_write_access(run.project_id, current_user, session)

    if run.status in rt.AGENT_TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot cancel a {run.status} run")

    await rt._signal_agent_run_temporal(run, "cancel", "manual_cancel")

    rt._mark_agent_run_cancelled(run)
    session.add(run)
    session.commit()
    session.refresh(run)
    queue_cancel_result = await rt._cancel_agent_run_queue_task(run)
    rt._record_agent_run_event(
        run.id,
        event_type="cancel",
        message="Agent run cancelled.",
        payload={
            "status": run.status,
            "agent_task_id": run.agent_task_id,
            "queue_cancel": queue_cancel_result,
        },
        agent_task_id=run.agent_task_id,
        session=session,
    )
    return rt._serialize_agent_run(run, session)


@router.post("/api/agents/runs/{id}/retry")
async def retry_agent_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
    current_user: Any = Depends(get_current_user_optional),
):
    rt = _runtime()
    source = session.get(AgentRun, id)
    if not source:
        raise HTTPException(status_code=404, detail="Run not found")
    rt._filter_agent_run_project(source, project_id)
    await rt._ensure_agent_write_access(source.project_id, current_user, session)

    if source.status not in rt.AGENT_TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot retry a {source.status} run")

    retry_config = dict(source.config or {})
    previous_attempt = max(
        rt._coerce_progress_int(retry_config.get("retry_attempt"), 0),
        rt._coerce_progress_int((source.progress or {}).get("retry_attempt"), 0),
    )
    next_attempt = previous_attempt + 1
    previous_workflow_id = source.temporal_workflow_id
    previous_temporal_run_id = source.temporal_run_id
    last_failure = None
    if isinstance(source.result, dict):
        last_failure = source.result.get("error") or source.result.get("summary")
    last_failure = last_failure or (source.progress or {}).get("message") or source.status
    last_observed_url = rt._latest_observed_url_for_run(source)
    artifacts = rt._collect_agent_run_artifacts(source.id) if source.agent_type in ("exploratory", "custom") else []
    artifact_counts = rt._run_artifact_counts(source.id, artifacts)
    retry_config.update(
        {
            "runtime": rt.normalize_agent_runtime(source.runtime or retry_config.get("runtime")),
            "retry_in_place": True,
            "source_run_id": source.id,
            "retry_attempt": next_attempt,
            "retry_context": {
                "attempt": next_attempt,
                "last_failure": str(last_failure)[:1200],
                "last_observed_url": last_observed_url,
                **artifact_counts,
            },
        }
    )
    if source.project_id and not retry_config.get("project_id"):
        retry_config["project_id"] = source.project_id
    browser_metadata = rt.browser_runtime_status() if rt._agent_run_has_browser_tools(source.agent_type, retry_config) else {}
    previous_status = source.status
    source.config = retry_config
    source.runtime = rt.normalize_agent_runtime(retry_config.get("runtime"))
    source.status = "queued"
    source.started_at = None
    source.completed_at = None
    source.agent_task_id = None
    source.temporal_workflow_id = None
    source.temporal_run_id = None
    source.progress = {
        **(source.progress or {}),
        **browser_metadata,
        "phase": "queued",
        "status": "queued",
        "runtime": source.runtime,
        "message": "Retrying in same run using saved browser auth/session artifacts.",
        "retry_in_place": True,
        "retry_attempt": next_attempt,
        "previous_status": previous_status,
        "previous_temporal_workflow_id": previous_workflow_id,
        "previous_temporal_run_id": previous_temporal_run_id,
        "last_failure": str(last_failure)[:1200],
        "last_observed_url": last_observed_url,
        **artifact_counts,
        "updated_at": datetime.utcnow().isoformat(),
    }
    session.add(source)
    session.commit()

    rt._record_agent_run_event(
        source.id,
        event_type="retry_started",
        message="Retrying in same run using saved browser auth/session artifacts.",
        payload={
            "agent_type": source.agent_type,
            "runtime": source.runtime,
            "status": source.status,
            "previous_status": previous_status,
            "retry_attempt": next_attempt,
            "previous_temporal_workflow_id": previous_workflow_id,
            "previous_temporal_run_id": previous_temporal_run_id,
            "last_failure": str(last_failure)[:1200],
            "last_observed_url": last_observed_url,
            **artifact_counts,
        },
        session=session,
    )

    await rt._start_agent_run_temporal_or_fail(source, session, workflow_attempt=next_attempt)
    session.refresh(source)
    return {
        **rt._serialize_agent_run(source, session),
        "run_id": source.id,
        "source_run_id": source.id,
        "retry_in_place": True,
        "retry_attempt": next_attempt,
        "previous_temporal_workflow_id": previous_workflow_id,
    }
