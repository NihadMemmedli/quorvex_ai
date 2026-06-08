import os
import time
from typing import Any
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from orchestrator.api.db import get_session
from orchestrator.api.models_db import Project
from orchestrator.services.ai_runtime_config import (
    CANONICAL_MODEL_ENV,
    DEFAULT_BASE_URL,
    RuntimeModelTier,
    apply_runtime_env_aliases,
    infer_display_provider,
    model_tiers,
    resolve_runtime_ai_selection,
)

router = APIRouter()
DEFAULT_PROJECT_ID = "default"
DEFAULT_PROJECT_NAME = "Default Project"
RUNTIME_SETTINGS_KEY = "ai_runtime_settings"


class Settings(BaseModel):
    llm_provider: str
    api_key: str | None = None
    base_url: str | None = None
    model_name: str | None = None
    light_model: str | None = None
    standard_model: str | None = None
    deep_model: str | None = None
    tool_deep_model: str | None = None
    chat_model: str | None = None
    embedding_model: str | None = None
    model_tiers: dict[str, str] | None = None
    agent_runtime: str | None = None
    assistant_runtime: str | None = None
    hermes_enabled: bool | None = None
    hermes_api_url: str | None = None
    hermes_api_key: str | None = None
    hermes_model: str | None = None
    hermes_sync_provider: bool | None = True


class SettingsConnectionResult(BaseModel):
    ok: bool
    model_name: str
    base_url: str
    message: str
    latency_ms: int | None = None


class HermesConnectionResult(BaseModel):
    ok: bool
    reachable: bool
    status: str
    message: str
    api_url: str
    model: str
    upstream_provider: str
    upstream_model: str
    hermes_home: str
    config_path: str
    env_path: str
    config_exists: bool
    env_exists: bool
    latency_ms: int | None = None


# Project .env file path. In containers, QUORVEX_SETTINGS_ENV_FILE points this
# at a writable shared data volume instead of the read-only application root.
ENV_FILE = Path(__file__).parent.parent.parent / ".env"
MODEL_ENV_KEYS = (
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_CHAT_MODEL",
    *CANONICAL_MODEL_ENV.values(),
)
DEFAULT_ANTHROPIC_BASE_URL = DEFAULT_BASE_URL
DEFAULT_HERMES_API_URL = "http://hermes:8642"
DEFAULT_HERMES_MODEL = "hermes-agent"
HERMES_RUNTIME_ALIASES = {
    "claude": "claude_sdk",
    "claude_sdk": "claude_sdk",
    "claude-agent-sdk": "claude_sdk",
    "hermes": "hermes",
    "hermes_agent": "hermes",
    "hermes-agent": "hermes",
}
ASSISTANT_RUNTIME_ALIASES = {
    **HERMES_RUNTIME_ALIASES,
    "openai": "openai",
    "openai_sdk": "openai",
    "openai-sdk": "openai",
}


def _env_file_path() -> Path:
    override = os.environ.get("QUORVEX_SETTINGS_ENV_FILE")
    if override:
        return Path(override)
    return ENV_FILE


def _runtime_data_dir() -> Path:
    if os.environ.get("QUORVEX_SETTINGS_ENV_FILE"):
        return _env_file_path().parent
    return ENV_FILE.parent / "data"


def _read_env_file() -> dict:
    """Read key-value pairs from .env file"""
    env_vars = {}
    env_file = _env_file_path()
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars


def _ensure_default_project(session: Session) -> Project:
    project = session.get(Project, DEFAULT_PROJECT_ID)
    if project:
        return project
    project = Project(
        id=DEFAULT_PROJECT_ID,
        name=DEFAULT_PROJECT_NAME,
        description="Default project for all existing and new content",
        settings={},
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def _write_env_file(env_vars: dict):
    """Write key-value pairs to .env file, preserving comments and structure"""
    env_file = _env_file_path()
    env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    existing_keys = set()

    # Read existing file to preserve structure and comments
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                stripped = line.strip()
                # Keep comments and empty lines as-is
                if not stripped or stripped.startswith("#"):
                    lines.append(line.rstrip("\n"))
                    continue
                if "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    existing_keys.add(key)
                    # Update if we have a new value for this key
                    if key in env_vars:
                        lines.append(f"{key}={env_vars[key]}")
                    else:
                        lines.append(line.rstrip("\n"))
                else:
                    lines.append(line.rstrip("\n"))

    # Add any new keys that weren't in the file
    for key, value in env_vars.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}")

    with open(env_file, "w") as f:
        f.write("\n".join(lines) + "\n")


def _mask_api_key(api_key: str | None) -> str:
    """Mask an API key for display."""
    if not api_key:
        return ""
    if len(api_key) > 8:
        return api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]
    return "********"


def _is_masked_api_key(api_key: str | None) -> bool:
    """Return True when the submitted value is a masked display value."""
    if not api_key:
        return False
    return set(api_key) == {"*"} or "*" in api_key


