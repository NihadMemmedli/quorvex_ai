"""Add test run total cost.

Revision ID: 050
Revises: 049
Create Date: 2026-06-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "050"
down_revision: str | None = "049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "testrun" not in _tables():
        return
    if "total_cost_usd" not in _columns("testrun"):
        op.add_column("testrun", sa.Column("total_cost_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    if "testrun" not in _tables():
        return
    if "total_cost_usd" in _columns("testrun"):
        op.drop_column("testrun", "total_cost_usd")
