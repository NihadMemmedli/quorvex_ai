"""
Centralized Configuration for Quorvex AI.

Handles path setup, environment loading, and application settings.
Replaces scattered os.getenv() calls with a single validated Settings class.
Uses pydantic-settings for automatic .env file loading and type validation.

Usage:
    from orchestrator.config import settings

    db_url = settings.database_url
    max_browsers = settings.max_browser_instances
"""

import logging
import sys
from pathlib import Path

# --- Path setup (preserved from original config.py) ---
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
ORCHESTRATOR_DIR = Path(__file__).parent.absolute()

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

# Re-export setup_claude_env for convenience
try:
    from orchestrator.load_env import setup_claude_env
except ImportError:
    try:
        from load_env import setup_claude_env
    except ImportError:

        def setup_claude_env():
            pass


def init():
    """Initialize environment and paths"""
    setup_claude_env()


# --- Centralized Settings ---

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    # Fallback for environments without pydantic-settings
    from pydantic import BaseModel as BaseSettings

    SettingsConfigDict = None

from pydantic import field_validator

logger = logging.getLogger(__name__)


class AppSettings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    # --- AI/LLM ---
    anthropic_auth_token: str = ""
    anthropic_base_url: str = ""
    anthropic_default_sonnet_model: str = ""
    openai_api_key: str | None = None

    # --- Database ---
    database_url: str | None = None

    # --- Authentication ---
    jwt_secret_key: str = "dev-secret-key-change-in-production"
    require_auth: bool = False
    allow_registration: bool = True

    # --- Browser Pool ---
    max_browser_instances: int = 5
    browser_slot_timeout: int = 3600

    # --- Agent Timeouts ---
    agent_timeout_seconds: int = 1800
    exploration_timeout_seconds: int | None = None
    planner_timeout_seconds: int | None = None
    generator_timeout_seconds: int | None = None

    # --- Exploration ---
    max_explorations_per_user: int = 2

    # --- Redis ---
    redis_url: str | None = None

    # --- MinIO Storage ---
    minio_endpoint: str | None = None
    minio_root_user: str | None = None
    minio_root_password: str | None = None
    minio_bucket: str = "playwright-backups"
    minio_bucket_artifacts: str = "playwright-artifacts"

    # --- Backup/Archival ---
    backup_retention: int = 30
    archive_hot_days: int = 30
    archive_total_days: int = 90

    # --- VNC ---
    vnc_enabled: bool = False
    display: str = ":99"

    # --- Logging ---
    log_level: str = "INFO"

    # --- Load Testing ---
    k6_max_vus: int = 1000
    k6_max_duration: str = "5m"
    k6_timeout_seconds: int = 3600

    # --- Security Testing ---
    zap_host: str = "localhost"
    zap_port: int = 8090
    zap_api_key: str | None = None
    zap_proxy_enabled: bool = False
    nuclei_timeout_seconds: int = 600
    security_scan_timeout: int = 1800

    # --- Playwright ---
    headless: bool = True
    base_url: str | None = None
    skill_dir: str | None = None
    skill_timeout: int | None = None
    slow_mo: int | None = None

    # --- Initial Admin ---
    initial_admin_email: str | None = None
    initial_admin_password: str | None = None

    # --- Parallelism ---
    default_parallelism: int = 2
    parallel_mode_enabled: bool = False

    # --- Base directory ---
    base_dir: str | None = None

    if SettingsConfigDict is not None:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore",
        )

    @field_validator("max_browser_instances", mode="before")
    @classmethod
    def validate_max_browsers(cls, v):
        try:
            v = int(v)
        except (TypeError, ValueError):
            logger.warning(f"Invalid MAX_BROWSER_INSTANCES value '{v}', using default 5")
            return 5
        if v < 1:
            return 1
        if v > 50:
            logger.warning(f"MAX_BROWSER_INSTANCES={v} is very high, capping at 50")
            return 50
        return v

    @field_validator("browser_slot_timeout", mode="before")
    @classmethod
    def validate_slot_timeout(cls, v):
        try:
            v = int(v)
        except (TypeError, ValueError):
            return 3600
        return max(60, v)

    def validate_production_config(self):
        """Log warnings for missing recommended config."""
        warnings = []

        if not self.database_url:
            warnings.append("DATABASE_URL not set - using SQLite (not recommended for production)")

        if self.jwt_secret_key == "dev-secret-key-change-in-production":
            warnings.append("JWT_SECRET_KEY is using default value - CHANGE IN PRODUCTION")

        if not self.anthropic_auth_token:
            warnings.append("ANTHROPIC_AUTH_TOKEN not set - AI features will not work")

        for w in warnings:
            logger.warning(f"Config: {w}")

        return warnings


def get_settings() -> AppSettings:
    """Get application settings singleton."""
    global _settings
    if _settings is None:
        _settings = AppSettings()
        _settings.validate_production_config()
    return _settings


_settings: AppSettings | None = None

# Convenience alias - lazy initialization to avoid import-time side effects
settings = get_settings()
