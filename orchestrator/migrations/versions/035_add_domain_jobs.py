"""Add durable domain job status records.

Revision ID: 035
Revises: 034
Create Date: 2026-05-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "035"
down_revision: str | None = "034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    if "domain_jobs" not in _table_names():
        op.create_table(
            "domain_jobs",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("job_type", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("progress_json", sa.Text(), nullable=True),
            sa.Column("result_json", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("temporal_workflow_id", sa.String(), nullable=True),
            sa.Column("temporal_run_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    indexes = _index_names("domain_jobs")
    if "ix_domain_jobs_job_type" not in indexes:
        op.create_index("ix_domain_jobs_job_type", "domain_jobs", ["job_type"])
    if "ix_domain_jobs_project_id" not in indexes:
        op.create_index("ix_domain_jobs_project_id", "domain_jobs", ["project_id"])
    if "ix_domain_jobs_status" not in indexes:
        op.create_index("ix_domain_jobs_status", "domain_jobs", ["status"])
    if "ix_domain_jobs_created_at" not in indexes:
        op.create_index("ix_domain_jobs_created_at", "domain_jobs", ["created_at"])
    if "ix_domain_jobs_updated_at" not in indexes:
        op.create_index("ix_domain_jobs_updated_at", "domain_jobs", ["updated_at"])
    if "ix_domain_jobs_type_status" not in indexes:
        op.create_index("ix_domain_jobs_type_status", "domain_jobs", ["job_type", "status"])
    if "ix_domain_jobs_project_created" not in indexes:
        op.create_index("ix_domain_jobs_project_created", "domain_jobs", ["project_id", "created_at"])
    if "ix_domain_jobs_temporal_workflow" not in indexes:
        op.create_index("ix_domain_jobs_temporal_workflow", "domain_jobs", ["temporal_workflow_id"])


def downgrade() -> None:
    if "domain_jobs" in _table_names():
        op.drop_table("domain_jobs")

