"""Add review state for discovered flows.

Revision ID: 030
Revises: 029
Create Date: 2026-05-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "030"
down_revision: str | None = "029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str], *, unique: bool = False) -> None:
    if index_name not in _index_names(table_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    tables = _table_names()

    if "discovered_flow_reviews" not in tables:
        op.create_table(
            "discovered_flow_reviews",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("flow_id", sa.Integer(), nullable=False),
            sa.Column("session_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("review_status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("reviewer", sa.String(), nullable=True),
            sa.Column("comment", sa.String(), nullable=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.Column("generated_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["flow_id"], ["discovered_flows.id"]),
            sa.ForeignKeyConstraint(["session_id"], ["exploration_sessions.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.UniqueConstraint("flow_id", name="uq_discovered_flow_reviews_flow_id"),
        )

    _create_index_if_missing("discovered_flow_reviews", "ix_discovered_flow_reviews_flow_id", ["flow_id"])
    _create_index_if_missing("discovered_flow_reviews", "ix_discovered_flow_reviews_session_id", ["session_id"])
    _create_index_if_missing("discovered_flow_reviews", "ix_discovered_flow_reviews_project_id", ["project_id"])
    _create_index_if_missing("discovered_flow_reviews", "ix_discovered_flow_reviews_review_status", ["review_status"])
    _create_index_if_missing(
        "discovered_flow_reviews",
        "ix_discovered_flow_reviews_project_status",
        ["project_id", "review_status"],
    )
    _create_index_if_missing(
        "discovered_flow_reviews",
        "ix_discovered_flow_reviews_session_status",
        ["session_id", "review_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_discovered_flow_reviews_session_status", table_name="discovered_flow_reviews")
    op.drop_index("ix_discovered_flow_reviews_project_status", table_name="discovered_flow_reviews")
    op.drop_index("ix_discovered_flow_reviews_review_status", table_name="discovered_flow_reviews")
    op.drop_index("ix_discovered_flow_reviews_project_id", table_name="discovered_flow_reviews")
    op.drop_index("ix_discovered_flow_reviews_session_id", table_name="discovered_flow_reviews")
    op.drop_index("ix_discovered_flow_reviews_flow_id", table_name="discovered_flow_reviews")
    op.drop_table("discovered_flow_reviews")
