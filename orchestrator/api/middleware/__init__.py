"""
Middleware modules for authentication, authorization, and rate limiting.
"""

from .auth import get_current_user, get_current_user_optional
from .permissions import ProjectRole, check_project_access, get_project_membership, require_project_role
from .rate_limit import AUTH_LIMITS, cleanup_expired_entries, limiter, rate_limit_exceeded_handler

__all__ = [
    # Auth middleware
    "get_current_user",
    "get_current_user_optional",
    # Permission middleware
    "ProjectRole",
    "check_project_access",
    "get_project_membership",
    "require_project_role",
    # Rate limiting
    "limiter",
    "AUTH_LIMITS",
    "rate_limit_exceeded_handler",
    "cleanup_expired_entries",
]
