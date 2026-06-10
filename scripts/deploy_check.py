#!/usr/bin/env python3
"""Deployment readiness checks for the external-nginx Quorvex runtime."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


FORBIDDEN_PUBLIC_PATTERNS = (
    "localhost",
    "127.0.0.1",
    "host.docker.internal",
    ":8001",
    ":6080",
    "http://",
)


def log(message: str) -> None:
    print(f"[deploy-check] {message}")


def fail(message: str) -> int:
    print(f"[deploy-check] ERROR: {message}", file=sys.stderr)
    return 1


def fetch(url: str, timeout: float = 10.0) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "quorvex-deploy-check/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8", errors="replace")


def fetch_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    status, body = fetch(url, timeout=timeout)
    if status >= 400:
        raise RuntimeError(f"HTTP {status}")
    return json.loads(body)


def wait_for_url(name: str, url: str, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            status, _ = fetch(url)
            if 200 <= status < 500:
                log(f"{name} reachable: {url} ({status})")
                return True
            last_error = f"HTTP {status}"
        except Exception as exc:  # noqa: BLE001 - report last connection failure
            last_error = str(exc)
        time.sleep(2)
    log(f"{name} not reachable after {timeout}s: {last_error}")
    return False


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def check_company_env(env_file: Path) -> bool:
    values = parse_env_file(env_file)
    if not values:
        print(f"[deploy-check] env file is required for company-mode checks: {env_file}", file=sys.stderr)
        return False

    ok = True
    for key in ("QUORVEX_PUBLIC_API_URL", "NEXT_PUBLIC_API_URL"):
        value = values.get(key, os.environ.get(key, ""))
        if value:
            print(f"[deploy-check] {key} must be blank for company external-nginx mode; got {value!r}", file=sys.stderr)
            ok = False

    vnc_ws = values.get("VNC_PUBLIC_WS_URL", os.environ.get("VNC_PUBLIC_WS_URL", ""))
    if vnc_ws:
        direct_patterns = FORBIDDEN_PUBLIC_PATTERNS[:-1]
        if not vnc_ws.startswith("wss://") or any(pattern in vnc_ws for pattern in direct_patterns):
            print(f"[deploy-check] VNC_PUBLIC_WS_URL is not company-safe: {vnc_ws!r}", file=sys.stderr)
            ok = False
    else:
        print("[deploy-check] VNC_PUBLIC_WS_URL is required for company external-nginx mode.", file=sys.stderr)
        ok = False

    recorder = values.get("RECORDER_BROWSER_URL", os.environ.get("RECORDER_BROWSER_URL", ""))
    if recorder and any(pattern in recorder for pattern in FORBIDDEN_PUBLIC_PATTERNS):
        print(f"[deploy-check] RECORDER_BROWSER_URL exposes a local/direct endpoint: {recorder!r}", file=sys.stderr)
        ok = False

    if ok:
        log("Company-mode env values look safe.")
    return ok


def check_agent_runtime(api_base: str, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    last_status = ""
    while time.monotonic() < deadline:
        try:
            agent = fetch_json(f"{api_base}/api/agents/temporal/health")
            workflows = fetch_json(f"{api_base}/workflows/temporal/health")
            if agent.get("available") is True and workflows.get("available") is True:
                log("Agent runtime ready.")
                return True
            last_status = f"agent={agent.get('status')} workflows={workflows.get('status')}"
        except Exception as exc:  # noqa: BLE001 - status probe should keep retrying
            last_status = str(exc)
        time.sleep(2)
    log(f"Agent runtime did not become ready: {last_status}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default=os.environ.get("QUORVEX_BACKEND_URL", "http://localhost:8001"))
    parser.add_argument("--frontend", default=os.environ.get("QUORVEX_FRONTEND_URL", "http://localhost:3000"))
    parser.add_argument("--env-file", default=os.environ.get("QUORVEX_ENV_FILE", ".env.prod"))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("DEPLOY_CHECK_TIMEOUT", "180")))
    parser.add_argument("--skip-agent", action="store_true", default=os.environ.get("DEPLOY_CHECK_SKIP_AGENT") == "true")
    args = parser.parse_args()

    backend = args.backend.rstrip("/")
    frontend = args.frontend.rstrip("/")
    failures = 0

    if not wait_for_url("frontend", frontend, args.timeout):
        failures += 1
    if not wait_for_url("backend health", f"{backend}/health", args.timeout):
        failures += 1

    for label, url in (
        ("storage health", f"{backend}/health/storage"),
        ("backup health", f"{backend}/health/backup"),
    ):
        try:
            payload = fetch_json(url)
            log(f"{label}: {payload.get('status') or payload.get('healthy') or 'reachable'}")
        except Exception as exc:  # noqa: BLE001
            print(f"[deploy-check] {label} failed: {exc}", file=sys.stderr)
            failures += 1

    try:
        payload = fetch_json(f"{frontend}/backend-proxy/health")
        log(f"same-origin backend proxy reachable: {payload.get('status') or 'ok'}")
    except Exception as exc:  # noqa: BLE001
        print(f"[deploy-check] same-origin backend proxy failed: {exc}", file=sys.stderr)
        failures += 1

    if not check_company_env(Path(args.env_file)):
        failures += 1

    if not args.skip_agent and not check_agent_runtime(backend, args.timeout):
        failures += 1

    if failures:
        return fail(f"{failures} check(s) failed.")
    log("Deployment checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
