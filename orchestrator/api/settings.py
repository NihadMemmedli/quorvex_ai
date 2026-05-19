import os
import time
from typing import Any
from pathlib import Path

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class Settings(BaseModel):
    llm_provider: str
    api_key: str | None = None
    base_url: str | None = None
    model_name: str | None = None


class SettingsConnectionResult(BaseModel):
    ok: bool
    model_name: str
    base_url: str
    message: str
    latency_ms: int | None = None


# Project .env file path
ENV_FILE = Path(__file__).parent.parent.parent / ".env"
MODEL_ENV_KEYS = (
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
)
DEFAULT_ANTHROPIC_BASE_URL = "https://api.z.ai/api/anthropic"


def _read_env_file() -> dict:
    """Read key-value pairs from .env file"""
    env_vars = {}
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars


def _write_env_file(env_vars: dict):
    """Write key-value pairs to .env file, preserving comments and structure"""
    lines = []
    existing_keys = set()

    # Read existing file to preserve structure and comments
    if ENV_FILE.exists():
        with open(ENV_FILE) as f:
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

    with open(ENV_FILE, "w") as f:
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


def _infer_provider(base_url: str | None) -> str:
    """Infer the configured provider from the base URL."""
    base_url_lower = (base_url or "").lower()
    if "api.z.ai" in base_url_lower or "bigmodel.cn" in base_url_lower:
        return "zai"
    if "openrouter.ai" in base_url_lower:
        return "openrouter"
    if "anthropic.com" in base_url_lower or not base_url_lower:
        return "anthropic"
    return "custom"


def _active_settings(env_vars: dict[str, str] | None = None) -> dict[str, str]:
    """Return the currently active AI settings, preferring .env then process env."""
    env_vars = env_vars if env_vars is not None else _read_env_file()
    base_url = env_vars.get("ANTHROPIC_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL", DEFAULT_ANTHROPIC_BASE_URL)
    model_name = next(
        (model for key in MODEL_ENV_KEYS if (model := env_vars.get(key))),
        "",
    ) or next((model for key in MODEL_ENV_KEYS if (model := os.environ.get(key))), "")
    api_key = (
        env_vars.get("ANTHROPIC_AUTH_TOKEN")
        or env_vars.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        or os.environ.get("ANTHROPIC_API_KEY", "")
    )
    return {
        "base_url": base_url,
        "model_name": model_name,
        "api_key": api_key,
        "llm_provider": _infer_provider(base_url),
    }


def _apply_runtime_settings(env_vars: dict[str, str], new_api_key: str | None = None):
    """Apply persisted settings to this running backend process."""
    for key in ("ANTHROPIC_BASE_URL", *MODEL_ENV_KEYS):
        value = env_vars.get(key)
        if value is not None:
            os.environ[key] = value

    if new_api_key:
        os.environ["ANTHROPIC_AUTH_TOKEN"] = new_api_key
        os.environ["ANTHROPIC_API_KEY"] = new_api_key
        os.environ.pop("ANTHROPIC_AUTH_TOKENS", None)
    elif env_vars.get("ANTHROPIC_AUTH_TOKEN"):
        os.environ["ANTHROPIC_AUTH_TOKEN"] = env_vars["ANTHROPIC_AUTH_TOKEN"]
        os.environ["ANTHROPIC_API_KEY"] = env_vars.get("ANTHROPIC_API_KEY", env_vars["ANTHROPIC_AUTH_TOKEN"])

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
        "base_url": active["base_url"],
        "model_name": active["model_name"],
        "api_key": _mask_api_key(active["api_key"]),
    }


@router.get("/settings")
def get_settings():
    """Get current settings from .env file (masked sensitive data)"""
    return _settings_response()


@router.post("/settings")
def update_settings(new_settings: Settings):
    """Update settings in .env file and apply them to the running process."""

    # Read existing env vars
    env_vars = _read_env_file()

    # Update fields
    if new_settings.base_url:
        env_vars["ANTHROPIC_BASE_URL"] = new_settings.base_url.rstrip("/")

    if new_settings.model_name:
        for key in MODEL_ENV_KEYS:
            env_vars[key] = new_settings.model_name

    new_api_key = None
    if new_settings.api_key and not _is_masked_api_key(new_settings.api_key):
        new_api_key = new_settings.api_key
        env_vars["ANTHROPIC_AUTH_TOKEN"] = new_settings.api_key
        env_vars["ANTHROPIC_API_KEY"] = new_settings.api_key
        env_vars["ANTHROPIC_AUTH_TOKENS"] = ""

    # Write back to .env file
    _write_env_file(env_vars)
    _apply_runtime_settings(env_vars, new_api_key=new_api_key)

    return {
        "status": "success",
        "message": "Settings saved and applied.",
        "settings": _settings_response(env_vars),
    }


@router.post("/settings/test-connection", response_model=SettingsConnectionResult)
async def test_settings_connection():
    """Test the currently active runtime AI settings without exposing secrets."""
    active = _active_settings()
    api_key = active["api_key"]
    base_url = (active["base_url"] or DEFAULT_ANTHROPIC_BASE_URL).rstrip("/")
    model_name = active["model_name"]
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
            if provider == "openrouter":
                response = await client.post(
                    f"{base_url}/v1/chat/completions",
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
