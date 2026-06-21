"""Add AutoPilot spec task evidence metadata.

Revision ID: 054
Revises: 053
Create Date: 2026-06-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "054"
down_revision: str | None = "053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "autopilot_spec_tasks" not in _tables():
        return
    if "evidence_metadata_json" not in _columns("autopilot_spec_tasks"):
        op.add_column(
            "autopilot_spec_tasks",
            sa.Column("evidence_metadata_json", sa.Text(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    if "autopilot_spec_tasks" not in _tables():
        return
    if "evidence_metadata_json" in _columns("autopilot_spec_tasks"):
        op.drop_column("autopilot_spec_tasks", "evidence_metadata_json")
