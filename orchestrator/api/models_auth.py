"""
Authentication and authorization database models.

This module defines the database schema for:
- User accounts
- Refresh tokens (with rotation support)
- Project memberships (role-based access control)
"""

import uuid
from datetime import datetime
from typing import Literal

from sqlmodel import Field, SQLModel, UniqueConstraint

# Role type for validation
RoleType = Literal["admin", "editor", "viewer"]


class User(SQLModel, table=True):
    """User account for authentication."""

    __tablename__ = "users"
    __table_args__ = {"extend_existing": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    email: str = Field(unique=True, index=True, max_length=255)
    password_hash: str = Field(max_length=255)
    full_name: str | None = Field(default=None, max_length=255)

    # Account status
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)  # Platform admin
    email_verified: bool = Field(default=False)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: datetime | None = Field(default=None)

    # Security
    failed_login_attempts: int = Field(default=0)
    locked_until: datetime | None = Field(default=None)


class RefreshToken(SQLModel, table=True):
    """Refresh token for JWT token rotation."""

    __tablename__ = "refresh_tokens"
    __table_args__ = {"extend_existing": True}

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    token_hash: str = Field(max_length=255)  # SHA-256 of token

    # Metadata
    device_info: str | None = Field(default=None, max_length=500)
    ip_address: str | None = Field(default=None, max_length=45)  # IPv6 max

    # Lifecycle
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
    revoked_at: datetime | None = Field(default=None)

    # Token rotation
    replaced_by: str | None = Field(default=None)  # New token ID if rotated


class ProjectMember(SQLModel, table=True):
    """User membership in a project with role-based access."""

    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"), {"extend_existing": True})

    id: int = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    user_id: str = Field(foreign_key="users.id", index=True)
    role: str = Field(default="viewer")  # admin, editor, viewer

    # Audit
    granted_by: str | None = Field(default=None, foreign_key="users.id")
    granted_at: datetime = Field(default_factory=datetime.utcnow)


# Pydantic models for API requests/responses


class UserCreate(SQLModel):
    """Request model for user registration."""

    email: str = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class UserResponse(SQLModel):
    """Response model for user data (excludes sensitive fields)."""

    id: str
    email: str
    full_name: str | None
    is_active: bool
    is_superuser: bool
    email_verified: bool
    created_at: datetime
    last_login: datetime | None


class LoginRequest(SQLModel):
    """Request model for user login."""

    email: str
    password: str


class TokenResponse(SQLModel):
    """Response model for authentication tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900  # 15 minutes in seconds


class RefreshTokenRequest(SQLModel):
    """Request model for token refresh."""

    refresh_token: str


class MemberCreate(SQLModel):
    """Request model for adding a project member."""

    email: str
    role: RoleType = "viewer"


class MemberUpdate(SQLModel):
    """Request model for updating a member's role."""

    role: RoleType


class MemberResponse(SQLModel):
    """Response model for project member data."""

    user_id: str
    email: str
    full_name: str | None
    role: str
    granted_at: datetime
    granted_by: str | None
