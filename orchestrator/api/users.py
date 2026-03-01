"""
User Management API Router (Superuser Only)

Provides endpoints for superusers to manage platform users:
- List all users
- View user details with project memberships
- Update user status (active/inactive, superuser)
- Delete users
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, func, select

from .db import get_session
from .middleware.auth import get_current_active_user
from .models_auth import ProjectMember, User, UserResponse

router = APIRouter(prefix="/users", tags=["users"])


# Request/Response models
class UserUpdateRequest(BaseModel):
    """Request model for updating user properties."""

    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = None


class UserWithProjectsResponse(BaseModel):
    """Response model for user with project memberships."""

    id: str
    email: str
    full_name: str | None
    is_active: bool
    is_superuser: bool
    email_verified: bool
    created_at: datetime
    last_login: datetime | None
    projects: list[dict]  # List of {project_id, project_name, role}


class UserListResponse(BaseModel):
    """Response model for list of users."""

    users: list[UserResponse]
    total: int


class UserCreateRequest(BaseModel):
    """Request model for creating a new user (admin only)."""

    email: str
    password: str
    full_name: str | None = None
    is_superuser: bool = False


def require_superuser(current_user: User = Depends(get_current_active_user)) -> User:
    """Dependency that ensures the current user is a superuser."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superuser access required")
    return current_user


@router.get("", response_model=UserListResponse)
def list_users(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_superuser),
    session: Session = Depends(get_session),
):
    """
    List all users (superuser only).

    Returns all users with basic info, ordered by creation date.
    """
    users = session.exec(select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)).all()

    total = session.exec(select(func.count(User.id))).one()

    return UserListResponse(
        users=[
            UserResponse(
                id=u.id,
                email=u.email,
                full_name=u.full_name,
                is_active=u.is_active,
                is_superuser=u.is_superuser,
                email_verified=u.email_verified,
                created_at=u.created_at,
                last_login=u.last_login,
            )
            for u in users
        ],
        total=total,
    )


@router.post("", response_model=UserResponse, status_code=201)
def create_user(
    data: UserCreateRequest, current_user: User = Depends(require_superuser), session: Session = Depends(get_session)
):
    """
    Create a new user (superuser only).

    Creates a user with the specified details. The user will be
    automatically added to the Default Project with viewer role.
    """
    from .models_db import Project
    from .security import hash_password, is_password_strong

    # Check if email already exists
    existing = session.exec(select(User).where(User.email == data.email.lower())).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    # Validate password strength
    is_strong, error_message = is_password_strong(data.password)
    if not is_strong:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_message)

    # Create user
    user = User(
        email=data.email.lower(),
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        is_superuser=data.is_superuser,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    # Auto-add user to Default Project with viewer role
    DEFAULT_PROJECT_ID = "default"
    try:
        default_project = session.get(Project, DEFAULT_PROJECT_ID)
        if default_project:
            member = ProjectMember(project_id=DEFAULT_PROJECT_ID, user_id=user.id, role="viewer")
            session.add(member)
            session.commit()
    except Exception:
        pass  # Don't fail user creation if project membership fails

    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        email_verified=user.email_verified,
        created_at=user.created_at,
        last_login=user.last_login,
    )


