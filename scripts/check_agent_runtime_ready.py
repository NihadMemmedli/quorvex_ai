#!/usr/bin/env python3
"""Wait until the local agent execution runtime is actually ready."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def _fetch_json(url: str, timeout: float = 5.0) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code} from {url}"
    except Exception as exc:
        return None, f"{url}: {exc}"

    try:
        return json.loads(body), None
    except json.JSONDecodeError as exc:
        return None, f"{url}: invalid JSON: {exc}"


def _poller_summary(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "pollers unavailable"
    pollers = payload.get("worker_pollers") or {}
    queue_status = payload.get("task_queue_status") or {}
    workflow = pollers.get("workflow", queue_status.get("workflow_pollers", 0))
    activity = pollers.get("activity", queue_status.get("activity_pollers", 0))
    return f"workflow={workflow}, activity={activity}"


def _ready(payload: dict[str, Any] | None) -> bool:
    return bool(payload and payload.get("available") is True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://localhost:8001")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    api_base = args.api_base.rstrip("/")
    deadline = time.monotonic() + args.timeout
    last_status = ""

    while time.monotonic() < deadline:
        health, health_error = _fetch_json(f"{api_base}/health")
        agent, agent_error = _fetch_json(f"{api_base}/api/agents/temporal/health")
        workflows, workflows_error = _fetch_json(f"{api_base}/workflows/temporal/health")

        if health is not None and _ready(agent) and _ready(workflows):
            print(
                "Agent runtime ready: "
                f"agent pollers {_poller_summary(agent)}; "
                f"workflow pollers {_poller_summary(workflows)}."
            )
            return 0

        status_parts = []
        if health_error:
            status_parts.append(f"api={health_error}")
        if agent_error:
            status_parts.append(f"agent={agent_error}")
        elif agent:
            status_parts.append(
                f"agent={agent.get('status')} ({_poller_summary(agent)}; {agent.get('error') or 'waiting'})"
            )
        if workflows_error:
            status_parts.append(f"workflows={workflows_error}")
        elif workflows:
            status_parts.append(
                f"workflows={workflows.get('status')} ({_poller_summary(workflows)}; {workflows.get('error') or 'waiting'})"
            )
        status = "; ".join(status_parts) or "waiting for API"
        if status != last_status:
            print(f"Waiting for agent runtime: {status}")
            last_status = status
        time.sleep(args.interval)

    print("Agent runtime did not become ready before timeout.", file=sys.stderr)
    print(f"Last status: {last_status or 'no status available'}", file=sys.stderr)
    print(
        "Check logs with: make prod-logs "
        "(backend, autonomous-mission-worker, custom-workflow-worker)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
