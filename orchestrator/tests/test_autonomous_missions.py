import json
import os
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-autonomous-tests")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

if "slowapi" not in sys.modules:
    slowapi_module = types.ModuleType("slowapi")
    slowapi_errors = types.ModuleType("slowapi.errors")
    slowapi_util = types.ModuleType("slowapi.util")

    class _Limiter:
        def __init__(self, *args, **kwargs):
            pass

        def limit(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    class _RateLimitExceeded(Exception):
        pass

    slowapi_module.Limiter = _Limiter
    slowapi_errors.RateLimitExceeded = _RateLimitExceeded
    slowapi_util.get_remote_address = lambda request: "test-client"
    sys.modules["slowapi"] = slowapi_module
    sys.modules["slowapi.errors"] = slowapi_errors
    sys.modules["slowapi.util"] = slowapi_util

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from orchestrator.api import autonomous as autonomous_api
from orchestrator.api.db import engine
from orchestrator.api.models_db import (
    ApplicationMap,
    AutonomousAgentEvent,
    AutonomousAgentWorkItem,
    AutonomousApproval,
    AutonomousFinding,
    AutonomousMission,
    AutonomousMissionRun,
    AutonomousTestProposal,
    BrowserPageState,
    CoverageGap,
    ExecutionSettings,
    ExplorationSession,
    Project,
    Requirement,
    RtmEntry,
    RtmSnapshot,
)
from orchestrator.services.autonomous_activities import (
    _agent_prompt_for_work_item,
    _allowed_tools_for_work_item,
    _assert_browser_lease_available,
    _auto_materialize_low_risk_proposals,
    _browser_context_handoff,
    _create_findings_from_completed_work_items,
    _create_proposals_for_approved_findings,
    _execute_agent_work_item_direct,
    _generate_pytest_content,
    _plan_whole_app_work_items,
    _prepare_child_browser_handoffs,
    _record_browser_observations_for_work_item,
    _row_has_required_evidence,
    _validate_child_browser_handoff_contract,
    _recover_stale_work_items,
    _validate_browser_handoff_mode,
    autonomous_health_diagnostics,
    backfill_autonomous_canonical_state,
    complete_mission_run,
    create_mission_run,
    execute_mission_iteration,
    fail_mission_run,
    load_mission_policy,
    monitor_autonomous_project,
)
from orchestrator.services.autonomous_events import create_autonomous_agent_event
from orchestrator.utils.agent_runner import AgentResult, ToolCall


def _ensure_tables() -> None:
    SQLModel.metadata.create_all(engine, checkfirst=True)
    import orchestrator.api.db as db_module

    db_module._run_migrations()


def _create_project_and_mission(session: Session, *, mission_type: str = "coverage") -> AutonomousMission:
    project = Project(id=f"autonomous-project-{uuid4().hex}", name=f"Autonomous Project {uuid4().hex}")
    mission = AutonomousMission(
        id=f"am-{uuid4().hex[:12]}",
        project_id=project.id,
        name="Coverage mission",
        mission_type=mission_type,
        status="paused",
        target_urls_json='["https://example.com"]',
        approval_policy="approval_required",
        autonomy_level="draft_validate",
        max_iterations=1,
        config_json='{"exploration_enabled": false}',
    )
    session.add(project)
    session.add(mission)
    session.commit()
    session.refresh(mission)
    return mission


def test_autonomous_work_item_prompt_includes_testdata_and_delegation_instructions():
    mission = AutonomousMission(
        id="am-testdata",
        project_id="project-1",
        name="Coverage mission",
        mission_type="coverage",
        status="running",
        target_urls_json='["https://example.com"]',
        config_json='{"runtime": "hermes", "test_data_refs": ["wetravel-auth.valid-user"]}',
    )
    item = AutonomousAgentWorkItem(
        id="work-1",
        mission_id=mission.id,
        role="explorer",
        objective="Explore login",
    )
    prompt = _agent_prompt_for_work_item(
        mission,
        item,
        {
            "prompt_markdown": (
                "## Available Project Test Data\n"
                "### wetravel-auth.valid-user\n"
                "- `testData.get('wetravel-auth.valid-user')` returns the resolved fixture data"
            ),
            "env_vars": {"TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME": "user@example.com"},
        },
    )

    assert "Available Project Test Data" in prompt
    assert "wetravel-auth.valid-user" in prompt
    assert "TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME" not in prompt
    assert "copy the relevant test-data ref names" in prompt
    assert "subagents do not automatically inherit" in prompt.lower()


def test_autonomous_browser_prompt_includes_handoff_and_validation_rules(tmp_path, monkeypatch):
    _ensure_tables()
    monkeypatch.setattr("orchestrator.services.autonomous_activities.RUNS_DIR", tmp_path)
    mission = AutonomousMission(
        id="am-browser-prompt",
        project_id="project-browser-prompt",
        name="Browser mission",
        mission_type="exploration",
        status="running",
        target_urls_json='["https://example.com"]',
        config_json='{"runtime": "hermes"}',
    )
    item = AutonomousAgentWorkItem(
        id="work-browser-prompt",
        mission_id=mission.id,
        project_id=mission.project_id,
        role="explorer",
        objective="Explore login",
    )
    run_dir = tmp_path / mission.id / item.id
    run_dir.mkdir(parents=True)
    handoff = _browser_context_handoff(
        mission=mission,
        item=item,
        run_dir=run_dir,
        runtime={"mcp_config_path": str(run_dir / ".mcp.json")},
        allowed_tools=["mcp__playwright__browser_navigate", "mcp__playwright__browser_snapshot"],
    )

    prompt = _agent_prompt_for_work_item(mission, item, {}, browser_handoff=handoff)

    assert "Current Browser Contract" in prompt
    assert "Required First Browser Action" in prompt
    assert "Call browser_navigate to https://example.com" in prompt
    assert "After navigation, dialog handling" in prompt
    assert "Parallel browser subagents must use isolated mode" in prompt


def test_child_browser_handoff_gets_isolated_mcp_config(tmp_path, monkeypatch):
    _ensure_tables()
    monkeypatch.setattr("orchestrator.services.autonomous_activities.RUNS_DIR", tmp_path)
    mission = AutonomousMission(
        id="am-child-browser",
        project_id="project-child-browser",
        name="Child browser mission",
        mission_type="exploration",
        status="running",
        target_urls_json='["https://example.com"]',
        config_json='{"runtime": "hermes", "hermes_max_concurrent_children": 1}',
    )
    item = AutonomousAgentWorkItem(
        id="work-child-browser",
        mission_id=mission.id,
        project_id=mission.project_id,
        role="explorer",
        objective="Explore checkout",
    )

    handoffs = _prepare_child_browser_handoffs(
        mission=mission,
        item=item,
        allowed_tools=["mcp__playwright__browser_navigate"],
        parent_auth_session_id=None,
        parent_auth_session_name=None,
        max_children=1,
    )

    assert len(handoffs) == 1
    handoff = handoffs[0]
    assert handoff["handoff_mode"] == "isolated"
    assert handoff["strict_mcp_config"] is True
    assert handoff["storage_state_attached"] is False
    assert "/children/child-1/" in handoff["mcp_config_path"]
    mcp_config = json.loads(Path(handoff["mcp_config_path"]).read_text())
    args = mcp_config["mcpServers"]["playwright"]["args"]
    assert "--isolated" in args
    assert "--storage-state" not in args
    assert "mcp__playwright__browser_navigate" in handoff["allowed_tools"]
    assert handoff["required_first_browser_action"].startswith("Call browser_navigate")


def test_parallel_browser_work_items_cannot_share_non_isolated_lease():
    _ensure_tables()
    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="exploration")
        running = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            role="explorer",
            objective="Explore live browser",
            status="running",
        )
        running.progress = {
            "browser_context_handoff": {
                "browser_lease": {
                    "mode": "sequential_handoff",
                    "lease_until": (datetime.utcnow() + timedelta(minutes=5)).isoformat(),
                }
            }
        }
        session.add(running)
        session.commit()

        with pytest.raises(RuntimeError, match="Browser lease conflict"):
            _assert_browser_lease_available(
                session,
                mission_id=mission.id,
                requested_owner_id="other-work-item",
                mode="sequential_handoff",
            )


def test_sequential_browser_handoff_requires_recent_snapshot():
    stale_item = AutonomousAgentWorkItem(
        id="work-stale-snapshot",
        mission_id="mission-stale-snapshot",
        role="explorer",
        objective="Use existing page",
    )

    with pytest.raises(RuntimeError, match="recent browser_snapshot"):
        _validate_browser_handoff_mode(stale_item, mode="sequential_handoff")

    stale_item.progress = {
        "browser_context_handoff": {
            "browser_lease": {"last_snapshot_at": (datetime.utcnow() - timedelta(minutes=10)).isoformat()}
        }
    }
    with pytest.raises(RuntimeError, match="within the last 5 minutes"):
        _validate_browser_handoff_mode(stale_item, mode="sequential_handoff")

    stale_item.progress = {
        "browser_context_handoff": {"browser_lease": {"last_snapshot_at": datetime.utcnow().isoformat()}}
    }
    _validate_browser_handoff_mode(stale_item, mode="sequential_handoff")


def test_child_browser_contract_requires_isolated_mcp_and_evidence_tools(tmp_path):
    mcp_config = tmp_path / ".mcp.json"
    mcp_config.write_text(json.dumps({"mcpServers": {"playwright": {"command": "node"}}}))
    contract = {
        "handoff_mode": "isolated",
        "mcp_config_path": str(mcp_config),
        "allowed_tools": ["mcp__playwright__browser_navigate", "mcp__playwright__browser_snapshot"],
        "required_first_browser_action": "Call browser_navigate, then call browser_snapshot before interaction.",
    }

    _validate_child_browser_handoff_contract(contract)

    contract["allowed_tools"] = ["mcp__playwright__browser_navigate"]
    with pytest.raises(RuntimeError, match="browser_snapshot"):
        _validate_child_browser_handoff_contract(contract)


def test_autonomous_evidence_gate_quarantines_low_evidence_rows(monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_REQUIRE_EVIDENCE", "1")

    assert not _row_has_required_evidence(
        "requirement",
        {
            "title": "Users can export data",
            "acceptance_criteria": ["Export is available"],
            "confidence": 0.5,
        },
    )
    assert _row_has_required_evidence(
        "requirement",
        {
            "title": "Users can save trips",
            "evidence": {"url": "https://example.test/trips", "selector": "button Save"},
            "confidence": 0.6,
        },
    )
    assert not _row_has_required_evidence("bug", {"title": "Broken", "description": "It broke"})


def test_autonomous_browser_observations_write_owner_metadata(monkeypatch):
    _ensure_tables()
    from orchestrator.memory import browser_memory as browser_memory_module
    from orchestrator.memory.browser_memory import ExplorationMemoryService

    monkeypatch.setattr(ExplorationMemoryService, "_index_page_state", lambda self, state, document: None)
    monkeypatch.setattr(ExplorationMemoryService, "_index_element", lambda self, element, state: None)
    monkeypatch.setattr(ExplorationMemoryService, "_project_state_to_graph", lambda self, state, elements: None)
    monkeypatch.setattr(
        ExplorationMemoryService,
        "_project_transition_to_graph",
        lambda self, transition, from_state, to_state: None,
    )

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="exploration")
        item = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=f"amrun-{uuid4().hex[:12]}",
            project_id=mission.project_id,
            role="explorer",
            objective="Explore dashboard",
        )
        session.add(item)
        session.commit()
        project_id = mission.project_id
        mission_id = mission.id
        item_id = item.id

    result = AgentResult(
        success=True,
        output='{"app_map_updates":[{"url":"https://example.com/dashboard","page_title":"Dashboard","elements":{"button":["Save"]}}]}',
        tool_calls=[
            ToolCall(
                name="mcp__playwright__browser_navigate",
                timestamp=datetime.utcnow(),
                success=True,
                input={"url": "https://example.com/dashboard"},
            ),
            ToolCall(
                name="mcp__playwright__browser_snapshot",
                timestamp=datetime.utcnow(),
                success=True,
            ),
        ],
    )

    summary = _record_browser_observations_for_work_item(
        mission=mission,
        item=item,
        result=result,
        browser_handoff={"start_url": "https://example.com", "mcp_config_path": "handoff-1"},
    )

    assert summary["states"] >= 1
    assert summary["app_map_states"] == 1
    with Session(browser_memory_module.engine) as session:
        states = session.exec(select(BrowserPageState).where(BrowserPageState.project_id == project_id)).all()

    assert states
    owner_metadata = [state.canonical_json.get("owner_metadata") for state in states if state.canonical_json]
    assert any(metadata and metadata["mission_id"] == mission_id for metadata in owner_metadata)
    assert any(metadata and metadata["work_item_id"] == item_id for metadata in owner_metadata)


