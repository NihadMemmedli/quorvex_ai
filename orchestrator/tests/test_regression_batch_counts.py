import json
import os
import sys
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-regression-batch-counts")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select


def test_create_regression_batch_caches_actual_playwright_test_count(tmp_path, monkeypatch):
    from orchestrator.api.db import engine
    from orchestrator.api.models_db import Project, RegressionBatch, SpecMetadata
    from orchestrator.api.models_db import TestRun as DBTestRun
    from orchestrator.api.regression import router as regression_router
    from orchestrator.services import batch_executor

    project_id = f"batch-counts-{uuid4().hex}"
    spec_name = "flows/multi-test.md"
    specs_dir = tmp_path / "specs"
    runs_dir = tmp_path / "runs"
    generated_dir = tmp_path / "tests" / "generated"
    (specs_dir / "flows").mkdir(parents=True)
    generated_dir.mkdir(parents=True)
    runs_dir.mkdir()
    (specs_dir / spec_name).write_text("# Multi Test\n", encoding="utf-8")
    (generated_dir / "multi-test.spec.ts").write_text(
        """
import { test } from '@playwright/test';

test('first flow', async () => {});
test('second flow', async () => {});
test.skip('third flow', async () => {});
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(batch_executor, "BASE_DIR", tmp_path)
    monkeypatch.setattr(batch_executor, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(batch_executor, "RUNS_DIR", runs_dir)

    SQLModel.metadata.create_all(engine)
    created_batch_id = None
    try:
        with Session(engine) as session:
            session.add(Project(id=project_id, name="Batch Counts"))
            session.add(SpecMetadata(spec_name=spec_name, project_id=project_id))
            session.commit()

            result = batch_executor.create_regression_batch(
                batch_executor.BatchConfig(project_id=project_id, automated_only=True),
                session,
            )
            created_batch_id = result.batch_id
            batch = session.get(RegressionBatch, created_batch_id)
            assert batch is not None
            assert batch.total_tests == 1
            assert batch.queued == 1
            assert batch.actual_total_tests == 3
            assert batch.actual_passed == 0
            assert batch.actual_failed == 0

        import orchestrator.api.regression as regression_module

        monkeypatch.setattr(regression_module, "TESTS_DIR", generated_dir)
        app = FastAPI()
        app.include_router(regression_router)
        with TestClient(app, raise_server_exceptions=False) as client:
            detail_response = client.get(f"/regression/batches/{created_batch_id}?project_id={project_id}")
            assert detail_response.status_code == 200
            detail = detail_response.json()
            assert detail["total_tests"] == 1
            assert detail["actual_total_tests"] == 3
            assert detail["runs"][0]["actual_test_count"] == 3

        with Session(engine) as session:
            cached = session.get(RegressionBatch, created_batch_id)
            assert cached is not None
            assert cached.actual_total_tests == 3
    finally:
        with Session(engine) as session:
            if created_batch_id:
                for run in session.exec(select(DBTestRun).where(DBTestRun.batch_id == created_batch_id)).all():
                    session.delete(run)
                batch = session.get(RegressionBatch, created_batch_id)
                if batch:
                    session.delete(batch)
            meta = session.get(SpecMetadata, (project_id, spec_name))
            if meta:
                session.delete(meta)
            project = session.get(Project, project_id)
            if project:
                session.delete(project)
            session.commit()


def test_list_batches_refreshes_stale_actual_pass_fail_cache(tmp_path, monkeypatch):
    from orchestrator.api.db import engine
    from orchestrator.api.models_db import Project, RegressionBatch
    from orchestrator.api.models_db import TestRun as DBTestRun
    from orchestrator.api.regression import router as regression_router

    project_id = f"stale-counts-{uuid4().hex}"
    batch_id = f"batch_{uuid4().hex}"
    generated_dir = tmp_path / "tests" / "generated"
    generated_dir.mkdir(parents=True)
    (generated_dir / "multi-test.spec.ts").write_text(
        """
import { test } from '@playwright/test';

test('first flow', async () => {});
test('second flow', async () => {});
test('third flow', async () => {});
""",
        encoding="utf-8",
    )

    import orchestrator.api.regression as regression_module

    monkeypatch.setattr(regression_module, "TESTS_DIR", generated_dir)

    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(Project(id=project_id, name="Stale Counts"))
            session.add(
                RegressionBatch(
                    id=batch_id,
                    name="Stale Counts",
                    project_id=project_id,
                    total_tests=1,
                    passed=1,
                    failed=0,
                    status="completed",
                    actual_total_tests=3,
                    actual_passed=0,
                    actual_failed=0,
                )
            )
            session.add(
                DBTestRun(
                    id=f"run_{uuid4().hex}",
                    spec_name="multi-test.md",
                    status="passed",
                    batch_id=batch_id,
                    project_id=project_id,
                )
            )
            session.commit()

        app = FastAPI()
        app.include_router(regression_router)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(f"/regression/batches?project_id={project_id}")
            assert response.status_code == 200
            batch = response.json()["batches"][0]
            assert batch["actual_total_tests"] == 3
            assert batch["actual_passed"] == 3
            assert batch["actual_failed"] == 0

        with Session(engine) as session:
            cached = session.get(RegressionBatch, batch_id)
            assert cached is not None
            assert cached.actual_passed == 3
    finally:
        with Session(engine) as session:
            for run in session.exec(select(DBTestRun).where(DBTestRun.batch_id == batch_id)).all():
                session.delete(run)
            batch = session.get(RegressionBatch, batch_id)
            if batch:
                session.delete(batch)
            project = session.get(Project, project_id)
            if project:
                session.delete(project)
            session.commit()


def test_failed_batch_uses_playwright_json_for_mixed_per_test_counts(tmp_path, monkeypatch):
    from orchestrator.api.db import engine
    from orchestrator.api.models_db import Project, RegressionBatch
    from orchestrator.api.models_db import TestRun as DBTestRun
    from orchestrator.api.regression import router as regression_router

    project_id = f"mixed-counts-{uuid4().hex}"
    batch_id = f"batch_{uuid4().hex}"
    run_id = f"run_{uuid4().hex}"
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / run_id
    generated_dir = tmp_path / "tests" / "generated"
    run_dir.mkdir(parents=True)
    generated_dir.mkdir(parents=True)
    (generated_dir / "multi-test.spec.ts").write_text(
        "\n".join(
            [
                "import { test } from '@playwright/test';",
                *[f"test('flow {index}', async () => {{}});" for index in range(1, 11)],
            ]
        ),
        encoding="utf-8",
    )
    specs = []
    for index in range(1, 11):
        status = "failed" if index == 10 else "passed"
        result = {"status": status, "duration": 10}
        if status == "failed":
            result["error"] = {"message": "Expected checkout total to match", "stack": "AssertionError"}
        specs.append(
            {
                "title": f"flow {index}",
                "file": "multi-test.spec.ts",
                "tests": [{"results": [result]}],
            }
        )
    (run_dir / "test-results.json").write_text(
        json.dumps({"suites": [{"title": "multi-test.spec.ts", "specs": specs}]}),
        encoding="utf-8",
    )

    import orchestrator.api.regression as regression_module

    monkeypatch.setattr(regression_module, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(regression_module, "TESTS_DIR", generated_dir)

    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(Project(id=project_id, name="Mixed Counts"))
            session.add(
                RegressionBatch(
                    id=batch_id,
                    name="Mixed Counts",
                    project_id=project_id,
                    total_tests=1,
                    passed=0,
                    failed=1,
                    status="completed",
                    actual_total_tests=10,
                    actual_passed=0,
                    actual_failed=10,
                )
            )
            session.add(
                DBTestRun(
                    id=run_id,
                    spec_name="multi-test.md",
                    status="failed",
                    batch_id=batch_id,
                    project_id=project_id,
                )
            )
            session.commit()

        app = FastAPI()
        app.include_router(regression_router)
        with TestClient(app, raise_server_exceptions=False) as client:
            detail_response = client.get(f"/regression/batches/{batch_id}?project_id={project_id}")
            assert detail_response.status_code == 200
            detail = detail_response.json()
            assert detail["actual_total_tests"] == 10
            assert detail["actual_passed"] == 9
            assert detail["actual_failed"] == 1
            assert detail["success_rate"] == 90.0
            assert detail["runs"][0]["actual_test_count"] == 10

            list_response = client.get(f"/regression/batches?project_id={project_id}")
            assert list_response.status_code == 200
            batch = list_response.json()["batches"][0]
            assert batch["actual_total_tests"] == 10
            assert batch["actual_passed"] == 9
            assert batch["actual_failed"] == 1
            assert batch["success_rate"] == 90.0

            export_response = client.get(f"/regression/batches/{batch_id}/export?format=json")
            assert export_response.status_code == 200
            summary = export_response.json()["summary"]
            assert summary["actual_total_tests"] == 10
            assert summary["actual_passed"] == 9
            assert summary["actual_failed"] == 1
            assert summary["success_rate"] == 90.0

        with Session(engine) as session:
            cached = session.get(RegressionBatch, batch_id)
            assert cached is not None
            assert cached.actual_passed == 9
            assert cached.actual_failed == 1
    finally:
        with Session(engine) as session:
            for run in session.exec(select(DBTestRun).where(DBTestRun.batch_id == batch_id)).all():
                session.delete(run)
            batch = session.get(RegressionBatch, batch_id)
            if batch:
                session.delete(batch)
            project = session.get(Project, project_id)
            if project:
                session.delete(project)
            session.commit()


def test_failed_batch_without_playwright_json_keeps_file_count_fallback(tmp_path, monkeypatch):
    from orchestrator.api.db import engine
    from orchestrator.api.models_db import Project, RegressionBatch
    from orchestrator.api.models_db import TestRun as DBTestRun
    from orchestrator.api.regression import router as regression_router

    project_id = f"fallback-counts-{uuid4().hex}"
    batch_id = f"batch_{uuid4().hex}"
    run_id = f"run_{uuid4().hex}"
    runs_dir = tmp_path / "runs"
    generated_dir = tmp_path / "tests" / "generated"
    (runs_dir / run_id).mkdir(parents=True)
    generated_dir.mkdir(parents=True)
    (generated_dir / "multi-test.spec.ts").write_text(
        """
import { test } from '@playwright/test';

test('first flow', async () => {});
test('second flow', async () => {});
test('third flow', async () => {});
""",
        encoding="utf-8",
    )

    import orchestrator.api.regression as regression_module

    monkeypatch.setattr(regression_module, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(regression_module, "TESTS_DIR", generated_dir)

    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(Project(id=project_id, name="Fallback Counts"))
            session.add(
                RegressionBatch(
                    id=batch_id,
                    name="Fallback Counts",
                    project_id=project_id,
                    total_tests=1,
                    passed=0,
                    failed=1,
                    status="completed",
                )
            )
            session.add(
                DBTestRun(
                    id=run_id,
                    spec_name="multi-test.md",
                    status="failed",
                    batch_id=batch_id,
                    project_id=project_id,
                )
            )
            session.commit()

        app = FastAPI()
        app.include_router(regression_router)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(f"/regression/batches/{batch_id}?project_id={project_id}")
            assert response.status_code == 200
            detail = response.json()
            assert detail["actual_total_tests"] == 3
            assert detail["actual_passed"] == 0
            assert detail["actual_failed"] == 3
            assert detail["success_rate"] == 0.0
    finally:
        with Session(engine) as session:
            for run in session.exec(select(DBTestRun).where(DBTestRun.batch_id == batch_id)).all():
                session.delete(run)
            batch = session.get(RegressionBatch, batch_id)
            if batch:
                session.delete(batch)
            project = session.get(Project, project_id)
            if project:
                session.delete(project)
            session.commit()


def test_automated_only_without_spec_names_selects_all_matching_project_specs(tmp_path, monkeypatch):
    from orchestrator.api.db import engine
    from orchestrator.api.models_db import Project, RegressionBatch, SpecMetadata
    from orchestrator.api.models_db import TestRun as DBTestRun
    from orchestrator.services import batch_executor

    project_id = f"all-automated-{uuid4().hex}"
    other_project_id = f"other-{uuid4().hex}"
    specs_dir = tmp_path / "specs"
    runs_dir = tmp_path / "runs"
    generated_dir = tmp_path / "tests" / "generated"
    specs_dir.mkdir()
    runs_dir.mkdir()
    generated_dir.mkdir(parents=True)

    matching_specs = [f"case-{index:03d}.md" for index in range(65)]
    for spec_name in matching_specs:
        (specs_dir / spec_name).write_text(f"# {spec_name}\n", encoding="utf-8")
        (generated_dir / spec_name.replace(".md", ".spec.ts")).write_text(
            "import { test } from '@playwright/test';\ntest('flow', async () => {});\n",
            encoding="utf-8",
        )

    other_spec = "other-project.md"
    (specs_dir / other_spec).write_text("# Other\n", encoding="utf-8")
    (generated_dir / "other-project.spec.ts").write_text(
        "import { test } from '@playwright/test';\ntest('other', async () => {});\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(batch_executor, "BASE_DIR", tmp_path)
    monkeypatch.setattr(batch_executor, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(batch_executor, "RUNS_DIR", runs_dir)

    SQLModel.metadata.create_all(engine)
    created_batch_id = None
    try:
        with Session(engine) as session:
            session.add(Project(id=project_id, name="All Automated"))
            session.add(Project(id=other_project_id, name="Other"))
            for spec_name in matching_specs:
                session.add(SpecMetadata(spec_name=spec_name, project_id=project_id, tags_json='["smoke"]'))
            session.add(SpecMetadata(spec_name=other_spec, project_id=other_project_id, tags_json='["smoke"]'))
            session.commit()

            selected = batch_executor.select_regression_specs(
                batch_executor.BatchConfig(project_id=project_id, automated_only=True, tags=["smoke"]),
                session,
            )
            assert set(selected) == set(matching_specs)
            assert len(selected) == 65

            result = batch_executor.create_regression_batch(
                batch_executor.BatchConfig(project_id=project_id, automated_only=True, tags=["smoke"]),
                session,
            )
            created_batch_id = result.batch_id
            assert len(result.run_ids) == 65
            assert len(result.tasks_to_start) == 65
            assert all(task["spec_name"] in matching_specs for task in result.tasks_to_start)
    finally:
        with Session(engine) as session:
            if created_batch_id:
                for run in session.exec(select(DBTestRun).where(DBTestRun.batch_id == created_batch_id)).all():
                    session.delete(run)
                batch = session.get(RegressionBatch, created_batch_id)
                if batch:
                    session.delete(batch)
            for spec_name in [*matching_specs, other_spec]:
                for project in (project_id, other_project_id):
                    meta = session.get(SpecMetadata, (project, spec_name))
                    if meta:
                        session.delete(meta)
            for project in (project_id, other_project_id):
                row = session.get(Project, project)
                if row:
                    session.delete(row)
            session.commit()
