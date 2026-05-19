"""Temporal workflows for persistent autonomous testing missions."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow


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
        iterations_completed = 0
        latest_run_id: str | None = None

        while not self._cancelled:
            await workflow.wait_condition(lambda: not self._paused or self._cancelled)
            if self._cancelled:
                break

            mission = await workflow.execute_activity(
                "load_mission_policy",
                mission_id,
                start_to_close_timeout=timedelta(seconds=30),
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
                    {"mission_id": mission_id, "status": "paused"},
                    start_to_close_timeout=timedelta(seconds=30),
                )
                self._paused = True
                continue

            run_id = await workflow.execute_activity(
                "create_mission_run",
                {
                    "mission_id": mission_id,
                    "workflow_id": workflow.info().workflow_id,
                    "trigger_type": "temporal",
                },
                start_to_close_timeout=timedelta(seconds=30),
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
                )
                await workflow.execute_activity(
                    "complete_mission_run",
                    {"run_id": run_id, "summary": summary},
                    start_to_close_timeout=timedelta(seconds=30),
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
                )

            iterations_completed += 1
            max_iterations = int(mission.get("max_iterations") or 0)
            if max_iterations > 0 and iterations_completed >= max_iterations:
                await workflow.execute_activity(
                    "update_mission_status",
                    {"mission_id": mission_id, "status": "completed"},
                    start_to_close_timeout=timedelta(seconds=30),
                )
                break

            delay_seconds = await workflow.execute_activity(
                "compute_next_delay_seconds",
                mission_id,
                start_to_close_timeout=timedelta(seconds=30),
            )
            await workflow.sleep(timedelta(seconds=max(1, int(delay_seconds))))

        if self._cancelled:
            await workflow.execute_activity(
                "update_mission_status",
                {"mission_id": mission_id, "status": "cancelled"},
                start_to_close_timeout=timedelta(seconds=30),
            )

        return {
            "mission_id": mission_id,
            "iterations_completed": iterations_completed,
            "latest_run_id": latest_run_id,
            "cancelled": self._cancelled,
        }
