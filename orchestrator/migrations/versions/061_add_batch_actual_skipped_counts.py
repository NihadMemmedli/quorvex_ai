"""Add skipped and other actual count columns to regression batches.

Revision ID: 061_batch_actual_skipped_counts
Revises: 060_large_batch_detail_indexes
Create Date: 2026-07-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "061_batch_actual_skipped_counts"
down_revision: str | None = "060_large_batch_detail_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("regression_batches", sa.Column("actual_skipped", sa.Integer(), nullable=True))
    op.add_column("regression_batches", sa.Column("actual_other", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("regression_batches", "actual_other")
    op.drop_column("regression_batches", "actual_skipped")
