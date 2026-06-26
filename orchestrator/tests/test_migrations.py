"""
Tests for database initialization and migration idempotency.

Run with: pytest orchestrator/tests/test_migrations.py -v
"""

import os
import re
import sys
from pathlib import Path

# Ensure test environment
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-migration-tests")

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestDatabaseInit:
    """Test that init_db() works correctly on a fresh database."""

    def test_alembic_revision_ids_are_unique_and_ordered(self):
        versions_dir = Path(__file__).parent.parent / "migrations" / "versions"
        revisions: dict[str, list[Path]] = {}
        down_revisions: dict[str, str | None] = {}
        for migration in versions_dir.glob("*.py"):
            text = migration.read_text(encoding="utf-8")
            match = re.search(r"^revision(?:\s*:\s*[^=]+)?\s*=\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)
            if not match:
                continue
            revision = match.group(1)
            revisions.setdefault(revision, []).append(migration)
            down_match = re.search(
                r"^down_revision(?:\s*:\s*[^=]+)?\s*=\s*(?:[\"']([^\"']+)[\"']|None)",
                text,
                re.MULTILINE,
            )
            down_revisions[revision] = down_match.group(1) if down_match and down_match.group(1) else None

        hardening = versions_dir / "033_autonomous_whole_app_hardening.py"
        hardening_text = hardening.read_text(encoding="utf-8")
        assert 'revision = "033"' in hardening_text
        assert 'down_revision = "032"' in hardening_text
        assert len(revisions.get("033", [])) == 1
        assert len(revisions.get("034", [])) == 1
        assert len(revisions.get("035", [])) == 1
        assert len(revisions.get("036", [])) == 1
        assert len(revisions.get("037", [])) == 1
        assert len(revisions.get("038", [])) == 1
        assert len(revisions.get("039", [])) == 1
        assert len(revisions.get("040", [])) == 1
        assert len(revisions.get("041", [])) == 1
        assert len(revisions.get("042", [])) == 1
        assert len(revisions.get("043", [])) == 1
        assert len(revisions.get("044", [])) == 1
        assert len(revisions.get("045", [])) == 1
        assert len(revisions.get("046", [])) == 1
        assert len(revisions.get("047", [])) == 1
        assert len(revisions.get("048", [])) == 1
        assert len(revisions.get("049", [])) == 1
        assert len(revisions.get("050", [])) == 1
        assert len(revisions.get("051", [])) == 1
        assert len(revisions.get("052", [])) == 1
        assert len(revisions.get("053", [])) == 1
        assert len(revisions.get("054", [])) == 1
        assert len(revisions.get("055", [])) == 1
        assert len(revisions.get("056", [])) == 1
        assert len(revisions.get("057", [])) == 1
        assert len(revisions.get("058", [])) == 1
        assert down_revisions["032"] == "031"
        assert down_revisions["033"] == "032"
        assert down_revisions["034"] == "033"
        assert down_revisions["035"] == "034"
        assert down_revisions["036"] == "035"
        assert down_revisions["037"] == "036"
        assert down_revisions["038"] == "037"
        assert down_revisions["039"] == "038"
        assert down_revisions["040"] == "039"
        assert down_revisions["041"] == "040"
        assert down_revisions["042"] == "041"
        assert down_revisions["043"] == "042"
        assert down_revisions["044"] == "043"
        assert down_revisions["045"] == "044"
        assert down_revisions["046"] == "045"
        assert down_revisions["047"] == "046"
        assert down_revisions["048"] == "047"
        assert down_revisions["049"] == "048"
        assert down_revisions["050"] == "049"
        assert down_revisions["051"] == "050"
        assert down_revisions["052"] == "051"
        assert down_revisions["053"] == "052"
        assert down_revisions["054"] == "053"
        assert down_revisions["055"] == "054"
        assert down_revisions["056"] == "055"
        assert down_revisions["057"] == "056"
        assert down_revisions["058"] == "057"

        referenced = {revision for revision in down_revisions.values() if revision}
        heads = sorted(set(revisions) - referenced)
        assert heads == ["058"]

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

    def test_run_migrations_repairs_legacy_prd_generation_live_browser_intent_columns(self, tmp_path):
        """Legacy PRD generation result tables should get live-browser intent columns idempotently."""
        db_path = tmp_path / "test_prd_generation_legacy.db"
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
                        CREATE TABLE prd_generation_results (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            prd_project VARCHAR NOT NULL,
                            feature_name VARCHAR NOT NULL,
                            status VARCHAR NOT NULL,
                            current_stage VARCHAR,
                            stage_message VARCHAR,
                            spec_path VARCHAR,
                            error_message VARCHAR,
                            created_at DATETIME,
                            started_at DATETIME,
                            completed_at DATETIME,
                            log_path VARCHAR,
                            project_id VARCHAR
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO prd_generation_results (
                            prd_project,
                            feature_name,
                            status
                        ) VALUES (
                            'legacy-prd',
                            'Checkout',
                            'running'
                        )
                        """
                    )
                )

            db_module._run_migrations()
            db_module._run_migrations()

            inspector = inspect(db_module.engine)
            columns = {col["name"] for col in inspector.get_columns("prd_generation_results")}
            assert {"target_url", "live_browser_requested"} <= columns

            with db_module.engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT target_url, live_browser_requested
                        FROM prd_generation_results
                        WHERE feature_name = 'Checkout'
                        """
                    )
                ).mappings().one()

            assert row["target_url"] is None
            assert row["live_browser_requested"] in (False, 0)

        finally:
            db_module.DATABASE_URL = original_url
            db_module.engine = original_engine

    def test_run_migrations_repairs_legacy_openapi_import_history_columns(self, tmp_path):
        """Legacy OpenAPI import history tables should get latest import workflow columns."""
        db_path = tmp_path / "test_openapi_import_history_legacy.db"
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
                        CREATE TABLE openapi_import_history (
                            id VARCHAR PRIMARY KEY,
                            project_id VARCHAR,
                            source_type VARCHAR NOT NULL,
                            source_url VARCHAR,
                            source_filename VARCHAR,
                            feature_filter VARCHAR,
                            status VARCHAR NOT NULL DEFAULT 'running',
                            files_generated INTEGER NOT NULL DEFAULT 0,
                            generated_paths_json VARCHAR NOT NULL DEFAULT '[]',
                            error_message TEXT,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            completed_at DATETIME
                        )
                        """
                    )
                )

            db_module._run_migrations()
            db_module._run_migrations()

            inspector = inspect(db_module.engine)
            columns = {col["name"] for col in inspector.get_columns("openapi_import_history")}
            assert {
                "base_url",
                "job_id",
                "method_filter_json",
                "mode",
                "needs_input",
                "missing_fields_json",
                "plan_path",
                "spec_paths_json",
                "test_paths_json",
                "evidence_paths_json",
                "matched_operations",
                "executed_operations",
                "blocked_operations_json",
                "failed_operations_json",
                "skipped_operations",
                "chunk_count",
                "recommended_mode",
                "recommended_next_action",
                "warnings_json",
                "diagnostics_json",
            } <= columns

            indexes = {index["name"] for index in inspector.get_indexes("openapi_import_history")}
            assert "ix_openapi_import_history_job_id" in indexes

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

    def test_run_migrations_repairs_legacy_agent_memory_columns(self, tmp_path, monkeypatch):
        """Legacy agent memory tables should get typed context columns added idempotently."""
        db_path = tmp_path / "test_agent_memory_legacy.db"
        db_url = f"sqlite:///{db_path}"

        from sqlalchemy import inspect, text
        from sqlmodel import create_engine

        import orchestrator.api.db as db_module
        from orchestrator.memory import agent_memory as agent_memory_module
        from orchestrator.memory.agent_memory import AgentMemoryService

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
                        CREATE TABLE agent_memories (
                            id VARCHAR PRIMARY KEY,
                            project_id VARCHAR,
                            user_id VARCHAR,
                            kind VARCHAR NOT NULL,
                            content TEXT NOT NULL,
                            summary TEXT,
                            tags JSON,
                            confidence FLOAT NOT NULL DEFAULT 0.7,
                            source_type VARCHAR,
                            source_id VARCHAR,
                            agent_type VARCHAR,
                            status VARCHAR NOT NULL DEFAULT 'active',
                            extra_data JSON,
                            created_at DATETIME NOT NULL,
                            updated_at DATETIME NOT NULL,
                            last_used_at DATETIME,
                            use_count INTEGER NOT NULL DEFAULT 0
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO agent_memories (
                            id, project_id, kind, content, summary, confidence,
                            status, created_at, updated_at, use_count
                        )
                        VALUES (
                            'memory-a',
                            'project-a',
                            'workflow_decision',
                            'Default exploration depth is deep for authenticated apps.',
                            'Use deep exploration for authenticated apps.',
                            0.9,
                            'active',
                            CURRENT_TIMESTAMP,
                            CURRENT_TIMESTAMP,
                            0
                        )
                        """
                    )
                )

            db_module._run_migrations()
            db_module._run_migrations()

            inspector = inspect(db_module.engine)
            columns = {col["name"] for col in inspector.get_columns("agent_memories")}
            indexes = {idx["name"] for idx in inspector.get_indexes("agent_memories")}

            assert {
                "memory_type",
                "scope",
                "importance",
                "valid_from",
                "valid_until",
                "supersedes_id",
                "review_required",
                "last_verified_at",
            } <= columns
            assert {
                "ix_agentmemory_project_type",
                "ix_agentmemory_scope_status",
                "ix_agent_memories_memory_type",
                "ix_agent_memories_scope",
                "ix_agent_memories_supersedes_id",
            } <= indexes

            with db_module.engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT memory_type, scope, importance, review_required
                        FROM agent_memories
                        WHERE id = 'memory-a'
                        """
                    )
                ).one()

            assert row.memory_type == "procedural"
            assert row.scope == "project"
            assert row.importance == 0.5
            assert row.review_required in (False, 0)

            monkeypatch.setenv("MEMORY_ENABLED", "true")
            monkeypatch.setattr(agent_memory_module, "engine", db_module.engine)
            memories = AgentMemoryService().search(project_id="project-a", limit=10, min_confidence=0.0)

            assert [memory.id for memory in memories] == ["memory-a"]
            assert memories[0].memory_type == "procedural"

        finally:
            db_module.DATABASE_URL = original_url
            db_module.engine = original_engine

    def test_run_migrations_repairs_legacy_agent_definition_columns(self, tmp_path):
        """Legacy custom agent definition tables should match the current ORM model."""
        db_path = tmp_path / "test_agent_definitions_legacy.db"
        db_url = f"sqlite:///{db_path}"

        from sqlalchemy import inspect, text
        from sqlmodel import Session, create_engine

        import orchestrator.api.db as db_module
        from orchestrator.api.models_db import AgentDefinition

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
                        CREATE TABLE agent_definitions (
                            id VARCHAR PRIMARY KEY,
                            project_id VARCHAR,
                            name VARCHAR NOT NULL,
                            description VARCHAR NOT NULL DEFAULT '',
                            system_prompt TEXT NOT NULL,
                            model VARCHAR,
                            timeout_seconds INTEGER NOT NULL DEFAULT 1800,
                            tool_ids_json TEXT NOT NULL DEFAULT '[]',
                            status VARCHAR NOT NULL DEFAULT 'active',
                            created_at DATETIME,
                            updated_at DATETIME
                        )
                        """
                    )
                )

            db_module._run_migrations()
            db_module._run_migrations()

            inspector = inspect(db_module.engine)
            columns = {col["name"] for col in inspector.get_columns("agent_definitions")}
            indexes = {idx["name"] for idx in inspector.get_indexes("agent_definitions")}

            assert {"runtime", "model_tier", "test_data_refs_json"} <= columns
            assert "ix_agent_definitions_runtime" in indexes

            definition = AgentDefinition(
                project_id="default",
                name="Legacy schema save probe",
                description="Ensures migrated schemas accept current agent definitions.",
                system_prompt="Inspect the target and report concise QA findings.",
                runtime="claude_sdk",
                model_tier="tool_deep",
                timeout_seconds=900,
                status="active",
            )
            definition.tool_ids = ["browser_snapshot"]

            with Session(db_module.engine) as session:
                session.add(definition)
                session.commit()
                session.refresh(definition)

                saved = session.get(AgentDefinition, definition.id)
                assert saved is not None
                assert saved.runtime == "claude_sdk"
                assert saved.model_tier == "tool_deep"
                assert saved.tool_ids == ["browser_snapshot"]

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
