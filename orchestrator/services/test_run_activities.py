"""Temporal activities for durable classic test runs."""

from __future__ import annotations

import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session

from orchestrator.api.db import engine
from orchestrator.api.models_db import TestRun

TERMINAL_STATUSES = {"passed", "failed", "error", "stopped", "cancelled", "completed"}


def _append_workflow_log(payload: dict[str, Any], message: str, **extra: Any) -> None:
    run_dir_value = payload.get("run_dir")
    if not run_dir_value:
        return
    try:
        run_dir = Path(str(run_dir_value))
        run_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "message": message,
            **extra,
        }
        with (run_dir / "workflow.log").open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


def _run_payload(run: TestRun | None) -> dict[str, Any]:
    if not run:
        return {"status": "missing", "terminal": True, "error_message": "Test run disappeared"}
    return {
        "run_id": run.id,
        "status": run.status,
        "terminal": run.status in TERMINAL_STATUSES,
        "temporal_workflow_id": run.temporal_workflow_id,
        "temporal_run_id": run.temporal_run_id,
    }


async def _cancel_agent_tasks_for_test_run_async(run_id: str) -> dict[str, Any]:
    from orchestrator.services.agent_queue import get_agent_queue

    queue = get_agent_queue()
    await queue.connect()
    return await queue.cancel_tasks_for_test_run(run_id)


def _cleanup_test_run_runtime(payload: dict[str, Any], run_id: str, reason: str) -> dict[str, Any]:
    cleanup: dict[str, Any] = {"run_id": run_id, "reason": reason}
    try:
        cleanup["agent_tasks"] = asyncio.run(_cancel_agent_tasks_for_test_run_async(run_id))
    except Exception as exc:
        cleanup["agent_tasks"] = {"error": str(exc)}
    try:
        from orchestrator.utils.browser_cleanup import kill_test_run_process_tree

        cleanup["processes"] = kill_test_run_process_tree(run_id)
    except Exception as exc:
        cleanup["processes"] = {"error": str(exc)}
    _append_workflow_log(payload, "Test run runtime cleanup completed.", run_id=run_id, cleanup=cleanup)
    return cleanup


def mark_test_run_temporal_started(payload: dict[str, Any]) -> dict[str, Any]:
    """Record Temporal metadata for a durable classic test run."""
    run_id = str(payload["run_id"])
    _append_workflow_log(payload, "Temporal workflow started.", run_id=run_id, workflow_id=payload.get("workflow_id"))
    with Session(engine) as session:
        run = session.get(TestRun, run_id)
        if not run:
            return {"run_id": run_id, "status": "missing", "terminal": True, "error_message": "Test run disappeared"}
        run.temporal_workflow_id = payload.get("workflow_id") or run.temporal_workflow_id
        run.temporal_run_id = payload.get("temporal_run_id") or run.temporal_run_id
        if run.status not in TERMINAL_STATUSES:
            run.status = "queued"
            run.stage_message = run.stage_message or "Queued for Temporal execution"
        session.add(run)
        session.commit()
        return _run_payload(run)


async def execute_test_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute the existing native/mobile run wrapper inside a Temporal activity."""
    run_id = str(payload["run_id"])
    _append_workflow_log(payload, "Temporal execute_test_run activity started.", run_id=run_id)
    with Session(engine) as session:
        run = session.get(TestRun, run_id)
        if not run:
            return {"run_id": run_id, "status": "missing", "terminal": True, "error_message": "Test run disappeared"}
        if run.status in TERMINAL_STATUSES:
            return _run_payload(run)

    from orchestrator.api import main as main_module
    from orchestrator.api.process_manager import get_process_manager

    if main_module.PROCESS_MANAGER is None:
        main_module.PROCESS_MANAGER = get_process_manager()

    if payload.get("target") == "mobile":
        await main_module.execute_mobile_run_task_wrapper(
            spec_path=str(payload["spec_path"]),
            run_dir=str(payload["run_dir"]),
            run_id=run_id,
            platform=str(payload.get("platform") or "ios"),
            appium_server_url=payload.get("appium_server_url"),
            capabilities_file=payload.get("capabilities_file"),
            batch_id=payload.get("batch_id"),
            spec_name=str(payload.get("spec_name") or ""),
            project_id=payload.get("project_id"),
        )
    else:
        await main_module.execute_run_task_wrapper(
            spec_path=str(payload["spec_path"]),
            run_dir=str(payload["run_dir"]),
            run_id=run_id,
            try_code_path=payload.get("try_code_path"),
            browser=str(payload.get("browser") or "chromium"),
            hybrid=bool(payload.get("hybrid", False)),
            max_iterations=int(payload.get("max_iterations") or 20),
            batch_id=payload.get("batch_id"),
            spec_name=str(payload.get("spec_name") or ""),
            project_id=payload.get("project_id"),
            model_tier=payload.get("model_tier"),
        )

    with Session(engine) as session:
        run = session.get(TestRun, run_id)
        _append_workflow_log(payload, "Temporal execute_test_run activity completed.", run_id=run_id, status=run.status if run else "missing")
        return _run_payload(run)


def request_stop_test_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Stop a Temporal-managed test run and its subprocess if it is active."""
    run_id = str(payload["run_id"])
    reason = str(payload.get("reason") or "Stopped by user")
    _append_workflow_log(payload, "Temporal stop requested.", run_id=run_id, reason=reason)
    from orchestrator.api.process_manager import get_process_manager

    stopped = get_process_manager().stop(run_id, timeout=int(payload.get("timeout") or 5))
    cleanup = _cleanup_test_run_runtime(payload, run_id, reason)
    with Session(engine) as session:
        run = session.get(TestRun, run_id)
        if not run:
            return {"run_id": run_id, "status": "missing", "terminal": True, "stopped": stopped, "cleanup": cleanup}
        if run.status not in TERMINAL_STATUSES:
            run.status = "stopped"
            run.queue_position = None
            run.completed_at = datetime.utcnow()
            run.stage_message = reason
            session.add(run)
            session.commit()
        run_dir = Path(payload.get("run_dir") or "") if payload.get("run_dir") else None
        if run_dir and run_dir.exists():
            (run_dir / "status.txt").write_text("stopped")
        elif (Path(__file__).resolve().parents[2] / "runs" / run_id).exists():
            (Path(__file__).resolve().parents[2] / "runs" / run_id / "status.txt").write_text("stopped")
        return {**_run_payload(run), "stopped": stopped, "cleanup": cleanup}


def finalize_test_run_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    """Record workflow-level completion metadata after test execution returns."""
    run_id = str(payload["run_id"])
    _append_workflow_log(payload, "Temporal workflow finalizing.", run_id=run_id)
    with Session(engine) as session:
        run = session.get(TestRun, run_id)
        if not run:
            return {"run_id": run_id, "status": "missing", "terminal": True}
        if run.status in TERMINAL_STATUSES and not run.completed_at:
            run.completed_at = datetime.utcnow()
            session.add(run)
            session.commit()
        result = _run_payload(run)
        if result.get("terminal"):
            result["cleanup"] = _cleanup_test_run_runtime(payload, run_id, "workflow finalized")
        _append_workflow_log(payload, "Temporal workflow finalized.", run_id=run_id, status=result.get("status"))
        return result
