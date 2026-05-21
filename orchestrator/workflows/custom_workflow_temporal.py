"""Temporal workflow for durable custom workflow runs."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

ACTIVITY_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
)

STEP_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=1)


@workflow.defn(name="CustomWorkflowRun")
class CustomWorkflowRun:
    """Durable wrapper around an existing persisted custom workflow run."""

    def __init__(self) -> None:
        self._cancelled = False
        self._paused = False
        self._pause_reason = "manual_pause"

    @workflow.signal
    async def pause(self, reason: str = "manual_pause") -> None:
        self._paused = True
        self._pause_reason = reason

    @workflow.signal
    async def resume(self) -> None:
        self._paused = False

    @workflow.signal
    async def cancel(self, reason: str = "manual_cancel") -> None:
        self._cancelled = True
        self._paused = False
        self._pause_reason = reason

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        run_id = payload["run_id"]
        info = workflow.info()
        await workflow.execute_activity(
            "mark_custom_workflow_started",
            {
                **payload,
                "workflow_id": info.workflow_id,
                "temporal_run_id": getattr(info, "run_id", None),
            },
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=ACTIVITY_RETRY_POLICY,
        )

        while True:
            while self._paused and not self._cancelled:
                await workflow.execute_activity(
                    "set_custom_workflow_status",
                    {"run_id": run_id, "status": "paused", "reason": self._pause_reason},
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
                await workflow.wait_condition(lambda: not self._paused or self._cancelled)

            if self._cancelled:
                await workflow.execute_activity(
                    "set_custom_workflow_status",
                    {"run_id": run_id, "status": "cancelled", "reason": self._pause_reason},
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
                return {"run_id": run_id, "status": "cancelled"}

            prepared = await workflow.execute_activity(
                "prepare_custom_workflow_step",
                {"run_id": run_id},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            action = prepared.get("action")
            if action == "paused":
                self._paused = True
                self._pause_reason = prepared.get("pause_reason") or self._pause_reason
                continue
            if action != "execute":
                return {"run_id": run_id, "status": prepared.get("status"), "action": action}

            step_result = await workflow.execute_activity(
                "execute_custom_workflow_step",
                {"run_id": run_id, "step_id": prepared.get("step_id")},
                start_to_close_timeout=timedelta(hours=12),
                retry_policy=STEP_ACTIVITY_RETRY_POLICY,
            )
            if step_result.get("action") == "completed":
                if step_result.get("status") in {"awaiting_input", "completed", "failed", "cancelled"}:
                    continue
                continue
            if step_result.get("action") == "paused":
                self._paused = True
                self._pause_reason = step_result.get("error_message") or self._pause_reason
                continue
            if step_result.get("action") == "cancelled":
                return {"run_id": run_id, "status": step_result.get("status"), "action": step_result.get("action")}

            recovery = await workflow.execute_activity(
                "handle_custom_workflow_step_failure",
                {
                    "run_id": run_id,
                    "step_id": prepared.get("step_id"),
                    "error_message": step_result.get("error_message") or "Workflow step failed",
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            if recovery.get("action") == "retry":
                backoff_seconds = int(recovery.get("backoff_seconds") or 0)
                if backoff_seconds > 0:
                    await workflow.sleep(timedelta(seconds=backoff_seconds))
                continue
            if recovery.get("action") == "continue":
                continue
            return {"run_id": run_id, "status": recovery.get("status"), "action": recovery.get("action")}
