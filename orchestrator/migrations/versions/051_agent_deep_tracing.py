"""Add agent deep tracing tables.

Revision ID: 051
Revises: 050
Create Date: 2026-06-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "051"
down_revision: str | None = "050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    if index_name not in _indexes(table_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    tables = _tables()
    if "agent_trace_snapshots" not in tables:
        op.create_table(
            "agent_trace_snapshots",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("agent_task_id", sa.String(), nullable=True),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("runtime", sa.String(), nullable=False, server_default="claude_sdk"),
            sa.Column("model", sa.String(), nullable=True),
            sa.Column("model_tier", sa.String(), nullable=True),
            sa.Column("allowed_tools_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("prompt_hash", sa.String(), nullable=True),
            sa.Column("context_hash", sa.String(), nullable=True),
            sa.Column("memory_block_hash", sa.String(), nullable=True),
            sa.Column("prompt_preview", sa.Text(), nullable=False, server_default=""),
            sa.Column("memory_preview", sa.Text(), nullable=False, server_default=""),
            sa.Column("prompt_artifact_path", sa.String(), nullable=True),
            sa.Column("context_artifact_path", sa.String(), nullable=True),
            sa.Column("test_data_refs_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("runtime_diagnostics", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["agentrun.id"]),
            sa.UniqueConstraint("run_id", "attempt", name="uq_agent_trace_snapshots_run_attempt"),
        )

    if "agent_trace_spans" not in _tables():
        op.create_table(
            "agent_trace_spans",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("trace_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("parent_span_id", sa.String(), nullable=True),
            sa.Column("agent_run_event_id", sa.String(), nullable=True),
            sa.Column("autonomous_mission_id", sa.String(), nullable=True),
            sa.Column("autonomous_work_item_id", sa.String(), nullable=True),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("span_type", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False, server_default=""),
            sa.Column("level", sa.String(), nullable=False, server_default="info"),
            sa.Column("message", sa.Text(), nullable=False, server_default=""),
            sa.Column("tool_name", sa.String(), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=True),
            sa.Column("duration_ms", sa.Float(), nullable=True),
            sa.Column("content_hash", sa.String(), nullable=True),
            sa.Column("input_preview", sa.JSON(), nullable=True),
            sa.Column("output_preview", sa.JSON(), nullable=True),
            sa.Column("artifact_path", sa.String(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["trace_id"], ["agent_trace_snapshots.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["agentrun.id"]),
            sa.ForeignKeyConstraint(["parent_span_id"], ["agent_trace_spans.id"]),
            sa.ForeignKeyConstraint(["agent_run_event_id"], ["agent_run_events.id"]),
        )

    _create_index_if_missing("agent_trace_snapshots", "ix_agent_trace_snapshots_run_created", ["run_id", "created_at"])
    _create_index_if_missing("agent_trace_snapshots", "ix_agent_trace_snapshots_project_created", ["project_id", "created_at"])
    _create_index_if_missing("agent_trace_snapshots", "ix_agent_trace_snapshots_agent_task", ["agent_task_id"])
    _create_index_if_missing("agent_trace_spans", "ix_agent_trace_spans_trace_sequence", ["trace_id", "sequence"])
    _create_index_if_missing("agent_trace_spans", "ix_agent_trace_spans_run_created", ["run_id", "created_at"])
    _create_index_if_missing("agent_trace_spans", "ix_agent_trace_spans_project_created", ["project_id", "created_at"])
    _create_index_if_missing("agent_trace_spans", "ix_agent_trace_spans_type_created", ["span_type", "created_at"])
    _create_index_if_missing("agent_trace_spans", "ix_agent_trace_spans_tool", ["tool_name"])
    _create_index_if_missing("agent_trace_spans", "ix_agent_trace_spans_agent_event", ["agent_run_event_id"])


def downgrade() -> None:
    if "agent_trace_spans" in _tables():
        for index_name in [
            "ix_agent_trace_spans_agent_event",
            "ix_agent_trace_spans_tool",
            "ix_agent_trace_spans_type_created",
            "ix_agent_trace_spans_project_created",
            "ix_agent_trace_spans_run_created",
            "ix_agent_trace_spans_trace_sequence",
        ]:
            if index_name in _indexes("agent_trace_spans"):
                op.drop_index(index_name, table_name="agent_trace_spans")
        op.drop_table("agent_trace_spans")

    if "agent_trace_snapshots" in _tables():
        for index_name in [
            "ix_agent_trace_snapshots_agent_task",
            "ix_agent_trace_snapshots_project_created",
            "ix_agent_trace_snapshots_run_created",
        ]:
            if index_name in _indexes("agent_trace_snapshots"):
                op.drop_index(index_name, table_name="agent_trace_snapshots")
        op.drop_table("agent_trace_snapshots")
