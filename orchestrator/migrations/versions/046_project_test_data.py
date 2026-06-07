"""Add project-scoped test data library.

Revision ID: 046
Revises: 045
Create Date: 2026-06-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "046"
down_revision: str | None = "045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    tables = _table_names()
    if "agent_definitions" in tables and "test_data_refs_json" not in _columns("agent_definitions"):
        op.add_column(
            "agent_definitions",
            sa.Column("test_data_refs_json", sa.Text(), nullable=False, server_default="[]"),
        )

    if "test_data_sets" not in tables:
        op.create_table(
            "test_data_sets",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=False, server_default=""),
            sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("format", sa.String(), nullable=False, server_default="json"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("project_id", "key", name="uq_test_data_sets_project_key"),
        )
        op.create_index("ix_test_data_sets_project_status", "test_data_sets", ["project_id", "status"])
        op.create_index("ix_test_data_sets_project_format", "test_data_sets", ["project_id", "format"])
        op.create_index("ix_test_data_sets_key", "test_data_sets", ["key"])
        op.create_index("ix_test_data_sets_project_id", "test_data_sets", ["project_id"])

    tables = _table_names()
    if "test_data_items" not in tables:
        op.create_table(
            "test_data_items",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("dataset_id", sa.String(), sa.ForeignKey("test_data_sets.id"), nullable=False),
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False, server_default=""),
            sa.Column("description", sa.String(), nullable=False, server_default=""),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("format", sa.String(), nullable=False, server_default="json"),
            sa.Column("data_json", sa.Text(), nullable=True),
            sa.Column("data_text", sa.Text(), nullable=True),
            sa.Column("sensitive_fields_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("encrypted_values_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("dataset_id", "key", name="uq_test_data_items_dataset_key"),
        )
        op.create_index("ix_test_data_items_dataset_status", "test_data_items", ["dataset_id", "status"])
        op.create_index("ix_test_data_items_dataset_id", "test_data_items", ["dataset_id"])
        op.create_index("ix_test_data_items_key", "test_data_items", ["key"])


def downgrade() -> None:
    tables = _table_names()
    if "test_data_items" in tables:
        op.drop_index("ix_test_data_items_key", table_name="test_data_items")
        op.drop_index("ix_test_data_items_dataset_id", table_name="test_data_items")
        op.drop_index("ix_test_data_items_dataset_status", table_name="test_data_items")
        op.drop_table("test_data_items")
    tables = _table_names()
    if "test_data_sets" in tables:
        op.drop_index("ix_test_data_sets_project_id", table_name="test_data_sets")
        op.drop_index("ix_test_data_sets_key", table_name="test_data_sets")
        op.drop_index("ix_test_data_sets_project_format", table_name="test_data_sets")
        op.drop_index("ix_test_data_sets_project_status", table_name="test_data_sets")
        op.drop_table("test_data_sets")
    tables = _table_names()
    if "agent_definitions" in tables and "test_data_refs_json" in _columns("agent_definitions"):
        op.drop_column("agent_definitions", "test_data_refs_json")
