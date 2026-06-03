"""Correlate OpenAPI import history rows with job IDs.

Revision ID: 044
Revises: 043
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "044"
down_revision: str | None = "043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "openapi_import_history" not in _table_names():
        return

    columns = _columns("openapi_import_history")
    if "job_id" not in columns:
        op.add_column("openapi_import_history", sa.Column("job_id", sa.String(), nullable=True))

    if "ix_openapi_import_history_job_id" not in _indexes("openapi_import_history"):
        op.create_index("ix_openapi_import_history_job_id", "openapi_import_history", ["job_id"])


def downgrade() -> None:
    if "openapi_import_history" not in _table_names():
        return

    if "ix_openapi_import_history_job_id" in _indexes("openapi_import_history"):
        op.drop_index("ix_openapi_import_history_job_id", table_name="openapi_import_history")

    if "job_id" in _columns("openapi_import_history"):
        op.drop_column("openapi_import_history", "job_id")
