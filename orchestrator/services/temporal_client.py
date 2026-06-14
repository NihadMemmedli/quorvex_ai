"""Temporal client helpers for autonomous testing missions."""

from __future__ import annotations

import logging
import re
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


def _temporal_memo(**values: Any) -> dict[str, Any]:
    """Build a small, safe memo payload visible in Temporal UI."""
    memo: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            text = value if not isinstance(value, str) else value.strip()
            if text != "":
                memo[key] = text
        elif isinstance(value, (list, tuple)):
            compact = [item for item in value if isinstance(item, (str, int, float, bool))]
            if compact:
                memo[key] = compact[:10]
    return memo


def _custom_workflow_run_memo(run_id: str) -> dict[str, Any]:
    memo = _temporal_memo(entity_type="custom_workflow", run_id=run_id)
    try:
        from sqlmodel import Session

        from orchestrator.api.db import engine
        from orchestrator.api.models_db import WorkflowDefinition, WorkflowRun

        with Session(engine) as session:
            run = session.get(WorkflowRun, run_id)
            definition = session.get(WorkflowDefinition, run.definition_id) if run else None
            return {
                **memo,
                **_temporal_memo(
                    project_id=getattr(run, "project_id", None),
                    definition_id=getattr(run, "definition_id", None),
                    definition_name=getattr(definition, "name", None),
                    trigger_type=getattr(run, "trigger_type", None),
                ),
            }
    except Exception:
        return memo


def _agent_run_memo(run_id: str, *, task_queue: str) -> dict[str, Any]:
    memo = _temporal_memo(entity_type="agent_run", run_id=run_id, task_queue=task_queue)
    try:
        from sqlmodel import Session

        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AgentRun

        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            config = run.config if run else {}
            return {
                **memo,
                **_temporal_memo(
                    project_id=getattr(run, "project_id", None),
                    agent_type=getattr(run, "agent_type", None),
                    runtime=getattr(run, "runtime", None),
                    name=config.get("name") or config.get("title") or config.get("task"),
                ),
            }
    except Exception:
        return memo


def _test_run_memo(run_id: str, payload: dict[str, Any], *, task_queue: str) -> dict[str, Any]:
    memo = _temporal_memo(entity_type="test_run", run_id=run_id, task_queue=task_queue)
    try:
        from sqlmodel import Session

        from orchestrator.api.db import engine
        from orchestrator.api.models_db import TestRun

        with Session(engine) as session:
            run = session.get(TestRun, run_id)
            return {
                **memo,
                **_temporal_memo(
                    project_id=getattr(run, "project_id", None) or payload.get("project_id"),
                    spec_name=getattr(run, "spec_name", None) or payload.get("spec_name"),
                    test_name=getattr(run, "test_name", None) or payload.get("test_name"),
                    browser=getattr(run, "browser", None) or payload.get("browser"),
                ),
            }
    except Exception:
        return {**memo, **_temporal_memo(project_id=payload.get("project_id"), spec_name=payload.get("spec_name"))}


def _autopilot_memo(session_id: str, *, task_queue: str) -> dict[str, Any]:
    memo = _temporal_memo(entity_type="autopilot", session_id=session_id, task_queue=task_queue)
    try:
        from sqlmodel import Session

        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AutoPilotSession

        with Session(engine) as session:
            autopilot = session.get(AutoPilotSession, session_id)
            return {
                **memo,
                **_temporal_memo(
                    project_id=getattr(autopilot, "project_id", None),
                    current_phase=getattr(autopilot, "current_phase", None),
                ),
            }
    except Exception:
        return memo


