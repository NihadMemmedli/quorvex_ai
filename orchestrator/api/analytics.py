"""
Analytics API Router

Provides endpoints for test analytics: pass-rate trends, flake detection,
failure classification, spec performance, and coverage overview.
"""

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Date, case, cast, distinct, func
from sqlmodel import Session, select

from .dashboard import categorize_error
from .db import get_database_type, get_session
from .models_db import SpecMetadata as DBSpecMetadata
from .models_db import TestRun as DBTestRun
from .projects import _count_all_specs_for_project

try:
    from ..utils.test_counter import get_project_test_count, get_total_test_count
except ImportError:

    def get_project_test_count(project_id, tests_dir, specs_dir, session):
        return 0, 0

    def get_total_test_count(dir_path, pattern="**/*.spec.ts"):
        from pathlib import Path

        test_files = list(Path(dir_path).glob(pattern))
        return len(test_files), len(test_files)


logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = BASE_DIR / "specs"
TESTS_DIR = BASE_DIR / "tests" / "generated"

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _period_to_cutoff(period: str) -> datetime:
    """Convert period string to a datetime cutoff."""
    days = {"7d": 7, "30d": 30, "90d": 90}
    return datetime.utcnow() - timedelta(days=days[period])


def _date_group_expression(db_type: str):
    """Return the appropriate date grouping expression for the database type."""
    if db_type == "postgresql":
        return cast(DBTestRun.created_at, Date)
    return func.date(DBTestRun.created_at)


