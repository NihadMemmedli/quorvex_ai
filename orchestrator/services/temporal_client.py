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
        return await Client.connect(
            settings.temporal_address, namespace=settings.temporal_namespace
        )
    except (
        Exception
    ) as exc:  # pragma: no cover - exercised only with a live Temporal server
        raise TemporalUnavailableError(
            f"Temporal is unavailable at {settings.temporal_address}: {exc}"
        ) from exc


async def describe_temporal_task_queue(task_queue: str) -> dict[str, Any]:
    """Return live Temporal task queue poller counts for workflow and activity tasks."""
    client = await _connect_client()
    try:
        from temporalio.api.enums.v1 import TaskQueueType
        from temporalio.api.taskqueue.v1 import TaskQueue
        from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
    except ImportError as exc:
        raise TemporalUnavailableError("temporalio task queue APIs are not available") from exc

    async def _describe(queue_type: int) -> dict[str, Any]:
        response = await client.workflow_service.describe_task_queue(
            DescribeTaskQueueRequest(
                namespace=settings.temporal_namespace,
                task_queue=TaskQueue(name=task_queue),
                task_queue_type=queue_type,
                report_pollers=True,
                include_task_queue_status=True,
            )
        )
        pollers = list(getattr(response, "pollers", []) or [])
        status = getattr(response, "task_queue_status", None)
        return {
            "poller_count": len(pollers),
            "pollers": [
                {
                    "identity": getattr(poller, "identity", None),
                    "last_access_time": _time_value_to_iso(getattr(poller, "last_access_time", None)),
                }
                for poller in pollers
            ],
            "backlog_count_hint": int(getattr(status, "backlog_count_hint", 0) or 0) if status else 0,
            "read_level": int(getattr(status, "read_level", 0) or 0) if status else 0,
            "ack_level": int(getattr(status, "ack_level", 0) or 0) if status else 0,
        }

    try:
        workflow = await _describe(TaskQueueType.Value("TASK_QUEUE_TYPE_WORKFLOW"))
        activity = await _describe(TaskQueueType.Value("TASK_QUEUE_TYPE_ACTIVITY"))
    except Exception as exc:  # pragma: no cover - requires live Temporal server behavior
        raise TemporalUnavailableError(f"Temporal task queue {task_queue} is not reachable: {exc}") from exc

    return {
        "task_queue": task_queue,
        "workflow": workflow,
        "activity": activity,
        "workflow_pollers": workflow["poller_count"],
        "activity_pollers": activity["poller_count"],
        "has_workflow_pollers": workflow["poller_count"] > 0,
        "has_activity_pollers": activity["poller_count"] > 0,
    }


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
    logger.info(
        "Started autonomous mission workflow %s for mission %s", workflow_id, mission_id
    )
    return TemporalWorkflowStart(
        workflow_id=workflow_id, run_id=getattr(handle, "first_execution_run_id", None)
    )


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
    return TemporalWorkflowStart(
        workflow_id=workflow_id, run_id=getattr(handle, "first_execution_run_id", None)
    )


async def start_agent_run_workflow(
    run_id: str,
    *,
    task_queue: str | None = None,
) -> TemporalWorkflowStart:
    """Start a durable Temporal workflow for a standalone agent run."""
    client = await _connect_client()
    workflow_id = f"agent-run-{run_id}"
    selected_task_queue = task_queue or settings.temporal_workflow_task_queue
    handle = await client.start_workflow(
        "AgentRunWorkflow",
        {"run_id": run_id},
        id=workflow_id,
        task_queue=selected_task_queue,
    )
    logger.info(
        "Started agent run Temporal workflow %s for %s task_queue=%s",
        workflow_id,
        run_id,
        selected_task_queue,
    )
    return TemporalWorkflowStart(
        workflow_id=workflow_id, run_id=getattr(handle, "first_execution_run_id", None)
    )


