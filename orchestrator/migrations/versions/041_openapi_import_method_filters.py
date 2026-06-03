"""Track OpenAPI import filters and generated artifacts.

Revision ID: 041
Revises: 040
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "041"
down_revision: str | None = "040"
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
    if "method_filter_json" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("method_filter_json", sa.String(), nullable=False, server_default="[]"),
        )
    if "mode" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("mode", sa.String(), nullable=False, server_default="plan_and_tests"),
        )
    if "plan_path" not in columns:
        op.add_column("openapi_import_history", sa.Column("plan_path", sa.String(), nullable=True))
    if "spec_paths_json" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("spec_paths_json", sa.String(), nullable=False, server_default="[]"),
        )
    if "test_paths_json" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("test_paths_json", sa.String(), nullable=False, server_default="[]"),
        )
    if "matched_operations" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("matched_operations", sa.Integer(), nullable=False, server_default="0"),
        )
    if "skipped_operations" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("skipped_operations", sa.Integer(), nullable=False, server_default="0"),
        )
    if "warnings_json" not in columns:
        op.add_column(
            "openapi_import_history",
            sa.Column("warnings_json", sa.String(), nullable=False, server_default="[]"),
        )


def downgrade() -> None:
    if "openapi_import_history" not in _table_names():
        return

    columns = _columns("openapi_import_history")
    for column in [
        "warnings_json",
        "skipped_operations",
        "matched_operations",
        "test_paths_json",
        "spec_paths_json",
        "plan_path",
        "mode",
        "method_filter_json",
    ]:
        if column in columns:
            op.drop_column("openapi_import_history", column)
