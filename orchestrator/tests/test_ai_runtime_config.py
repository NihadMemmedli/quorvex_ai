import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.services.ai_runtime_config import (
    apply_runtime_env_aliases,
    model_tiers,
    resolve_model,
    resolve_openai_chat_model,
    resolve_runtime_ai_selection,
)

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
    "QUORVEX_LLM_AUTH_MODE",
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
    "ZAI_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
}


@pytest.fixture(autouse=True)
def restore_runtime_env():
    original = {key: os.environ.get(key) for key in RUNTIME_ENV_KEYS}
    yield
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_model_tiers_prefer_canonical_env(monkeypatch):
    monkeypatch.setenv("QUORVEX_LLM_LIGHT_MODEL", "cheap-model")
    monkeypatch.setenv("QUORVEX_LLM_STANDARD_MODEL", "standard-model")
    monkeypatch.setenv("QUORVEX_LLM_DEEP_MODEL", "deep-model")
    monkeypatch.setenv("QUORVEX_LLM_TOOL_DEEP_MODEL", "tool-model")
    monkeypatch.setenv("QUORVEX_LLM_CHAT_MODEL", "chat-model")
    monkeypatch.setenv("QUORVEX_EMBEDDING_MODEL", "embed-model")

    assert model_tiers() == {
        "light": "cheap-model",
        "standard": "standard-model",
        "deep": "deep-model",
        "tool_deep": "tool-model",
        "chat": "chat-model",
        "embedding": "embed-model",
    }


def test_model_tiers_fall_back_to_legacy_env(monkeypatch):
    for key in (
        "QUORVEX_LLM_LIGHT_MODEL",
        "QUORVEX_LLM_STANDARD_MODEL",
        "QUORVEX_LLM_DEEP_MODEL",
        "QUORVEX_LLM_TOOL_DEEP_MODEL",
        "QUORVEX_LLM_CHAT_MODEL",
        "QUORVEX_EMBEDDING_MODEL",
        "ANTHROPIC_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", "legacy-haiku")
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "legacy-sonnet")
    monkeypatch.setenv("ANTHROPIC_DEFAULT_OPUS_MODEL", "legacy-opus")
    monkeypatch.setenv("ANTHROPIC_CHAT_MODEL", "legacy-chat")
    monkeypatch.setenv("EMBEDDING_MODEL", "legacy-embedding")

    assert resolve_model("light") == "legacy-haiku"
    assert resolve_model("standard") == "legacy-sonnet"
    assert resolve_model("deep") == "legacy-opus"
    assert resolve_model("tool_deep") == "legacy-opus"
    assert resolve_model("chat") == "legacy-chat"
    assert resolve_model("embedding") == "legacy-embedding"


