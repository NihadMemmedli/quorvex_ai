"""
Rate limiting middleware using slowapi.

Provides protection against brute force attacks and API abuse.
Uses Redis in production for distributed rate limiting,
or in-memory storage for development.
"""

import logging
import os
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

# Use Redis in production, memory in development
REDIS_URL = os.getenv("REDIS_URL")

if REDIS_URL:
    logger.info("Rate limiting: using Redis backend")
    storage_uri = REDIS_URL
else:
    logger.info("Rate limiting: using in-memory backend (not suitable for production)")
    storage_uri = "memory://"

# Create the limiter instance
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=storage_uri,
    default_limits=["1000/hour"],  # Global default for all endpoints
)

# Specific rate limits for authentication endpoints
AUTH_LIMITS = {
    "login": "10/minute",  # Prevent brute force attacks
    "register": "3/minute",  # Prevent spam account creation
    "refresh": "30/minute",  # Allow normal usage patterns
    "forgot_password": "3/hour",  # Prevent email abuse
    "verify_email": "10/hour",  # Prevent verification abuse
}

# Rate limits for other sensitive endpoints
API_LIMITS = {
    "create_project": "10/minute",
    "run_test": "30/minute",
    "bulk_run": "5/minute",
    "start_exploration": "5/minute",
    "stop_exploration": "10/minute",
}


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """
    Custom handler for rate limit exceeded errors.

    Returns a JSON response with retry information.
    """
    retry_after = getattr(exc, "retry_after", 60)

    logger.warning(f"Rate limit exceeded: {request.client.host} - {request.url.path} - retry_after={retry_after}")

    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please slow down.", "retry_after": retry_after},
        headers={"Retry-After": str(retry_after)},
    )


def get_rate_limit_key(request: Request) -> str:
    """
    Get the rate limit key for a request.

    Uses authenticated user ID if available, otherwise IP address.
    This prevents authenticated users from being rate limited by IP
    when multiple users share the same IP (e.g., corporate network).
    """
    # Try to get user from request state (set by auth middleware)
    user = getattr(request.state, "user", None)
    if user:
        return f"user:{user.id}"

    # Fall back to IP address
    return get_remote_address(request)


def cleanup_expired_entries() -> int:
    """Remove expired entries from in-memory rate limit storage.

    No-op when using Redis (it handles TTL natively).
    Returns count of removed entries, or -1 if not applicable.
    """
    if REDIS_URL:
        return -1

    try:
        storage = limiter._storage
        if not hasattr(storage, "expirations"):
            return -1

        now = time.time()
        expired = [k for k, exp in list(storage.expirations.items()) if exp <= now]
        for key in expired:
            storage.clear(key)

        if expired:
            logger.info(f"Rate limiter cleanup: removed {len(expired)} expired entries")
        return len(expired)
    except Exception as e:
        logger.warning(f"Rate limiter cleanup error: {e}")
        return 0
