"""
Load Testing Router

Provides endpoints for managing K6 load test specs, scripts, running load tests,
tracking background jobs, and querying run history with metrics/timeseries.
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Integer, and_, func
from sqlmodel import Session, select

from .db import engine, get_session
from .models_db import LoadTestRun

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)


BASE_DIR = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = BASE_DIR / "specs"
SCRIPTS_DIR = BASE_DIR / "scripts" / "load"
RUNS_DIR = BASE_DIR / "runs" / "load"

router = APIRouter(prefix="/load-testing", tags=["load-testing"])

# ========== In-Memory Job Tracking ==========
_load_jobs: dict[str, dict] = {}
MAX_TRACKED_JOBS = 200

# Track running K6 subprocess PIDs for stop support
_running_processes: dict[str, int] = {}  # run_id -> pid


def _cleanup_old_jobs():
    """Remove completed/failed jobs older than 1 hour."""
    try:
        now = time.time()
        to_remove = []
        for job_id, job in _load_jobs.items():
            if job["status"] in ("completed", "failed", "cancelled"):
                completed_at = job.get("completed_at", 0)
                if now - completed_at > 3600:
                    to_remove.append(job_id)
        for job_id in to_remove:
            del _load_jobs[job_id]
        # Enforce hard cap
        if len(_load_jobs) > MAX_TRACKED_JOBS:
            sorted_jobs = sorted(_load_jobs.items(), key=lambda x: x[1].get("started_at", 0))
            for job_id, _ in sorted_jobs[: len(_load_jobs) - MAX_TRACKED_JOBS]:
                del _load_jobs[job_id]
    except Exception as e:
        logger.warning(f"Job cleanup error: {e}")


# ========== Pydantic Models ==========


class CreateLoadSpecRequest(BaseModel):
    name: str
    content: str
    project_id: str | None = "default"


class UpdateLoadSpecRequest(BaseModel):
    content: str


class RunLoadTestRequest(BaseModel):
    script_path: str  # relative path like "scripts/load/test.js"
    spec_name: str | None = None
    vus: int | None = None
    duration: str | None = None
    project_id: str | None = "default"


class RunFromSpecRequest(BaseModel):
    spec_name: str
    vus: int | None = None
    duration: str | None = None
    project_id: str | None = "default"


class GenerateScriptRequest(BaseModel):
    spec_name: str
    project_id: str | None = "default"


# ========== Helper Functions ==========


def _get_specs_dir(project_id: str = "default") -> Path:
    """Get load specs directory, optionally scoped by project."""
    if project_id and project_id != "default":
        d = SPECS_DIR / project_id / "load"
    else:
        d = SPECS_DIR / "load"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _scan_load_specs(project_id: str = "default") -> list[dict]:
    """Scan for load test spec markdown files, scoped to a single project."""
    specs = []
    d = _get_specs_dir(project_id)

    if not d.exists():
        return specs

    for md_file in sorted(d.rglob("*.md")):
        try:
            # Check for matching generated script
            stem = md_file.stem
            script_path = None
            for ext in [".k6.js", ".k6.ts", ".js", ".ts"]:
                candidate = SCRIPTS_DIR / f"{stem}{ext}"
                if candidate.exists():
                    script_path = str(candidate.relative_to(BASE_DIR))
                    break

            specs.append(
                {
                    "name": md_file.name,
                    "path": str(md_file.relative_to(BASE_DIR)),
                    "has_script": script_path is not None,
                    "script_path": script_path,
                    "modified_at": datetime.fromtimestamp(md_file.stat().st_mtime).isoformat(),
                }
            )
        except Exception as e:
            logger.warning(f"Error scanning load spec {md_file}: {e}")

    return specs


def _scan_scripts() -> list[dict]:
    """Scan scripts/load/ directory for K6 scripts."""
    scripts = []
    if not SCRIPTS_DIR.exists():
        return scripts

    for f in sorted(SCRIPTS_DIR.glob("*.js")) + sorted(SCRIPTS_DIR.glob("*.ts")):
        stat = f.stat()
        scripts.append(
            {
                "name": f.name,
                "path": str(f.relative_to(BASE_DIR)),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )

    return scripts


# ========== Background Job Runner ==========


def _run_load_test_sync(
    job_id: str,
    run_id: str,
    script_path: str,
    spec_name: str | None,
    vus: int | None,
    duration: str | None,
    project_id: str,
):
    """Synchronous function to run K6 load test. Called from run_in_executor."""
    try:
        from workflows.load_test_runner import run_load_test, update_db_record

        if job_id in _load_jobs:
            _load_jobs[job_id].update(
                {
                    "stage": "running",
                    "message": "K6 load test running...",
                }
            )

        def _register_pid(pid):
            _running_processes[run_id] = pid

        result = run_load_test(
            run_id=run_id,
            script_path=str(BASE_DIR / script_path),
            vus=vus,
            duration=duration,
            pid_callback=_register_pid,
        )

        # Update in-memory job - defensive: ensure summary/overview are dicts
        status = result.get("status", "failed")
        summary = result.get("summary") or {}
        if not isinstance(summary, dict):
            logger.warning(f"[{run_id}] summary is {type(summary).__name__}, expected dict")
            summary = {}
        overview = summary.get("overview") or {}
        if not isinstance(overview, dict):
            overview = {}

        message_parts = []
        if status == "completed":
            total_req = overview.get("total_requests", 0)
            avg_rt = overview.get("avg_response_time_ms", 0)
            rps = overview.get("requests_per_second", 0)
            message_parts.append(f"{total_req} requests, {avg_rt}ms avg, {rps} rps")
            thresholds_passed = summary.get("thresholds_passed")
            if thresholds_passed is False:
                message_parts.append("(thresholds FAILED)")
            elif thresholds_passed is True:
                message_parts.append("(thresholds passed)")
        else:
            message_parts.append(result.get("error", "Unknown error"))

        if job_id in _load_jobs:
            _load_jobs[job_id].update(
                {
                    "status": status,
                    "stage": "done",
                    "message": " ".join(message_parts),
                    "result": {
                        "run_id": run_id,
                        "run_dir": result.get("run_dir"),
                        "exit_code": result.get("exit_code"),
                        "total_requests": overview.get("total_requests", 0),
                        "avg_response_time_ms": overview.get("avg_response_time_ms", 0),
                        "requests_per_second": overview.get("requests_per_second", 0),
                        "thresholds_passed": summary.get("thresholds_passed"),
                    },
                    "completed_at": time.time(),
                }
            )

        # Persist results to DB
        try:
            update_db_record(run_id, result)
        except Exception as e:
            logger.error(f"Failed to update DB for run {run_id}: {e}")

    except Exception as e:
        logger.error(f"[{run_id}] _run_load_test_sync crashed: {e}", exc_info=True)
        if job_id in _load_jobs:
            _load_jobs[job_id].update(
                {
                    "status": "failed",
                    "stage": "error",
                    "message": str(e),
                    "result": {"run_id": run_id},
                    "completed_at": time.time(),
                }
            )
        # Try to update DB with failure
        try:
            with Session(engine) as session:
                db_run = session.get(LoadTestRun, run_id)
                if db_run:
                    db_run.status = "failed"
                    db_run.completed_at = datetime.utcnow()
                    db_run.current_stage = "error"
                    db_run.error_message = str(e)
                    session.add(db_run)
                    session.commit()
        except Exception as e:
            logger.warning(f"Failed to update DB with failure for {run_id}: {e}")
    finally:
        try:
            from orchestrator.services.load_test_lock import release_sync

            release_sync(run_id)
        except Exception as e:
            logger.warning(f"Failed to release load test lock: {e}")
        _running_processes.pop(run_id, None)


def _run_generate_script_sync(job_id: str, spec_path: str, project_id: str):
    """Synchronous function to generate a K6 script from a spec using AI."""
    if job_id in _load_jobs:
        _load_jobs[job_id].update(
            {
                "stage": "generating",
                "message": "AI generating K6 script from spec...",
            }
        )

    try:
        import asyncio

        from workflows.load_test_generator import LoadTestGenerator

        generator = LoadTestGenerator(project_id=project_id)
        # Run the async generator in a new event loop since we're in a thread
        loop = asyncio.new_event_loop()
        try:
            script_path = loop.run_until_complete(generator.generate(str(BASE_DIR / spec_path)))
        finally:
            loop.close()

        if job_id in _load_jobs:
            _load_jobs[job_id].update(
                {
                    "status": "completed",
                    "stage": "done",
                    "message": "K6 script generated successfully",
                    "result": {"script_path": str(Path(script_path).relative_to(BASE_DIR))},
                    "completed_at": time.time(),
                }
            )
    except Exception as e:
        logger.error(f"Script generation failed for job {job_id}: {e}")
        if job_id in _load_jobs:
            _load_jobs[job_id].update(
                {
                    "status": "failed",
                    "stage": "error",
                    "message": str(e),
                    "completed_at": time.time(),
                }
            )


# ========== Segment Monitoring & Aggregation ==========


async def _monitor_segments(job_id: str, run_id: str, num_segments: int):
    """Background coroutine that polls segment completion and aggregates results."""
    from orchestrator.services.k6_queue import get_k6_queue

    max_wait = 7200  # 2 hour safety cap
    poll_interval = 5
    elapsed = 0

    try:
        queue = get_k6_queue()
        await queue.connect()

        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            try:
                seg_status = await queue.get_segment_status(run_id)
            except Exception as e:
                logger.warning(f"[{run_id}] Segment status check failed: {e}")
                continue

            completed = seg_status["completed"]
            failed = seg_status["failed"]
            total = seg_status["total_segments"]

            # Update job tracker with progress
            if job_id in _load_jobs:
                _load_jobs[job_id]["message"] = (
                    f"Distributed across {total} workers "
                    f"(segments: {completed + failed}/{total} done, "
                    f"{seg_status['running']} running)"
                )

            if seg_status["all_done"]:
                logger.info(f"[{run_id}] All {total} segments completed ({completed} ok, {failed} failed)")
                await _aggregate_segment_results(job_id, run_id, queue)
                # Release exclusive lock after aggregation
                try:
                    from orchestrator.services.load_test_lock import release

                    await release(run_id)
                except Exception as e:
                    logger.warning(f"[{run_id}] Failed to release load test lock: {e}")
                return

        # Timeout
        logger.warning(f"[{run_id}] Segment monitor timed out after {max_wait}s")
        if job_id in _load_jobs:
            _load_jobs[job_id].update(
                {
                    "status": "failed",
                    "stage": "error",
                    "message": f"Segment monitoring timed out after {max_wait}s",
                    "completed_at": time.time(),
                }
            )
        # Release exclusive lock on timeout
        try:
            from orchestrator.services.load_test_lock import release

            await release(run_id)
        except Exception as e:
            logger.warning(f"[{run_id}] Failed to release load test lock: {e}")

    except Exception as e:
        logger.error(f"[{run_id}] Segment monitor error: {e}", exc_info=True)
        if job_id in _load_jobs:
            _load_jobs[job_id].update(
                {
                    "status": "failed",
                    "stage": "error",
                    "message": f"Segment monitor error: {e}",
                    "completed_at": time.time(),
                }
            )
        # Release exclusive lock on error
        try:
            from orchestrator.services.load_test_lock import release

            await release(run_id)
        except Exception as e:
            logger.warning(f"[{run_id}] Failed to release load test lock: {e}")


async def _aggregate_segment_results(job_id: str, run_id: str, queue):
    """Fetch segment results from Redis, merge metrics, update DB."""
    from orchestrator.services.k6_queue import K6TaskStatus

    # Get segment task IDs
    segment_json = await queue._redis.get(f"{queue.SEGMENTS_PREFIX}{run_id}")
    if not segment_json:
        logger.error(f"[{run_id}] No segment mapping found")
        return

    task_ids = json.loads(segment_json)
    segment_results = []
    errors = []

    for task_id in task_ids:
        result_json = await queue._redis.hget(queue.RESULTS_KEY, task_id)
        if result_json:
            result_data = json.loads(result_json)
            if result_data.get("status") == "completed":
                segment_results.append(result_data)
            else:
                errors.append(result_data.get("error", "Unknown error"))
        else:
            task = await queue.get_task(task_id)
            if task and task.status in (K6TaskStatus.FAILED, K6TaskStatus.TIMEOUT, K6TaskStatus.CANCELLED):
                errors.append(task.error or f"Segment {task.segment_index} {task.status.value}")

    if not segment_results:
        # All segments failed
        merged = {
            "status": "failed",
            "error": f"All segments failed: {'; '.join(errors)}",
        }
    else:
        merged = _merge_segment_metrics(segment_results)
        if errors:
            merged["error"] = f"Partial failure ({len(errors)} segments failed): {'; '.join(errors)}"

    # Update DB record with merged results
    try:
        from workflows.load_test_runner import update_db_record

        update_db_record(run_id, merged)
    except Exception as e:
        logger.error(f"[{run_id}] Failed to update DB with aggregated results: {e}")

    # Update in-memory job tracker
    if job_id in _load_jobs:
        summary = merged.get("summary") or {}
        overview = summary.get("overview") or {} if isinstance(summary, dict) else {}

        if merged.get("status") == "completed" or segment_results:
            total_req = overview.get("total_requests", 0)
            avg_rt = overview.get("avg_response_time_ms", 0)
            rps = overview.get("requests_per_second", 0)
            msg = f"{total_req} requests, {avg_rt:.0f}ms avg, {rps:.1f} rps ({len(segment_results)} workers)"
            if errors:
                msg += f" ({len(errors)} segments failed)"
        else:
            msg = merged.get("error", "All segments failed")

        _load_jobs[job_id].update(
            {
                "status": merged.get("status", "failed"),
                "stage": "done",
                "message": msg,
                "result": {
                    "run_id": run_id,
                    "total_requests": overview.get("total_requests", 0),
                    "avg_response_time_ms": overview.get("avg_response_time_ms", 0),
                    "requests_per_second": overview.get("requests_per_second", 0),
                    "worker_count": len(task_ids),
                },
                "completed_at": time.time(),
            }
        )


def _merge_segment_metrics(segment_results: list) -> dict:
    """Merge metrics from multiple K6 segment results into a single result.

    Aggregation rules:
    - Counts (total_requests, failed_requests, data_*): SUM
    - requests_per_second: SUM (segments ran simultaneously)
    - avg_response_time_ms: Weighted average by request count
    - Percentiles (p50/p90/p95/p99): MAX across segments (conservative)
    - max_response_time_ms: MAX
    - min_response_time_ms: MIN
    - thresholds_passed: AND (all must pass)
    """
    if not segment_results:
        return {"status": "failed", "error": "No segment results to merge"}

    merged_overview = {}
    merged_summary = {}
    all_http_status = {}

    total_requests_sum = 0
    weighted_avg_sum = 0

    for result in segment_results:
        summary = result.get("summary") or {}
        if not isinstance(summary, dict):
            continue
        overview = summary.get("overview") or {}
        if not isinstance(overview, dict):
            continue

        req_count = overview.get("total_requests", 0) or 0
        total_requests_sum += req_count

        # Weighted average accumulator
        avg_rt = overview.get("avg_response_time_ms", 0) or 0
        weighted_avg_sum += avg_rt * req_count

    # SUM metrics
    for key in ["total_requests", "failed_requests", "data_received_bytes", "data_sent_bytes"]:
        val = sum((r.get("summary", {}).get("overview", {}).get(key, 0) or 0) for r in segment_results)
        merged_overview[key] = val

    # SUM RPS (segments ran simultaneously)
    merged_overview["requests_per_second"] = sum(
        (r.get("summary", {}).get("overview", {}).get("requests_per_second", 0) or 0) for r in segment_results
    )

    # Weighted average response time
    if total_requests_sum > 0:
        merged_overview["avg_response_time_ms"] = round(weighted_avg_sum / total_requests_sum, 2)
    else:
        merged_overview["avg_response_time_ms"] = 0

    # MAX for percentiles (conservative)
    for key in [
        "p50_response_time_ms",
        "p90_response_time_ms",
        "p95_response_time_ms",
        "p99_response_time_ms",
        "max_response_time_ms",
    ]:
        vals = [r.get("summary", {}).get("overview", {}).get(key) for r in segment_results]
        vals = [v for v in vals if v is not None]
        merged_overview[key] = max(vals) if vals else None

    # MIN for min response time
    min_vals = [r.get("summary", {}).get("overview", {}).get("min_response_time_ms") for r in segment_results]
    min_vals = [v for v in min_vals if v is not None]
    merged_overview["min_response_time_ms"] = min(min_vals) if min_vals else None

    # AND for thresholds_passed
    threshold_vals = [r.get("summary", {}).get("thresholds_passed") for r in segment_results]
    threshold_vals = [v for v in threshold_vals if v is not None]
    merged_summary["thresholds_passed"] = all(threshold_vals) if threshold_vals else None

    # Merge HTTP status counts (SUM)
    for result in segment_results:
        http_counts = result.get("http_status_counts") or {}
        for code, count in http_counts.items():
            all_http_status[code] = all_http_status.get(code, 0) + count

    # Merge timeseries by timestamp bucket (sum throughput, weighted avg response time)
    ts_buckets = {}
    for result in segment_results:
        for point in result.get("timeseries") or []:
            ts = point.get("timestamp", "")
            if ts not in ts_buckets:
                ts_buckets[ts] = {
                    "timestamp": ts,
                    "throughput": 0,
                    "response_time_avg": 0,
                    "response_time_p95": 0,
                    "vus": 0,
                    "error_rate": 0,
                    "_count": 0,
                }
            bucket = ts_buckets[ts]
            bucket["throughput"] += point.get("throughput", 0)
            bucket["vus"] += point.get("vus", 0)
            bucket["response_time_avg"] += point.get("response_time_avg", 0)
            bucket["response_time_p95"] = max(bucket["response_time_p95"], point.get("response_time_p95", 0))
            bucket["error_rate"] += point.get("error_rate", 0)
            bucket["_count"] += 1

    # Average the response_time_avg and error_rate across segments per bucket
    merged_timeseries = []
    for ts in sorted(ts_buckets.keys()):
        bucket = ts_buckets[ts]
        count = bucket.pop("_count", 1) or 1
        bucket["response_time_avg"] = round(bucket["response_time_avg"] / count, 2)
        bucket["error_rate"] = round(bucket["error_rate"] / count, 4)
        merged_timeseries.append(bucket)

    # Compute peak VUs from merged timeseries (VUs are already summed across segments)
    merged_overview["vus_max"] = (
        max((p.get("vus", 0) for p in merged_timeseries), default=0)
        if merged_timeseries
        else sum((r.get("summary", {}).get("overview", {}).get("vus_max", 0) or 0) for r in segment_results)
    )

    # Peak RPS: max from merged timeseries, or sum of segment requests_per_second
    timeseries_peak = max((p.get("throughput", 0) for p in merged_timeseries), default=0) if merged_timeseries else 0
    segment_rps_sum = merged_overview.get("requests_per_second", 0)
    merged_overview["peak_rps"] = max(timeseries_peak, segment_rps_sum)

    # Merge thresholds detail and checks from first result (they're the same test config)
    first_summary = segment_results[0].get("summary") or {}
    merged_summary["overview"] = merged_overview
    merged_summary["thresholds"] = first_summary.get("thresholds", {})
    merged_summary["checks"] = first_summary.get("checks", [])
    merged_summary["metrics_raw"] = first_summary.get("metrics_raw", {})

    # Determine overall status
    statuses = [r.get("status", "failed") for r in segment_results]
    if all(s == "completed" for s in statuses):
        status = "completed"
    elif any(s == "completed" for s in statuses):
        status = "completed"  # Partial success is still "completed" with error notes
    else:
        status = "failed"

    return {
        "status": status,
        "summary": merged_summary,
        "timeseries": merged_timeseries,
        "http_status_counts": all_http_status,
        "error": None,
    }


# ========== Spec Endpoints ==========


@router.get("/specs")
async def list_load_specs(project_id: str = Query("default")):
    """List all load test specifications."""
    return await asyncio.to_thread(_scan_load_specs, project_id)


@router.get("/specs/{name:path}")
async def get_load_spec(name: str, project_id: str = Query("default")):
    """Get a single load test spec content."""
    specs_dir = _get_specs_dir(project_id)
    target = None
    if await asyncio.to_thread(specs_dir.exists):
        for md_file in specs_dir.rglob("*.md"):
            if md_file.name == name:
                target = md_file
                break

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Load spec '{name}' not found")

    content = await asyncio.to_thread(target.read_text, encoding="utf-8")
    return {
        "name": target.name,
        "path": str(target.relative_to(BASE_DIR)),
        "content": content,
    }


@router.post("/specs")
async def create_load_spec(req: CreateLoadSpecRequest):
    """Create a new load test spec file."""
    name = req.name if req.name.endswith(".md") else f"{req.name}.md"

    specs_dir = _get_specs_dir(req.project_id)
    target = specs_dir / name

    if target.exists():
        raise HTTPException(status_code=409, detail=f"Spec '{name}' already exists")

    content = req.content
    if "## Type: Load" not in content and "## type: load" not in content.lower():
        lines = content.split("\n")
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("# "):
                insert_idx = i + 1
                break
        lines.insert(insert_idx, "\n## Type: Load\n")
        content = "\n".join(lines)

    await asyncio.to_thread(target.write_text, content, encoding="utf-8")
    logger.info(f"Created load spec: {target}")
    return {
        "name": target.name,
        "path": str(target.relative_to(BASE_DIR)),
        "message": "Load test spec created",
    }


@router.put("/specs/{name:path}")
async def update_load_spec(name: str, req: UpdateLoadSpecRequest, project_id: str = Query("default")):
    """Update an existing load test spec."""
    specs_dir = _get_specs_dir(project_id)
    target = None
    if specs_dir.exists():
        for md_file in specs_dir.rglob("*.md"):
            if md_file.name == name:
                target = md_file
                break

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Load spec '{name}' not found")

    await asyncio.to_thread(target.write_text, req.content, encoding="utf-8")
    return {"name": target.name, "path": str(target.relative_to(BASE_DIR)), "message": "Spec updated"}


@router.delete("/specs/{name:path}")
async def delete_load_spec(name: str, project_id: str = Query("default")):
    """Delete a load test spec."""
    specs_dir = _get_specs_dir(project_id)
    target = None
    if specs_dir.exists():
        for md_file in specs_dir.rglob("*.md"):
            if md_file.name == name:
                target = md_file
                break

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Load spec '{name}' not found")

    await asyncio.to_thread(target.unlink)
    return {"message": f"Spec '{name}' deleted"}


# ========== Script Endpoints ==========


@router.get("/scripts")
async def list_scripts():
    """List all generated K6 scripts."""
    return await asyncio.to_thread(_scan_scripts)


@router.get("/scripts/{name:path}")
async def get_script(name: str):
    """View content of a K6 script."""
    target = SCRIPTS_DIR / name
    if not await asyncio.to_thread(target.exists):
        raise HTTPException(status_code=404, detail=f"Script '{name}' not found")

    content = await asyncio.to_thread(target.read_text, encoding="utf-8")
    return {
        "name": target.name,
        "path": str(target.relative_to(BASE_DIR)),
        "content": content,
    }


@router.get("/scripts/{name:path}/download")
async def download_script(name: str):
    """Download a K6 script file."""
    from fastapi.responses import FileResponse

    target = SCRIPTS_DIR / name
    if not await asyncio.to_thread(target.exists):
        raise HTTPException(status_code=404, detail=f"Script '{name}' not found")

    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type="application/javascript",
    )


# ========== Generation Endpoints ==========


@router.post("/generate")
async def generate_script(req: GenerateScriptRequest):
    """AI-generate a K6 script from a load test spec. Returns job ID for polling."""
    _cleanup_old_jobs()

    # Find the spec
    spec_path = None
    for d in [_get_specs_dir(req.project_id), SPECS_DIR / "load"]:
        if not d.exists():
            continue
        for md_file in d.rglob("*.md"):
            if md_file.name == req.spec_name:
                spec_path = str(md_file.relative_to(BASE_DIR))
                break
        if spec_path:
            break

    if not spec_path:
        raise HTTPException(status_code=404, detail=f"Spec '{req.spec_name}' not found")

    job_id = str(uuid.uuid4())[:8]
    _load_jobs[job_id] = {
        "status": "running",
        "stage": "queued",
        "message": "Queuing script generation...",
        "started_at": time.time(),
        "result": None,
        "completed_at": None,
    }

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_generate_script_sync, job_id, spec_path, req.project_id)

    return {"job_id": job_id, "status": "running", "message": "Script generation started"}


# ========== Run Endpoints ==========


@router.post("/run")
async def run_load_test_endpoint(req: RunLoadTestRequest):
    """Run a K6 script. Returns job ID for polling."""
    _cleanup_old_jobs()

    # Exclusive lock: only one load test at a time
    from orchestrator.services.load_test_lock import acquire, get_active_info, is_active

    if await is_active():
        info = await get_active_info()
        raise HTTPException(
            status_code=409,
            detail=f"Load test already running: {info.get('run_id', 'unknown')} ({info.get('vus', '?')} VUs)",
        )

    script_file = BASE_DIR / req.script_path
    if not script_file.exists():
        raise HTTPException(status_code=404, detail=f"Script not found: {req.script_path}")

    job_id = str(uuid.uuid4())[:8]
    run_id = f"load-{job_id}"

    # Create DB record
    try:
        with Session(engine) as session:
            db_run = LoadTestRun(
                id=run_id,
                spec_name=req.spec_name,
                script_path=req.script_path,
                status="running",
                project_id=req.project_id,
                vus=req.vus,
                duration=req.duration,
                current_stage="running",
                started_at=datetime.utcnow(),
            )
            session.add(db_run)
            session.commit()
    except Exception as e:
        logger.error(f"Failed to create LoadTestRun for {run_id}: {e}", exc_info=True)

    # Acquire exclusive lock
    lock_acquired = await acquire(run_id, vus=req.vus, duration=req.duration)
    if not lock_acquired:
        raise HTTPException(status_code=409, detail="Another load test started concurrently")

    _load_jobs[job_id] = {
        "status": "running",
        "stage": "queued",
        "message": "Queuing load test...",
        "started_at": time.time(),
        "result": {"run_id": run_id},
        "completed_at": None,
    }

    # Try distributed execution via K6 worker queue
    from orchestrator.services.k6_queue import get_k6_queue, should_use_k6_queue

    if should_use_k6_queue():
        try:
            queue = get_k6_queue()
            await queue.connect()
            # Only enqueue if workers are actually alive to consume tasks
            workers_alive = await queue.worker_count()
            if workers_alive > 1:
                # Multiple workers: split test into segments for true distributed execution
                task_ids = await queue.enqueue_segmented_test(
                    run_id=run_id,
                    script_path=str(BASE_DIR / req.script_path),
                    num_segments=workers_alive,
                    vus=req.vus,
                    duration=req.duration,
                    spec_name=req.spec_name,
                    project_id=req.project_id,
                )
                _load_jobs[job_id].update(
                    {
                        "_task_ids": task_ids,
                        "_distributed": True,
                        "_segmented": True,
                        "_num_segments": workers_alive,
                        "message": f"Distributed across {workers_alive} workers (segments: 0/{workers_alive} completed)",
                    }
                )

                # Set worker_count on the DB record
                try:
                    with Session(engine) as session:
                        db_run = session.get(LoadTestRun, run_id)
                        if db_run:
                            db_run.worker_count = workers_alive
                            session.add(db_run)
                            session.commit()
                except Exception as e:
                    logger.warning(f"Failed to set worker_count for {run_id}: {e}")

                # Start background monitor for segment completion
                asyncio.create_task(_monitor_segments(job_id, run_id, workers_alive))

                logger.info(f"K6 test {run_id} split into {workers_alive} segments (tasks={task_ids})")
                return {
                    "job_id": job_id,
                    "run_id": run_id,
                    "status": "running",
                    "message": f"Load test distributed across {workers_alive} workers",
                    "execution_mode": "distributed",
                    "worker_count": workers_alive,
                }
            elif workers_alive == 1:
                # Single worker: use existing single-task path (backward compatible)
                task_id = await queue.enqueue_k6_test(
                    run_id=run_id,
                    script_path=str(BASE_DIR / req.script_path),
                    vus=req.vus,
                    duration=req.duration,
                    spec_name=req.spec_name,
                    project_id=req.project_id,
                )
                _load_jobs[job_id].update({"_task_id": task_id, "_distributed": True})
                logger.info(f"K6 test {run_id} enqueued to single worker (task={task_id})")
                return {
                    "job_id": job_id,
                    "run_id": run_id,
                    "status": "running",
                    "message": "Load test queued for distributed execution",
                    "execution_mode": "distributed",
                }
            else:
                logger.warning("K6 queue available but no workers connected, falling back to local execution")
        except Exception as e:
            logger.warning(f"K6 queue unavailable, falling back to local: {e}")

    # Fallback: run locally in backend container
    logger.info(f"Running K6 test {run_id} locally in backend container")
    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        None,
        _run_load_test_sync,
        job_id,
        run_id,
        req.script_path,
        req.spec_name,
        req.vus,
        req.duration,
        req.project_id,
    )

    return {
        "job_id": job_id,
        "run_id": run_id,
        "status": "running",
        "message": "Load test started (local)",
        "execution_mode": "local",
    }


@router.post("/run-from-spec")
async def run_from_spec(req: RunFromSpecRequest):
    """Generate a K6 script from spec then run it. Returns job ID for polling."""
    _cleanup_old_jobs()

    # Find spec
    spec_path = None
    for d in [_get_specs_dir(req.project_id), SPECS_DIR / "load"]:
        if not d.exists():
            continue
        for md_file in d.rglob("*.md"):
            if md_file.name == req.spec_name:
                spec_path = md_file
                break
        if spec_path:
            break

    if not spec_path:
        raise HTTPException(status_code=404, detail=f"Spec '{req.spec_name}' not found")

    # Check if script already exists
    stem = spec_path.stem
    existing_script = None
    for ext in [".k6.js", ".k6.ts", ".js", ".ts"]:
        candidate = SCRIPTS_DIR / f"{stem}{ext}"
        if candidate.exists():
            existing_script = str(candidate.relative_to(BASE_DIR))
            break

    if existing_script:
        # Script exists, run it directly
        run_req = RunLoadTestRequest(
            script_path=existing_script,
            spec_name=req.spec_name,
            vus=req.vus,
            duration=req.duration,
            project_id=req.project_id,
        )
        return await run_load_test_endpoint(run_req)

    # No script - need to generate first then run
    # For now, return error asking to generate first
    raise HTTPException(
        status_code=400,
        detail=f"No K6 script found for spec '{req.spec_name}'. Generate a script first using POST /load-testing/generate.",
    )


@router.post("/runs/{run_id}/stop")
async def stop_load_test_endpoint(run_id: str):
    """Stop a running load test by killing its K6 subprocess."""
    # Try distributed cancel first
    try:
        from orchestrator.services.k6_queue import get_k6_queue, should_use_k6_queue

        if should_use_k6_queue():
            queue = get_k6_queue()
            await queue.connect()
            cancelled = await queue.cancel_task(run_id)
            if cancelled:
                # Update DB
                with Session(engine) as session:
                    db_run = session.get(LoadTestRun, run_id)
                    if db_run:
                        db_run.status = "cancelled"
                        db_run.completed_at = datetime.utcnow()
                        db_run.current_stage = "cancelled"
                        db_run.error_message = "Cancelled by user"
                        session.add(db_run)
                        session.commit()
                # Release exclusive lock
                try:
                    from orchestrator.services.load_test_lock import release

                    await release(run_id)
                except Exception as e:
                    logger.warning(f"Failed to release load test lock: {e}")
                return {"message": f"Load test {run_id} cancel requested (distributed)"}
    except Exception as e:
        logger.warning(f"Distributed cancel failed: {e}")

    # Fallback: local stop
    pid = _running_processes.get(run_id)

    if not pid:
        # Try to find from DB and check if still marked as running
        try:
            with Session(engine) as session:
                db_run = session.get(LoadTestRun, run_id)
                if db_run and db_run.status == "running":
                    db_run.status = "cancelled"
                    db_run.completed_at = datetime.utcnow()
                    db_run.current_stage = "cancelled"
                    db_run.error_message = "Cancelled by user"
                    session.add(db_run)
                    session.commit()
                    # Release exclusive lock
                    try:
                        from orchestrator.services.load_test_lock import release

                        await release(run_id)
                    except Exception as e:
                        logger.warning(f"Failed to release load test lock: {e}")
                    return {"message": f"Run {run_id} marked as cancelled (process not found)"}
        except Exception as e:
            logger.warning(f"Failed to update DB for cancelled run {run_id}: {e}")
        raise HTTPException(status_code=404, detail=f"No running process found for {run_id}")

    from workflows.load_test_runner import stop_load_test

    stopped = stop_load_test(run_id, pid)

    # Even if process is already dead, clean up the lock and DB
    # Update DB
    try:
        with Session(engine) as session:
            db_run = session.get(LoadTestRun, run_id)
            if db_run and db_run.status == "running":
                db_run.status = "cancelled"
                db_run.completed_at = datetime.utcnow()
                db_run.current_stage = "cancelled"
                db_run.error_message = "Cancelled by user"
                session.add(db_run)
                session.commit()
    except Exception as e:
        logger.warning(f"Failed to update DB after stopping {run_id}: {e}")

    # Update job tracker
    for _job_id, job in _load_jobs.items():
        if job.get("result", {}).get("run_id") == run_id:
            job.update(
                {
                    "status": "cancelled",
                    "stage": "cancelled",
                    "message": "Cancelled by user",
                    "completed_at": time.time(),
                }
            )
            break

    # Release exclusive lock
    try:
        from orchestrator.services.load_test_lock import release

        await release(run_id)
    except Exception as e:
        logger.warning(f"Failed to release load test lock: {e}")

    # Clean up process tracker
    _running_processes.pop(run_id, None)

    if stopped:
        return {"message": f"Load test {run_id} stopped"}
    return {"message": f"Load test {run_id} cancelled (process already exited)"}


@router.post("/force-unlock")
async def force_unlock():
    """Force-release a stuck load test lock regardless of run_id ownership.

    Use this as a last resort when the lock is stuck with no associated running process
    (e.g., after a server restart while a load test was active).
    """
    from orchestrator.services.load_test_lock import force_release, is_active

    if not await is_active():
        return {"message": "No active load test lock to release", "released": None}

    released_info = await force_release()
    if not released_info:
        return {"message": "No lock was held", "released": None}

    # Try to update the DB record to "cancelled" if one exists
    run_id = released_info.get("run_id")
    if run_id:
        try:
            with Session(engine) as session:
                db_run = session.get(LoadTestRun, run_id)
                if db_run and db_run.status == "running":
                    db_run.status = "cancelled"
                    db_run.completed_at = datetime.utcnow()
                    db_run.current_stage = "cancelled"
                    db_run.error_message = "Force-unlocked by user"
                    session.add(db_run)
                    session.commit()
        except Exception as e:
            logger.warning(f"Failed to update DB after force-unlock for {run_id}: {e}")

        # Clean up in-memory job tracker
        for _job_id, job in _load_jobs.items():
            if job.get("result", {}).get("run_id") == run_id:
                job.update(
                    {
                        "status": "cancelled",
                        "stage": "cancelled",
                        "message": "Force-unlocked by user",
                        "completed_at": time.time(),
                    }
                )
                break

        # Clean up process tracker
        _running_processes.pop(run_id, None)

    logger.warning(f"Load test lock force-released: {released_info}")
    return {"message": "Load test lock force-released", "released": released_info}


# ========== Job Tracking Endpoints ==========


@router.get("/jobs")
async def list_jobs(status: str | None = Query(None)):
    """List all tracked load test jobs."""
    _cleanup_old_jobs()
    jobs = []
    for job_id, job in _load_jobs.items():
        if status and job["status"] != status:
            continue
        jobs.append(
            {
                "job_id": job_id,
                "status": job["status"],
                "stage": job.get("stage"),
                "message": job.get("message"),
                "result": job.get("result"),
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
            }
        )
    return sorted(jobs, key=lambda x: x.get("started_at") or 0, reverse=True)


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get status of a background job."""
    job = _load_jobs.get(job_id)
    if not job:
        # Fallback: check DB for completed load test runs
        # The run_id is typically "load-{job_id}"
        try:
            with Session(engine) as session:
                for candidate_run_id in [f"load-{job_id}", job_id]:
                    db_run = session.get(LoadTestRun, candidate_run_id)
                    if db_run:
                        return {
                            "job_id": job_id,
                            "status": db_run.status,
                            "stage": db_run.current_stage,
                            "message": db_run.error_message or f"Load test {db_run.status}",
                            "result": {
                                "run_id": db_run.id,
                                "total_requests": db_run.total_requests,
                                "avg_response_time_ms": db_run.avg_response_time_ms,
                                "requests_per_second": db_run.requests_per_second,
                            },
                        }
        except Exception as e:
            logger.warning(f"DB fallback lookup failed for load job {job_id}: {e}")
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    # For segmented distributed jobs, return progress from the background monitor
    if job.get("_segmented"):
        return {
            "job_id": job_id,
            "status": job["status"],
            "stage": job.get("stage"),
            "message": job.get("message"),
            "result": job.get("result"),
            "execution_mode": "distributed",
            "worker_count": job.get("_num_segments"),
        }

    # For single-task distributed jobs, fetch real-time status from Redis
    if job.get("_distributed"):
        try:
            from orchestrator.services.k6_queue import K6TaskStatus, get_k6_queue

            queue = get_k6_queue()
            await queue.connect()
            task = await queue.get_task(job["_task_id"])
            if task:
                # When task finishes, sync results to DB as a fallback
                # (in case the worker's DB update failed)
                if task.status in (K6TaskStatus.COMPLETED, K6TaskStatus.FAILED) and not job.get("_db_synced"):
                    try:
                        result_json = await queue._redis.hget(queue.RESULTS_KEY, task.id)
                        if result_json:
                            import json as _json

                            result_data = _json.loads(result_json)
                            from orchestrator.workflows.load_test_runner import update_db_record

                            update_db_record(task.run_id, result_data)
                            job["_db_synced"] = True
                            logger.info(f"Synced distributed task {task.id} results to DB (fallback)")
                    except Exception as db_err:
                        logger.warning(f"Failed to sync distributed results to DB: {db_err}")

                return {
                    "job_id": job_id,
                    "status": task.status.value,
                    "stage": task.status.value,
                    "message": task.error or f"K6 test {task.status.value}",
                    "result": job.get("result"),
                    "execution_mode": "distributed",
                }
        except Exception as e:
            logger.debug(f"Failed to check distributed task status: {e}")

    return {
        "job_id": job_id,
        "status": job["status"],
        "stage": job.get("stage"),
        "message": job.get("message"),
        "result": job.get("result"),
    }


