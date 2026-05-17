"""Add CI control center audit and workflow proposal tables.

Revision ID: 012
Revises: 011
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ci_pipeline_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("external_pipeline_id", sa.String(), nullable=False),
        sa.Column("external_project_id", sa.String(), nullable=True),
        sa.Column("external_url", sa.String(), nullable=True),
        sa.Column("ref", sa.String(), nullable=True),
        sa.Column("triggered_from", sa.String(), nullable=False, server_default="dashboard"),
        sa.Column("batch_id", sa.String(), nullable=True),
        sa.Column("schedule_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("stages_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("total_tests", sa.Integer(), nullable=True),
        sa.Column("passed_tests", sa.Integer(), nullable=True),
        sa.Column("failed_tests", sa.Integer(), nullable=True),
        sa.Column("test_report_url", sa.String(), nullable=True),
        sa.Column("artifacts_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["batch_id"], ["regression_batches.id"]),
        sa.ForeignKeyConstraint(["schedule_id"], ["cron_schedules.id"]),
    )
    op.create_index("ix_ci_pipeline_project_provider_created", "ci_pipeline_mappings", ["project_id", "provider", "created_at"])
    op.create_index("ix_ci_pipeline_project_provider_external", "ci_pipeline_mappings", ["project_id", "provider", "external_pipeline_id"], unique=True)
    op.create_index("ix_ci_pipeline_mappings_project_id", "ci_pipeline_mappings", ["project_id"])
    op.create_index("ix_ci_pipeline_mappings_provider", "ci_pipeline_mappings", ["provider"])
    op.create_index("ix_ci_pipeline_mappings_external_pipeline_id", "ci_pipeline_mappings", ["external_pipeline_id"])
    op.create_index("ix_ci_pipeline_mappings_batch_id", "ci_pipeline_mappings", ["batch_id"])
    op.create_index("ix_ci_pipeline_mappings_schedule_id", "ci_pipeline_mappings", ["schedule_id"])

    op.create_table(
        "ci_workflow_change_requests",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False, server_default="github"),
        sa.Column("workflow_name", sa.String(), nullable=False),
        sa.Column("workflow_path", sa.String(), nullable=False),
        sa.Column("ref", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("generated_yaml", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("validation_errors", sa.JSON(), nullable=True),
        sa.Column("validation_warnings", sa.JSON(), nullable=True),
        sa.Column("pull_request_url", sa.String(), nullable=True),
        sa.Column("pull_request_number", sa.Integer(), nullable=True),
        sa.Column("pull_request_branch", sa.String(), nullable=True),
        sa.Column("pull_request_base_ref", sa.String(), nullable=True),
        sa.Column("commit_sha", sa.String(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ci_workflow_change_project_created", "ci_workflow_change_requests", ["project_id", "created_at"])
    op.create_index("ix_ci_workflow_change_project_status", "ci_workflow_change_requests", ["project_id", "status"])
    op.create_index("ix_ci_workflow_change_requests_project_id", "ci_workflow_change_requests", ["project_id"])
    op.create_index("ix_ci_workflow_change_requests_provider", "ci_workflow_change_requests", ["provider"])
    op.create_index("ix_ci_workflow_change_requests_status", "ci_workflow_change_requests", ["status"])

    op.create_table(
        "ci_audit_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=True),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="ok"),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("actor_email", sa.String(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ci_audit_project_created", "ci_audit_events", ["project_id", "created_at"])
    op.create_index("ix_ci_audit_project_action", "ci_audit_events", ["project_id", "action"])
    op.create_index("ix_ci_audit_events_project_id", "ci_audit_events", ["project_id"])
    op.create_index("ix_ci_audit_events_provider", "ci_audit_events", ["provider"])
    op.create_index("ix_ci_audit_events_action", "ci_audit_events", ["action"])
    op.create_index("ix_ci_audit_events_status", "ci_audit_events", ["status"])
    op.create_index("ix_ci_audit_events_created_at", "ci_audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("ci_audit_events")
    op.drop_table("ci_workflow_change_requests")
    op.drop_table("ci_pipeline_mappings")
