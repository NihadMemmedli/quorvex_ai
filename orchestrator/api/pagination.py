"""
Pagination utility for API endpoints.

Provides a standardized way to paginate database query results across
all API endpoints. Uses offset-based pagination with configurable limits.
"""

from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import Select, func
from sqlmodel import Session, select

T = TypeVar("T")


class PaginatedResponse(BaseModel):
    """Standard paginated response wrapper."""

    items: list[Any]
    total: int
    limit: int
    offset: int
    has_more: bool


def paginate_query(
    session: Session,
    query: Select,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Execute a paginated query and return results with metadata.

    Args:
        session: Database session
        query: SQLAlchemy Select query to paginate
        limit: Maximum items to return (default 50)
        offset: Number of items to skip (default 0)

    Returns:
        Dict with items, total, limit, offset, has_more
    """
    # Count total matching records
    count_q = select(func.count()).select_from(query.subquery())
    total = session.exec(count_q).one()

    # Fetch paginated results
    items = session.exec(query.offset(offset).limit(limit)).all()

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + limit < total,
    }
