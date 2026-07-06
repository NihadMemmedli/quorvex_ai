"""Temporal workflow for durable classic test runs."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

CONTROL_ACTIVITY_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=3,
)

TEST_RUN_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=1)

DEFAULT_AI_PIPELINE_TIMEOUT_SECONDS = 7200
MIN_AI_PIPELINE_TIMEOUT_SECONDS = 900
MAX_AI_PIPELINE_TIMEOUT_SECONDS = 86400
DEFAULT_TEST_RUN_QUEUE_WAIT_TIMEOUT_SECONDS = 86400
MAX_TEST_RUN_ACTIVITY_TIMEOUT_SECONDS = 129600
TEST_RUN_CLEANUP_BUFFER_SECONDS = 1800


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _test_run_activity_timeout(payload: dict[str, Any]) -> timedelta:
    execution_timeout = _bounded_int(
        payload.get("ai_pipeline_timeout_seconds"),
        default=DEFAULT_AI_PIPELINE_TIMEOUT_SECONDS,
        minimum=MIN_AI_PIPELINE_TIMEOUT_SECONDS,
        maximum=MAX_AI_PIPELINE_TIMEOUT_SECONDS,
    )
    queue_timeout = _bounded_int(
        payload.get("browser_slot_wait_timeout_seconds"),
        default=max(DEFAULT_TEST_RUN_QUEUE_WAIT_TIMEOUT_SECONDS, execution_timeout),
        minimum=MIN_AI_PIPELINE_TIMEOUT_SECONDS,
        maximum=MAX_TEST_RUN_ACTIVITY_TIMEOUT_SECONDS,
    )
    seconds = min(
        MAX_TEST_RUN_ACTIVITY_TIMEOUT_SECONDS,
        queue_timeout + execution_timeout + TEST_RUN_CLEANUP_BUFFER_SECONDS,
    )
    return timedelta(seconds=seconds)


@workflow.defn(name="TestRunWorkflow")
class TestRunWorkflow:
    """Durable wrapper around the existing classic test-run executor."""

    def __init__(self) -> None:
        self._stop_requested = False
        self._stop_reason = "manual_stop"

    @workflow.signal
    async def stop(self, reason: str = "manual_stop") -> None:
        self._stop_requested = True
        self._stop_reason = reason

    @workflow.signal
    async def cancel(self, reason: str = "manual_cancel") -> None:
        self._stop_requested = True
        self._stop_reason = reason

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        run_id = str(payload["run_id"])
        info = workflow.info()
        started = await workflow.execute_activity(
            "mark_test_run_temporal_started",
            {
                **payload,
                "workflow_id": info.workflow_id,
                "temporal_run_id": getattr(info, "run_id", None),
            },
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=CONTROL_ACTIVITY_RETRY_POLICY,
        )
        if started.get("terminal"):
            return {"run_id": run_id, "status": started.get("status"), "action": "already_terminal"}

        execution = workflow.start_activity(
            "execute_test_run",
            payload,
            start_to_close_timeout=_test_run_activity_timeout(payload),
            retry_policy=TEST_RUN_ACTIVITY_RETRY_POLICY,
        )
        await workflow.wait_condition(lambda: self._stop_requested or execution.done())

        if self._stop_requested and not execution.done():
            await workflow.execute_activity(
                "request_stop_test_run",
                {**payload, "reason": self._stop_reason},
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=CONTROL_ACTIVITY_RETRY_POLICY,
            )

        result = await execution
        finalized = await workflow.execute_activity(
            "finalize_test_run_workflow",
            {"run_id": run_id, "result": result},
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=CONTROL_ACTIVITY_RETRY_POLICY,
        )
        return {
            "run_id": run_id,
            "status": finalized.get("status") or result.get("status"),
            "action": "stopped" if self._stop_requested else "completed",
        }
