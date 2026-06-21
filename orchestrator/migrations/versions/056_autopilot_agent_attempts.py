"""Add AutoPilot agent attempt retry state.

Revision ID: 056
Revises: 055
Create Date: 2026-06-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "056"
down_revision: str | None = "055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    if "autopilot_agent_attempts" not in _tables():
        op.create_table(
            "autopilot_agent_attempts",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("session_id", sa.String(), nullable=False),
            sa.Column("stable_key", sa.String(), nullable=False),
            sa.Column("source_type", sa.String(), nullable=True),
            sa.Column("source_id", sa.String(), nullable=True),
            sa.Column("agent_kind", sa.String(), nullable=False, server_default="agent"),
            sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("claude_session_id", sa.String(), nullable=True),
            sa.Column("session_dir", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="running"),
            sa.Column("error_type", sa.String(), nullable=True),
            sa.Column("retry_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["session_id"], ["autopilot_sessions.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("session_id", "stable_key", "attempt_number", name="uq_autopilot_agent_attempt"),
        )

    indexes = _index_names("autopilot_agent_attempts")
    for name, columns in {
        "ix_autopilot_agent_attempts_session_id": ["session_id"],
        "ix_autopilot_agent_attempts_stable_key": ["stable_key"],
        "ix_autopilot_agent_attempts_source_type": ["source_type"],
        "ix_autopilot_agent_attempts_source_id": ["source_id"],
        "ix_autopilot_agent_attempts_agent_kind": ["agent_kind"],
        "ix_autopilot_agent_attempts_attempt_number": ["attempt_number"],
        "ix_autopilot_agent_attempts_claude_session_id": ["claude_session_id"],
        "ix_autopilot_agent_attempts_status": ["status"],
        "ix_autopilot_agent_attempts_error_type": ["error_type"],
        "ix_autopilot_agent_attempts_retry_eligible": ["retry_eligible"],
        "ix_autopilot_agent_attempts_updated_at": ["updated_at"],
        "ix_autopilot_agent_attempts_session_key": ["session_id", "stable_key"],
        "ix_autopilot_agent_attempts_session_status": ["session_id", "status"],
    }.items():
        if name not in indexes:
            op.create_index(name, "autopilot_agent_attempts", columns)


def downgrade() -> None:
    if "autopilot_agent_attempts" not in _tables():
        return
    for name in (
        "ix_autopilot_agent_attempts_session_status",
        "ix_autopilot_agent_attempts_session_key",
        "ix_autopilot_agent_attempts_updated_at",
        "ix_autopilot_agent_attempts_retry_eligible",
        "ix_autopilot_agent_attempts_error_type",
        "ix_autopilot_agent_attempts_status",
        "ix_autopilot_agent_attempts_claude_session_id",
        "ix_autopilot_agent_attempts_attempt_number",
        "ix_autopilot_agent_attempts_agent_kind",
        "ix_autopilot_agent_attempts_source_id",
        "ix_autopilot_agent_attempts_source_type",
        "ix_autopilot_agent_attempts_stable_key",
        "ix_autopilot_agent_attempts_session_id",
    ):
        if name in _index_names("autopilot_agent_attempts"):
            op.drop_index(name, table_name="autopilot_agent_attempts")
    op.drop_table("autopilot_agent_attempts")
