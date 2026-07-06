"""Add scheduled regression batch state.

Revision ID: 059
Revises: 058
Create Date: 2026-06-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "059"
down_revision: str | None = "058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    if "regression_batches" in _tables():
        columns = _columns("regression_batches")
        additions = [
            ("scheduler_status", sa.String(), True),
            ("scheduler_workflow_id", sa.String(), True),
            ("scheduler_run_id", sa.String(), True),
            ("chunk_size", sa.Integer(), True),
            ("max_active_runs", sa.Integer(), True),
            ("dispatch_total", sa.Integer(), False),
            ("dispatch_started", sa.Integer(), False),
            ("dispatch_completed", sa.Integer(), False),
            ("dispatch_failed", sa.Integer(), False),
            ("dispatch_cancelled", sa.Integer(), False),
            ("next_spec_index", sa.Integer(), False),
            ("scheduler_error", sa.Text(), True),
        ]
        for name, type_, nullable in additions:
            if name in columns:
                continue
            kwargs = {}
            if not nullable:
                kwargs["server_default"] = "0"
            op.add_column("regression_batches", sa.Column(name, type_, nullable=nullable, **kwargs))
        if "ix_regression_batches_scheduler_status" not in _indexes("regression_batches"):
            op.create_index(
                "ix_regression_batches_scheduler_status",
                "regression_batches",
                ["scheduler_status"],
            )

    if "regression_batch_items" not in _tables():
        op.create_table(
            "regression_batch_items",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("batch_id", sa.String(), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("spec_name", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("run_id", sa.String(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["batch_id"], ["regression_batches.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["testrun.id"]),
            sa.UniqueConstraint("batch_id", "ordinal", name="uq_regression_batch_items_batch_ordinal"),
        )
        op.create_index(
            "ix_regression_batch_items_batch_status",
            "regression_batch_items",
            ["batch_id", "status"],
        )
        op.create_index(
            "ix_regression_batch_items_batch_ordinal",
            "regression_batch_items",
            ["batch_id", "ordinal"],
        )
        op.create_index("ix_regression_batch_items_run_id", "regression_batch_items", ["run_id"])


def downgrade() -> None:
    if "regression_batch_items" in _tables():
        op.drop_table("regression_batch_items")
    if "regression_batches" not in _tables():
        return
    for index_name in ("ix_regression_batches_scheduler_status",):
        if index_name in _indexes("regression_batches"):
            op.drop_index(index_name, table_name="regression_batches")
    for column in (
        "scheduler_error",
        "next_spec_index",
        "dispatch_cancelled",
        "dispatch_failed",
        "dispatch_completed",
        "dispatch_started",
        "dispatch_total",
        "max_active_runs",
        "chunk_size",
        "scheduler_run_id",
        "scheduler_workflow_id",
        "scheduler_status",
    ):
        if column in _columns("regression_batches"):
            op.drop_column("regression_batches", column)
