"""Custom workflow definition and execution endpoints."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from orchestrator.config import settings
from orchestrator.services.temporal_client import (
    TemporalUnavailableError,
    check_custom_workflow_temporal_health,
    get_custom_workflow_temporal_diagnostics,
    signal_custom_workflow_run,
    start_custom_workflow_run,
)
from orchestrator.services.agent_cancellation import cancel_workflow_child_agent_runs
from orchestrator.services.workflow_operations import (
    create_workflow_revision,
    emit_workflow_event,
    ensure_workflow_revision,
    json_changed,
    percentile,
    query_workflow_events,
    restore_workflow_revision,
    workflow_duration_seconds,
    workflow_event_to_dict,
    workflow_notification_to_dict,
    workflow_revision_diff,
    workflow_schedule_execution_to_dict,
    workflow_schedule_to_dict,
)
from orchestrator.services.workflow_runner import (
    ACTIVE_STATUSES,
    RECOVERY_ACTIONS,
    TERMINAL_STATUSES,
    create_workflow_run_steps,
    duplicate_workflow_definition_record,
    reset_workflow_run_for_step_retry,
    validate_workflow_definition_payload,
    validate_workflow_steps,
    workflow_step_catalog,
)
from orchestrator.services.workflow_step_registry import WORKFLOW_TEMPLATES, sync_builtin_workflow_step_types

from .db import get_session
from .middleware.auth import get_current_user_optional
from .middleware.permissions import ProjectRole, check_project_access
from .models_db import (
    AgentRun,
    WorkflowDefinition,
    WorkflowDefinitionRevision,
    WorkflowEvent,
    WorkflowNotification,
    WorkflowRun,
    WorkflowRunStep,
    WorkflowSchedule,
    WorkflowScheduleExecution,
)
from .time_utils import utc_iso

router = APIRouter(prefix="/workflows", tags=["workflows"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = BASE_DIR / "runs"


class WorkflowStepSpec(BaseModel):
    key: str | None = None
    type: str
    label: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    continue_on_error: bool = False
    recovery_policy: dict[str, Any] | None = None


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
    trigger_type: str | None = None
    trigger_id: str | None = None
    recovery_policy: dict[str, Any] = Field(default_factory=dict)


class WorkflowValidationRequest(WorkflowDefinitionRequest):
    pass


class WorkflowImportRequest(BaseModel):
    project_id: str | None = None
    workflow: dict[str, Any]


class WorkflowRollbackRequest(BaseModel):
    change_summary: str | None = None


class WorkflowScheduleRequest(BaseModel):
    definition_id: str
    revision_id: str | None = None
    revision_mode: str = Field(default="pinned", pattern="^(latest|pinned)$")
    name: str
    description: str = ""
    cron_expression: str
    timezone: str = "UTC"
    inputs: dict[str, Any] = Field(default_factory=dict)
    start_step_key: str | None = None
    enabled: bool = True
    notify_on_completion: bool = False
    notify_on_failure: bool = True
    notify_on_review_needed: bool = True


class WorkflowScheduleUpdateRequest(BaseModel):
    revision_id: str | None = None
    revision_mode: str | None = Field(default=None, pattern="^(latest|pinned)$")
    name: str | None = None
    description: str | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    inputs: dict[str, Any] | None = None
    start_step_key: str | None = None
    enabled: bool | None = None
    notify_on_completion: bool | None = None
    notify_on_failure: bool | None = None
    notify_on_review_needed: bool | None = None


def _step_to_dict(step: WorkflowRunStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "run_id": step.run_id,
        "definition_id": step.definition_id,
        "step_order": step.step_order,
        "step_key": step.step_key,
        "step_type": step.step_type,
        "step_type_version": step.step_type_version,
        "label": step.label,
        "status": step.status,
        "continue_on_error": step.continue_on_error,
        "input": step.input,
        "rendered_input": step.rendered_input,
        "context_snapshot": step.context_snapshot,
        "input_resolution": step.input_resolution,
        "output": step.output,
        "output_validation_errors": step.output_validation_errors,
        "step_config": step.step_config,
        "error_message": step.error_message,
        "attempt_count": step.attempt_count,
        "max_attempts": step.max_attempts,
        "retry_backoff_seconds": step.retry_backoff_seconds,
        "recovery_action": step.recovery_action,
        "skipped_reason": step.skipped_reason,
        "external_kind": step.external_kind,
        "external_id": step.external_id,
        "started_at": utc_iso(step.started_at),
        "completed_at": utc_iso(step.completed_at),
        "updated_at": utc_iso(step.updated_at),
    }


def _definition_to_dict(definition: WorkflowDefinition) -> dict[str, Any]:
    return {
        "id": definition.id,
        "project_id": definition.project_id,
        "name": definition.name,
        "description": definition.description,
        "version": definition.version,
        "steps": definition.steps,
        "status": definition.status,
        "created_by": definition.created_by,
        "created_at": utc_iso(definition.created_at),
        "updated_at": utc_iso(definition.updated_at),
    }


def _definition_export(definition: WorkflowDefinition) -> dict[str, Any]:
    return {
        "schema_version": "quorvex.workflow.v1",
        "name": definition.name,
        "description": definition.description,
        "version": definition.version,
        "steps": definition.steps,
        "metadata": {
            "source": "quorvex",
            "exported_at": utc_iso(datetime.utcnow()),
        },
    }


def _run_to_dict(run: WorkflowRun, session: Session, *, include_steps: bool = True) -> dict[str, Any]:
    payload = {
        "id": run.id,
        "definition_id": run.definition_id,
        "revision_id": run.revision_id,
        "definition_version": run.definition_version,
        "project_id": run.project_id,
        "status": run.status,
        "current_step_index": run.current_step_index,
        "progress": run.progress,
        "inputs": run.inputs,
        "context": run.context,
        "recovery_policy": run.recovery_policy,
        "result": run.result,
        "error_message": run.error_message,
        "triggered_by": run.triggered_by,
        "trigger_type": run.trigger_type,
        "trigger_id": run.trigger_id,
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
        "heartbeat_at": utc_iso(run.heartbeat_at),
        "pause_reason": run.pause_reason,
        "created_at": utc_iso(run.created_at),
        "started_at": utc_iso(run.started_at),
        "completed_at": utc_iso(run.completed_at),
        "updated_at": utc_iso(run.updated_at),
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


def _short_text(value: Any, limit: int = 280) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except TypeError:
            text = str(value)
    if not text:
        return None
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown").lower()
        counts[value] = counts.get(value, 0) + 1
    return counts


def _step_duration_seconds(step: WorkflowRunStep) -> int | None:
    if not step.started_at:
        return None
    end = step.completed_at or datetime.utcnow()
    return max(int((end - step.started_at).total_seconds()), 0)


def _output_summary(output: dict[str, Any] | None) -> str | None:
    if not isinstance(output, dict):
        return None
    candidates = [
        output.get("summary"),
        output.get("message"),
        output.get("status_message"),
        output.get("error_message"),
    ]
    result = output.get("result")
    if isinstance(result, dict):
        candidates.extend([result.get("summary"), result.get("message"), result.get("error_message")])
    structured = output.get("structured_report")
    if isinstance(structured, dict):
        candidates.extend([structured.get("summary"), structured.get("title")])
    for candidate in candidates:
        text = _short_text(candidate)
        if text:
            return text
    return None


def _normalise_finding(raw: Any, *, run: WorkflowRun, step: WorkflowRunStep | None, source_kind: str) -> dict[str, Any] | None:
    if isinstance(raw, str):
        raw = {"title": raw}
    if not isinstance(raw, dict):
        return None
    title = _short_text(raw.get("title") or raw.get("name") or raw.get("summary") or raw.get("message") or raw.get("description"), 180)
    description = _short_text(raw.get("description") or raw.get("details") or raw.get("message") or raw.get("error"), 700)
    evidence = _short_text(raw.get("evidence") or raw.get("actual") or raw.get("stack") or raw.get("failure"), 1000)
    if not title and not description and not evidence:
        return None
    return {
        "id": raw.get("id") or raw.get("fingerprint") or f"{source_kind}:{step.id if step else run.id}:{abs(hash(str(raw))) % 1000000}",
        "workflow_run_id": run.id,
        "workflow_step_id": step.id if step else None,
        "step_key": step.step_key if step else None,
        "source_kind": source_kind,
        "source_run_id": (step.external_id if step else None) or raw.get("run_id") or raw.get("scan_id"),
        "severity": str(raw.get("severity") or raw.get("level") or raw.get("priority") or "info").lower(),
        "category": raw.get("category") or raw.get("type") or raw.get("scanner"),
        "title": title or "Finding",
        "description": description,
        "evidence": evidence,
        "recommendation": _short_text(raw.get("recommendation") or raw.get("remediation") or raw.get("fix"), 700),
        "status": str(raw.get("status") or "open").lower(),
    }


def _collect_findings_from_output(run: WorkflowRun, step: WorkflowRunStep) -> list[dict[str, Any]]:
    output = step.output if isinstance(step.output, dict) else {}
    sources: list[Any] = [
        output.get("findings"),
        output.get("issues"),
        output.get("failures"),
    ]
    result = output.get("result")
    if isinstance(result, dict):
        sources.extend([result.get("findings"), result.get("issues"), result.get("failures")])
    structured = output.get("structured_report")
    if isinstance(structured, dict):
        sources.extend([structured.get("findings"), structured.get("issues")])

    findings: list[dict[str, Any]] = []
    for source in sources:
        values = source if isinstance(source, list) else [source] if source else []
        for raw in values:
            finding = _normalise_finding(raw, run=run, step=step, source_kind=step.external_kind or step.step_type)
            if finding:
                findings.append(finding)
    return findings


def _collect_test_run_findings(run: WorkflowRun, step: WorkflowRunStep) -> list[dict[str, Any]]:
    if step.external_kind != "test_run" or not step.external_id:
        return []
    run_dir = RUNS_DIR / step.external_id
    results_path = run_dir / "test-results.json"
    if not results_path.exists():
        if step.error_message:
            finding = _normalise_finding(
                {"title": "Test run failed", "description": step.error_message, "severity": "error", "category": "test_run"},
                run=run,
                step=step,
                source_kind="test_run",
            )
            return [finding] if finding else []
        return []
    try:
        from orchestrator.utils.test_results_parser import parse_test_results

        parsed = parse_test_results(str(results_path))
    except Exception:
        parsed = None
    findings: list[dict[str, Any]] = []
    for test in (parsed or {}).get("tests") or []:
        if test.get("status") not in {"failed", "timedOut"}:
            continue
        error = test.get("error") if isinstance(test.get("error"), dict) else {}
        finding = _normalise_finding(
            {
                "title": test.get("full_title") or test.get("title") or "Failed test",
                "description": error.get("message") or "Test failed",
                "evidence": error.get("stack"),
                "severity": "error",
                "category": error.get("category") or "test_failure",
                "status": "open",
                "file": test.get("file"),
            },
            run=run,
            step=step,
            source_kind="test_run",
        )
        if finding:
            findings.append(finding)
    return findings


def _collect_artifacts_from_step(step: WorkflowRunStep) -> list[dict[str, Any]]:
    output = step.output if isinstance(step.output, dict) else {}
    candidates: list[Any] = [output.get("artifacts")]
    result = output.get("result")
    if isinstance(result, dict):
        candidates.append(result.get("artifacts"))
    artifacts: list[dict[str, Any]] = []
    for candidate in candidates:
        values = candidate if isinstance(candidate, list) else [candidate] if candidate else []
        for index, raw in enumerate(values):
            if isinstance(raw, str):
                item = {"name": raw.rsplit("/", 1)[-1], "path": raw}
            elif isinstance(raw, dict):
                item = dict(raw)
            else:
                continue
            item.setdefault("source_step_id", step.id)
            item.setdefault("step_key", step.step_key)
            item.setdefault("source_kind", step.external_kind or step.step_type)
            item.setdefault("id", f"{step.id}:{index}:{item.get('name') or item.get('path') or item.get('url')}")
            artifacts.append(item)
    if step.external_kind == "test_run" and step.external_id:
        run_dir = RUNS_DIR / step.external_id
        if run_dir.exists():
            for file in run_dir.glob("**/*"):
                if file.is_file() and file.suffix.lower() in {".png", ".jpg", ".jpeg", ".webm", ".mp4", ".zip", ".html"}:
                    try:
                        rel = file.relative_to(RUNS_DIR)
                    except ValueError:
                        continue
                    artifacts.append(
                        {
                            "id": f"{step.id}:{rel}",
                            "name": file.name,
                            "path": f"/artifacts/{rel}",
                            "type": "image" if file.suffix.lower() in {".png", ".jpg", ".jpeg"} else file.suffix.lower().lstrip("."),
                            "source_step_id": step.id,
                            "step_key": step.step_key,
                            "source_kind": "test_run",
                        }
                    )
    return artifacts


def _dedupe_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for artifact in artifacts:
        key = (
            str(artifact.get("source_step_id") or artifact.get("step_key") or ""),
            str(artifact.get("path") or artifact.get("url") or artifact.get("name") or ""),
            str(artifact.get("type") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return deduped


def _collect_agent_child_artifacts(agent_run_id: str) -> list[dict[str, Any]]:
    suffix_types = {
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".webm": "video",
        ".mp4": "video",
    }
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for runs_root in (RUNS_DIR, Path("/app/runs")):
        session_dir = runs_root / agent_run_id
        if not session_dir.exists():
            continue
        for file in session_dir.glob("**/*"):
            if not file.is_file():
                continue
            artifact_type = suffix_types.get(file.suffix.lower())
            if not artifact_type:
                continue
            try:
                resolved = str(file.resolve())
                if resolved in seen:
                    continue
                seen.add(resolved)
                rel = file.relative_to(runs_root)
                modified_at = datetime.utcfromtimestamp(file.stat().st_mtime)
            except (OSError, ValueError):
                continue
            artifacts.append(
                {
                    "name": file.name,
                    "path": f"/artifacts/{rel}",
                    "type": artifact_type,
                    "modified_at": utc_iso(modified_at),
                }
            )
    return sorted(
        artifacts,
        key=lambda item: (
            item.get("type") != "video",
            str(item.get("modified_at") or ""),
            str(item.get("name") or ""),
        ),
        reverse=True,
    )


def _safe_agent_progress(progress: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(progress, dict):
        return {}
    allowed_keys = {
        "phase",
        "status",
        "message",
        "current_stage",
        "activity_label",
        "tool_calls",
        "browser_tool_calls",
        "interactions",
        "last_tool",
        "last_tool_label",
        "recent_tools",
        "has_browser_tools",
        "updated_at",
        "agent_task_id",
    }
    safe = {key: progress.get(key) for key in allowed_keys if progress.get(key) is not None}
    recent_tools = safe.get("recent_tools")
    if isinstance(recent_tools, list):
        safe["recent_tools"] = [
            {
                "name": str(item.get("name") or ""),
                "label": str(item.get("label") or item.get("name") or ""),
                "at": item.get("at"),
            }
            for item in recent_tools
            if isinstance(item, dict)
        ][-12:]
    else:
        safe.pop("recent_tools", None)
    return safe


def _agent_run_summary(run: AgentRun) -> str | None:
    result = run.result if isinstance(run.result, dict) else {}
    structured = result.get("structured_report") if isinstance(result, dict) else None
    if isinstance(structured, dict) and structured.get("summary"):
        return str(structured.get("summary"))
    if isinstance(result, dict) and result.get("summary"):
        return str(result.get("summary"))
    progress = run.progress if isinstance(run.progress, dict) else {}
    if progress.get("message"):
        return str(progress.get("message"))
    return None


def _external_child_for_step(step: WorkflowRunStep, session: Session) -> dict[str, Any] | None:
    external_id = step.external_id
    external_kind = step.external_kind
    if not external_id or not external_kind:
        output = step.output if isinstance(step.output, dict) else {}
        external_id = output.get("external_id")
        external_kind = output.get("external_kind") or external_kind
    if not external_id or not external_kind:
        return None
    output = step.output if isinstance(step.output, dict) else {}
    result = output.get("result") if isinstance(output.get("result"), dict) else {}
    child = {
        "kind": external_kind,
        "id": external_id,
        "step_id": step.id,
        "step_key": step.step_key,
        "status": output.get("status") or result.get("status") or step.status,
        "summary": _output_summary(output),
    }
    if external_kind == "agent_run":
        agent_run = session.get(AgentRun, external_id)
        if agent_run:
            artifacts = _collect_agent_child_artifacts(external_id)
            child.update(
                {
                    "status": agent_run.status,
                    "summary": _output_summary(output) or _agent_run_summary(agent_run),
                    "agent_type": agent_run.agent_type,
                    "progress": _safe_agent_progress(agent_run.progress),
                    "artifacts": artifacts,
                    "latest_image": next((artifact for artifact in artifacts if artifact.get("type") == "image"), None),
                    "agent_task_id": agent_run.agent_task_id,
                }
            )
    return child


def _build_debug_timeline(run: WorkflowRun, steps: list[WorkflowRunStep], events: list[WorkflowEvent]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [
        {
            "type": "run",
            "status": "created",
            "title": "Run created",
            "message": f"Workflow run {run.id} was created.",
            "created_at": utc_iso(run.created_at),
        }
    ]
    if run.started_at:
        items.append(
            {
                "type": "run",
                "status": "started",
                "title": "Run started",
                "message": "Workflow execution started.",
                "created_at": utc_iso(run.started_at),
            }
        )
    for step in steps:
        if step.started_at:
            items.append(
                {
                    "type": "step",
                    "status": step.status,
                    "title": f"Started {step.label or step.step_key}",
                    "message": _output_summary(step.output) or step.error_message,
                    "step_id": step.id,
                    "step_key": step.step_key,
                    "created_at": utc_iso(step.started_at),
                }
            )
        if step.completed_at:
            items.append(
                {
                    "type": "step",
                    "status": step.status,
                    "title": f"{step.status.title()} {step.label or step.step_key}",
                    "message": step.error_message or _output_summary(step.output),
                    "step_id": step.id,
                    "step_key": step.step_key,
                    "created_at": utc_iso(step.completed_at),
                }
            )
    for event in events:
        items.append(
            {
                "type": "event",
                "status": event.severity,
                "title": event.event_type,
                "message": event.message,
                "step_id": event.step_id,
                "created_at": utc_iso(event.created_at),
            }
        )
    return sorted(items, key=lambda item: item.get("created_at") or "")


def _build_run_health(
    run: WorkflowRun,
    steps: list[WorkflowRunStep],
    events: list[WorkflowEvent],
    findings: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    current = next((step for step in steps if step.step_order == run.current_step_index), None)
    attention = next((step for step in steps if step.status in {"failed", "awaiting_input", "paused", "running"}), None)
    active = attention or current
    last_event = events[-1] if events else None
    status_counts = _count_by([{"status": step.status} for step in steps], "status")
    finding_counts = _count_by(findings, "severity")
    next_action = "Review the run output."
    if run.status == "running" and active:
        next_action = f"Waiting for step {active.step_order + 1}: {active.label or active.step_key}."
    elif run.status == "awaiting_input" and active:
        next_action = f"Input is required for {active.label or active.step_key}."
    elif run.status == "failed" and active:
        next_action = f"Inspect or retry failed step {active.step_order + 1}: {active.label or active.step_key}."
    elif run.status == "completed":
        next_action = "Review findings and artifacts." if findings or artifacts else "No follow-up action detected."
    elif run.status == "paused":
        next_action = run.pause_reason or "Resume or cancel this paused workflow."
    elif run.status == "cancelled":
        next_action = "Run was cancelled."
    return {
        "current_step_id": active.id if active else None,
        "current_step_key": active.step_key if active else None,
        "current_step_label": active.label if active else None,
        "current_step_status": active.status if active else None,
        "next_action": next_action,
        "last_message": run.error_message or (last_event.message if last_event else None) or (active.error_message if active else None),
        "status_counts": status_counts,
        "finding_counts": finding_counts,
        "finding_count": len(findings),
        "artifact_count": len(artifacts),
        "event_count": len(events),
        "step_count": len(steps),
        "last_event_at": utc_iso(last_event.created_at) if last_event else None,
        "heartbeat_at": utc_iso(run.heartbeat_at),
    }


async def _workflow_debug_payload(run: WorkflowRun, session: Session, *, include_temporal: bool = True) -> dict[str, Any]:
    steps = session.exec(
        select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id).order_by(WorkflowRunStep.step_order)
    ).all()
    events = query_workflow_events(session, run_id=run.id, order="asc", limit=200)
    findings: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    external_children: list[dict[str, Any]] = []
    for step in steps:
        findings.extend(_collect_findings_from_output(run, step))
        findings.extend(_collect_test_run_findings(run, step))
        artifacts.extend(_collect_artifacts_from_step(step))
        child = _external_child_for_step(step, session)
        if child:
            external_children.append(child)
            child_artifacts = child.get("artifacts") if isinstance(child.get("artifacts"), list) else []
            for index, artifact in enumerate(child_artifacts):
                if not isinstance(artifact, dict):
                    continue
                artifacts.append(
                    {
                        **artifact,
                        "id": f"{step.id}:child:{index}:{artifact.get('path') or artifact.get('name') or artifact.get('url')}",
                        "source_step_id": step.id,
                        "step_key": step.step_key,
                        "source_kind": child.get("kind") or step.external_kind or step.step_type,
                    }
                )
    artifacts = _dedupe_artifacts(artifacts)

    temporal: dict[str, Any] | None = None
    if include_temporal:
        temporal = {
            "run_id": run.id,
            "temporal_workflow_id": run.temporal_workflow_id,
            "temporal_run_id": run.temporal_run_id,
            "temporal_ui_url": settings.temporal_ui_url,
            "temporal_available": False,
            "temporal_error": None,
            "timeline": [],
            "activities": [],
            "summary": {"total_activities": 0, "failed_activities": 0, "retry_count": 0, "last_failure": None},
        }
        if run.temporal_workflow_id:
            try:
                temporal = {**temporal, **await get_custom_workflow_temporal_diagnostics(run.temporal_workflow_id, run.temporal_run_id)}
            except TemporalUnavailableError as exc:
                temporal["temporal_error"] = str(exc)
            except Exception as exc:
                temporal["temporal_error"] = f"Temporal diagnostics unavailable: {exc}"
        else:
            temporal["temporal_error"] = "No Temporal workflow id recorded for this run."

    return {
        "run": _run_to_dict(run, session, include_steps=True),
        "steps": [_step_to_dict(step) | {"duration_seconds": _step_duration_seconds(step), "summary": _output_summary(step.output)} for step in steps],
        "events": [workflow_event_to_dict(event) for event in events],
        "temporal": temporal,
        "timeline": _build_debug_timeline(run, steps, events),
        "findings": findings,
        "artifacts": artifacts,
        "external_children": external_children,
        "health": _build_run_health(run, steps, events, findings, artifacts),
    }


def _revision_to_dict(revision: WorkflowDefinitionRevision) -> dict[str, Any]:
    return {
        "id": revision.id,
        "definition_id": revision.definition_id,
        "project_id": revision.project_id,
        "version": revision.version,
        "name": revision.name,
        "description": revision.description,
        "steps": revision.steps,
        "change_summary": revision.change_summary,
        "created_by": revision.created_by,
        "created_at": utc_iso(revision.created_at),
    }


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


def _validate_recovery_policy(policy: dict[str, Any], *, label: str = "recovery_policy") -> dict[str, Any]:
    if not policy:
        return {}
    action = str(policy.get("action") or "fail").strip().lower()
    if action not in RECOVERY_ACTIONS:
        raise HTTPException(status_code=400, detail=f"{label}.action must be one of: {', '.join(sorted(RECOVERY_ACTIONS))}")
    try:
        max_attempts = max(1, int(policy.get("max_attempts") or 1))
        retry_backoff_seconds = max(0, int(policy.get("retry_backoff_seconds") or 0))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{label} retry values must be numbers") from exc
    return {
        "action": action,
        "max_attempts": max_attempts,
        "retry_backoff_seconds": retry_backoff_seconds,
    }


def _mark_temporal_start_failed(session: Session, run: WorkflowRun, message: str) -> None:
    refreshed = session.get(WorkflowRun, run.id) or run
    refreshed.status = "failed"
    refreshed.error_message = message
    refreshed.completed_at = datetime.utcnow()
    refreshed.updated_at = datetime.utcnow()
    session.add(refreshed)
    emit_workflow_event(
        session,
        event_type="workflow.temporal_start_failed",
        message=f"Temporal failed to start workflow run {refreshed.id}: {message}",
        severity="error",
        run=refreshed,
        payload={"temporal_error": message},
        notify=True,
    )
    session.commit()


async def _launch_run_durably(run: WorkflowRun, background_tasks: BackgroundTasks | None = None, session: Session | None = None) -> None:
    """Start the required Temporal workflow for a custom workflow run."""
    del background_tasks
    try:
        temporal = await start_custom_workflow_run(run.id)
        if session:
            refreshed = session.get(WorkflowRun, run.id)
            if refreshed:
                refreshed.temporal_workflow_id = temporal.workflow_id
                refreshed.temporal_run_id = temporal.run_id
                refreshed.updated_at = datetime.utcnow()
                session.add(refreshed)
                session.commit()
        return
    except TemporalUnavailableError as exc:
        message = str(exc)
    except Exception as exc:
        message = f"Failed to start Temporal workflow: {exc}"
    if session:
        _mark_temporal_start_failed(session, run, message)
    raise HTTPException(status_code=503, detail=message)


def _validate_cron(cron_expression: str, timezone: str) -> datetime | None:
    try:
        from orchestrator.services.scheduler import get_next_n_run_times

        next_runs = get_next_n_run_times(cron_expression, timezone, count=1)
        return next_runs[0] if next_runs else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _get_revision_or_404(
    session: Session,
    definition: WorkflowDefinition,
    revision_id: str | None,
) -> WorkflowDefinitionRevision:
    if not revision_id:
        return ensure_workflow_revision(session, definition)
    revision = session.get(WorkflowDefinitionRevision, revision_id)
    if not revision or revision.definition_id != definition.id:
        raise HTTPException(status_code=400, detail="Workflow revision not found for this definition")
    return revision


def _schedule_event_payload(schedule: WorkflowSchedule, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schedule_id": schedule.id,
        "schedule_name": schedule.name,
        "definition_id": schedule.definition_id,
        "revision_id": schedule.revision_id,
        "revision_mode": schedule.revision_mode,
        "enabled": schedule.enabled,
        "cron_expression": schedule.cron_expression,
        "timezone": schedule.timezone,
        "start_step_key": schedule.start_step_key,
    }
    if extra:
        payload.update(extra)
    return payload


def _changed_schedule_fields(before: dict[str, Any], schedule: WorkflowSchedule) -> dict[str, dict[str, Any]]:
    after = _schedule_event_payload(schedule)
    keys = ["schedule_name", "revision_id", "revision_mode", "enabled", "cron_expression", "timezone", "start_step_key"]
    return {
        key: {"from": before.get(key), "to": after.get(key)}
        for key in keys
        if before.get(key) != after.get(key)
    }


@router.get("/catalog")
def get_workflow_catalog(
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    sync_builtin_workflow_step_types(session)
    return {"steps": workflow_step_catalog(session, project_id), "templates": WORKFLOW_TEMPLATES}


@router.get("/admin/step-types")
def get_admin_workflow_step_types(
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    if not getattr(user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    sync_builtin_workflow_step_types(session)
    return {"steps": workflow_step_catalog(session, None)}


@router.post("/validate")
def validate_workflow_definition(
    request: WorkflowValidationRequest,
    session: Session = Depends(get_session),
):
    sync_builtin_workflow_step_types(session)
    return validate_workflow_definition_payload(
        name=request.name,
        steps=[step.model_dump() for step in request.steps],
        session=session,
        project_id=request.project_id,
    )


@router.post("/import/validate")
def validate_workflow_import(
    request: WorkflowImportRequest,
    session: Session = Depends(get_session),
):
    workflow = request.workflow or {}
    if workflow.get("schema_version") != "quorvex.workflow.v1":
        return {
            "valid": False,
            "form_errors": [{"code": "schema_version", "message": "Unsupported workflow export schema version."}],
            "step_errors": {},
            "warnings": {},
        }
    sync_builtin_workflow_step_types(session)
    return validate_workflow_definition_payload(
        name=str(workflow.get("name") or ""),
        steps=list(workflow.get("steps") or []),
        session=session,
        project_id=request.project_id,
    )


@router.post("/import")
async def import_workflow_definition(
    request: WorkflowImportRequest,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    workflow = request.workflow or {}
    if workflow.get("schema_version") != "quorvex.workflow.v1":
        raise HTTPException(status_code=400, detail="Unsupported workflow export schema version")
    await _ensure_write_access(request.project_id, user, session)
    name = str(workflow.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Workflow name is required")
    try:
        sync_builtin_workflow_step_types(session)
        steps = validate_workflow_steps(list(workflow.get("steps") or []), session=session, project_id=request.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing = session.exec(
        select(WorkflowDefinition)
        .where(WorkflowDefinition.project_id == request.project_id)
        .where(WorkflowDefinition.status == "active")
        .where(WorkflowDefinition.name == name)
    ).first()
    if existing:
        name = f"{name} Copy"
    definition = WorkflowDefinition(
        project_id=request.project_id,
        name=name,
        description=str(workflow.get("description") or "").strip(),
        created_by=getattr(user, "id", None),
    )
    definition.steps = steps
    session.add(definition)
    session.flush()
    create_workflow_revision(
        session,
        definition,
        change_summary="Imported workflow",
        created_by=getattr(user, "id", None),
        version=1,
    )
    emit_workflow_event(
        session,
        event_type="workflow.definition_created",
        message=f"Workflow definition {definition.name} was imported.",
        definition_id=definition.id,
        payload={"definition_name": definition.name, "step_count": len(steps), "source": "import"},
        notify=False,
    )
    session.commit()
    session.refresh(definition)
    return _definition_to_dict(definition)


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


@router.get("/analytics")
def get_workflow_analytics(
    project_id: str | None = Query(default=None),
    definition_id: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_session),
):
    runs_stmt = select(WorkflowRun).order_by(col(WorkflowRun.created_at).desc()).limit(limit)
    steps_stmt = select(WorkflowRunStep)
    if project_id:
        runs_stmt = runs_stmt.where(WorkflowRun.project_id == project_id)
        steps_stmt = steps_stmt.where(WorkflowRunStep.definition_id.in_(
            [d.id for d in session.exec(select(WorkflowDefinition).where(WorkflowDefinition.project_id == project_id)).all()]
        ))
    if definition_id:
        runs_stmt = runs_stmt.where(WorkflowRun.definition_id == definition_id)
        steps_stmt = steps_stmt.where(WorkflowRunStep.definition_id == definition_id)
    runs = session.exec(runs_stmt).all()
    run_ids = [run.id for run in runs]
    steps = session.exec(steps_stmt.where(WorkflowRunStep.run_id.in_(run_ids))).all() if run_ids else []
    durations = [value for value in (workflow_duration_seconds(run) for run in runs) if value is not None]
    terminal = [run for run in runs if run.status in TERMINAL_STATUSES]
    failed = [run for run in runs if run.status == "failed"]
    completed = [run for run in runs if run.status == "completed"]
    by_trigger: dict[str, int] = {}
    for run in runs:
        by_trigger[run.trigger_type or "manual"] = by_trigger.get(run.trigger_type or "manual", 0) + 1
    step_failures: dict[str, int] = {}
    step_durations: dict[str, list[float]] = {}
    for step in steps:
        if step.status == "failed":
            step_failures[step.step_type] = step_failures.get(step.step_type, 0) + 1
        if step.started_at and step.completed_at:
            step_durations.setdefault(step.step_type, []).append(max(0, (step.completed_at - step.started_at).total_seconds()))
    return {
        "runs": len(runs),
        "active_runs": len([run for run in runs if run.status in ACTIVE_STATUSES]),
        "completed_runs": len(completed),
        "failed_runs": len(failed),
        "success_rate": round((len(completed) / len(terminal)) * 100, 1) if terminal else 0.0,
        "failure_rate": round((len(failed) / len(terminal)) * 100, 1) if terminal else 0.0,
        "duration_seconds": {
            "median": percentile(durations, 0.5),
            "p95": percentile(durations, 0.95),
        },
        "trigger_breakdown": by_trigger,
        "flakiest_steps": sorted(
            [{"step_type": step_type, "failures": count} for step_type, count in step_failures.items()],
            key=lambda item: item["failures"],
            reverse=True,
        )[:10],
        "slowest_steps": sorted(
            [
                {"step_type": step_type, "p95_duration_seconds": percentile(values, 0.95)}
                for step_type, values in step_durations.items()
            ],
            key=lambda item: item["p95_duration_seconds"] or 0,
            reverse=True,
        )[:10],
        "recent_failures": [_run_to_dict(run, session, include_steps=False) for run in failed[:10]],
    }


@router.get("/events")
def list_workflow_events(
    project_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    definition_id: str | None = Query(default=None),
    schedule_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    q: str | None = Query(default=None),
    entity_scope: str = Query(default="all", pattern="^(all|run|schedule|definition)$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    events = query_workflow_events(
        session,
        project_id=project_id,
        run_id=run_id,
        definition_id=definition_id,
        schedule_id=schedule_id,
        event_type=event_type,
        severity=severity,
        q=q,
        entity_scope=entity_scope,
        order=order,
        limit=limit,
    )
    return [workflow_event_to_dict(event) for event in events]


@router.get("/notifications")
def list_workflow_notifications(
    project_id: str | None = Query(default=None),
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    stmt = select(WorkflowNotification).order_by(col(WorkflowNotification.created_at).desc()).limit(limit)
    if project_id:
        stmt = stmt.where(WorkflowNotification.project_id == project_id)
    if unread_only:
        stmt = stmt.where(WorkflowNotification.read_at == None)
    return [workflow_notification_to_dict(notification) for notification in session.exec(stmt).all()]


@router.post("/notifications/{notification_id}/read")
def mark_workflow_notification_read(notification_id: str, session: Session = Depends(get_session)):
    notification = session.get(WorkflowNotification, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read_at = datetime.utcnow()
    session.add(notification)
    session.commit()
    return workflow_notification_to_dict(notification)


@router.get("/temporal/health")
async def get_workflow_temporal_health():
    return await check_custom_workflow_temporal_health()


@router.get("/schedules")
def list_workflow_schedules(
    project_id: str | None = Query(default=None),
    definition_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    stmt = select(WorkflowSchedule).order_by(col(WorkflowSchedule.created_at).desc())
    if project_id:
        stmt = stmt.where(WorkflowSchedule.project_id == project_id)
    if definition_id:
        stmt = stmt.where(WorkflowSchedule.definition_id == definition_id)
    return [workflow_schedule_to_dict(schedule) for schedule in session.exec(stmt).all()]


@router.post("/schedules")
async def create_workflow_schedule(
    request: WorkflowScheduleRequest,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    definition = _get_definition_or_404(request.definition_id, None, session)
    await _ensure_write_access(definition.project_id, user, session)
    next_run = _validate_cron(request.cron_expression, request.timezone)
    if request.start_step_key and not any(step.get("key") == request.start_step_key for step in definition.steps):
        raise HTTPException(status_code=400, detail=f"Workflow step not found: {request.start_step_key}")
    revision_mode = request.revision_mode
    revision = _get_revision_or_404(session, definition, request.revision_id)
    schedule = WorkflowSchedule(
        project_id=definition.project_id,
        definition_id=definition.id,
        revision_id=revision.id if revision_mode == "pinned" else None,
        revision_mode=revision_mode,
        name=request.name.strip(),
        description=request.description.strip(),
        cron_expression=request.cron_expression,
        timezone=request.timezone,
        start_step_key=request.start_step_key,
        enabled=request.enabled,
        next_run_at=next_run,
        notify_on_completion=request.notify_on_completion,
        notify_on_failure=request.notify_on_failure,
        notify_on_review_needed=request.notify_on_review_needed,
        created_by=getattr(user, "id", None),
    )
    schedule.inputs = request.inputs
    session.add(schedule)
    session.flush()
    emit_workflow_event(
        session,
        event_type="workflow.schedule_created",
        message=f"Workflow schedule {schedule.name} created.",
        schedule=schedule,
        payload=_schedule_event_payload(schedule, {"definition_version": revision.version if revision_mode == "pinned" else None}),
        notify=False,
    )
    session.commit()
    session.refresh(schedule)
    try:
        from orchestrator.services.scheduler import add_workflow_schedule_job

        if schedule.enabled:
            add_workflow_schedule_job(schedule.id, schedule.cron_expression, schedule.timezone)
    except Exception as exc:
        schedule.status = "error"
        schedule.last_error = str(exc)
        session.add(schedule)
        session.commit()
    return workflow_schedule_to_dict(schedule)


@router.put("/schedules/{schedule_id}")
async def update_workflow_schedule(
    schedule_id: str,
    request: WorkflowScheduleUpdateRequest,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    schedule = session.get(WorkflowSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Workflow schedule not found")
    await _ensure_write_access(schedule.project_id, user, session)
    definition = _get_definition_or_404(schedule.definition_id, schedule.project_id, session)
    before = _schedule_event_payload(schedule)
    cron = request.cron_expression or schedule.cron_expression
    timezone = request.timezone or schedule.timezone
    schedule.next_run_at = _validate_cron(cron, timezone)
    if request.start_step_key and not any(step.get("key") == request.start_step_key for step in definition.steps):
        raise HTTPException(status_code=400, detail=f"Workflow step not found: {request.start_step_key}")
    next_revision_mode = request.revision_mode or schedule.revision_mode or "pinned"
    if next_revision_mode == "latest":
        schedule.revision_id = None
    elif request.revision_id is not None:
        schedule.revision_id = _get_revision_or_404(session, definition, request.revision_id).id
    elif not schedule.revision_id:
        schedule.revision_id = ensure_workflow_revision(session, definition, created_by=getattr(user, "id", None)).id
    schedule.revision_mode = next_revision_mode
    for field in ("name", "description", "cron_expression", "timezone", "start_step_key"):
        value = getattr(request, field)
        if value is not None:
            setattr(schedule, field, value)
    for field in ("enabled", "notify_on_completion", "notify_on_failure", "notify_on_review_needed"):
        value = getattr(request, field)
        if value is not None:
            setattr(schedule, field, value)
    if request.inputs is not None:
        schedule.inputs = request.inputs
    schedule.updated_at = datetime.utcnow()
    schedule.status = "active" if schedule.enabled else "paused"
    schedule.last_error = None
    session.add(schedule)
    changed_fields = _changed_schedule_fields(before, schedule)
    if changed_fields:
        emit_workflow_event(
            session,
            event_type="workflow.schedule_updated",
            message=f"Workflow schedule {schedule.name} updated.",
            schedule=schedule,
            payload=_schedule_event_payload(schedule, {"changed_fields": changed_fields}),
            notify=False,
        )
    if "enabled" in changed_fields:
        event_type = "workflow.schedule_resumed" if schedule.enabled else "workflow.schedule_paused"
        emit_workflow_event(
            session,
            event_type=event_type,
            message=f"Workflow schedule {schedule.name} {'resumed' if schedule.enabled else 'paused'}.",
            schedule=schedule,
            payload=_schedule_event_payload(schedule),
            notify=False,
        )
    session.commit()
    try:
        from orchestrator.services.scheduler import add_workflow_schedule_job, pause_schedule_job

        if schedule.enabled:
            add_workflow_schedule_job(schedule.id, schedule.cron_expression, schedule.timezone)
        else:
            pause_schedule_job(schedule.id)
    except Exception as exc:
        schedule.status = "error"
        schedule.last_error = str(exc)
        session.add(schedule)
        session.commit()
    return workflow_schedule_to_dict(schedule)


@router.delete("/schedules/{schedule_id}")
async def delete_workflow_schedule(
    schedule_id: str,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    schedule = session.get(WorkflowSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Workflow schedule not found")
    await _ensure_write_access(schedule.project_id, user, session)
    try:
        from orchestrator.services.scheduler import remove_schedule_job

        remove_schedule_job(schedule.id)
    except Exception:
        pass
    emit_workflow_event(
        session,
        event_type="workflow.schedule_deleted",
        message=f"Workflow schedule {schedule.name} deleted.",
        schedule=schedule,
        payload=_schedule_event_payload(schedule),
        notify=False,
    )
    session.flush()
    executions = session.exec(select(WorkflowScheduleExecution).where(WorkflowScheduleExecution.schedule_id == schedule.id)).all()
    for execution in executions:
        session.delete(execution)
    events = session.exec(select(WorkflowEvent).where(WorkflowEvent.schedule_id == schedule.id)).all()
    for event in events:
        event.schedule_id = None
        session.add(event)
    session.flush()
    session.delete(schedule)
    session.commit()
    return {"status": "deleted", "id": schedule_id}


@router.post("/schedules/{schedule_id}/run-now")
async def run_workflow_schedule_now(
    schedule_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    schedule = session.get(WorkflowSchedule, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Workflow schedule not found")
    await _ensure_write_access(schedule.project_id, user, session)
    execution = WorkflowScheduleExecution(
        schedule_id=schedule.id,
        status="running",
        trigger_type="manual",
        started_at=datetime.utcnow(),
    )
    session.add(execution)
    session.flush()
    emit_workflow_event(
        session,
        event_type="workflow.schedule_triggered",
        message=f"Workflow schedule {schedule.name} triggered manually.",
        schedule=schedule,
        payload=_schedule_event_payload(schedule, {"execution_id": execution.id, "trigger_type": "manual"}),
        notify=False,
    )
    session.commit()
    session.refresh(execution)
    try:
        from orchestrator.services.scheduler import execute_workflow_schedule

        background_tasks.add_task(execute_workflow_schedule, schedule.id, execution.id, "manual")
    except Exception as exc:
        execution.status = "failed"
        execution.error_message = str(exc)
        execution.completed_at = datetime.utcnow()
        session.add(execution)
        session.commit()
    return workflow_schedule_execution_to_dict(execution)


@router.get("/schedules/{schedule_id}/executions")
def list_workflow_schedule_executions(
    schedule_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
):
    if not session.get(WorkflowSchedule, schedule_id):
        raise HTTPException(status_code=404, detail="Workflow schedule not found")
    executions = session.exec(
        select(WorkflowScheduleExecution)
        .where(WorkflowScheduleExecution.schedule_id == schedule_id)
        .order_by(col(WorkflowScheduleExecution.created_at).desc())
        .limit(limit)
    ).all()
    return [workflow_schedule_execution_to_dict(execution) for execution in executions]


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
        sync_builtin_workflow_step_types(session)
        steps = validate_workflow_steps([step.model_dump() for step in request.steps], session=session, project_id=request.project_id)
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
    session.flush()
    create_workflow_revision(
        session,
        definition,
        change_summary="Initial workflow revision",
        created_by=getattr(user, "id", None),
        version=1,
    )
    emit_workflow_event(
        session,
        event_type="workflow.definition_created",
        message=f"Workflow definition {definition.name} was created.",
        definition_id=definition.id,
        payload={"definition_name": definition.name, "step_count": len(steps)},
        notify=False,
    )
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


@router.get("/definitions/{definition_id}/export")
def export_workflow_definition(
    definition_id: str,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    return _definition_export(definition)


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
    session.flush()
    create_workflow_revision(
        session,
        clone,
        change_summary=f"Duplicated from {definition.name}",
        created_by=getattr(user, "id", None),
        version=1,
    )
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


@router.get("/definitions/{definition_id}/revisions")
def list_definition_revisions(
    definition_id: str,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    ensure_workflow_revision(session, definition)
    session.commit()
    revisions = session.exec(
        select(WorkflowDefinitionRevision)
        .where(WorkflowDefinitionRevision.definition_id == definition.id)
        .order_by(col(WorkflowDefinitionRevision.version).desc())
    ).all()
    return [_revision_to_dict(revision) for revision in revisions]


@router.get("/definitions/{definition_id}/revisions/{version}")
def get_definition_revision(
    definition_id: str,
    version: int,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    revision = session.exec(
        select(WorkflowDefinitionRevision)
        .where(WorkflowDefinitionRevision.definition_id == definition.id)
        .where(WorkflowDefinitionRevision.version == version)
    ).first()
    if not revision:
        raise HTTPException(status_code=404, detail="Workflow revision not found")
    return _revision_to_dict(revision)


@router.get("/definitions/{definition_id}/revisions/{version}/rollback-preview")
def preview_definition_revision_rollback(
    definition_id: str,
    version: int,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    revision = session.exec(
        select(WorkflowDefinitionRevision)
        .where(WorkflowDefinitionRevision.definition_id == definition.id)
        .where(WorkflowDefinitionRevision.version == version)
    ).first()
    if not revision:
        raise HTTPException(status_code=404, detail="Workflow revision not found")
    diff = workflow_revision_diff(definition.steps, revision.steps)
    emit_workflow_event(
        session,
        event_type="workflow.definition_rollback_previewed",
        message=f"Workflow rollback preview generated for {definition.name} v{version}.",
        definition_id=definition.id,
        payload={
            "current_version": definition.version,
            "target_version": revision.version,
            "target_revision_id": revision.id,
            "summary": diff["summary"],
        },
        notify=False,
    )
    session.commit()
    return {
        "definition_id": definition.id,
        "current_version": definition.version,
        "target_version": revision.version,
        "target_revision_id": revision.id,
        "diff": diff,
        "current_steps": definition.steps,
        "target_steps": revision.steps,
    }


@router.post("/definitions/{definition_id}/revisions/{version}/rollback")
async def rollback_definition_revision(
    definition_id: str,
    version: int,
    request: WorkflowRollbackRequest,
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user=Depends(get_current_user_optional),
):
    definition = _get_definition_or_404(definition_id, project_id, session)
    await _ensure_write_access(definition.project_id, user, session)
    revision = session.exec(
        select(WorkflowDefinitionRevision)
        .where(WorkflowDefinitionRevision.definition_id == definition.id)
        .where(WorkflowDefinitionRevision.version == version)
    ).first()
    if not revision:
        raise HTTPException(status_code=404, detail="Workflow revision not found")
    source_version = definition.version
    diff = workflow_revision_diff(definition.steps, revision.steps)
    restored = restore_workflow_revision(session, definition, revision, created_by=getattr(user, "id", None))
    if request.change_summary:
        restored.change_summary = request.change_summary
        session.add(restored)
    emit_workflow_event(
        session,
        event_type="workflow.definition_rolled_back",
        message=f"Workflow {definition.name} rolled back to version {version}.",
        definition_id=definition.id,
        payload={
            "source_version": source_version,
            "target_version": revision.version,
            "target_revision_id": revision.id,
            "restored_revision_id": restored.id,
            "diff_summary": diff["summary"],
        },
        notify=False,
    )
    session.commit()
    session.refresh(restored)
    return {"definition": _definition_to_dict(definition), "revision": _revision_to_dict(restored)}


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
    previous_steps = definition.steps

    if request.name is not None:
        if not request.name.strip():
            raise HTTPException(status_code=400, detail="Workflow name is required")
        definition.name = request.name.strip()
    if request.description is not None:
        definition.description = request.description.strip()
    if request.steps is not None:
        try:
            sync_builtin_workflow_step_types(session)
            next_steps = validate_workflow_steps(
                [step.model_dump() for step in request.steps],
                session=session,
                project_id=definition.project_id,
            )
            definition.steps = next_steps
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if request.status is not None:
        if request.status not in {"active", "archived"}:
            raise HTTPException(status_code=400, detail="Invalid workflow status")
        definition.status = request.status
    definition.updated_at = datetime.utcnow()
    session.add(definition)
    if request.steps is not None and json_changed(previous_steps, definition.steps):
        create_workflow_revision(
            session,
            definition,
            change_summary="Workflow steps updated",
            created_by=getattr(user, "id", None),
        )
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

    revision = ensure_workflow_revision(session, definition, created_by=getattr(user, "id", None))
    recovery_policy = _validate_recovery_policy(request.recovery_policy, label="run recovery_policy")
    run = WorkflowRun(
        definition_id=definition.id,
        workflow_id=definition.id,
        revision_id=revision.id,
        definition_version=revision.version,
        project_id=definition.project_id,
        status="queued",
        triggered_by=request.triggered_by or getattr(user, "id", None) or "ui",
        trigger_type=request.trigger_type or ("assistant" if request.triggered_by == "chat" else "manual"),
        trigger_id=request.trigger_id,
    )
    run.inputs = request.inputs
    run.recovery_policy = recovery_policy
    session.add(run)
    session.commit()
    session.refresh(run)
    try:
        create_workflow_run_steps(session, definition, run, start_step_key=request.start_step_key, steps_override=revision.steps)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    emit_workflow_event(
        session,
        event_type="workflow.run_created",
        message=f"Workflow run {run.id} was created.",
        run=run,
        payload={
            "definition_id": definition.id,
            "definition_name": definition.name,
            "revision_id": revision.id,
            "definition_version": revision.version,
            "trigger_type": run.trigger_type,
            "start_step_key": request.start_step_key,
        },
        notify=False,
    )
    if request.start_step_key:
        emit_workflow_event(
            session,
            event_type="workflow.run_started_from_step",
            message=f"Workflow run {run.id} was started from step {request.start_step_key}.",
            run=run,
            payload={
                "definition_id": definition.id,
                "definition_name": definition.name,
                "revision_id": revision.id,
                "definition_version": revision.version,
                "trigger_type": run.trigger_type,
                "start_step_key": request.start_step_key,
            },
            notify=False,
        )
    session.commit()
    await _launch_run_durably(run, background_tasks, session)
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


@router.get("/runs/{run_id}/diagnostics")
async def get_workflow_run_diagnostics(run_id: str, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    payload: dict[str, Any] = {
        "run_id": run.id,
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
        "temporal_ui_url": settings.temporal_ui_url,
        "temporal_available": False,
        "temporal_error": None,
        "workflow_status": None,
        "timeline": [],
        "activities": [],
        "summary": {
            "total_activities": 0,
            "failed_activities": 0,
            "retry_count": 0,
            "last_failure": None,
        },
    }
    if not run.temporal_workflow_id:
        payload["temporal_error"] = "No Temporal workflow id recorded for this run."
        return payload

    try:
        temporal = await get_custom_workflow_temporal_diagnostics(run.temporal_workflow_id, run.temporal_run_id)
    except TemporalUnavailableError as exc:
        payload["temporal_error"] = str(exc)
        return payload
    except Exception as exc:
        payload["temporal_error"] = f"Temporal diagnostics unavailable: {exc}"
        return payload

    return {**payload, **temporal}


@router.get("/runs/{run_id}/debug")
async def get_workflow_run_debug(
    run_id: str,
    include_temporal: bool = Query(default=True),
    session: Session = Depends(get_session),
):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return await _workflow_debug_payload(run, session, include_temporal=include_temporal)


@router.get("/runs/{run_id}/steps")
def list_workflow_run_steps(run_id: str, session: Session = Depends(get_session)):
    if not session.get(WorkflowRun, run_id):
        raise HTTPException(status_code=404, detail="Workflow run not found")
    steps = session.exec(
        select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id).order_by(WorkflowRunStep.step_order)
    ).all()
    return [_step_to_dict(step) for step in steps]


@router.post("/runs/{run_id}/steps/{step_id}/retry")
async def retry_workflow_run_step(run_id: str, step_id: int, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
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
    emit_workflow_event(
        session,
        event_type="workflow.step_retry_queued",
        message=f"Workflow step {step.step_key} was queued for retry.",
        severity="warning",
        run=run,
        step_id=step.id,
        payload={
            "step_key": step.step_key,
            "attempt_count": step.attempt_count,
            "max_attempts": step.max_attempts,
            "recovery_action": step.recovery_action,
        },
        notify=False,
    )
    session.commit()
    await _launch_run_durably(run, background_tasks, session)
    return {"run_id": run.id, "step_id": step.id, "status": "queued"}


@router.post("/runs/{run_id}/pause")
async def pause_workflow_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Cannot pause a terminal workflow run")
    run.status = "paused"
    run.pause_reason = "manual_pause"
    run.updated_at = datetime.utcnow()
    session.add(run)
    steps = session.exec(
        select(WorkflowRunStep)
        .where(WorkflowRunStep.run_id == run_id)
        .where(WorkflowRunStep.status.in_(["running"]))
    ).all()
    for step in steps:
        step.status = "paused"
        step.updated_at = datetime.utcnow()
        session.add(step)
    emit_workflow_event(
        session,
        event_type="workflow.paused",
        message=f"Workflow run {run.id} was paused.",
        severity="warning",
        run=run,
        payload={"reason": "manual_pause"},
        notify=False,
    )
    session.commit()
    if run.temporal_workflow_id:
        try:
            await signal_custom_workflow_run(run.temporal_workflow_id, "pause", "manual_pause")
        except Exception:
            pass
    return {"run_id": run.id, "status": run.status}


@router.post("/runs/{run_id}/resume")
async def resume_workflow_run(run_id: str, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Cannot resume a terminal workflow run")
    previous_status = run.status
    if run.status == "awaiting_input":
        steps = session.exec(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id)).all()
        for step in steps:
            if step.status == "awaiting_input":
                step.status = "completed"
                step.completed_at = datetime.utcnow()
                step.updated_at = datetime.utcnow()
                session.add(step)
            elif step.status == "paused":
                step.status = "pending"
                step.started_at = None
                step.updated_at = datetime.utcnow()
                session.add(step)
    elif run.status == "paused":
        steps = session.exec(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id)).all()
        for step in steps:
            if step.status == "paused":
                step.status = "pending"
                step.started_at = None
                step.updated_at = datetime.utcnow()
                session.add(step)
    run.status = "queued"
    run.pause_reason = None
    run.updated_at = datetime.utcnow()
    session.add(run)
    emit_workflow_event(
        session,
        event_type="workflow.resumed",
        message=f"Workflow run {run.id} was resumed.",
        run=run,
        payload={"previous_status": previous_status},
        notify=False,
    )
    session.commit()
    if run.temporal_workflow_id:
        try:
            await signal_custom_workflow_run(run.temporal_workflow_id, "resume")
            return {"run_id": run.id, "status": "running"}
        except Exception:
            pass
    await _launch_run_durably(run, background_tasks, session)
    return {"run_id": run.id, "status": "running"}


@router.post("/runs/{run_id}/cancel")
async def cancel_workflow_run(run_id: str, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Workflow run is already terminal")
    child_cancel = await cancel_workflow_child_agent_runs(run, session, reason="workflow_cancelled")
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
    emit_workflow_event(
        session,
        event_type="workflow.cancelled",
        message=f"Workflow run {run.id} was cancelled.",
        severity="warning",
        run=run,
        payload=child_cancel,
    )
    session.commit()
    if run.temporal_workflow_id:
        try:
            await signal_custom_workflow_run(run.temporal_workflow_id, "cancel", "manual_cancel")
        except Exception:
            pass
    return {"run_id": run.id, "status": run.status}


@router.post("/runs/{run_id}/steps/{step_id}/skip")
async def skip_workflow_run_step(run_id: str, step_id: int, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    run = session.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    step = session.get(WorkflowRunStep, step_id)
    if not step or step.run_id != run_id:
        raise HTTPException(status_code=404, detail="Workflow run step not found")
    if step.status not in {"failed", "pending", "running", "awaiting_input"}:
        raise HTTPException(status_code=409, detail=f"Cannot skip a {step.status} step")
    step.status = "skipped"
    step.skipped_reason = "manual_skip"
    step.output = {"skipped": True, "reason": "manual_skip"}
    step.completed_at = datetime.utcnow()
    step.updated_at = datetime.utcnow()
    run.context = {**run.context, "steps": {**(run.context.get("steps") or {}), step.step_key: step.output or {}}}
    if run.status in {"failed", "awaiting_input", "paused"}:
        run.status = "queued"
        run.completed_at = None
        run.error_message = None
    run.updated_at = datetime.utcnow()
    session.add(step)
    session.add(run)
    emit_workflow_event(
        session,
        event_type="workflow.step_skipped",
        message=f"Workflow step {step.step_key} was skipped.",
        severity="warning",
        run=run,
        step_id=step.id,
        notify=True,
    )
    session.commit()
    await _launch_run_durably(run, background_tasks, session)
    return {"run_id": run.id, "step_id": step.id, "status": "queued"}
