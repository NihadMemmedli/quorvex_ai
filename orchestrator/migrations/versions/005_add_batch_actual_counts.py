"""Add cached actual test count columns to regression_batches.

These columns cache the computed test counts so list_batches() does not
need O(batches x specs x disk reads) per page load.

Revision ID: 005
Revises: 004
Create Date: 2026-02-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("regression_batches", sa.Column("actual_total_tests", sa.Integer(), nullable=True))
    op.add_column("regression_batches", sa.Column("actual_passed", sa.Integer(), nullable=True))
    op.add_column("regression_batches", sa.Column("actual_failed", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("regression_batches", "actual_total_tests")
    op.drop_column("regression_batches", "actual_passed")
    op.drop_column("regression_batches", "actual_failed")
