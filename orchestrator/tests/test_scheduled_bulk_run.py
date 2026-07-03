import os
import sys
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-scheduled-bulk-run")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select


def _write_specs(specs_dir: Path, spec_names: list[str]) -> None:
    for spec_name in spec_names:
        spec_path = specs_dir / spec_name
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(f"# {spec_path.stem}\n", encoding="utf-8")


def _cleanup_batch(engine, project_id: str, batch_id: str | None = None) -> None:
    from orchestrator.api.models_db import Project, RegressionBatch, RegressionBatchItem
    from orchestrator.api.models_db import TestRun as DBTestRun

    with Session(engine) as session:
        if batch_id:
            items = session.exec(select(RegressionBatchItem).where(RegressionBatchItem.batch_id == batch_id)).all()
            for item in items:
                session.delete(item)
            for run in session.exec(select(DBTestRun).where(DBTestRun.batch_id == batch_id)).all():
                session.delete(run)
            batch = session.get(RegressionBatch, batch_id)
            if batch:
                session.delete(batch)
        project = session.get(Project, project_id)
        if project:
            session.delete(project)
        session.commit()


def test_scheduled_regression_batch_accepts_more_than_immediate_bulk_limit(tmp_path, monkeypatch):
    from orchestrator.api import spec_files
    from orchestrator.api.db import engine, init_db
    from orchestrator.api.models_db import Project, RegressionBatch, RegressionBatchItem
    from orchestrator.services import batch_executor
    from orchestrator.services import scheduled_batch_executor

    project_id = f"scheduled-accept-{uuid4().hex}"
    spec_names = ["flows/one.md", "flows/two.md", "flows/three.md"]
    specs_dir = tmp_path / "specs"
    runs_dir = tmp_path / "runs"
    specs_dir.mkdir()
    runs_dir.mkdir()
    _write_specs(specs_dir, spec_names)

    monkeypatch.setenv("QUORVEX_MAX_BULK_RUN_SPECS", "1")
    monkeypatch.setenv("QUORVEX_REGRESSION_CHUNK_SIZE", "2")
    monkeypatch.setenv("QUORVEX_REGRESSION_MAX_ACTIVE_PER_BATCH", "1")
    monkeypatch.setattr(batch_executor, "BASE_DIR", tmp_path)
    monkeypatch.setattr(batch_executor, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(batch_executor, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(spec_files, "BASE_DIR", tmp_path)
    monkeypatch.setattr(spec_files, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(spec_files, "RUNS_DIR", runs_dir)

    init_db()
    created_batch_id = None
    try:
        with Session(engine) as session:
            session.add(Project(id=project_id, name=f"Scheduled Accept {uuid4().hex}"))
            session.commit()

            config = batch_executor.BatchConfig(project_id=project_id, spec_names=spec_names)
            assert scheduled_batch_executor.should_schedule_bulk_run(len(spec_names)) is True
            result = scheduled_batch_executor.create_scheduled_regression_batch(
                config,
                session,
                spec_names=spec_names,
                browser_auth_session_id=None,
                use_project_default_browser_auth=False,
                model_tier=None,
            )
            created_batch_id = result.batch_id
            batch = session.get(RegressionBatch, result.batch_id)
            items = session.exec(
                select(RegressionBatchItem).where(RegressionBatchItem.batch_id == result.batch_id)
            ).all()

            assert result.count == 3
            assert batch is not None
            assert batch.scheduler_status == "pending"
            assert batch.dispatch_total == 3
            assert batch.chunk_size == 2
            assert batch.max_active_runs == 1
            assert len(items) == 3
            assert {item.status for item in items} == {"pending"}
    finally:
        _cleanup_batch(engine, project_id, created_batch_id)


def test_bulk_run_scheduled_mode_starts_only_bounded_initial_slice(tmp_path, monkeypatch):
    from orchestrator.api import main as main_module
    from orchestrator.api import runs as runs_module
    from orchestrator.api import spec_files
    from orchestrator.api.db import engine, init_db
    from orchestrator.api.models_db import Project, RegressionBatch, RegressionBatchItem
    from orchestrator.api.models_db import TestRun as DBTestRun
    from orchestrator.api.runs import router as runs_router
    from orchestrator.services import batch_executor

    project_id = f"scheduled-api-{uuid4().hex}"
    spec_names = [f"flows/case-{i}.md" for i in range(5)]
    specs_dir = tmp_path / "specs"
    runs_dir = tmp_path / "runs"
    specs_dir.mkdir()
    runs_dir.mkdir()
    _write_specs(specs_dir, spec_names)

    started_run_ids: list[str] = []

    async def fake_start_test_run_temporal_or_fail(run, payload, session):
        started_run_ids.append(run.id)
        run.temporal_workflow_id = f"temporal-{run.id}"
        run.temporal_run_id = "temporal-run"
        session.add(run)
        session.commit()

    monkeypatch.setenv("QUORVEX_MAX_BULK_RUN_SPECS", "2")
    monkeypatch.setenv("QUORVEX_REGRESSION_CHUNK_SIZE", "4")
    monkeypatch.setenv("QUORVEX_REGRESSION_MAX_ACTIVE_PER_BATCH", "2")
    monkeypatch.setenv("QUORVEX_REGRESSION_GLOBAL_ACTIVE_LIMIT", "100")
    monkeypatch.setattr(batch_executor, "BASE_DIR", tmp_path)
    monkeypatch.setattr(batch_executor, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(batch_executor, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(spec_files, "BASE_DIR", tmp_path)
    monkeypatch.setattr(spec_files, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(spec_files, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(runs_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(runs_module, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(runs_module, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(runs_module, "browser_runtime_status", lambda: {"live_view_available": False})
    monkeypatch.setattr(main_module, "_validate_browser_auth_selection_for_project", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module, "_normalize_request_test_data_refs", lambda refs: list(refs or []))
    monkeypatch.setattr(main_module, "_has_browser_auth_selection", lambda **kwargs: False)
    monkeypatch.setattr(
        main_module,
        "_resolve_browser_auth_storage_state_for_run",
        lambda *args, **kwargs: (None, {"mode": "none", "storage_state_attached": False}),
    )
    monkeypatch.setattr(main_module, "_start_test_run_temporal_or_fail", fake_start_test_run_temporal_or_fail)

    init_db()
    created_batch_id = None
    try:
        with Session(engine) as session:
            session.add(Project(id=project_id, name=f"Scheduled API {uuid4().hex}"))
            session.commit()

        app = FastAPI()
        app.include_router(runs_router)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                "/runs/bulk",
                json={"project_id": project_id, "spec_names": spec_names, "browser": "chromium"},
            )

        assert response.status_code == 200, response.text
        body = response.json()
        created_batch_id = body["batch_id"]
        assert body["count"] == 5
        assert body["mode"] == "scheduled"
        assert body["scheduled"] is True
        assert body["run_ids"] == []
        assert body["dispatched"] == 2
        assert len(started_run_ids) == 2

        with Session(engine) as session:
            batch = session.get(RegressionBatch, created_batch_id)
            items = session.exec(
                select(RegressionBatchItem).where(RegressionBatchItem.batch_id == created_batch_id)
            ).all()
            runs = session.exec(select(DBTestRun).where(DBTestRun.batch_id == created_batch_id)).all()

            assert batch is not None
            assert batch.scheduler_status == "dispatching"
            assert batch.dispatch_total == 5
            assert batch.dispatch_started == 2
            assert batch.chunk_size == 4
            assert batch.max_active_runs == 2
            assert len(runs) == 2
            runs_by_id = {run.id: run for run in runs}
            assert sum(1 for item in items if item.status == "queued" and item.run_id) == 2
            assert sum(1 for item in items if item.status == "pending" and not item.run_id) == 3
            assert all(
                item.run_id in runs_by_id
                for item in items
                if item.status == "queued"
            )
            assert all(run.temporal_workflow_id for run in runs)
    finally:
        _cleanup_batch(engine, project_id, created_batch_id)


def test_cancel_scheduled_bulk_batch_marks_pending_scheduler_work_cancelled(tmp_path, monkeypatch):
    from orchestrator.api import regression as regression_module
    from orchestrator.api.db import engine, init_db
    from orchestrator.api.models_db import Project, RegressionBatch, RegressionBatchItem
    from orchestrator.api.models_db import TestRun as DBTestRun

    project_id = f"scheduled-cancel-{uuid4().hex}"
    batch_id = f"batch_{uuid4().hex}"

    class FakeProcessManager:
        def stop(self, *args, **kwargs):
            return True

    monkeypatch.setattr(regression_module, "get_process_manager", lambda: FakeProcessManager())
    monkeypatch.setattr(regression_module, "RUNS_DIR", tmp_path / "runs")

    init_db()
    try:
        with Session(engine) as session:
            session.add(Project(id=project_id, name=f"Scheduled Cancel {uuid4().hex}"))
            session.add(
                RegressionBatch(
                    id=batch_id,
                    name="Scheduled Cancel",
                    project_id=project_id,
                    total_tests=3,
                    queued=3,
                    status="running",
                    scheduler_status="running",
                    chunk_size=2,
                    max_active_runs=1,
                    dispatch_total=3,
                    dispatch_started=1,
                    next_spec_index=1,
                )
            )
            for index in range(3):
                run_id = f"{batch_id}_run_{index}"
                session.add(
                    DBTestRun(
                        id=run_id,
                        spec_name=f"flows/case-{index}.md",
                        test_name=f"flows/case-{index}.md",
                        status="queued",
                        batch_id=batch_id,
                        project_id=project_id,
                    )
                )
                session.add(
                    RegressionBatchItem(
                        id=f"{batch_id}_item_{index}",
                        batch_id=batch_id,
                        ordinal=index,
                        spec_name=f"flows/case-{index}.md",
                        status="queued",
                        run_id=run_id,
                    )
                )
            session.commit()

            response = regression_module.cancel_batch_runs(batch_id, project_id=project_id, session=session)

        assert response["queued_cancelled"] == 3

        with Session(engine) as session:
            batch = session.get(RegressionBatch, batch_id)
            runs = session.exec(select(DBTestRun).where(DBTestRun.batch_id == batch_id)).all()
            items = session.exec(select(RegressionBatchItem).where(RegressionBatchItem.batch_id == batch_id)).all()

            assert batch is not None
            assert batch.scheduler_status == "cancelled"
            assert batch.dispatch_cancelled == 3
            assert {run.status for run in runs} == {"cancelled"}
            assert {item.status for item in items} == {"cancelled"}
    finally:
        _cleanup_batch(engine, project_id, batch_id)
