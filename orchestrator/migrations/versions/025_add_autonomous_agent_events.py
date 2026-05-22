"""Add autonomous agent events.

Revision ID: 025
Revises: 024
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "025"
down_revision: str | None = "024"
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
    if "autonomous_agent_events" not in _table_names():
        op.create_table(
            "autonomous_agent_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("mission_id", sa.String(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=True),
            sa.Column("work_item_id", sa.String(), nullable=True),
            sa.Column("agent_task_id", sa.String(), nullable=True),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("level", sa.String(), nullable=False, server_default="info"),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["mission_id"], ["autonomous_missions.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["autonomous_mission_runs.id"]),
            sa.ForeignKeyConstraint(["work_item_id"], ["autonomous_agent_work_items.id"]),
        )

    _create_index_if_missing(
        "autonomous_agent_events",
        "ix_autonomous_agent_events_mission_sequence",
        ["mission_id", "sequence"],
    )
    _create_index_if_missing(
        "autonomous_agent_events",
        "ix_autonomous_agent_events_work_item_sequence",
        ["work_item_id", "sequence"],
    )
    _create_index_if_missing(
        "autonomous_agent_events",
        "ix_autonomous_agent_events_project_created",
        ["project_id", "created_at"],
    )
    _create_index_if_missing(
        "autonomous_agent_events",
        "ix_autonomous_agent_events_agent_task",
        ["agent_task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_autonomous_agent_events_agent_task", table_name="autonomous_agent_events")
    op.drop_index("ix_autonomous_agent_events_project_created", table_name="autonomous_agent_events")
    op.drop_index("ix_autonomous_agent_events_work_item_sequence", table_name="autonomous_agent_events")
    op.drop_index("ix_autonomous_agent_events_mission_sequence", table_name="autonomous_agent_events")
    op.drop_table("autonomous_agent_events")
