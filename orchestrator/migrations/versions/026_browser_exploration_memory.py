"""Add browser exploration memory.

Revision ID: 026
Revises: 025
Create Date: 2026-05-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "026"
down_revision: str | None = "025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    if index_name not in _index_names(table_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    tables = _table_names()

    if "browser_page_states" not in tables:
        op.create_table(
            "browser_page_states",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("session_id", sa.String(), nullable=True),
            sa.Column("page_key", sa.String(), nullable=False),
            sa.Column("state_key", sa.String(), nullable=False),
            sa.Column("url", sa.String(), nullable=False),
            sa.Column("url_template", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("page_type", sa.String(), nullable=True),
            sa.Column("auth_state", sa.String(), nullable=True),
            sa.Column("viewport", sa.String(), nullable=True),
            sa.Column("locale", sa.String(), nullable=True),
            sa.Column("exact_hash", sa.String(), nullable=False),
            sa.Column("simhash", sa.String(), nullable=True),
            sa.Column("embedding_id", sa.String(), nullable=True),
            sa.Column("snapshot_ref", sa.String(), nullable=True),
            sa.Column("canonical_json", sa.JSON(), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("visit_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("novelty_score", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("importance_score", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("decay_score", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["session_id"], ["exploration_sessions.id"]),
            sa.UniqueConstraint("project_id", "state_key", name="uq_browser_page_states_project_state"),
        )

    if "browser_elements" not in tables:
        op.create_table(
            "browser_elements",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("state_id", sa.String(), nullable=False),
            sa.Column("element_key", sa.String(), nullable=False),
            sa.Column("role", sa.String(), nullable=True),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("text", sa.String(), nullable=True),
            sa.Column("element_type", sa.String(), nullable=True),
            sa.Column("locator_candidates_json", sa.JSON(), nullable=True),
            sa.Column("attributes_json", sa.JSON(), nullable=True),
            sa.Column("form_context_json", sa.JSON(), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("seen_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("tested_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("importance_score", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("stability_score", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["state_id"], ["browser_page_states.id"]),
            sa.UniqueConstraint("project_id", "state_id", "element_key", name="uq_browser_elements_project_state_key"),
        )

    if "browser_transitions" not in tables:
        op.create_table(
            "browser_transitions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("session_id", sa.String(), nullable=True),
            sa.Column("from_state_id", sa.String(), nullable=False),
            sa.Column("to_state_id", sa.String(), nullable=False),
            sa.Column("action_type", sa.String(), nullable=False),
            sa.Column("action_signature", sa.String(), nullable=False),
            sa.Column("element_id", sa.String(), nullable=True),
            sa.Column("action_value_kind", sa.String(), nullable=True),
            sa.Column("transition_type", sa.String(), nullable=False, server_default="interaction"),
            sa.Column("api_signature_json", sa.JSON(), nullable=True),
            sa.Column("success_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("avg_duration_ms", sa.Float(), nullable=False, server_default="0"),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("novelty_at_discovery", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("risk_level", sa.String(), nullable=False, server_default="low"),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["session_id"], ["exploration_sessions.id"]),
            sa.ForeignKeyConstraint(["from_state_id"], ["browser_page_states.id"]),
            sa.ForeignKeyConstraint(["to_state_id"], ["browser_page_states.id"]),
            sa.ForeignKeyConstraint(["element_id"], ["browser_elements.id"]),
            sa.UniqueConstraint(
                "project_id",
                "from_state_id",
                "to_state_id",
                "action_signature",
                name="uq_browser_transitions_project_signature",
            ),
        )

    if "browser_frontier_items" not in tables:
        op.create_table(
            "browser_frontier_items",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("state_id", sa.String(), nullable=False),
            sa.Column("element_id", sa.String(), nullable=True),
            sa.Column("action_type", sa.String(), nullable=False),
            sa.Column("priority_score", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("status", sa.String(), nullable=False, server_default="queued"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_attempted_at", sa.DateTime(), nullable=True),
            sa.Column("next_due_at", sa.DateTime(), nullable=True),
            sa.Column("block_reason", sa.String(), nullable=True),
            sa.Column("lease_owner", sa.String(), nullable=True),
            sa.Column("lease_until", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["state_id"], ["browser_page_states.id"]),
            sa.ForeignKeyConstraint(["element_id"], ["browser_elements.id"]),
            sa.UniqueConstraint("project_id", "state_id", "element_id", "action_type", name="uq_browser_frontier_action"),
        )

    if "browser_state_clusters" not in tables:
        op.create_table(
            "browser_state_clusters",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("cluster_key", sa.String(), nullable=False),
            sa.Column("representative_state_id", sa.String(), nullable=True),
            sa.Column("member_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("embedding_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["representative_state_id"], ["browser_page_states.id"]),
            sa.UniqueConstraint("project_id", "cluster_key", name="uq_browser_state_clusters_project_key"),
        )

    _create_index_if_missing("browser_page_states", "ix_browser_page_states_project_page", ["project_id", "page_key"])
    _create_index_if_missing("browser_page_states", "ix_browser_page_states_project_state", ["project_id", "state_key"])
    _create_index_if_missing("browser_page_states", "ix_browser_page_states_project_seen", ["project_id", "last_seen_at"])
    _create_index_if_missing("browser_elements", "ix_browser_elements_project_state", ["project_id", "state_id"])
    _create_index_if_missing("browser_elements", "ix_browser_elements_project_key", ["project_id", "element_key"])
    _create_index_if_missing("browser_elements", "ix_browser_elements_project_role", ["project_id", "role"])
    _create_index_if_missing("browser_transitions", "ix_browser_transitions_project_from", ["project_id", "from_state_id"])
    _create_index_if_missing("browser_transitions", "ix_browser_transitions_project_to", ["project_id", "to_state_id"])
    _create_index_if_missing("browser_transitions", "ix_browser_transitions_project_seen", ["project_id", "last_seen_at"])
    _create_index_if_missing(
        "browser_frontier_items",
        "ix_browser_frontier_project_status_priority",
        ["project_id", "status", "priority_score"],
    )
    _create_index_if_missing("browser_frontier_items", "ix_browser_frontier_project_due", ["project_id", "next_due_at"])
    _create_index_if_missing("browser_state_clusters", "ix_browser_state_clusters_project_key", ["project_id", "cluster_key"])


def downgrade() -> None:
    for table_name, index_name in (
        ("browser_state_clusters", "ix_browser_state_clusters_project_key"),
        ("browser_frontier_items", "ix_browser_frontier_project_due"),
        ("browser_frontier_items", "ix_browser_frontier_project_status_priority"),
        ("browser_transitions", "ix_browser_transitions_project_seen"),
        ("browser_transitions", "ix_browser_transitions_project_to"),
        ("browser_transitions", "ix_browser_transitions_project_from"),
        ("browser_elements", "ix_browser_elements_project_role"),
        ("browser_elements", "ix_browser_elements_project_key"),
        ("browser_elements", "ix_browser_elements_project_state"),
        ("browser_page_states", "ix_browser_page_states_project_seen"),
        ("browser_page_states", "ix_browser_page_states_project_state"),
        ("browser_page_states", "ix_browser_page_states_project_page"),
    ):
        if table_name in _table_names() and index_name in _index_names(table_name):
            op.drop_index(index_name, table_name=table_name)

    for table_name in (
        "browser_state_clusters",
        "browser_frontier_items",
        "browser_transitions",
        "browser_elements",
        "browser_page_states",
    ):
        if table_name in _table_names():
            op.drop_table(table_name)
