"""Shared project filtering helpers for API queries."""

from __future__ import annotations

from typing import Any


def apply_project_filter(statement: Any, model: Any, project_id: str | None) -> Any:
    """Apply Quorvex project filtering semantics to a SQLModel statement.

    The historical default project stored some rows with NULL project_id. Treat
    project_id=default as both explicit "default" and NULL so legacy rows stay
    visible in dashboards and analytics.
    """

    if not project_id:
        return statement
    if project_id == "default":
        return statement.where((model.project_id == project_id) | (model.project_id == None))
    return statement.where(model.project_id == project_id)
