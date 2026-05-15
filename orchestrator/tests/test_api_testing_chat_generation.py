import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-api-tests")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture()
def api_testing_client(monkeypatch, tmp_path):
    from orchestrator.api import api_testing

    monkeypatch.setattr(api_testing, "BASE_DIR", tmp_path)
    monkeypatch.setattr(api_testing, "SPECS_DIR", tmp_path / "specs")
    monkeypatch.setattr(api_testing, "TESTS_DIR", tmp_path / "tests" / "generated")
    api_testing._api_jobs.clear()

    app = FastAPI()
    app.include_router(api_testing.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, api_testing, tmp_path


def test_create_and_generate_api_test_creates_project_spec_and_job(api_testing_client, monkeypatch):
    client, api_testing, tmp_path = api_testing_client

    async def fake_generate(job_id: str, spec_path: str, project_id: str):
        api_testing._api_jobs[job_id] = {
            "status": "completed",
            "message": "fake generation complete",
            "result": {"test_path": "tests/generated/fake.api.spec.ts"},
            "project_id": project_id,
        }

    monkeypatch.setattr(api_testing, "_run_generate_test", fake_generate)

    response = client.post(
        "/api-testing/create-and-generate",
        json={
            "name": "chat-demo-api.md",
            "project_id": "chat-project",
            "content": "# Test: Chat Demo API\n\n## Base URL: https://httpbin.org\n\n## Steps\n1. GET /get\n",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "chat-demo-api.md"
    assert data["path"] == "specs/chat-project/api/chat-demo-api.md"
    assert data["job_id"]
    assert data["status"] == "running"

    created = tmp_path / "specs" / "chat-project" / "api" / "chat-demo-api.md"
    assert created.exists()
    assert "## Type: API" in created.read_text()


def test_generate_api_test_finds_project_scoped_spec(api_testing_client, monkeypatch):
    client, api_testing, tmp_path = api_testing_client

    spec_dir = tmp_path / "specs" / "chat-project" / "api"
    spec_dir.mkdir(parents=True)
    (spec_dir / "project-api.md").write_text(
        "# Test: Project API\n\n## Type: API\n## Base URL: https://httpbin.org\n\n## Steps\n1. GET /get\n",
        encoding="utf-8",
    )

    async def fake_generate(job_id: str, spec_path: str, project_id: str):
        api_testing._api_jobs[job_id] = {
            "status": "completed",
            "message": "fake generation complete",
            "result": {"spec_path": spec_path},
            "project_id": project_id,
        }

    monkeypatch.setattr(api_testing, "_run_generate_test", fake_generate)

    response = client.post(
        "/api-testing/generate",
        json={"spec_name": "project-api.md", "project_id": "chat-project"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["job_id"]
    assert data["status"] == "running"


def test_generated_tests_list_includes_summary(api_testing_client):
    client, _api_testing, tmp_path = api_testing_client

    tests_dir = tmp_path / "tests" / "generated" / "chat-project"
    tests_dir.mkdir(parents=True)
    (tests_dir / "demo.api.spec.ts").write_text(
        "import { test, expect } from '@playwright/test';\n\ntest('demo one', async () => {});\n",
        encoding="utf-8",
    )

    response = client.get("/api-testing/generated-tests?project_id=chat-project")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["summary"]["total_files"] == 1
    assert data["summary"]["total_tests"] == 1
    assert data["summary"]["not_run"] == 1


def test_generated_tests_summary_endpoint_keeps_existing_shape(api_testing_client):
    client, _api_testing, tmp_path = api_testing_client

    tests_dir = tmp_path / "tests" / "generated" / "chat-project"
    tests_dir.mkdir(parents=True)
    (tests_dir / "demo.api.spec.ts").write_text(
        "import { test } from '@playwright/test';\n\ntest('demo one', async () => {});\n",
        encoding="utf-8",
    )

    response = client.get("/api-testing/generated-tests/summary?project_id=chat-project")

    assert response.status_code == 200
    assert response.json() == {
        "total_files": 1,
        "total_tests": 1,
        "passed": 0,
        "failed": 0,
        "not_run": 1,
    }
