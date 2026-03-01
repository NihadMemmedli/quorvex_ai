import json
import logging
import os
import time as _time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from sqlmodel import select

from .projects import _count_all_specs_for_project

# Import test counter utility for accurate test counting
try:
    from ..utils.test_counter import get_project_test_count, get_total_test_count
except ImportError:
    # Fallback if utility not available
    def get_total_test_count(dir_path: str, pattern: str = "**/*.spec.ts") -> tuple[int, int]:
        from pathlib import Path

        test_files = list(Path(dir_path).glob(pattern))
        return len(test_files), len(test_files)

    def get_project_test_count(project_id: str, tests_dir: str, specs_dir: str, session) -> tuple[int, int]:
        return 0, 0


logger = logging.getLogger(__name__)
router = APIRouter()

# Simple TTL cache for expensive dashboard aggregations
_dashboard_cache: dict[str, tuple] = {}  # key -> (data, timestamp)
_DASHBOARD_CACHE_TTL = 30  # seconds

BASE_DIR = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = BASE_DIR / "runs"
SPECS_DIR = BASE_DIR / "specs"
TESTS_DIR = BASE_DIR / "tests" / "generated"


def categorize_error(err_msg: str) -> str:
    """
    Categorize error messages into actionable categories.
    Uses case-insensitive matching with multiple patterns per category.
    """
    err_lower = err_msg.lower()

    # Timeout errors (check first as TimeoutError is common)
    if any(p in err_lower for p in ["timeout", "timed out", "exceeded", "30000ms", "waiting for selector"]):
        return "Timeout"

    # Rate limiting (check before network errors)
    if any(
        p in err_lower
        for p in ["429", "rate limit", "too many requests", "throttle", "quota exceeded", "rate limiting"]
    ):
        return "Rate Limiting"

    # Assertion / Expectation failures
    if any(
        p in err_lower
        for p in [
            "expect",
            "assert",
            "should",
            "tobe",
            "toequal",
            "tohave",
            "tomatch",
            "tocontain",
            "expected",
            "but found",
            "but got",
            "comparison failed",
            "not found on page",
            "text not found",
            "does not match",
        ]
    ):
        return "Assertion Failed"

    # Selector / Element issues
    if any(
        p in err_lower
        for p in [
            "selector",
            "locator",
            "element not found",
            "not visible",
            "not attached",
            "target closed",
            "no element",
            "cannot find",
            "strict mode violation",
            "resolved to",
            "detached",
            "intercept",
            "outside of the viewport",
            "does not navigate",
            "url remains",
        ]
    ):
        return "Selector/Element Issue"

    # JavaScript / Script errors
    if any(
        p in err_lower
        for p in [
            "typeerror",
            "referenceerror",
            "syntaxerror",
            "cannot read properties",
            "undefined is not",
            "null is not",
            "is not a function",
            "is not defined",
            "script error",
            "evaluation failed",
            "runtime error",
            "application crashed",
            "application error",
        ]
    ):
        return "Script Error"

    # Navigation / HTTP errors
    if any(
        p in err_lower
        for p in [
            "navigation",
            "net::",
            "err_",
            "failed to load",
            "404",
            "500",
            "502",
            "503",
            "504",
            "not found",
            "page crash",
            "context was destroyed",
            "page closed",
            "neterror",
            "dns",
            "connection refused",
            "connection reset",
            "does not exist",
            "service unavailable",
            "bad gateway",
        ]
    ):
        return "Navigation/HTTP Error"

    # Authentication / Authorization
    if any(
        p in err_lower
        for p in [
            "auth",
            "login failed",
            "credential",
            "401",
            "403",
            "forbidden",
            "unauthorized",
            "access denied",
            "permission denied",
            "session expired",
            "invalid password",
            "sign in",
            "logged in",
        ]
    ):
        return "Authentication Error"

    # Healing / Auto-fix failures
    if any(
        p in err_lower
        for p in [
            "healing",
            "could not fix",
            "failed after",
            "healing attempts",
            "auto-fix",
            "autofix",
            "repair failed",
        ]
    ):
        return "Healing Failed"

    # Test Configuration / Data issues
    if any(
        p in err_lower
        for p in [
            "test plan",
            "incomplete",
            "missing",
            "not available",
            "not configured",
            "not provided",
            "precondition",
            "setup failed",
            "tools not available",
            "mcp tools",
            "already logged",
        ]
    ):
        return "Test Setup Issue"

    # Network request issues (blocked, violated, etc.)
    if any(
        p in err_lower
        for p in ["network", "fetch", "xhr", "api error", "response error", "blocked request", "violation", "cors"]
    ):
        return "Network/API Error"

    # If no specific category matched
    return "Other Error"


