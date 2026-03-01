"""
K6 Result Parser

Parses K6 output files:
- --summary-export JSON files (aggregate metrics)
- --out json= JSONL files (time-series data for charts)
"""

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _get_metric_values(metric_data: dict[str, Any]) -> dict[str, Any]:
    """Extract metric values handling both K6 output formats.

    handleSummary() format: {"type":"trend","values":{"avg":123,...}}
    --summary-export format: {"avg":123,"count":5,"thresholds":{...}} (flat)
    """
    if not isinstance(metric_data, dict):
        return {}
    if "values" in metric_data:
        return metric_data["values"]
    # Flat format (--summary-export) - the dict itself contains the values
    return metric_data


def parse_summary(summary_path: str) -> dict[str, Any]:
    """Parse a K6 --summary-export JSON file into structured metrics.

    Returns dict with keys:
        overview: {total_requests, failed_requests, avg_response_time_ms, ...}
        thresholds: {name: {ok: bool, ...}, ...}
        checks: [{name, passes, fails, rate}, ...]
        http_status_counts: {200: count, 404: count, ...}
        metrics_raw: full metrics dict from K6
    """
    path = Path(summary_path)
    if not path.exists():
        logger.warning(f"Summary file not found: {summary_path}")
        return _empty_summary()

    try:
        content = path.read_text(errors="replace").strip()
        if not content:
            logger.warning(f"Summary file is empty: {summary_path}")
            return _empty_summary()
        data = json.loads(content)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to parse summary file {summary_path}: {e}")
        return _empty_summary()

    metrics = data.get("metrics", {})

    # Extract core HTTP duration metrics
    # handleSummary() format wraps values: {"type":"trend","values":{"avg":123,...}}
    # --summary-export format is flat: {"avg":123,"count":5,"thresholds":{...}}
    # When both target the same file, --summary-export wins (writes last)
    http_dur = _get_metric_values(metrics.get("http_req_duration", {}))
    http_reqs = _get_metric_values(metrics.get("http_reqs", {}))
    http_failed = _get_metric_values(metrics.get("http_req_failed", {}))
    data_recv = _get_metric_values(metrics.get("data_received", {}))
    data_sent_m = _get_metric_values(metrics.get("data_sent", {}))
    vus_m = _get_metric_values(metrics.get("vus", {}))
    iterations_m = _get_metric_values(metrics.get("iterations", {}))

    total_requests = int(http_reqs.get("count", 0))
    # http_req_failed "passes" = requests that matched the fail condition (i.e., actually failed)
    failed_count = int(http_failed.get("passes", 0))

    overview = {
        "total_requests": total_requests,
        "failed_requests": failed_count,
        "avg_response_time_ms": round(http_dur.get("avg", 0), 2),
        "min_response_time_ms": round(http_dur.get("min", 0), 2),
        "max_response_time_ms": round(http_dur.get("max", 0), 2),
        "p50_response_time_ms": round(http_dur["med"], 2) if "med" in http_dur else None,
        "p90_response_time_ms": round(http_dur["p(90)"], 2) if "p(90)" in http_dur else None,
        "p95_response_time_ms": round(http_dur["p(95)"], 2) if "p(95)" in http_dur else None,
        "p99_response_time_ms": round(http_dur["p(99)"], 2) if "p(99)" in http_dur else None,
        "requests_per_second": round(http_reqs.get("rate", 0), 2),
        "data_received_bytes": int(data_recv.get("count", 0)),
        "data_sent_bytes": int(data_sent_m.get("count", 0)),
        "vus_max": int(vus_m.get("max", 0)),
        "iterations": int(iterations_m.get("count", 0)),
        "error_rate": round(http_failed.get("rate", 0), 6),
    }

    # Thresholds - two possible locations:
    #   handleSummary(): top-level "thresholds" key (not present in --summary-export)
    #   --summary-export: embedded inside each metric as metric.thresholds
    thresholds_raw = data.get("thresholds", {})
    thresholds = {}
    all_passed = True

    if thresholds_raw:
        # handleSummary() format: {"http_req_duration{\"p(95)<3000\"}": {"ok": true}}
        for name, detail in thresholds_raw.items():
            ok = detail.get("ok", False) if isinstance(detail, dict) else bool(detail)
            thresholds[name] = {"ok": ok}
            if not ok:
                all_passed = False
    else:
        # --summary-export format: thresholds inside each metric
        # e.g. metrics.http_reqs.thresholds = {"rate>2": true}
        # where true = threshold was crossed (failed)
        for metric_name, metric_data in metrics.items():
            if not isinstance(metric_data, dict):
                continue
            metric_thresholds = metric_data.get("thresholds", {})
            if not isinstance(metric_thresholds, dict):
                continue
            for thresh_name, crossed in metric_thresholds.items():
                ok = not bool(crossed)  # crossed=true means failed
                thresholds[f"{metric_name}{{{thresh_name}}}"] = {"ok": ok}
                if not ok:
                    all_passed = False

    # Checks from root_group
    checks = _extract_checks(data.get("root_group", {}))

    # Checks metric for overall rate
    checks_metric = _get_metric_values(metrics.get("checks", {}))

    # HTTP status counts - not directly in summary export, derive from tags if available
    http_status_counts = {}

    return {
        "overview": overview,
        "thresholds": thresholds,
        "thresholds_passed": all_passed if thresholds else None,
        "checks": checks,
        "checks_rate": round(checks_metric.get("rate", 0), 4) if checks_metric else None,
        "http_status_counts": http_status_counts,
        "metrics_raw": metrics,
    }


