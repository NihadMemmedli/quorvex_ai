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


class FakeFailedAgentResult:
    success = False
    output = ""

    def __init__(self, error, *, error_type=None, timed_out=False, cancelled=False):
        self.error = error
        self.error_type = error_type
        self.timed_out = timed_out
        self.cancelled = cancelled


def _agent_payload(result):
    return {
        "success": bool(getattr(result, "success", False)),
        "output": getattr(result, "output", "") or "",
        "error": getattr(result, "error", None),
        "error_type": getattr(result, "error_type", None),
        "timed_out": bool(getattr(result, "timed_out", False)),
        "cancelled": bool(getattr(result, "cancelled", False)),
    }


def _patch_claude_code_subprocess(monkeypatch, result):
    captured = {}

    def fake_subprocess(_cls, prompt, runtime_env_vars):
        captured["prompt"] = prompt
        captured["runtime_env_vars"] = runtime_env_vars
        return _agent_payload(result)

    monkeypatch.setattr(
        AISpecSplitter,
        "_run_claude_code_subprocess",
        classmethod(fake_subprocess),
    )
    return captured


def test_claude_code_mode_extracts_test_cases_via_subprocess(monkeypatch):
    captured = _patch_claude_code_subprocess(monkeypatch, FakeAgentResult())
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

    assert (
        captured["runtime_env_vars"]["CLAUDE_CODE_OAUTH_TOKEN"]
        == "oauth-token-1234567890"
    )
    assert "Return ONLY the JSON" in captured["prompt"]
    assert cases[0]["id"] == "TC-001"
    assert cases[0]["_url"] == "https://example.test/checkout"


def test_claude_code_mode_extracts_smart_groups_via_subprocess(monkeypatch):
    _patch_claude_code_subprocess(monkeypatch, FakeAgentResult())

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


def test_claude_code_failed_result_with_test_case_json_error_extracts_cases(
    monkeypatch,
):
    _patch_claude_code_subprocess(
        monkeypatch,
        FakeFailedAgentResult(
            f"CLI returned error:\n```json\n{FakeAgentResult.output}\n```"
        ),
    )

    cases = AISpecSplitter.extract_test_cases(
        SPEC_CONTENT,
        "checkout.md",
        runtime_env_vars=_claude_code_env(),
    )

    assert cases[0]["id"] == "TC-001"
    assert cases[0]["name"] == "Complete checkout"
    assert cases[0]["_url"] == "https://example.test/checkout"


def test_claude_code_failed_result_with_test_case_json_error_extracts_groups(
    monkeypatch,
):
    _patch_claude_code_subprocess(
        monkeypatch,
        FakeFailedAgentResult(
            f"CLI returned error:\n```json\n{FakeAgentResult.output}\n```"
        ),
    )

    cases, groups = AISpecSplitter.extract_and_group(
        SPEC_CONTENT,
        "checkout.md",
        runtime_env_vars=_claude_code_env(),
    )

    assert cases[0]["id"] == "TC-001"
    assert groups == [
        {
            "name": "Checkout",
            "test_ids": ["TC-001"],
            "description": "Checkout flow tests",
        }
    ]


def test_claude_code_failed_result_without_test_case_json_still_raises(monkeypatch):
    _patch_claude_code_subprocess(
        monkeypatch,
        FakeFailedAgentResult('CLI returned error: {"message": "quota exceeded"}'),
    )

    with pytest.raises(RuntimeError) as exc_info:
        AISpecSplitter.extract_test_cases(
            SPEC_CONTENT,
            "checkout.md",
            runtime_env_vars=_claude_code_env(),
        )

    message = str(exc_info.value)
    assert "Claude Code extraction failed" in message
    assert "quota exceeded" in message


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"timed_out": True}, "timed out"),
        ({"cancelled": True}, "cancelled"),
        ({"error_type": "claude_code_auth_required"}, "auth required"),
    ],
)
def test_claude_code_classified_failed_result_with_json_still_raises(
    monkeypatch,
    kwargs,
    expected,
):
    _patch_claude_code_subprocess(
        monkeypatch,
        FakeFailedAgentResult(
            f"CLI {expected}:\n```json\n{FakeAgentResult.output}\n```",
            **kwargs,
        ),
    )

    with pytest.raises(RuntimeError) as exc_info:
        AISpecSplitter.extract_test_cases(
            SPEC_CONTENT,
            "checkout.md",
            runtime_env_vars=_claude_code_env(),
        )

    message = str(exc_info.value)
    assert "Claude Code extraction failed" in message
    assert expected in message


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

    def fake_call(selection, prompt, configured_provider=""):
        captured.update(
            {
                "api_key": selection.api_key,
                "base_url": selection.base_url,
                "model": selection.model,
                "provider": selection.provider,
                "configured_provider": configured_provider,
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
    assert captured["configured_provider"] == "anthropic"
    assert cases[0]["id"] == "TC-001"


class FakeModelResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = "provider error"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text}")

    def json(self):
        return self._payload


def test_openai_compatible_split_uses_chat_completions(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeModelResponse({"choices": [{"message": {"content": FakeAgentResult.output}}]})

    monkeypatch.setattr("httpx.post", fake_post)

    cases = AISpecSplitter.extract_test_cases(
        SPEC_CONTENT,
        "checkout.md",
        runtime_env_vars={
            "QUORVEX_LLM_PROVIDER": "openai",
            "QUORVEX_LLM_BASE_URL": "https://llm.example.test/api",
            "QUORVEX_LLM_API_KEY": "openai-key",
            "QUORVEX_LLM_STANDARD_MODEL": "gpt-test",
            "CLAUDE_CODE_OAUTH_TOKEN": "",
        },
    )

    assert cases[0]["id"] == "TC-001"
    assert calls[0]["url"] == "https://llm.example.test/api/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer openai-key"
    assert "x-api-key" not in calls[0]["headers"]


def test_openrouter_split_uses_chat_completions_for_custom_base_url(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeModelResponse({"choices": [{"message": {"content": FakeAgentResult.output}}]})

    monkeypatch.setattr("httpx.post", fake_post)

    AISpecSplitter.extract_test_cases(
        SPEC_CONTENT,
        "checkout.md",
        runtime_env_vars={
            "QUORVEX_LLM_PROVIDER": "openrouter",
            "QUORVEX_LLM_BASE_URL": "https://llm.company.test/openrouter",
            "QUORVEX_LLM_API_KEY": "router-key",
            "QUORVEX_LLM_STANDARD_MODEL": "anthropic/claude-test",
            "CLAUDE_CODE_OAUTH_TOKEN": "",
        },
    )

    assert calls[0]["url"] == "https://llm.company.test/openrouter/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer router-key"


def test_zai_anthropic_compatible_split_uses_messages(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeModelResponse({"content": [{"type": "text", "text": FakeAgentResult.output}]})

    monkeypatch.setattr("httpx.post", fake_post)

    AISpecSplitter.extract_test_cases(
        SPEC_CONTENT,
        "checkout.md",
        runtime_env_vars={
            "QUORVEX_LLM_PROVIDER": "zai",
            "QUORVEX_LLM_BASE_URL": "https://api.z.ai/api/anthropic",
            "ZAI_API_KEY": "zai-key",
            "QUORVEX_LLM_STANDARD_MODEL": "glm-test",
            "CLAUDE_CODE_OAUTH_TOKEN": "",
        },
    )

    assert calls[0]["url"] == "https://api.z.ai/api/anthropic/v1/messages"
    assert calls[0]["headers"]["x-api-key"] == "zai-key"
    assert "Authorization" not in calls[0]["headers"]


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
