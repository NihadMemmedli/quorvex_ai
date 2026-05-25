"""Add durable agent run events.

Revision ID: 032
Revises: 031
Create Date: 2026-05-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "032"
down_revision: str | None = "031"
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
    if "agent_run_events" not in _table_names():
        op.create_table(
            "agent_run_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("agent_task_id", sa.String(), nullable=True),
            sa.Column("temporal_workflow_id", sa.String(), nullable=True),
            sa.Column("temporal_run_id", sa.String(), nullable=True),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("level", sa.String(), nullable=False, server_default="info"),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["agentrun.id"]),
        )

    _create_index_if_missing("agent_run_events", "ix_agent_run_events_run_sequence", ["run_id", "sequence"])
    _create_index_if_missing("agent_run_events", "ix_agent_run_events_project_created", ["project_id", "created_at"])
    _create_index_if_missing("agent_run_events", "ix_agent_run_events_agent_task", ["agent_task_id"])
    _create_index_if_missing(
        "agent_run_events",
        "ix_agent_run_events_temporal_workflow",
        ["temporal_workflow_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_run_events_temporal_workflow", table_name="agent_run_events")
    op.drop_index("ix_agent_run_events_agent_task", table_name="agent_run_events")
    op.drop_index("ix_agent_run_events_project_created", table_name="agent_run_events")
    op.drop_index("ix_agent_run_events_run_sequence", table_name="agent_run_events")
    op.drop_table("agent_run_events")
