import asyncio
import base64
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, func, or_
from sqlmodel import Session, select
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from utils.playwright_mcp import browser_runtime_status

from . import agent_run_control, agent_run_runtime, exploration, run_files, spec_files
from .db import engine, get_session
from .models_db import AgentRun, AgentRunEvent

router = APIRouter(tags=["agent-run-observability"])
logger = logging.getLogger(__name__)

AGENT_PARTIAL_STATUS = agent_run_control.AGENT_PARTIAL_STATUS
AGENT_TERMINAL_STATUSES = agent_run_control.AGENT_TERMINAL_STATUSES
AGENT_ACTIVE_STATUSES = agent_run_control.AGENT_ACTIVE_STATUSES
RUNS_DIR = spec_files.RUNS_DIR


def _agent_run_test_run_id(run: AgentRun) -> str | None:
    if run.agent_type != "spec_generation":
        return None
    config = run.config or {}
    progress = run.progress or {}
    if config.get("source") != "test_run" and progress.get("source") != "test_run":
        return None
    for key in ("test_run_id", "source_run_id", "run_id"):
        value = config.get(key) or progress.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return run.id


def _fallback_session_activity(run: AgentRun) -> dict[str, Any] | None:
    test_run_id = _agent_run_test_run_id(run)
    if not test_run_id:
        return None
    run_dir = RUNS_DIR / test_run_id
    if not run_dir.exists() and test_run_id != run.id:
        run_dir = RUNS_DIR / run.id
    if not run_dir.exists():
        return None
    try:
        activity = run_files._extract_agent_session_activity(run_dir)
    except Exception as exc:
        logger.debug("Failed to recover session activity for agent run %s: %s", run.id, exc)
        return None
    if not isinstance(activity, dict):
        return None
    return {**activity, "test_run_id": test_run_id}


def _synthetic_created_at(run: AgentRun) -> str:
    value = run.updated_at or run.completed_at or run.started_at or run.created_at
    return value.isoformat()


def _tool_name_from_row(row: str) -> str | None:
    text = str(row or "").strip()
    if not text:
        return None
    if text.startswith("CALL "):
        text = text[5:]
        return text.split(" input=", 1)[0].strip() or None
    if text.startswith(("OK ", "ERROR ")):
        text = text.split(" ", 1)[1]
        return text.split(" -> ", 1)[0].strip() or None
    return None


def _is_browser_tool(tool_name: str | None) -> bool:
    value = str(tool_name or "")
    return "__browser_" in value or value.startswith("mcp__playwright")


