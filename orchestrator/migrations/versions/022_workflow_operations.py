"""Add workflow operations tables and runtime fields.

Revision ID: 022
Revises: 021
Create Date: 2026-05-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "022"
down_revision: str | None = "021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in _columns(table_name):
        op.add_column(table_name, column)


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    if index_name not in _indexes(table_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    tables = _tables()

    if "workflow_definition_revisions" not in tables:
        op.create_table(
            "workflow_definition_revisions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("definition_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=False, server_default=""),
            sa.Column("steps_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("change_summary", sa.String(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["definition_id"], ["workflow_definitions.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.UniqueConstraint("definition_id", "version", name="uq_workflow_revision_definition_version"),
        )
    _create_index_if_missing("workflow_definition_revisions", "ix_workflow_revisions_definition_version", ["definition_id", "version"])
    _create_index_if_missing("workflow_definition_revisions", "ix_workflow_revisions_project_created", ["project_id", "created_at"])

    run_fields = [
        sa.Column("revision_id", sa.String(), nullable=True),
        sa.Column("definition_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("recovery_policy_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("trigger_type", sa.String(), nullable=False, server_default="manual"),
        sa.Column("trigger_id", sa.String(), nullable=True),
        sa.Column("temporal_workflow_id", sa.String(), nullable=True),
        sa.Column("temporal_run_id", sa.String(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("pause_reason", sa.String(), nullable=True),
    ]
    for column in run_fields:
        _add_column_if_missing("workflow_runs", column)
    _create_index_if_missing("workflow_runs", "ix_workflow_runs_revision_id", ["revision_id"])
    _create_index_if_missing("workflow_runs", "ix_workflow_runs_trigger_id", ["trigger_id"])
    _create_index_if_missing("workflow_runs", "ix_workflow_runs_temporal_workflow_id", ["temporal_workflow_id"])

    step_fields = [
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("retry_backoff_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovery_action", sa.String(), nullable=False, server_default="fail"),
        sa.Column("skipped_reason", sa.String(), nullable=True),
    ]
    for column in step_fields:
        _add_column_if_missing("workflow_run_steps", column)

    if "workflow_schedules" not in tables:
        op.create_table(
            "workflow_schedules",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("definition_id", sa.String(), nullable=False),
            sa.Column("revision_id", sa.String(), nullable=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=False, server_default=""),
            sa.Column("cron_expression", sa.String(), nullable=False),
            sa.Column("timezone", sa.String(), nullable=False, server_default="UTC"),
            sa.Column("inputs_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("start_step_key", sa.String(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("notify_on_completion", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("notify_on_failure", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("notify_on_review_needed", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("next_run_at", sa.DateTime(), nullable=True),
            sa.Column("last_run_at", sa.DateTime(), nullable=True),
            sa.Column("last_run_status", sa.String(), nullable=True),
            sa.Column("last_run_id", sa.String(), nullable=True),
            sa.Column("total_executions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("successful_executions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_executions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("avg_duration_seconds", sa.Float(), nullable=True),
            sa.Column("created_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["definition_id"], ["workflow_definitions.id"]),
            sa.ForeignKeyConstraint(["revision_id"], ["workflow_definition_revisions.id"]),
            sa.ForeignKeyConstraint(["last_run_id"], ["workflow_runs.id"]),
        )
    _create_index_if_missing("workflow_schedules", "ix_workflow_schedules_project_enabled", ["project_id", "enabled"])
    _create_index_if_missing("workflow_schedules", "ix_workflow_schedules_definition_enabled", ["definition_id", "enabled"])

    if "workflow_schedule_executions" not in tables:
        op.create_table(
            "workflow_schedule_executions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("schedule_id", sa.String(), nullable=False),
            sa.Column("workflow_run_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("trigger_type", sa.String(), nullable=False, server_default="schedule"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["schedule_id"], ["workflow_schedules.id"]),
            sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"]),
        )
    _create_index_if_missing("workflow_schedule_executions", "ix_workflow_schedule_exec_schedule_created", ["schedule_id", "created_at"])
    _create_index_if_missing("workflow_schedule_executions", "ix_workflow_schedule_exec_run", ["workflow_run_id"])

    if "workflow_events" not in tables:
        op.create_table(
            "workflow_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("definition_id", sa.String(), nullable=True),
            sa.Column("run_id", sa.String(), nullable=True),
            sa.Column("step_id", sa.Integer(), nullable=True),
            sa.Column("schedule_id", sa.String(), nullable=True),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("severity", sa.String(), nullable=False, server_default="info"),
            sa.Column("message", sa.Text(), nullable=False, server_default=""),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["definition_id"], ["workflow_definitions.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"]),
            sa.ForeignKeyConstraint(["step_id"], ["workflow_run_steps.id"]),
            sa.ForeignKeyConstraint(["schedule_id"], ["workflow_schedules.id"]),
        )
    _create_index_if_missing("workflow_events", "ix_workflow_events_project_created", ["project_id", "created_at"])
    _create_index_if_missing("workflow_events", "ix_workflow_events_run_created", ["run_id", "created_at"])
    _create_index_if_missing("workflow_events", "ix_workflow_events_type_created", ["event_type", "created_at"])

    if "workflow_notifications" not in tables:
        op.create_table(
            "workflow_notifications",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("event_id", sa.String(), nullable=True),
            sa.Column("channel", sa.String(), nullable=False, server_default="in_app"),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("target_url", sa.String(), nullable=True),
            sa.Column("read_at", sa.DateTime(), nullable=True),
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["event_id"], ["workflow_events.id"]),
        )
    _create_index_if_missing("workflow_notifications", "ix_workflow_notifications_project_read", ["project_id", "read_at"])
    _create_index_if_missing("workflow_notifications", "ix_workflow_notifications_event", ["event_id"])


def downgrade() -> None:
    for table in (
        "workflow_notifications",
        "workflow_events",
        "workflow_schedule_executions",
        "workflow_schedules",
        "workflow_definition_revisions",
    ):
        if table in _tables():
            op.drop_table(table)

    for table_name, columns in {
        "workflow_run_steps": ["skipped_reason", "recovery_action", "retry_backoff_seconds", "max_attempts", "attempt_count"],
        "workflow_runs": [
            "pause_reason",
            "heartbeat_at",
            "temporal_run_id",
            "temporal_workflow_id",
            "trigger_id",
            "trigger_type",
            "recovery_policy_json",
            "definition_version",
            "revision_id",
        ],
    }.items():
        existing = _columns(table_name)
        for column_name in columns:
            if column_name in existing:
                op.drop_column(table_name, column_name)
