"""Add memory injection telemetry.

Revision ID: 027
Revises: 026
Create Date: 2026-05-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "027"
down_revision: str | None = "026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
    if index_name not in indexes:
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if "memory_injection_events" not in _table_names():
        op.create_table(
            "memory_injection_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("actor_type", sa.String(), nullable=False),
            sa.Column("stage", sa.String(), nullable=False),
            sa.Column("source_type", sa.String(), nullable=True),
            sa.Column("source_id", sa.String(), nullable=True),
            sa.Column("query", sa.Text(), nullable=False, server_default=""),
            sa.Column("memory_ids_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("context_preview", sa.Text(), nullable=False, server_default=""),
            sa.Column("outcome", sa.String(), nullable=False, server_default="injected"),
            sa.Column("extra_data", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        )

    _create_index_if_missing(
        "memory_injection_events",
        "ix_memory_injection_project_created",
        ["project_id", "created_at"],
    )
    _create_index_if_missing(
        "memory_injection_events",
        "ix_memory_injection_stage_created",
        ["stage", "created_at"],
    )
    _create_index_if_missing(
        "memory_injection_events",
        "ix_memory_injection_source",
        ["source_type", "source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_injection_source", table_name="memory_injection_events")
    op.drop_index("ix_memory_injection_stage_created", table_name="memory_injection_events")
    op.drop_index("ix_memory_injection_project_created", table_name="memory_injection_events")
    op.drop_table("memory_injection_events")