def _extract_checks(group: dict[str, Any]) -> list[dict[str, Any]]:
    """Recursively extract checks from root_group and nested groups."""
    checks = []
    raw_checks = group.get("checks", [])

    # handleSummary() gives dicts keyed by name; --summary-export gives arrays
    if isinstance(raw_checks, dict):
        for name, detail in raw_checks.items():
            if not isinstance(detail, dict):
                continue
            passes = detail.get("passes", 0)
            fails = detail.get("fails", 0)
            total = passes + fails
            checks.append(
                {
                    "name": name,
                    "passes": passes,
                    "fails": fails,
                    "rate": round(passes / total, 4) if total > 0 else 0,
                }
            )
    elif isinstance(raw_checks, list):
        for check in raw_checks:
            if not isinstance(check, dict):
                continue
            passes = check.get("passes", 0)
            fails = check.get("fails", 0)
            total = passes + fails
            checks.append(
                {
                    "name": check.get("name", "unknown"),
                    "passes": passes,
                    "fails": fails,
                    "rate": round(passes / total, 4) if total > 0 else 0,
                }
            )

    # Recurse into sub-groups (also may be dict or list)
    raw_groups = group.get("groups", [])
    if isinstance(raw_groups, dict):
        for sub_group in raw_groups.values():
            if isinstance(sub_group, dict):
                checks.extend(_extract_checks(sub_group))
    elif isinstance(raw_groups, list):
        for sub_group in raw_groups:
            if isinstance(sub_group, dict):
                checks.extend(_extract_checks(sub_group))

    return checks


def _empty_summary() -> dict[str, Any]:
    """Return empty summary structure."""
    return {
        "overview": {
            "total_requests": 0,
            "failed_requests": 0,
            "avg_response_time_ms": 0,
            "min_response_time_ms": 0,
            "max_response_time_ms": 0,
            "p50_response_time_ms": 0,
            "p90_response_time_ms": 0,
            "p95_response_time_ms": 0,
            "p99_response_time_ms": 0,
            "requests_per_second": 0,
            "data_received_bytes": 0,
            "data_sent_bytes": 0,
            "vus_max": 0,
            "iterations": 0,
            "error_rate": 0,
        },
        "thresholds": {},
        "thresholds_passed": None,
        "checks": [],
        "checks_rate": None,
        "http_status_counts": {},
        "metrics_raw": {},
    }


