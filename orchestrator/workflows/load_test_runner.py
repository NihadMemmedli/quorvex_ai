"""
Load Test Runner

Executes K6 load test scripts via subprocess, parses results,
and updates the LoadTestRun DB record with metrics.
"""

import json
import logging
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = BASE_DIR / "runs" / "load"

# Safety limits
K6_TIMEOUT_SECONDS = int(os.environ.get("K6_TIMEOUT_SECONDS", "3600"))
K6_MAX_VUS = int(os.environ.get("K6_MAX_VUS", "1000"))
K6_MAX_DURATION = os.environ.get("K6_MAX_DURATION", "5m")


def run_load_test(
    run_id: str,
    script_path: str,
    vus: int | None = None,
    duration: str | None = None,
    env_vars: dict | None = None,
    pid_callback=None,
    execution_segment: str | None = None,
) -> dict:
    """Execute a K6 load test script and return parsed results.

    Args:
        run_id: Unique run ID (load-<uuid8>)
        script_path: Path to the K6 .js script
        vus: Override virtual users (capped by K6_MAX_VUS)
        duration: Override duration (capped by K6_MAX_DURATION)
        env_vars: Extra environment variables for the K6 script

    Returns:
        Dict with keys: status, summary, timeseries, http_status_counts, error
    """
    # Validate script exists
    script = Path(script_path)
    if not script.exists():
        return {"status": "failed", "error": f"Script not found: {script_path}"}

    # Safety: cap VUs (skip for segmented execution - K6 splits VUs via --execution-segment)
    if vus is not None and vus > K6_MAX_VUS and not execution_segment:
        logger.warning(f"VUs capped from {vus} to {K6_MAX_VUS}")
        vus = K6_MAX_VUS

    # Create run directory (segment-specific subdirectory to prevent file collisions)
    run_dir = RUNS_DIR / run_id
    if execution_segment:
        seg_safe = execution_segment.replace("/", "_").replace(":", "-")
        run_dir = RUNS_DIR / run_id / f"seg-{seg_safe}"
    run_dir.mkdir(parents=True, exist_ok=True)

    summary_file = run_dir / "summary.json"
    jsonl_file = run_dir / "results.jsonl"
    log_file = run_dir / "execution.log"

    # Build K6 command
    cmd = [
        "k6",
        "run",
        str(script),
        "--summary-export",
        str(summary_file),
        "--out",
        f"json={jsonl_file}",
    ]

    if vus is not None:
        cmd.extend(["--vus", str(vus)])
    if duration is not None:
        cmd.extend(["--duration", duration])
    if execution_segment is not None:
        cmd.extend(["--execution-segment", execution_segment])

    # Prepare environment
    env = os.environ.copy()
    # Ensure K6 can write its config (avoids /root permission errors in Docker)
    if "HOME" not in env or env["HOME"] == "/root":
        env["HOME"] = "/tmp"
    env.setdefault("K6_NO_USAGE_REPORT", "true")
    if env_vars:
        env.update(env_vars)

    logger.info(f"[{run_id}] Starting K6: {' '.join(cmd)}")

    process = None
    try:
        with open(log_file, "w") as lf:
            process = subprocess.Popen(
                cmd,
                cwd=run_dir,
                stdout=lf,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )

            # Report PID to caller for stop support
            if pid_callback:
                pid_callback(process.pid)

            try:
                process.wait(timeout=K6_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                logger.warning(f"[{run_id}] K6 timed out after {K6_TIMEOUT_SECONDS}s, killing")
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    process.kill()
                process.wait(timeout=15)
                return {
                    "status": "failed",
                    "error": f"Timeout after {K6_TIMEOUT_SECONDS} seconds",
                    "exit_code": -1,
                    "run_dir": str(run_dir),
                }

        exit_code = process.returncode
        logger.info(f"[{run_id}] K6 exited with code {exit_code}")

        # Parse results
        from utils.k6_result_parser import extract_http_status_counts, parse_jsonl_timeseries, parse_summary

        summary = parse_summary(str(summary_file))
        timeseries = parse_jsonl_timeseries(str(jsonl_file))
        http_status_counts = extract_http_status_counts(str(jsonl_file))

        # Merge HTTP status counts from JSONL into summary
        summary["http_status_counts"] = http_status_counts

        # Determine status from exit code and thresholds
        status = "completed"
        if exit_code != 0:
            # K6 exits with code 99 when thresholds fail
            if exit_code == 99:
                status = "completed"  # still completed, thresholds just failed
            else:
                status = "failed"

        return {
            "status": status,
            "exit_code": exit_code,
            "summary": summary,
            "timeseries": timeseries,
            "http_status_counts": http_status_counts,
            "run_dir": str(run_dir),
            "error": None,
        }

    except FileNotFoundError:
        msg = "k6 binary not found. Install K6: https://k6.io/docs/get-started/installation/"
        logger.error(f"[{run_id}] {msg}")
        return {"status": "failed", "error": msg, "run_dir": str(run_dir)}
    except Exception as e:
        logger.error(f"[{run_id}] Load test failed: {e}")
        return {"status": "failed", "error": str(e), "run_dir": str(run_dir)}


def stop_load_test(run_id: str, pid: int) -> bool:
    """Stop a running K6 process by sending SIGTERM.

    Args:
        run_id: Run ID for logging
        pid: Process ID of the K6 process

    Returns:
        True if signal was sent, False if process not found
    """
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        logger.info(f"[{run_id}] Sent SIGTERM to K6 process group {pid}")
        return True
    except ProcessLookupError:
        logger.warning(f"[{run_id}] K6 process {pid} not found (already exited?)")
        return False
    except OSError as e:
        logger.error(f"[{run_id}] Failed to stop K6 process {pid}: {e}")
        return False


def update_db_record(run_id: str, result: dict) -> None:
    """Update the LoadTestRun DB record with parsed results.

    Called after run_load_test() completes. Imports DB engine lazily
    to avoid circular imports when used from the API layer.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from sqlmodel import Session

    from api.db import engine
    from api.models_db import LoadTestRun

    summary = result.get("summary") or {}
    if not isinstance(summary, dict):
        summary = {}
    overview = summary.get("overview") or {}
    if not isinstance(overview, dict):
        overview = {}
    timeseries = result.get("timeseries") or []
    if not isinstance(timeseries, list):
        timeseries = []

    try:
        with Session(engine) as session:
            db_run = session.get(LoadTestRun, run_id)
            if not db_run:
                logger.warning(f"LoadTestRun {run_id} not found in DB - creating retroactively")
                db_run = LoadTestRun(
                    id=run_id,
                    status="pending",
                    started_at=datetime.utcnow(),
                )
                session.add(db_run)

            db_run.status = result.get("status", "failed")
            db_run.completed_at = datetime.utcnow()
            db_run.current_stage = "done"

            if result.get("error"):
                db_run.error_message = result["error"]

            # Core metrics
            db_run.total_requests = overview.get("total_requests")
            db_run.failed_requests = overview.get("failed_requests")
            db_run.avg_response_time_ms = overview.get("avg_response_time_ms")
            db_run.p50_response_time_ms = overview.get("p50_response_time_ms")
            db_run.p90_response_time_ms = overview.get("p90_response_time_ms")
            db_run.p95_response_time_ms = overview.get("p95_response_time_ms")
            db_run.p99_response_time_ms = overview.get("p99_response_time_ms")
            db_run.max_response_time_ms = overview.get("max_response_time_ms")
            db_run.min_response_time_ms = overview.get("min_response_time_ms")
            db_run.requests_per_second = overview.get("requests_per_second")
            db_run.data_received_bytes = overview.get("data_received_bytes")
            db_run.data_sent_bytes = overview.get("data_sent_bytes")

            # Use pre-computed peak_rps if available (from distributed aggregation)
            if overview.get("peak_rps"):
                db_run.peak_rps = overview["peak_rps"]
            elif timeseries:
                db_run.peak_rps = max((t.get("throughput", 0) for t in timeseries), default=0)

            # Compute peak VUs from overview or timeseries
            peak_vus = overview.get("vus_max")
            if not peak_vus and timeseries:
                peak_vus = max((t.get("vus", 0) for t in timeseries), default=0)
            db_run.peak_vus = peak_vus or None

            # Result details
            db_run.thresholds_passed = summary.get("thresholds_passed")
            db_run.thresholds_detail_json = json.dumps(summary.get("thresholds", {}))
            db_run.checks_json = json.dumps(summary.get("checks", []))
            db_run.http_status_counts_json = json.dumps(result.get("http_status_counts", {}))
            db_run.metrics_summary_json = json.dumps(summary.get("metrics_raw", {}))

            # Store timeseries (can be large - limit to prevent DB bloat)
            MAX_TIMESERIES_POINTS = 3600  # 1 hour at 1s intervals
            if len(timeseries) > MAX_TIMESERIES_POINTS:
                # Downsample: keep every Nth point
                step = len(timeseries) // MAX_TIMESERIES_POINTS
                timeseries = timeseries[::step]
            db_run.timeseries_json = json.dumps(timeseries)

            session.add(db_run)
            session.commit()
            logger.info(f"[{run_id}] DB record updated with {overview.get('total_requests', 0)} total requests")

    except Exception as e:
        logger.error(f"[{run_id}] Failed to update DB record: {e}")


# ========== CLI Entry Point ==========

if __name__ == "__main__":
    import argparse
    import uuid as _uuid

    parser = argparse.ArgumentParser(description="Run a K6 load test")
    parser.add_argument("--spec", required=True, help="Path to load test spec (generates script first) or .js script")
    parser.add_argument("--vus", type=int, help="Override virtual users")
    parser.add_argument("--duration", help="Override duration (e.g., '30s', '1m')")
    args = parser.parse_args()

    from orchestrator.logging_config import setup_logging

    setup_logging()

    spec_or_script = Path(args.spec)
    if not spec_or_script.exists():
        logger.error(f"File not found: {args.spec}")
        sys.exit(1)

    run_id = f"load-{str(_uuid.uuid4())[:8]}"

    if spec_or_script.suffix in (".js", ".ts"):
        # Direct script execution
        result = run_load_test(run_id, str(spec_or_script), vus=args.vus, duration=args.duration)
    else:
        # Markdown spec - generate first, then run
        logger.info(f"[cli] Generating K6 script from spec: {spec_or_script}")
        import asyncio

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from orchestrator.load_env import setup_claude_env

        setup_claude_env()
        from orchestrator.workflows.load_test_generator import LoadTestGenerator

        generator = LoadTestGenerator()
        script_path = asyncio.run(generator.generate(str(spec_or_script)))
        logger.info(f"[cli] Generated script: {script_path}")
        result = run_load_test(run_id, str(script_path), vus=args.vus, duration=args.duration)

    # Log summary
    status = result.get("status", "unknown")
    overview = result.get("summary", {}).get("overview", {})
    logger.info("=" * 60)
    logger.info(f"Load Test Result: {status.upper()}")
    logger.info(f"Run ID: {run_id}")
    if overview:
        logger.info(f"Total Requests: {overview.get('total_requests', 0)}")
        logger.info(f"Failed: {overview.get('failed_requests', 0)}")
        logger.info(f"Avg Response Time: {overview.get('avg_response_time_ms', 0):.1f}ms")
        logger.info(f"P95: {overview.get('p95_response_time_ms', 0):.1f}ms")
        logger.info(f"RPS: {overview.get('requests_per_second', 0):.1f}")
    if result.get("error"):
        logger.error(f"Error: {result['error']}")
    logger.info("=" * 60)

    sys.exit(0 if status == "completed" else 1)
