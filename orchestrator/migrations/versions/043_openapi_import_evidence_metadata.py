"""Track OpenAPI import evidence metadata.

Revision ID: 043
Revises: 042
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "043"
down_revision: str | None = "042"
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
    if "evidence_paths_json" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("evidence_paths_json", sa.String(), nullable=False, server_default="[]"),
        )
    if "executed_operations" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("executed_operations", sa.Integer(), nullable=False, server_default="0"),
        )
    if "blocked_operations_json" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("blocked_operations_json", sa.String(), nullable=False, server_default="[]"),
        )
    if "failed_operations_json" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("failed_operations_json", sa.String(), nullable=False, server_default="[]"),
        )
    if "recommended_next_action" not in columns:
        op.add_column("openapi_import_history", sa.Column("recommended_next_action", sa.String(), nullable=True))
    if "base_url" not in columns:
        op.add_column("openapi_import_history", sa.Column("base_url", sa.String(), nullable=True))
    if "needs_input" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("needs_input", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "missing_fields_json" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("missing_fields_json", sa.String(), nullable=False, server_default="[]"),
        )
    if "diagnostics_json" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("diagnostics_json", sa.String(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    if "openapi_import_history" not in _table_names():
        return

    columns = _columns("openapi_import_history")
    for column in [
        "recommended_next_action",
        "diagnostics_json",
        "missing_fields_json",
        "needs_input",
        "base_url",
        "failed_operations_json",
        "blocked_operations_json",
        "executed_operations",
        "evidence_paths_json",
    ]:
        if column in columns:
            op.drop_column("openapi_import_history", column)
