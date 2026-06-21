"""Add persisted AutoPilot checklist items.

Revision ID: 055
Revises: 054
Create Date: 2026-06-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "055"
down_revision: str | None = "054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    if "autopilot_checklist_items" not in _tables():
        op.create_table(
            "autopilot_checklist_items",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("session_id", sa.String(), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("kind", sa.String(), nullable=False, server_default="task"),
            sa.Column("phase_name", sa.String(), nullable=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("detail", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
            sa.Column("items_completed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("items_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("source_type", sa.String(), nullable=True),
            sa.Column("source_id", sa.String(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["session_id"], ["autopilot_sessions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    indexes = _index_names("autopilot_checklist_items")
    for name, columns in {
        "ix_autopilot_checklist_session_sequence": ["session_id", "sequence"],
        "ix_autopilot_checklist_session_status": ["session_id", "status"],
        "ix_autopilot_checklist_session_phase": ["session_id", "phase_name"],
    }.items():
        if name not in indexes:
            op.create_index(name, "autopilot_checklist_items", columns)


def downgrade() -> None:
    if "autopilot_checklist_items" not in _tables():
        return
    for name in (
        "ix_autopilot_checklist_session_phase",
        "ix_autopilot_checklist_session_status",
        "ix_autopilot_checklist_session_sequence",
    ):
        if name in _index_names("autopilot_checklist_items"):
            op.drop_index(name, table_name="autopilot_checklist_items")
    op.drop_table("autopilot_checklist_items")
