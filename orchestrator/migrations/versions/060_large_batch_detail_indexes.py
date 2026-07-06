"""Add large regression batch detail indexes.

Revision ID: 060_large_batch_detail_indexes
Revises: 059_regression_batch_scheduler
Create Date: 2026-07-06
"""

from alembic import op


revision = "060_large_batch_detail_indexes"
down_revision = "059_regression_batch_scheduler"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_testrun_batch_status_spec_id",
        "testrun",
        ["batch_id", "status", "spec_name", "id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_testrun_batch_spec_id",
        "testrun",
        ["batch_id", "spec_name", "id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_testrun_project_spec_created",
        "testrun",
        ["project_id", "spec_name", "created_at"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_regression_batches_status_created",
        "regression_batches",
        ["status", "created_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_regression_batches_status_created", table_name="regression_batches", if_exists=True)
    op.drop_index("ix_testrun_project_spec_created", table_name="testrun", if_exists=True)
    op.drop_index("ix_testrun_batch_spec_id", table_name="testrun", if_exists=True)
    op.drop_index("ix_testrun_batch_status_spec_id", table_name="testrun", if_exists=True)
