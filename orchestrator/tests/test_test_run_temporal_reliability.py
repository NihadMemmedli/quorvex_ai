from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from orchestrator.api.test_run_runtime_support import start_test_run_temporal_or_fail


class _Session:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_start_test_run_temporal_fails_when_browser_queue_has_no_pollers(monkeypatch, tmp_path):
    from orchestrator.services import temporal_client

    async def _no_pollers(task_queue):
        return {
            "task_queue": task_queue,
            "workflow": {"poller_count": 0},
            "activity": {"poller_count": 0},
        }

    async def _unexpected_start(*args, **kwargs):
        raise AssertionError("workflow should not start without pollers")

    monkeypatch.setattr(temporal_client, "describe_temporal_task_queue", _no_pollers)
    monkeypatch.setattr(temporal_client, "start_test_run_workflow", _unexpected_start)

    run_dir = tmp_path / "run-no-pollers"
    run_dir.mkdir()
    run = SimpleNamespace(
        id="run-no-pollers",
        status="queued",
        queue_position=1,
        completed_at=None,
        error_message=None,
        stage_message=None,
        batch_id=None,
        temporal_workflow_id=None,
        temporal_run_id=None,
    )
    runtime = SimpleNamespace(
        RUNS_DIR=tmp_path,
        datetime=__import__("datetime").datetime,
        update_batch_stats=lambda batch_id: None,
    )
    session = _Session()

    with pytest.raises(HTTPException) as exc:
        await start_test_run_temporal_or_fail(
            runtime,
            run,
            {"run_dir": str(run_dir)},
            session,
            task_queue="quorvex-browser-workflows",
        )

    assert exc.value.status_code == 503
    assert run.status == "error"
    assert run.queue_position is None
    assert "No Temporal pollers" in run.error_message
    assert (run_dir / "status.txt").read_text() == "error"
