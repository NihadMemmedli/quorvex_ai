"""Track OpenAPI import chunk metadata.

Revision ID: 042
Revises: 041
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "042"
down_revision: str | None = "041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "openapi_import_history" not in _table_names():
        return

    columns = _columns("openapi_import_history")
    if "chunk_count" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        )
    if "recommended_mode" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("recommended_mode", sa.String(), nullable=False, server_default="plan_and_tests"),
        )


def downgrade() -> None:
    if "openapi_import_history" not in _table_names():
        return

    columns = _columns("openapi_import_history")
    for column in ["recommended_mode", "chunk_count"]:
        if column in columns:
            op.drop_column("openapi_import_history", column)