def get_healing_stats(runs_dir: Path, period_start: float | None) -> dict:
    """Parse validation.json files for healing metrics."""
    stats = {
        "overall": {"total_heals_attempted": 0, "total_heals_succeeded": 0, "success_rate": 0},
        "by_mode": {
            "native_healer": {"attempted": 0, "succeeded": 0, "success_rate": 0},
            "ralph": {"attempted": 0, "succeeded": 0, "success_rate": 0},
        },
        "avg_iterations_to_success": 0,
        "trend": [],
    }

    if not runs_dir.exists():
        return stats

    daily_healing = defaultdict(lambda: {"attempted": 0, "succeeded": 0})
    total_iterations_on_success = []

    for run_path in runs_dir.iterdir():
        if not run_path.is_dir():
            continue

        validation_file = run_path / "validation.json"
        if not validation_file.exists():
            continue

        try:
            # Parse timestamp from directory name
            run_id = run_path.name
            timestamp = 0
            try:
                time_part = "_".join(run_id.split("_")[:2])
                dt = datetime.strptime(time_part, "%Y-%m-%d_%H-%M-%S")
                timestamp = dt.timestamp()
                date_str = dt.strftime("%Y-%m-%d")
            except ValueError:
                timestamp = os.path.getmtime(run_path)
                date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")

            # Apply period filter
            if period_start and timestamp < period_start:
                continue

            validation_data = json.loads(validation_file.read_text())

            # Extract healing info - check for healing-related fields
            mode = validation_data.get("mode", "native_healer")
            iterations = validation_data.get("iterations", validation_data.get("healing_iterations", 1))
            status = validation_data.get("status", validation_data.get("final_status", "unknown"))

            # Determine if this was a healing attempt
            # A healing attempt is when validation was needed (test didn't pass initially)
            was_healed = validation_data.get("healed", False) or iterations > 0

            if was_healed or status in ("passed", "failed"):
                stats["overall"]["total_heals_attempted"] += 1
                daily_healing[date_str]["attempted"] += 1

                # Normalize mode name
                if mode in ("native", "native_healer"):
                    mode_key = "native_healer"
                elif mode in ("ralph", "hybrid"):
                    mode_key = "ralph"
                else:
                    mode_key = "native_healer"

                stats["by_mode"][mode_key]["attempted"] += 1

                if status in ("passed", "success", "completed"):
                    stats["overall"]["total_heals_succeeded"] += 1
                    stats["by_mode"][mode_key]["succeeded"] += 1
                    daily_healing[date_str]["succeeded"] += 1
                    if iterations > 0:
                        total_iterations_on_success.append(iterations)

        except Exception as e:
            logger.warning(f"Error processing validation {validation_file}: {e}")
            continue

    # Calculate success rates
    if stats["overall"]["total_heals_attempted"] > 0:
        stats["overall"]["success_rate"] = round(
            stats["overall"]["total_heals_succeeded"] / stats["overall"]["total_heals_attempted"] * 100, 1
        )

    for mode_key in ["native_healer", "ralph"]:
        if stats["by_mode"][mode_key]["attempted"] > 0:
            stats["by_mode"][mode_key]["success_rate"] = round(
                stats["by_mode"][mode_key]["succeeded"] / stats["by_mode"][mode_key]["attempted"] * 100, 1
            )

    if total_iterations_on_success:
        stats["avg_iterations_to_success"] = round(
            sum(total_iterations_on_success) / len(total_iterations_on_success), 1
        )

    # Build trend
    for date_str in sorted(daily_healing.keys()):
        day_stats = daily_healing[date_str]
        rate = 0
        if day_stats["attempted"] > 0:
            rate = round(day_stats["succeeded"] / day_stats["attempted"] * 100, 1)
        stats["trend"].append({"date": date_str, "success_rate": rate, "attempts": day_stats["attempted"]})

    return stats


