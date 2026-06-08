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

    setattr(sys.modules["slowapi"].Limiter, "limit", _limit)

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


def _create_custom_report_run(run_id: str, project_id: str, requirements: list[dict]) -> None:
    _ensure_tables()
    _cleanup(run_id, project_id)
    with Session(engine) as session:
        run = AgentRun(
            id=run_id,
            agent_type="custom",
            status="completed",
            project_id=project_id,
            config_json='{"url":"https://example.test","agent_name":"Requirements Agent"}',
        )
        run.result = {
            "output": "Done",
            "structured_report": {
                "summary": "Captured candidate requirements.",
                "findings": [],
                "test_ideas": [],
                "requirements": requirements,
            },
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
