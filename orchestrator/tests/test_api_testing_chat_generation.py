import asyncio
import os
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-api-tests")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture()
def api_testing_client(monkeypatch, tmp_path):
    from orchestrator.api import api_testing

    monkeypatch.setattr(api_testing, "BASE_DIR", tmp_path)
    monkeypatch.setattr(api_testing, "SPECS_DIR", tmp_path / "specs")
    monkeypatch.setattr(api_testing, "TESTS_DIR", tmp_path / "tests" / "generated")
    monkeypatch.setattr(api_testing, "RUNS_DIR", tmp_path / "runs")
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'api-testing.db'}",
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(api_testing, "engine", test_engine)
    api_testing._api_jobs.clear()

    app = FastAPI()
    app.include_router(api_testing.router)

    def override_session():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[api_testing.get_session] = override_session
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, api_testing, tmp_path
    api_testing._api_jobs.clear()


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


class _FakePlaywrightProcess:
    def __init__(self, returncode: int, output: str, stdout):
        self.returncode = returncode
        self.pid = 12345
        if output:
            stdout.write(output)
            stdout.flush()

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_direct_api_run_uses_run_scoped_playwright_artifacts(api_testing_client, monkeypatch):
    _client, api_testing, tmp_path = api_testing_client
    captured = {}

    def fake_popen(cmd, cwd, stdout, stderr, env, start_new_session):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return _FakePlaywrightProcess(0, "1 passed\n", stdout)

    monkeypatch.setattr(api_testing.subprocess, "Popen", fake_popen)

    job_id = "direct-env"
    run_id = "api-direct-env"
    api_testing._api_jobs[job_id] = {"status": "running"}

    api_testing._run_direct_test_sync(
        job_id,
        run_id,
        "tests/generated/demo.api.spec.ts",
        "demo.api.spec.ts",
        "chat-project",
    )

    run_dir = tmp_path / "runs" / run_id
    assert captured["cmd"] == [
        "npx",
        "playwright",
        "test",
        "tests/generated/demo.api.spec.ts",
        "--reporter=list,json",
        "--project",
        "chromium",
        "--timeout=120000",
    ]
    assert captured["env"]["PLAYWRIGHT_OUTPUT_DIR"] == str(run_dir / "test-results")
    assert captured["env"]["PLAYWRIGHT_HTML_REPORT"] == str(run_dir / "playwright-report")
    assert captured["env"]["PLAYWRIGHT_JSON_OUTPUT_FILE"] == str(run_dir / "test-results.json")
    assert api_testing._api_jobs[job_id]["result"]["passed"] is True


def test_direct_api_run_classifies_infrastructure_failure_and_skips_healing(api_testing_client, monkeypatch):
    _client, api_testing, _tmp_path = api_testing_client
    healer_calls = {"count": 0}

    def fake_popen(cmd, cwd, stdout, stderr, env, start_new_session):
        return _FakePlaywrightProcess(
            1,
            "Error: EACCES: permission denied, mkdir '/app/test-results'\n",
            stdout,
        )

    class FakeHealer:
        def __init__(self):
            healer_calls["count"] += 1

        async def heal_test(self, *args, **kwargs):
            return "fixed"

    fake_healer_module = types.ModuleType("workflows.native_api_healer")
    fake_healer_module.NativeApiHealer = FakeHealer

    monkeypatch.setattr(api_testing.subprocess, "Popen", fake_popen)
    monkeypatch.setitem(sys.modules, "workflows.native_api_healer", fake_healer_module)

    job_id = "direct-infra"
    api_testing._api_jobs[job_id] = {"status": "running"}

    api_testing._run_direct_test_sync(
        job_id,
        "api-direct-infra",
        "tests/generated/demo.api.spec.ts",
        "demo.api.spec.ts",
        "chat-project",
        heal_on_failure=True,
    )

    result = api_testing._api_jobs[job_id]["result"]
    assert result["passed"] is False
    assert result["category"] == "infrastructure"
    assert result["healing_attempts"] == 0
    assert healer_calls["count"] == 0