def test_load_mission_policy_returns_durable_controls():
    _ensure_tables()
    with Session(engine) as session:
        mission = _create_project_and_mission(session)

    policy = load_mission_policy(mission.id)

    assert policy["id"] == mission.id
    assert policy["project_id"] == mission.project_id
    assert policy["target_urls"] == ["https://example.com"]
    assert policy["approval_policy"] == "approval_required"


def test_execute_mission_iteration_creates_deduped_approval_gated_coverage_finding():
    _ensure_tables()
    with Session(engine) as session:
        for stale_gap in session.exec(select(CoverageGap)).all():
            session.delete(stale_gap)
        session.commit()
        mission = _create_project_and_mission(session)
        mission_id = mission.id
        gap = CoverageGap(
            gap_type="missing_edge_case",
            severity="high",
            description="Checkout error states are not covered",
            suggested_test="Create a test for declined-card checkout behavior.",
            url="https://example.com/checkout",
        )
        session.add(gap)
        session.commit()

    run_id = create_mission_run({"mission_id": mission_id, "workflow_id": "wf-test"})
    summary = execute_mission_iteration({"mission_id": mission_id, "run_id": run_id, "workflow_id": "wf-test"})

    assert summary["findings_created"] == 1
    assert summary["approvals_created"] == 1

    duplicate_summary = execute_mission_iteration(
        {"mission_id": mission_id, "run_id": run_id, "workflow_id": "wf-test"}
    )
    assert duplicate_summary["findings_created"] == 0

    with Session(engine) as session:
        findings = session.exec(select(AutonomousFinding).where(AutonomousFinding.mission_id == mission_id)).all()
        approvals = session.exec(select(AutonomousApproval).where(AutonomousApproval.mission_id == mission_id)).all()
        mission_db = session.get(AutonomousMission, mission_id)

    assert len(findings) == 1
    assert findings[0].status == "awaiting_approval"
    assert findings[0].approval_required is True
    assert findings[0].finding_type == "coverage_gap"
    assert len(approvals) == 1
    assert approvals[0].action_type == "persist_test"
    assert approvals[0].status == "pending"
    assert mission_db.total_findings == 1

    with Session(engine) as session:
        proposals = session.exec(
            select(AutonomousTestProposal).where(AutonomousTestProposal.mission_id == mission_id)
        ).all()

    assert len(proposals) == 1
    assert proposals[0].approval_status == "pending"
    assert proposals[0].test_type in {"e2e", "api", "regression", "security", "accessibility", "unit"}
    assert proposals[0].suggested_file_path.startswith(("tests/generated/", "orchestrator/tests/generated/"))
    assert (
        "coverage" in proposals[0].generated_spec_content.lower()
        or "rationale" in proposals[0].generated_spec_content.lower()
    )


def test_complete_mission_run_persists_summary():
    _ensure_tables()
    with Session(engine) as session:
        mission = _create_project_and_mission(session)

    run_id = create_mission_run({"mission_id": mission.id, "workflow_id": "wf-complete"})
    complete_mission_run({"run_id": run_id, "summary": {"findings_created": 0}})

    with Session(engine) as session:
        run = session.get(AutonomousMissionRun, run_id)

    assert run.status == "completed"
    assert run.current_stage == "completed"
    assert run.summary["findings_created"] == 0
    assert run.completed_at is not None


def test_create_mission_run_is_idempotent_for_workflow_iteration():
    _ensure_tables()
    with Session(engine) as session:
        mission = _create_project_and_mission(session)
        mission_id = mission.id

    payload = {"mission_id": mission_id, "workflow_id": "wf-idempotent", "iteration_index": 1}
    first_run_id = create_mission_run(payload)
    second_run_id = create_mission_run(payload)

    with Session(engine) as session:
        mission_db = session.get(AutonomousMission, mission_id)
        runs = session.exec(select(AutonomousMissionRun).where(AutonomousMissionRun.mission_id == mission_id)).all()

    assert first_run_id == second_run_id
    assert len(runs) == 1
    assert mission_db.total_runs == 1


def test_fail_mission_run_pauses_after_consecutive_failures():
    _ensure_tables()
    with Session(engine) as session:
        mission = _create_project_and_mission(session)
        mission.config = {"max_consecutive_failures": 2}
        session.add(mission)
        session.commit()
        mission_id = mission.id

    first_run_id = create_mission_run({"mission_id": mission_id, "workflow_id": "wf-fail-1"})
    fail_mission_run({"mission_id": mission_id, "run_id": first_run_id, "error": "Transient browser crash"})
    second_run_id = create_mission_run({"mission_id": mission_id, "workflow_id": "wf-fail-2"})
    fail_mission_run({"mission_id": mission_id, "run_id": second_run_id, "error": "Repeated browser crash"})

    with Session(engine) as session:
        mission_db = session.get(AutonomousMission, mission_id)

    assert mission_db.status == "paused"
    assert mission_db.health_status == "blocked"
    assert mission_db.paused_reason == "consecutive_failures"
    assert mission_db.consecutive_failures == 2


def test_execute_mission_iteration_creates_proposal_for_approved_finding():
    _ensure_tables()
    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="regression")
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="running",
        )
        finding = AutonomousFinding(
            id=f"amfind-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            finding_type="bug",
            severity="medium",
            title="Profile page regression needs coverage",
            description="Create a regression test for the profile page.",
            status="approved",
            dedupe_key=f"approved-{uuid4().hex}",
            evidence_json='{"url": "https://example.com/profile"}',
            source_type="manual",
            source_id="finding-source",
        )
        session.add(run)
        session.add(finding)
        session.commit()
        mission_id = mission.id
        run_id = run.id
        finding_id = finding.id

    summary = execute_mission_iteration({"mission_id": mission_id, "run_id": run_id, "workflow_id": "wf-approved"})
    duplicate = execute_mission_iteration({"mission_id": mission_id, "run_id": run_id, "workflow_id": "wf-approved"})

    assert summary["test_proposals_created"] == 1
    assert duplicate["test_proposals_created"] == 0

    with Session(engine) as session:
        proposals = session.exec(
            select(AutonomousTestProposal).where(AutonomousTestProposal.mission_id == mission_id)
        ).all()

    assert len(proposals) == 1
    assert proposals[0].finding_id == finding_id
    assert proposals[0].target_url == "https://example.com/profile"
    assert proposals[0].approval_status == "pending"


def test_execute_mission_iteration_creates_memory_delta_finding(monkeypatch):
    _ensure_tables()
    from orchestrator.memory import browser_memory as browser_memory_module
    from orchestrator.memory.browser_memory import ExplorationMemoryService

    monkeypatch.setattr(ExplorationMemoryService, "_index_page_state", lambda self, state, document: None)
    monkeypatch.setattr(ExplorationMemoryService, "_index_element", lambda self, element, state: None)
    monkeypatch.setattr(ExplorationMemoryService, "_project_state_to_graph", lambda self, state, elements: None)
    monkeypatch.setattr(
        ExplorationMemoryService,
        "_project_transition_to_graph",
        lambda self, transition, from_state, to_state: None,
    )

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="exploration")
        mission.config = {"exploration_enabled": False}
        session.add(mission)
        session.commit()
        mission_id = mission.id
        project_id = mission.project_id

    memory = browser_memory_module.get_exploration_memory_service(project_id=project_id)
    memory.upsert_page_state(
        session_id="memory-run-1",
        url="https://example.com/login",
        title="Login",
        snapshot_text='- button "Sign in" [ref=e1]',
    )

    first_run_id = create_mission_run({"mission_id": mission_id, "workflow_id": "wf-memory-1", "iteration_index": 1})
    first_summary = execute_mission_iteration(
        {"mission_id": mission_id, "run_id": first_run_id, "workflow_id": "wf-memory-1"}
    )
    assert first_summary["memory_delta"]["has_previous_baseline"] is False

    memory.upsert_page_state(
        session_id="memory-run-2",
        url="https://example.com/login",
        title="Login",
        snapshot_text='- textbox "Email" [ref=e1]\n- button "Continue" [ref=e2]',
    )

    second_run_id = create_mission_run({"mission_id": mission_id, "workflow_id": "wf-memory-2", "iteration_index": 2})
    second_summary = execute_mission_iteration(
        {"mission_id": mission_id, "run_id": second_run_id, "workflow_id": "wf-memory-2"}
    )

    assert second_summary["memory_delta"]["has_previous_baseline"] is True
    assert second_summary["memory_delta"]["change_count"] >= 1
    assert second_summary["memory_delta"]["findings_created"] >= 1

    with Session(engine) as session:
        findings = session.exec(
            select(AutonomousFinding).where(
                AutonomousFinding.mission_id == mission_id,
                AutonomousFinding.finding_type == "memory_delta",
            )
        ).all()
        run = session.get(AutonomousMissionRun, second_run_id)

    assert findings
    assert run.checkpoint["memory_delta"]["summary"]["changed_page_states"] >= 1
    assert findings[0].evidence["change_type"] == "changed_page"
    assert findings[0].evidence["test_value"] == "regression_candidate"
    assert findings[0].evidence["risk_level"] == "high"


