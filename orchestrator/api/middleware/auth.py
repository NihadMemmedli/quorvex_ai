"""
Authentication middleware for JWT token validation.

Provides FastAPI dependencies for extracting and validating
authenticated users from JWT bearer tokens.
"""

import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from ..db import get_session
from ..models_auth import User
from ..security import decode_token

# HTTP Bearer authentication scheme
security = HTTPBearer(auto_error=False)

# Feature flag for gradual rollout
# When false, endpoints work without authentication (for migration period)
REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "false").lower() == "true"


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security), session: Session = Depends(get_session)
) -> User | None:
    """
    Extract and validate user from JWT access token.

    This is a required authentication dependency. When REQUIRE_AUTH is true,
    it raises 401 if authentication fails. When false, it returns None
    for unauthenticated requests (migration period).

    Args:
        credentials: Bearer token from Authorization header
        session: Database session

    Returns:
        User object if authenticated, None if unauthenticated and REQUIRE_AUTH is false

    Raises:
        HTTPException: 401 if authentication fails and REQUIRE_AUTH is true
    """
    if not credentials:
        if not REQUIRE_AUTH:
            return None  # Allow unauthenticated during migration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = decode_token(credentials.credentials)
    if not token_data or token_data.type != "access":
        if not REQUIRE_AUTH:
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = session.get(User, token_data.sub)
    if not user or not user.is_active:
        if not REQUIRE_AUTH:
            return None
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security), session: Session = Depends(get_session)
) -> User | None:
    """
    Optional authentication - returns None if not authenticated.

    Use this for endpoints that work both with and without authentication,
    providing enhanced functionality when authenticated.

    Args:
        credentials: Bearer token from Authorization header
        session: Database session

    Returns:
        User object if authenticated, None otherwise
    """
    if not credentials:
        return None

    try:
        token_data = decode_token(credentials.credentials)
        if not token_data or token_data.type != "access":
            return None

        user = session.get(User, token_data.sub)
        return user if user and user.is_active else None
    except Exception:
        return None


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Require an active authenticated user.

    Use this as a dependency when authentication is required
    regardless of the REQUIRE_AUTH flag.

    Args:
        current_user: User from get_current_user dependency

    Returns:
        Active user object

    Raises:
        HTTPException: 401 if not authenticated or user is inactive
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    return current_user


async def get_current_superuser(current_user: User = Depends(get_current_active_user)) -> User:
    """
    Require a superuser (platform admin).

    Use this as a dependency for admin-only endpoints.

    Args:
        current_user: User from get_current_active_user dependency

    Returns:
        Superuser object

    Raises:
        HTTPException: 403 if user is not a superuser
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superuser access required")
    return current_user
