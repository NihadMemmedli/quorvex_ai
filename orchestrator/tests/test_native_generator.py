import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.workflows.native_generator import NativeGenerator


def test_generator_prompt_accepts_memory_run_id(monkeypatch):
    monkeypatch.setenv("MEMORY_ENABLED", "false")
    generator = object.__new__(NativeGenerator)
    generator._extract_credential_placeholders = lambda _content: {}

    prompt = generator._build_generator_prompt(
        spec_path="/tmp/spec.md",
        spec_content="# Test\n1. Navigate to https://example.test",
        spec_name="recorded-flow",
        output_path="/tmp/recorded-flow.spec.ts",
        target_url="https://example.test",
        memory_run_id="run-123",
    )

    assert "https://example.test" in prompt
    assert "<test-file>/tmp/recorded-flow.spec.ts</test-file>" in prompt
    assert 'generator_setup_page` with `seedFile: "tests/seed.spec.ts"`' in prompt


def test_generator_agent_definition_requires_seed_file():
    content = (Path(__file__).resolve().parents[2] / ".claude" / "agents" / "playwright-test-generator.md").read_text()

    assert 'generator_setup_page` tool with `seedFile: "tests/seed.spec.ts"`' in content