def test_apply_runtime_env_aliases_sets_selected_model_and_preserves_tiers(monkeypatch):
    env_vars = {
        "QUORVEX_LLM_BASE_URL": "https://proxy.example.com",
        "QUORVEX_LLM_API_KEY": "runtime-key",
        "QUORVEX_LLM_LIGHT_MODEL": "cheap-model",
        "QUORVEX_LLM_STANDARD_MODEL": "standard-model",
        "QUORVEX_LLM_DEEP_MODEL": "deep-model",
        "QUORVEX_LLM_TOOL_DEEP_MODEL": "tool-model",
        "QUORVEX_LLM_CHAT_MODEL": "chat-model",
        "QUORVEX_EMBEDDING_MODEL": "embed-model",
    }

    selection = apply_runtime_env_aliases(env_vars, tier="tool_deep")

    assert selection.model == "tool-model"
    assert os.environ["ANTHROPIC_MODEL"] == "tool-model"
    assert os.environ["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "cheap-model"
    assert os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "standard-model"
    assert os.environ["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "deep-model"
    assert os.environ["ANTHROPIC_CHAT_MODEL"] == "chat-model"
    assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "runtime-key"


def test_runtime_selection_supports_canonical_key_pool(monkeypatch):
    monkeypatch.setenv("QUORVEX_LLM_API_KEY", "canonical-key")
    monkeypatch.setenv("QUORVEX_LLM_CHAT_MODEL", "chat-model")

    selection = resolve_runtime_ai_selection("chat")

    assert selection.model == "chat-model"
    assert selection.api_key == "canonical-key"
    assert selection.api_key_env == "QUORVEX_LLM_API_KEY"


def test_runtime_selection_uses_first_canonical_key_pool_entry(monkeypatch):
    monkeypatch.delenv("QUORVEX_LLM_API_KEY", raising=False)
    monkeypatch.setenv("QUORVEX_LLM_API_KEYS", "pool-key-1,pool-key-2")

    selection = resolve_runtime_ai_selection("tool_deep")

    assert selection.api_key == "pool-key-1"
    assert selection.api_key_env == "QUORVEX_LLM_API_KEYS"


def test_runtime_selection_prefers_single_canonical_key_over_key_pool(monkeypatch):
    monkeypatch.setenv("QUORVEX_LLM_API_KEY", "canonical-key")
    monkeypatch.setenv("QUORVEX_LLM_API_KEYS", "pool-key-1,pool-key-2")

    selection = resolve_runtime_ai_selection("tool_deep")

    assert selection.api_key == "canonical-key"
    assert selection.api_key_env == "QUORVEX_LLM_API_KEY"


def test_zai_runtime_selection_accepts_provider_specific_key(monkeypatch):
    for key in (
        "QUORVEX_LLM_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("QUORVEX_LLM_PROVIDER", "anthropic_compatible")
    monkeypatch.setenv("QUORVEX_LLM_BASE_URL", "https://api.z.ai/api/anthropic")
    monkeypatch.setenv("ZAI_API_KEY", "zai-runtime-key")

    selection = resolve_runtime_ai_selection("tool_deep")

    assert selection.provider == "anthropic_compatible"
    assert selection.api_key == "zai-runtime-key"
    assert selection.api_key_env == "ZAI_API_KEY"

    apply_runtime_env_aliases(None, tier="tool_deep")
    assert os.environ["QUORVEX_LLM_API_KEY"] == "zai-runtime-key"
    assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "zai-runtime-key"
    assert os.environ["ANTHROPIC_API_KEY"] == "zai-runtime-key"

    env_file_selection = resolve_runtime_ai_selection(
        "tool_deep",
        env_vars={
            "QUORVEX_LLM_PROVIDER": "anthropic_compatible",
            "QUORVEX_LLM_BASE_URL": "https://api.z.ai/api/anthropic",
            "QUORVEX_LLM_API_KEY": "",
            "ZAI_API_KEY": "zai-runtime-key",
        },
    )
    assert env_file_selection.api_key == "zai-runtime-key"
    assert env_file_selection.api_key_env == "ZAI_API_KEY"


def test_api_key_rotator_accepts_zai_key_for_zai_base_url(monkeypatch):
    from orchestrator.services.api_key_rotator import ApiKeyRotator

    for key in (
        "QUORVEX_LLM_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "QUORVEX_LLM_API_KEYS",
        "ANTHROPIC_AUTH_TOKENS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("QUORVEX_LLM_BASE_URL", "https://api.z.ai/api/anthropic")
    monkeypatch.setenv("ZAI_API_KEY", "zai-rotator-key")

    rotator = ApiKeyRotator()
    rotator.initialize()
    slot = rotator.get_active_key()

    assert slot is not None
    assert slot.token == "zai-rotator-key"


def test_openai_chat_model_is_separate_from_anthropic_runtime(monkeypatch):
    monkeypatch.setenv("QUORVEX_LLM_LIGHT_MODEL", "glm-light")
    monkeypatch.setenv("OPENAI_MODEL_ID", "gpt-mini")

    assert resolve_openai_chat_model() == "gpt-mini"


def test_infer_display_provider_detects_openai():
    from orchestrator.services.ai_runtime_config import infer_display_provider

    assert infer_display_provider("https://api.openai.com/v1") == "openai"


def test_agent_runner_uses_resolved_model_in_claude_options(monkeypatch):
    from orchestrator.utils.agent_runner import AgentRunner

    monkeypatch.setenv("QUORVEX_LLM_TOOL_DEEP_MODEL", "tool-model")
    runner = AgentRunner(allowed_tools=["mcp__playwright__browser_navigate"])

    selection = apply_runtime_env_aliases(None, tier=runner.model_tier)
    runner.model = selection.model

    assert runner.model_tier == "tool_deep"
    assert runner._claude_options_kwargs()["model"] == "tool-model"


@pytest.mark.asyncio
async def test_agent_runner_run_prefers_explicit_env_vars_for_runtime_aliases(monkeypatch):
    from orchestrator.utils import agent_runner as agent_runner_module
    from orchestrator.utils.agent_runner import AgentRunner

    captured = {}

    class FakeClaudeAgentOptions:
        def __init__(self, **kwargs):
            captured["options"] = kwargs

    class FakeMessage:
        content = "done"

    async def fake_query(prompt, options):
        captured["prompt"] = prompt
        captured["env_during_query"] = {
            "ANTHROPIC_MODEL": os.environ.get("ANTHROPIC_MODEL"),
            "QUORVEX_LLM_API_KEY": os.environ.get("QUORVEX_LLM_API_KEY"),
            "ANTHROPIC_AUTH_TOKEN": os.environ.get("ANTHROPIC_AUTH_TOKEN"),
            "CLAUDE_CODE_OAUTH_TOKEN": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
        }
        yield FakeMessage()

    def fail_active_settings(*_args, **_kwargs):
        raise AssertionError("explicit env_vars should bypass active Settings refresh")

    monkeypatch.setenv("QUORVEX_LLM_STANDARD_MODEL", "stale-process-model")
    monkeypatch.setenv("ANTHROPIC_MODEL", "stale-process-model")
    monkeypatch.setenv("QUORVEX_LLM_API_KEY", "stale-process-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "stale-process-key")
    monkeypatch.setattr(agent_runner_module, "AGENT_QUEUE_AVAILABLE", False)
    monkeypatch.setattr(agent_runner_module, "query", fake_query)
    monkeypatch.setattr(agent_runner_module, "ClaudeAgentOptions", FakeClaudeAgentOptions)
    monkeypatch.setattr(AgentRunner, "_apply_active_ai_settings", staticmethod(fail_active_settings))

    runner = AgentRunner(
        allowed_tools=[],
        log_tools=False,
        model_tier="standard",
        env_vars={
            "QUORVEX_LLM_AUTH_MODE": "claude_code_subscription",
            "QUORVEX_LLM_PROVIDER": "anthropic",
            "CLAUDE_CODE_OAUTH_TOKEN": "oauth-token-1234567890",
            "QUORVEX_LLM_API_KEY": "",
            "ANTHROPIC_AUTH_TOKEN": "",
            "ANTHROPIC_API_KEY": "",
            "QUORVEX_LLM_STANDARD_MODEL": "settings-standard-model",
        },
    )

    result = await runner.run("Return done")

    assert result.success is True
    assert result.output == "done"
    assert captured["options"]["model"] == "settings-standard-model"
    assert captured["env_during_query"]["ANTHROPIC_MODEL"] == "settings-standard-model"
    assert captured["env_during_query"]["QUORVEX_LLM_API_KEY"] is None
    assert captured["env_during_query"]["ANTHROPIC_AUTH_TOKEN"] is None
    assert captured["env_during_query"]["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-token-1234567890"


def test_browser_dialog_policy_applies_only_when_dialog_tool_available():
    from orchestrator.utils.browser_dialog_policy import (
        append_browser_dialog_recovery_policy,
        browser_dialog_recovery_policy_for_tools,
    )

    policy = browser_dialog_recovery_policy_for_tools(
        ["mcp__playwright-test__browser_handle_dialog"]
    )

    assert "Leave site?" in policy
    assert "`accept: true`" in policy
    assert browser_dialog_recovery_policy_for_tools(["Read", "Grep"]) == ""

    prompt = append_browser_dialog_recovery_policy("Browse the app.", ["browser_dialog"])
    assert prompt.count("## Browser Dialog Recovery") == 1
    assert (
        append_browser_dialog_recovery_policy(prompt, ["browser_dialog"]).count(
            "## Browser Dialog Recovery"
        )
        == 1
    )


def test_agent_runner_diagnostics_reports_runtime_and_memory(monkeypatch):
    from orchestrator.api import settings as settings_api
    from orchestrator.utils.agent_runner import AgentRunner

    for key in (
        "QUORVEX_LLM_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
            "ZAI_API_KEY",
        ):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(settings_api, "runtime_env_vars", lambda: {})
    monkeypatch.setenv("QUORVEX_LLM_TOOL_DEEP_MODEL", "diagnostic-tool-model")
    runner = AgentRunner(
        allowed_tools=["Read", "mcp__playwright__browser_navigate"],
        memory_agent_type="NativeHealer",
        memory_stage="native_healer",
        model_tier="tool_deep",
    )

    diagnostics = runner.diagnostics(agent_class="NativeHealer", prompt="hello")

    assert diagnostics["agent_class"] == "NativeHealer"
    assert diagnostics["tier"] == "tool_deep"
    assert diagnostics["model"] == "diagnostic-tool-model"
    assert diagnostics["api_key_set"] is False
    assert diagnostics["mcp_prefixes"] == ["mcp__playwright"]
    assert diagnostics["memory"]["inject"] is True
    assert len(diagnostics["prompt"]["hash"]) == 64


def test_agent_runner_merges_settings_credentials_with_sparse_run_env(monkeypatch, tmp_path):
    from orchestrator.api import settings as settings_api
    from orchestrator.utils.agent_runner import AgentRunner

    fixture_file = tmp_path / "resolved-fixtures.json"
    fixture_file.write_text("{}")
    monkeypatch.setattr(
        settings_api,
        "runtime_env_vars",
        lambda: {
            "QUORVEX_LLM_PROVIDER": "anthropic",
            "QUORVEX_LLM_AUTH_MODE": "api_key",
            "QUORVEX_LLM_BASE_URL": "https://settings.example/anthropic",
            "ANTHROPIC_BASE_URL": "https://settings.example/anthropic",
            "QUORVEX_LLM_API_KEY": "settings-secret-key",
            "QUORVEX_LLM_API_KEYS": "",
            "ANTHROPIC_AUTH_TOKEN": "settings-secret-key",
            "ANTHROPIC_API_KEY": "settings-secret-key",
            "QUORVEX_LLM_LIGHT_MODEL": "settings-light",
            "QUORVEX_LLM_STANDARD_MODEL": "settings-standard",
            "QUORVEX_LLM_DEEP_MODEL": "settings-deep",
            "QUORVEX_LLM_TOOL_DEEP_MODEL": "settings-tool",
            "QUORVEX_LLM_CHAT_MODEL": "settings-chat",
            "QUORVEX_EMBEDDING_MODEL": "settings-embed",
        },
    )

    runner = AgentRunner(
        allowed_tools=["mcp__playwright-test__browser_snapshot"],
        model_tier="tool_deep",
        env_vars={"QUORVEX_TEST_DATA_FILE": str(fixture_file)},
    )

    env_vars = runner._collect_api_env_vars()
    diagnostics = runner.diagnostics(prompt="use fixture")
    diagnostics_json = json.dumps(diagnostics, sort_keys=True)

    assert env_vars["QUORVEX_LLM_API_KEY"] == "settings-secret-key"
    assert env_vars["ANTHROPIC_AUTH_TOKEN"] == "settings-secret-key"
    assert env_vars["ANTHROPIC_API_KEY"] == "settings-secret-key"
    assert env_vars["ANTHROPIC_MODEL"] == "settings-tool"
    assert env_vars["QUORVEX_LLM_ACTIVE_MODEL"] == "settings-tool"
    assert env_vars["QUORVEX_TEST_DATA_FILE"] == str(fixture_file)
    assert diagnostics["api_key_set"] is True
    assert diagnostics["claude_code_oauth_token_set"] is False
    assert "settings-secret-key" not in diagnostics_json


def test_agent_runner_claude_code_settings_survive_sparse_run_env(monkeypatch, tmp_path):
    from orchestrator.api import settings as settings_api
    from orchestrator.utils.agent_runner import AgentRunner

    monkeypatch.setenv("QUORVEX_LLM_PROVIDER", "anthropic_compatible")
    monkeypatch.setenv("QUORVEX_LLM_BASE_URL", "https://api.z.ai/api/anthropic")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.z.ai/api/anthropic")
    monkeypatch.setenv("QUORVEX_LLM_TOOL_DEEP_MODEL", "glm-5.1")
    monkeypatch.setenv("ANTHROPIC_MODEL", "glm-5.1")
    monkeypatch.setenv("QUORVEX_LLM_API_KEY", "stale-process-key")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "stale-process-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "stale-process-key")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "")
    fixture_file = tmp_path / "resolved-fixtures.json"
    fixture_file.write_text("{}")
    monkeypatch.setattr(
        settings_api,
        "runtime_env_vars",
        lambda: {
            "QUORVEX_LLM_PROVIDER": "anthropic",
            "QUORVEX_LLM_AUTH_MODE": "claude_code_subscription",
            "QUORVEX_LLM_BASE_URL": "https://api.anthropic.com",
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "CLAUDE_CODE_OAUTH_TOKEN": "settings-oauth-token",
            "QUORVEX_LLM_API_KEY": "",
            "QUORVEX_LLM_API_KEYS": "",
            "ANTHROPIC_AUTH_TOKEN": "",
            "ANTHROPIC_API_KEY": "",
            "QUORVEX_LLM_STANDARD_MODEL": "claude-standard",
            "QUORVEX_LLM_DEEP_MODEL": "claude-deep",
            "QUORVEX_LLM_TOOL_DEEP_MODEL": "claude-tool",
        },
    )

    runner = AgentRunner(
        model_tier="tool_deep",
        env_vars={"QUORVEX_TEST_DATA_FILE": str(fixture_file)},
    )

    env_vars = runner._collect_api_env_vars()
    diagnostics = runner.diagnostics(prompt="use fixture")

    assert env_vars["CLAUDE_CODE_OAUTH_TOKEN"] == "settings-oauth-token"
    assert env_vars["QUORVEX_LLM_BASE_URL"] == "https://api.anthropic.com"
    assert env_vars["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"
    assert env_vars["ANTHROPIC_MODEL"] == "claude-tool"
    assert env_vars["QUORVEX_LLM_ACTIVE_MODEL"] == "claude-tool"
    assert env_vars["QUORVEX_TEST_DATA_FILE"] == str(fixture_file)
    assert "QUORVEX_LLM_API_KEY" not in env_vars
    assert "ANTHROPIC_AUTH_TOKEN" not in env_vars
    assert "ANTHROPIC_API_KEY" not in env_vars
    assert diagnostics["api_key_set"] is False
    assert diagnostics["claude_code_oauth_token_set"] is True
    assert diagnostics["model"] == "claude-tool"
    assert "settings-oauth-token" not in json.dumps(diagnostics, sort_keys=True)


def test_agent_runner_empty_run_credentials_do_not_mask_settings(monkeypatch):
    from orchestrator.api import settings as settings_api
    from orchestrator.utils.agent_runner import AgentRunner

    monkeypatch.setattr(
        settings_api,
        "runtime_env_vars",
        lambda: {
            "QUORVEX_LLM_PROVIDER": "anthropic",
            "QUORVEX_LLM_AUTH_MODE": "api_key",
            "QUORVEX_LLM_BASE_URL": "https://settings.example/anthropic",
            "ANTHROPIC_BASE_URL": "https://settings.example/anthropic",
            "QUORVEX_LLM_API_KEY": "settings-secret-key",
            "ANTHROPIC_AUTH_TOKEN": "settings-secret-key",
            "ANTHROPIC_API_KEY": "settings-secret-key",
            "QUORVEX_LLM_STANDARD_MODEL": "settings-standard",
        },
    )
    runner = AgentRunner(
        model_tier="standard",
        env_vars={
            "QUORVEX_LLM_API_KEY": "",
            "ANTHROPIC_AUTH_TOKEN": "",
            "ANTHROPIC_API_KEY": "",
            "AGENT_COST_LOG": "/tmp/agent-costs.jsonl",
        },
    )

    env_vars = runner._collect_api_env_vars()

    assert env_vars["QUORVEX_LLM_API_KEY"] == "settings-secret-key"
    assert env_vars["ANTHROPIC_AUTH_TOKEN"] == "settings-secret-key"
    assert env_vars["ANTHROPIC_API_KEY"] == "settings-secret-key"
    assert env_vars["AGENT_COST_LOG"] == "/tmp/agent-costs.jsonl"


def test_agent_runner_forwards_browser_runtime_env(monkeypatch):
    from orchestrator.utils.agent_runner import AgentRunner

    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("VNC_ENABLED", "true")
    monkeypatch.setenv("HEADLESS", "false")
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "false")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")
    monkeypatch.setenv("PLAYWRIGHT_WORKERS", "1")

    runner = AgentRunner(allowed_tools=[])
    env_vars = runner._collect_api_env_vars()

    assert env_vars["DISPLAY"] == ":99"
    assert env_vars["VNC_ENABLED"] == "true"
    assert env_vars["HEADLESS"] == "false"
    assert env_vars["PLAYWRIGHT_HEADLESS"] == "false"
    assert env_vars["PLAYWRIGHT_BROWSERS_PATH"] == "/ms-playwright"
    assert env_vars["PLAYWRIGHT_WORKERS"] == "1"


def test_agent_runner_forwards_resolved_zai_key(monkeypatch):
    from orchestrator.api import settings as settings_api
    from orchestrator.utils.agent_runner import AgentRunner

    for key in (
        "QUORVEX_LLM_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_API_KEY",
        ):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(settings_api, "runtime_env_vars", lambda: {})
    monkeypatch.setenv("QUORVEX_LLM_PROVIDER", "anthropic_compatible")
    monkeypatch.setenv("QUORVEX_LLM_BASE_URL", "https://api.z.ai/api/anthropic")
    monkeypatch.setenv("ZAI_API_KEY", "zai-forwarded-key")

    runner = AgentRunner(allowed_tools=[])
    env_vars = runner._collect_api_env_vars()

    assert env_vars["QUORVEX_LLM_API_KEY"] == "zai-forwarded-key"
    assert env_vars["ANTHROPIC_AUTH_TOKEN"] == "zai-forwarded-key"
    assert env_vars["ANTHROPIC_API_KEY"] == "zai-forwarded-key"


def test_settings_active_config_reads_zai_provider_key(tmp_path, monkeypatch):
    from orchestrator.api import settings as settings_api

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "QUORVEX_LLM_PROVIDER=anthropic_compatible",
                "QUORVEX_LLM_BASE_URL=https://api.z.ai/api/anthropic",
                "ZAI_API_KEY=zai-settings-key",
                "QUORVEX_LLM_CHAT_MODEL=glm-5-turbo",
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(settings_api, "ENV_FILE", env_file)

    active = settings_api._active_settings()

    assert active["llm_provider"] == "zai"
    assert active["api_key"] == "zai-settings-key"


def test_settings_update_model_name_updates_standard_and_chat_only(tmp_path, monkeypatch):
    from orchestrator.api import settings as settings_api

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "ANTHROPIC_AUTH_TOKEN=old-key",
                "ANTHROPIC_MODEL=old-standard",
                "ANTHROPIC_DEFAULT_OPUS_MODEL=old-deep",
                "ANTHROPIC_DEFAULT_SONNET_MODEL=old-standard",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL=old-light",
                "ANTHROPIC_CHAT_MODEL=old-chat",
                "ANTHROPIC_BASE_URL=https://api.anthropic.com",
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(settings_api, "ENV_FILE", env_file)
    monkeypatch.setattr(
        "orchestrator.services.api_key_rotator.get_api_key_rotator",
        lambda: type("Rotator", (), {"initialize": lambda self: None})(),
    )

    response = settings_api.update_settings(
        settings_api.Settings(
            llm_provider="anthropic",
            base_url="https://api.anthropic.com",
            model_name="new-standard",
        )
    )

    env_vars = settings_api._read_env_file()
    assert response["settings"]["model_tiers"]["standard"] == "new-standard"
    assert response["settings"]["model_tiers"]["chat"] == "new-standard"
    assert env_vars["ANTHROPIC_MODEL"] == "new-standard"
    assert env_vars["ANTHROPIC_CHAT_MODEL"] == "new-standard"
    assert env_vars["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "new-standard"
    assert env_vars["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "old-deep"
    assert env_vars["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "old-light"


def test_settings_update_uses_configured_writable_env_file(tmp_path, monkeypatch):
    from orchestrator.api import settings as settings_api

    runtime_env = tmp_path / "runtime" / "runtime.env"
    monkeypatch.setenv("QUORVEX_SETTINGS_ENV_FILE", str(runtime_env))
    monkeypatch.setattr(settings_api, "ENV_FILE", tmp_path / "unwritable-root" / ".env")
    monkeypatch.setattr(
        "orchestrator.services.api_key_rotator.get_api_key_rotator",
        lambda: type("Rotator", (), {"initialize": lambda self: None})(),
    )

    response = settings_api.update_settings(
        settings_api.Settings(
            llm_provider="zai",
            api_key="zai-key",
            base_url="https://api.z.ai/api/anthropic",
            model_name="glm-5.1",
            agent_runtime="hermes",
        )
    )

    env_vars = settings_api._read_env_file()
    assert response["settings"]["agent_runtime"] == "claude_sdk"
    assert runtime_env.exists()
    assert not (tmp_path / "unwritable-root" / ".env").exists()
    assert env_vars["QUORVEX_AGENT_RUNTIME"] == "claude_sdk"
    assert not (tmp_path / "runtime" / "hermes").exists()
    assert not any(key.startswith("HERMES_") for key in env_vars)


def test_settings_update_persists_openai_assistant_runtime(tmp_path, monkeypatch):
    from orchestrator.api import settings as settings_api

    env_file = tmp_path / ".env"
    env_file.write_text("QUORVEX_AGENT_RUNTIME=claude_sdk\nQUORVEX_ASSISTANT_RUNTIME=claude_sdk\n")
    monkeypatch.setattr(settings_api, "ENV_FILE", env_file)
    monkeypatch.setattr(
        "orchestrator.services.api_key_rotator.get_api_key_rotator",
        lambda: type("Rotator", (), {"initialize": lambda self: None})(),
    )

    response = settings_api.update_settings(
        settings_api.Settings(
            llm_provider="openai",
            api_key="sk-openai-test",
            base_url="https://api.openai.com/v1",
            model_name="gpt-4o-mini",
            agent_runtime="claude_sdk",
            assistant_runtime="openai",
        )
    )

    env_vars = settings_api._read_env_file()
    assert response["settings"]["llm_provider"] == "openai"
    assert response["settings"]["agent_runtime"] == "claude_sdk"
    assert response["settings"]["assistant_runtime"] == "openai"
    assert env_vars["QUORVEX_ASSISTANT_RUNTIME"] == "openai"
    assert "OPENAI_API_KEY" not in env_vars
    assert os.environ["OPENAI_API_KEY"] == "sk-openai-test"
    assert env_vars["OPENAI_BASE_URL"] == "https://api.openai.com/v1"
    assert not any(key.startswith("HERMES_") for key in env_vars)
    assert not (tmp_path / "data" / "hermes").exists()


def test_apply_runtime_settings_projects_agent_and_assistant_runtime(monkeypatch):
    from orchestrator.api import settings as settings_api

    monkeypatch.delenv("QUORVEX_AGENT_RUNTIME", raising=False)
    monkeypatch.delenv("QUORVEX_ASSISTANT_RUNTIME", raising=False)
    monkeypatch.setattr(
        "orchestrator.services.api_key_rotator.get_api_key_rotator",
        lambda: type("Rotator", (), {"initialize": lambda self: None})(),
    )

    settings_api._apply_runtime_settings(
        {
            "QUORVEX_LLM_PROVIDER": "anthropic",
            "QUORVEX_LLM_AUTH_MODE": "claude_code_subscription",
            "QUORVEX_LLM_BASE_URL": "https://api.anthropic.com",
            "CLAUDE_CODE_OAUTH_TOKEN": "oauth-token",
            "QUORVEX_AGENT_RUNTIME": "claude_sdk",
            "QUORVEX_ASSISTANT_RUNTIME": "openai",
        }
    )

    assert os.environ["QUORVEX_AGENT_RUNTIME"] == "claude_sdk"
    assert os.environ["QUORVEX_ASSISTANT_RUNTIME"] == "openai"


@pytest.mark.asyncio
async def test_settings_test_connection_uses_openai_chat_completions(tmp_path, monkeypatch):
    from orchestrator.api import settings as settings_api

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "QUORVEX_LLM_PROVIDER=openai",
                "QUORVEX_LLM_BASE_URL=https://api.openai.com/v1",
                "OPENAI_BASE_URL=https://api.openai.com/v1",
                "QUORVEX_LLM_API_KEY=sk-openai-test",
                "OPENAI_API_KEY=sk-openai-test",
                "QUORVEX_LLM_CHAT_MODEL=gpt-4o-mini",
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(settings_api, "ENV_FILE", env_file)
    seen: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = "{}"

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            seen["url"] = url
            seen["headers"] = headers
            seen["json"] = json
            return FakeResponse()

    monkeypatch.setattr(settings_api.httpx, "AsyncClient", FakeClient)

    result = await settings_api.test_settings_connection()

    assert result.ok is True
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer sk-openai-test"
    assert seen["json"]["model"] == "gpt-4o-mini"
