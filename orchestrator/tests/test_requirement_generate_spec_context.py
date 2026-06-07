import os
import sys
import types
from pathlib import Path
from uuid import uuid4

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-requirement-generate-spec-tests")
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
from sqlmodel import Session, SQLModel, select

from orchestrator.api.db import _run_migrations, engine
from orchestrator.api.main import app
from orchestrator.api.models_db import AgentRun, BrowserAuthSession, Project, TestDataItem as DBTestDataItem
from orchestrator.api.models_db import TestDataSet as DBTestDataSet
from orchestrator.memory.exploration_store import get_exploration_store
from orchestrator.services.browser_auth_sessions import encrypt_storage_state
from orchestrator.services.test_data_resolver import prepare_test_data_item_storage


def _create_project() -> str:
    SQLModel.metadata.create_all(engine)
    _run_migrations()
    project_id = f"req-generate-{uuid4().hex}"
    with Session(engine) as session:
        session.add(Project(id=project_id, name=f"Requirement Generate {uuid4().hex}"))
        session.commit()
    return project_id


def _create_requirement(project_id: str) -> int:
    store = get_exploration_store(project_id=project_id)
    requirement = store.store_requirement(
        req_code="REQ-001",
        title=f"Checkout requires saved cart {uuid4().hex[:6]}",
        category="checkout",
        description="Users can complete checkout with prepared project data.",
        acceptance_criteria=["Checkout succeeds with a valid user and cart."],
    )
    assert requirement.id is not None
    return requirement.id


def _create_test_data(project_id: str) -> str:
    with Session(engine) as session:
        dataset = DBTestDataSet(
            project_id=project_id,
            key="checkout-users",
            name="Checkout Users",
        )
        session.add(dataset)
        session.flush()

        storage = prepare_test_data_item_storage(
            data={"email": "buyer@example.test", "password": "secret-pass"},
            sensitive_fields=["password"],
        )
        item = DBTestDataItem(
            dataset_id=dataset.id,
            key="valid-buyer",
            name="Valid buyer",
            data_text=storage["text"],
        )
        item.data = storage["data"]
        item.sensitive_fields = storage["sensitive_fields"]
        item.encrypted_values = storage["encrypted_values"]
        session.add(item)
        session.commit()
    return "checkout-users.valid-buyer"


def _create_browser_auth_session(project_id: str, *, status: str = "active") -> str:
    state = {
        "cookies": [{"name": "sid", "value": f"cookie-{uuid4().hex}", "domain": "example.test", "path": "/"}],
        "origins": [],
    }
    with Session(engine) as session:
        row = BrowserAuthSession(
            project_id=project_id,
            name=f"Saved Login {uuid4().hex[:6]}",
            base_url="https://example.test",
            login_url="https://example.test/login",
            username_key="LOGIN_USERNAME",
            password_key="LOGIN_PASSWORD",
            storage_state_json_encrypted=encrypt_storage_state(state),
            status=status,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


class _FakePlanner:
    calls: list[dict] = []
    init_kwargs: list[dict] = []
    generated_paths: list[Path] = []

    def __init__(self, *args, **kwargs):
        self.init_kwargs.append(kwargs)

    async def generate_spec_from_flow_context(self, **kwargs):
        self.calls.append(kwargs)
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"generated-{uuid4().hex}.md"
        output_path.write_text("# Generated Spec\n\n### TC-001: Checkout\n")
        self.generated_paths.append(output_path)
        return output_path


@pytest.fixture(autouse=True)
def _cleanup_fake_generated_specs():
    yield
    for path in _FakePlanner.generated_paths:
        try:
            path.unlink(missing_ok=True)
            path.parent.rmdir()
        except OSError:
            pass
    for kwargs in _FakePlanner.init_kwargs:
        session_dir = kwargs.get("session_dir")
        if session_dir:
            try:
                import shutil

                shutil.rmtree(session_dir, ignore_errors=True)
            except OSError:
                pass
    _FakePlanner.generated_paths = []
    _FakePlanner.init_kwargs = []


def test_requirement_generate_spec_passes_test_data_and_browser_auth(monkeypatch):
    from workflows import native_planner as native_planner_module

    project_id = _create_project()
    req_id = _create_requirement(project_id)
    test_data_ref = _create_test_data(project_id)
    browser_auth_session_id = _create_browser_auth_session(project_id)

    _FakePlanner.calls = []
    monkeypatch.setattr(native_planner_module, "NativePlanner", _FakePlanner)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/requirements/{req_id}/generate-spec?project_id={project_id}",
            json={
                "target_url": "https://example.test/checkout",
                "browser_auth_session_id": browser_auth_session_id,
                "test_data_refs": [test_data_ref],
                "force_regenerate": True,
            },
        )

    assert response.status_code == 200
    assert _FakePlanner.calls
    call = _FakePlanner.calls[0]
    assert "checkout-users.valid-buyer" in call["flow_context"]
    assert call["auth_context"]["browser_auth_session_id"] == browser_auth_session_id
    assert call["auth_context"]["storage_state_attached"] is True
    assert _FakePlanner.init_kwargs[0]["session_dir"].joinpath(".mcp.json").exists()


