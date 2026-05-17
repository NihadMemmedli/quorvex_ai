"""Add agent working memories.

Revision ID: 011
Revises: 010
Create Date: 2026-05-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_memories",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("source_type", sa.String(), nullable=True),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("agent_type", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("extra_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
    )
    op.create_index("ix_agentmemory_project_status", "agent_memories", ["project_id", "status"])
    op.create_index("ix_agentmemory_project_kind", "agent_memories", ["project_id", "kind"])
    op.create_index("ix_agentmemory_user_status", "agent_memories", ["user_id", "status"])
    op.create_index("ix_agentmemory_source", "agent_memories", ["source_type", "source_id"])
    op.create_index("ix_agentmemory_last_used", "agent_memories", ["last_used_at"])
    op.create_index("ix_agent_memories_project_id", "agent_memories", ["project_id"])
    op.create_index("ix_agent_memories_user_id", "agent_memories", ["user_id"])
    op.create_index("ix_agent_memories_kind", "agent_memories", ["kind"])
    op.create_index("ix_agent_memories_agent_type", "agent_memories", ["agent_type"])
    op.create_index("ix_agent_memories_status", "agent_memories", ["status"])


def downgrade() -> None:
    op.drop_table("agent_memories")
