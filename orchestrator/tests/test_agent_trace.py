import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlmodel import Session, SQLModel, select

from orchestrator.api import db as db_module
from orchestrator.api.db import engine
from orchestrator.api.models_db import AgentRun, AgentTraceSnapshot, AgentTraceSpan
from orchestrator.services.agent_run_events import create_agent_run_event
from orchestrator.services.agent_trace import ensure_trace_snapshot, list_trace_spans, record_trace_span, serialize_span


def _ensure_tables() -> None:
    SQLModel.metadata.create_all(engine, checkfirst=True)
    db_module._run_migrations()


def _cleanup_run(run_id: str) -> None:
    with Session(engine) as session:
        for span in session.exec(select(AgentTraceSpan).where(AgentTraceSpan.run_id == run_id)).all():
            session.delete(span)
        for snapshot in session.exec(select(AgentTraceSnapshot).where(AgentTraceSnapshot.run_id == run_id)).all():
            session.delete(snapshot)
        run = session.get(AgentRun, run_id)
        if run:
            session.delete(run)
        session.commit()
    shutil.rmtree(Path(__file__).resolve().parents[2] / "runs" / run_id, ignore_errors=True)


def _create_run(run_id: str) -> None:
    with Session(engine) as session:
        run = AgentRun(
            id=run_id,
            agent_type="custom",
            runtime="claude_sdk",
            status="running",
            config_json=json.dumps({"allowed_tools": ["Read"], "test_data_refs": ["login.admin"]}),
            project_id=None,
        )
        session.add(run)
        session.commit()


def test_trace_snapshot_redacts_prompt_and_creates_prompt_span():
    _ensure_tables()
    run_id = "agent-trace-redaction"
    _cleanup_run(run_id)
    _create_run(run_id)

    try:
        snapshot = ensure_trace_snapshot(
            run_id=run_id,
            prompt="Use token Bearer abc.def.ghi and password=secret",
            runtime="claude_sdk",
            allowed_tools=["Read"],
        )

        assert snapshot is not None
        assert snapshot.prompt_hash
        assert "Bearer [redacted]" in snapshot.prompt_preview
        assert "abc.def.ghi" not in snapshot.prompt_preview
        artifact = Path(__file__).resolve().parents[2] / "runs" / run_id / "trace" / "final_prompt.redacted.json"
        artifact_text = artifact.read_text(encoding="utf-8")
        assert "Bearer [redacted]" in artifact_text
        assert "password=[redacted]" in artifact_text
        assert "abc.def.ghi" not in artifact_text
        assert "password=secret" not in artifact_text
        spans = list_trace_spans(run_id=run_id)
        assert any(span.span_type == "prompt_build" for span in spans)
        assert snapshot.prompt_artifact_path and snapshot.prompt_artifact_path.endswith("final_prompt.redacted.json")
    finally:
        _cleanup_run(run_id)


def test_trace_spans_filter_and_link_agent_events():
    _ensure_tables()
    run_id = "agent-trace-spans"
    _cleanup_run(run_id)
    _create_run(run_id)

    try:
        event = create_agent_run_event(
            run_id=run_id,
            event_type="tool_call",
            message="Using Read.",
            payload={"tool_name": "Read", "tool_input": {"api_key": "secret", "path": "README.md"}},
        )
        record_trace_span(
            run_id=run_id,
            span_type="tool_result",
            name="Read result",
            tool_name="Read",
            success=True,
            duration_ms=12,
            output_preview={"content": "ok"},
        )

        tool_spans = list_trace_spans(run_id=run_id, span_type="tool_call")
        assert event is not None
        assert len(tool_spans) == 1
        response = serialize_span(tool_spans[0])
        assert response["agent_run_event_id"] == event.id
        assert response["input_preview"]["api_key"] == "[redacted]"

        result_spans = list_trace_spans(run_id=run_id, tool="Read", q="result")
        assert any(span.span_type == "tool_result" for span in result_spans)
    finally:
        _cleanup_run(run_id)
