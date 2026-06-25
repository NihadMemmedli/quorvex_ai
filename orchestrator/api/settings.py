import asyncio
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

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
    auth_mode: str | None = None
    api_key: str | None = None
    claude_code_oauth_token: str | None = None
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


class SettingsConnectionResult(BaseModel):
    ok: bool
    model_name: str
    base_url: str
    message: str
    latency_ms: int | None = None


class ClaudeCodeSetupTokenResult(BaseModel):
    ok: bool
    status: str
    message: str
    fallback_command: str = "claude setup-token"
    cli_path: str | None = None
    masked_token: str | None = None
    token_configured: bool = False
    settings: dict[str, Any] | None = None


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
CLAUDE_CODE_PROVIDER = "claude_code_subscription"
AUTH_MODE_API_KEY = "api_key"
AUTH_MODE_CLAUDE_CODE = "claude_code_subscription"
CLAUDE_CODE_BASE_URL = "https://api.anthropic.com"
CLAUDE_CODE_SETUP_TOKEN_COMMAND = "claude setup-token"
CLAUDE_CODE_SETUP_TIMEOUT_SECONDS = 45
RUNTIME_ALIASES = {
    "claude": "claude_sdk",
    "claude_sdk": "claude_sdk",
    "claude-agent-sdk": "claude_sdk",
    "hermes": "claude_sdk",
    "hermes_agent": "claude_sdk",
    "hermes-agent": "claude_sdk",
}
ASSISTANT_RUNTIME_ALIASES = {
    **RUNTIME_ALIASES,
    "openai": "openai",
    "openai_sdk": "openai",
    "openai-sdk": "openai",
}
PERSISTED_ENV_FILE_KEYS = (
    "QUORVEX_LLM_PROVIDER",
    "QUORVEX_LLM_AUTH_MODE",
    "QUORVEX_LLM_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "OPENAI_BASE_URL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_MODEL",
    "OPENAI_MODEL_ID",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_CHAT_MODEL",
    "OPENAI_CHAT_MODEL",
    "EMBEDDING_MODEL",
    "QUORVEX_AGENT_RUNTIME",
    "QUORVEX_ASSISTANT_RUNTIME",
    *CANONICAL_MODEL_ENV.values(),
)


def _env_file_path() -> Path:
    override = os.environ.get("QUORVEX_SETTINGS_ENV_FILE")
    if override:
        return Path(override)
    return ENV_FILE


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
    """Write non-secret runtime settings to the env file.

    Credential values are persisted through encrypted Settings rows and applied to
    the current process environment, but they are not written back to clear-text
    env files.
    """
    env_file = _env_file_path()
    env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for key in PERSISTED_ENV_FILE_KEYS:
        value = env_vars.get(key)
        if value is not None:
            lines.append(f"{key}={value}")
    env_file.write_text("\n".join(lines) + "\n")


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


def _normalize_auth_mode(value: str | None, provider: str | None = None) -> str:
    raw = (value or "").strip().lower()
    provider_value = (provider or "").strip().lower()
    if raw in {"claude_code", "claude-code", AUTH_MODE_CLAUDE_CODE} or provider_value == CLAUDE_CODE_PROVIDER:
        return AUTH_MODE_CLAUDE_CODE
    return AUTH_MODE_API_KEY


def _oauth_token_from_env(env_vars: dict[str, str] | None = None) -> str:
    if env_vars is not None and "CLAUDE_CODE_OAUTH_TOKEN" in env_vars:
        return env_vars.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    return os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")


def _encrypt_runtime_secret(value: str) -> str:
    from orchestrator.api.credentials import encrypt_credential

    return encrypt_credential(value)


def _decrypt_runtime_secret(value: str) -> str:
    from orchestrator.api.credentials import decrypt_credential

    return decrypt_credential(value)


def _infer_provider(base_url: str | None) -> str:
    """Infer the configured provider from the base URL."""
    return infer_display_provider(base_url)


def _normalize_runtime(value: str | None) -> str:
    if not value:
        return "claude_sdk"
    return RUNTIME_ALIASES.get(value.strip().lower(), "claude_sdk")


