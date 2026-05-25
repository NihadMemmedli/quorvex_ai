#!/usr/bin/env python3
"""Run a bounded autonomous mission soak against the product UI.

The script expects the API/web/worker stack to be running. It creates a
conservative whole-app mission, starts it, periodically runs the autonomous
monitor, and fails if core health invariants are violated.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


def _request(method: str, url: str, *, token: str | None = None, payload: dict[str, Any] | None = None) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with {exc.code}: {body}") from exc


def _mission_payload(name: str, target_url: str, iterations: int) -> dict[str, Any]:
    return {
        "name": name,
        "description": "Bounded product-UI autonomous soak mission.",
        "mission_type": "mixed",
        "target_urls": [target_url],
        "max_runtime_minutes": 120,
        "max_iterations": iterations,
        "max_llm_budget_usd": 10,
        "autonomy_level": "draft_validate",
        "approval_policy": "auto_materialize_low_risk",
        "config": {
            "whole_app_team": True,
            "team_mode": "whole_app",
            "mission_template": "whole_app_team",
            "max_parallel_agents": 2,
            "planner_batch_size": 7,
            "work_item_stale_minutes": 15,
            "write_policy": "proposals_only",
        },
    }


def _assert_soak_health(diagnostics: dict[str, Any]) -> None:
    failures = []
    if diagnostics.get("work_items", {}).get("stale_running", 0):
        failures.append("stale running work items remain")
    if diagnostics.get("requirements", {}).get("duplicate_canonical_keys", 0):
        failures.append("duplicate canonical requirements detected")
    if diagnostics.get("proposals", {}).get("validation_failed", 0):
        failures.append("failed validations remain")
    if failures:
        raise RuntimeError("; ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=os.environ.get("SOAK_API_BASE", "http://127.0.0.1:8000"))
    parser.add_argument("--project-id", default=os.environ.get("SOAK_PROJECT_ID", "default"))
    parser.add_argument("--target-url", default=os.environ.get("SOAK_TARGET_URL", "http://127.0.0.1:3000"))
    parser.add_argument("--token", default=os.environ.get("SOAK_AUTH_TOKEN"))
    parser.add_argument("--iterations", type=int, default=int(os.environ.get("SOAK_ITERATIONS", "10")))
    parser.add_argument("--minutes", type=int, default=int(os.environ.get("SOAK_MINUTES", "120")))
    parser.add_argument("--poll-seconds", type=int, default=int(os.environ.get("SOAK_POLL_SECONDS", "60")))
    args = parser.parse_args()

    base = args.api_base.rstrip("/")
    project = urllib.parse.quote(args.project_id, safe="")
    mission_name = f"Product UI autonomous soak {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
    mission = _request(
        "POST",
        f"{base}/autonomous/{project}/missions",
        token=args.token,
        payload=_mission_payload(mission_name, args.target_url, args.iterations),
    )
    mission_id = urllib.parse.quote(str(mission["id"]), safe="")
    _request("POST", f"{base}/autonomous/{project}/missions/{mission_id}/start", token=args.token)

    deadline = time.time() + args.minutes * 60
    last_diagnostics: dict[str, Any] = {}
    while time.time() < deadline:
        monitor = _request("POST", f"{base}/autonomous/{project}/diagnostics/monitor", token=args.token)
        last_diagnostics = monitor.get("diagnostics") or monitor
        time.sleep(max(5, args.poll_seconds))

    final_diagnostics = _request("GET", f"{base}/autonomous/{project}/diagnostics", token=args.token)
    _assert_soak_health(final_diagnostics)
    print(json.dumps({"mission_id": mission["id"], "last_monitor": last_diagnostics, "final": final_diagnostics}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