def test_execute_mission_iteration_queues_background_exploration(monkeypatch):
    _ensure_tables()
    launched: dict[str, object] = {}

    monkeypatch.setattr(
        "orchestrator.services.autonomous_activities._create_memory_delta_artifacts",
        lambda session, mission, run: {
            "change_count": 0,
            "findings_created": 0,
            "test_proposals_created": 0,
            "delta_summary": {},
            "has_previous_baseline": False,
        },
    )
    monkeypatch.setattr(
        "orchestrator.services.autonomous_activities._create_coverage_gap_artifacts",
        lambda session, mission, run: {"findings_created": 0, "approvals_created": 0, "test_proposals_created": 0},
    )

    def fake_launch(session_id, request_body, *, user_key="system", track=False):
        launched["session_id"] = session_id
        launched["request"] = request_body
        launched["user_key"] = user_key
        launched["track"] = track
        return None

    monkeypatch.setattr("orchestrator.api.exploration.launch_exploration_background", fake_launch)

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="exploration")
        mission.config = {
            "exploration_enabled": True,
            "allowed_domains": ["example.com"],
            "allowed_routes": ["/"],
            "read_only": True,
            "max_interactions": 7,
            "max_depth": 3,
        }
        session.add(mission)
        session.commit()
        mission_id = mission.id

    run_id = create_mission_run({"mission_id": mission_id, "workflow_id": "wf-explore-queue"})
    summary = execute_mission_iteration({"mission_id": mission_id, "run_id": run_id, "workflow_id": "wf-explore-queue"})

    assert summary["exploration"]["queued"] is True
    assert launched["session_id"] == summary["exploration"]["session_id"]
    assert launched["user_key"] == f"autonomous:{mission_id}"
    assert launched["request"].max_interactions == 7

    with Session(engine) as session:
        run = session.get(AutonomousMissionRun, run_id)
        exploration = session.get(ExplorationSession, summary["exploration"]["session_id"])

    assert exploration is not None
    assert exploration.status == "queued"
    assert exploration.config["autonomous_mission_id"] == mission_id
    assert exploration.config["autonomous_run_id"] == run_id
    assert run.checkpoint["exploration_session_id"] == exploration.id
    assert run.current_stage == "exploration_queued"


def test_execute_mission_iteration_waits_for_prior_running_exploration(monkeypatch):
    _ensure_tables()
    monkeypatch.setattr(
        "orchestrator.services.autonomous_activities._create_memory_delta_artifacts",
        lambda session, mission, run: (_ for _ in ()).throw(AssertionError("memory delta should wait for exploration")),
    )

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="exploration")
        mission.config = {"exploration_enabled": True}
        session.add(mission)
        session.commit()
        exploration_session_id = f"explore-wait-{uuid4().hex[:8]}"
        previous_run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="completed",
            checkpoint_json=f'{{"exploration_session_id": "{exploration_session_id}"}}',
            created_at=datetime.utcnow() - timedelta(minutes=5),
        )
        exploration = ExplorationSession(
            id=exploration_session_id,
            project_id=mission.project_id,
            entry_url="https://example.com",
            status="running",
            pages_discovered=2,
        )
        session.add(previous_run)
        session.add(exploration)
        session.commit()
        mission_id = mission.id

    run_id = create_mission_run({"mission_id": mission_id, "workflow_id": "wf-explore-wait"})
    summary = execute_mission_iteration({"mission_id": mission_id, "run_id": run_id, "workflow_id": "wf-explore-wait"})

    assert summary["exploration"]["waiting"] is True
    assert summary["exploration"]["session_id"] == exploration_session_id
    with Session(engine) as session:
        run = session.get(AutonomousMissionRun, run_id)
        mission = session.get(AutonomousMission, mission_id)

    assert run.current_stage == "waiting_for_exploration"
    assert run.checkpoint["waiting_on_exploration_session_id"] == exploration_session_id
    assert mission.current_stage == "waiting_for_exploration"


def test_app_changes_endpoint_groups_memory_delta_findings():
    _ensure_tables()
    app = FastAPI()
    app.include_router(autonomous_api.router)

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="exploration")
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="completed",
        )
        finding = AutonomousFinding(
            id=f"amfind-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            finding_type="memory_delta",
            severity="medium",
            title="Login page changed",
            description="The remembered login page now exposes a continue button.",
            status="awaiting_approval",
            confidence=0.86,
            dedupe_key=f"memory-delta-{uuid4().hex}",
            source_type="browser_memory",
            source_id="login",
        )
        finding.evidence = {
            "kind": "changed_page_state",
            "url": "https://example.com/login",
            "page_key": "login",
            "changed_fields": {"snapshot_text": {"before": "Sign in", "after": "Continue"}},
        }
        proposal = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            finding_id=finding.id,
            title="Login continue regression",
            target_url="https://example.com/login",
            route="/login",
            test_type="e2e",
            rationale="Cover the changed login flow.",
            generated_spec_content="import { test } from '@playwright/test';\n",
            suggested_file_path="tests/generated/login-continue.spec.ts",
            risk_level="medium",
            approval_status="pending",
            dedupe_key=f"proposal-{uuid4().hex}",
            source_type="memory_delta",
            source_id=finding.id,
        )
        session.add(run)
        session.add(finding)
        session.add(proposal)
        session.commit()
        project_id = mission.project_id
        mission_id = mission.id

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/autonomous/{project_id}/missions/{mission_id}/app-changes")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["change_type"] == "changed_page_state"
    assert payload["items"][0]["proposal"]["approval_status"] == "pending"
    assert payload["items"][0]["test_value"] == "informational"
    assert payload["grouped"]["changed_page_state"][0]["url"] == "https://example.com/login"


def test_app_changes_endpoint_returns_classification_fields():
    _ensure_tables()
    app = FastAPI()
    app.include_router(autonomous_api.router)

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="exploration")
        finding = AutonomousFinding(
            id=f"amfind-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            finding_type="memory_delta",
            severity="high",
            title="Checkout changed",
            description="Checkout page changed and should be reviewed.",
            status="awaiting_approval",
            confidence=0.84,
            dedupe_key=f"memory-delta-{uuid4().hex}",
            source_type="browser_memory_delta",
            source_id="checkout",
        )
        finding.evidence = {
            "kind": "changed_page_state",
            "change_type": "changed_page",
            "risk_level": "high",
            "test_value": "regression_candidate",
            "uncertainty_reason": "Review expected checkout behavior.",
            "url": "https://example.com/checkout",
        }
        session.add(finding)
        session.commit()
        project_id = mission.project_id
        mission_id = mission.id

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/autonomous/{project_id}/missions/{mission_id}/app-changes")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["change_type"] == "changed_page"
    assert item["risk_level"] == "high"
    assert item["test_value"] == "regression_candidate"
    assert item["uncertainty_reason"] == "Review expected checkout behavior."


def test_finding_decision_endpoints_store_review_and_sync_pending_proposal():
    _ensure_tables()
    app = FastAPI()
    app.include_router(autonomous_api.router)

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="exploration")
        finding = AutonomousFinding(
            id=f"amfind-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            finding_type="memory_delta",
            severity="medium",
            title="Settings changed",
            description="Settings page changed.",
            status="awaiting_approval",
            confidence=0.8,
            dedupe_key=f"finding-decision-{uuid4().hex}",
            source_type="browser_memory_delta",
            source_id="settings",
        )
        proposal = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            finding_id=finding.id,
            title="Settings change coverage",
            test_type="e2e",
            rationale="Cover settings change.",
            generated_spec_content="import { test } from '@playwright/test';\n",
            suggested_file_path="tests/generated/settings-change.spec.ts",
            risk_level="medium",
            approval_status="pending",
            dedupe_key=f"proposal-{uuid4().hex}",
            source_type="memory_delta",
            source_id=finding.id,
        )
        session.add(finding)
        session.add(proposal)
        session.commit()
        project_id = mission.project_id
        finding_id = finding.id
        proposal_id = proposal.id

    with TestClient(app, raise_server_exceptions=False) as client:
        missing_comment = client.post(f"/autonomous/{project_id}/findings/{finding_id}/reject", json={})
        assert missing_comment.status_code == 400

        rejected = client.post(
            f"/autonomous/{project_id}/findings/{finding_id}/reject",
            json={"comment": "Current behavior is expected and already covered.", "reviewer": "qa-lead"},
        )

    assert rejected.status_code == 200
    payload = rejected.json()
    assert payload["status"] == "rejected"
    assert payload["evidence"]["review"]["decision"] == "rejected"
    assert payload["evidence"]["review"]["comment"] == "Current behavior is expected and already covered."
    assert payload["evidence"]["review"]["reviewer"] == "qa-lead"

    with Session(engine) as session:
        stored_proposal = session.get(AutonomousTestProposal, proposal_id)

    assert stored_proposal.approval_status == "rejected"


def test_approved_memory_delta_finding_generates_proposal_with_requirement_truth_warning():
    _ensure_tables()
    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="regression")
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="running",
        )
        requirement = Requirement(
            project_id=mission.project_id,
            req_code=f"REQ-WARN-{uuid4().hex[:8]}",
            title="Checkout should show confirmation",
            category="checkout",
            priority="high",
            status="draft",
            truth_state="candidate_requirement",
            source_type="app_observation",
            confidence=0.68,
        )
        session.add(requirement)
        session.commit()
        session.refresh(requirement)
        finding = AutonomousFinding(
            id=f"amfind-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            finding_type="memory_delta",
            severity="high",
            title="Checkout confirmation changed",
            description="Create regression coverage for checkout confirmation.",
            status="approved",
            dedupe_key=f"approved-memory-{uuid4().hex}",
            source_type="browser_memory_delta",
            source_id="checkout",
        )
        finding.evidence = {"url": "https://example.com/checkout", "requirement_id": requirement.id}
        session.add(run)
        session.add(finding)
        session.commit()
        mission_id = mission.id
        run_id = run.id
        finding_id = finding.id

    summary = execute_mission_iteration(
        {"mission_id": mission_id, "run_id": run_id, "workflow_id": "wf-approved-memory"}
    )

    assert summary["test_proposals_created"] == 1
    with Session(engine) as session:
        proposal = session.exec(
            select(AutonomousTestProposal).where(AutonomousTestProposal.finding_id == finding_id)
        ).first()

    assert proposal is not None
    assert proposal.source_metadata["requirement_truth_state"] == "candidate_requirement"
    assert proposal.source_metadata["generation_allowed"] is True
    assert "not been confirmed" in proposal.source_metadata["generation_warning"]


def test_team_timeline_endpoint_returns_role_status_events_and_output():
    _ensure_tables()
    app = FastAPI()
    app.include_router(autonomous_api.router)

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="mixed")
        item = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            role="validator",
            objective="Validate generated checkout proposal.",
            status="completed",
            priority=10,
            result_json='{"output": "Validator accepted the checkout proposal."}',
            artifacts_json='[{"label": "Validator report", "content": "Detailed validation notes"}]',
        )
        session.add(item)
        session.commit()
        create_autonomous_agent_event(
            mission_id=mission.id,
            project_id=mission.project_id,
            work_item_id=item.id,
            event_type="assistant_output",
            message="Validator accepted the checkout proposal.",
            session=session,
        )
        project_id = mission.project_id
        mission_id = mission.id

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/autonomous/{project_id}/missions/{mission_id}/team-timeline")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["status_counts"]["completed"] == 1
    assert payload["items"][0]["role"] == "validator"
    assert payload["items"][0]["latest_event"]["event_type"] == "assistant_output"
    assert "accepted" in payload["items"][0]["latest_output"]
    assert payload["items"][0]["artifacts_count"] == 1


