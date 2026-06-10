from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlmodel import Session

RUNTIME_ENV_KEYS = {
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_AUTH_TOKENS",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_CHAT_MODEL",
    "QUORVEX_LLM_PROVIDER",
    "QUORVEX_LLM_BASE_URL",
    "QUORVEX_LLM_API_KEY",
    "QUORVEX_LLM_API_KEYS",
    "QUORVEX_LLM_LIGHT_MODEL",
    "QUORVEX_LLM_STANDARD_MODEL",
    "QUORVEX_LLM_DEEP_MODEL",
    "QUORVEX_LLM_TOOL_DEEP_MODEL",
    "QUORVEX_LLM_CHAT_MODEL",
    "QUORVEX_EMBEDDING_MODEL",
    "QUORVEX_SETTINGS_ENV_FILE",
    "QUORVEX_AGENT_RUNTIME",
    "QUORVEX_ASSISTANT_RUNTIME",
    "ZAI_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL_ID",
    "OPENAI_CHAT_MODEL",
    "HERMES_ENABLED",
    "HERMES_API_URL",
    "HERMES_API_KEY",
    "HERMES_MODEL",
    "HERMES_HOME",
    "HERMES_SYNC_PROVIDER",
    "HERMES_UPSTREAM_PROVIDER",
    "HERMES_UPSTREAM_MODEL",
}


def pytest_configure(config):
    """Establish root-run test defaults before application modules import."""
    test_db = Path(os.environ.get("QUORVEX_TEST_DB_PATH", f"/tmp/quorvex_pytest_{os.getpid()}.db"))
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{test_db}")
    os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest")
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

    import orchestrator.api as canonical_api
    import orchestrator.api.db as canonical_db
    import orchestrator.api.models_auth as canonical_models_auth
    import orchestrator.api.models_db as canonical_models_db

    sys.modules.setdefault("api", canonical_api)
    sys.modules.setdefault("api.db", canonical_db)
    sys.modules.setdefault("api.models_auth", canonical_models_auth)
    sys.modules.setdefault("api.models_db", canonical_models_db)


@pytest.fixture(scope="session", autouse=True)
def app_db_tables():
    """Create the minimal app table needed by shared Settings cleanup."""
    from orchestrator.api import db as db_module

    with db_module.engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id VARCHAR PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    base_url VARCHAR,
                    description VARCHAR,
                    settings JSON,
                    created_at DATETIME,
                    last_active DATETIME
                )
                """
            )
        )
    yield


@pytest.fixture(autouse=True)
def isolated_runtime_settings(app_db_tables):
    """Prevent Settings tests from leaking mutable runtime state."""
    from orchestrator.api import db as db_module
    from orchestrator.api.models_db import Project
    from orchestrator.api.settings import DEFAULT_PROJECT_ID, RUNTIME_SETTINGS_KEY

    def clear_runtime_settings():
        with Session(db_module.engine) as session:
            project = session.get(Project, DEFAULT_PROJECT_ID)
            if not project or not isinstance(project.settings, dict):
                return
            project_settings = dict(project.settings)
            if RUNTIME_SETTINGS_KEY not in project_settings:
                return
            project_settings.pop(RUNTIME_SETTINGS_KEY, None)
            project.settings = project_settings
            session.add(project)
            session.commit()

    original_env = {key: os.environ.get(key) for key in RUNTIME_ENV_KEYS}
    clear_runtime_settings()
    try:
        yield
    finally:
        clear_runtime_settings()
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
