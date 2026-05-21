"""
Tests for database initialization and migration idempotency.

Run with: pytest orchestrator/tests/test_migrations.py -v
"""

import os
import sys
from pathlib import Path

# Ensure test environment
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-migration-tests")

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestDatabaseInit:
    """Test that init_db() works correctly on a fresh database."""

    def test_init_db_fresh_sqlite(self, tmp_path):
        """init_db() should run cleanly on a fresh SQLite database."""
        db_path = tmp_path / "test.db"
        db_url = f"sqlite:///{db_path}"

        # Patch DATABASE_URL before importing
        import orchestrator.api.db as db_module

        original_url = db_module.DATABASE_URL
        original_engine = db_module.engine

        try:
            db_module.DATABASE_URL = db_url
            db_module.engine = (
                db_module._create_engine.__wrapped__()
                if hasattr(db_module._create_engine, "__wrapped__")
                else db_module.create_engine(
                    db_url, echo=False, connect_args={"check_same_thread": False, "timeout": 30}
                )
            )

            # Should not raise
            from sqlmodel import SQLModel

            SQLModel.metadata.create_all(db_module.engine, checkfirst=True)

            # Verify tables were created
            from sqlalchemy import inspect

            inspector = inspect(db_module.engine)
            tables = inspector.get_table_names()

            assert "testrun" in tables
            assert "projects" in tables
        finally:
            db_module.DATABASE_URL = original_url
            db_module.engine = original_engine

    def test_run_migrations_idempotent(self, tmp_path):
        """_run_migrations() should be idempotent - safe to run multiple times."""
        db_path = tmp_path / "test_idempotent.db"
        db_url = f"sqlite:///{db_path}"

        from sqlmodel import SQLModel, create_engine

        import orchestrator.api.db as db_module

        original_url = db_module.DATABASE_URL
        original_engine = db_module.engine

        try:
            db_module.DATABASE_URL = db_url
            db_module.engine = create_engine(
                db_url, echo=False, connect_args={"check_same_thread": False, "timeout": 30}
            )

            # Create all tables first
            SQLModel.metadata.create_all(db_module.engine, checkfirst=True)

            # Run migrations twice - should not raise
            db_module._run_migrations()
            db_module._run_migrations()

            # Verify indexes exist (from the FK index additions)
            from sqlalchemy import inspect

            inspector = inspect(db_module.engine)
            tables = inspector.get_table_names()

            # Check that key tables have their indexes
            if "testrun" in tables:
                indexes = inspector.get_indexes("testrun")
                index_names = {idx["name"] for idx in indexes}
                assert "ix_testrun_created_at" in index_names

        finally:
            db_module.DATABASE_URL = original_url
            db_module.engine = original_engine

    def test_migrations_add_columns_safely(self, tmp_path):
        """Migrations should safely handle already-existing columns."""
        db_path = tmp_path / "test_columns.db"
        db_url = f"sqlite:///{db_path}"

        from sqlmodel import SQLModel, create_engine

        import orchestrator.api.db as db_module

        original_url = db_module.DATABASE_URL
        original_engine = db_module.engine

        try:
            db_module.DATABASE_URL = db_url
            db_module.engine = create_engine(
                db_url, echo=False, connect_args={"check_same_thread": False, "timeout": 30}
            )

            # Create tables and run migrations
            SQLModel.metadata.create_all(db_module.engine, checkfirst=True)
            db_module._run_migrations()

            # Run again - columns already exist, should not fail
            db_module._run_migrations()

            # Verify key columns exist
            from sqlalchemy import inspect

            inspector = inspect(db_module.engine)

            if "testrun" in inspector.get_table_names():
                columns = {col["name"] for col in inspector.get_columns("testrun")}
                assert "completed_at" in columns
                assert "batch_id" in columns
                assert "project_id" in columns
                assert "current_stage" in columns
                assert "test_type" in columns

        finally:
            db_module.DATABASE_URL = original_url
            db_module.engine = original_engine

    def test_run_migrations_repairs_legacy_autonomous_health_columns(self, tmp_path):
        """Legacy autonomous tables should get health/status columns added idempotently."""
        db_path = tmp_path / "test_autonomous_legacy.db"
        db_url = f"sqlite:///{db_path}"

        from sqlalchemy import inspect, text
        from sqlmodel import create_engine

        import orchestrator.api.db as db_module

        original_url = db_module.DATABASE_URL
        original_engine = db_module.engine

        try:
            db_module.DATABASE_URL = db_url
            db_module.engine = create_engine(
                db_url, echo=False, connect_args={"check_same_thread": False, "timeout": 30}
            )

            with db_module.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        CREATE TABLE autonomous_missions (
                            id VARCHAR PRIMARY KEY,
                            project_id VARCHAR,
                            name VARCHAR NOT NULL,
                            description VARCHAR,
                            mission_type VARCHAR NOT NULL,
                            status VARCHAR NOT NULL,
                            target_urls_json VARCHAR NOT NULL,
                            schedule_cron VARCHAR,
                            timezone VARCHAR NOT NULL,
                            autonomy_level VARCHAR NOT NULL,
                            approval_policy VARCHAR NOT NULL,
                            max_runtime_minutes INTEGER NOT NULL,
                            max_iterations INTEGER NOT NULL,
                            max_llm_budget_usd FLOAT,
                            budget_used_usd FLOAT NOT NULL,
                            config_json VARCHAR NOT NULL,
                            latest_workflow_id VARCHAR,
                            latest_run_id VARCHAR,
                            last_run_at DATETIME,
                            next_run_at DATETIME,
                            last_error VARCHAR,
                            total_runs INTEGER NOT NULL,
                            total_findings INTEGER NOT NULL,
                            created_by VARCHAR,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE TABLE autonomous_mission_runs (
                            id VARCHAR PRIMARY KEY,
                            mission_id VARCHAR NOT NULL,
                            project_id VARCHAR,
                            workflow_id VARCHAR,
                            mission_type VARCHAR NOT NULL,
                            trigger_type VARCHAR NOT NULL,
                            status VARCHAR NOT NULL,
                            current_stage VARCHAR,
                            summary_json VARCHAR NOT NULL,
                            artifacts_json VARCHAR NOT NULL,
                            error_message VARCHAR,
                            budget_used_usd FLOAT NOT NULL,
                            started_at DATETIME,
                            completed_at DATETIME,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL
                        )
                        """
                    )
                )

            db_module._run_migrations()
            db_module._run_migrations()

            inspector = inspect(db_module.engine)
            mission_columns = {col["name"] for col in inspector.get_columns("autonomous_missions")}
            run_columns = {col["name"] for col in inspector.get_columns("autonomous_mission_runs")}
            mission_indexes = {idx["name"] for idx in inspector.get_indexes("autonomous_missions")}

            assert {
                "health_status",
                "paused_reason",
                "consecutive_failures",
                "last_heartbeat_at",
                "current_stage",
                "next_action",
            } <= mission_columns
            assert "checkpoint_json" in run_columns
            assert "ix_autonomous_missions_health_status" in mission_indexes

        finally:
            db_module.DATABASE_URL = original_url
            db_module.engine = original_engine

    def test_detects_legacy_alembic_drift(self, tmp_path):
        """A database stamped at 001 with post-baseline objects should use legacy sync."""
        db_path = tmp_path / "test_alembic_drift.db"
        db_url = f"sqlite:///{db_path}"

        from sqlalchemy import text
        from sqlmodel import create_engine

        import orchestrator.api.db as db_module

        original_url = db_module.DATABASE_URL
        original_engine = db_module.engine

        try:
            db_module.DATABASE_URL = db_url
            db_module.engine = create_engine(
                db_url, echo=False, connect_args={"check_same_thread": False, "timeout": 30}
            )

            with db_module.engine.begin() as conn:
                conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR NOT NULL)"))
                conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('001')"))
                conn.execute(text("CREATE TABLE testrun (id VARCHAR PRIMARY KEY, spec_name VARCHAR)"))
                conn.execute(text("CREATE INDEX ix_testrun_spec_name ON testrun (spec_name)"))

            assert db_module._has_legacy_alembic_drift() is True

            with db_module.engine.begin() as conn:
                conn.execute(text("UPDATE alembic_version SET version_num = '017'"))

            assert db_module._has_legacy_alembic_drift() is False

        finally:
            db_module.DATABASE_URL = original_url
            db_module.engine = original_engine
