import logging
import os
import time
from collections.abc import Generator
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from orchestrator.config import settings as app_settings

logger = logging.getLogger(__name__)

# Import auth models to ensure they're registered with SQLModel metadata
# This must happen before create_all() is called
from .models_auth import ProjectMember, RefreshToken, User  # noqa: F401

# Import all DB models to ensure they're registered with SQLModel metadata
# This must happen before create_all() is called
from .models_db import (  # noqa: F401
    AgentRun,
    ApplicationMap,
    ArchiveJob,
    AutoPilotPhase,
    AutoPilotQuestion,
    # Auto Pilot pipeline models
    AutoPilotSession,
    AutoPilotSpecTask,
    AutoPilotTestTask,
    # AI Chat models
    ChatConversation,
    ChatMessage,
    CoverageGap,
    CoverageMetric,
    # Scheduling models
    CronSchedule,
    # Database testing models
    DbConnection,
    DbTestCheck,
    DbTestRun,
    DiscoveredApiEndpoint,
    DiscoveredElement,
    DiscoveredFlow,
    DiscoveredTransition,
    ExecutionSettings,
    ExplorationSession,
    FlowStep,
    LlmComparisonRun,
    # LLM dataset models
    LlmDataset,
    LlmDatasetCase,
    LlmDatasetVersion,
    # LLM testing models
    LlmProvider,
    LlmSchedule,
    LlmScheduleExecution,
    LlmTestResult,
    LlmTestRun,
    # Load testing models
    LoadTestRun,
    # OpenAPI import history
    OpenApiImportHistory,
    PrdGenerationResult,
    Project,
    RegressionBatch,
    Requirement,
    RequirementSource,
    RtmEntry,
    RtmSnapshot,
    # Production data management models
    RunArtifact,
    ScheduleExecution,
    SecurityFinding,
    # Security testing models
    SecurityScanRun,
    SpecMetadata,
    StorageStats,
    TestPattern,
    # TestRail integration models
    TestrailCaseMapping,
    TestrailRunMapping,
    TestRun,
)

# Database URL configuration
# Priority: DATABASE_URL env var (via centralized settings) > SQLite default (for development)
DATABASE_URL = app_settings.database_url
if not DATABASE_URL:
    orchestrator_dir = Path(__file__).resolve().parent.parent
    data_dir = orchestrator_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{data_dir}/playwright_agent.db"
    logger.warning(f"DATABASE_URL not set, using SQLite at {data_dir}/playwright_agent.db")
    logger.warning("For production with parallel execution, set DATABASE_URL to a PostgreSQL connection string")


def get_database_type() -> str:
    """Detect the database type from the connection URL."""
    if "postgresql" in DATABASE_URL or "postgres" in DATABASE_URL:
        return "postgresql"
    return "sqlite"


def is_parallel_mode_available() -> bool:
    """Check if parallel mode is available (requires PostgreSQL for parallelism > 1)."""
    return get_database_type() == "postgresql"


def _create_engine():
    """Create the database engine with appropriate settings based on database type."""
    db_type = get_database_type()

    if db_type == "sqlite":
        # SQLite with WAL mode for better concurrent read performance
        # Note: Write locking still applies, so parallelism > 1 not recommended
        return create_engine(
            DATABASE_URL,
            echo=False,
            connect_args={
                "check_same_thread": False,
                "timeout": 30,  # Wait up to 30 seconds for lock
            },
        )
    else:
        # PostgreSQL with connection pooling for concurrent access
        # Pool sized for 5-10 concurrent tests (10 tests × 6 sessions each = 60 connections)
        return create_engine(
            DATABASE_URL,
            echo=False,
            pool_size=30,  # Base connections for concurrent tests
            max_overflow=60,  # Burst capacity for peak load
            pool_pre_ping=True,
            pool_recycle=300,  # Recycle connections every 5 minutes
            pool_timeout=30,  # Explicit timeout to fail fast on exhaustion
            connect_args={
                "options": "-c statement_timeout=30000"  # Kill queries running >30s
            },
        )


engine = _create_engine()

# Slow query logging via SQLAlchemy event listener
from sqlalchemy import event


