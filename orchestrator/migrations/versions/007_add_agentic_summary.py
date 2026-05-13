"""Add agentic QA summary to test runs.

Revision ID: 007
Revises: 006
Create Date: 2026-05-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    column_type = sa.JSON() if dialect != "postgresql" else postgresql.JSONB()
    op.add_column("testrun", sa.Column("agentic_summary", column_type, nullable=True))


def downgrade() -> None:
    op.drop_column("testrun", "agentic_summary")