@router.get("/jobs/{job_id}/logs")
async def get_job_logs(job_id: str, tail: int = Query(200, ge=1, le=5000)):
    """Get execution logs for a running or completed job."""
    job = _load_jobs.get(job_id)
    if not job:
        # Fallback: try to find run directory from DB
        run_id = None
        try:
            with Session(engine) as session:
                for candidate_run_id in [f"load-{job_id}", job_id]:
                    db_run = session.get(LoadTestRun, candidate_run_id)
                    if db_run:
                        run_id = db_run.id
                        break
        except Exception as e:
            logger.warning(f"DB fallback lookup for logs failed for load job {job_id}: {e}")
        if not run_id:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
        # Use the DB-derived run_id for log reading
        log_file = RUNS_DIR / run_id / "execution.log"
        if not await asyncio.to_thread(log_file.exists):
            return {"job_id": job_id, "logs": "", "line_count": 0}
        try:
            content = await asyncio.to_thread(log_file.read_text, errors="replace")
            lines = content.splitlines()
            total = len(lines)
            tail_lines = lines[-tail:] if len(lines) > tail else lines
            return {
                "job_id": job_id,
                "logs": "\n".join(tail_lines),
                "line_count": total,
                "truncated": total > tail,
            }
        except Exception as e:
            return {"job_id": job_id, "logs": f"Error reading logs: {e}", "line_count": 0}

    run_id = job.get("result", {}).get("run_id") if job.get("result") else None
    if not run_id:
        return {"job_id": job_id, "logs": "", "line_count": 0}

    # For distributed jobs, read logs from Redis
    if job.get("_distributed"):
        try:
            from orchestrator.services.k6_queue import get_k6_queue

            queue = get_k6_queue()
            await queue.connect()
            log_lines = await queue.get_logs(run_id, tail=tail)
            return {
                "job_id": job_id,
                "logs": "\n".join(log_lines),
                "line_count": len(log_lines),
            }
        except Exception as e:
            logger.debug(f"Failed to check distributed task status: {e}")

    log_file = RUNS_DIR / run_id / "execution.log"
    if not await asyncio.to_thread(log_file.exists):
        return {"job_id": job_id, "logs": "", "line_count": 0}

    try:
        content = await asyncio.to_thread(log_file.read_text, errors="replace")
        lines = content.splitlines()
        total = len(lines)
        tail_lines = lines[-tail:] if len(lines) > tail else lines
        return {
            "job_id": job_id,
            "logs": "\n".join(tail_lines),
            "line_count": total,
            "truncated": total > tail,
        }
    except Exception as e:
        return {"job_id": job_id, "logs": f"Error reading logs: {e}", "line_count": 0}


