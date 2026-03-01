"""
Playwright JSON Reporter Output Parser

Parses the structured JSON output from Playwright's JSON reporter
into a normalized summary with per-test pass/fail, error messages,
durations, stack traces, and error categorization.
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Error category patterns
ERROR_CATEGORIES = {
    "auth": [
        r"40[13]",
        r"unauthorized",
        r"forbidden",
        r"authentication",
        r"auth.?fail",
        r"invalid.?token",
        r"expired.?token",
        r"access.?denied",
    ],
    "connectivity": [
        r"ECONNREFUSED",
        r"ECONNRESET",
        r"ENOTFOUND",
        r"ETIMEDOUT",
        r"fetch failed",
        r"network.?error",
        r"connection.?refused",
        r"DNS.?resolution",
    ],
    "assertion": [
        r"expect\(",
        r"toEqual",
        r"toBe\(",
        r"toContain",
        r"toHaveProperty",
        r"toMatch",
        r"Expected.*received",
        r"AssertionError",
        r"expected.*to\s+(be|equal|contain|match|have)",
    ],
    "timeout": [
        r"TimeoutError",
        r"Timeout.*exceeded",
        r"timed?\s*out",
        r"waiting.*timeout",
        r"navigation.*timeout",
    ],
    "not_found": [
        r"404",
        r"not\s+found",
        r"endpoint.*not.*exist",
        r"route.*not.*found",
    ],
    "server_error": [
        r"5\d{2}",
        r"internal\s+server\s+error",
        r"bad\s+gateway",
        r"service\s+unavailable",
    ],
}


def categorize_error(error_message: str) -> str:
    """Categorize an error message into a known category."""
    if not error_message:
        return "unknown"

    lower_msg = error_message.lower()
    for category, patterns in ERROR_CATEGORIES.items():
        for pattern in patterns:
            if re.search(pattern, lower_msg, re.IGNORECASE):
                return category

    return "unknown"


def parse_test_results(json_path: str) -> dict | None:
    """
    Parse Playwright JSON reporter output into structured summary.

    Args:
        json_path: Path to the test-results.json file

    Returns:
        Dict with structure:
        {
            "summary": {"total": N, "passed": N, "failed": N, "skipped": N, "flaky": N},
            "duration_ms": N,
            "tests": [
                {
                    "title": "test name",
                    "full_title": "suite > test name",
                    "status": "passed|failed|skipped|timedOut",
                    "duration_ms": N,
                    "error": {"message": "...", "stack": "...", "category": "auth|..."},
                    "retry": N,
                    "file": "path/to/test.spec.ts",
                }
            ],
            "error_summary": {"auth": N, "assertion": N, ...},
            "first_failure": "First test failure message or null",
        }
    """
    path = Path(json_path)
    if not path.exists():
        logger.debug(f"Test results file not found: {json_path}")
        return None

    try:
        data = json.loads(path.read_text(errors="replace"))
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Failed to parse test results JSON: {e}")
        return None

    suites = data.get("suites", [])
    tests = []
    _extract_tests_from_suites(suites, tests, parent_titles=[])

    # Build summary
    passed = sum(1 for t in tests if t["status"] == "passed")
    failed = sum(1 for t in tests if t["status"] in ("failed", "timedOut"))
    skipped = sum(1 for t in tests if t["status"] == "skipped")
    flaky = sum(1 for t in tests if t.get("status") == "flaky")
    total = len(tests)

    # Error categorization
    error_summary: dict[str, int] = {}
    first_failure = None
    for t in tests:
        if t.get("error") and t["error"].get("category"):
            cat = t["error"]["category"]
            error_summary[cat] = error_summary.get(cat, 0) + 1
        if t["status"] in ("failed", "timedOut") and not first_failure:
            first_failure = t.get("error", {}).get("message", "Test failed")

    # Total duration
    total_duration = sum(t.get("duration_ms", 0) for t in tests)

    return {
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "flaky": flaky,
        },
        "duration_ms": total_duration,
        "tests": tests,
        "error_summary": error_summary,
        "first_failure": first_failure,
    }


def _extract_tests_from_suites(suites: list[dict], tests: list[dict], parent_titles: list[str]) -> None:
    """Recursively extract test results from nested suite structure."""
    for suite in suites:
        suite_title = suite.get("title", "")
        current_titles = parent_titles + ([suite_title] if suite_title else [])

        # Process specs within suite
        for spec in suite.get("specs", []):
            spec_title = spec.get("title", "Unknown test")
            full_title = " > ".join(current_titles + [spec_title])

            # Each spec can have multiple test results (retries)
            # Take the last result as the final outcome
            for test_entry in spec.get("tests", []):
                results = test_entry.get("results", [])
                if not results:
                    continue

                # Use the last result (final attempt)
                final_result = results[-1]
                status = final_result.get("status", "unknown")

                # Map Playwright statuses
                if status == "interrupted":
                    status = "failed"

                # Extract error info
                error_info = None
                error_data = final_result.get("error", {})
                if error_data:
                    error_msg = error_data.get("message", "")
                    error_stack = error_data.get("stack", "")
                    # Clean up ANSI escape codes
                    error_msg = _strip_ansi(error_msg)
                    error_stack = _strip_ansi(error_stack)
                    error_info = {
                        "message": error_msg[:500] if error_msg else "",
                        "stack": error_stack[:2000] if error_stack else "",
                        "category": categorize_error(error_msg + " " + error_stack),
                    }

                # Also check for errors in earlier results if final passed (flaky)
                if not error_info and status in ("failed", "timedOut"):
                    for r in results:
                        if r.get("error"):
                            err = r["error"]
                            msg = _strip_ansi(err.get("message", ""))
                            stack = _strip_ansi(err.get("stack", ""))
                            error_info = {
                                "message": msg[:500],
                                "stack": stack[:2000],
                                "category": categorize_error(msg + " " + stack),
                            }
                            break

                # Determine file path from test location
                file_path = spec.get("file", test_entry.get("projectName", ""))

                tests.append(
                    {
                        "title": spec_title,
                        "full_title": full_title,
                        "status": status,
                        "duration_ms": final_result.get("duration", 0),
                        "error": error_info,
                        "retry": len(results) - 1,
                        "file": file_path,
                    }
                )

        # Recurse into nested suites
        _extract_tests_from_suites(suite.get("suites", []), tests, current_titles)


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    if not text:
        return ""
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


def get_first_failure_message(json_path: str) -> str | None:
    """
    Quick helper to get just the first failure message from test results.
    Useful for updating DB error_message without full parsing.
    """
    results = parse_test_results(json_path)
    if results:
        return results.get("first_failure")
    return None
