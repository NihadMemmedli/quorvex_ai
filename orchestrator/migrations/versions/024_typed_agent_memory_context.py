"""Add typed agent memory context fields.

Revision ID: 024
Revises: 023
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "024"
down_revision: str | None = "023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _add_column_if_missing(table_name: str, columns: set[str], column: sa.Column) -> None:
    if column.name not in columns:
        op.add_column(table_name, column)


def _create_index_if_missing(table_name: str, indexes: set[str], name: str, columns: list[str]) -> None:
    if name not in indexes:
        op.create_index(name, table_name, columns)


def upgrade() -> None:
    table = "agent_memories"
    columns = _columns(table)
    if not columns:
        return

    _add_column_if_missing(table, columns, sa.Column("memory_type", sa.String(), nullable=False, server_default="semantic"))
    _add_column_if_missing(table, columns, sa.Column("scope", sa.String(), nullable=False, server_default="project"))
    _add_column_if_missing(table, columns, sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"))
    _add_column_if_missing(table, columns, sa.Column("valid_from", sa.DateTime(), nullable=True))
    _add_column_if_missing(table, columns, sa.Column("valid_until", sa.DateTime(), nullable=True))
    _add_column_if_missing(table, columns, sa.Column("supersedes_id", sa.String(), nullable=True))
    _add_column_if_missing(table, columns, sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing(table, columns, sa.Column("last_verified_at", sa.DateTime(), nullable=True))

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE agent_memories
            SET memory_type = CASE
                WHEN kind IN ('failure_pattern') THEN 'episodic'
                WHEN kind IN ('agent_lesson', 'workflow_decision') THEN 'procedural'
                ELSE 'semantic'
            END
            WHERE memory_type IS NULL OR memory_type = 'semantic'
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE agent_memories
            SET scope = CASE
                WHEN user_id IS NOT NULL AND user_id != '' THEN 'user'
                WHEN project_id IS NOT NULL AND project_id != '' THEN 'project'
                ELSE 'global'
            END
            WHERE scope IS NULL OR scope = 'project'
            """
        )
    )

    indexes = _indexes(table)
    _create_index_if_missing(table, indexes, "ix_agentmemory_project_type", ["project_id", "memory_type"])
    _create_index_if_missing(table, indexes, "ix_agentmemory_scope_status", ["scope", "status"])
    _create_index_if_missing(table, indexes, "ix_agent_memories_memory_type", ["memory_type"])
    _create_index_if_missing(table, indexes, "ix_agent_memories_scope", ["scope"])
    _create_index_if_missing(table, indexes, "ix_agent_memories_supersedes_id", ["supersedes_id"])


def downgrade() -> None:
    table = "agent_memories"
    columns = _columns(table)
    indexes = _indexes(table)

    for index_name in [
        "ix_agent_memories_supersedes_id",
        "ix_agent_memories_scope",
        "ix_agent_memories_memory_type",
        "ix_agentmemory_scope_status",
        "ix_agentmemory_project_type",
    ]:
        if index_name in indexes:
            op.drop_index(index_name, table_name=table)

    for column_name in [
        "last_verified_at",
        "review_required",
        "supersedes_id",
        "valid_until",
        "valid_from",
        "importance",
        "scope",
        "memory_type",
    ]:
        if column_name in columns:
            op.drop_column(table, column_name)