# ========== Dashboard & Trends Endpoints ==========


@router.get("/dashboard")
async def get_dashboard(
    project_id: str | None = Query(None),
    session: Session = Depends(get_session),
):
    """Aggregate dashboard data for the load testing overview tab."""
    # Base filter
    base_filter = []
    if project_id:
        if project_id == "default":
            base_filter.append((LoadTestRun.project_id == "default") | (LoadTestRun.project_id == None))
        else:
            base_filter.append(LoadTestRun.project_id == project_id)

    # Total / completed / failed counts
    count_q = select(
        func.count().label("total"),
        func.sum(func.cast(LoadTestRun.status == "completed", Integer)).label("completed"),
        func.sum(func.cast(LoadTestRun.status == "failed", Integer)).label("failed"),
    ).select_from(LoadTestRun)
    for f in base_filter:
        count_q = count_q.where(f)
    row = session.exec(count_q).one()
    total_runs = row.total or 0
    completed_runs = row.completed or 0
    failed_runs = row.failed or 0
    pass_rate = round((completed_runs / total_runs) * 100, 1) if total_runs > 0 else 0.0

    # Averages from completed runs
    avg_q = (
        select(
            func.avg(LoadTestRun.p95_response_time_ms).label("avg_p95"),
            func.avg(LoadTestRun.requests_per_second).label("avg_rps"),
            func.sum(LoadTestRun.total_requests).label("total_reqs"),
        )
        .select_from(LoadTestRun)
        .where(LoadTestRun.status == "completed")
    )
    for f in base_filter:
        avg_q = avg_q.where(f)
    avg_row = session.exec(avg_q).one()
    avg_p95_ms = round(avg_row.avg_p95, 1) if avg_row.avg_p95 else 0.0
    avg_rps = round(avg_row.avg_rps, 1) if avg_row.avg_rps else 0.0
    total_requests_all_time = avg_row.total_reqs or 0

    # Recent runs (last 10)
    recent_q = select(LoadTestRun)
    for f in base_filter:
        recent_q = recent_q.where(f)
    recent_q = recent_q.order_by(LoadTestRun.created_at.desc()).limit(10)
    recent_runs_raw = session.exec(recent_q).all()
    recent_runs = [_serialize_run(r) for r in recent_runs_raw]

    # P95 trend (last 30 days, grouped by date)
    from sqlalchemy import Date as SADate
    from sqlalchemy import cast

    p95_q = (
        select(
            cast(LoadTestRun.created_at, SADate).label("run_date"),
            func.avg(LoadTestRun.p95_response_time_ms).label("avg_p95"),
            func.count().label("count"),
        )
        .select_from(LoadTestRun)
        .where(
            LoadTestRun.status == "completed",
            LoadTestRun.p95_response_time_ms != None,
        )
    )
    for f in base_filter:
        p95_q = p95_q.where(f)
    p95_q = (
        p95_q.group_by(cast(LoadTestRun.created_at, SADate))
        .order_by(cast(LoadTestRun.created_at, SADate).desc())
        .limit(30)
    )
    p95_rows = session.exec(p95_q).all()
    p95_trend = [
        {
            "date": str(r.run_date),
            "p95": round(r.avg_p95, 1) if r.avg_p95 else 0,
            "count": r.count,
        }
        for r in reversed(list(p95_rows))
    ]

    # Top slow endpoints: parse metrics_summary_json from last 20 completed runs
    slow_q = select(LoadTestRun.metrics_summary_json).where(LoadTestRun.status == "completed")
    for f in base_filter:
        slow_q = slow_q.where(f)
    slow_q = slow_q.order_by(LoadTestRun.created_at.desc()).limit(20)
    metrics_rows = session.exec(slow_q).all()

    endpoint_stats: dict[str, list] = {}
    for metrics_json_str in metrics_rows:
        try:
            metrics = json.loads(metrics_json_str) if isinstance(metrics_json_str, str) else {}
        except (json.JSONDecodeError, TypeError):
            continue
        for key, val in metrics.items():
            if not isinstance(val, dict) or "values" not in val:
                continue
            values = val.get("values", {})
            if not isinstance(values, dict):
                continue
            p95 = values.get("p(95)") or values.get("p95")
            if p95 is not None:
                endpoint_stats.setdefault(key, []).append(float(p95))

    top_slow_endpoints = []
    for endpoint, p95_values in endpoint_stats.items():
        avg_p95 = sum(p95_values) / len(p95_values)
        top_slow_endpoints.append(
            {
                "endpoint": endpoint,
                "avg_p95_ms": round(avg_p95, 1),
                "occurrence_count": len(p95_values),
            }
        )
    top_slow_endpoints.sort(key=lambda x: x["avg_p95_ms"], reverse=True)
    top_slow_endpoints = top_slow_endpoints[:10]

    return {
        "total_runs": total_runs,
        "completed_runs": completed_runs,
        "failed_runs": failed_runs,
        "pass_rate": pass_rate,
        "avg_p95_ms": avg_p95_ms,
        "avg_rps": avg_rps,
        "total_requests_all_time": total_requests_all_time,
        "recent_runs": recent_runs,
        "p95_trend": p95_trend,
        "top_slow_endpoints": top_slow_endpoints,
    }