@router.get("/{user_id}", response_model=UserWithProjectsResponse)
def get_user(user_id: str, current_user: User = Depends(require_superuser), session: Session = Depends(get_session)):
    """
    Get user details with project memberships (superuser only).
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get project memberships with project names
    from .models_db import Project

    memberships = session.exec(
        select(ProjectMember, Project)
        .join(Project, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user_id)
    ).all()

    projects = [{"project_id": pm.project_id, "project_name": proj.name, "role": pm.role} for pm, proj in memberships]

    return UserWithProjectsResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        email_verified=user.email_verified,
        created_at=user.created_at,
        last_login=user.last_login,
        projects=projects,
    )


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    data: UserUpdateRequest,
    current_user: User = Depends(require_superuser),
    session: Session = Depends(get_session),
):
    """
    Update user properties (superuser only).

    Can update:
    - is_active: Enable/disable user account
    - is_superuser: Grant/revoke superuser status
    - full_name: Update display name
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent self-demotion from superuser
    if user_id == current_user.id and data.is_superuser is False:
        raise HTTPException(status_code=400, detail="Cannot remove your own superuser status")

    # Prevent self-deactivation
    if user_id == current_user.id and data.is_active is False:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    # Apply updates
    if data.is_active is not None:
        user.is_active = data.is_active
    if data.is_superuser is not None:
        user.is_superuser = data.is_superuser
    if data.full_name is not None:
        user.full_name = data.full_name

    user.updated_at = datetime.utcnow()
    session.add(user)
    session.commit()
    session.refresh(user)

    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        email_verified=user.email_verified,
        created_at=user.created_at,
        last_login=user.last_login,
    )


@router.delete("/{user_id}")
def delete_user(user_id: str, current_user: User = Depends(require_superuser), session: Session = Depends(get_session)):
    """
    Delete a user account (superuser only).

    Cannot delete your own account.
    Removes all project memberships and refresh tokens.
    """
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Delete project memberships
    memberships = session.exec(select(ProjectMember).where(ProjectMember.user_id == user_id)).all()
    for m in memberships:
        session.delete(m)

    # Delete refresh tokens
    from .models_auth import RefreshToken

    tokens = session.exec(select(RefreshToken).where(RefreshToken.user_id == user_id)).all()
    for t in tokens:
        session.delete(t)

    # Delete the user
    session.delete(user)
    session.commit()

    return {
        "message": "User deleted successfully",
        "user_id": user_id,
        "deleted_memberships": len(memberships),
        "deleted_tokens": len(tokens),
    }


@router.get("/{user_id}/projects")
def get_user_projects(
    user_id: str, current_user: User = Depends(require_superuser), session: Session = Depends(get_session)
):
    """
    Get all project memberships for a user (superuser only).
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    from .models_db import Project

    memberships = session.exec(
        select(ProjectMember, Project)
        .join(Project, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user_id)
    ).all()

    return {
        "user_id": user_id,
        "user_email": user.email,
        "projects": [
            {
                "project_id": pm.project_id,
                "project_name": proj.name,
                "role": pm.role,
                "granted_at": pm.granted_at.isoformat() if pm.granted_at else None,
            }
            for pm, proj in memberships
        ],
    }


@router.post("/{user_id}/projects/{project_id}")
def add_user_to_project(
    user_id: str,
    project_id: str,
    role: str = "viewer",
    current_user: User = Depends(require_superuser),
    session: Session = Depends(get_session),
):
    """
    Add a user to a project (superuser only).
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    from .models_db import Project

    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check if already a member
    existing = session.exec(
        select(ProjectMember).where(ProjectMember.project_id == project_id).where(ProjectMember.user_id == user_id)
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="User is already a member of this project")

    # Validate role
    valid_roles = ["admin", "editor", "viewer"]
    if role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}")

    # Create membership
    member = ProjectMember(project_id=project_id, user_id=user_id, role=role, granted_by=current_user.id)
    session.add(member)
    session.commit()

    return {"message": "User added to project", "user_id": user_id, "project_id": project_id, "role": role}


@router.delete("/{user_id}/projects/{project_id}")
def remove_user_from_project(
    user_id: str,
    project_id: str,
    current_user: User = Depends(require_superuser),
    session: Session = Depends(get_session),
):
    """
    Remove a user from a project (superuser only).
    """
    membership = session.exec(
        select(ProjectMember).where(ProjectMember.project_id == project_id).where(ProjectMember.user_id == user_id)
    ).first()

    if not membership:
        raise HTTPException(status_code=404, detail="User is not a member of this project")

    session.delete(membership)
    session.commit()

    return {"message": "User removed from project", "user_id": user_id, "project_id": project_id}
