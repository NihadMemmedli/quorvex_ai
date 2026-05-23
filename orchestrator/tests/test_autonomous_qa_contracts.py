import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-autonomous-qa-contracts")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from orchestrator.api import requirements as requirements_api  # noqa: E402
from orchestrator.api.db import _run_migrations, engine  # noqa: E402
from orchestrator.api.models_db import (  # noqa: E402
    AutonomousAgentEvent,
    AutonomousFinding,
    AutonomousMission,
    AutonomousTestProposal,
    Project,
    Requirement,
)
from orchestrator.api.requirements import (  # noqa: E402
    _requirement_confidence,
    _requirement_source_type,
    _requirement_truth_state,
    _requirement_uncertainty_reason,
)
from orchestrator.services.exploration_policy import (  # noqa: E402
    ExplorationPolicyError,
    ExplorationSafetyPolicy,
    policy_to_agent_instructions,
    validate_exploration_policy,
)


def test_exploration_policy_infers_domain_and_builds_agent_guardrails():
    policy = validate_exploration_policy(
        "https://staging.example.com/settings",
        ExplorationSafetyPolicy(
            allowed_routes=["/settings"],
            blocked_routes=["/billing"],
            read_only=True,
            blocked_action_terms=["delete account"],
        ),
    )

    assert policy.allowed_domains == ["staging.example.com"]
    instructions = policy_to_agent_instructions(policy)
    assert "Read-only mode is enabled" in instructions
    assert "delete account" in instructions
    assert "Do not navigate outside" in instructions


def test_exploration_policy_blocks_disallowed_domains_and_routes():
    with pytest.raises(ExplorationPolicyError):
        validate_exploration_policy(
            "https://prod.example.com/admin",
            ExplorationSafetyPolicy(allowed_domains=["staging.example.com"]),
        )

    with pytest.raises(ExplorationPolicyError):
        validate_exploration_policy(
            "https://staging.example.com/billing",
            ExplorationSafetyPolicy(allowed_domains=["example.com"], blocked_routes=["/billing"]),
        )


def test_requirement_truth_contract_separates_candidate_and_confirmed_requirements():
    candidate = SimpleNamespace(status="draft", source_session_id="explore-1")
    confirmed = SimpleNamespace(status="approved", source_session_id="explore-1")
    observed = SimpleNamespace(status="observed", source_session_id="explore-1")
    manual = SimpleNamespace(status="draft", source_session_id=None)

    assert _requirement_truth_state(candidate) == "candidate_requirement"
    assert _requirement_source_type(candidate) == "app_observation"
    assert _requirement_confidence(candidate) == 0.7
    assert _requirement_uncertainty_reason(candidate)

    assert _requirement_truth_state(confirmed) == "confirmed_requirement"
    assert _requirement_source_type(confirmed) == "app_observation"
    assert _requirement_confidence(confirmed) == 1.0

    assert _requirement_truth_state(observed) == "observed_behavior"
    assert _requirement_uncertainty_reason(observed)

    assert _requirement_truth_state(manual) == "manual_requirement"
    assert _requirement_source_type(manual) == "manual_entry"


def test_requirement_truth_decisions_are_durable():
    SQLModel.metadata.create_all(engine, checkfirst=True)
    _run_migrations()
    app = FastAPI()
    app.include_router(requirements_api.router)

    with Session(engine) as session:
        project = Project(id=f"truth-project-{uuid4().hex}", name=f"Requirement Truth Project {uuid4().hex}")
        requirement = Requirement(
            project_id=project.id,
            req_code=f"REQ-TRUTH-{uuid4().hex[:8]}",
            title="Login should reject empty password",
            description="Candidate inferred from observed login behavior.",
            category="authentication",
            priority="high",
            status="draft",
            truth_state="candidate_requirement",
            source_type="app_observation",
            confidence=0.65,
            uncertainty_reason="Observed behavior needs human confirmation.",
        )
        session.add(project)
        session.add(requirement)
        session.commit()
        session.refresh(requirement)
        project_id = project.id
        requirement_id = requirement.id

    with TestClient(app, raise_server_exceptions=False) as client:
        confirmed = client.post(
            f"/requirements/{requirement_id}/confirm?project_id={project_id}",
            json={"user": "qa-lead", "comment": "Matches the auth spec."},
        )

    assert confirmed.status_code == 200
    confirmed_body = confirmed.json()
    assert confirmed_body["truth_state"] == "confirmed_requirement"
    assert confirmed_body["status"] == "confirmed"
    assert confirmed_body["confidence"] == 1.0
    assert confirmed_body["confirmed_by"] == "qa-lead"
    assert confirmed_body["uncertainty_reason"] is None

    with TestClient(app, raise_server_exceptions=False) as client:
        rejected = client.post(
            f"/requirements/{requirement_id}/reject?project_id={project_id}",
            json={"user": "qa-lead", "comment": "Superseded by SSO flow."},
        )

    assert rejected.status_code == 200
    rejected_body = rejected.json()
    assert rejected_body["truth_state"] == "rejected_requirement"
    assert rejected_body["status"] == "rejected"
    assert rejected_body["rejected_by"] == "qa-lead"
    assert rejected_body["uncertainty_reason"] == "Superseded by SSO flow."

    with Session(engine) as session:
        stored = session.get(Requirement, requirement_id)

    assert stored.truth_state == "rejected_requirement"
    assert stored.rejected_by == "qa-lead"