async def start_test_run_workflow(
    run_id: str,
    payload: dict[str, Any],
    *,
    task_queue: str | None = None,
) -> TemporalWorkflowStart:
    """Start a durable Temporal workflow for a classic test run."""
    client = await _connect_client()
    workflow_id = f"test-run-{run_id}"
    selected_task_queue = task_queue or settings.temporal_browser_workflow_task_queue
    handle = await client.start_workflow(
        "TestRunWorkflow",
        {"run_id": run_id, **payload},
        id=workflow_id,
        task_queue=selected_task_queue,
    )
    logger.info(
        "Started test run Temporal workflow %s for %s task_queue=%s",
        workflow_id,
        run_id,
        selected_task_queue,
    )
    return TemporalWorkflowStart(
        workflow_id=workflow_id, run_id=getattr(handle, "first_execution_run_id", None)
    )


async def start_autopilot_workflow(
    session_id: str,
    *,
    task_queue: str | None = None,
) -> TemporalWorkflowStart:
    """Start a durable Temporal workflow for an AutoPilot session."""
    client = await _connect_client()
    workflow_id = f"autopilot-{session_id}"
    selected_task_queue = task_queue or settings.temporal_browser_workflow_task_queue
    handle = await client.start_workflow(
        "AutoPilotWorkflow",
        {"session_id": session_id},
        id=workflow_id,
        task_queue=selected_task_queue,
    )
    logger.info(
        "Started AutoPilot Temporal workflow %s for %s task_queue=%s",
        workflow_id,
        session_id,
        selected_task_queue,
    )
    return TemporalWorkflowStart(
        workflow_id=workflow_id, run_id=getattr(handle, "first_execution_run_id", None)
    )


async def start_domain_job_workflow(job_type: str, job_id: str, payload: dict[str, Any]) -> TemporalWorkflowStart:
    """Start a durable Temporal workflow for a domain background job."""
    client = await _connect_client()
    workflow_id = f"domain-job-{job_type}-{job_id}"
    handle = await client.start_workflow(
        "DomainJobWorkflow",
        {"job_type": job_type, "job_id": job_id, **payload},
        id=workflow_id,
        task_queue=settings.temporal_workflow_task_queue,
    )
    logger.info("Started domain job Temporal workflow %s for %s", workflow_id, job_id)
    return TemporalWorkflowStart(
        workflow_id=workflow_id, run_id=getattr(handle, "first_execution_run_id", None)
    )


async def signal_custom_workflow_run(workflow_id: str, signal_name: str, *args) -> None:
    """Signal a running custom workflow Temporal workflow."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(signal_name, *args)


async def signal_agent_run_workflow(workflow_id: str, signal_name: str, *args) -> None:
    """Signal a running standalone agent Temporal workflow."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(signal_name, *args)


async def signal_test_run_workflow(workflow_id: str, signal_name: str, *args) -> None:
    """Signal a running classic test run Temporal workflow."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(signal_name, *args)


async def signal_autopilot_workflow(workflow_id: str, signal_name: str, *args) -> None:
    """Signal a running AutoPilot Temporal workflow."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(signal_name, *args)


async def signal_autonomous_mission_workflow(
    workflow_id: str, signal_name: str
) -> None:
    """Signal a running autonomous mission workflow."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(signal_name)


async def describe_agent_run_workflow(workflow_id: str) -> dict:
    """Return lightweight Temporal workflow status for standalone agent runs."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id)
    try:
        description = await handle.describe()
    except Exception as exc:  # pragma: no cover - requires live Temporal
        raise TemporalUnavailableError(
            f"Workflow {workflow_id} is not reachable: {exc}"
        ) from exc
    status = getattr(description, "status", None)
    return {
        "available": True,
        "workflow_id": workflow_id,
        "workflow_status": (
            getattr(status, "name", str(status)) if status is not None else None
        ),
        "error": None,
    }


