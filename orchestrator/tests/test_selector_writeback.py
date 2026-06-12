from __future__ import annotations

import sys
import types
from pathlib import Path

from orchestrator.memory import selector_writeback


def test_extract_selectors_captures_playwright_selector_context():
    content = """
import { test, expect } from '@playwright/test';

test('login uses durable selectors', async ({ page }) => {
  await page.goto('https://example.test/login');
  await page.getByRole('button', { exact: true, name: 'Sign in' }).click();
  await page.getByLabel('Email address').fill('user@example.test');
  await page.getByTestId('password-input').fill('secret');
  await page.getByPlaceholder('Search trips').fill('baku');
  await expect(page.getByText('Welcome back')).toBeVisible();
  await page.locator('[data-qa="remember-me"]').check();
});

test('selector without navigation does not inherit previous page', async ({ page }) => {
  await page.getByRole('link', { name: 'Help' }).click();
});
"""

    selectors = selector_writeback.extract_selectors(content)

    assert [item["type"] for item in selectors] == [
        "getByRole",
        "getByLabel",
        "getByTestId",
        "getByPlaceholder",
        "getByText",
        "locator",
        "getByRole",
    ]

    role = selectors[0]
    assert role["value"] == "button"
    assert role["name"] == "Sign in"
    assert role["action"] == "click"
    assert role["page_url"] == "https://example.test/login"
    assert role["test_title"] == "login uses durable selectors"
    assert role["playwright_selector"] == "getByRole('button', { exact: true, name: 'Sign in' })"

    assert selectors[1]["value"] == "Email address"
    assert selectors[1]["action"] == "fill"
    assert selectors[2]["value"] == "password-input"
    assert selectors[3]["value"] == "Search trips"
    assert selectors[4]["value"] == "Welcome back"
    assert selectors[4]["action"] == "assert"

    locator = selectors[5]
    assert locator["value"] == '[data-qa="remember-me"]'
    assert locator["action"] == "check"
    assert locator["playwright_selector"] == 'locator(\'[data-qa="remember-me"]\')'

    later_test_selector = selectors[6]
    assert later_test_selector["test_title"] == "selector without navigation does not inherit previous page"
    assert later_test_selector["page_url"] == ""


def test_selector_writeback_enabled_honors_env_kill_switches(monkeypatch):
    monkeypatch.setenv("MEMORY_SELECTOR_WRITEBACK", "true")
    monkeypatch.setenv("MEMORY_ENABLED", "true")
    assert selector_writeback.selector_writeback_enabled() is True

    monkeypatch.setenv("MEMORY_SELECTOR_WRITEBACK", "false")
    assert selector_writeback.selector_writeback_enabled() is False

    monkeypatch.setenv("MEMORY_SELECTOR_WRITEBACK", "true")
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    assert selector_writeback.selector_writeback_enabled() is False


def test_record_passing_test_selectors_missing_project_id_returns_zero(tmp_path, monkeypatch):
    spec = tmp_path / "missing-project.spec.ts"
    spec.write_text("test('x', async ({ page }) => { await page.getByText('Hi').click(); });")
    monkeypatch.setenv("MEMORY_SELECTOR_WRITEBACK", "true")
    monkeypatch.setenv("MEMORY_ENABLED", "true")
    monkeypatch.delenv("MEMORY_PROJECT_ID", raising=False)
    monkeypatch.delenv("PROJECT_ID", raising=False)

    assert selector_writeback.record_passing_test_selectors(spec) == 0


def test_record_passing_test_selectors_stores_successful_patterns_with_metadata(
    tmp_path: Path, monkeypatch
):
    spec = tmp_path / "selectors.spec.ts"
    spec.write_text(
        """
test('checkout persists selectors', async ({ page }) => {
  await page.goto('https://example.test/checkout');
  await page.getByRole('button', { name: 'Pay now' }).click();
  await page.getByLabel('Card number').fill('4242424242424242');
});
"""
    )
    monkeypatch.setenv("MEMORY_SELECTOR_WRITEBACK", "true")
    monkeypatch.setenv("MEMORY_ENABLED", "true")
    monkeypatch.delenv("MEMORY_PROJECT_ID", raising=False)
    monkeypatch.delenv("PROJECT_ID", raising=False)

    calls = []

    class FakeManager:
        def store_test_pattern(self, **kwargs):
            calls.append(kwargs)
            return f"pattern-{len(calls)}"

    def fake_get_memory_manager(*, project_id):
        assert project_id == "project-a"
        return FakeManager()

    fake_manager_module = types.ModuleType("orchestrator.memory.manager")
    fake_manager_module.get_memory_manager = fake_get_memory_manager
    monkeypatch.setitem(sys.modules, "orchestrator.memory.manager", fake_manager_module)

    stored = selector_writeback.record_passing_test_selectors(
        spec,
        project_id="project-a",
        run_id="run-123",
    )

    assert stored == 2
    assert [call["success"] for call in calls] == [True, True]
    assert [call["test_name"] for call in calls] == [
        "checkout persists selectors",
        "checkout persists selectors",
    ]
    assert calls[0]["selector"] == {
        "type": "getByRole",
        "value": "button",
        "name": "Pay now",
        "strategy": "getByRole",
        "element_role": "button",
        "element_name": "Pay now",
    }
    assert calls[1]["selector"]["element_label"] == "Card number"

    first_metadata = calls[0]["metadata"]
    assert first_metadata["page_url"] == "https://example.test/checkout"
    assert first_metadata["playwright_selector"] == "getByRole('button', { name: 'Pay now' })"
    assert first_metadata["spec_file"] == str(spec)
    assert first_metadata["run_id"] == "run-123"