def parse_jsonl_timeseries(
    jsonl_path: str,
    sample_interval_ms: int = 1000,
) -> list[dict[str, Any]]:
    """Parse K6 --out json= JSONL file into time-bucketed series for charting.

    Each line in the JSONL file looks like:
        {"type":"Point","metric":"http_req_duration","data":{"time":"...","value":180.5,"tags":{...}}}

    Returns list of time buckets:
        [
            {
                "timestamp": "2024-01-01T00:00:01.000Z",
                "response_time_avg": 180.5,
                "response_time_p95": 250.0,
                "throughput": 42,
                "vus": 10,
                "error_rate": 0.02,
                "error_count": 1,
                "request_count": 42,
            },
            ...
        ]
    """
    path = Path(jsonl_path)
    if not path.exists():
        logger.warning(f"JSONL file not found: {jsonl_path}")
        return []

    # Collect data points by time bucket
    buckets: dict[str, dict[str, list]] = defaultdict(
        lambda: {
            "durations": [],
            "vus": [],
            "errors": 0,
            "requests": 0,
            "status_codes": defaultdict(int),
        }
    )

    line_count = 0
    parse_errors = 0

    try:
        with open(path, errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                line_count += 1
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue

                if entry.get("type") != "Point":
                    continue

                metric = entry.get("metric", "")
                data = entry.get("data", {})
                ts = data.get("time", "")
                value = data.get("value", 0)
                tags = data.get("tags", {})

                if not ts:
                    continue

                # Bucket by second (truncate to second)
                bucket_key = ts[:19] + "Z" if len(ts) > 19 else ts

                bucket = buckets[bucket_key]

                if metric == "http_req_duration":
                    bucket["durations"].append(value)
                elif metric == "http_reqs":
                    bucket["requests"] += int(value)
                    status = tags.get("status", "")
                    if status:
                        bucket["status_codes"][status] += 1
                elif metric == "http_req_failed":
                    if value == 1:
                        bucket["errors"] += 1
                elif metric == "vus":
                    bucket["vus"].append(int(value))

    except OSError as e:
        logger.error(f"Failed to read JSONL file {jsonl_path}: {e}")
        return []

    if parse_errors > 0:
        logger.warning(f"Skipped {parse_errors}/{line_count} malformed lines in {jsonl_path}")

    # Convert buckets to sorted timeseries
    timeseries = []
    for ts_key in sorted(buckets.keys()):
        bucket = buckets[ts_key]
        durations = bucket["durations"]
        request_count = bucket["requests"] if bucket["requests"] > 0 else len(durations)

        avg_rt = 0
        p95_rt = 0
        if durations:
            durations_sorted = sorted(durations)
            avg_rt = round(sum(durations_sorted) / len(durations_sorted), 2)
            p95_idx = min(int(len(durations_sorted) * 0.95), len(durations_sorted) - 1)
            p95_rt = round(durations_sorted[p95_idx], 2)

        vus_val = bucket["vus"][-1] if bucket["vus"] else 0
        error_count = bucket["errors"]
        error_rate = round(error_count / request_count, 4) if request_count > 0 else 0

        timeseries.append(
            {
                "timestamp": ts_key,
                "response_time_avg": avg_rt,
                "response_time_p95": p95_rt,
                "throughput": request_count,
                "vus": vus_val,
                "error_rate": error_rate,
                "error_count": error_count,
                "request_count": request_count,
            }
        )

    return timeseries


def extract_http_status_counts(jsonl_path: str) -> dict[str, int]:
    """Extract HTTP status code distribution from JSONL output.

    Returns dict like {"200": 4500, "404": 12, "500": 3}.
    """
    path = Path(jsonl_path)
    if not path.exists():
        return {}

    counts: dict[str, int] = defaultdict(int)
    try:
        with open(path, errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "Point":
                    continue
                if entry.get("metric") != "http_reqs":
                    continue
                status = entry.get("data", {}).get("tags", {}).get("status", "")
                if status:
                    counts[status] += 1
    except OSError:
        pass

    return dict(counts)
