"""Temporal workflows for persistent autonomous testing missions."""

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
CONTINUE_AS_NEW_EVERY = 100


@workflow.defn(name="AutonomousMissionWorkflow")
class AutonomousMissionWorkflow:
    """Long-lived mission workflow that launches bounded testing iterations."""

    def __init__(self) -> None:
        self._paused = False
        self._cancelled = False

    @workflow.signal
    async def pause(self) -> None:
        self._paused = True

    @workflow.signal
    async def resume(self) -> None:
        self._paused = False

    @workflow.signal
    async def cancel(self) -> None:
        self._cancelled = True
        self._paused = False

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        mission_id = payload["mission_id"]
        iterations_completed = int(payload.get("iterations_completed", 0))
        iterations_since_continue = int(payload.get("iterations_since_continue", 0))
        latest_run_id: str | None = None

        while not self._cancelled:
            await workflow.execute_activity(
                "update_mission_heartbeat",
                {
                    "mission_id": mission_id,
                    "current_stage": "waiting",
                    "health_status": "healthy",
                    "next_action": "Waiting for the next mission iteration.",
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            await workflow.wait_condition(lambda: not self._paused or self._cancelled)
            if self._cancelled:
                break

            mission = await workflow.execute_activity(
                "load_mission_policy",
                mission_id,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            if mission.get("status") in {"cancelled", "completed"}:
                break
            if mission.get("status") == "paused":
                self._paused = True
                continue
            if mission.get("max_llm_budget_usd") is not None and mission.get("budget_used_usd", 0) >= mission[
                "max_llm_budget_usd"
            ]:
                await workflow.execute_activity(
                    "update_mission_status",
                    {
                        "mission_id": mission_id,
                        "status": "paused",
                        "health_status": "blocked",
                        "paused_reason": "llm_budget_exhausted",
                        "current_stage": "paused",
                        "next_action": "Increase the LLM budget or lower mission scope before resuming.",
                    },
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
                self._paused = True
                continue

            pending_approvals = await workflow.execute_activity(
                "count_pending_mission_approvals",
                mission_id,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            max_pending_approvals = int((mission.get("config") or {}).get("max_pending_approvals") or 25)
            if pending_approvals >= max(1, max_pending_approvals):
                await workflow.execute_activity(
                    "update_mission_status",
                    {
                        "mission_id": mission_id,
                        "status": "paused",
                        "health_status": "blocked",
                        "paused_reason": "pending_approval_limit",
                        "current_stage": "paused",
                        "next_action": "Review pending approvals before resuming the mission.",
                    },
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
                self._paused = True
                continue

            run_id = await workflow.execute_activity(
                "create_mission_run",
                {
                    "mission_id": mission_id,
                    "workflow_id": workflow.info().workflow_id,
                    "trigger_type": "temporal",
                    "iteration_index": iterations_completed + 1,
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            latest_run_id = run_id

            try:
                summary = await workflow.execute_activity(
                    "execute_mission_iteration",
                    {
                        "mission_id": mission_id,
                        "run_id": run_id,
                        "workflow_id": workflow.info().workflow_id,
                    },
                    start_to_close_timeout=timedelta(minutes=max(1, int(mission.get("max_runtime_minutes") or 60))),
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
                await workflow.execute_activity(
                    "complete_mission_run",
                    {"run_id": run_id, "summary": summary},
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
            except Exception as exc:
                await workflow.execute_activity(
                    "fail_mission_run",
                    {
                        "mission_id": mission_id,
                        "run_id": run_id,
                        "error": str(exc),
                    },
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )

            iterations_completed += 1
            iterations_since_continue += 1
            max_iterations = int(mission.get("max_iterations") or 0)
            total_runs = int(mission.get("total_runs") or 0) + 1
            if max_iterations > 0 and total_runs >= max_iterations:
                await workflow.execute_activity(
                    "update_mission_status",
                    {
                        "mission_id": mission_id,
                        "status": "completed",
                        "health_status": "blocked",
                        "current_stage": "completed",
                        "next_action": None,
                    },
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )
                break

            delay_seconds = await workflow.execute_activity(
                "compute_next_delay_seconds",
                mission_id,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            if iterations_since_continue >= CONTINUE_AS_NEW_EVERY:
                workflow.continue_as_new(
                    {
                        "mission_id": mission_id,
                        "iterations_completed": iterations_completed,
                        "iterations_since_continue": 0,
                    }
                )
            await workflow.sleep(timedelta(seconds=max(1, int(delay_seconds))))

        if self._cancelled:
            await workflow.execute_activity(
                "update_mission_status",
                {
                    "mission_id": mission_id,
                    "status": "cancelled",
                    "health_status": "blocked",
                    "paused_reason": "cancelled",
                    "current_stage": "cancelled",
                    "next_action": None,
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=ACTIVITY_RETRY_POLICY,
            )

        return {
            "mission_id": mission_id,
            "iterations_completed": iterations_completed,
            "latest_run_id": latest_run_id,
            "cancelled": self._cancelled,
        }
