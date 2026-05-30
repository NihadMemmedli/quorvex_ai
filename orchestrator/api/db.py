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
    AgentDefinition,
    AgentMemory,
    AgentRun,
    AgentRunEvent,
    AgentToolDefinition,
    ApplicationMap,
    ArchiveJob,
    AutonomousAgentWorkItem,
    AutonomousApproval,
    AutonomousFinding,
    AutonomousMission,
    AutonomousMissionRun,
    AutonomousTestProposal,
    AutoPilotPhase,
    AutoPilotQuestion,
    # Auto Pilot pipeline models
    AutoPilotSession,
    AutoPilotSpecTask,
    AutoPilotTestTask,
    # AI Chat models
    ChatConversation,
    ChatMessage,
    CiAuditEvent,
    CiPipelineMapping,
    CiTestSubset,
    CiTestSubsetItem,
    CiWorkflowChangeRequest,
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
    DomainJob,
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
    MemoryInjectionEvent,
    # OpenAPI import history
    OpenApiImportHistory,
    PrChangedFile,
    PrdGenerationResult,
    PrImpactAnalysis,
    Project,
    PrQualityGateRun,
    PrSelectedTest,
    RecordingSession,
    RegressionBatch,
    RepoIndexedFile,
    RepoIndexSnapshot,
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
    TestExecutionHistory,
    TestImpactMap,
    TestPattern,
    # TestRail integration models
    TestrailCaseMapping,
    TestrailRunMapping,
    TestRun,
    WorkflowDefinition,
    WorkflowDefinitionRevision,
    WorkflowEvent,
    WorkflowNotification,
    WorkflowRun,
    WorkflowRunStep,
    WorkflowSchedule,
    WorkflowScheduleExecution,
    WorkflowStepType,
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

    with engine.begin() as conn:
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

            if "temporal_workflow_id" not in existing_columns:
                conn.execute(text("ALTER TABLE testrun ADD COLUMN temporal_workflow_id VARCHAR"))
                logger.info("Added column: testrun.temporal_workflow_id")

            if "temporal_run_id" not in existing_columns:
                conn.execute(text("ALTER TABLE testrun ADD COLUMN temporal_run_id VARCHAR"))
                logger.info("Added column: testrun.temporal_run_id")

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

            if "agentic_summary" not in existing_columns:
                if db_type == "postgresql":
                    conn.execute(text("ALTER TABLE testrun ADD COLUMN agentic_summary JSONB"))
                else:
                    conn.execute(text("ALTER TABLE testrun ADD COLUMN agentic_summary JSON"))
                logger.info("Added column: testrun.agentic_summary")

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
            if "runtime" not in agentrun_columns:
                conn.execute(text("ALTER TABLE agentrun ADD COLUMN runtime VARCHAR NOT NULL DEFAULT 'claude_sdk'"))
                logger.info("Added column: agentrun.runtime")
            if "project_id" not in agentrun_columns:
                conn.execute(text("ALTER TABLE agentrun ADD COLUMN project_id VARCHAR"))
                logger.info("Added column: agentrun.project_id")
            if "progress_json" not in agentrun_columns:
                conn.execute(text("ALTER TABLE agentrun ADD COLUMN progress_json TEXT"))
                logger.info("Added column: agentrun.progress_json")
            if "agent_task_id" not in agentrun_columns:
                conn.execute(text("ALTER TABLE agentrun ADD COLUMN agent_task_id VARCHAR"))
                logger.info("Added column: agentrun.agent_task_id")

        # Repair agent memory tables created before typed/scoped memory fields.
        if "agent_memories" in inspector.get_table_names():
            agent_memory_columns = {col["name"] for col in inspector.get_columns("agent_memories")}
            agent_memory_timestamp_type = "TIMESTAMP" if db_type == "postgresql" else "DATETIME"
            agent_memory_bool_false = "FALSE" if db_type == "postgresql" else "0"
            typed_memory_columns = {
                "memory_type": "VARCHAR NOT NULL DEFAULT 'semantic'",
                "scope": "VARCHAR NOT NULL DEFAULT 'project'",
                "importance": "FLOAT NOT NULL DEFAULT 0.5",
                "valid_from": agent_memory_timestamp_type,
                "valid_until": agent_memory_timestamp_type,
                "supersedes_id": "VARCHAR",
                "review_required": f"BOOLEAN NOT NULL DEFAULT {agent_memory_bool_false}",
                "last_verified_at": agent_memory_timestamp_type,
            }
            for column_name, column_type in typed_memory_columns.items():
                if column_name not in agent_memory_columns:
                    conn.execute(text(f"ALTER TABLE agent_memories ADD COLUMN {column_name} {column_type}"))
                    logger.info("Added column: agent_memories.%s", column_name)

            conn.execute(
                text(
                    """
                    UPDATE agent_memories
                    SET memory_type = CASE
                        WHEN kind IN ('failure_pattern') THEN 'episodic'
                        WHEN kind IN ('agent_lesson', 'workflow_decision') THEN 'procedural'
                        ELSE 'semantic'
                    END
                    WHERE memory_type IS NULL OR memory_type = 'semantic'
                    """
                )
            )
            conn.execute(
                text(
                    """
                    UPDATE agent_memories
                    SET scope = CASE
                        WHEN user_id IS NOT NULL AND user_id != '' THEN 'user'
                        WHEN project_id IS NOT NULL AND project_id != '' THEN 'project'
                        ELSE 'global'
                    END
                    WHERE scope IS NULL OR scope = 'project'
                    """
                )
            )
            conn.execute(text("UPDATE agent_memories SET importance = 0.5 WHERE importance IS NULL"))
            conn.execute(text(f"UPDATE agent_memories SET review_required = {agent_memory_bool_false} WHERE review_required IS NULL"))

            try:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_agentmemory_project_type "
                        "ON agent_memories (project_id, memory_type)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_agentmemory_scope_status "
                        "ON agent_memories (scope, status)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_agent_memories_memory_type "
                        "ON agent_memories (memory_type)"
                    )
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_memories_scope ON agent_memories (scope)"))
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_agent_memories_supersedes_id "
                        "ON agent_memories (supersedes_id)"
                    )
                )
            except Exception as e:
                logger.debug(f"Index may already exist on agent_memories: {e}")

        if "memory_injection_events" not in inspector.get_table_names():
            timestamp_type = "TIMESTAMP" if db_type == "postgresql" else "DATETIME"
            json_type = "JSONB" if db_type == "postgresql" else "JSON"
            conn.execute(
                text(f"""
                CREATE TABLE memory_injection_events (
                    id VARCHAR PRIMARY KEY,
                    project_id VARCHAR,
                    actor_type VARCHAR NOT NULL,
                    stage VARCHAR NOT NULL,
                    source_type VARCHAR,
                    source_id VARCHAR,
                    query TEXT NOT NULL DEFAULT '',
                    memory_ids_json TEXT NOT NULL DEFAULT '[]',
                    context_preview TEXT NOT NULL DEFAULT '',
                    outcome VARCHAR NOT NULL DEFAULT 'injected',
                    extra_data {json_type},
                    created_at {timestamp_type} NOT NULL
                )
                """)
            )
            logger.info("Created table: memory_injection_events")
        if "memory_injection_events" in inspector.get_table_names():
            try:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_injection_project_created "
                        "ON memory_injection_events (project_id, created_at)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_injection_stage_created "
                        "ON memory_injection_events (stage, created_at)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_injection_source "
                        "ON memory_injection_events (source_type, source_id)"
                    )
                )
            except Exception as e:
                logger.debug(f"Index may already exist on memory_injection_events: {e}")

        if "memory_graph_nodes" not in inspector.get_table_names():
            timestamp_type = "TIMESTAMP" if db_type == "postgresql" else "DATETIME"
            json_type = "JSONB" if db_type == "postgresql" else "JSON"
            conn.execute(
                text(f"""
                CREATE TABLE memory_graph_nodes (
                    id VARCHAR PRIMARY KEY,
                    project_id VARCHAR,
                    node_type VARCHAR NOT NULL,
                    label TEXT NOT NULL,
                    memory_id VARCHAR,
                    entity_key VARCHAR NOT NULL,
                    confidence FLOAT NOT NULL DEFAULT 0.7,
                    status VARCHAR NOT NULL DEFAULT 'active',
                    extra_data {json_type},
                    created_at {timestamp_type} NOT NULL,
                    updated_at {timestamp_type} NOT NULL
                )
                """)
            )
            logger.info("Created table: memory_graph_nodes")
        if "memory_graph_edges" not in inspector.get_table_names():
            timestamp_type = "TIMESTAMP" if db_type == "postgresql" else "DATETIME"
            json_type = "JSONB" if db_type == "postgresql" else "JSON"
            conn.execute(
                text(f"""
                CREATE TABLE memory_graph_edges (
                    id VARCHAR PRIMARY KEY,
                    project_id VARCHAR,
                    source_node_id VARCHAR NOT NULL,
                    target_node_id VARCHAR NOT NULL,
                    relationship_type VARCHAR NOT NULL,
                    weight FLOAT NOT NULL DEFAULT 0.7,
                    evidence_memory_id VARCHAR,
                    status VARCHAR NOT NULL DEFAULT 'active',
                    extra_data {json_type},
                    created_at {timestamp_type} NOT NULL,
                    updated_at {timestamp_type} NOT NULL
                )
                """)
            )
            logger.info("Created table: memory_graph_edges")
        try:
            graph_tables = set(inspector.get_table_names())
            if "memory_graph_nodes" in graph_tables:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_graph_node_identity "
                        "ON memory_graph_nodes (project_id, node_type, entity_key)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_graph_nodes_project_type "
                        "ON memory_graph_nodes (project_id, node_type)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_graph_nodes_project_status "
                        "ON memory_graph_nodes (project_id, status)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_graph_nodes_memory "
                        "ON memory_graph_nodes (memory_id)"
                    )
                )
            if "memory_graph_edges" in graph_tables:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_graph_edge_identity "
                        "ON memory_graph_edges (project_id, source_node_id, target_node_id, relationship_type)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_graph_edges_project_type "
                        "ON memory_graph_edges (project_id, relationship_type)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_graph_edges_source "
                        "ON memory_graph_edges (source_node_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_graph_edges_target "
                        "ON memory_graph_edges (target_node_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_graph_edges_evidence "
                        "ON memory_graph_edges (evidence_memory_id)"
                    )
                )
        except Exception as e:
            logger.debug(f"Index may already exist on memory knowledge graph: {e}")

        if "memory_feedback_events" not in inspector.get_table_names():
            timestamp_type = "TIMESTAMP" if db_type == "postgresql" else "DATETIME"
            conn.execute(
                text(f"""
                CREATE TABLE memory_feedback_events (
                    id VARCHAR PRIMARY KEY,
                    project_id VARCHAR,
                    memory_id VARCHAR NOT NULL,
                    injection_event_id VARCHAR,
                    conversation_id VARCHAR,
                    message_index INTEGER,
                    rating VARCHAR NOT NULL,
                    signal FLOAT NOT NULL DEFAULT 0.0,
                    source VARCHAR NOT NULL DEFAULT 'manual_dashboard',
                    comment TEXT,
                    user_id VARCHAR,
                    created_at {timestamp_type} NOT NULL
                )
                """)
            )
            logger.info("Created table: memory_feedback_events")
        if "memory_feedback_aggregates" not in inspector.get_table_names():
            timestamp_type = "TIMESTAMP" if db_type == "postgresql" else "DATETIME"
            conn.execute(
                text(f"""
                CREATE TABLE memory_feedback_aggregates (
                    id VARCHAR PRIMARY KEY,
                    project_id VARCHAR,
                    project_key VARCHAR NOT NULL DEFAULT '__global__',
                    memory_id VARCHAR NOT NULL,
                    positive_feedback_count INTEGER NOT NULL DEFAULT 0,
                    negative_feedback_count INTEGER NOT NULL DEFAULT 0,
                    feedback_score FLOAT NOT NULL DEFAULT 0.0,
                    last_feedback_at {timestamp_type},
                    updated_at {timestamp_type} NOT NULL
                )
                """)
            )
            logger.info("Created table: memory_feedback_aggregates")
        try:
            feedback_inspector = inspect(conn)
            feedback_tables = set(feedback_inspector.get_table_names())
            if "memory_feedback_events" in feedback_tables:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_feedback_project_created "
                        "ON memory_feedback_events (project_id, created_at)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_feedback_memory "
                        "ON memory_feedback_events (memory_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_feedback_injection "
                        "ON memory_feedback_events (injection_event_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_feedback_source "
                        "ON memory_feedback_events (source)"
                    )
                )
            if "memory_feedback_aggregates" in feedback_tables:
                feedback_aggregate_columns = {
                    col["name"] for col in feedback_inspector.get_columns("memory_feedback_aggregates")
                }
                if "project_key" not in feedback_aggregate_columns:
                    conn.execute(
                        text(
                            "ALTER TABLE memory_feedback_aggregates "
                            "ADD COLUMN project_key VARCHAR NOT NULL DEFAULT '__global__'"
                        )
                    )
                    conn.execute(
                        text(
                            "UPDATE memory_feedback_aggregates "
                            "SET project_key = COALESCE(project_id, '__global__') "
                            "WHERE project_key = '__global__'"
                        )
                    )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_feedback_aggregate_project_memory "
                        "ON memory_feedback_aggregates (project_key, memory_id)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_feedback_aggregate_project_score "
                        "ON memory_feedback_aggregates (project_id, feedback_score)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_memory_feedback_aggregate_memory "
                        "ON memory_feedback_aggregates (memory_id)"
                    )
                )
        except Exception as e:
            logger.debug(f"Index may already exist on memory feedback tables: {e}")

        # Create UI-created agent tables for databases initialized before this feature.
        if "agent_definitions" not in inspector.get_table_names():
            if db_type == "postgresql":
                conn.execute(
                    text("""
                    CREATE TABLE agent_definitions (
                        id VARCHAR PRIMARY KEY,
                        project_id VARCHAR,
                        name VARCHAR NOT NULL,
                        description VARCHAR NOT NULL DEFAULT '',
                        system_prompt TEXT NOT NULL,
                        runtime VARCHAR NOT NULL DEFAULT 'claude_sdk',
                        model VARCHAR,
                        timeout_seconds INTEGER NOT NULL DEFAULT 1800,
                        tool_ids_json TEXT NOT NULL DEFAULT '[]',
                        status VARCHAR NOT NULL DEFAULT 'active',
                        created_at TIMESTAMP,
                        updated_at TIMESTAMP
                    )
                    """)
                )
            else:
                conn.execute(
                    text("""
                    CREATE TABLE agent_definitions (
                        id VARCHAR PRIMARY KEY,
                        project_id VARCHAR,
                        name VARCHAR NOT NULL,
                        description VARCHAR NOT NULL DEFAULT '',
                        system_prompt TEXT NOT NULL,
                        runtime VARCHAR NOT NULL DEFAULT 'claude_sdk',
                        model VARCHAR,
                        timeout_seconds INTEGER NOT NULL DEFAULT 1800,
                        tool_ids_json TEXT NOT NULL DEFAULT '[]',
                        status VARCHAR NOT NULL DEFAULT 'active',
                        created_at DATETIME,
                        updated_at DATETIME
                    )
                    """)
                )
            logger.info("Created table: agent_definitions")
        else:
            agent_definition_columns = {col["name"] for col in inspector.get_columns("agent_definitions")}
            if "runtime" not in agent_definition_columns:
                conn.execute(text("ALTER TABLE agent_definitions ADD COLUMN runtime VARCHAR NOT NULL DEFAULT 'claude_sdk'"))
                logger.info("Added column: agent_definitions.runtime")

        if "agent_tool_definitions" not in inspector.get_table_names():
            if db_type == "postgresql":
                conn.execute(
                    text("""
                    CREATE TABLE agent_tool_definitions (
                        id VARCHAR PRIMARY KEY,
                        label VARCHAR NOT NULL,
                        description VARCHAR NOT NULL DEFAULT '',
                        category VARCHAR NOT NULL DEFAULT 'general',
                        tool_name VARCHAR NOT NULL,
                        risk VARCHAR NOT NULL DEFAULT 'low',
                        enabled BOOLEAN NOT NULL DEFAULT TRUE,
                        requires_mcp_server VARCHAR,
                        updated_at TIMESTAMP
                    )
                    """)
                )
            else:
                conn.execute(
                    text("""
                    CREATE TABLE agent_tool_definitions (
                        id VARCHAR PRIMARY KEY,
                        label VARCHAR NOT NULL,
                        description VARCHAR NOT NULL DEFAULT '',
                        category VARCHAR NOT NULL DEFAULT 'general',
                        tool_name VARCHAR NOT NULL,
                        risk VARCHAR NOT NULL DEFAULT 'low',
                        enabled BOOLEAN NOT NULL DEFAULT 1,
                        requires_mcp_server VARCHAR,
                        updated_at DATETIME
                    )
                    """)
                )
            logger.info("Created table: agent_tool_definitions")

        if "agent_definitions" in inspector.get_table_names():
            try:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_agent_definitions_project_status "
                        "ON agent_definitions (project_id, status)"
                    )
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_definitions_runtime ON agent_definitions (runtime)"))
            except Exception as e:
                logger.debug(f"Index may already exist on agent_definitions: {e}")

        timestamp_type = "TIMESTAMP" if db_type == "postgresql" else "DATETIME"
        boolean_false = "false" if db_type == "postgresql" else "0"
        if "workflow_definitions" not in inspector.get_table_names():
            conn.execute(
                text(f"""
                CREATE TABLE workflow_definitions (
                    id VARCHAR PRIMARY KEY,
                    project_id VARCHAR,
                    name VARCHAR NOT NULL,
                    description VARCHAR NOT NULL DEFAULT '',
                    version INTEGER NOT NULL DEFAULT 1,
                    steps_json TEXT NOT NULL DEFAULT '[]',
                    status VARCHAR NOT NULL DEFAULT 'active',
                    created_by VARCHAR,
                    created_at {timestamp_type},
                    updated_at {timestamp_type}
                )
                """)
            )
            logger.info("Created table: workflow_definitions")
        else:
            wf_cols = {col["name"] for col in inspector.get_columns("workflow_definitions")}
            if "steps_json" not in wf_cols:
                conn.execute(text("ALTER TABLE workflow_definitions ADD COLUMN steps_json TEXT NOT NULL DEFAULT '[]'"))
                if "steps" in wf_cols:
                    conn.execute(text("UPDATE workflow_definitions SET steps_json = COALESCE(CAST(steps AS TEXT), '[]')"))
                logger.info("Added column: workflow_definitions.steps_json")
            if "created_by" not in wf_cols:
                conn.execute(text("ALTER TABLE workflow_definitions ADD COLUMN created_by VARCHAR"))
                logger.info("Added column: workflow_definitions.created_by")
            if "version" not in wf_cols:
                conn.execute(text("ALTER TABLE workflow_definitions ADD COLUMN version INTEGER NOT NULL DEFAULT 1"))
                logger.info("Added column: workflow_definitions.version")

        if "workflow_runs" not in inspector.get_table_names():
            conn.execute(
                text(f"""
                CREATE TABLE workflow_runs (
                    id VARCHAR PRIMARY KEY,
                    workflow_id VARCHAR,
                    definition_id VARCHAR NOT NULL,
                    project_id VARCHAR,
                    status VARCHAR NOT NULL DEFAULT 'queued',
                    current_step_index INTEGER NOT NULL DEFAULT 0,
                    progress FLOAT NOT NULL DEFAULT 0,
                    inputs_json TEXT NOT NULL DEFAULT '{{}}',
                    context_json TEXT NOT NULL DEFAULT '{{}}',
                    result_json TEXT,
                    error_message TEXT,
                    triggered_by VARCHAR,
                    created_at {timestamp_type},
                    started_at {timestamp_type},
                    completed_at {timestamp_type},
                    updated_at {timestamp_type}
                )
                """)
            )
            logger.info("Created table: workflow_runs")
        else:
            run_cols = {col["name"] for col in inspector.get_columns("workflow_runs")}
            if "workflow_id" not in run_cols:
                conn.execute(text("ALTER TABLE workflow_runs ADD COLUMN workflow_id VARCHAR"))
                conn.execute(text("UPDATE workflow_runs SET workflow_id = definition_id WHERE workflow_id IS NULL"))
                logger.info("Added column: workflow_runs.workflow_id")
            if "definition_id" not in run_cols:
                conn.execute(text("ALTER TABLE workflow_runs ADD COLUMN definition_id VARCHAR"))
                if "workflow_id" in run_cols:
                    conn.execute(text("UPDATE workflow_runs SET definition_id = workflow_id WHERE definition_id IS NULL"))
                logger.info("Added column: workflow_runs.definition_id")
            if "progress" not in run_cols:
                conn.execute(text("ALTER TABLE workflow_runs ADD COLUMN progress FLOAT NOT NULL DEFAULT 0"))
                logger.info("Added column: workflow_runs.progress")
            if "inputs_json" not in run_cols:
                conn.execute(text("ALTER TABLE workflow_runs ADD COLUMN inputs_json TEXT NOT NULL DEFAULT '{}'"))
                if "input_data" in run_cols:
                    conn.execute(text("UPDATE workflow_runs SET inputs_json = COALESCE(CAST(input_data AS TEXT), '{}')"))
                logger.info("Added column: workflow_runs.inputs_json")
            if "context_json" not in run_cols:
                conn.execute(text("ALTER TABLE workflow_runs ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'"))
                logger.info("Added column: workflow_runs.context_json")
            if "result_json" not in run_cols:
                conn.execute(text("ALTER TABLE workflow_runs ADD COLUMN result_json TEXT"))
                if "result_data" in run_cols:
                    conn.execute(text("UPDATE workflow_runs SET result_json = CAST(result_data AS TEXT) WHERE result_data IS NOT NULL"))
                logger.info("Added column: workflow_runs.result_json")
            if "triggered_by" not in run_cols:
                conn.execute(text("ALTER TABLE workflow_runs ADD COLUMN triggered_by VARCHAR"))
                logger.info("Added column: workflow_runs.triggered_by")
            workflow_run_operation_columns = {
                "revision_id": "VARCHAR",
                "definition_version": "INTEGER NOT NULL DEFAULT 1",
                "recovery_policy_json": "TEXT NOT NULL DEFAULT '{}'",
                "trigger_type": "VARCHAR NOT NULL DEFAULT 'manual'",
                "trigger_id": "VARCHAR",
                "temporal_workflow_id": "VARCHAR",
                "temporal_run_id": "VARCHAR",
                "heartbeat_at": timestamp_type,
                "pause_reason": "VARCHAR",
            }
            for column_name, column_type in workflow_run_operation_columns.items():
                if column_name not in run_cols:
                    conn.execute(text(f"ALTER TABLE workflow_runs ADD COLUMN {column_name} {column_type}"))
                    logger.info("Added column: workflow_runs.%s", column_name)

        if "workflow_run_steps" not in inspector.get_table_names():
            bool_default = "FALSE" if db_type == "postgresql" else "0"
            pk_type = "SERIAL PRIMARY KEY" if db_type == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
            conn.execute(
                text(f"""
                CREATE TABLE workflow_run_steps (
                    id {pk_type},
                    run_id VARCHAR NOT NULL,
                    workflow_id VARCHAR,
                    definition_id VARCHAR NOT NULL,
                    step_index INTEGER NOT NULL DEFAULT 0,
                    step_order INTEGER NOT NULL,
                    step_id VARCHAR NOT NULL DEFAULT 'step',
                    step_key VARCHAR NOT NULL,
                    step_type VARCHAR NOT NULL,
                    step_type_version INTEGER NOT NULL DEFAULT 1,
                    step_config_json TEXT NOT NULL DEFAULT '{{}}',
                    name VARCHAR NOT NULL DEFAULT '',
                    label VARCHAR NOT NULL,
                    status VARCHAR NOT NULL DEFAULT 'pending',
                    continue_on_error BOOLEAN NOT NULL DEFAULT {bool_default},
                    input_json TEXT NOT NULL DEFAULT '{{}}',
                    rendered_input_json TEXT NOT NULL DEFAULT '{{}}',
                    context_snapshot_json TEXT NOT NULL DEFAULT '{{}}',
                    input_resolution_json TEXT NOT NULL DEFAULT '[]',
                    output_json TEXT,
                    output_validation_errors_json TEXT NOT NULL DEFAULT '[]',
                    error_message TEXT,
                    external_kind VARCHAR,
                    external_id VARCHAR,
                    created_at {timestamp_type},
                    started_at {timestamp_type},
                    completed_at {timestamp_type},
                    updated_at {timestamp_type}
                )
                """)
            )
            logger.info("Created table: workflow_run_steps")
        else:
            step_cols = {col["name"] for col in inspector.get_columns("workflow_run_steps")}
            if "workflow_id" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN workflow_id VARCHAR"))
                conn.execute(text("UPDATE workflow_run_steps SET workflow_id = definition_id WHERE workflow_id IS NULL"))
                logger.info("Added column: workflow_run_steps.workflow_id")
            if "definition_id" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN definition_id VARCHAR"))
                if "workflow_id" in step_cols:
                    conn.execute(text("UPDATE workflow_run_steps SET definition_id = workflow_id WHERE definition_id IS NULL"))
                logger.info("Added column: workflow_run_steps.definition_id")
            if "step_index" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN step_index INTEGER NOT NULL DEFAULT 0"))
                if "step_order" in step_cols:
                    conn.execute(text("UPDATE workflow_run_steps SET step_index = step_order"))
                logger.info("Added column: workflow_run_steps.step_index")
            if "step_order" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN step_order INTEGER NOT NULL DEFAULT 0"))
                if "step_index" in step_cols:
                    conn.execute(text("UPDATE workflow_run_steps SET step_order = step_index"))
                logger.info("Added column: workflow_run_steps.step_order")
            if "step_id" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN step_id VARCHAR NOT NULL DEFAULT 'step'"))
                if "step_key" in step_cols:
                    conn.execute(text("UPDATE workflow_run_steps SET step_id = step_key WHERE step_key IS NOT NULL"))
                logger.info("Added column: workflow_run_steps.step_id")
            if "step_key" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN step_key VARCHAR NOT NULL DEFAULT 'step'"))
                if "step_id" in step_cols:
                    conn.execute(text("UPDATE workflow_run_steps SET step_key = step_id WHERE step_id IS NOT NULL"))
                logger.info("Added column: workflow_run_steps.step_key")
            if "step_type_version" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN step_type_version INTEGER NOT NULL DEFAULT 1"))
                logger.info("Added column: workflow_run_steps.step_type_version")
            if "step_config_json" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN step_config_json TEXT NOT NULL DEFAULT '{}'"))
                logger.info("Added column: workflow_run_steps.step_config_json")
            if "name" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN name VARCHAR NOT NULL DEFAULT ''"))
                if "label" in step_cols:
                    conn.execute(text("UPDATE workflow_run_steps SET name = label WHERE label IS NOT NULL"))
                logger.info("Added column: workflow_run_steps.name")
            if "label" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN label VARCHAR NOT NULL DEFAULT ''"))
                if "name" in step_cols:
                    conn.execute(text("UPDATE workflow_run_steps SET label = name WHERE name IS NOT NULL"))
                logger.info("Added column: workflow_run_steps.label")
            if "continue_on_error" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN continue_on_error BOOLEAN NOT NULL DEFAULT FALSE"))
                logger.info("Added column: workflow_run_steps.continue_on_error")
            if "input_json" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN input_json TEXT NOT NULL DEFAULT '{}'"))
                if "input_data" in step_cols:
                    conn.execute(text("UPDATE workflow_run_steps SET input_json = COALESCE(CAST(input_data AS TEXT), '{}')"))
                logger.info("Added column: workflow_run_steps.input_json")
            if "rendered_input_json" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN rendered_input_json TEXT NOT NULL DEFAULT '{}'"))
                logger.info("Added column: workflow_run_steps.rendered_input_json")
            if "context_snapshot_json" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN context_snapshot_json TEXT NOT NULL DEFAULT '{}'"))
                logger.info("Added column: workflow_run_steps.context_snapshot_json")
            if "input_resolution_json" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN input_resolution_json TEXT NOT NULL DEFAULT '[]'"))
                logger.info("Added column: workflow_run_steps.input_resolution_json")
            if "output_json" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN output_json TEXT"))
                if "output_data" in step_cols:
                    conn.execute(text("UPDATE workflow_run_steps SET output_json = CAST(output_data AS TEXT) WHERE output_data IS NOT NULL"))
                logger.info("Added column: workflow_run_steps.output_json")
            if "output_validation_errors_json" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN output_validation_errors_json TEXT NOT NULL DEFAULT '[]'"))
                logger.info("Added column: workflow_run_steps.output_validation_errors_json")
            if "external_kind" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN external_kind VARCHAR"))
                logger.info("Added column: workflow_run_steps.external_kind")
            if "external_id" not in step_cols:
                conn.execute(text("ALTER TABLE workflow_run_steps ADD COLUMN external_id VARCHAR"))
                logger.info("Added column: workflow_run_steps.external_id")
            workflow_step_operation_columns = {
                "attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "max_attempts": "INTEGER NOT NULL DEFAULT 1",
                "retry_backoff_seconds": "INTEGER NOT NULL DEFAULT 0",
                "recovery_action": "VARCHAR NOT NULL DEFAULT 'fail'",
                "skipped_reason": "VARCHAR",
            }
            for column_name, column_type in workflow_step_operation_columns.items():
                if column_name not in step_cols:
                    conn.execute(text(f"ALTER TABLE workflow_run_steps ADD COLUMN {column_name} {column_type}"))
                    logger.info("Added column: workflow_run_steps.%s", column_name)
            if "created_at" not in step_cols:
                if db_type == "sqlite":
                    conn.execute(text(f"ALTER TABLE workflow_run_steps ADD COLUMN created_at {timestamp_type}"))
                    conn.execute(text("UPDATE workflow_run_steps SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
                else:
                    conn.execute(text(f"ALTER TABLE workflow_run_steps ADD COLUMN created_at {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP"))
                logger.info("Added column: workflow_run_steps.created_at")

        try:
            if "workflow_definitions" in inspector.get_table_names():
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_workflow_definitions_project_status "
                        "ON workflow_definitions (project_id, status)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_workflow_definitions_project_updated "
                        "ON workflow_definitions (project_id, updated_at)"
                    )
                )
            if "workflow_runs" in inspector.get_table_names():
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_workflow_runs_project_status "
                        "ON workflow_runs (project_id, status)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_workflow_runs_definition_created "
                        "ON workflow_runs (definition_id, created_at)"
                    )
                )
            if "workflow_run_steps" in inspector.get_table_names():
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_workflow_run_steps_run_order "
                        "ON workflow_run_steps (run_id, step_order)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_workflow_run_steps_external "
                        "ON workflow_run_steps (external_kind, external_id)"
                    )
                )
        except Exception as e:
            logger.debug(f"Index may already exist on workflow tables: {e}")

        if "workflow_step_types" not in inspector.get_table_names():
            conn.execute(
                text(f"""
                CREATE TABLE workflow_step_types (
                    id VARCHAR PRIMARY KEY,
                    project_id VARCHAR,
                    type VARCHAR NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    label VARCHAR NOT NULL,
                    description VARCHAR NOT NULL DEFAULT '',
                    required_json TEXT NOT NULL DEFAULT '[]',
                    input_schema_json TEXT NOT NULL DEFAULT '{{}}',
                    ui_schema_json TEXT NOT NULL DEFAULT '{{}}',
                    output_schema_json TEXT NOT NULL DEFAULT '{{}}',
                    default_input_json TEXT NOT NULL DEFAULT '{{}}',
                    category VARCHAR NOT NULL DEFAULT 'Utility',
                    risk_level VARCHAR NOT NULL DEFAULT 'low',
                    is_async BOOLEAN NOT NULL DEFAULT {boolean_false},
                    auto_wait_defaults_json TEXT NOT NULL DEFAULT '{{}}',
                    handler_kind VARCHAR NOT NULL DEFAULT 'builtin',
                    handler_config_json TEXT NOT NULL DEFAULT '{{}}',
                    status VARCHAR NOT NULL DEFAULT 'active',
                    created_at {timestamp_type},
                    updated_at {timestamp_type}
                )
                """)
            )
            logger.info("Created table: workflow_step_types")

        conn_inspector = inspect(conn)
        if "workflow_step_types" in conn_inspector.get_table_names():
            step_type_columns = {col["name"] for col in conn_inspector.get_columns("workflow_step_types")}
            if "category" not in step_type_columns:
                conn.execute(text("ALTER TABLE workflow_step_types ADD COLUMN category VARCHAR NOT NULL DEFAULT 'Utility'"))
                logger.info("Added column: workflow_step_types.category")
            if "risk_level" not in step_type_columns:
                conn.execute(text("ALTER TABLE workflow_step_types ADD COLUMN risk_level VARCHAR NOT NULL DEFAULT 'low'"))
                logger.info("Added column: workflow_step_types.risk_level")
            if "is_async" not in step_type_columns:
                conn.execute(text(f"ALTER TABLE workflow_step_types ADD COLUMN is_async BOOLEAN NOT NULL DEFAULT {boolean_false}"))
                logger.info("Added column: workflow_step_types.is_async")
            if "auto_wait_defaults_json" not in step_type_columns:
                conn.execute(text("ALTER TABLE workflow_step_types ADD COLUMN auto_wait_defaults_json TEXT NOT NULL DEFAULT '{}'"))
                logger.info("Added column: workflow_step_types.auto_wait_defaults_json")
            try:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_workflow_step_types_project_status "
                        "ON workflow_step_types (project_id, status)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_workflow_step_types_type_version "
                        "ON workflow_step_types (type, version)"
                    )
                )
            except Exception as e:
                logger.debug(f"Index may already exist on workflow_step_types: {e}")

        # Add title_embedding_json to requirements table for deduplication
        if "requirements" in inspector.get_table_names():
            req_columns = {col["name"] for col in inspector.get_columns("requirements")}
            if "title_embedding_json" not in req_columns:
                conn.execute(text("ALTER TABLE requirements ADD COLUMN title_embedding_json TEXT"))
                logger.info("Added column: requirements.title_embedding_json")
            if "canonical_key" not in req_columns:
                conn.execute(text("ALTER TABLE requirements ADD COLUMN canonical_key VARCHAR"))
                logger.info("Added column: requirements.canonical_key")
            requirement_timestamp_type = "TIMESTAMP" if db_type == "postgresql" else "DATETIME"
            requirement_truth_columns = {
                "truth_state": "VARCHAR NOT NULL DEFAULT 'candidate_requirement'",
                "source_type": "VARCHAR NOT NULL DEFAULT 'manual'",
                "confidence": "FLOAT NOT NULL DEFAULT 0.9",
                "uncertainty_reason": "TEXT",
                "confirmed_by": "VARCHAR",
                "confirmed_at": requirement_timestamp_type,
                "rejected_by": "VARCHAR",
                "rejected_at": requirement_timestamp_type,
            }
            for column_name, column_type in requirement_truth_columns.items():
                if column_name not in req_columns:
                    conn.execute(text(f"ALTER TABLE requirements ADD COLUMN {column_name} {column_type}"))
                    logger.info("Added column: requirements.%s", column_name)
            try:
                conn.execute(
                    text(
                        """
                        UPDATE requirements
                        SET truth_state = CASE
                            WHEN status IN ('approved', 'implemented', 'tested', 'confirmed') THEN 'confirmed_requirement'
                            WHEN status IN ('rejected') THEN 'rejected_requirement'
                            WHEN source_session_id IS NOT NULL THEN 'candidate_requirement'
                            ELSE truth_state
                        END
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        UPDATE requirements
                        SET source_type = CASE
                            WHEN source_session_id IS NOT NULL THEN 'exploration'
                            WHEN truth_state = 'confirmed_requirement' THEN 'human_approval'
                            ELSE source_type
                        END
                        """
                    )
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_requirements_truth_state ON requirements (truth_state)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_requirements_source_type ON requirements (source_type)"))
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_requirements_project_canonical "
                        "ON requirements (project_id, canonical_key)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_requirements_project_canonical "
                        "ON requirements (project_id, canonical_key)"
                    )
                )
            except Exception as e:
                logger.debug(f"Requirement truth-state migration note: {e}")

        if "rtm_entries" in inspector.get_table_names():
            rtm_columns = {col["name"] for col in inspector.get_columns("rtm_entries")}
            if "dedupe_key" not in rtm_columns:
                conn.execute(text("ALTER TABLE rtm_entries ADD COLUMN dedupe_key VARCHAR"))
                logger.info("Added column: rtm_entries.dedupe_key")
            try:
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_rtm_entries_project_dedupe ON rtm_entries (project_id, dedupe_key)")
                )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_rtm_entries_project_dedupe "
                        "ON rtm_entries (project_id, dedupe_key)"
                    )
                )
            except Exception as e:
                logger.debug(f"RTM dedupe migration note: {e}")

        if "application_map" in inspector.get_table_names():
            app_map_columns = {col["name"] for col in inspector.get_columns("application_map")}
            if "project_id" not in app_map_columns:
                conn.execute(text("ALTER TABLE application_map ADD COLUMN project_id VARCHAR"))
                logger.info("Added column: application_map.project_id")
            if "app_surface_key" not in app_map_columns:
                conn.execute(text("ALTER TABLE application_map ADD COLUMN app_surface_key VARCHAR"))
                logger.info("Added column: application_map.app_surface_key")
            try:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_application_map_project_surface "
                        "ON application_map (project_id, app_surface_key)"
                    )
                )
            except Exception as e:
                logger.debug(f"Application map index migration note: {e}")

        if "autonomous_agent_work_items" in inspector.get_table_names():
            work_item_columns = {col["name"] for col in inspector.get_columns("autonomous_agent_work_items")}
            timestamp_type = "TIMESTAMP" if db_type == "postgresql" else "DATETIME"
            work_item_columns_to_add = {
                "planner_key": "VARCHAR",
                "lease_until": timestamp_type,
                "last_heartbeat_at": timestamp_type,
                "recovery_count": "INTEGER NOT NULL DEFAULT 0",
                "recovery_reason": "TEXT",
            }
            for column_name, column_type in work_item_columns_to_add.items():
                if column_name not in work_item_columns:
                    conn.execute(text(f"ALTER TABLE autonomous_agent_work_items ADD COLUMN {column_name} {column_type}"))
                    logger.info("Added column: autonomous_agent_work_items.%s", column_name)
            try:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_autonomous_work_items_mission_planner "
                        "ON autonomous_agent_work_items (mission_id, planner_key)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_autonomous_work_items_mission_lease "
                        "ON autonomous_agent_work_items (mission_id, lease_until)"
                    )
                )
            except Exception as e:
                logger.debug(f"Autonomous work item planner migration note: {e}")

        if "autonomous_test_proposals" in inspector.get_table_names():
            proposal_columns = {col["name"] for col in inspector.get_columns("autonomous_test_proposals")}
            timestamp_type = "TIMESTAMP" if db_type == "postgresql" else "DATETIME"
            proposal_columns_to_add = {
                "validation_status": "VARCHAR NOT NULL DEFAULT 'not_run'",
                "validation_result_json": "TEXT",
                "validation_artifacts_json": "TEXT NOT NULL DEFAULT '[]'",
                "validation_log_path": "VARCHAR",
                "validation_trace_path": "VARCHAR",
                "validated_at": timestamp_type,
            }
            for column_name, column_type in proposal_columns_to_add.items():
                if column_name not in proposal_columns:
                    conn.execute(text(f"ALTER TABLE autonomous_test_proposals ADD COLUMN {column_name} {column_type}"))
                    logger.info("Added column: autonomous_test_proposals.%s", column_name)
            try:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_autonomous_test_proposals_validation_status "
                        "ON autonomous_test_proposals (validation_status)"
                    )
                )
            except Exception as e:
                logger.debug(f"Autonomous proposal validation migration note: {e}")

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

        timestamp_type = "TIMESTAMP" if db_type == "postgresql" else "DATETIME"

        if "agentrun" in inspector.get_table_names():
            agentrun_columns = {col["name"] for col in inspector.get_columns("agentrun")}
            agentrun_columns_to_add = {
                "temporal_workflow_id": "VARCHAR",
                "temporal_run_id": "VARCHAR",
                "started_at": timestamp_type,
                "completed_at": timestamp_type,
            }
            for column_name, column_type in agentrun_columns_to_add.items():
                if column_name not in agentrun_columns:
                    conn.execute(text(f"ALTER TABLE agentrun ADD COLUMN {column_name} {column_type}"))
                    logger.info("Added column: agentrun.%s", column_name)
            try:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_agentrun_temporal_workflow_id "
                        "ON agentrun (temporal_workflow_id)"
                    )
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_agentrun_runtime ON agentrun (runtime)"))
            except Exception as e:
                logger.debug(f"Index may already exist on agentrun temporal workflow id: {e}")

        if "autopilot_sessions" in inspector.get_table_names():
            autopilot_columns = {col["name"] for col in inspector.get_columns("autopilot_sessions")}
            for column_name in ("temporal_workflow_id", "temporal_run_id"):
                if column_name not in autopilot_columns:
                    conn.execute(text(f"ALTER TABLE autopilot_sessions ADD COLUMN {column_name} VARCHAR"))
                    logger.info("Added column: autopilot_sessions.%s", column_name)
            try:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_autopilot_sessions_temporal_workflow_id "
                        "ON autopilot_sessions (temporal_workflow_id)"
                    )
                )
            except Exception as e:
                logger.debug(f"Index may already exist on autopilot temporal workflow id: {e}")

        if "agentrun" in inspector.get_table_names() and "agent_run_events" not in inspector.get_table_names():
            conn.execute(
                text(
                    f"""
                    CREATE TABLE agent_run_events (
                        id VARCHAR PRIMARY KEY,
                        project_id VARCHAR,
                        run_id VARCHAR NOT NULL,
                        agent_task_id VARCHAR,
                        temporal_workflow_id VARCHAR,
                        temporal_run_id VARCHAR,
                        sequence INTEGER NOT NULL,
                        event_type VARCHAR NOT NULL,
                        level VARCHAR NOT NULL DEFAULT 'info',
                        message TEXT NOT NULL,
                        payload_json TEXT NOT NULL DEFAULT '{{}}',
                        created_at {timestamp_type} NOT NULL
                    )
                    """
                )
            )
            logger.info("Created table: agent_run_events")

        if "agent_run_events" in inspector.get_table_names():
            for index_sql in (
                "CREATE INDEX IF NOT EXISTS ix_agent_run_events_run_sequence ON agent_run_events (run_id, sequence)",
                "CREATE INDEX IF NOT EXISTS ix_agent_run_events_project_created ON agent_run_events (project_id, created_at)",
                "CREATE INDEX IF NOT EXISTS ix_agent_run_events_agent_task ON agent_run_events (agent_task_id)",
                "CREATE INDEX IF NOT EXISTS ix_agent_run_events_temporal_workflow ON agent_run_events (temporal_workflow_id)",
            ):
                try:
                    conn.execute(text(index_sql))
                except Exception as e:
                    logger.debug(f"Index may already exist on agent_run_events: {e}")

        if "autonomous_missions" in inspector.get_table_names():
            mission_columns = {col["name"] for col in inspector.get_columns("autonomous_missions")}
            if "health_status" not in mission_columns:
                conn.execute(
                    text("ALTER TABLE autonomous_missions ADD COLUMN health_status VARCHAR NOT NULL DEFAULT 'healthy'")
                )
                logger.info("Added column: autonomous_missions.health_status")
            if "paused_reason" not in mission_columns:
                conn.execute(text("ALTER TABLE autonomous_missions ADD COLUMN paused_reason VARCHAR"))
                logger.info("Added column: autonomous_missions.paused_reason")
            if "consecutive_failures" not in mission_columns:
                conn.execute(
                    text("ALTER TABLE autonomous_missions ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0")
                )
                logger.info("Added column: autonomous_missions.consecutive_failures")
            if "last_heartbeat_at" not in mission_columns:
                conn.execute(
                    text(f"ALTER TABLE autonomous_missions ADD COLUMN last_heartbeat_at {timestamp_type}")
                )
                logger.info("Added column: autonomous_missions.last_heartbeat_at")
            if "current_stage" not in mission_columns:
                conn.execute(text("ALTER TABLE autonomous_missions ADD COLUMN current_stage VARCHAR"))
                logger.info("Added column: autonomous_missions.current_stage")
            if "next_action" not in mission_columns:
                conn.execute(text("ALTER TABLE autonomous_missions ADD COLUMN next_action VARCHAR"))
                logger.info("Added column: autonomous_missions.next_action")

            try:
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_autonomous_missions_health_status "
                        "ON autonomous_missions (health_status)"
                    )
                )
            except Exception as e:
                logger.debug(f"Index may already exist on autonomous_missions: {e}")

        if "autonomous_mission_runs" in inspector.get_table_names():
            run_columns = {col["name"] for col in inspector.get_columns("autonomous_mission_runs")}
            if "checkpoint_json" not in run_columns:
                conn.execute(
                    text("ALTER TABLE autonomous_mission_runs ADD COLUMN checkpoint_json TEXT NOT NULL DEFAULT '{}'")
                )
                logger.info("Added column: autonomous_mission_runs.checkpoint_json")

        if "autonomous_agent_events" not in inspector.get_table_names() and "autonomous_missions" in inspector.get_table_names():
            conn.execute(
                text(
                    f"""
                    CREATE TABLE autonomous_agent_events (
                        id VARCHAR PRIMARY KEY,
                        project_id VARCHAR,
                        mission_id VARCHAR NOT NULL,
                        run_id VARCHAR,
                        work_item_id VARCHAR,
                        agent_task_id VARCHAR,
                        sequence INTEGER NOT NULL,
                        event_type VARCHAR NOT NULL,
                        level VARCHAR NOT NULL DEFAULT 'info',
                        message TEXT NOT NULL,
                        payload_json TEXT NOT NULL DEFAULT '{{}}',
                        created_at {timestamp_type} NOT NULL
                    )
                    """
                )
            )
            logger.info("Created table: autonomous_agent_events")

        if "autonomous_agent_events" in inspector.get_table_names():
            for index_sql in (
                "CREATE INDEX IF NOT EXISTS ix_autonomous_agent_events_mission_sequence ON autonomous_agent_events (mission_id, sequence)",
                "CREATE INDEX IF NOT EXISTS ix_autonomous_agent_events_work_item_sequence ON autonomous_agent_events (work_item_id, sequence)",
                "CREATE INDEX IF NOT EXISTS ix_autonomous_agent_events_project_created ON autonomous_agent_events (project_id, created_at)",
                "CREATE INDEX IF NOT EXISTS ix_autonomous_agent_events_agent_task ON autonomous_agent_events (agent_task_id)",
            ):
                try:
                    conn.execute(text(index_sql))
                except Exception as e:
                    logger.debug(f"Index may already exist on autonomous_agent_events: {e}")

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

        # ===== GitHub PR Quality Gates =====
        if "pr_quality_gate_runs" not in inspector.get_table_names():
            timestamp_type = "TIMESTAMP" if db_type == "postgresql" else "DATETIME"
            bool_true = "TRUE" if db_type == "postgresql" else "1"
            conn.execute(
                text(f"""
                CREATE TABLE pr_quality_gate_runs (
                    id VARCHAR PRIMARY KEY,
                    project_id VARCHAR,
                    provider VARCHAR NOT NULL DEFAULT 'github',
                    owner VARCHAR NOT NULL,
                    repo VARCHAR NOT NULL,
                    pr_number INTEGER NOT NULL,
                    head_sha VARCHAR NOT NULL,
                    analysis_id VARCHAR,
                    batch_id VARCHAR,
                    status VARCHAR NOT NULL DEFAULT 'initializing',
                    github_state VARCHAR NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    post_feedback BOOLEAN NOT NULL DEFAULT {bool_true},
                    create_commit_status BOOLEAN NOT NULL DEFAULT {bool_true},
                    feedback_comment_id VARCHAR,
                    feedback_comment_url VARCHAR,
                    commit_status_url VARCHAR,
                    last_feedback_state VARCHAR,
                    feedback_errors_json TEXT NOT NULL DEFAULT '[]',
                    final_feedback_published_at {timestamp_type},
                    created_at {timestamp_type},
                    updated_at {timestamp_type},
                    completed_at {timestamp_type},
                    CONSTRAINT uq_pr_quality_gate_identity UNIQUE (
                        project_id, provider, owner, repo, pr_number, head_sha
                    )
                )
                """)
            )
            logger.info("Created table: pr_quality_gate_runs")
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_pr_quality_gate_project_pr_sha "
                    "ON pr_quality_gate_runs (project_id, pr_number, head_sha)"
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_pr_quality_gate_batch ON pr_quality_gate_runs (batch_id)"))
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_pr_quality_gate_status_updated "
                    "ON pr_quality_gate_runs (status, updated_at)"
                )
            )

        if "pr_quality_gate_runs" in inspector.get_table_names():
            try:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_pr_quality_gate_identity_idx "
                        "ON pr_quality_gate_runs (project_id, provider, owner, repo, pr_number, head_sha)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_pr_quality_gate_project_pr_sha "
                        "ON pr_quality_gate_runs (project_id, pr_number, head_sha)"
                    )
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_pr_quality_gate_batch ON pr_quality_gate_runs (batch_id)"))
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_pr_quality_gate_status_updated "
                        "ON pr_quality_gate_runs (status, updated_at)"
                    )
                )
            except Exception as e:
                logger.debug(f"Index may already exist on pr_quality_gate_runs: {e}")

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


