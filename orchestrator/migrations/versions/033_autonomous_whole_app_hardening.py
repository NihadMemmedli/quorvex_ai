"""Autonomous whole-app hardening fields.

Revision ID: 033
Revises: 032
Create Date: 2026-05-24
"""

import sqlalchemy as sa
from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("requirements", sa.Column("canonical_key", sa.String(), nullable=True))
    op.create_index("ix_requirements_project_canonical", "requirements", ["project_id", "canonical_key"])
    op.create_unique_constraint("uq_requirements_project_canonical", "requirements", ["project_id", "canonical_key"])

    op.add_column("rtm_entries", sa.Column("dedupe_key", sa.String(), nullable=True))
    op.create_index("ix_rtm_entries_project_dedupe", "rtm_entries", ["project_id", "dedupe_key"])
    op.create_unique_constraint("uq_rtm_entries_project_dedupe", "rtm_entries", ["project_id", "dedupe_key"])

    op.add_column("application_map", sa.Column("project_id", sa.String(), nullable=True))
    op.add_column("application_map", sa.Column("app_surface_key", sa.String(), nullable=True))
    op.create_index("ix_application_map_project_surface", "application_map", ["project_id", "app_surface_key"])

    op.add_column("autonomous_agent_work_items", sa.Column("planner_key", sa.String(), nullable=True))
    op.add_column("autonomous_agent_work_items", sa.Column("lease_until", sa.DateTime(), nullable=True))
    op.add_column("autonomous_agent_work_items", sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True))
    op.add_column(
        "autonomous_agent_work_items",
        sa.Column("recovery_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("autonomous_agent_work_items", sa.Column("recovery_reason", sa.Text(), nullable=True))
    op.create_index("ix_autonomous_work_items_mission_planner", "autonomous_agent_work_items", ["mission_id", "planner_key"])
    op.create_index("ix_autonomous_work_items_mission_lease", "autonomous_agent_work_items", ["mission_id", "lease_until"])

    op.add_column(
        "autonomous_test_proposals",
        sa.Column("validation_status", sa.String(), nullable=False, server_default="not_run"),
    )
    op.add_column("autonomous_test_proposals", sa.Column("validation_result_json", sa.Text(), nullable=True))
    op.add_column(
        "autonomous_test_proposals",
        sa.Column("validation_artifacts_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column("autonomous_test_proposals", sa.Column("validation_log_path", sa.String(), nullable=True))
    op.add_column("autonomous_test_proposals", sa.Column("validation_trace_path", sa.String(), nullable=True))
    op.add_column("autonomous_test_proposals", sa.Column("validated_at", sa.DateTime(), nullable=True))
    op.create_index("ix_autonomous_test_proposals_validation_status", "autonomous_test_proposals", ["validation_status"])


def downgrade() -> None:
    op.drop_index("ix_autonomous_test_proposals_validation_status", table_name="autonomous_test_proposals")
    op.drop_column("autonomous_test_proposals", "validated_at")
    op.drop_column("autonomous_test_proposals", "validation_trace_path")
    op.drop_column("autonomous_test_proposals", "validation_log_path")
    op.drop_column("autonomous_test_proposals", "validation_artifacts_json")
    op.drop_column("autonomous_test_proposals", "validation_result_json")
    op.drop_column("autonomous_test_proposals", "validation_status")

    op.drop_index("ix_autonomous_work_items_mission_lease", table_name="autonomous_agent_work_items")
    op.drop_index("ix_autonomous_work_items_mission_planner", table_name="autonomous_agent_work_items")
    op.drop_column("autonomous_agent_work_items", "recovery_reason")
    op.drop_column("autonomous_agent_work_items", "recovery_count")
    op.drop_column("autonomous_agent_work_items", "last_heartbeat_at")
    op.drop_column("autonomous_agent_work_items", "lease_until")
    op.drop_column("autonomous_agent_work_items", "planner_key")

    op.drop_index("ix_application_map_project_surface", table_name="application_map")
    op.drop_column("application_map", "app_surface_key")
    op.drop_column("application_map", "project_id")

    op.drop_constraint("uq_rtm_entries_project_dedupe", "rtm_entries", type_="unique")
    op.drop_index("ix_rtm_entries_project_dedupe", table_name="rtm_entries")
    op.drop_column("rtm_entries", "dedupe_key")

    op.drop_constraint("uq_requirements_project_canonical", "requirements", type_="unique")
    op.drop_index("ix_requirements_project_canonical", table_name="requirements")
    op.drop_column("requirements", "canonical_key")