async def describe_test_run_workflow(workflow_id: str) -> dict:
    """Return lightweight Temporal workflow status for classic test runs."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id)
    try:
        description = await handle.describe()
    except Exception as exc:  # pragma: no cover - requires live Temporal
        raise TemporalUnavailableError(
            f"Workflow {workflow_id} is not reachable: {exc}"
        ) from exc
    status = getattr(description, "status", None)
    return {
        "available": True,
        "workflow_id": workflow_id,
        "workflow_type": "TestRunWorkflow",
        "workflow_status": (
            getattr(status, "name", str(status)) if status is not None else None
        ),
        "error": None,
    }


async def describe_autopilot_workflow(workflow_id: str) -> dict[str, Any]:
    """Return lightweight Temporal workflow status for AutoPilot sessions."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id)
    try:
        description = await handle.describe()
    except Exception as exc:  # pragma: no cover - requires live Temporal
        raise TemporalUnavailableError(
            f"Workflow {workflow_id} is not reachable: {exc}"
        ) from exc
    status = getattr(description, "status", None)
    return {
        "available": True,
        "workflow_id": workflow_id,
        "workflow_type": "AutoPilotWorkflow",
        "workflow_status": (
            getattr(status, "name", str(status)) if status is not None else None
        ),
        "error": None,
    }


async def check_agent_run_temporal_health() -> dict[str, Any]:
    """Return Temporal readiness for standalone agent-run workflows."""
    worker_contract: dict[str, Any] = {}
    try:
        from orchestrator.services.custom_workflow_worker import get_worker_contract

        worker_contract = get_worker_contract()
    except Exception as exc:
        worker_contract = {"contract_error": str(exc)}

    try:
        await _connect_client()
    except TemporalUnavailableError as exc:
        return {
            "available": False,
            "status": "unavailable",
            "address": settings.temporal_address,
            "namespace": settings.temporal_namespace,
            "task_queue": settings.temporal_workflow_task_queue,
            "workflow_type": "AgentRunWorkflow",
            "worker_module": "orchestrator.services.custom_workflow_worker",
            "worker_contract": worker_contract,
            "error": str(exc),
        }

    task_queue_status: dict[str, Any] = {}
    try:
        task_queue_status = await describe_temporal_task_queue(settings.temporal_workflow_task_queue)
    except TemporalUnavailableError as exc:
        return {
            "available": False,
            "status": "degraded",
            "address": settings.temporal_address,
            "namespace": settings.temporal_namespace,
            "task_queue": settings.temporal_workflow_task_queue,
            "workflow_type": "AgentRunWorkflow",
            "worker_module": "orchestrator.services.custom_workflow_worker",
            "worker_contract": worker_contract,
            "task_queue_status": task_queue_status,
            "error": str(exc),
        }

    has_workers = bool(task_queue_status.get("has_workflow_pollers")) and bool(
        task_queue_status.get("has_activity_pollers")
    )
    return {
        "available": has_workers,
        "status": "healthy" if has_workers else "degraded",
        "address": settings.temporal_address,
        "namespace": settings.temporal_namespace,
        "task_queue": settings.temporal_workflow_task_queue,
        "workflow_type": "AgentRunWorkflow",
        "worker_module": "orchestrator.services.custom_workflow_worker",
        "worker_contract": worker_contract,
        "task_queue_status": task_queue_status,
        "worker_pollers": {
            "workflow": task_queue_status.get("workflow_pollers", 0),
            "activity": task_queue_status.get("activity_pollers", 0),
        },
        "error": None if has_workers else "No Temporal worker pollers are active for agent runs.",
    }


