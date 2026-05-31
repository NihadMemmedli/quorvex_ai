import json
import sys
from pathlib import Path

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import orchestrator.api.prd as prd_api
from orchestrator.services import agent_queue as agent_queue_module
from orchestrator.api.models_db import PrdGenerationEvent, PrdGenerationResult
from orchestrator.api.prd import GenerateRequest, _prepare_prd_generation_mcp_workspace
from orchestrator.services.agent_queue import AgentTask, AgentTaskStatus
from orchestrator.utils.agent_tool_allowlists import get_agent_allowed_tools


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
        event = PrdGenerationEvent(
            generation_id=generation.id,
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