def test_work_item_review_endpoints_store_gate_metadata_and_target_decision():
    _ensure_tables()
    app = FastAPI()
    app.include_router(autonomous_api.router)

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="mixed")
        reviewer = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            role="validator",
            objective="Review the spec writer output.",
            status="completed",
            result_json='{"output": "Needs stronger assertions."}',
        )
        target = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            role="spec_writer",
            objective="Draft Playwright coverage.",
            status="completed",
            result_json='{"output": "Drafted a smoke test."}',
        )
        session.add(reviewer)
        session.add(target)
        session.commit()
        project_id = mission.project_id
        reviewer_id = reviewer.id
        target_id = target.id

    with TestClient(app, raise_server_exceptions=False) as client:
        missing_reason = client.post(f"/autonomous/{project_id}/work-items/{reviewer_id}/needs-revision", json={})
        assert missing_reason.status_code == 400

        reviewed = client.post(
            f"/autonomous/{project_id}/work-items/{reviewer_id}/needs-revision",
            json={
                "comment": "Assertions are too weak.",
                "reviewer": "qa-reviewer",
                "target_work_item_id": target_id,
            },
        )
        timeline = client.get(f"/autonomous/{project_id}/missions/{reviewed.json()['mission_id']}/team-timeline")
        mission_status = client.get(f"/autonomous/{project_id}/missions/{reviewed.json()['mission_id']}/status")

    assert reviewed.status_code == 200
    assert reviewed.json()["review_decision"] == "needs_revision"
    assert reviewed.json()["reviewed_work_item_id"] == target_id
    assert reviewed.json()["revision_work_item"]["status"] == "queued"
    assert reviewed.json()["revision_work_item"]["role"] == "spec_writer"
    revision_id = reviewed.json()["revision_work_item"]["id"]

    with Session(engine) as session:
        target_db = session.get(AutonomousAgentWorkItem, target_id)
        revision_db = session.get(AutonomousAgentWorkItem, revision_id)

    assert target_db.result["review_decision"] == "needs_revision"
    assert target_db.result["review_reason"] == "Assertions are too weak."
    assert target_db.result["reviewed_role"] == "validator"
    assert target_db.result["revision_work_item_id"] == revision_id
    assert revision_db.status == "queued"
    assert revision_db.priority == max(0, target_db.priority - autonomous_api.REVISION_PRIORITY_BOOST)
    assert revision_db.progress["original_priority"] == target_db.priority
    assert revision_db.progress["revision_priority_boost"] == autonomous_api.REVISION_PRIORITY_BOOST
    assert revision_db.progress["revision_of_work_item_id"] == target_id
    assert revision_db.progress["reviewer_work_item_id"] == reviewer_id
    assert revision_db.progress["review_reason"] == "Assertions are too weak."
    assert timeline.status_code == 200
    by_id = {item["id"]: item for item in timeline.json()["items"]}
    assert by_id[target_id]["review_decision"] == "needs_revision"
    assert by_id[target_id]["review_reason"] == "Assertions are too weak."
    assert by_id[revision_id]["status"] == "queued"
    assert by_id[revision_id]["is_revision"] is True
    assert by_id[revision_id]["revision_of_work_item_id"] == target_id
    assert mission_status.status_code == 200
    team_summary = mission_status.json()["mission"]["team_summary"]
    assert team_summary["revision_count"] == 1
    assert team_summary["pending_revision_count"] == 1
    assert team_summary["accepted_revision_count"] == 0
    assert team_summary["needs_revision_count"] == 1
    assert team_summary["revision_attention"] is True
    assert "revision follow-up" in mission_status.json()["next_action"]


def test_rejected_work_item_result_does_not_create_finding():
    _ensure_tables()
    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="mixed")
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="running",
        )
        accepted = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            role="explorer",
            objective="Explore checkout.",
            status="completed",
            result_json='{"output": "Checkout has a saved-card path.", "review_decision": "accepted"}',
        )
        rejected = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            role="requirements_analyst",
            objective="Infer requirements.",
            status="completed",
            result_json='{"output": "Speculative requirement.", "review_decision": "rejected"}',
        )
        session.add(run)
        session.add(accepted)
        session.add(rejected)
        session.commit()
        accepted_id = accepted.id

        created = _create_findings_from_completed_work_items(session, mission, run)
        findings = session.exec(select(AutonomousFinding).where(AutonomousFinding.mission_id == mission.id)).all()

    assert created == 1
    assert len(findings) == 1
    assert findings[0].source_id == accepted_id


def test_accepted_revision_work_item_creates_proposal_with_full_lineage():
    _ensure_tables()
    app = FastAPI()
    app.include_router(autonomous_api.router)

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="mixed")
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="running",
        )
        reviewer = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            role="validator",
            objective="Review generated checkout coverage.",
            status="completed",
            result_json='{"output": "Needs stronger assertions."}',
        )
        original = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            role="spec_writer",
            objective="Draft checkout regression coverage.",
            status="completed",
            result_json='{"output": "Drafted weak checkout coverage."}',
        )
        session.add(run)
        session.add(reviewer)
        session.add(original)
        session.commit()
        project_id = mission.project_id
        mission_id = mission.id
        run_id = run.id
        reviewer_id = reviewer.id
        original_id = original.id

    with TestClient(app, raise_server_exceptions=False) as client:
        revision_response = client.post(
            f"/autonomous/{project_id}/work-items/{reviewer_id}/needs-revision",
            json={
                "comment": "Assertions are too weak.",
                "reviewer": "qa-reviewer",
                "target_work_item_id": original_id,
            },
        )

    assert revision_response.status_code == 200
    revision_id = revision_response.json()["revision_work_item"]["id"]

    with Session(engine) as session:
        revision = session.get(AutonomousAgentWorkItem, revision_id)
        revision.status = "completed"
        revision.completed_at = datetime.utcnow()
        revision.result = {
            **revision.result,
            "output": "Improved checkout regression coverage with failure assertions.",
        }
        revision.artifacts = [
            {
                "type": "agent_report",
                "label": "Revision report",
                "content": "Improved checkout regression coverage with failure assertions.",
            }
        ]
        session.add(revision)
        session.commit()

    with TestClient(app, raise_server_exceptions=False) as client:
        accepted = client.post(
            f"/autonomous/{project_id}/work-items/{revision_id}/accept",
            json={"comment": "Revision now covers the failure mode.", "reviewer": "qa-reviewer"},
        )
        mission_status = client.get(f"/autonomous/{project_id}/missions/{mission_id}/status")

    assert accepted.status_code == 200
    assert mission_status.status_code == 200
    accepted_summary = mission_status.json()["mission"]["team_summary"]
    assert accepted_summary["revision_count"] == 1
    assert accepted_summary["pending_revision_count"] == 0
    assert accepted_summary["accepted_revision_count"] == 1

    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        run = session.get(AutonomousMissionRun, run_id)
        created = _create_findings_from_completed_work_items(session, mission, run)
        finding = session.exec(
            select(AutonomousFinding).where(
                AutonomousFinding.mission_id == mission_id,
                AutonomousFinding.source_id == revision_id,
            )
        ).first()
        finding.status = "approved"
        session.add(finding)
        session.commit()
        proposals_created = _create_proposals_for_approved_findings(session, mission, run)
        proposal = session.exec(
            select(AutonomousTestProposal).where(AutonomousTestProposal.finding_id == finding.id)
        ).first()
        proposal_id = proposal.id
        finding_id = finding.id
        finding_evidence = finding.evidence
        proposal_metadata = proposal.source_metadata

    assert created == 1
    assert proposals_created == 1
    assert finding_evidence["work_item_id"] == revision_id
    assert finding_evidence["revision_of_work_item_id"] == original_id
    assert finding_evidence["reviewer_work_item_id"] == reviewer_id
    assert finding_evidence["review_reason"] == "Assertions are too weak."
    assert proposal_metadata["work_item_id"] == revision_id
    assert proposal_metadata["revision_of_work_item_id"] == original_id
    assert proposal_metadata["reviewer_work_item_id"] == reviewer_id
    assert proposal_metadata["review_reason"] == "Assertions are too weak."
    assert proposal_metadata["revision_attempt"] == 1

    with TestClient(app, raise_server_exceptions=False) as client:
        audit = client.get(f"/autonomous/{project_id}/proposals/{proposal_id}/audit")

    assert audit.status_code == 200
    audit_payload = audit.json()
    assert [item["id"] for item in audit_payload["revision_chain"]] == [original_id, revision_id]
    assert audit_payload["source_work_item"]["id"] == revision_id
    assert audit_payload["finding"]["id"] == finding_id


def test_execute_mission_iteration_creates_parallel_team_work_items(monkeypatch):
    _ensure_tables()
    with Session(engine) as session:
        settings = session.get(ExecutionSettings, 1) or ExecutionSettings(id=1)
        settings.parallelism = 2
        session.add(settings)
        session.commit()

    def fake_enqueue(session, mission, item):
        item.agent_task_id = f"agent-task-{item.role}"
        item.status = "running"
        item.attempt_count += 1
        item.progress = {"phase": "queued", "message": "fake queued"}
        session.add(item)
        session.commit()
        return True

    monkeypatch.setattr("orchestrator.services.autonomous_activities._enqueue_agent_work_item", fake_enqueue)

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="mixed")
        mission.config = {
            "whole_app_team": True,
            "max_parallel_agents": 2,
            "roles": ["surface_mapper", "requirements_analyst", "rtm_mapper"],
        }
        session.add(mission)
        session.commit()
        mission_id = mission.id

    run_id = create_mission_run({"mission_id": mission_id, "workflow_id": "wf-team"})
    summary = execute_mission_iteration({"mission_id": mission_id, "run_id": run_id, "workflow_id": "wf-team"})

    assert summary["work_items_created"] == 3
    assert summary["work_items_enqueued"] == 2
    assert summary["team"]["running_count"] == 2

    with Session(engine) as session:
        items = session.exec(
            select(AutonomousAgentWorkItem).where(AutonomousAgentWorkItem.mission_id == mission_id)
        ).all()

    assert {item.role for item in items} == {"surface_mapper", "requirements_analyst", "rtm_mapper"}
    assert len([item for item in items if item.status == "running"]) == 2


def test_execute_mission_iteration_clamps_team_parallelism_to_execution_settings(monkeypatch):
    _ensure_tables()

    def fake_enqueue(session, mission, item):
        item.agent_task_id = f"agent-task-{item.role}"
        item.status = "running"
        item.attempt_count += 1
        session.add(item)
        session.commit()
        return True

    monkeypatch.setattr("orchestrator.services.autonomous_activities._enqueue_agent_work_item", fake_enqueue)

    previous_parallelism = 2
    with Session(engine) as session:
        settings = session.get(ExecutionSettings, 1) or ExecutionSettings(id=1)
        previous_parallelism = settings.parallelism
        settings.parallelism = 1
        session.add(settings)
        mission = _create_project_and_mission(session, mission_type="mixed")
        mission.config = {
            "whole_app_team": True,
            "max_parallel_agents": 3,
            "roles": ["surface_mapper", "requirements_analyst", "rtm_mapper"],
        }
        session.add(mission)
        session.commit()
        mission_id = mission.id

    try:
        run_id = create_mission_run({"mission_id": mission_id, "workflow_id": "wf-team-clamped"})
        summary = execute_mission_iteration(
            {"mission_id": mission_id, "run_id": run_id, "workflow_id": "wf-team-clamped"}
        )
    finally:
        with Session(engine) as session:
            settings = session.get(ExecutionSettings, 1) or ExecutionSettings(id=1)
            settings.parallelism = previous_parallelism
            session.add(settings)
            session.commit()

    assert summary["team"]["max_parallel_agents"] == 1
    assert summary["work_items_enqueued"] == 1
    assert summary["team"]["running_count"] == 1


