"""Harden project isolation uniqueness.

Revision ID: 053
Revises: 052
Create Date: 2026-06-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "053"
down_revision: str | None = "052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_PROJECT_ID = "default"


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _dialect() -> str:
    return op.get_bind().dialect.name


def _tables() -> set[str]:
    return set(_inspector().get_table_names())


def _columns(table_name: str) -> dict[str, dict[str, object]]:
    if table_name not in _tables():
        return {}
    return {col["name"]: col for col in _inspector().get_columns(table_name)}


def _indexes(table_name: str) -> dict[str, dict[str, object]]:
    if table_name not in _tables():
        return {}
    return {idx["name"]: idx for idx in _inspector().get_indexes(table_name)}


def _unique_constraints(table_name: str) -> set[str]:
    if table_name not in _tables():
        return set()
    return {constraint["name"] for constraint in _inspector().get_unique_constraints(table_name) if constraint["name"]}


def _pk_columns(table_name: str) -> list[str]:
    if table_name not in _tables():
        return []
    return list(_inspector().get_pk_constraint(table_name).get("constrained_columns") or [])


def _ensure_default_project() -> None:
    if "projects" not in _tables():
        return
    columns = _columns("projects")
    insert_columns = ["id"]
    if "name" in columns:
        insert_columns.append("name")
    if "description" in columns:
        insert_columns.append("description")
    if "created_at" in columns:
        insert_columns.append("created_at")
    if "last_active" in columns:
        insert_columns.append("last_active")

    select_values = []
    for column in insert_columns:
        if column in {"created_at", "last_active"}:
            select_values.append("CURRENT_TIMESTAMP")
        else:
            select_values.append(f":{column}")

    op.get_bind().execute(
        sa.text(
            f"""
            INSERT INTO projects ({", ".join(insert_columns)})
            SELECT {", ".join(select_values)}
            WHERE NOT EXISTS (SELECT 1 FROM projects WHERE id = :id)
            """
        ),
        {"id": DEFAULT_PROJECT_ID, "name": "Default Project", "description": "Default project for legacy unscoped rows"},
    )


def _add_project_id_if_missing(table_name: str) -> None:
    if table_name not in _tables():
        return
    if "project_id" not in _columns(table_name):
        op.add_column(
            table_name,
            sa.Column("project_id", sa.String(), nullable=False, server_default=DEFAULT_PROJECT_ID),
        )


def _backfill_project_id(table_name: str) -> None:
    if table_name in _tables() and "project_id" in _columns(table_name):
        op.execute(sa.text(f"UPDATE {table_name} SET project_id = :project_id WHERE project_id IS NULL").bindparams(project_id=DEFAULT_PROJECT_ID))


def _set_project_id_not_null(table_name: str) -> None:
    if table_name not in _tables() or "project_id" not in _columns(table_name):
        return
    if _columns(table_name)["project_id"].get("nullable") is False:
        return
    if _dialect() == "sqlite":
        with op.batch_alter_table(table_name) as batch:
            batch.alter_column(
                "project_id",
                existing_type=sa.String(),
                nullable=False,
                server_default=DEFAULT_PROJECT_ID,
            )
    else:
        op.alter_column(
            table_name,
            "project_id",
            existing_type=sa.String(),
            nullable=False,
            server_default=DEFAULT_PROJECT_ID,
        )


def _ensure_project_id(table_name: str) -> None:
    _add_project_id_if_missing(table_name)
    _backfill_project_id(table_name)
    _set_project_id_not_null(table_name)


def _drop_index_if_exists(table_name: str, index_name: str) -> None:
    if index_name in _indexes(table_name):
        op.drop_index(index_name, table_name=table_name)


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str], *, unique: bool = False) -> None:
    if index_name not in _indexes(table_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _repair_sqlite_specmetadata() -> None:
    columns = _columns("specmetadata")
    legacy_columns = [
        name
        for name in (
            "project_id",
            "spec_name",
            "tags_json",
            "description",
            "author",
            "last_modified",
            "created_by",
            "last_modified_by",
        )
        if name in columns or name == "project_id"
    ]
    op.execute("ALTER TABLE specmetadata RENAME TO specmetadata_old")
    op.create_table(
        "specmetadata",
        sa.Column("project_id", sa.String(), nullable=False, server_default=DEFAULT_PROJECT_ID),
        sa.Column("spec_name", sa.String(), nullable=False),
        sa.Column("tags_json", sa.String(), nullable=False, server_default="[]"),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("author", sa.String(), nullable=True),
        sa.Column("last_modified", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("last_modified_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("project_id", "spec_name"),
    )
    select_columns = []
    for column in legacy_columns:
        if column == "project_id":
            if "project_id" in columns:
                select_columns.append(f"COALESCE(project_id, '{DEFAULT_PROJECT_ID}')")
            else:
                select_columns.append(f"'{DEFAULT_PROJECT_ID}'")
        else:
            select_columns.append(column)
    op.execute(
        f"""
        INSERT OR IGNORE INTO specmetadata ({", ".join(legacy_columns)})
        SELECT {", ".join(select_columns)}
        FROM specmetadata_old
        ORDER BY COALESCE(project_id, '{DEFAULT_PROJECT_ID}'), spec_name
        """
    )
    op.drop_table("specmetadata_old")
    _create_index_if_missing("specmetadata", "ix_specmetadata_project_id", ["project_id"])
    _create_index_if_missing("specmetadata", "ix_specmetadata_project_spec", ["project_id", "spec_name"])


def _repair_specmetadata() -> None:
    if "specmetadata" not in _tables():
        return
    _ensure_project_id("specmetadata")
    if _pk_columns("specmetadata") == ["project_id", "spec_name"]:
        return
    if _dialect() == "sqlite":
        _repair_sqlite_specmetadata()
        return

    pk = _inspector().get_pk_constraint("specmetadata")
    if pk.get("name"):
        op.drop_constraint(pk["name"], "specmetadata", type_="primary")
    op.create_primary_key("pk_specmetadata", "specmetadata", ["project_id", "spec_name"])


def _repair_test_patterns() -> None:
    if "test_patterns" not in _tables():
        return
    _ensure_project_id("test_patterns")
    if _indexes("test_patterns").get("ix_test_patterns_pattern_hash", {}).get("unique"):
        _drop_index_if_exists("test_patterns", "ix_test_patterns_pattern_hash")
    _create_index_if_missing("test_patterns", "ix_test_patterns_pattern_hash", ["pattern_hash"])
    op.execute(
        """
        DELETE FROM test_patterns
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM test_patterns
            GROUP BY project_id, pattern_hash
        )
        """
    )
    _create_index_if_missing(
        "test_patterns",
        "uq_test_patterns_project_pattern_hash",
        ["project_id", "pattern_hash"],
        unique=True,
    )


def _repair_coverage_tables() -> None:
    for table_name, indexes in {
        "coverage_metrics": [
            ("ix_coverage_metrics_project_metric", ["project_id", "metric_type"]),
        ],
        "discovered_elements": [
            ("ix_discovered_elements_project_url", ["project_id", "url"]),
        ],
        "coverage_gaps": [
            ("ix_coverage_gaps_project_resolved", ["project_id", "resolved"]),
        ],
    }.items():
        if table_name not in _tables():
            continue
        _ensure_project_id(table_name)
        for index_name, columns in indexes:
            _create_index_if_missing(table_name, index_name, columns)


def _repair_application_map() -> None:
    if "application_map" not in _tables():
        return
    _ensure_project_id("application_map")
    if "app_surface_key" not in _columns("application_map"):
        op.add_column("application_map", sa.Column("app_surface_key", sa.String(), nullable=True))
    if _indexes("application_map").get("ix_application_map_url", {}).get("unique"):
        _drop_index_if_exists("application_map", "ix_application_map_url")
    _create_index_if_missing("application_map", "ix_application_map_url", ["url"])
    _create_index_if_missing("application_map", "ix_application_map_project_surface", ["project_id", "app_surface_key"])
    op.execute(
        """
        DELETE FROM application_map
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM application_map
            GROUP BY project_id, url
        )
        """
    )
    if "uq_application_map_project_url" not in _unique_constraints("application_map"):
        _create_index_if_missing(
            "application_map",
            "uq_application_map_project_url",
            ["project_id", "url"],
            unique=True,
        )


def upgrade() -> None:
    _ensure_default_project()
    _repair_specmetadata()
    _repair_coverage_tables()
    _repair_test_patterns()
    _repair_application_map()


def downgrade() -> None:
    for table_name, index_name in (
        ("application_map", "uq_application_map_project_url"),
        ("test_patterns", "uq_test_patterns_project_pattern_hash"),
        ("coverage_metrics", "ix_coverage_metrics_project_metric"),
        ("discovered_elements", "ix_discovered_elements_project_url"),
        ("coverage_gaps", "ix_coverage_gaps_project_resolved"),
    ):
        _drop_index_if_exists(table_name, index_name)
    if "application_map" in _tables() and "ix_application_map_url" in _indexes("application_map"):
        _drop_index_if_exists("application_map", "ix_application_map_url")
        _create_index_if_missing("application_map", "ix_application_map_url", ["url"], unique=True)
    if "test_patterns" in _tables() and "ix_test_patterns_pattern_hash" in _indexes("test_patterns"):
        _drop_index_if_exists("test_patterns", "ix_test_patterns_pattern_hash")
        _create_index_if_missing("test_patterns", "ix_test_patterns_pattern_hash", ["pattern_hash"], unique=True)
