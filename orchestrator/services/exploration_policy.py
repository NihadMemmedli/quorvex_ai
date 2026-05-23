"""Safety policy helpers for autonomous app exploration."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field

DEFAULT_RISKY_ACTION_TERMS = [
    "delete",
    "destroy",
    "remove",
    "reset",
    "refund",
    "charge",
    "pay",
    "purchase",
    "subscribe",
    "cancel subscription",
    "invite admin",
]


class ExplorationSafetyPolicy(BaseModel):
    """User-controlled guardrails for browser exploration agents."""

    environment: str = Field(default="staging")
    allowed_domains: list[str] = Field(default_factory=list)
    allowed_routes: list[str] = Field(default_factory=list)
    blocked_routes: list[str] = Field(default_factory=list)
    read_only: bool = False
    approval_required_for_risky_actions: bool = True
    blocked_action_terms: list[str] = Field(default_factory=list)
    approval_required_terms: list[str] = Field(default_factory=lambda: list(DEFAULT_RISKY_ACTION_TERMS))
    credential_scope: str = "project"
    write_policy: str = "proposals_only"
    destructive_action_policy: str = "pause_for_approval"


class ExplorationPolicyError(ValueError):
    """Raised when an exploration target violates the configured policy."""


def normalize_domain(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    parsed = urlparse(text if "://" in text else f"https://{text}")
    return (parsed.netloc or parsed.path).split("@")[-1].split(":")[0]


def _normalize_route(value: str) -> str:
    route = str(value or "").strip()
    if not route:
        return ""
    if not route.startswith("/"):
        route = f"/{route}"
    return re.sub(r"/{2,}", "/", route)


def _route_matches(path: str, route: str) -> bool:
    normalized_path = _normalize_route(path)
    normalized_route = _normalize_route(route)
    if not normalized_route:
        return False
    return normalized_path == normalized_route or normalized_path.startswith(normalized_route.rstrip("/") + "/")


def build_effective_policy(entry_url: str, policy: ExplorationSafetyPolicy | None) -> ExplorationSafetyPolicy:
    effective = policy or ExplorationSafetyPolicy()
    if not effective.allowed_domains:
        parsed = urlparse(entry_url)
        domain = normalize_domain(parsed.netloc)
        if domain:
            effective.allowed_domains = [domain]
    if not effective.blocked_action_terms:
        effective.blocked_action_terms = []
    return effective


def validate_exploration_policy(entry_url: str, policy: ExplorationSafetyPolicy | None) -> ExplorationSafetyPolicy:
    parsed = urlparse(entry_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ExplorationPolicyError(f"Entry URL must be an absolute HTTP(S) URL: {entry_url}")

    effective = build_effective_policy(entry_url, policy)
    target_domain = normalize_domain(parsed.netloc)
    allowed_domains = [normalize_domain(domain) for domain in effective.allowed_domains if normalize_domain(domain)]
    if allowed_domains and target_domain not in allowed_domains and not any(
        target_domain.endswith(f".{domain}") for domain in allowed_domains
    ):
        raise ExplorationPolicyError(f"Entry URL domain {target_domain} is outside the allowed exploration domains")

    if effective.allowed_routes and not any(_route_matches(parsed.path or "/", route) for route in effective.allowed_routes):
        raise ExplorationPolicyError(f"Entry route {parsed.path or '/'} is outside the allowed exploration routes")

    if effective.blocked_routes and any(_route_matches(parsed.path or "/", route) for route in effective.blocked_routes):
        raise ExplorationPolicyError(f"Entry route {parsed.path or '/'} is blocked by the exploration policy")

    return effective


def policy_to_agent_instructions(policy: ExplorationSafetyPolicy) -> str:
    allowed_domains = ", ".join(policy.allowed_domains) or "the target domain only"
    allowed_routes = ", ".join(policy.allowed_routes) or "no route allowlist configured"
    blocked_routes = ", ".join(policy.blocked_routes) or "none"
    approval_terms = ", ".join(policy.approval_required_terms) or "none"
    blocked_terms = ", ".join(policy.blocked_action_terms) or "none"
    read_only_rule = (
        "Read-only mode is enabled: do not submit forms or trigger state-changing actions."
        if policy.read_only
        else "Read-only mode is disabled, but avoid irreversible state changes."
    )
    return "\n".join(
        [
            "Exploration safety policy:",
            f"- Environment: {policy.environment}. Prefer staging/test data; warn if the target appears production-like.",
            f"- Allowed domains: {allowed_domains}. Do not navigate outside these domains.",
            f"- Allowed routes: {allowed_routes}.",
            f"- Blocked routes: {blocked_routes}. Do not visit blocked routes.",
            f"- {read_only_rule}",
            f"- Destructive action policy: {policy.destructive_action_policy}.",
            f"- Pause and request approval before actions whose labels or nearby context include: {approval_terms}.",
            f"- Never perform actions whose labels or nearby context include: {blocked_terms}.",
            f"- Credential scope: {policy.credential_scope}; write policy: {policy.write_policy}.",
            "- Record skipped risky actions as audit-relevant observations instead of clicking them.",
        ]
    )