# ---------------------------------------------------------------------------
# Endpoint 1: Pass-Rate Trends
# ---------------------------------------------------------------------------
@router.get("/pass-rate-trends")
def get_pass_rate_trends(
    period: str = Query("30d", pattern="^(7d|30d|90d)$"),
    test_type: str = Query("all", pattern="^(all|api|browser)$"),
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    cutoff = _period_to_cutoff(period)
    db_type = get_database_type()
    date_expr = _date_group_expression(db_type)

    stmt = select(
        date_expr.label("date"),
        func.count().label("total_runs"),
        func.sum(case((DBTestRun.status == "passed", 1), else_=0)).label("passed"),
        func.sum(case((DBTestRun.status == "failed", 1), else_=0)).label("failed"),
    ).where(DBTestRun.created_at >= cutoff)

    if project_id:
        stmt = stmt.where(DBTestRun.project_id == project_id)
    if test_type != "all":
        stmt = stmt.where(DBTestRun.test_type == test_type)

    stmt = stmt.group_by(date_expr).order_by(date_expr)
    rows = session.exec(stmt).all()

    data_points = []
    for row in rows:
        total = row.total_runs or 0
        passed = row.passed or 0
        failed = row.failed or 0
        pass_rate = round((passed / total) * 100, 1) if total > 0 else 0.0
        data_points.append(
            {
                "date": str(row.date),
                "total_runs": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": pass_rate,
            }
        )

    # Summary
    total_runs = sum(dp["total_runs"] for dp in data_points)
    avg_pass_rate = round(sum(dp["pass_rate"] for dp in data_points) / len(data_points), 1) if data_points else 0.0

    # Trend direction: compare last 7 days avg vs previous 7 days avg
    now = datetime.utcnow()
    last_7d = [dp for dp in data_points if dp["date"] >= str((now - timedelta(days=7)).date())]
    prev_7d = [
        dp
        for dp in data_points
        if str((now - timedelta(days=14)).date()) <= dp["date"] < str((now - timedelta(days=7)).date())
    ]
    last_avg = (sum(dp["pass_rate"] for dp in last_7d) / len(last_7d)) if last_7d else 0
    prev_avg = (sum(dp["pass_rate"] for dp in prev_7d) / len(prev_7d)) if prev_7d else 0
    diff = last_avg - prev_avg
    if diff > 5:
        trend_direction = "up"
    elif diff < -5:
        trend_direction = "down"
    else:
        trend_direction = "flat"

    return {
        "data_points": data_points,
        "summary": {
            "avg_pass_rate": avg_pass_rate,
            "total_runs": total_runs,
            "trend_direction": trend_direction,
        },
    }


# ---------------------------------------------------------------------------
# Endpoint 2: Flake Detection
# ---------------------------------------------------------------------------
@router.get("/flake-detection")
def get_flake_detection(
    project_id: str | None = Query(default=None),
    min_runs: int = Query(default=5, ge=2),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    stmt = select(DBTestRun).order_by(DBTestRun.created_at)
    if project_id:
        stmt = stmt.where(DBTestRun.project_id == project_id)
    runs = session.exec(stmt).all()

    # Group by spec_name
    spec_runs: dict[str, list[str]] = defaultdict(list)
    for run in runs:
        spec_runs[run.spec_name].append(run.status)

    # Load quarantine info
    quarantined_specs = set()
    metas = session.exec(select(DBSpecMetadata)).all()
    for meta in metas:
        try:
            tags = json.loads(meta.tags_json) if meta.tags_json else []
        except json.JSONDecodeError:
            tags = []
        if "quarantined" in tags:
            quarantined_specs.add(meta.spec_name)

    flaky_specs = []
    for spec_name, statuses in spec_runs.items():
        if len(statuses) < min_runs:
            continue
        transitions = sum(1 for i in range(1, len(statuses)) if statuses[i] != statuses[i - 1])
        flakiness_score = round(transitions / (len(statuses) - 1), 3)
        is_flaky = flakiness_score > 0.3
        recent_results = statuses[-10:]

        flaky_specs.append(
            {
                "spec_name": spec_name,
                "total_runs": len(statuses),
                "flakiness_score": flakiness_score,
                "is_flaky": is_flaky,
                "recent_results": recent_results,
                "is_quarantined": spec_name in quarantined_specs,
            }
        )

    flaky_specs.sort(key=lambda x: x["flakiness_score"], reverse=True)
    flaky_specs = flaky_specs[:limit]
    total_flaky = sum(1 for s in flaky_specs if s["is_flaky"])

    return {
        "flaky_specs": flaky_specs,
        "total_flaky": total_flaky,
        "threshold": 0.3,
    }


# ---------------------------------------------------------------------------
# Endpoint 3: Quarantine Management
# ---------------------------------------------------------------------------
@router.post("/quarantine/{spec_name:path}")
def quarantine_spec(spec_name: str, session: Session = Depends(get_session)):
    meta = session.get(DBSpecMetadata, spec_name)
    if not meta:
        meta = DBSpecMetadata(spec_name=spec_name, tags_json="[]")
        session.add(meta)

    try:
        tags = json.loads(meta.tags_json) if meta.tags_json else []
    except json.JSONDecodeError:
        tags = []

    if "quarantined" not in tags:
        tags.append("quarantined")
        meta.tags_json = json.dumps(tags)
        session.commit()
        session.refresh(meta)

    return {"status": "quarantined"}


@router.delete("/quarantine/{spec_name:path}")
def unquarantine_spec(spec_name: str, session: Session = Depends(get_session)):
    meta = session.get(DBSpecMetadata, spec_name)
    if not meta:
        raise HTTPException(status_code=404, detail="Spec metadata not found")

    try:
        tags = json.loads(meta.tags_json) if meta.tags_json else []
    except json.JSONDecodeError:
        tags = []

    if "quarantined" in tags:
        tags.remove("quarantined")
        meta.tags_json = json.dumps(tags)
        session.commit()
        session.refresh(meta)

    return {"status": "unquarantined"}


# ---------------------------------------------------------------------------
# Endpoint 4: Failure Classification
# ---------------------------------------------------------------------------
CATEGORY_MAP = {
    "Assertion Failed": "defect",
    "Script Error": "defect",
    "Selector/Element Issue": "flaky",
    "Healing Failed": "flaky",
    "Navigation/HTTP Error": "environment",
    "Network/API Error": "environment",
    "Authentication Error": "environment",
    "Rate Limiting": "environment",
    "Timeout": "timeout",
    "Test Setup Issue": "defect",
    "Other Error": "defect",
}


@router.get("/failure-classification")
def get_failure_classification(
    project_id: str | None = Query(default=None),
    period: str = Query("30d", pattern="^(7d|30d|90d)$"),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    cutoff = _period_to_cutoff(period)
    stmt = (
        select(DBTestRun)
        .where(DBTestRun.status == "failed")
        .where(DBTestRun.created_at >= cutoff)
        .order_by(DBTestRun.created_at.desc())
    )
    if project_id:
        stmt = stmt.where(DBTestRun.project_id == project_id)

    failed_runs = session.exec(stmt).all()

    distribution: dict[str, int] = {"defect": 0, "flaky": 0, "environment": 0, "timeout": 0}
    recent_failures = []

    for run in failed_runs:
        err_msg = run.error_message or "Unknown error"
        detailed_category = categorize_error(err_msg)
        classification = CATEGORY_MAP.get(detailed_category, "defect")
        distribution[classification] += 1

        if len(recent_failures) < limit:
            recent_failures.append(
                {
                    "run_id": run.id,
                    "spec_name": run.spec_name,
                    "classification": classification,
                    "error_message": err_msg[:500],
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                }
            )

    return {
        "distribution": distribution,
        "recent_failures": recent_failures,
    }


# ---------------------------------------------------------------------------
# Endpoint 5: Spec Performance
# ---------------------------------------------------------------------------
@router.get("/spec-performance")
def get_spec_performance(
    project_id: str | None = Query(default=None),
    period: str = Query("30d", pattern="^(7d|30d|90d)$"),
    sort_by: str = Query("failures", pattern="^(failures|pass_rate)$"),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    cutoff = _period_to_cutoff(period)
    stmt = select(DBTestRun).where(DBTestRun.created_at >= cutoff)
    if project_id:
        stmt = stmt.where(DBTestRun.project_id == project_id)

    runs = session.exec(stmt).all()

    # Aggregate by spec_name
    spec_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"passed": 0, "failed": 0, "total": 0, "last_run_at": None, "recent_runs": [], "older_runs": []}
    )
    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)

    for run in runs:
        d = spec_data[run.spec_name]
        d["total"] += 1
        if run.status == "passed":
            d["passed"] += 1
        elif run.status == "failed":
            d["failed"] += 1
        if d["last_run_at"] is None or (run.created_at and run.created_at > d["last_run_at"]):
            d["last_run_at"] = run.created_at

        # Bucket for trend calculation
        if run.created_at and run.created_at >= seven_days_ago:
            d["recent_runs"].append(run.status)
        elif run.created_at and run.created_at >= fourteen_days_ago:
            d["older_runs"].append(run.status)

    specs = []
    for spec_name, d in spec_data.items():
        total = d["total"]
        passed = d["passed"]
        failed = d["failed"]
        pass_rate = round((passed / total) * 100, 1) if total > 0 else 0.0

        # Trend: compare last 7d pass rate vs previous 7d
        recent_total = len(d["recent_runs"])
        recent_passed = sum(1 for s in d["recent_runs"] if s == "passed")
        recent_rate = (recent_passed / recent_total * 100) if recent_total > 0 else None

        older_total = len(d["older_runs"])
        older_passed = sum(1 for s in d["older_runs"] if s == "passed")
        older_rate = (older_passed / older_total * 100) if older_total > 0 else None

        if recent_rate is not None and older_rate is not None:
            diff = recent_rate - older_rate
            trend = "up" if diff > 5 else ("down" if diff < -5 else "flat")
        else:
            trend = "flat"

        specs.append(
            {
                "spec_name": spec_name,
                "total_runs": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": pass_rate,
                "last_run_at": d["last_run_at"].isoformat() if d["last_run_at"] else None,
                "trend": trend,
            }
        )

    if sort_by == "failures":
        specs.sort(key=lambda x: x["failed"], reverse=True)
    else:
        specs.sort(key=lambda x: x["pass_rate"])

    specs = specs[:limit]
    return {"specs": specs}


# ---------------------------------------------------------------------------
# Endpoint 6: Coverage Overview
# ---------------------------------------------------------------------------
@router.get("/coverage-overview")
def get_coverage_overview(
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    # Total specs
    if project_id:
        total_specs = _count_all_specs_for_project(project_id, session)
    else:
        total_specs = len(list(SPECS_DIR.glob("**/*.md"))) if SPECS_DIR.exists() else 0

    # Total test files
    if project_id:
        test_count, _ = get_project_test_count(project_id, str(TESTS_DIR), str(SPECS_DIR), session)
        total_test_files = test_count
    else:
        file_count, _ = get_total_test_count(str(TESTS_DIR))
        total_test_files = file_count

    # Specs with at least one test file (distinct spec_names that have generated tests)
    specs_with_tests = total_test_files

    # Specs run at least once
    stmt = select(func.count(distinct(DBTestRun.spec_name)))
    if project_id:
        stmt = stmt.where(DBTestRun.project_id == project_id)
    specs_run_at_least_once = session.exec(stmt).one() or 0

    run_coverage_percent = round((specs_run_at_least_once / total_specs) * 100, 1) if total_specs > 0 else 0.0

    # Tags distribution
    meta_stmt = select(DBSpecMetadata)
    if project_id:
        meta_stmt = meta_stmt.where(DBSpecMetadata.project_id == project_id)
    metas = session.exec(meta_stmt).all()

    tag_counter: Counter = Counter()
    for meta in metas:
        try:
            tags = json.loads(meta.tags_json) if meta.tags_json else []
        except json.JSONDecodeError:
            tags = []
        for tag in tags:
            tag_counter[tag] += 1

    tags_distribution = [{"tag": tag, "count": count} for tag, count in tag_counter.most_common()]

    return {
        "total_specs": total_specs,
        "total_test_files": total_test_files,
        "specs_with_tests": specs_with_tests,
        "specs_run_at_least_once": specs_run_at_least_once,
        "run_coverage_percent": run_coverage_percent,
        "tags_distribution": tags_distribution,
    }
