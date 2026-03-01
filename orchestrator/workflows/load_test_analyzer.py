"""
Load Test Analyzer - AI-powered load test result analysis.

Uses Claude agent to analyze K6 load test metrics and provide:
1. Performance grading (A-F)
2. Bottleneck identification
3. Anomaly detection
4. Capacity estimation
5. Actionable recommendations

Follows the same pattern as security_analyzer.py using AgentRunner.
"""

import asyncio
import json
import sys
from pathlib import Path

# Setup path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from load_env import setup_claude_env
from logging_config import get_logger, setup_logging
from utils.agent_runner import AgentRunner
from utils.json_utils import extract_json_from_markdown

logger = get_logger(__name__)


async def analyze_load_test_run(run_data: dict) -> dict:
    """Analyze a completed load test run and generate performance insights.

    Args:
        run_data: Serialized LoadTestRun dict with metrics, thresholds, and HTTP status data.

    Returns:
        Dict with keys: summary, performance_grade, bottlenecks, anomalies,
        recommendations, capacity_estimate
    """
    setup_claude_env()

    # Build metrics section
    metrics_text = _format_metrics(run_data)
    thresholds_text = _format_thresholds(run_data)
    http_status_text = _format_http_status(run_data)
    endpoints_text = _format_endpoints(run_data)

    prompt = f"""Analyze the following K6 load test results and provide a comprehensive performance assessment.

## Test Configuration
- Spec: {run_data.get("spec_name", "Unknown")}
- Virtual Users: {run_data.get("vus", "N/A")}
- Duration: {run_data.get("duration", "N/A")}
- Actual Duration: {run_data.get("duration_seconds", "N/A")} seconds
- Workers: {run_data.get("worker_count", 1)}

## Core Metrics
{metrics_text}

## Threshold Results
{thresholds_text}

## HTTP Status Distribution
{http_status_text}

## Per-Endpoint Breakdown
{endpoints_text}

## Instructions
Analyze these results and respond with a JSON object:

```json
{{
    "summary": "Executive summary of load test performance (2-3 sentences)",
    "performance_grade": "A|B|C|D|F",
    "bottlenecks": [
        {{
            "area": "Area name (e.g., API endpoint, database, network)",
            "issue": "Description of the bottleneck",
            "severity": "critical|high|medium|low",
            "recommendation": "Specific fix or investigation step"
        }}
    ],
    "anomalies": [
        {{
            "metric": "Metric name",
            "observation": "What was observed",
            "possible_cause": "Likely explanation"
        }}
    ],
    "recommendations": [
        {{
            "priority": 1,
            "title": "Recommendation title",
            "description": "Detailed recommendation",
            "expected_impact": "Expected improvement"
        }}
    ],
    "capacity_estimate": {{
        "current_max_rps": <number based on observed data>,
        "estimated_breaking_point_vus": <number>,
        "confidence": "high|medium|low"
    }}
}}
```

Focus on actionable insights. Use SRE best practices. Grade conservatively.
"""

    runner = AgentRunner(
        timeout_seconds=120,
        allowed_tools=[],  # No tools needed for analysis
        log_tools=False,
    )
    result = await runner.run(prompt)

    if not result.success:
        error_msg = result.error or "Unknown error"
        if result.timed_out:
            raise RuntimeError(f"Load test analysis timed out: {error_msg}")
        raise RuntimeError(f"Load test analysis failed: {error_msg}")

    result_text = result.output

    if not result_text or not result_text.strip():
        raise RuntimeError("AI analysis returned empty result")

    try:
        parsed = extract_json_from_markdown(result_text)
        if isinstance(parsed, dict):
            return parsed
    except Exception as e:
        logger.warning(f"Failed to parse AI analysis as JSON: {e}")

    # Return raw text as summary if JSON parsing fails
    return {
        "summary": result_text[:1000],
        "performance_grade": "N/A",
        "bottlenecks": [],
        "anomalies": [],
        "recommendations": [],
        "capacity_estimate": {},
    }


