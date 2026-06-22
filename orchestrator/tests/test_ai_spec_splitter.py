import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.utils.ai_spec_splitter import AISpecSplitter
from orchestrator.utils.prd_spec_splitter import PRDSpecSplitter

SPEC_CONTENT = """# Checkout Tests

**Target URL**: https://example.test

## Happy Path Tests

### TC-001: Complete checkout

1. Navigate to /checkout
2. Pay with a saved card
"""


def _claude_code_env(**overrides):
    env = {
        "QUORVEX_LLM_AUTH_MODE": "claude_code_subscription",
        "QUORVEX_LLM_PROVIDER": "anthropic",
        "CLAUDE_CODE_OAUTH_TOKEN": "oauth-token-1234567890",
        "QUORVEX_LLM_API_KEY": "",
        "QUORVEX_LLM_API_KEYS": "",
        "ANTHROPIC_AUTH_TOKEN": "",
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_AUTH_TOKENS": "",
        "OPENAI_API_KEY": "",
        "QUORVEX_LLM_STANDARD_MODEL": "claude-sonnet-test",
    }
    env.update(overrides)
    return env


class FakeAgentResult:
    success = True
    output = """{
      "test_cases": [
        {
          "id": "TC-001",
          "name": "Complete checkout",
          "category": "Happy Path",
          "description": "Verify checkout completion",
          "preconditions": [],
          "steps": ["Navigate to /checkout", "Pay with a saved card"],
          "expected_results": ["Checkout succeeds"],
          "selectors": [],
          "url": "/checkout",
          "file_path": null,
          "seed": null
        }
      ],
      "groups": [
        {
          "name": "Checkout",
          "test_ids": ["TC-001"],
          "description": "Checkout flow tests"
        }
      ]
    }"""


def test_claude_code_mode_extracts_test_cases_via_agent_runner(monkeypatch):
    captured = {}

    class FakeRunner:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        async def run(self, prompt):
            captured["prompt"] = prompt
            return FakeAgentResult()

    monkeypatch.setattr("orchestrator.utils.ai_spec_splitter.AgentRunner", FakeRunner)
    monkeypatch.setattr(
        AISpecSplitter,
        "_call_text_model",
        staticmethod(
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("direct API path should not run")
            )
        ),
    )

    cases = AISpecSplitter.extract_test_cases(
        SPEC_CONTENT,
        "checkout.md",
        runtime_env_vars=_claude_code_env(),
    )

    assert captured["kwargs"]["allowed_tools"] == []
    assert captured["kwargs"]["log_tools"] is False
    assert captured["kwargs"]["model_tier"] == "standard"
    assert captured["kwargs"]["env_vars"]["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-token-1234567890"
    assert "Return ONLY the JSON" in captured["prompt"]
    assert cases[0]["id"] == "TC-001"
    assert cases[0]["_url"] == "https://example.test/checkout"


def test_claude_code_mode_extracts_smart_groups_via_agent_runner(monkeypatch):
    class FakeRunner:
        def __init__(self, **_kwargs):
            pass

        async def run(self, _prompt):
            return FakeAgentResult()

    monkeypatch.setattr("orchestrator.utils.ai_spec_splitter.AgentRunner", FakeRunner)

    cases, groups = AISpecSplitter.extract_and_group(
        SPEC_CONTENT,
        "checkout.md",
        runtime_env_vars=_claude_code_env(),
    )

    assert cases[0]["name"] == "Complete checkout"
    assert groups == [
        {
            "name": "Checkout",
            "test_ids": ["TC-001"],
            "description": "Checkout flow tests",
        }
    ]


def test_missing_direct_key_and_claude_token_raises_actionable_message():
    with pytest.raises(RuntimeError) as exc_info:
        AISpecSplitter.extract_test_cases(
            SPEC_CONTENT,
            "checkout.md",
            runtime_env_vars=_claude_code_env(CLAUDE_CODE_OAUTH_TOKEN=""),
        )

    message = str(exc_info.value)
    assert "API key" in message
    assert "Claude Code OAuth token" in message
    assert "Settings" in message


def test_direct_api_key_path_still_uses_text_model(monkeypatch):
    captured = {}

    def fake_call(api_key, base_url, model, prompt):
        captured.update(
            {
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
                "prompt": prompt,
            }
        )
        return FakeAgentResult.output

    monkeypatch.setattr(AISpecSplitter, "_call_text_model", staticmethod(fake_call))

    cases = AISpecSplitter.extract_test_cases(
        SPEC_CONTENT,
        "checkout.md",
        runtime_env_vars={
            "QUORVEX_LLM_PROVIDER": "anthropic",
            "QUORVEX_LLM_BASE_URL": "https://api.example.test",
            "QUORVEX_LLM_API_KEY": "direct-key",
            "QUORVEX_LLM_STANDARD_MODEL": "direct-model",
            "CLAUDE_CODE_OAUTH_TOKEN": "",
        },
    )

    assert captured["api_key"] == "direct-key"
    assert captured["base_url"] == "https://api.example.test"
    assert captured["model"] == "direct-model"
    assert cases[0]["id"] == "TC-001"


def test_ai_split_child_spec_includes_explicit_target_url_line(tmp_path, monkeypatch):
    spec_path = tmp_path / "checkout-parent.md"
    spec_path.write_text(
        """# Checkout Tests

**Target URL**: https://example.test

### TC-001: Complete checkout
1. Navigate to /checkout

### TC-002: Review receipt
1. Navigate to /receipt
""",
        encoding="utf-8",
    )

    def fake_extract_and_group(_content, _spec_name="", runtime_env_vars=None):
        return (
            [
                {
                    "id": "TC-001",
                    "name": "Complete checkout",
                    "category": "Happy Path",
                    "content": "",
                    "_ai_extracted": True,
                    "_description": "Verify checkout completion",
                    "_preconditions": [],
                    "_steps": ["Navigate to /checkout", "Pay with a saved card"],
                    "_expected_results": ["Checkout succeeds"],
                    "_selectors": [],
                    "_url": "https://example.test/checkout",
                }
            ],
            [],
        )

    monkeypatch.setattr(
        "orchestrator.utils.ai_spec_splitter.AISpecSplitter.extract_and_group",
        fake_extract_and_group,
    )

    files, _groups = PRDSpecSplitter.split_spec(
        spec_path, use_ai=True, ai_fallback=False
    )

    child = files[0].read_text(encoding="utf-8")
    assert "Target URL: https://example.test/checkout" in child
    assert "- URL: https://example.test/checkout" in child