def test_requirement_truth_filter_and_bulk_review_decisions():
    SQLModel.metadata.create_all(engine, checkfirst=True)
    _run_migrations()
    app = FastAPI()
    app.include_router(requirements_api.router)

    with Session(engine) as session:
        project = Project(id=f"truth-project-{uuid4().hex}", name=f"Requirement Review Project {uuid4().hex}")
        candidate = Requirement(
            project_id=project.id,
            req_code=f"REQ-CAND-{uuid4().hex[:8]}",
            title="Candidate requirement",
            category="navigation",
            priority="medium",
            status="draft",
            truth_state="candidate_requirement",
            source_type="app_observation",
            confidence=0.7,
        )
        manual = Requirement(
            project_id=project.id,
            req_code=f"REQ-MAN-{uuid4().hex[:8]}",
            title="Manual requirement",
            category="navigation",
            priority="medium",
            status="draft",
            truth_state="manual_requirement",
            source_type="manual",
            confidence=0.9,
        )
        session.add(project)
        session.add(candidate)
        session.add(manual)
        session.commit()
        session.refresh(candidate)
        session.refresh(manual)
        project_id = project.id
        candidate_id = candidate.id
        manual_id = manual.id

    with TestClient(app, raise_server_exceptions=False) as client:
        filtered = client.get(f"/requirements?project_id={project_id}&truth_state=candidate_requirement")
        bulk = client.post(
            f"/requirements/review/decisions?project_id={project_id}",
            json={
                "user": "qa-reviewer",
                "decisions": [
                    {"req_id": candidate_id, "decision": "confirm"},
                    {"req_id": manual_id, "decision": "stale", "comment": "Outdated copy."},
                ],
            },
        )

    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == candidate_id
    assert bulk.status_code == 200
    payload = bulk.json()
    assert payload["updated"] == 2
    assert payload["errors"] == []
    states = {item["id"]: item["truth_state"] for item in payload["requirements"]}
    assert states[candidate_id] == "confirmed_requirement"
    assert states[manual_id] == "stale_requirement"


