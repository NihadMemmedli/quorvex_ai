"""Extend workflow step registry metadata.

Revision ID: 020
Revises: 019
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "020"
down_revision: str | None = "019"
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
    _add_column_if_missing("workflow_step_types", sa.Column("category", sa.String(), nullable=False, server_default="Utility"))
    _add_column_if_missing("workflow_step_types", sa.Column("risk_level", sa.String(), nullable=False, server_default="low"))
    _add_column_if_missing("workflow_step_types", sa.Column("is_async", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing("workflow_step_types", sa.Column("auto_wait_defaults_json", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    columns = _column_names("workflow_step_types")
    for column_name in ("auto_wait_defaults_json", "is_async", "risk_level", "category"):
        if column_name in columns:
            op.drop_column("workflow_step_types", column_name)
