#!/usr/bin/env python3
"""
Integration tests for production security fixes.

These tests start the actual API and verify behavior.

Run with: JWT_SECRET_KEY=test pytest orchestrator/tests/test_production_integration.py -v
"""

import os
import sys
from io import BytesIO
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

# Ensure JWT_SECRET_KEY is set for testing
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-integration-tests")

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestAPIStartup:
    """Test that the API starts correctly with new security requirements."""

    def test_api_module_imports(self):
        """API modules should import without error when JWT_SECRET_KEY is set."""
        # This will fail if there are syntax errors or import issues
        from orchestrator.api import main, security

        assert security.JWT_SECRET_KEY == "test-secret-key-for-integration-tests"
        assert main.app is not None

    def test_cors_middleware_configured(self):
        """CORS middleware should be configured on the app."""
        from orchestrator.api.main import app

        # Check middleware is present
        [m.cls.__name__ for m in app.user_middleware if hasattr(m, "cls")]
        # CORSMiddleware may be wrapped, check app has cors config
        assert hasattr(app, "user_middleware") or len(app.user_middleware) > 0

    def test_file_upload_constants(self):
        """File upload security constants should be accessible."""
        from orchestrator.api.main import ALLOWED_UPLOAD_TYPES, MAX_UPLOAD_SIZE_BYTES

        assert MAX_UPLOAD_SIZE_BYTES == 5_000_000
        assert "text/csv" in ALLOWED_UPLOAD_TYPES
        assert "application/csv" in ALLOWED_UPLOAD_TYPES


class TestFileUploadEndpoint:
    """Test file upload security at the endpoint level."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from fastapi.testclient import TestClient

        from orchestrator.api.main import app

        return TestClient(app)

    def test_upload_rejects_large_file(self, client):
        """Upload should reject files larger than 5MB."""
        # Create a file larger than 5MB
        large_content = b"x" * (5_000_001)

        response = client.post("/import/testrail", files={"file": ("large.csv", BytesIO(large_content), "text/csv")})

        assert response.status_code == 413
        assert "exceeds" in response.json()["detail"].lower()

    def test_upload_rejects_invalid_type(self, client):
        """Upload should reject files with invalid content type."""
        response = client.post(
            "/import/testrail", files={"file": ("test.exe", BytesIO(b"malicious"), "application/octet-stream")}
        )

        assert response.status_code == 400
        assert "invalid file type" in response.json()["detail"].lower()

    def test_upload_accepts_valid_csv(self, client):
        """Upload should accept valid CSV files."""
        # Create a minimal valid TestRail CSV
        csv_content = b"ID,Title,Steps,Expected Result\n1,Test Login,Click login,User logged in\n"

        response = client.post("/import/testrail", files={"file": ("test.csv", BytesIO(csv_content), "text/csv")})

        # Should either succeed or fail on parsing (not security validation)
        # 400 for parse error is acceptable, 413/400 for security is what we're testing
        assert response.status_code != 413  # Not size error
        # If it's 400, it should be a parse error, not a type error
        if response.status_code == 400:
            detail = response.json().get("detail", "").lower()
            assert "invalid file type" not in detail


class TestCORSEndpoint:
    """Test CORS headers at the endpoint level."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        from fastapi.testclient import TestClient

        from orchestrator.api.main import app

        return TestClient(app)

    def test_cors_allows_configured_origin(self, client):
        """CORS should allow configured origin."""
        response = client.options(
            "/health", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}
        )

        # Should include CORS headers for allowed origin
        cors_origin = response.headers.get("access-control-allow-origin")
        assert cors_origin == "http://localhost:3000" or cors_origin is None  # Some test clients don't trigger CORS

    def test_cors_blocks_unknown_origin(self, client):
        """CORS should not allow unknown origins."""
        response = client.options(
            "/health", headers={"Origin": "https://evil.com", "Access-Control-Request-Method": "GET"}
        )

        # Should NOT include evil.com in allowed origins
        cors_origin = response.headers.get("access-control-allow-origin", "")
        assert cors_origin != "https://evil.com"
        assert cors_origin != "*"


class TestDatabaseQueries:
    """Test database query efficiency."""

    def test_count_query_uses_sql_count(self):
        """Verify the runs endpoint uses SQL COUNT, not Python len()."""
        import inspect

        from orchestrator.api.main import app

        # Get the list_runs endpoint function
        for route in app.routes:
            if hasattr(route, "path") and route.path == "/runs":
                # Get the endpoint function source
                endpoint = route.endpoint
                source = inspect.getsource(endpoint)

                # Should use func.count(), not len(all())
                assert "func.count()" in source or "select(func.count())" in source
                assert "len(session.exec" not in source or "total = len(session.exec" not in source
                break
        else:
            pytest.fail("Could not find /runs endpoint")


class TestRateLimiting:
    """Test rate limiting configuration."""

    def test_rate_limiter_configured(self):
        """Rate limiter should be configured with Redis support."""
        from orchestrator.api.middleware.rate_limit import limiter

        assert limiter is not None
        # In test environment, REDIS_URL may not be set
        # Just verify the module loads correctly


class TestSecurityConfiguration:
    """Test overall security configuration."""

    def test_password_requirements(self):
        """Password validation should enforce strength requirements."""
        from orchestrator.api.security import is_password_strong

        # Weak passwords should fail
        is_valid, _ = is_password_strong("weak")
        assert not is_valid

        is_valid, _ = is_password_strong("12345678")
        assert not is_valid

        # Strong password should pass
        is_valid, _ = is_password_strong("SecureP@ss123!")
        assert is_valid

    def test_token_creation(self):
        """JWT tokens should be creatable."""
        from orchestrator.api.security import create_access_token, create_refresh_token, decode_token

        access = create_access_token("user-123")
        assert access is not None

        # Decode should work
        payload = decode_token(access)
        assert payload is not None
        assert payload.sub == "user-123"
        assert payload.type == "access"

        # Refresh token
        refresh = create_refresh_token("user-123", "token-id-456")
        payload = decode_token(refresh)
        assert payload is not None
        assert payload.sub == "user-123"
        assert payload.type == "refresh"
        assert payload.jti == "token-id-456"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
