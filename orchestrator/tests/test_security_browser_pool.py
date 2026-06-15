import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.api import credentials as credentials_api
from orchestrator.api import security_testing
from orchestrator.services.browser_pool import OperationType


class _FakeLocator:
    @property
    def first(self):
        return self

    async def count(self):
        return 1

    async def fill(self, _value, timeout=None):
        return None

    async def click(self, timeout=None):
        return None


class _FakeKeyboard:
    async def press(self, _key):
        return None


class _FakePage:
    keyboard = _FakeKeyboard()

    def locator(self, _selector):
        return _FakeLocator()

    async def goto(self, *_args, **_kwargs):
        return None

    async def wait_for_load_state(self, *_args, **_kwargs):
        return None


class _FakeContext:
    async def new_page(self):
        return _FakePage()

    async def cookies(self):
        return [{"name": "sid", "value": "abc", "domain": "example.com", "path": "/"}]


class _FakeBrowser:
    async def new_context(self, **_kwargs):
        return _FakeContext()

    async def close(self):
        return None


class _FakeChromium:
    async def launch(self, **_kwargs):
        return _FakeBrowser()


class _FakePlaywright:
    chromium = _FakeChromium()


class _FakeAsyncPlaywright:
    async def __aenter__(self):
        return _FakePlaywright()

    async def __aexit__(self, *_args):
        return None


@pytest.mark.asyncio
async def test_authenticated_security_preflight_acquires_browser_pool_slot(monkeypatch):
    captured: dict[str, object] = {}

    @asynccontextmanager
    async def fake_browser_operation_slot(**kwargs):
        captured["slot_kwargs"] = kwargs
        yield

    playwright_module = types.ModuleType("playwright")
    playwright_async_api = types.ModuleType("playwright.async_api")
    playwright_async_api.async_playwright = lambda: _FakeAsyncPlaywright()
    playwright_module.async_api = playwright_async_api
    monkeypatch.setitem(sys.modules, "playwright", playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.async_api", playwright_async_api)
    monkeypatch.setattr(security_testing, "browser_operation_slot", fake_browser_operation_slot)
    monkeypatch.setattr(
        credentials_api,
        "get_merged_credentials",
        lambda _project_id, _session: {"USER": "user@example.com", "PASS": "secret"},
    )

    request = security_testing.QuickScanRequest(
        target_url="https://example.com",
        project_id="default",
        auth_config=security_testing.SecurityAuthConfig(
            enabled=True,
            login_url="https://example.com/login",
            username_key="USER",
            password_key="PASS",
        ),
    )

    headers = await security_testing._build_auth_headers(request, "default")

    assert headers == {"Cookie": "sid=abc"}
    slot_kwargs = captured["slot_kwargs"]
    assert slot_kwargs["operation_type"] == OperationType.SECURITY
    assert str(slot_kwargs["request_id"]).startswith("security-auth:default:")