@router.get("/runs/trends")
async def get_run_trends(
    spec_name: str = Query(..., description="Spec name to get trends for"),
    limit: int = Query(10, ge=1, le=50),
    project_id: str | None = Query(None),
    session: Session = Depends(get_session),
):
    """Get trend data for a specific load test spec over its recent runs."""
    query = select(LoadTestRun).where(LoadTestRun.spec_name == spec_name)

    if project_id:
        if project_id == "default":
            query = query.where((LoadTestRun.project_id == "default") | (LoadTestRun.project_id == None))
        else:
            query = query.where(LoadTestRun.project_id == project_id)

    query = query.order_by(LoadTestRun.created_at.desc()).limit(limit)
    runs = session.exec(query).all()

    trend_runs = []
    for r in runs:
        error_rate = 0.0
        if r.total_requests and r.total_requests > 0:
            error_rate = round(((r.failed_requests or 0) / r.total_requests) * 100, 2)

        trend_runs.append(
            {
                "id": r.id,
                "status": r.status,
                "p95_response_time_ms": r.p95_response_time_ms,
                "avg_response_time_ms": r.avg_response_time_ms,
                "requests_per_second": r.requests_per_second,
                "error_rate": error_rate,
                "total_requests": r.total_requests,
                "thresholds_passed": r.thresholds_passed,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "duration_seconds": r.duration_seconds,
            }
        )

    return {
        "spec_name": spec_name,
        "runs": trend_runs,
        "count": len(trend_runs),
    }


