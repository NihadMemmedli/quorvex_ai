"""Add workflow schedule revision mode.

Revision ID: 023
Revises: 022
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "023"
down_revision: str | None = "022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if "revision_mode" not in _columns("workflow_schedules"):
        op.add_column(
            "workflow_schedules",
            sa.Column("revision_mode", sa.String(), nullable=False, server_default="pinned"),
        )


def downgrade() -> None:
    if "revision_mode" in _columns("workflow_schedules"):
        op.drop_column("workflow_schedules", "revision_mode")
