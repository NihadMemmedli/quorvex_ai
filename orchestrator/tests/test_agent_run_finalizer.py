import shutil
from pathlib import Path

from orchestrator.services.agent_run_finalizer import AgentRunFinalizer


def _cleanup_run_dir(run_id: str) -> None:
    shutil.rmtree(Path(__file__).resolve().parents[2] / "runs" / run_id, ignore_errors=True)


def test_custom_finalizer_accepts_valid_json_report():
    finalized = AgentRunFinalizer().finalize(
        run_id="finalizer-custom-valid",
        agent_type="custom",
        config={"prompt": "inspect login"},
        raw_model_output='{"structured_report":{"summary":"Looks good","scope":"login","findings":[],"test_ideas":[],"requirements":[],"evidence":[],"pages_checked":[],"follow_up_actions":[]}}',
    )

    assert finalized.status == "completed"
    assert finalized.result["contract_status"] == "valid"
    assert finalized.result["structured_report"]["summary"] == "Looks good"


def test_custom_finalizer_extracts_markdown_wrapped_json():
    finalized = AgentRunFinalizer().finalize(
        run_id="finalizer-custom-markdown",
        agent_type="custom",
        config={"prompt": "inspect login"},
        raw_model_output='Summary\n```json\n{"structured_report":{"summary":"Wrapped","scope":"login","findings":[],"test_ideas":[],"requirements":[],"evidence":[],"pages_checked":[],"follow_up_actions":[]}}\n```',
    )

    assert finalized.status == "completed"
    assert finalized.result["contract_status"] == "repaired"
    assert finalized.result["structured_report"]["summary"] == "Wrapped"


def test_custom_finalizer_repairs_malformed_json():
    finalized = AgentRunFinalizer().finalize(
        run_id="finalizer-custom-malformed",
        agent_type="custom",
        config={"prompt": "inspect login"},
        raw_model_output='```json\n{"structured_report":{"summary":"Trailing comma","scope":"login","findings":[],"test_ideas":[],"requirements":[],"evidence":[],"pages_checked":[],"follow_up_actions":[],}}\n```',
    )

    assert finalized.status == "completed"
    assert finalized.result["contract_status"] == "repaired"
    assert finalized.result["structured_report"]["summary"] == "Trailing comma"
    assert any(item["strategy"] == "repair_malformed_json" and item["status"] == "success" for item in finalized.result["repair_attempts"])


def test_custom_finalizer_synthesizes_partial_report_from_prose_and_artifact():
    finalized = AgentRunFinalizer().finalize(
        run_id="finalizer-custom-prose",
        agent_type="custom",
        config={"prompt": "inspect public pages", "url": "https://example.test"},
        raw_model_output="The login page returned an error and should get regression coverage.",
        artifacts=[{"name": "live-step-001.png", "path": "/artifacts/run/live-step-001.png", "type": "image"}],
    )

    assert finalized.status == "completed_partial"
    assert finalized.result["contract_status"] == "partial"
    assert finalized.result["structured_report"]["evidence"]
    assert finalized.result["contract_warnings"]


def test_custom_finalizer_fails_empty_output_without_evidence():
    finalized = AgentRunFinalizer().finalize(
        run_id="finalizer-custom-empty",
        agent_type="custom",
        config={"prompt": "inspect"},
        raw_model_output="",
    )

    assert finalized.status == "failed"
    assert finalized.result["contract_status"] == "invalid"
    assert "structured output" in finalized.result["summary"]