def test_direct_api_run_invokes_healer_for_assertion_failure_when_requested(api_testing_client, monkeypatch):
    _client, api_testing, _tmp_path = api_testing_client
    popen_calls = {"count": 0}
    healer_calls = {"count": 0}

    def fake_popen(cmd, cwd, stdout, stderr, env, start_new_session):
        popen_calls["count"] += 1
        if popen_calls["count"] == 1:
            return _FakePlaywrightProcess(1, "Error: expect(received).toBe(expected)\n", stdout)
        return _FakePlaywrightProcess(0, "1 passed\n", stdout)

    class FakeHealer:
        def __init__(self):
            healer_calls["count"] += 1

        async def heal_test(self, *args, **kwargs):
            return "fixed"

    fake_healer_module = types.ModuleType("workflows.native_api_healer")
    fake_healer_module.NativeApiHealer = FakeHealer

    monkeypatch.setattr(api_testing.subprocess, "Popen", fake_popen)
    monkeypatch.setitem(sys.modules, "workflows.native_api_healer", fake_healer_module)

    job_id = "direct-heal"
    api_testing._api_jobs[job_id] = {"status": "running"}

    api_testing._run_direct_test_sync(
        job_id,
        "api-direct-heal",
        "tests/generated/demo.api.spec.ts",
        "demo.api.spec.ts",
        "chat-project",
        heal_on_failure=True,
    )

    result = api_testing._api_jobs[job_id]["result"]
    assert result["passed"] is True
    assert result["healed"] is True
    assert result["healing_attempts"] == 1
    assert result["category"] is None
    assert healer_calls["count"] == 1
    assert popen_calls["count"] == 2


def test_run_direct_endpoint_defaults_to_no_healing_and_accepts_explicit_flag(api_testing_client, monkeypatch):
    client, api_testing, tmp_path = api_testing_client
    tests_dir = tmp_path / "tests" / "generated"
    tests_dir.mkdir(parents=True)
    (tests_dir / "demo.api.spec.ts").write_text("import { test } from '@playwright/test';\n", encoding="utf-8")
    calls = []

    class ImmediateLoop:
        def run_in_executor(self, executor, func, *args):
            calls.append(args)

    monkeypatch.setattr(api_testing.asyncio, "get_event_loop", lambda: ImmediateLoop())

    default_response = client.post(
        "/api-testing/run-direct",
        json={"test_path": "tests/generated/demo.api.spec.ts", "project_id": "chat-project"},
    )
    healing_response = client.post(
        "/api-testing/run-direct",
        json={
            "test_path": "tests/generated/demo.api.spec.ts",
            "project_id": "chat-project",
            "heal_on_failure": True,
        },
    )

    assert default_response.status_code == 200
    assert healing_response.status_code == 200
    assert calls[0][-1] is False
    assert calls[1][-1] is True


