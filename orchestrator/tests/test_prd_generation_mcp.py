import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-prd-generation-tests")

import orchestrator.api.prd as prd_api
from orchestrator.api.models_db import PrdGenerationEvent, PrdGenerationResult, Project, Requirement
from orchestrator.api.prd import GenerateRequest, _prepare_prd_generation_mcp_workspace
from orchestrator.services import agent_queue as agent_queue_module
from orchestrator.services.agent_queue import AgentTask, AgentTaskStatus
from orchestrator.utils.agent_tool_allowlists import get_agent_allowed_tools


class _AcquiredBrowserSlot:
    async def __aenter__(self):
        return True

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _AvailableBrowserPool:
    async def get_status(self):
        return {"available": 1}

    def browser_slot(self, *args, **kwargs):
        return _AcquiredBrowserSlot()


async def _fake_get_browser_pool():
    return _AvailableBrowserPool()


async def _fake_check_system_available(operation: str):
    return None


def test_prd_generation_workspace_uses_playwright_test_mcp(tmp_path):
    base_dir = tmp_path / "project"
    run_dir = tmp_path / "runs" / "prd-generation-123"
    base_dir.mkdir()
    (base_dir / "playwright.config.ts").write_text(
        """
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || './test-results',
  testMatch: ['generated/**/*.spec.ts', 'e2e/**/*.spec.ts'],
  use: {
    video: 'retain-on-failure',
  },
});
"""
    )

    runtime = _prepare_prd_generation_mcp_workspace(run_dir, base_dir=base_dir, headless=True)

    mcp_config_path = run_dir / ".mcp.json"
    config = json.loads(mcp_config_path.read_text())
    server = config["mcpServers"]["playwright-test"]
    copied_config = run_dir / "playwright.config.ts"

    assert runtime["mcp_config_path"] == str(mcp_config_path)
    assert server["command"] == "npx"
    assert server["args"] == [
        "playwright",
        "run-test-mcp-server",
        "-c",
        str(copied_config),
        "--headless",
    ]
    assert f"testDir: '{base_dir}/tests'" in copied_config.read_text()
    assert f"outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || '{run_dir}/test-results'" in copied_config.read_text()

    allowed_tools = get_agent_allowed_tools("playwright-test-planner", mcp_config_dir=run_dir)
    assert "mcp__playwright-test__planner_setup_page" in allowed_tools
    assert "mcp__playwright-test__planner_save_plan" in allowed_tools


