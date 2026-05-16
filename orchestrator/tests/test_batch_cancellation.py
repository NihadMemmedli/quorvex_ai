import asyncio
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from orchestrator.api.models_db import RegressionBatch
from orchestrator.api.models_db import TestRun as DBTestRun
from orchestrator.api.process_manager import ProcessInfo, ProcessManager
from orchestrator.api.regression import _apply_batch_status_counts


def _now():
    return datetime.now(timezone.utc)


def test_batch_stats_treat_cancelled_as_stopped_terminal():
    batch = RegressionBatch(id="batch-test", status="running")
    runs = [
        DBTestRun(id="run-passed", spec_name="a.md", status="passed", completed_at=_now()),
        DBTestRun(id="run-cancelled", spec_name="b.md", status="cancelled", completed_at=_now()),
    ]

    _apply_batch_status_counts(batch, runs)

    assert batch.status == "completed"
    assert batch.passed == 1
    assert batch.stopped == 1
    assert batch.running == 0
    assert batch.queued == 0


def test_batch_stats_stay_running_when_active_runs_remain():
    batch = RegressionBatch(id="batch-test", status="pending")
    runs = [
        DBTestRun(id="run-cancelled", spec_name="a.md", status="cancelled", completed_at=_now()),
        DBTestRun(id="run-queued", spec_name="b.md", status="queued"),
    ]

    _apply_batch_status_counts(batch, runs)

    assert batch.status == "running"
    assert batch.stopped == 1
    assert batch.queued == 1


def test_process_manager_stop_prefers_process_group_over_task(tmp_path):
    manager = ProcessManager(data_dir=tmp_path)
    loop = asyncio.new_event_loop()
    task = loop.create_task(asyncio.sleep(60))
    manager._asyncio_tasks["run-1"] = task
    manager._processes["run-1"] = ProcessInfo(
        run_id="run-1",
        pid=123,
        pgid=456,
        started_at=_now().isoformat(),
    )
    calls = []

    def terminate_group(pgid: int, pid: int, timeout: int = 5) -> bool:
        calls.append((pgid, pid, timeout))
        return True

    manager._terminate_process_group = terminate_group

    try:
        assert manager.stop("run-1", timeout=7) is True
        assert calls == [(456, 123, 7)]
        assert not task.cancelled()
        assert "run-1" not in manager._processes
        assert "run-1" not in manager._asyncio_tasks
    finally:
        task.cancel()
        loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
        loop.close()


def test_process_manager_can_wait_for_process_registration_before_task_cancel(tmp_path):
    manager = ProcessManager(data_dir=tmp_path)
    loop = asyncio.new_event_loop()
    task = loop.create_task(asyncio.sleep(60))
    manager._asyncio_tasks["run-1"] = task

    try:
        assert manager.stop("run-1", cancel_task_if_no_process=False) is False
        assert not task.cancelled()
        assert "run-1" in manager._asyncio_tasks
    finally:
        task.cancel()
        loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
        loop.close()
