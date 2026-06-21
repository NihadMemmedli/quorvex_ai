import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.api.models_db import TestRun as DBTestRun
from orchestrator.api.run_files import build_run_observability_health


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
