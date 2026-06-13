import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.agents.exploratory_agent import ExplorationState, ExploratoryAgent


def _agent() -> ExploratoryAgent:
    agent = ExploratoryAgent()
    agent.state = ExplorationState(start_time=time.time())
    return agent


def test_process_results_fails_parse_fallback_with_zero_evidence(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    agent = _agent()

    result = agent._process_results(
        "I could not complete the task. There is no structured result here.",
        {"url": "https://example.com", "time_limit_minutes": 1, "project_id": "default"},
    )

    assert result["status"] == "failed"
    assert result["exploration_failed"] is True
    assert result["failure_reason"] == "zero_evidence_parse_fallback"
    assert result["parsing_failed"] is True
    assert result["action_trace"] == []
    assert result["total_flows_discovered"] == 0
    assert result["coverage"]["coverage_score"] == 0.0
    assert result["error_details"]
    assert "no structured result" in result["raw_output_preview"]


def test_process_results_keeps_recovered_action_trace_successful(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    agent = _agent()

    result = agent._process_results(
        "\n".join(
            [
                "Step 1: Navigate https://example.com",
                "Step 2: Click Sign in",
                "Step 3: Fill Email",
            ]
        ),
        {"url": "https://example.com", "time_limit_minutes": 1, "project_id": "default"},
    )

    assert result.get("status") != "failed"
    assert result["parsing_failed"] is True
    assert len(result["action_trace"]) == 3
    assert result["total_flows_discovered"] == 1
    assert result["coverage"]["coverage_score"] > 0.0
