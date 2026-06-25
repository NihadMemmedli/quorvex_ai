"""Add AI pipeline timeout execution setting.

Revision ID: 058
Revises: 057
Create Date: 2026-06-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "058"
down_revision: str | None = "057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    if "execution_settings" not in _tables():
        return
    if "ai_pipeline_timeout_seconds" not in _columns("execution_settings"):
        op.add_column(
            "execution_settings",
            sa.Column("ai_pipeline_timeout_seconds", sa.Integer(), nullable=False, server_default="7200"),
        )


def downgrade() -> None:
    if "execution_settings" not in _tables():
        return
    if "ai_pipeline_timeout_seconds" in _columns("execution_settings"):
        op.drop_column("execution_settings", "ai_pipeline_timeout_seconds")