def _domain_job_memo(job_type: str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    memo = _temporal_memo(entity_type="domain_job", job_type=job_type, job_id=job_id)
    try:
        from sqlmodel import Session

        from orchestrator.api.db import engine
        from orchestrator.api.models_db import DomainJob

        with Session(engine) as session:
            job = session.get(DomainJob, job_id)
            return {
                **memo,
                **_temporal_memo(
                    project_id=getattr(job, "project_id", None) or payload.get("project_id"),
                    task_queue=settings.temporal_workflow_task_queue,
                ),
            }
    except Exception:
        return {**memo, **_temporal_memo(project_id=payload.get("project_id"))}


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
        memo=_temporal_memo(entity_type="autonomous_mission", mission_id=mission_id),
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
        memo=_custom_workflow_run_memo(run_id),
    )
    logger.info("Started custom workflow Temporal run %s for %s", workflow_id, run_id)
    return TemporalWorkflowStart(
        workflow_id=workflow_id, run_id=getattr(handle, "first_execution_run_id", None)
    )


async def start_agent_run_workflow(
    run_id: str,
    *,
    task_queue: str | None = None,
    attempt: int | None = None,
) -> TemporalWorkflowStart:
    """Start a durable Temporal workflow for a standalone agent run."""
    client = await _connect_client()
    workflow_id = f"agent-run-{run_id}-attempt-{attempt}" if attempt else f"agent-run-{run_id}"
    selected_task_queue = task_queue or settings.temporal_workflow_task_queue
    handle = await client.start_workflow(
        "AgentRunWorkflow",
        {"run_id": run_id},
        id=workflow_id,
        task_queue=selected_task_queue,
        memo=_agent_run_memo(run_id, task_queue=selected_task_queue),
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
        memo=_test_run_memo(run_id, payload, task_queue=selected_task_queue),
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
        memo=_autopilot_memo(session_id, task_queue=selected_task_queue),
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
        memo=_domain_job_memo(job_type, job_id, payload),
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


async def check_autonomous_mission_temporal_health() -> dict[str, Any]:
    """Return Temporal readiness for autonomous mission workflows and activities."""
    worker_contract: dict[str, Any] = {}
    try:
        from orchestrator.services.autonomous_mission_worker import get_worker_contract

        worker_contract = get_worker_contract()
    except Exception as exc:
        worker_contract = {"contract_error": str(exc)}

    task_queue = settings.temporal_task_queue
    base = {
        "address": settings.temporal_address,
        "namespace": settings.temporal_namespace,
        "task_queue": task_queue,
        "workflow_type": "AutonomousMissionWorkflow",
        "worker_module": "orchestrator.services.autonomous_mission_worker",
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
        "error": None
        if has_workers
        else (
            "No Temporal worker pollers are active for autonomous missions. "
            f"Start orchestrator.services.autonomous_mission_worker on task queue {task_queue}."
        ),
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
    product_run_id = _custom_workflow_product_run_id(workflow_id)
    timeline = _build_custom_workflow_temporal_timeline(
        activities,
        _custom_workflow_step_context(product_run_id) if product_run_id else {},
        run_id=product_run_id,
    )
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
        "timeline": timeline,
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


def _custom_workflow_product_run_id(workflow_id: str) -> str | None:
    prefix = "custom-workflow-run-"
    return workflow_id[len(prefix):] if workflow_id.startswith(prefix) else None


def _parse_custom_workflow_step_activity_id(
    activity_id: str | None,
    *,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    if not activity_id:
        return None
    if run_id:
        prefix = f"custom-workflow-step-{run_id}-"
        if not activity_id.startswith(prefix):
            return None
        rest = activity_id[len(prefix):]
    else:
        match = re.match(r"^custom-workflow-step-(.+)$", activity_id)
        if not match:
            return None
        rest = match.group(1)
    match = re.match(r"^(\d+)-(.+)-(\d+)-attempt-(\d+)$", rest)
    if not match:
        return None
    return {
        "step_order": int(match.group(1)),
        "step_key": match.group(2),
        "step_id": int(match.group(3)),
        "attempt": int(match.group(4)),
    }


def _custom_workflow_step_context(run_id: str) -> dict[int, dict[str, Any]]:
    try:
        from sqlmodel import Session, select

        from orchestrator.api.db import engine
        from orchestrator.api.models_db import WorkflowRunStep

        with Session(engine) as session:
            steps = session.exec(
                select(WorkflowRunStep)
                .where(WorkflowRunStep.run_id == run_id)
                .order_by(WorkflowRunStep.step_order)
            ).all()
            return {
                int(step.id): {
                    "step_id": step.id,
                    "step_key": step.step_key,
                    "step_order": step.step_order,
                    "step_label": step.label,
                    "step_type": step.step_type,
                    "step_status": step.status,
                    "error_message": step.error_message,
                }
                for step in steps
                if step.id is not None
            }
    except Exception:
        return {}


def _build_custom_workflow_temporal_timeline(
    activities: list[dict[str, Any]],
    step_context: dict[int, dict[str, Any]],
    *,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    for activity in activities:
        activity_type = str(activity.get("activity_type") or "")
        if activity_type != "execute_custom_workflow_step":
            timeline.append(_activity_timeline_item(activity, None, None))
            continue
        parsed = _parse_custom_workflow_step_activity_id(str(activity.get("activity_id") or ""), run_id=run_id)
        step = step_context.get(int(parsed["step_id"])) if parsed else None
        timeline.append(_activity_timeline_item(activity, parsed, step))
    return timeline


def _activity_timeline_item(
    activity: dict[str, Any],
    parsed: dict[str, Any] | None,
    step: dict[str, Any] | None,
) -> dict[str, Any]:
    status = str(activity.get("status") or "unknown")
    step_label = (
        (step or {}).get("step_label")
        or (step or {}).get("step_key")
        or (parsed or {}).get("step_key")
        or _activity_label(str(activity.get("activity_type") or activity.get("activity_id") or "activity"))
    )
    step_order = (step or {}).get("step_order")
    if step_order is None and parsed:
        step_order = parsed.get("step_order")
    display_order = int(step_order) + 1 if step_order is not None else None
    title = f"Step {display_order}: {step_label}" if display_order is not None else str(step_label)
    duration_seconds = _duration_seconds(activity.get("started_at") or activity.get("scheduled_at"), activity.get("completed_at"))
    attempt = (parsed or {}).get("attempt") or activity.get("attempt_count")
    failure_summary = activity.get("failure_message") or activity.get("last_failure")
    message = _timeline_message(status, attempt, duration_seconds, failure_summary)
    return {
        "title": title,
        "message": message,
        "status": status,
        "step_label": step_label,
        "step_key": (step or {}).get("step_key") or (parsed or {}).get("step_key"),
        "step_type": (step or {}).get("step_type") or activity.get("activity_type"),
        "step_id": (step or {}).get("step_id") or (parsed or {}).get("step_id"),
        "step_order": step_order,
        "attempt": attempt,
        "duration_seconds": duration_seconds,
        "started_at": activity.get("started_at"),
        "completed_at": activity.get("completed_at"),
        "scheduled_at": activity.get("scheduled_at"),
        "failure_summary": failure_summary,
        "raw_activity_id": activity.get("activity_id"),
        "last_event_type": activity.get("last_event_type"),
        "worker_identity": activity.get("last_worker_identity"),
    }


def _timeline_message(
    status: str,
    attempt: Any,
    duration_seconds: int | None,
    failure_summary: Any,
) -> str:
    attempt_text = f"Attempt {attempt}" if attempt else "Activity"
    duration_text = f" after {duration_seconds}s" if duration_seconds is not None else ""
    if status == "completed":
        return f"{attempt_text} completed{duration_text}."
    if status in {"failed", "timed_out"}:
        suffix = f": {failure_summary}" if failure_summary else "."
        return f"{attempt_text} {status.replace('_', ' ')}{duration_text}{suffix}"
    if status == "started":
        return f"{attempt_text} is running."
    if status == "scheduled":
        return f"{attempt_text} is scheduled."
    return f"{attempt_text} status is {status.replace('_', ' ')}."


def _duration_seconds(started_at: Any, completed_at: Any) -> int | None:
    if not started_at or not completed_at:
        return None
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
        return max(0, int((end - start).total_seconds()))
    except Exception:
        return None


def _activity_label(value: str) -> str:
    label = value.replace("_", " ").replace("-", " ").strip()
    return label[:1].upper() + label[1:] if label else "Temporal activity"


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
