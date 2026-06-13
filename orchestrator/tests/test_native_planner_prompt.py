import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.workflows.native_planner import NativePlanner


def test_planner_prompt_instructs_seed_file_for_setup():
    planner = object.__new__(NativePlanner)

    prompt = planner._build_hybrid_prompt(
        feature_name="Checkout",
        feature_slug="checkout",
        prd_context="Users can complete checkout.",
        target_url="https://example.test/checkout",
        login_url=None,
        credentials=None,
        output_path="/tmp/checkout.md",
    )

    assert 'planner_setup_page` with `seedFile: "tests/seed.spec.ts"`' in prompt
    assert "https://example.test/checkout" in prompt
    assert "## Draft Playwright Script" in prompt
    assert "Do not use `page.waitForTimeout()`" in prompt
    assert "await expect(...).toBeVisible()" in prompt
    assert "Do not call `browser_close`" in prompt
    assert "handle browser cleanup after acceptance or final failure" in prompt


def test_planner_prompt_normalizes_markdown_target_url():
    planner = object.__new__(NativePlanner)

    prompt = planner._build_hybrid_prompt(
        feature_name="Trips",
        feature_slug="trips",
        prd_context="Users can review trips.",
        target_url="https://pre.wetravel.to/user/my_trips?view=List`",
        login_url=None,
        credentials=None,
        output_path="/tmp/trips.md",
    )

    assert "https://pre.wetravel.to/user/my_trips?view=List`" not in prompt
    assert "https://pre.wetravel.to/user/my_trips?view=List" in prompt


def test_planner_agent_definition_requires_seed_file():
    content = (Path(__file__).resolve().parents[2] / ".claude" / "agents" / "playwright-test-planner.md").read_text()

    assert 'planner_setup_page` tool once with `seedFile: "tests/seed.spec.ts"`' in content


def test_planner_agent_definition_requires_draft_playwright_script():
    content = (Path(__file__).resolve().parents[2] / ".claude" / "agents" / "playwright-test-planner.md").read_text()

    assert "## Draft Playwright Script" in content
    assert "Use Playwright web-first assertions" in content
    assert "Do not include `page.waitForTimeout()`" in content
