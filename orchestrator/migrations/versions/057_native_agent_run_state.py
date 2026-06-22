"""Add native agent run state, notes, evidence, and findings.

Revision ID: 057
Revises: 056
Create Date: 2026-06-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "057"
down_revision: str | None = "056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _tables() -> set[str]:
    return set(_inspector().get_table_names())


def _columns(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {column["name"] for column in _inspector().get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {idx["name"] for idx in _inspector().get_indexes(table_name)}


def _unique_constraints(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {constraint["name"] for constraint in _inspector().get_unique_constraints(table_name)}


def _create_index_if_missing(table_name: str, name: str, columns: list[str]) -> None:
    if name not in _index_names(table_name):
        op.create_index(name, table_name, columns)


def _create_unique_if_missing(table_name: str, name: str, columns: list[str]) -> None:
    if name not in _unique_constraints(table_name):
        op.create_unique_constraint(name, table_name, columns)


def upgrade() -> None:
    if "agentrun" in _tables():
        columns = _columns("agentrun")
        for name, column in {
            "state_json": sa.Column("state_json", sa.Text(), nullable=True),
            "contract_status": sa.Column("contract_status", sa.String(), nullable=True),
            "finalization_status": sa.Column("finalization_status", sa.String(), nullable=True),
            "reporter_status": sa.Column("reporter_status", sa.String(), nullable=True),
            "verifier_status": sa.Column("verifier_status", sa.String(), nullable=True),
            "updated_at": sa.Column("updated_at", sa.DateTime(), nullable=True),
        }.items():
            if name not in columns:
                op.add_column("agentrun", column)
        _create_index_if_missing("agentrun", "ix_agentrun_contract_status", ["contract_status"])
        _create_index_if_missing("agentrun", "ix_agentrun_finalization_status", ["finalization_status"])
        _create_index_if_missing("agentrun", "ix_agentrun_reporter_status", ["reporter_status"])
        _create_index_if_missing("agentrun", "ix_agentrun_verifier_status", ["verifier_status"])
        _create_index_if_missing("agentrun", "ix_agentrun_updated_at", ["updated_at"])

    if "agent_run_events" in _tables():
        if "idempotency_key" not in _columns("agent_run_events"):
            op.add_column("agent_run_events", sa.Column("idempotency_key", sa.String(), nullable=True))
        _create_index_if_missing("agent_run_events", "ix_agent_run_events_idempotency_key", ["idempotency_key"])
        _create_unique_if_missing(
            "agent_run_events",
            "uq_agent_run_events_run_idempotency_key",
            ["run_id", "idempotency_key"],
        )

    if "agent_run_task_contracts" not in _tables():
        op.create_table(
            "agent_run_task_contracts",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("objective", sa.Text(), nullable=False),
            sa.Column("scope", sa.Text(), nullable=True),
            sa.Column("success_criteria_json", sa.Text(), nullable=True, server_default="[]"),
            sa.Column("allowed_tools_json", sa.Text(), nullable=True, server_default="[]"),
            sa.Column("output_expectations_json", sa.Text(), nullable=True, server_default="{}"),
            sa.Column("source", sa.String(), nullable=False, server_default="runtime"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["agentrun.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", name="uq_agent_run_task_contracts_run_id"),
        )
    _create_index_if_missing("agent_run_task_contracts", "ix_agent_run_task_contracts_run_id", ["run_id"])
    _create_index_if_missing(
        "agent_run_task_contracts",
        "ix_agent_run_task_contracts_project_created",
        ["project_id", "created_at"],
    )

    if "agent_run_work_items" not in _tables():
        op.create_table(
            "agent_run_work_items",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("parent_work_item_id", sa.String(), nullable=True),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="open"),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("owner", sa.String(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["agentrun.id"]),
            sa.ForeignKeyConstraint(["parent_work_item_id"], ["agent_run_work_items.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("agent_run_work_items", "ix_agent_run_work_items_run_status", ["run_id", "status"])
    _create_index_if_missing(
        "agent_run_work_items",
        "ix_agent_run_work_items_project_created",
        ["project_id", "created_at"],
    )

    if "agent_run_notes" not in _tables():
        op.create_table(
            "agent_run_notes",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("agent_task_id", sa.String(), nullable=True),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("note_type", sa.String(), nullable=False, server_default="observation"),
            sa.Column("level", sa.String(), nullable=False, server_default="info"),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("source", sa.String(), nullable=True),
            sa.Column("tags_json", sa.Text(), nullable=True, server_default="[]"),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("url", sa.String(), nullable=True),
            sa.Column("tool_name", sa.String(), nullable=True),
            sa.Column("artifact_path", sa.String(), nullable=True),
            sa.Column("actionable", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("related_event_sequence", sa.Integer(), nullable=True),
            sa.Column("related_trace_span_id", sa.String(), nullable=True),
            sa.Column("idempotency_key", sa.String(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["agentrun.id"]),
            sa.ForeignKeyConstraint(["related_trace_span_id"], ["agent_trace_spans.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", "sequence", name="uq_agent_run_notes_run_sequence"),
            sa.UniqueConstraint("run_id", "idempotency_key", name="uq_agent_run_notes_run_idempotency_key"),
        )
    for name, columns in {
        "ix_agent_run_notes_run_sequence": ["run_id", "sequence"],
        "ix_agent_run_notes_project_created": ["project_id", "created_at"],
        "ix_agent_run_notes_type_level": ["note_type", "level"],
        "ix_agent_run_notes_agent_task_id": ["agent_task_id"],
        "ix_agent_run_notes_note_type": ["note_type"],
        "ix_agent_run_notes_level": ["level"],
        "ix_agent_run_notes_source": ["source"],
        "ix_agent_run_notes_tool_name": ["tool_name"],
        "ix_agent_run_notes_actionable": ["actionable"],
        "ix_agent_run_notes_idempotency_key": ["idempotency_key"],
    }.items():
        _create_index_if_missing("agent_run_notes", name, columns)

    if "agent_run_evidence" not in _tables():
        op.create_table(
            "agent_run_evidence",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("note_id", sa.String(), nullable=True),
            sa.Column("evidence_type", sa.String(), nullable=False, server_default="artifact"),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("stable_key", sa.String(), nullable=False),
            sa.Column("artifact_path", sa.String(), nullable=True),
            sa.Column("url", sa.String(), nullable=True),
            sa.Column("tool_name", sa.String(), nullable=True),
            sa.Column("trace_span_id", sa.String(), nullable=True),
            sa.Column("event_sequence", sa.Integer(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["agentrun.id"]),
            sa.ForeignKeyConstraint(["note_id"], ["agent_run_notes.id"]),
            sa.ForeignKeyConstraint(["trace_span_id"], ["agent_trace_spans.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", "stable_key", name="uq_agent_run_evidence_run_stable_key"),
        )
    for name, columns in {
        "ix_agent_run_evidence_run_kind": ["run_id", "evidence_type"],
        "ix_agent_run_evidence_project_created": ["project_id", "created_at"],
        "ix_agent_run_evidence_note_id": ["note_id"],
        "ix_agent_run_evidence_stable_key": ["stable_key"],
        "ix_agent_run_evidence_tool_name": ["tool_name"],
    }.items():
        _create_index_if_missing("agent_run_evidence", name, columns)

    if "agent_run_findings" not in _tables():
        op.create_table(
            "agent_run_findings",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("run_id", sa.String(), nullable=False),
            sa.Column("note_id", sa.String(), nullable=True),
            sa.Column("stable_key", sa.String(), nullable=False),
            sa.Column("title", sa.Text(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("severity", sa.String(), nullable=True),
            sa.Column("confidence", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="candidate"),
            sa.Column("evidence_ids_json", sa.Text(), nullable=True, server_default="[]"),
            sa.Column("diagnostics_json", sa.Text(), nullable=True, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["run_id"], ["agentrun.id"]),
            sa.ForeignKeyConstraint(["note_id"], ["agent_run_notes.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", "stable_key", name="uq_agent_run_findings_run_stable_key"),
        )
    for name, columns in {
        "ix_agent_run_findings_run_status": ["run_id", "status"],
        "ix_agent_run_findings_project_created": ["project_id", "created_at"],
        "ix_agent_run_findings_note_id": ["note_id"],
        "ix_agent_run_findings_stable_key": ["stable_key"],
        "ix_agent_run_findings_severity": ["severity"],
        "ix_agent_run_findings_confidence": ["confidence"],
        "ix_agent_run_findings_status": ["status"],
    }.items():
        _create_index_if_missing("agent_run_findings", name, columns)


def downgrade() -> None:
    for table_name in (
        "agent_run_findings",
        "agent_run_evidence",
        "agent_run_notes",
        "agent_run_work_items",
        "agent_run_task_contracts",
    ):
        if table_name in _tables():
            op.drop_table(table_name)

    if "agent_run_events" in _tables():
        if "uq_agent_run_events_run_idempotency_key" in _unique_constraints("agent_run_events"):
            op.drop_constraint("uq_agent_run_events_run_idempotency_key", "agent_run_events", type_="unique")
        if "ix_agent_run_events_idempotency_key" in _index_names("agent_run_events"):
            op.drop_index("ix_agent_run_events_idempotency_key", table_name="agent_run_events")
        if "idempotency_key" in _columns("agent_run_events"):
            op.drop_column("agent_run_events", "idempotency_key")

    if "agentrun" in _tables():
        for index_name in (
            "ix_agentrun_updated_at",
            "ix_agentrun_verifier_status",
            "ix_agentrun_reporter_status",
            "ix_agentrun_finalization_status",
            "ix_agentrun_contract_status",
        ):
            if index_name in _index_names("agentrun"):
                op.drop_index(index_name, table_name="agentrun")
        for column_name in (
            "updated_at",
            "verifier_status",
            "reporter_status",
            "finalization_status",
            "contract_status",
            "state_json",
        ):
            if column_name in _columns("agentrun"):
                op.drop_column("agentrun", column_name)