def test_completed_team_work_items_merge_structured_artifacts_without_duplicates():
    _ensure_tables()
    unique = uuid4().hex
    target_url = f"https://example.com/{unique}/checkout"
    structured_output = {
        "summary": "Checkout coverage analysis.",
        "app_map_updates": [
            {
                "url": target_url,
                "page_title": "Checkout",
                "linked_urls": [f"https://example.com/{unique}/cart"],
                "elements": {"buttons": ["Pay"]},
            }
        ],
        "requirements": [
            {
                "title": "Checkout blocks declined card payments",
                "description": "The checkout flow should reject declined card payments with a clear message.",
                "category": "checkout",
                "priority": "high",
                "truth_state": "confirmed_requirement",
                "confidence": 0.95,
                "acceptance_criteria": ["Declined cards show an error without creating an order."],
            }
        ],
        "rtm_candidates": [
            {
                "requirement_title": "Checkout blocks declined card payments",
                "test_spec_name": "checkout-declined-card.spec.ts",
                "test_spec_path": "tests/generated/checkout-declined-card.spec.ts",
                "mapping_type": "full",
                "confidence": 0.9,
                "coverage_notes": "Covers declined-card payment failure.",
            }
        ],
        "test_proposals": [
            {
                "title": "Checkout declined card regression",
                "rationale": "Covers the critical checkout payment failure path.",
                "target_url": target_url,
                "test_type": "e2e",
                "risk_level": "high",
            }
        ],
        "bugs": [
            {
                "title": "Checkout spinner does not stop after declined card",
                "description": "The page remains loading after a declined card response.",
                "severity": "high",
                "target_url": target_url,
                "action": "Submit declined card",
                "observed_failure": "Spinner remains visible after the decline response.",
                "expected_behavior": "The checkout page shows a payment error.",
            }
        ],
        "blockers": [],
    }

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="mixed")
        mission.config = {"whole_app_team": True, "exploration_enabled": False}
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="running",
        )
        first = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            role="requirements_analyst",
            objective="Analyze checkout.",
            status="completed",
        )
        first.result = {"output": json.dumps(structured_output)}
        second = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            role="spec_writer",
            objective="Draft checkout coverage.",
            status="completed",
        )
        second.result = {"output": json.dumps(structured_output)}
        session.add(run)
        session.add(first)
        session.add(second)
        session.commit()
        mission_id = mission.id
        project_id = mission.project_id
        run_id = run.id

    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        run = session.get(AutonomousMissionRun, run_id)
        created = _create_findings_from_completed_work_items(session, mission, run)
        requirements = session.exec(select(Requirement).where(Requirement.project_id == project_id)).all()
        rtm_entries = session.exec(select(RtmEntry).where(RtmEntry.project_id == project_id)).all()
        proposals = session.exec(
            select(AutonomousTestProposal).where(AutonomousTestProposal.project_id == project_id)
        ).all()
        findings = session.exec(select(AutonomousFinding).where(AutonomousFinding.project_id == project_id)).all()
        snapshots = session.exec(select(RtmSnapshot).where(RtmSnapshot.project_id == project_id)).all()
        app_map = session.exec(select(ApplicationMap).where(ApplicationMap.url == target_url)).first()
        merge_summaries = [
            item.result.get("structured_merge")
            for item in session.exec(
                select(AutonomousAgentWorkItem).where(AutonomousAgentWorkItem.mission_id == mission_id)
            ).all()
        ]

    assert created == 1
    assert len(requirements) == 1
    assert requirements[0].truth_state == "confirmed_requirement"
    assert len(rtm_entries) == 1
    assert rtm_entries[0].mapping_type == "full"
    assert len(proposals) == 1
    assert proposals[0].source_metadata["artifact_type"] == "test_proposal"
    assert proposals[0].source_metadata["requirement_id"] == requirements[0].id
    assert len(findings) == 1
    assert findings[0].finding_type == "bug"
    assert findings[0].evidence["artifact_type"] == "bug"
    assert len(snapshots) == 1
    assert app_map is not None
    assert merge_summaries[0]["requirements_created"] == 1
    assert merge_summaries[1]["requirements_reused"] == 1
    assert merge_summaries[1]["findings_reused"] == 1


def test_invalid_structured_agent_output_creates_revision_work_item():
    _ensure_tables()
    invalid_output = {
        "summary": "Invalid requirement payload.",
        "requirements": [{"description": "Missing the required title field."}],
    }

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="mixed")
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="running",
        )
        item = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            role="requirements_analyst",
            objective="Analyze checkout.",
            status="completed",
        )
        item.result = {"output": json.dumps(invalid_output)}
        session.add(run)
        session.add(item)
        session.commit()
        mission_id = mission.id
        item_id = item.id
        run_id = run.id

    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        run = session.get(AutonomousMissionRun, run_id)
        created = _create_findings_from_completed_work_items(session, mission, run)
        original = session.get(AutonomousAgentWorkItem, item_id)
        revisions = session.exec(
            select(AutonomousAgentWorkItem).where(
                AutonomousAgentWorkItem.mission_id == mission_id,
                AutonomousAgentWorkItem.status == "queued",
            )
        ).all()

    assert created == 0
    assert original.result["review_decision"] == "needs_revision"
    assert original.result["validation_errors"]
    assert len(revisions) == 1
    assert revisions[0].progress["revision_of_work_item_id"] == item_id
    assert revisions[0].progress["review_reason"] == "structured_contract_validation"


def test_whole_app_planner_creates_idempotent_rtm_gap_work_items():
    _ensure_tables()
    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="mixed")
        mission.config = {"whole_app_team": True, "exploration_enabled": False}
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="running",
        )
        requirement = Requirement(
            project_id=mission.project_id,
            req_code=f"REQ-PLAN-{uuid4().hex[:6]}",
            title="Checkout rejects expired cards",
            description="Expired cards should be rejected with a user-facing error.",
            category="checkout",
            priority="high",
            status="confirmed",
            truth_state="confirmed_requirement",
            source_type="manual",
            confidence=1.0,
            canonical_key=f"plan-{uuid4().hex}",
        )
        session.add(run)
        session.add(requirement)
        session.add(mission)
        session.commit()
        mission_id = mission.id
        run_id = run.id

    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        run = session.get(AutonomousMissionRun, run_id)
        first = _plan_whole_app_work_items(session, mission, run)
        second = _plan_whole_app_work_items(session, mission, run)
        items = session.exec(
            select(AutonomousAgentWorkItem).where(AutonomousAgentWorkItem.mission_id == mission_id)
        ).all()

    assert first == 1
    assert second == 0
    assert len(items) == 1
    assert items[0].role == "spec_writer"
    assert items[0].planner_key.startswith("rtm_gap:")


def test_stale_running_work_item_is_recovered_once(monkeypatch):
    _ensure_tables()
    monkeypatch.setattr(
        "orchestrator.services.autonomous_activities._agent_task_recovery_state",
        lambda task_id: "missing_agent_task",
    )
    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="mixed")
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="running",
        )
        item = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            role="explorer",
            planner_key=f"frontier:{uuid4().hex}",
            objective="Explore stale frontier.",
            status="running",
            agent_task_id=f"missing-{uuid4().hex}",
            lease_until=datetime.utcnow() - timedelta(minutes=5),
            last_heartbeat_at=datetime.utcnow() - timedelta(hours=2),
        )
        item.progress = {"planner_key": item.planner_key}
        session.add(run)
        session.add(item)
        session.commit()
        mission_id = mission.id
        run_id = run.id
        item_id = item.id

    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        run = session.get(AutonomousMissionRun, run_id)
        first = _recover_stale_work_items(session, mission, run)
        second = _recover_stale_work_items(session, mission, run)
        original = session.get(AutonomousAgentWorkItem, item_id)
        replacements = session.exec(
            select(AutonomousAgentWorkItem).where(
                AutonomousAgentWorkItem.mission_id == mission_id,
                AutonomousAgentWorkItem.status == "queued",
            )
        ).all()

    assert first == 1
    assert second == 0
    assert original.status == "failed"
    assert original.recovery_reason == "missing_agent_task"
    assert len(replacements) == 1
    assert replacements[0].planner_key == original.planner_key
    assert replacements[0].progress["recovered_from_work_item_id"] == item_id
    assert replacements[0].recovery_count == 1


def test_auto_materialize_low_risk_policy_writes_and_validates(monkeypatch, tmp_path):
    _ensure_tables()
    monkeypatch.setattr("orchestrator.services.autonomous_activities.REPOSITORY_ROOT", tmp_path)

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="mixed")
        mission.approval_policy = "auto_materialize_low_risk"
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="running",
        )
        proposal = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            title="Generated pytest smoke",
            target_url="https://example.com",
            route="/",
            test_type="unit",
            rationale="Low risk generated smoke test.",
            generated_spec_content="def test_generated_smoke():\n    assert True\n",
            suggested_file_path=f"orchestrator/tests/generated/test_generated_{uuid4().hex}.py",
            risk_level="low",
            approval_status="pending",
            dedupe_key=f"proposal-{uuid4().hex}",
            source_type="autonomous_structured_spec",
            source_id=f"source-{uuid4().hex}",
        )
        session.add(run)
        session.add(proposal)
        session.add(mission)
        session.commit()
        mission_id = mission.id
        run_id = run.id
        proposal_id = proposal.id

    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        run = session.get(AutonomousMissionRun, run_id)
        summary = _auto_materialize_low_risk_proposals(session, mission, run)
        proposal = session.get(AutonomousTestProposal, proposal_id)

    assert summary["materialized"] == 1
    assert summary["validated"] == 1
    assert proposal.approval_status == "materialized"
    assert proposal.validation_status == "passed"
    assert proposal.validation_artifacts
    assert proposal.validation_log_path
    assert (tmp_path / proposal.materialized_file_path).exists()


def test_failed_auto_materialized_validation_creates_repair_work_item(monkeypatch, tmp_path):
    _ensure_tables()
    monkeypatch.setattr("orchestrator.services.autonomous_activities.REPOSITORY_ROOT", tmp_path)

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="mixed")
        mission.approval_policy = "auto_materialize_low_risk"
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="running",
        )
        proposal = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            title="Generated failing pytest smoke",
            target_url="https://example.com",
            route="/",
            test_type="unit",
            rationale="Low risk generated smoke test.",
            generated_spec_content="def test_generated_smoke_failure():\n    assert False\n",
            suggested_file_path=f"orchestrator/tests/generated/test_generated_failure_{uuid4().hex}.py",
            risk_level="low",
            approval_status="pending",
            dedupe_key=f"proposal-{uuid4().hex}",
            source_type="autonomous_structured_spec",
            source_id=f"source-{uuid4().hex}",
        )
        session.add(run)
        session.add(proposal)
        session.add(mission)
        session.commit()
        mission_id = mission.id
        run_id = run.id
        proposal_id = proposal.id

    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        run = session.get(AutonomousMissionRun, run_id)
        summary = _auto_materialize_low_risk_proposals(session, mission, run)
        proposal = session.get(AutonomousTestProposal, proposal_id)
        repair = session.exec(
            select(AutonomousAgentWorkItem).where(
                AutonomousAgentWorkItem.mission_id == mission_id,
                AutonomousAgentWorkItem.planner_key == f"proposal_validation_failure:{proposal_id}",
            )
        ).first()

    assert summary["validation_failed"] == 1
    assert proposal.validation_status == "failed"
    assert proposal.validation_result["returncode"] != 0
    assert proposal.validation_artifacts
    assert proposal.validation_log_path
    assert repair is not None
    assert repair.status == "queued"


