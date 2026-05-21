#!/usr/bin/env python3
"""Temporal worker for custom workflow runs."""

from __future__ import annotations

import asyncio
import logging
import signal
from concurrent.futures import ThreadPoolExecutor

from orchestrator.config import settings
from orchestrator.services import custom_workflow_activities
from orchestrator.workflows.custom_workflow_temporal import CustomWorkflowRun

logger = logging.getLogger("custom_workflow_worker")


def _activity(fn):
    from temporalio import activity

    return activity.defn(name=fn.__name__)(fn)


async def main() -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    with ThreadPoolExecutor(max_workers=8) as activity_executor:
        worker = Worker(
            client,
            task_queue=settings.temporal_workflow_task_queue,
            workflows=[CustomWorkflowRun],
            activities=[
                _activity(custom_workflow_activities.execute_custom_workflow_run),
                _activity(custom_workflow_activities.mark_custom_workflow_started),
                _activity(custom_workflow_activities.prepare_custom_workflow_step),
                _activity(custom_workflow_activities.execute_custom_workflow_step),
                _activity(custom_workflow_activities.handle_custom_workflow_step_failure),
                _activity(custom_workflow_activities.set_custom_workflow_status),
            ],
            activity_executor=activity_executor,
        )
        logger.info(
            "Starting custom workflow Temporal worker at %s namespace=%s task_queue=%s",
            settings.temporal_address,
            settings.temporal_namespace,
            settings.temporal_workflow_task_queue,
        )
        async with worker:
            await stop_event.wait()


if __name__ == "__main__":
    asyncio.run(main())
