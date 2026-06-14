"""
API endpoint tests for the Quorvex AI platform.

Tests cover:
- 404 responses for non-existent resources
- 422 responses for invalid request bodies
- Pagination edge cases
- Health check endpoints
- Error response sanitization (no Python tracebacks in responses)

Run with: JWT_SECRET_KEY=test pytest orchestrator/tests/test_api_endpoints.py -v
"""

import json
import os
import shutil
import sys
import types
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

# Ensure test environment
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-api-tests")
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

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi.testclient import TestClient
from sqlmodel import Session, select


@pytest.fixture(scope="module")
def client():
    """Create a test client for the API."""
    from orchestrator.api.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestHealthEndpoints:
    """Test health check endpoints."""

    def test_health_returns_200(self, client):
        """GET /health should always return 200."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "checks" in data

    def test_health_includes_database_check(self, client):
        """Health check should include database status."""
        response = client.get("/health")
        data = response.json()
        assert "database" in data["checks"]
        assert "status" in data["checks"]["database"]

    def test_health_storage_returns_200(self, client):
        """GET /health/storage should return storage health."""
        response = client.get("/health/storage")
        assert response.status_code == 200
        data = response.json()
        assert "database" in data
        assert "local_storage" in data

    def test_health_response_has_request_id(self, client):
        """Responses should include X-Request-ID header."""
        response = client.get("/health")
        assert "x-request-id" in response.headers


class TestRunEndpoints:
    """Test run-related endpoints."""

    def test_get_nonexistent_run_returns_404(self, client):
        """GET /runs/{id} with non-existent ID should return 404."""
        response = client.get("/runs/nonexistent-run-id-12345")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_list_runs_default_pagination(self, client):
        """GET /runs should return paginated results."""
        response = client.get("/runs")
        assert response.status_code == 200
        data = response.json()
        # Should have pagination fields
        assert "total" in data
        assert "runs" in data or "items" in data

    def test_list_runs_with_limit(self, client):
        """GET /runs with limit parameter should respect it."""
        response = client.get("/runs?limit=5")
        assert response.status_code == 200
        data = response.json()
        runs = data.get("runs", data.get("items", []))
        assert len(runs) <= 5

    def test_list_runs_with_offset(self, client):
        """GET /runs with offset should work."""
        response = client.get("/runs?offset=0&limit=5")
        assert response.status_code == 200

    def test_list_runs_limit_capped_at_100(self, client):
        """GET /runs with limit > 100 should be capped."""
        response = client.get("/runs?limit=500")
        assert response.status_code == 200

    def test_list_runs_with_project_filter(self, client):
        """GET /runs with project_id filter should work."""
        response = client.get("/runs?project_id=default")
        assert response.status_code == 200

    def test_stop_nonexistent_run_returns_404(self, client):
        """POST /runs/{id}/stop with non-existent ID should return 404."""
        response = client.post("/runs/nonexistent-run-id/stop")
        assert response.status_code == 404

    def test_get_active_run_status_wins_over_failed_validation(self, client):
        """GET /runs/{id} should keep active DB status despite stale validation failure."""
        from orchestrator.api import main as main_module
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import TestRun as DBTestRun

        run_id = f"active-validation-precedence-{uuid4()}"

        with Session(engine) as session:
            session.add(
                DBTestRun(
                    id=run_id,
                    spec_name="active-validation-precedence.md",
                    status="running",
                    created_at=datetime.utcnow(),
                    test_name="Active validation precedence",
                )
            )
            session.commit()

        try:
            run_dir = main_module.RUNS_DIR / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "validation.json").write_text(json.dumps({"status": "failed"}))

            response = client.get(f"/runs/{run_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "running"
            assert data["effective_status"] == "running"
            assert data["validation"]["status"] == "failed"
        finally:
            shutil.rmtree(main_module.RUNS_DIR / run_id, ignore_errors=True)
            with Session(engine) as session:
                run = session.get(DBTestRun, run_id)
                if run:
                    session.delete(run)
                    session.commit()

    def test_get_completed_run_uses_failed_validation_status(self, client):
        """GET /runs/{id} should use validation failure once the DB run is finalized."""
        from orchestrator.api import main as main_module
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import TestRun as DBTestRun

        run_id = f"completed-validation-precedence-{uuid4()}"

        with Session(engine) as session:
            session.add(
                DBTestRun(
                    id=run_id,
                    spec_name="completed-validation-precedence.md",
                    status="completed",
                    created_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                    test_name="Completed validation precedence",
                )
            )
            session.commit()

        try:
            run_dir = main_module.RUNS_DIR / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "validation.json").write_text(json.dumps({"status": "failed"}))

            response = client.get(f"/runs/{run_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "completed"
            assert data["effective_status"] == "failed"
            assert data["validation"]["status"] == "failed"
        finally:
            shutil.rmtree(main_module.RUNS_DIR / run_id, ignore_errors=True)
            with Session(engine) as session:
                run = session.get(DBTestRun, run_id)
                if run:
                    session.delete(run)
                    session.commit()


class TestAgentRunHistoryEndpoints:
    def _cleanup(self, run_ids: list[str]) -> None:
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AgentRun, AgentRunEvent

        with Session(engine) as session:
            for run_id in run_ids:
                for event in session.exec(select(AgentRunEvent).where(AgentRunEvent.run_id == run_id)).all():
                    session.delete(event)
                run = session.get(AgentRun, run_id)
                if run:
                    session.delete(run)
            session.commit()

    def _seed_history_runs(self, marker: str) -> list[str]:
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AgentRun, AgentRunEvent

        run_ids = [f"agent-history-{marker}-{index}" for index in range(5)]
        self._cleanup(run_ids)
        with Session(engine) as session:
            for index, run_id in enumerate(run_ids):
                session.add(
                    AgentRun(
                        id=run_id,
                        agent_type="custom" if index % 2 else "exploratory",
                        runtime="claude_sdk",
                        status="completed" if index < 3 else "failed",
                        created_at=datetime(2026, 1, 1, 12, index, 0),
                        config_json=json.dumps({"url": f"https://example.test/{marker}/{index}", "agent_name": f"{marker} agent"}),
                        result_json=json.dumps({"summary": "large summary", "payload": "x" * 5000}),
                        progress_json=json.dumps({"message": f"{marker} progress {index}"}),
                        project_id=None,
                    )
                )
            session.add(
                AgentRunEvent(
                    id=f"agent-history-event-{marker}",
                    run_id=run_ids[0],
                    sequence=1,
                    event_type="completed",
                    level="info",
                    message="completed",
                    payload_json="{}",
                    created_at=datetime(2026, 1, 1, 12, 10, 0),
                )
            )
            session.commit()
        return run_ids

    def test_agent_runs_history_is_paged_compact_and_filterable(self, client):
        marker = f"marker-{uuid4().hex[:8]}"
        run_ids = self._seed_history_runs(marker)
        try:
            response = client.get(f"/api/agents/runs?project_id=default&limit=2&q={marker}&status=completed&agent_type=exploratory")
            assert response.status_code == 200
            data = response.json()
            assert set(data) >= {"items", "total", "counts", "next_cursor"}
            assert data["total"] == 2
            assert len(data["items"]) == 2
            assert data["counts"]["status"]["completed"] == 3
            assert all(item["agent_type"] == "exploratory" for item in data["items"])
            assert all(item["status"] == "completed" for item in data["items"])
            assert all("result" not in item and "artifacts" not in item and "health" not in item for item in data["items"])
            assert all(item["summary"].startswith(marker) for item in data["items"])
        finally:
            self._cleanup(run_ids)

    def test_agent_runs_history_cursor_does_not_duplicate_rows(self, client):
        marker = f"cursor-{uuid4().hex[:8]}"
        run_ids = self._seed_history_runs(marker)
        try:
            first = client.get(f"/api/agents/runs?project_id=default&limit=2&q={marker}")
            assert first.status_code == 200
            first_data = first.json()
            assert first_data["next_cursor"]

            second = client.get(f"/api/agents/runs?project_id=default&limit=2&q={marker}&cursor={first_data['next_cursor']}")
            assert second.status_code == 200
            second_data = second.json()
            first_ids = [item["id"] for item in first_data["items"]]
            second_ids = [item["id"] for item in second_data["items"]]
            assert len(first_ids) == 2
            assert len(second_ids) == 2
            assert set(first_ids).isdisjoint(second_ids)
        finally:
            self._cleanup(run_ids)

    def test_agent_run_detail_keeps_full_result_and_health(self, client):
        marker = f"detail-{uuid4().hex[:8]}"
        run_ids = self._seed_history_runs(marker)
        try:
            response = client.get(f"/api/agents/runs/{run_ids[0]}?project_id=default")
            assert response.status_code == 200
            data = response.json()
            assert data["result"]["payload"].startswith("x")
            assert "artifacts" in data
            assert "health" in data
            assert data["health"]["event_count"] >= 1
        finally:
            self._cleanup(run_ids)


class TestAgentDefinitionEndpoints:
    """Test UI-created custom agent definition endpoints."""

    def test_create_list_and_archive_agent_definition(self, client):
        """POST /api/agents/definitions should persist custom agents without server errors."""
        name = f"API Save Probe {uuid4().hex}"
        payload = {
            "project_id": "default",
            "name": name,
            "description": "Created by an API regression test.",
            "system_prompt": "Inspect the target and report concise QA findings.",
            "runtime": "claude_sdk",
            "model_tier": "tool_deep",
            "timeout_seconds": 900,
            "tool_ids": ["browser_snapshot", "browser_console", "browser_network"],
        }

        create_response = client.post("/api/agents/definitions", json=payload)
        assert create_response.status_code == 200, create_response.text
        created = create_response.json()
        definition_id = created["id"]

        try:
            assert created["name"] == name
            assert created["runtime"] == "claude_sdk"
            assert created["model_tier"] == "tool_deep"
            assert created["timeout_seconds"] == 900
            assert created["tool_ids"] == payload["tool_ids"]

            list_response = client.get("/api/agents/definitions?project_id=default")
            assert list_response.status_code == 200, list_response.text
            definitions = list_response.json()
            assert any(definition["id"] == definition_id for definition in definitions)
        finally:
            archive_response = client.delete(f"/api/agents/definitions/{definition_id}?project_id=default")
            assert archive_response.status_code == 200, archive_response.text

    def test_get_run_includes_live_browser_metadata(self, client, monkeypatch):
        """GET /runs/{id} should expose runtime metadata for live browser view."""
        from orchestrator.api import main as main_module
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import TestRun as DBTestRun

        run_id = f"live-browser-metadata-{uuid4()}"
        monkeypatch.setattr(
            main_module,
            "browser_runtime_status",
            lambda: {
                "browser_runtime": "temporal_vnc_worker",
                "live_view_available": True,
                "runtime_message": "Browser execution is delegated to the live browser worker.",
                "vnc_url": "ws://localhost:6080/websockify",
            },
        )

        with Session(engine) as session:
            session.add(
                DBTestRun(
                    id=run_id,
                    spec_name="live-browser-metadata.md",
                    status="running",
                    created_at=datetime.utcnow(),
                    test_name="Live Browser Metadata",
                )
            )
            session.commit()

        try:
            response = client.get(f"/runs/{run_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["browser_runtime"] == "temporal_vnc_worker"
            assert data["live_view_available"] is True
            assert data["runtime_message"] == "Browser execution is delegated to the live browser worker."
            assert data["vnc_url"] == "ws://localhost:6080/websockify"

            run_dir = main_module.RUNS_DIR / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "execution.log").write_text("started")
            detail_response = client.get(f"/runs/{run_id}")
            assert detail_response.status_code == 200
            detail_data = detail_response.json()
            assert detail_data["browser_runtime"] == "temporal_vnc_worker"
            assert detail_data["live_view_available"] is True
            assert detail_data["runtime_message"] == "Browser execution is delegated to the live browser worker."
            assert detail_data["vnc_url"] == "ws://localhost:6080/websockify"
        finally:
            shutil.rmtree(main_module.RUNS_DIR / run_id, ignore_errors=True)
            with Session(engine) as session:
                run = session.get(DBTestRun, run_id)
                if run:
                    session.delete(run)
                    session.commit()

    def test_get_run_includes_log_diagnostics_without_execution_log(self, client, monkeypatch):
        """GET /runs/{id} should expose DB and browser-pool diagnostics before execution.log exists."""
        from orchestrator.api import main as main_module
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import TestRun as DBTestRun

        class _Pool:
            async def get_status(self):
                return {
                    "max_browsers": 1,
                    "running": 1,
                    "queued": 1,
                    "available": 0,
                    "running_requests": [run_id],
                    "queued_requests": ["agent:agent-child"],
                    "running_details": [
                        {
                            "request_id": run_id,
                            "operation_type": "test_run",
                            "description": "Test run",
                            "started_at": "2026-05-30T00:00:00+00:00",
                        }
                    ],
                    "by_type": {"test_run": 1},
                }

        run_id = f"log-diagnostics-{uuid4()}"
        monkeypatch.setattr(main_module, "BROWSER_POOL", _Pool())

        with Session(engine) as session:
            session.add(
                DBTestRun(
                    id=run_id,
                    spec_name="log-diagnostics.md",
                    status="running",
                    created_at=datetime.utcnow(),
                    current_stage="planning",
                    stage_message="Planning test steps",
                )
            )
            session.commit()

        try:
            run_dir = main_module.RUNS_DIR / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            response = client.get(f"/runs/{run_id}")
            assert response.status_code == 200
            data = response.json()
            assert "Run Lifecycle" in data["log"]
            assert "status=running" in data["log"]
            assert "Browser Pool" in data["log"]
            assert data["blocker_message"] == "Planner agent is waiting for browser slot held by parent run."
            assert any(section["title"] == "Browser Pool" for section in data["log_sections"])
        finally:
            shutil.rmtree(main_module.RUNS_DIR / run_id, ignore_errors=True)
            with Session(engine) as session:
                run = session.get(DBTestRun, run_id)
                if run:
                    session.delete(run)
                    session.commit()

    def test_get_run_surfaces_pipeline_error_without_stale_browser_blocker(self, client, monkeypatch):
        """Terminal pipeline failures should show root-cause logs instead of stale browser queue blockers."""
        from orchestrator.api import main as main_module
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import TestRun as DBTestRun

        class _Pool:
            async def get_status(self):
                return {
                    "max_browsers": 1,
                    "running": 0,
                    "queued": 1,
                    "available": 1,
                    "running_requests": [],
                    "queued_requests": [run_id],
                    "by_type": {},
                }

        run_id = f"pipeline-error-{uuid4()}"
        error_msg = "Missing required @testdata refs: wetravel-auth.valid-user (dataset_not_found)"
        monkeypatch.setattr(main_module, "BROWSER_POOL", _Pool())

        with Session(engine) as session:
            session.add(
                DBTestRun(
                    id=run_id,
                    spec_name="missing-testdata.md",
                    status="failed",
                    created_at=datetime.utcnow(),
                    current_stage="running",
                    stage_message="Running native pipeline",
                )
            )
            session.commit()

        try:
            run_dir = main_module.RUNS_DIR / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "status.txt").write_text("failed")
            (run_dir / "pipeline_error.json").write_text(
                json.dumps(
                    {
                        "stage": "test_data_resolution",
                        "error": error_msg,
                        "refs": ["wetravel-auth.valid-user"],
                        "missing_test_data": [
                            {
                                "ref": "wetravel-auth.valid-user",
                                "reason": "dataset_not_found",
                            }
                        ],
                    }
                )
            )

            response = client.get(f"/runs/{run_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["error_message"] == f"[test_data_resolution] {error_msg}"
            assert data["blocker_message"] is None
            assert "Pipeline Error" in data["log"]
            assert "Test Data" in data["log"]
            assert "missing_refs=wetravel-auth.valid-user (dataset_not_found)" in data["log"]
            assert "Test run is waiting for a browser slot" not in data["log"]
            assert any(section["title"] == "Pipeline Error" for section in data["log_sections"])
            assert any(section["title"] == "Test Data" for section in data["log_sections"])
        finally:
            shutil.rmtree(main_module.RUNS_DIR / run_id, ignore_errors=True)
            with Session(engine) as session:
                run = session.get(DBTestRun, run_id)
                if run:
                    session.delete(run)
                    session.commit()

    def test_update_agentic_summary_and_get_run(self, client):
        """POST /runs/{id}/agentic-summary should persist compact summary."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import TestRun as DBTestRun

        run_id = f"agentic-summary-{uuid4()}"
        summary = {
            "schema_version": "1.0",
            "design": {"flake_risk": "high"},
            "critic": {"issue_count": 2},
            "diagnosis": {"category": "timing", "heal_allowed": True},
            "stability": {"status": "stable", "total_runs": 2},
            "costs": {"total_usd": 0.42, "by_stage": {"native_generator": {"cost_usd": 0.42}}},
        }

        with Session(engine) as session:
            session.add(
                DBTestRun(
                    id=run_id,
                    spec_name="agentic-summary-test.md",
                    status="passed",
                    created_at=datetime.utcnow(),
                    test_name="agentic-summary-test.md",
                )
            )
            session.commit()

        try:
            response = client.post(f"/runs/{run_id}/agentic-summary", json={"summary": summary})
            assert response.status_code == 200
            assert response.json()["agentic_summary"]["design"]["flake_risk"] == "high"

            detail_response = client.get(f"/runs/{run_id}")
            assert detail_response.status_code == 200
            assert detail_response.json()["agentic_summary"]["stability"]["status"] == "stable"
            with Session(engine) as session:
                persisted = session.get(DBTestRun, run_id)
                assert persisted.total_cost_usd == 0.42
        finally:
            with Session(engine) as session:
                run = session.get(DBTestRun, run_id)
                if run:
                    session.delete(run)
                    session.commit()


