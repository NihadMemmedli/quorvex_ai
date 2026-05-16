"""Add PR test advisor tables.

Revision ID: 009
Revises: 008
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pr_impact_analyses",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False, server_default="github"),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("base_ref", sa.String(), nullable=True),
        sa.Column("head_ref", sa.String(), nullable=True),
        sa.Column("head_sha", sa.String(), nullable=True),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="completed"),
        sa.Column("risk_level", sa.String(), nullable=False, server_default="medium"),
        sa.Column("confidence", sa.String(), nullable=False, server_default="medium"),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("fallback_reason", sa.String(), nullable=True),
        sa.Column("ai_notes", sa.String(), nullable=True),
        sa.Column("changed_files_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("selected_tests_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_candidate_tests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("saved_tests_count", sa.Integer(), nullable=True),
        sa.Column("category_summary", sa.JSON(), nullable=True),
        sa.Column("batch_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_pr_impact_project_created", "pr_impact_analyses", ["project_id", "created_at"])
    op.create_index("ix_pr_impact_project_pr", "pr_impact_analyses", ["project_id", "pr_number"])
    op.create_index("ix_pr_impact_analyses_provider", "pr_impact_analyses", ["provider"])
    op.create_index("ix_pr_impact_analyses_project_id", "pr_impact_analyses", ["project_id"])
    op.create_index("ix_pr_impact_analyses_pr_number", "pr_impact_analyses", ["pr_number"])

    op.create_table(
        "pr_changed_files",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("analysis_id", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="modified"),
        sa.Column("additions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deletions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("changes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("previous_filename", sa.String(), nullable=True),
        sa.Column("area", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("risk_level", sa.String(), nullable=False, server_default="medium"),
        sa.Column("reason", sa.String(), nullable=True),
    )
    op.create_index("ix_pr_changed_analysis", "pr_changed_files", ["analysis_id"])
    op.create_index("ix_pr_changed_path", "pr_changed_files", ["path"])
    op.create_index("ix_pr_changed_files_analysis_id", "pr_changed_files", ["analysis_id"])

    op.create_table(
        "pr_selected_tests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("analysis_id", sa.String(), nullable=False),
        sa.Column("spec_name", sa.String(), nullable=False),
        sa.Column("test_path", sa.String(), nullable=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("confidence", sa.String(), nullable=False, server_default="medium"),
        sa.Column("risk_level", sa.String(), nullable=False, server_default="medium"),
        sa.Column("selection_source", sa.String(), nullable=False, server_default="rule"),
        sa.Column("estimated_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("categories", sa.JSON(), nullable=True),
    )
    op.create_index("ix_pr_selected_analysis", "pr_selected_tests", ["analysis_id"])
    op.create_index("ix_pr_selected_spec", "pr_selected_tests", ["spec_name"])
    op.create_index("ix_pr_selected_tests_analysis_id", "pr_selected_tests", ["analysis_id"])

    op.create_table(
        "test_impact_maps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("spec_name", sa.String(), nullable=False),
        sa.Column("test_path", sa.String(), nullable=True),
        sa.Column("impacted_paths", sa.JSON(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("categories", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="metadata"),
        sa.Column("confidence", sa.String(), nullable=False, server_default="medium"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_test_impact_project_spec", "test_impact_maps", ["project_id", "spec_name"])
    op.create_index("ix_test_impact_maps_project_id", "test_impact_maps", ["project_id"])
    op.create_index("ix_test_impact_maps_spec_name", "test_impact_maps", ["spec_name"])

    op.create_table(
        "test_execution_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("spec_name", sa.String(), nullable=False),
        sa.Column("test_name", sa.String(), nullable=True),
        sa.Column("test_path", sa.String(), nullable=True),
        sa.Column("browser", sa.String(), nullable=False, server_default="chromium"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("failure_category", sa.String(), nullable=True),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("batch_id", sa.String(), nullable=True),
        sa.Column("is_flaky", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("executed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_test_history_project_spec", "test_execution_history", ["project_id", "spec_name"])
    op.create_index("ix_test_history_project_executed", "test_execution_history", ["project_id", "executed_at"])
    op.create_index("ix_test_history_run_id", "test_execution_history", ["run_id"])
    op.create_index("ix_test_execution_history_project_id", "test_execution_history", ["project_id"])
    op.create_index("ix_test_execution_history_spec_name", "test_execution_history", ["spec_name"])
    op.create_index("ix_test_execution_history_status", "test_execution_history", ["status"])

    op.create_table(
        "repo_index_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False, server_default="github"),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("ref", sa.String(), nullable=False),
        sa.Column("commit_sha", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="completed"),
        sa.Column("indexed_files_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_files_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("test_files_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("route_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_repo_index_project_created", "repo_index_snapshots", ["project_id", "created_at"])
    op.create_index("ix_repo_index_project_ref", "repo_index_snapshots", ["project_id", "ref"])
    op.create_index("ix_repo_index_snapshots_project_id", "repo_index_snapshots", ["project_id"])
    op.create_index("ix_repo_index_snapshots_provider", "repo_index_snapshots", ["provider"])
    op.create_index("ix_repo_index_snapshots_status", "repo_index_snapshots", ["status"])

    op.create_table(
        "repo_indexed_files",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("file_type", sa.String(), nullable=False, server_default="source"),
        sa.Column("area", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("sha", sa.String(), nullable=True),
        sa.Column("imports", sa.JSON(), nullable=True),
        sa.Column("imported_by", sa.JSON(), nullable=True),
        sa.Column("routes", sa.JSON(), nullable=True),
        sa.Column("symbols", sa.JSON(), nullable=True),
        sa.Column("keywords", sa.JSON(), nullable=True),
        sa.Column("risk_flags", sa.JSON(), nullable=True),
    )
    op.create_index("ix_repo_indexed_snapshot_path", "repo_indexed_files", ["snapshot_id", "path"])
    op.create_index("ix_repo_indexed_project_path", "repo_indexed_files", ["project_id", "path"])
    op.create_index("ix_repo_indexed_files_snapshot_id", "repo_indexed_files", ["snapshot_id"])
    op.create_index("ix_repo_indexed_files_project_id", "repo_indexed_files", ["project_id"])
    op.create_index("ix_repo_indexed_files_path", "repo_indexed_files", ["path"])


def downgrade() -> None:
    op.drop_table("repo_indexed_files")
    op.drop_table("repo_index_snapshots")
    op.drop_table("test_execution_history")
    op.drop_table("test_impact_maps")
    op.drop_table("pr_selected_tests")
    op.drop_table("pr_changed_files")
    op.drop_table("pr_impact_analyses")
