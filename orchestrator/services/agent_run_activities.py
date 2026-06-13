"""Temporal activities for durable standalone agent runs."""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlmodel import Session

from orchestrator.api.db import engine
from orchestrator.api.models_db import AgentRun
from orchestrator.services.agent_run_events import create_agent_run_event

PARTIAL_STATUS = "completed_partial"
TERMINAL_STATUSES = {"completed", PARTIAL_STATUS, "failed", "cancelled", "timeout"}


def _short_tool_name(tool_name: str | None) -> str:
    if not tool_name:
        return ""
    return str(tool_name).rsplit("__", 1)[-1] if "__" in str(tool_name) else str(tool_name)


def _coerce_progress_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_progress(progress: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(progress or {})
    for key in ("tool_calls", "browser_tool_calls", "interactions"):
        if key in normalized:
            normalized[key] = _coerce_progress_int(normalized.get(key))

    last_tool = normalized.get("last_tool") or normalized.get("current_tool")
    if last_tool:
        normalized["last_tool"] = str(last_tool)
        normalized["current_tool"] = str(last_tool)

    label = normalized.get("last_tool_label") or normalized.get("current_tool_label")
    if not label and last_tool:
        label = _short_tool_name(str(last_tool))
    if label:
        normalized["last_tool_label"] = str(label)
        normalized["current_tool_label"] = str(label)

    return normalized


def _persist_agent_run_progress(run_id: str, agent_task_id: str, patch: dict[str, Any]) -> None:
    if not patch:
        return
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if not run or run.status in TERMINAL_STATUSES:
            return

        progress_patch = dict(patch)
        last_tool = progress_patch.get("last_tool") or progress_patch.get("current_tool")
        if not last_tool:
            progress_patch.pop("last_tool", None)
            progress_patch.pop("current_tool", None)
            last_tool = (run.progress or {}).get("last_tool") or (run.progress or {}).get("current_tool")

        existing = run.progress or {}
        recent_tools = list(existing.get("recent_tools") or [])
        if last_tool and (not recent_tools or recent_tools[-1].get("name") != last_tool):
            recent_tools.append(
                {
                    "name": str(last_tool),
                    "label": _short_tool_name(str(last_tool)),
                    "at": datetime.utcnow().isoformat(),
                }
            )
            recent_tools = recent_tools[-12:]

        run.progress = _normalize_progress(
            {
                **existing,
                **progress_patch,
                "agent_task_id": agent_task_id,
                "recent_tools": recent_tools,
                "updated_at": datetime.utcnow().isoformat(),
            }
        )
        run.agent_task_id = agent_task_id
        session.add(run)
        session.commit()


@contextmanager
def _temporal_agent_execution_env():
    """Run agent work inside the Temporal activity instead of Redis queue workers."""
    previous = os.environ.get("USE_AGENT_QUEUE")
    previous_temporal = os.environ.get("QUORVEX_AGENT_TEMPORAL_ACTIVITY")
    os.environ["USE_AGENT_QUEUE"] = "false"
    os.environ["QUORVEX_AGENT_TEMPORAL_ACTIVITY"] = "true"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("USE_AGENT_QUEUE", None)
        else:
            os.environ["USE_AGENT_QUEUE"] = previous
        if previous_temporal is None:
            os.environ.pop("QUORVEX_AGENT_TEMPORAL_ACTIVITY", None)
        else:
            os.environ["QUORVEX_AGENT_TEMPORAL_ACTIVITY"] = previous_temporal


def _run_payload(run: AgentRun | None) -> dict[str, Any]:
    if not run:
        return {"status": "missing", "terminal": True, "error_message": "Agent run disappeared"}
    return {
        "run_id": run.id,
        "status": run.status,
        "terminal": run.status in TERMINAL_STATUSES,
        "agent_task_id": run.agent_task_id,
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
    }


def mark_agent_run_temporal_started(payload: dict[str, Any]) -> dict[str, Any]:
    """Record Temporal metadata for a durable standalone agent run."""
    run_id = str(payload["run_id"])
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if not run:
            return {"run_id": run_id, "status": "missing", "terminal": True, "error_message": "Agent run disappeared"}
        run.temporal_workflow_id = payload.get("workflow_id") or run.temporal_workflow_id
        run.temporal_run_id = payload.get("temporal_run_id") or run.temporal_run_id
        run.started_at = run.started_at or datetime.utcnow()
        if run.status not in TERMINAL_STATUSES and run.status != "paused":
            run.status = "running"
        run.progress = {
            **(run.progress or {}),
            "phase": run.status,
            "status": run.status,
            "message": "Agent run is managed by Temporal.",
            "updated_at": datetime.utcnow().isoformat(),
        }
        session.add(run)
        session.commit()
        create_agent_run_event(
            run_id=run.id,
            event_type="temporal_started",
            message="Agent Temporal workflow started.",
            payload={
                "workflow_id": run.temporal_workflow_id,
                "temporal_run_id": run.temporal_run_id,
                "status": run.status,
            },
            session=session,
        )
        return _run_payload(run)


async def execute_agent_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute or reattach to the Redis-backed agent task for one AgentRun."""
    run_id = str(payload["run_id"])
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if not run:
            return {"run_id": run_id, "status": "missing", "terminal": True, "error_message": "Agent run disappeared"}
        if run.status in TERMINAL_STATUSES:
            return _run_payload(run)
        agent_type = run.agent_type
        config = run.config
        agent_task_id = run.agent_task_id

    if agent_type == "__temporal_smoke__" and config.get("temporal_smoke") is True:
        return _complete_smoke_agent_run(run_id)

    if agent_task_id:
        return await _reattach_agent_task(run_id, agent_task_id)

    from orchestrator.api.main import execute_agent_background

    with _temporal_agent_execution_env():
        try:
            await execute_agent_background(run_id, agent_type, config)
        except asyncio.CancelledError:
            with Session(engine) as session:
                run = session.get(AgentRun, run_id)
                if run and run.status not in TERMINAL_STATUSES:
                    run.status = "cancelled"
                    run.completed_at = datetime.utcnow()
                    run.progress = {
                        **(run.progress or {}),
                        "phase": "cancelled",
                        "status": "cancelled",
                        "message": "Agent run cancelled.",
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    session.add(run)
                    session.commit()
                    create_agent_run_event(
                        run_id=run.id,
                        agent_task_id=run.agent_task_id,
                        event_type="cancel",
                        message="Agent activity cancelled.",
                        payload={"status": run.status},
                        session=session,
                    )
                return _run_payload(run)
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        return _run_payload(run)


def _complete_smoke_agent_run(run_id: str) -> dict[str, Any]:
    """Complete a deterministic no-op run used by Temporal smoke tests."""
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if run and run.status not in TERMINAL_STATUSES:
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            run.result = {"summary": "Temporal smoke agent run completed.", "smoke": True}
            run.progress = {
                **(run.progress or {}),
                "phase": "completed",
                "status": "completed",
                "message": "Temporal smoke agent run completed.",
                "updated_at": datetime.utcnow().isoformat(),
            }
            session.add(run)
            session.commit()
            create_agent_run_event(
                run_id=run.id,
                event_type="complete",
                message="Temporal smoke agent run completed.",
                payload={"smoke": True},
                session=session,
            )
        return _run_payload(run)


async def _reattach_agent_task(run_id: str, agent_task_id: str) -> dict[str, Any]:
    """Wait for an existing queued task instead of enqueueing a duplicate."""
    from orchestrator.services.agent_queue import get_agent_queue

    queue = get_agent_queue()
    await queue.connect()

    def _on_progress(progress: dict[str, Any]) -> None:
        _persist_agent_run_progress(run_id, agent_task_id, progress)

    try:
        result_text = await queue.wait_for_result(
            agent_task_id,
            timeout=12 * 60 * 60,
            poll_interval=1.0,
            on_progress=_on_progress,
        )
        final_task = await queue.get_task(agent_task_id)
    except Exception as exc:
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            if run and run.status not in TERMINAL_STATUSES:
                recovered = None
                if run.agent_type == "exploratory":
                    try:
                        from orchestrator.api.main import (
                            _exploratory_result_has_usable_evidence,
                            _merge_agent_failure_into_result,
                            _recover_exploratory_partial_result,
                        )

                        if _exploratory_result_has_usable_evidence(run.result):
                            recovered = _merge_agent_failure_into_result(
                                run.result,
                                exc,
                                failure_reason="reattach_failed_after_evidence",
                            )
                        else:
                            recovered = _recover_exploratory_partial_result(run_id, run.config, exc)
                    except Exception:
                        recovered = None
                if recovered is not None:
                    run.status = PARTIAL_STATUS
                    run.completed_at = datetime.utcnow()
                    run.result = recovered
                    run.progress = {
                        **(run.progress or {}),
                        "phase": PARTIAL_STATUS,
                        "status": PARTIAL_STATUS,
                        "message": recovered.get("summary") or "Recovered partial Explorer evidence after task reattach failed.",
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    event_type = "partial"
                    event_level = "warning"
                    event_message = "Agent task reattach failed, but partial Explorer evidence was recovered."
                    payload = {"error": str(exc), "status": run.status, "failure_reason": recovered.get("failure_reason")}
                else:
                    run.progress = {
                        **(run.progress or {}),
                        "phase": "retrying",
                        "status": run.status,
                        "message": f"Agent task reattach failed and will be retried by Temporal: {exc}",
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    event_type = "retry"
                    event_level = "warning"
                    event_message = f"Agent task reattach failed; Temporal will retry if attempts remain: {exc}"
                    payload = {"error": str(exc), "status": run.status, "retryable": True}
                session.add(run)
                session.commit()
                create_agent_run_event(
                    run_id=run.id,
                    agent_task_id=agent_task_id,
                    event_type=event_type,
                    level=event_level,
                    message=event_message,
                    payload=payload,
                    session=session,
                )
                if recovered is None:
                    raise
            return _run_payload(run)

    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if run and run.status not in TERMINAL_STATUSES:
            task_telemetry = getattr(final_task, "telemetry", {}) if final_task is not None else {}
            tool_calls = []
            if isinstance(task_telemetry, dict):
                for key in ("tool_calls", "tool_call_records"):
                    value = task_telemetry.get(key)
                    if isinstance(value, list):
                        tool_calls = value
                        break
            try:
                from orchestrator.services.agent_run_finalizer import AgentRunFinalizer

                finalized = AgentRunFinalizer().finalize(
                    run_id=run_id,
                    agent_type=run.agent_type,
                    config=run.config,
                    raw_model_output=result_text or "",
                    tool_calls=tool_calls,
                    runtime_diagnostics={
                        "source": "temporal_reattach",
                        "agent_task_id": agent_task_id,
                        "task_telemetry": task_telemetry if isinstance(task_telemetry, dict) else {},
                    },
                )
                run.status = finalized.status
                run.result = finalized.result
            except Exception as finalizer_error:
                run.status = PARTIAL_STATUS if result_text else "failed"
                run.result = {
                    "summary": (result_text or str(finalizer_error))[:500],
                    "output": result_text or "",
                    "contract_status": "partial" if result_text else "invalid",
                    "repair_attempts": [
                        {
                            "attempt": 0,
                            "strategy": "agent_run_finalizer",
                            "status": "failed",
                            "error": str(finalizer_error),
                        }
                    ],
                    "contract_warnings": ["Agent output finalization failed."],
                    "diagnostics": {
                        "finalizer": {
                            "source": "temporal_reattach",
                            "agent_task_id": agent_task_id,
                            "error": str(finalizer_error),
                        }
                    },
                }
            run.completed_at = datetime.utcnow()
            run.progress = {
                **(run.progress or {}),
                "phase": run.status,
                "status": run.status,
                "message": (run.result or {}).get("summary") or "Agent task completed after Temporal reattach.",
                "updated_at": datetime.utcnow().isoformat(),
            }
            session.add(run)
            session.commit()
            create_agent_run_event(
                run_id=run.id,
                agent_task_id=agent_task_id,
                event_type="complete" if run.status == "completed" else "partial" if run.status == PARTIAL_STATUS else "error",
                level="info" if run.status == "completed" else "warning" if run.status == PARTIAL_STATUS else "error",
                message=f"Agent run {run.status} after Temporal reattach.",
                payload={
                    "result_preview": (result_text or "")[:1200],
                    "status": run.status,
                    "contract_status": (run.result or {}).get("contract_status"),
                },
                session=session,
            )
        return _run_payload(run)


def set_agent_run_control_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply a Temporal control signal to the AgentRun row."""
    run_id = str(payload["run_id"])
    status = str(payload["status"])
    reason = str(payload.get("reason") or status)
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if not run:
            return {"run_id": run_id, "status": "missing", "terminal": True}
        if run.status in TERMINAL_STATUSES:
            return _run_payload(run)
        previous_status = run.status
        run.status = status
        if status in TERMINAL_STATUSES:
            run.completed_at = datetime.utcnow()
        run.progress = {
            **(run.progress or {}),
            "phase": status,
            "status": status,
            "message": reason,
            "paused_from": previous_status if status == "paused" else (run.progress or {}).get("paused_from"),
            "updated_at": datetime.utcnow().isoformat(),
        }
        session.add(run)
        session.commit()
        create_agent_run_event(
            run_id=run.id,
            agent_task_id=run.agent_task_id,
            event_type=status if status in {"paused", "cancelled"} else "control",
            message=f"Agent run marked {status}: {reason}",
            payload={"status": status, "previous_status": previous_status, "reason": reason},
            session=session,
        )
        return _run_payload(run)


def finalize_agent_run_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    """Record workflow-level completion metadata after agent execution returns."""
    run_id = str(payload["run_id"])
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if not run:
            return {"run_id": run_id, "status": "missing", "terminal": True}
        result = payload.get("result") or {}
        if run.status not in TERMINAL_STATUSES and isinstance(result, dict) and result.get("status") == "failed":
            error_message = str(result.get("error") or result.get("error_message") or "Agent Temporal activity failed")
            run.status = "failed"
            run.completed_at = datetime.utcnow()
            existing_result = run.result if isinstance(run.result, dict) else {}
            run.result = {**existing_result, "error": error_message}
            run.progress = {
                **(run.progress or {}),
                "phase": "failed",
                "status": "failed",
                "message": error_message,
                "updated_at": datetime.utcnow().isoformat(),
            }
            session.add(run)
            session.commit()
        if run.status in TERMINAL_STATUSES and not run.completed_at:
            run.completed_at = datetime.utcnow()
            session.add(run)
            session.commit()
        create_agent_run_event(
            run_id=run.id,
            agent_task_id=run.agent_task_id,
            event_type="temporal_finished",
            message=f"Agent Temporal workflow finished with status {run.status}.",
            payload={"status": run.status, "result": result},
            session=session,
        )
        return _run_payload(run)
