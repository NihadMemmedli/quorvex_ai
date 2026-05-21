"""Add autonomous mission health fields.

Revision ID: 017
Revises: 016
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in _column_names(table_name):
        op.add_column(table_name, column)


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
    if index_name not in indexes:
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    _add_column_if_missing(
        "autonomous_missions",
        sa.Column("health_status", sa.String(), nullable=False, server_default="healthy"),
    )
    _add_column_if_missing("autonomous_missions", sa.Column("paused_reason", sa.String(), nullable=True))
    _add_column_if_missing(
        "autonomous_missions",
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing("autonomous_missions", sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True))
    _add_column_if_missing("autonomous_missions", sa.Column("current_stage", sa.String(), nullable=True))
    _add_column_if_missing("autonomous_missions", sa.Column("next_action", sa.String(), nullable=True))
    _add_column_if_missing(
        "autonomous_mission_runs",
        sa.Column("checkpoint_json", sa.Text(), nullable=False, server_default="{}"),
    )
    _create_index_if_missing("autonomous_missions", "ix_autonomous_missions_health_status", ["health_status"])


def downgrade() -> None:
    op.drop_index("ix_autonomous_missions_health_status", table_name="autonomous_missions")
    op.drop_column("autonomous_mission_runs", "checkpoint_json")
    op.drop_column("autonomous_missions", "next_action")
    op.drop_column("autonomous_missions", "current_stage")
    op.drop_column("autonomous_missions", "last_heartbeat_at")
    op.drop_column("autonomous_missions", "consecutive_failures")
    op.drop_column("autonomous_missions", "paused_reason")
    op.drop_column("autonomous_missions", "health_status")
