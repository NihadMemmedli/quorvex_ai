"""
Permission middleware for project-level access control.

Provides role-based access control (RBAC) for projects:
- Admin: Full access including member management
- Editor: Can create/edit specs and run tests
- Viewer: Read-only access

Permission Matrix:
| Action              | Admin | Editor | Viewer |
|---------------------|:-----:|:------:|:------:|
| View project        |   Y   |   Y    |   Y    |
| View specs/runs     |   Y   |   Y    |   Y    |
| Create/edit specs   |   Y   |   Y    |   N    |
| Run tests           |   Y   |   Y    |   N    |
| Delete specs/runs   |   Y   |   N    |   N    |
| Manage members      |   Y   |   N    |   N    |
| Update project      |   Y   |   N    |   N    |
| Delete project      |   Y   |   N    |   N    |
"""

from functools import wraps

from fastapi import HTTPException, status
from sqlmodel import Session, select

from ..models_auth import ProjectMember, User


class ProjectRole:
    """Project role constants with hierarchy."""

    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"

    # Role hierarchy for permission checking
    # Higher number = more permissions
    HIERARCHY = {ADMIN: 3, EDITOR: 2, VIEWER: 1}

    # Role display names
    DISPLAY_NAMES = {ADMIN: "Admin", EDITOR: "Editor", VIEWER: "Viewer"}

    @classmethod
    def get_level(cls, role: str) -> int:
        """Get the hierarchy level of a role."""
        return cls.HIERARCHY.get(role, 0)

    @classmethod
    def has_higher_or_equal_role(cls, user_role: str, required_role: str) -> bool:
        """Check if user_role is >= required_role in hierarchy."""
        return cls.get_level(user_role) >= cls.get_level(required_role)


async def get_project_membership(project_id: str, user_id: str, session: Session) -> ProjectMember | None:
    """
    Get user's membership in a project.

    Args:
        project_id: Project ID to check
        user_id: User ID to check
        session: Database session

    Returns:
        ProjectMember if user is a member, None otherwise
    """
    return session.exec(
        select(ProjectMember).where(ProjectMember.project_id == project_id).where(ProjectMember.user_id == user_id)
    ).first()


async def check_project_access(
    project_id: str, user: User | None, required_roles: list[str], session: Session
) -> ProjectMember | None:
    """
    Check if user has one of the required roles in the project.

    When REQUIRE_AUTH is false and user is None, returns None
    to allow unauthenticated access during migration.

    Args:
        project_id: Project ID to check access for
        user: User object (can be None during migration)
        required_roles: List of roles that grant access
        session: Database session

    Returns:
        ProjectMember object if access granted, None for unauthenticated

    Raises:
        HTTPException 403: If authenticated but lacks required role
    """
    # Allow unauthenticated access during migration
    if user is None:
        return None

    # Superusers have full access to all projects
    if user.is_superuser:
        return ProjectMember(project_id=project_id, user_id=user.id, role=ProjectRole.ADMIN)

    membership = await get_project_membership(project_id, user.id, session)

    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have access to this project")

    if membership.role not in required_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This action requires one of these roles: {', '.join(required_roles)}",
        )

    return membership


def require_project_role(required_roles: list[str]):
    """
    Decorator factory for checking project-level permissions.

    Creates a decorator that validates the user has one of the
    required roles in the specified project.

    Usage:
        @require_project_role([ProjectRole.ADMIN, ProjectRole.EDITOR])
        async def create_spec(project_id: str, ...):
            ...

    Args:
        required_roles: List of roles that grant access to the endpoint

    Returns:
        Decorator function
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, project_id: str, current_user: User | None, session: Session, **kwargs):
            # Check access (will raise 403 if denied)
            await check_project_access(project_id, current_user, required_roles, session)
            return await func(*args, project_id=project_id, current_user=current_user, session=session, **kwargs)

        return wrapper

    return decorator


# Convenience role groups for common permission patterns
VIEW_ROLES = [ProjectRole.ADMIN, ProjectRole.EDITOR, ProjectRole.VIEWER]
EDIT_ROLES = [ProjectRole.ADMIN, ProjectRole.EDITOR]
ADMIN_ROLES = [ProjectRole.ADMIN]
