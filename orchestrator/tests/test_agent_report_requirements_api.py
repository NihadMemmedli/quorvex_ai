import sys
import types
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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
elif not hasattr(sys.modules["slowapi"].Limiter, "limit"):
    def _limit(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator

    sys.modules["slowapi"].Limiter.limit = _limit

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, select

from orchestrator.api import db as db_module
from orchestrator.api.db import engine
from orchestrator.api.main import app
from orchestrator.api.models_db import AgentRun, AgentRunEvent, Requirement


def _ensure_tables() -> None:
    SQLModel.metadata.create_all(engine, checkfirst=True)
    db_module._run_migrations()


def _cleanup(run_id: str, project_id: str) -> None:
    with Session(engine) as session:
        for event in session.exec(select(AgentRunEvent).where(AgentRunEvent.run_id == run_id)).all():
            session.delete(event)
        run = session.get(AgentRun, run_id)
        if run:
            session.delete(run)
        for requirement in session.exec(select(Requirement).where(Requirement.project_id == project_id)).all():
            session.delete(requirement)
        session.commit()


def _create_custom_report_run(
    run_id: str,
    project_id: str,
    requirements: list[dict],
    *,
    findings: list[dict] | None = None,
    test_ideas: list[dict] | None = None,
    agent_type: str = "custom",
    structured_report: dict | None = None,
) -> None:
    _ensure_tables()
    _cleanup(run_id, project_id)
    report = structured_report if structured_report is not None else {
        "summary": "Captured candidate requirements.",
        "scope": "Checkout",
        "findings": findings or [],
        "test_ideas": test_ideas or [],
        "requirements": requirements,
    }
    with Session(engine) as session:
        run = AgentRun(
            id=run_id,
            agent_type=agent_type,
            status="completed",
            project_id=project_id,
            config_json='{"url":"https://example.test","agent_name":"Requirements Agent"}',
        )
        run.result = {
            "output": "Done",
            "structured_report": report,
        }
        session.add(run)
        session.commit()


def test_import_all_report_requirements_creates_candidates_and_marks_items():
    run_id = f"agent-req-import-{uuid.uuid4().hex[:8]}"
    project_id = f"agent-req-project-{uuid.uuid4().hex[:8]}"
    _create_custom_report_run(
        run_id,
        project_id,
        [
            {
                "id": "R-001",
                "title": "Login requires visible error feedback",
                "description": "Invalid credentials should not fail silently.",
                "category": "authentication",
                "priority": "high",
                "acceptance_criteria": ["Invalid credentials show a visible error."],
                "page": "/login",
                "evidence": "No error was visible.",
                "confidence": 0.81,
            },
            {
                "id": "R-002",
                "title": "Support page loads help content",
                "priority": "medium",
                "acceptance_criteria": ["Support content appears after navigation."],
            },
        ],
    )

    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            f"/api/agents/runs/{run_id}/report-requirements/import?project_id={project_id}",
            json={"import_all": True},
        )
        client.close()

        assert response.status_code == 200
        payload = response.json()
        assert payload["created"] == 2
        assert payload["skipped"] == 0
        assert [item["item_id"] for item in payload["requirements"]] == ["R-001", "R-002"]

        with Session(engine) as session:
            requirements = session.exec(select(Requirement).where(Requirement.project_id == project_id)).all()
            assert len(requirements) == 2
            first = next(req for req in requirements if req.title == "Login requires visible error feedback")
            assert first.truth_state == "candidate_requirement"
            assert first.source_type == "custom_agent_run"
            assert first.confidence == 0.81
            assert first.uncertainty_reason == "Imported from a custom agent report; agent-derived requirement requires human review."
            run = session.get(AgentRun, run_id)
            report_items = run.result["structured_report"]["requirements"]
            assert report_items[0]["imported_requirement_id"] == first.id
            assert report_items[0]["imported_requirement_code"] == first.req_code
            event = session.exec(
                select(AgentRunEvent).where(
                    AgentRunEvent.run_id == run_id,
                    AgentRunEvent.event_type == "requirements_imported",
                )
            ).first()
            assert event is not None
            assert first.req_code in event.payload["created_requirement_codes"]
    finally:
        _cleanup(run_id, project_id)


