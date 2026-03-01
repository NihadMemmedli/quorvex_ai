"""Fix flow_steps.value column type from BOOLEAN to VARCHAR.

The column was incorrectly created as BOOLEAN by SQLModel's create_all()
before Alembic existed. The model defines it as Optional[str], and
exploration inserts URLs, text, and stringified booleans.

Revision ID: 004
Revises: 003
Create Date: 2026-02-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'flow_steps'
                  AND column_name = 'value'
                  AND data_type = 'boolean'
            ) THEN
                ALTER TABLE flow_steps ALTER COLUMN value TYPE VARCHAR
                USING CASE WHEN value IS NULL THEN NULL
                           WHEN value THEN 'true'
                           ELSE 'false' END;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    # No-op: cannot losslessly convert arbitrary strings back to boolean
    pass