@router.post("/runs/{run_id}/analyze")
async def analyze_run(run_id: str, session: Session = Depends(get_session)):
    """Trigger AI analysis of a completed load test run."""
    db_run = session.get(LoadTestRun, run_id)
    if not db_run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    if db_run.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Run must be completed to analyze (current: {db_run.status})",
        )

    # Check if already analyzed
    existing = db_run.ai_analysis
    if existing and existing.get("summary"):
        return {"status": "already_analyzed", "ai_analysis": existing}

    # Build run data for analysis
    run_data = _serialize_run(db_run)
    run_data["thresholds_detail"] = db_run.thresholds_detail
    run_data["http_status_counts"] = db_run.http_status_counts
    run_data["metrics_summary"] = db_run.metrics_summary

    job_id = f"analyze-{uuid.uuid4().hex[:8]}"
    _load_jobs[job_id] = {
        "status": "running",
        "stage": "analyzing",
        "message": "Running AI analysis on load test results...",
        "started_at": time.time(),
        "result": {"run_id": run_id},
        "completed_at": None,
    }

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_analysis_sync, job_id, run_id, run_data)

    return {"job_id": job_id, "run_id": run_id, "status": "running"}


def _run_analysis_sync(job_id: str, run_id: str, run_data: dict):
    """Synchronous wrapper for AI analysis. Called from run_in_executor."""
    try:
        _load_jobs[job_id].update({"stage": "analyzing", "message": "AI analyzing load test metrics..."})

        from orchestrator.workflows.load_test_analyzer import analyze_load_test_run

        analysis = asyncio.run(analyze_load_test_run(run_data))

        # Store result in DB
        with Session(engine) as session:
            db_run = session.get(LoadTestRun, run_id)
            if db_run:
                db_run.ai_analysis = analysis
                session.add(db_run)
                session.commit()

        _load_jobs[job_id].update(
            {
                "status": "completed",
                "stage": "done",
                "message": "AI analysis complete",
                "completed_at": time.time(),
                "result": {"run_id": run_id, "ai_analysis": analysis},
            }
        )
        logger.info(f"AI analysis completed for run {run_id}")

    except Exception as e:
        logger.error(f"AI analysis failed for run {run_id}: {e}")
        _load_jobs[job_id].update(
            {
                "status": "failed",
                "stage": "error",
                "message": f"AI analysis failed: {str(e)}",
                "completed_at": time.time(),
            }
        )


