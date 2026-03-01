"""Add performance indexes to testrun table.

Indexes for spec_name, test_type, and composite (test_type, project_id, created_at)
to support paginated API testing queries at scale (50k+ runs).

Revision ID: 002
Revises: 001
Create Date: 2026-02-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_testrun_spec_name", "testrun", ["spec_name"])
    op.create_index("ix_testrun_test_type", "testrun", ["test_type"])
    op.create_index(
        "ix_testrun_type_project_date",
        "testrun",
        ["test_type", "project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_testrun_type_project_date", table_name="testrun")
    op.drop_index("ix_testrun_test_type", table_name="testrun")
    op.drop_index("ix_testrun_spec_name", table_name="testrun")
