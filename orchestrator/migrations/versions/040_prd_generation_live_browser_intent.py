"""Track PRD generation live browser intent.

Revision ID: 040
Revises: 039
Create Date: 2026-05-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "040"
down_revision: str | None = "039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "prd_generation_results" not in _table_names():
        return

    columns = _columns("prd_generation_results")
    if "target_url" not in columns:
        op.add_column("prd_generation_results", sa.Column("target_url", sa.String(), nullable=True))
    if "live_browser_requested" not in columns:
        op.add_column(
            "prd_generation_results",
            sa.Column("live_browser_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    if "prd_generation_results" not in _table_names():
        return

    columns = _columns("prd_generation_results")
    if "live_browser_requested" in columns:
        op.drop_column("prd_generation_results", "live_browser_requested")
    if "target_url" in columns:
        op.drop_column("prd_generation_results", "target_url")