async def check_autopilot_temporal_health() -> dict[str, Any]:
    """Return Temporal readiness for AutoPilot browser workflows."""
    worker_contract: dict[str, Any] = {}
    try:
        from orchestrator.services.custom_workflow_worker import get_worker_contract

        worker_contract = get_worker_contract()
    except Exception as exc:
        worker_contract = {"contract_error": str(exc)}

    task_queue = settings.temporal_browser_workflow_task_queue
    base = {
        "address": settings.temporal_address,
        "namespace": settings.temporal_namespace,
        "task_queue": task_queue,
        "workflow_type": "AutoPilotWorkflow",
        "worker_module": "orchestrator.services.custom_workflow_worker",
        "worker_contract": worker_contract,
    }

    try:
        await _connect_client()
    except TemporalUnavailableError as exc:
        return {**base, "available": False, "status": "unavailable", "error": str(exc)}

    task_queue_status: dict[str, Any] = {}
    try:
        task_queue_status = await describe_temporal_task_queue(task_queue)
    except TemporalUnavailableError as exc:
        return {
            **base,
            "available": False,
            "status": "degraded",
            "task_queue_status": task_queue_status,
            "error": str(exc),
        }

    has_workers = bool(task_queue_status.get("has_workflow_pollers")) and bool(
        task_queue_status.get("has_activity_pollers")
    )
    return {
        **base,
        "available": has_workers,
        "status": "healthy" if has_workers else "degraded",
        "task_queue_status": task_queue_status,
        "worker_pollers": {
            "workflow": task_queue_status.get("workflow_pollers", 0),
            "activity": task_queue_status.get("activity_pollers", 0),
        },
        "error": None if has_workers else "No Temporal worker pollers are active for AutoPilot browser workflows.",
    }


async def describe_autonomous_mission_workflow(workflow_id: str) -> dict:
    """Return lightweight Temporal workflow status for mission health checks."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id)
    try:
        description = await handle.describe()
    except Exception as exc:  # pragma: no cover - requires live Temporal
        raise TemporalUnavailableError(
            f"Workflow {workflow_id} is not reachable: {exc}"
        ) from exc
    status = getattr(description, "status", None)
    return {
        "available": True,
        "workflow_id": workflow_id,
        "workflow_status": (
            getattr(status, "name", str(status)) if status is not None else None
        ),
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
    task_queue_status: dict[str, Any] = {}
    try:
        task_queue_status = await describe_temporal_task_queue(settings.temporal_workflow_task_queue)
    except TemporalUnavailableError as exc:
        return {
            "available": False,
            "status": "degraded",
            "address": settings.temporal_address,
            "namespace": settings.temporal_namespace,
            "task_queue": settings.temporal_workflow_task_queue,
            "workflow_types": ["CustomWorkflowRun", "AgentRunWorkflow", "DomainJobWorkflow", "TestRunWorkflow"],
            "worker_module": "orchestrator.services.custom_workflow_worker",
            "task_queue_status": task_queue_status,
            "error": str(exc),
        }
    has_workers = bool(task_queue_status.get("has_workflow_pollers")) and bool(task_queue_status.get("has_activity_pollers"))
    return {
        "available": has_workers,
        "status": "healthy" if has_workers else "degraded",
        "address": settings.temporal_address,
        "namespace": settings.temporal_namespace,
        "task_queue": settings.temporal_workflow_task_queue,
        "workflow_types": ["CustomWorkflowRun", "AgentRunWorkflow", "DomainJobWorkflow", "TestRunWorkflow"],
        "worker_module": "orchestrator.services.custom_workflow_worker",
        "task_queue_status": task_queue_status,
        "error": None if has_workers else "No Temporal worker pollers are active for custom workflows.",
    }


async def get_custom_workflow_temporal_diagnostics(
    workflow_id: str, run_id: str | None = None
) -> dict[str, Any]:
    """Return parsed Temporal activity history for a custom workflow run."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id, run_id=run_id)
    try:
        description = await handle.describe()
        events = [event async for event in handle.fetch_history_events()]
    except Exception as exc:  # pragma: no cover - requires live Temporal
        raise TemporalUnavailableError(
            f"Workflow {workflow_id} history is not reachable: {exc}"
        ) from exc

    activities = _merge_pending_activity_history(_parse_activity_history(events), description)
    workflow_meta = _parse_workflow_history(events, description)
    failures = [activity for activity in activities if activity.get("last_failure")]
    retry_count = sum(
        max(0, int(activity.get("attempt_count") or 0) - 1) for activity in activities
    )
    status = getattr(description, "status", None)
    return {
        "temporal_available": True,
        "temporal_error": None,
        "temporal_namespace": getattr(settings, "temporal_namespace", None),
        "workflow_status": (
            getattr(status, "name", str(status)) if status is not None else None
        ),
        "activities": activities,
        "summary": {
            "total_activities": len(activities),
            "failed_activities": len(
                [
                    activity
                    for activity in activities
                    if activity.get("status") == "failed"
                ]
            ),
            "retry_count": retry_count,
            "last_failure": failures[-1]["last_failure"] if failures else None,
        },
        **workflow_meta,
    }


