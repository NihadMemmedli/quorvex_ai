"""
Project Management API Router

Provides CRUD endpoints for managing projects. Projects provide isolation
for specs, runs, and batches in a multi-tenant environment.

Also includes project membership management for multi-user support.
"""

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlmodel import Session, func, select

from .credentials import delete_project_credential, list_project_credentials, set_project_credential
from .db import get_session
from .middleware.auth import get_current_user, get_current_user_optional
from .middleware.permissions import ADMIN_ROLES, EDIT_ROLES, VIEW_ROLES, ProjectRole, check_project_access
from .models import (
    CredentialCreate,
    CredentialListResponse,
    CredentialResponse,
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from .models_auth import MemberCreate, MemberResponse, MemberUpdate, ProjectMember, User
from .models_db import Project, RegressionBatch
from .models_db import SpecMetadata as DBSpecMetadata
from .models_db import TestRun as DBTestRun

# Path setup for spec counting
BASE_DIR = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = BASE_DIR / "specs"


def _get_code_path_fast(spec_path: Path) -> str | None:
    """Fast check if a spec has a generated test file."""
    stem = spec_path.stem
    stem_slug = stem.replace("_", "-")

    candidates = [
        f"tests/generated/{stem}.spec.ts",
        f"tests/generated/{stem_slug}.spec.ts",
        f"tests/templates/{stem}.spec.ts",
        f"tests/templates/{stem_slug}.spec.ts",
        f"tests/{stem}.spec.ts",
    ]

    for c in candidates:
        if (BASE_DIR / c).exists():
            return str(BASE_DIR / c)
    return None


def _count_all_specs_for_project(project_id: str, session: Session) -> int:
    """Count ALL specs belonging to a project (automated or not).

    For the default project, counts specs with NULL project_id or no SpecMetadata.
    For other projects, counts specs with explicit project_id match.
    """
    if not SPECS_DIR.exists():
        return 0

    count = 0
    for f in SPECS_DIR.glob("**/*.md"):
        name = str(f.relative_to(SPECS_DIR))
        meta = session.get(DBSpecMetadata, name)

        if project_id == DEFAULT_PROJECT_ID:
            # Default project: include specs with no metadata or NULL/default project_id
            if meta is None or meta.project_id is None or meta.project_id == DEFAULT_PROJECT_ID:
                count += 1
        else:
            # Other projects: only include specs explicitly assigned
            if meta and meta.project_id == project_id:
                count += 1

    return count


def _count_automated_specs_for_project(project_id: str, session: Session) -> int:
    """Count automated specs belonging to a project (those with generated test files).

    For the default project, counts specs with NULL project_id or no SpecMetadata.
    For other projects, counts specs with explicit project_id match.
    """
    if not SPECS_DIR.exists():
        return 0

    count = 0
    for f in SPECS_DIR.glob("**/*.md"):
        # Only count automated specs (those with generated test files)
        if not _get_code_path_fast(f):
            continue

        name = str(f.relative_to(SPECS_DIR))
        meta = session.get(DBSpecMetadata, name)

        if project_id == DEFAULT_PROJECT_ID:
            # Default project: include specs with no metadata or NULL/default project_id
            if meta is None or meta.project_id is None or meta.project_id == DEFAULT_PROJECT_ID:
                count += 1
        else:
            # Other projects: only include specs explicitly assigned
            if meta and meta.project_id == project_id:
                count += 1

    return count


router = APIRouter(prefix="/projects", tags=["projects"])

# Default project ID - used for migration and as fallback
DEFAULT_PROJECT_ID = "default"
DEFAULT_PROJECT_NAME = "Default Project"


def _project_to_response(
    project: Project, spec_count: int = 0, run_count: int = 0, batch_count: int = 0
) -> ProjectResponse:
    """Convert database project to response model."""
    return ProjectResponse(
        id=project.id,
        name=project.name,
        base_url=project.base_url,
        description=project.description,
        created_at=project.created_at.isoformat() if project.created_at else None,
        last_active=project.last_active.isoformat() if project.last_active else None,
        spec_count=spec_count,
        run_count=run_count,
        batch_count=batch_count,
    )


def ensure_default_project(session: Session) -> Project:
    """Ensure the default project exists, create if not."""
    project = session.get(Project, DEFAULT_PROJECT_ID)
    if not project:
        project = Project(
            id=DEFAULT_PROJECT_ID,
            name=DEFAULT_PROJECT_NAME,
            description="Default project for all existing and new content",
        )
        session.add(project)
        session.commit()
        session.refresh(project)
    return project


@router.get("", response_model=ProjectListResponse)
def list_projects(
    current_user: User | None = Depends(get_current_user_optional), session: Session = Depends(get_session)
):
    """
    List projects accessible to the current user.

    - Superusers see all projects
    - Regular users only see projects they are members of
    - Unauthenticated users see all projects (for backward compatibility during migration)
    """
    # Ensure default project exists
    ensure_default_project(session)

    # Determine which projects to show based on user
    if current_user is None:
        # No auth - return all projects (backward compatibility)
        projects = session.exec(select(Project).order_by(Project.name)).all()
    elif current_user.is_superuser:
        # Superuser sees all projects
        projects = session.exec(select(Project).order_by(Project.name)).all()
    else:
        # Regular user - only projects they're a member of
        projects = session.exec(
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == current_user.id)
            .order_by(Project.name)
        ).all()

    # Get counts for each project
    results = []
    for project in projects:
        # Count all specs from filesystem (not just automated ones)
        spec_count = _count_all_specs_for_project(project.id, session)

        # Count runs and batches from database
        # For default project, also count items with NULL project_id (legacy data)
        if project.id == DEFAULT_PROJECT_ID:
            run_count = session.exec(
                select(func.count(DBTestRun.id)).where(
                    or_(DBTestRun.project_id == project.id, DBTestRun.project_id == None)
                )
            ).one()
            batch_count = session.exec(
                select(func.count(RegressionBatch.id)).where(
                    or_(RegressionBatch.project_id == project.id, RegressionBatch.project_id == None)
                )
            ).one()
        else:
            run_count = session.exec(select(func.count(DBTestRun.id)).where(DBTestRun.project_id == project.id)).one()
            batch_count = session.exec(
                select(func.count(RegressionBatch.id)).where(RegressionBatch.project_id == project.id)
            ).one()

        results.append(
            _project_to_response(
                project, spec_count=spec_count or 0, run_count=run_count or 0, batch_count=batch_count or 0
            )
        )

    return ProjectListResponse(projects=results, total=len(results))


