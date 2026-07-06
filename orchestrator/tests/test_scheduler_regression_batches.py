import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-scheduler-regression-batches")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlmodel import Session, select


def _write_specs(specs_dir: Path, spec_names: list[str]) -> None:
    for spec_name in spec_names:
        spec_path = specs_dir / spec_name
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(f"# {spec_path.stem}\n", encoding="utf-8")


def _cleanup_scheduler_records(engine, project_id: str, schedule_id: str, batch_id: str | None = None) -> None:
    from orchestrator.api.models_db import CronSchedule, Project, RegressionBatch, RegressionBatchItem, ScheduleExecution
    from orchestrator.api.models_db import TestRun as DBTestRun

    with Session(engine) as session:
        for execution in session.exec(select(ScheduleExecution).where(ScheduleExecution.schedule_id == schedule_id)).all():
            session.delete(execution)
        schedule = session.get(CronSchedule, schedule_id)
        if schedule:
            session.delete(schedule)
        if batch_id:
            for item in session.exec(select(RegressionBatchItem).where(RegressionBatchItem.batch_id == batch_id)).all():
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


def test_cron_schedule_uses_durable_batch_for_oversized_selection(tmp_path, monkeypatch):
    from orchestrator.api import main as main_module
    from orchestrator.api import spec_files
    from orchestrator.api.db import engine, init_db
    from orchestrator.api.models_db import CronSchedule, Project, RegressionBatch, RegressionBatchItem, ScheduleExecution
    from orchestrator.api.models_db import TestRun as DBTestRun
    from orchestrator.services import batch_executor, scheduled_batch_executor
    from orchestrator.services.scheduler import _execute_scheduled_batch

    project_id = f"scheduler-large-{uuid4().hex}"
    schedule_id = f"sched-{uuid4().hex[:8]}"
    spec_names = [f"flows/case-{index}.md" for index in range(3)]
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
    monkeypatch.setenv("QUORVEX_REGRESSION_CHUNK_SIZE", "2")
    monkeypatch.setenv("QUORVEX_REGRESSION_MAX_ACTIVE_PER_BATCH", "1")
    monkeypatch.setenv("QUORVEX_REGRESSION_GLOBAL_ACTIVE_LIMIT", "100")
    monkeypatch.setattr(batch_executor, "BASE_DIR", tmp_path)
    monkeypatch.setattr(batch_executor, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(batch_executor, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(spec_files, "BASE_DIR", tmp_path)
    monkeypatch.setattr(spec_files, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(spec_files, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(scheduled_batch_executor, "browser_runtime_status", lambda: {"live_view_available": False})
    monkeypatch.setattr(main_module, "BROWSER_POOL", type("FakePool", (), {"effective_max_browsers": 5})())
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
            session.add(Project(id=project_id, name=f"Scheduler Large {uuid4().hex}"))
            session.add(
                CronSchedule(
                    id=schedule_id,
                    project_id=project_id,
                    name="Nightly Regression",
                    cron_expression="0 1 * * *",
                    automated_only=False,
                    spec_names_json='["flows/case-0.md", "flows/case-1.md", "flows/case-2.md"]',
                    enabled=True,
                    status="active",
                )
            )
            session.commit()

        asyncio.run(_execute_scheduled_batch(schedule_id))

        with Session(engine) as session:
            execution = session.exec(
                select(ScheduleExecution).where(ScheduleExecution.schedule_id == schedule_id)
            ).one()
            schedule = session.get(CronSchedule, schedule_id)
            created_batch_id = execution.batch_id
            batch = session.get(RegressionBatch, created_batch_id)
            items = session.exec(select(RegressionBatchItem).where(RegressionBatchItem.batch_id == created_batch_id)).all()
            runs = session.exec(select(DBTestRun).where(DBTestRun.batch_id == created_batch_id)).all()

            assert execution.status == "running"
            assert execution.batch_id
            assert execution.total_tests == 3
            assert execution.error_message is None
            assert schedule is not None
            assert schedule.status == "active"
            assert schedule.last_error is None
            assert schedule.last_batch_id == execution.batch_id
            assert schedule.total_executions == 1
            assert batch is not None
            assert batch.name == "Scheduled: Nightly Regression"
            assert batch.scheduler_status == "dispatching"
            assert batch.dispatch_total == 3
            assert batch.chunk_size == 2
            assert batch.max_active_runs == 5
            assert len(items) == 3
            assert len(runs) == 2
            assert len(started_run_ids) == 2
    finally:
        _cleanup_scheduler_records(engine, project_id, schedule_id, created_batch_id)


def test_scheduled_regression_batch_limits_healer_for_existing_generated_tests(tmp_path, monkeypatch):
    from orchestrator.api import spec_files
    from orchestrator.api.db import engine, init_db
    from orchestrator.api.models_db import RegressionBatch, RegressionBatchItem
    from orchestrator.services import batch_executor, scheduled_batch_executor

    project_id = f"scheduler-healer-limit-{uuid4().hex}"
    spec_name = "flows/reused.md"
    specs_dir = tmp_path / "specs"
    runs_dir = tmp_path / "runs"
    generated_dir = tmp_path / "tests" / "generated"
    (specs_dir / "flows").mkdir(parents=True)
    runs_dir.mkdir()
    generated_dir.mkdir(parents=True)
    (specs_dir / spec_name).write_text("# Reused\n", encoding="utf-8")
    (generated_dir / "reused.spec.ts").write_text(
        "import { test } from '@playwright/test';\ntest('reused', async () => {});\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(batch_executor, "BASE_DIR", tmp_path)
    monkeypatch.setattr(batch_executor, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(batch_executor, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(spec_files, "BASE_DIR", tmp_path)
    monkeypatch.setattr(spec_files, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(spec_files, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(scheduled_batch_executor, "_actual_test_count_for_spec", lambda _spec_name: 1)

    init_db()
    batch_id = None
    try:
        with Session(engine) as session:
            result = scheduled_batch_executor.create_scheduled_regression_batch(
                batch_executor.BatchConfig(project_id=project_id, automated_only=True),
                session,
                spec_names=[spec_name],
                browser_auth_session_id=None,
                use_project_default_browser_auth=False,
                model_tier=None,
            )
            batch_id = result.batch_id
            item = session.exec(
                select(RegressionBatchItem).where(RegressionBatchItem.batch_id == batch_id)
            ).one()
            assert item.payload["healer_max_attempts"] == 1
    finally:
        with Session(engine) as session:
            if batch_id:
                for item in session.exec(
                    select(RegressionBatchItem).where(RegressionBatchItem.batch_id == batch_id)
                ).all():
                    session.delete(item)
                batch = session.get(RegressionBatch, batch_id)
                if batch:
                    session.delete(batch)
            session.commit()


def test_cron_schedule_keeps_immediate_batch_for_small_selection(tmp_path, monkeypatch):
    from orchestrator.api import main as main_module
    from orchestrator.api.db import engine, init_db
    from orchestrator.api.models_db import CronSchedule, Project, RegressionBatch, ScheduleExecution
    from orchestrator.api.models_db import TestRun as DBTestRun
    from orchestrator.services import batch_executor
    from orchestrator.services.scheduler import _execute_scheduled_batch

    project_id = f"scheduler-small-{uuid4().hex}"
    schedule_id = f"sched-{uuid4().hex[:8]}"
    spec_names = ["flows/small.md"]
    specs_dir = tmp_path / "specs"
    runs_dir = tmp_path / "runs"
    specs_dir.mkdir()
    runs_dir.mkdir()
    _write_specs(specs_dir, spec_names)

    async def fake_execute_run_task_wrapper(**kwargs):
        with Session(engine) as session:
            run = session.get(DBTestRun, kwargs["run_id"])
            if run:
                run.status = "passed"
                session.add(run)
                session.commit()

    monkeypatch.setenv("QUORVEX_MAX_BULK_RUN_SPECS", "50")
    monkeypatch.setattr(batch_executor, "BASE_DIR", tmp_path)
    monkeypatch.setattr(batch_executor, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(batch_executor, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(main_module, "PROCESS_MANAGER", None)
    monkeypatch.setattr(main_module, "execute_run_task_wrapper", fake_execute_run_task_wrapper)
    monkeypatch.setattr(main_module, "_task_exception_handler", lambda task: None)

    init_db()
    created_batch_id = None
    try:
        with Session(engine) as session:
            session.add(Project(id=project_id, name=f"Scheduler Small {uuid4().hex}"))
            session.add(
                CronSchedule(
                    id=schedule_id,
                    project_id=project_id,
                    name="Small Regression",
                    cron_expression="0 1 * * *",
                    automated_only=False,
                    spec_names_json='["flows/small.md"]',
                    enabled=True,
                    status="active",
                )
            )
            session.commit()

        asyncio.run(_execute_scheduled_batch(schedule_id))

        with Session(engine) as session:
            execution = session.exec(
                select(ScheduleExecution).where(ScheduleExecution.schedule_id == schedule_id)
            ).one()
            created_batch_id = execution.batch_id
            batch = session.get(RegressionBatch, created_batch_id)

            assert execution.batch_id
            assert execution.total_tests == 1
            assert execution.status == "running"
            assert batch is not None
            assert batch.scheduler_status is None
    finally:
        _cleanup_scheduler_records(engine, project_id, schedule_id, created_batch_id)