@event.listens_for(engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info.setdefault("query_start_time", []).append(time.time())


@event.listens_for(engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    total = time.time() - conn.info["query_start_time"].pop(-1)
    if total > 1.0:  # Log queries taking more than 1 second
        logger.warning(f"Slow query ({total:.2f}s): {statement[:200]}")


def _run_migrations():
    """Run database migrations to add new columns/tables."""
    from sqlalchemy import inspect, text

    db_type = get_database_type()
    inspector = inspect(engine)

    with engine.connect() as conn:
        # Check and add new columns to testrun table
        if "testrun" in inspector.get_table_names():
            existing_columns = {col["name"] for col in inspector.get_columns("testrun")}

            # Add completed_at column
            if "completed_at" not in existing_columns:
                if db_type == "postgresql":
                    conn.execute(text("ALTER TABLE testrun ADD COLUMN completed_at TIMESTAMP"))
                else:
                    conn.execute(text("ALTER TABLE testrun ADD COLUMN completed_at DATETIME"))
                logger.info("Added column: testrun.completed_at")

            # Add batch_id column
            if "batch_id" not in existing_columns:
                conn.execute(text("ALTER TABLE testrun ADD COLUMN batch_id VARCHAR"))
                logger.info("Added column: testrun.batch_id")

            # Add error_message column
            if "error_message" not in existing_columns:
                conn.execute(text("ALTER TABLE testrun ADD COLUMN error_message TEXT"))
                logger.info("Added column: testrun.error_message")

            # Add project_id column
            if "project_id" not in existing_columns:
                conn.execute(text("ALTER TABLE testrun ADD COLUMN project_id VARCHAR"))
                logger.info("Added column: testrun.project_id")

            # Stage tracking columns for real-time UI feedback
            if "current_stage" not in existing_columns:
                conn.execute(text("ALTER TABLE testrun ADD COLUMN current_stage VARCHAR"))
                logger.info("Added column: testrun.current_stage")

            if "stage_started_at" not in existing_columns:
                if db_type == "postgresql":
                    conn.execute(text("ALTER TABLE testrun ADD COLUMN stage_started_at TIMESTAMP"))
                else:
                    conn.execute(text("ALTER TABLE testrun ADD COLUMN stage_started_at DATETIME"))
                logger.info("Added column: testrun.stage_started_at")

            if "stage_message" not in existing_columns:
                conn.execute(text("ALTER TABLE testrun ADD COLUMN stage_message VARCHAR"))
                logger.info("Added column: testrun.stage_message")

            if "healing_attempt" not in existing_columns:
                conn.execute(text("ALTER TABLE testrun ADD COLUMN healing_attempt INTEGER"))
                logger.info("Added column: testrun.healing_attempt")

            # Add test_type column (API testing feature)
            if "test_type" not in existing_columns:
                conn.execute(text("ALTER TABLE testrun ADD COLUMN test_type VARCHAR DEFAULT 'browser'"))
                logger.info("Added column: testrun.test_type")

        # Create regression_batches table if it doesn't exist
        if "regression_batches" not in inspector.get_table_names():
            if db_type == "postgresql":
                conn.execute(
                    text("""
                    CREATE TABLE regression_batches (
                        id VARCHAR PRIMARY KEY,
                        name VARCHAR,
                        triggered_by VARCHAR,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        started_at TIMESTAMP,
                        completed_at TIMESTAMP,
                        browser VARCHAR NOT NULL DEFAULT 'chromium',
                        tags_used_json VARCHAR NOT NULL DEFAULT '[]',
                        hybrid_mode BOOLEAN NOT NULL DEFAULT FALSE,
                        project_id VARCHAR,
                        total_tests INTEGER NOT NULL DEFAULT 0,
                        passed INTEGER NOT NULL DEFAULT 0,
                        failed INTEGER NOT NULL DEFAULT 0,
                        stopped INTEGER NOT NULL DEFAULT 0,
                        running INTEGER NOT NULL DEFAULT 0,
                        queued INTEGER NOT NULL DEFAULT 0,
                        status VARCHAR NOT NULL DEFAULT 'pending'
                    )
                """)
                )
            else:
                conn.execute(
                    text("""
                    CREATE TABLE regression_batches (
                        id VARCHAR PRIMARY KEY,
                        name VARCHAR,
                        triggered_by VARCHAR,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        started_at DATETIME,
                        completed_at DATETIME,
                        browser VARCHAR NOT NULL DEFAULT 'chromium',
                        tags_used_json VARCHAR NOT NULL DEFAULT '[]',
                        hybrid_mode BOOLEAN NOT NULL DEFAULT 0,
                        project_id VARCHAR,
                        total_tests INTEGER NOT NULL DEFAULT 0,
                        passed INTEGER NOT NULL DEFAULT 0,
                        failed INTEGER NOT NULL DEFAULT 0,
                        stopped INTEGER NOT NULL DEFAULT 0,
                        running INTEGER NOT NULL DEFAULT 0,
                        queued INTEGER NOT NULL DEFAULT 0,
                        status VARCHAR NOT NULL DEFAULT 'pending'
                    )
                """)
                )
            logger.info("Created table: regression_batches")
        else:
            # Add project_id to existing regression_batches table
            batch_columns = {col["name"] for col in inspector.get_columns("regression_batches")}
            if "project_id" not in batch_columns:
                conn.execute(text("ALTER TABLE regression_batches ADD COLUMN project_id VARCHAR"))
                logger.info("Added column: regression_batches.project_id")

            # Cached actual test counts (D1 performance fix)
            if "actual_total_tests" not in batch_columns:
                conn.execute(text("ALTER TABLE regression_batches ADD COLUMN actual_total_tests INTEGER"))
                logger.info("Added column: regression_batches.actual_total_tests")
            if "actual_passed" not in batch_columns:
                conn.execute(text("ALTER TABLE regression_batches ADD COLUMN actual_passed INTEGER"))
                logger.info("Added column: regression_batches.actual_passed")
            if "actual_failed" not in batch_columns:
                conn.execute(text("ALTER TABLE regression_batches ADD COLUMN actual_failed INTEGER"))
                logger.info("Added column: regression_batches.actual_failed")

        # Add project_id to specmetadata table
        if "specmetadata" in inspector.get_table_names():
            spec_columns = {col["name"] for col in inspector.get_columns("specmetadata")}
            if "project_id" not in spec_columns:
                conn.execute(text("ALTER TABLE specmetadata ADD COLUMN project_id VARCHAR"))
                logger.info("Added column: specmetadata.project_id")

        # Add project_id to agentrun table
        if "agentrun" in inspector.get_table_names():
            agentrun_columns = {col["name"] for col in inspector.get_columns("agentrun")}
            if "project_id" not in agentrun_columns:
                conn.execute(text("ALTER TABLE agentrun ADD COLUMN project_id VARCHAR"))
                logger.info("Added column: agentrun.project_id")

        # Add title_embedding_json to requirements table for deduplication
        if "requirements" in inspector.get_table_names():
            req_columns = {col["name"] for col in inspector.get_columns("requirements")}
            if "title_embedding_json" not in req_columns:
                conn.execute(text("ALTER TABLE requirements ADD COLUMN title_embedding_json TEXT"))
                logger.info("Added column: requirements.title_embedding_json")

        # Add log_path to prd_generation_results table for real-time log streaming
        if "prd_generation_results" in inspector.get_table_names():
            prd_gen_columns = {col["name"] for col in inspector.get_columns("prd_generation_results")}
            if "log_path" not in prd_gen_columns:
                conn.execute(text("ALTER TABLE prd_generation_results ADD COLUMN log_path VARCHAR"))
                logger.info("Added column: prd_generation_results.log_path")

        # ===== User tracking columns (Phase: Multi-User Support) =====

        # Add created_by and triggered_by to existing tables
        user_tracking_columns = {
            "projects": ["created_by"],
            "testrun": ["triggered_by"],
            "specmetadata": ["created_by", "last_modified_by"],
            "exploration_sessions": ["created_by"],
            "requirements": ["created_by", "last_modified_by"],
        }

        for table_name, columns in user_tracking_columns.items():
            if table_name in inspector.get_table_names():
                existing = {col["name"] for col in inspector.get_columns(table_name)}
                for col in columns:
                    if col not in existing:
                        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col} VARCHAR"))
                        logger.info(f"Added column: {table_name}.{col}")

        # Create indexes for auth tables (if they exist)
        if "users" in inspector.get_table_names():
            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)"))
            except Exception as e:
                logger.debug(f"Index creation note: {e}")

        if "refresh_tokens" in inspector.get_table_names():
            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user_id ON refresh_tokens (user_id)"))
            except Exception as e:
                logger.debug(f"Index creation note: {e}")

        if "project_members" in inspector.get_table_names():
            try:
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_project_members_project_id ON project_members (project_id)")
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_project_members_user_id ON project_members (user_id)"))
            except Exception as e:
                logger.debug(f"Index creation note: {e}")

        # ===== Production Data Management - Performance Indexes =====

        # Add performance indexes for testrun table (Phase 4: Database Optimization)
        if "testrun" in inspector.get_table_names():
            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_testrun_created_at ON testrun (created_at)"))
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_testrun_project_date ON testrun (project_id, created_at)")
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_testrun_status_date ON testrun (status, created_at)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_testrun_test_type ON testrun (test_type)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_testrun_type_spec ON testrun (test_type, spec_name)"))
                logger.info("Created performance indexes on testrun table")
            except Exception as e:
                logger.debug(f"Indexes may already exist on testrun: {e}")

        # Add indexes for run_artifacts table
        if "run_artifacts" in inspector.get_table_names():
            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_run_artifacts_run_id ON run_artifacts (run_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_run_artifacts_type ON run_artifacts (artifact_type)"))
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_run_artifacts_storage ON run_artifacts (storage_type)")
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_run_artifacts_expires ON run_artifacts (expires_at)"))
                logger.info("Created indexes on run_artifacts table")
            except Exception as e:
                logger.debug(f"Indexes may already exist on run_artifacts: {e}")

        # Add indexes for archive_jobs table
        if "archive_jobs" in inspector.get_table_names():
            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_archive_jobs_status ON archive_jobs (status)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_archive_jobs_created ON archive_jobs (created_at)"))
                logger.info("Created indexes on archive_jobs table")
            except Exception as e:
                logger.debug(f"Indexes may already exist on archive_jobs: {e}")

        # Add indexes for storage_stats table
        if "storage_stats" in inspector.get_table_names():
            try:
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_storage_stats_recorded ON storage_stats (recorded_at)")
                )
                logger.info("Created indexes on storage_stats table")
            except Exception as e:
                logger.debug(f"Indexes may already exist on storage_stats: {e}")

        # ===== TestRail Integration Tables =====

        if "testrail_case_mappings" in inspector.get_table_names():
            try:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_testrail_case_unique "
                        "ON testrail_case_mappings (project_id, spec_name, testrail_suite_id)"
                    )
                )
                logger.info("Created unique index on testrail_case_mappings")
            except Exception as e:
                logger.debug(f"Index may already exist on testrail_case_mappings: {e}")

        if "testrail_run_mappings" in inspector.get_table_names():
            try:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_testrail_run_unique "
                        "ON testrail_run_mappings (project_id, batch_id, testrail_run_id)"
                    )
                )
                logger.info("Created unique index on testrail_run_mappings")
            except Exception as e:
                logger.debug(f"Index may already exist on testrail_run_mappings: {e}")

        # ===== Load Testing - Distributed Execution =====

        # Add worker_count to load_test_runs table for distributed K6 execution
        if "load_test_runs" in inspector.get_table_names():
            lt_columns = {col["name"] for col in inspector.get_columns("load_test_runs")}
            if "worker_count" not in lt_columns:
                conn.execute(text("ALTER TABLE load_test_runs ADD COLUMN worker_count INTEGER"))
                logger.info("Added column: load_test_runs.worker_count")
            if "peak_vus" not in lt_columns:
                conn.execute(text("ALTER TABLE load_test_runs ADD COLUMN peak_vus INTEGER"))
                logger.info("Added column: load_test_runs.peak_vus")
            if "ai_analysis_json" not in lt_columns:
                conn.execute(
                    text("ALTER TABLE load_test_runs ADD COLUMN ai_analysis_json VARCHAR NOT NULL DEFAULT '{}'")
                )
                logger.info("Added column: load_test_runs.ai_analysis_json")

        # ===== Missing FK Indexes =====
        try:
            if "coverage_metrics" in inspector.get_table_names():
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_coverage_metrics_run_id ON coverage_metrics (run_id)"))
            if "flow_steps" in inspector.get_table_names():
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_flow_steps_transition_id ON flow_steps (transition_id)")
                )
            if "requirements" in inspector.get_table_names():
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_requirements_source_session_id ON requirements (source_session_id)"
                    )
                )
            if "llm_test_runs" in inspector.get_table_names():
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_llm_test_runs_provider_id ON llm_test_runs (provider_id)")
                )
            logger.info("Created missing FK indexes")
        except Exception as e:
            logger.debug(f"FK index creation note: {e}")

        # ===== Fix flow_steps.value column type (BOOLEAN -> VARCHAR) =====
        if db_type == "postgresql" and "flow_steps" in inspector.get_table_names():
            try:
                result = conn.execute(
                    text(
                        "SELECT data_type FROM information_schema.columns "
                        "WHERE table_name = 'flow_steps' AND column_name = 'value'"
                    )
                )
                row = result.fetchone()
                if row and row[0] == "boolean":
                    conn.execute(
                        text(
                            "ALTER TABLE flow_steps ALTER COLUMN value TYPE VARCHAR "
                            "USING CASE WHEN value IS NULL THEN NULL "
                            "WHEN value THEN 'true' ELSE 'false' END"
                        )
                    )
                    logger.info("Fixed flow_steps.value column type: BOOLEAN -> VARCHAR")
            except Exception as e:
                logger.warning(f"Could not fix flow_steps.value column type: {e}")

        # ===== LLM Testing - Dataset Execution =====
        if "llm_test_runs" in inspector.get_table_names():
            llm_run_cols = {c["name"] for c in inspector.get_columns("llm_test_runs")}
            if "dataset_id" not in llm_run_cols:
                conn.execute(text("ALTER TABLE llm_test_runs ADD COLUMN dataset_id VARCHAR"))
                logger.info("Added column: llm_test_runs.dataset_id")
            if "dataset_name" not in llm_run_cols:
                conn.execute(text("ALTER TABLE llm_test_runs ADD COLUMN dataset_name VARCHAR"))
                logger.info("Added column: llm_test_runs.dataset_name")
            if "dataset_version" not in llm_run_cols:
                conn.execute(text("ALTER TABLE llm_test_runs ADD COLUMN dataset_version INTEGER"))
                logger.info("Added column: llm_test_runs.dataset_version")

        if "llm_datasets" in inspector.get_table_names():
            ds_cols = {c["name"] for c in inspector.get_columns("llm_datasets")}
            if "is_golden" not in ds_cols:
                conn.execute(text("ALTER TABLE llm_datasets ADD COLUMN is_golden BOOLEAN DEFAULT FALSE"))
                logger.info("Added column: llm_datasets.is_golden")

        # ===== Chat - Missing columns =====
        if "chat_conversations" in inspector.get_table_names():
            chat_cols = {c["name"] for c in inspector.get_columns("chat_conversations")}
            if "is_starred" not in chat_cols:
                if db_type == "postgresql":
                    conn.execute(text("ALTER TABLE chat_conversations ADD COLUMN is_starred BOOLEAN DEFAULT FALSE"))
                else:
                    conn.execute(text("ALTER TABLE chat_conversations ADD COLUMN is_starred BOOLEAN DEFAULT 0"))
                logger.info("Added column: chat_conversations.is_starred")
            if "summary" not in chat_cols:
                conn.execute(text("ALTER TABLE chat_conversations ADD COLUMN summary TEXT"))
                logger.info("Added column: chat_conversations.summary")

        if "chat_messages" in inspector.get_table_names():
            msg_cols = {c["name"] for c in inspector.get_columns("chat_messages")}
            if "content_json" not in msg_cols:
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN content_json TEXT"))
                logger.info("Added column: chat_messages.content_json")

        # ===== Exploration - Discovered Issues =====
        if "discovered_issues" not in inspector.get_table_names():
            if db_type == "postgresql":
                conn.execute(
                    text("""
                    CREATE TABLE discovered_issues (
                        id SERIAL PRIMARY KEY,
                        session_id VARCHAR NOT NULL REFERENCES exploration_sessions(id),
                        issue_type VARCHAR NOT NULL,
                        severity VARCHAR NOT NULL DEFAULT 'medium',
                        url VARCHAR NOT NULL DEFAULT '',
                        description VARCHAR NOT NULL DEFAULT '',
                        element VARCHAR,
                        evidence VARCHAR,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """)
                )
            else:
                conn.execute(
                    text("""
                    CREATE TABLE discovered_issues (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id VARCHAR NOT NULL REFERENCES exploration_sessions(id),
                        issue_type VARCHAR NOT NULL,
                        severity VARCHAR NOT NULL DEFAULT 'medium',
                        url VARCHAR NOT NULL DEFAULT '',
                        description VARCHAR NOT NULL DEFAULT '',
                        element VARCHAR,
                        evidence VARCHAR,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_discovered_issues_session_id ON discovered_issues (session_id)")
            )
            logger.info("Created table: discovered_issues")

        if "exploration_sessions" in inspector.get_table_names():
            es_cols = {c["name"] for c in inspector.get_columns("exploration_sessions")}
            if "issues_discovered" not in es_cols:
                conn.execute(
                    text("ALTER TABLE exploration_sessions ADD COLUMN issues_discovered INTEGER NOT NULL DEFAULT 0")
                )
                logger.info("Added column: exploration_sessions.issues_discovered")
            if "progress_data" not in es_cols:
                conn.execute(text("ALTER TABLE exploration_sessions ADD COLUMN progress_data TEXT"))
                logger.info("Added column: exploration_sessions.progress_data")

        conn.commit()


def _create_initial_admin_if_configured(session: Session):
    """Create initial admin user from environment variables if configured.

    This function enables bootstrapping the first admin user during production
    deployment. It only runs when:
    1. INITIAL_ADMIN_EMAIL and INITIAL_ADMIN_PASSWORD are set in environment
    2. No users exist in the database (first startup)

    After first deployment, you can clear these env vars for security.
    """
    from sqlmodel import select

    from .security import hash_password, is_password_strong

    try:
        # Check if any users exist
        existing_users = session.exec(select(User).limit(1)).first()
        if existing_users:
            logger.info("Users already exist, skipping initial admin creation")
            return

        admin_email = (app_settings.initial_admin_email or "").strip()
        admin_password = (app_settings.initial_admin_password or "").strip()

        if not admin_email or not admin_password:
            logger.info("INITIAL_ADMIN_EMAIL/PASSWORD not set, skipping admin creation")
            return

        # Validate password strength
        is_strong, error = is_password_strong(admin_password)
        if not is_strong:
            logger.error(f"INITIAL_ADMIN_PASSWORD failed validation: {error}")
            return

        # Create admin user
        admin = User(
            email=admin_email.lower(),
            password_hash=hash_password(admin_password),
            full_name="Admin User",
            is_active=True,
            is_superuser=True,
            email_verified=True,
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)

        logger.info(f"✓ Created initial admin user: {admin_email}")

        # Add admin to default project (non-critical, wrapped separately)
        try:
            member = ProjectMember(project_id="default", user_id=admin.id, role="admin")
            session.add(member)
            session.commit()
            logger.info("✓ Added admin to default project")
        except Exception as e:
            logger.warning(f"Could not add admin to default project: {e}")
            # Don't fail - admin user was created successfully

    except Exception as e:
        logger.error(f"Failed to create initial admin user: {e}")
        # Don't re-raise - init_db should continue


def _run_alembic_migrations():
    """Run Alembic migrations for PostgreSQL databases.

    For fresh databases: runs all migrations from scratch.
    For existing databases: stamps current revision if alembic_version
    table doesn't exist, then upgrades to head.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    project_root = Path(__file__).resolve().parent.parent.parent
    alembic_cfg = Config(str(project_root / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)

    inspector = inspect(engine)
    tables = inspector.get_table_names()

    if "alembic_version" not in tables and len(tables) > 0:
        # Existing database without Alembic - stamp current revision
        logger.info("Existing database detected, stamping Alembic baseline (001)...")
        command.stamp(alembic_cfg, "001")
        logger.info("Alembic baseline stamped. Future migrations will run normally.")
    else:
        # Fresh database or already using Alembic - run all pending migrations
        logger.info("Running Alembic migrations to head...")
        command.upgrade(alembic_cfg, "head")
        logger.info("Alembic migrations complete.")


def init_db():
    """Initialize the database schema and settings."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError, ProgrammingError

    # SQLite production guard: prevent SQLite usage in production environments
    if get_database_type() == "sqlite" and os.getenv("ENVIRONMENT", "development") == "production":
        raise RuntimeError(
            "SQLite is not supported for production deployments. Set DATABASE_URL to a PostgreSQL connection string."
        )

    if get_database_type() == "postgresql":
        # PostgreSQL: use Alembic for schema management
        try:
            _run_alembic_migrations()
        except Exception as e:
            logger.warning(f"Alembic migration failed, falling back to create_all: {e}")

        # Always run create_all with checkfirst=True to pick up new models
        # that don't have Alembic migrations yet (e.g., SecurityScanRun)
        try:
            SQLModel.metadata.create_all(engine, checkfirst=True)
            logger.info("Database tables synced (create_all with checkfirst)")
        except (ProgrammingError, OperationalError) as ce:
            if "already exists" not in str(ce).lower():
                raise

        # Run legacy migrations for any columns not yet in Alembic
        logger.info("Running legacy column migrations...")
        _run_migrations()
    else:
        # SQLite: use create_all + legacy migrations (no Alembic)
        try:
            SQLModel.metadata.create_all(engine, checkfirst=True)
            logger.info("Database tables created successfully")
        except (ProgrammingError, OperationalError) as e:
            error_str = str(e).lower()
            if "already exists" in error_str:
                logger.info("Database tables already exist")
            else:
                logger.error(f"Error creating database tables: {e}")
                raise

        logger.info("Running database migrations...")
        _run_migrations()

    # Enable WAL mode for SQLite (improves concurrent read performance)
    if get_database_type() == "sqlite":
        from sqlalchemy import text

        max_browsers = app_settings.max_browser_instances
        if max_browsers > 1:
            logger.error(
                "WARNING: SQLite detected with MAX_BROWSER_INSTANCES=%d. "
                "SQLite has limited concurrent write support. "
                "For production with parallel execution, set DATABASE_URL to a PostgreSQL connection string. "
                "Consider setting MAX_BROWSER_INSTANCES=1 or switching to PostgreSQL.",
                max_browsers,
            )
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA busy_timeout=60000"))  # 60 second timeout
            conn.commit()

    # Initialize execution settings with defaults if not exists
    with Session(engine) as session:
        settings = session.get(ExecutionSettings, 1)
        if not settings:
            # Use environment defaults for initial settings
            env_parallelism = app_settings.default_parallelism
            env_parallel_enabled = app_settings.parallel_mode_enabled

            # Only enable parallel mode if database supports it
            parallel_enabled = env_parallel_enabled and is_parallel_mode_available()

            settings = ExecutionSettings(
                id=1, parallelism=max(1, min(10, env_parallelism)), parallel_mode_enabled=parallel_enabled
            )
            session.add(settings)
            session.commit()
            logger.info(
                f"Created execution settings: parallelism={settings.parallelism}, parallel_mode={settings.parallel_mode_enabled}"
            )

        # Ensure default project exists
        default_project = session.get(Project, "default")
        if not default_project:
            default_project = Project(
                id="default", name="Default Project", description="Default project for all existing and new content"
            )
            session.add(default_project)
            session.commit()
            logger.info("Created default project")

        # Create initial admin user if configured
        _create_initial_admin_if_configured(session)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
