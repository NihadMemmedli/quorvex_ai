from services.recording_parser import build_markdown_spec, parse_playwright_codegen, slugify


def test_parse_common_codegen_actions_and_assertions():
    code = """
import { test, expect } from '@playwright/test';

test('test', async ({ page }) => {
  await page.goto('https://the-internet.herokuapp.com/login');
  await page.getByLabel('Username').fill('tomsmith');
  await page.getByLabel('Password').fill('SuperSecretPassword!');
  await page.getByRole('button', { name: 'Login' }).click();
  await expect(page.getByText('You logged into a secure area!')).toBeVisible();
});
"""

    parsed = parse_playwright_codegen(code, title="Login flow")

    assert parsed.target_url == "https://the-internet.herokuapp.com/login"
    assert [step.action for step in parsed.steps] == ["navigate", "fill", "fill", "click", "assert"]
    assert "field labeled `Password`" in parsed.steps[2].description
    assert "{{PASSWORD}}" in parsed.steps[2].description
    assert parsed.unsupported_lines == []


def test_parse_codegen_preserves_utf8_and_redacts_azerbaijani_password():
    code = """
  await page.getByRole('button', { name: 'Bağla' }).click();
  await page.getByRole('button', { name: 'Dig\\u0259r \\u00fcsullar' }).click();
  await page.getByRole('textbox', { name: 'Şifrə' }).fill('Jj3630882!!!');
"""

    parsed = parse_playwright_codegen(code, title="Azerbaijani login flow")

    assert "button named `Bağla`" in parsed.steps[0].description
    assert "button named `Digər üsullar`" in parsed.steps[1].description
    assert "textbox named `Şifrə`" in parsed.steps[2].description
    assert "{{PASSWORD}}" in parsed.steps[2].description
    assert "Jj3630882!!!" not in parsed.steps[2].description


def test_build_markdown_preserves_unsupported_lines():
    code = """
  await page.goto('https://example.com');
  await page.getByRole('listitem').filter({ hasText: 'Advanced' }).click();
"""

    parsed = parse_playwright_codegen(code, title="Advanced flow")
    markdown = build_markdown_spec(parsed, source_code_path="tests/recordings/advanced-flow.spec.ts")

    assert "# Test: Advanced flow" in markdown
    assert "Navigate to https://example.com" in markdown
    assert "## Notes" in markdown
    assert "filter" in markdown
    assert "`tests/recordings/advanced-flow.spec.ts`" in markdown


def test_slugify_has_stable_fallback_and_limit():
    assert slugify("Login happy path!") == "login-happy-path"
    assert slugify("!!!") == "recorded-flow"
    assert len(slugify("a" * 120)) <= 80
