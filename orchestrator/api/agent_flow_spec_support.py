"""Support helpers for browser-backed flow spec generation."""

from __future__ import annotations

import logging
import re
import time as time_module
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

MAX_FLOW_SPEC_JOBS = 100
_flow_spec_jobs: dict[str, dict] = {}


def _requires_authentication(url: str) -> bool:
    """Check if URL pattern typically requires authentication."""
    auth_patterns = [
        "/user/",
        "/admin/",
        "/dashboard",
        "/account/",
        "/my_",
        "/settings",
        "/profile",
        "/billing",
        "/itinerary",
        "/trips",
        "/bookings",
    ]
    return any(pattern in url.lower() for pattern in auth_patterns)


def _detect_login_url(target_url: str) -> str:
    """Detect login URL based on target domain."""
    parsed = urlparse(target_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    # Map domains to login URLs.
    login_url_map = {
        "myapp.example.com": "/users/sign_in",
        "pre.myapp.example.com": "/users/sign_in",
    }

    for domain_pattern, login_path in login_url_map.items():
        if domain_pattern in parsed.netloc:
            return f"{base}{login_path}"

    # Default: assume /login.
    return f"{base}/login"


def _is_login_page(url: str) -> bool:
    """Check if URL is a login page itself."""
    login_patterns = ["/login", "/signin", "/sign_in", "/sign-in", "/auth"]
    return any(pattern in url.lower() for pattern in login_patterns)


def _extract_domain_name(url: str) -> str:
    """Extract a clean domain name from URL for folder naming."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        # Remove common prefixes.
        hostname = re.sub(r"^(www\.|pre\.|staging\.|dev\.|test\.)", "", hostname)
        # Get the main domain part before the TLD.
        parts = hostname.split(".")
        if len(parts) >= 2:
            return parts[0]
        return hostname or "unknown"
    except Exception as e:
        logger.debug(f"URL parse failed for hostname extraction: {e}")
        return "unknown"


def _slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    slug = text.lower()
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"[^\w\-]", "", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug[:50] if len(slug) > 50 else slug


def _cleanup_flow_spec_jobs(
    jobs: dict[str, dict] | None = None,
    max_jobs: int | None = None,
) -> None:
    """Remove completed/failed jobs older than 1 hour, enforce cap."""
    jobs = _flow_spec_jobs if jobs is None else jobs
    max_jobs = MAX_FLOW_SPEC_JOBS if max_jobs is None else max_jobs

    now = time_module.time()
    to_remove = []
    for job_id, job in jobs.items():
        if job["status"] in ("completed", "failed"):
            completed_at = job.get("completed_at", 0)
            if now - completed_at > 3600:
                to_remove.append(job_id)
    for job_id in to_remove:
        del jobs[job_id]
    if len(jobs) > max_jobs:
        evictable = sorted(
            [(jid, j) for jid, j in jobs.items() if j["status"] != "running"],
            key=lambda x: x[1].get("started_at", 0),
        )
        for job_id, _ in evictable[: len(jobs) - max_jobs]:
            del jobs[job_id]
