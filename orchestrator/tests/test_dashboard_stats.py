import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-dashboard-stats")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlmodel import Session, SQLModel

from orchestrator.api import dashboard
from orchestrator.api.db import engine
from orchestrator.api.models_db import TestRun


def test_dashboard_stats_counts_db_only_runs_and_filesystem_runs(monkeypatch, tmp_path):
    SQLModel.metadata.create_all(engine, checkfirst=True)
    dashboard._dashboard_cache.clear()

    runs_dir = tmp_path / "runs"
    specs_dir = tmp_path / "specs"
    tests_dir = tmp_path / "tests"
    run_dir = runs_dir / "2026-05-28_10-00-00"
    run_dir.mkdir(parents=True)
    specs_dir.mkdir()
    tests_dir.mkdir()
    (specs_dir / "login.md").write_text("# Test: Login\n")
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "finalState": "passed",
                "duration": 12,
                "testName": "Filesystem run",
                "steps": [],
            }
        )
    )

    monkeypatch.setattr(dashboard, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(dashboard, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(dashboard, "TESTS_DIR", tests_dir)

    db_run_id = f"dashboard-db-only-{uuid4().hex}"
    db_run = TestRun(
        id=db_run_id,
        spec_name="db-only.md",
        test_name="DB only run",
        status="failed",
        created_at=datetime.utcnow() - timedelta(minutes=5),
        completed_at=datetime.utcnow(),
        error_message="Timeout waiting for selector",
    )
    with Session(engine) as session:
        session.add(db_run)
        session.commit()

    try:
        stats = dashboard.get_dashboard_stats(period="7d", project_id=None)
    finally:
        dashboard._dashboard_cache.clear()
        with Session(engine) as session:
            row = session.get(TestRun, db_run_id)
            if row:
                session.delete(row)
                session.commit()

    assert stats["total_runs"] == 2
    assert stats["pass_rate"] == 50.0
    assert stats["last_run"] == db_run_id
    assert {"category": "Timeout", "count": 1} in stats["errors"]