async def get_agent_run_temporal_diagnostics(
    workflow_id: str, run_id: str | None = None
) -> dict[str, Any]:
    """Return parsed Temporal activity history for a standalone agent run."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id, run_id=run_id)
    try:
        description = await handle.describe()
        events = [event async for event in handle.fetch_history_events()]
    except Exception as exc:  # pragma: no cover - requires live Temporal
        raise TemporalUnavailableError(
            f"Workflow {workflow_id} history is not reachable: {exc}"
        ) from exc

    activities = _merge_pending_activity_history(_parse_activity_history(events), description)
    workflow_meta = _parse_workflow_history(events, description)
    workflow_task_failures = _parse_workflow_task_failures(events)
    failures = [activity for activity in activities if activity.get("last_failure")]
    retry_count = sum(
        max(0, int(activity.get("attempt_count") or 0) - 1) for activity in activities
    )
    status = getattr(description, "status", None)
    worker_registration_failure = _agent_run_worker_registration_failure(
        workflow_task_failures
    )
    diagnostic_error = None
    if worker_registration_failure and not activities:
        diagnostic_error = worker_registration_failure
    task_queue_status: dict[str, Any] = {}
    try:
        task_queue_status = await describe_temporal_task_queue(settings.temporal_workflow_task_queue)
    except TemporalUnavailableError as exc:
        diagnostic_error = diagnostic_error or str(exc)
    return {
        "available": not diagnostic_error,
        "temporal_available": True,
        "error": diagnostic_error,
        "temporal_error": diagnostic_error,
        "temporal_namespace": getattr(settings, "temporal_namespace", None),
        "task_queue": getattr(settings, "temporal_workflow_task_queue", None),
        "workflow_type": "AgentRunWorkflow",
        "task_queue_status": task_queue_status,
        "workflow_status": (
            getattr(status, "name", str(status)) if status is not None else None
        ),
        "activities": activities,
        "workflow_task_failures": workflow_task_failures,
        "summary": {
            "total_activities": len(activities),
            "failed_activities": len(
                [
                    activity
                    for activity in activities
                    if activity.get("status") == "failed"
                ]
            ),
            "retry_count": retry_count,
            "last_failure": failures[-1]["last_failure"] if failures else None,
            "last_workflow_task_failure": (
                workflow_task_failures[-1]["message"]
                if workflow_task_failures
                else None
            ),
        },
        **workflow_meta,
    }


async def get_autopilot_temporal_diagnostics(
    workflow_id: str, run_id: str | None = None
) -> dict[str, Any]:
    """Return parsed Temporal activity history for an AutoPilot session."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id, run_id=run_id)
    try:
        description = await handle.describe()
        events = [event async for event in handle.fetch_history_events()]
    except Exception as exc:  # pragma: no cover - requires live Temporal
        raise TemporalUnavailableError(
            f"Workflow {workflow_id} history is not reachable: {exc}"
        ) from exc

    activities = _merge_pending_activity_history(_parse_activity_history(events), description)
    workflow_meta = _parse_workflow_history(events, description)
    workflow_task_failures = _parse_workflow_task_failures(events)
    failures = [activity for activity in activities if activity.get("last_failure")]
    retry_count = sum(
        max(0, int(activity.get("attempt_count") or 0) - 1) for activity in activities
    )
    status = getattr(description, "status", None)
    worker_registration_failure = _autopilot_worker_registration_failure(
        workflow_task_failures
    )
    diagnostic_error = worker_registration_failure if worker_registration_failure and not activities else None
    task_queue_status: dict[str, Any] = {}
    try:
        task_queue_status = await describe_temporal_task_queue(settings.temporal_browser_workflow_task_queue)
    except TemporalUnavailableError as exc:
        diagnostic_error = diagnostic_error or str(exc)
    return {
        "available": not diagnostic_error,
        "temporal_available": True,
        "error": diagnostic_error,
        "temporal_error": diagnostic_error,
        "temporal_namespace": getattr(settings, "temporal_namespace", None),
        "task_queue": getattr(settings, "temporal_browser_workflow_task_queue", None),
        "workflow_type": "AutoPilotWorkflow",
        "task_queue_status": task_queue_status,
        "workflow_status": (
            getattr(status, "name", str(status)) if status is not None else None
        ),
        "activities": activities,
        "workflow_task_failures": workflow_task_failures,
        "summary": {
            "total_activities": len(activities),
            "failed_activities": len(
                [
                    activity
                    for activity in activities
                    if activity.get("status") == "failed"
                ]
            ),
            "retry_count": retry_count,
            "last_failure": failures[-1]["last_failure"] if failures else None,
            "last_workflow_task_failure": (
                workflow_task_failures[-1]["message"]
                if workflow_task_failures
                else None
            ),
        },
        **workflow_meta,
    }


