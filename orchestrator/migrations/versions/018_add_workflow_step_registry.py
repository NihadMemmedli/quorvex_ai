"""Add workflow step registry.

Revision ID: 018
Revises: 017
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in _column_names(table_name):
        op.add_column(table_name, column)


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
    if index_name not in indexes:
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if "workflow_step_types" not in _table_names():
        op.create_table(
            "workflow_step_types",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("type", sa.String(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("label", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=False, server_default=""),
            sa.Column("required_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("input_schema_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("ui_schema_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("output_schema_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("default_input_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("category", sa.String(), nullable=False, server_default="Utility"),
            sa.Column("risk_level", sa.String(), nullable=False, server_default="low"),
            sa.Column("is_async", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("auto_wait_defaults_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("handler_kind", sa.String(), nullable=False, server_default="builtin"),
            sa.Column("handler_config_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.UniqueConstraint("project_id", "type", "version", name="uq_workflow_step_type_project_type_version"),
        )

    _create_index_if_missing("workflow_step_types", "ix_workflow_step_types_project_status", ["project_id", "status"])
    _create_index_if_missing("workflow_step_types", "ix_workflow_step_types_type_version", ["type", "version"])

    _add_column_if_missing(
        "workflow_run_steps",
        sa.Column("step_type_version", sa.Integer(), nullable=False, server_default="1"),
    )
    _add_column_if_missing(
        "workflow_run_steps",
        sa.Column("step_config_json", sa.Text(), nullable=False, server_default="{}"),
    )
    _add_column_if_missing("workflow_step_types", sa.Column("category", sa.String(), nullable=False, server_default="Utility"))
    _add_column_if_missing("workflow_step_types", sa.Column("risk_level", sa.String(), nullable=False, server_default="low"))
    _add_column_if_missing("workflow_step_types", sa.Column("is_async", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column_if_missing("workflow_step_types", sa.Column("auto_wait_defaults_json", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("workflow_run_steps", "step_config_json")
    op.drop_column("workflow_run_steps", "step_type_version")
    op.drop_column("workflow_step_types", "auto_wait_defaults_json")
    op.drop_column("workflow_step_types", "is_async")
    op.drop_column("workflow_step_types", "risk_level")
    op.drop_column("workflow_step_types", "category")
    op.drop_index("ix_workflow_step_types_type_version", table_name="workflow_step_types")
    op.drop_index("ix_workflow_step_types_project_status", table_name="workflow_step_types")
    op.drop_table("workflow_step_types")