class TestAgentRunControlEndpoints:
    """Test autonomous agent pause/resume API endpoints."""

    def test_get_agent_run_merges_and_normalizes_live_queue_progress(self, client, monkeypatch):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AgentRun

        run_id = f"agent-live-progress-{uuid4()}"
        task_id = f"agent-task-{uuid4()}"

        class FakeQueue:
            async def connect(self):
                return None

            async def get_task_progress(self, value: str):
                assert value == task_id
                return {
                    "phase": "tool_use",
                    "last_tool": "mcp__playwright__browser_click",
                    "tool_calls": "3",
                    "browser_tool_calls": "2",
                    "interactions": "2",
                    "message": "Clicking checkout",
                }

        monkeypatch.setattr("orchestrator.services.agent_queue.get_agent_queue", lambda: FakeQueue())

        with Session(engine) as session:
            run = AgentRun(
                id=run_id,
                agent_type="custom",
                status="running",
                agent_task_id=task_id,
                config_json='{"prompt":"inspect"}',
            )
            run.progress = {
                "phase": "queued",
                "tool_calls": 0,
                "browser_tool_calls": 0,
                "message": "Queued",
            }
            session.add(run)
            session.commit()

        try:
            response = client.get(f"/api/agents/runs/{run_id}")
            assert response.status_code == 200
            progress = response.json()["progress"]
            assert progress["phase"] == "tool_use"
            assert progress["message"] == "Clicking checkout"
            assert progress["tool_calls"] == 3
            assert progress["browser_tool_calls"] == 2
            assert progress["interactions"] == 2
            assert progress["last_tool"] == "mcp__playwright__browser_click"
            assert progress["current_tool"] == "mcp__playwright__browser_click"
            assert progress["last_tool_label"] == "browser_click"
            assert progress["current_tool_label"] == "browser_click"
        finally:
            with Session(engine) as session:
                run = session.get(AgentRun, run_id)
                if run:
                    session.delete(run)
                    session.commit()

    def test_cancel_run_before_task_exists(self, client):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AgentRun

        run_id = f"agent-control-{uuid4()}"
        with Session(engine) as session:
            run = AgentRun(id=run_id, agent_type="custom", status="running", config_json='{"prompt":"inspect"}')
            session.add(run)
            session.commit()

        try:
            response = client.post(f"/api/agents/runs/{run_id}/cancel")
            assert response.status_code == 200
            cancelled = response.json()
            assert cancelled["status"] == "cancelled"
            assert cancelled["progress"]["phase"] == "cancelled"
            assert cancelled["progress"]["cancelled_from"] == "running"
        finally:
            with Session(engine) as session:
                run = session.get(AgentRun, run_id)
                if run:
                    session.delete(run)
                    session.commit()

    def test_cancel_paused_run_before_task_exists(self, client):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AgentRun

        run_id = f"agent-control-{uuid4()}"
        with Session(engine) as session:
            run = AgentRun(id=run_id, agent_type="custom", status="paused", config_json='{"prompt":"inspect"}')
            run.progress = {"phase": "paused", "status": "paused", "paused_from": "running"}
            session.add(run)
            session.commit()

        try:
            response = client.post(f"/api/agents/runs/{run_id}/cancel")
            assert response.status_code == 200
            cancelled = response.json()
            assert cancelled["status"] == "cancelled"
            assert cancelled["progress"]["phase"] == "cancelled"
            assert cancelled["progress"]["cancelled_from"] == "paused"
        finally:
            with Session(engine) as session:
                run = session.get(AgentRun, run_id)
                if run:
                    session.delete(run)
                    session.commit()

    def test_cancel_completed_agent_run_returns_conflict(self, client):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AgentRun

        run_id = f"agent-control-{uuid4()}"
        with Session(engine) as session:
            run = AgentRun(id=run_id, agent_type="custom", status="completed", config_json="{}")
            session.add(run)
            session.commit()

        try:
            response = client.post(f"/api/agents/runs/{run_id}/cancel")
            assert response.status_code == 409
            data = response.json()
            assert "detail" in data
        finally:
            with Session(engine) as session:
                run = session.get(AgentRun, run_id)
                if run:
                    session.delete(run)
                    session.commit()

    def test_pause_resume_run_before_task_exists(self, client):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AgentRun

        run_id = f"agent-control-{uuid4()}"
        with Session(engine) as session:
            run = AgentRun(id=run_id, agent_type="custom", status="running", config_json='{"prompt":"inspect"}')
            session.add(run)
            session.commit()

        pause_response = client.post(f"/api/agents/runs/{run_id}/pause")
        assert pause_response.status_code == 200
        paused = pause_response.json()
        assert paused["status"] == "paused"
        assert paused["progress"]["phase"] == "paused"
        assert paused["progress"]["paused_from"] == "running"

        resume_response = client.post(f"/api/agents/runs/{run_id}/resume")
        assert resume_response.status_code == 200
        resumed = resume_response.json()
        assert resumed["status"] == "running"
        assert resumed["progress"]["phase"] == "resumed"

        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            if run:
                session.delete(run)
                session.commit()

    def test_pause_completed_agent_run_returns_conflict(self, client):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AgentRun

        run_id = f"agent-control-{uuid4()}"
        with Session(engine) as session:
            run = AgentRun(id=run_id, agent_type="custom", status="completed", config_json="{}")
            session.add(run)
            session.commit()

        response = client.post(f"/api/agents/runs/{run_id}/pause")
        assert response.status_code == 409
        data = response.json()
        assert "detail" in data

        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            if run:
                session.delete(run)
                session.commit()


