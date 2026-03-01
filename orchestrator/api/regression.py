"""
Regression Batch API Router

Provides endpoints for managing regression batches - groupings of related test runs
from a single bulk execution. Supports batch listing, details, refresh, and export.
"""

import base64
import csv
import io
import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, desc, select

from .db import get_session
from .models import (
    BatchExportResponse,
    BatchRunInList,
    RegressionBatchDetail,
    RegressionBatchListResponse,
    RegressionBatchSummary,
)
from .models_db import RegressionBatch
from .models_db import TestRun as DBTestRun

logger = logging.getLogger(__name__)

# Import test counter utility for accurate test counting
_test_counter_available = False
try:
    from ..utils.test_counter import count_tests_in_file, get_test_count_for_spec

    _test_counter_available = True
    logger.info("Test counter utility loaded successfully")
except Exception as e:
    # Fallback if utility not available
    logger.warning(f"Failed to import test_counter utility: {e}. Using fallback (1 test per file).")

    def count_tests_in_file(file_path: str) -> int:
        return 1

    def get_test_count_for_spec(spec_name: str, tests_dir: str = "tests/generated") -> int:
        return 1


router = APIRouter(prefix="/regression", tags=["regression"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = BASE_DIR / "runs"
TESTS_DIR = BASE_DIR / "tests" / "generated"


def _get_test_code_path(spec_name: str) -> Path | None:
    """Get the generated test file path for a spec.

    Handles various spec path formats:
    - Simple: "my-test.md" -> "my-test.spec.ts"
    - Nested: "folder/subfolder/my-test.md" -> "my-test.spec.ts"
    - With underscores: "folder_subfolder_my-test.md" -> "my-test.spec.ts"
    """
    # Normalize spec name - remove .md extension if present
    base_name = spec_name
    if base_name.endswith(".md"):
        base_name = base_name[:-3]

    # Extract just the filename (without directory path)
    # This handles nested specs like "myapp-manage-rooms/trip-package-management-tests/11-create-new-resource.md"
    filename_only = Path(base_name).name

    # Also prepare the full path with underscores for flat structure
    full_path_underscored = base_name.replace("/", "_").replace("\\", "_")

    # Try various possible test file names, prioritizing filename-only match
    possible_names = [
        # First try filename only (most common pattern)
        f"{filename_only}.spec.ts",
        f"{filename_only.replace('-', '_')}.spec.ts",
        f"{filename_only.replace('_', '-')}.spec.ts",
        # Then try full path with underscores
        f"{full_path_underscored}.spec.ts",
        f"{full_path_underscored.replace('-', '_')}.spec.ts",
        f"{full_path_underscored.replace('_', '-')}.spec.ts",
    ]

    # Check if TESTS_DIR exists
    if not TESTS_DIR.exists():
        logger.warning(f"Tests directory does not exist: {TESTS_DIR}")
        return None

    for name in possible_names:
        test_file = TESTS_DIR / name
        if test_file.exists():
            logger.debug(f"Found test file for spec '{spec_name}': {test_file}")
            return test_file

    # Try glob matching with filename only
    for test_file in TESTS_DIR.glob(f"*{filename_only}*.spec.ts"):
        logger.debug(f"Found test file via glob for spec '{spec_name}': {test_file}")
        return test_file

    # Try glob matching with full path
    for test_file in TESTS_DIR.glob(f"*{full_path_underscored}*.spec.ts"):
        logger.debug(f"Found test file via glob for spec '{spec_name}': {test_file}")
        return test_file

    logger.debug(f"No test file found for spec '{spec_name}'. Searched in {TESTS_DIR}")
    return None


def _count_tests_for_run(run: DBTestRun) -> int:
    """Count actual tests for a single run."""
    test_path = _get_test_code_path(run.spec_name)
    if test_path:
        return count_tests_in_file(str(test_path))
    return 1


def _calculate_actual_test_counts(runs: list[DBTestRun]) -> tuple[int, int, int]:
    """
    Calculate actual test counts by parsing test files.
    Batches filesystem lookups by unique spec name to avoid redundant I/O.

    Returns:
        Tuple of (actual_total, actual_passed, actual_failed)
    """
    actual_total = 0
    actual_passed = 0
    actual_failed = 0

    # Batch: compute test count per unique spec_name once
    spec_test_counts: dict[str, int] = {}
    for run in runs:
        if run.spec_name not in spec_test_counts:
            test_path = _get_test_code_path(run.spec_name)
            spec_test_counts[run.spec_name] = count_tests_in_file(str(test_path)) if test_path else 1

    for run in runs:
        test_count = spec_test_counts[run.spec_name]
        actual_total += test_count

        # For now, if the run passed, all tests passed; if failed, all failed
        # In the future, we can parse Playwright JSON reports for individual test results
        if run.status in ("passed", "completed"):
            actual_passed += test_count
        elif run.status in ("failed", "error"):
            actual_failed += test_count
        # stopped/running/queued don't contribute to passed/failed counts

    return actual_total, actual_passed, actual_failed


def _batch_to_summary(
    batch: RegressionBatch,
    actual_total: int | None = None,
    actual_passed: int | None = None,
    actual_failed: int | None = None,
) -> RegressionBatchSummary:
    """Convert database batch to summary response."""
    return RegressionBatchSummary(
        id=batch.id,
        name=batch.name,
        status=batch.status,
        created_at=batch.created_at.isoformat() if batch.created_at else None,
        completed_at=batch.completed_at.isoformat() if batch.completed_at else None,
        browser=batch.browser,
        tags_used=batch.tags_used,
        hybrid_mode=batch.hybrid_mode,
        total_tests=batch.total_tests,
        passed=batch.passed,
        failed=batch.failed,
        stopped=batch.stopped,
        running=batch.running,
        queued=batch.queued,
        success_rate=batch.success_rate,
        duration_seconds=batch.duration_seconds,
        actual_total_tests=actual_total,
        actual_passed=actual_passed,
        actual_failed=actual_failed,
        project_id=batch.project_id,
    )


def _run_to_batch_item(run: DBTestRun, test_count: int = 1) -> BatchRunInList:
    """Convert database run to batch run item."""
    duration = None
    if run.started_at and run.completed_at:
        duration = int((run.completed_at - run.started_at).total_seconds())

    return BatchRunInList(
        id=run.id,
        spec_name=run.spec_name,
        test_name=run.test_name,
        status=run.status,
        steps_completed=run.steps_completed,
        total_steps=run.total_steps,
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        error_message=run.error_message,
        duration_seconds=duration,
        actual_test_count=test_count,
    )


@router.get("/batches", response_model=RegressionBatchListResponse)
def list_batches(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, description="Filter by status: pending, running, completed"),
    project_id: str | None = Query(default=None, description="Filter by project ID"),
    include_actual_counts: bool = Query(
        default=False, description="Include actual test counts (slower when not cached)"
    ),
    session: Session = Depends(get_session),
):
    """
    List all regression batches with pagination.
    Newest batches first. Uses cached actual counts when available.
    """
    # Build query
    query = select(RegressionBatch)

    if status:
        query = query.where(RegressionBatch.status == status)

    if project_id:
        query = query.where(RegressionBatch.project_id == project_id)

    # Count total
    count_query = select(func.count()).select_from(RegressionBatch)
    if status:
        count_query = count_query.where(RegressionBatch.status == status)
    if project_id:
        count_query = count_query.where(RegressionBatch.project_id == project_id)
    total = session.exec(count_query).one()

    # Get paginated results
    query = query.order_by(desc(RegressionBatch.created_at)).offset(offset).limit(limit)
    batches = session.exec(query).all()

    # Build summaries with optional actual test counts
    summaries = []
    for batch in batches:
        actual_total, actual_passed, actual_failed = None, None, None

        # Use cached values from DB if available
        if batch.actual_total_tests is not None:
            actual_total = batch.actual_total_tests
            actual_passed = batch.actual_passed
            actual_failed = batch.actual_failed
        elif include_actual_counts:
            # Fallback: compute from disk (expensive)
            runs = session.exec(select(DBTestRun).where(DBTestRun.batch_id == batch.id)).all()
            actual_total, actual_passed, actual_failed = _calculate_actual_test_counts(runs)

        summaries.append(
            _batch_to_summary(
                batch, actual_total=actual_total, actual_passed=actual_passed, actual_failed=actual_failed
            )
        )

    return RegressionBatchListResponse(
        batches=summaries, total=total, limit=limit, offset=offset, has_more=(offset + len(batches)) < total
    )


@router.get("/batches/{batch_id}", response_model=RegressionBatchDetail)
def get_batch_detail(
    batch_id: str,
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
    session: Session = Depends(get_session),
):
    """
    Get detailed batch information including all runs.
    """
    batch = session.get(RegressionBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Filter by project_id if provided
    if project_id:
        if batch.project_id:
            if project_id == "default":
                if batch.project_id not in (None, "default"):
                    raise HTTPException(status_code=404, detail="Batch not found")
            elif batch.project_id != project_id:
                raise HTTPException(status_code=404, detail="Batch not found")

    # Get all runs for this batch
    runs_query = select(DBTestRun).where(DBTestRun.batch_id == batch_id)
    runs = session.exec(runs_query).all()

    # Calculate actual test counts
    actual_total, actual_passed, actual_failed = _calculate_actual_test_counts(runs)

    # Sort runs: failed first, then by status, then by name
    status_order = {"failed": 0, "stopped": 1, "running": 2, "queued": 3, "passed": 4, "completed": 4}
    runs_sorted = sorted(runs, key=lambda r: (status_order.get(r.status, 5), r.spec_name))

    # Build run items with actual test counts
    run_items = []
    for run in runs_sorted:
        test_count = _count_tests_for_run(run)
        run_items.append(_run_to_batch_item(run, test_count=test_count))

    return RegressionBatchDetail(
        id=batch.id,
        name=batch.name,
        status=batch.status,
        created_at=batch.created_at.isoformat() if batch.created_at else None,
        started_at=batch.started_at.isoformat() if batch.started_at else None,
        completed_at=batch.completed_at.isoformat() if batch.completed_at else None,
        browser=batch.browser,
        tags_used=batch.tags_used,
        hybrid_mode=batch.hybrid_mode,
        triggered_by=batch.triggered_by,
        total_tests=batch.total_tests,
        passed=batch.passed,
        failed=batch.failed,
        stopped=batch.stopped,
        running=batch.running,
        queued=batch.queued,
        success_rate=batch.success_rate,
        duration_seconds=batch.duration_seconds,
        actual_total_tests=actual_total,
        actual_passed=actual_passed,
        actual_failed=actual_failed,
        project_id=batch.project_id,
        runs=run_items,
    )


@router.patch("/batches/{batch_id}/refresh")
def refresh_batch_stats(batch_id: str, session: Session = Depends(get_session)):
    """
    Recalculate batch statistics from associated runs.
    Useful if stats get out of sync.
    """
    batch = session.get(RegressionBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Get all runs for this batch
    runs_query = select(DBTestRun).where(DBTestRun.batch_id == batch_id)
    runs = session.exec(runs_query).all()

    # Recalculate counts
    batch.total_tests = len(runs)
    batch.passed = sum(1 for r in runs if r.status in ("passed", "completed"))
    batch.failed = sum(1 for r in runs if r.status in ("failed", "error"))
    batch.stopped = sum(1 for r in runs if r.status == "stopped")
    batch.running = sum(1 for r in runs if r.status in ("running", "in_progress"))
    batch.queued = sum(1 for r in runs if r.status == "queued")

    # Update status
    if batch.running > 0 or batch.queued > 0:
        batch.status = "running"
    elif batch.total_tests > 0 and (batch.passed + batch.failed + batch.stopped) == batch.total_tests:
        batch.status = "completed"
        if not batch.completed_at:
            batch.completed_at = datetime.utcnow()
    elif batch.total_tests == 0:
        batch.status = "completed"
        if not batch.completed_at:
            batch.completed_at = datetime.utcnow()

    # Find earliest start and latest end
    started_runs = [r for r in runs if r.started_at]
    completed_runs = [r for r in runs if r.completed_at]

    if started_runs and not batch.started_at:
        batch.started_at = min(r.started_at for r in started_runs)

    if completed_runs and batch.status == "completed":
        batch.completed_at = max(r.completed_at for r in completed_runs)

    # Cache actual test counts (D1 performance fix)
    actual_total, actual_passed, actual_failed = _calculate_actual_test_counts(runs)
    batch.actual_total_tests = actual_total
    batch.actual_passed = actual_passed
    batch.actual_failed = actual_failed

    session.add(batch)
    session.commit()
    session.refresh(batch)

    return _batch_to_summary(batch, actual_total=actual_total, actual_passed=actual_passed, actual_failed=actual_failed)


def generate_batch_html_report(batch: RegressionBatch, tests: list[dict]) -> str:
    """Generate a standalone HTML report for the batch."""

    # Calculate stats
    passed_count = sum(1 for t in tests if t["status"] in ("passed", "completed"))
    failed_count = sum(1 for t in tests if t["status"] in ("failed", "error"))
    sum(1 for t in tests if t["status"] == "stopped")
    success_rate = round((passed_count / len(tests) * 100), 1) if tests else 0

    # Format dates
    created_at = batch.created_at.strftime("%b %d, %Y %I:%M %p") if batch.created_at else "-"
    batch.completed_at.strftime("%b %d, %Y %I:%M %p") if batch.completed_at else "-"

    # Format duration
    def format_duration(seconds):
        if not seconds:
            return "-"
        if seconds < 60:
            return f"{seconds}s"
        mins = seconds // 60
        secs = seconds % 60
        if mins < 60:
            return f"{mins}m {secs}s"
        hrs = mins // 60
        return f"{hrs}h {mins % 60}m"

    duration = format_duration(batch.duration_seconds)

    # Get success rate color
    def get_rate_color(rate):
        if rate >= 90:
            return "#10b981"
        if rate >= 70:
            return "#f59e0b"
        return "#ef4444"

    # Helper to escape HTML
    def escape_html(text):
        if not text:
            return ""
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    # Build test rows with expandable details
    test_rows = []
    for _idx, t in enumerate(tests):
        status = t["status"]
        status_color = {
            "passed": "#10b981",
            "completed": "#10b981",
            "failed": "#ef4444",
            "stopped": "#f59e0b",
            "running": "#3b82f6",
            "in_progress": "#3b82f6",
            "queued": "#f59e0b",
        }.get(status, "#6b7280")

        status_label = {
            "passed": "Passed",
            "completed": "Passed",
            "failed": "Failed",
            "stopped": "Stopped",
            "running": "Running",
            "in_progress": "Running",
            "queued": "Queued",
        }.get(status, status.title())

        test_duration = format_duration(t.get("duration_seconds"))
        test_name = escape_html(t.get("test_name") or t.get("spec_name", "-"))

        # Build run details section if available
        run_details_html = ""
        run_details = t.get("run_details")
        if run_details and run_details.get("steps"):
            steps_html = []
            for step in run_details["steps"]:
                step_num = step.get("stepNumber", step.get("step", "?"))
                action = escape_html(step.get("action", "-"))
                description = escape_html(step.get("description") or step.get("details", "-"))
                result = step.get("result", "unknown")
                selector = escape_html(step.get("selector", ""))
                error = escape_html(step.get("error", ""))
                screenshot_b64 = step.get("screenshot_base64", "")

                step_status_class = (
                    "success" if result == "success" else "failure" if result == "failure" else "pending"
                )

                screenshot_html = ""
                if screenshot_b64:
                    screenshot_html = f"""
                        <div class="screenshot-container">
                            <img class="screenshot-thumb"
                                 src="data:image/png;base64,{screenshot_b64}"
                                 alt="Step {step_num} screenshot"
                                 onclick="openModal(this.src)" />
                        </div>
                    """

                error_html = f'<div class="step-error">{error}</div>' if error else ""
                selector_html = f'<code class="step-selector">{selector}</code>' if selector else ""

                steps_html.append(f"""
                    <div class="step-item {step_status_class}">
                        <div class="step-header">
                            <span class="step-num">{step_num}</span>
                            <span class="step-action">{action}</span>
                            <span class="step-desc">{description}</span>
                            <span class="step-result-badge {step_status_class}">{result}</span>
                        </div>
                        {selector_html}
                        {error_html}
                        {screenshot_html}
                    </div>
                """)

            success_count = run_details.get(
                "successCount", sum(1 for s in run_details["steps"] if s.get("result") == "success")
            )
            total_count = len(run_details["steps"])
            run_details_html = f"""
                <div class="run-details-content">
                    <div class="run-summary">
                        <span class="run-summary-item">📊 {success_count}/{total_count} steps successful</span>
                        <span class="run-summary-item">🕐 Started: {run_details.get("startTime", "-")}</span>
                    </div>
                    <div class="steps-container">
                        {"".join(steps_html)}
                    </div>
                </div>
            """

        # Build the expandable test row
        has_details = bool(run_details_html)
        expand_indicator = '<span class="expand-icon">▶</span>' if has_details else ""

        test_rows.append(f"""
            <details class="test-details" {"open" if status == "failed" else ""}>
                <summary class="test-summary">
                    {expand_indicator}
                    <span class="test-name">{test_name}</span>
                    <span class="status-badge" style="background: {status_color}20; color: {status_color}; border: 1px solid {status_color}40">{status_label}</span>
                    <span class="test-meta">{t.get("steps_completed", 0)}/{t.get("total_steps", 0)} steps</span>
                    <span class="test-meta">{test_duration}</span>
                </summary>
                {run_details_html if has_details else '<div class="no-details">No detailed run data available</div>'}
            </details>
        """)

    # Build failure details
    failures_html = ""
    failed_tests = [t for t in tests if t["status"] == "failed" and t.get("error_message")]
    if failed_tests:
        failure_items = []
        for t in failed_tests:
            failure_items.append(f"""
                <div class="failure-item">
                    <div class="failure-header">{t.get("test_name") or t.get("spec_name", "-")}</div>
                    <pre class="failure-error">{t.get("error_message", "")}</pre>
                </div>
            """)
        failures_html = f"""
            <div class="section">
                <h2 class="section-title">
                    <span class="icon">⚠️</span> Failure Details ({len(failed_tests)} failed)
                </h2>
                {"".join(failure_items)}
            </div>
        """

    # Tags HTML
    tags_html = ""
    if batch.tags_used:
        tags = "".join(f'<span class="tag">{tag}</span>' for tag in batch.tags_used)
        tags_html = f'<div class="tags">{tags}</div>'

    # Hybrid mode badge
    hybrid_html = ""
    if batch.hybrid_mode:
        hybrid_html = '<span class="hybrid-badge">Extended Healing</span>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Batch Report - {batch.id}</title>
    <style>
        :root {{
            --bg: #0f172a;
            --surface: #1e293b;
            --surface-hover: #334155;
            --border: #334155;
            --text: #f1f5f9;
            --text-secondary: #94a3b8;
            --primary: #3b82f6;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --radius: 8px;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            padding: 2rem;
        }}

        .container {{
            max-width: 1100px;
            margin: 0 auto;
        }}

        header {{
            margin-bottom: 2rem;
        }}

        h1 {{
            font-size: 1.75rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }}

        .meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
            color: var(--text-secondary);
            font-size: 0.9rem;
            margin-bottom: 0.75rem;
        }}

        .meta-item {{
            display: flex;
            align-items: center;
            gap: 0.35rem;
        }}

        .tags {{
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }}

        .tag {{
            font-size: 0.8rem;
            padding: 0.2rem 0.6rem;
            border-radius: 9999px;
            background: rgba(59, 130, 246, 0.1);
            color: var(--primary);
            font-weight: 500;
        }}

        .hybrid-badge {{
            padding: 0.15rem 0.5rem;
            border-radius: 4px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-size: 0.75rem;
            font-weight: 500;
        }}

        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 1rem;
            margin-bottom: 2rem;
        }}

        .card {{
            background: var(--surface);
            border-radius: var(--radius);
            border: 1px solid var(--border);
        }}

        .stat-card {{
            padding: 1.25rem;
            text-align: center;
        }}

        .stat-card.success {{
            border-left: 3px solid var(--success);
        }}

        .stat-card.danger {{
            border-left: 3px solid var(--danger);
        }}

        .stat-value {{
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 0.25rem;
        }}

        .stat-label {{
            color: var(--text-secondary);
            font-size: 0.9rem;
        }}

        .section {{
            margin-bottom: 2rem;
        }}

        .section-title {{
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            background: var(--surface);
            border-radius: var(--radius);
            overflow: hidden;
        }}

        th {{
            background: var(--surface-hover);
            padding: 0.75rem 1.25rem;
            text-align: left;
            font-size: 0.8rem;
            font-weight: 600;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            border-bottom: 1px solid var(--border);
        }}

        td {{
            padding: 0.875rem 1.25rem;
            border-bottom: 1px solid var(--border);
            font-size: 0.9rem;
        }}

        tr:last-child td {{
            border-bottom: none;
        }}

        .test-name {{
            font-weight: 500;
        }}

        .center {{
            text-align: center;
            color: var(--text-secondary);
        }}

        .status-badge {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.25rem 0.6rem;
            border-radius: 9999px;
            font-size: 0.8rem;
            font-weight: 600;
        }}

        .error {{
            color: var(--danger);
            font-size: 0.85rem;
        }}

        .failure-item {{
            padding: 1rem;
            border-radius: var(--radius);
            background: rgba(239, 68, 68, 0.05);
            border: 1px solid rgba(239, 68, 68, 0.2);
            margin-bottom: 0.75rem;
        }}

        .failure-header {{
            font-weight: 600;
            font-size: 0.95rem;
            margin-bottom: 0.5rem;
        }}

        .failure-error {{
            margin: 0;
            padding: 0.75rem;
            border-radius: 4px;
            background: rgba(0, 0, 0, 0.2);
            font-size: 0.8rem;
            color: var(--danger);
            overflow: auto;
            max-height: 150px;
            white-space: pre-wrap;
            word-break: break-word;
            font-family: 'Monaco', 'Menlo', monospace;
        }}

        .footer {{
            margin-top: 3rem;
            padding-top: 1.5rem;
            border-top: 1px solid var(--border);
            color: var(--text-secondary);
            font-size: 0.85rem;
            text-align: center;
        }}

        /* Expandable test details */
        .test-details {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            margin-bottom: 0.5rem;
        }}

        .test-details[open] {{
            border-color: var(--primary);
        }}

        .test-details[open] .expand-icon {{
            transform: rotate(90deg);
        }}

        .test-summary {{
            padding: 0.875rem 1.25rem;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            list-style: none;
        }}

        .test-summary::-webkit-details-marker {{
            display: none;
        }}

        .test-summary:hover {{
            background: var(--surface-hover);
        }}

        .expand-icon {{
            color: var(--text-secondary);
            font-size: 0.7rem;
            transition: transform 0.2s;
        }}

        .test-summary .test-name {{
            font-weight: 500;
            flex: 1;
        }}

        .test-meta {{
            color: var(--text-secondary);
            font-size: 0.85rem;
        }}

        .run-details-content {{
            border-top: 1px solid var(--border);
            padding: 1rem 1.25rem;
        }}

        .run-summary {{
            display: flex;
            gap: 1.5rem;
            margin-bottom: 1rem;
            padding-bottom: 0.75rem;
            border-bottom: 1px solid var(--border);
        }}

        .run-summary-item {{
            font-size: 0.85rem;
            color: var(--text-secondary);
        }}

        .steps-container {{
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }}

        .step-item {{
            background: var(--bg);
            border-radius: 6px;
            padding: 0.875rem;
            border-left: 3px solid var(--border);
        }}

        .step-item.success {{
            border-left-color: var(--success);
        }}

        .step-item.failure {{
            border-left-color: var(--danger);
            background: rgba(239, 68, 68, 0.05);
        }}

        .step-item.pending {{
            border-left-color: var(--warning);
        }}

        .step-header {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            flex-wrap: wrap;
        }}

        .step-num {{
            background: var(--surface-hover);
            color: var(--text-secondary);
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.15rem 0.5rem;
            border-radius: 4px;
            min-width: 28px;
            text-align: center;
        }}

        .step-action {{
            font-weight: 500;
            color: var(--primary);
            font-size: 0.9rem;
        }}

        .step-desc {{
            color: var(--text);
            font-size: 0.9rem;
            flex: 1;
        }}

        .step-result-badge {{
            font-size: 0.75rem;
            padding: 0.15rem 0.5rem;
            border-radius: 4px;
            font-weight: 500;
        }}

        .step-result-badge.success {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--success);
        }}

        .step-result-badge.failure {{
            background: rgba(239, 68, 68, 0.15);
            color: var(--danger);
        }}

        .step-result-badge.pending {{
            background: rgba(245, 158, 11, 0.15);
            color: var(--warning);
        }}

        .step-selector {{
            display: block;
            margin-top: 0.5rem;
            padding: 0.5rem 0.75rem;
            background: var(--surface);
            border-radius: 4px;
            font-size: 0.8rem;
            color: var(--text-secondary);
            font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
            overflow-x: auto;
        }}

        .step-error {{
            margin-top: 0.5rem;
            padding: 0.5rem 0.75rem;
            background: rgba(239, 68, 68, 0.1);
            border-radius: 4px;
            font-size: 0.8rem;
            color: var(--danger);
            font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
        }}

        .screenshot-container {{
            margin-top: 0.75rem;
        }}

        .screenshot-thumb {{
            max-width: 300px;
            max-height: 180px;
            border-radius: 6px;
            border: 1px solid var(--border);
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .screenshot-thumb:hover {{
            transform: scale(1.02);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }}

        .no-details {{
            padding: 1rem 1.25rem;
            color: var(--text-secondary);
            font-style: italic;
            border-top: 1px solid var(--border);
        }}

        /* Screenshot modal */
        .modal {{
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.9);
            justify-content: center;
            align-items: center;
        }}

        .modal.active {{
            display: flex;
        }}

        .modal img {{
            max-width: 95%;
            max-height: 95%;
            border-radius: 8px;
        }}

        .modal-close {{
            position: absolute;
            top: 20px;
            right: 30px;
            color: white;
            font-size: 2rem;
            cursor: pointer;
            z-index: 1001;
        }}

        @media print {{
            body {{
                background: white;
                color: #1a1a1a;
            }}
            .card, .test-details {{
                background: #f8f8f8;
            }}
            .screenshot-thumb {{
                max-width: 200px;
            }}
        }}

        @media (max-width: 768px) {{
            .summary-cards {{
                grid-template-columns: repeat(2, 1fr);
            }}
            .test-summary {{
                flex-wrap: wrap;
            }}
            .screenshot-thumb {{
                max-width: 100%;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{batch.name or batch.id}</h1>
            <div class="meta">
                <span class="meta-item">📅 {created_at}</span>
                <span>|</span>
                <span class="meta-item">🌐 {batch.browser.title() if batch.browser else "Chromium"}</span>
                <span>|</span>
                <span class="meta-item">⏱️ Duration: {duration}</span>
                {hybrid_html}
            </div>
            {tags_html}
        </header>

        <div class="summary-cards">
            <div class="card stat-card">
                <div class="stat-value">{batch.total_tests}</div>
                <div class="stat-label">Total Tests</div>
            </div>
            <div class="card stat-card success">
                <div class="stat-value" style="color: var(--success)">{passed_count}</div>
                <div class="stat-label">Passed</div>
            </div>
            <div class="card stat-card danger">
                <div class="stat-value" style="color: var(--danger)">{failed_count}</div>
                <div class="stat-label">Failed</div>
            </div>
            <div class="card stat-card" style="border-left: 3px solid {get_rate_color(success_rate)}">
                <div class="stat-value" style="color: {get_rate_color(success_rate)}">{success_rate}%</div>
                <div class="stat-label">Success Rate</div>
            </div>
        </div>

        <div class="section">
            <h2 class="section-title">Test Results</h2>
            <div class="tests-list">
                {"".join(test_rows)}
            </div>
        </div>

        {failures_html}

        <div class="footer">
            Generated on {datetime.utcnow().strftime("%B %d, %Y at %I:%M %p UTC")} • Batch ID: {batch.id}
        </div>
    </div>

    <!-- Screenshot Modal -->
    <div id="screenshotModal" class="modal" onclick="closeModal()">
        <span class="modal-close" onclick="closeModal()">&times;</span>
        <img id="modalImg" src="" alt="Screenshot" onclick="event.stopPropagation()">
    </div>

    <script>
        function openModal(src) {{
            document.getElementById('modalImg').src = src;
            document.getElementById('screenshotModal').classList.add('active');
            document.body.style.overflow = 'hidden';
        }}

        function closeModal() {{
            document.getElementById('screenshotModal').classList.remove('active');
            document.body.style.overflow = '';
        }}

        document.addEventListener('keydown', function(e) {{
            if (e.key === 'Escape') closeModal();
        }});
    </script>
</body>
</html>"""

    return html


@router.get("/batches/{batch_id}/export")
def export_batch(
    batch_id: str,
    format: str = Query(default="json", description="Export format: json, csv, or html"),
    session: Session = Depends(get_session),
):
    """
    Export batch data as JSON, CSV, or HTML.
    """
    batch = session.get(RegressionBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Get all runs for this batch
    runs_query = select(DBTestRun).where(DBTestRun.batch_id == batch_id)
    runs = session.exec(runs_query).all()

    # Prepare test data
    tests = []
    for run in runs:
        duration = None
        if run.started_at and run.completed_at:
            duration = int((run.completed_at - run.started_at).total_seconds())

        tests.append(
            {
                "id": run.id,
                "spec_name": run.spec_name,
                "test_name": run.test_name or run.spec_name,
                "status": run.status,
                "steps_completed": run.steps_completed,
                "total_steps": run.total_steps,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "error_message": run.error_message,
                "duration_seconds": duration,
            }
        )

    if format == "csv":
        # Generate CSV
        output = io.StringIO()
        if tests:
            writer = csv.DictWriter(output, fieldnames=tests[0].keys())
            writer.writeheader()
            writer.writerows(tests)

        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=batch_{batch_id}.csv"},
        )
    elif format == "html":
        # Load run details from filesystem for HTML export
        for test in tests:
            run_dir = RUNS_DIR / test["id"]
            run_file = run_dir / "run.json"
            if run_file.exists():
                try:
                    run_data = json.loads(run_file.read_text())
                    test["run_details"] = run_data

                    # Load screenshots as base64
                    if run_data.get("steps"):
                        for step in run_data["steps"]:
                            screenshot_path = step.get("screenshot")
                            if screenshot_path:
                                # Handle both absolute and relative paths
                                if Path(screenshot_path).is_absolute():
                                    full_path = Path(screenshot_path)
                                else:
                                    full_path = run_dir / screenshot_path
                                if full_path.exists():
                                    with open(full_path, "rb") as f:
                                        step["screenshot_base64"] = base64.b64encode(f.read()).decode("utf-8")
                except (OSError, json.JSONDecodeError):
                    pass  # Skip if run.json is invalid or unreadable

        # Generate HTML report with run details
        html_content = generate_batch_html_report(batch, tests)
        return Response(
            content=html_content,
            media_type="text/html",
            headers={"Content-Disposition": f"attachment; filename=batch_{batch_id}.html"},
        )
    else:
        # Return JSON
        return BatchExportResponse(
            batch_id=batch.id,
            name=batch.name,
            created_at=batch.created_at.isoformat() if batch.created_at else None,
            completed_at=batch.completed_at.isoformat() if batch.completed_at else None,
            status=batch.status,
            browser=batch.browser,
            tags_used=batch.tags_used,
            hybrid_mode=batch.hybrid_mode,
            summary={
                "total_tests": batch.total_tests,
                "passed": batch.passed,
                "failed": batch.failed,
                "stopped": batch.stopped,
                "success_rate": batch.success_rate,
                "duration_seconds": batch.duration_seconds,
            },
            tests=tests,
        )


@router.get("/debug/test-counts")
def debug_test_counts():
    """
    Debug endpoint to verify test counting is working correctly.
    Returns information about the tests directory and sample file counts.
    """
    result = {
        "tests_dir": str(TESTS_DIR),
        "tests_dir_exists": TESTS_DIR.exists(),
        "base_dir": str(BASE_DIR),
        "test_counter_available": _test_counter_available,
        "sample_files": [],
        "total_files": 0,
        "total_tests": 0,
        "files_with_multiple_tests": 0,
    }

    if TESTS_DIR.exists():
        test_files = list(TESTS_DIR.glob("*.spec.ts"))
        result["total_files"] = len(test_files)

        # Sample up to 10 files with their test counts
        for test_file in test_files[:10]:
            count = count_tests_in_file(str(test_file))
            result["sample_files"].append({"name": test_file.name, "test_count": count})
            result["total_tests"] += count
            if count > 1:
                result["files_with_multiple_tests"] += 1

        # Count remaining files
        for test_file in test_files[10:]:
            count = count_tests_in_file(str(test_file))
            result["total_tests"] += count
            if count > 1:
                result["files_with_multiple_tests"] += 1

    return result


@router.get("/debug/batch/{batch_id}/test-counts")
def debug_batch_test_counts(batch_id: str, session: Session = Depends(get_session)):
    """
    Debug endpoint to see test counting for a specific batch.
    Shows how each run maps to test files and the counted tests.
    """
    batch = session.get(RegressionBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    runs_query = select(DBTestRun).where(DBTestRun.batch_id == batch_id)
    runs = session.exec(runs_query).all()

    run_details = []
    total_actual = 0
    for run in runs:
        test_path = _get_test_code_path(run.spec_name)
        test_count = 1
        if test_path:
            test_count = count_tests_in_file(str(test_path))
        total_actual += test_count

        run_details.append(
            {
                "spec_name": run.spec_name,
                "test_path": str(test_path) if test_path else None,
                "test_path_exists": test_path.exists() if test_path else False,
                "test_count": test_count,
                "status": run.status,
            }
        )

    return {
        "batch_id": batch_id,
        "batch_total_tests": batch.total_tests,  # File count
        "actual_total_tests": total_actual,  # Real test count
        "tests_dir": str(TESTS_DIR),
        "tests_dir_exists": TESTS_DIR.exists(),
        "runs": run_details,
    }


class BatchRenameRequest(BaseModel):
    name: str


@router.patch("/batches/{batch_id}")
def update_batch(batch_id: str, body: BatchRenameRequest, session: Session = Depends(get_session)):
    """D3: Update batch name."""
    batch = session.get(RegressionBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    batch.name = body.name
    session.add(batch)
    session.commit()
    session.refresh(batch)
    return _batch_to_summary(batch)


@router.post("/batches/{batch_id}/rerun-failed")
async def rerun_failed(batch_id: str, session: Session = Depends(get_session)):
    """D2: Re-run only the failed tests from a batch, creating a new batch."""
    batch = session.get(RegressionBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Get failed runs
    failed_runs = session.exec(
        select(DBTestRun).where(DBTestRun.batch_id == batch_id, DBTestRun.status == "failed")
    ).all()

    if not failed_runs:
        raise HTTPException(status_code=400, detail="No failed tests to re-run")

    failed_spec_names = [r.spec_name for r in failed_runs]

    # Create new batch using batch_executor
    from orchestrator.services.batch_executor import BatchConfig, create_regression_batch

    config = BatchConfig(
        project_id=batch.project_id or "default",
        browser=batch.browser,
        hybrid_mode=batch.hybrid_mode,
        spec_names=failed_spec_names,
        automated_only=False,
        batch_name=f"Re-run Failed: {batch.name or batch.id}",
        triggered_by="rerun-failed",
    )

    try:
        result = create_regression_batch(config, session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Start the tasks (same pattern as main.py create_bulk_run)
    import asyncio

    from .main import PROCESS_MANAGER, start_native_run

    for task_args in result.tasks_to_start:
        task = asyncio.ensure_future(
            start_native_run(
                task_args["spec_path"],
                task_args["run_dir"],
                task_args["run_id"],
                task_args.get("try_code_path"),
                task_args["browser"],
                task_args["hybrid"],
                task_args["max_iterations"],
                batch_id=task_args["batch_id"],
                spec_name=task_args["spec_name"],
                project_id=task_args["project_id"],
            )
        )
        if hasattr(PROCESS_MANAGER, "register_task"):
            PROCESS_MANAGER.register_task(task_args["run_id"], task)

    return {
        "batch_id": result.batch_id,
        "run_ids": result.run_ids,
        "count": len(result.run_ids),
        "original_batch_id": batch_id,
        "failed_specs": failed_spec_names,
    }


@router.get("/batches/trend")
def batch_trend(
    project_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
):
    """D4: Success rate trend across recent completed batches."""
    query = select(RegressionBatch).where(RegressionBatch.status == "completed")
    if project_id:
        query = query.where(RegressionBatch.project_id == project_id)
    query = query.order_by(desc(RegressionBatch.created_at)).limit(limit)
    batches = session.exec(query).all()

    trend = []
    for b in reversed(batches):  # oldest first for chart
        trend.append(
            {
                "batch_id": b.id,
                "name": b.name,
                "created_at": b.created_at.isoformat() if b.created_at else None,
                "success_rate": b.success_rate,
                "passed": b.passed,
                "failed": b.failed,
                "total": b.total_tests,
            }
        )
    return trend


@router.get("/batches/{batch_id}/error-summary")
def error_summary(batch_id: str, session: Session = Depends(get_session)):
    """D5: Categorize errors in a batch's failed runs."""
    batch = session.get(RegressionBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    failed_runs = session.exec(
        select(DBTestRun).where(DBTestRun.batch_id == batch_id, DBTestRun.status == "failed")
    ).all()

    categories: dict[str, int] = {}
    for run in failed_runs:
        msg = (run.error_message or "").lower()
        if "timeout" in msg:
            cat = "Timeout"
        elif any(k in msg for k in ("selector", "locator", "element")):
            cat = "Selector"
        elif any(k in msg for k in ("navigation", "net::")):
            cat = "Network"
        elif any(k in msg for k in ("assertion", "expect")):
            cat = "Assertion"
        else:
            cat = "Other"
        categories[cat] = categories.get(cat, 0) + 1

    total_errors = sum(categories.values())
    items = []
    for name, count in sorted(categories.items(), key=lambda x: -x[1]):
        items.append(
            {
                "name": name,
                "count": count,
                "percentage": round(count / total_errors * 100, 1) if total_errors else 0,
            }
        )

    return {"categories": items, "total_errors": total_errors}


class CompareBatchesRequest(BaseModel):
    batch_ids: list[str]


@router.post("/batches/compare")
def compare_batches(body: CompareBatchesRequest, session: Session = Depends(get_session)):
    """D6: Compare two batches, showing regressions and improvements."""
    if len(body.batch_ids) != 2:
        raise HTTPException(status_code=400, detail="Exactly 2 batch IDs required")

    old_id, new_id = body.batch_ids
    old_batch = session.get(RegressionBatch, old_id)
    new_batch = session.get(RegressionBatch, new_id)
    if not old_batch or not new_batch:
        raise HTTPException(status_code=404, detail="One or both batches not found")

    old_runs = session.exec(select(DBTestRun).where(DBTestRun.batch_id == old_id)).all()
    new_runs = session.exec(select(DBTestRun).where(DBTestRun.batch_id == new_id)).all()

    def _normalize_status(s: str) -> str:
        if s in ("passed", "completed"):
            return "passed"
        return s

    old_map = {r.spec_name: _normalize_status(r.status) for r in old_runs}
    new_map = {r.spec_name: _normalize_status(r.status) for r in new_runs}

    all_specs = set(old_map.keys()) | set(new_map.keys())

    regressions = []
    improvements = []
    unchanged_passing = 0
    unchanged_failing = 0

    for spec in sorted(all_specs):
        old_s = old_map.get(spec)
        new_s = new_map.get(spec)
        if old_s == new_s:
            if new_s == "passed":
                unchanged_passing += 1
            else:
                unchanged_failing += 1
        elif old_s == "passed" and new_s != "passed":
            regressions.append({"spec_name": spec, "old_status": old_s, "new_status": new_s})
        elif old_s != "passed" and new_s == "passed":
            improvements.append({"spec_name": spec, "old_status": old_s or "new", "new_status": new_s})
        else:
            # Both non-passing but different (e.g., failed -> stopped)
            unchanged_failing += 1

    return {
        "regressions": regressions,
        "improvements": improvements,
        "unchanged_passing": unchanged_passing,
        "unchanged_failing": unchanged_failing,
        "old_batch": {"id": old_id, "name": old_batch.name},
        "new_batch": {"id": new_id, "name": new_batch.name},
    }


@router.get("/spec-history")
def spec_history(
    spec_name: str = Query(..., description="Spec name to get history for"),
    project_id: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
):
    """D7: Per-test history across batches."""
    query = select(DBTestRun).where(
        DBTestRun.spec_name == spec_name,
        DBTestRun.batch_id != None,  # noqa: E711 - SQLAlchemy needs this
    )
    if project_id:
        query = query.where(DBTestRun.project_id == project_id)
    query = query.order_by(desc(DBTestRun.created_at)).limit(limit)

    runs = session.exec(query).all()

    history = []
    for r in runs:
        batch = session.get(RegressionBatch, r.batch_id) if r.batch_id else None
        history.append(
            {
                "batch_id": r.batch_id,
                "batch_name": batch.name if batch else None,
                "run_id": r.id,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "error_message": r.error_message,
            }
        )

    return history


@router.get("/flaky-tests")
def flaky_tests(
    project_id: str | None = Query(default=None),
    min_batches: int = Query(default=5, ge=2),
    window: int = Query(default=10, ge=2, le=50),
    session: Session = Depends(get_session),
):
    """D8: Detect flaky tests that alternate between pass/fail across recent batches."""
    # Get recent completed batches
    batch_query = select(RegressionBatch).where(RegressionBatch.status == "completed")
    if project_id:
        batch_query = batch_query.where(RegressionBatch.project_id == project_id)
    batch_query = batch_query.order_by(desc(RegressionBatch.created_at)).limit(window)
    recent_batches = session.exec(batch_query).all()

    if len(recent_batches) < min_batches:
        return {"flaky_tests": [], "total": 0, "batches_analyzed": len(recent_batches)}

    batch_ids = [b.id for b in recent_batches]

    # Get all runs for these batches
    runs = session.exec(
        select(DBTestRun).where(DBTestRun.batch_id.in_(batch_ids))  # type: ignore[attr-defined]
    ).all()

    # Group by spec_name
    spec_results: dict[str, list[str]] = {}
    # Build a batch order map for sorting results chronologically
    batch_order = {bid: i for i, bid in enumerate(reversed(batch_ids))}

    for r in runs:
        spec_results.setdefault(r.spec_name, [])
        norm = "pass" if r.status in ("passed", "completed") else "fail"
        spec_results[r.spec_name].append((batch_order.get(r.batch_id, 0), norm))

    flaky = []
    for spec_name, results in spec_results.items():
        # Sort by batch order (oldest first)
        results.sort(key=lambda x: x[0])
        statuses = [s for _, s in results]

        pass_count = statuses.count("pass")
        fail_count = statuses.count("fail")

        if pass_count > 0 and fail_count > 0 and len(statuses) >= min_batches:
            flakiness_rate = round(min(pass_count, fail_count) / len(statuses) * 100, 1)
            flaky.append(
                {
                    "spec_name": spec_name,
                    "pass_count": pass_count,
                    "fail_count": fail_count,
                    "flakiness_rate": flakiness_rate,
                    "recent_results": statuses[-window:],
                }
            )

    # Sort by flakiness rate descending
    flaky.sort(key=lambda x: -x["flakiness_rate"])

    return {"flaky_tests": flaky, "total": len(flaky), "batches_analyzed": len(recent_batches)}


@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: str, session: Session = Depends(get_session)):
    """
    Delete a batch. Does not delete associated runs, just unlinks them.
    """
    batch = session.get(RegressionBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Unlink runs from batch
    runs_query = select(DBTestRun).where(DBTestRun.batch_id == batch_id)
    runs = session.exec(runs_query).all()
    for run in runs:
        run.batch_id = None
        session.add(run)

    # Delete batch
    session.delete(batch)
    session.commit()

    return {"status": "deleted", "batch_id": batch_id, "unlinked_runs": len(runs)}