@router.post("", response_model=ProjectResponse)
def create_project(request: ProjectCreate, session: Session = Depends(get_session)):
    """
    Create a new project.
    """
    # Check if name already exists
    existing = session.exec(select(Project).where(Project.name == request.name)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Project with this name already exists")

    project = Project(
        id=str(uuid.uuid4()), name=request.name, base_url=request.base_url, description=request.description
    )

    session.add(project)
    session.commit()
    session.refresh(project)

    return _project_to_response(project)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, session: Session = Depends(get_session)):
    """
    Get a specific project by ID.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Count all specs from filesystem (maintains project isolation)
    spec_count = _count_all_specs_for_project(project_id, session)

    # Get run/batch counts from database
    # For default project, also count items with NULL project_id (legacy data)
    if project_id == DEFAULT_PROJECT_ID:
        run_count = session.exec(
            select(func.count(DBTestRun.id)).where(
                or_(DBTestRun.project_id == project.id, DBTestRun.project_id == None)
            )
        ).one()
        batch_count = session.exec(
            select(func.count(RegressionBatch.id)).where(
                or_(RegressionBatch.project_id == project.id, RegressionBatch.project_id == None)
            )
        ).one()
    else:
        run_count = session.exec(select(func.count(DBTestRun.id)).where(DBTestRun.project_id == project.id)).one()
        batch_count = session.exec(
            select(func.count(RegressionBatch.id)).where(RegressionBatch.project_id == project.id)
        ).one()

    return _project_to_response(
        project, spec_count=spec_count or 0, run_count=run_count or 0, batch_count=batch_count or 0
    )


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: str, request: ProjectUpdate, session: Session = Depends(get_session)):
    """
    Update a project.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check if new name conflicts with existing project
    if request.name and request.name != project.name:
        existing = session.exec(select(Project).where(Project.name == request.name)).first()
        if existing:
            raise HTTPException(status_code=400, detail="Project with this name already exists")
        project.name = request.name

    if request.base_url is not None:
        project.base_url = request.base_url

    if request.description is not None:
        project.description = request.description

    project.last_active = datetime.utcnow()

    session.add(project)
    session.commit()
    session.refresh(project)

    return _project_to_response(project)


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    reassign_to: str | None = Query(
        default=None,
        description="Project ID to reassign content to. If not provided, content is reassigned to default project.",
    ),
    session: Session = Depends(get_session),
):
    """
    Delete a project. Content (specs, runs, batches) is reassigned to another project.
    The default project cannot be deleted.
    """
    if project_id == DEFAULT_PROJECT_ID:
        raise HTTPException(status_code=400, detail="Cannot delete the default project")

    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Determine target project for reassignment
    target_project_id = reassign_to or DEFAULT_PROJECT_ID

    # Ensure target project exists
    if target_project_id != DEFAULT_PROJECT_ID:
        target = session.get(Project, target_project_id)
        if not target:
            raise HTTPException(status_code=400, detail="Target project for reassignment not found")
    else:
        ensure_default_project(session)

    # Reassign specs
    specs = session.exec(select(DBSpecMetadata).where(DBSpecMetadata.project_id == project_id)).all()
    for spec in specs:
        spec.project_id = target_project_id
        session.add(spec)

    # Reassign runs
    runs = session.exec(select(DBTestRun).where(DBTestRun.project_id == project_id)).all()
    for run in runs:
        run.project_id = target_project_id
        session.add(run)

    # Reassign batches
    batches = session.exec(select(RegressionBatch).where(RegressionBatch.project_id == project_id)).all()
    for batch in batches:
        batch.project_id = target_project_id
        session.add(batch)

    # Delete the project
    session.delete(project)
    session.commit()

    return {
        "status": "deleted",
        "project_id": project_id,
        "reassigned_to": target_project_id,
        "reassigned_specs": len(specs),
        "reassigned_runs": len(runs),
        "reassigned_batches": len(batches),
    }