def test_autonomous_diagnostics_and_backfill_canonical_state():
    _ensure_tables()
    unique = uuid4().hex
    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="mixed")
        requirement = Requirement(
            project_id=mission.project_id,
            req_code=f"REQ-BACKFILL-{unique[:8]}",
            title="Backfilled requirement",
            category="navigation",
            priority="medium",
            status="draft",
            truth_state="confirmed_requirement",
            source_type="manual",
            confidence=1.0,
        )
        session.add(requirement)
        session.flush()
        entry = RtmEntry(
            project_id=mission.project_id,
            requirement_id=requirement.id,
            test_spec_name=f"backfill-{unique}.spec.ts",
            mapping_type="full",
        )
        app_map = ApplicationMap(url=f"https://example.com/{unique}/backfill")
        session.add(entry)
        session.add(app_map)
        session.commit()
        project_id = mission.project_id

    with Session(engine) as session:
        before = autonomous_health_diagnostics(session, project_id=project_id)
        dry_run = backfill_autonomous_canonical_state(session, project_id=project_id, dry_run=True)
        still_before = autonomous_health_diagnostics(session, project_id=project_id)
        summary = backfill_autonomous_canonical_state(session, project_id=project_id)
        after = autonomous_health_diagnostics(session, project_id=project_id)

    assert before["requirements"]["missing_canonical_key"] >= 1
    assert dry_run["dry_run"] is True
    assert still_before["requirements"]["missing_canonical_key"] == before["requirements"]["missing_canonical_key"]
    assert summary["requirements_backfilled"] >= 1
    assert summary["rtm_entries_backfilled"] >= 1
    assert after["requirements"]["missing_canonical_key"] == 0
    assert after["rtm"]["missing_dedupe_key"] == 0


def test_autonomous_monitor_recovers_stale_work_and_updates_mission(monkeypatch):
    _ensure_tables()
    monkeypatch.setattr(
        "orchestrator.services.autonomous_activities._agent_task_recovery_state",
        lambda task_id: "missing_agent_task",
    )
    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="mixed")
        mission.status = "running"
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="running",
        )
        mission.latest_run_id = run.id
        item = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            role="explorer",
            planner_key=f"frontier:{uuid4().hex}",
            objective="Explore stale frontier.",
            status="running",
            agent_task_id=f"missing-{uuid4().hex}",
            lease_until=datetime.utcnow() - timedelta(minutes=5),
            last_heartbeat_at=datetime.utcnow() - timedelta(hours=2),
        )
        session.add(run)
        session.add(item)
        session.add(mission)
        session.commit()
        project_id = mission.project_id
        mission_id = mission.id

    with Session(engine) as session:
        result = monitor_autonomous_project(session, project_id)
        mission = session.get(AutonomousMission, mission_id)
        replacements = session.exec(
            select(AutonomousAgentWorkItem).where(
                AutonomousAgentWorkItem.mission_id == mission_id,
                AutonomousAgentWorkItem.status == "queued",
            )
        ).all()

    assert result["recovery"]["stale_recovered_count"] == 1
    assert mission.config["autonomous_monitor"]["last_monitor_at"]
    assert mission.config["autonomous_monitor"]["stale_running_count"] == 0
    assert len(replacements) == 1


def test_execute_mission_iteration_prioritizes_revision_work_items(monkeypatch):
    _ensure_tables()
    enqueued_ids: list[str] = []

    def fake_enqueue(session, mission, item):
        enqueued_ids.append(item.id)
        item.agent_task_id = f"agent-task-{item.id}"
        item.status = "running"
        session.add(item)
        session.commit()
        return True

    monkeypatch.setattr("orchestrator.services.autonomous_activities._enqueue_agent_work_item", fake_enqueue)

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="mixed")
        mission.config = {"whole_app_team": True, "max_parallel_agents": 1, "roles": ["explorer"]}
        session.add(mission)
        session.commit()
        mission_id = mission.id

    run_id = create_mission_run({"mission_id": mission_id, "workflow_id": "wf-revision-priority"})

    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        regular = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission_id,
            run_id=run_id,
            project_id=mission.project_id,
            role="explorer",
            objective="Ordinary exploration.",
            status="queued",
            priority=1,
        )
        revision = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission_id,
            run_id=run_id,
            project_id=mission.project_id,
            role="spec_writer",
            objective="Revise spec.",
            status="queued",
            priority=50,
        )
        revision.progress = {"revision_of_work_item_id": regular.id, "revision_attempt": 1}
        revision.result = {"revision_of_work_item_id": regular.id, "review_decision": "pending", "revision_attempt": 1}
        session.add(regular)
        session.add(revision)
        session.commit()
        regular_id = regular.id
        revision_id = revision.id

    summary = execute_mission_iteration(
        {"mission_id": mission_id, "run_id": run_id, "workflow_id": "wf-revision-priority"}
    )

    assert summary["work_items_created"] == 0
    assert summary["work_items_enqueued"] == 1
    assert enqueued_ids == [revision_id]

    with Session(engine) as session:
        regular = session.get(AutonomousAgentWorkItem, regular_id)
        revision = session.get(AutonomousAgentWorkItem, revision_id)

    assert regular.status == "queued"
    assert revision.status == "running"


def test_autonomous_work_item_uses_role_based_tool_allowlist():
    item = AutonomousAgentWorkItem(
        id=f"amwork-{uuid4().hex[:12]}",
        mission_id=f"am-{uuid4().hex[:12]}",
        role="spec_writer",
        objective="Draft proposals only.",
    )

    allowed = _allowed_tools_for_work_item(item)

    assert allowed
    assert "*" not in allowed
    assert "Write" not in allowed
    assert "Read" in allowed


def test_work_item_api_lists_retries_and_cancels():
    _ensure_tables()
    app = FastAPI()
    app.include_router(autonomous_api.router)
    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="mixed")
        item = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            role="surface_mapper",
            objective="Map the app surface.",
            status="failed",
            error_message="Worker failed",
        )
        session.add(item)
        session.commit()
        project_id = mission.project_id
        mission_id = mission.id
        item_id = item.id

    with TestClient(app, raise_server_exceptions=False) as client:
        listed = client.get(f"/autonomous/{project_id}/missions/{mission_id}/work-items")
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == item_id

        project_listed = client.get(f"/autonomous/{project_id}/work-items?limit=8")
        assert project_listed.status_code == 200
        assert project_listed.json()[0]["id"] == item_id

        retried = client.post(f"/autonomous/{project_id}/work-items/{item_id}/retry")
        assert retried.status_code == 200
        assert retried.json()["status"] == "queued"
        assert retried.json()["agent_task_id"] is None

        cancelled = client.post(f"/autonomous/{project_id}/work-items/{item_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        events = client.get(f"/autonomous/{project_id}/work-items/{item_id}/events")
        assert events.status_code == 200
        event_types = [event["event_type"] for event in events.json()]
        assert "lifecycle" in event_types


def test_autonomous_agent_events_are_ordered_and_redacted():
    _ensure_tables()
    with Session(engine) as session:
        mission = _create_project_and_mission(session)
        project_id = mission.project_id
        mission_id = mission.id

    first = create_autonomous_agent_event(
        project_id=project_id,
        mission_id=mission_id,
        event_type="assistant_output",
        message="Inspecting login flow",
        payload={"authorization": "Bearer should-not-leak", "nested": {"api_key": "secret"}},
    )
    second = create_autonomous_agent_event(
        project_id=project_id,
        mission_id=mission_id,
        event_type="browser_action",
        message="Tool call: browser_click",
        payload={"short_name": "browser_click"},
    )

    with Session(engine) as session:
        events = session.exec(
            select(AutonomousAgentEvent)
            .where(AutonomousAgentEvent.mission_id == mission_id)
            .order_by(AutonomousAgentEvent.sequence)
        ).all()

    assert [event.id for event in events] == [first.id, second.id]
    assert events[0].payload["authorization"] == "[redacted]"
    assert events[0].payload["nested"]["api_key"] == "[redacted]"


@pytest.mark.asyncio
async def test_autonomous_temporal_health_degrades_without_worker_pollers(monkeypatch):
    from orchestrator.services import temporal_client

    async def connected():
        return object()

    async def task_queue_status(_task_queue: str):
        return {
            "workflow_pollers": 0,
            "activity_pollers": 0,
            "has_workflow_pollers": False,
            "has_activity_pollers": False,
        }

    monkeypatch.setattr(temporal_client, "_connect_client", connected)
    monkeypatch.setattr(temporal_client, "describe_temporal_task_queue", task_queue_status)

    health = await temporal_client.check_autonomous_mission_temporal_health()

    assert health["available"] is False
    assert health["status"] == "degraded"
    assert health["task_queue"]
    assert health["worker_pollers"] == {"workflow": 0, "activity": 0}
    assert "autonomous missions" in health["error"]


def test_start_mission_returns_503_when_autonomous_worker_unavailable(monkeypatch):
    _ensure_tables()
    app = FastAPI()
    app.include_router(autonomous_api.router)
    with Session(engine) as session:
        mission = _create_project_and_mission(session)
        project_id = mission.project_id
        mission_id = mission.id

    async def unavailable():
        return {
            "available": False,
            "status": "degraded",
            "task_queue": "quorvex-autonomous-missions",
            "worker_pollers": {"workflow": 0, "activity": 0},
            "error": "No Temporal worker pollers are active for autonomous missions.",
        }

    async def should_not_start(_mission_id: str):
        raise AssertionError("workflow should not start without pollers")

    monkeypatch.setattr("orchestrator.services.temporal_client.check_autonomous_mission_temporal_health", unavailable)
    monkeypatch.setattr("orchestrator.services.temporal_client.start_autonomous_mission_workflow", should_not_start)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(f"/autonomous/{project_id}/missions/{mission_id}/start")

    assert response.status_code == 503
    payload = response.json()["detail"]
    assert payload["task_queue"] == "quorvex-autonomous-missions"
    assert payload["worker_pollers"] == {"workflow": 0, "activity": 0}
    with Session(engine) as session:
        mission_db = session.get(AutonomousMission, mission_id)
        assert mission_db.status == "error"
        assert mission_db.current_stage == "worker_unavailable"


def test_direct_work_item_execution_emits_progress_tool_browser_and_completion_events(monkeypatch, tmp_path):
    _ensure_tables()

    class FakeRuntime:
        async def run(self, _prompt, context):
            context.on_task_enqueued("agent-task-1")
            context.on_progress({"phase": "running", "message": "Inspecting target page"})
            context.on_tool_use("mcp__playwright__browser_navigate", {"url": "https://example.com"})
            context.on_progress(
                {
                    "phase": "tool_result",
                    "message": "Navigation complete",
                    "last_tool": "mcp__playwright__browser_navigate",
                    "tool_calls": 1,
                    "browser_tool_calls": 1,
                }
            )
            return AgentResult(
                success=True,
                output="Finished browser-backed exploration.",
                tool_calls=[
                    ToolCall(
                        name="mcp__playwright__browser_navigate",
                        timestamp=datetime.utcnow(),
                        success=True,
                        input={"url": "https://example.com"},
                    )
                ],
                messages_received=3,
                text_blocks_received=1,
                duration_seconds=1.2,
            )

    monkeypatch.setattr("orchestrator.services.autonomous_activities.RUNS_DIR", tmp_path)
    monkeypatch.setattr("orchestrator.services.agent_runtimes.get_agent_runtime", lambda _runtime: FakeRuntime())
    monkeypatch.setattr(
        "orchestrator.utils.playwright_mcp.browser_runtime_status",
        lambda: {
            "browser_runtime": "vnc",
            "live_view_available": True,
            "vnc_url": "ws://localhost:6080/websockify",
        },
    )

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="exploration")
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="running",
        )
        item = AutonomousAgentWorkItem(
            id=f"amwi-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            role="explorer",
            objective="Explore the homepage",
            assigned_surface="https://example.com",
            status="queued",
        )
        session.add(run)
        session.add(item)
        session.commit()

        assert _execute_agent_work_item_direct(session, mission, item) is True

        events = session.exec(
            select(AutonomousAgentEvent)
            .where(AutonomousAgentEvent.work_item_id == item.id)
            .order_by(AutonomousAgentEvent.sequence)
        ).all()
        event_types = [event.event_type for event in events]
        assert "progress" in event_types
        assert "tool_call" in event_types
        assert "browser_action" in event_types
        assert "assistant_output" in event_types
        assert "complete" in event_types


