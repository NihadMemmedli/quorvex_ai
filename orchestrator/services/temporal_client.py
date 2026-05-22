"""Temporal client helpers for autonomous testing missions."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from orchestrator.config import settings

logger = logging.getLogger(__name__)


class TemporalUnavailableError(RuntimeError):
    """Raised when Temporal is not reachable or the SDK is unavailable."""


@dataclass(frozen=True)
class TemporalWorkflowStart:
    workflow_id: str
    run_id: str | None = None


async def _connect_client():
    try:
        from temporalio.client import Client
    except ImportError as exc:
        raise TemporalUnavailableError("temporalio is not installed") from exc

    try:
        return await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    except Exception as exc:  # pragma: no cover - exercised only with a live Temporal server
        raise TemporalUnavailableError(f"Temporal is unavailable at {settings.temporal_address}: {exc}") from exc


async def start_autonomous_mission_workflow(mission_id: str) -> TemporalWorkflowStart:
    """Start the long-lived Temporal workflow for a mission."""
    client = await _connect_client()
    workflow_id = f"autonomous-mission-{mission_id}-{uuid.uuid4().hex[:8]}"
    handle = await client.start_workflow(
        "AutonomousMissionWorkflow",
        {"mission_id": mission_id},
        id=workflow_id,
        task_queue=settings.temporal_task_queue,
    )
    logger.info("Started autonomous mission workflow %s for mission %s", workflow_id, mission_id)
    return TemporalWorkflowStart(workflow_id=workflow_id, run_id=getattr(handle, "first_execution_run_id", None))


async def start_custom_workflow_run(run_id: str) -> TemporalWorkflowStart:
    """Start a durable Temporal workflow for a custom workflow run."""
    client = await _connect_client()
    workflow_id = f"custom-workflow-run-{run_id}"
    handle = await client.start_workflow(
        "CustomWorkflowRun",
        {"run_id": run_id},
        id=workflow_id,
        task_queue=settings.temporal_workflow_task_queue,
    )
    logger.info("Started custom workflow Temporal run %s for %s", workflow_id, run_id)
    return TemporalWorkflowStart(workflow_id=workflow_id, run_id=getattr(handle, "first_execution_run_id", None))


async def signal_custom_workflow_run(workflow_id: str, signal_name: str, *args) -> None:
    """Signal a running custom workflow Temporal workflow."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(signal_name, *args)


async def signal_autonomous_mission_workflow(workflow_id: str, signal_name: str) -> None:
    """Signal a running autonomous mission workflow."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(signal_name)


async def describe_autonomous_mission_workflow(workflow_id: str) -> dict:
    """Return lightweight Temporal workflow status for mission health checks."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id)
    try:
        description = await handle.describe()
    except Exception as exc:  # pragma: no cover - requires live Temporal
        raise TemporalUnavailableError(f"Workflow {workflow_id} is not reachable: {exc}") from exc
    status = getattr(description, "status", None)
    return {
        "available": True,
        "workflow_id": workflow_id,
        "workflow_status": getattr(status, "name", str(status)) if status is not None else None,
        "error": None,
    }


async def check_custom_workflow_temporal_health() -> dict[str, Any]:
    """Return workflow-specific Temporal connection readiness."""
    try:
        await _connect_client()
    except TemporalUnavailableError as exc:
        return {
            "available": False,
            "status": "unavailable",
            "address": settings.temporal_address,
            "namespace": settings.temporal_namespace,
            "task_queue": settings.temporal_workflow_task_queue,
            "error": str(exc),
        }
    return {
        "available": True,
        "status": "healthy",
        "address": settings.temporal_address,
        "namespace": settings.temporal_namespace,
        "task_queue": settings.temporal_workflow_task_queue,
        "error": None,
    }


