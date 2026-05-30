"""Load environment variables from .env file"""

import os


def setup_claude_env():
    """Setup environment variables from .env file only.

    Runtime AI credentials should be defined with the canonical QUORVEX_LLM_*
    variables. Legacy ANTHROPIC_* aliases are still populated for SDK clients.
    """
    from dotenv import find_dotenv, load_dotenv

    # Load from .env file - this is the ONLY source for credentials
    env_path = find_dotenv()
    if env_path:
        load_dotenv(env_path, override=False)  # Don't override existing env vars

    # Determine headless mode based on VNC_ENABLED and existing settings
    # Priority: existing env var > VNC_ENABLED > default (headless in Docker, headed locally)
    vnc_enabled = os.environ.get("VNC_ENABLED", "").lower() == "true"
    in_docker = os.path.exists("/.dockerenv") or os.environ.get("DOCKER_CONTAINER") == "true"

    # VNC mode = headed (false), Docker without VNC = headless (true), local = headed (false)
    if vnc_enabled:
        default_headless = "false"  # VNC needs headed browser
    elif in_docker:
        default_headless = "true"  # Docker default is headless
    else:
        default_headless = "false"  # Local development default is headed

    # Only set if not already configured (allows queue manager to override)
    if "HEADLESS" not in os.environ:
        os.environ["HEADLESS"] = default_headless
    if "PLAYWRIGHT_HEADLESS" not in os.environ:
        os.environ["PLAYWRIGHT_HEADLESS"] = os.environ.get("HEADLESS", default_headless)

    # Configure SDK buffer size for large browser snapshots
    try:
        from orchestrator.sdk_config import configure_sdk_buffer

        configure_sdk_buffer()
    except ImportError:
        try:
            from sdk_config import configure_sdk_buffer

            configure_sdk_buffer()
        except ImportError:
            pass

    # Initialize multi-key rotator and set the first active key
    try:
        from orchestrator.services.api_key_rotator import get_api_key_rotator
    except ImportError:
        try:
            from services.api_key_rotator import get_api_key_rotator
        except ImportError:
            get_api_key_rotator = None

    if get_api_key_rotator is not None:
        rotator = get_api_key_rotator()
        if not rotator._initialized:
            rotator.initialize()
            slot = rotator.get_active_key()
            if slot:
                rotator.activate_key(slot)

    try:
        from orchestrator.services.ai_runtime_config import apply_runtime_env_aliases
    except ImportError:
        try:
            from services.ai_runtime_config import apply_runtime_env_aliases
        except ImportError:
            apply_runtime_env_aliases = None

    selection = None
    if apply_runtime_env_aliases is not None:
        tier = os.environ.get("QUORVEX_RUN_MODEL_TIER", "standard")
        if tier not in {"light", "standard", "deep", "tool_deep", "chat", "embedding"}:
            tier = "standard"
        selection = apply_runtime_env_aliases(tier=tier)

    active_model = selection.model if selection else (
        os.environ.get("QUORVEX_LLM_STANDARD_MODEL")
        or os.environ.get("ANTHROPIC_MODEL")
        or os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL")
        or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
        or os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", "")
    )

    # Return the key AI-related env vars for logging purposes
    return {
        "QUORVEX_LLM_PROVIDER": os.environ.get("QUORVEX_LLM_PROVIDER", ""),
        "QUORVEX_LLM_BASE_URL": os.environ.get("QUORVEX_LLM_BASE_URL", os.environ.get("ANTHROPIC_BASE_URL", "")),
        "QUORVEX_LLM_MODEL": active_model,
        "QUORVEX_RUN_MODEL_TIER": os.environ.get("QUORVEX_RUN_MODEL_TIER", ""),
        "ANTHROPIC_BASE_URL": os.environ.get("ANTHROPIC_BASE_URL", ""),
        "ANTHROPIC_MODEL": active_model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL", ""),
        "ANTHROPIC_DEFAULT_SONNET_MODEL": os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", ""),
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", ""),
        "API_TIMEOUT_MS": os.environ.get("API_TIMEOUT_MS", ""),
        "QUORVEX_LLM_API_KEY": "***" if os.environ.get("QUORVEX_LLM_API_KEY") else "",
        "ANTHROPIC_AUTH_TOKEN": "***" if os.environ.get("ANTHROPIC_AUTH_TOKEN") else "",
    }


if __name__ == "__main__":
    env = setup_claude_env()
    print("Loaded environment variables:")
    for key in env.keys():
        if "TOKEN" not in key:  # Don't print tokens
            print(f"  {key}={env[key]}")
        else:
            print(f"  {key}=***")