def get_time_of_day_analysis(runs: list[dict]) -> dict:
    """Analyze pass rates by hour of day."""
    hourly_stats = {hour: {"total": 0, "passed": 0, "failed": 0} for hour in range(24)}

    for run in runs:
        timestamp = run.get("timestamp", 0)
        if timestamp:
            hour = datetime.fromtimestamp(timestamp).hour
            hourly_stats[hour]["total"] += 1
            if run.get("status") == "passed":
                hourly_stats[hour]["passed"] += 1
            else:
                hourly_stats[hour]["failed"] += 1

    # Convert to list format and calculate pass rates
    result = []
    for hour in range(24):
        stats = hourly_stats[hour]
        pass_rate = 0
        if stats["total"] > 0:
            pass_rate = round(stats["passed"] / stats["total"] * 100, 1)
        result.append(
            {
                "hour": hour,
                "total": stats["total"],
                "passed": stats["passed"],
                "failed": stats["failed"],
                "pass_rate": pass_rate,
            }
        )

    # Find peak failure hours (hours with > 0 runs and < 50% pass rate)
    peak_failure_hours = [item["hour"] for item in result if item["total"] >= 2 and item["pass_rate"] < 50]

    # Find best hours (hours with > 0 runs and >= 80% pass rate)
    best_hours = [item["hour"] for item in result if item["total"] >= 2 and item["pass_rate"] >= 80]

    return {
        "hourly_stats": result,
        "peak_failure_hours": peak_failure_hours[:5],  # Top 5
        "best_hours": best_hours[:5],  # Top 5
    }


