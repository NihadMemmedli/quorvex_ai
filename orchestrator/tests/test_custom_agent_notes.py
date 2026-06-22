import importlib.util
import sys
from pathlib import Path

from sqlmodel import Session, SQLModel, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.api import db as db_module
from orchestrator.api.agent_definition_support import _resolve_agent_tools, _sync_agent_tool_catalog
from orchestrator.api.db import engine
from orchestrator.api.models_db import AgentRun, AgentRunEvent, AgentRunEvidence, AgentRunNote, AgentRunTaskContract
from orchestrator.services.agent_native_runs import list_agent_run_notes


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
        for evidence in session.exec(select(AgentRunEvidence).where(AgentRunEvidence.run_id == run_id)).all():
            session.delete(evidence)
        for note in session.exec(select(AgentRunNote).where(AgentRunNote.run_id == run_id)).all():
            session.delete(note)
        for contract in session.exec(select(AgentRunTaskContract).where(AgentRunTaskContract.run_id == run_id)).all():
            session.delete(contract)
        for event in session.exec(select(AgentRunEvent).where(AgentRunEvent.run_id == run_id)).all():
            session.delete(event)
        run = session.get(AgentRun, run_id)
        if run:
            session.delete(run)
        session.commit()


def test_agent_tool_catalog_sync_and_resolve_includes_agent_note():
    _ensure_tables()
    with Session(engine) as session:
        tools = _sync_agent_tool_catalog(session)
        note_tool = next(tool for tool in tools if tool.id == "agent_note")

        assert note_tool.tool_name == "mcp__quorvex-agent__quorvex_record_note"
        assert note_tool.category == "Notes"
        assert note_tool.risk == "low"
        assert note_tool.requires_mcp_server == "quorvex-agent"

        allowed_tools, selected_tools = _resolve_agent_tools(["agent_note"], session)

    assert allowed_tools == ["mcp__quorvex-agent__quorvex_record_note"]
    assert selected_tools[0]["id"] == "agent_note"


def test_resolve_agent_tools_auto_adds_agent_note_tool():
    _ensure_tables()
    with Session(engine) as session:
        allowed_tools, selected_tools = _resolve_agent_tools(["read_file"], session)

    assert allowed_tools == ["Read", "mcp__quorvex-agent__quorvex_record_note"]
    assert [tool["id"] for tool in selected_tools] == ["read_file", "agent_note"]


def test_custom_tool_use_callback_records_events_without_native_tool_notes():
    source = (Path(__file__).resolve().parents[1] / "api" / "agent_background_runner_support.py").read_text()
    section = source.split("def _on_custom_tool_use", 1)[1].split("def _on_custom_progress", 1)[0]

    assert "_record_agent_run_event" in section
    assert "_update_agent_run_progress" in section
    assert "_commit_native_note" not in section


def test_custom_runtime_always_wires_agent_note_tool_and_prompt_guidance():
    source = (Path(__file__).resolve().parents[1] / "api" / "agent_background_runner_support.py").read_text()
    custom_section = source.split('elif agent_type == "custom":', 1)[1].split("# Update DB success", 1)[0]

    assert 'allowed_tools.append("mcp__quorvex-agent__quorvex_record_note")' in custom_section
    assert 'include_agent_note_tool=True' in custom_section
    assert "Use quorvex_record_note for meaningful findings, decisions, blockers, handoff notes" in custom_section
    assert "validation observations" in custom_section


def test_custom_partial_finalization_uses_partial_event_type():
    source = (Path(__file__).resolve().parents[1] / "api" / "agent_background_runner_support.py").read_text()
    finalization_section = source.split("# Update DB success", 1)[1].split("except asyncio.CancelledError", 1)[0]

    assert '"partial" if run.status == AGENT_PARTIAL_STATUS else "complete"' in finalization_section
    assert '"Agent run completed with partial output."' in finalization_section


def test_quorvex_record_note_commits_agent_source_note(monkeypatch):
    _ensure_tables()
    run_id = "custom-agent-explicit-note"
    _cleanup_run(run_id)
    _create_agent_run(run_id)
    monkeypatch.setenv("QUORVEX_AGENT_RUN_ID", run_id)

    server_path = Path(__file__).resolve().parents[2] / "tools" / "agent_note_mcp" / "server.py"
    spec = importlib.util.spec_from_file_location("agent_note_mcp_server", server_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    try:
        result = module.quorvex_record_note(
            title="Checkout validation gap",
            body="Postal code submission did not show validation feedback.",
            note_type="finding",
            level="warning",
            tags=["checkout", "validation"],
            actionable=True,
            confidence=0.84,
            url="https://example.test/checkout",
        )

        assert result["status"] == "recorded"
        assert result["type"] == "finding"

        notes = list_agent_run_notes(run_id=run_id)
        assert len(notes) == 1
        note = notes[0]
        assert note.source == "agent"
        assert note.note_type == "finding"
        assert note.level == "warning"
        assert note.title == "Checkout validation gap"
        assert note.actionable is True
        assert note.confidence == 0.84
        assert note.tags == ["checkout", "validation"]
    finally:
        _cleanup_run(run_id)


def test_quorvex_record_note_accepts_healer_note_types(monkeypatch):
    _ensure_tables()
    run_id = "custom-agent-healer-note-type"
    _cleanup_run(run_id)
    _create_agent_run(run_id)
    monkeypatch.setenv("QUORVEX_AGENT_RUN_ID", run_id)

    server_path = Path(__file__).resolve().parents[2] / "tools" / "agent_note_mcp" / "server.py"
    spec = importlib.util.spec_from_file_location("agent_note_mcp_server_healer", server_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    try:
        result = module.quorvex_record_note(
            title="Sort dropdown evidence captured",
            body="Options were inspected before patching.",
            note_type="evidence",
            tags=["healer"],
        )

        assert result["status"] == "recorded"
        assert result["type"] == "evidence"
        notes = list_agent_run_notes(run_id=run_id)
        assert notes[0].note_type == "evidence"
    finally:
        _cleanup_run(run_id)
