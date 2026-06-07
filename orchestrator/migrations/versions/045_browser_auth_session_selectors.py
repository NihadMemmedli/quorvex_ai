"""Add browser auth session selector configuration.

Revision ID: 045
Revises: 044
Create Date: 2026-06-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "045"
down_revision: str | None = "044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "browser_auth_sessions" not in _table_names():
        return

    columns = _columns("browser_auth_sessions")
    for column_name in [
        "username_selector",
        "password_selector",
        "username_continue_selector",
        "submit_selector",
        "success_url_pattern",
    ]:
        if column_name not in columns:
            op.add_column("browser_auth_sessions", sa.Column(column_name, sa.String(), nullable=True))


def downgrade() -> None:
    if "browser_auth_sessions" not in _table_names():
        return

    columns = _columns("browser_auth_sessions")
    for column_name in [
        "success_url_pattern",
        "submit_selector",
        "username_continue_selector",
        "password_selector",
        "username_selector",
    ]:
        if column_name in columns:
            op.drop_column("browser_auth_sessions", column_name)
