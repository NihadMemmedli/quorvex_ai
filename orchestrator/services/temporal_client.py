"""Temporal client helpers for autonomous testing missions."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

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


async def signal_autonomous_mission_workflow(workflow_id: str, signal_name: str) -> None:
    """Signal a running autonomous mission workflow."""
    client = await _connect_client()
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(signal_name)
