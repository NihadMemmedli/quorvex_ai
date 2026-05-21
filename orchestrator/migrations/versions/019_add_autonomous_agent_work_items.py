"""Add autonomous agent work items.

Revision ID: 019
Revises: 018
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "019"
down_revision: str | None = "018"
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
    if "autonomous_agent_work_items" not in _table_names():
        op.create_table(
            "autonomous_agent_work_items",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("mission_id", sa.String(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("objective", sa.Text(), nullable=False),
            sa.Column("assigned_surface_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("status", sa.String(), nullable=False, server_default="queued"),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
            sa.Column("agent_task_id", sa.String(), nullable=True),
            sa.Column("progress_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("artifacts_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("error_message", sa.String(), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("budget_used_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["mission_id"], ["autonomous_missions.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["autonomous_mission_runs.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        )

    _create_index_if_missing(
        "autonomous_agent_work_items",
        "ix_autonomous_work_items_mission_status",
        ["mission_id", "status"],
    )
    _create_index_if_missing(
        "autonomous_agent_work_items",
        "ix_autonomous_work_items_project_status",
        ["project_id", "status"],
    )
    _create_index_if_missing(
        "autonomous_agent_work_items",
        "ix_autonomous_work_items_agent_task",
        ["agent_task_id"],
    )
    _create_index_if_missing(
        "autonomous_agent_work_items",
        "ix_autonomous_work_items_role_status",
        ["role", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_autonomous_work_items_role_status", table_name="autonomous_agent_work_items")
    op.drop_index("ix_autonomous_work_items_agent_task", table_name="autonomous_agent_work_items")
    op.drop_index("ix_autonomous_work_items_project_status", table_name="autonomous_agent_work_items")
    op.drop_index("ix_autonomous_work_items_mission_status", table_name="autonomous_agent_work_items")
    op.drop_table("autonomous_agent_work_items")
