"""Add Temporal metadata for standalone agent runs.

Revision ID: 034
Revises: 033
Create Date: 2026-05-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "034"
down_revision: str | None = "033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    columns = _column_names("agentrun")
    if "temporal_workflow_id" not in columns:
        op.add_column("agentrun", sa.Column("temporal_workflow_id", sa.String(), nullable=True))
    if "temporal_run_id" not in columns:
        op.add_column("agentrun", sa.Column("temporal_run_id", sa.String(), nullable=True))
    if "started_at" not in columns:
        op.add_column("agentrun", sa.Column("started_at", sa.DateTime(), nullable=True))
    if "completed_at" not in columns:
        op.add_column("agentrun", sa.Column("completed_at", sa.DateTime(), nullable=True))
    if "ix_agentrun_temporal_workflow_id" not in _index_names("agentrun"):
        op.create_index("ix_agentrun_temporal_workflow_id", "agentrun", ["temporal_workflow_id"])


def downgrade() -> None:
    if "ix_agentrun_temporal_workflow_id" in _index_names("agentrun"):
        op.drop_index("ix_agentrun_temporal_workflow_id", table_name="agentrun")
    columns = _column_names("agentrun")
    for column in ("completed_at", "started_at", "temporal_run_id", "temporal_workflow_id"):
        if column in columns:
            op.drop_column("agentrun", column)
