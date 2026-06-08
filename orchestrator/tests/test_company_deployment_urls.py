import sys
import os
import types
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ORCHESTRATOR_DIR))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-company-url-tests")
os.environ.setdefault("REQUIRE_AUTH", "false")

if "slowapi" not in sys.modules:
    slowapi = types.ModuleType("slowapi")
    slowapi_errors = types.ModuleType("slowapi.errors")
    slowapi_util = types.ModuleType("slowapi.util")

    class _TestLimiter:
        def __init__(self, *args, **kwargs):
            pass

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

from orchestrator.api import recordings
from orchestrator.api import settings as settings_api
from orchestrator.services.ai_runtime_config import resolve_runtime_ai_selection
from orchestrator.services.agent_runtimes.hermes import HermesClient


def test_recorder_browser_url_does_not_expose_local_vnc_by_default(monkeypatch):
    monkeypatch.delenv("RECORDER_BROWSER_URL", raising=False)
    monkeypatch.delenv("VNC_PUBLIC_URL", raising=False)
    monkeypatch.setenv("VNC_ENABLED", "true")

    assert recordings._recorder_browser_url() is None


def test_recorder_browser_url_prefers_explicit_company_url(monkeypatch):
    monkeypatch.setenv(
        "RECORDER_BROWSER_URL",
        "https://mytest.idda.az/vnc.html?autoconnect=true&resize=scale",
    )
    monkeypatch.setenv("VNC_PUBLIC_URL", "https://ignored.example.com")

    assert (
        recordings._recorder_browser_url()
        == "https://mytest.idda.az/vnc.html?autoconnect=true&resize=scale"
    )


def test_recorder_browser_url_derives_vnc_page_from_public_vnc_url(monkeypatch):
    monkeypatch.delenv("RECORDER_BROWSER_URL", raising=False)
    monkeypatch.setenv("VNC_PUBLIC_URL", "https://mytest.idda.az")

    assert (
        recordings._recorder_browser_url()
        == "https://mytest.idda.az/vnc.html?autoconnect=true&resize=scale"
    )


def test_hermes_defaults_use_compose_service_url(tmp_path, monkeypatch):
    empty_runtime_env = tmp_path / "runtime.env"
    empty_runtime_env.write_text("")
    monkeypatch.setenv("QUORVEX_SETTINGS_ENV_FILE", str(empty_runtime_env))
    monkeypatch.delenv("HERMES_API_URL", raising=False)
    monkeypatch.delenv("HERMES_API_KEY", raising=False)

    active = settings_api._active_settings({})
    assert active["hermes_api_url"] == "http://hermes:8642"

    selection = resolve_runtime_ai_selection("chat", env_vars={"QUORVEX_LLM_PROVIDER": "hermes"})
    assert selection.base_url == "http://hermes:8642"

    client = HermesClient()
    assert client.base_url == "http://hermes:8642"
