"""Add workflow run step context snapshots.

Revision ID: 021
Revises: 020
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "021"
down_revision: str | None = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in _column_names(table_name):
        op.add_column(table_name, column)


def upgrade() -> None:
    _add_column_if_missing("workflow_run_steps", sa.Column("rendered_input_json", sa.Text(), nullable=False, server_default="{}"))
    _add_column_if_missing("workflow_run_steps", sa.Column("context_snapshot_json", sa.Text(), nullable=False, server_default="{}"))
    _add_column_if_missing("workflow_run_steps", sa.Column("input_resolution_json", sa.Text(), nullable=False, server_default="[]"))
    _add_column_if_missing("workflow_run_steps", sa.Column("output_validation_errors_json", sa.Text(), nullable=False, server_default="[]"))


def downgrade() -> None:
    columns = _column_names("workflow_run_steps")
    for column_name in (
        "output_validation_errors_json",
        "input_resolution_json",
        "context_snapshot_json",
        "rendered_input_json",
    ):
        if column_name in columns:
            op.drop_column("workflow_run_steps", column_name)