@router.post("/{project_id}/assign-spec")
def assign_spec_to_project(
    project_id: str,
    spec_name: str = Query(..., description="Name of the spec to assign"),
    session: Session = Depends(get_session),
):
    """
    Assign a spec to a project.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get or create spec metadata
    spec_meta = session.get(DBSpecMetadata, spec_name)
    if not spec_meta:
        spec_meta = DBSpecMetadata(spec_name=spec_name, project_id=project_id)
    else:
        spec_meta.project_id = project_id

    session.add(spec_meta)
    session.commit()

    return {"status": "assigned", "spec_name": spec_name, "project_id": project_id}


@router.post("/{project_id}/bulk-assign-specs")
def bulk_assign_specs_to_project(project_id: str, spec_names: list[str], session: Session = Depends(get_session)):
    """
    Assign multiple specs to a project.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    assigned = []
    for spec_name in spec_names:
        spec_meta = session.get(DBSpecMetadata, spec_name)
        if not spec_meta:
            spec_meta = DBSpecMetadata(spec_name=spec_name, project_id=project_id)
        else:
            spec_meta.project_id = project_id
        session.add(spec_meta)
        assigned.append(spec_name)

    session.commit()

    return {"status": "assigned", "assigned_count": len(assigned), "spec_names": assigned, "project_id": project_id}


# ===== Project Membership Endpoints =====


