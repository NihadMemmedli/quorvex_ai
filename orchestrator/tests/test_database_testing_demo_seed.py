import os
import shutil
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-database-demo")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture()
def database_testing_client():
    from orchestrator.api.database_testing import router

    app = FastAPI()
    app.include_router(router)

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture()
def demo_seed(monkeypatch):
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import seed_database_testing_demo as seed

    seed.init_db()

    suffix = uuid4().hex[:8]
    project_id = f"db-demo-{suffix}"
    conn_id = f"dbc-{suffix}"
    run_id = f"dbt-{suffix}"
    spec_name = f"demo-shop-quality-{suffix}.md"

    monkeypatch.setattr(seed, "DEMO_CONNECTION_ID", conn_id)
    monkeypatch.setattr(seed, "DEMO_RUN_ID", run_id)
    monkeypatch.setattr(seed, "DEMO_SPEC_NAME", spec_name)

    yield seed, project_id, conn_id, run_id, spec_name

    from orchestrator.api.db import engine
    from orchestrator.api.models_db import DbConnection, DbTestCheck, DbTestRun, Project

    with Session(engine) as session:
        checks = session.exec(select(DbTestCheck).where(DbTestCheck.run_id == run_id)).all()
        for check in checks:
            session.delete(check)
        run = session.get(DbTestRun, run_id)
        if run:
            session.delete(run)
        conn = session.get(DbConnection, conn_id)
        if conn:
            session.delete(conn)
        project = session.get(Project, project_id)
        if project:
            session.delete(project)
        session.commit()

    spec_dir = Path(__file__).resolve().parent.parent.parent / "specs" / project_id
    shutil.rmtree(spec_dir, ignore_errors=True)


def test_database_demo_seed_creates_endpoint_visible_content(database_testing_client, demo_seed):
    seed, project_id, conn_id, run_id, spec_name = demo_seed
    result = seed.ensure_demo_platform_data(
        project_id=project_id,
        profile=seed.ConnectionProfile(
            host="localhost",
            port=5434,
            database="playwright_agent",
            username="postgres",
            password="postgres",
        ),
    )

    assert result["connection_id"] == conn_id
    assert result["run_id"] == run_id

    connections = database_testing_client.get(f"/database-testing/connections?project_id={project_id}")
    assert connections.status_code == 200
    assert [item["id"] for item in connections.json()] == [conn_id]
    assert connections.json()[0]["password"] == "********"

    specs = database_testing_client.get(f"/database-testing/specs?project_id={project_id}")
    assert specs.status_code == 200
    assert any(item["name"] == spec_name for item in specs.json())

    runs = database_testing_client.get(f"/database-testing/runs?project_id={project_id}")
    assert runs.status_code == 200
    run_rows = runs.json()["runs"]
    assert len(run_rows) == 1
    assert run_rows[0]["id"] == run_id
    assert run_rows[0]["failed_checks"] == 4
    assert run_rows[0]["pass_rate"] == 50.0

    omitted_checks = database_testing_client.get(f"/database-testing/runs/{run_id}/checks")
    assert omitted_checks.status_code == 422

    wrong_project_checks = database_testing_client.get(
        f"/database-testing/runs/{run_id}/checks?project_id=wrong-project"
    )
    assert wrong_project_checks.status_code == 404

    checks = database_testing_client.get(f"/database-testing/runs/{run_id}/checks?project_id={project_id}")
    assert checks.status_code == 200
    assert len(checks.json()) == 8
    assert any(check["status"] == "failed" and check["sample_data"] for check in checks.json())


def test_database_demo_seed_is_idempotent(database_testing_client, demo_seed):
    seed, project_id, conn_id, run_id, _spec_name = demo_seed
    profile = seed.ConnectionProfile(
        host="localhost",
        port=5434,
        database="playwright_agent",
        username="postgres",
        password="postgres",
    )

    seed.ensure_demo_platform_data(project_id=project_id, profile=profile)
    seed.ensure_demo_platform_data(project_id=project_id, profile=profile)

    connections = database_testing_client.get(f"/database-testing/connections?project_id={project_id}")
    runs = database_testing_client.get(f"/database-testing/runs?project_id={project_id}")
    checks = database_testing_client.get(f"/database-testing/runs/{run_id}/checks?project_id={project_id}")

    assert connections.status_code == 200
    assert len(connections.json()) == 1
    assert connections.json()[0]["id"] == conn_id
    assert runs.status_code == 200
    assert len(runs.json()["runs"]) == 1
    assert checks.status_code == 200
    assert len(checks.json()) == 8
