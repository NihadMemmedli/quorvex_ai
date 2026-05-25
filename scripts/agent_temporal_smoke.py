#!/usr/bin/env python3
"""Run a deterministic Temporal smoke test for standalone agent runs."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlmodel import Session, select

from orchestrator.api.db import engine, init_db
from orchestrator.api.models_db import AgentRun, AgentRunEvent
from orchestrator.services.agent_run_events import create_agent_run_event
from orchestrator.services.temporal_client import TemporalUnavailableError, get_agent_run_temporal_diagnostics, start_agent_run_workflow


def _terminal(status: str) -> bool:
    return status in {"completed", "failed", "cancelled", "timeout"}


async def run_smoke(timeout_seconds: int) -> dict:
    init_db()
    run_id = f"agent-temporal-smoke-{uuid.uuid4().hex[:10]}"

    with Session(engine) as session:
        run = AgentRun(
            id=run_id,
            agent_type="__temporal_smoke__",
            status="queued",
            config_json=json.dumps({"temporal_smoke": True, "created_by": "agent_temporal_smoke"}),
        )
        session.add(run)
        session.commit()
        create_agent_run_event(
            run_id=run_id,
            event_type="created",
            message="Temporal smoke agent run created.",
            payload={"smoke": True},
            session=session,
        )

    try:
        temporal = await start_agent_run_workflow(run_id)
    except TemporalUnavailableError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Failed to start Temporal smoke workflow: {exc}") from exc

    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if not run:
            raise RuntimeError(f"Smoke run disappeared: {run_id}")
        run.temporal_workflow_id = temporal.workflow_id
        run.temporal_run_id = temporal.run_id
        session.add(run)
        session.commit()
        create_agent_run_event(
            run_id=run_id,
            event_type="temporal_scheduled",
            message="Temporal smoke workflow scheduled.",
            payload={"workflow_id": temporal.workflow_id, "temporal_run_id": temporal.run_id},
            session=session,
        )

    deadline = time.monotonic() + timeout_seconds
    last_status = "queued"
    while time.monotonic() < deadline:
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            if not run:
                raise RuntimeError(f"Smoke run disappeared while polling: {run_id}")
            last_status = run.status
            if _terminal(run.status):
                events = session.exec(
                    select(AgentRunEvent).where(AgentRunEvent.run_id == run_id).order_by(AgentRunEvent.sequence)
                ).all()
                diagnostics = await get_agent_run_temporal_diagnostics(run.temporal_workflow_id, run.temporal_run_id)
                return {
                    "run_id": run_id,
                    "status": run.status,
                    "temporal_workflow_id": run.temporal_workflow_id,
                    "temporal_run_id": run.temporal_run_id,
                    "events": [event.event_type for event in events],
                    "temporal": {
                        "available": diagnostics.get("available"),
                        "workflow_status": diagnostics.get("workflow_status"),
                        "activity_count": len(diagnostics.get("activities") or []),
                        "retry_count": (diagnostics.get("summary") or {}).get("retry_count"),
                    },
                }
        await asyncio.sleep(1)

    raise TimeoutError(f"Smoke run {run_id} did not finish within {timeout_seconds}s; last status={last_status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=90, help="Seconds to wait for the Temporal run to finish.")
    args = parser.parse_args()

    try:
        result = asyncio.run(run_smoke(args.timeout))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1

    expected_events = {"created", "temporal_scheduled", "temporal_started", "complete", "temporal_finished"}
    missing = sorted(expected_events - set(result["events"]))
    if result["status"] != "completed" or missing or not result["temporal"].get("available"):
        result["ok"] = False
        result["missing_events"] = missing
        print(json.dumps(result, indent=2), file=sys.stderr)
        return 1

    result["ok"] = True
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
