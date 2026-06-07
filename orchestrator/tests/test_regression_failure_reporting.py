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
from sqlmodel import Session, SQLModel, select


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


def test_rerun_failed_creates_batch_for_failed_and_error_runs(monkeypatch):
    import orchestrator.api.regression as regression_module
    from orchestrator.api.db import engine
    from orchestrator.api.models_db import RegressionBatch
    from orchestrator.api.models_db import TestRun as DBTestRun
    from orchestrator.api.regression import RUNS_DIR, router
    from orchestrator.services.batch_executor import SPECS_DIR

    batch_id = f"batch-rerun-failed-{uuid4()}"
    spec_root = f"rerun-failed-{uuid4()}"
    failed_spec = f"{spec_root}/failed-case.md"
    error_spec = f"{spec_root}/error-case.md"
    passed_spec = f"{spec_root}/passed-case.md"
    stopped_spec = f"{spec_root}/stopped-case.md"
    now = datetime.utcnow()
    scheduled_tasks: list[dict] = []
    created_batch_id = None
    created_run_ids: list[str] = []

    SQLModel.metadata.create_all(engine)

    for spec_name in (failed_spec, error_spec, passed_spec, stopped_spec):
        spec_path = SPECS_DIR / spec_name
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(f"# {Path(spec_name).stem}\n")

    def fake_start_regression_tasks(tasks_to_start, runtime):
        scheduled_tasks.extend(tasks_to_start)

    monkeypatch.setattr(regression_module, "_get_bulk_run_runtime", lambda: ("process-manager", "handler", "executor"))
    monkeypatch.setattr(regression_module, "_start_regression_tasks", fake_start_regression_tasks)

    with Session(engine) as session:
        session.add(
            RegressionBatch(
                id=batch_id,
                name="Original batch",
                created_at=now,
                browser="chromium",
                total_tests=4,
                failed=2,
                status="completed",
                project_id="default",
            )
        )
        for spec_name, status in (
            (failed_spec, "failed"),
            (error_spec, "error"),
            (passed_spec, "passed"),
            (stopped_spec, "stopped"),
        ):
            session.add(
                DBTestRun(
                    id=f"rerun-source-{uuid4()}",
                    spec_name=spec_name,
                    test_name=spec_name,
                    status=status,
                    batch_id=batch_id,
                    project_id="default",
                    created_at=now,
                    completed_at=now,
                    browser_auth={"test_data_refs": ["auth-users.valid-admin"]} if spec_name == failed_spec else None,
                )
            )
        session.commit()

    try:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(f"/regression/batches/{batch_id}/rerun-failed")

        assert response.status_code == 200
        data = response.json()
        created_batch_id = data["batch_id"]
        created_run_ids = data["run_ids"]
        assert data["count"] == 2
        assert set(data["failed_specs"]) == {failed_spec, error_spec}
        assert {task["spec_name"] for task in scheduled_tasks} == {failed_spec, error_spec}
        assert len(scheduled_tasks) == 2
        failed_task = next(task for task in scheduled_tasks if task["spec_name"] == failed_spec)
        assert failed_task["test_data_refs"] == ["auth-users.valid-admin"]

        with Session(engine) as session:
            new_batch = session.get(RegressionBatch, created_batch_id)
            assert new_batch is not None
            assert new_batch.triggered_by == "rerun-failed"
            assert new_batch.total_tests == 2
            new_runs = session.exec(select(DBTestRun).where(DBTestRun.batch_id == created_batch_id)).all()
            assert {run.spec_name for run in new_runs} == {failed_spec, error_spec}
            assert {run.status for run in new_runs} == {"queued"}
            new_failed_run = next(run for run in new_runs if run.spec_name == failed_spec)
            assert (new_failed_run.browser_auth or {}).get("test_data_refs") == ["auth-users.valid-admin"]
    finally:
        shutil.rmtree(SPECS_DIR / spec_root, ignore_errors=True)
        for run_id in created_run_ids:
            shutil.rmtree(RUNS_DIR / run_id, ignore_errors=True)
        with Session(engine) as session:
            for cleanup_batch_id in (batch_id, created_batch_id):
                if not cleanup_batch_id:
                    continue
                for run in session.exec(select(DBTestRun).where(DBTestRun.batch_id == cleanup_batch_id)).all():
                    shutil.rmtree(RUNS_DIR / run.id, ignore_errors=True)
                    session.delete(run)
                batch = session.get(RegressionBatch, cleanup_batch_id)
                if batch:
                    session.delete(batch)
            session.commit()


def test_rerun_failed_rejects_batch_without_failed_or_error_runs(monkeypatch):
    import orchestrator.api.regression as regression_module
    from orchestrator.api.db import engine
    from orchestrator.api.models_db import RegressionBatch
    from orchestrator.api.models_db import TestRun as DBTestRun
    from orchestrator.api.regression import router

    batch_id = f"batch-rerun-empty-{uuid4()}"
    now = datetime.utcnow()

    def fail_if_runtime_is_resolved():
        raise AssertionError("runtime should not be resolved when there are no failed runs")

    monkeypatch.setattr(regression_module, "_get_bulk_run_runtime", fail_if_runtime_is_resolved)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            RegressionBatch(
                id=batch_id,
                name="Clean batch",
                created_at=now,
                browser="chromium",
                total_tests=1,
                passed=1,
                failed=0,
                status="completed",
                project_id="default",
            )
        )
        session.add(
            DBTestRun(
                id=f"rerun-clean-source-{uuid4()}",
                spec_name="clean.md",
                test_name="clean.md",
                status="passed",
                batch_id=batch_id,
                project_id="default",
                created_at=now,
                completed_at=now,
            )
        )
        session.commit()

    try:
        app = FastAPI()
        app.include_router(router)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(f"/regression/batches/{batch_id}/rerun-failed")

        assert response.status_code == 400
        assert response.json()["detail"] == "No failed tests to re-run"
    finally:
        with Session(engine) as session:
            for run in session.exec(select(DBTestRun).where(DBTestRun.batch_id == batch_id)).all():
                session.delete(run)
            batch = session.get(RegressionBatch, batch_id)
            if batch:
                session.delete(batch)
            session.commit()
