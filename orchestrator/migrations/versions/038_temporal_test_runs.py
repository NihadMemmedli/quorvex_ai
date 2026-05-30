"""Add Temporal metadata for classic test runs.

Revision ID: 038
Revises: 037
Create Date: 2026-05-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "038"
down_revision: str | None = "037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    columns = _column_names("testrun")
    if "temporal_workflow_id" not in columns:
        op.add_column("testrun", sa.Column("temporal_workflow_id", sa.String(), nullable=True))
    if "temporal_run_id" not in columns:
        op.add_column("testrun", sa.Column("temporal_run_id", sa.String(), nullable=True))
    if "ix_testrun_temporal_workflow_id" not in _index_names("testrun"):
        op.create_index("ix_testrun_temporal_workflow_id", "testrun", ["temporal_workflow_id"])


def downgrade() -> None:
    if "ix_testrun_temporal_workflow_id" in _index_names("testrun"):
        op.drop_index("ix_testrun_temporal_workflow_id", table_name="testrun")
    columns = _column_names("testrun")
    for column in ("temporal_run_id", "temporal_workflow_id"):
        if column in columns:
            op.drop_column("testrun", column)