def get_failure_patterns(runs_dir: Path, period_start: float | None) -> dict:
    """Find tests that commonly fail together."""
    result = {"common_co_failures": [], "isolated_failures": []}

    if not runs_dir.exists():
        return result

    # Group runs by batch (prefer batch_id if available, otherwise use 5-minute time windows)
    batches = defaultdict(list)
    test_solo_failures = defaultdict(lambda: {"solo": 0, "total_failures": 0})

    for run_path in runs_dir.iterdir():
        if not run_path.is_dir():
            continue

        run_file = run_path / "run.json"
        if not run_file.exists():
            continue

        try:
            run_id = run_path.name
            timestamp = 0
            try:
                time_part = "_".join(run_id.split("_")[:2])
                dt = datetime.strptime(time_part, "%Y-%m-%d_%H-%M-%S")
                timestamp = dt.timestamp()
            except ValueError:
                timestamp = os.path.getmtime(run_path)

            # Apply period filter
            if period_start and timestamp < period_start:
                continue

            run_data = json.loads(run_file.read_text())
            status = run_data.get("finalState", "unknown")

            # Extract test name - prefer testName from run data, then try to parse from run_id
            test_name = run_data.get("testName")
            if not test_name:
                # Try to extract from run_id (format: 2026-01-09_01-17-58_test-name.md)
                parts = run_id.split("_", 2)
                if len(parts) >= 3:
                    # Remove .md extension if present
                    test_name = parts[2].replace(".md", "").replace("-", " ").replace("_", " ").title()
                else:
                    # Can't extract meaningful name, skip this run for pattern analysis
                    continue

            # Prefer batch_id/run_id if available for grouping, otherwise use 5-minute time windows
            batch_id = run_data.get("batch_id") or run_data.get("batchId")
            if batch_id:
                batch_key = str(batch_id)
            else:
                # Use 5-minute granularity for batch grouping (runs within 5 minutes are same batch)
                dt = datetime.fromtimestamp(timestamp)
                # Round down to nearest 5 minutes
                minute_bucket = (dt.minute // 5) * 5
                batch_key = dt.strftime(f"%Y-%m-%d_%H-{minute_bucket:02d}")

            batches[batch_key].append({"test_name": test_name, "status": status})
        except Exception as e:
            logger.warning(f"Error processing run for failure patterns {run_path}: {e}")
            continue

    # Analyze co-failures
    co_failure_counts = Counter()

    for _batch_key, batch_runs in batches.items():
        failed_tests = [r["test_name"] for r in batch_runs if r["status"] != "passed"]

        # Deduplicate test names - same test failing multiple times in a batch
        # shouldn't count as "co-failure with itself"
        unique_failed_tests = list(set(failed_tests))

        if len(unique_failed_tests) == 1:
            # Solo failure (even if same test failed multiple times)
            test_solo_failures[unique_failed_tests[0]]["solo"] += 1
            test_solo_failures[unique_failed_tests[0]]["total_failures"] += 1
        elif len(unique_failed_tests) >= 2:
            # Co-failures - track all pairs of DIFFERENT tests
            for test in unique_failed_tests:
                test_solo_failures[test]["total_failures"] += 1
            for pair in combinations(sorted(unique_failed_tests), 2):
                co_failure_counts[pair] += 1

    # Build co-failure list
    for (test1, test2), count in co_failure_counts.most_common(10):
        total_failures_for_pair = min(
            test_solo_failures[test1]["total_failures"], test_solo_failures[test2]["total_failures"]
        )
        co_occurrence_rate = round(count / total_failures_for_pair * 100, 1) if total_failures_for_pair > 0 else 0
        result["common_co_failures"].append(
            {"tests": [test1, test2], "co_occurrence_count": count, "co_occurrence_rate": co_occurrence_rate}
        )

    # Build isolated failures list (lowered threshold from 50% to 30%)
    for test_name, stats in test_solo_failures.items():
        if stats["total_failures"] >= 2:
            solo_rate = round(stats["solo"] / stats["total_failures"] * 100, 1)
            if solo_rate >= 30:  # Lowered from 50% to 30% for better detection
                result["isolated_failures"].append({"test": test_name, "solo_failure_rate": solo_rate})

    result["isolated_failures"].sort(key=lambda x: x["solo_failure_rate"], reverse=True)
    result["isolated_failures"] = result["isolated_failures"][:10]  # Top 10

    return result


def get_test_growth_trends(runs_dir: Path, specs_dir: Path, tests_dir: Path, period_start: float | None) -> dict:
    """
    Track test growth metrics over time using actual file and run data.
    Shows: total specs, generated tests, and passing tests by date.
    """
    result = {"has_data": False, "trend": [], "latest": None, "growth": {"specs": 0, "generated": 0, "passing": 0}}

    # Collect daily data
    daily_data = defaultdict(lambda: {"total_specs": 0, "generated_tests": 0, "passing_tests": 0, "total_runs": 0})

    # 1. Count spec files by creation/modification date
    if specs_dir.exists():
        for spec_file in specs_dir.glob("**/*.md"):
            try:
                timestamp = os.path.getmtime(spec_file)
                if period_start and timestamp < period_start:
                    continue
                date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
                daily_data[date_str]["total_specs"] += 1
            except Exception as e:
                logger.debug(f"Skipping file in metrics scan: {e}")
                continue

    # 2. Count generated test files by creation/modification date
    if tests_dir.exists():
        for test_file in tests_dir.glob("**/*.spec.ts"):
            try:
                timestamp = os.path.getmtime(test_file)
                if period_start and timestamp < period_start:
                    continue
                date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
                daily_data[date_str]["generated_tests"] += 1
            except Exception as e:
                logger.debug(f"Skipping file in metrics scan: {e}")
                continue

    # 3. Count passing runs by date
    if runs_dir.exists():
        for run_path in runs_dir.iterdir():
            if not run_path.is_dir():
                continue

            run_file = run_path / "run.json"
            if not run_file.exists():
                continue

            try:
                run_id = run_path.name
                timestamp = 0
                try:
                    time_part = "_".join(run_id.split("_")[:2])
                    dt = datetime.strptime(time_part, "%Y-%m-%d_%H-%M-%S")
                    timestamp = dt.timestamp()
                    date_str = dt.strftime("%Y-%m-%d")
                except ValueError:
                    timestamp = os.path.getmtime(run_path)
                    date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")

                # Apply period filter
                if period_start and timestamp < period_start:
                    continue

                run_data = json.loads(run_file.read_text())
                status = run_data.get("finalState", "unknown")

                daily_data[date_str]["total_runs"] += 1
                if status == "passed":
                    daily_data[date_str]["passing_tests"] += 1

            except Exception as e:
                logger.debug(f"Skipping file in metrics scan: {e}")
                continue

    if not daily_data:
        return result

    result["has_data"] = True

    # Build cumulative trend (running totals over time)
    cumulative_specs = 0
    cumulative_generated = 0
    cumulative_passing = 0

    for date_str in sorted(daily_data.keys()):
        day_stats = daily_data[date_str]
        cumulative_specs += day_stats["total_specs"]
        cumulative_generated += day_stats["generated_tests"]
        cumulative_passing += day_stats["passing_tests"]

        result["trend"].append(
            {
                "date": date_str,
                "total_specs": cumulative_specs,
                "generated_tests": cumulative_generated,
                "passing_tests": cumulative_passing,
                "daily_runs": day_stats["total_runs"],
            }
        )

    # Set latest totals
    if result["trend"]:
        latest = result["trend"][-1]
        result["latest"] = {
            "total_specs": latest["total_specs"],
            "generated_tests": latest["generated_tests"],
            "passing_tests": latest["passing_tests"],
        }

        # Calculate growth (compare first and last)
        if len(result["trend"]) >= 2:
            first = result["trend"][0]
            result["growth"] = {
                "specs": latest["total_specs"] - first["total_specs"],
                "generated": latest["generated_tests"] - first["generated_tests"],
                "passing": latest["passing_tests"] - first["passing_tests"],
            }

    return result


def get_period_start_timestamp(period: str) -> float | None:
    """Get the start timestamp for the given period filter."""
    now = datetime.now()
    if period == "24h":
        return (now - timedelta(hours=24)).timestamp()
    elif period == "7d":
        return (now - timedelta(days=7)).timestamp()
    elif period == "30d":
        return (now - timedelta(days=30)).timestamp()
    return None  # "all" - no filter


def get_slowest_tests(runs: list[dict], limit: int = 10) -> list[dict]:
    """Get tests with highest average execution time."""
    test_durations = defaultdict(list)
    for run in runs:
        if run.get("duration") and run.get("spec_name"):
            test_durations[run["spec_name"]].append(run["duration"])

    results = []
    for spec_name, durations in test_durations.items():
        results.append(
            {
                "spec_name": spec_name,
                "avg_duration": round(sum(durations) / len(durations), 1),
                "run_count": len(durations),
                "max_duration": round(max(durations), 1),
            }
        )

    return sorted(results, key=lambda x: x["avg_duration"], reverse=True)[:limit]


def get_flaky_tests(runs: list[dict], min_runs: int = 3) -> list[dict]:
    """Get tests that have both passes and failures (flaky)."""
    test_results = defaultdict(lambda: {"passed": 0, "failed": 0})
    for run in runs:
        if run.get("spec_name") and run.get("status"):
            if run["status"] in ("passed", "completed"):
                test_results[run["spec_name"]]["passed"] += 1
            elif run["status"] == "failed":
                test_results[run["spec_name"]]["failed"] += 1

    flaky = []
    for spec_name, results in test_results.items():
        total = results["passed"] + results["failed"]
        if total >= min_runs and results["passed"] > 0 and results["failed"] > 0:
            # Flakiness rate: how inconsistent the results are (higher = more flaky)
            flakiness = min(results["passed"], results["failed"]) / total * 100
            flaky.append(
                {
                    "spec_name": spec_name,
                    "passed": results["passed"],
                    "failed": results["failed"],
                    "total": total,
                    "flakiness_rate": round(flakiness * 2, 1),  # Scale to 0-100%
                }
            )

    return sorted(flaky, key=lambda x: x["flakiness_rate"], reverse=True)


def extract_spec_name(run_id: str, run_data: dict) -> str | None:
    """Extract spec name from run data or directory name."""
    # First try testName from run data
    if run_data.get("testName"):
        return run_data["testName"]

    # Try to extract from directory name (format: 2026-01-08_00-06-45_spec_name.md)
    parts = run_id.split("_", 2)
    if len(parts) >= 3:
        spec_part = parts[2]
        # Remove .md extension if present
        if spec_part.endswith(".md"):
            spec_part = spec_part[:-3]
        return spec_part.replace("_", " ").title()

    return None


@router.get("/dashboard")
def get_dashboard_stats(
    period: str = Query("7d", regex="^(24h|7d|30d|all)$"), project_id: str | None = Query(default=None)
) -> dict[str, Any]:
    """
    Aggregates statistics from all runs in the runs directory.
    Supports period filtering: 24h, 7d, 30d, or all.
    Optionally filters by project_id.
    """
    global _dashboard_cache

    # Check TTL cache first
    cache_key = f"dashboard:{project_id}:{period}"
    cached = _dashboard_cache.get(cache_key)
    if cached:
        data, ts = cached
        if _time.time() - ts < _DASHBOARD_CACHE_TTL:
            return data

    # Import here to avoid circular imports
    from .db import get_session
    from .models_db import TestRun as DBTestRun

    runs_dir = RUNS_DIR
    period_start = get_period_start_timestamp(period)

    # Data structures for aggregation
    daily_stats = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0, "duration_sum": 0, "duration_count": 0})
    error_counts = Counter()
    runs_list = []
    all_durations = []

    # Get project-filtered run IDs if project_id is specified
    project_run_ids = None
    if project_id:
        session = next(get_session())
        try:
            # Query runs for this project
            query = select(DBTestRun.id).where(DBTestRun.project_id == project_id)
            # Include runs with null project_id for "default" project
            if project_id == "default":
                query = select(DBTestRun.id).where(
                    (DBTestRun.project_id == project_id) | (DBTestRun.project_id == None)
                )
            project_run_ids = set(session.exec(query).all())
        finally:
            session.close()

    total_specs = 0
    # Process Specs - count all specs by project if specified
    if project_id:
        session = next(get_session())
        try:
            # Count all specs (not just automated) for this project
            total_specs = _count_all_specs_for_project(project_id, session)
        finally:
            session.close()
    else:
        # No project filter - count all specs from filesystem
        if SPECS_DIR.exists():
            total_specs = len(list(SPECS_DIR.glob("**/*.md")))

    if not runs_dir.exists():
        return {
            "total_specs": total_specs,
            "total_runs": 0,
            "success_rate": 0,
            "pass_rate": 0,
            "avg_duration_seconds": 0,
            "slowest_test_duration": 0,
            "flaky_test_count": 0,
            "last_run": "Never",
            "trends": [],
            "errors": [],
            "slowest_tests": [],
            "flaky_tests": [],
            "period": period,
        }

    # Build a cache of database runs for fallback when run.json doesn't exist
    # Only query DB for runs that exist on filesystem to avoid loading ALL runs
    db_runs_cache = {}
    if project_id:
        fs_run_ids = [d.name for d in runs_dir.iterdir() if d.is_dir()] if runs_dir.exists() else []
        if fs_run_ids:
            session = next(get_session())
            try:
                batch_size = 500
                for i in range(0, len(fs_run_ids), batch_size):
                    batch = fs_run_ids[i : i + batch_size]
                    query = select(DBTestRun).where(DBTestRun.id.in_(batch))
                    if project_id != "default":
                        query = query.where(DBTestRun.project_id == project_id)
                    else:
                        query = query.where((DBTestRun.project_id == project_id) | (DBTestRun.project_id == None))
                    for db_run in session.exec(query).all():
                        db_runs_cache[db_run.id] = db_run
            finally:
                session.close()

    # Track which runs we've processed (from filesystem)
    processed_run_ids = set()

    # Iterate through all run directories
    for run_path in runs_dir.iterdir():
        if not run_path.is_dir():
            continue

        run_id = run_path.name
        run_file = run_path / "run.json"
        run_data = None

        # Try to read from run.json first
        if run_file.exists():
            try:
                run_data = json.loads(run_file.read_text())
            except Exception as e:
                logger.debug(f"Skipping file in metrics scan: {e}")

        # Fallback to database if run.json doesn't exist but run is in project
        if run_data is None and run_id in db_runs_cache:
            db_run = db_runs_cache[run_id]
            # Calculate duration from timestamps
            duration_secs = 0
            if db_run.created_at and db_run.completed_at:
                duration_secs = (db_run.completed_at - db_run.created_at).total_seconds()

            # Get error message from database first, then try validation.json
            error_msg = db_run.error_message or ""
            if not error_msg and db_run.status == "failed":
                validation_file = run_path / "validation.json"
                if validation_file.exists():
                    try:
                        val_data = json.loads(validation_file.read_text())
                        error_msg = val_data.get("error") or val_data.get("message") or ""
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON in validation file {validation_file}: {e}")
                    except OSError as e:
                        logger.warning(f"Cannot read validation file {validation_file}: {e}")

            run_data = {
                "finalState": db_run.status or "unknown",
                "duration": duration_secs,
                "testName": db_run.spec_name or run_id,
                "steps": [],
                "_validation_error": error_msg,
            }

        # Fallback to validation.json if neither run.json nor database has data
        if run_data is None:
            validation_file = run_path / "validation.json"
            if validation_file.exists():
                try:
                    val_data = json.loads(validation_file.read_text())
                    val_status = val_data.get("status", "unknown")
                    # Map validation status to finalState
                    if val_status == "success":
                        final_state = "passed"
                    elif val_status == "failed":
                        final_state = "failed"
                    else:
                        final_state = val_status
                    run_data = {
                        "finalState": final_state,
                        "duration": 0,
                        "testName": run_id,
                        "steps": [],
                        "_validation_error": val_data.get("error") or val_data.get("message") or "",
                    }
                except Exception as e:
                    logger.debug(f"Skipping file in metrics scan: {e}")

        if run_data is None:
            continue

        processed_run_ids.add(run_id)

        try:
            timestamp = 0
            date_str = "Unknown"

            # Parse timestamp from directory name
            try:
                # Handle both formats: "2026-01-08_12-47-09" and "2026-01-08_00-06-45_spec_name.md"
                time_part = "_".join(run_id.split("_")[:2])
                dt = datetime.strptime(time_part, "%Y-%m-%d_%H-%M-%S")
                timestamp = dt.timestamp()
                date_str = dt.strftime("%Y-%m-%d")
            except ValueError:
                timestamp = os.path.getmtime(run_path)
                date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")

            # Apply period filter
            if period_start and timestamp < period_start:
                continue

            # Apply project filter
            if project_run_ids is not None and run_id not in project_run_ids:
                continue

            status = run_data.get("finalState", "unknown")
            duration = run_data.get("duration", 0)
            spec_name = extract_spec_name(run_id, run_data)

            # Track durations for overall average
            if duration and duration > 0:
                all_durations.append(duration)

            # --- Aggregate Daily Trends ---
            daily_stats[date_str]["total"] += 1

            # Treat "passed" and "completed" as success
            if status in ("passed", "completed", "success"):
                daily_stats[date_str]["passed"] += 1
                daily_stats[date_str]["duration_sum"] += duration
                daily_stats[date_str]["duration_count"] += 1
            # Handle stopped/cancelled runs - count as failed but don't add to error chart
            # (they're not real errors, just user-cancelled runs)
            elif status in ("stopped", "cancelled", "aborted"):
                daily_stats[date_str]["failed"] += 1
                # Don't add to error_counts - excluded from error categorization chart
            # Handle unknown/incomplete runs
            elif status in ("unknown", "pending", "running"):
                # Don't count incomplete runs in error stats
                pass
            else:
                # Actual failures - try to categorize the error
                daily_stats[date_str]["failed"] += 1

                error_found = False
                error_msg = ""

                # 1. Check steps array for errors
                for step in run_data.get("steps", []):
                    if step.get("error") and str(step.get("error")).strip():
                        error_msg = step.get("error", "")
                        error_found = True
                        break

                # 2. Check root-level error fields in run_data (including _validation_error from fallback)
                if not error_found:
                    for field in ["error", "errorMessage", "message", "failureMessage", "_validation_error"]:
                        if run_data.get(field) and str(run_data.get(field)).strip():
                            error_msg = str(run_data.get(field))
                            error_found = True
                            break

                # 3. Check validation.json for detailed errors (always try, not just for non-database runs)
                if not error_found:
                    validation_file = run_path / "validation.json"
                    if validation_file.exists():
                        try:
                            val_data = json.loads(validation_file.read_text())
                            # Check multiple possible error fields in validation
                            for field in ["error", "errorMessage", "message", "failure_reason"]:
                                if val_data.get(field) and str(val_data.get(field)).strip():
                                    error_msg = str(val_data.get(field))
                                    error_found = True
                                    break
                            # Also check validation steps
                            if not error_found:
                                for step in val_data.get("steps", []):
                                    if step.get("error"):
                                        error_msg = step.get("error", "")
                                        error_found = True
                                        break
                        except Exception as e:
                            logger.debug(f"Skipping file in metrics scan: {e}")

                # 4. Categorize the error
                if error_found and error_msg.strip():
                    cat = categorize_error(error_msg)
                    error_counts[cat] += 1
                # Don't count runs without error info in the error chart
                # (they're likely incomplete or legacy runs without proper tracking)

            runs_list.append(
                {
                    "id": run_id,
                    "date": date_str,
                    "status": status,
                    "duration": duration,
                    "timestamp": timestamp,
                    "spec_name": spec_name,
                }
            )

        except Exception as e:
            logger.warning(f"Error processing run {run_path}: {e}")
            continue

    # Format Output
    trends = []
    for date, stats in sorted(daily_stats.items()):
        avg_duration = 0
        if stats["duration_count"] > 0:
            avg_duration = stats["duration_sum"] / stats["duration_count"]

        trends.append(
            {
                "date": date,
                "total": stats["total"],
                "passed": stats["passed"],
                "failed": stats["failed"],
                "avg_duration": round(avg_duration, 2),
            }
        )

    errors = [{"category": k, "count": v} for k, v in error_counts.most_common(5)]

    # Calculate aggregates
    total_runs = len(runs_list)
    passed_runs = sum(1 for r in runs_list if r["status"] == "passed")
    pass_rate = round((passed_runs / total_runs * 100), 1) if total_runs > 0 else 0
    avg_duration = round(sum(all_durations) / len(all_durations), 1) if all_durations else 0

    # Calculate slowest and flaky tests
    slowest_tests = get_slowest_tests(runs_list, limit=10)
    flaky_tests = get_flaky_tests(runs_list, min_runs=2)  # Lower threshold for better detection

    last_run = "Never"
    if runs_list:
        # Sort by timestamp desc
        last_run_obj = sorted(runs_list, key=lambda x: x["timestamp"], reverse=True)[0]
        last_run = last_run_obj["id"]

    # Calculate actual test counts (individual tests in test files)
    actual_total_tests, total_test_files = 0, 0
    if TESTS_DIR.exists():
        if project_id:
            # Project-scoped test counting
            session = next(get_session())
            try:
                actual_total_tests, total_test_files = get_project_test_count(
                    project_id, str(TESTS_DIR), str(SPECS_DIR), session
                )
            finally:
                session.close()
        else:
            # Global test counting (no project filter)
            actual_total_tests, total_test_files = get_total_test_count(str(TESTS_DIR))

    result = {
        "total_specs": total_specs,
        "total_runs": total_runs,
        "success_rate": pass_rate,  # Keep for backward compatibility
        "pass_rate": pass_rate,
        "avg_duration_seconds": avg_duration,
        "slowest_test_duration": slowest_tests[0]["avg_duration"] if slowest_tests else 0,
        "flaky_test_count": len(flaky_tests),
        "last_run": last_run,
        "trends": trends,
        "errors": errors,
        "slowest_tests": slowest_tests,
        "flaky_tests": flaky_tests,
        "period": period,
        "healing_stats": get_healing_stats(runs_dir, period_start),
        "time_of_day_analysis": get_time_of_day_analysis(runs_list),
        "failure_patterns": get_failure_patterns(runs_dir, period_start),
        "test_growth_trends": get_test_growth_trends(runs_dir, SPECS_DIR, TESTS_DIR, period_start),
        # Actual test counts
        "actual_total_tests": actual_total_tests,
        "total_test_files": total_test_files,
    }

    # Store in cache
    _dashboard_cache[cache_key] = (result, _time.time())
    # Evict stale entries to prevent memory leak
    if len(_dashboard_cache) > 100:
        now = _time.time()
        _dashboard_cache = {k: v for k, v in _dashboard_cache.items() if now - v[1] < _DASHBOARD_CACHE_TTL * 2}

    return result