def test_upload_prd_uses_writable_runtime_upload_dir_and_cleans_temp_file(monkeypatch, tmp_path):
    import orchestrator.services.load_test_lock as load_test_lock
    import orchestrator.workflows.prd_processor as prd_processor

    monkeypatch.setattr(prd_api, "BASE_DIR", tmp_path)
    monkeypatch.setattr(prd_api, "get_browser_pool", _fake_get_browser_pool)
    monkeypatch.setattr(load_test_lock, "check_system_available", _fake_check_system_available)

    captured: dict[str, Path | str | int] = {}

    class FakePRDProcessor:
        def process_prd(self, pdf_path, project_name, target_feature_count=15):
            temp_path = Path(pdf_path)
            captured["temp_path"] = temp_path
            captured["project_name"] = project_name
            captured["target_feature_count"] = target_feature_count

            assert temp_path.exists()
            assert temp_path.parent == tmp_path / "prds" / "uploads"
            assert temp_path.name.startswith("prd_")
            assert temp_path.name.endswith("-wetravel-manage-rooms.pdf")

            return {
                "project": project_name,
                "features": [
                    {
                        "name": "Room Management",
                        "slug": "room-management",
                        "requirements": ["Users can manage rooms."],
                        "content": "Room management",
                    }
                ],
                "total_chunks": 1,
                "config": {"target_feature_count": target_feature_count},
            }

    monkeypatch.setattr(prd_processor, "PRDProcessor", FakePRDProcessor)

    app = FastAPI()
    app.include_router(prd_api.router)
    client = TestClient(app)

    response = client.post(
        "/api/prd/upload?project=custom-prd&target_features=12",
        files={"file": ("wetravel-manage-rooms.pdf", b"%PDF-1.4\n", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["project"] == "custom-prd"
    assert captured["project_name"] == "custom-prd"
    assert captured["target_feature_count"] == 12
    assert not captured["temp_path"].exists()
    assert list((tmp_path / "prds" / "uploads").iterdir()) == []


def test_upload_prd_returns_actionable_error_when_upload_storage_unwritable(monkeypatch, tmp_path):
    import orchestrator.services.load_test_lock as load_test_lock
    import orchestrator.workflows.prd_processor as prd_processor

    monkeypatch.setattr(prd_api, "BASE_DIR", tmp_path)
    monkeypatch.setattr(prd_api, "get_browser_pool", _fake_get_browser_pool)
    monkeypatch.setattr(load_test_lock, "check_system_available", _fake_check_system_available)

    class UnexpectedPRDProcessor:
        def process_prd(self, *args, **kwargs):
            raise AssertionError("PRD processing should not start when upload storage is unavailable")

    monkeypatch.setattr(prd_processor, "PRDProcessor", UnexpectedPRDProcessor)

    original_mkdir = Path.mkdir

    def fail_upload_dir_mkdir(self, *args, **kwargs):
        if self == tmp_path / "prds" / "uploads":
            raise PermissionError("permission denied")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_upload_dir_mkdir)

    app = FastAPI()
    app.include_router(prd_api.router)
    client = TestClient(app)

    response = client.post(
        "/api/prd/upload",
        files={"file": ("wetravel-manage-rooms.pdf", b"%PDF-1.4\n", "application/pdf")},
    )

    assert response.status_code == 500
    assert "PRD upload storage is not writable" in response.json()["detail"]


def test_upload_prd_rejects_zero_feature_processor_result(monkeypatch, tmp_path):
    import orchestrator.services.load_test_lock as load_test_lock
    import orchestrator.workflows.prd_processor as prd_processor

    monkeypatch.setattr(prd_api, "BASE_DIR", tmp_path)
    monkeypatch.setattr(prd_api, "get_browser_pool", _fake_get_browser_pool)
    monkeypatch.setattr(load_test_lock, "check_system_available", _fake_check_system_available)

    class EmptyPRDProcessor:
        def process_prd(self, pdf_path, project_name, target_feature_count=15):
            return {
                "project": project_name,
                "features": [],
                "total_chunks": 0,
                "config": {"target_feature_count": target_feature_count},
            }

    monkeypatch.setattr(prd_processor, "PRDProcessor", EmptyPRDProcessor)

    app = FastAPI()
    app.include_router(prd_api.router)
    client = TestClient(app)

    response = client.post(
        "/api/prd/upload",
        files={"file": ("wetravel-manage-rooms.pdf", b"%PDF-1.4\n", "application/pdf")},
    )

    assert response.status_code == 502
    assert "zero features" in response.json()["detail"]


def test_upload_prd_surfaces_extraction_failure(monkeypatch, tmp_path):
    import orchestrator.services.load_test_lock as load_test_lock
    import orchestrator.workflows.prd_processor as prd_processor
    from orchestrator.workflows.prd_processor import PRDProcessingError

    monkeypatch.setattr(prd_api, "BASE_DIR", tmp_path)
    monkeypatch.setattr(prd_api, "get_browser_pool", _fake_get_browser_pool)
    monkeypatch.setattr(load_test_lock, "check_system_available", _fake_check_system_available)

    class FailingPRDProcessor:
        def process_prd(self, pdf_path, project_name, target_feature_count=15):
            raise PRDProcessingError("AI feature extraction failed for every PRD chunk.", status_code=502)

    monkeypatch.setattr(prd_processor, "PRDProcessor", FailingPRDProcessor)

    app = FastAPI()
    app.include_router(prd_api.router)
    client = TestClient(app)

    response = client.post(
        "/api/prd/upload",
        files={"file": ("wetravel-manage-rooms.pdf", b"%PDF-1.4\n", "application/pdf")},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "AI feature extraction failed for every PRD chunk."


@pytest.mark.asyncio
async def test_list_projects_marks_empty_metadata_as_stale(monkeypatch, tmp_path):
    monkeypatch.setattr(prd_api, "BASE_DIR", tmp_path)
    stale_dir = tmp_path / "prds" / "wetravel-manage-rooms"
    stale_dir.mkdir(parents=True)
    (stale_dir / "metadata.json").write_text(
        json.dumps(
            {
                "project": "wetravel-manage-rooms",
                "features": [],
                "total_chunks": 0,
                "processed_at": "2026-06-07T10:00:00",
            }
        )
    )

    projects = await prd_api.list_projects()

    assert projects == [
        {
            "project": "wetravel-manage-rooms",
            "processed_at": "2026-06-07T10:00:00",
            "total_chunks": 0,
            "feature_count": 0,
            "status": "stale",
            "message": "Previous PRD analysis produced no features. Re-upload the PDF to retry.",
        }
    ]


@pytest.mark.asyncio
async def test_get_features_rejects_empty_stale_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(prd_api, "BASE_DIR", tmp_path)
    stale_dir = tmp_path / "prds" / "wetravel-manage-rooms"
    stale_dir.mkdir(parents=True)
    (stale_dir / "metadata.json").write_text(
        json.dumps({"project": "wetravel-manage-rooms", "features": [], "total_chunks": 0})
    )

    with pytest.raises(prd_api.HTTPException) as exc_info:
        await prd_api.get_features("wetravel-manage-rooms")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Previous PRD analysis produced no features. Re-upload the PDF to retry."


@pytest.mark.asyncio
async def test_import_requirements_creates_rows_for_tenant_project(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[Project.__table__, Requirement.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)
    monkeypatch.setattr(prd_api, "BASE_DIR", tmp_path)

    with Session(engine) as session:
        session.add(Project(id="tenant-project", name="Tenant Project"))
        session.commit()

    prd_dir = tmp_path / "prds" / "prd-project"
    prd_dir.mkdir(parents=True)
    (prd_dir / "metadata.json").write_text(
        json.dumps(
            {
                "tenant_project_id": "metadata-project",
                "features": [
                    {"name": "Checkout", "slug": "checkout", "requirements": ["Users can pay by card."]},
                    {"name": "Account", "slug": "account", "requirements": ["Users can reset passwords."]},
                ],
            }
        )
    )

    response = await prd_api.import_requirements("prd-project", tenant_project_id="tenant-project")

    assert response.created == 2
    assert response.skipped == 0
    assert response.total == 2
    assert [requirement.req_code for requirement in response.requirements] == ["REQ-001", "REQ-002"]

    with Session(engine) as session:
        requirements = session.exec(
            select(Requirement).where(Requirement.project_id == "tenant-project").order_by(Requirement.req_code)
        ).all()
        assert [requirement.title for requirement in requirements] == [
            "Users can pay by card.",
            "Users can reset passwords.",
        ]
        assert requirements[0].description == "Imported from PRD project 'prd-project', feature 'Checkout'."
        assert requirements[0].category == "prd"
        assert requirements[0].priority == "medium"
        assert requirements[0].status == "draft"
        assert requirements[0].truth_state == "candidate_requirement"
        assert requirements[0].source_type == "prd"
        assert requirements[0].confidence == 0.85


@pytest.mark.asyncio
async def test_import_requirements_repeated_import_skips_duplicate_titles(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[Project.__table__, Requirement.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)
    monkeypatch.setattr(prd_api, "BASE_DIR", tmp_path)

    with Session(engine) as session:
        session.add(Project(id="tenant-project", name="Tenant Project"))
        session.commit()

    prd_dir = tmp_path / "prds" / "prd-project"
    prd_dir.mkdir(parents=True)
    (prd_dir / "metadata.json").write_text(
        json.dumps(
            {
                "tenant_project_id": "tenant-project",
                "features": [
                    {"name": "Checkout", "slug": "checkout", "requirements": ["Users can pay by card."]},
                    {"name": "Account", "slug": "account", "requirements": ["Users can reset passwords."]},
                ],
            }
        )
    )

    first = await prd_api.import_requirements("prd-project", tenant_project_id=None)
    second = await prd_api.import_requirements("prd-project", tenant_project_id=None)

    assert first.created == 2
    assert second.created == 0
    assert second.skipped == 2
    assert second.total == 2

    with Session(engine) as session:
        requirements = session.exec(select(Requirement).where(Requirement.project_id == "tenant-project")).all()
        assert len(requirements) == 2


@pytest.mark.asyncio
async def test_import_requirements_rejects_unknown_tenant_project(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[Project.__table__, Requirement.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)
    monkeypatch.setattr(prd_api, "BASE_DIR", tmp_path)

    prd_dir = tmp_path / "prds" / "prd-project"
    prd_dir.mkdir(parents=True)
    (prd_dir / "metadata.json").write_text(
        json.dumps(
            {
                "features": [
                    {"name": "Checkout", "slug": "checkout", "requirements": ["Users can pay by card."]},
                ],
            }
        )
    )

    with pytest.raises(prd_api.HTTPException) as exc_info:
        await prd_api.import_requirements("prd-project", tenant_project_id="missing-project")

    assert exc_info.value.status_code == 404
    assert "Target project 'missing-project' not found" == exc_info.value.detail


@pytest.mark.asyncio
async def test_import_requirements_missing_metadata_returns_404(monkeypatch, tmp_path):
    monkeypatch.setattr(prd_api, "BASE_DIR", tmp_path)

    with pytest.raises(prd_api.HTTPException) as exc_info:
        await prd_api.import_requirements("missing-prd", tenant_project_id="tenant-project")

    assert exc_info.value.status_code == 404


def test_import_requirements_route_is_registered_and_imports(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[Project.__table__, Requirement.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)
    monkeypatch.setattr(prd_api, "BASE_DIR", tmp_path)

    with Session(engine) as session:
        session.add(Project(id="tenant-project", name="Tenant Project"))
        session.commit()

    prd_dir = tmp_path / "prds" / "prd-project"
    prd_dir.mkdir(parents=True)
    (prd_dir / "metadata.json").write_text(
        json.dumps(
            {
                "features": [
                    {"name": "Checkout", "slug": "checkout", "requirements": ["Users can pay by card."]},
                ],
            }
        )
    )

    app = FastAPI()
    app.include_router(prd_api.router)
    client = TestClient(app)

    response = client.post("/api/prd/prd-project/import-requirements?tenant_project_id=tenant-project")

    assert response.status_code == 200
    assert response.json()["created"] == 1
    assert response.json()["total"] == 1

    with Session(engine) as session:
        requirement = session.exec(select(Requirement).where(Requirement.project_id == "tenant-project")).one()
        assert requirement.title == "Users can pay by card."


def test_prd_generation_workspace_uses_headed_mcp_for_live_browser_runs(tmp_path):
    base_dir = tmp_path / "project"
    run_dir = tmp_path / "runs" / "prd-generation-123"
    base_dir.mkdir()
    (base_dir / "playwright.config.ts").write_text(
        """
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || './test-results',
  testMatch: ['generated/**/*.spec.ts', 'e2e/**/*.spec.ts'],
  use: {
    video: 'retain-on-failure',
  },
});
"""
    )

    runtime = _prepare_prd_generation_mcp_workspace(run_dir, base_dir=base_dir, headless=False)

    config = json.loads((run_dir / ".mcp.json").read_text())
    server = config["mcpServers"]["playwright-test"]
    copied_config = (run_dir / "playwright.config.ts").read_text()

    assert "--headless" not in server["args"]
    assert server["env"]["HEADLESS"] == "false"
    assert server["env"]["PLAYWRIGHT_HEADLESS"] == "false"
    assert "headless: runHeaded ? false : undefined" in copied_config
    assert runtime["mcp_args"] == [
        "playwright",
        "run-test-mcp-server",
        "-c",
        str(run_dir / "playwright.config.ts"),
    ]


@pytest.mark.asyncio
async def test_generate_plan_persists_target_url_as_live_browser_intent(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[PrdGenerationResult.__table__, PrdGenerationEvent.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)
    monkeypatch.setattr(prd_api, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(
        prd_api,
        "browser_runtime_status",
        lambda: {
            "browser_runtime": "vnc",
            "live_view_available": True,
            "runtime_message": "Browser will run on the VNC display.",
        },
    )

    started: dict[str, object] = {}

    def fake_run_generation_task(**kwargs):
        started.update(kwargs)
        return object()

    monkeypatch.setattr(prd_api, "_run_generation_task", fake_run_generation_task)
    monkeypatch.setattr(prd_api.asyncio, "create_task", lambda task: task)
    prd_api._running_generations.clear()

    response = await prd_api.generate_plan(
        "prd-project",
        GenerateRequest(feature="Checkout", target_url=" https://example.test "),
        BackgroundTasks(),
    )

    generation_id = response["generation_id"]
    assert response["target_url"] == "https://example.test"
    assert response["live_browser_requested"] is True
    assert response["live_view_available"] is True
    assert started["target_url"] == "https://example.test"

    with Session(engine) as session:
        generation = session.get(PrdGenerationResult, generation_id)
        assert generation is not None
        assert generation.target_url == "https://example.test"
        assert generation.live_browser_requested is True

    prd_api._running_generations.clear()


@pytest.mark.asyncio
async def test_generate_plan_without_target_url_stays_prd_only(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[PrdGenerationResult.__table__, PrdGenerationEvent.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)
    monkeypatch.setattr(prd_api, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(
        prd_api,
        "browser_runtime_status",
        lambda: {
            "browser_runtime": "vnc",
            "live_view_available": True,
            "runtime_message": "Browser will run on the VNC display.",
        },
    )

    started: dict[str, object] = {}

    def fake_run_generation_task(**kwargs):
        started.update(kwargs)
        return object()

    monkeypatch.setattr(prd_api, "_run_generation_task", fake_run_generation_task)
    monkeypatch.setattr(prd_api.asyncio, "create_task", lambda task: task)
    prd_api._running_generations.clear()

    response = await prd_api.generate_plan(
        "prd-project",
        GenerateRequest(feature="Checkout", target_url="   "),
        BackgroundTasks(),
    )

    generation_id = response["generation_id"]
    assert response["target_url"] is None
    assert response["live_browser_requested"] is False
    assert response["live_view_available"] is False
    assert "PRD-only generation" in response["runtime_message"]
    assert started["target_url"] is None

    with Session(engine) as session:
        generation = session.get(PrdGenerationResult, generation_id)
        assert generation is not None
        assert generation.target_url is None
        assert generation.live_browser_requested is False
        status = prd_api._generation_status_response(generation)

    assert status.live_browser_requested is False
    assert status.live_view_available is False
    assert status.vnc_url is None
    assert status.browser_runtime == "prd_only"

    prd_api._running_generations.clear()


def test_prd_only_generation_status_never_reports_live_view(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[PrdGenerationResult.__table__, PrdGenerationEvent.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)
    monkeypatch.setattr(
        prd_api,
        "browser_runtime_status",
        lambda: {
            "browser_runtime": "vnc",
            "live_view_available": True,
            "runtime_message": "Browser will run on the VNC display.",
            "vnc_url": "ws://localhost:6080/websockify",
        },
    )

    with Session(engine) as session:
        generation = PrdGenerationResult(
            prd_project="prd-project",
            feature_name="Checkout",
            status="running",
            target_url=None,
            live_browser_requested=False,
        )
        session.add(generation)
        session.commit()
        session.refresh(generation)
        response = prd_api._generation_status_response(generation)

    assert response.live_browser_requested is False
    assert response.live_view_available is False
    assert response.browser_runtime == "prd_only"
    assert "PRD-only generation" in response.runtime_message
    assert response.vnc_url is None
    assert response.display_diagnostics is None


def test_target_url_is_live_browser_status_source_of_truth(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[PrdGenerationResult.__table__, PrdGenerationEvent.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)
    monkeypatch.setattr(
        prd_api,
        "browser_runtime_status",
        lambda: {
            "browser_runtime": "vnc",
            "live_view_available": True,
            "runtime_message": "Browser will run on the VNC display.",
        },
    )
    monkeypatch.setattr(
        prd_api,
        "live_browser_display_diagnostics",
        lambda: {"browser_window_count": 1, "browser_process_count": 1},
    )

    with Session(engine) as session:
        generation = PrdGenerationResult(
            prd_project="prd-project",
            feature_name="Checkout",
            status="running",
            target_url="https://example.test",
            live_browser_requested=False,
        )
        session.add(generation)
        session.commit()
        session.refresh(generation)
        response = prd_api._generation_status_response(generation)

    assert response.live_browser_requested is True


def test_live_browser_generation_status_uses_runtime_when_target_url_present(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[PrdGenerationResult.__table__, PrdGenerationEvent.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)
    monkeypatch.setattr(
        prd_api,
        "browser_runtime_status",
        lambda: {
            "browser_runtime": "vnc",
            "live_view_available": True,
            "runtime_message": "Browser will run on the VNC display.",
            "vnc_url": "ws://localhost:6080/websockify",
        },
    )
    monkeypatch.setattr(
        prd_api,
        "live_browser_display_diagnostics",
        lambda: {"browser_window_count": 0, "browser_process_count": 1},
    )

    with Session(engine) as session:
        generation = PrdGenerationResult(
            prd_project="prd-project",
            feature_name="Checkout",
            status="running",
            target_url=" https://example.test ",
            live_browser_requested=True,
        )
        session.add(generation)
        session.commit()
        session.refresh(generation)
        response = prd_api._generation_status_response(generation)

    assert response.target_url == "https://example.test"
    assert response.live_browser_requested is True
    assert response.live_view_available is True
    assert response.browser_runtime == "vnc"
    assert response.display_diagnostics == {
        "browser_window_count": 0,
        "browser_process_count": 1,
        "browser_process_seen": True,
        "browser_window_seen": False,
        "probed_at": response.display_diagnostics["probed_at"],
    }
    assert response.browser_activity_seen is False
    assert response.browser_active is False


@pytest.mark.asyncio
async def test_live_browser_status_reports_missing_live_browser_capable_worker(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[PrdGenerationResult.__table__, PrdGenerationEvent.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)
    monkeypatch.setattr(
        prd_api,
        "browser_runtime_status",
        lambda: {
            "browser_runtime": "vnc",
            "live_view_available": True,
            "runtime_message": "Browser will run on the VNC display.",
        },
    )
    monkeypatch.setattr(
        prd_api,
        "live_browser_display_diagnostics",
        lambda: {"browser_window_count": 0, "browser_process_count": 0},
    )

    task = AgentTask(
        id="agent-live-queued",
        prompt="inspect",
        status=AgentTaskStatus.QUEUED,
        requires_live_browser=True,
    )

    class FakeQueue:
        async def connect(self):
            return None

        async def get_task(self, task_id: str):
            return task if task_id == task.id else None

        async def get_worker_health(self):
            return {
                "worker_count": 1,
                "live_browser_worker_count": 0,
                "non_live_browser_worker_count": 1,
            }

        async def get_task_progress(self, task_id: str):
            return {}

    monkeypatch.setattr(agent_queue_module, "REDIS_AVAILABLE", True)
    monkeypatch.setattr(agent_queue_module, "should_use_agent_queue", lambda: True)
    monkeypatch.setattr(agent_queue_module, "get_agent_queue", lambda: FakeQueue())

    with Session(engine) as session:
        generation = PrdGenerationResult(
            prd_project="prd-project",
            feature_name="Checkout",
            status="running",
            target_url="https://example.test",
            live_browser_requested=True,
        )
        session.add(generation)
        session.commit()
        session.refresh(generation)
        generation_id = generation.id
        event = PrdGenerationEvent(
            generation_id=generation_id,
            sequence=1,
            role="playwright_planner",
            event_type="task_enqueued",
            message="Planner task enqueued.",
        )
        event.payload = {"agent_task_id": task.id}
        session.add(event)
        session.commit()
        response = await prd_api._generation_status_response_with_queue(generation)

    assert response.agent_task_id == task.id
    assert response.agent_task_status == "queued"
    assert response.agent_queue_health["live_browser_worker_count"] == 0
    assert "No live-browser-capable agent worker" in response.runtime_message


def test_generation_status_surfaces_non_browser_last_tool(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[PrdGenerationResult.__table__, PrdGenerationEvent.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)
    monkeypatch.setattr(
        prd_api,
        "browser_runtime_status",
        lambda: {
            "browser_runtime": "vnc",
            "live_view_available": True,
            "runtime_message": "Browser will run on the VNC display.",
        },
    )
    monkeypatch.setattr(
        prd_api,
        "live_browser_display_diagnostics",
        lambda: {"browser_window_count": 0, "browser_process_count": 0},
    )

    with Session(engine) as session:
        generation = PrdGenerationResult(
            prd_project="prd-project",
            feature_name="Checkout",
            status="running",
            target_url="https://example.test",
            live_browser_requested=True,
        )
        session.add(generation)
        session.commit()
        session.refresh(generation)
        event = PrdGenerationEvent(
            generation_id=generation.id,
            sequence=1,
            role="playwright_planner",
            event_type="planner_profile_violation",
            level="error",
            message="Planner profile violation: live PRD planner used Read.",
        )
        event.payload = {"tool_label": "Read"}
        session.add(event)
        session.commit()
        response = prd_api._generation_status_response(generation)

    assert response.browser_last_tool == "Read"
    assert response.browser_activity_seen is False


def test_failed_prd_generation_event_includes_enriched_diagnostics(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[PrdGenerationResult.__table__, PrdGenerationEvent.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)

    with Session(engine) as session:
        generation = PrdGenerationResult(
            prd_project="prd-project",
            feature_name="Checkout",
            status="running",
        )
        session.add(generation)
        session.commit()
        session.refresh(generation)
        generation_id = generation.id

    prd_api._fail_generation(
        generation_id,
        "Failed to generate spec: agent produced no output",
        payload={
            "messages_received": 0,
            "text_blocks_received": 0,
            "tool_calls": 0,
            "timed_out": False,
            "agent_error": None,
            "expected_output_path": "/tmp/checkout.md",
        },
    )

    with Session(engine) as session:
        generation = session.get(PrdGenerationResult, generation_id)
        event = session.exec(
            select(PrdGenerationEvent).where(PrdGenerationEvent.generation_id == generation_id)
        ).one()

    assert generation.status == "failed"
    assert generation.error_message == "Failed to generate spec: agent produced no output"
    assert event.event_type == "failed"
    assert event.message == generation.error_message
    assert event.payload["messages_received"] == 0
    assert event.payload["text_blocks_received"] == 0
    assert event.payload["tool_calls"] == 0
    assert event.payload["expected_output_path"] == "/tmp/checkout.md"


def test_generation_artifacts_include_planner_debug_files(tmp_path, monkeypatch):
    monkeypatch.setattr(prd_api, "RUNS_DIR", tmp_path)
    run_dir = tmp_path / "prd-generation-7"
    run_dir.mkdir()
    (run_dir / "raw_output.txt").write_text("")
    (run_dir / "tool_calls.json").write_text("[]")
    (run_dir / "agent_summary.json").write_text("{}")

    artifacts = prd_api._collect_generation_artifacts(7)
    names = {artifact["name"] for artifact in artifacts}

    assert {"raw_output.txt", "tool_calls.json", "agent_summary.json"}.issubset(names)


def test_prd_task_enqueued_persists_agent_task_id(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[PrdGenerationResult.__table__, PrdGenerationEvent.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)

    with Session(engine) as session:
        generation = PrdGenerationResult(prd_project="prd-project", feature_name="Checkout", status="running")
        session.add(generation)
        session.commit()
        session.refresh(generation)
        generation_id = generation.id

    prd_api._persist_generation_agent_task_id(generation_id, "agent-persisted")

    with Session(engine) as session:
        generation = session.get(PrdGenerationResult, generation_id)
        assert generation.agent_task_id == "agent-persisted"
        assert prd_api._generation_status_response(generation).agent_task_id == "agent-persisted"


def test_prd_agent_task_id_falls_back_to_legacy_task_enqueued_event(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[PrdGenerationResult.__table__, PrdGenerationEvent.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)

    with Session(engine) as session:
        generation = PrdGenerationResult(prd_project="prd-project", feature_name="Checkout", status="running")
        session.add(generation)
        session.commit()
        session.refresh(generation)
        generation_id = generation.id
        event = PrdGenerationEvent(
            generation_id=generation_id,
            sequence=1,
            role="playwright_planner",
            event_type="task_enqueued",
            message="Planner task enqueued.",
        )
        event.payload = {"agent_task_id": "agent-legacy"}
        session.add(event)
        session.commit()

    assert prd_api._generation_agent_task_id(generation_id) == "agent-legacy"


@pytest.mark.asyncio
async def test_prd_reconciliation_keeps_fresh_queue_task_running(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[PrdGenerationResult.__table__, PrdGenerationEvent.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)
    monkeypatch.setattr(
        prd_api,
        "browser_runtime_status",
        lambda: {"browser_runtime": "vnc", "live_view_available": True, "runtime_message": "ok"},
    )
    monkeypatch.setattr(
        prd_api,
        "live_browser_display_diagnostics",
        lambda: {"browser_window_count": 1, "browser_process_count": 1},
    )

    task = AgentTask(
        id="agent-running",
        prompt="inspect",
        status=AgentTaskStatus.RUNNING,
        worker_id="worker-1",
        requires_live_browser=True,
    )
    heartbeat_at = "2026-06-07T12:00:00"

    class FakeQueue:
        async def connect(self):
            return None

        async def get_task(self, task_id: str):
            return task if task_id == task.id else None

        async def get_worker_health(self):
            return {"worker_count": 1, "live_browser_worker_count": 1, "running_tasks": 1, "alive_tasks": 1}

        async def get_task_heartbeat(self, task_id: str):
            return {"ts": heartbeat_at, "progress": {"phase": "tool_use", "message": "Using browser_snapshot...", "last_tool": "browser_snapshot"}}

        async def get_task_progress(self, task_id: str):
            return {"tool_calls": 1, "last_tool": "browser_snapshot"}

        async def check_heartbeat(self, task_id: str, max_stale_seconds: int = 120):
            return True

    monkeypatch.setattr(agent_queue_module, "REDIS_AVAILABLE", True)
    monkeypatch.setattr(agent_queue_module, "should_use_agent_queue", lambda: True)
    monkeypatch.setattr(agent_queue_module, "get_agent_queue", lambda: FakeQueue())

    with Session(engine) as session:
        generation = PrdGenerationResult(
            prd_project="prd-project",
            feature_name="Checkout",
            status="running",
            target_url="https://example.test",
            live_browser_requested=True,
            agent_task_id=task.id,
        )
        session.add(generation)
        session.commit()
        session.refresh(generation)
        generation_id = generation.id

    with Session(engine) as session:
        generation = session.get(PrdGenerationResult, generation_id)
        response = await prd_api._generation_status_response_with_queue(generation)

    assert response.status == "running"
    assert response.current_stage == "tool_use"
    assert response.stage_message == "Using browser_snapshot..."
    assert response.agent_task_id == task.id
    assert response.agent_task_status == "running"
    assert response.agent_worker_id == "worker-1"
    assert response.queue_telemetry["heartbeat_alive"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("queue_status", "expected_status"),
    [
        (AgentTaskStatus.FAILED, "failed"),
        (AgentTaskStatus.TIMEOUT, "failed"),
        (AgentTaskStatus.CANCELLED, "cancelled"),
    ],
)
async def test_prd_reconciliation_maps_terminal_queue_status(monkeypatch, queue_status, expected_status):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[PrdGenerationResult.__table__, PrdGenerationEvent.__table__])
    monkeypatch.setattr(prd_api, "engine", engine)
    monkeypatch.setattr(
        prd_api,
        "browser_runtime_status",
        lambda: {"browser_runtime": "vnc", "live_view_available": True, "runtime_message": "ok"},
    )
    monkeypatch.setattr(
        prd_api,
        "live_browser_display_diagnostics",
        lambda: {"browser_window_count": 0, "browser_process_count": 0},
    )

    task = AgentTask(
        id=f"agent-{queue_status.value}",
        prompt="inspect",
        status=queue_status,
        worker_id="worker-1",
        error=f"queue {queue_status.value}",
        telemetry={"tool_calls": 2},
        requires_live_browser=True,
    )

    class FakeQueue:
        async def connect(self):
            return None

        async def get_task(self, task_id: str):
            return task if task_id == task.id else None

        async def get_worker_health(self):
            return {"worker_count": 1, "live_browser_worker_count": 1}

        async def get_task_heartbeat(self, task_id: str):
            return None

        async def get_task_progress(self, task_id: str):
            return {}

        async def check_heartbeat(self, task_id: str, max_stale_seconds: int = 120):
            return False

        async def fail_stale_running_task(self, task_id: str, error: str):
            return True

    monkeypatch.setattr(agent_queue_module, "REDIS_AVAILABLE", True)
    monkeypatch.setattr(agent_queue_module, "should_use_agent_queue", lambda: True)
    monkeypatch.setattr(agent_queue_module, "get_agent_queue", lambda: FakeQueue())

    with Session(engine) as session:
        generation = PrdGenerationResult(
            prd_project="prd-project",
            feature_name="Checkout",
            status="running",
            target_url="https://example.test",
            live_browser_requested=True,
            agent_task_id=task.id,
        )
        session.add(generation)
        session.commit()
        session.refresh(generation)
        generation_id = generation.id

    with Session(engine) as session:
        generation = session.get(PrdGenerationResult, generation_id)
        response = await prd_api._generation_status_response_with_queue(generation)
        event = session.exec(
            select(PrdGenerationEvent)
            .where(PrdGenerationEvent.generation_id == generation_id)
            .order_by(PrdGenerationEvent.sequence.desc())
        ).first()

    assert response.status == expected_status
    if expected_status == "failed":
        assert response.error_message == task.error
    else:
        assert response.stage_message == task.error
    assert event is not None
    assert event.event_type == expected_status
    assert event.payload["agent_task_id"] == task.id