def _normalize_assistant_runtime(value: str | None) -> str:
    if not value:
        return "claude_sdk"
    return ASSISTANT_RUNTIME_ALIASES.get(value.strip().lower(), "claude_sdk")


def _is_truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _strip_ansi(value: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", value)


def _parse_claude_setup_token(output: str) -> str | None:
    """Extract a Claude Code OAuth token from CLI output without logging it."""
    text = _strip_ansi(output)
    patterns = (
        r"(?:export\s+)?CLAUDE_CODE_OAUTH_TOKEN\s*=\s*['\"]?([A-Za-z0-9._:/+=-]{20,})",
        r"(?:oauth\s+token|access\s+token|token)\s*[:=]\s*['\"]?([A-Za-z0-9._:/+=-]{20,})",
        r"\b(sk-ant-[A-Za-z0-9._:/+=-]{20,})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip().strip("'\"")

    for line in text.splitlines():
        value = line.strip().strip("'\"")
        if len(value) >= 40 and not re.search(r"\s", value) and re.search(r"[A-Za-z]", value) and re.search(r"\d", value):
            return value
    return None


def _resolve_claude_cli() -> str | None:
    configured = os.environ.get("CLAUDE_CODE_CLI_PATH", "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser())

    path_cli = shutil.which("claude")
    if path_cli:
        candidates.append(Path(path_cli))

    repo_root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            repo_root / "node_modules" / ".bin" / "claude",
            repo_root / "web" / "node_modules" / ".bin" / "claude",
        ]
    )

    seen: set[str] = set()
    for candidate in candidates:
        candidate_str = str(candidate)
        if candidate_str in seen:
            continue
        seen.add(candidate_str)
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate_str
    return None


async def _run_claude_setup_token(cli_path: str, timeout_seconds: int = CLAUDE_CODE_SETUP_TIMEOUT_SECONDS) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        cli_path,
        "setup-token",
        stdin=subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "NO_COLOR": "1"},
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise
    output = "\n".join(
        part.decode("utf-8", errors="replace")
        for part in (stdout, stderr)
        if part
    )
    return proc.returncode or 0, output


def _save_claude_code_oauth_token(session: Session, token: str) -> dict[str, Any]:
    existing = dict(_db_runtime_settings(session) or {})
    runtime_settings = existing or _settings_from_active(_active_settings_from_env(runtime_env_vars(session)))
    runtime_settings["llm_provider"] = CLAUDE_CODE_PROVIDER
    runtime_settings["auth_mode"] = AUTH_MODE_CLAUDE_CODE
    runtime_settings["base_url"] = CLAUDE_CODE_BASE_URL
    runtime_settings["claude_code_oauth_token_encrypted"] = _encrypt_runtime_secret(token)
    if "api_key_encrypted" not in runtime_settings:
        runtime_settings["api_key_encrypted"] = existing.get("api_key_encrypted", "")

    env_vars = _settings_to_env_vars(runtime_settings)
    _save_db_runtime_settings(session, runtime_settings)
    _write_env_file(env_vars)
    _apply_runtime_settings(env_vars)
    return _settings_response(env_vars)