async def get_custom_workflow_temporal_diagnostics(workflow_id: str, run_id: str | None = None) -> dict[str, Any]:
    """Return parsed Temporal activity history for a custom workflow run."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id, run_id=run_id)
    try:
        description = await handle.describe()
        events = [event async for event in handle.fetch_history_events()]
    except Exception as exc:  # pragma: no cover - requires live Temporal
        raise TemporalUnavailableError(f"Workflow {workflow_id} history is not reachable: {exc}") from exc

    activities = _parse_activity_history(events)
    workflow_meta = _parse_workflow_history(events, description)
    failures = [activity for activity in activities if activity.get("last_failure")]
    retry_count = sum(max(0, int(activity.get("attempt_count") or 0) - 1) for activity in activities)
    status = getattr(description, "status", None)
    return {
        "temporal_available": True,
        "temporal_error": None,
        "temporal_namespace": getattr(settings, "temporal_namespace", None),
        "workflow_status": getattr(status, "name", str(status)) if status is not None else None,
        "activities": activities,
        "summary": {
            "total_activities": len(activities),
            "failed_activities": len([activity for activity in activities if activity.get("status") == "failed"]),
            "retry_count": retry_count,
            "last_failure": failures[-1]["last_failure"] if failures else None,
        },
        **workflow_meta,
    }


def _parse_workflow_history(events: list[Any], description: Any | None = None) -> dict[str, Any]:
    started_at: str | None = None
    closed_at: str | None = None
    close_event_type: str | None = None
    first_event_at: str | None = None
    last_event_at: str | None = None
    close_event_types = {
        "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED",
        "EVENT_TYPE_WORKFLOW_EXECUTION_FAILED",
        "EVENT_TYPE_WORKFLOW_EXECUTION_TIMED_OUT",
        "EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED",
        "EVENT_TYPE_WORKFLOW_EXECUTION_TERMINATED",
        "EVENT_TYPE_WORKFLOW_EXECUTION_CONTINUED_AS_NEW",
    }

    for event in events:
        event_time = _proto_time(event)
        if event_time:
            first_event_at = first_event_at or event_time
            last_event_at = event_time
        event_type = _event_type_name(event)
        if event_type == "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED":
            started_at = event_time
        elif event_type in close_event_types:
            closed_at = event_time
            close_event_type = event_type

    if description is not None:
        started_at = started_at or _time_value_to_iso(getattr(description, "start_time", None))
        closed_at = closed_at or _time_value_to_iso(getattr(description, "close_time", None))

    return {
        "history_event_count": len(events),
        "history_first_event_at": first_event_at,
        "history_last_event_at": last_event_at,
        "workflow_started_at": started_at,
        "workflow_closed_at": closed_at,
        "close_event_type": close_event_type,
    }


def _parse_activity_history(events: list[Any]) -> list[dict[str, Any]]:
    activities: dict[int, dict[str, Any]] = {}
    order: list[int] = []

    for event in events:
        event_type = _event_type_name(event)
        if event_type == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED":
            attrs = event.activity_task_scheduled_event_attributes
            activity_id = int(event.event_id)
            activity_type = getattr(getattr(attrs, "activity_type", None), "name", None)
            activities[activity_id] = {
                "activity_id": attrs.activity_id or str(activity_id),
                "activity_type": activity_type,
                "status": "scheduled",
                "scheduled_at": _proto_time(event),
                "started_at": None,
                "completed_at": None,
                "attempt_count": 0,
                "last_failure": None,
                "scheduled_event_id": activity_id,
                "started_event_id": None,
                "last_event_type": event_type,
                "failure_type": None,
                "failure_message": None,
                "failure_stack_trace": None,
                "timeout_type": None,
            }
            order.append(activity_id)
        elif event_type == "EVENT_TYPE_ACTIVITY_TASK_STARTED":
            attrs = event.activity_task_started_event_attributes
            activity = activities.setdefault(int(attrs.scheduled_event_id), _unknown_activity(attrs.scheduled_event_id))
            activity["status"] = "started"
            activity["started_at"] = _proto_time(event)
            activity["started_event_id"] = int(getattr(event, "event_id", 0) or 0) or None
            activity["last_event_type"] = event_type
            activity["attempt_count"] = max(int(activity.get("attempt_count") or 0), int(attrs.attempt or 1))
            if getattr(attrs, "last_failure", None):
                activity.update(_failure_details(attrs.last_failure))
        elif event_type == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED":
            attrs = event.activity_task_completed_event_attributes
            activity = activities.setdefault(int(attrs.scheduled_event_id), _unknown_activity(attrs.scheduled_event_id))
            activity["status"] = "completed"
            activity["completed_at"] = _proto_time(event)
            activity["last_event_type"] = event_type
        elif event_type == "EVENT_TYPE_ACTIVITY_TASK_FAILED":
            attrs = event.activity_task_failed_event_attributes
            activity = activities.setdefault(int(attrs.scheduled_event_id), _unknown_activity(attrs.scheduled_event_id))
            activity["status"] = "failed"
            activity["completed_at"] = _proto_time(event)
            activity["last_event_type"] = event_type
            activity.update(_failure_details(getattr(attrs, "failure", None)))
        elif event_type == "EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT":
            attrs = event.activity_task_timed_out_event_attributes
            activity = activities.setdefault(int(attrs.scheduled_event_id), _unknown_activity(attrs.scheduled_event_id))
            activity["status"] = "timed_out"
            activity["completed_at"] = _proto_time(event)
            activity["last_event_type"] = event_type
            timeout_type = getattr(attrs, "timeout_type", None)
            if timeout_type is not None:
                activity["timeout_type"] = _enum_value_name(timeout_type)
            activity.update(_failure_details(getattr(attrs, "failure", None)))

    return [activities[event_id] for event_id in order if event_id in activities]


def _unknown_activity(scheduled_event_id: int) -> dict[str, Any]:
    return {
        "activity_id": str(scheduled_event_id),
        "activity_type": "unknown",
        "status": "unknown",
        "scheduled_at": None,
        "started_at": None,
        "completed_at": None,
        "attempt_count": 0,
        "last_failure": None,
        "scheduled_event_id": int(scheduled_event_id),
        "started_event_id": None,
        "last_event_type": None,
        "failure_type": None,
        "failure_message": None,
        "failure_stack_trace": None,
        "timeout_type": None,
    }


def _failure_details(failure: Any | None) -> dict[str, Any]:
    if not failure:
        return {
            "last_failure": None,
            "failure_type": None,
            "failure_message": None,
            "failure_stack_trace": None,
        }
    message = getattr(failure, "message", None) or str(failure)
    application_info = getattr(failure, "application_failure_info", None)
    timeout_info = getattr(failure, "timeout_failure_info", None)
    failure_type = getattr(application_info, "type", None) if application_info else None
    if not failure_type and timeout_info:
        failure_type = _enum_value_name(getattr(timeout_info, "timeout_type", None))
    return {
        "last_failure": message,
        "failure_type": failure_type,
        "failure_message": message,
        "failure_stack_trace": getattr(failure, "stack_trace", None),
    }


def _event_type_name(event: Any) -> str:
    try:
        from temporalio.api.enums.v1 import EventType

        return EventType.Name(int(event.event_type))
    except Exception:
        return getattr(event.event_type, "name", str(event.event_type))


def _proto_time(event: Any) -> str | None:
    return _time_value_to_iso(getattr(event, "event_time", None))


def _time_value_to_iso(value: Any | None) -> str | None:
    if not value:
        return None
    try:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return value.ToDatetime(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _enum_value_name(value: Any | None) -> str | None:
    if value is None or value == 0:
        return None
    name = getattr(value, "name", None)
    if name and name != "TIMEOUT_TYPE_UNSPECIFIED":
        return str(name)
    text = str(value)
    return None if text in {"0", "TIMEOUT_TYPE_UNSPECIFIED"} else text