def _build_alembic_config():
    from alembic.config import Config

    project_root = Path(__file__).resolve().parent.parent.parent
    alembic_cfg = Config(str(project_root / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    return alembic_cfg


def _stamp_alembic_head():
    from alembic import command

    command.stamp(_build_alembic_config(), "head")
    logger.info("Alembic version stamped to head after legacy schema sync.")


def _get_alembic_version() -> str | None:
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import SQLAlchemyError

    inspector = inspect(engine)
    if "alembic_version" not in inspector.get_table_names():
        return None
    try:
        with engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()
    except SQLAlchemyError as exc:
        logger.warning(f"Could not read Alembic version: {exc}")
        return None


def _has_alembic_version_table() -> bool:
    from sqlalchemy import inspect

    return "alembic_version" in inspect(engine).get_table_names()


def _has_empty_alembic_version() -> bool:
    return _has_alembic_version_table() and _get_alembic_version() is None


def _required_workflow_schema_present() -> bool:
    """Return True when legacy sync has already created workflow schema expected by head."""
    from sqlalchemy import inspect

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    required_tables = {
        "workflow_definitions",
        "workflow_definition_revisions",
        "workflow_runs",
        "workflow_run_steps",
        "workflow_schedules",
        "workflow_events",
    }
    if not required_tables.issubset(tables):
        return False

    required_columns = {
        "workflow_schedules": {"revision_mode"},
        "workflow_runs": {"temporal_workflow_id", "temporal_run_id", "heartbeat_at", "pause_reason"},
        "workflow_run_steps": {"attempt_count", "recovery_action", "rendered_input_json", "context_snapshot_json"},
        "workflow_events": {"schedule_id", "payload_json"},
    }
    for table, columns in required_columns.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        if not columns.issubset(existing):
            return False
    return True


def _has_legacy_alembic_drift() -> bool:
    """Detect databases stamped at 001 after schema was already partially migrated."""
    from sqlalchemy import inspect

    version = _get_alembic_version()
    if version is None and _has_alembic_version_table() and _required_workflow_schema_present():
        return True
    if version != "001":
        return False

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "testrun" in tables:
        testrun_indexes = {idx["name"] for idx in inspector.get_indexes("testrun")}
        if "ix_testrun_spec_name" in testrun_indexes:
            return True

    post_baseline_tables = {
        "agent_memories",
        "autonomous_missions",
        "ci_pipeline_mappings",
        "openapi_import_history",
        "workflow_definitions",
    }
    return bool(tables & post_baseline_tables)


def _run_alembic_migrations() -> bool:
    """Run Alembic migrations for PostgreSQL databases.

    For fresh databases: runs all migrations from scratch.
    For existing databases: stamps current revision if alembic_version
    table doesn't exist, then upgrades to head.

    Returns True when startup must run the legacy sync path and stamp head
    afterwards, because the database was baseline-stamped after later schema
    objects had already been created.
    """
    from alembic import command
    from sqlalchemy import inspect

    alembic_cfg = _build_alembic_config()

    inspector = inspect(engine)
    tables = inspector.get_table_names()

    if "alembic_version" not in tables and len(tables) > 0:
        # Existing database without Alembic - stamp current revision
        logger.info("Existing database detected, stamping Alembic baseline (001)...")
        command.stamp(alembic_cfg, "001")
        logger.info("Alembic baseline stamped. Future migrations will run normally.")
        return _has_legacy_alembic_drift()

    if _has_empty_alembic_version() and _required_workflow_schema_present():
        logger.warning(
            "Alembic version table exists but has no version row, and workflow schema is already present. "
            "Skipping normal upgrade so legacy schema sync can stamp head without replaying baseline migrations."
        )
        return True

    if _has_legacy_alembic_drift():
        logger.warning(
            "Alembic is stamped at 001, but post-baseline schema objects already exist. "
            "Skipping normal upgrade so legacy schema sync can repair drift before stamping head."
        )
        return True

    # Fresh database or already using Alembic - run all pending migrations
    logger.info("Running Alembic migrations to head...")
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic migrations complete.")
    return False


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
        should_stamp_head_after_sync = False
        try:
            should_stamp_head_after_sync = _run_alembic_migrations()
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
        if should_stamp_head_after_sync:
            _stamp_alembic_head()
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
        if _has_empty_alembic_version() and _required_workflow_schema_present():
            _stamp_alembic_head()

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