def test_explorer_finalizer_does_not_invent_unsupported_claimed_flows(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    run_id = "finalizer-explorer-claimed-flows"
    _cleanup_run_dir(run_id)
    try:
        output = "\n".join(
            [
                '{"id":"evt_001","event_type":"page_observed","url":"https://example.test","title":"Home"}',
                "I discovered 2 flows across the app.",
            ]
        )
        finalized = AgentRunFinalizer().finalize(
            run_id=run_id,
            agent_type="exploratory",
            config={"url": "https://example.test", "time_limit_minutes": 1, "project_id": "default"},
            raw_model_output=output,
        )

        assert finalized.status == "completed_partial"
        assert finalized.result["contract_status"] == "partial"
        assert finalized.result["total_flows_discovered"] == 0
        assert finalized.result["discovered_flow_summaries"] == []
        assert any(item["strategy"] == "evidence_to_flow_recovery" for item in finalized.result["repair_attempts"])
    finally:
        _cleanup_run_dir(run_id)


def test_explorer_finalizer_exposes_unsupported_flow_candidates(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    run_id = "finalizer-explorer-unsupported-candidate"
    _cleanup_run_dir(run_id)
    try:
        output = "\n".join(
            [
                '{"id":"evt_001","event_type":"page_observed","url":"https://example.test","title":"Home"}',
                '{"id":"evt_002","event_type":"action_result","action":"click","target":"Pricing","success":true,"outcome":"Pricing opened","url":"https://example.test/pricing"}',
                '{"id":"evt_003","event_type":"flow_candidate","title":"Open pricing","step_event_ids":["evt_001","evt_999"],"evidence_event_ids":["evt_001","evt_999"],"entry_point":"https://example.test","exit_point":"https://example.test/pricing","test_ideas":["Verify pricing opens."],"edge_cases":[]}',
            ]
        )
        finalized = AgentRunFinalizer().finalize(
            run_id=run_id,
            agent_type="exploratory",
            config={"url": "https://example.test", "time_limit_minutes": 1, "project_id": "default"},
            raw_model_output=output,
        )

        assert finalized.status == "completed_partial"
        assert finalized.result["discovered_flow_summaries"] == []
        assert finalized.result["total_flows_discovered"] == 0
        assert finalized.result["unsupported_flow_candidates"][0]["title"] == "Open pricing"
        assert finalized.result["unsupported_flow_candidates"][0]["missing_evidence_event_ids"] == ["evt_999"]
        assert finalized.result["diagnostics"]["unsupported_flow_candidates"] == 1
        assert finalized.result["diagnostics"]["missing_evidence_event_ids"] == ["evt_999"]
    finally:
        _cleanup_run_dir(run_id)


def test_explorer_finalizer_dedupes_warnings_and_counts_artifacts():
    finalized = AgentRunFinalizer().finalize(
        run_id="finalizer-explorer-artifacts",
        agent_type="exploratory",
        config={"url": "https://example.test", "time_limit_minutes": 1, "project_id": "default"},
        raw_model_output="",
        existing_result={
            "summary": "Evidence was captured, but no completed evidence-backed flow was observed.",
            "coverage": {"pages_visited": 0, "flows_discovered": 0},
            "contract_warning": "Evidence was captured, but no completed evidence-backed flow was observed.",
            "contract_warnings": [
                "Evidence was captured, but no completed evidence-backed flow was observed.",
                "Screenshot evidence was captured.",
            ],
            "discovered_flow_summaries": [],
            "total_flows_discovered": 0,
        },
        artifacts=[
            {"name": "live-step-001.png", "path": "/artifacts/run/live-step-001.png", "type": "image"},
            {"name": "exploration.webm", "path": "/artifacts/run/exploration.webm", "type": "video"},
        ],
    )

    assert finalized.status == "completed_partial"
    assert finalized.result["contract_warnings"] == [
        "Evidence was captured, but no completed evidence-backed flow was observed.",
        "Screenshot evidence was captured.",
    ]
    assert "contract_warning" not in finalized.result
    assert finalized.result["artifact_evidence"]["artifact_count"] == 2
    assert finalized.result["artifact_evidence"]["screenshot_count"] == 1
    assert finalized.result["diagnostics"]["finalizer"]["artifact_count"] == 2
    assert finalized.result["diagnostics"]["finalizer"]["screenshot_count"] == 1


def test_explorer_finalizer_requires_browser_telemetry_for_flows(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    artifact_only_run = "finalizer-explorer-artifact-only"
    telemetry_run = "finalizer-explorer-telemetry"
    _cleanup_run_dir(artifact_only_run)
    _cleanup_run_dir(telemetry_run)
    try:
        artifact_only = AgentRunFinalizer().finalize(
            run_id=artifact_only_run,
            agent_type="exploratory",
            config={"url": "https://example.test", "time_limit_minutes": 1, "project_id": "default"},
            raw_model_output="",
            artifacts=[{"name": "live-step-001.png", "path": "/artifacts/run/live-step-001.png", "type": "image"}],
        )

        assert artifact_only.status == "completed_partial"
        assert artifact_only.result["total_flows_discovered"] == 0
        assert artifact_only.result["discovered_flow_summaries"] == []
        assert artifact_only.result["artifact_evidence"]["screenshot_count"] == 1

        with_telemetry = AgentRunFinalizer().finalize(
            run_id=telemetry_run,
            agent_type="exploratory",
            config={"url": "https://example.test", "time_limit_minutes": 1, "project_id": "default"},
            raw_model_output="",
            tool_calls=[
                {
                    "name": "mcp__playwright-test__browser_navigate",
                    "tool_use_id": "toolu_nav",
                    "input": {"url": "https://example.test"},
                    "success": True,
                },
                {
                    "name": "mcp__playwright-test__browser_click",
                    "tool_use_id": "toolu_click",
                    "input": {"element": "Pricing", "target": "Pricing"},
                    "success": True,
                },
            ],
            artifacts=[{"name": "live-step-001.png", "path": "/artifacts/run/live-step-001.png", "type": "image"}],
        )

        assert with_telemetry.status == "completed"
        assert with_telemetry.result["total_flows_discovered"] == 1
        assert with_telemetry.result["discovered_flow_summaries"]
        assert with_telemetry.result["diagnostics"]["browser_tool_calls"] == 2
    finally:
        _cleanup_run_dir(artifact_only_run)
        _cleanup_run_dir(telemetry_run)
