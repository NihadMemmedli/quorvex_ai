#!/usr/bin/env python3
"""Temporal worker for custom workflow runs."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import AsyncExitStack
from concurrent.futures import ThreadPoolExecutor

from orchestrator.config import settings
from orchestrator.services import (
    agent_run_activities,
    custom_workflow_activities,
    domain_job_activities,
    test_run_activities,
)
from orchestrator.workflows.agent_run_workflow import AgentRunWorkflow
from orchestrator.workflows.autopilot_temporal import AutoPilotWorkflow
from orchestrator.workflows.custom_workflow_temporal import CustomWorkflowRun
from orchestrator.workflows.domain_job_workflow import DomainJobWorkflow
from orchestrator.workflows.test_run_workflow import TestRunWorkflow

logger = logging.getLogger("custom_workflow_worker")


def _activity(fn):
    from temporalio import activity

    return activity.defn(name=fn.__name__)(fn)


def mark_autopilot_temporal_started(payload):
    from orchestrator.services.autopilot_activities import mark_autopilot_temporal_started as fn

    return fn(payload)


async def execute_autopilot_pipeline(payload):
    from orchestrator.services.autopilot_activities import execute_autopilot_pipeline as fn

    return await fn(payload)


def set_autopilot_control_status(payload):
    from orchestrator.services.autopilot_activities import set_autopilot_control_status as fn

    return fn(payload)


def finalize_autopilot_workflow(payload):
    from orchestrator.services.autopilot_activities import finalize_autopilot_workflow as fn

    return fn(payload)


WORKFLOWS = [CustomWorkflowRun, AgentRunWorkflow, AutoPilotWorkflow, DomainJobWorkflow, TestRunWorkflow]
ACTIVITIES = [
    _activity(agent_run_activities.mark_agent_run_temporal_started),
    _activity(agent_run_activities.execute_agent_run),
    _activity(agent_run_activities.set_agent_run_control_status),
    _activity(agent_run_activities.finalize_agent_run_workflow),
    _activity(mark_autopilot_temporal_started),
    _activity(execute_autopilot_pipeline),
    _activity(set_autopilot_control_status),
    _activity(finalize_autopilot_workflow),
    _activity(domain_job_activities.execute_domain_job),
    _activity(test_run_activities.mark_test_run_temporal_started),
    _activity(test_run_activities.execute_test_run),
    _activity(test_run_activities.request_stop_test_run),
    _activity(test_run_activities.finalize_test_run_workflow),
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
    if "AutoPilotWorkflow" not in contract["workflows"]:
        missing.append("AutoPilotWorkflow")
    if "DomainJobWorkflow" not in contract["workflows"]:
        missing.append("DomainJobWorkflow")
    if "TestRunWorkflow" not in contract["workflows"]:
        missing.append("TestRunWorkflow")
    required_activities = {
        "mark_agent_run_temporal_started",
        "execute_agent_run",
        "set_agent_run_control_status",
        "finalize_agent_run_workflow",
        "mark_autopilot_temporal_started",
        "execute_autopilot_pipeline",
        "set_autopilot_control_status",
        "finalize_autopilot_workflow",
        "execute_domain_job",
        "mark_test_run_temporal_started",
        "execute_test_run",
        "request_stop_test_run",
        "finalize_test_run_workflow",
    }
    missing.extend(sorted(required_activities - set(contract["activities"])))
    if missing:
        raise RuntimeError(
            f"Custom workflow worker contract is incomplete: missing {', '.join(missing)}"
        )


def _configured_task_queues() -> list[str]:
    raw = os.environ.get("TEMPORAL_WORKFLOW_TASK_QUEUES", "").strip()
    if raw:
        queues = [queue.strip() for queue in raw.split(",") if queue.strip()]
    else:
        queues = [settings.temporal_workflow_task_queue]
    seen = set()
    return [queue for queue in queues if not (queue in seen or seen.add(queue))]


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
    task_queues = _configured_task_queues()
    with ThreadPoolExecutor(max_workers=8) as activity_executor:
        workers = [
            Worker(
                client,
                task_queue=task_queue,
                workflows=WORKFLOWS,
                activities=ACTIVITIES,
                activity_executor=activity_executor,
            )
            for task_queue in task_queues
        ]
        logger.info(
            "Starting custom workflow Temporal worker at %s namespace=%s task_queues=%s workflows=%s activities=%s",
            settings.temporal_address,
            settings.temporal_namespace,
            ",".join(task_queues),
            ",".join(contract["workflows"]),
            ",".join(contract["activities"]),
        )
        async with AsyncExitStack() as stack:
            for worker in workers:
                await stack.enter_async_context(worker)
            await stop_event.wait()


if __name__ == "__main__":
    asyncio.run(main())