def test_direct_work_item_execution_does_not_overwrite_cancelled_state(monkeypatch, tmp_path):
    _ensure_tables()
    item_id_holder: dict[str, str] = {}

    class FakeRuntime:
        async def run(self, _prompt, context):
            with Session(engine) as session:
                item = session.get(AutonomousAgentWorkItem, item_id_holder["item_id"])
                item.status = "cancelled"
                item.error_message = "Cancelled while runtime was active"
                item.progress = {"phase": "cancelled", "message": item.error_message}
                session.add(item)
                session.commit()
            assert context.is_cancelled() is True
            return AgentResult(
                success=True,
                output="Late successful output that must remain partial evidence only.",
                tool_calls=[
                    ToolCall(
                        name="mcp__playwright__browser_snapshot",
                        timestamp=datetime.utcnow(),
                        success=True,
                    )
                ],
                messages_received=2,
                text_blocks_received=1,
                duration_seconds=0.4,
            )

    monkeypatch.setattr("orchestrator.services.autonomous_activities.RUNS_DIR", tmp_path)
    monkeypatch.setattr("orchestrator.services.agent_runtimes.get_agent_runtime", lambda _runtime: FakeRuntime())

    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="exploration")
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="running",
        )
        item = AutonomousAgentWorkItem(
            id=f"amwi-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            role="explorer",
            objective="Explore the homepage",
            status="queued",
        )
        session.add(run)
        session.add(item)
        session.commit()
        item_id_holder["item_id"] = item.id

        assert _execute_agent_work_item_direct(session, mission, item) is False

        cancelled = session.get(AutonomousAgentWorkItem, item.id)
        assert cancelled.status == "cancelled"
        assert cancelled.error_message == "Cancelled while runtime was active"
        assert cancelled.result["output"] == "Late successful output that must remain partial evidence only."
        assert cancelled.result["telemetry"]["cancelled"] is True


def test_autonomous_artifacts_endpoint_returns_latest_screenshot(monkeypatch, tmp_path):
    _ensure_tables()
    monkeypatch.setattr(autonomous_api, "BASE_DIR", tmp_path)
    run_root = tmp_path / "runs"

    app = FastAPI()
    app.include_router(autonomous_api.router)
    with Session(engine) as session:
        mission = _create_project_and_mission(session, mission_type="exploration")
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="running",
        )
        item = AutonomousAgentWorkItem(
            id=f"amwi-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            role="explorer",
            objective="Explore with browser",
            status="running",
        )
        mission.latest_run_id = run.id
        session.add(mission)
        session.add(run)
        session.add(item)
        session.commit()
        project_id = mission.project_id
        mission_id = mission.id
        item_id = item.id

    screenshot_dir = run_root / "autonomous" / mission_id / item_id
    screenshot_dir.mkdir(parents=True)
    (screenshot_dir / "live-step-001.png").write_bytes(b"png")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/autonomous/{project_id}/missions/{mission_id}/artifacts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["latest_image"]["name"] == "live-step-001.png"
    assert payload["latest_image"]["path"].startswith("/artifacts/autonomous/")
    assert payload["artifact_count"] >= 1


def test_mission_status_endpoint_reports_health_and_blocking_approvals():
    _ensure_tables()
    app = FastAPI()
    app.include_router(autonomous_api.router)
    with Session(engine) as session:
        mission = _create_project_and_mission(session)
        mission.status = "paused"
        mission.health_status = "blocked"
        mission.paused_reason = "pending_approval_limit"
        mission.next_action = "Review pending approvals before resuming the mission."
        approval = AutonomousApproval(
            id=f"amappr-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            action_type="persist_test",
            status="pending",
        )
        session.add(mission)
        session.add(approval)
        session.commit()
        project_id = mission.project_id
        mission_id = mission.id

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/autonomous/{project_id}/missions/{mission_id}/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mission"]["health_status"] == "blocked"
    assert payload["pending_approval_count"] == 1
    assert payload["blocking_approvals"][0]["action_type"] == "persist_test"
    assert "Review pending approvals" in payload["next_action"]


def test_create_mission_rejects_target_outside_allowed_domain():
    _ensure_tables()
    app = FastAPI()
    app.include_router(autonomous_api.router)
    with Session(engine) as session:
        project = Project(id=f"autonomous-project-{uuid4().hex}", name=f"Safety Project {uuid4().hex}")
        session.add(project)
        session.commit()
        project_id = project.id

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/autonomous/{project_id}/missions",
            json={
                "name": "Unsafe scope",
                "mission_type": "exploration",
                "target_urls": ["https://production.example.com"],
                "config": {"allowed_domains": ["staging.example.com"], "environment": "staging"},
            },
        )

    assert response.status_code == 400
    assert "outside the allowed" in response.text


def test_test_proposal_api_approve_reject_and_materialize(monkeypatch, tmp_path):
    _ensure_tables()
    monkeypatch.setattr(autonomous_api, "BASE_DIR", tmp_path)
    app = FastAPI()
    app.include_router(autonomous_api.router)

    with Session(engine) as session:
        mission = _create_project_and_mission(session)
        approved = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            title="Homepage autonomous coverage",
            target_url="https://example.com",
            route="/",
            test_type="e2e",
            rationale="Exercise homepage rendering from an autonomous coverage gap.",
            generated_spec_content="import { test, expect } from '@playwright/test';\n\ntest('generated', async ({ page }) => { await page.goto('https://example.com'); await expect(page.locator('body')).toBeVisible(); });\n",
            suggested_file_path="tests/generated/homepage-autonomous-coverage.spec.ts",
            risk_level="medium",
            approval_status="pending",
            dedupe_key=f"proposal-{uuid4().hex}",
            source_type="coverage_gap",
            source_id="1",
        )
        rejected = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            title="Rejected proposal",
            test_type="e2e",
            rationale="Reject this proposal.",
            generated_spec_content="import { test } from '@playwright/test';\n",
            suggested_file_path="tests/generated/rejected-proposal.spec.ts",
            risk_level="low",
            approval_status="pending",
            dedupe_key=f"proposal-{uuid4().hex}",
            source_type="coverage_gap",
            source_id="2",
        )
        session.add(approved)
        session.add(rejected)
        session.commit()
        project_id = mission.project_id
        approved_id = approved.id
        rejected_id = rejected.id

    with TestClient(app, raise_server_exceptions=False) as client:
        listed = client.get(f"/autonomous/{project_id}/proposals")
        assert listed.status_code == 200
        assert {item["id"] for item in listed.json()} >= {approved_id, rejected_id}

        pending_materialize = client.post(f"/autonomous/{project_id}/proposals/{approved_id}/materialize")
        assert pending_materialize.status_code == 409

        approved_response = client.post(
            f"/autonomous/{project_id}/proposals/{approved_id}/approve",
            json={"comment": "Approve generated test"},
        )
        assert approved_response.status_code == 200
        assert approved_response.json()["approval_status"] == "approved"

        materialized = client.post(f"/autonomous/{project_id}/proposals/{approved_id}/materialize")
        assert materialized.status_code == 200
        assert materialized.json()["approval_status"] == "materialized"
        assert (tmp_path / "tests/generated/homepage-autonomous-coverage.spec.ts").exists()

        rejected_response = client.post(f"/autonomous/{project_id}/proposals/{rejected_id}/reject")
        assert rejected_response.status_code == 200
        assert rejected_response.json()["approval_status"] == "rejected"


def test_test_proposal_review_context_reports_duplicates_and_audit(monkeypatch, tmp_path):
    _ensure_tables()
    monkeypatch.setattr(autonomous_api, "BASE_DIR", tmp_path)
    app = FastAPI()
    app.include_router(autonomous_api.router)
    existing_file = tmp_path / "tests/generated/homepage-autonomous-coverage.spec.ts"
    existing_file.parent.mkdir(parents=True)
    existing_file.write_text("import { test } from '@playwright/test';\n", encoding="utf-8")

    with Session(engine) as session:
        mission = _create_project_and_mission(session)
        requirement = Requirement(
            project_id=mission.project_id,
            req_code=f"REQ-AUDIT-{uuid4().hex[:8]}",
            title="Homepage renders useful content",
            category="navigation",
            priority="medium",
            status="draft",
            truth_state="candidate_requirement",
            source_type="app_observation",
            confidence=0.72,
        )
        source_item = AutonomousAgentWorkItem(
            id=f"amwork-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            role="spec_writer",
            objective="Draft homepage coverage.",
            status="completed",
            result_json='{"output": "Drafted homepage coverage.", "review_decision": "accepted"}',
        )
        session.add(requirement)
        session.add(source_item)
        session.flush()
        finding = AutonomousFinding(
            id=f"amfind-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            finding_type="coverage_gap",
            severity="medium",
            title="Homepage coverage gap",
            description="Homepage should have generated coverage.",
            status="approved",
            confidence=0.78,
            dedupe_key=f"finding-{uuid4().hex}",
            source_type="autonomous_work_item",
            source_id=source_item.id,
        )
        finding.evidence = {"requirement_id": requirement.id, "work_item_id": source_item.id}
        first = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            finding_id=finding.id,
            title="Homepage autonomous coverage",
            target_url="https://example.com",
            route="/",
            test_type="e2e",
            rationale="Exercise homepage rendering.",
            generated_spec_content="import { test } from '@playwright/test';\n",
            suggested_file_path="tests/generated/homepage-autonomous-coverage.spec.ts",
            risk_level="medium",
            approval_status="pending",
            dedupe_key=f"proposal-{uuid4().hex}",
            source_type="coverage_gap",
            source_id="1",
            source_metadata_json=f'{{"requirement_id": {requirement.id}, "work_item_id": "{source_item.id}"}}',
        )
        second = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            title="Homepage autonomous coverage smoke",
            target_url="https://example.com",
            route="/",
            test_type="e2e",
            rationale="Similar homepage rendering.",
            generated_spec_content="import { test } from '@playwright/test';\n",
            suggested_file_path="tests/generated/homepage-autonomous-coverage-smoke.spec.ts",
            risk_level="low",
            approval_status="pending",
            dedupe_key=f"proposal-{uuid4().hex}",
            source_type="coverage_gap",
            source_id="2",
        )
        session.add(finding)
        session.add(first)
        session.add(second)
        session.commit()
        project_id = mission.project_id
        proposal_id = first.id
        source_item_id = source_item.id
        requirement_id = requirement.id

    with TestClient(app, raise_server_exceptions=False) as client:
        proposal = client.get(f"/autonomous/{project_id}/proposals/{proposal_id}")
        audit = client.get(f"/autonomous/{project_id}/proposals/{proposal_id}/audit")

    assert proposal.status_code == 200
    review = proposal.json()["review_context"]
    assert review["duplicate"]["has_warning"] is True
    assert review["duplicate"]["existing_file_conflict"] is True
    assert review["duplicate"]["blocking"] is True
    assert review["duplicate"]["severity"] == "blocking"
    assert review["duplicate"]["matches"][0]["kind"] == "generated_test"
    assert review["provenance"]["source_type"] == "coverage_gap"
    assert audit.status_code == 200
    audit_payload = audit.json()
    assert audit_payload["timeline"][0]["type"] == "proposal_created"
    assert audit_payload["source_work_item"]["id"] == source_item_id
    assert audit_payload["linked_requirement"]["id"] == requirement_id
    assert audit_payload["finding"]["id"]
    assert audit_payload["revision_chain"][0]["id"] == source_item_id


