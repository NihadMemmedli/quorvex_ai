"""Initial schema - captures all existing tables.

This migration represents the baseline schema. For existing databases,
stamp this revision without running it: alembic stamp 001

Revision ID: 001
Revises: None
Create Date: 2026-02-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Projects (must be first - many FKs reference this)
    op.create_table(
        "projects",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_active", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_name", "projects", ["name"], unique=True)

    # Users
    op.create_table(
        "users",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_login", sa.DateTime(), nullable=True),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # Refresh tokens
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("device_info", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("replaced_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    # Project members
    op.create_table(
        "project_members",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="member"),
        sa.Column("granted_by", sa.String(), nullable=True),
        sa.Column("granted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_members_project_id", "project_members", ["project_id"])
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])

    # Execution settings
    op.create_table(
        "execution_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("parallelism", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("parallel_mode_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("headless_in_parallel", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Regression batches
    op.create_table(
        "regression_batches",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("triggered_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("browser", sa.String(), nullable=False, server_default="chromium"),
        sa.Column("tags_used_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("hybrid_mode", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("total_tests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stopped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("running", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("queued", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_regression_batches_project_id", "regression_batches", ["project_id"])

    # Test runs
    op.create_table(
        "testrun",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("spec_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("test_name", sa.String(), nullable=True),
        sa.Column("steps_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("browser", sa.String(), nullable=False, server_default="chromium"),
        sa.Column("queue_position", sa.Integer(), nullable=True),
        sa.Column("queued_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("batch_id", sa.String(), nullable=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("current_stage", sa.String(), nullable=True),
        sa.Column("stage_started_at", sa.DateTime(), nullable=True),
        sa.Column("stage_message", sa.String(), nullable=True),
        sa.Column("healing_attempt", sa.Integer(), nullable=True),
        sa.Column("triggered_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["regression_batches.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_testrun_batch_id", "testrun", ["batch_id"])
    op.create_index("ix_testrun_project_id", "testrun", ["project_id"])
    op.create_index("ix_testrun_created_at", "testrun", ["created_at"])
    op.create_index("ix_testrun_project_date", "testrun", ["project_id", "created_at"])
    op.create_index("ix_testrun_status_date", "testrun", ["status", "created_at"])

    # Spec metadata
    op.create_table(
        "specmetadata",
        sa.Column("spec_name", sa.String(), nullable=False),
        sa.Column("tags_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("last_modified", sa.DateTime(), nullable=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("last_modified_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("spec_name"),
    )
    op.create_index("ix_specmetadata_project_id", "specmetadata", ["project_id"])

    # Agent runs
    op.create_table(
        "agentrun",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("agent_type", sa.String(), nullable=False),
        sa.Column("config_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("result_json", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agentrun_project_id", "agentrun", ["project_id"])

    # Coverage metrics
    op.create_table(
        "coverage_metrics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("metric_type", sa.String(), nullable=False),
        sa.Column("metric_name", sa.String(), nullable=False),
        sa.Column("covered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("percentage", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("extra_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["testrun.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_coverage_metrics_metric_type", "coverage_metrics", ["metric_type"])

    # Discovered elements
    op.create_table(
        "discovered_elements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("selector_type", sa.String(), nullable=False),
        sa.Column("selector_value", sa.String(), nullable=False),
        sa.Column("element_type", sa.String(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("first_seen", sa.DateTime(), nullable=True),
        sa.Column("last_seen", sa.DateTime(), nullable=True),
        sa.Column("test_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_discovered_elements_url", "discovered_elements", ["url"])

    # Test patterns
    op.create_table(
        "test_patterns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pattern_hash", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("selector_type", sa.String(), nullable=False),
        sa.Column("selector_template", sa.String(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_duration", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_test_patterns_pattern_hash", "test_patterns", ["pattern_hash"], unique=True)

    # Coverage gaps
    op.create_table(
        "coverage_gaps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("gap_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False, server_default="medium"),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("suggested_test", sa.String(), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("extra_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Application map
    op.create_table(
        "application_map",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("page_title", sa.String(), nullable=True),
        sa.Column("linked_urls", sa.JSON(), nullable=True),
        sa.Column("elements", sa.JSON(), nullable=True),
        sa.Column("forms", sa.JSON(), nullable=True),
        sa.Column("api_endpoints", sa.JSON(), nullable=True),
        sa.Column("last_crawled", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_application_map_url", "application_map", ["url"], unique=True)

    # Exploration sessions
    op.create_table(
        "exploration_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("entry_url", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("strategy", sa.String(), nullable=False, server_default="goal_directed"),
        sa.Column("config_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("pages_discovered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("flows_discovered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("elements_discovered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("api_endpoints_discovered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_exploration_sessions_project_id", "exploration_sessions", ["project_id"])

    # Discovered transitions
    op.create_table(
        "discovered_transitions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("before_url", sa.String(), nullable=False),
        sa.Column("before_page_type", sa.String(), nullable=True),
        sa.Column("before_snapshot_ref", sa.String(), nullable=True),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("action_target_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("action_value", sa.String(), nullable=True),
        sa.Column("after_url", sa.String(), nullable=False),
        sa.Column("after_page_type", sa.String(), nullable=True),
        sa.Column("after_snapshot_ref", sa.String(), nullable=True),
        sa.Column("transition_type", sa.String(), nullable=False),
        sa.Column("api_calls_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("changes_description", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["exploration_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_discovered_transitions_session_id", "discovered_transitions", ["session_id"])

    # Discovered flows
    op.create_table(
        "discovered_flows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("flow_name", sa.String(), nullable=False),
        sa.Column("flow_category", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("start_url", sa.String(), nullable=False),
        sa.Column("end_url", sa.String(), nullable=False),
        sa.Column("step_count", sa.Integer(), nullable=False),
        sa.Column("is_success_path", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("preconditions_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("postconditions_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["exploration_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_discovered_flows_session_id", "discovered_flows", ["session_id"])
    op.create_index("ix_discovered_flows_project_id", "discovered_flows", ["project_id"])

    # Flow steps
    op.create_table(
        "flow_steps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("flow_id", sa.Integer(), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("transition_id", sa.Integer(), nullable=True),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("action_description", sa.String(), nullable=False),
        sa.Column("element_ref", sa.String(), nullable=True),
        sa.Column("element_role", sa.String(), nullable=True),
        sa.Column("element_name", sa.String(), nullable=True),
        sa.Column("value", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["flow_id"], ["discovered_flows.id"]),
        sa.ForeignKeyConstraint(["transition_id"], ["discovered_transitions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_flow_steps_flow_id", "flow_steps", ["flow_id"])

    # Discovered API endpoints
    op.create_table(
        "discovered_api_endpoints",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("request_headers_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("request_body_sample", sa.String(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body_sample", sa.String(), nullable=True),
        sa.Column("triggered_by_action", sa.String(), nullable=True),
        sa.Column("first_seen", sa.DateTime(), nullable=True),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["exploration_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_discovered_api_endpoints_session_id", "discovered_api_endpoints", ["session_id"])
    op.create_index("ix_discovered_api_endpoints_project_id", "discovered_api_endpoints", ["project_id"])
    op.create_index("ix_discovered_api_endpoints_url", "discovered_api_endpoints", ["url"])

    # Requirements
    op.create_table(
        "requirements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("req_code", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("acceptance_criteria_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("title_embedding_json", sa.Text(), nullable=True),
        sa.Column("source_session_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("last_modified_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["source_session_id"], ["exploration_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_requirements_project_id", "requirements", ["project_id"])
    op.create_index("ix_requirements_req_code", "requirements", ["req_code"])

    # Requirement sources
    op.create_table(
        "requirement_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("requirement_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.ForeignKeyConstraint(["requirement_id"], ["requirements.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_requirement_sources_requirement_id", "requirement_sources", ["requirement_id"])

    # RTM entries
    op.create_table(
        "rtm_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("requirement_id", sa.Integer(), nullable=False),
        sa.Column("test_spec_name", sa.String(), nullable=False),
        sa.Column("test_spec_path", sa.String(), nullable=True),
        sa.Column("mapping_type", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("coverage_notes", sa.String(), nullable=True),
        sa.Column("gap_notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["requirement_id"], ["requirements.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rtm_entries_project_id", "rtm_entries", ["project_id"])
    op.create_index("ix_rtm_entries_requirement_id", "rtm_entries", ["requirement_id"])

    # RTM snapshots
    op.create_table(
        "rtm_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("snapshot_name", sa.String(), nullable=True),
        sa.Column("total_requirements", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("covered_requirements", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("partial_requirements", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uncovered_requirements", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coverage_percentage", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("snapshot_data_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rtm_snapshots_project_id", "rtm_snapshots", ["project_id"])

    # PRD generation results
    op.create_table(
        "prd_generation_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("prd_project", sa.String(), nullable=False),
        sa.Column("feature_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("current_stage", sa.String(), nullable=True),
        sa.Column("stage_message", sa.String(), nullable=True),
        sa.Column("spec_path", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("log_path", sa.String(), nullable=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prd_generation_results_prd_project", "prd_generation_results", ["prd_project"])
    op.create_index("ix_prd_generation_results_feature_name", "prd_generation_results", ["feature_name"])

    # Run artifacts
    op.create_table(
        "run_artifacts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column("artifact_name", sa.String(), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("storage_type", sa.String(), nullable=False, server_default="local"),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("extra_data_json", sa.String(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_run_artifacts_run_id", "run_artifacts", ["run_id"])
    op.create_index("ix_run_artifacts_type", "run_artifacts", ["artifact_type"])
    op.create_index("ix_run_artifacts_storage", "run_artifacts", ["storage_type"])
    op.create_index("ix_run_artifacts_expires", "run_artifacts", ["expires_at"])

    # Archive jobs
    op.create_table(
        "archive_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_type", sa.String(), nullable=False, server_default="archival"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("artifacts_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("artifacts_archived", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("artifacts_deleted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bytes_archived", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bytes_freed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("error_details_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("config_json", sa.String(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_archive_jobs_status", "archive_jobs", ["status"])
    op.create_index("ix_archive_jobs_created", "archive_jobs", ["created_at"])

    # Storage stats
    op.create_table(
        "storage_stats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=True),
        sa.Column("postgres_size_mb", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("testrun_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runs_dir_size_mb", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("runs_dir_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("specs_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tests_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("minio_backups_size_mb", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("minio_backups_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("minio_artifacts_size_mb", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("minio_artifacts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_backup_at", sa.DateTime(), nullable=True),
        sa.Column("backup_age_hours", sa.Float(), nullable=True),
        sa.Column("minio_connected", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("postgres_connected", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("alerts_json", sa.String(), nullable=False, server_default="[]"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_storage_stats_recorded", "storage_stats", ["recorded_at"])

    # TestRail case mappings
    op.create_table(
        "testrail_case_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("spec_name", sa.String(), nullable=False),
        sa.Column("testrail_case_id", sa.Integer(), nullable=False),
        sa.Column("testrail_suite_id", sa.Integer(), nullable=False),
        sa.Column("testrail_section_id", sa.Integer(), nullable=False),
        sa.Column("testrail_project_id", sa.Integer(), nullable=False),
        sa.Column("sync_direction", sa.String(), nullable=False, server_default="push"),
        sa.Column("last_pushed_at", sa.DateTime(), nullable=True),
        sa.Column("last_pulled_at", sa.DateTime(), nullable=True),
        sa.Column("local_hash", sa.String(), nullable=True),
        sa.Column("remote_hash", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_testrail_case_mappings_project_id", "testrail_case_mappings", ["project_id"])
    op.create_index("ix_testrail_case_mappings_spec_name", "testrail_case_mappings", ["spec_name"])
    op.create_index(
        "ix_testrail_case_unique",
        "testrail_case_mappings",
        ["project_id", "spec_name", "testrail_suite_id"],
        unique=True,
    )

    # TestRail run mappings
    op.create_table(
        "testrail_run_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("batch_id", sa.String(), nullable=False),
        sa.Column("testrail_run_id", sa.Integer(), nullable=False),
        sa.Column("testrail_project_id", sa.Integer(), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("results_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_testrail_run_mappings_project_id", "testrail_run_mappings", ["project_id"])
    op.create_index("ix_testrail_run_mappings_batch_id", "testrail_run_mappings", ["batch_id"])
    op.create_index(
        "ix_testrail_run_unique",
        "testrail_run_mappings",
        ["project_id", "batch_id", "testrail_run_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("testrail_run_mappings")
    op.drop_table("testrail_case_mappings")
    op.drop_table("storage_stats")
    op.drop_table("archive_jobs")
    op.drop_table("run_artifacts")
    op.drop_table("prd_generation_results")
    op.drop_table("rtm_snapshots")
    op.drop_table("rtm_entries")
    op.drop_table("requirement_sources")
    op.drop_table("requirements")
    op.drop_table("discovered_api_endpoints")
    op.drop_table("flow_steps")
    op.drop_table("discovered_flows")
    op.drop_table("discovered_transitions")
    op.drop_table("exploration_sessions")
    op.drop_table("application_map")
    op.drop_table("coverage_gaps")
    op.drop_table("test_patterns")
    op.drop_table("discovered_elements")
    op.drop_table("coverage_metrics")
    op.drop_table("agentrun")
    op.drop_table("specmetadata")
    op.drop_table("testrun")
    op.drop_table("regression_batches")
    op.drop_table("execution_settings")
    op.drop_table("project_members")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    op.drop_table("projects")
