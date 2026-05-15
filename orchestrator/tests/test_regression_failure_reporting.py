import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-regression-failure-tests")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel


def test_batch_failure_reporting_uses_artifacts_and_error_runs():
    from orchestrator.api.db import engine
    from orchestrator.api.models_db import RegressionBatch
    from orchestrator.api.models_db import TestRun as DBTestRun
    from orchestrator.api.regression import RUNS_DIR, router

    batch_id = f"batch-failure-reporting-{uuid4()}"
    run_ids = [f"failure-reporting-{uuid4()}" for _ in range(4)]
    now = datetime.utcnow()

    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            RegressionBatch(
                id=batch_id,
                name="Failure reporting test",
                created_at=now,
                started_at=now,
                completed_at=now,
                browser="chromium",
                total_tests=3,
                failed=4,
                status="completed",
            )
        )
        session.add(
            DBTestRun(
                id=run_ids[0],
                spec_name="timeout.md",
                test_name="Timeout case",
                status="failed",
                batch_id=batch_id,
                error_message="Timeout 30000ms exceeded while waiting for locator",
                created_at=now,
                started_at=now,
                completed_at=now,
            )
        )
        session.add(
            DBTestRun(
                id=run_ids[1],
                spec_name="pipeline.md",
                test_name="Pipeline case",
                status="error",
                batch_id=batch_id,
                created_at=now,
                started_at=now,
                completed_at=now,
            )
        )
        session.add(
            DBTestRun(
                id=run_ids[2],
                spec_name="assertion.md",
                test_name="Assertion case",
                status="failed",
                batch_id=batch_id,
                error_message="Generic failure",
                created_at=now,
                started_at=now,
                completed_at=now,
            )
        )
        session.add(
            DBTestRun(
                id=run_ids[3],
                spec_name="execution-log.md",
                test_name="Execution log case",
                status="failed",
                batch_id=batch_id,
                created_at=now,
                started_at=now,
                completed_at=now,
            )
        )
        session.commit()

    pipeline_dir = RUNS_DIR / run_ids[1]
    assertion_dir = RUNS_DIR / run_ids[2]
    execution_log_dir = RUNS_DIR / run_ids[3]
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    assertion_dir.mkdir(parents=True, exist_ok=True)
    execution_log_dir.mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "pipeline_error.json").write_text(
        json.dumps({"stage": "generation", "error": "locator button Submit was not found"})
    )
    (assertion_dir / "test-results.json").write_text(
        json.dumps(
            {
                "suites": [
                    {
                        "title": "suite",
                        "specs": [
                            {
                                "title": "asserts total",
                                "file": "tests/assertion.spec.ts",
                                "tests": [
                                    {
                                        "results": [
                                            {
                                                "status": "failed",
                                                "duration": 25,
                                                "error": {
                                                    "message": "Error: expect(received).toBe(expected)",
                                                    "stack": "Expected: 2\nReceived: 1",
                                                },
                                            }
                                        ]
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        )
    )
    (execution_log_dir / "execution.log").write_text(
        """
Running 1 test using 1 worker

Test timeout of 30000ms exceeded.

Error: page.goto: Test timeout of 30000ms exceeded.
Call log:
  - navigating to "https://my.gov.az/en/services/retirement-calculator", waiting until "domcontentloaded"

at /app/tests/generated/example.spec.ts:20:33
"""
    )

    try:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app, raise_server_exceptions=False) as client:
            detail_response = client.get(f"/regression/batches/{batch_id}")
            assert detail_response.status_code == 200
            runs = {run["id"]: run for run in detail_response.json()["runs"]}
            assert runs[run_ids[0]]["failure_category"] == "Timeout"
            assert runs[run_ids[1]]["failure_category"] == "Selector"
            assert runs[run_ids[1]]["failure_source"] == "pipeline_error.json"
            assert runs[run_ids[2]]["failure_category"] == "Assertion"
            assert runs[run_ids[2]]["error_stack"] == "Expected: 2\nReceived: 1"
            assert runs[run_ids[3]]["failure_category"] == "Timeout"
            assert runs[run_ids[3]]["failure_source"] == "execution.log"
            assert "page.goto" in runs[run_ids[3]]["failure_summary"]

            summary_response = client.get(f"/regression/batches/{batch_id}/error-summary")
            assert summary_response.status_code == 200
            summary = summary_response.json()
            assert summary["total_errors"] == 4
            categories = {item["name"]: item for item in summary["categories"]}
            assert {"Timeout", "Selector", "Assertion"}.issubset(categories)
            assert categories["Selector"]["examples"][0]["run_id"] == run_ids[1]
    finally:
        for run_id in run_ids:
            shutil.rmtree(RUNS_DIR / run_id, ignore_errors=True)
        with Session(engine) as session:
            for run_id in run_ids:
                run = session.get(DBTestRun, run_id)
                if run:
                    session.delete(run)
            batch = session.get(RegressionBatch, batch_id)
            if batch:
                session.delete(batch)
            session.commit()