def test_test_proposal_review_refresh_queue_and_staleness(monkeypatch, tmp_path):
    _ensure_tables()
    monkeypatch.setattr(autonomous_api, "BASE_DIR", tmp_path)
    app = FastAPI()
    app.include_router(autonomous_api.router)

    with Session(engine) as session:
        mission = _create_project_and_mission(session)
        created_at = datetime.utcnow() - timedelta(days=1)
        proposal = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            title="Settings exploration proposal",
            target_url="https://example.com/settings",
            route="/settings",
            test_type="e2e",
            rationale="Validate settings page discovered by exploration.",
            generated_spec_content="import { test } from '@playwright/test';\n",
            suggested_file_path="tests/generated/settings-exploration.spec.ts",
            risk_level="medium",
            approval_status="pending",
            dedupe_key=f"proposal-{uuid4().hex}",
            source_type="exploration",
            source_id="exp-1",
            source_metadata_json='{"exploration_session_id":"exp-1"}',
            created_at=created_at,
            updated_at=created_at,
        )
        state = BrowserPageState(
            id=f"bps-{uuid4().hex[:12]}",
            project_id=mission.project_id,
            session_id=None,
            page_key="settings",
            state_key=f"settings-{uuid4().hex}",
            url="https://example.com/settings",
            url_template="/settings",
            title="Settings",
            exact_hash=f"hash-{uuid4().hex}",
            last_seen_at=datetime.utcnow(),
            status="active",
        )
        session.add(proposal)
        session.add(state)
        session.commit()
        project_id = mission.project_id
        proposal_id = proposal.id

    with TestClient(app, raise_server_exceptions=False) as client:
        refreshed = client.post(f"/autonomous/{project_id}/proposals/{proposal_id}/refresh-review")
        queue = client.get(f"/autonomous/{project_id}/proposal-review")

    assert refreshed.status_code == 200
    staleness = refreshed.json()["review_context"]["staleness"]
    assert staleness["status"] == "needs_review"
    assert staleness["is_stale"] is False
    assert staleness["reasons"][0]["source"] == "browser_memory"
    assert queue.status_code == 200
    assert queue.json()["counts"]["needs_review"] >= 1
    with Session(engine) as session:
        stored = session.get(AutonomousTestProposal, proposal_id)
        assert stored.source_metadata["review"]["staleness"]["status"] == "needs_review"


def test_test_proposal_materialize_blocks_duplicate_without_override(monkeypatch, tmp_path):
    _ensure_tables()
    monkeypatch.setattr(autonomous_api, "BASE_DIR", tmp_path)
    app = FastAPI()
    app.include_router(autonomous_api.router)

    with Session(engine) as session:
        mission = _create_project_and_mission(session)
        existing = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            title="Existing checkout coverage",
            target_url="https://example.com/checkout",
            route="/checkout",
            test_type="e2e",
            rationale="Already materialized checkout coverage.",
            generated_spec_content="import { test } from '@playwright/test';\n",
            suggested_file_path="tests/generated/existing-checkout.spec.ts",
            materialized_file_path="tests/generated/existing-checkout.spec.ts",
            risk_level="medium",
            approval_status="materialized",
            dedupe_key=f"proposal-{uuid4().hex}",
            source_type="coverage_gap",
            source_id="existing",
        )
        proposal = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            title="New checkout coverage",
            target_url="https://example.com/checkout",
            route="/checkout",
            test_type="e2e",
            rationale="Duplicate checkout coverage.",
            generated_spec_content="import { test } from '@playwright/test';\n",
            suggested_file_path="tests/generated/new-checkout.spec.ts",
            risk_level="medium",
            approval_status="approved",
            dedupe_key=f"proposal-{uuid4().hex}",
            source_type="coverage_gap",
            source_id="new",
        )
        session.add(existing)
        session.add(proposal)
        session.commit()
        project_id = mission.project_id
        proposal_id = proposal.id

    with TestClient(app, raise_server_exceptions=False) as client:
        blocked = client.post(f"/autonomous/{project_id}/proposals/{proposal_id}/materialize")
        overridden = client.post(
            f"/autonomous/{project_id}/proposals/{proposal_id}/materialize",
            json={
                "override_blocking_duplicate": True,
                "override_reason": "Intentional variant with different assertions",
            },
        )

    assert blocked.status_code == 409
    assert "Blocking duplicate" in blocked.text
    assert overridden.status_code == 200
    assert overridden.json()["approval_status"] == "materialized"
    assert (tmp_path / "tests/generated/new-checkout.spec.ts").exists()


def test_test_proposal_materialize_rejects_unsafe_paths(monkeypatch, tmp_path):
    _ensure_tables()
    monkeypatch.setattr(autonomous_api, "BASE_DIR", tmp_path)
    app = FastAPI()
    app.include_router(autonomous_api.router)

    with Session(engine) as session:
        mission = _create_project_and_mission(session)
        proposal = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            title="Unsafe path proposal",
            test_type="e2e",
            rationale="Should not materialize outside generated tests.",
            generated_spec_content="import { test } from '@playwright/test';\n",
            suggested_file_path="../unsafe.spec.ts",
            risk_level="medium",
            approval_status="approved",
            dedupe_key=f"proposal-{uuid4().hex}",
            source_type="coverage_gap",
            source_id="unsafe",
        )
        session.add(proposal)
        session.commit()
        project_id = mission.project_id
        proposal_id = proposal.id

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(f"/autonomous/{project_id}/proposals/{proposal_id}/materialize")

    assert response.status_code == 400
    assert not (tmp_path / "unsafe.spec.ts").exists()


def test_proposal_approval_syncs_linked_approval_and_finding():
    _ensure_tables()
    app = FastAPI()
    app.include_router(autonomous_api.router)
    with Session(engine) as session:
        mission = _create_project_and_mission(session)
        run = AutonomousMissionRun(
            id=f"amrun-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            mission_type=mission.mission_type,
            status="running",
        )
        finding = AutonomousFinding(
            id=f"amfind-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            finding_type="coverage_gap",
            severity="medium",
            title="Linked finding",
            description="Linked proposal approval should update this finding.",
            status="awaiting_approval",
            dedupe_key=f"finding-{uuid4().hex}",
        )
        approval = AutonomousApproval(
            id=f"amappr-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            finding_id=finding.id,
            project_id=mission.project_id,
            action_type="persist_test",
            status="pending",
        )
        proposal = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            run_id=run.id,
            project_id=mission.project_id,
            finding_id=finding.id,
            approval_id=approval.id,
            title="Linked proposal",
            test_type="e2e",
            rationale="Approval sync regression.",
            generated_spec_content="import { test } from '@playwright/test';\n",
            suggested_file_path="tests/generated/linked-proposal.spec.ts",
            risk_level="medium",
            approval_status="pending",
            dedupe_key=f"proposal-{uuid4().hex}",
        )
        session.add(run)
        session.add(finding)
        session.add(approval)
        session.add(proposal)
        session.commit()
        project_id = mission.project_id
        proposal_id = proposal.id
        approval_id = approval.id
        finding_id = finding.id

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(f"/autonomous/{project_id}/proposals/{proposal_id}/approve")

    assert response.status_code == 200
    with Session(engine) as session:
        approval_db = session.get(AutonomousApproval, approval_id)
        finding_db = session.get(AutonomousFinding, finding_id)
    assert approval_db.status == "approved"
    assert finding_db.status == "approved"


def test_approval_endpoint_syncs_linked_proposal():
    _ensure_tables()
    app = FastAPI()
    app.include_router(autonomous_api.router)
    with Session(engine) as session:
        mission = _create_project_and_mission(session)
        approval = AutonomousApproval(
            id=f"amappr-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            action_type="persist_test",
            status="pending",
        )
        proposal = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            approval_id=approval.id,
            title="Approval-linked proposal",
            test_type="e2e",
            rationale="Approval endpoint should update proposal.",
            generated_spec_content="import { test } from '@playwright/test';\n",
            suggested_file_path="tests/generated/approval-linked-proposal.spec.ts",
            risk_level="medium",
            approval_status="pending",
            dedupe_key=f"proposal-{uuid4().hex}",
        )
        approval.requested_payload = {"proposal_id": proposal.id}
        session.add(approval)
        session.add(proposal)
        session.commit()
        project_id = mission.project_id
        approval_id = approval.id
        proposal_id = proposal.id

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(f"/autonomous/{project_id}/approvals/{approval_id}/reject")

    assert response.status_code == 200
    with Session(engine) as session:
        proposal_db = session.get(AutonomousTestProposal, proposal_id)
    assert proposal_db.approval_status == "rejected"


def test_delete_mission_removes_proposals_before_dependencies():
    _ensure_tables()
    app = FastAPI()
    app.include_router(autonomous_api.router)
    with Session(engine) as session:
        mission = _create_project_and_mission(session)
        proposal = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=mission.project_id,
            title="Delete me",
            test_type="e2e",
            rationale="Mission deletion should clean proposals.",
            generated_spec_content="import { test } from '@playwright/test';\n",
            suggested_file_path="tests/generated/delete-me.spec.ts",
            risk_level="low",
            approval_status="pending",
            dedupe_key=f"proposal-{uuid4().hex}",
        )
        session.add(proposal)
        session.commit()
        project_id = mission.project_id
        mission_id = mission.id
        proposal_id = proposal.id

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.delete(f"/autonomous/{project_id}/missions/{mission_id}")

    assert response.status_code == 200
    with Session(engine) as session:
        assert session.get(AutonomousTestProposal, proposal_id) is None
        assert session.get(AutonomousMission, mission_id) is None


def test_coverage_gap_generation_skips_non_target_urls():
    _ensure_tables()
    with Session(engine) as session:
        for stale_gap in session.exec(select(CoverageGap)).all():
            session.delete(stale_gap)
        session.commit()
        mission = _create_project_and_mission(session)
        gap = CoverageGap(
            gap_type="untested_flow",
            severity="medium",
            description="Unrelated domain should not be proposed",
            suggested_test="Do not create this proposal.",
            url="https://other.example.org/settings",
        )
        session.add(gap)
        session.commit()
        mission_id = mission.id

    run_id = create_mission_run({"mission_id": mission_id, "workflow_id": "wf-scope"})
    summary = execute_mission_iteration({"mission_id": mission_id, "run_id": run_id, "workflow_id": "wf-scope"})

    assert summary["findings_created"] == 0
    assert summary["test_proposals_created"] == 0


def test_update_mission_rejects_invalid_cron():
    _ensure_tables()
    app = FastAPI()
    app.include_router(autonomous_api.router)
    with Session(engine) as session:
        mission = _create_project_and_mission(session)
        project_id = mission.project_id
        mission_id = mission.id

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch(
            f"/autonomous/{project_id}/missions/{mission_id}",
            json={"schedule_cron": "not a cron"},
        )

    assert response.status_code == 400


def test_generated_pytest_content_escapes_triple_quotes():
    content = _generate_pytest_content(
        title="API quote safety",
        rationale='User input contains """ triple quotes and\nmultiple lines.',
        target_url="https://example.com/api/status",
        route="/api/status",
    )

    compile(content, "generated_test.py", "exec")
    assert '""" triple quotes' in content