# ========== Run History Endpoints ==========


@router.get("/runs")
async def list_runs(
    project_id: str | None = Query(None),
    spec_name: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    """List load test runs from DB with pagination and filters."""
    query = select(LoadTestRun)

    if project_id:
        if project_id == "default":
            query = query.where((LoadTestRun.project_id == "default") | (LoadTestRun.project_id == None))
        else:
            query = query.where(LoadTestRun.project_id == project_id)
    if spec_name:
        query = query.where(LoadTestRun.spec_name == spec_name)
    if status:
        query = query.where(LoadTestRun.status == status)

    count_query = select(func.count()).select_from(query.subquery())
    total = session.exec(count_query).one()

    query = query.order_by(LoadTestRun.created_at.desc())
    query = query.offset(offset).limit(limit)
    runs = session.exec(query).all()

    return {
        "runs": [_serialize_run(r) for r in runs],
        "total": total,
        "has_more": (offset + limit) < total,
    }


@router.get("/runs/latest-by-spec")
async def latest_runs_by_spec(
    project_id: str | None = Query(None),
    session: Session = Depends(get_session),
):
    """Get the latest load test run for each spec_name."""
    subq = select(
        LoadTestRun.spec_name,
        func.max(LoadTestRun.created_at).label("max_created"),
    ).where(LoadTestRun.spec_name != None)
    if project_id:
        if project_id == "default":
            subq = subq.where((LoadTestRun.project_id == "default") | (LoadTestRun.project_id == None))
        else:
            subq = subq.where(LoadTestRun.project_id == project_id)
    subq = subq.group_by(LoadTestRun.spec_name).subquery()

    query = select(LoadTestRun).join(
        subq,
        and_(
            LoadTestRun.spec_name == subq.c.spec_name,
            LoadTestRun.created_at == subq.c.max_created,
        ),
    )
    runs = session.exec(query).all()

    result = {}
    for r in runs:
        result[r.spec_name] = _serialize_run(r)

    return {"specs": result}


@router.get("/runs/compare")
async def compare_runs(
    run_a: str = Query(..., description="First run ID (baseline)"),
    run_b: str = Query(..., description="Second run ID (candidate)"),
    session: Session = Depends(get_session),
):
    """Compare two load test runs with delta metrics and normalized timeseries."""
    db_run_a = session.get(LoadTestRun, run_a)
    if not db_run_a:
        raise HTTPException(status_code=404, detail=f"Run '{run_a}' not found")
    db_run_b = session.get(LoadTestRun, run_b)
    if not db_run_b:
        raise HTTPException(status_code=404, detail=f"Run '{run_b}' not found")

    # Serialize both runs with full details
    data_a = _serialize_run(db_run_a)
    data_a["thresholds_detail"] = db_run_a.thresholds_detail
    data_a["checks"] = db_run_a.checks
    data_a["http_status_counts"] = db_run_a.http_status_counts
    data_a["metrics_summary"] = db_run_a.metrics_summary

    data_b = _serialize_run(db_run_b)
    data_b["thresholds_detail"] = db_run_b.thresholds_detail
    data_b["checks"] = db_run_b.checks
    data_b["http_status_counts"] = db_run_b.http_status_counts
    data_b["metrics_summary"] = db_run_b.metrics_summary

    # Compute deltas
    deltas = _compute_deltas(data_a, data_b)

    # Normalize timeseries to elapsed seconds
    ts_a = _normalize_timeseries(db_run_a.timeseries, db_run_a.started_at)
    ts_b = _normalize_timeseries(db_run_b.timeseries, db_run_b.started_at)

    return {
        "run_a": data_a,
        "run_b": data_b,
        "run_a_timeseries": ts_a,
        "run_b_timeseries": ts_b,
        "deltas": deltas,
    }


def _compute_deltas(run_a: dict, run_b: dict) -> dict:
    """Compute delta metrics between two runs with polarity-aware improvement flags.

    Lower-is-better metrics: response times, failed_requests, error_rate
    Higher-is-better metrics: total_requests, requests_per_second, peak_rps
    Neutral metrics: peak_vus, data_received_bytes, data_sent_bytes, duration_seconds
    """
    LOWER_IS_BETTER = {
        "avg_response_time_ms",
        "p50_response_time_ms",
        "p95_response_time_ms",
        "p99_response_time_ms",
        "max_response_time_ms",
        "min_response_time_ms",
        "failed_requests",
        "error_rate",
    }
    HIGHER_IS_BETTER = {
        "total_requests",
        "requests_per_second",
        "peak_rps",
    }
    NEUTRAL = {
        "peak_vus",
        "data_received_bytes",
        "data_sent_bytes",
        "duration_seconds",
    }

    METRIC_KEYS = LOWER_IS_BETTER | HIGHER_IS_BETTER | NEUTRAL

    # Compute error_rate on-the-fly for both runs
    def _error_rate(run: dict) -> float | None:
        total = run.get("total_requests")
        failed = run.get("failed_requests")
        if total and total > 0 and failed is not None:
            return round(failed / total * 100, 4)
        return 0.0 if total and total > 0 else None

    val_a_map = {k: run_a.get(k) for k in METRIC_KEYS}
    val_b_map = {k: run_b.get(k) for k in METRIC_KEYS}
    val_a_map["error_rate"] = _error_rate(run_a)
    val_b_map["error_rate"] = _error_rate(run_b)

    deltas = {}
    for key in METRIC_KEYS:
        a = val_a_map.get(key)
        b = val_b_map.get(key)

        if a is None and b is None:
            continue

        a_val = a if a is not None else 0
        b_val = b if b is not None else 0
        diff = b_val - a_val

        if a_val != 0:
            pct = round((diff / abs(a_val)) * 100, 2)
        else:
            pct = None

        if abs(diff) < 1e-9:
            direction = "same"
        elif diff > 0:
            direction = "up"
        else:
            direction = "down"

        entry = {
            "value": round(diff, 4) if isinstance(diff, float) else diff,
            "pct": pct,
            "direction": direction,
        }

        if direction == "same":
            pass  # No "improved" key for unchanged metrics → neutral gray in UI
        elif key in LOWER_IS_BETTER:
            entry["improved"] = direction == "down"
        elif key in HIGHER_IS_BETTER:
            entry["improved"] = direction == "up"
        # Neutral metrics: no "improved" key

        deltas[key] = entry

    return deltas


def _normalize_timeseries(timeseries: list, started_at: datetime | None) -> list:
    """Convert absolute timestamps in timeseries to elapsed seconds from started_at."""
    if not timeseries or not started_at:
        return []

    normalized = []
    for point in timeseries:
        ts_str = point.get("timestamp")
        elapsed = None

        if ts_str and started_at:
            try:
                # Try ISO format first
                ts_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                # Make started_at offset-aware if ts_dt is offset-aware, or vice versa
                if ts_dt.tzinfo is not None and started_at.tzinfo is None:
                    elapsed = (ts_dt.replace(tzinfo=None) - started_at).total_seconds()
                elif ts_dt.tzinfo is None and started_at.tzinfo is not None:
                    elapsed = (ts_dt - started_at.replace(tzinfo=None)).total_seconds()
                else:
                    elapsed = (ts_dt - started_at).total_seconds()
            except (ValueError, TypeError):
                elapsed = None

        # If no valid timestamp, use index-based fallback
        if elapsed is None:
            elapsed = len(normalized) * 10  # assume ~10s intervals

        normalized.append(
            {
                "elapsed_seconds": round(elapsed),
                "response_time_avg": point.get("response_time_avg"),
                "response_time_p95": point.get("response_time_p95"),
                "throughput": point.get("throughput"),
                "vus": point.get("vus"),
                "error_rate": point.get("error_rate"),
            }
        )

    # Deduplicate: if multiple points round to same second, average their values
    seen = {}
    for point in normalized:
        key = point["elapsed_seconds"]
        if key in seen:
            existing = seen[key]
            for field in ("response_time_avg", "response_time_p95", "throughput", "vus", "error_rate"):
                if point.get(field) is not None and existing.get(field) is not None:
                    existing[field] = (existing[field] + point[field]) / 2
                elif point.get(field) is not None:
                    existing[field] = point[field]
        else:
            seen[key] = point
    return sorted(seen.values(), key=lambda p: p["elapsed_seconds"])


@router.get("/runs/{run_id}")
async def get_run(run_id: str, session: Session = Depends(get_session)):
    """Get detailed run info with all metrics."""
    db_run = session.get(LoadTestRun, run_id)
    if not db_run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    data = _serialize_run(db_run)
    # Include full details
    data["thresholds_detail"] = db_run.thresholds_detail
    data["checks"] = db_run.checks
    data["http_status_counts"] = db_run.http_status_counts
    data["metrics_summary"] = db_run.metrics_summary
    data["stages"] = db_run.stages
    data["thresholds_config"] = db_run.thresholds
    data["ai_analysis"] = db_run.ai_analysis
    return data


@router.get("/runs/{run_id}/timeseries")
async def get_run_timeseries(run_id: str, session: Session = Depends(get_session)):
    """Get time-series chart data for a run."""
    db_run = session.get(LoadTestRun, run_id)
    if not db_run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    return {
        "run_id": run_id,
        "timeseries": db_run.timeseries,
        "point_count": len(db_run.timeseries),
    }


# ========== Status Endpoint ==========


@router.get("/status")
async def get_load_testing_status():
    """Health endpoint showing execution mode and worker info."""
    from orchestrator.services.k6_queue import get_k6_queue, should_use_k6_queue
    from orchestrator.services.load_test_lock import get_active_info as lt_get_active_info
    from orchestrator.services.load_test_lock import is_active as lt_is_active

    load_test_active = await lt_is_active()
    active_run_info = await lt_get_active_info()

    if should_use_k6_queue():
        try:
            queue = get_k6_queue()
            await queue.connect()
            metrics = await queue.get_metrics()
            workers_alive = metrics.get("workers_alive", 0)
            # Only report "distributed" if workers are actually connected
            mode = "distributed" if workers_alive > 0 else "local"
            return {
                "mode": mode,
                "workers_connected": workers_alive,
                "queue_length": metrics.get("queue_length", 0),
                "running_tasks": metrics.get("running", 0),
                "load_test_active": load_test_active,
                "active_run": active_run_info,
            }
        except Exception as e:
            logger.debug(f"K6 queue check failed: {e}")

    return {
        "mode": "local",
        "workers_connected": 0,
        "queue_length": 0,
        "running_tasks": len([j for j in _load_jobs.values() if j["status"] == "running"]),
        "load_test_active": load_test_active,
        "active_run": active_run_info,
    }


# ========== System Limits Endpoint ==========


@router.get("/system-limits")
async def get_system_limits():
    """Return system resource limits and current capacity for the load testing UI."""
    from orchestrator.services.browser_pool import InMemoryBrowserPool
    from orchestrator.services.k6_queue import get_k6_queue, should_use_k6_queue
    from orchestrator.services.load_test_lock import LOCK_TTL_SECONDS
    from orchestrator.services.load_test_lock import is_active as lt_is_active

    # K6 safety limits from env
    k6_max_vus = int(os.environ.get("K6_MAX_VUS", "1000"))
    k6_max_duration = os.environ.get("K6_MAX_DURATION", "5m")
    k6_timeout_seconds = int(os.environ.get("K6_TIMEOUT_SECONDS", "3600"))
    max_browser_instances = int(os.environ.get("MAX_BROWSER_INSTANCES", "5"))

    # Browser pool live status
    pool = InMemoryBrowserPool.get_instance_sync()
    if pool:
        pool_status = await pool.get_status()
        browser_slots_running = pool_status["running"]
        browser_slots_available = pool_status["available"]
    else:
        browser_slots_running = 0
        browser_slots_available = max_browser_instances

    # Execution mode and worker count
    execution_mode = "local"
    workers_connected = 0
    if should_use_k6_queue():
        try:
            queue = get_k6_queue()
            await queue.connect()
            metrics = await queue.get_metrics()
            workers_alive = metrics.get("workers_alive", 0)
            if workers_alive > 0:
                execution_mode = "distributed"
                workers_connected = workers_alive
        except Exception as e:
            logger.debug(f"K6 queue check failed: {e}")

    # Effective max VUs: distributed multiplies by worker count
    effective_max_vus = k6_max_vus * workers_connected if execution_mode == "distributed" else k6_max_vus

    # Lock status
    load_test_lock_active = await lt_is_active()

    return {
        "k6_max_vus": k6_max_vus,
        "k6_max_duration": k6_max_duration,
        "k6_timeout_seconds": k6_timeout_seconds,
        "max_browser_instances": max_browser_instances,
        "browser_slots_available": browser_slots_available,
        "browser_slots_running": browser_slots_running,
        "execution_mode": execution_mode,
        "workers_connected": workers_connected,
        "effective_max_vus": effective_max_vus,
        "load_test_lock_active": load_test_lock_active,
        "lock_ttl_seconds": LOCK_TTL_SECONDS,
    }


# ========== Serialization ==========


def _serialize_run(r: LoadTestRun) -> dict:
    """Serialize a LoadTestRun for API response."""
    return {
        "id": r.id,
        "spec_name": r.spec_name,
        "script_path": r.script_path,
        "status": r.status,
        "project_id": r.project_id,
        "vus": r.vus,
        "duration": r.duration,
        "current_stage": r.current_stage,
        "error_message": r.error_message,
        # Core metrics
        "total_requests": r.total_requests,
        "failed_requests": r.failed_requests,
        "avg_response_time_ms": r.avg_response_time_ms,
        "p50_response_time_ms": r.p50_response_time_ms,
        "p90_response_time_ms": r.p90_response_time_ms,
        "p95_response_time_ms": r.p95_response_time_ms,
        "p99_response_time_ms": r.p99_response_time_ms,
        "max_response_time_ms": r.max_response_time_ms,
        "min_response_time_ms": r.min_response_time_ms,
        "requests_per_second": r.requests_per_second,
        "peak_rps": r.peak_rps,
        "peak_vus": r.peak_vus,
        "data_received_bytes": r.data_received_bytes,
        "data_sent_bytes": r.data_sent_bytes,
        "thresholds_passed": r.thresholds_passed,
        "worker_count": r.worker_count,
        # Timestamps
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "duration_seconds": r.duration_seconds,
    }