def test_import_selected_report_requirement_is_idempotent():
    run_id = f"agent-req-import-{uuid.uuid4().hex[:8]}"
    project_id = f"agent-req-project-{uuid.uuid4().hex[:8]}"
    _create_custom_report_run(
        run_id,
        project_id,
        [
            {"id": "R-001", "title": "Profile saves edited name", "priority": "high"},
            {"id": "R-002", "title": "Profile rejects blank name", "priority": "medium"},
        ],
    )

    try:
        client = TestClient(app, raise_server_exceptions=False)
        first = client.post(
            f"/api/agents/runs/{run_id}/report-requirements/import?project_id={project_id}",
            json={"item_ids": ["R-002"]},
        )
        second = client.post(
            f"/api/agents/runs/{run_id}/report-requirements/import?project_id={project_id}",
            json={"item_ids": ["R-002"]},
        )
        client.close()

        assert first.status_code == 200
        assert first.json()["created"] == 1
        assert second.status_code == 200
        assert second.json()["created"] == 0
        assert second.json()["skipped_items"][0]["reason"] == "already_imported"
        with Session(engine) as session:
            requirements = session.exec(select(Requirement).where(Requirement.project_id == project_id)).all()
            assert len(requirements) == 1
            assert requirements[0].title == "Profile rejects blank name"
    finally:
        _cleanup(run_id, project_id)


def test_import_report_requirements_rejects_missing_item_id():
    run_id = f"agent-req-import-{uuid.uuid4().hex[:8]}"
    project_id = f"agent-req-project-{uuid.uuid4().hex[:8]}"
    _create_custom_report_run(run_id, project_id, [{"id": "R-001", "title": "Dashboard loads"}])

    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            f"/api/agents/runs/{run_id}/report-requirements/import?project_id={project_id}",
            json={"item_ids": ["R-999"]},
        )
        client.close()

        assert response.status_code == 404
        assert response.json()["detail"]["missing_item_ids"] == ["R-999"]
        with Session(engine) as session:
            requirements = session.exec(select(Requirement).where(Requirement.project_id == project_id)).all()
            assert requirements == []
    finally:
        _cleanup(run_id, project_id)


def test_agent_report_search_supports_requirement_items():
    run_id = f"agent-req-search-{uuid.uuid4().hex[:8]}"
    project_id = f"agent-req-project-{uuid.uuid4().hex[:8]}"
    _create_custom_report_run(run_id, project_id, [{"id": "R-001", "title": "Checkout preserves cart"}])

    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            f"/api/agents/reports/search?project_id={project_id}&item_type=requirement&query=checkout"
        )
        client.close()

        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 1
        assert payload["items"][0]["type"] == "requirement"
        assert payload["items"][0]["item"]["id"] == "R-001"
    finally:
        _cleanup(run_id, project_id)


def test_edit_report_requirement_then_import_uses_updated_content():
    run_id = f"agent-req-edit-{uuid.uuid4().hex[:8]}"
    project_id = f"agent-req-project-{uuid.uuid4().hex[:8]}"
    _create_custom_report_run(
        run_id,
        project_id,
        [
            {
                "id": "R-001",
                "title": "Original checkout title",
                "priority": "medium",
                "acceptance_criteria": ["Original criterion."],
            }
        ],
    )

    try:
        client = TestClient(app, raise_server_exceptions=False)
        edit = client.patch(
            f"/api/agents/runs/{run_id}/report-items/R-001?item_type=requirement&project_id={project_id}",
            json={
                "patch": {
                    "title": "Checkout shows postal code errors",
                    "description": "Address validation must explain missing postal codes.",
                    "priority": "high",
                    "acceptance_criteria": ["Missing postal code shows inline feedback."],
                }
            },
        )
        imported = client.post(
            f"/api/agents/runs/{run_id}/report-requirements/import?project_id={project_id}",
            json={"item_ids": ["R-001"]},
        )
        client.close()

        assert edit.status_code == 200
        edited_item = edit.json()["item"]
        assert edited_item["title"] == "Checkout shows postal code errors"
        assert edited_item["acceptance_criteria"] == ["Missing postal code shows inline feedback."]
        assert imported.status_code == 200
        with Session(engine) as session:
            requirement = session.exec(select(Requirement).where(Requirement.project_id == project_id)).one()
            assert requirement.title == "Checkout shows postal code errors"
            assert requirement.priority == "high"
            assert requirement.acceptance_criteria == ["Missing postal code shows inline feedback."]
    finally:
        _cleanup(run_id, project_id)


def test_edit_report_item_rejects_protected_fields():
    run_id = f"agent-report-edit-{uuid.uuid4().hex[:8]}"
    project_id = f"agent-req-project-{uuid.uuid4().hex[:8]}"
    _create_custom_report_run(
        run_id,
        project_id,
        [{"id": "R-001", "title": "Checkout preserves cart"}],
    )

    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.patch(
            f"/api/agents/runs/{run_id}/report-items/R-001?item_type=requirement&project_id={project_id}",
            json={"patch": {"id": "R-999", "title": "Edited title"}},
        )
        client.close()

        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["fields"] == ["id"]
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            item = run.result["structured_report"]["requirements"][0]
            assert item["id"] == "R-001"
            assert item["title"] == "Checkout preserves cart"
    finally:
        _cleanup(run_id, project_id)


