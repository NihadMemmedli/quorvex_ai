"""Add memory feedback scoring tables.

Revision ID: 029
Revises: 028
Create Date: 2026-05-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "029"
down_revision: str | None = "028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str], *, unique: bool = False) -> None:
    if index_name not in _index_names(table_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    tables = _table_names()

    if "memory_feedback_events" not in tables:
        op.create_table(
            "memory_feedback_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("memory_id", sa.String(), nullable=False),
            sa.Column("injection_event_id", sa.String(), nullable=True),
            sa.Column("conversation_id", sa.String(), nullable=True),
            sa.Column("message_index", sa.Integer(), nullable=True),
            sa.Column("rating", sa.String(), nullable=False),
            sa.Column("signal", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("source", sa.String(), nullable=False, server_default="manual_dashboard"),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("user_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["memory_id"], ["agent_memories.id"]),
            sa.ForeignKeyConstraint(["injection_event_id"], ["memory_injection_events.id"]),
            sa.ForeignKeyConstraint(["conversation_id"], ["chat_conversations.id"]),
        )

    if "memory_feedback_aggregates" not in tables:
        op.create_table(
            "memory_feedback_aggregates",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("project_key", sa.String(), nullable=False, server_default="__global__"),
            sa.Column("memory_id", sa.String(), nullable=False),
            sa.Column("positive_feedback_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("negative_feedback_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("feedback_score", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("last_feedback_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["memory_id"], ["agent_memories.id"]),
            sa.UniqueConstraint("project_key", "memory_id", name="uq_memory_feedback_aggregate_project_memory"),
        )
    elif "project_key" not in _column_names("memory_feedback_aggregates"):
        op.add_column(
            "memory_feedback_aggregates",
            sa.Column("project_key", sa.String(), nullable=False, server_default="__global__"),
        )
        op.execute(
            "UPDATE memory_feedback_aggregates "
            "SET project_key = COALESCE(project_id, '__global__') "
            "WHERE project_key = '__global__'"
        )

    _create_index_if_missing(
        "memory_feedback_events",
        "ix_memory_feedback_project_created",
        ["project_id", "created_at"],
    )
    _create_index_if_missing("memory_feedback_events", "ix_memory_feedback_memory", ["memory_id"])
    _create_index_if_missing("memory_feedback_events", "ix_memory_feedback_injection", ["injection_event_id"])
    _create_index_if_missing("memory_feedback_events", "ix_memory_feedback_source", ["source"])
    _create_index_if_missing(
        "memory_feedback_aggregates",
        "ix_memory_feedback_aggregate_project_score",
        ["project_id", "feedback_score"],
    )
    _create_index_if_missing("memory_feedback_aggregates", "ix_memory_feedback_aggregate_memory", ["memory_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_feedback_aggregate_memory", table_name="memory_feedback_aggregates")
    op.drop_index("ix_memory_feedback_aggregate_project_score", table_name="memory_feedback_aggregates")
    op.drop_index("ix_memory_feedback_source", table_name="memory_feedback_events")
    op.drop_index("ix_memory_feedback_injection", table_name="memory_feedback_events")
    op.drop_index("ix_memory_feedback_memory", table_name="memory_feedback_events")
    op.drop_index("ix_memory_feedback_project_created", table_name="memory_feedback_events")
    op.drop_table("memory_feedback_aggregates")
    op.drop_table("memory_feedback_events")