def _synthetic_agent_notes(run: AgentRun, after_sequence: int = 0, limit: int = 100) -> list[dict[str, Any]]:
    activity = _fallback_session_activity(run)
    if not isinstance(activity, dict):
        return []
    notes = activity.get("notes") if isinstance(activity, dict) else []
    if not isinstance(notes, list):
        return []
    source = str(activity.get("source") or "session_jsonl")
    created_at = _synthetic_created_at(run)
    rows: list[dict[str, Any]] = []
    for index, note in enumerate(notes, start=1):
        sequence = index
        if sequence <= after_sequence:
            continue
        body = str(note or "").strip()
        if not body:
            continue
        title = body.splitlines()[0].strip()[:120] or "Recovered agent note"
        rows.append(
            {
                "id": f"synthetic-note-{run.id}-{sequence}",
                "project_id": run.project_id,
                "run_id": run.id,
                "agent_task_id": run.agent_task_id,
                "sequence": sequence,
                "note_type": "observation",
                "level": "info",
                "title": title,
                "body": body,
                "source": "session_jsonl",
                "tags": ["recovered"],
                "confidence": None,
                "url": None,
                "tool_name": None,
                "artifact_path": source,
                "actionable": False,
                "related_event_sequence": None,
                "related_trace_span_id": None,
                "payload": {
                    "source": "session_jsonl",
                    "artifact_source": source,
                    "test_run_id": activity.get("test_run_id"),
                    "synthetic": True,
                },
                "created_at": created_at,
                "synthetic": True,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _synthetic_agent_events(
    run: AgentRun,
    *,
    after_sequence: int = 0,
    event_type: str | None = None,
    level: str | None = None,
    limit: int = 200,
    sequence_offset: int = 0,
) -> list[dict[str, Any]]:
    activity = _fallback_session_activity(run)
    if not isinstance(activity, dict):
        return []
    tool_rows = activity.get("tool_rows") if isinstance(activity, dict) else []
    if not isinstance(tool_rows, list):
        return []
    source = str(activity.get("source") or "session_jsonl")
    created_at = _synthetic_created_at(run)
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(tool_rows, start=1):
        sequence = sequence_offset + index
        if sequence <= after_sequence:
            continue
        message = str(row or "").strip()
        if not message:
            continue
        tool_name = _tool_name_from_row(message)
        recovered_type = "browser_action" if _is_browser_tool(tool_name) else "tool_call"
        recovered_level = "error" if message.startswith("ERROR ") else "info"
        if event_type and recovered_type != event_type:
            continue
        if level and recovered_level != level:
            continue
        rows.append(
            {
                "id": f"synthetic-event-{run.id}-{sequence}",
                "project_id": run.project_id,
                "run_id": run.id,
                "agent_task_id": run.agent_task_id,
                "temporal_workflow_id": run.temporal_workflow_id,
                "temporal_run_id": run.temporal_run_id,
                "sequence": sequence,
                "event_type": recovered_type,
                "level": recovered_level,
                "message": message,
                "payload": {
                    "source": "session_jsonl",
                    "artifact_source": source,
                    "test_run_id": activity.get("test_run_id"),
                    "tool_name": tool_name,
                    "synthetic": True,
                },
                "idempotency_key": None,
                "created_at": created_at,
                "synthetic": True,
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _session_activity_progress(run: AgentRun) -> dict[str, Any]:
    activity = _fallback_session_activity(run)
    progress = activity.get("progress") if isinstance(activity, dict) else None
    if not isinstance(progress, dict):
        return {}
    tool_rows = activity.get("tool_rows") if isinstance(activity.get("tool_rows"), list) else []
    recent_tools: list[dict[str, Any]] = []
    for index, row in enumerate(tool_rows[-8:], start=max(1, len(tool_rows) - 7)):
        tool_name = _tool_name_from_row(str(row))
        recent_tools.append(
            {
                "sequence": index,
                "tool_name": tool_name,
                "label": _short_tool_name(tool_name or str(row)),
                "message": str(row),
                "source": "session_jsonl",
                "synthetic": True,
            }
        )
    return {
        **progress,
        "source": "session_jsonl",
        "artifact_source": activity.get("source"),
        "test_run_id": activity.get("test_run_id"),
        "recent_tools": recent_tools,
        "synthetic": True,
    }


def _collect_agent_run_artifacts(run_id: str) -> list[dict[str, Any]]:
    """Return browser recording/screenshot artifacts for an agent run."""
    try:
        return jsonable_encoder(exploration._collect_exploration_artifacts(run_id))
    except Exception as exc:
        logger.debug("Failed to collect artifacts for agent run %s: %s", run_id, exc)
        return []


def _read_run_text_artifact(run_id: str, name: str, max_chars: int | None = None) -> str:
    path = RUNS_DIR / run_id / name
    if not path.exists() or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.debug("Failed to read %s for agent run %s: %s", name, run_id, exc)
        return ""
    return text if max_chars is None else text[:max_chars]


def _read_run_json_artifact(run_id: str, name: str) -> Any:
    text = _read_run_text_artifact(run_id, name)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception as exc:
        logger.debug("Failed to parse %s for agent run %s: %s", name, run_id, exc)
        return None


def _run_artifact_counts(run_id: str, artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    artifacts = list(artifacts if artifacts is not None else _collect_agent_run_artifacts(run_id))
    run_dir = RUNS_DIR / run_id
    raw_output = _read_run_text_artifact(run_id, "raw_output.txt")
    tool_calls = _read_run_json_artifact(run_id, "tool_calls.json")
    return {
        "artifact_count": len(artifacts),
        "screenshot_count": len([item for item in artifacts if str(item.get("type") or "") == "image"]),
        "log_count": len([item for item in artifacts if str(item.get("type") or "") == "log"]),
        "raw_output_chars": len(raw_output),
        "tool_call_count": len(tool_calls) if isinstance(tool_calls, list) else 0,
        "storage_state_reused": (run_dir / "browser-auth-storage-state.json").exists(),
    }


def _jsonl_latest_url(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None
    for line in reversed(lines[-500:]):
        try:
            event = json.loads(line)
        except Exception:
            match = re.search(r"https?://[^\s\"'<>),]+", line)
            if match:
                return match.group(0)
            continue
        if isinstance(event, dict):
            for key in ("url", "last_url", "target"):
                value = event.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return value
    return None


def _latest_observed_url_for_run(run: AgentRun) -> str | None:
    progress = run.progress or {}
    for key in ("last_observed_url", "current_url", "last_url", "url"):
        value = progress.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value

    run_dir = RUNS_DIR / run.id
    candidates = [
        run_dir / "exploration_events.jsonl",
        run_dir / "browser-memory-observations.jsonl",
        run_dir / "agent_summary.json",
        run_dir / "tool_calls.json",
        run_dir / "raw_output.txt",
    ]
    existing = [path for path in candidates if path.exists()]
    for path in sorted(existing, key=lambda item: item.stat().st_mtime, reverse=True):
        if path.suffix == ".jsonl":
            url = _jsonl_latest_url(path)
            if url:
                return url
        else:
            text = _read_run_text_artifact(run.id, path.name, max_chars=250_000)
            matches = re.findall(r"https?://[^\s\"'<>),]+", text)
            if matches:
                return matches[-1]
    value = (run.config or {}).get("url")
    return value if isinstance(value, str) and value.startswith(("http://", "https://")) else None


def _filter_agent_run_project(run: AgentRun, project_id: str | None) -> None:
    if not project_id:
        return
    if run.project_id:
        if project_id == "default":
            if run.project_id not in (None, "default"):
                raise HTTPException(status_code=404, detail="Run not found")
        elif run.project_id != project_id:
            raise HTTPException(status_code=404, detail="Run not found")


def _coerce_progress_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _short_tool_name(tool_name: str | None) -> str:
    if not tool_name:
        return ""
    return str(tool_name).rsplit("__", 1)[-1] if "__" in str(tool_name) else str(tool_name)


def _normalize_agent_run_progress(progress: dict[str, Any] | None) -> dict[str, Any]:
    """Keep live agent progress compatible across direct, queue, and event paths."""
    normalized = dict(progress or {})
    for key in ("tool_calls", "browser_tool_calls", "interactions"):
        if key in normalized:
            normalized[key] = _coerce_progress_int(normalized.get(key))

    last_tool = normalized.get("last_tool") or normalized.get("current_tool")
    if last_tool:
        normalized["last_tool"] = str(last_tool)
        normalized["current_tool"] = str(last_tool)

    label = normalized.get("last_tool_label") or normalized.get("current_tool_label")
    if not label and last_tool:
        label = _short_tool_name(str(last_tool))
    if label:
        normalized["last_tool_label"] = str(label)
        normalized["current_tool_label"] = str(label)

    return normalized


async def _agent_run_temporal_payload(run: AgentRun) -> dict[str, Any]:
    from orchestrator.config import settings as app_settings
    from orchestrator.services.temporal_client import TemporalUnavailableError, get_agent_run_temporal_diagnostics

    progress = run.progress or {}
    task_queue = progress.get("task_queue") or app_settings.temporal_workflow_task_queue
    workflow_url = None
    if app_settings.temporal_ui_url and run.temporal_workflow_id:
        workflow_url = (
            f"{app_settings.temporal_ui_url.rstrip('/')}/namespaces/"
            f"{app_settings.temporal_namespace}/workflows/{run.temporal_workflow_id}"
        )
    payload: dict[str, Any] = {
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
        "temporal_ui_url": app_settings.temporal_ui_url,
        "temporal_ui_workflow_url": workflow_url,
        "temporal_namespace": app_settings.temporal_namespace,
        "task_queue": task_queue,
        "workflow_type": "AgentRunWorkflow",
        "available": False,
        "workflow_status": None,
        "activities": [],
        "summary": {"total_activities": 0, "failed_activities": 0, "retry_count": 0, "last_failure": None},
        "error": None,
    }
    if not run.temporal_workflow_id:
        payload["error"] = "No Temporal workflow id recorded for this agent run."
        return payload
    try:
        return {
            **payload,
            **await get_agent_run_temporal_diagnostics(
                run.temporal_workflow_id,
                run.temporal_run_id,
                task_queue=str(task_queue) if task_queue else None,
            ),
        }
    except TemporalUnavailableError as exc:
        payload["error"] = str(exc)
    except Exception as exc:
        payload["error"] = f"Temporal diagnostics unavailable: {exc}"
    return payload


def _agent_run_health(run: AgentRun, session: Session | None = None) -> dict[str, Any]:
    if session is None:
        with Session(engine) as scoped_session:
            return _agent_run_health(run, scoped_session)

    latest_event = session.exec(
        select(AgentRunEvent).where(AgentRunEvent.run_id == run.id).order_by(AgentRunEvent.sequence.desc()).limit(1)
    ).first()
    event_count = session.exec(select(func.count(AgentRunEvent.id)).where(AgentRunEvent.run_id == run.id)).one()
    tool_count = session.exec(
        select(func.count(AgentRunEvent.id)).where(
            AgentRunEvent.run_id == run.id,
            AgentRunEvent.event_type.in_(["tool_call", "browser_action"]),
        )
    ).one()
    error_count = session.exec(
        select(func.count(AgentRunEvent.id)).where(
            AgentRunEvent.run_id == run.id,
            AgentRunEvent.level.in_(["error", "critical"]),
        )
    ).one()

    progress = run.progress or {}
    if int(tool_count or 0) == 0:
        synthetic_events = _synthetic_agent_events(run, limit=500, sequence_offset=int(event_count or 0))
        synthetic_tool_count = len(synthetic_events)
        if synthetic_tool_count:
            event_count = int(event_count or 0) + synthetic_tool_count
            tool_count = synthetic_tool_count
            error_count = int(error_count or 0) + len([event for event in synthetic_events if event.get("level") == "error"])
            if latest_event is None:
                latest_event_response = synthetic_events[-1]
            else:
                latest_event_response = None
        else:
            latest_event_response = None
    else:
        latest_event_response = None
    if latest_event:
        from orchestrator.services.agent_run_events import event_to_response

        latest_event_response = event_to_response(latest_event)

    return {
        "event_count": int(event_count or 0),
        "tool_event_count": int(tool_count or 0),
        "error_event_count": int(error_count or 0),
        "latest_event": latest_event_response,
        "latest_heartbeat_at": progress.get("updated_at"),
        "agent_task_id": run.agent_task_id,
        "terminal": run.status in AGENT_TERMINAL_STATUSES,
        "terminal_reason": (latest_event.message if latest_event and run.status in AGENT_TERMINAL_STATUSES else None),
    }


def _agent_run_has_browser_tools(agent_type: str, config: dict[str, Any]) -> bool:
    """Return whether this agent run will need a Playwright browser."""
    if agent_type == "custom":
        return agent_run_runtime.custom_agent_uses_browser_tools(config.get("allowed_tools") or [])
    return agent_type in ("exploratory", "spec_generation")


def _serialize_agent_run(run: AgentRun, session: Session | None = None) -> dict[str, Any]:
    progress = run.progress or {}
    recovered_progress = _session_activity_progress(run)
    if recovered_progress:
        current_tool_calls = _coerce_progress_int(progress.get("tool_calls"))
        current_browser_tool_calls = _coerce_progress_int(progress.get("browser_tool_calls"))
        recovered_tool_calls = _coerce_progress_int(recovered_progress.get("tool_calls"))
        recovered_browser_tool_calls = _coerce_progress_int(recovered_progress.get("browser_tool_calls"))
        has_recent_tools = bool(progress.get("recent_tools"))
        has_recovered_recent_tools = bool(recovered_progress.get("recent_tools"))
        if (
            recovered_tool_calls > current_tool_calls
            or recovered_browser_tool_calls > current_browser_tool_calls
            or (has_recovered_recent_tools and not has_recent_tools)
        ):
            progress = {
                **progress,
                **{
                    key: value
                    for key, value in recovered_progress.items()
                    if key
                    in {
                        "artifact_source",
                        "test_run_id",
                        "recent_tools",
                        "synthetic",
                        "messages_received",
                        "text_blocks_received",
                        "completed_tool_calls",
                        "pending_tool_calls",
                        "output_chars",
                    }
                },
                "source": progress.get("source") or recovered_progress.get("source"),
                "phase": progress.get("phase") or recovered_progress.get("phase"),
                "tool_calls": max(current_tool_calls, recovered_tool_calls),
                "browser_tool_calls": max(current_browser_tool_calls, recovered_browser_tool_calls),
            }
    if _agent_run_has_browser_tools(run.agent_type, run.config):
        progress = {**browser_runtime_status(), **progress}
    progress = _normalize_agent_run_progress(progress)
    payload = {
        "id": run.id,
        "agent_type": run.agent_type,
        "runtime": getattr(run, "runtime", "claude_sdk") or "claude_sdk",
        "status": run.status,
        "created_at": run.created_at.isoformat(),
        "config": run.config,
        "result": run.result,
        "project_id": run.project_id,
        "progress": progress,
        "agent_task_id": run.agent_task_id,
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "updated_at": run.updated_at.isoformat() if getattr(run, "updated_at", None) else None,
        "state": run.state,
        "contract_status": run.contract_status,
        "finalization_status": run.finalization_status,
        "reporter_status": run.reporter_status,
        "verifier_status": run.verifier_status,
        "artifacts": _collect_agent_run_artifacts(run.id)
        if run.agent_type in ("exploratory", "custom", "spec_generation")
        else [],
    }
    payload["health"] = _agent_run_health(run, session)
    return payload


def _safe_json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _compact_agent_run_config(config: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "url",
        "agent_name",
        "flow_title",
        "prompt",
        "instructions",
        "runtime",
        "timeout_seconds",
        "browser_auth_session_id",
        "retry_of",
        "source_run_id",
    }
    compact: dict[str, Any] = {}
    for key in keys:
        value = config.get(key)
        if value is not None and value != "":
            compact[key] = value
    selected_tools = config.get("selected_tools")
    if isinstance(selected_tools, list):
        compact["selected_tools"] = selected_tools[:12]
    return compact


def _compact_agent_run_summary(progress: dict[str, Any]) -> str | None:
    for key in ("summary", "message", "phase"):
        value = progress.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
    return None


def _encode_agent_run_cursor(created_at: datetime, run_id: str) -> str:
    payload = json.dumps({"created_at": created_at.isoformat(), "id": run_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_agent_run_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        created_at = datetime.fromisoformat(str(payload["created_at"]).replace("Z", "+00:00"))
        if created_at.tzinfo is not None:
            created_at = created_at.replace(tzinfo=None)
        return created_at, str(payload["id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


def _agent_run_project_filters(project_id: str | None) -> list[Any]:
    if not project_id:
        return []
    if project_id == "default":
        return [or_(AgentRun.project_id == project_id, AgentRun.project_id == None)]
    return [AgentRun.project_id == project_id]


def _agent_run_search_filter(q: str | None) -> Any | None:
    needle = (q or "").strip().lower()
    if not needle:
        return None
    pattern = f"%{needle}%"
    return or_(
        func.lower(AgentRun.id).like(pattern),
        func.lower(AgentRun.agent_type).like(pattern),
        func.lower(AgentRun.status).like(pattern),
        func.lower(AgentRun.config_json).like(pattern),
        func.lower(AgentRun.progress_json).like(pattern),
    )


def _agent_run_status_filter(status: str | None) -> Any | None:
    normalized = (status or "").strip().lower()
    if not normalized or normalized == "all":
        return None
    if normalized == "active":
        return AgentRun.status.in_(AGENT_ACTIVE_STATUSES)
    if normalized == "completed":
        return AgentRun.status.in_({"completed", AGENT_PARTIAL_STATUS})
    if normalized == "cancelled":
        return AgentRun.status.in_({"cancelled", "canceled"})
    return AgentRun.status == normalized


def _agent_run_type_filter(agent_type: str | None) -> Any | None:
    normalized = (agent_type or "").strip()
    if not normalized or normalized == "all":
        return None
    return AgentRun.agent_type == normalized


def _agent_run_history_filters(
    *,
    project_id: str | None,
    status: str | None = None,
    agent_type: str | None = None,
    q: str | None = None,
) -> list[Any]:
    filters = _agent_run_project_filters(project_id)
    for item in (
        _agent_run_status_filter(status),
        _agent_run_type_filter(agent_type),
        _agent_run_search_filter(q),
    ):
        if item is not None:
            filters.append(item)
    return filters


def _agent_run_history_counts(session: Session, *, project_id: str | None, q: str | None) -> dict[str, Any]:
    base_filters = _agent_run_history_filters(project_id=project_id, q=q)
    status_counts = {
        status: int(count or 0)
        for status, count in session.exec(
            select(AgentRun.status, func.count(AgentRun.id)).where(*base_filters).group_by(AgentRun.status)
        ).all()
    }
    type_counts = {
        agent_type: int(count or 0)
        for agent_type, count in session.exec(
            select(AgentRun.agent_type, func.count(AgentRun.id)).where(*base_filters).group_by(AgentRun.agent_type)
        ).all()
    }
    total = sum(status_counts.values())
    completed = status_counts.get("completed", 0) + status_counts.get(AGENT_PARTIAL_STATUS, 0)
    active = sum(status_counts.get(status, 0) for status in AGENT_ACTIVE_STATUSES)
    cancelled = status_counts.get("cancelled", 0) + status_counts.get("canceled", 0)
    return {
        "status": {
            "all": total,
            "active": active,
            "completed": completed,
            "failed": status_counts.get("failed", 0),
            "cancelled": cancelled,
            "paused": status_counts.get("paused", 0),
        },
        "type": {
            "all": total,
            "exploratory": type_counts.get("exploratory", 0),
            "custom": type_counts.get("custom", 0),
            "writer": type_counts.get("writer", 0),
            "spec_generation": type_counts.get("spec_generation", 0),
        },
    }


def _serialize_agent_run_summary_row(row: Any) -> dict[str, Any]:
    (
        run_id,
        agent_type,
        runtime,
        status,
        created_at,
        started_at,
        completed_at,
        project_id,
        config_json,
        progress_json,
        contract_status,
        finalization_status,
        reporter_status,
        verifier_status,
    ) = row
    config = _compact_agent_run_config(_safe_json_dict(config_json))
    progress = _normalize_agent_run_progress(_safe_json_dict(progress_json))
    return {
        "id": run_id,
        "agent_type": agent_type,
        "runtime": runtime or "claude_sdk",
        "status": status,
        "created_at": created_at.isoformat(),
        "started_at": started_at.isoformat() if started_at else None,
        "completed_at": completed_at.isoformat() if completed_at else None,
        "project_id": project_id,
        "config": config,
        "progress": progress,
        "summary": _compact_agent_run_summary(progress),
        "contract_status": contract_status,
        "finalization_status": finalization_status,
        "reporter_status": reporter_status,
        "verifier_status": verifier_status,
    }


async def _live_agent_queue_progress(run: AgentRun) -> dict[str, Any]:
    if not run.agent_task_id or run.status in AGENT_TERMINAL_STATUSES:
        return {}
    try:
        from orchestrator.services.agent_queue import get_agent_queue

        queue = get_agent_queue()
        await queue.connect()
        progress = await queue.get_task_progress(str(run.agent_task_id))
        return progress if isinstance(progress, dict) else {}
    except Exception as exc:
        logger.debug("Failed to read live queue progress for agent run %s: %s", run.id, exc)
        return {}


async def _serialize_agent_run_live(run: AgentRun, session: Session | None = None) -> dict[str, Any]:
    payload = _serialize_agent_run(run, session)
    live_progress = await _live_agent_queue_progress(run)
    if live_progress:
        payload["progress"] = _normalize_agent_run_progress(
            {
                **(payload.get("progress") or {}),
                **live_progress,
            }
        )
    return payload


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
    filters = _agent_run_history_filters(project_id=project_id, status=status, agent_type=agent_type, q=q)
    decoded_cursor = _decode_agent_run_cursor(cursor)
    if decoded_cursor:
        cursor_created_at, cursor_id = decoded_cursor
        filters.append(
            or_(
                AgentRun.created_at < cursor_created_at,
                and_(AgentRun.created_at == cursor_created_at, AgentRun.id < cursor_id),
            )
        )

    total_filters = _agent_run_history_filters(project_id=project_id, status=status, agent_type=agent_type, q=q)
    total = int(session.exec(select(func.count(AgentRun.id)).where(*total_filters)).one() or 0)
    counts = _agent_run_history_counts(session, project_id=project_id, q=q)
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
            AgentRun.contract_status,
            AgentRun.finalization_status,
            AgentRun.reporter_status,
            AgentRun.verifier_status,
        )
        .where(*filters)
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(limit)
    )
    if offset and not cursor:
        statement = statement.offset(offset)

    rows = session.exec(statement).all()
    items = [_serialize_agent_run_summary_row(row) for row in rows]
    next_cursor = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = _encode_agent_run_cursor(last[4], last[0])
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
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    _filter_agent_run_project(run, project_id)

    payload = await _serialize_agent_run_live(run, session)
    payload["temporal"] = await _agent_run_temporal_payload(run)
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
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(run, project_id)

    from orchestrator.services.agent_run_events import event_to_response, list_agent_run_events

    events = list_agent_run_events(
        run_id=run.id,
        after_sequence=after_sequence,
        event_type=event_type,
        level=level,
        limit=limit,
        session=session,
    )
    durable_responses = [event_to_response(event) for event in events]
    durable_tool_count = session.exec(
        select(func.count(AgentRunEvent.id)).where(
            AgentRunEvent.run_id == run.id,
            AgentRunEvent.event_type.in_(["tool_call", "browser_action"]),
        )
    ).one()
    if int(durable_tool_count or 0) > 0:
        return durable_responses
    if event_type and event_type not in {"tool_call", "browser_action"}:
        return durable_responses
    max_sequence = session.exec(select(func.max(AgentRunEvent.sequence)).where(AgentRunEvent.run_id == run.id)).one()
    synthetic_events = _synthetic_agent_events(
        run,
        after_sequence=after_sequence,
        event_type=event_type,
        level=level,
        limit=max(1, limit - len(durable_responses)) if durable_responses else limit,
        sequence_offset=int(max_sequence or 0),
    )
    if not synthetic_events:
        return durable_responses
    return sorted([*durable_responses, *synthetic_events], key=lambda item: int(item.get("sequence") or 0))[:limit]


@router.get("/api/agents/runs/{id}/notes")
def list_agent_run_notes_api(
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
):
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(run, project_id)

    from orchestrator.services.agent_native_runs import list_agent_run_notes, serialize_agent_run_note

    notes = list_agent_run_notes(
        run_id=run.id,
        after_sequence=after_sequence,
        limit=limit,
        session=session,
    )
    if notes:
        return [serialize_agent_run_note(note) for note in notes]
    from orchestrator.api.models_db import AgentRunNote

    durable_note_count = session.exec(select(func.count(AgentRunNote.id)).where(AgentRunNote.run_id == run.id)).one()
    if int(durable_note_count or 0) > 0:
        return []
    return _synthetic_agent_notes(run, after_sequence=after_sequence, limit=limit)


@router.get("/api/agents/runs/{id}/events/stream")
async def stream_agent_run_events_api(
    request: Request,
    id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
):
    with Session(engine) as session:
        run = session.get(AgentRun, id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        _filter_agent_run_project(run, project_id)

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
                terminal = bool(run and run.status in AGENT_TERMINAL_STATUSES)
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
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(run, project_id)

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
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(run, project_id)

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
    run = session.get(AgentRun, id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _filter_agent_run_project(run, project_id)

    from orchestrator.services.agent_trace import trace_bundle_for_run

    bundle = await trace_bundle_for_run(run=run, session=session)
    response = JSONResponse(
        {
            "schema": "quorvex.agent_trace_export.v1",
            "exported_at": datetime.utcnow().isoformat(),
            "run": _serialize_agent_run(run, session),
            **bundle,
        }
    )
    response.headers["Content-Disposition"] = f'attachment; filename="agent-trace-{run.id}.json"'
    return response


@router.get("/api/agents/temporal/health")
async def get_agent_temporal_health():
    from orchestrator.services.temporal_client import check_agent_run_temporal_health

    return await check_agent_run_temporal_health()
