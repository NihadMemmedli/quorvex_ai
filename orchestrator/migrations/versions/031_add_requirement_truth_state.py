"""Add durable requirement truth-state fields.

Revision ID: 031
Revises: 030
Create Date: 2026-05-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "031"
down_revision: str | None = "030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    if index_name not in _index_names(table_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    columns = _column_names("requirements")
    if "truth_state" not in columns:
        op.add_column(
            "requirements",
            sa.Column("truth_state", sa.String(), nullable=False, server_default="candidate_requirement"),
        )
    if "source_type" not in columns:
        op.add_column("requirements", sa.Column("source_type", sa.String(), nullable=False, server_default="manual"))
    if "confidence" not in columns:
        op.add_column("requirements", sa.Column("confidence", sa.Float(), nullable=False, server_default="0.9"))
    if "uncertainty_reason" not in columns:
        op.add_column("requirements", sa.Column("uncertainty_reason", sa.Text(), nullable=True))
    if "confirmed_by" not in columns:
        op.add_column("requirements", sa.Column("confirmed_by", sa.String(), nullable=True))
    if "confirmed_at" not in columns:
        op.add_column("requirements", sa.Column("confirmed_at", sa.DateTime(), nullable=True))
    if "rejected_by" not in columns:
        op.add_column("requirements", sa.Column("rejected_by", sa.String(), nullable=True))
    if "rejected_at" not in columns:
        op.add_column("requirements", sa.Column("rejected_at", sa.DateTime(), nullable=True))

    op.execute(
        """
        UPDATE requirements
        SET truth_state = CASE
            WHEN status IN ('approved', 'implemented', 'tested', 'confirmed') THEN 'confirmed_requirement'
            WHEN status IN ('rejected') THEN 'rejected_requirement'
            WHEN source_session_id IS NOT NULL THEN 'candidate_requirement'
            ELSE truth_state
        END
        """
    )
    op.execute(
        """
        UPDATE requirements
        SET source_type = CASE
            WHEN source_session_id IS NOT NULL THEN 'exploration'
            WHEN truth_state = 'confirmed_requirement' THEN 'human_approval'
            ELSE source_type
        END
        """
    )
    op.execute(
        """
        UPDATE requirements
        SET confidence = CASE
            WHEN truth_state = 'confirmed_requirement' THEN 1.0
            WHEN source_session_id IS NOT NULL THEN 0.7
            ELSE confidence
        END
        """
    )

    _create_index_if_missing("requirements", "ix_requirements_truth_state", ["truth_state"])
    _create_index_if_missing("requirements", "ix_requirements_source_type", ["source_type"])


def downgrade() -> None:
    op.drop_index("ix_requirements_source_type", table_name="requirements")
    op.drop_index("ix_requirements_truth_state", table_name="requirements")
    for column in (
        "rejected_at",
        "rejected_by",
        "confirmed_at",
        "confirmed_by",
        "uncertainty_reason",
        "confidence",
        "source_type",
        "truth_state",
    ):
        op.drop_column("requirements", column)