def test_requirement_spec_status_warns_but_allows_non_confirmed_generation():
    SQLModel.metadata.create_all(engine, checkfirst=True)
    _run_migrations()
    app = FastAPI()
    app.include_router(requirements_api.router)

    with Session(engine) as session:
        project = Project(id=f"truth-project-{uuid4().hex}", name=f"Requirement Spec Warning {uuid4().hex}")
        requirement = Requirement(
            project_id=project.id,
            req_code=f"REQ-SPEC-{uuid4().hex[:8]}",
            title="Observed login behavior",
            category="authentication",
            priority="medium",
            status="observed",
            truth_state="observed_behavior",
            source_type="app_observation",
            confidence=0.5,
        )
        session.add(project)
        session.add(requirement)
        session.commit()
        session.refresh(requirement)
        project_id = project.id
        requirement_id = requirement.id

    with TestClient(app, raise_server_exceptions=True) as client:
        response = client.get(f"/requirements/{requirement_id}/spec-status?project_id={project_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["has_spec"] is False
    assert payload["truth_state"] == "observed_behavior"
    assert payload["generation_allowed"] is True
    assert "observed behavior" in payload["generation_warning"].lower()


def test_rejected_requirement_propagates_to_linked_autonomous_artifacts():
    SQLModel.metadata.create_all(engine, checkfirst=True)
    _run_migrations()
    app = FastAPI()
    app.include_router(requirements_api.router)

    with Session(engine) as session:
        project = Project(id=f"truth-project-{uuid4().hex}", name=f"Requirement Propagation {uuid4().hex}")
        mission = AutonomousMission(
            id=f"am-{uuid4().hex[:12]}",
            project_id=project.id,
            name="Propagation mission",
            mission_type="regression",
            status="paused",
            target_urls_json='["https://example.com"]',
            approval_policy="approval_required",
            autonomy_level="draft_validate",
            max_iterations=1,
        )
        requirement = Requirement(
            project_id=project.id,
            req_code=f"REQ-PROP-{uuid4().hex[:8]}",
            title="Rejected candidate requirement",
            category="checkout",
            priority="high",
            status="draft",
            truth_state="candidate_requirement",
            source_type="app_observation",
            confidence=0.7,
        )
        session.add(project)
        session.add(mission)
        session.add(requirement)
        session.flush()
        finding = AutonomousFinding(
            id=f"amfind-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=project.id,
            finding_type="memory_delta",
            severity="high",
            title="Candidate-linked finding",
            description="This finding is linked to a candidate requirement.",
            status="awaiting_approval",
            confidence=0.8,
            dedupe_key=f"finding-{uuid4().hex}",
            source_type="browser_memory_delta",
            source_id="checkout",
        )
        finding.evidence = {"requirement_id": requirement.id}
        pending = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=project.id,
            finding_id=finding.id,
            title="Pending linked proposal",
            test_type="e2e",
            rationale="Should be rejected with requirement.",
            generated_spec_content="import { test } from '@playwright/test';\n",
            suggested_file_path="tests/generated/pending-linked.spec.ts",
            risk_level="high",
            approval_status="pending",
            dedupe_key=f"proposal-{uuid4().hex}",
            source_type="autonomous_finding",
            source_id=finding.id,
        )
        pending.source_metadata = {"requirement_id": requirement.id}
        materialized = AutonomousTestProposal(
            id=f"amprop-{uuid4().hex[:12]}",
            mission_id=mission.id,
            project_id=project.id,
            finding_id=finding.id,
            title="Materialized linked proposal",
            test_type="e2e",
            rationale="Should keep materialized status.",
            generated_spec_content="import { test } from '@playwright/test';\n",
            suggested_file_path="tests/generated/materialized-linked.spec.ts",
            risk_level="medium",
            approval_status="materialized",
            dedupe_key=f"proposal-{uuid4().hex}",
            source_type="autonomous_finding",
            source_id=finding.id,
            materialized_file_path="tests/generated/materialized-linked.spec.ts",
        )
        materialized.source_metadata = {"requirement_id": requirement.id}
        session.add(finding)
        session.add(pending)
        session.add(materialized)
        session.commit()
        project_id = project.id
        requirement_id = requirement.id
        finding_id = finding.id
        pending_id = pending.id
        materialized_id = materialized.id

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/requirements/{requirement_id}/reject?project_id={project_id}",
            json={"user": "qa-lead", "comment": "Incorrect inferred requirement."},
        )

    assert response.status_code == 200
    with Session(engine) as session:
        finding_db = session.get(AutonomousFinding, finding_id)
        pending_db = session.get(AutonomousTestProposal, pending_id)
        materialized_db = session.get(AutonomousTestProposal, materialized_id)
        events = session.exec(
            select(AutonomousAgentEvent).where(
                AutonomousAgentEvent.project_id == project_id,
                AutonomousAgentEvent.event_type == "requirement_propagation",
            )
        ).all()

    assert finding_db.status == "rejected"
    assert finding_db.evidence["requirement_truth_state"] == "rejected_requirement"
    assert pending_db.approval_status == "rejected"
    assert pending_db.source_metadata["requirement_truth_state"] == "rejected_requirement"
    assert materialized_db.approval_status == "materialized"
    assert materialized_db.source_metadata["requirement_truth_state"] == "rejected_requirement"
    assert events
    assert events[-1].payload["finding_count"] >= 1
    assert pending_id in events[-1].payload["proposal_ids"]