def _active_settings_from_env(env_vars: dict[str, str] | None = None) -> dict[str, str]:
    """Return active AI settings from a resolved env-style mapping."""
    env_vars = env_vars if env_vars is not None else _read_env_file()
    selection = resolve_runtime_ai_selection("chat", env_vars=env_vars)
    tiers = model_tiers(env_vars)
    base_url = selection.base_url or DEFAULT_ANTHROPIC_BASE_URL
    model_name = selection.model
    provider_label = env_vars.get("QUORVEX_LLM_PROVIDER") or ""
    if provider_label in {"anthropic_compatible", "openai_compatible", "hermes", "hermes_agent", "hermes-agent"}:
        provider_label = _infer_provider(base_url)
    auth_mode = _normalize_auth_mode(env_vars.get("QUORVEX_LLM_AUTH_MODE"), provider_label)
    claude_code_oauth_token = _oauth_token_from_env(env_vars)
    if auth_mode == AUTH_MODE_API_KEY and claude_code_oauth_token and not selection.api_key and _infer_provider(base_url) == "anthropic":
        auth_mode = AUTH_MODE_CLAUDE_CODE
    if selection.provider == "anthropic_compatible":
        model_name = (
            env_vars.get("QUORVEX_LLM_DEEP_MODEL")
            or env_vars.get("ANTHROPIC_MODEL")
            or env_vars.get("ANTHROPIC_DEFAULT_OPUS_MODEL")
            or selection.model
        )
    api_key = "" if auth_mode == AUTH_MODE_CLAUDE_CODE else selection.api_key
    if auth_mode == AUTH_MODE_API_KEY and not api_key:
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
    display_provider = provider_label or _infer_provider(base_url)
    if auth_mode == AUTH_MODE_CLAUDE_CODE:
        display_provider = CLAUDE_CODE_PROVIDER
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
        "claude_code_oauth_token": claude_code_oauth_token,
        "auth_mode": auth_mode,
        "llm_provider": display_provider,
        "agent_runtime": agent_runtime,
        "assistant_runtime": _normalize_assistant_runtime(
            env_vars.get("QUORVEX_ASSISTANT_RUNTIME")
            or os.environ.get("QUORVEX_ASSISTANT_RUNTIME")
            or agent_runtime
        ),
    }


def _settings_to_env_vars(settings: dict[str, Any]) -> dict[str, str]:
    env_vars: dict[str, str] = {}
    provider = str(settings.get("llm_provider") or "zai")
    if provider in {"hermes", "hermes_agent", "hermes-agent"}:
        provider = "zai"
    auth_mode = _normalize_auth_mode(str(settings.get("auth_mode") or ""), provider)
    if auth_mode == AUTH_MODE_CLAUDE_CODE:
        provider = "anthropic"
    base_url = str(settings.get("base_url") or DEFAULT_ANTHROPIC_BASE_URL).rstrip("/")
    if auth_mode == AUTH_MODE_CLAUDE_CODE and (not base_url or "api.z.ai" in base_url):
        base_url = CLAUDE_CODE_BASE_URL
    api_key = _decrypt_runtime_secret(str(settings.get("api_key_encrypted") or ""))
    claude_code_oauth_token = _decrypt_runtime_secret(str(settings.get("claude_code_oauth_token_encrypted") or ""))

    env_vars["QUORVEX_LLM_PROVIDER"] = provider
    env_vars["QUORVEX_LLM_AUTH_MODE"] = auth_mode
    env_vars["QUORVEX_LLM_BASE_URL"] = base_url
    env_vars["ANTHROPIC_BASE_URL"] = base_url
    if provider == "openai":
        env_vars["OPENAI_BASE_URL"] = base_url
    if auth_mode == AUTH_MODE_CLAUDE_CODE:
        env_vars["CLAUDE_CODE_OAUTH_TOKEN"] = claude_code_oauth_token
        env_vars["QUORVEX_LLM_API_KEY"] = ""
        env_vars["QUORVEX_LLM_API_KEYS"] = ""
        env_vars["ANTHROPIC_AUTH_TOKEN"] = ""
        env_vars["ANTHROPIC_API_KEY"] = ""
        env_vars["ANTHROPIC_AUTH_TOKENS"] = ""
        env_vars["OPENAI_API_KEY"] = ""
    else:
        env_vars["CLAUDE_CODE_OAUTH_TOKEN"] = ""
    if auth_mode == AUTH_MODE_API_KEY and api_key:
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
    return env_vars


