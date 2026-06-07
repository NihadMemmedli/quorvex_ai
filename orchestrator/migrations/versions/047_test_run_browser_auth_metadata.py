"""Add browser auth metadata to test runs.

Revision ID: 047
Revises: 046
Create Date: 2026-06-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "047"
down_revision: str | None = "046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    if "testrun" not in _table_names():
        return
    if "browser_auth" not in _columns("testrun"):
        op.add_column("testrun", sa.Column("browser_auth", sa.JSON(), nullable=True))


def downgrade() -> None:
    if "testrun" not in _table_names():
        return
    if "browser_auth" in _columns("testrun"):
        op.drop_column("testrun", "browser_auth")
