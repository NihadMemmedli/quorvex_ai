"""Durable chunked scheduler for large regression batches."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from logging_config import get_logger
from utils.playwright_mcp import browser_runtime_status

from orchestrator.api import run_files, spec_files
from orchestrator.api.models_db import RegressionBatch, RegressionBatchItem
from orchestrator.api.models_db import TestRun as DBTestRun
from orchestrator.utils.browser_auth_classification import is_login_logout_spec

from .batch_executor import BatchConfig, _actual_test_count_for_spec, _get_try_code_path, _test_data_refs_for_spec

logger = get_logger(__name__)

TERMINAL_RUN_STATUSES = {"passed", "completed", "failed", "error", "stopped", "cancelled"}
ACTIVE_ITEM_STATUSES = {"queued", "running"}
DEFAULT_CHUNK_SIZE = 25
DEFAULT_MAX_ACTIVE_RUNS = 4
DEFAULT_GLOBAL_ACTIVE_LIMIT = 6


@dataclass
class ScheduledBatchResult:
    batch_id: str
    count: int
    chunk_size: int
    max_active_runs: int
    dispatched: int


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


def configured_chunk_size() -> int:
    return _env_int("QUORVEX_REGRESSION_CHUNK_SIZE", DEFAULT_CHUNK_SIZE)


def configured_max_active_runs() -> int:
    return _env_int("QUORVEX_REGRESSION_MAX_ACTIVE_PER_BATCH", DEFAULT_MAX_ACTIVE_RUNS)


def configured_global_active_limit() -> int:
    return _env_int("QUORVEX_REGRESSION_GLOBAL_ACTIVE_LIMIT", DEFAULT_GLOBAL_ACTIVE_LIMIT)


def should_schedule_bulk_run(spec_count: int) -> bool:
    from .batch_executor import _max_bulk_run_specs

    return spec_count > _max_bulk_run_specs()


def _is_login_specific_spec(spec_name: str, spec_content: str) -> bool:
    return is_login_logout_spec(spec_name, spec_content)


def create_scheduled_regression_batch(
    config: BatchConfig,
    session: Session,
    *,
    spec_names: list[str],
    browser_auth_session_id: str | None,
    use_project_default_browser_auth: bool,
    model_tier: str | None,
    chunk_size: int | None = None,
    max_active_runs: int | None = None,
) -> ScheduledBatchResult:
    now = datetime.utcnow()
    batch_id = f"batch_{now.strftime('%Y-%m-%d_%H-%M-%S')}_{uuid.uuid4().hex[:8]}"
    selected_chunk_size = chunk_size or configured_chunk_size()
    selected_max_active = max_active_runs or configured_max_active_runs()
    actual_total_tests = sum(_actual_test_count_for_spec(spec_name) for spec_name in spec_names)
    batch = RegressionBatch(
        id=batch_id,
        name=config.batch_name or f"Regression Run - {now.strftime('%Y-%m-%d %H:%M')}",
        triggered_by=config.triggered_by,
        created_at=now,
        browser=config.browser,
        tags_used_json=json.dumps(config.tags or []),
        hybrid_mode=config.hybrid_mode,
        project_id=config.project_id,
        total_tests=len(spec_names),
        queued=len(spec_names),
        actual_total_tests=actual_total_tests,
        actual_passed=0,
        actual_failed=0,
        actual_skipped=0,
        actual_other=0,
        status="pending",
        scheduler_status="pending",
        chunk_size=selected_chunk_size,
        max_active_runs=selected_max_active,
        dispatch_total=len(spec_names),
        next_spec_index=0,
    )
    session.add(batch)

    for ordinal, spec_name in enumerate(spec_names):
        spec_path = spec_files.SPECS_DIR / spec_name
        try_code_path = _get_try_code_path(spec_name, spec_path) if spec_path.exists() else None
        payload = {
            "browser": config.browser,
            "hybrid": config.hybrid_mode,
            "max_iterations": config.max_iterations,
            "healer_max_attempts": 1 if try_code_path else None,
            "project_id": config.project_id,
            "spec_name": spec_name,
            "test_data_refs": _test_data_refs_for_spec(config, spec_name),
            "browser_auth_session_id": browser_auth_session_id,
            "use_project_default_browser_auth": use_project_default_browser_auth,
            "model_tier": model_tier,
        }
        item = RegressionBatchItem(
            id=f"{batch_id}_{ordinal}",
            batch_id=batch_id,
            ordinal=ordinal,
            spec_name=spec_name,
            status="pending",
            payload_json=json.dumps(payload),
            created_at=now,
        )
        session.add(item)
    session.commit()
    logger.info("Created scheduled regression batch %s with %d planned items", batch_id, len(spec_names))
    return ScheduledBatchResult(
        batch_id=batch_id,
        count=len(spec_names),
        chunk_size=selected_chunk_size,
        max_active_runs=selected_max_active,
        dispatched=0,
    )


def refresh_scheduled_batch_counts(session: Session, batch: RegressionBatch) -> None:
    active_items = session.exec(
        select(RegressionBatchItem).where(
            RegressionBatchItem.batch_id == batch.id,
            RegressionBatchItem.run_id != None,  # noqa: E711 - SQLAlchemy needs this
            RegressionBatchItem.status.notin_(list(TERMINAL_RUN_STATUSES)),
        )
    ).all()

    run_ids = [item.run_id for item in active_items if item.run_id]
    runs_by_id: dict[str, DBTestRun] = {}
    if run_ids:
        runs = session.exec(select(DBTestRun).where(DBTestRun.id.in_(run_ids))).all()
        runs_by_id = {run.id: run for run in runs}

    now = datetime.utcnow()
    for item in active_items:
        run = runs_by_id.get(item.run_id)
        if not run:
            continue
        if run.status in TERMINAL_RUN_STATUSES and item.status not in TERMINAL_RUN_STATUSES:
            item.status = run.status
            item.completed_at = run.completed_at or now
            item.error_message = run.error_message
            session.add(item)
        elif run.status in {"running", "in_progress"} and item.status != "running":
            item.status = "running"
            item.started_at = run.started_at or item.started_at or now
            session.add(item)
        elif run.status == "queued" and item.status != "queued":
            item.status = "queued"
            session.add(item)

    rows = session.exec(
        select(RegressionBatchItem.status, func.count(RegressionBatchItem.id))
        .where(RegressionBatchItem.batch_id == batch.id)
        .group_by(RegressionBatchItem.status)
    ).all()
    if not rows:
        return
    counts = {status: int(count or 0) for status, count in rows}
    pending = counts.get("pending", 0)
    passed = counts.get("passed", 0) + counts.get("completed", 0)
    failed = counts.get("failed", 0) + counts.get("error", 0)
    cancelled = counts.get("stopped", 0) + counts.get("cancelled", 0)
    active = sum(counts.get(status, 0) for status in ACTIVE_ITEM_STATUSES)
    started = session.exec(
        select(func.count(RegressionBatchItem.id)).where(
            RegressionBatchItem.batch_id == batch.id,
            RegressionBatchItem.run_id != None,  # noqa: E711 - SQLAlchemy needs this
        )
    ).one()

    batch.total_tests = sum(counts.values())
    batch.passed = passed
    batch.failed = failed
    batch.stopped = cancelled
    batch.running = active
    batch.queued = pending
    batch.dispatch_started = int(started or 0)
    batch.dispatch_completed = passed + failed + cancelled
    batch.dispatch_failed = failed
    batch.dispatch_cancelled = cancelled
    if batch.scheduler_status == "cancelling" and active == 0:
        batch.scheduler_status = "cancelled"
        batch.status = "completed"
        batch.completed_at = batch.completed_at or now
    elif pending == 0 and active == 0:
        batch.scheduler_status = "completed"
        batch.status = "completed"
        batch.completed_at = batch.completed_at or now
    elif active > 0 or pending > 0:
        batch.scheduler_status = "dispatching" if active > 0 else "pending"
        batch.status = "running" if active > 0 else "pending"
        if active > 0 and not batch.started_at:
            batch.started_at = now
    session.add(batch)


def _global_active_run_count(session: Session) -> int:
    statement = select(func.count()).select_from(DBTestRun).where(
        DBTestRun.status.in_(["queued", "running", "in_progress"])
    )
    return int(session.exec(statement).one() or 0)


async def dispatch_scheduled_batch(runtime: Any, batch_id: str) -> int:
    """Dispatch a bounded number of pending items for a scheduled batch."""

    dispatched = 0
    with Session(runtime.engine) as session:
        batch = session.get(RegressionBatch, batch_id)
        if not batch or not batch.scheduler_status or batch.scheduler_status in {"completed", "cancelled", "failed"}:
            return 0
        refresh_scheduled_batch_counts(session, batch)
        session.commit()
        session.refresh(batch)
        if batch.scheduler_status in {"completed", "cancelled", "failed", "cancelling"}:
            return 0

        active_items = session.exec(
            select(RegressionBatchItem).where(
                RegressionBatchItem.batch_id == batch_id,
                RegressionBatchItem.status.in_(list(ACTIVE_ITEM_STATUSES)),
            )
        ).all()
        batch_limit = max(1, batch.max_active_runs or configured_max_active_runs())
        global_available = max(0, configured_global_active_limit() - _global_active_run_count(session))
        available = min(batch_limit - len(active_items), global_available, batch.chunk_size or configured_chunk_size())
        if available <= 0:
            return 0

        pending_items = session.exec(
            select(RegressionBatchItem)
            .where(RegressionBatchItem.batch_id == batch_id, RegressionBatchItem.status == "pending")
            .order_by(RegressionBatchItem.ordinal)
            .limit(available)
        ).all()

        for item in pending_items:
            started = await _materialize_and_start_item(runtime, session, batch, item)
            if started:
                dispatched += 1
        refresh_scheduled_batch_counts(session, batch)
        session.commit()
    return dispatched


async def _materialize_and_start_item(
    runtime: Any,
    session: Session,
    batch: RegressionBatch,
    item: RegressionBatchItem,
) -> bool:
    payload_config = item.payload
    spec_name = item.spec_name
    spec_path = spec_files.SPECS_DIR / spec_name
    now = datetime.utcnow()
    if not spec_path.exists():
        item.status = "error"
        item.completed_at = now
        item.error_message = f"Spec file not found: {spec_name}"
        session.add(item)
        return False

    run_id = now.strftime("%Y-%m-%d_%H-%M-%S") + f"_{uuid.uuid4().hex[:8]}_{spec_name.replace('/', '_')}"
    run_dir = spec_files.RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    spec_content = spec_path.read_text(encoding="utf-8")
    (run_dir / "spec.md").write_text(spec_content, encoding="utf-8")
    (run_dir / "status.txt").write_text("queued", encoding="utf-8")
    try_code_path = _get_try_code_path(spec_name, spec_path)
    healer_max_attempts = payload_config.get("healer_max_attempts")
    if healer_max_attempts is None and try_code_path:
        healer_max_attempts = 1

    queued_count = int(
        session.exec(select(func.count()).select_from(DBTestRun).where(DBTestRun.status == "queued")).one() or 0
    )
    run = DBTestRun(
        id=run_id,
        spec_name=spec_name,
        test_name=spec_name,
        status="queued",
        browser=payload_config.get("browser") or batch.browser,
        queued_at=now,
        queue_position=queued_count + 1,
        batch_id=batch.id,
        project_id=payload_config.get("project_id"),
    )
    session.add(run)
    session.flush()
    item.run_id = run_id
    item.status = "queued"
    item.started_at = now
    session.add(item)
    session.commit()

    requested_browser_auth_session_id = payload_config.get("browser_auth_session_id")
    requested_project_default_auth = bool(payload_config.get("use_project_default_browser_auth"))
    auth_conflict_warning: str | None = None
    if runtime._has_browser_auth_selection(
        browser_auth_session_id=requested_browser_auth_session_id,
        use_project_default_browser_auth=requested_project_default_auth,
    ) and _is_login_specific_spec(spec_name, spec_content):
        auth_conflict_warning = "Selected browser auth was ignored because this spec appears to test login/logout."
        requested_browser_auth_session_id = None
        requested_project_default_auth = False

    storage_state_path, browser_auth_intent = runtime._resolve_browser_auth_storage_state_for_run(
        session,
        payload_config.get("project_id"),
        run_dir=Path(run_dir),
        browser_auth_session_id=requested_browser_auth_session_id,
        use_project_default_browser_auth=requested_project_default_auth,
        target_url=run_files.extract_run_target_url_from_content(spec_content),
    )
    if auth_conflict_warning:
        browser_auth_intent["auth_conflict_warning"] = auth_conflict_warning
        browser_auth_intent["requested_browser_auth_session_id"] = payload_config.get("browser_auth_session_id")
        browser_auth_intent["use_project_default_browser_auth"] = bool(
            payload_config.get("use_project_default_browser_auth")
        )
    test_data_refs = [str(ref).strip() for ref in payload_config.get("test_data_refs") or [] if str(ref).strip()]
    if test_data_refs:
        browser_auth_intent["test_data_refs"] = test_data_refs
    run.browser_auth = browser_auth_intent
    session.add(run)
    session.commit()

    from orchestrator.config import settings as app_settings

    planned_runtime = dict(browser_runtime_status())
    planned_headless = not bool(planned_runtime.get("live_view_available"))
    run_files.write_run_browser_metadata(
        Path(run_dir),
        run_files.build_run_browser_metadata(
            headless=planned_headless,
            phase="scheduled",
            task_queue=app_settings.temporal_browser_workflow_task_queue,
        ),
    )
    payload = {
        "target": "browser",
        "spec_path": str(spec_path),
        "run_dir": str(run_dir),
        "try_code_path": try_code_path,
        "healer_max_attempts": healer_max_attempts,
        "browser": payload_config.get("browser") or batch.browser,
        "hybrid": bool(payload_config.get("hybrid")),
        "max_iterations": payload_config.get("max_iterations") or 20,
        "batch_id": batch.id,
        "spec_name": spec_name,
        "project_id": payload_config.get("project_id"),
        "model_tier": payload_config.get("model_tier"),
        "test_data_refs": test_data_refs,
        "browser_auth_context": browser_auth_intent,
    }
    if storage_state_path:
        payload["storage_state_path"] = storage_state_path
    try:
        await runtime._start_test_run_temporal_or_fail(run, payload, session)
    except Exception as exc:
        item.status = "error"
        item.completed_at = datetime.utcnow()
        item.error_message = str(exc)[:500]
        batch.scheduler_error = str(exc)[:500]
        session.add(item)
        session.add(batch)
        session.commit()
        logger.warning("Failed to start scheduled item %s for batch %s: %s", item.id, batch.id, exc)
        return False
    return True
