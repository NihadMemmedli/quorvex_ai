import os
import sys
import types
from pathlib import Path
from uuid import uuid4

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
    AutonomousAgentWorkItem,
    AutonomousApproval,
    AutonomousFinding,
    AutonomousMission,
    AutonomousMissionRun,
    AutonomousTestProposal,
    CoverageGap,
    Project,
)
from orchestrator.services.autonomous_activities import (
    _generate_pytest_content,
    complete_mission_run,
    create_mission_run,
    execute_mission_iteration,
    fail_mission_run,
    load_mission_policy,
)


def _ensure_tables() -> None:
    SQLModel.metadata.create_all(engine, checkfirst=True)


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
    )
    session.add(project)
    session.add(mission)
    session.commit()
    session.refresh(mission)
    return mission


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

    duplicate_summary = execute_mission_iteration({"mission_id": mission_id, "run_id": run_id, "workflow_id": "wf-test"})
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
        proposals = session.exec(select(AutonomousTestProposal).where(AutonomousTestProposal.mission_id == mission_id)).all()

    assert len(proposals) == 1
    assert proposals[0].approval_status == "pending"
    assert proposals[0].test_type in {"e2e", "api", "regression", "security", "accessibility", "unit"}
    assert proposals[0].suggested_file_path.startswith(("tests/generated/", "orchestrator/tests/generated/"))
    assert "coverage" in proposals[0].generated_spec_content.lower() or "rationale" in proposals[0].generated_spec_content.lower()


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
        proposals = session.exec(select(AutonomousTestProposal).where(AutonomousTestProposal.mission_id == mission_id)).all()

    assert len(proposals) == 1
    assert proposals[0].finding_id == finding_id
    assert proposals[0].target_url == "https://example.com/profile"
    assert proposals[0].approval_status == "pending"


def test_execute_mission_iteration_creates_parallel_team_work_items(monkeypatch):
    _ensure_tables()

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
        items = session.exec(select(AutonomousAgentWorkItem).where(AutonomousAgentWorkItem.mission_id == mission_id)).all()

    assert {item.role for item in items} == {"surface_mapper", "requirements_analyst", "rtm_mapper"}
    assert len([item for item in items if item.status == "running"]) == 2


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
