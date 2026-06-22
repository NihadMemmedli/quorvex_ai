import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.api import run_files as run_files_module
from orchestrator.api.models_db import TestRun as DBTestRun
from orchestrator.api.run_files import build_run_observability_health, compose_test_run_log_payload


def _touch(path: Path, when: datetime) -> None:
    timestamp = when.timestamp()
    os.utime(path, (timestamp, timestamp))


def test_run_health_does_not_warn_for_long_running_temporal_activity_with_recent_log(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    now = datetime.now(timezone.utc)
    log_path = run_dir / "execution.log"
    log_path.write_text("still running\n")
    _touch(log_path, now - timedelta(seconds=15))
    run = DBTestRun(
        id="run-active",
        spec_name="checkout.md",
        status="running",
        current_stage="execution",
        stage_started_at=now - timedelta(minutes=5),
    )

    health = build_run_observability_health(
        run,
        run_dir,
        {
            "temporal": {
                "history_last_event_at": (now - timedelta(minutes=5)).isoformat(),
                "activities": [{"activity_type": "execute_test_run", "status": "started"}],
            }
        },
    )

    assert health["has_recent_output"] is True
    assert health["stuck_warning"] is None
    assert health["warnings"] == []


def test_run_health_does_not_warn_for_long_running_temporal_activity_with_recent_artifact(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    now = datetime.now(timezone.utc)
    log_path = run_dir / "execution.log"
    artifact_path = run_dir / "test-results" / "trace.zip"
    artifact_path.parent.mkdir()
    log_path.write_text("old log\n")
    artifact_path.write_text("new artifact")
    _touch(log_path, now - timedelta(minutes=5))
    _touch(artifact_path, now - timedelta(seconds=20))
    run = DBTestRun(
        id="run-artifact-active",
        spec_name="checkout.md",
        status="running",
        current_stage="execution",
        stage_started_at=now - timedelta(minutes=5),
    )

    health = build_run_observability_health(
        run,
        run_dir,
        {
            "temporal": {
                "history_last_event_at": (now - timedelta(minutes=5)).isoformat(),
                "activities": [{"activity_type": "execute_test_run", "status": "started"}],
            }
        },
    )

    assert health["has_recent_output"] is True
    assert health["stuck_warning"] is None
    assert health["warnings"] == []


def test_run_health_warns_when_temporal_history_log_and_artifacts_are_stale(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    now = datetime.now(timezone.utc)
    log_path = run_dir / "execution.log"
    artifact_path = run_dir / "test-results" / "trace.zip"
    artifact_path.parent.mkdir()
    log_path.write_text("old log\n")
    artifact_path.write_text("old artifact")
    _touch(log_path, now - timedelta(minutes=5))
    _touch(artifact_path, now - timedelta(minutes=5))
    run = DBTestRun(
        id="run-stale",
        spec_name="checkout.md",
        status="running",
        current_stage="execution",
        stage_started_at=now - timedelta(minutes=5),
    )

    health = build_run_observability_health(
        run,
        run_dir,
        {
            "temporal": {
                "history_last_event_at": (now - timedelta(minutes=5)).isoformat(),
                "activities": [{"activity_type": "execute_test_run", "status": "started"}],
            }
        },
    )

    assert health["has_recent_output"] is False
    assert health["stuck_warning"] is not None
    assert any("No new execution.log output" in warning for warning in health["warnings"])
    assert any("Temporal activity execute_test_run is started" in warning for warning in health["warnings"])


def test_run_health_warns_for_unproductive_agent_stream(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "execution.log").write_text("fresh log")
    (run_dir / "checkout.md").write_text("# Test Plan: Checkout\n")
    run = DBTestRun(
        id="run-unproductive",
        spec_name="checkout.md",
        status="running",
        current_stage="planning",
        stage_started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )

    health = build_run_observability_health(
        run,
        run_dir,
        {
            "agent_progress": {
                "messages_received": 600,
                "text_blocks_received": 0,
                "tool_calls": 0,
                "output_chars": 0,
                "elapsed_seconds": 240,
                "unproductive_stream": True,
            }
        },
    )

    assert health["agent_progress"]["messages_received"] == 600
    assert health["stuck_warning"] is not None
    assert "600 messages" in health["warnings"][0]
    assert "Saved planner artifacts were detected" in health["warnings"][0]


def _session_event(event_type: str, content: list[dict]) -> str:
    role = "assistant" if event_type == "assistant" else "user"
    return json.dumps({"type": event_type, "message": {"role": role, "content": content}})


@pytest.mark.asyncio
async def test_run_log_sections_include_agent_session_notes_and_tools(tmp_path: Path, monkeypatch):
    class FakePool:
        async def get_status(self):
            return {
                "max_browsers": 1,
                "running": 0,
                "queued": 0,
                "available": 1,
                "running_requests": [],
                "queued_requests": [],
            }

    async def fake_browser_pool():
        return FakePool()

    monkeypatch.setattr(run_files_module, "_browser_pool", fake_browser_pool)

    run_dir = tmp_path / "run"
    session_dir = run_dir / "projects" / "-app-runs-demo"
    session_dir.mkdir(parents=True)
    (run_dir / "agent_progress.json").write_text(
        json.dumps(
            {
                "messages_received": 800,
                "text_blocks_received": 0,
                "tool_calls": 0,
                "output_chars": 0,
            }
        )
    )
    (session_dir / "session-1.jsonl").write_text(
        "\n".join(
            [
                _session_event(
                    "assistant",
                    [
                        {"type": "text", "text": "Opening the page"},
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "mcp__playwright-test__browser_snapshot",
                            "input": {},
                        },
                    ],
                ),
                _session_event(
                    "user",
                    [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "Snapshot captured",
                        }
                    ],
                ),
            ]
        )
    )
    run = DBTestRun(
        id="run-session",
        spec_name="checkout.md",
        status="running",
        current_stage="planning",
        stage_started_at=datetime.now(timezone.utc),
    )

    payload = await compose_test_run_log_payload(run, run_dir)

    titles = [section["title"] for section in payload["log_sections"]]
    assert "Agent Notes" in titles
    assert "Agent Tool Activity" in titles
    assert payload["diagnostics"]["agent_progress"]["tool_calls"] == 1
    assert payload["diagnostics"]["agent_progress"]["text_blocks_received"] == 1
    assert payload["diagnostics"]["agent_progress"]["unproductive_stream"] is False


@pytest.mark.asyncio
async def test_run_log_prefers_structured_healer_notes_over_raw_session_notes(tmp_path: Path, monkeypatch):
    class FakePool:
        async def get_status(self):
            return {
                "max_browsers": 1,
                "running": 0,
                "queued": 0,
                "available": 1,
                "running_requests": [],
                "queued_requests": [],
            }

    async def fake_browser_pool():
        return FakePool()

    monkeypatch.setattr(run_files_module, "_browser_pool", fake_browser_pool)

    run_dir = tmp_path / "run"
    session_dir = run_dir / "projects" / "-app-runs-demo"
    session_dir.mkdir(parents=True)
    (run_dir / "healing_attempts.json").write_text(
        json.dumps(
            {
                "attempts": [
                    {
                        "attempt": 1,
                        "guardrail_status": "passed",
                        "passed_after": True,
                        "mcp_evidence_tools_used": ["test_debug", "browser_evaluate"],
                        "root_cause": "Sort default is persisted by prior user preference.",
                        "strategy": "Assert options, select asc, then verify value changes.",
                        "changed_selectors": "select[name=sort]",
                    }
                ]
            }
        )
    )
    (run_dir / "failure_evidence_packet.json").write_text(
        json.dumps({"attempt": 1, "error_summary": "expected sort to be new", "failed_test": {"title": "TC-009 sort"}})
    )
    (session_dir / "session-1.jsonl").write_text(
        _session_event("assistant", [{"type": "text", "text": "```json\n{\"raw\":\"assistant\"}\n```"}])
    )
    run = DBTestRun(
        id="run-structured-notes",
        spec_name="sort.md",
        status="failed",
        current_stage="healing",
        stage_started_at=datetime.now(timezone.utc),
    )

    payload = await compose_test_run_log_payload(run, run_dir)

    note_sections = [section for section in payload["log_sections"] if section["title"] == "Agent Notes"]
    assert len(note_sections) == 1
    assert note_sections[0]["source"] == "native_healer_structured"
    assert "evidence_tools: test_debug, browser_evaluate" in note_sections[0]["content"]
    assert "attempted_fix: Assert options, select asc, then verify value changes." in note_sections[0]["content"]
    assert "```json" not in note_sections[0]["content"]
    assert any(section["title"] == "Raw Agent Notes" for section in payload["log_sections"])
    assert payload["diagnostics"]["structured_healer_notes"] is True
