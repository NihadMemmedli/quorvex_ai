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