def _format_metrics(run_data: dict) -> str:
    """Format core metrics for the prompt."""
    lines = []
    fields = [
        ("Total Requests", "total_requests"),
        ("Failed Requests", "failed_requests"),
        ("Requests/Second", "requests_per_second"),
        ("Peak RPS", "peak_rps"),
        ("Peak VUs", "peak_vus"),
        ("Avg Response Time (ms)", "avg_response_time_ms"),
        ("P50 Response Time (ms)", "p50_response_time_ms"),
        ("P90 Response Time (ms)", "p90_response_time_ms"),
        ("P95 Response Time (ms)", "p95_response_time_ms"),
        ("P99 Response Time (ms)", "p99_response_time_ms"),
        ("Max Response Time (ms)", "max_response_time_ms"),
        ("Min Response Time (ms)", "min_response_time_ms"),
        ("Data Received (bytes)", "data_received_bytes"),
        ("Data Sent (bytes)", "data_sent_bytes"),
    ]
    for label, key in fields:
        val = run_data.get(key)
        if val is not None:
            lines.append(f"- {label}: {val}")

    # Compute error rate
    total = run_data.get("total_requests", 0)
    failed = run_data.get("failed_requests", 0)
    if total and total > 0:
        error_rate = (failed / total) * 100
        lines.append(f"- Error Rate: {error_rate:.2f}%")

    return "\n".join(lines) if lines else "No metrics available."


def _format_thresholds(run_data: dict) -> str:
    """Format threshold results."""
    thresholds = run_data.get("thresholds_detail", {})
    if not thresholds:
        passed = run_data.get("thresholds_passed")
        if passed is not None:
            return f"Overall: {'PASSED' if passed else 'FAILED'}"
        return "No thresholds configured."

    lines = []
    for name, detail in thresholds.items():
        if isinstance(detail, dict):
            status = "PASS" if detail.get("ok") else "FAIL"
            lines.append(f"- {name}: {status}")
        else:
            lines.append(f"- {name}: {detail}")
    return "\n".join(lines)


def _format_http_status(run_data: dict) -> str:
    """Format HTTP status distribution."""
    status_counts = run_data.get("http_status_counts", {})
    if not status_counts:
        return "No HTTP status data available."

    lines = []
    for code, count in sorted(status_counts.items()):
        lines.append(f"- HTTP {code}: {count}")
    return "\n".join(lines)


def _format_endpoints(run_data: dict) -> str:
    """Format per-endpoint metrics from metrics_summary."""
    metrics = run_data.get("metrics_summary", {})
    if not metrics:
        return "No per-endpoint data available."

    lines = []
    for metric_name, metric_data in metrics.items():
        if not isinstance(metric_data, dict):
            continue
        # Look for http_req_duration-type metrics with URL tags
        if "values" in metric_data:
            values = metric_data["values"]
            if isinstance(values, dict):
                parts = []
                for k, v in values.items():
                    if v is not None:
                        parts.append(f"{k}={v}")
                if parts:
                    lines.append(f"- {metric_name}: {', '.join(parts[:6])}")
    return "\n".join(lines[:30]) if lines else "No per-endpoint data available."


if __name__ == "__main__":
    setup_logging()
    # Test with sample data
    sample_run = {
        "spec_name": "smoke-test.md",
        "vus": 10,
        "duration": "30s",
        "duration_seconds": 30,
        "total_requests": 1500,
        "failed_requests": 5,
        "avg_response_time_ms": 150.0,
        "p95_response_time_ms": 320.0,
        "p99_response_time_ms": 500.0,
        "requests_per_second": 50.0,
        "thresholds_passed": True,
        "thresholds_detail": {"http_req_duration{p95}": {"ok": True}},
        "http_status_counts": {"200": 1450, "201": 45, "500": 5},
        "metrics_summary": {},
    }
    result = asyncio.run(analyze_load_test_run(sample_run))
    print(json.dumps(result, indent=2))