async def get_test_run_temporal_diagnostics(
    workflow_id: str, run_id: str | None = None
) -> dict[str, Any]:
    """Return parsed Temporal activity history for a classic browser test run."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id, run_id=run_id)
    try:
        description = await handle.describe()
        events = [event async for event in handle.fetch_history_events()]
    except Exception as exc:  # pragma: no cover - requires live Temporal
        raise TemporalUnavailableError(
            f"Workflow {workflow_id} history is not reachable: {exc}"
        ) from exc

    activities = _merge_pending_activity_history(_parse_activity_history(events), description)
    workflow_meta = _parse_workflow_history(events, description)
    workflow_task_failures = _parse_workflow_task_failures(events)
    failures = [activity for activity in activities if activity.get("last_failure")]
    retry_count = sum(
        max(0, int(activity.get("attempt_count") or 0) - 1) for activity in activities
    )
    status = getattr(description, "status", None)
    worker_registration_failure = _test_run_worker_registration_failure(
        workflow_task_failures
    )
    diagnostic_error = worker_registration_failure if worker_registration_failure and not activities else None
    task_queue_status: dict[str, Any] = {}
    try:
        task_queue_status = await describe_temporal_task_queue(settings.temporal_browser_workflow_task_queue)
    except TemporalUnavailableError as exc:
        diagnostic_error = diagnostic_error or str(exc)
    return {
        "available": not diagnostic_error,
        "temporal_available": True,
        "error": diagnostic_error,
        "temporal_error": diagnostic_error,
        "temporal_namespace": getattr(settings, "temporal_namespace", None),
        "task_queue": getattr(settings, "temporal_browser_workflow_task_queue", None),
        "workflow_type": "TestRunWorkflow",
        "task_queue_status": task_queue_status,
        "workflow_status": (
            getattr(status, "name", str(status)) if status is not None else None
        ),
        "activities": activities,
        "workflow_task_failures": workflow_task_failures,
        "summary": {
            "total_activities": len(activities),
            "failed_activities": len(
                [
                    activity
                    for activity in activities
                    if activity.get("status") == "failed"
                ]
            ),
            "retry_count": retry_count,
            "last_failure": failures[-1]["last_failure"] if failures else None,
            "last_workflow_task_failure": (
                workflow_task_failures[-1]["message"]
                if workflow_task_failures
                else None
            ),
        },
        **workflow_meta,
    }


def _parse_workflow_history(
    events: list[Any], description: Any | None = None
) -> dict[str, Any]:
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
        started_at = started_at or _time_value_to_iso(
            getattr(description, "start_time", None)
        )
        closed_at = closed_at or _time_value_to_iso(
            getattr(description, "close_time", None)
        )

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
            activity = activities.setdefault(
                int(attrs.scheduled_event_id),
                _unknown_activity(attrs.scheduled_event_id),
            )
            activity["status"] = "started"
            activity["started_at"] = _proto_time(event)
            activity["started_event_id"] = (
                int(getattr(event, "event_id", 0) or 0) or None
            )
            activity["last_event_type"] = event_type
            activity["attempt_count"] = max(
                int(activity.get("attempt_count") or 0), int(attrs.attempt or 1)
            )
            if getattr(attrs, "last_failure", None):
                activity.update(_failure_details(attrs.last_failure))
        elif event_type == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED":
            attrs = event.activity_task_completed_event_attributes
            activity = activities.setdefault(
                int(attrs.scheduled_event_id),
                _unknown_activity(attrs.scheduled_event_id),
            )
            activity["status"] = "completed"
            activity["completed_at"] = _proto_time(event)
            activity["last_event_type"] = event_type
        elif event_type == "EVENT_TYPE_ACTIVITY_TASK_FAILED":
            attrs = event.activity_task_failed_event_attributes
            activity = activities.setdefault(
                int(attrs.scheduled_event_id),
                _unknown_activity(attrs.scheduled_event_id),
            )
            activity["status"] = "failed"
            activity["completed_at"] = _proto_time(event)
            activity["last_event_type"] = event_type
            activity.update(_failure_details(getattr(attrs, "failure", None)))
        elif event_type == "EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT":
            attrs = event.activity_task_timed_out_event_attributes
            activity = activities.setdefault(
                int(attrs.scheduled_event_id),
                _unknown_activity(attrs.scheduled_event_id),
            )
            activity["status"] = "timed_out"
            activity["completed_at"] = _proto_time(event)
            activity["last_event_type"] = event_type
            timeout_type = getattr(attrs, "timeout_type", None)
            if timeout_type is not None:
                activity["timeout_type"] = _enum_value_name(timeout_type)
            activity.update(_failure_details(getattr(attrs, "failure", None)))

    return [activities[event_id] for event_id in order if event_id in activities]


def _merge_pending_activity_history(
    activities: list[dict[str, Any]],
    description: Any | None,
) -> list[dict[str, Any]]:
    """Overlay live pending activity state from WorkflowExecutionDescription.

    Temporal history records an activity as scheduled and later completed/failed,
    but a currently running long activity can remain scheduled in history while
    its live state is only exposed through DescribeWorkflowExecution.
    """
    raw_description = getattr(description, "raw_description", None)
    pending_activities = list(getattr(raw_description, "pending_activities", []) or [])
    if not pending_activities:
        return activities

    by_activity_id = {
        str(activity.get("activity_id")): activity
        for activity in activities
        if activity.get("activity_id") is not None
    }
    merged = list(activities)
    terminal_statuses = {"completed", "failed", "timed_out", "cancelled"}

    for pending in pending_activities:
        activity_id = str(getattr(pending, "activity_id", "") or "")
        if not activity_id:
            continue

        activity = by_activity_id.get(activity_id)
        if activity is None:
            activity_type = getattr(getattr(pending, "activity_type", None), "name", None)
            activity = {
                **_unknown_activity(0),
                "activity_id": activity_id,
                "activity_type": activity_type or "unknown",
                "scheduled_event_id": None,
            }
            by_activity_id[activity_id] = activity
            merged.append(activity)

        state_name = _pending_activity_state_name(getattr(pending, "state", None))
        live_status = _pending_activity_status(state_name)
        if live_status and str(activity.get("status") or "") not in terminal_statuses:
            activity["status"] = live_status
            activity["last_event_type"] = state_name

        last_started_at = _time_value_to_iso(getattr(pending, "last_started_time", None))
        if last_started_at:
            activity["started_at"] = activity.get("started_at") or last_started_at
            activity["last_started_at"] = last_started_at

        attempt = int(getattr(pending, "attempt", 0) or 0)
        if attempt:
            activity["attempt_count"] = max(int(activity.get("attempt_count") or 0), attempt)

        worker_identity = getattr(pending, "last_worker_identity", None)
        if worker_identity:
            activity["last_worker_identity"] = worker_identity

        next_attempt_at = _time_value_to_iso(getattr(pending, "next_attempt_schedule_time", None))
        if next_attempt_at:
            activity["next_attempt_schedule_at"] = next_attempt_at

        last_failure = getattr(pending, "last_failure", None)
        if last_failure:
            activity.update(_failure_details(last_failure))

    return merged


def _pending_activity_status(state_name: str | None) -> str | None:
    if not state_name:
        return None
    normalized = state_name.lower()
    if normalized.endswith("_started"):
        return "started"
    if normalized.endswith("_cancel_requested"):
        return "cancel_requested"
    if normalized.endswith("_scheduled"):
        return "scheduled"
    return normalized.replace("pending_activity_state_", "")


def _pending_activity_state_name(value: Any | None) -> str | None:
    if value is None or value == 0:
        return None
    name = getattr(value, "name", None)
    if name:
        return str(name)
    try:
        from temporalio.api.enums.v1 import PendingActivityState

        return PendingActivityState.Name(int(value))
    except Exception:
        text = str(value)
        return None if text == "0" else text


def _parse_workflow_task_failures(events: list[Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for event in events:
        event_type = _event_type_name(event)
        if event_type != "EVENT_TYPE_WORKFLOW_TASK_FAILED":
            continue
        attrs = getattr(event, "workflow_task_failed_event_attributes", None)
        failure_details = _failure_details(
            getattr(attrs, "failure", None) if attrs else None
        )
        message = failure_details.get("failure_message") or failure_details.get(
            "last_failure"
        )
        cause = getattr(attrs, "cause", None) if attrs else None
        failures.append(
            {
                "event_id": int(getattr(event, "event_id", 0) or 0) or None,
                "at": _proto_time(event),
                "message": message or "Workflow task failed",
                "failure_type": failure_details.get("failure_type"),
                "failure_stack_trace": failure_details.get("failure_stack_trace"),
                "cause": _enum_value_name(cause)
                or (str(cause) if cause is not None else None),
                "scheduled_event_id": (
                    int(getattr(attrs, "scheduled_event_id", 0) or 0) if attrs else None
                ),
                "started_event_id": (
                    int(getattr(attrs, "started_event_id", 0) or 0) if attrs else None
                ),
            }
        )
    return failures


def _agent_run_worker_registration_failure(
    failures: list[dict[str, Any]],
) -> str | None:
    for failure in reversed(failures):
        message = str(failure.get("message") or "")
        if "AgentRunWorkflow" in message and "not registered" in message:
            return "Temporal worker does not have AgentRunWorkflow registered. Restart the custom workflow worker with the latest code."
    return None


def _autopilot_worker_registration_failure(
    failures: list[dict[str, Any]],
) -> str | None:
    for failure in reversed(failures):
        message = str(failure.get("message") or "")
        if "AutoPilotWorkflow" in message and "not registered" in message:
            return (
                "Temporal worker does not have AutoPilotWorkflow registered on the "
                "browser workflow task queue. Restart the custom browser workflow worker "
                "with the latest code."
            )
    return None


def _test_run_worker_registration_failure(
    failures: list[dict[str, Any]],
) -> str | None:
    for failure in reversed(failures):
        message = str(failure.get("message") or "")
        if "TestRunWorkflow" in message and "not registered" in message:
            return (
                "Temporal worker does not have TestRunWorkflow registered on the "
                "browser workflow task queue. Restart the custom browser workflow worker "
                "with the latest code."
            )
    return None


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
        if (
            hasattr(value, "seconds")
            and hasattr(value, "nanos")
            and int(getattr(value, "seconds", 0) or 0) == 0
            and int(getattr(value, "nanos", 0) or 0) == 0
        ):
            return None
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
