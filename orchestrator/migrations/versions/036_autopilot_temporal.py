"""Add Temporal metadata for AutoPilot sessions.

Revision ID: 036
Revises: 035
Create Date: 2026-05-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "036"
down_revision: str | None = "035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    columns = _column_names("autopilot_sessions")
    if "temporal_workflow_id" not in columns:
        op.add_column("autopilot_sessions", sa.Column("temporal_workflow_id", sa.String(), nullable=True))
    if "temporal_run_id" not in columns:
        op.add_column("autopilot_sessions", sa.Column("temporal_run_id", sa.String(), nullable=True))
    if "ix_autopilot_sessions_temporal_workflow_id" not in _index_names("autopilot_sessions"):
        op.create_index(
            "ix_autopilot_sessions_temporal_workflow_id",
            "autopilot_sessions",
            ["temporal_workflow_id"],
        )


def downgrade() -> None:
    if "ix_autopilot_sessions_temporal_workflow_id" in _index_names("autopilot_sessions"):
        op.drop_index("ix_autopilot_sessions_temporal_workflow_id", table_name="autopilot_sessions")
    columns = _column_names("autopilot_sessions")
    for column in ("temporal_run_id", "temporal_workflow_id"):
        if column in columns:
            op.drop_column("autopilot_sessions", column)