class TestSpecEndpoints:
    """Test spec-related endpoints."""

    def test_get_nonexistent_spec_returns_404(self, client):
        """GET /specs/{name} with non-existent spec should return 404."""
        response = client.get("/specs/nonexistent-spec-name-xyz")
        assert response.status_code == 404

    def test_list_specs_returns_200(self, client):
        """GET /specs/list should return spec listing."""
        response = client.get("/specs/list")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_list_specs_with_project_filter(self, client):
        """GET /specs/list with project_id filter should work."""
        response = client.get("/specs/list?project_id=default")
        assert response.status_code == 200

    def test_split_spec_regex_returns_extraction_metadata(self, client, tmp_path, monkeypatch):
        """POST /specs/split should report regex extraction when explicitly selected."""
        from orchestrator.api import main as main_module

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        (specs_dir / "multi.md").write_text(
            """# Test: First flow

## Source
Test ID: TC-001
Category: Happy Path

## Steps
1. Navigate to /

## Expected Outcome
- First flow succeeds

# Test: Second flow

## Source
Test ID: TC-002
Category: Happy Path

## Steps
1. Click Continue

## Expected Outcome
- Second flow succeeds
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(main_module, "SPECS_DIR", specs_dir)

        response = client.post(
            "/specs/split",
            json={"spec_name": "multi.md", "mode": "individual", "extraction_method": "regex"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert data["extraction_method"] == "regex"
        assert data["ai_used"] is False
        assert data["warning"] is None

    def test_split_spec_rejects_regex_grouped_mode(self, client, tmp_path, monkeypatch):
        """Smart Groups require AI extraction."""
        from orchestrator.api import main as main_module

        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        (specs_dir / "multi.md").write_text(
            """# Test: First flow

## Source
Test ID: TC-001
Category: Happy Path

# Test: Second flow

## Source
Test ID: TC-002
Category: Happy Path
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(main_module, "SPECS_DIR", specs_dir)

        response = client.post(
            "/specs/split",
            json={"spec_name": "multi.md", "mode": "grouped", "extraction_method": "regex"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Smart Groups requires AI extraction."

    def test_list_specs_excludes_templates_by_default_and_can_return_templates(self, client, tmp_path, monkeypatch):
        """GET /specs/list should keep templates separate unless templates_only=true."""
        from orchestrator.api import main as main_module

        specs_dir = tmp_path / "specs"
        (specs_dir / "templates").mkdir(parents=True)
        (specs_dir / "regular.md").write_text("# Regular\n", encoding="utf-8")
        (specs_dir / "templates" / "example.md").write_text("# Template\n", encoding="utf-8")
        monkeypatch.setattr(main_module, "SPECS_DIR", specs_dir)

        response = client.get("/specs/list")
        assert response.status_code == 200
        names = {item["name"] for item in response.json()["items"]}
        assert "regular.md" in names
        assert "templates/example.md" not in names

        response = client.get("/specs/list?templates_only=true")
        assert response.status_code == 200
        names = {item["name"] for item in response.json()["items"]}
        assert "templates/example.md" in names
        assert "regular.md" not in names

    def test_list_templates_respects_project_filter(self, client, tmp_path, monkeypatch):
        """GET /specs/list?templates_only=true should preserve project filtering."""
        from orchestrator.api import main as main_module
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import SpecMetadata as DBSpecMetadata
        from orchestrator.api.models_db import get_spec_metadata

        project_id = f"template-project-{uuid4()}"
        included_name = f"templates/{uuid4()}.md"
        excluded_name = f"templates/{uuid4()}.md"

        specs_dir = tmp_path / "specs"
        (specs_dir / "templates").mkdir(parents=True)
        (specs_dir / included_name).write_text("# Project Template\n", encoding="utf-8")
        (specs_dir / excluded_name).write_text("# Other Template\n", encoding="utf-8")
        monkeypatch.setattr(main_module, "SPECS_DIR", specs_dir)

        with Session(engine) as session:
            session.add(DBSpecMetadata(spec_name=included_name, project_id=project_id, tags_json='["template"]'))
            session.add(DBSpecMetadata(spec_name=excluded_name, project_id=f"other-{project_id}", tags_json='["template"]'))
            session.commit()

        try:
            response = client.get(f"/specs/list?templates_only=true&project_id={project_id}")
            assert response.status_code == 200
            names = {item["name"] for item in response.json()["items"]}
            assert included_name in names
            assert excluded_name not in names
        finally:
            with Session(engine) as session:
                for spec_name in (included_name, excluded_name):
                    meta = get_spec_metadata(session, spec_name, project_id if spec_name == included_name else f"other-{project_id}")
                    if meta:
                        session.delete(meta)
                session.commit()

    def test_list_specs_includes_autopilot_spec_only_for_registered_project(self, client, tmp_path, monkeypatch):
        """Autopilot specs are visible only through the project recorded in SpecMetadata."""
        from orchestrator.api import main as main_module
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import Project, SpecMetadata, get_spec_metadata

        project_id = f"wetravel-project-{uuid4().hex}"
        session_id = f"autopilot_{uuid4().hex}"
        spec_name = f"autopilot/{session_id}/checkout-flow.md"
        specs_dir = tmp_path / "specs"
        (specs_dir / "autopilot" / session_id).mkdir(parents=True)
        (specs_dir / spec_name).write_text("# Checkout Flow\n", encoding="utf-8")
        monkeypatch.setattr(main_module, "SPECS_DIR", specs_dir)

        with Session(engine) as session:
            session.add(Project(id=project_id, name="Wetravel Project"))
            session.add(SpecMetadata(spec_name=spec_name, project_id=project_id, tags_json="[]"))
            session.commit()

        try:
            project_response = client.get(f"/specs/list?project_id={project_id}")
            assert project_response.status_code == 200
            project_names = {item["name"] for item in project_response.json()["items"]}
            assert spec_name in project_names

            default_response = client.get("/specs/list?project_id=default")
            assert default_response.status_code == 200
            default_names = {item["name"] for item in default_response.json()["items"]}
            assert spec_name not in default_names
        finally:
            with Session(engine) as session:
                meta = get_spec_metadata(session, spec_name, project_id)
                if meta:
                    session.delete(meta)
                project = session.get(Project, project_id)
                if project:
                    session.delete(project)
                session.commit()

    def test_create_spec_missing_name(self, client):
        """POST /specs with missing name should return 422."""
        response = client.post("/specs", json={"content": "# Test"})
        assert response.status_code == 422

    def test_create_spec_missing_content(self, client):
        """POST /specs with missing content should return 422."""
        response = client.post("/specs", json={"name": "test"})
        assert response.status_code == 422

    def test_create_spec_empty_body(self, client):
        """POST /specs with empty body should return 422."""
        response = client.post("/specs", json={})
        assert response.status_code == 422

    def test_delete_nonexistent_spec_returns_404(self, client):
        """DELETE /specs/{name} with non-existent spec should return 404."""
        response = client.delete("/specs/nonexistent-spec-name-xyz")
        assert response.status_code == 404

    def test_get_spec_folders(self, client):
        """GET /specs/folders should return folder tree."""
        response = client.get("/specs/folders")
        assert response.status_code == 200

    def test_get_automated_specs(self, client):
        """GET /specs/automated should return automated specs."""
        response = client.get("/specs/automated")
        assert response.status_code == 200

    def test_get_spec_generated_code_nonexistent(self, client):
        """GET /specs/{name}/generated-code for non-existent spec."""
        response = client.get("/specs/nonexistent-spec/generated-code")
        assert response.status_code in (404, 200)  # May return empty or 404


class TestProjectEndpoints:
    """Test project-related endpoints."""

    def test_list_projects(self, client):
        """GET /projects should return project list."""
        response = client.get("/projects")
        assert response.status_code == 200
        data = response.json()
        assert "projects" in data
        assert isinstance(data["projects"], list)

    def test_get_default_project(self, client):
        """GET /projects/default should return the default project."""
        response = client.get("/projects/default")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "default"

    def test_create_project_accepts_valid_base_url(self, client):
        """POST /projects should persist a valid project base URL."""
        name = f"Project Base URL {uuid4().hex}"
        response = client.post(
            "/projects",
            json={
                "name": name,
                "description": "Project with default app URL",
                "base_url": "  https://pre.wetravel.to/  ",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        try:
            assert data["name"] == name
            assert data["base_url"] == "https://pre.wetravel.to/"
        finally:
            client.delete(f"/projects/{data['id']}")

    def test_create_project_allows_blank_and_omitted_base_url(self, client):
        """POST /projects should allow empty or omitted base_url."""
        created_ids: list[str] = []
        try:
            omitted_response = client.post("/projects", json={"name": f"Omitted Base URL {uuid4().hex}"})
            assert omitted_response.status_code == 200, omitted_response.text
            omitted = omitted_response.json()
            created_ids.append(omitted["id"])
            assert omitted["base_url"] is None

            blank_response = client.post(
                "/projects",
                json={"name": f"Blank Base URL {uuid4().hex}", "base_url": "   "},
            )
            assert blank_response.status_code == 200, blank_response.text
            blank = blank_response.json()
            created_ids.append(blank["id"])
            assert blank["base_url"] is None
        finally:
            for project_id in created_ids:
                client.delete(f"/projects/{project_id}")

    def test_project_base_url_rejects_invalid_urls(self, client):
        """Project create and update should reject malformed base URLs."""
        create_response = client.post(
            "/projects",
            json={"name": f"Invalid Base URL {uuid4().hex}", "base_url": "ftp://example.com"},
        )
        assert create_response.status_code == 422

        name = f"Invalid Update Base URL {uuid4().hex}"
        response = client.post("/projects", json={"name": name, "base_url": "https://example.com"})
        assert response.status_code == 200, response.text
        project_id = response.json()["id"]
        try:
            update_response = client.put(f"/projects/{project_id}", json={"base_url": "not-a-url"})
            assert update_response.status_code == 422

            clear_response = client.put(f"/projects/{project_id}", json={"base_url": ""})
            assert clear_response.status_code == 200, clear_response.text
            assert clear_response.json()["base_url"] is None
        finally:
            client.delete(f"/projects/{project_id}")

    def test_get_nonexistent_project_returns_404(self, client):
        """GET /projects/{id} with non-existent ID should return 404."""
        response = client.get("/projects/nonexistent-project-xyz")
        assert response.status_code == 404

    def test_delete_default_project_rejected(self, client):
        """DELETE /projects/default should be rejected."""
        response = client.delete("/projects/default")
        # Should reject deletion of default project
        assert response.status_code in (400, 403, 422)

    def test_delete_nonexistent_project_returns_404(self, client):
        """DELETE /projects/{id} with non-existent ID should return 404."""
        response = client.delete("/projects/nonexistent-project-xyz")
        assert response.status_code == 404

    def test_delete_project_reassigns_content_and_removes_ancillary_rows(self, client):
        """DELETE /projects/{id} should preserve core content and remove scoped ancillary rows."""
        from orchestrator.api.db import engine
        from orchestrator.api.models_auth import ProjectMember, User
        from orchestrator.api.models_db import (
            DiscoveredFlow,
            ExplorationSession,
            FlowStep,
            Project,
            RegressionBatch,
            SpecMetadata,
            TestRun,
            get_spec_metadata,
        )
        from orchestrator.api.projects import ensure_default_project

        suffix = uuid4().hex
        project_id = f"delete-project-{suffix}"
        spec_name = f"delete-project-{suffix}.md"
        run_id = f"delete-run-{suffix}"
        batch_id = f"delete-batch-{suffix}"
        exploration_id = f"delete-exploration-{suffix}"
        user_id = f"delete-user-{suffix}"
        flow_id = None
        step_id = None

        with Session(engine) as session:
            ensure_default_project(session)
            session.add(Project(id=project_id, name=f"Delete Project {suffix}"))
            session.add(SpecMetadata(spec_name=spec_name, project_id=project_id))
            session.add(RegressionBatch(id=batch_id, name="Delete Batch", project_id=project_id))
            session.add(
                TestRun(
                    id=run_id,
                    spec_name=spec_name,
                    status="passed",
                    batch_id=batch_id,
                    project_id=project_id,
                )
            )
            session.add(
                User(
                    id=user_id,
                    email=f"delete-project-{suffix}@example.com",
                    password_hash="test-password-hash",
                )
            )
            session.add(ProjectMember(project_id=project_id, user_id=user_id, role="admin"))
            session.add(ExplorationSession(id=exploration_id, project_id=project_id, entry_url="https://example.com"))
            session.commit()

            flow = DiscoveredFlow(
                session_id=exploration_id,
                project_id=project_id,
                flow_name="Delete Flow",
                flow_category="navigation",
                start_url="https://example.com",
                end_url="https://example.com/done",
                step_count=1,
            )
            session.add(flow)
            session.commit()
            session.refresh(flow)
            flow_id = flow.id

            step = FlowStep(
                flow_id=flow_id,
                step_number=1,
                action_type="click",
                action_description="Click continue",
            )
            session.add(step)
            session.commit()
            session.refresh(step)
            step_id = step.id

        try:
            response = client.delete(f"/projects/{project_id}")
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["project_id"] == project_id
            assert data["reassigned_to"] == "default"
            assert data["reassigned_specs"] == 1
            assert data["reassigned_runs"] == 1
            assert data["reassigned_batches"] == 1
            assert data["deleted_ancillary_rows"]["project_members"] == 1
            assert data["deleted_ancillary_rows"]["exploration_sessions"] == 1
            assert data["deleted_ancillary_rows"]["discovered_flows"] == 1
            assert data["deleted_ancillary_rows"]["flow_steps"] == 1

            with Session(engine) as session:
                assert session.get(Project, project_id) is None
                assert get_spec_metadata(session, spec_name, "default").project_id == "default"
                assert session.get(TestRun, run_id).project_id == "default"
                assert session.get(RegressionBatch, batch_id).project_id == "default"
                membership = session.exec(
                    select(ProjectMember).where(
                        ProjectMember.project_id == project_id,
                        ProjectMember.user_id == user_id,
                    )
                ).first()
                assert membership is None
                assert session.get(ExplorationSession, exploration_id) is None
                assert session.get(DiscoveredFlow, flow_id) is None
                assert session.get(FlowStep, step_id) is None
        finally:
            with Session(engine) as session:
                membership = session.exec(
                    select(ProjectMember).where(
                        ProjectMember.project_id == project_id,
                        ProjectMember.user_id == user_id,
                    )
                ).first()
                if membership:
                    session.delete(membership)

                spec_meta = get_spec_metadata(session, spec_name, "default")
                if spec_meta:
                    session.delete(spec_meta)

                for model, key in (
                    (FlowStep, step_id),
                    (DiscoveredFlow, flow_id),
                    (ExplorationSession, exploration_id),
                    (TestRun, run_id),
                    (RegressionBatch, batch_id),
                    (Project, project_id),
                    (User, user_id),
                ):
                    if key is None:
                        continue
                    obj = session.get(model, key)
                    if obj:
                        session.delete(obj)
                session.commit()


class TestExecutionSettings:
    """Test execution settings endpoints."""

    def test_get_execution_settings(self, client):
        """GET /execution-settings should return current settings."""
        response = client.get("/execution-settings")
        assert response.status_code == 200
        data = response.json()
        assert "parallelism" in data

    def test_update_execution_settings_invalid_parallelism(self, client):
        """PUT /execution-settings with invalid parallelism should be handled."""
        response = client.put("/execution-settings", json={"parallelism": -1})
        # Should either reject or clamp to valid range
        assert response.status_code in (200, 422)


class TestAISettings:
    """Test runtime AI settings endpoints."""

    def test_update_settings_applies_runtime_env_and_clears_multi_key_rotation(self, client, tmp_path, monkeypatch):
        """POST /settings should persist and immediately apply the selected AI settings."""
        from orchestrator.api import settings as settings_api

        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "ANTHROPIC_AUTH_TOKEN=old-key",
                    "ANTHROPIC_API_KEY=old-key",
                    "ANTHROPIC_AUTH_TOKENS=old-key,backup-key",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL=old-model",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL=old-model",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL=old-model",
                    "ANTHROPIC_MODEL=old-model",
                    "ANTHROPIC_BASE_URL=https://api.anthropic.com",
                ]
            )
            + "\n"
        )
        monkeypatch.setattr(settings_api, "ENV_FILE", env_file)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "old-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "old-key")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKENS", "old-key,backup-key")

        class FakeRotator:
            initialized = False

            def initialize(self):
                self.initialized = True

        fake_rotator = FakeRotator()
        monkeypatch.setattr(
            "orchestrator.services.api_key_rotator.get_api_key_rotator",
            lambda: fake_rotator,
        )

        response = client.post(
            "/settings",
            json={
                "llm_provider": "anthropic",
                "api_key": "new-key-123456",
                "base_url": "https://api.anthropic.com/",
                "model_name": "claude-test-model",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Settings saved and applied."
        assert data["settings"]["api_key"] == "new-******3456"
        assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "new-key-123456"
        assert os.environ["ANTHROPIC_API_KEY"] == "new-key-123456"
        assert "ANTHROPIC_AUTH_TOKENS" not in os.environ
        assert os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "claude-test-model"
        assert os.environ["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "old-model"
        assert os.environ["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "old-model"
        assert os.environ["ANTHROPIC_MODEL"] == "claude-test-model"
        assert os.environ["ANTHROPIC_CHAT_MODEL"] == "claude-test-model"
        assert os.environ["QUORVEX_LLM_STANDARD_MODEL"] == "claude-test-model"
        assert os.environ["QUORVEX_LLM_CHAT_MODEL"] == "claude-test-model"
        assert fake_rotator.initialized is True

        env_vars = settings_api._read_env_file()
        assert env_vars["ANTHROPIC_AUTH_TOKEN"] == "new-key-123456"
        assert env_vars["ANTHROPIC_API_KEY"] == "new-key-123456"
        assert env_vars["ANTHROPIC_AUTH_TOKENS"] == ""
        assert env_vars["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "claude-test-model"
        assert env_vars["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "old-model"
        assert env_vars["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "old-model"
        assert env_vars["ANTHROPIC_MODEL"] == "claude-test-model"
        assert env_vars["ANTHROPIC_CHAT_MODEL"] == "claude-test-model"
        assert env_vars["QUORVEX_LLM_STANDARD_MODEL"] == "claude-test-model"
        assert env_vars["QUORVEX_LLM_CHAT_MODEL"] == "claude-test-model"
        assert env_vars["QUORVEX_AGENT_RUNTIME"] == "claude_sdk"
        assert env_vars["HERMES_SYNC_PROVIDER"] == "true"
        assert env_vars["HERMES_UPSTREAM_PROVIDER"] == "anthropic"
        assert env_vars["HERMES_UPSTREAM_MODEL"] == "claude-test-model"

        hermes_dir = tmp_path / "data" / "hermes"
        assert (hermes_dir / ".env").read_text()
        hermes_config = (hermes_dir / "config.yaml").read_text()
        assert 'provider: "anthropic"' in hermes_config
        assert 'default: "claude-test-model"' in hermes_config

    def test_update_settings_can_configure_hermes_runtime_and_openrouter_provider(self, client, tmp_path, monkeypatch):
        """Settings should produce a Hermes home bundle that mirrors Quorvex's selected provider."""
        from orchestrator.api import settings as settings_api

        env_file = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_AUTH_TOKEN=old-key\nANTHROPIC_BASE_URL=https://api.anthropic.com\n")
        monkeypatch.setattr(settings_api, "ENV_FILE", env_file)
        monkeypatch.delenv("HERMES_ENABLED", raising=False)
        monkeypatch.delenv("HERMES_API_URL", raising=False)
        monkeypatch.delenv("HERMES_API_KEY", raising=False)

        response = client.post(
            "/settings",
            json={
                "llm_provider": "openrouter",
                "api_key": "sk-or-v1-test",
                "base_url": "https://openrouter.ai/api",
                "model_name": "anthropic/claude-sonnet-4.6",
                "agent_runtime": "hermes",
                "hermes_enabled": True,
                "hermes_api_url": "http://localhost:8642/",
                "hermes_api_key": "local-hermes-key",
                "hermes_model": "quorvex-hermes",
                "hermes_sync_provider": True,
            },
        )

        assert response.status_code == 200
        data = response.json()["settings"]
        assert data["agent_runtime"] == "hermes"
        assert data["hermes_enabled"] is True
        assert data["hermes_upstream_provider"] == "openrouter"
        assert data["hermes_upstream_model"] == "anthropic/claude-sonnet-4.6"

        env_vars = settings_api._read_env_file()
        assert env_vars["QUORVEX_AGENT_RUNTIME"] == "hermes"
        assert env_vars["HERMES_ENABLED"] == "true"
        assert env_vars["HERMES_API_URL"] == "http://localhost:8642"
        assert env_vars["HERMES_API_KEY"] == "local-hermes-key"
        assert env_vars["HERMES_MODEL"] == "quorvex-hermes"
        assert env_vars["HERMES_UPSTREAM_PROVIDER"] == "openrouter"

        hermes_env = (tmp_path / "data" / "hermes" / ".env").read_text()
        hermes_config = (tmp_path / "data" / "hermes" / "config.yaml").read_text()
        assert "API_SERVER_KEY=local-hermes-key" in hermes_env
        assert "OPENROUTER_API_KEY=sk-or-v1-test" in hermes_env
        assert 'provider: "openrouter"' in hermes_config
        assert 'default: "anthropic/claude-sonnet-4.6"' in hermes_config

    def test_update_settings_persists_separate_assistant_runtime_and_openai_provider(self, client, tmp_path, monkeypatch):
        """Settings should allow assistant chat runtime to differ from backend agent runs."""
        from orchestrator.api import settings as settings_api

        env_file = tmp_path / ".env"
        env_file.write_text("QUORVEX_AGENT_RUNTIME=claude_sdk\nQUORVEX_ASSISTANT_RUNTIME=claude_sdk\n")
        monkeypatch.setattr(settings_api, "ENV_FILE", env_file)
        monkeypatch.delenv("HERMES_ENABLED", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        response = client.post(
            "/settings",
            json={
                "llm_provider": "openai",
                "api_key": "sk-openai-test",
                "base_url": "https://api.openai.com/v1",
                "model_name": "gpt-4o-mini",
                "agent_runtime": "claude_sdk",
                "assistant_runtime": "openai",
                "hermes_enabled": True,
                "hermes_api_url": "http://hermes:8642",
                "hermes_api_key": "local-hermes-key",
                "hermes_model": "hermes-agent",
                "hermes_sync_provider": True,
            },
        )

        assert response.status_code == 200
        data = response.json()["settings"]
        assert data["llm_provider"] == "openai"
        assert data["agent_runtime"] == "claude_sdk"
        assert data["assistant_runtime"] == "openai"
        assert data["hermes_upstream_provider"] == "openai"
        assert data["hermes_upstream_model"] == "gpt-4o-mini"

        env_vars = settings_api._read_env_file()
        assert env_vars["QUORVEX_AGENT_RUNTIME"] == "claude_sdk"
        assert env_vars["QUORVEX_ASSISTANT_RUNTIME"] == "openai"
        assert env_vars["QUORVEX_LLM_PROVIDER"] == "openai"
        assert env_vars["OPENAI_API_KEY"] == "sk-openai-test"
        assert env_vars["OPENAI_BASE_URL"] == "https://api.openai.com/v1"

        hermes_env = (tmp_path / "data" / "hermes" / ".env").read_text()
        hermes_config = (tmp_path / "data" / "hermes" / "config.yaml").read_text()
        assert "API_SERVER_KEY=local-hermes-key" in hermes_env
        assert "OPENAI_API_KEY=sk-openai-test" in hermes_env
        assert 'provider: "openai"' in hermes_config

    def test_settings_test_hermes_reports_gateway_and_generated_config(self, client, tmp_path, monkeypatch):
        """POST /settings/test-hermes should validate both Hermes API and generated config files."""
        from orchestrator.api import settings as settings_api

        hermes_home = tmp_path / "hermes"
        hermes_home.mkdir()
        (hermes_home / "config.yaml").write_text('model:\n  provider: "openai"\n  default: "gpt-4o-mini"\n')
        (hermes_home / ".env").write_text("API_SERVER_KEY=local-hermes-key\nOPENAI_API_KEY=sk-openai-test\n")
        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "HERMES_ENABLED=true",
                    "HERMES_API_URL=http://hermes:8642",
                    "HERMES_API_KEY=local-hermes-key",
                    "HERMES_MODEL=hermes-agent",
                    f"HERMES_HOME={hermes_home}",
                    "HERMES_UPSTREAM_PROVIDER=openai",
                    "HERMES_UPSTREAM_MODEL=gpt-4o-mini",
                ]
            )
            + "\n"
        )
        monkeypatch.setattr(settings_api, "ENV_FILE", env_file)
        monkeypatch.setattr(
            settings_api,
            "_check_hermes_gateway",
            lambda active=None: {
                "reachable": True,
                "status": "reachable",
                "message": "Hermes API responded with HTTP 200.",
            },
        )

        response = client.post("/settings/test-hermes")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["reachable"] is True
        assert data["upstream_provider"] == "openai"
        assert data["upstream_model"] == "gpt-4o-mini"
        assert data["config_exists"] is True
        assert data["env_exists"] is True

    def test_update_settings_uses_configured_writable_env_file(self, client, tmp_path, monkeypatch):
        """Container settings should persist to a writable runtime env file when configured."""
        from orchestrator.api import settings as settings_api

        runtime_env = tmp_path / "runtime" / "runtime.env"
        monkeypatch.setenv("QUORVEX_SETTINGS_ENV_FILE", str(runtime_env))
        monkeypatch.setattr(settings_api, "ENV_FILE", tmp_path / "readonly-root" / ".env")
        monkeypatch.delenv("HERMES_ENABLED", raising=False)

        response = client.post(
            "/settings",
            json={
                "llm_provider": "zai",
                "api_key": "zai-key",
                "base_url": "https://api.z.ai/api/anthropic",
                "model_name": "glm-5.1",
                "agent_runtime": "hermes",
                "hermes_enabled": True,
                "hermes_api_url": "http://hermes:8642",
                "hermes_model": "hermes-agent",
                "hermes_sync_provider": True,
            },
        )

        assert response.status_code == 200
        env_vars = settings_api._read_env_file()
        assert runtime_env.exists()
        assert not (tmp_path / "readonly-root" / ".env").exists()
        assert env_vars["HERMES_ENABLED"] == "true"
        assert env_vars["QUORVEX_AGENT_RUNTIME"] == "hermes"
        assert env_vars["HERMES_API_URL"] == "http://hermes:8642"
        assert (tmp_path / "runtime" / "hermes" / "config.yaml").exists()

    def test_agent_runner_refreshes_runtime_ai_settings(self, tmp_path, monkeypatch):
        """Backend agent workflows should use the same active AI settings as chat/settings."""
        from orchestrator.api import settings as settings_api
        from orchestrator.utils.agent_runner import AgentRunner

        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "ANTHROPIC_AUTH_TOKEN=runner-key",
                    "ANTHROPIC_API_KEY=runner-key",
                    "ANTHROPIC_MODEL=runner-model",
                    "ANTHROPIC_BASE_URL=https://proxy.example.com",
                ]
            )
            + "\n"
        )
        monkeypatch.setattr(settings_api, "ENV_FILE", env_file)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

        AgentRunner._apply_active_ai_settings()

        assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "runner-key"
        assert os.environ["ANTHROPIC_API_KEY"] == "runner-key"
        assert os.environ["ANTHROPIC_MODEL"] == "runner-model"
        assert os.environ["ANTHROPIC_BASE_URL"] == "https://proxy.example.com"

    def test_update_settings_masked_api_key_preserves_existing_secret(self, client, tmp_path, monkeypatch):
        """Submitting a masked key should not overwrite the real stored key."""
        from orchestrator.api import settings as settings_api

        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "ANTHROPIC_AUTH_TOKEN=real-existing-key",
                    "ANTHROPIC_API_KEY=real-existing-key",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL=old-model",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL=old-model",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL=old-model",
                    "ANTHROPIC_MODEL=old-model",
                    "ANTHROPIC_BASE_URL=https://api.anthropic.com",
                ]
            )
            + "\n"
        )
        monkeypatch.setattr(settings_api, "ENV_FILE", env_file)
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "real-existing-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "real-existing-key")

        response = client.post(
            "/settings",
            json={
                "llm_provider": "anthropic",
                "api_key": "real*********key",
                "base_url": "https://api.anthropic.com",
                "model_name": "new-model",
            },
        )

        assert response.status_code == 200
        env_vars = settings_api._read_env_file()
        assert env_vars["ANTHROPIC_AUTH_TOKEN"] == "real-existing-key"
        assert env_vars["ANTHROPIC_API_KEY"] == "real-existing-key"
        assert env_vars["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "new-model"
        assert env_vars["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "old-model"
        assert env_vars["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "old-model"
        assert env_vars["ANTHROPIC_MODEL"] == "new-model"
        assert env_vars["ANTHROPIC_CHAT_MODEL"] == "new-model"
        assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "real-existing-key"
        assert os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "new-model"
        assert os.environ["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "old-model"
        assert os.environ["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "old-model"
        assert os.environ["ANTHROPIC_MODEL"] == "new-model"

    def test_settings_test_connection_uses_active_runtime_settings(self, client, tmp_path, monkeypatch):
        """POST /settings/test-connection should make a minimal provider request without exposing keys."""
        from orchestrator.api import settings as settings_api

        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "ANTHROPIC_AUTH_TOKEN=test-secret-key",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL=claude-test-model",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL=claude-test-model",
                    "ANTHROPIC_MODEL=claude-test-model",
                    "ANTHROPIC_BASE_URL=https://api.anthropic.com",
                ]
            )
            + "\n"
        )
        monkeypatch.setattr(settings_api, "ENV_FILE", env_file)

        calls = []

        class FakeResponse:
            status_code = 200
            text = '{"ok":true}'

        class FakeClient:
            def __init__(self, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, headers, json):
                calls.append({"url": url, "headers": headers, "json": json})
                return FakeResponse()

        monkeypatch.setattr(settings_api.httpx, "AsyncClient", FakeClient)

        response = client.post("/settings/test-connection")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["model_name"] == "claude-test-model"
        assert data["base_url"] == "https://api.anthropic.com"
        assert data["message"] == "Connection successful."
        assert calls[0]["url"] == "https://api.anthropic.com/v1/messages"
        assert calls[0]["headers"]["x-api-key"] == "test-secret-key"
        assert calls[0]["json"]["model"] == "claude-test-model"

    def test_settings_detects_zai_provider_and_uses_anthropic_messages_endpoint(self, client, tmp_path, monkeypatch):
        """Z.ai should be treated as an Anthropic-compatible provider."""
        from orchestrator.api import settings as settings_api

        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "ANTHROPIC_AUTH_TOKEN=zai-secret-key",
                    "ANTHROPIC_MODEL=glm-5.1",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL=glm-5.1",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL=glm-5-turbo",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL=glm-4.5-air",
                    "ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic",
                ]
            )
            + "\n"
        )
        monkeypatch.setattr(settings_api, "ENV_FILE", env_file)

        calls = []

        class FakeResponse:
            status_code = 200
            text = '{"ok":true}'

        class FakeClient:
            def __init__(self, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, headers, json):
                calls.append({"url": url, "headers": headers, "json": json})
                return FakeResponse()

        monkeypatch.setattr(settings_api.httpx, "AsyncClient", FakeClient)

        settings_response = client.get("/settings")
        assert settings_response.status_code == 200
        assert settings_response.json()["llm_provider"] == "zai"

        response = client.post("/settings/test-connection")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["model_name"] == "glm-5.1"
        assert data["base_url"] == "https://api.z.ai/api/anthropic"
        assert calls[0]["url"] == "https://api.z.ai/api/anthropic/v1/messages"
        assert calls[0]["headers"]["x-api-key"] == "zai-secret-key"
        assert calls[0]["json"]["model"] == "glm-5.1"

    def test_settings_test_connection_uses_claude_code_when_api_key_missing(self, client, tmp_path, monkeypatch):
        """POST /settings/test-connection should support local Claude Code subscription auth."""
        from orchestrator.api import settings as settings_api

        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "ANTHROPIC_AUTH_TOKEN=",
                    "ANTHROPIC_API_KEY=",
                    "CLAUDE_CODE_OAUTH_TOKEN=",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL=claude-sonnet-4-6",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-4-6",
                    "ANTHROPIC_MODEL=claude-sonnet-4-6",
                    "ANTHROPIC_BASE_URL=https://api.anthropic.com",
                ]
            )
            + "\n"
        )
        monkeypatch.setattr(settings_api, "ENV_FILE", env_file)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKENS", raising=False)

        runner_calls = []

        class FakeResult:
            success = True
            error = None

        class FakeRunner:
            def __init__(self, timeout_seconds, allowed_tools, log_tools, model_tier=None):
                runner_calls.append(
                    {
                        "timeout_seconds": timeout_seconds,
                        "allowed_tools": allowed_tools,
                        "log_tools": log_tools,
                        "model_tier": model_tier,
                    }
                )

            async def run(self, prompt, timeout_override=None):
                runner_calls.append({"prompt": prompt, "timeout_override": timeout_override})
                return FakeResult()

        monkeypatch.setattr("orchestrator.utils.agent_runner.AgentRunner", FakeRunner)

        response = client.post("/settings/test-connection")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["model_name"] == "claude-sonnet-4-6"
        assert data["message"] == "Claude Code connection successful."
        assert runner_calls[0]["allowed_tools"] == []
        assert runner_calls[0]["model_tier"] == "chat"
        assert runner_calls[1]["timeout_override"] == 30

    def test_get_settings_prefers_active_agent_model_over_sonnet_default(self, client, tmp_path, monkeypatch):
        """GET /settings should display the actual agent model override when present."""
        from orchestrator.api import settings as settings_api

        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "ANTHROPIC_AUTH_TOKEN=test-secret-key",
                    "ANTHROPIC_MODEL=claude-opus-4-7",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL=claude-opus-4-7",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-4-6",
                    "ANTHROPIC_BASE_URL=https://api.anthropic.com",
                ]
            )
            + "\n"
        )
        monkeypatch.setattr(settings_api, "ENV_FILE", env_file)

        response = client.get("/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["model_name"] == "claude-opus-4-7"

    def test_get_settings_falls_back_to_opus_before_sonnet_default(self, client, tmp_path, monkeypatch):
        """GET /settings should prefer the Opus default over Sonnet when no active override exists."""
        from orchestrator.api import settings as settings_api

        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "ANTHROPIC_AUTH_TOKEN=test-secret-key",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL=claude-opus-4-7",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-4-6",
                    "ANTHROPIC_BASE_URL=https://api.anthropic.com",
                ]
            )
            + "\n"
        )
        monkeypatch.setattr(settings_api, "ENV_FILE", env_file)

        response = client.get("/settings")

        assert response.status_code == 200
        data = response.json()
        assert data["model_name"] == "claude-opus-4-7"


