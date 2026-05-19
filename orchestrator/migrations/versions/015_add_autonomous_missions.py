"""Add autonomous testing mission tables.

Revision ID: 015
Revises: 014
Create Date: 2026-05-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    def create_index_if_missing(name: str, table: str, columns: list[str]) -> None:
        existing = {idx["name"] for idx in inspector.get_indexes(table)}
        if name not in existing:
            op.create_index(name, table, columns)

    if "autonomous_missions" not in tables:
        op.create_table(
            "autonomous_missions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=True),
            sa.Column("mission_type", sa.String(), nullable=False, server_default="mixed"),
            sa.Column("status", sa.String(), nullable=False, server_default="paused"),
            sa.Column("target_urls_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("schedule_cron", sa.String(), nullable=True),
            sa.Column("timezone", sa.String(), nullable=False, server_default="UTC"),
            sa.Column("autonomy_level", sa.String(), nullable=False, server_default="draft_validate"),
            sa.Column("approval_policy", sa.String(), nullable=False, server_default="approval_required"),
            sa.Column("max_runtime_minutes", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("max_iterations", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_llm_budget_usd", sa.Float(), nullable=True),
            sa.Column("budget_used_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("latest_workflow_id", sa.String(), nullable=True),
            sa.Column("latest_run_id", sa.String(), nullable=True),
            sa.Column("last_run_at", sa.DateTime(), nullable=True),
            sa.Column("next_run_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("total_runs", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_findings", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        )
    create_index_if_missing("ix_autonomous_missions_project_status", "autonomous_missions", ["project_id", "status"])
    create_index_if_missing("ix_autonomous_missions_project_type", "autonomous_missions", ["project_id", "mission_type"])
    create_index_if_missing("ix_autonomous_missions_project_id", "autonomous_missions", ["project_id"])
    create_index_if_missing("ix_autonomous_missions_mission_type", "autonomous_missions", ["mission_type"])
    create_index_if_missing("ix_autonomous_missions_status", "autonomous_missions", ["status"])

    if "autonomous_mission_runs" not in tables:
        op.create_table(
            "autonomous_mission_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("mission_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("workflow_id", sa.String(), nullable=True),
            sa.Column("mission_type", sa.String(), nullable=False, server_default="mixed"),
            sa.Column("trigger_type", sa.String(), nullable=False, server_default="temporal"),
            sa.Column("status", sa.String(), nullable=False, server_default="queued"),
            sa.Column("current_stage", sa.String(), nullable=True),
            sa.Column("summary_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("artifacts_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("budget_used_usd", sa.Float(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["mission_id"], ["autonomous_missions.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        )
    create_index_if_missing("ix_autonomous_runs_mission_created", "autonomous_mission_runs", ["mission_id", "created_at"])
    create_index_if_missing("ix_autonomous_runs_project_status", "autonomous_mission_runs", ["project_id", "status"])
    create_index_if_missing("ix_autonomous_runs_workflow", "autonomous_mission_runs", ["workflow_id"])
    create_index_if_missing("ix_autonomous_mission_runs_mission_id", "autonomous_mission_runs", ["mission_id"])
    create_index_if_missing("ix_autonomous_mission_runs_project_id", "autonomous_mission_runs", ["project_id"])
    create_index_if_missing("ix_autonomous_mission_runs_status", "autonomous_mission_runs", ["status"])

    if "autonomous_findings" not in tables:
        op.create_table(
            "autonomous_findings",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("mission_id", sa.String(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("finding_type", sa.String(), nullable=False),
            sa.Column("severity", sa.String(), nullable=False, server_default="medium"),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="open"),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0.7"),
            sa.Column("dedupe_key", sa.String(), nullable=False),
            sa.Column("evidence_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("source_type", sa.String(), nullable=True),
            sa.Column("source_id", sa.String(), nullable=True),
            sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("external_issue_url", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["mission_id"], ["autonomous_missions.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["autonomous_mission_runs.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        )
    create_index_if_missing("ix_autonomous_findings_project_status", "autonomous_findings", ["project_id", "status"])
    create_index_if_missing("ix_autonomous_findings_mission_created", "autonomous_findings", ["mission_id", "created_at"])
    create_index_if_missing("ix_autonomous_findings_dedupe", "autonomous_findings", ["project_id", "dedupe_key"])
    create_index_if_missing("ix_autonomous_findings_mission_id", "autonomous_findings", ["mission_id"])
    create_index_if_missing("ix_autonomous_findings_run_id", "autonomous_findings", ["run_id"])
    create_index_if_missing("ix_autonomous_findings_project_id", "autonomous_findings", ["project_id"])
    create_index_if_missing("ix_autonomous_findings_finding_type", "autonomous_findings", ["finding_type"])
    create_index_if_missing("ix_autonomous_findings_status", "autonomous_findings", ["status"])
    create_index_if_missing("ix_autonomous_findings_dedupe_key", "autonomous_findings", ["dedupe_key"])

    if "autonomous_approvals" not in tables:
        op.create_table(
            "autonomous_approvals",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("mission_id", sa.String(), nullable=False),
            sa.Column("run_id", sa.String(), nullable=True),
            sa.Column("finding_id", sa.String(), nullable=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("action_type", sa.String(), nullable=False, server_default="external_issue"),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("requested_payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("response_json", sa.Text(), nullable=True),
            sa.Column("decided_by", sa.String(), nullable=True),
            sa.Column("requested_at", sa.DateTime(), nullable=False),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["mission_id"], ["autonomous_missions.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["autonomous_mission_runs.id"]),
            sa.ForeignKeyConstraint(["finding_id"], ["autonomous_findings.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        )
    create_index_if_missing("ix_autonomous_approvals_project_status", "autonomous_approvals", ["project_id", "status"])
    create_index_if_missing("ix_autonomous_approvals_mission_status", "autonomous_approvals", ["mission_id", "status"])
    create_index_if_missing("ix_autonomous_approvals_mission_id", "autonomous_approvals", ["mission_id"])
    create_index_if_missing("ix_autonomous_approvals_run_id", "autonomous_approvals", ["run_id"])
    create_index_if_missing("ix_autonomous_approvals_finding_id", "autonomous_approvals", ["finding_id"])
    create_index_if_missing("ix_autonomous_approvals_project_id", "autonomous_approvals", ["project_id"])
    create_index_if_missing("ix_autonomous_approvals_status", "autonomous_approvals", ["status"])


def downgrade() -> None:
    op.drop_table("autonomous_approvals")
    op.drop_table("autonomous_findings")
    op.drop_table("autonomous_mission_runs")
    op.drop_table("autonomous_missions")
