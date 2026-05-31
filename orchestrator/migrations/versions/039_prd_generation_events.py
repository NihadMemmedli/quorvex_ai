"""Add structured PRD generation events.

Revision ID: 039
Revises: 038
Create Date: 2026-05-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "039"
down_revision: str | None = "038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    if "prd_generation_events" not in _table_names():
        op.create_table(
            "prd_generation_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("generation_id", sa.Integer(), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("level", sa.String(), nullable=False),
            sa.Column("message", sa.String(), nullable=False),
            sa.Column("payload_json", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["generation_id"], ["prd_generation_results.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    indexes = _index_names("prd_generation_events")
    if "ix_prd_generation_events_generation_id" not in indexes:
        op.create_index("ix_prd_generation_events_generation_id", "prd_generation_events", ["generation_id"])
    if "ix_prd_generation_events_sequence" not in indexes:
        op.create_index("ix_prd_generation_events_sequence", "prd_generation_events", ["sequence"])
    if "ix_prd_generation_events_role" not in indexes:
        op.create_index("ix_prd_generation_events_role", "prd_generation_events", ["role"])
    if "ix_prd_generation_events_event_type" not in indexes:
        op.create_index("ix_prd_generation_events_event_type", "prd_generation_events", ["event_type"])
    if "ix_prd_generation_events_generation_sequence" not in indexes:
        op.create_index(
            "ix_prd_generation_events_generation_sequence",
            "prd_generation_events",
            ["generation_id", "sequence"],
        )


def downgrade() -> None:
    if "prd_generation_events" in _table_names():
        for index in (
            "ix_prd_generation_events_generation_sequence",
            "ix_prd_generation_events_event_type",
            "ix_prd_generation_events_role",
            "ix_prd_generation_events_sequence",
            "ix_prd_generation_events_generation_id",
        ):
            if index in _index_names("prd_generation_events"):
                op.drop_index(index, table_name="prd_generation_events")
        op.drop_table("prd_generation_events")
