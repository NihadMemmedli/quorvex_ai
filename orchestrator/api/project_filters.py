"""Shared project filtering helpers for API queries."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


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


def require_project_id(project_id: str | None) -> str:
    """Return a non-empty project id or raise the same status as validation gaps."""

    if not project_id:
        raise HTTPException(status_code=422, detail="project_id is required")
    return project_id


def project_matches(row_project_id: str | None, project_id: str) -> bool:
    """Strict object-route project match with legacy NULL rows in default only."""

    if project_id == "default":
        return row_project_id in (None, "default")
    return row_project_id == project_id


def get_project_row_or_404(
    session: Any,
    model: Any,
    object_id: Any,
    project_id: str,
    *,
    detail: str = "Object not found",
) -> Any:
    """Fetch an object by primary key and hide wrong-project rows behind 404."""

    row = session.get(model, object_id)
    if not row or not project_matches(getattr(row, "project_id", None), project_id):
        raise HTTPException(status_code=404, detail=detail)
    return row


def strict_project_filter(statement: Any, model: Any, project_id: str) -> Any:
    """Apply required tenant filtering for object/action lookups."""

    return apply_project_filter(statement, model, require_project_id(project_id))


PROJECT_ROUTE_CONTRACTS: dict[str, dict[str, int | str]] = {
    "workflows.object_actions": {
        "missing_project_id": 422,
        "wrong_project_id": 404,
        "matching_project_id": 200,
    },
    "test_data.object_actions": {
        "missing_project_id": 422,
        "wrong_project_id": 404,
        "matching_project_id": 200,
    },
    "testing_domains.object_actions": {
        "missing_project_id": 422,
        "wrong_project_id": 404,
        "matching_project_id": 200,
    },
    "product_ai_domains.object_actions": {
        "missing_project_id": 422,
        "wrong_project_id": 404,
        "matching_project_id": 200,
    },
}
