"""Add openapi_import_history table for persistent import tracking.

Revision ID: 003
Revises: 002
Create Date: 2026-02-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "openapi_import_history",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("source_filename", sa.String(), nullable=True),
        sa.Column("feature_filter", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("files_generated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generated_paths_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_openapi_import_history_project_id", "openapi_import_history", ["project_id"])
    op.create_index("ix_openapi_import_history_created_at", "openapi_import_history", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_openapi_import_history_created_at", table_name="openapi_import_history")
    op.drop_index("ix_openapi_import_history_project_id", table_name="openapi_import_history")
    op.drop_table("openapi_import_history")
