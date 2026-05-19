#!/usr/bin/env python3
"""Temporal worker for autonomous testing missions."""

from __future__ import annotations

import asyncio
import logging
import signal
from concurrent.futures import ThreadPoolExecutor

from orchestrator.config import settings
from orchestrator.services import autonomous_activities
from orchestrator.workflows.autonomous_mission_workflow import AutonomousMissionWorkflow

logger = logging.getLogger("autonomous_mission_worker")


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
            task_queue=settings.temporal_task_queue,
            workflows=[AutonomousMissionWorkflow],
            activities=[
                _activity(autonomous_activities.load_mission_policy),
                _activity(autonomous_activities.create_mission_run),
                _activity(autonomous_activities.execute_mission_iteration),
                _activity(autonomous_activities.complete_mission_run),
                _activity(autonomous_activities.fail_mission_run),
                _activity(autonomous_activities.update_mission_status),
                _activity(autonomous_activities.compute_next_delay_seconds),
            ],
            activity_executor=activity_executor,
        )

        logger.info(
            "Starting autonomous mission Temporal worker at %s namespace=%s task_queue=%s",
            settings.temporal_address,
            settings.temporal_namespace,
            settings.temporal_task_queue,
        )
        async with worker:
            await stop_event.wait()


if __name__ == "__main__":
    asyncio.run(main())
