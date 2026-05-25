import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.api import db as db_module
from orchestrator.api.db import engine
from orchestrator.api.models_db import AgentRun, AgentRunEvent
from orchestrator.services.agent_queue import AgentTask, AgentTaskStatus
from orchestrator.services.agent_run_events import (
    create_agent_run_event,
    event_to_response,
    list_agent_run_events,
    safe_event_payload,
)
from orchestrator.tests.test_agent_queue_reliability import _MemoryQueue, _MemoryRedis


def _ensure_tables() -> None:
    SQLModel.metadata.create_all(engine, checkfirst=True)
    db_module._run_migrations()


def _create_agent_run(run_id: str) -> None:
    with Session(engine) as session:
        session.add(
            AgentRun(
                id=run_id,
                agent_type="custom",
                status="running",
                config_json="{}",
                project_id=None,
            )
        )
        session.commit()


def _cleanup_run(run_id: str) -> None:
    with Session(engine) as session:
        for event in session.exec(select(AgentRunEvent).where(AgentRunEvent.run_id == run_id)).all():
            session.delete(event)
        run = session.get(AgentRun, run_id)
        if run:
            session.delete(run)
        session.commit()


def test_agent_run_event_payload_redacts_and_truncates_sensitive_values():
    payload = safe_event_payload(
        {
            "authorization": "Bearer abc.def.ghi",
            "nested": {"api_key": "secret-key", "message": "Bearer visible-token"},
            "items": list(range(100)),
        }
    )

    assert payload["authorization"] == "[redacted]"
    assert payload["nested"]["api_key"] == "[redacted]"
    assert payload["nested"]["message"] == "Bearer [redacted]"
    assert len(payload["items"]) == 80


def test_agent_run_events_are_sequence_ordered_and_serialized():
    _ensure_tables()
    run_id = "agent-run-events-sequence"
    _cleanup_run(run_id)
    _create_agent_run(run_id)

    try:
        first = create_agent_run_event(
            run_id=run_id,
            event_type="queued",
            message="Queued",
            payload={"token": "secret"},
        )
        second = create_agent_run_event(
            run_id=run_id,
            event_type="tool_call",
            message="Tool call",
            agent_task_id="agent-task-1",
            payload={"tool_name": "Read"},
        )

        assert first is not None
        assert second is not None
        assert first.sequence == 1
        assert second.sequence == 2

        events = list_agent_run_events(run_id=run_id, after_sequence=1)
        assert [event.sequence for event in events] == [2]
        response = event_to_response(events[0])
        assert response["agent_task_id"] == "agent-task-1"
        assert response["payload"] == {"tool_name": "Read"}
    finally:
        _cleanup_run(run_id)


@pytest.mark.asyncio
async def test_agent_queue_cleanup_emits_agent_run_recovery_event():
    _ensure_tables()
    run_id = "agent-run-events-cleanup"
    task_id = "agent-cleanup-task"
    _cleanup_run(run_id)
    _create_agent_run(run_id)

    redis = _MemoryRedis()
    queue = _MemoryQueue(redis)
    task = AgentTask(
        id=task_id,
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        owner_type="agent_run",
        owner_id=run_id,
        started_at=datetime.utcnow() - timedelta(minutes=60),
        timeout_seconds=10,
    )
    await redis.hset(queue.TASKS_KEY, task.id, json.dumps(task.to_dict()))
    await redis.sadd(queue.RUNNING_KEY, task.id)

    try:
        counts = await queue.cleanup_orphaned_and_stale_tasks(max_age_minutes=45)

        assert counts["timed_out"] == 1
        events = list_agent_run_events(run_id=run_id, event_type="recovery")
        assert len(events) == 1
        assert "timed out" in events[0].message.lower()
        assert events[0].payload["status"] == "timeout"
    finally:
        _cleanup_run(run_id)