class TestQueueEndpoints:
    """Test queue-related endpoints."""

    def test_get_queue_status(self, client):
        """GET /queue-status should return queue information."""
        response = client.get("/queue-status")
        assert response.status_code == 200
        data = response.json()
        assert "running_count" in data or "running" in data

    def test_agent_queue_status_excludes_stale_running_tasks(
        self, client, monkeypatch
    ):
        """GET /api/agents/queue-status should count only live running tasks as active."""
        import orchestrator.api.main as main_module
        import orchestrator.services.agent_queue as agent_queue_module

        class FakeQueue:
            async def connect(self):
                return None

            async def get_metrics(self):
                return {
                    "queue_length": 0,
                    "running": 1,
                    "workers_alive": 2,
                    "stale_running": 1,
                    "oldest_queued_age_seconds": None,
                    "by_status": {"running": 1},
                }

            async def get_worker_health(self):
                return {
                    "worker_count": 2,
                    "alive_tasks": 0,
                }

            async def get_running_task_summaries(self):
                return [
                    {
                        "id": "agent-stale-running",
                        "status": "running",
                        "heartbeat_alive": False,
                        "live": False,
                        "orphaned": True,
                    }
                ]

        class FakeBrowserPool:
            async def get_status(self):
                return {
                    "running": 0,
                    "max_browsers": 3,
                    "available": 3,
                    "by_type": {"agent": 0},
                }

        monkeypatch.setattr(agent_queue_module, "REDIS_AVAILABLE", True)
        monkeypatch.setattr(agent_queue_module, "should_use_agent_queue", lambda: True)
        monkeypatch.setattr(agent_queue_module, "get_agent_queue", lambda: FakeQueue())
        monkeypatch.setattr(main_module, "BROWSER_POOL", FakeBrowserPool())

        response = client.get("/api/agents/queue-status")

        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "redis"
        assert data["active"] == 0
        assert data["raw_running"] == 1
        assert data["running_tasks"] == []
        assert data["stale_running"] == 1
        assert data["orphaned_tasks"] == 1
        assert data["workers_busy"] == 0
        assert data["workers_idle"] == 2

    def test_agent_queue_status_includes_persisted_active_agent_runs(
        self, client, monkeypatch
    ):
        """GET /api/agents/queue-status should surface active AgentRun rows in Redis mode."""
        import orchestrator.api.main as main_module
        import orchestrator.services.agent_queue as agent_queue_module
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AgentRun

        run_id = f"agent-queue-active-{uuid4()}"

        class FakeQueue:
            async def connect(self):
                return None

            async def get_metrics(self):
                return {
                    "queue_length": 0,
                    "running": 0,
                    "workers_alive": 1,
                    "stale_running": 0,
                    "oldest_queued_age_seconds": None,
                    "by_status": {},
                }

            async def get_worker_health(self):
                return {
                    "worker_count": 1,
                    "alive_tasks": 0,
                }

            async def get_running_task_summaries(self):
                return []

        class FakeBrowserPool:
            async def get_status(self):
                return {
                    "running": 0,
                    "max_browsers": 3,
                    "available": 3,
                    "by_type": {"agent": 0},
                }

        monkeypatch.setattr(agent_queue_module, "REDIS_AVAILABLE", True)
        monkeypatch.setattr(agent_queue_module, "should_use_agent_queue", lambda: True)
        monkeypatch.setattr(agent_queue_module, "get_agent_queue", lambda: FakeQueue())
        monkeypatch.setattr(main_module, "BROWSER_POOL", FakeBrowserPool())

        with Session(engine) as session:
            run = AgentRun(
                id=run_id,
                agent_type="custom",
                status="running",
                started_at=datetime(2026, 1, 1, 12, 0, 0),
                config_json='{"prompt":"inspect"}',
            )
            run.progress = {"phase": "running", "message": "Inspecting checkout"}
            session.add(run)
            session.commit()

        try:
            response = client.get("/api/agents/queue-status")

            assert response.status_code == 200
            data = response.json()
            assert data["mode"] == "redis"
            assert data["active"] == 1
            assert data["active_runs"] == 1
            assert data["queue_tasks_active"] == 0
            assert data["queued"] == 0
            assert data["running_tasks"][0]["id"] == run_id
            assert data["running_tasks"][0]["agent_type"] == "custom"
            assert data["running_tasks"][0]["status"] == "running"
            assert data["running_tasks"][0]["progress"]["message"] == "Inspecting checkout"
        finally:
            with Session(engine) as session:
                run = session.get(AgentRun, run_id)
                if run:
                    session.delete(run)
                    session.commit()

    def test_clean_stale_agent_queue_tasks_returns_cleanup_breakdown(
        self, client, monkeypatch
    ):
        """POST /api/agents/queue-clean-stale should clean stale queue work."""
        import orchestrator.services.agent_queue as agent_queue_module

        class FakeQueue:
            async def connect(self):
                return None

            async def cleanup_orphaned_and_stale_tasks(self):
                return {
                    "cancelled_orphaned": 1,
                    "timed_out": 0,
                    "terminal_owner": 0,
                    "orphaned_queued": 0,
                    "stale_ownerless_queued": 0,
                    "missing_task_refs": 0,
                    "skipped_active": 2,
                }

        monkeypatch.setattr(agent_queue_module, "REDIS_AVAILABLE", True)
        monkeypatch.setattr(agent_queue_module, "should_use_agent_queue", lambda: True)
        monkeypatch.setattr(agent_queue_module, "get_agent_queue", lambda: FakeQueue())

        response = client.post("/api/agents/queue-clean-stale")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["cleaned"] == 1
        assert data["cancelled_orphaned"] == 1
        assert data["skipped_active"] == 2


