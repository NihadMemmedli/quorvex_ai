import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.api import load_testing
from orchestrator.services import k6_queue, load_test_lock
from orchestrator.services.k6_queue import K6Task, K6TaskStatus
from orchestrator.workflows import load_test_runner


class _FakeRedis:
    def __init__(self, results: dict[str, dict]):
        self._results = results

    async def hget(self, key: str, task_id: str):
        result = self._results.get(task_id)
        return json.dumps(result) if result is not None else None


class _FakeQueue:
    RESULTS_KEY = "results"

    def __init__(self, task: K6Task, results: dict[str, dict] | None = None):
        self._task = task
        self._redis = _FakeRedis(results or {})

    async def connect(self):
        return None

    async def get_task(self, task_id: str):
        if task_id == self._task.id:
            return self._task
        return None


@pytest.mark.asyncio
async def test_completed_single_worker_distributed_job_releases_lock_and_syncs_db(monkeypatch):
    task = K6Task(
        id="task-1",
        run_id="load-abc12345",
        script_path="scripts/load/demo.k6.js",
        status=K6TaskStatus.COMPLETED,
    )
    result = {
        "status": "completed",
        "run_dir": "runs/load/load-abc12345",
        "exit_code": 0,
        "summary": {
            "thresholds_passed": True,
            "overview": {
                "total_requests": 42,
                "avg_response_time_ms": 123.4,
                "requests_per_second": 7.8,
            },
        },
    }
    fake_queue = _FakeQueue(task, {task.id: result})
    jobs = {
        "abc12345": {
            "status": "running",
            "stage": "queued",
            "message": "Queuing load test...",
            "result": {"run_id": task.run_id},
            "started_at": 1.0,
            "completed_at": None,
            "_task_id": task.id,
            "_distributed": True,
        }
    }
    sync_calls = []
    release_calls = []

    async def fake_release(run_id: str):
        release_calls.append(run_id)
        return True

    monkeypatch.setattr(load_testing, "_load_jobs", jobs)
    monkeypatch.setattr(k6_queue, "get_k6_queue", lambda: fake_queue)
    monkeypatch.setattr(load_test_runner, "update_db_record", lambda run_id, data: sync_calls.append((run_id, data)))
    monkeypatch.setattr(load_test_lock, "release", fake_release)

    response = await load_testing.get_job_status("abc12345")

    assert response["status"] == "completed"
    assert response["stage"] == "done"
    assert response["message"] == "42 requests, 123.4ms avg, 7.8 rps"
    assert response["result"]["total_requests"] == 42
    assert sync_calls == [(task.run_id, result)]
    assert release_calls == [task.run_id]
    assert jobs["abc12345"]["_lock_released"] is True


@pytest.mark.asyncio
async def test_cancelled_single_worker_distributed_job_releases_lock_without_result(monkeypatch):
    task = K6Task(
        id="task-2",
        run_id="load-cancel1",
        script_path="scripts/load/demo.k6.js",
        status=K6TaskStatus.CANCELLED,
        error="Cancelled by user",
    )
    fake_queue = _FakeQueue(task)
    jobs = {
        "cancel1": {
            "status": "running",
            "stage": "running",
            "message": "K6 load test running...",
            "result": {"run_id": task.run_id},
            "started_at": 1.0,
            "completed_at": None,
            "_task_id": task.id,
            "_distributed": True,
        }
    }
    release_calls = []

    async def fake_release(run_id: str):
        release_calls.append(run_id)
        return True

    monkeypatch.setattr(load_testing, "_load_jobs", jobs)
    monkeypatch.setattr(k6_queue, "get_k6_queue", lambda: fake_queue)
    monkeypatch.setattr(load_test_lock, "release", fake_release)

    response = await load_testing.get_job_status("cancel1")

    assert response["status"] == "cancelled"
    assert response["stage"] == "cancelled"
    assert response["message"] == "Cancelled by user"
    assert response["result"]["run_id"] == task.run_id
    assert release_calls == [task.run_id]
    assert jobs["cancel1"]["_lock_released"] is True
