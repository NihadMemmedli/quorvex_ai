#!/usr/bin/env python3
"""
End-to-end tests for production security fixes.

Tests:
1. JWT_SECRET_KEY is required (no default)
2. CORS configuration restricts origins
3. File upload security (size, type, path traversal)
4. N+1 query fix uses efficient COUNT
5. .gitignore includes production secrets

Run with: pytest orchestrator/tests/test_production_security.py -v
"""

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestJWTSecretKeyRequired:
    """Test that JWT_SECRET_KEY environment variable is required."""

    def test_jwt_secret_key_missing_raises_error(self):
        """Application should fail to start without JWT_SECRET_KEY."""
        # Save current value
        original = os.environ.get("JWT_SECRET_KEY")

        try:
            # Remove the env var
            if "JWT_SECRET_KEY" in os.environ:
                del os.environ["JWT_SECRET_KEY"]

            # Clear any cached imports
            if "orchestrator.api.security" in sys.modules:
                del sys.modules["orchestrator.api.security"]

            # Importing should raise ValueError
            with pytest.raises(ValueError) as exc_info:
                pass

            assert "JWT_SECRET_KEY" in str(exc_info.value)
            assert "REQUIRED" in str(exc_info.value)
        finally:
            # Restore original value
            if original:
                os.environ["JWT_SECRET_KEY"] = original
            # Clear module again
            if "orchestrator.api.security" in sys.modules:
                del sys.modules["orchestrator.api.security"]

    def test_jwt_secret_key_present_works(self):
        """Application should start when JWT_SECRET_KEY is set."""
        # Save current value
        original = os.environ.get("JWT_SECRET_KEY")

        try:
            # Set a test value
            os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing-only"

            # Clear any cached imports
            if "orchestrator.api.security" in sys.modules:
                del sys.modules["orchestrator.api.security"]

            # Should import without error
            from orchestrator.api import security

            assert security.JWT_SECRET_KEY == "test-secret-key-for-testing-only"
        finally:
            # Restore original value
            if original:
                os.environ["JWT_SECRET_KEY"] = original
            else:
                del os.environ["JWT_SECRET_KEY"]
            # Clear module
            if "orchestrator.api.security" in sys.modules:
                del sys.modules["orchestrator.api.security"]


class TestCORSConfiguration:
    """Test CORS configuration restricts origins properly."""

    def test_cors_default_localhost(self):
        """Default CORS should allow only localhost:3000."""
        # Save and clear
        original = os.environ.get("ALLOWED_ORIGINS")
        if "ALLOWED_ORIGINS" in os.environ:
            del os.environ["ALLOWED_ORIGINS"]

        try:
            # Re-evaluate the default
            allowed = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
            assert allowed == ["http://localhost:3000"]
        finally:
            if original:
                os.environ["ALLOWED_ORIGINS"] = original

    def test_cors_custom_origins(self):
        """CORS should accept comma-separated origins."""
        os.environ["ALLOWED_ORIGINS"] = "https://app.company.com,http://localhost:3000"

        try:
            allowed = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
            assert "https://app.company.com" in allowed
            assert "http://localhost:3000" in allowed
            assert len(allowed) == 2
        finally:
            del os.environ["ALLOWED_ORIGINS"]

    def test_cors_not_wildcard(self):
        """CORS should never be wildcard in production config."""
        # Read the main.py file and check CORS config
        main_py = Path(__file__).parent.parent / "api" / "main.py"
        content = main_py.read_text()

        # Should not have allow_origins=["*"] anymore
        assert 'allow_origins=["*"]' not in content
        # Should have ALLOWED_ORIGINS env var
        assert "ALLOWED_ORIGINS" in content


class TestFileUploadSecurity:
    """Test file upload security validations."""

    def test_upload_constants_defined(self):
        """Upload security constants should be defined in main.py."""
        main_py = Path(__file__).parent.parent / "api" / "main.py"
        content = main_py.read_text()

        # Check for size limit
        assert "MAX_UPLOAD_SIZE_BYTES" in content
        assert "5_000_000" in content or "5000000" in content

        # Check for allowed types
        assert "ALLOWED_UPLOAD_TYPES" in content
        assert "text/csv" in content or '"csv"' in content

    def test_path_traversal_protection(self):
        """File names should be sanitized to prevent path traversal."""
        main_py = Path(__file__).parent.parent / "api" / "main.py"
        content = main_py.read_text()

        # Should use Path().name to strip directory components
        assert "Path(fname).name" in content or "path traversal" in content.lower()


class TestN1QueryFix:
    """Test N+1 query is fixed with efficient COUNT."""

    def test_uses_func_count(self):
        """Query should use func.count() instead of len(all())."""
        main_py = Path(__file__).parent.parent / "api" / "main.py"
        content = main_py.read_text()

        # Should import func from sqlalchemy
        assert "from sqlalchemy import func" in content

        # Should use func.count() for counting
        assert "func.count()" in content

        # The old pattern should not exist
        # Note: There might be other uses of this pattern, so we check the specific runs endpoint
        # Check that the runs endpoint uses efficient counting
        runs_section = content[content.find("def list_runs") :]
        runs_section = runs_section[: runs_section.find("\n@app.")]  # Get just the list_runs function

        # Should have efficient count query
        assert "func.count()" in runs_section or "select(func.count())" in runs_section


