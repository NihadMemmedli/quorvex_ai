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

import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

# Ensure test environment
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-api-tests")
os.environ.setdefault("REQUIRE_AUTH", "false")

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi.testclient import TestClient
from sqlmodel import Session


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
        finally:
            with Session(engine) as session:
                run = session.get(DBTestRun, run_id)
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

    def test_get_nonexistent_project_returns_404(self, client):
        """GET /projects/{id} with non-existent ID should return 404."""
        response = client.get("/projects/nonexistent-project-xyz")
        assert response.status_code == 404

    def test_delete_default_project_rejected(self, client):
        """DELETE /projects/default should be rejected."""
        response = client.delete("/projects/default")
        # Should reject deletion of default project
        assert response.status_code in (400, 403, 422)


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
        assert os.environ["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-test-model"
        assert os.environ["ANTHROPIC_MODEL"] == "claude-test-model"
        assert fake_rotator.initialized is True

        env_vars = settings_api._read_env_file()
        assert env_vars["ANTHROPIC_AUTH_TOKEN"] == "new-key-123456"
        assert env_vars["ANTHROPIC_API_KEY"] == "new-key-123456"
        assert env_vars["ANTHROPIC_AUTH_TOKENS"] == ""
        assert env_vars["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "claude-test-model"
        assert env_vars["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "claude-test-model"
        assert env_vars["ANTHROPIC_MODEL"] == "claude-test-model"

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
        assert env_vars["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "new-model"
        assert env_vars["ANTHROPIC_MODEL"] == "new-model"
        assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "real-existing-key"
        assert os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "new-model"
        assert os.environ["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "new-model"
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
            def __init__(self, timeout_seconds, allowed_tools, log_tools):
                runner_calls.append(
                    {
                        "timeout_seconds": timeout_seconds,
                        "allowed_tools": allowed_tools,
                        "log_tools": log_tools,
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