def _encrypt_runtime_secret(value: str) -> str:
    from orchestrator.api.credentials import encrypt_credential

    return encrypt_credential(value)


def _decrypt_runtime_secret(value: str) -> str:
    from orchestrator.api.credentials import decrypt_credential

    return decrypt_credential(value)


def _infer_provider(base_url: str | None) -> str:
    """Infer the configured provider from the base URL."""
    return infer_display_provider(base_url)


def _infer_hermes_provider(llm_provider: str, base_url: str | None) -> str:
    if llm_provider == "openrouter":
        return "openrouter"
    if llm_provider == "zai":
        return "zai"
    if llm_provider == "anthropic":
        return "anthropic"
    if llm_provider == "openai":
        return "openai"
    base_url_lower = (base_url or "").lower()
    if "openrouter.ai" in base_url_lower:
        return "openrouter"
    if "api.z.ai" in base_url_lower or "bigmodel.cn" in base_url_lower:
        return "zai"
    if "anthropic.com" in base_url_lower:
        return "anthropic"
    if "api.openai.com" in base_url_lower:
        return "openai"
    return "custom"


def _normalize_runtime(value: str | None) -> str:
    if not value:
        return "claude_sdk"
    return HERMES_RUNTIME_ALIASES.get(value.strip().lower(), "claude_sdk")


def _normalize_assistant_runtime(value: str | None) -> str:
    if not value:
        return "claude_sdk"
    return ASSISTANT_RUNTIME_ALIASES.get(value.strip().lower(), "claude_sdk")


def _is_truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _hermes_config_dir() -> Path:
    return _runtime_data_dir() / "hermes"


