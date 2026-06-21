"""Shared constants and pure helpers for autonomous mission services."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

MAX_PROPOSALS_PER_ITERATION = 5
VALID_TEST_TYPES = {"e2e", "api", "regression", "security", "accessibility", "unit"}
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3
DEFAULT_MAX_PENDING_APPROVALS = 25
DEFAULT_MAX_PARALLEL_AGENTS = 2
DEFAULT_WORK_ITEM_BATCH_SIZE = 7
DEFAULT_WORK_ITEM_STALE_MINUTES = 45
DEFAULT_STRUCTURED_GUARDRAIL_REPAIR_ATTEMPTS = 2
DEFAULT_STRUCTURED_GUARDRAIL_REPAIR_MAX_TURNS = 2
WORK_ITEM_ACTIVE_STATUSES = {"queued", "running"}
WORK_ITEM_TERMINAL_STATUSES = {"completed", "failed", "blocked", "cancelled"}
WHOLE_APP_TEAM_ROLES = (
    "surface_mapper",
    "explorer",
    "requirements_analyst",
    "rtm_mapper",
    "spec_writer",
    "regression_scout",
    "flake_triager",
)
REVISION_METADATA_KEYS = (
    "revision_of_work_item_id",
    "reviewer_work_item_id",
    "review_reason",
    "revision_attempt",
)
STRUCTURED_AGENT_ARTIFACT_KEYS = (
    "requirements",
    "rtm_candidates",
    "test_proposals",
    "bugs",
    "findings",
    "app_map_updates",
)
LOW_RISK_LEVELS = {"low", "info"}
PROPOSAL_VALIDATION_TIMEOUT_SECONDS = 120
BROWSER_LEASE_MODES = {"isolated", "sequential_handoff", "read_only_snapshot"}
DEFAULT_BROWSER_ACTIONS = (
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_fill_form",
    "browser_select_option",
    "browser_press_key",
    "browser_wait_for",
    "browser_handle_dialog",
    "browser_evaluate",
    "browser_take_screenshot",
    "browser_console_messages",
    "browser_network_requests",
    "browser_close",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalize_fingerprint_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(_normalize_fingerprint_value(item) for item in value)
    if isinstance(value, dict):
        return " ".join(
            f"{_normalize_fingerprint_value(key)} {_normalize_fingerprint_value(value[key])}" for key in sorted(value)
        )
    text = str(value).lower()
    text = re.sub(r"https?://[^/\s]+", "", text)
    text = re.sub(r"[^a-z0-9/._ -]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _stable_dedupe_hash(*parts: Any, length: int = 32) -> str:
    raw = "|".join(_normalize_fingerprint_value(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def _route_from_url(target_url: str | None) -> str | None:
    if not target_url:
        return None
    parsed = urlparse(target_url)
    route = parsed.path or "/"
    return f"{route}?{parsed.query}" if parsed.query else route


def _requirement_fingerprint(row: dict[str, Any]) -> str:
    return _stable_dedupe_hash(
        "requirement",
        row.get("category") or "other",
        row.get("title"),
        row.get("acceptance_criteria") or row.get("criteria") or [],
    )


def _spec_fingerprint(row: dict[str, Any], requirement_ids: list[int] | None = None) -> str:
    route = row.get("route") or _route_from_url(row.get("target_url"))
    return _stable_dedupe_hash(
        "spec",
        row.get("test_type") or "e2e",
        route or row.get("target_url"),
        requirement_ids or row.get("requirement_ids") or row.get("requirements") or [],
        row.get("scenario") or row.get("title") or row.get("intent"),
    )


def _bug_fingerprint(row: dict[str, Any]) -> str:
    return _stable_dedupe_hash(
        "bug",
        row.get("route") or _route_from_url(row.get("target_url")) or row.get("url"),
        row.get("action") or row.get("steps") or row.get("reproduction_steps"),
        row.get("observed_failure") or row.get("actual") or row.get("description"),
        row.get("error") or row.get("error_message"),
    )