def test_requirement_generate_spec_rejects_missing_test_data(monkeypatch):
    from workflows import native_planner as native_planner_module

    project_id = _create_project()
    req_id = _create_requirement(project_id)
    _FakePlanner.calls = []
    monkeypatch.setattr(native_planner_module, "NativePlanner", _FakePlanner)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/requirements/{req_id}/generate-spec?project_id={project_id}",
            json={
                "target_url": "https://example.test/checkout",
                "test_data_refs": ["missing.ref"],
                "force_regenerate": True,
            },
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["error"] == "test_data_refs_unresolved"
    assert detail["missing_test_data"] == [{"ref": "missing.ref", "reason": "dataset_not_found"}]
    assert _FakePlanner.calls == []


def test_requirement_generate_spec_rejects_unusable_browser_auth(monkeypatch):
    from workflows import native_planner as native_planner_module

    project_id = _create_project()
    req_id = _create_requirement(project_id)
    browser_auth_session_id = _create_browser_auth_session(project_id, status="revoked")

    _FakePlanner.calls = []
    monkeypatch.setattr(native_planner_module, "NativePlanner", _FakePlanner)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/requirements/{req_id}/generate-spec?project_id={project_id}",
            json={
                "target_url": "https://example.test/checkout",
                "browser_auth_session_id": browser_auth_session_id,
                "force_regenerate": True,
            },
        )

    assert response.status_code == 400
    assert "not usable" in response.json()["detail"]
    assert _FakePlanner.calls == []


def test_requirement_generate_spec_job_returns_cached_result(monkeypatch):
    from workflows import native_planner as native_planner_module

    project_id = _create_project()
    req_id = _create_requirement(project_id)
    _FakePlanner.calls = []
    monkeypatch.setattr(native_planner_module, "NativePlanner", _FakePlanner)

    specs_dir = Path(__file__).resolve().parents[2] / "specs" / "requirements" / project_id
    specs_dir.mkdir(parents=True, exist_ok=True)
    spec_path = specs_dir / f"cached-{uuid4().hex}.md"
    spec_path.write_text("# Cached Spec\n")
    store = get_exploration_store(project_id=project_id)
    entry = store.store_rtm_entry(
        requirement_id=req_id,
        test_spec_name=spec_path.name,
        test_spec_path=str(spec_path),
        mapping_type="full",
    )

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                f"/requirements/{req_id}/generate-spec-jobs?project_id={project_id}",
                json={
                    "target_url": "https://example.test/checkout",
                    "force_regenerate": False,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cached"
        assert data["result"]["cached"] is True
        assert data["result"]["rtm_entry_id"] == entry.id
        assert data["result"]["spec_content"] == "# Cached Spec\n"
        assert _FakePlanner.calls == []
    finally:
        spec_path.unlink(missing_ok=True)


def test_requirement_generate_spec_job_runs_and_polls_agent_run(monkeypatch):
    from workflows import native_planner as native_planner_module

    project_id = _create_project()
    req_id = _create_requirement(project_id)
    browser_auth_session_id = _create_browser_auth_session(project_id)
    _FakePlanner.calls = []
    monkeypatch.setattr(native_planner_module, "NativePlanner", _FakePlanner)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/requirements/{req_id}/generate-spec-jobs?project_id={project_id}",
            json={
                "target_url": "https://example.test/checkout",
                "browser_auth_session_id": browser_auth_session_id,
                "force_regenerate": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert data["job_id"].startswith(f"reqspec-{req_id}-")
        assert data["agent_run_id"] == data["job_id"]

        poll = client.get(f"/requirements/generate-spec-jobs/{data['job_id']}")

    assert poll.status_code == 200
    status = poll.json()
    assert status["status"] == "completed"
    assert status["result"]["cached"] is False
    assert status["result"]["requirement_id"] == req_id
    assert status["agent_run_id"] == data["agent_run_id"]
    assert status["agent_run"]["agent_type"] == "spec_generation"
    assert status["agent_run"]["progress"]["has_browser_tools"] is True
    assert "browser_runtime" in status["agent_run"]["progress"]
    assert status["agent_run"]["progress"]["browser_auth_session_id"] == browser_auth_session_id

    with Session(engine) as session:
        run = session.get(AgentRun, data["agent_run_id"])
        assert run is not None
        assert run.status == "completed"
        assert run.result["requirement_id"] == req_id


def test_requirement_generate_spec_job_rejects_missing_test_data_before_agent_run(monkeypatch):
    from workflows import native_planner as native_planner_module

    project_id = _create_project()
    req_id = _create_requirement(project_id)
    _FakePlanner.calls = []
    monkeypatch.setattr(native_planner_module, "NativePlanner", _FakePlanner)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/requirements/{req_id}/generate-spec-jobs?project_id={project_id}",
            json={
                "target_url": "https://example.test/checkout",
                "test_data_refs": ["missing.ref"],
                "force_regenerate": True,
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "test_data_refs_unresolved"
    assert _FakePlanner.calls == []
    with Session(engine) as session:
        runs = session.exec(select(AgentRun).where(AgentRun.id.like(f"reqspec-{req_id}-%"))).all()
        assert runs == []
