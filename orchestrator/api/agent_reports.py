import json
import sys
from datetime import datetime
from importlib import import_module
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from .db import get_session
from .models_db import AgentRun

router = APIRouter(tags=["agent-reports"])


class ImportReportRequirementsRequest(BaseModel):
    item_ids: list[str] | None = None
    import_all: bool = False


class UpdateAgentReportItemRequest(BaseModel):
    patch: dict[str, Any]


class UpdateAgentReportOverviewRequest(BaseModel):
    summary: str | None = None
    scope: str | None = None


def _runtime() -> Any:
    return (
        sys.modules.get("orchestrator.api.main")
        or sys.modules.get("api.main")
        or import_module("orchestrator.api.main")
    )


@router.get("/api/agents/runs/{id}/report")
def get_agent_run_report(
    id: str,
    project_id: str = Query(..., description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    rt = _runtime()
    run = rt._get_agent_report_run(session, id, project_id)

    result = run.result or {}
    artifacts = rt._collect_agent_run_artifacts(run.id) if run.agent_type in ("exploratory", "custom") else []
    structured = result.get("structured_report") if isinstance(result, dict) else None
    if run.agent_type == "custom" and not isinstance(structured, dict):
        structured = rt._build_custom_agent_structured_report(
            result.get("output", "") if isinstance(result, dict) else "",
            run.config,
            artifacts,
        )

    return {
        "id": run.id,
        "agent_type": run.agent_type,
        "status": run.status,
        "created_at": run.created_at.isoformat(),
        "config": run.config,
        "project_id": run.project_id,
        "summary": rt._agent_run_summary(run),
        "structured_report": structured,
        "raw_output": result.get("output") if isinstance(result, dict) else None,
        "artifacts": artifacts,
    }


@router.patch("/api/agents/runs/{run_id}/report")
def update_agent_run_report_overview(
    run_id: str,
    request: UpdateAgentReportOverviewRequest,
    project_id: str = Query(..., description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    rt = _runtime()
    run = rt._get_agent_report_run(session, run_id, project_id)

    result, report = rt._stored_custom_agent_report(run)
    fields_set = getattr(request, "model_fields_set", None)
    if fields_set is None:
        fields_set = getattr(request, "__fields_set__", set())
    if "summary" in fields_set:
        report["summary"] = rt._clean_text(request.summary, 2000)
    if "scope" in fields_set:
        report["scope"] = rt._clean_text(request.scope, 2000)

    result["structured_report"] = report
    run.result = result
    session.add(run)
    session.commit()
    session.refresh(run)

    return {
        "structured_report": report,
        "run": rt._serialize_agent_run(run, session),
    }


@router.patch("/api/agents/runs/{run_id}/report-items/{item_id}")
def update_agent_run_report_item(
    run_id: str,
    item_id: str,
    request: UpdateAgentReportItemRequest,
    item_type: str = Query(..., description="finding, test_idea, or requirement"),
    project_id: str = Query(..., description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    rt = _runtime()
    run = rt._get_agent_report_run(session, run_id, project_id)

    normalized_type = rt._normalize_report_item_type(item_type)
    result, report = rt._stored_custom_agent_report(run)
    item = rt._find_report_item(report, normalized_type, item_id)
    if normalized_type == "requirement" and (
        item.get("imported_requirement_id") or item.get("imported_requirement_code") or item.get("imported_at")
    ):
        raise HTTPException(
            status_code=409,
            detail="This report requirement was already imported. Edit it in Requirements instead.",
        )

    for field, value in rt._editable_report_item_patch(normalized_type, request.patch or {}).items():
        item[field] = value

    result["structured_report"] = report
    run.result = result
    session.add(run)
    session.commit()
    session.refresh(run)

    return {
        "item": item,
        "run": rt._serialize_agent_run(run, session),
    }


@router.get("/api/agents/reports/search")
def search_agent_reports(
    project_id: str | None = Query(default=None),
    query: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    item_type: str | None = Query(default=None, description="finding, test_idea, requirement, page, evidence, or action"),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    rt = _runtime()
    statement = select(AgentRun).where(AgentRun.agent_type == "custom").order_by(AgentRun.created_at.desc())
    if project_id:
        if project_id == "default":
            statement = statement.where((AgentRun.project_id == project_id) | (AgentRun.project_id == None))
        else:
            statement = statement.where(AgentRun.project_id == project_id)

    needle = (query or "").strip().lower()
    severity_filter = (severity or "").strip().lower()
    type_filter = (item_type or "").strip().lower()
    results: list[dict[str, Any]] = []

    for run in session.exec(statement.limit(200)).all():
        result = run.result or {}
        structured = result.get("structured_report") if isinstance(result, dict) else None
        if not isinstance(structured, dict):
            continue

        collections = {
            "finding": structured.get("findings") or [],
            "test_idea": structured.get("test_ideas") or [],
            "requirement": structured.get("requirements") or [],
            "page": structured.get("pages_checked") or [],
            "evidence": structured.get("evidence") or [],
            "action": structured.get("follow_up_actions") or [],
        }
        for current_type, items in collections.items():
            if type_filter and current_type != type_filter:
                continue
            for item in rt._as_report_list(items):
                if not isinstance(item, dict):
                    continue
                haystack = json.dumps(item, ensure_ascii=False).lower()
                if needle and needle not in haystack:
                    continue
                item_severity = rt._clean_text(item.get("severity") or item.get("priority"), 30).lower()
                if severity_filter and item_severity != severity_filter:
                    continue
                results.append(
                    {
                        "run_id": run.id,
                        "agent_name": run.config.get("agent_name") or "Custom Agent",
                        "created_at": run.created_at.isoformat(),
                        "type": current_type,
                        "item": item,
                    }
                )
                if len(results) >= limit:
                    return {"items": results, "count": len(results)}
    return {"items": results, "count": len(results)}


@router.post("/api/agents/runs/{run_id}/report-requirements/import")
def import_agent_report_requirements(
    run_id: str,
    request: ImportReportRequirementsRequest,
    project_id: str = Query(..., description="Project ID for verification"),
    session: Session = Depends(get_session),
):
    """Import reviewed custom-agent report requirements as candidate requirements."""
    from memory.exploration_store import get_exploration_store

    rt = _runtime()
    run = rt._get_agent_report_run(session, run_id, project_id)
    if run.agent_type != "custom":
        raise HTTPException(status_code=400, detail="Only custom agent reports can import requirements")

    result = run.result or {}
    report = result.get("structured_report") if isinstance(result, dict) else None
    if not isinstance(report, dict):
        raise HTTPException(status_code=400, detail="This run does not have a stored structured report")

    requirements_items = [item for item in rt._as_report_list(report.get("requirements")) if isinstance(item, dict)]
    if not requirements_items:
        raise HTTPException(status_code=400, detail="This report does not contain structured requirements")

    requested_ids = {rt._clean_text(item_id, 80) for item_id in (request.item_ids or []) if rt._clean_text(item_id, 80)}
    if not request.import_all and not requested_ids:
        raise HTTPException(status_code=400, detail="Provide item_ids or set import_all=true")

    indexed = {str(item.get("id") or ""): item for item in requirements_items if item.get("id")}
    if request.import_all:
        selected = requirements_items
    else:
        missing = sorted(item_id for item_id in requested_ids if item_id not in indexed)
        if missing:
            raise HTTPException(status_code=404, detail={"message": "Report requirement item not found", "missing_item_ids": missing})
        selected = [indexed[item_id] for item_id in requested_ids]

    target_project_id = run.project_id or project_id or run.config.get("project_id") or "default"
    store = get_exploration_store(project_id=target_project_id)
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for item in selected:
        item_id = rt._clean_text(item.get("id"), 80)
        imported_id = item.get("imported_requirement_id")
        imported_code = item.get("imported_requirement_code")
        if imported_id or imported_code:
            skipped.append(
                {
                    "item_id": item_id,
                    "reason": "already_imported",
                    "requirement_id": imported_id,
                    "req_code": imported_code,
                }
            )
            continue

        body = rt._requirement_create_body_from_report_item(item)
        if not body["title"]:
            skipped.append({"item_id": item_id, "reason": "missing_title"})
            continue

        req_code = store.get_next_requirement_code()
        requirement = store.store_requirement(
            req_code=req_code,
            title=body["title"],
            description=body["description"],
            category=body["category"],
            priority=body["priority"],
            acceptance_criteria=body["acceptance_criteria"],
            truth_state=body["truth_state"],
            source_type=body["source_type"],
            confidence=body["confidence"],
            uncertainty_reason=body["uncertainty_reason"],
        )
        item["imported_requirement_id"] = requirement.id
        item["imported_requirement_code"] = requirement.req_code
        item["imported_at"] = datetime.utcnow().isoformat()
        created.append(
            {
                "item_id": item_id,
                "id": requirement.id,
                "req_code": requirement.req_code,
                "title": requirement.title,
                "project_id": target_project_id,
            }
        )

    if not isinstance(result, dict):
        result = {}
    result["structured_report"] = report
    run.result = result
    session.add(run)
    session.commit()
    session.refresh(run)

    if created:
        rt._record_agent_run_event(
            run.id,
            event_type="requirements_imported",
            message=f"Imported {len(created)} custom-agent report requirement(s).",
            payload={
                "created_requirements": created,
                "created_requirement_ids": [item["id"] for item in created],
                "created_requirement_codes": [item["req_code"] for item in created],
                "skipped": skipped,
            },
            session=session,
        )

    return {
        "created": len(created),
        "skipped": len(skipped),
        "requirements": created,
        "skipped_items": skipped,
        "run": rt._serialize_agent_run(run, session),
    }