class TestDashboardEndpoints:
    """Test dashboard endpoints."""

    def test_dashboard_stats(self, client):
        """GET /dashboard should return statistics."""
        response = client.get("/dashboard")
        assert response.status_code == 200

    def test_dashboard_stats_with_project(self, client):
        """GET /dashboard with project filter should work."""
        response = client.get("/dashboard?project_id=default")
        assert response.status_code == 200


class TestErrorSanitization:
    """Test that error responses don't leak internal details."""

    def test_404_response_format(self, client):
        """404 responses should have consistent format."""
        response = client.get("/runs/does-not-exist-12345")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        # Should not contain Python tracebacks
        detail = str(data["detail"])
        assert "Traceback" not in detail
        assert 'File "' not in detail

    def test_422_response_format(self, client):
        """422 responses should have validation error details."""
        response = client.post("/specs", json={})
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_invalid_json_body(self, client):
        """Sending invalid JSON should return 422."""
        response = client.post("/specs", content=b"not valid json", headers={"Content-Type": "application/json"})
        assert response.status_code == 422


class TestSpecMetadataEndpoints:
    """Test spec metadata CRUD endpoints."""

    def test_get_all_metadata(self, client):
        """GET /spec-metadata should return metadata list."""
        response = client.get("/spec-metadata")
        assert response.status_code == 200

    def test_get_nonexistent_metadata(self, client):
        """GET /spec-metadata/{name} for non-existent spec."""
        response = client.get("/spec-metadata/nonexistent-spec")
        # Returns default empty metadata or 404
        assert response.status_code in (200, 404)


class TestBrowserPoolEndpoints:
    """Test browser pool status endpoints."""

    def test_browser_pool_status(self, client):
        """GET /api/browser-pool/status should return pool info."""
        response = client.get("/api/browser-pool/status")
        assert response.status_code == 200

    def test_browser_pool_recent(self, client):
        """GET /api/browser-pool/recent should return recent operations."""
        response = client.get("/api/browser-pool/recent")
        assert response.status_code == 200