def test_edit_report_finding_and_test_idea_updates_stored_json_and_search():
    run_id = f"agent-report-edit-{uuid.uuid4().hex[:8]}"
    project_id = f"agent-req-project-{uuid.uuid4().hex[:8]}"
    _create_custom_report_run(
        run_id,
        project_id,
        [],
        findings=[{"id": "F-001", "title": "Original finding", "severity": "low"}],
        test_ideas=[{"id": "T-001", "title": "Original test", "steps": ["Old step"], "expected": "Old result"}],
    )

    try:
        client = TestClient(app, raise_server_exceptions=False)
        finding = client.patch(
            f"/api/agents/runs/{run_id}/report-items/F-001?item_type=finding&project_id={project_id}",
            json={"patch": {"title": "Edited address validation finding", "severity": "high", "evidence": "Edited evidence"}},
        )
        test_idea = client.patch(
            f"/api/agents/runs/{run_id}/report-items/T-001?item_type=test_idea&project_id={project_id}",
            json={"patch": {"title": "Edited regression test", "steps": ["Open checkout", "Submit blank postal code"], "expected": "Edited expected"}},
        )
        search = client.get(
            f"/api/agents/reports/search?project_id={project_id}&item_type=finding&query=edited%20address"
        )
        client.close()

        assert finding.status_code == 200
        assert test_idea.status_code == 200
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            report = run.result["structured_report"]
            assert report["findings"][0]["title"] == "Edited address validation finding"
            assert report["findings"][0]["severity"] == "high"
            assert report["test_ideas"][0]["steps"] == ["Open checkout", "Submit blank postal code"]
            assert report["test_ideas"][0]["expected"] == "Edited expected"
        assert search.status_code == 200
        assert search.json()["count"] == 1
        assert search.json()["items"][0]["item"]["title"] == "Edited address validation finding"
    finally:
        _cleanup(run_id, project_id)


def test_edit_report_overview_updates_summary_and_scope():
    run_id = f"agent-report-overview-{uuid.uuid4().hex[:8]}"
    project_id = f"agent-req-project-{uuid.uuid4().hex[:8]}"
    _create_custom_report_run(run_id, project_id, [])

    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.patch(
            f"/api/agents/runs/{run_id}/report?project_id={project_id}",
            json={"summary": "Edited summary.", "scope": "Edited scope."},
        )
        client.close()

        assert response.status_code == 200
        payload = response.json()
        assert payload["structured_report"]["summary"] == "Edited summary."
        assert payload["structured_report"]["scope"] == "Edited scope."
        assert payload["run"]["result"]["structured_report"]["summary"] == "Edited summary."
    finally:
        _cleanup(run_id, project_id)


def test_edit_report_item_rejects_missing_non_custom_and_imported_requirement():
    run_id = f"agent-report-reject-{uuid.uuid4().hex[:8]}"
    project_id = f"agent-req-project-{uuid.uuid4().hex[:8]}"
    _create_custom_report_run(
        run_id,
        project_id,
        [{"id": "R-001", "title": "Imported requirement", "imported_requirement_id": 123}],
        findings=[{"id": "F-001", "title": "Finding"}],
    )
    non_custom_run_id = f"agent-report-noncustom-{uuid.uuid4().hex[:8]}"
    _create_custom_report_run(non_custom_run_id, project_id, [], agent_type="exploratory")

    try:
        client = TestClient(app, raise_server_exceptions=False)
        missing = client.patch(
            f"/api/agents/runs/{run_id}/report-items/F-999?item_type=finding&project_id={project_id}",
            json={"patch": {"title": "Nope"}},
        )
        non_custom = client.patch(
            f"/api/agents/runs/{non_custom_run_id}/report-items/R-001?item_type=requirement&project_id={project_id}",
            json={"patch": {"title": "Nope"}},
        )
        imported = client.patch(
            f"/api/agents/runs/{run_id}/report-items/R-001?item_type=requirement&project_id={project_id}",
            json={"patch": {"title": "Nope"}},
        )
        client.close()

        assert missing.status_code == 404
        assert non_custom.status_code == 400
        assert imported.status_code == 409
    finally:
        _cleanup(run_id, project_id)
        _cleanup(non_custom_run_id, project_id)
