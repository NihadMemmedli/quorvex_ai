"""Temporal workflow for durable standalone agent runs."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

CONTROL_ACTIVITY_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
)

AGENT_ACTIVITY_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=10),
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
)


@workflow.defn(name="AgentRunWorkflow")
class AgentRunWorkflow:
    """Durable wrapper around a persisted AgentRun row."""

    def __init__(self) -> None:
        self._paused = False
        self._cancelled = False
        self._control_reason = "manual_control"

    @workflow.signal
    async def pause(self, reason: str = "manual_pause") -> None:
        self._paused = True
        self._control_reason = reason

    @workflow.signal
    async def resume(self) -> None:
        self._paused = False

    @workflow.signal
    async def cancel(self, reason: str = "manual_cancel") -> None:
        self._cancelled = True
        self._paused = False
        self._control_reason = reason

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        run_id = str(payload["run_id"])
        info = workflow.info()
        started = await workflow.execute_activity(
            "mark_agent_run_temporal_started",
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

        while self._paused and not self._cancelled:
            await workflow.execute_activity(
                "set_agent_run_control_status",
                {"run_id": run_id, "status": "paused", "reason": self._control_reason},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=CONTROL_ACTIVITY_RETRY_POLICY,
            )
            await workflow.wait_condition(lambda: not self._paused or self._cancelled)

        if self._cancelled:
            await workflow.execute_activity(
                "set_agent_run_control_status",
                {"run_id": run_id, "status": "cancelled", "reason": self._control_reason},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=CONTROL_ACTIVITY_RETRY_POLICY,
            )
            return {"run_id": run_id, "status": "cancelled", "action": "cancelled"}

        result = await workflow.execute_activity(
            "execute_agent_run",
            {"run_id": run_id},
            start_to_close_timeout=timedelta(hours=12),
            retry_policy=AGENT_ACTIVITY_RETRY_POLICY,
        )
        if self._cancelled:
            await workflow.execute_activity(
                "set_agent_run_control_status",
                {"run_id": run_id, "status": "cancelled", "reason": self._control_reason},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=CONTROL_ACTIVITY_RETRY_POLICY,
            )
            return {"run_id": run_id, "status": "cancelled", "action": "cancelled"}

        await workflow.execute_activity(
            "finalize_agent_run_workflow",
            {"run_id": run_id, "result": result},
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=CONTROL_ACTIVITY_RETRY_POLICY,
        )
        return {"run_id": run_id, "status": result.get("status"), "action": "completed"}
