"""Add autonomous test proposal table.

Revision ID: 016
Revises: 015
Create Date: 2026-05-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "autonomous_test_proposals" not in tables:
        op.create_table(
            "autonomous_test_proposals",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("mission_id", sa.String(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("finding_id", sa.String(), nullable=True),
            sa.Column("coverage_gap_id", sa.Integer(), nullable=True),
            sa.Column("approval_id", sa.String(), nullable=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("target_url", sa.String(), nullable=True),
            sa.Column("route", sa.String(), nullable=True),
            sa.Column("test_type", sa.String(), nullable=False, server_default="e2e"),
            sa.Column("rationale", sa.Text(), nullable=False),
            sa.Column("generated_spec_content", sa.Text(), nullable=False),
            sa.Column("suggested_file_path", sa.String(), nullable=False),
            sa.Column("risk_level", sa.String(), nullable=False, server_default="medium"),
            sa.Column("approval_status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("dedupe_key", sa.String(), nullable=False),
            sa.Column("source_type", sa.String(), nullable=True),
            sa.Column("source_id", sa.String(), nullable=True),
            sa.Column("source_metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("materialized_file_path", sa.String(), nullable=True),
            sa.Column("materialization_result_json", sa.Text(), nullable=True),
            sa.Column("approved_by", sa.String(), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("rejected_by", sa.String(), nullable=True),
            sa.Column("rejected_at", sa.DateTime(), nullable=True),
            sa.Column("materialized_by", sa.String(), nullable=True),
            sa.Column("materialized_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["mission_id"], ["autonomous_missions.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["autonomous_mission_runs.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["finding_id"], ["autonomous_findings.id"]),
            sa.ForeignKeyConstraint(["coverage_gap_id"], ["coverage_gaps.id"]),
            sa.ForeignKeyConstraint(["approval_id"], ["autonomous_approvals.id"]),
            sa.UniqueConstraint("project_id", "dedupe_key", name="uq_autonomous_test_proposals_project_dedupe"),
        )

    inspector = sa.inspect(bind)
    indexes = {idx["name"] for idx in inspector.get_indexes("autonomous_test_proposals")}
    uniques_by_table = {
        table: {constraint["name"] for constraint in inspector.get_unique_constraints(table)}
        for table in ("autonomous_findings", "autonomous_test_proposals")
        if table in set(inspector.get_table_names())
    }

    def create_index_if_missing(name: str, columns: list[str]) -> None:
        if name not in indexes:
            op.create_index(name, "autonomous_test_proposals", columns)

    create_index_if_missing("ix_autonomous_test_proposals_project_status", ["project_id", "approval_status"])
    create_index_if_missing("ix_autonomous_test_proposals_mission_created", ["mission_id", "created_at"])
    create_index_if_missing("ix_autonomous_test_proposals_dedupe", ["project_id", "dedupe_key"])
    create_index_if_missing("ix_autonomous_test_proposals_mission_id", ["mission_id"])
    create_index_if_missing("ix_autonomous_test_proposals_run_id", ["run_id"])
    create_index_if_missing("ix_autonomous_test_proposals_project_id", ["project_id"])
    create_index_if_missing("ix_autonomous_test_proposals_finding_id", ["finding_id"])
    create_index_if_missing("ix_autonomous_test_proposals_coverage_gap_id", ["coverage_gap_id"])
    create_index_if_missing("ix_autonomous_test_proposals_approval_id", ["approval_id"])
    create_index_if_missing("ix_autonomous_test_proposals_test_type", ["test_type"])
    create_index_if_missing("ix_autonomous_test_proposals_approval_status", ["approval_status"])
    create_index_if_missing("ix_autonomous_test_proposals_dedupe_key", ["dedupe_key"])
    if "uq_autonomous_findings_project_dedupe" not in uniques_by_table.get("autonomous_findings", set()):
        op.create_unique_constraint(
            "uq_autonomous_findings_project_dedupe",
            "autonomous_findings",
            ["project_id", "dedupe_key"],
        )
    if "uq_autonomous_test_proposals_project_dedupe" not in uniques_by_table.get("autonomous_test_proposals", set()):
        op.create_unique_constraint(
            "uq_autonomous_test_proposals_project_dedupe",
            "autonomous_test_proposals",
            ["project_id", "dedupe_key"],
        )


def downgrade() -> None:
    op.drop_constraint("uq_autonomous_findings_project_dedupe", "autonomous_findings", type_="unique")
    op.drop_table("autonomous_test_proposals")
