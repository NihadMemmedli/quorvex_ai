"""Add agent runtime selection fields.

Revision ID: 037
Revises: 036
Create Date: 2026-05-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "037"
down_revision: str | None = "036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    agentrun_columns = _column_names("agentrun")
    if "runtime" not in agentrun_columns:
        op.add_column("agentrun", sa.Column("runtime", sa.String(), nullable=False, server_default="claude_sdk"))
    if "ix_agentrun_runtime" not in _index_names("agentrun"):
        op.create_index("ix_agentrun_runtime", "agentrun", ["runtime"])

    definition_columns = _column_names("agent_definitions")
    if "runtime" not in definition_columns:
        op.add_column("agent_definitions", sa.Column("runtime", sa.String(), nullable=False, server_default="claude_sdk"))
    if "ix_agent_definitions_runtime" not in _index_names("agent_definitions"):
        op.create_index("ix_agent_definitions_runtime", "agent_definitions", ["runtime"])
    if "model_tier" not in definition_columns:
        op.add_column("agent_definitions", sa.Column("model_tier", sa.String(), nullable=True))


def downgrade() -> None:
    if "ix_agent_definitions_runtime" in _index_names("agent_definitions"):
        op.drop_index("ix_agent_definitions_runtime", table_name="agent_definitions")
    if "runtime" in _column_names("agent_definitions"):
        op.drop_column("agent_definitions", "runtime")
    if "model_tier" in _column_names("agent_definitions"):
        op.drop_column("agent_definitions", "model_tier")

    if "ix_agentrun_runtime" in _index_names("agentrun"):
        op.drop_index("ix_agentrun_runtime", table_name="agentrun")
    if "runtime" in _column_names("agentrun"):
        op.drop_column("agentrun", "runtime")