@router.get("/{project_id}/members", response_model=list[MemberResponse])
async def list_project_members(
    project_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    """
    List all members of a project.

    Requires viewer access or higher. When authentication is not enforced,
    returns all members for the project.
    """
    # Verify project exists
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check access (when auth is enabled)
    await check_project_access(project_id, current_user, VIEW_ROLES, session)

    # Get all members with their user info
    members = session.exec(
        select(ProjectMember, User)
        .join(User, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
    ).all()

    return [
        MemberResponse(
            user_id=member.user_id,
            email=user.email,
            full_name=user.full_name,
            role=member.role,
            granted_at=member.granted_at,
            granted_by=member.granted_by,
        )
        for member, user in members
    ]


@router.post("/{project_id}/members", response_model=MemberResponse, status_code=201)
async def add_project_member(
    project_id: str,
    data: MemberCreate,
    current_user: User | None = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """
    Add a user to a project.

    Requires admin access to the project.
    """
    # Verify project exists
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check admin access
    await check_project_access(project_id, current_user, ADMIN_ROLES, session)

    # Find user by email
    user = session.exec(select(User).where(User.email == data.email.lower())).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if already a member
    existing = session.exec(
        select(ProjectMember).where(ProjectMember.project_id == project_id).where(ProjectMember.user_id == user.id)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="User is already a member of this project")

    # Create membership
    member = ProjectMember(
        project_id=project_id, user_id=user.id, role=data.role, granted_by=current_user.id if current_user else None
    )
    session.add(member)
    session.commit()
    session.refresh(member)

    return MemberResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=member.role,
        granted_at=member.granted_at,
        granted_by=member.granted_by,
    )


@router.put("/{project_id}/members/{user_id}", response_model=MemberResponse)
async def update_member_role(
    project_id: str,
    user_id: str,
    data: MemberUpdate,
    current_user: User | None = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """
    Update a member's role in a project.

    Requires admin access to the project.
    """
    # Verify project exists
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check admin access
    await check_project_access(project_id, current_user, ADMIN_ROLES, session)

    # Find the membership
    member = session.exec(
        select(ProjectMember).where(ProjectMember.project_id == project_id).where(ProjectMember.user_id == user_id)
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # Get user info for response
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update role
    member.role = data.role
    session.add(member)
    session.commit()
    session.refresh(member)

    return MemberResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=member.role,
        granted_at=member.granted_at,
        granted_by=member.granted_by,
    )


@router.delete("/{project_id}/members/{user_id}")
async def remove_project_member(
    project_id: str,
    user_id: str,
    current_user: User | None = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """
    Remove a member from a project.

    Requires admin access to the project.
    Cannot remove the last admin from a project.
    """
    # Verify project exists
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check admin access
    await check_project_access(project_id, current_user, ADMIN_ROLES, session)

    # Find the membership
    member = session.exec(
        select(ProjectMember).where(ProjectMember.project_id == project_id).where(ProjectMember.user_id == user_id)
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    # Prevent removing the last admin
    if member.role == ProjectRole.ADMIN:
        admin_count = session.exec(
            select(func.count(ProjectMember.id))
            .where(ProjectMember.project_id == project_id)
            .where(ProjectMember.role == ProjectRole.ADMIN)
        ).one()
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove the last admin from a project")

    session.delete(member)
    session.commit()

    return {"message": "Member removed successfully", "user_id": user_id}


@router.get("/{project_id}/my-role")
async def get_my_project_role(
    project_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    """
    Get the current user's role in a project.

    Returns null role if user is not a member (but may still have access
    during migration period when auth is not enforced).
    """
    # Verify project exists
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not current_user:
        return {"project_id": project_id, "user_id": None, "role": None, "is_superuser": False, "auth_required": False}

    # Superusers have implicit admin access
    if current_user.is_superuser:
        return {
            "project_id": project_id,
            "user_id": current_user.id,
            "role": ProjectRole.ADMIN,
            "is_superuser": True,
            "auth_required": True,
        }

    # Get membership
    member = session.exec(
        select(ProjectMember)
        .where(ProjectMember.project_id == project_id)
        .where(ProjectMember.user_id == current_user.id)
    ).first()

    return {
        "project_id": project_id,
        "user_id": current_user.id,
        "role": member.role if member else None,
        "is_superuser": False,
        "auth_required": True,
    }


# ===== Project Credentials Endpoints =====


@router.get("/{project_id}/credentials", response_model=CredentialListResponse)
async def get_project_credentials_list(
    project_id: str,
    include_env: bool = Query(default=True, description="Include .env credentials in the list"),
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    """
    List all credentials for a project with masked values.

    Returns credentials from both project settings and .env file.
    Project credentials take precedence over .env values.

    Requires viewer access or higher.
    """
    # Verify project exists
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check access (when auth is enabled)
    await check_project_access(project_id, current_user, VIEW_ROLES, session)

    # Get credentials list with masked values
    credentials = list_project_credentials(project_id, session, include_env=include_env)

    return CredentialListResponse(credentials=[CredentialResponse(**c) for c in credentials], project_id=project_id)


@router.post("/{project_id}/credentials", response_model=CredentialResponse, status_code=201)
async def add_or_update_credential(
    project_id: str,
    data: CredentialCreate,
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    """
    Add or update a credential for a project.

    The credential value is encrypted before storage.
    API responses only return masked values.

    Requires editor access or higher.
    """
    # Verify project exists
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check edit access (when auth is enabled)
    await check_project_access(project_id, current_user, EDIT_ROLES, session)

    # Validate key name (alphanumeric + underscore, uppercase recommended)
    import re

    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", data.key):
        raise HTTPException(
            status_code=400,
            detail="Credential key must start with a letter or underscore and contain only alphanumeric characters and underscores",
        )

    # Validate value is not empty
    if not data.value or not data.value.strip():
        raise HTTPException(status_code=400, detail="Credential value cannot be empty")

    # Set the credential (encrypts and stores)
    success = set_project_credential(project_id, data.key, data.value, session)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save credential")

    # Import here to avoid circular imports
    from .credentials import mask_credential

    return CredentialResponse(key=data.key, masked_value=mask_credential(data.value), source="project")


@router.delete("/{project_id}/credentials/{credential_key}")
async def remove_credential(
    project_id: str,
    credential_key: str,
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_session),
):
    """
    Remove a credential from a project.

    Only removes project-specific credentials.
    .env credentials cannot be removed through this API.

    Requires editor access or higher.
    """
    # Verify project exists
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check edit access (when auth is enabled)
    await check_project_access(project_id, current_user, EDIT_ROLES, session)

    # Delete the credential
    success = delete_project_credential(project_id, credential_key, session)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Credential '{credential_key}' not found in project settings (note: .env credentials cannot be deleted via API)",
        )

    return {
        "message": f"Credential '{credential_key}' removed successfully",
        "project_id": project_id,
        "key": credential_key,
    }