def _settings_from_active(active: dict[str, str]) -> dict[str, Any]:
    return {
        "llm_provider": active["llm_provider"],
        "auth_mode": active.get("auth_mode") or AUTH_MODE_API_KEY,
        "base_url": active["base_url"],
        "model_name": active["model_name"],
        "light_model": active["light_model"],
        "standard_model": active["standard_model"],
        "deep_model": active["deep_model"],
        "tool_deep_model": active["tool_deep_model"],
        "chat_model": active["chat_model"],
        "embedding_model": active["embedding_model"],
        "api_key_encrypted": _encrypt_runtime_secret(active["api_key"]) if active.get("api_key") else "",
        "claude_code_oauth_token_encrypted": _encrypt_runtime_secret(active["claude_code_oauth_token"])
        if active.get("claude_code_oauth_token")
        else "",
        "agent_runtime": active["agent_runtime"],
        "assistant_runtime": active["assistant_runtime"],
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
        env_vars = _settings_to_env_vars(runtime_settings or {})
        try:
            from orchestrator.services.execution_timeouts import merge_ai_pipeline_timeout_env_vars

            return merge_ai_pipeline_timeout_env_vars(env_vars)
        except Exception:
            return env_vars
    try:
        from orchestrator.api.db import engine

        with Session(engine) as db_session:
            runtime_settings = _db_runtime_settings(db_session)
            env_vars = _settings_to_env_vars(runtime_settings or {})
            try:
                from orchestrator.services.execution_timeouts import merge_ai_pipeline_timeout_env_vars

                return merge_ai_pipeline_timeout_env_vars(env_vars)
            except Exception:
                return env_vars
    except Exception:
        env_vars = _read_env_file()
        try:
            from orchestrator.services.execution_timeouts import merge_ai_pipeline_timeout_env_vars

            return merge_ai_pipeline_timeout_env_vars(env_vars)
        except Exception:
            return env_vars


def _coerce_session(session: Any) -> tuple[Session, bool]:
    if isinstance(session, Session):
        return session, False
    from orchestrator.api.db import engine

    return Session(engine), True


def _active_settings(env_vars: dict[str, str] | None = None, session: Session | None = None) -> dict[str, str]:
    """Return active AI settings, preferring DB-backed Settings over env bootstrap."""
    if env_vars is not None:
        return _active_settings_from_env(env_vars)
    if session is None:
        return _active_settings_from_env(_read_env_file())
    return _active_settings_from_env(runtime_env_vars(session))


def _apply_runtime_settings(env_vars: dict[str, str], new_api_key: str | None = None):
    """Apply persisted settings to this running backend process."""
    for key in (
        "QUORVEX_LLM_PROVIDER",
        "QUORVEX_LLM_AUTH_MODE",
        "QUORVEX_LLM_BASE_URL",
        "QUORVEX_LLM_API_KEY",
        "QUORVEX_LLM_API_KEYS",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKENS",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL_ID",
        "OPENAI_CHAT_MODEL",
        *MODEL_ENV_KEYS,
    ):
        value = env_vars.get(key)
        if value is not None:
            if value == "" and key in {
                "QUORVEX_LLM_API_KEY",
                "QUORVEX_LLM_API_KEYS",
                "ANTHROPIC_AUTH_TOKEN",
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_AUTH_TOKENS",
                "CLAUDE_CODE_OAUTH_TOKEN",
                "OPENAI_API_KEY",
            }:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    if new_api_key and env_vars.get("QUORVEX_LLM_AUTH_MODE") != AUTH_MODE_CLAUDE_CODE:
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
    return {
        "llm_provider": active["llm_provider"],
        "auth_mode": active.get("auth_mode") or AUTH_MODE_API_KEY,
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
        "claude_code_oauth_token": _mask_api_key(active.get("claude_code_oauth_token")),
        "claude_code_oauth_token_configured": bool(active.get("claude_code_oauth_token")),
        "agent_runtime": active["agent_runtime"],
        "assistant_runtime": active["assistant_runtime"],
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
    for secret_key in ("api_key_encrypted", "claude_code_oauth_token_encrypted"):
        if existing.get(secret_key) and not runtime_settings.get(secret_key):
            runtime_settings[secret_key] = existing[secret_key]
    provider_value = new_settings.llm_provider or runtime_settings.get("llm_provider") or "zai"
    if provider_value in {"hermes", "hermes_agent", "hermes-agent"}:
        provider_value = "zai"
    auth_mode = _normalize_auth_mode(new_settings.auth_mode or str(runtime_settings.get("auth_mode") or ""), provider_value)
    if provider_value == CLAUDE_CODE_PROVIDER:
        auth_mode = AUTH_MODE_CLAUDE_CODE
    runtime_settings["llm_provider"] = provider_value
    runtime_settings["auth_mode"] = auth_mode

    if new_settings.base_url:
        runtime_settings["base_url"] = new_settings.base_url.rstrip("/")
    elif auth_mode == AUTH_MODE_CLAUDE_CODE:
        runtime_settings["base_url"] = CLAUDE_CODE_BASE_URL
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

    new_api_key = None
    if new_settings.api_key and not _is_masked_api_key(new_settings.api_key):
        new_api_key = new_settings.api_key
        runtime_settings["api_key_encrypted"] = _encrypt_runtime_secret(new_settings.api_key)
    elif "api_key_encrypted" not in runtime_settings:
        runtime_settings["api_key_encrypted"] = ""
    if new_settings.claude_code_oauth_token and not _is_masked_api_key(new_settings.claude_code_oauth_token):
        runtime_settings["claude_code_oauth_token_encrypted"] = _encrypt_runtime_secret(
            new_settings.claude_code_oauth_token
        )
    elif "claude_code_oauth_token_encrypted" not in runtime_settings:
        runtime_settings["claude_code_oauth_token_encrypted"] = ""

    env_vars = _settings_to_env_vars(runtime_settings)

    _save_db_runtime_settings(session, runtime_settings)
    _write_env_file(env_vars)
    _apply_runtime_settings(env_vars, new_api_key=new_api_key)

    settings_response = _settings_response(env_vars)

    return {
        "status": "success",
        "message": "Settings saved and applied.",
        "settings": settings_response,
    }


@router.post("/settings/claude-code/setup-token", response_model=ClaudeCodeSetupTokenResult)
async def setup_claude_code_token(session: Session = Depends(get_session)):
    """Generate and save a Claude Code OAuth token when the local CLI is available."""
    cli_path = _resolve_claude_cli()
    if not cli_path:
        return ClaudeCodeSetupTokenResult(
            ok=False,
            status="cli_missing",
            message=(
                "Claude Code CLI was not found from CLAUDE_CODE_CLI_PATH, PATH, or the bundled npm install. "
                "Run the fallback command on the host where Claude Code is logged in, then paste the token here."
            ),
        )

    try:
        returncode, output = await _run_claude_setup_token(cli_path)
    except asyncio.TimeoutError:
        return ClaudeCodeSetupTokenResult(
            ok=False,
            status="timeout",
            cli_path=cli_path,
            message=(
                "Claude Code did not return a token before the timeout. It may be waiting for an interactive login "
                "or cannot access the host Claude Code session. Run the fallback command in your terminal, then paste the token."
            ),
        )
    except OSError as exc:
        return ClaudeCodeSetupTokenResult(
            ok=False,
            status="cli_error",
            cli_path=cli_path,
            message=f"Claude Code CLI could not be started: {exc}. Run the fallback command, then paste the token.",
        )

    token = _parse_claude_setup_token(output)
    if not token:
        status = "login_required" if re.search(r"login|auth|sign\s*in|not\s+authenticated", output, re.I) else "token_not_found"
        detail = (
            "Claude Code did not return an OAuth token. The backend may not be logged in or may not be able to access "
            "the host Claude Code state. Run the fallback command in your terminal, then paste the token."
        )
        if returncode != 0:
            detail = f"{detail} Claude Code exited with status {returncode}."
        return ClaudeCodeSetupTokenResult(
            ok=False,
            status=status,
            cli_path=cli_path,
            message=detail,
        )

    db_session, should_close = _coerce_session(session)
    try:
        settings_response = _save_claude_code_oauth_token(db_session, token)
    finally:
        if should_close:
            db_session.close()

    return ClaudeCodeSetupTokenResult(
        ok=True,
        status="success",
        cli_path=cli_path,
        message="Claude Code OAuth token generated, saved, and applied.",
        masked_token=_mask_api_key(token),
        token_configured=True,
        settings=settings_response,
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
    auth_mode = active.get("auth_mode") or AUTH_MODE_API_KEY
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
    if auth_mode == AUTH_MODE_CLAUDE_CODE or (not api_key and provider == "anthropic"):
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
    if assistant_runtime == "openai" or active["llm_provider"] == "openai":
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
        "auth_mode": active.get("auth_mode") or AUTH_MODE_API_KEY,
        "claude_code_oauth_token": active.get("claude_code_oauth_token", ""),
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
        "source": "settings",
    }
