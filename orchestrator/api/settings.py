import os
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class Settings(BaseModel):
    llm_provider: str
    api_key: str | None = None
    base_url: str | None = None
    model_name: str | None = None


# Project .env file path
ENV_FILE = Path(__file__).parent.parent.parent / ".env"


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


@router.get("/settings")
def get_settings():
    """Get current settings from .env file (masked sensitive data)"""
    settings = {}

    # Read from .env file
    env_vars = _read_env_file()

    # Get values from .env file first, fallback to current environment
    settings["base_url"] = env_vars.get("ANTHROPIC_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL", "")
    settings["model_name"] = env_vars.get("ANTHROPIC_DEFAULT_SONNET_MODEL") or os.environ.get(
        "ANTHROPIC_DEFAULT_SONNET_MODEL", ""
    )

    # Mask API Key
    api_key = env_vars.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    if api_key:
        if len(api_key) > 8:
            settings["api_key"] = api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]
        else:
            settings["api_key"] = "********"
    else:
        settings["api_key"] = ""

    # Infer provider based on base_url
    base_url_lower = settings.get("base_url", "").lower()
    if "openrouter.ai" in base_url_lower:
        settings["llm_provider"] = "openrouter"
    elif "anthropic.com" in base_url_lower or not base_url_lower:
        settings["llm_provider"] = "anthropic"
    else:
        settings["llm_provider"] = "custom"

    return settings


@router.post("/settings")
def update_settings(new_settings: Settings):
    """Update settings in .env file"""

    # Read existing env vars
    env_vars = _read_env_file()

    # Update fields
    if new_settings.base_url:
        env_vars["ANTHROPIC_BASE_URL"] = new_settings.base_url

    if new_settings.model_name:
        env_vars["ANTHROPIC_DEFAULT_SONNET_MODEL"] = new_settings.model_name

    if new_settings.api_key and "********" not in new_settings.api_key and "*" * 4 not in new_settings.api_key:
        env_vars["ANTHROPIC_AUTH_TOKEN"] = new_settings.api_key

    # Write back to .env file
    _write_env_file(env_vars)

    return {
        "status": "success",
        "message": "Settings saved to .env file. Please restart the agent for changes to take full effect.",
    }
