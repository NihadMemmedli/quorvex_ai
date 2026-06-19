import asyncio
import os
import sys
import types
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-browser-auth-tests")
os.environ.setdefault("REQUIRE_AUTH", "false")

if "slowapi" not in sys.modules:
    slowapi = types.ModuleType("slowapi")
    slowapi_errors = types.ModuleType("slowapi.errors")
    slowapi_util = types.ModuleType("slowapi.util")

    class _TestLimiter:
        def __init__(self, *args, **kwargs):
            self._storage = types.SimpleNamespace(expirations={})

        def limit(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    class _TestRateLimitExceeded(Exception):
        retry_after = 60

    slowapi.Limiter = _TestLimiter
    slowapi_errors.RateLimitExceeded = _TestRateLimitExceeded
    slowapi_util.get_remote_address = lambda request: "test-client"
    sys.modules["slowapi"] = slowapi
    sys.modules["slowapi.errors"] = slowapi_errors
    sys.modules["slowapi.util"] = slowapi_util

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel

from orchestrator.api.credentials import set_project_credential
from orchestrator.api.db import _run_migrations, engine
from orchestrator.api.models_db import BrowserAuthSession, Project
from orchestrator.services.browser_auth_sessions import (
    BROWSER_AUTH_CAPTURE_VERSION,
    BrowserAuthSessionError,
    create_browser_auth_session,
    decrypt_storage_state,
    encrypt_storage_state,
    refresh_browser_auth_session,
    resolve_browser_auth_for_run,
    validate_browser_auth_session,
)
from orchestrator.services.temporal_client import TemporalWorkflowStart
from orchestrator.utils.agent_runner import AgentResult


def _create_project() -> str:
    SQLModel.metadata.create_all(engine)
    _run_migrations()
    project_id = f"browser-auth-{uuid4().hex}"
    with Session(engine) as session:
        session.add(Project(id=project_id, name=f"Browser Auth {uuid4().hex}"))
        session.commit()
    return project_id


def _create_uuid_project() -> str:
    SQLModel.metadata.create_all(engine)
    _run_migrations()
    project_id = str(uuid4())
    with Session(engine) as session:
        session.add(Project(id=project_id, name=f"Browser Auth UUID {uuid4().hex}"))
        session.commit()
    return project_id


def _create_active_browser_auth_session(
    project_id: str,
    *,
    is_default: bool = False,
    status: str = "active",
    state: dict | None = None,
) -> str:
    state = state or {
        "cookies": [
            {
                "name": "sid",
                "value": f"cookie-{uuid4().hex}",
                "domain": "example.com",
                "path": "/",
            }
        ],
        "origins": [],
    }
    with Session(engine) as session:
        row = BrowserAuthSession(
            project_id=project_id,
            name=f"App Login {uuid4().hex[:6]}",
            base_url="https://example.com",
            login_url="https://example.com/login",
            username_key="LOGIN_USERNAME",
            password_key="LOGIN_PASSWORD",
            storage_state_json_encrypted=encrypt_storage_state(state),
            status=status,
            is_default=is_default,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def _patch_main_datetime(monkeypatch, main_module, offset_seconds: int) -> None:
    fixed_now = datetime(2026, 1, 1, 12, 0, 0) + timedelta(
        seconds=offset_seconds + int(uuid4().hex[:8], 16) % 10_000_000
    )

    class FixedDateTime(datetime):
        @classmethod
        def utcnow(cls):
            return fixed_now

    monkeypatch.setattr(main_module, "datetime", FixedDateTime)


def test_storage_state_encryption_round_trip():
    state = {
        "cookies": [
            {"name": "session", "value": "secret", "domain": "example.com", "path": "/"}
        ],
        "origins": [],
    }

    encrypted = encrypt_storage_state(state)

    assert encrypted != str(state)
    assert decrypt_storage_state(encrypted) == state


def test_resolve_browser_auth_for_run_writes_decrypted_state(tmp_path):
    project_id = _create_project()
    state = {
        "cookies": [
            {"name": "sid", "value": "abc", "domain": "example.com", "path": "/"}
        ],
        "origins": [],
    }

    with Session(engine) as session:
        row = BrowserAuthSession(
            project_id=project_id,
            name="Default",
            base_url="https://example.com",
            login_url="https://example.com/login",
            username_key="LOGIN_USERNAME",
            password_key="LOGIN_PASSWORD",
            storage_state_json_encrypted=encrypt_storage_state(state),
            status="active",
            is_default=True,
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        resolved = resolve_browser_auth_for_run(
            session, project_id, run_dir=tmp_path, use_default=True
        )

    assert resolved is not None
    assert resolved.storage_state_path.exists()
    assert "abc" in resolved.storage_state_path.read_text()


def test_create_run_resolves_explicit_browser_auth_session_into_temporal_payload(
    tmp_path, monkeypatch
):
    from orchestrator.api import main as main_module
    from orchestrator.api.main import app

    project_id = _create_project()
    auth_session_id = _create_active_browser_auth_session(
        project_id,
        state={
            "cookies": [
                {
                    "name": "sid",
                    "value": "single-run",
                    "domain": "example.com",
                    "path": "/",
                }
            ],
            "origins": [],
        },
    )
    specs_dir = tmp_path / "specs"
    runs_dir = tmp_path / "runs"
    specs_dir.mkdir()
    runs_dir.mkdir()
    (specs_dir / "checkout.md").write_text(
        "# Checkout\n\n## Steps\n1. Open https://example.com"
    )
    _patch_main_datetime(monkeypatch, main_module, 1)
    monkeypatch.setattr(main_module, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(main_module, "RUNS_DIR", runs_dir)

    started_payloads: list[dict] = []

    async def fake_start_test_run_workflow(run_id, payload, *, task_queue=None):
        started_payloads.append(payload)
        return TemporalWorkflowStart(
            workflow_id=f"test-run-{run_id}", run_id="temporal-run"
        )

    monkeypatch.setattr(
        "orchestrator.services.temporal_client.start_test_run_workflow",
        fake_start_test_run_workflow,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/runs",
            json={
                "spec_name": "checkout.md",
                "project_id": project_id,
                "browser_auth_session_id": auth_session_id,
            },
        )

    assert response.status_code == 200, response.text
    assert len(started_payloads) == 1
    storage_state_path = Path(started_payloads[0]["storage_state_path"])
    assert storage_state_path.parent.parent == runs_dir
    assert "single-run" in storage_state_path.read_text()
    assert (
        started_payloads[0]["browser_auth_context"]["browser_auth_session_id"]
        == auth_session_id
    )
    assert started_payloads[0]["browser_auth_context"]["storage_state_attached"] is True
    body = response.json()
    assert body["browser_auth"]["browser_auth_session_id"] == auth_session_id

    with TestClient(app, raise_server_exceptions=False) as client:
        detail_response = client.get(f"/runs/{body['id']}")
        list_response = client.get("/runs", params={"project_id": project_id})

    assert detail_response.status_code == 200, detail_response.text
    assert (
        detail_response.json()["browser_auth"]["browser_auth_session_id"]
        == auth_session_id
    )
    assert list_response.status_code == 200, list_response.text
    assert (
        list_response.json()["runs"][0]["browser_auth"]["browser_auth_session_id"]
        == auth_session_id
    )


def test_create_run_without_browser_auth_leaves_temporal_payload_unchanged(
    tmp_path, monkeypatch
):
    from orchestrator.api import main as main_module
    from orchestrator.api.main import app

    project_id = _create_project()
    specs_dir = tmp_path / "specs"
    runs_dir = tmp_path / "runs"
    specs_dir.mkdir()
    runs_dir.mkdir()
    (specs_dir / "public.md").write_text(
        "# Public\n\n## Steps\n1. Open https://example.com"
    )
    _patch_main_datetime(monkeypatch, main_module, 2)
    monkeypatch.setattr(main_module, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(main_module, "RUNS_DIR", runs_dir)

    started_payloads: list[dict] = []

    async def fake_start_test_run_workflow(run_id, payload, *, task_queue=None):
        started_payloads.append(payload)
        return TemporalWorkflowStart(
            workflow_id=f"test-run-{run_id}", run_id="temporal-run"
        )

    monkeypatch.setattr(
        "orchestrator.services.temporal_client.start_test_run_workflow",
        fake_start_test_run_workflow,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/runs", json={"spec_name": "public.md", "project_id": project_id}
        )

    assert response.status_code == 200, response.text
    assert len(started_payloads) == 1
    assert "storage_state_path" not in started_payloads[0]
    assert started_payloads[0]["browser_auth_context"]["mode"] == "none"
    assert (
        started_payloads[0]["browser_auth_context"]["storage_state_attached"] is False
    )


def test_login_spec_forces_no_browser_auth_even_when_session_selected(
    tmp_path, monkeypatch
):
    from orchestrator.api import main as main_module
    from orchestrator.api.main import app

    project_id = _create_project()
    auth_session_id = _create_active_browser_auth_session(
        project_id,
        state={
            "cookies": [
                {
                    "name": "sid",
                    "value": "preauth",
                    "domain": "example.com",
                    "path": "/",
                }
            ],
            "origins": [],
        },
    )
    specs_dir = tmp_path / "specs"
    runs_dir = tmp_path / "runs"
    specs_dir.mkdir()
    runs_dir.mkdir()
    (specs_dir / "login.md").write_text(
        "# TC-001 Login With Valid Credentials\n\n## Steps\n1. Open https://example.com/login"
    )
    _patch_main_datetime(monkeypatch, main_module, 4)
    monkeypatch.setattr(main_module, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(main_module, "RUNS_DIR", runs_dir)

    started_payloads: list[dict] = []

    async def fake_start_test_run_workflow(run_id, payload, *, task_queue=None):
        started_payloads.append(payload)
        return TemporalWorkflowStart(
            workflow_id=f"test-run-{run_id}", run_id="temporal-run"
        )

    monkeypatch.setattr(
        "orchestrator.services.temporal_client.start_test_run_workflow",
        fake_start_test_run_workflow,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/runs",
            json={
                "spec_name": "login.md",
                "project_id": project_id,
                "browser_auth_session_id": auth_session_id,
            },
        )

    assert response.status_code == 200, response.text
    assert "storage_state_path" not in started_payloads[0]
    auth_context = started_payloads[0]["browser_auth_context"]
    assert auth_context["mode"] == "none"
    assert auth_context["requested_browser_auth_session_id"] == auth_session_id
    assert "ignored" in auth_context["auth_conflict_warning"]


def test_bulk_run_writes_one_storage_state_file_per_run_for_project_default(
    tmp_path, monkeypatch
):
    from orchestrator.api import main as main_module
    from orchestrator.api.main import app
    from orchestrator.services import batch_executor

    project_id = _create_project()
    _create_active_browser_auth_session(
        project_id,
        is_default=True,
        state={
            "cookies": [
                {
                    "name": "sid",
                    "value": "bulk-run",
                    "domain": "example.com",
                    "path": "/",
                }
            ],
            "origins": [],
        },
    )
    specs_dir = tmp_path / "specs"
    runs_dir = tmp_path / "runs"
    specs_dir.mkdir()
    runs_dir.mkdir()
    (specs_dir / "one.md").write_text("# One\n\n## Steps\n1. Open https://example.com")
    (specs_dir / "two.md").write_text("# Two\n\n## Steps\n1. Open https://example.com")
    monkeypatch.setattr(main_module, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(batch_executor, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(batch_executor, "RUNS_DIR", runs_dir)

    started_payloads: list[dict] = []

    async def fake_start_test_run_workflow(run_id, payload, *, task_queue=None):
        started_payloads.append(payload)
        return TemporalWorkflowStart(
            workflow_id=f"test-run-{run_id}", run_id="temporal-run"
        )

    monkeypatch.setattr(
        "orchestrator.services.temporal_client.start_test_run_workflow",
        fake_start_test_run_workflow,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/runs/bulk",
            json={
                "spec_names": ["one.md", "two.md"],
                "project_id": project_id,
                "use_project_default_browser_auth": True,
            },
        )

    assert response.status_code == 200, response.text
    assert len(started_payloads) == 2
    storage_paths = [
        Path(payload["storage_state_path"]) for payload in started_payloads
    ]
    assert len({path for path in storage_paths}) == 2
    assert all(path.parent.parent == runs_dir for path in storage_paths)
    assert all("bulk-run" in path.read_text() for path in storage_paths)


def test_bulk_run_rejects_missing_test_data_before_temporal_start(
    tmp_path, monkeypatch
):
    from orchestrator.api import main as main_module
    from orchestrator.api.main import app
    from orchestrator.services import batch_executor

    project_id = _create_project()
    specs_dir = tmp_path / "specs"
    runs_dir = tmp_path / "runs"
    specs_dir.mkdir()
    runs_dir.mkdir()
    (specs_dir / "needs-data.md").write_text(
        '# Needs Data\n\n@testdata "missing.ref"\n\n1. Open https://example.com'
    )
    monkeypatch.setattr(batch_executor, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(batch_executor, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(main_module, "RUNS_DIR", runs_dir)

    async def fail_if_temporal_starts(run_id, payload, *, task_queue=None):
        raise AssertionError("Temporal should not start for unresolved test data")

    monkeypatch.setattr(
        "orchestrator.services.temporal_client.start_test_run_workflow",
        fail_if_temporal_starts,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/runs/bulk",
            json={
                "spec_names": ["needs-data.md"],
                "project_id": project_id,
                "test_data_refs": ["missing.ref"],
            },
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "test_data_refs_unresolved"
    assert detail["missing_test_data"] == [
        {"ref": "missing.ref", "reason": "dataset_not_found"}
    ]
    assert list(runs_dir.iterdir()) == []


def test_bulk_run_discovers_generated_code_test_data_refs_and_propagates_payload(
    tmp_path, monkeypatch
):
    from orchestrator.api import main as main_module
    from orchestrator.api.main import app
    from orchestrator.api.models_db import TestDataItem, TestDataSet
    from orchestrator.services import batch_executor
    from orchestrator.services.test_data_resolver import prepare_test_data_item_storage

    project_id = _create_project()
    specs_dir = tmp_path / "specs"
    runs_dir = tmp_path / "runs"
    generated_dir = tmp_path / "generated"
    specs_dir.mkdir()
    runs_dir.mkdir()
    generated_dir.mkdir()
    spec_path = specs_dir / "generated-data.md"
    code_path = generated_dir / "generated-data.spec.ts"
    spec_path.write_text("# Generated Data\n\n1. Open https://example.com")
    code_path.write_text("testData.get('auth-users.valid-admin');")

    storage = prepare_test_data_item_storage(
        data={"email": "admin@example.com", "password": "secret-pass"},
        sensitive_fields=["password"],
    )
    with Session(engine) as session:
        dataset = TestDataSet(
            project_id=project_id, key="auth-users", name="Auth Users", status="active"
        )
        session.add(dataset)
        session.commit()
        session.refresh(dataset)
        item = TestDataItem(
            dataset_id=dataset.id,
            key="valid-admin",
            name="Valid Admin",
            status="active",
            format="json",
        )
        item.data = storage["data"]
        item.sensitive_fields = storage["sensitive_fields"]
        item.encrypted_values = storage["encrypted_values"]
        session.add(item)
        session.commit()

    monkeypatch.setattr(batch_executor, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(batch_executor, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(main_module, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(
        batch_executor,
        "_get_try_code_path",
        lambda _spec_name, _spec_path: str(code_path),
    )

    started_payloads: list[dict] = []

    async def fake_start_test_run_workflow(run_id, payload, *, task_queue=None):
        started_payloads.append(payload)
        return TemporalWorkflowStart(
            workflow_id=f"test-run-{run_id}", run_id="temporal-run"
        )

    monkeypatch.setattr(
        "orchestrator.services.temporal_client.start_test_run_workflow",
        fake_start_test_run_workflow,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/runs/bulk",
            json={"spec_names": ["generated-data.md"], "project_id": project_id},
        )

    assert response.status_code == 200, response.text
    assert started_payloads[0]["test_data_refs"] == ["auth-users.valid-admin"]
    assert "secret-pass" not in str(started_payloads[0])


def test_run_rejects_cross_project_browser_auth_session_before_temporal_start(
    tmp_path, monkeypatch
):
    from orchestrator.api import main as main_module
    from orchestrator.api.main import app

    project_id = _create_project()
    other_project_id = _create_project()
    auth_session_id = _create_active_browser_auth_session(other_project_id)
    specs_dir = tmp_path / "specs"
    runs_dir = tmp_path / "runs"
    specs_dir.mkdir()
    runs_dir.mkdir()
    (specs_dir / "private.md").write_text(
        "# Private\n\n## Steps\n1. Open https://example.com"
    )
    _patch_main_datetime(monkeypatch, main_module, 3)
    monkeypatch.setattr(main_module, "SPECS_DIR", specs_dir)
    monkeypatch.setattr(main_module, "RUNS_DIR", runs_dir)

    async def fail_if_temporal_starts(run_id, payload, *, task_queue=None):
        raise AssertionError("Temporal should not start for invalid browser auth")

    monkeypatch.setattr(
        "orchestrator.services.temporal_client.start_test_run_workflow",
        fail_if_temporal_starts,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/runs",
            json={
                "spec_name": "private.md",
                "project_id": project_id,
                "browser_auth_session_id": auth_session_id,
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Browser auth session was not found"


def test_browser_auth_session_api_lifecycle():
    from orchestrator.api.main import app

    project_id = _create_project()
    state = {"cookies": [], "origins": []}

    with TestClient(app, raise_server_exceptions=False) as client:
        create_response = client.post(
            f"/projects/{project_id}/browser-auth-sessions",
            json={
                "name": "App login",
                "base_url": "https://example.com",
                "login_url": "https://example.com/login",
                "username_key": "LOGIN_USERNAME",
                "password_key": "LOGIN_PASSWORD",
                "make_default": True,
                "storage_state": state,
            },
        )
        assert create_response.status_code == 201, create_response.text
        created = create_response.json()
        assert created["status"] == "active"
        assert created["is_default"] is True
        assert "storage_state" not in created
        session_id = created["id"]

        list_response = client.get(f"/projects/{project_id}/browser-auth-sessions")
        assert list_response.status_code == 200, list_response.text
        listed = list_response.json()["sessions"]
        assert any(item["id"] == session_id for item in listed)

        validate_response = client.post(
            f"/projects/{project_id}/browser-auth-sessions/{session_id}/validate"
        )
        assert validate_response.status_code == 200, validate_response.text
        assert validate_response.json()["status"] == "active"

        default_response = client.patch(
            f"/projects/{project_id}/browser-auth-sessions/{session_id}/default"
        )
        assert default_response.status_code == 200, default_response.text
        assert default_response.json()["is_default"] is True

        delete_response = client.delete(
            f"/projects/{project_id}/browser-auth-sessions/{session_id}"
        )
        assert delete_response.status_code == 200, delete_response.text
        assert delete_response.json()["status"] == "revoked"


def test_validate_browser_auth_session_does_not_require_llm_key(monkeypatch):
    project_id = _create_project()
    state = {
        "cookies": [
            {"name": "sid", "value": "abc", "domain": "example.com", "path": "/"}
        ],
        "origins": [],
    }
    for key in (
        "QUORVEX_LLM_API_KEY",
        "QUORVEX_LLM_API_KEYS",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "ZAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    with Session(engine) as session:
        row = BrowserAuthSession(
            project_id=project_id,
            name="Stored login",
            base_url="https://example.com",
            login_url="https://example.com/login",
            username_key="LOGIN_USERNAME",
            password_key="LOGIN_PASSWORD",
            storage_state_json_encrypted=encrypt_storage_state(state),
            status="active",
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        validated = validate_browser_auth_session(session, project_id, row.id)

    assert validated.status == "active"
    assert validated.failure_reason is None
    assert validated.last_validated_at is not None


def test_browser_auth_session_api_round_trips_advanced_capture_settings():
    from orchestrator.api.main import app

    project_id = _create_project()
    state = {"cookies": [], "origins": []}

    payload = {
        "name": "Advanced login",
        "base_url": "https://example.com",
        "login_url": "https://example.com/login",
        "username_key": "LOGIN_USERNAME",
        "password_key": "LOGIN_PASSWORD",
        "username_selector": "#email",
        "password_selector": "#password",
        "username_continue_selector": "button.next",
        "submit_selector": "button.sign-in",
        "success_url_pattern": "/dashboard$",
        "storage_state": state,
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        create_response = client.post(
            f"/projects/{project_id}/browser-auth-sessions", json=payload
        )
        list_response = client.get(f"/projects/{project_id}/browser-auth-sessions")

    assert create_response.status_code == 201, create_response.text
    created = create_response.json()
    for key in [
        "username_selector",
        "password_selector",
        "username_continue_selector",
        "submit_selector",
        "success_url_pattern",
    ]:
        assert created[key] == payload[key]

    assert list_response.status_code == 200, list_response.text
    listed = list_response.json()["sessions"]
    assert listed[0]["username_selector"] == "#email"
    assert listed[0]["success_url_pattern"] == "/dashboard$"


def test_browser_auth_session_api_accepts_new_uuid_project():
    from orchestrator.api.main import app

    project_id = _create_uuid_project()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/projects/{project_id}/browser-auth-sessions",
            json={
                "name": "UUID app login",
                "base_url": "https://example.com",
                "login_url": "https://example.com/login",
                "username_key": "LOGIN_USERNAME",
                "password_key": "LOGIN_PASSWORD",
                "make_default": True,
                "storage_state": {"cookies": [], "origins": []},
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["project_id"] == project_id
    assert body["status"] == "active"
    assert body["is_default"] is True


def test_browser_auth_session_missing_project_returns_project_not_found():
    from orchestrator.api.main import app

    SQLModel.metadata.create_all(engine)
    missing_project_id = f"missing-{uuid4().hex}"

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/projects/{missing_project_id}/browser-auth-sessions")

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


def test_browser_auth_session_create_mcp_failure_returns_400_and_persists_invalid(
    monkeypatch,
):
    from orchestrator.api.main import app
    from orchestrator.services import browser_auth_sessions as service

    project_id = _create_uuid_project()
    with Session(engine) as session:
        assert set_project_credential(
            project_id, "LOGIN_USERNAME", "user@example.com", session
        )
        assert set_project_credential(
            project_id, "LOGIN_PASSWORD", "secret-password", session
        )

    def fail_mcp_capture(**_kwargs):
        raise BrowserAuthSessionError("security challenge detected")

    monkeypatch.setattr(
        service, "capture_storage_state_via_mcp_agent", fail_mcp_capture
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/projects/{project_id}/browser-auth-sessions",
            json={
                "name": "Broken login",
                "base_url": "https://example.com",
                "login_url": "https://example.com/login",
                "username_key": "LOGIN_USERNAME",
                "password_key": "LOGIN_PASSWORD",
                "make_default": True,
            },
        )
        list_response = client.get(f"/projects/{project_id}/browser-auth-sessions")

    assert response.status_code == 400, response.text
    assert "Security challenge detected" in response.json()["detail"]
    assert list_response.status_code == 200, list_response.text
    sessions = list_response.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["name"] == "Broken login"
    assert sessions[0]["status"] == "invalid"
    assert sessions[0]["is_default"] is False
    assert "Security challenge detected" in sessions[0]["failure_reason"]
    assert sessions[0]["capture_backend_version"] == BROWSER_AUTH_CAPTURE_VERSION


def test_browser_auth_session_create_reactivates_revoked_same_name_row(monkeypatch):
    from orchestrator.api.main import app
    from orchestrator.services import browser_auth_sessions as service

    project_id = _create_uuid_project()
    old_state = {
        "cookies": [
            {"name": "old", "value": "stale", "domain": "example.com", "path": "/"}
        ],
        "origins": [],
    }
    captured: dict[str, object] = {}

    with Session(engine) as session:
        assert set_project_credential(
            project_id, "LOGIN_USERNAME", "user@example.com", session
        )
        assert set_project_credential(
            project_id, "LOGIN_PASSWORD", "secret-password", session
        )
        row = BrowserAuthSession(
            project_id=project_id,
            name="wetravel_farhad",
            base_url="https://old.example.com",
            login_url="https://old.example.com/login",
            username_key="OLD_USER",
            password_key="OLD_PASSWORD",
            storage_state_json_encrypted=encrypt_storage_state(old_state),
            status="revoked",
            is_default=True,
            failure_reason="Revoked by user",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        existing_id = row.id

    def fake_mcp_capture(**kwargs):
        captured.update(kwargs)
        return {
            "cookies": [
                {
                    "name": "sid",
                    "value": "fresh",
                    "domain": "pre.wetravel.to",
                    "path": "/",
                }
            ],
            "origins": [],
        }

    monkeypatch.setattr(
        service, "capture_storage_state_via_mcp_agent", fake_mcp_capture
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        hidden_response = client.get(f"/projects/{project_id}/browser-auth-sessions")
        create_response = client.post(
            f"/projects/{project_id}/browser-auth-sessions",
            json={
                "name": "wetravel_farhad",
                "base_url": "https://pre.wetravel.to/",
                "login_url": "https://pre.wetravel.to/users/sign_in",
                "username_key": "LOGIN_USERNAME",
                "password_key": "LOGIN_PASSWORD",
            },
        )
        list_response = client.get(f"/projects/{project_id}/browser-auth-sessions")

    assert hidden_response.status_code == 200, hidden_response.text
    assert hidden_response.json()["sessions"] == []
    assert create_response.status_code == 201, create_response.text
    body = create_response.json()
    assert body["id"] == existing_id
    assert body["status"] == "active"
    assert body["is_default"] is False
    assert body["failure_reason"] is None
    assert body["base_url"] == "https://pre.wetravel.to/"
    assert captured["session_id"] == existing_id
    sessions = list_response.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["id"] == existing_id

    with Session(engine) as session:
        reactivated = session.get(BrowserAuthSession, existing_id)
        state = decrypt_storage_state(reactivated.storage_state_json_encrypted)
        assert state["cookies"][0]["value"] == "fresh"


def test_browser_auth_session_create_updates_invalid_same_name_row(monkeypatch):
    from orchestrator.api.main import app
    from orchestrator.services import browser_auth_sessions as service

    project_id = _create_uuid_project()
    captured: dict[str, object] = {}

    with Session(engine) as session:
        assert set_project_credential(
            project_id, "LOGIN_USERNAME", "user@example.com", session
        )
        assert set_project_credential(
            project_id, "LOGIN_PASSWORD", "secret-password", session
        )
        row = BrowserAuthSession(
            project_id=project_id,
            name="Broken login",
            base_url="https://old.example.com",
            login_url="https://old.example.com/login",
            username_key="OLD_USER",
            password_key="OLD_PASSWORD",
            status="invalid",
            failure_reason="Old failure",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        existing_id = row.id

    def fake_mcp_capture(**kwargs):
        captured.update(kwargs)
        return {"cookies": [], "origins": []}

    monkeypatch.setattr(
        service, "capture_storage_state_via_mcp_agent", fake_mcp_capture
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        create_response = client.post(
            f"/projects/{project_id}/browser-auth-sessions",
            json={
                "name": "Broken login",
                "base_url": "https://example.com",
                "login_url": "https://example.com/login",
                "username_key": "LOGIN_USERNAME",
                "password_key": "LOGIN_PASSWORD",
                "username_selector": "#email",
            },
        )
        list_response = client.get(f"/projects/{project_id}/browser-auth-sessions")

    assert create_response.status_code == 201, create_response.text
    body = create_response.json()
    assert body["id"] == existing_id
    assert body["status"] == "active"
    assert body["failure_reason"] is None
    assert body["username_selector"] == "#email"
    assert captured["session_id"] == existing_id
    sessions = list_response.json()["sessions"]
    assert len([item for item in sessions if item["name"] == "Broken login"]) == 1


def test_create_browser_auth_session_integrity_error_is_normalized(monkeypatch):
    project_id = _create_uuid_project()

    with Session(engine) as session:
        original_commit = session.commit
        calls = {"count": 0}

        def fail_first_commit():
            calls["count"] += 1
            if calls["count"] == 1:
                from sqlalchemy.exc import IntegrityError

                raise IntegrityError(
                    "INSERT INTO browser_auth_sessions", {}, Exception("duplicate")
                )
            return original_commit()

        monkeypatch.setattr(session, "commit", fail_first_commit)

        try:
            create_browser_auth_session(
                session,
                project_id=project_id,
                name="Race login",
                base_url="https://example.com",
                login_url="https://example.com/login",
                username_key="LOGIN_USERNAME",
                password_key="LOGIN_PASSWORD",
                storage_state={"cookies": [], "origins": []},
            )
        except BrowserAuthSessionError as exc:
            assert "already in use" in str(exc)
        else:
            raise AssertionError("Expected BrowserAuthSessionError")


def test_refresh_browser_auth_session_uses_mcp_capture_and_passes_advanced_selectors(
    monkeypatch,
):
    from orchestrator.services import browser_auth_sessions as service

    project_id = _create_project()
    captured: dict[str, object] = {}

    with Session(engine) as session:
        assert set_project_credential(
            project_id, "LOGIN_USERNAME", "user@example.com", session
        )
        assert set_project_credential(
            project_id, "LOGIN_PASSWORD", "secret-password", session
        )
        row = BrowserAuthSession(
            project_id=project_id,
            name="Advanced refresh",
            base_url="https://example.com",
            login_url="https://example.com/login",
            username_key="LOGIN_USERNAME",
            password_key="LOGIN_PASSWORD",
            username_selector="#email",
            password_selector="#password",
            username_continue_selector="button.next",
            submit_selector="button.sign-in",
            success_url_pattern="/dashboard$",
            status="pending",
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        def fake_mcp_capture(**kwargs):
            captured.update(kwargs)
            return {"cookies": [], "origins": []}

        monkeypatch.setattr(
            service, "capture_storage_state_via_mcp_agent", fake_mcp_capture
        )

        def fake_runtime_env_vars(session_arg=None):
            captured["runtime_session"] = session_arg
            return {
                "QUORVEX_LLM_PROVIDER": "zai",
                "QUORVEX_LLM_BASE_URL": "https://api.z.ai/api/anthropic",
                "QUORVEX_LLM_API_KEY": "settings-session-key",
                "QUORVEX_LLM_TOOL_DEEP_MODEL": "glm-5.1",
            }

        monkeypatch.setattr(service, "runtime_env_vars", fake_runtime_env_vars)

        refreshed = refresh_browser_auth_session(session, project_id, row.id)

    assert refreshed.status == "active"
    assert captured["session_id"] == row.id
    assert captured["username_selector"] == "#email"
    assert captured["password_selector"] == "#password"
    assert captured["username_continue_selector"] == "button.next"
    assert captured["submit_selector"] == "button.sign-in"
    assert captured["success_url_pattern"] == "/dashboard$"
    assert captured["runtime_session"] is session
    assert captured["runtime_env"]["QUORVEX_LLM_API_KEY"] == "settings-session-key"


def test_refresh_browser_auth_session_falls_back_to_direct_playwright_when_mcp_omits_storage(
    monkeypatch,
):
    from orchestrator.services import browser_auth_sessions as service

    project_id = _create_project()
    captured: dict[str, object] = {}

    with Session(engine) as session:
        assert set_project_credential(
            project_id, "LOGIN_USERNAME", "user@example.com", session
        )
        assert set_project_credential(
            project_id, "LOGIN_PASSWORD", "secret-password", session
        )
        row = BrowserAuthSession(
            project_id=project_id,
            name="Fallback refresh",
            base_url="https://example.com",
            login_url="https://example.com/login",
            username_key="LOGIN_USERNAME",
            password_key="LOGIN_PASSWORD",
            username_selector="#email",
            password_selector="#password",
            status="pending",
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        def fake_mcp_capture(**kwargs):
            captured["mcp"] = kwargs
            raise service.BrowserAuthStorageStateMissingError(
                "Storage state file not produced by MCP browser auth capture."
            )

        def fake_direct_capture(**kwargs):
            captured["direct"] = kwargs
            return {
                "cookies": [
                    {
                        "name": "sid",
                        "value": "fallback",
                        "domain": "example.com",
                        "path": "/",
                    }
                ],
                "origins": [],
            }

        monkeypatch.setattr(
            service, "capture_storage_state_via_mcp_agent", fake_mcp_capture
        )
        monkeypatch.setattr(
            service, "create_storage_state_via_playwright", fake_direct_capture
        )

        refreshed = refresh_browser_auth_session(session, project_id, row.id)

    assert refreshed.status == "active"
    assert refreshed.failure_reason is None
    assert captured["mcp"]["session_id"] == row.id
    assert captured["direct"]["username_selector"] == "#email"
    assert captured["direct"]["password_selector"] == "#password"
    assert isinstance(captured["direct"]["run_dir"], Path)
    assert (
        decrypt_storage_state(refreshed.storage_state_json_encrypted)["cookies"][0][
            "value"
        ]
        == "fallback"
    )


def test_refresh_browser_auth_session_security_challenge_does_not_fall_back(
    monkeypatch,
):
    from orchestrator.services import browser_auth_sessions as service

    project_id = _create_project()
    direct_called = False

    with Session(engine) as session:
        assert set_project_credential(
            project_id, "LOGIN_USERNAME", "user@example.com", session
        )
        assert set_project_credential(
            project_id, "LOGIN_PASSWORD", "secret-password", session
        )
        row = BrowserAuthSession(
            project_id=project_id,
            name="Challenge refresh",
            base_url="https://example.com",
            login_url="https://example.com/login",
            username_key="LOGIN_USERNAME",
            password_key="LOGIN_PASSWORD",
            status="pending",
        )
        session.add(row)
        session.commit()
        session.refresh(row)

        def fake_mcp_capture(**_kwargs):
            raise BrowserAuthSessionError("security challenge detected")

        def fake_direct_capture(**_kwargs):
            nonlocal direct_called
            direct_called = True
            return {"cookies": [], "origins": []}

        monkeypatch.setattr(
            service, "capture_storage_state_via_mcp_agent", fake_mcp_capture
        )
        monkeypatch.setattr(
            service, "create_storage_state_via_playwright", fake_direct_capture
        )

        try:
            refresh_browser_auth_session(session, project_id, row.id)
        except BrowserAuthSessionError as exc:
            message = str(exc)
        else:
            raise AssertionError("Expected BrowserAuthSessionError")

        session.refresh(row)

    assert direct_called is False
    assert "Security challenge detected" in message
    assert row.status == "invalid"
    assert "Security challenge detected" in row.failure_reason


def test_create_storage_state_via_playwright_validates_missing_and_malformed_storage_state(
    tmp_path, monkeypatch
):
    from orchestrator.services import browser_auth_sessions as service

    def fake_run_without_output(*_args, **_kwargs):
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(service.subprocess, "run", fake_run_without_output)

    try:
        service.create_storage_state_via_playwright(
            base_url="https://example.com",
            login_url="https://example.com/login",
            username="user@example.com",
            password="secret-password",
            run_dir=tmp_path / "missing",
        )
    except BrowserAuthSessionError as exc:
        assert "storage state file was not produced" in str(exc)
    else:
        raise AssertionError("Expected BrowserAuthSessionError")

    def fake_run_with_malformed_output(*_args, **kwargs):
        Path(kwargs["env"]["BROWSER_AUTH_OUTPUT_PATH"]).write_text(
            "{not-json", encoding="utf-8"
        )
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(service.subprocess, "run", fake_run_with_malformed_output)

    try:
        service.create_storage_state_via_playwright(
            base_url="https://example.com",
            login_url="https://example.com/login",
            username="user@example.com",
            password="secret-password",
            run_dir=tmp_path / "malformed",
        )
    except BrowserAuthSessionError as exc:
        assert "not valid JSON" in str(exc)
    else:
        raise AssertionError("Expected BrowserAuthSessionError")


def test_capture_storage_state_via_mcp_agent_reads_and_validates_storage_state(
    tmp_path, monkeypatch
):
    from orchestrator.services import browser_auth_sessions as service

    monkeypatch.setattr(service, "AUTH_SESSIONS_DIR", tmp_path)
    captured: dict[str, object] = {}

    def fake_run_async_capture(
        prompt, *, run_dir, timeout_seconds, session_id, runtime_env=None
    ):
        captured["prompt"] = prompt
        captured["run_dir"] = run_dir
        captured["timeout_seconds"] = timeout_seconds
        captured["session_id"] = session_id
        captured["runtime_env"] = runtime_env
        artifacts = Path(run_dir) / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "storage-state.json").write_text(
            '{"cookies":[{"name":"sid","value":"abc","domain":"example.com","path":"/"}],"origins":[]}'
        )
        return AgentResult(success=True, output="saved")

    monkeypatch.setattr(service, "_run_async_capture", fake_run_async_capture)

    state = service.capture_storage_state_via_mcp_agent(
        session_id="session-123",
        base_url="https://example.com",
        login_url="https://example.com/login",
        username="user@example.com",
        password="secret-password",
        username_selector="#email",
    )

    assert state["cookies"][0]["value"] == "abc"
    assert captured["session_id"] == "session-123"
    assert "BROWSER_AUTH_USERNAME" in str(captured["prompt"])
    assert "secret-password" not in str(captured["prompt"])
    assert "Leave site?" in str(captured["prompt"])
    assert "`accept: true`" in str(captured["prompt"])
    run_dir = Path(captured["run_dir"])
    config = (run_dir / ".mcp.json").read_text()
    assert "--caps" in config
    assert "storage" in config
    assert "--secrets" in config
    secrets = run_dir / "browser-auth-secrets.env"
    assert secrets.exists()
    assert oct(secrets.stat().st_mode & 0o777) == "0o600"


def test_run_async_capture_acquires_browser_auth_pool_slot(monkeypatch, tmp_path):
    from orchestrator.services import browser_auth_sessions as service
    from orchestrator.services.browser_pool import OperationType

    captured: dict[str, object] = {}

    @asynccontextmanager
    async def fake_browser_operation_slot(**kwargs):
        captured["slot_kwargs"] = kwargs
        yield

    async def fake_run_capture_agent(
        prompt, *, run_dir, timeout_seconds, session_id, runtime_env=None
    ):
        captured["prompt"] = prompt
        captured["runtime_env"] = runtime_env
        return AgentResult(success=True, output="captured")

    monkeypatch.setattr(service, "browser_operation_slot", fake_browser_operation_slot)
    monkeypatch.setattr(service, "_run_capture_agent", fake_run_capture_agent)

    result = service._run_async_capture(
        "capture prompt",
        run_dir=tmp_path,
        timeout_seconds=30,
        session_id="session-123",
    )

    assert result.success is True
    slot_kwargs = captured["slot_kwargs"]
    assert slot_kwargs["request_id"] == "browser-auth:session-123"
    assert slot_kwargs["operation_type"] == OperationType.BROWSER_AUTH


def test_capture_storage_state_via_mcp_agent_accepts_run_dir_storage_state(
    tmp_path, monkeypatch
):
    from orchestrator.services import browser_auth_sessions as service

    monkeypatch.setattr(service, "AUTH_SESSIONS_DIR", tmp_path)

    def fake_run_async_capture(_prompt, *, run_dir, **_kwargs):
        Path(run_dir, "storage-state.json").write_text(
            '{"cookies":[{"name":"sid","value":"root-output","domain":"example.com","path":"/"}],"origins":[]}'
        )
        return AgentResult(success=True, output="saved")

    monkeypatch.setattr(service, "_run_async_capture", fake_run_async_capture)

    state = service.capture_storage_state_via_mcp_agent(
        session_id="session-root-output",
        base_url="https://example.com",
        login_url="https://example.com/login",
        username="user@example.com",
        password="secret-password",
    )

    assert state["cookies"][0]["value"] == "root-output"


def test_capture_storage_state_via_mcp_agent_missing_file_normalizes_failure(
    tmp_path, monkeypatch
):
    from orchestrator.services import browser_auth_sessions as service

    monkeypatch.setattr(service, "AUTH_SESSIONS_DIR", tmp_path)

    def fake_run_async_capture(*_args, **_kwargs):
        return AgentResult(success=True, output="done")

    monkeypatch.setattr(service, "_run_async_capture", fake_run_async_capture)

    try:
        service.capture_storage_state_via_mcp_agent(
            session_id="session-456",
            base_url="https://example.com",
            login_url="https://example.com/login",
            username="user@example.com",
            password="secret",
        )
    except BrowserAuthSessionError as exc:
        assert "Storage state file not produced" in str(exc)
    else:
        raise AssertionError("Expected BrowserAuthSessionError")


def test_mcp_capture_normalizes_old_direct_helper_error_text(monkeypatch):
    from orchestrator.services import browser_auth_sessions as service

    normalized = service._normalize_capture_error(
        "locator.fill timeout at [eval]:35:25"
    )

    assert "locator.fill" not in normalized
    assert "[eval]" not in normalized
    assert "MCP browser auth capture failed" in normalized


def test_mcp_capture_normalizes_claude_login_error():
    from orchestrator.services import browser_auth_sessions as service

    normalized = service._normalize_capture_error("Not logged in · Please run /login")

    assert "LLM runtime is not authenticated" in normalized
    assert "Settings or deployment environment secrets" in normalized


def test_run_capture_agent_uses_settings_backed_zai_key_for_preflight(
    tmp_path, monkeypatch
):
    from orchestrator.services import browser_auth_sessions as service

    captured: dict[str, object] = {}

    class FakeAgentRunner:
        def __init__(self, **kwargs):
            captured["runner_kwargs"] = kwargs

        async def run(self, prompt, timeout_override=None):
            captured["prompt"] = prompt
            captured["timeout_override"] = timeout_override
            return AgentResult(success=True, output="ok")

    monkeypatch.setattr(service, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(
        service,
        "runtime_env_vars",
        lambda: {
            "QUORVEX_LLM_PROVIDER": "zai",
            "QUORVEX_LLM_BASE_URL": "https://api.z.ai/api/anthropic",
            "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
            "QUORVEX_LLM_API_KEY": "settings-zai-token",
            "QUORVEX_LLM_TOOL_DEEP_MODEL": "glm-5.1",
        },
    )

    result = asyncio.run(
        service._run_capture_agent(
            "capture login",
            run_dir=tmp_path,
            timeout_seconds=5,
            session_id="session-settings-key",
        )
    )

    assert result.success is True
    assert captured["timeout_override"] == 5
    assert os.environ["QUORVEX_LLM_API_KEY"] == "settings-zai-token"
    assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "settings-zai-token"


def test_run_capture_agent_uses_explicit_runtime_env_for_preflight(
    tmp_path, monkeypatch
):
    from orchestrator.services import browser_auth_sessions as service

    captured: dict[str, object] = {}

    class FakeAgentRunner:
        def __init__(self, **kwargs):
            captured["runner_kwargs"] = kwargs

        async def run(self, prompt, timeout_override=None):
            captured["prompt"] = prompt
            captured["timeout_override"] = timeout_override
            return AgentResult(success=True, output="ok")

    def fail_runtime_env_vars():
        raise AssertionError("runtime_env_vars should not be called")

    monkeypatch.setattr(service, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(service, "runtime_env_vars", fail_runtime_env_vars)

    result = asyncio.run(
        service._run_capture_agent(
            "capture login",
            run_dir=tmp_path,
            timeout_seconds=5,
            session_id="session-explicit-key",
            runtime_env={
                "QUORVEX_LLM_PROVIDER": "zai",
                "QUORVEX_LLM_BASE_URL": "https://api.z.ai/api/anthropic",
                "QUORVEX_LLM_API_KEY": "explicit-settings-token",
                "QUORVEX_LLM_TOOL_DEEP_MODEL": "glm-5.1",
            },
        )
    )

    assert result.success is True
    assert captured["timeout_override"] == 5
    assert os.environ["QUORVEX_LLM_API_KEY"] == "explicit-settings-token"
    assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "explicit-settings-token"


def test_run_capture_agent_missing_zai_key_has_actionable_message(
    tmp_path, monkeypatch
):
    from orchestrator.services import browser_auth_sessions as service

    for key in (
        "QUORVEX_LLM_API_KEY",
        "QUORVEX_LLM_API_KEYS",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_AUTH_TOKENS",
        "ANTHROPIC_API_KEY",
        "ZAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        service,
        "runtime_env_vars",
        lambda: {
            "QUORVEX_LLM_PROVIDER": "zai",
            "QUORVEX_LLM_BASE_URL": "https://api.z.ai/api/anthropic",
            "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
            "QUORVEX_LLM_TOOL_DEEP_MODEL": "glm-5.1",
        },
    )

    try:
        asyncio.run(
            service._run_capture_agent(
                "capture login",
                run_dir=tmp_path,
                timeout_seconds=5,
                session_id="session-no-key",
            )
        )
    except BrowserAuthSessionError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected BrowserAuthSessionError")

    assert "LLM provider API key is not configured for zai" in message
    assert "Settings or deployment environment secrets" in message
    assert (
        "restart the backend and worker services if using environment secrets"
        in message
    )
