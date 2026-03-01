"""Alembic environment configuration.

Reads DATABASE_URL from environment and runs migrations against PostgreSQL.
SQLite databases use the legacy auto-migration in db.py instead.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add project root to path so we can import models
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Import all models so Alembic can see them for autogenerate
from sqlmodel import SQLModel

from orchestrator.api.models_auth import ProjectMember, RefreshToken, User  # noqa: F401
from orchestrator.api.models_db import (  # noqa: F401
    AgentRun,
    ApplicationMap,
    ArchiveJob,
    CoverageGap,
    CoverageMetric,
    DiscoveredApiEndpoint,
    DiscoveredElement,
    DiscoveredFlow,
    DiscoveredTransition,
    ExecutionSettings,
    ExplorationSession,
    FlowStep,
    PrdGenerationResult,
    Project,
    RegressionBatch,
    Requirement,
    RequirementSource,
    RtmEntry,
    RtmSnapshot,
    RunArtifact,
    SpecMetadata,
    StorageStats,
    TestPattern,
    TestrailCaseMapping,
    TestrailRunMapping,
    TestRun,
)

# Alembic Config object
config = context.config

# Set up logging from alembic.ini
# disable_existing_loggers=False prevents Alembic from silently disabling
# application loggers (e.g. orchestrator.api.main) that were created before
# this migration runs.  Without this, all named loggers are permanently
# disabled after the first Alembic migration.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Target metadata for autogenerate
target_metadata = SQLModel.metadata

# Override sqlalchemy.url from environment
database_url = os.environ.get("DATABASE_URL", "")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without connecting)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connects to database)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
