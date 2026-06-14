import os
import sys
import types
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select

pytestmark = [pytest.mark.project_isolation, pytest.mark.backend_negative]

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-project-boundaries")
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


def _workflow_client(tmp_path):
    from orchestrator.api import workflows
    from orchestrator.api.models_db import (
        Project,
        WorkflowDefinition,
        WorkflowRun,
        WorkflowRunStep,
        WorkflowSchedule,
        WorkflowScheduleExecution,
    )

    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'workflow-boundary.db'}",
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        session.add(Project(id="project-a", name="Project A"))
        session.add(Project(id="project-b", name="Project B"))
        definition_a = WorkflowDefinition(project_id="project-a", name="Workflow A")
        definition_a.steps = [{"key": "review", "type": "review_gate", "input": {"question": "A?"}}]
        definition_b = WorkflowDefinition(project_id="project-b", name="Workflow B")
        definition_b.steps = [{"key": "review", "type": "review_gate", "input": {"question": "B?"}}]
        session.add(definition_a)
        session.add(definition_b)
        session.commit()
        session.refresh(definition_a)
        session.refresh(definition_b)

        run_b = WorkflowRun(definition_id=definition_b.id, project_id="project-b", status="running")
        session.add(run_b)
        session.commit()
        session.refresh(run_b)
        step_b = WorkflowRunStep(
            run_id=run_b.id,
            definition_id=definition_b.id,
            step_order=0,
            step_key="review",
            step_type="review_gate",
            label="Review Gate",
            status="failed",
        )
        schedule_b = WorkflowSchedule(
            project_id="project-b",
            definition_id=definition_b.id,
            name="Schedule B",
            cron_expression="0 0 * * *",
            timezone="UTC",
            next_run_at=datetime.utcnow(),
        )
        session.add(step_b)
        session.add(schedule_b)
        session.commit()
        session.refresh(step_b)
        session.refresh(schedule_b)
        session.add(WorkflowScheduleExecution(schedule_id=schedule_b.id, status="completed"))
        session.commit()
        ids = {
            "definition_a": definition_a.id,
            "definition_b": definition_b.id,
            "run_b": run_b.id,
            "step_b": step_b.id,
            "schedule_b": schedule_b.id,
        }

    app = FastAPI()
    app.include_router(workflows.router)

    def override_session():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[workflows.get_session] = override_session
    return TestClient(app, raise_server_exceptions=False), ids


def test_workflow_object_routes_require_matching_project(tmp_path):
    client, ids = _workflow_client(tmp_path)

    assert client.get(f"/workflows/runs/{ids['run_b']}").status_code == 422
    assert client.get(f"/workflows/runs/{ids['run_b']}?project_id=project-a").status_code == 404
    assert client.get(f"/workflows/runs/{ids['run_b']}/steps?project_id=project-a").status_code == 404
    assert client.post(f"/workflows/runs/{ids['run_b']}/pause?project_id=project-a").status_code == 404
    assert (
        client.post(
            f"/workflows/runs/{ids['run_b']}/steps/{ids['step_b']}/retry?project_id=project-a"
        ).status_code
        == 404
    )

    assert (
        client.get(
            f"/workflows/definitions/{ids['definition_b']}?project_id=project-a"
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/workflows/definitions/{ids['definition_b']}/duplicate?project_id=project-a"
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/workflows/schedules/{ids['schedule_b']}/run-now?project_id=project-a"
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/workflows/schedules/{ids['schedule_b']}/executions?project_id=project-a"
        ).status_code
        == 404
    )
    assert client.get(f"/workflows/runs/{ids['run_b']}?project_id=project-b").status_code == 200


def test_application_map_same_url_is_project_scoped(tmp_path):
    from orchestrator.api.models_db import ApplicationMap, Project
    from orchestrator.services.autonomous_activities import _merge_app_map_update

    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'application-map-boundary.db'}",
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        session.add(Project(id="project-a", name="Project A"))
        session.add(Project(id="project-b", name="Project B"))
        session.commit()

        row = {"url": "https://example.test/settings", "page_title": "Settings"}
        assert _merge_app_map_update(session, SimpleNamespace(project_id="project-a"), row)
        assert _merge_app_map_update(session, SimpleNamespace(project_id="project-b"), row)
        session.commit()

        rows = session.exec(select(ApplicationMap).where(ApplicationMap.url == row["url"])).all()

    assert sorted(item.project_id for item in rows) == ["project-a", "project-b"]
