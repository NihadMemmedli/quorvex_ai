"""Add CI generated test subset tables.

Revision ID: 013
Revises: 012
Create Date: 2026-05-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ci_test_subsets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("mode", sa.String(), nullable=False, server_default="both"),
        sa.Column("default_browser", sa.String(), nullable=False, server_default="chromium"),
        sa.Column("base_url_secret", sa.String(), nullable=False, server_default="APP_BASE_URL"),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.UniqueConstraint("project_id", "slug", name="uq_ci_test_subset_project_slug"),
    )
    op.create_index("ix_ci_test_subset_project_created", "ci_test_subsets", ["project_id", "created_at"])
    op.create_index("ix_ci_test_subset_project_slug", "ci_test_subsets", ["project_id", "slug"])
    op.create_index("ix_ci_test_subsets_project_id", "ci_test_subsets", ["project_id"])
    op.create_index("ix_ci_test_subsets_slug", "ci_test_subsets", ["slug"])
    op.create_index("ix_ci_test_subsets_mode", "ci_test_subsets", ["mode"])

    op.create_table(
        "ci_test_subset_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("subset_id", sa.String(), nullable=False),
        sa.Column("spec_name", sa.String(), nullable=False),
        sa.Column("code_path", sa.String(), nullable=False),
        sa.Column("target_path", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("categories", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["subset_id"], ["ci_test_subsets.id"]),
        sa.UniqueConstraint("subset_id", "spec_name", name="uq_ci_test_subset_item_spec"),
    )
    op.create_index("ix_ci_test_subset_items_subset", "ci_test_subset_items", ["subset_id"])
    op.create_index("ix_ci_test_subset_items_spec", "ci_test_subset_items", ["spec_name"])
    op.create_index("ix_ci_test_subset_items_subset_id", "ci_test_subset_items", ["subset_id"])
    op.create_index("ix_ci_test_subset_items_spec_name", "ci_test_subset_items", ["spec_name"])


def downgrade() -> None:
    op.drop_table("ci_test_subset_items")
    op.drop_table("ci_test_subsets")