def _yaml_scalar(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _write_hermes_provider_bundle(active: dict[str, str], env_vars: dict[str, str]) -> dict[str, str]:
    """Write a Hermes home bundle that mirrors Quorvex's active model provider."""
    provider = _infer_hermes_provider(active["llm_provider"], active["base_url"])
    model_name = active["model_name"] or "glm-5.1"
    api_key = active["api_key"]
    base_url = (active["base_url"] or "").rstrip("/")
    config_dir = _hermes_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    hermes_env: dict[str, str] = {
        "API_SERVER_ENABLED": "true",
        "API_SERVER_HOST": "127.0.0.1",
        "API_SERVER_PORT": "8642",
        "API_SERVER_KEY": env_vars.get("HERMES_API_KEY", ""),
    }
    if provider == "openrouter":
        hermes_env["OPENROUTER_API_KEY"] = api_key
    elif provider == "zai":
        hermes_env["GLM_API_KEY"] = api_key
    elif provider == "anthropic":
        hermes_env["ANTHROPIC_API_KEY"] = api_key
    elif provider == "openai":
        hermes_env["OPENAI_API_KEY"] = api_key
    else:
        hermes_env["OPENAI_API_KEY"] = api_key
        if base_url:
            hermes_env["OPENAI_BASE_URL"] = base_url

    env_lines = [f"{key}={value}" for key, value in hermes_env.items()]
    (config_dir / ".env").write_text("\n".join(env_lines) + "\n")

    config_lines = [
        "model:",
        f"  provider: {_yaml_scalar(provider)}",
        f"  default: {_yaml_scalar(model_name)}",
    ]
    if provider == "custom" and base_url:
        config_lines.append(f"  base_url: {_yaml_scalar(base_url)}")
    config_lines.extend(
        [
            "mcp_servers:",
            "  quorvex_playwright:",
            "    command: npx",
            "    args:",
            "      - -y",
            "      - '@playwright/mcp@0.0.75'",
            "      - --browser",
            "      - chromium",
            "      - --isolated",
            "    env:",
            "      DISPLAY: ':99'",
            "      HEADLESS: 'false'",
            "terminal:",
            "  backend: docker",
            f"  cwd: {_yaml_scalar(str(_runtime_data_dir().parent))}",
            "  docker_mount_cwd_to_workspace: true",
        ]
    )
    (config_dir / "config.yaml").write_text("\n".join(config_lines) + "\n")

    env_vars["HERMES_HOME"] = str(config_dir)
    env_vars["HERMES_UPSTREAM_PROVIDER"] = provider
    env_vars["HERMES_UPSTREAM_MODEL"] = model_name
    return {
        "provider": provider,
        "model": model_name,
        "home": str(config_dir),
        "config_path": str(config_dir / "config.yaml"),
        "env_path": str(config_dir / ".env"),
    }


def _check_hermes_gateway(active: dict[str, str] | None = None) -> dict[str, Any]:
    active = active or _active_settings()
    if not _is_truthy(active.get("hermes_enabled"), default=False):
        return {
            "reachable": False,
            "status": "disabled",
            "message": "Hermes is disabled.",
        }

    url = (active.get("hermes_api_url") or DEFAULT_HERMES_API_URL).rstrip("/")
    headers = {}
    if active.get("hermes_api_key"):
        headers["Authorization"] = f"Bearer {active['hermes_api_key']}"

    try:
        with httpx.Client(timeout=1.5) as client:
            response = client.get(f"{url}/v1/runs", headers=headers)
        if response.status_code in {401, 403}:
            return {
                "reachable": False,
                "status": "unauthorized",
                "message": f"Hermes API rejected the configured bearer token with HTTP {response.status_code}.",
            }
        reachable = 200 <= response.status_code < 300
        return {
            "reachable": reachable,
            "status": "reachable" if reachable else "error",
            "message": f"Hermes API responded with HTTP {response.status_code}.",
        }
    except Exception as exc:
        return {
            "reachable": False,
            "status": "unreachable",
            "message": f"Hermes API is not reachable at {url}: {exc}",
        }


def _active_settings_from_env(env_vars: dict[str, str] | None = None) -> dict[str, str]:
    """Return active AI settings from a resolved env-style mapping."""
    env_vars = env_vars if env_vars is not None else _read_env_file()
    selection = resolve_runtime_ai_selection("chat", env_vars=env_vars)
    tiers = model_tiers(env_vars)
    base_url = selection.base_url or DEFAULT_ANTHROPIC_BASE_URL
    model_name = selection.model
    provider_label = env_vars.get("QUORVEX_LLM_PROVIDER") or os.environ.get("QUORVEX_LLM_PROVIDER") or ""
    if provider_label in {"anthropic_compatible", "openai_compatible"}:
        provider_label = _infer_provider(base_url)
    if selection.provider == "anthropic_compatible":
        model_name = (
            env_vars.get("QUORVEX_LLM_DEEP_MODEL")
            or env_vars.get("ANTHROPIC_MODEL")
            or env_vars.get("ANTHROPIC_DEFAULT_OPUS_MODEL")
            or selection.model
        )
    api_key = selection.api_key
    if not api_key:
        if provider_label == "openai":
            api_key = (
                env_vars.get("QUORVEX_LLM_API_KEY")
                or env_vars.get("OPENAI_API_KEY")
                or os.environ.get("QUORVEX_LLM_API_KEY", "")
                or os.environ.get("OPENAI_API_KEY", "")
            )
        else:
            api_key = (
                env_vars.get("QUORVEX_LLM_API_KEY")
                or env_vars.get("QUORVEX_LLM_API_KEYS", "").split(",", 1)[0].strip()
                or env_vars.get("ANTHROPIC_AUTH_TOKEN")
                or env_vars.get("ANTHROPIC_API_KEY")
                or os.environ.get("QUORVEX_LLM_API_KEY", "")
                or os.environ.get("QUORVEX_LLM_API_KEYS", "").split(",", 1)[0].strip()
                or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
                or os.environ.get("ANTHROPIC_API_KEY", "")
            )
    agent_runtime = _normalize_runtime(env_vars.get("QUORVEX_AGENT_RUNTIME") or os.environ.get("QUORVEX_AGENT_RUNTIME"))
    return {
        "base_url": base_url,
        "model_name": model_name,
        "light_model": tiers["light"],
        "standard_model": tiers["standard"],
        "deep_model": tiers["deep"],
        "tool_deep_model": tiers["tool_deep"],
        "chat_model": tiers["chat"],
        "embedding_model": tiers["embedding"],
        "api_key": api_key,
        "llm_provider": provider_label or _infer_provider(base_url),
        "agent_runtime": agent_runtime,
        "assistant_runtime": _normalize_assistant_runtime(
            env_vars.get("QUORVEX_ASSISTANT_RUNTIME")
            or os.environ.get("QUORVEX_ASSISTANT_RUNTIME")
            or agent_runtime
        ),
        "hermes_enabled": str(
            _is_truthy(env_vars.get("HERMES_ENABLED") or os.environ.get("HERMES_ENABLED"), default=False)
        ).lower(),
        "hermes_api_url": env_vars.get("HERMES_API_URL")
        or os.environ.get("HERMES_API_URL", DEFAULT_HERMES_API_URL),
        "hermes_api_key": env_vars.get("HERMES_API_KEY") or os.environ.get("HERMES_API_KEY", ""),
        "hermes_model": env_vars.get("HERMES_MODEL") or os.environ.get("HERMES_MODEL", DEFAULT_HERMES_MODEL),
        "hermes_sync_provider": env_vars.get("HERMES_SYNC_PROVIDER")
        or os.environ.get("HERMES_SYNC_PROVIDER", "true"),
        "hermes_upstream_provider": env_vars.get("HERMES_UPSTREAM_PROVIDER")
        or os.environ.get("HERMES_UPSTREAM_PROVIDER", ""),
        "hermes_upstream_model": env_vars.get("HERMES_UPSTREAM_MODEL") or os.environ.get("HERMES_UPSTREAM_MODEL", ""),
        "hermes_home": env_vars.get("HERMES_HOME") or os.environ.get("HERMES_HOME", ""),
    }


def _settings_to_env_vars(settings: dict[str, Any]) -> dict[str, str]:
    env_vars: dict[str, str] = {}
    provider = str(settings.get("llm_provider") or "zai")
    base_url = str(settings.get("base_url") or DEFAULT_ANTHROPIC_BASE_URL).rstrip("/")
    api_key = _decrypt_runtime_secret(str(settings.get("api_key_encrypted") or ""))
    hermes_api_key = _decrypt_runtime_secret(str(settings.get("hermes_api_key_encrypted") or ""))

    env_vars["QUORVEX_LLM_PROVIDER"] = provider
    env_vars["QUORVEX_LLM_BASE_URL"] = base_url
    env_vars["ANTHROPIC_BASE_URL"] = base_url
    if provider == "openai":
        env_vars["OPENAI_BASE_URL"] = base_url
    if api_key:
        env_vars["QUORVEX_LLM_API_KEY"] = api_key
        env_vars["QUORVEX_LLM_API_KEYS"] = ""
        if provider == "openai":
            env_vars["OPENAI_API_KEY"] = api_key
        else:
            env_vars["ANTHROPIC_AUTH_TOKEN"] = api_key
            env_vars["ANTHROPIC_API_KEY"] = api_key
            env_vars["ANTHROPIC_AUTH_TOKENS"] = ""

    tiers = {
        "light": settings.get("light_model"),
        "standard": settings.get("standard_model") or settings.get("model_name"),
        "deep": settings.get("deep_model") or settings.get("model_name"),
        "tool_deep": settings.get("tool_deep_model") or settings.get("deep_model") or settings.get("model_name"),
        "chat": settings.get("chat_model") or settings.get("standard_model") or settings.get("model_name"),
        "embedding": settings.get("embedding_model"),
    }
    for tier, model in tiers.items():
        if model and tier in CANONICAL_MODEL_ENV:
            env_vars[CANONICAL_MODEL_ENV[tier]] = str(model)
    if tiers.get("light"):
        env_vars["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = str(tiers["light"])
    if tiers.get("standard"):
        env_vars["ANTHROPIC_DEFAULT_SONNET_MODEL"] = str(tiers["standard"])
        env_vars["ANTHROPIC_MODEL"] = str(tiers["standard"])
        if provider == "openai":
            env_vars["OPENAI_MODEL_ID"] = str(tiers["standard"])
    if tiers.get("deep"):
        env_vars["ANTHROPIC_DEFAULT_OPUS_MODEL"] = str(tiers["deep"])
    if tiers.get("chat"):
        env_vars["ANTHROPIC_CHAT_MODEL"] = str(tiers["chat"])
        if provider == "openai":
            env_vars["OPENAI_CHAT_MODEL"] = str(tiers["chat"])
    if tiers.get("embedding"):
        env_vars["EMBEDDING_MODEL"] = str(tiers["embedding"])

    env_vars["QUORVEX_AGENT_RUNTIME"] = _normalize_runtime(str(settings.get("agent_runtime") or "claude_sdk"))
    env_vars["QUORVEX_ASSISTANT_RUNTIME"] = _normalize_assistant_runtime(
        str(settings.get("assistant_runtime") or env_vars["QUORVEX_AGENT_RUNTIME"])
    )
    env_vars["HERMES_ENABLED"] = "true" if bool(settings.get("hermes_enabled")) else "false"
    env_vars["HERMES_API_URL"] = str(settings.get("hermes_api_url") or DEFAULT_HERMES_API_URL).rstrip("/")
    env_vars["HERMES_MODEL"] = str(settings.get("hermes_model") or DEFAULT_HERMES_MODEL)
    env_vars["HERMES_SYNC_PROVIDER"] = "true" if bool(settings.get("hermes_sync_provider", True)) else "false"
    if hermes_api_key:
        env_vars["HERMES_API_KEY"] = hermes_api_key
    for source_key, env_key in (
        ("hermes_home", "HERMES_HOME"),
        ("hermes_upstream_provider", "HERMES_UPSTREAM_PROVIDER"),
        ("hermes_upstream_model", "HERMES_UPSTREAM_MODEL"),
    ):
        if settings.get(source_key):
            env_vars[env_key] = str(settings[source_key])
    return env_vars


def _settings_from_active(active: dict[str, str]) -> dict[str, Any]:
    return {
        "llm_provider": active["llm_provider"],
        "base_url": active["base_url"],
        "model_name": active["model_name"],
        "light_model": active["light_model"],
        "standard_model": active["standard_model"],
        "deep_model": active["deep_model"],
        "tool_deep_model": active["tool_deep_model"],
        "chat_model": active["chat_model"],
        "embedding_model": active["embedding_model"],
        "api_key_encrypted": _encrypt_runtime_secret(active["api_key"]) if active.get("api_key") else "",
        "agent_runtime": active["agent_runtime"],
        "assistant_runtime": active["assistant_runtime"],
        "hermes_enabled": _is_truthy(active["hermes_enabled"]),
        "hermes_api_url": active["hermes_api_url"],
        "hermes_api_key_encrypted": _encrypt_runtime_secret(active["hermes_api_key"]) if active.get("hermes_api_key") else "",
        "hermes_model": active["hermes_model"],
        "hermes_sync_provider": _is_truthy(active["hermes_sync_provider"], default=True),
        "hermes_upstream_provider": active["hermes_upstream_provider"],
        "hermes_upstream_model": active["hermes_upstream_model"],
        "hermes_home": active["hermes_home"],
    }


def _db_runtime_settings(session: Session, *, initialize: bool = True) -> dict[str, Any] | None:
    project = _ensure_default_project(session)
    project_settings = dict(project.settings or {})
    runtime_settings = project_settings.get(RUNTIME_SETTINGS_KEY)
    if isinstance(runtime_settings, dict):
        return runtime_settings
    if not initialize:
        return None

    runtime_settings = _settings_from_active(_active_settings_from_env(_read_env_file()))
    project_settings[RUNTIME_SETTINGS_KEY] = runtime_settings
    project.settings = project_settings
    session.add(project)
    session.commit()
    session.refresh(project)
    return runtime_settings


def _save_db_runtime_settings(session: Session, runtime_settings: dict[str, Any]) -> None:
    project = _ensure_default_project(session)
    project_settings = dict(project.settings or {})
    project_settings[RUNTIME_SETTINGS_KEY] = runtime_settings
    project.settings = project_settings
    session.add(project)
    session.commit()
    session.refresh(project)


def runtime_env_vars(session: Session | None = None) -> dict[str, str]:
    """Return Settings-backed runtime values as env-style keys, falling back to env bootstrap."""
    if session is not None:
        runtime_settings = _db_runtime_settings(session)
        return _settings_to_env_vars(runtime_settings or {})
    try:
        from orchestrator.api.db import engine

        with Session(engine) as db_session:
            runtime_settings = _db_runtime_settings(db_session)
            return _settings_to_env_vars(runtime_settings or {})
    except Exception:
        return _read_env_file()


def _coerce_session(session: Any) -> tuple[Session, bool]:
    if isinstance(session, Session):
        return session, False
    from orchestrator.api.db import engine

    return Session(engine), True


def _active_settings(env_vars: dict[str, str] | None = None, session: Session | None = None) -> dict[str, str]:
    """Return active AI settings, preferring DB-backed Settings over env bootstrap."""
    return _active_settings_from_env(env_vars if env_vars is not None else runtime_env_vars(session))


def _apply_runtime_settings(env_vars: dict[str, str], new_api_key: str | None = None):
    """Apply persisted settings to this running backend process."""
    for key in (
        "QUORVEX_LLM_PROVIDER",
        "QUORVEX_LLM_BASE_URL",
        "QUORVEX_LLM_API_KEY",
        "QUORVEX_LLM_API_KEYS",
        "ANTHROPIC_BASE_URL",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL_ID",
        "OPENAI_CHAT_MODEL",
        *MODEL_ENV_KEYS,
    ):
        value = env_vars.get(key)
        if value is not None:
            os.environ[key] = value

    if new_api_key:
        os.environ["QUORVEX_LLM_API_KEY"] = new_api_key
        if env_vars.get("QUORVEX_LLM_PROVIDER") == "openai":
            os.environ["OPENAI_API_KEY"] = new_api_key
        else:
            os.environ["ANTHROPIC_AUTH_TOKEN"] = new_api_key
            os.environ["ANTHROPIC_API_KEY"] = new_api_key
            os.environ.pop("ANTHROPIC_AUTH_TOKENS", None)
    elif env_vars.get("ANTHROPIC_AUTH_TOKEN"):
        os.environ["ANTHROPIC_AUTH_TOKEN"] = env_vars["ANTHROPIC_AUTH_TOKEN"]
        os.environ["ANTHROPIC_API_KEY"] = env_vars.get("ANTHROPIC_API_KEY", env_vars["ANTHROPIC_AUTH_TOKEN"])

    try:
        apply_runtime_env_aliases(env_vars, tier="chat")
    except Exception:
        # Keep settings save resilient even if optional model routing code fails.
        pass

    for key in (
        "QUORVEX_AGENT_RUNTIME",
        "QUORVEX_ASSISTANT_RUNTIME",
        "HERMES_ENABLED",
        "HERMES_API_URL",
        "HERMES_API_KEY",
        "HERMES_MODEL",
        "HERMES_HOME",
        "HERMES_SYNC_PROVIDER",
        "HERMES_UPSTREAM_PROVIDER",
        "HERMES_UPSTREAM_MODEL",
    ):
        if key in env_vars:
            os.environ[key] = env_vars[key]

    try:
        from orchestrator.services.api_key_rotator import get_api_key_rotator

        get_api_key_rotator().initialize()
    except Exception:
        # Settings should still save even if the optional rotator is unavailable.
        pass


def _settings_response(env_vars: dict[str, str] | None = None) -> dict[str, Any]:
    active = _active_settings(env_vars)
    hermes_home = active["hermes_home"] or str(_hermes_config_dir())
    hermes_status = _check_hermes_gateway(active)
    return {
        "llm_provider": active["llm_provider"],
        "base_url": active["base_url"],
        "model_name": active["model_name"],
        "light_model": active["light_model"],
        "standard_model": active["standard_model"],
        "deep_model": active["deep_model"],
        "tool_deep_model": active["tool_deep_model"],
        "chat_model": active["chat_model"],
        "embedding_model": active["embedding_model"],
        "model_tiers": {
            "light": active["light_model"],
            "standard": active["standard_model"],
            "deep": active["deep_model"],
            "tool_deep": active["tool_deep_model"],
            "chat": active["chat_model"],
            "embedding": active["embedding_model"],
        },
        "api_key": _mask_api_key(active["api_key"]),
        "agent_runtime": active["agent_runtime"],
        "assistant_runtime": active["assistant_runtime"],
        "hermes_enabled": _is_truthy(active["hermes_enabled"]),
        "hermes_api_url": active["hermes_api_url"],
        "hermes_api_key": _mask_api_key(active["hermes_api_key"]),
        "hermes_model": active["hermes_model"],
        "hermes_sync_provider": _is_truthy(active["hermes_sync_provider"], default=True),
        "hermes_upstream_provider": active["hermes_upstream_provider"],
        "hermes_upstream_model": active["hermes_upstream_model"],
        "hermes_home": hermes_home,
        "hermes_config_path": str(Path(hermes_home) / "config.yaml"),
        "hermes_env_path": str(Path(hermes_home) / ".env"),
        "hermes_reachable": hermes_status["reachable"],
        "hermes_status": hermes_status["status"],
        "hermes_status_message": hermes_status["message"],
    }


@router.get("/settings")
def get_settings(session: Session = Depends(get_session)):
    """Get current Settings-backed runtime settings (masked sensitive data)."""
    db_session, should_close = _coerce_session(session)
    try:
        return _settings_response(runtime_env_vars(db_session))
    finally:
        if should_close:
            db_session.close()


@router.post("/settings")
def update_settings(new_settings: Settings, session: Session = Depends(get_session)):
    """Update Settings-backed runtime configuration and apply it to this process."""
    db_session, should_close = _coerce_session(session)
    try:
        return _update_settings(new_settings, db_session)
    finally:
        if should_close:
            db_session.close()


def _update_settings(new_settings: Settings, session: Session):
    existing = dict(_db_runtime_settings(session) or {})
    env_vars = _settings_to_env_vars(existing) if existing else runtime_env_vars(session)
    active = _active_settings_from_env(env_vars)

    runtime_settings = _settings_from_active(active)
    provider_value = new_settings.llm_provider or runtime_settings.get("llm_provider") or "zai"
    runtime_settings["llm_provider"] = provider_value

    if new_settings.base_url:
        runtime_settings["base_url"] = new_settings.base_url.rstrip("/")
    if new_settings.model_name:
        runtime_settings["model_name"] = new_settings.model_name

    tier_updates: dict[RuntimeModelTier, str] = {}
    if new_settings.model_tiers:
        for tier, model in new_settings.model_tiers.items():
            if tier in CANONICAL_MODEL_ENV and model:
                tier_updates[tier] = model  # type: ignore[assignment]
    for tier, model in {
        "light": new_settings.light_model,
        "standard": new_settings.standard_model,
        "deep": new_settings.deep_model,
        "tool_deep": new_settings.tool_deep_model,
        "chat": new_settings.chat_model,
        "embedding": new_settings.embedding_model,
    }.items():
        if model:
            tier_updates[tier] = model  # type: ignore[assignment]

    previous_tiers = {
        "light": runtime_settings.get("light_model") or active["light_model"],
        "standard": runtime_settings.get("standard_model") or active["standard_model"],
        "deep": runtime_settings.get("deep_model") or active["deep_model"],
        "tool_deep": runtime_settings.get("tool_deep_model") or active["tool_deep_model"],
        "chat": runtime_settings.get("chat_model") or active["chat_model"],
        "embedding": runtime_settings.get("embedding_model") or active["embedding_model"],
    }
    if new_settings.model_name and tier_updates:
        standard_unchanged = (new_settings.standard_model or previous_tiers["standard"]) == previous_tiers["standard"]
        chat_unchanged = (new_settings.chat_model or previous_tiers["chat"]) == previous_tiers["chat"]
        if standard_unchanged and chat_unchanged and new_settings.model_name != previous_tiers["chat"]:
            tier_updates["standard"] = new_settings.model_name
            tier_updates["chat"] = new_settings.model_name
    elif new_settings.model_name:
        tier_updates["standard"] = new_settings.model_name
        tier_updates["chat"] = new_settings.model_name

    for tier, model in tier_updates.items():
        runtime_settings[f"{tier}_model"] = model
    if runtime_settings.get("standard_model"):
        runtime_settings["model_name"] = runtime_settings["standard_model"]

    runtime_settings["agent_runtime"] = _normalize_runtime(
        new_settings.agent_runtime or str(runtime_settings.get("agent_runtime") or "claude_sdk")
    )
    runtime_settings["assistant_runtime"] = _normalize_assistant_runtime(
        new_settings.assistant_runtime
        or str(runtime_settings.get("assistant_runtime") or runtime_settings["agent_runtime"])
    )

    if new_settings.hermes_enabled is not None:
        runtime_settings["hermes_enabled"] = new_settings.hermes_enabled
    if new_settings.hermes_api_url:
        runtime_settings["hermes_api_url"] = new_settings.hermes_api_url.rstrip("/")
    if new_settings.hermes_model:
        runtime_settings["hermes_model"] = new_settings.hermes_model
    if new_settings.hermes_sync_provider is not None:
        runtime_settings["hermes_sync_provider"] = new_settings.hermes_sync_provider

    new_api_key = None
    if new_settings.api_key and not _is_masked_api_key(new_settings.api_key):
        new_api_key = new_settings.api_key
        runtime_settings["api_key_encrypted"] = _encrypt_runtime_secret(new_settings.api_key)
    elif "api_key_encrypted" not in runtime_settings:
        runtime_settings["api_key_encrypted"] = ""

    if new_settings.hermes_api_key and not _is_masked_api_key(new_settings.hermes_api_key):
        runtime_settings["hermes_api_key_encrypted"] = _encrypt_runtime_secret(new_settings.hermes_api_key)
    elif "hermes_api_key_encrypted" not in runtime_settings:
        runtime_settings["hermes_api_key_encrypted"] = ""

    env_vars = _settings_to_env_vars(runtime_settings)
    hermes_bundle = None
    if _is_truthy(env_vars.get("HERMES_SYNC_PROVIDER"), default=True):
        hermes_bundle = _write_hermes_provider_bundle(_active_settings_from_env(env_vars), env_vars)
        runtime_settings["hermes_home"] = hermes_bundle["home"]
        runtime_settings["hermes_upstream_provider"] = hermes_bundle["provider"]
        runtime_settings["hermes_upstream_model"] = hermes_bundle["model"]
        env_vars = _settings_to_env_vars(runtime_settings)

    _save_db_runtime_settings(session, runtime_settings)
    _apply_runtime_settings(env_vars, new_api_key=new_api_key)

    settings_response = _settings_response(env_vars)
    if hermes_bundle:
        settings_response.update(
            {
                "hermes_upstream_provider": hermes_bundle["provider"],
                "hermes_upstream_model": hermes_bundle["model"],
                "hermes_home": hermes_bundle["home"],
                "hermes_config_path": hermes_bundle["config_path"],
                "hermes_env_path": hermes_bundle["env_path"],
            }
        )

    return {
        "status": "success",
        "message": "Settings saved and applied.",
        "settings": settings_response,
    }


@router.post("/settings/test-hermes", response_model=HermesConnectionResult)
async def test_hermes_connection(session: Session = Depends(get_session)):
    """Test the Hermes API server and generated Hermes home bundle."""
    db_session, should_close = _coerce_session(session)
    try:
        active = _active_settings(session=db_session)
    finally:
        if should_close:
            db_session.close()
    hermes_home = active["hermes_home"] or str(_hermes_config_dir())
    config_path = str(Path(hermes_home) / "config.yaml")
    env_path = str(Path(hermes_home) / ".env")
    started = time.monotonic()
    gateway = _check_hermes_gateway(active)
    latency_ms = int((time.monotonic() - started) * 1000)
    config_exists = Path(config_path).exists()
    env_exists = Path(env_path).exists()

    if not _is_truthy(active["hermes_enabled"]):
        message = "Hermes is disabled. Enable the Hermes backend before testing."
    elif not gateway["reachable"]:
        message = gateway["message"]
    elif not config_exists or not env_exists:
        missing = []
        if not config_exists:
            missing.append("config.yaml")
        if not env_exists:
            missing.append(".env")
        message = f"Hermes API is reachable, but generated Hermes home is missing {', '.join(missing)}."
    else:
        upstream_model = active["hermes_upstream_model"]
        upstream_suffix = f" ({upstream_model})" if upstream_model else ""
        message = (
            f"Hermes API is reachable and generated config is present for "
            f"{active['hermes_upstream_provider'] or 'pending'}{upstream_suffix}."
        )

    ok = bool(_is_truthy(active["hermes_enabled"]) and gateway["reachable"] and config_exists and env_exists)
    return HermesConnectionResult(
        ok=ok,
        reachable=bool(gateway["reachable"]),
        status=str(gateway["status"]),
        message=message,
        api_url=(active["hermes_api_url"] or DEFAULT_HERMES_API_URL).rstrip("/"),
        model=active["hermes_model"],
        upstream_provider=active["hermes_upstream_provider"],
        upstream_model=active["hermes_upstream_model"],
        hermes_home=hermes_home,
        config_path=config_path,
        env_path=env_path,
        config_exists=config_exists,
        env_exists=env_exists,
        latency_ms=latency_ms,
    )


@router.post("/settings/test-connection", response_model=SettingsConnectionResult)
async def test_settings_connection(session: Session = Depends(get_session)):
    """Test the currently active runtime AI settings without exposing secrets."""
    db_session, should_close = _coerce_session(session)
    try:
        env_vars = runtime_env_vars(db_session)
    finally:
        if should_close:
            db_session.close()
    active = _active_settings(env_vars)
    selection = resolve_runtime_ai_selection("chat", env_vars=env_vars)
    api_key = active["api_key"]
    base_url = (selection.base_url or DEFAULT_ANTHROPIC_BASE_URL).rstrip("/")
    model_name = selection.model
    provider = active["llm_provider"]

    if not model_name:
        return SettingsConnectionResult(
            ok=False,
            model_name=model_name,
            base_url=base_url,
            message="No model configured.",
        )

    started = time.monotonic()
    if not api_key and provider == "anthropic":
        try:
            from orchestrator.utils.agent_runner import AgentRunner

            runner = AgentRunner(
                timeout_seconds=30,
                allowed_tools=[],
                log_tools=False,
                model_tier="chat",
            )
            result = await runner.run(
                "Reply with exactly: ok",
                timeout_override=30,
            )
            latency_ms = int((time.monotonic() - started) * 1000)
            if result.success:
                return SettingsConnectionResult(
                    ok=True,
                    model_name=model_name,
                    base_url=base_url,
                    message="Claude Code connection successful.",
                    latency_ms=latency_ms,
                )
            return SettingsConnectionResult(
                ok=False,
                model_name=model_name,
                base_url=base_url,
                message=f"Claude Code connection failed: {result.error or 'No response'}",
                latency_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = int((time.monotonic() - started) * 1000)
            return SettingsConnectionResult(
                ok=False,
                model_name=model_name,
                base_url=base_url,
                message=f"Claude Code connection failed: {e}",
                latency_ms=latency_ms,
            )

    if not api_key:
        return SettingsConnectionResult(
            ok=False,
            model_name=model_name,
            base_url=base_url,
            message="No API key configured.",
        )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if provider in {"openrouter", "openai"}:
                response = await client.post(
                    _chat_completions_url(base_url),
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": "Say ok."}],
                        "max_tokens": 5,
                        "temperature": 0,
                    },
                )
            else:
                response = await client.post(
                    f"{base_url}/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model_name,
                        "max_tokens": 5,
                        "messages": [{"role": "user", "content": "Say ok."}],
                    },
                )

        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            detail = response.text[:500]
            return SettingsConnectionResult(
                ok=False,
                model_name=model_name,
                base_url=base_url,
                message=f"Provider returned HTTP {response.status_code}: {detail}",
                latency_ms=latency_ms,
            )

        return SettingsConnectionResult(
            ok=True,
            model_name=model_name,
            base_url=base_url,
            message="Connection successful.",
            latency_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = int((time.monotonic() - started) * 1000)
        return SettingsConnectionResult(
            ok=False,
            model_name=model_name,
            base_url=base_url,
            message=str(e),
            latency_ms=latency_ms,
        )


@router.get("/settings/runtime-chat")
def get_runtime_chat_settings(
    session: Session = Depends(get_session),
    internal_caller: str | None = Header(default=None, alias="X-Quorvex-Internal-Caller"),
):
    """Return resolved secret-bearing runtime settings for server-side chat routing."""
    if internal_caller != "web-chat":
        raise HTTPException(status_code=403, detail="Runtime chat settings are only available to server-side chat.")
    db_session, should_close = _coerce_session(session)
    try:
        env_vars = runtime_env_vars(db_session)
    finally:
        if should_close:
            db_session.close()
    active = _active_settings(env_vars)
    assistant_runtime = active["assistant_runtime"]
    hermes_enabled = _is_truthy(active["hermes_enabled"])
    if assistant_runtime == "hermes" and hermes_enabled:
        route_provider = "hermes"
    elif assistant_runtime == "openai" or active["llm_provider"] == "openai":
        route_provider = "openai"
    else:
        route_provider = "anthropic"
    return {
        "route_provider": route_provider,
        "llm_provider": active["llm_provider"],
        "assistant_runtime": assistant_runtime,
        "agent_runtime": active["agent_runtime"],
        "base_url": active["base_url"],
        "api_key": active["api_key"],
        "model_name": active["model_name"],
        "chat_model": active["chat_model"],
        "standard_model": active["standard_model"],
        "model_tiers": {
            "light": active["light_model"],
            "standard": active["standard_model"],
            "deep": active["deep_model"],
            "tool_deep": active["tool_deep_model"],
            "chat": active["chat_model"],
            "embedding": active["embedding_model"],
        },
        "hermes_enabled": hermes_enabled,
        "hermes_api_url": active["hermes_api_url"],
        "hermes_api_key": active["hermes_api_key"],
        "hermes_model": active["hermes_model"],
        "source": "settings",
    }
