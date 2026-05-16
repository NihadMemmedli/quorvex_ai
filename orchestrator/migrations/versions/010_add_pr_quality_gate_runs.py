"""Add PR quality gate runs.

Revision ID: 010
Revises: 009
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pr_quality_gate_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False, server_default="github"),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("repo", sa.String(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("head_sha", sa.String(), nullable=False),
        sa.Column("analysis_id", sa.String(), nullable=True),
        sa.Column("batch_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="initializing"),
        sa.Column("github_state", sa.String(), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("post_feedback", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("create_commit_status", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("feedback_comment_id", sa.String(), nullable=True),
        sa.Column("feedback_comment_url", sa.String(), nullable=True),
        sa.Column("commit_status_url", sa.String(), nullable=True),
        sa.Column("last_feedback_state", sa.String(), nullable=True),
        sa.Column("feedback_errors_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("final_feedback_published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "project_id",
            "provider",
            "owner",
            "repo",
            "pr_number",
            "head_sha",
            name="uq_pr_quality_gate_identity",
        ),
    )
    op.create_index("ix_pr_quality_gate_project_pr_sha", "pr_quality_gate_runs", ["project_id", "pr_number", "head_sha"])
    op.create_index("ix_pr_quality_gate_batch", "pr_quality_gate_runs", ["batch_id"])
    op.create_index("ix_pr_quality_gate_status_updated", "pr_quality_gate_runs", ["status", "updated_at"])
    op.create_index("ix_pr_quality_gate_runs_project_id", "pr_quality_gate_runs", ["project_id"])
    op.create_index("ix_pr_quality_gate_runs_provider", "pr_quality_gate_runs", ["provider"])
    op.create_index("ix_pr_quality_gate_runs_pr_number", "pr_quality_gate_runs", ["pr_number"])
    op.create_index("ix_pr_quality_gate_runs_head_sha", "pr_quality_gate_runs", ["head_sha"])
    op.create_index("ix_pr_quality_gate_runs_analysis_id", "pr_quality_gate_runs", ["analysis_id"])
    op.create_index("ix_pr_quality_gate_runs_batch_id", "pr_quality_gate_runs", ["batch_id"])
    op.create_index("ix_pr_quality_gate_runs_status", "pr_quality_gate_runs", ["status"])
    op.create_index("ix_pr_quality_gate_runs_github_state", "pr_quality_gate_runs", ["github_state"])


def downgrade() -> None:
    op.drop_table("pr_quality_gate_runs")
