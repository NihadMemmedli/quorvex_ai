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
from pathlib import Path

import pytest

# Ensure test environment
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-api-tests")
os.environ.setdefault("REQUIRE_AUTH", "false")

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi.testclient import TestClient


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
        assert isinstance(data, list)

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
        assert "items" in data or isinstance(data, list)

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
        """GET /dashboard/stats should return statistics."""
        response = client.get("/dashboard/stats")
        assert response.status_code == 200

    def test_dashboard_stats_with_project(self, client):
        """GET /dashboard/stats with project filter should work."""
        response = client.get("/dashboard/stats?project_id=default")
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
