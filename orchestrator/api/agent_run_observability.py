import asyncio
import json
import sys
from datetime import datetime
from importlib import import_module
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlmodel import Session, select
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from .db import engine, get_session
from .models_db import AgentRun

router = APIRouter(tags=["agent-run-observability"])


def _runtime() -> Any:
    return sys.modules.get("orchestrator.api.main") or sys.modules.get("api.main") or import_module("orchestrator.api.main")


@router.get("/api/agents/runs")
def list_agent_runs(
    project_id: str | None = None,
    status: str | None = Query(default=None, description="Status filter: all, active, completed, failed, cancelled, paused, or exact status"),
    agent_type: str | None = Query(default=None, description="Agent type filter"),
    q: str | None = Query(default=None, description="Case-insensitive search across IDs and compact run metadata"),
    limit: int = Query(default=40, ge=1, le=100, description="Max items to return"),
    cursor: str | None = Query(default=None, description="Cursor returned from the previous page"),
    offset: int = Query(default=0, ge=0, description="Items to skip"),
    session: Session = Depends(get_session),
):
    rt = _runtime()
    filters = rt._agent_run_history_filters(project_id=project_id, status=status, agent_type=agent_type, q=q)
    decoded_cursor = rt._decode_agent_run_cursor(cursor)
    if decoded_cursor:
        cursor_created_at, cursor_id = decoded_cursor
        filters.append(
            or_(
                AgentRun.created_at < cursor_created_at,
                and_(AgentRun.created_at == cursor_created_at, AgentRun.id < cursor_id),
            )
        )

    total_filters = rt._agent_run_history_filters(project_id=project_id, status=status, agent_type=agent_type, q=q)
    total = int(session.exec(select(func.count(AgentRun.id)).where(*total_filters)).one() or 0)
    counts = rt._agent_run_history_counts(session, project_id=project_id, q=q)
    statement = (
        select(
            AgentRun.id,
            AgentRun.agent_type,
            AgentRun.runtime,
            AgentRun.status,
            AgentRun.created_at,
            AgentRun.started_at,
            AgentRun.completed_at,
            AgentRun.project_id,
            AgentRun.config_json,
            AgentRun.progress_json,
        )
        .where(*filters)
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(limit)
    )
    if offset and not cursor:
        statement = statement.offset(offset)

    rows = session.exec(statement).all()
    items = [rt._serialize_agent_run_summary_row(row) for row in rows]
    next_cursor = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = rt._encode_agent_run_cursor(last[4], last[0])
    return {
        "items": items,
        "total": total,
        "counts": counts,
        "next_cursor": next_cursor,
    }


@router.get("/api/agents/runs/{id}")
async def get_agent_run(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    rt = _runtime()
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    rt._filter_agent_run_project(run, project_id)

    payload = await rt._serialize_agent_run_live(run, session)
    payload["temporal"] = await rt._agent_run_temporal_payload(run)
    return payload


@router.get("/api/agents/runs/{id}/events")
def list_agent_run_events_api(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    after_sequence: int = Query(default=0, ge=0),
    event_type: str | None = Query(default=None),
    level: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_session),
):
    rt = _runtime()
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rt._filter_agent_run_project(run, project_id)

    from orchestrator.services.agent_run_events import event_to_response, list_agent_run_events

    events = list_agent_run_events(
        run_id=run.id,
        after_sequence=after_sequence,
        event_type=event_type,
        level=level,
        limit=limit,
        session=session,
    )
    return [event_to_response(event) for event in events]


@router.get("/api/agents/runs/{id}/events/stream")
async def stream_agent_run_events_api(
    request: Request,
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    rt = _runtime()
    with Session(engine) as session:
        run = session.get(AgentRun, id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        rt._filter_agent_run_project(run, project_id)

    async def event_generator():
        sequence = after_sequence
        idle_ticks = 0
        from orchestrator.services.agent_run_events import event_to_response, list_agent_run_events

        while True:
            if await request.is_disconnected():
                break
            terminal = False
            with Session(engine) as session:
                run = session.get(AgentRun, id)
                terminal = bool(run and run.status in rt.AGENT_TERMINAL_STATUSES)
                events = list_agent_run_events(run_id=id, after_sequence=sequence, limit=limit, session=session)
                for event in events:
                    sequence = max(sequence, event.sequence)
                    yield f"data: {json.dumps(event_to_response(event))}\n\n"
                if events:
                    idle_ticks = 0
                else:
                    idle_ticks += 1
            if terminal and not events:
                yield f"event: complete\ndata: {json.dumps({'run_id': id, 'sequence': sequence})}\n\n"
                break
            if idle_ticks >= 15:
                yield f": heartbeat {datetime.utcnow().isoformat()}\n\n"
                idle_ticks = 0
            await asyncio.sleep(1.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/api/agents/runs/{id}/trace")
async def get_agent_run_trace_api(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    rt = _runtime()
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rt._filter_agent_run_project(run, project_id)

    from orchestrator.services.agent_trace import trace_bundle_for_run

    return await trace_bundle_for_run(run=run, session=session)


@router.get("/api/agents/runs/{id}/trace/spans")
def list_agent_run_trace_spans_api(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    trace_id: str | None = Query(default=None),
    span_type: str | None = Query(default=None),
    level: str | None = Query(default=None),
    tool: str | None = Query(default=None),
    q: str | None = Query(default=None),
    after_sequence: int = Query(default=0, ge=0),
    before_sequence: int | None = Query(default=None, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    session: Session = Depends(get_session),
):
    rt = _runtime()
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rt._filter_agent_run_project(run, project_id)

    from orchestrator.services.agent_trace import list_trace_spans, serialize_span

    spans = list_trace_spans(
        run_id=run.id,
        trace_id=trace_id,
        span_type=span_type,
        level=level,
        tool=tool,
        q=q,
        after_sequence=after_sequence,
        before_sequence=before_sequence,
        limit=limit,
        session=session,
    )
    return [serialize_span(span) for span in spans]


@router.get("/api/agents/runs/{id}/trace/export")
async def export_agent_run_trace_api(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    rt = _runtime()
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rt._filter_agent_run_project(run, project_id)

    from orchestrator.services.agent_trace import trace_bundle_for_run

    bundle = await trace_bundle_for_run(run=run, session=session)
    response = JSONResponse(
        {
            "schema": "quorvex.agent_trace_export.v1",
            "exported_at": datetime.utcnow().isoformat(),
            "run": rt._serialize_agent_run(run, session),
            **bundle,
        }
    )
    response.headers["Content-Disposition"] = f'attachment; filename="agent-trace-{run.id}.json"'
    return response


@router.get("/api/agents/temporal/health")
async def get_agent_temporal_health():
    from orchestrator.services.temporal_client import check_agent_run_temporal_health

    return await check_agent_run_temporal_health()