def test_import_openapi_accepts_method_filter_mode_and_base_url(api_testing_client, monkeypatch):
    client, api_testing, _tmp_path = api_testing_client

    async def fake_import(job_id: str, url: str, base_url, feature_filter, method_filter, mode: str, project_id: str):
        api_testing._api_jobs[job_id] = {
            "status": "completed",
            "message": "fake import complete",
            "result": {
                "plan_path": "specs/generated/api/openapi-plan-post.md",
                "spec_paths": ["specs/generated/api/post-operations.md"],
                "test_paths": ["tests/generated/openapi-post-operations.api.spec.ts"],
                "matched_operations": 1,
                "skipped_operations": 2,
                "warnings": [],
                "selected_methods": method_filter,
                "mode": mode,
                "base_url": base_url,
                "feature_filter": feature_filter,
                "project_id": project_id,
            },
            "project_id": project_id,
        }

    monkeypatch.setattr(api_testing, "_run_import_openapi", fake_import)

    response = client.post(
        "/api-testing/import-openapi",
        json={
            "url": "https://example.test/openapi.json",
            "base_url": "http://localhost:8001",
            "feature_filter": "orders",
            "method_filter": ["POST"],
            "mode": "plan_and_tests",
            "project_id": "chat-project",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["job_id"]
    assert data["status"] == "running"

    job = api_testing._api_jobs[data["job_id"]]
    assert job["status"] in {"running", "completed"}
    assert job["project_id"] == "chat-project"


@pytest.mark.parametrize(
    ("payload_mode", "expected_mode"),
    [
        (pytest.param("__missing__", "plan_and_tests", id="missing")),
        (None, "plan_and_tests"),
        ("", "plan_and_tests"),
        ("   ", "plan_and_tests"),
        ("evidence_specs", "evidence_specs"),
        ("plan_only", "plan_only"),
    ],
)
def test_import_openapi_normalizes_supported_modes(api_testing_client, monkeypatch, payload_mode, expected_mode):
    client, api_testing, _tmp_path = api_testing_client
    captured_calls = []

    async def fake_import(job_id: str, url: str, base_url, feature_filter, method_filter, mode: str, project_id: str):
        captured_calls.append(
            {
                "job_id": job_id,
                "url": url,
                "base_url": base_url,
                "feature_filter": feature_filter,
                "method_filter": method_filter,
                "mode": mode,
                "project_id": project_id,
            }
        )

    monkeypatch.setattr(api_testing, "_run_import_openapi", fake_import)

    payload = {
        "url": "https://example.test/openapi.json",
        "base_url": "http://localhost:8001",
        "project_id": "chat-project",
    }
    if payload_mode != "__missing__":
        payload["mode"] = payload_mode

    response = client.post("/api-testing/import-openapi", json=payload)

    assert response.status_code == 200
    assert captured_calls
    assert captured_calls[0]["mode"] == expected_mode
    assert captured_calls[0]["project_id"] == "chat-project"


def test_import_openapi_rejects_invalid_mode_with_allowed_modes(api_testing_client):
    client, _api_testing, _tmp_path = api_testing_client

    response = client.post(
        "/api-testing/import-openapi",
        json={
            "url": "https://example.test/openapi.json",
            "mode": "legacy_import",
        },
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "legacy_import" in detail
    assert "evidence_specs" in detail
    assert "plan_only" in detail
    assert "tests_only" in detail
    assert "plan_and_tests" in detail


def test_import_openapi_schema_defaults_to_plan_and_tests(api_testing_client):
    client, _api_testing, _tmp_path = api_testing_client

    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    mode_schema = schema["components"]["schemas"]["ImportOpenApiRequest"]["properties"]["mode"]
    assert mode_schema["default"] == "plan_and_tests"


def test_openapi_import_history_persists_job_id(api_testing_client, monkeypatch):
    client, api_testing, _tmp_path = api_testing_client
    from orchestrator.api.models_db import OpenApiImportHistory
    from workflows import openapi_processor

    class FakeResult:
        needs_input = False
        base_url = "https://api.example.test"
        missing_fields = []
        test_paths = ["tests/generated/openapi-users.api.spec.ts"]
        spec_paths = ["specs/generated/api/users.md"]
        plan_path = "specs/generated/api/openapi-plan.md"
        evidence_paths = []
        matched_operations = 1
        executed_operations = 0
        blocked_operations = []
        failed_operations = []
        skipped_operations = 0
        chunk_count = 1
        recommended_mode = "plan_and_tests"
        recommended_next_action = "Run generated API tests."
        warnings = []
        diagnostics = {}

        def as_dict(self):
            return {
                "base_url": self.base_url,
                "spec_paths": self.spec_paths,
                "test_paths": self.test_paths,
                "matched_operations": self.matched_operations,
            }

    class FakeProcessor:
        def __init__(self, project_id: str):
            self.project_id = project_id

        async def process_import(self, *args, **kwargs):
            return FakeResult()

    monkeypatch.setattr(openapi_processor, "OpenApiProcessor", FakeProcessor)

    asyncio.run(
        api_testing._run_import_openapi(
            "job-persisted",
            "https://api.example.test/openapi.json",
            "https://api.example.test",
            None,
            None,
            "plan_and_tests",
            "chat-project",
        )
    )

    with Session(api_testing.engine) as session:
        records = session.exec(
            api_testing.select(OpenApiImportHistory).where(OpenApiImportHistory.job_id == "job-persisted")
        ).all()

    assert len(records) == 1
    assert records[0].status == "completed"
    assert api_testing._api_jobs["job-persisted"]["history_id"] == records[0].id


def test_import_history_reconciles_stale_running_rows(api_testing_client):
    client, api_testing, _tmp_path = api_testing_client
    from orchestrator.api.models_db import OpenApiImportHistory

    stale_created_at = datetime.utcnow() - timedelta(seconds=api_testing.OPENAPI_IMPORT_RUNNING_TTL_SECONDS + 60)
    fresh_created_at = datetime.utcnow()
    with Session(api_testing.engine) as session:
        session.add(
            OpenApiImportHistory(
                id="oai-stale",
                job_id="stale-job",
                project_id="chat-project",
                source_type="url",
                source_url="https://example.test/stale-openapi.json",
                status="running",
                created_at=stale_created_at,
            )
        )
        session.add(
            OpenApiImportHistory(
                id="oai-fresh",
                job_id="fresh-job",
                project_id="chat-project",
                source_type="url",
                source_url="https://example.test/fresh-openapi.json",
                status="running",
                created_at=fresh_created_at,
            )
        )
        session.commit()

    response = client.get("/api-testing/import-history?project_id=chat-project")

    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert items["oai-stale"]["status"] == "failed"
    assert items["oai-stale"]["error_message"] == api_testing.OPENAPI_IMPORT_EXPIRED_MESSAGE
    assert items["oai-fresh"]["status"] == "running"


def test_get_job_status_falls_back_to_import_history(api_testing_client):
    client, api_testing, _tmp_path = api_testing_client
    from orchestrator.api.models_db import OpenApiImportHistory

    with Session(api_testing.engine) as session:
        session.add(
            OpenApiImportHistory(
                id="oai-complete",
                job_id="expired-job",
                project_id="chat-project",
                source_type="url",
                source_url="https://example.test/openapi.json",
                base_url="https://example.test",
                status="completed",
                files_generated=1,
                spec_paths_json='["specs/generated/api/users.md"]',
                test_paths_json='["tests/generated/openapi-users.api.spec.ts"]',
                matched_operations=2,
                completed_at=datetime.utcnow(),
            )
        )
        session.commit()

    response = client.get("/api-testing/jobs/expired-job")

    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "expired-job"
    assert data["status"] == "completed"
    assert data["type"] == "openapi_import"
    assert data["result"]["history_id"] == "oai-complete"
    assert data["result"]["spec_paths"] == ["specs/generated/api/users.md"]


def test_get_job_status_expires_stale_import_history(api_testing_client):
    client, api_testing, _tmp_path = api_testing_client
    from orchestrator.api.models_db import OpenApiImportHistory

    with Session(api_testing.engine) as session:
        session.add(
            OpenApiImportHistory(
                id="oai-expired-job",
                job_id="expired-running-job",
                project_id="chat-project",
                source_type="url",
                source_url="https://example.test/openapi.json",
                status="running",
                created_at=datetime.utcnow() - timedelta(seconds=api_testing.OPENAPI_IMPORT_RUNNING_TTL_SECONDS + 60),
            )
        )
        session.commit()

    response = client.get("/api-testing/jobs/expired-running-job")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["message"] == api_testing.OPENAPI_IMPORT_EXPIRED_MESSAGE
