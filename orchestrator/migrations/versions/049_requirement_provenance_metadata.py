"""Add requirement provenance metadata.

Revision ID: 049
Revises: 048
Create Date: 2026-06-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "049"
down_revision: str | None = "048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "requirements" not in _tables():
        return
    if "provenance_metadata_json" not in _columns("requirements"):
        op.add_column(
            "requirements",
            sa.Column("provenance_metadata_json", sa.Text(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    if "requirements" not in _tables():
        return
    if "provenance_metadata_json" in _columns("requirements"):
        op.drop_column("requirements", "provenance_metadata_json")
