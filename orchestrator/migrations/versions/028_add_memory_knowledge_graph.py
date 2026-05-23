"""Add memory knowledge graph.

Revision ID: 028
Revises: 027
Create Date: 2026-05-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "028"
down_revision: str | None = "027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name: str) -> set[str]:
    return {idx["name"] for idx in sa.inspect(op.get_bind()).get_indexes(table_name)}


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str], *, unique: bool = False) -> None:
    if index_name not in _index_names(table_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    tables = _table_names()

    if "memory_graph_nodes" not in tables:
        op.create_table(
            "memory_graph_nodes",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("node_type", sa.String(), nullable=False),
            sa.Column("label", sa.Text(), nullable=False),
            sa.Column("memory_id", sa.String(), nullable=True),
            sa.Column("entity_key", sa.String(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0.7"),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("extra_data", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["memory_id"], ["agent_memories.id"]),
            sa.UniqueConstraint("project_id", "node_type", "entity_key", name="uq_memory_graph_node_identity"),
        )

    if "memory_graph_edges" not in tables:
        op.create_table(
            "memory_graph_edges",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=True),
            sa.Column("source_node_id", sa.String(), nullable=False),
            sa.Column("target_node_id", sa.String(), nullable=False),
            sa.Column("relationship_type", sa.String(), nullable=False),
            sa.Column("weight", sa.Float(), nullable=False, server_default="0.7"),
            sa.Column("evidence_memory_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("extra_data", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.ForeignKeyConstraint(["source_node_id"], ["memory_graph_nodes.id"]),
            sa.ForeignKeyConstraint(["target_node_id"], ["memory_graph_nodes.id"]),
            sa.ForeignKeyConstraint(["evidence_memory_id"], ["agent_memories.id"]),
            sa.UniqueConstraint(
                "project_id",
                "source_node_id",
                "target_node_id",
                "relationship_type",
                name="uq_memory_graph_edge_identity",
            ),
        )

    _create_index_if_missing("memory_graph_nodes", "ix_memory_graph_nodes_project_type", ["project_id", "node_type"])
    _create_index_if_missing("memory_graph_nodes", "ix_memory_graph_nodes_project_status", ["project_id", "status"])
    _create_index_if_missing("memory_graph_nodes", "ix_memory_graph_nodes_memory", ["memory_id"])
    _create_index_if_missing(
        "memory_graph_edges",
        "ix_memory_graph_edges_project_type",
        ["project_id", "relationship_type"],
    )
    _create_index_if_missing("memory_graph_edges", "ix_memory_graph_edges_source", ["source_node_id"])
    _create_index_if_missing("memory_graph_edges", "ix_memory_graph_edges_target", ["target_node_id"])
    _create_index_if_missing("memory_graph_edges", "ix_memory_graph_edges_evidence", ["evidence_memory_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_graph_edges_evidence", table_name="memory_graph_edges")
    op.drop_index("ix_memory_graph_edges_target", table_name="memory_graph_edges")
    op.drop_index("ix_memory_graph_edges_source", table_name="memory_graph_edges")
    op.drop_index("ix_memory_graph_edges_project_type", table_name="memory_graph_edges")
    op.drop_index("ix_memory_graph_nodes_memory", table_name="memory_graph_nodes")
    op.drop_index("ix_memory_graph_nodes_project_status", table_name="memory_graph_nodes")
    op.drop_index("ix_memory_graph_nodes_project_type", table_name="memory_graph_nodes")
    op.drop_table("memory_graph_edges")
    op.drop_table("memory_graph_nodes")
