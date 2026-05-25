#!/usr/bin/env python3
"""Temporal worker for custom workflow runs."""

from __future__ import annotations

import asyncio
import logging
import signal
from concurrent.futures import ThreadPoolExecutor

from orchestrator.config import settings
from orchestrator.services import agent_run_activities
from orchestrator.services import custom_workflow_activities
from orchestrator.services import domain_job_activities
from orchestrator.workflows.agent_run_workflow import AgentRunWorkflow
from orchestrator.workflows.custom_workflow_temporal import CustomWorkflowRun
from orchestrator.workflows.domain_job_workflow import DomainJobWorkflow

logger = logging.getLogger("custom_workflow_worker")


def _activity(fn):
    from temporalio import activity

    return activity.defn(name=fn.__name__)(fn)


WORKFLOWS = [CustomWorkflowRun, AgentRunWorkflow, DomainJobWorkflow]
ACTIVITIES = [
    _activity(agent_run_activities.mark_agent_run_temporal_started),
    _activity(agent_run_activities.execute_agent_run),
    _activity(agent_run_activities.set_agent_run_control_status),
    _activity(agent_run_activities.finalize_agent_run_workflow),
    _activity(domain_job_activities.execute_domain_job),
    _activity(custom_workflow_activities.mark_custom_workflow_started),
    _activity(custom_workflow_activities.prepare_custom_workflow_step),
    _activity(custom_workflow_activities.execute_custom_workflow_step),
    _activity(custom_workflow_activities.handle_custom_workflow_step_failure),
    _activity(custom_workflow_activities.set_custom_workflow_status),
]


def get_worker_contract() -> dict[str, list[str]]:
    """Return the workflow/activity contract this worker is expected to serve."""
    return {
        "workflows": [workflow.__name__ for workflow in WORKFLOWS],
        "activities": [
            getattr(activity, "__name__", str(activity)) for activity in ACTIVITIES
        ],
        "capabilities": ["direct_agent_execution"],
    }


def _validate_worker_contract() -> None:
    contract = get_worker_contract()
    missing = []
    if "AgentRunWorkflow" not in contract["workflows"]:
        missing.append("AgentRunWorkflow")
    if "DomainJobWorkflow" not in contract["workflows"]:
        missing.append("DomainJobWorkflow")
    required_activities = {
        "mark_agent_run_temporal_started",
        "execute_agent_run",
        "set_agent_run_control_status",
        "finalize_agent_run_workflow",
        "execute_domain_job",
    }
    missing.extend(sorted(required_activities - set(contract["activities"])))
    if missing:
        raise RuntimeError(
            f"Custom workflow worker contract is incomplete: missing {', '.join(missing)}"
        )


async def main() -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    client = await Client.connect(
        settings.temporal_address, namespace=settings.temporal_namespace
    )
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    _validate_worker_contract()
    contract = get_worker_contract()
    with ThreadPoolExecutor(max_workers=8) as activity_executor:
        worker = Worker(
            client,
            task_queue=settings.temporal_workflow_task_queue,
            workflows=WORKFLOWS,
            activities=ACTIVITIES,
            activity_executor=activity_executor,
        )
        logger.info(
            "Starting custom workflow Temporal worker at %s namespace=%s task_queue=%s workflows=%s activities=%s",
            settings.temporal_address,
            settings.temporal_namespace,
            settings.temporal_workflow_task_queue,
            ",".join(contract["workflows"]),
            ",".join(contract["activities"]),
        )
        async with worker:
            await stop_event.wait()


if __name__ == "__main__":
    asyncio.run(main())
