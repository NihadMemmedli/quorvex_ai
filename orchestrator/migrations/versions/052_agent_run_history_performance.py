"""Add agent run history performance indexes.

Revision ID: 052
Revises: 051
Create Date: 2026-06-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "052"
down_revision: str | None = "051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _unique_constraints(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {constraint["name"] for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table_name)}


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    if index_name not in _indexes(table_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if "agentrun" in _tables():
        _create_index_if_missing("agentrun", "ix_agentrun_project_created_id", ["project_id", "created_at", "id"])
        _create_index_if_missing(
            "agentrun",
            "ix_agentrun_project_status_created_id",
            ["project_id", "status", "created_at", "id"],
        )
        _create_index_if_missing(
            "agentrun",
            "ix_agentrun_project_agent_type_created_id",
            ["project_id", "agent_type", "created_at", "id"],
        )

    if "agent_run_events" in _tables() and "uq_agent_run_events_run_sequence" not in _unique_constraints("agent_run_events"):
        op.execute(
            """
            WITH ordered AS (
                SELECT
                    id,
                    row_number() OVER (PARTITION BY run_id ORDER BY sequence, created_at, id) AS new_sequence
                FROM agent_run_events
            )
            UPDATE agent_run_events
            SET sequence = ordered.new_sequence
            FROM ordered
            WHERE agent_run_events.id = ordered.id
              AND agent_run_events.sequence <> ordered.new_sequence
            """
        )
        op.create_unique_constraint(
            "uq_agent_run_events_run_sequence",
            "agent_run_events",
            ["run_id", "sequence"],
        )


def downgrade() -> None:
    if "agent_run_events" in _tables() and "uq_agent_run_events_run_sequence" in _unique_constraints("agent_run_events"):
        op.drop_constraint("uq_agent_run_events_run_sequence", "agent_run_events", type_="unique")
    if "agentrun" in _tables():
        for index_name in (
            "ix_agentrun_project_agent_type_created_id",
            "ix_agentrun_project_status_created_id",
            "ix_agentrun_project_created_id",
        ):
            if index_name in _indexes("agentrun"):
                op.drop_index(index_name, table_name="agentrun")
