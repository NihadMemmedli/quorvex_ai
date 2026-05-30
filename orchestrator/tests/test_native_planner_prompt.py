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


def test_planner_agent_definition_requires_seed_file():
    content = (Path(__file__).resolve().parents[2] / ".claude" / "agents" / "playwright-test-planner.md").read_text()

    assert 'planner_setup_page` tool once with `seedFile: "tests/seed.spec.ts"`' in content
