"""Canonical runtime AI provider and model selection.

This module is the boundary between Quorvex runtime code and environment
variables. Runtime callers should resolve a tier here instead of reading
provider/model env vars directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

RuntimeModelTier = Literal["light", "standard", "deep", "tool_deep", "chat", "embedding"]
RuntimeProvider = Literal["anthropic_compatible", "openai_compatible"]

DEFAULT_BASE_URL = "https://api.z.ai/api/anthropic"
DEFAULT_LIGHT_MODEL = "glm-4.5-air"
DEFAULT_STANDARD_MODEL = "glm-5-turbo"
DEFAULT_DEEP_MODEL = "glm-5.1"
DEFAULT_OPENAI_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

CANONICAL_MODEL_ENV: dict[RuntimeModelTier, str] = {
    "light": "QUORVEX_LLM_LIGHT_MODEL",
    "standard": "QUORVEX_LLM_STANDARD_MODEL",
    "deep": "QUORVEX_LLM_DEEP_MODEL",
    "tool_deep": "QUORVEX_LLM_TOOL_DEEP_MODEL",
    "chat": "QUORVEX_LLM_CHAT_MODEL",
    "embedding": "QUORVEX_EMBEDDING_MODEL",
}

LEGACY_MODEL_ENV: dict[RuntimeModelTier, tuple[str, ...]] = {
    "light": ("ANTHROPIC_DEFAULT_HAIKU_MODEL",),
    "standard": ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL"),
    "deep": ("ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_MODEL"),
    "tool_deep": ("ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_MODEL"),
    "chat": ("ANTHROPIC_CHAT_MODEL", "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL"),
    "embedding": ("EMBEDDING_MODEL", "OPENAI_EMBEDDING_MODEL"),
}

DEFAULT_MODEL_BY_TIER: dict[RuntimeModelTier, str] = {
    "light": DEFAULT_LIGHT_MODEL,
    "standard": DEFAULT_STANDARD_MODEL,
    "deep": DEFAULT_DEEP_MODEL,
    "tool_deep": DEFAULT_DEEP_MODEL,
    "chat": DEFAULT_STANDARD_MODEL,
    "embedding": DEFAULT_EMBEDDING_MODEL,
}

ANTHROPIC_COMPATIBLE_KEY_ENV = (
    "QUORVEX_LLM_API_KEY",
    "QUORVEX_LLM_API_KEYS",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
)


@dataclass(frozen=True)
class RuntimeAISelection:
    """Resolved runtime AI selection for a specific task tier."""

    tier: RuntimeModelTier
    provider: RuntimeProvider
    runtime: str
    model: str
    base_url: str
    api_key: str
    api_key_env: str | None
    temperature: float
    max_tokens: int
    reasoning_budget: int | None = None


def _env_get(env_vars: dict[str, str] | None, key: str, default: str = "") -> str:
    if env_vars is not None and key in env_vars:
        return env_vars.get(key, "")
    return os.environ.get(key, default)


def _first_env(env_vars: dict[str, str] | None, keys: tuple[str, ...], default: str = "") -> tuple[str, str | None]:
    if env_vars is not None:
        found_in_env_vars = False
        for key in keys:
            if key in env_vars:
                found_in_env_vars = True
            value = env_vars.get(key, "")
            if value:
                return value, key
        if found_in_env_vars:
            return default, None
    for key in keys:
        value = os.environ.get(key, "")
        if value:
            return value, key
    return default, None


def _api_key_value(key: str, value: str) -> str:
    if key == "QUORVEX_LLM_API_KEYS":
        return value.split(",", 1)[0].strip()
    return value


def _first_api_key(env_vars: dict[str, str] | None, keys: tuple[str, ...], default: str = "") -> tuple[str, str | None]:
    if env_vars is not None:
        found_in_env_vars = False
        for key in keys:
            if key in env_vars:
                found_in_env_vars = True
            value = _api_key_value(key, env_vars.get(key, ""))
            if value:
                return value, key
        if found_in_env_vars:
            return default, None
    for key in keys:
        value = _api_key_value(key, os.environ.get(key, ""))
        if value:
            return value, key
    return default, None


def normalize_runtime_provider(value: str | None, base_url: str | None = None) -> RuntimeProvider:
    raw = (value or "").strip().lower()
    if raw in {"openai", "openai_compatible", "openai-compatible"}:
        return "openai_compatible"
    if raw in {
        "anthropic",
        "anthropic_compatible",
        "anthropic-compatible",
        "claude_code_subscription",
        "zai",
        "openrouter",
        "custom",
        "hermes",
        "hermes_agent",
        "hermes-agent",
    }:
        return "anthropic_compatible"

    url = (base_url or "").lower()
    if "openai.com" in url:
        return "openai_compatible"
    return "anthropic_compatible"


def infer_display_provider(base_url: str | None) -> str:
    """Return the settings/UI provider label for the configured base URL."""

    base_url_lower = (base_url or "").lower()
    if "api.openai.com" in base_url_lower:
        return "openai"
    if "api.z.ai" in base_url_lower or "bigmodel.cn" in base_url_lower:
        return "zai"
    if "openrouter.ai" in base_url_lower:
        return "openrouter"
    if "anthropic.com" in base_url_lower or not base_url_lower:
        return "anthropic"
    return "custom"


def anthropic_compatible_key_env(base_url: str | None = None) -> tuple[str, ...]:
    """Return credential env precedence for Anthropic-compatible runtimes."""

    provider = infer_display_provider(base_url)
    if provider == "zai":
        return (*ANTHROPIC_COMPATIBLE_KEY_ENV, "ZAI_API_KEY")
    return ANTHROPIC_COMPATIBLE_KEY_ENV


def resolve_model(tier: RuntimeModelTier, env_vars: dict[str, str] | None = None, override: str | None = None) -> str:
    """Resolve the model for a tier from canonical env, legacy aliases, then defaults."""

    if override:
        return override
    canonical = CANONICAL_MODEL_ENV[tier]
    model, _ = _first_env(env_vars, (canonical, *LEGACY_MODEL_ENV[tier]), DEFAULT_MODEL_BY_TIER[tier])
    return model


def resolve_runtime_ai_selection(
    tier: RuntimeModelTier = "standard",
    *,
    env_vars: dict[str, str] | None = None,
    model_override: str | None = None,
    runtime_override: str | None = None,
) -> RuntimeAISelection:
    """Resolve provider, model, credential, and generation defaults for a task tier."""

    base_url, _ = _first_env(env_vars, ("QUORVEX_LLM_BASE_URL", "ANTHROPIC_BASE_URL"), DEFAULT_BASE_URL)
    provider_value = env_vars.get("QUORVEX_LLM_PROVIDER", "") if env_vars is not None else os.environ.get("QUORVEX_LLM_PROVIDER", "")
    provider = normalize_runtime_provider(provider_value, base_url)
    runtime_value = env_vars.get("QUORVEX_AGENT_RUNTIME", "") if env_vars is not None else os.environ.get("QUORVEX_AGENT_RUNTIME", "")
    runtime = runtime_override or runtime_value or "claude_sdk"

    if provider == "openai_compatible":
        base_url = _env_get(env_vars, "OPENAI_BASE_URL") or base_url
        fallback_model = DEFAULT_OPENAI_CHAT_MODEL if tier != "embedding" else DEFAULT_EMBEDDING_MODEL
        model = model_override or _env_get(env_vars, CANONICAL_MODEL_ENV[tier]) or _env_get(
            env_vars, "OPENAI_MODEL_ID", fallback_model
        )
        api_key, api_key_env = _first_api_key(
            env_vars, ("QUORVEX_LLM_API_KEY", "QUORVEX_LLM_API_KEYS", "OPENAI_API_KEY")
        )
    else:
        model = resolve_model(tier, env_vars, model_override)
        api_key, api_key_env = _first_api_key(env_vars, anthropic_compatible_key_env(base_url))

    temperature_by_tier = {
        "light": 0.0,
        "standard": 0.1,
        "deep": 0.1,
        "tool_deep": 0.0,
        "chat": 0.3,
        "embedding": 0.0,
    }
    max_tokens_by_tier = {
        "light": 1000,
        "standard": 4096,
        "deep": 8192,
        "tool_deep": 8192,
        "chat": 2048,
        "embedding": 0,
    }
    reasoning_budget_by_tier = {
        "deep": int(_env_get(env_vars, "QUORVEX_LLM_DEEP_REASONING_BUDGET", "2048") or "2048"),
        "tool_deep": int(_env_get(env_vars, "QUORVEX_LLM_TOOL_DEEP_REASONING_BUDGET", "4096") or "4096"),
    }

    return RuntimeAISelection(
        tier=tier,
        provider=provider,
        runtime=runtime,
        model=model,
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        api_key_env=api_key_env,
        temperature=temperature_by_tier[tier],
        max_tokens=max_tokens_by_tier[tier],
        reasoning_budget=reasoning_budget_by_tier.get(tier),
    )


def model_tiers(env_vars: dict[str, str] | None = None) -> dict[str, str]:
    """Return all configured runtime model tiers."""

    return {tier: resolve_model(tier, env_vars) for tier in CANONICAL_MODEL_ENV}


def resolve_openai_chat_model(env_vars: dict[str, str] | None = None, default: str = DEFAULT_OPENAI_CHAT_MODEL) -> str:
    """Resolve an OpenAI-compatible chat model for OpenAI-only utilities."""

    model, _ = _first_env(
        env_vars,
        (
            "QUORVEX_OPENAI_MODEL",
            "QUORVEX_MEMORY_LLM_MODEL",
            "OPENAI_MODEL_ID",
            "OPENAI_MODEL",
            "OPENAI_CHAT_MODEL",
        ),
        default,
    )
    return model


def apply_runtime_env_aliases(
    env_vars: dict[str, str] | None = None,
    *,
    tier: RuntimeModelTier = "standard",
    model_override: str | None = None,
) -> RuntimeAISelection:
    """Apply canonical settings to legacy env names expected by SDK/CLI clients."""

    selection = resolve_runtime_ai_selection(tier, env_vars=env_vars, model_override=model_override)

    os.environ["QUORVEX_LLM_BASE_URL"] = selection.base_url
    os.environ["ANTHROPIC_BASE_URL"] = selection.base_url
    os.environ[CANONICAL_MODEL_ENV[tier]] = selection.model
    os.environ["ANTHROPIC_MODEL"] = selection.model

    tiers = model_tiers(env_vars)
    os.environ["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = tiers["light"]
    os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"] = tiers["standard"]
    os.environ["ANTHROPIC_DEFAULT_OPUS_MODEL"] = tiers["deep"]
    os.environ["ANTHROPIC_CHAT_MODEL"] = tiers["chat"]
    os.environ["QUORVEX_LLM_LIGHT_MODEL"] = tiers["light"]
    os.environ["QUORVEX_LLM_STANDARD_MODEL"] = tiers["standard"]
    os.environ["QUORVEX_LLM_DEEP_MODEL"] = tiers["deep"]
    os.environ["QUORVEX_LLM_TOOL_DEEP_MODEL"] = tiers["tool_deep"]
    os.environ["QUORVEX_LLM_CHAT_MODEL"] = tiers["chat"]
    os.environ["QUORVEX_EMBEDDING_MODEL"] = tiers["embedding"]

    if selection.api_key:
        os.environ["QUORVEX_LLM_API_KEY"] = selection.api_key
        if selection.provider == "anthropic_compatible":
            os.environ["ANTHROPIC_AUTH_TOKEN"] = selection.api_key
            os.environ["ANTHROPIC_API_KEY"] = selection.api_key

    return selection