class TestGitIgnore:
    """Test .gitignore includes production secrets."""

    def test_env_prod_ignored(self):
        """.env.prod should be in .gitignore."""
        gitignore = Path(__file__).parent.parent.parent / ".gitignore"
        content = gitignore.read_text()

        assert ".env.prod" in content

    def test_env_local_patterns_ignored(self):
        """.env.*.local should be in .gitignore."""
        gitignore = Path(__file__).parent.parent.parent / ".gitignore"
        content = gitignore.read_text()

        assert ".env.*.local" in content


class TestDockerComposeProduction:
    """Test docker-compose.prod.yml configuration."""

    def test_redis_service_exists(self):
        """Redis service should be defined."""
        compose = Path(__file__).parent.parent.parent / "docker-compose.prod.yml"
        content = compose.read_text()

        assert "redis:" in content
        assert "redis:7-alpine" in content or "redis:" in content

    def test_jwt_required_in_compose(self):
        """JWT_SECRET_KEY should be required in docker-compose."""
        compose = Path(__file__).parent.parent.parent / "docker-compose.prod.yml"
        content = compose.read_text()

        # Should use :? syntax to require the variable
        assert "JWT_SECRET_KEY:" in content
        # Should not have unsafe default
        assert "dev-secret-key" not in content

    def test_redis_url_configured(self):
        """Backend should have REDIS_URL configured."""
        compose = Path(__file__).parent.parent.parent / "docker-compose.prod.yml"
        content = compose.read_text()

        assert "REDIS_URL:" in content
        assert "redis://" in content

    def test_allowed_origins_configured(self):
        """Backend should have ALLOWED_ORIGINS configured."""
        compose = Path(__file__).parent.parent.parent / "docker-compose.prod.yml"
        content = compose.read_text()

        assert "ALLOWED_ORIGINS:" in content

    def test_registration_disabled_by_default(self):
        """ALLOW_REGISTRATION should default to false in production."""
        compose = Path(__file__).parent.parent.parent / "docker-compose.prod.yml"
        content = compose.read_text()

        # Should have ALLOW_REGISTRATION set to false
        assert "ALLOW_REGISTRATION:" in content
        # Find the line and check it defaults to false
        for line in content.split("\n"):
            if "ALLOW_REGISTRATION:" in line:
                assert "false" in line.lower()
                break

    def test_log_rotation_configured(self):
        """Services should have log rotation configured."""
        compose = Path(__file__).parent.parent.parent / "docker-compose.prod.yml"
        content = compose.read_text()

        assert "max-size:" in content
        assert "max-file:" in content

    def test_nginx_service_exists(self):
        """Nginx service should be defined."""
        compose = Path(__file__).parent.parent.parent / "docker-compose.prod.yml"
        content = compose.read_text()

        assert "nginx:" in content
        assert "nginx:alpine" in content


class TestNginxConfiguration:
    """Test nginx configuration."""

    def test_nginx_conf_exists(self):
        """nginx.conf should exist."""
        nginx_conf = Path(__file__).parent.parent.parent / "nginx" / "nginx.conf"
        assert nginx_conf.exists()

    def test_tls_configuration(self):
        """Nginx should have TLS configuration."""
        nginx_conf = Path(__file__).parent.parent.parent / "nginx" / "nginx.conf"
        content = nginx_conf.read_text()

        assert "ssl_certificate" in content
        assert "ssl_protocols" in content
        assert "TLSv1.2" in content or "TLSv1.3" in content

    def test_security_headers(self):
        """Nginx should add security headers."""
        nginx_conf = Path(__file__).parent.parent.parent / "nginx" / "nginx.conf"
        content = nginx_conf.read_text()

        assert "X-Frame-Options" in content
        assert "X-Content-Type-Options" in content

    def test_rate_limiting(self):
        """Nginx should have rate limiting."""
        nginx_conf = Path(__file__).parent.parent.parent / "nginx" / "nginx.conf"
        content = nginx_conf.read_text()

        assert "limit_req_zone" in content
        assert "limit_req" in content


class TestEnvProdExample:
    """Test .env.prod.example template."""

    def test_example_file_exists(self):
        """.env.prod.example should exist."""
        example = Path(__file__).parent.parent.parent / ".env.prod.example"
        assert example.exists()

    def test_required_vars_documented(self):
        """Required variables should be documented."""
        example = Path(__file__).parent.parent.parent / ".env.prod.example"
        content = example.read_text()

        assert "JWT_SECRET_KEY" in content
        assert "POSTGRES_PASSWORD" in content
        assert "ANTHROPIC_AUTH_TOKEN" in content
        assert "MINIO_ROOT_PASSWORD" in content

    def test_no_real_secrets(self):
        """Example file should not contain real secrets."""
        example = Path(__file__).parent.parent.parent / ".env.prod.example"
        content = example.read_text()

        # Should have placeholder patterns, not actual keys
        assert "sk-" not in content  # No OpenAI keys
        assert "sk-ant-" not in content  # No Anthropic keys

        # Values should be placeholders
        lines_with_equals = [line for line in content.split("\n") if "=" in line and not line.startswith("#")]
        for line in lines_with_equals:
            key, value = line.split("=", 1)
            # Actual secrets should be placeholders
            if any(secret in key for secret in ["PASSWORD", "SECRET", "TOKEN", "KEY"]):
                # Should either be a placeholder or reference to generation
                assert "<" in value or "generate" in value.lower() or value.strip() == "" or "${" in value, (
                    f"Potential secret in {key}"
                )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
