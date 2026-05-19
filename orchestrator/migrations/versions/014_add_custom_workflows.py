"""Add custom workflow definition and run tables.

Revision ID: 014
Revises: 013
Create Date: 2026-05-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    def create_index_if_missing(name: str, table: str, columns: list[str]) -> None:
        existing = {idx["name"] for idx in inspector.get_indexes(table)}
        if name not in existing:
            op.create_index(name, table, columns)

    if "workflow_definitions" not in tables:
        op.create_table(
            "workflow_definitions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=False, server_default=""),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("steps_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("created_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        )
    else:
        cols = {col["name"] for col in inspector.get_columns("workflow_definitions")}
        if "steps_json" not in cols:
            op.add_column("workflow_definitions", sa.Column("steps_json", sa.Text(), nullable=False, server_default="[]"))
            if "steps" in cols:
                bind.execute(sa.text("UPDATE workflow_definitions SET steps_json = COALESCE(CAST(steps AS TEXT), '[]')"))
        if "created_by" not in cols:
            op.add_column("workflow_definitions", sa.Column("created_by", sa.String(), nullable=True))
        if "version" not in cols:
            op.add_column("workflow_definitions", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    create_index_if_missing("ix_workflow_definitions_project_status", "workflow_definitions", ["project_id", "status"])
    create_index_if_missing("ix_workflow_definitions_project_updated", "workflow_definitions", ["project_id", "updated_at"])
    create_index_if_missing("ix_workflow_definitions_project_id", "workflow_definitions", ["project_id"])

    if "workflow_runs" not in tables:
        op.create_table(
            "workflow_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("workflow_id", sa.String(), nullable=True),
            sa.Column("definition_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="queued"),
            sa.Column("current_step_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
            sa.Column("inputs_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("context_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("result_json", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("triggered_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["workflow_id"], ["workflow_definitions.id"]),
            sa.ForeignKeyConstraint(["definition_id"], ["workflow_definitions.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        )
    else:
        cols = {col["name"] for col in inspector.get_columns("workflow_runs")}
        if "definition_id" not in cols:
            op.add_column("workflow_runs", sa.Column("definition_id", sa.String(), nullable=True))
            if "workflow_id" in cols:
                bind.execute(sa.text("UPDATE workflow_runs SET definition_id = workflow_id WHERE definition_id IS NULL"))
        if "workflow_id" not in cols:
            op.add_column("workflow_runs", sa.Column("workflow_id", sa.String(), nullable=True))
            bind.execute(sa.text("UPDATE workflow_runs SET workflow_id = definition_id WHERE workflow_id IS NULL"))
        for name, column in [
            ("progress", sa.Column("progress", sa.Float(), nullable=False, server_default="0")),
            ("inputs_json", sa.Column("inputs_json", sa.Text(), nullable=False, server_default="{}")),
            ("context_json", sa.Column("context_json", sa.Text(), nullable=False, server_default="{}")),
            ("result_json", sa.Column("result_json", sa.Text(), nullable=True)),
            ("triggered_by", sa.Column("triggered_by", sa.String(), nullable=True)),
        ]:
            if name not in cols:
                op.add_column("workflow_runs", column)
        if "input_data" in cols:
            bind.execute(sa.text("UPDATE workflow_runs SET inputs_json = COALESCE(CAST(input_data AS TEXT), '{}')"))
        if "result_data" in cols:
            bind.execute(sa.text("UPDATE workflow_runs SET result_json = CAST(result_data AS TEXT) WHERE result_data IS NOT NULL"))
    create_index_if_missing("ix_workflow_runs_project_status", "workflow_runs", ["project_id", "status"])
    create_index_if_missing("ix_workflow_runs_definition_created", "workflow_runs", ["definition_id", "created_at"])
    create_index_if_missing("ix_workflow_runs_definition_id", "workflow_runs", ["definition_id"])
    create_index_if_missing("ix_workflow_runs_project_id", "workflow_runs", ["project_id"])

    if "workflow_run_steps" not in tables:
        op.create_table(
            "workflow_run_steps",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("workflow_id", sa.String(), nullable=True),
            sa.Column("definition_id", sa.String(), nullable=False),
            sa.Column("step_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("step_order", sa.Integer(), nullable=False),
            sa.Column("step_id", sa.String(), nullable=False, server_default="step"),
            sa.Column("step_key", sa.String(), nullable=False),
            sa.Column("step_type", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False, server_default=""),
            sa.Column("label", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("continue_on_error", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("input_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("output_json", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("external_kind", sa.String(), nullable=True),
            sa.Column("external_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"]),
            sa.ForeignKeyConstraint(["workflow_id"], ["workflow_definitions.id"]),
            sa.ForeignKeyConstraint(["definition_id"], ["workflow_definitions.id"]),
        )
    else:
        cols = {col["name"] for col in inspector.get_columns("workflow_run_steps")}
        additions = [
            ("workflow_id", sa.Column("workflow_id", sa.String(), nullable=True)),
            ("definition_id", sa.Column("definition_id", sa.String(), nullable=True)),
            ("step_index", sa.Column("step_index", sa.Integer(), nullable=False, server_default="0")),
            ("step_order", sa.Column("step_order", sa.Integer(), nullable=False, server_default="0")),
            ("step_id", sa.Column("step_id", sa.String(), nullable=False, server_default="step")),
            ("step_key", sa.Column("step_key", sa.String(), nullable=False, server_default="step")),
            ("name", sa.Column("name", sa.String(), nullable=False, server_default="")),
            ("label", sa.Column("label", sa.String(), nullable=False, server_default="")),
            ("continue_on_error", sa.Column("continue_on_error", sa.Boolean(), nullable=False, server_default=sa.false())),
            ("input_json", sa.Column("input_json", sa.Text(), nullable=False, server_default="{}")),
            ("output_json", sa.Column("output_json", sa.Text(), nullable=True)),
            ("external_kind", sa.Column("external_kind", sa.String(), nullable=True)),
            ("external_id", sa.Column("external_id", sa.String(), nullable=True)),
            ("created_at", sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now())),
        ]
        for name, column in additions:
            if name not in cols:
                op.add_column("workflow_run_steps", column)
        if "workflow_id" in cols:
            bind.execute(sa.text("UPDATE workflow_run_steps SET definition_id = workflow_id WHERE definition_id IS NULL"))
        else:
            bind.execute(sa.text("UPDATE workflow_run_steps SET workflow_id = definition_id WHERE workflow_id IS NULL"))
        if "step_index" in cols:
            bind.execute(sa.text("UPDATE workflow_run_steps SET step_order = step_index"))
        if "step_id" in cols:
            bind.execute(sa.text("UPDATE workflow_run_steps SET step_key = step_id WHERE step_id IS NOT NULL"))
        if "name" in cols:
            bind.execute(sa.text("UPDATE workflow_run_steps SET label = name WHERE name IS NOT NULL"))
        if "input_data" in cols:
            bind.execute(sa.text("UPDATE workflow_run_steps SET input_json = COALESCE(CAST(input_data AS TEXT), '{}')"))
        if "output_data" in cols:
            bind.execute(sa.text("UPDATE workflow_run_steps SET output_json = CAST(output_data AS TEXT) WHERE output_data IS NOT NULL"))
    create_index_if_missing("ix_workflow_run_steps_run_order", "workflow_run_steps", ["run_id", "step_order"])
    create_index_if_missing("ix_workflow_run_steps_external", "workflow_run_steps", ["external_kind", "external_id"])
    create_index_if_missing("ix_workflow_run_steps_run_id", "workflow_run_steps", ["run_id"])
    create_index_if_missing("ix_workflow_run_steps_definition_id", "workflow_run_steps", ["definition_id"])


def downgrade() -> None:
    op.drop_table("workflow_run_steps")
    op.drop_table("workflow_runs")
    op.drop_table("workflow_definitions")
