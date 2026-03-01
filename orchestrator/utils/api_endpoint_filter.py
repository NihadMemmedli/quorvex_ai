"""
API Endpoint Filter - Filters noise from discovered API endpoints.

Used by the exploration-to-API-tests workflow to exclude:
- Static assets (.js, .css, .png, etc.)
- Third-party domains (analytics, CDNs, error tracking)
- Browser internal URLs
- Non-API endpoints
"""

import re
from typing import Any
from urllib.parse import urlparse

# Third-party domains to exclude
THIRD_PARTY_DOMAINS = {
    "google-analytics.com",
    "analytics.google.com",
    "www.google-analytics.com",
    "googletagmanager.com",
    "www.googletagmanager.com",
    "segment.io",
    "api.segment.io",
    "cdn.segment.com",
    "sentry.io",
    "o0.ingest.sentry.io",
    "hotjar.com",
    "static.hotjar.com",
    "intercom.io",
    "api.intercom.io",
    "widget.intercom.io",
    "mixpanel.com",
    "api.mixpanel.com",
    "amplitude.com",
    "api.amplitude.com",
    "fullstory.com",
    "rs.fullstory.com",
    "heap.io",
    "heapanalytics.com",
    "clarity.ms",
    "facebook.com",
    "connect.facebook.net",
    "twitter.com",
    "platform.twitter.com",
    "linkedin.com",
    "cloudflare.com",
    "cdnjs.cloudflare.com",
    "challenges.cloudflare.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "maps.googleapis.com",
    "maps.gstatic.com",
    "recaptcha.net",
    "www.recaptcha.net",
    "stripe.com",
    "js.stripe.com",
    "api.stripe.com",
    "paypal.com",
    "newrelic.com",
    "js-agent.newrelic.com",
    "datadog.com",
    "browser-intake-datadoghq.com",
}

# Static asset extensions to exclude
STATIC_EXTENSIONS = {
    ".js",
    ".css",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".map",
    ".br",
    ".gz",
    ".mp4",
    ".webm",
    ".mp3",
    ".ogg",
    ".pdf",
    ".doc",
    ".docx",
}

# API-like URL patterns to include
API_PATTERNS = [
    r"/api/",
    r"/v\d+/",
    r"/graphql",
    r"/rest/",
    r"/rpc/",
    r"/webhook",
]


def is_api_endpoint(url: str) -> bool:
    """Check if a URL looks like an API endpoint."""
    parsed = urlparse(url)
    path = parsed.path.lower()

    # Check for API patterns in path
    for pattern in API_PATTERNS:
        if re.search(pattern, path, re.IGNORECASE):
            return True

    return False


def is_third_party(url: str) -> bool:
    """Check if a URL belongs to a third-party service."""
    parsed = urlparse(url)
    domain = parsed.hostname or ""

    # Check against known third-party domains
    for tp_domain in THIRD_PARTY_DOMAINS:
        if domain == tp_domain or domain.endswith("." + tp_domain):
            return True

    return False


def is_static_asset(url: str) -> bool:
    """Check if a URL points to a static asset."""
    parsed = urlparse(url)
    path = parsed.path.lower()

    # Check extension
    for ext in STATIC_EXTENSIONS:
        if path.endswith(ext):
            return True

    # Check common static paths
    static_paths = ["/static/", "/assets/", "/public/", "/_next/static/", "/dist/", "/build/"]
    for sp in static_paths:
        if sp in path:
            return True

    return False


def is_browser_internal(url: str) -> bool:
    """Check if a URL is browser-internal."""
    return url.startswith(("chrome-extension://", "blob:", "data:", "about:", "javascript:"))


def filter_api_endpoints(endpoints: list[dict[str, Any]], app_domain: str = None) -> list[dict[str, Any]]:
    """
    Filter a list of discovered API endpoints to remove noise.

    Args:
        endpoints: List of endpoint dicts with at least 'url' and 'method' keys
        app_domain: Optional domain of the application (to prioritize same-domain endpoints)

    Returns:
        Filtered list of API endpoints
    """
    filtered = []

    for ep in endpoints:
        url = ep.get("url", "")
        method = ep.get("method", "GET").upper()
        ep.get("response_status")

        # Skip browser internal URLs
        if is_browser_internal(url):
            continue

        # Skip static assets
        if is_static_asset(url):
            continue

        # Skip third-party domains
        if is_third_party(url):
            continue

        # Skip preflight OPTIONS requests
        if method == "OPTIONS":
            continue

        # If we have an app_domain, prefer same-domain endpoints
        if app_domain:
            parsed = urlparse(url)
            ep_domain = parsed.hostname or ""
            if ep_domain != app_domain and not is_api_endpoint(url):
                continue

        # Include if it matches API patterns OR has a JSON-like response
        response_body = ep.get("response_body_sample", "") or ""
        content_type = ""
        headers = ep.get("request_headers", {})
        if isinstance(headers, dict):
            content_type = headers.get("content-type", headers.get("Content-Type", ""))

        is_json_response = (
            response_body.strip().startswith("{")
            or response_body.strip().startswith("[")
            or "application/json" in content_type
        )

        if is_api_endpoint(url) or is_json_response or method in ("POST", "PUT", "PATCH", "DELETE"):
            filtered.append(ep)

    return filtered


def group_by_base_path(endpoints: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """
    Group endpoints by their base path.

    E.g., /api/users/1 and /api/users/2 -> grouped under /api/users
    """
    groups: dict[str, list[dict[str, Any]]] = {}

    for ep in endpoints:
        url = ep.get("url", "")
        parsed = urlparse(url)
        path = parsed.path

        # Extract base path: /api/users/123 -> /api/users
        # Remove trailing ID-like segments (numbers, UUIDs)
        parts = [p for p in path.split("/") if p]
        base_parts = []
        for part in parts:
            # Stop at ID-like segments
            if re.match(r"^\d+$", part) or re.match(r"^[0-9a-f-]{36}$", part):
                break
            base_parts.append(part)

        if not base_parts:
            base_path = "root"
        else:
            base_path = "/" + "/".join(base_parts)

        if base_path not in groups:
            groups[base_path] = []
        groups[base_path].append(ep)

    return groups
