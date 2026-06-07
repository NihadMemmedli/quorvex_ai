"""Track PRD generation queue ownership.

Revision ID: 048
Revises: 047
Create Date: 2026-06-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "048"
down_revision: str | None = "047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "prd_generation_results" not in _table_names():
        return

    columns = _columns("prd_generation_results")
    if "agent_task_id" not in columns:
        op.add_column("prd_generation_results", sa.Column("agent_task_id", sa.String(), nullable=True))
    if "agent_worker_id" not in columns:
        op.add_column("prd_generation_results", sa.Column("agent_worker_id", sa.String(), nullable=True))
    if "last_heartbeat_at" not in columns:
        op.add_column("prd_generation_results", sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True))
    if "queue_telemetry_json" not in columns:
        op.add_column(
            "prd_generation_results",
            sa.Column("queue_telemetry_json", sa.String(), nullable=False, server_default="{}"),
        )

    indexes = _index_names("prd_generation_results")
    if "ix_prd_generation_results_agent_task_id" not in indexes:
        op.create_index("ix_prd_generation_results_agent_task_id", "prd_generation_results", ["agent_task_id"])
    if "ix_prd_generation_results_agent_worker_id" not in indexes:
        op.create_index("ix_prd_generation_results_agent_worker_id", "prd_generation_results", ["agent_worker_id"])


def downgrade() -> None:
    if "prd_generation_results" not in _table_names():
        return

    indexes = _index_names("prd_generation_results")
    if "ix_prd_generation_results_agent_worker_id" in indexes:
        op.drop_index("ix_prd_generation_results_agent_worker_id", table_name="prd_generation_results")
    if "ix_prd_generation_results_agent_task_id" in indexes:
        op.drop_index("ix_prd_generation_results_agent_task_id", table_name="prd_generation_results")

    columns = _columns("prd_generation_results")
    for column_name in ("queue_telemetry_json", "last_heartbeat_at", "agent_worker_id", "agent_task_id"):
        if column_name in columns:
            op.drop_column("prd_generation_results", column_name)
