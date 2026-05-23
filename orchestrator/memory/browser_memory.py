"""Durable browser exploration memory.

This module stores browser-agent observations as canonical page states,
elements, transitions, and frontier work. It intentionally accepts partial
inputs so existing exploration runs can populate useful memory before deeper
runtime snapshot capture is available everywhere.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import (
    BrowserElement,
    BrowserFrontierItem,
    BrowserPageState,
    BrowserStateCluster,
    BrowserTransition,
)

from .config import get_config

TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "cache",
    "ts",
    "timestamp",
    "session",
    "token",
}
BEHAVIOR_QUERY_KEYS = {"tab", "step", "page", "sort", "filter", "q", "query", "search", "locale", "lang"}
ACTIONABLE_ROLES = {
    "button",
    "link",
    "textbox",
    "checkbox",
    "radio",
    "combobox",
    "menuitem",
    "option",
    "tab",
    "switch",
    "slider",
}
HIGH_VALUE_TERMS = {
    "submit",
    "save",
    "search",
    "login",
    "sign in",
    "checkout",
    "create",
    "add",
    "export",
    "upload",
    "filter",
    "continue",
    "next",
}
RISKY_TERMS = {"delete", "destroy", "remove", "reset", "logout", "sign out", "cancel subscription"}
SENSITIVE_PATTERNS = [
    re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\b\s*[:=]?\s*[^\s,\]}]+"),
    re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"),
]
SNAPSHOT_LINE_RE = re.compile(
    r"^\s*[-*]?\s*(?P<role>[A-Za-z][\w-]*)"
    r"(?:\s+\"(?P<name_q>[^\"]*)\"|\s+'(?P<name_s>[^']*)'|\s+(?P<name_plain>[^\[]+?))?"
    r"(?P<meta>(?:\s+\[[^\]]+\])*)\s*:?\s*$"
)


@dataclass(frozen=True)
class CanonicalState:
    page_key: str
    state_key: str
    url_template: str
    exact_hash: str
    simhash: str
    canonical: dict[str, Any]
    embedding_text: str
    elements: list[dict[str, Any]]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(value: str, length: int = 32) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _clip(text: str | None, limit: int = 240) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    return normalized if len(normalized) <= limit else normalized[: limit - 3].rstrip() + "..."


def redact_snapshot_text(text: str | None) -> str:
    redacted = str(text or "")
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def normalize_url_template(url: str) -> str:
    parsed = urlparse(url or "")
    path_parts = []
    for part in parsed.path.split("/"):
        if not part:
            continue
        if re.fullmatch(r"\d+", part):
            path_parts.append("{id}")
        elif re.fullmatch(r"[0-9a-fA-F]{8,}", part):
            path_parts.append("{hex}")
        elif re.fullmatch(r"[0-9a-fA-F-]{32,36}", part):
            path_parts.append("{uuid}")
        else:
            path_parts.append(part)
    path = "/" + "/".join(path_parts) if path_parts else "/"
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key in BEHAVIOR_QUERY_KEYS and key not in TRACKING_QUERY_KEYS
    ]
    query = urlencode(sorted(query_items))
    return urlunparse((parsed.scheme, parsed.netloc, path, "", query, ""))


def page_key_for_url(url: str, *, auth_state: str = "unknown", viewport: str = "default") -> str:
    template = normalize_url_template(url)
    parsed = urlparse(template)
    return "|".join([parsed.netloc or "unknown-host", parsed.path or "/", parsed.query or "-", auth_state, viewport])


def _simhash(tokens: list[str], bits: int = 64) -> str:
    vector = [0] * bits
    for token in tokens:
        digest = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
        for idx in range(bits):
            vector[idx] += 1 if digest & (1 << idx) else -1
    value = 0
    for idx, weight in enumerate(vector):
        if weight >= 0:
            value |= 1 << idx
    return f"{value:016x}"


def parse_accessibility_snapshot(snapshot_text: str | None) -> list[dict[str, Any]]:
    """Extract a compact actionable element inventory from a Playwright snapshot."""
    text = redact_snapshot_text(snapshot_text)
    elements: list[dict[str, Any]] = []
    role_counts: dict[tuple[str, str], int] = {}
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        match = SNAPSHOT_LINE_RE.match(candidate)
        if not match:
            continue
        role = (match.group("role") or "").lower()
        if role not in ACTIONABLE_ROLES and role not in {"heading", "dialog", "navigation", "main", "form"}:
            continue
        name = match.group("name_q") or match.group("name_s") or match.group("name_plain") or ""
        name = _clip(name.strip().strip(":"))
        meta = match.group("meta") or ""
        ref_match = re.search(r"\bref=([^\s,\]]+)", meta)
        key_base = (role, name.lower())
        ordinal = role_counts.get(key_base, 0)
        role_counts[key_base] = ordinal + 1
        element = {
            "role": role,
            "name": name,
            "text": name,
            "ref": ref_match.group(1) if ref_match else None,
            "states": sorted(set(re.findall(r"\b(expanded|selected|checked|disabled|pressed)\b", meta.lower()))),
            "ordinal": ordinal,
        }
        element["importance_score"] = score_element_importance(element)
        element["locator_candidates"] = build_locator_candidates(element)
        elements.append(element)
    return elements[:250]


def score_element_importance(element: dict[str, Any]) -> float:
    role = str(element.get("role") or "").lower()
    name = str(element.get("name") or element.get("text") or "").lower()
    score = 0.3
    if role in ACTIONABLE_ROLES:
        score += 0.25
    if any(term in name for term in HIGH_VALUE_TERMS):
        score += 0.3
    if role in {"button", "textbox", "combobox", "tab"}:
        score += 0.1
    if any(term in name for term in RISKY_TERMS):
        score -= 0.35
    return max(0.0, min(1.0, score))


def _locator_score(strategy: str, element: dict[str, Any], *, duplicate: bool = False) -> float:
    role = str(element.get("role") or "").lower()
    name = str(element.get("name") or "").strip()
    score = {
        "role": 0.9,
        "label": 0.86,
        "placeholder": 0.78,
        "testid": 0.82,
        "text": 0.62,
        "css": 0.4,
        "ref": 0.2,
    }.get(strategy, 0.5)
    if role in ACTIONABLE_ROLES:
        score += 0.04
    if not name:
        score -= 0.25
    if duplicate:
        score -= 0.18
    if re.search(r"\d{2,}|[0-9]{1,2}/[0-9]{1,2}|[$€£]", name):
        score -= 0.12
    return round(max(0.0, min(1.0, score)), 3)


def build_locator_candidates(element: dict[str, Any]) -> list[dict[str, Any]]:
    role = str(element.get("role") or "").lower()
    name = _clip(element.get("name") or element.get("text") or "", 120)
    duplicate = int(element.get("ordinal") or 0) > 0
    candidates: list[dict[str, Any]] = []
    if role in ACTIONABLE_ROLES and name:
        candidates.append(
            {
                "strategy": "role",
                "locator": f"getByRole({json.dumps(role)}, {{ name: {json.dumps(name)} }})",
                "score": _locator_score("role", element, duplicate=duplicate),
                "durable": True,
            }
        )
    if role in {"textbox", "combobox", "checkbox", "radio", "switch"} and name:
        candidates.append(
            {
                "strategy": "label",
                "locator": f"getByLabel({json.dumps(name)})",
                "score": _locator_score("label", element, duplicate=duplicate),
                "durable": True,
            }
        )
    if role == "textbox" and name:
        candidates.append(
            {
                "strategy": "placeholder",
                "locator": f"getByPlaceholder({json.dumps(name)})",
                "score": _locator_score("placeholder", element, duplicate=duplicate),
                "durable": True,
            }
        )
    if name and role not in ACTIONABLE_ROLES:
        candidates.append(
            {
                "strategy": "text",
                "locator": f"getByText({json.dumps(name)})",
                "score": _locator_score("text", element, duplicate=duplicate),
                "durable": True,
            }
        )
    if element.get("ref"):
        candidates.append(
            {
                "strategy": "ref",
                "locator": str(element["ref"]),
                "score": _locator_score("ref", element, duplicate=duplicate),
                "durable": False,
            }
        )
    return sorted(candidates, key=lambda item: item["score"], reverse=True)[:3]


def canonicalize_state(
    *,
    url: str,
    snapshot_text: str | None = None,
    title: str | None = None,
    auth_state: str = "unknown",
    viewport: str = "default",
    locale: str | None = None,
    source_fidelity: str = "live_snapshot",
) -> CanonicalState:
    elements = parse_accessibility_snapshot(snapshot_text)
    url_template = normalize_url_template(url)
    page_key = page_key_for_url(url, auth_state=auth_state, viewport=viewport)
    canonical = {
        "url_template": url_template,
        "title": _clip(title, 160),
        "auth_state": auth_state,
        "viewport": viewport,
        "locale": locale or "",
        "source_fidelity": source_fidelity,
        "elements": [
            {
                "role": item.get("role"),
                "name": item.get("name"),
                "states": item.get("states") or [],
                "ordinal": item.get("ordinal", 0),
            }
            for item in elements
        ],
    }
    if not elements:
        canonical["url_only"] = True
    canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    exact_hash = _hash(canonical_json, 64)
    state_key = _hash(f"{page_key}|{exact_hash}", 40)
    tokens = re.findall(r"[a-z0-9]+", canonical_json.lower())
    embedding_bits = [page_key, title or "", " ".join(f"{e.get('role')} {e.get('name')}" for e in elements[:40])]
    return CanonicalState(
        page_key=page_key,
        state_key=state_key,
        url_template=url_template,
        exact_hash=exact_hash,
        simhash=_simhash(tokens or [page_key]),
        canonical=canonical,
        embedding_text=_clip(" ".join(embedding_bits), 1200),
        elements=elements,
    )


class ExplorationMemoryService:
    """SQL-backed durable memory for browser exploration."""

    def __init__(self, session: Session | None = None, project_id: str | None = None):
        self.session = session
        self.project_id = project_id or get_config().project_id or "default"

    def _session(self) -> Session:
        return self.session or Session(engine, expire_on_commit=False)

    def upsert_page_state(
        self,
        *,
        session_id: str | None,
        url: str,
        snapshot_text: str | None = None,
        title: str | None = None,
        snapshot_ref: str | None = None,
        auth_state: str = "unknown",
        viewport: str = "default",
        locale: str | None = None,
        source_fidelity: str = "live_snapshot",
    ) -> BrowserPageState:
        owns_session = self.session is None
        db = self._session()
        try:
            state = canonicalize_state(
                url=url,
                snapshot_text=snapshot_text,
                title=title,
                auth_state=auth_state,
                viewport=viewport,
                locale=locale,
                source_fidelity=source_fidelity,
            )
            now = _utcnow()
            existing = db.exec(
                select(BrowserPageState)
                .where(BrowserPageState.project_id == self.project_id)
                .where(BrowserPageState.state_key == state.state_key)
            ).first()
            if existing:
                existing.last_seen_at = now
                existing.visit_count = (existing.visit_count or 0) + 1
                existing.snapshot_ref = snapshot_ref or existing.snapshot_ref
                existing.session_id = session_id or existing.session_id
                existing.canonical_json = state.canonical
                existing.simhash = state.simhash
                existing.embedding_id = existing.embedding_id or f"browser_state:{existing.id}"
                existing.page_type = source_fidelity
                existing.importance_score = max(
                    float(existing.importance_score or 0),
                    self._state_importance(state.elements) * self._source_fidelity_score(source_fidelity),
                )
                db.add(existing)
                db.commit()
                db.refresh(existing)
                page_state = existing
            else:
                state_id = f"bpstate-{_hash(f'{self.project_id}|{state.state_key}', 16)}"
                page_state = BrowserPageState(
                    id=state_id,
                    project_id=self.project_id,
                    session_id=session_id,
                    page_key=state.page_key,
                    state_key=state.state_key,
                    url=url,
                    url_template=state.url_template,
                    title=title,
                    page_type=source_fidelity,
                    auth_state=auth_state,
                    viewport=viewport,
                    locale=locale,
                    exact_hash=state.exact_hash,
                    simhash=state.simhash,
                    embedding_id=f"browser_state:{state_id}",
                    snapshot_ref=snapshot_ref,
                    canonical_json=state.canonical,
                    first_seen_at=now,
                    last_seen_at=now,
                    novelty_score=1.0,
                    importance_score=self._state_importance(state.elements)
                    * self._source_fidelity_score(source_fidelity),
                )
                db.add(page_state)
                db.commit()
                db.refresh(page_state)

            elements = self._upsert_elements(db, page_state, state.elements, source_fidelity=source_fidelity)
            self._upsert_cluster(db, page_state, state)
            self._index_page_state(page_state, state.embedding_text)
            for element in elements:
                self._index_element(element, page_state)
                self._upsert_frontier_item(db, page_state, element)
            self._project_state_to_graph(page_state, elements)
            return page_state
        finally:
            if owns_session:
                db.close()

    def record_transition(
        self,
        *,
        session_id: str | None,
        from_state: BrowserPageState,
        to_state: BrowserPageState,
        action_type: str,
        target: str | None = None,
        success: bool = True,
        duration_ms: float = 0.0,
    ) -> BrowserTransition:
        owns_session = self.session is None
        db = self._session()
        try:
            now = _utcnow()
            element = self._find_matching_element(db, from_state.id, target)
            signature = self._action_signature(action_type, target, element.id if element else None)
            existing = db.exec(
                select(BrowserTransition)
                .where(BrowserTransition.project_id == self.project_id)
                .where(BrowserTransition.from_state_id == from_state.id)
                .where(BrowserTransition.to_state_id == to_state.id)
                .where(BrowserTransition.action_signature == signature)
            ).first()
            if existing:
                if success:
                    existing.success_count = (existing.success_count or 0) + 1
                else:
                    existing.failure_count = (existing.failure_count or 0) + 1
                existing.avg_duration_ms = (
                    ((existing.avg_duration_ms or 0.0) + duration_ms) / 2 if duration_ms else existing.avg_duration_ms
                )
                existing.last_seen_at = now
                db.add(existing)
                db.commit()
                db.refresh(existing)
                transition = existing
            else:
                transition_id = f"bptran-{_hash(f'{from_state.id}|{to_state.id}|{signature}', 16)}"
                transition = BrowserTransition(
                    id=transition_id,
                    project_id=self.project_id,
                    session_id=session_id,
                    from_state_id=from_state.id,
                    to_state_id=to_state.id,
                    action_type=action_type or "unknown",
                    action_signature=signature,
                    element_id=element.id if element else None,
                    transition_type="navigation" if from_state.url != to_state.url else "interaction",
                    success_count=1 if success else 0,
                    failure_count=0 if success else 1,
                    avg_duration_ms=duration_ms or 0.0,
                    risk_level=self._risk_level(action_type, target),
                    first_seen_at=now,
                    last_seen_at=now,
                )
                db.add(transition)
                db.commit()
                db.refresh(transition)
            if element:
                element.tested_count = (element.tested_count or 0) + 1
                if success:
                    element.success_count = (element.success_count or 0) + 1
                else:
                    element.failure_count = (element.failure_count or 0) + 1
                element.last_seen_at = now
                db.add(element)
                db.commit()
            if element and success:
                self._complete_matching_frontier(db, transition=transition, element=element)
            self._project_transition_to_graph(transition, from_state, to_state)
            return transition
        finally:
            if owns_session:
                db.close()

    def seed_from_action_trace(
        self,
        *,
        session_id: str | None,
        entry_url: str,
        action_trace: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Populate durable memory from existing ExploratoryAgent trace output."""
        current = self.upsert_page_state(
            session_id=session_id,
            url=entry_url,
            title=entry_url,
            source_fidelity="action_trace",
        )
        states = 1
        transitions = 0
        for action in action_trace or []:
            action_type = str(action.get("action") or "unknown").lower()
            target = str(action.get("target") or "").strip()
            if not target:
                continue
            if action_type == "navigate" and target.startswith("http"):
                next_state = self.upsert_page_state(
                    session_id=session_id,
                    url=target,
                    title=target,
                    source_fidelity="action_trace",
                )
                states += 1
            else:
                snapshot_text = f'- {self._role_for_action(action_type)} "{_clip(target, 120)}"'
                next_state = self.upsert_page_state(
                    session_id=session_id,
                    url=current.url,
                    title=current.title or current.url,
                    snapshot_text=snapshot_text,
                    source_fidelity="action_trace",
                )
            self.record_transition(
                session_id=session_id,
                from_state=current,
                to_state=next_state,
                action_type=action_type,
                target=target,
                success=str(action.get("outcome") or "ok").lower() not in {"failed", "error"},
            )
            transitions += 1
            current = next_state
        return {"states": states, "transitions": transitions}

    def get_memory_bundle(self, *, query: str = "", limit: int = 5) -> dict[str, Any]:
        owns_session = self.session is None
        db = self._session()
        try:
            states = db.exec(
                select(BrowserPageState)
                .where(BrowserPageState.project_id == self.project_id)
                .where(BrowserPageState.status == "active")
                .order_by(col(BrowserPageState.last_seen_at).desc())
                .limit(limit * 3)
            ).all()
            states = sorted(
                states,
                key=lambda state: (
                    self._source_fidelity_score(self._state_source_fidelity(state)),
                    state.last_seen_at or datetime.min,
                ),
                reverse=True,
            )[:limit]
            elements = []
            if states:
                state_ids = [state.id for state in states]
                elements = db.exec(
                    select(BrowserElement)
                    .where(BrowserElement.project_id == self.project_id)
                    .where(col(BrowserElement.state_id).in_(state_ids))
                    .order_by(col(BrowserElement.importance_score).desc())
                    .limit(limit * 3)
                ).all()
            return {
                "states": [
                    {
                        "id": state.id,
                        "url": state.url,
                        "page_key": state.page_key,
                        "state_key": state.state_key,
                        "source_fidelity": self._state_source_fidelity(state),
                        "visit_count": state.visit_count,
                        "last_seen_at": state.last_seen_at.isoformat() if state.last_seen_at else None,
                    }
                    for state in states
                ],
                "elements": [
                    {
                        "id": element.id,
                        "state_id": element.state_id,
                        "role": element.role,
                        "name": element.name,
                        "tested_count": element.tested_count,
                        "success_count": element.success_count,
                        "failure_count": element.failure_count,
                        "stability_score": round(float(element.stability_score or 0), 3),
                        "importance_score": round(float(element.importance_score or 0), 3),
                        "best_locator": (element.locator_candidates_json or [{}])[0],
                        "source_fidelity": (element.attributes_json or {}).get("source_fidelity", "unknown"),
                        "last_seen_at": element.last_seen_at.isoformat() if element.last_seen_at else None,
                    }
                    for element in elements
                ],
                "frontier": self.get_frontier_work(query=query, limit=limit, db=db),
            }
        finally:
            if owns_session:
                db.close()

    def capture_memory_baseline(
        self,
        *,
        session_id: str | None = None,
        url_scope: str | None = None,
        limit: int = 500,
        include_inactive: bool = False,
        db: Session | None = None,
    ) -> dict[str, Any]:
        """Return a portable browser-memory snapshot suitable for later diffing."""
        owns_session = db is None
        db = db or self._session()
        try:
            state_query = select(BrowserPageState).where(BrowserPageState.project_id == self.project_id)
            if session_id:
                state_query = state_query.where(BrowserPageState.session_id == session_id)
            if not include_inactive:
                state_query = state_query.where(BrowserPageState.status == "active")
            if url_scope:
                state_query = state_query.where(
                    (col(BrowserPageState.url).contains(url_scope))
                    | (col(BrowserPageState.url_template).contains(url_scope))
                )
            states = db.exec(
                state_query.order_by(col(BrowserPageState.last_seen_at).desc()).limit(max(1, limit))
            ).all()
            state_by_id = {state.id: state for state in states}
            elements: list[BrowserElement] = []
            if state_by_id:
                elements = db.exec(
                    select(BrowserElement)
                    .where(BrowserElement.project_id == self.project_id)
                    .where(col(BrowserElement.state_id).in_(list(state_by_id)))
                    .order_by(col(BrowserElement.last_seen_at).desc())
                    .limit(max(1, limit * 5))
                ).all()
            return {
                "project_id": self.project_id,
                "captured_at": _utcnow().isoformat(),
                "session_id": session_id,
                "url_scope": url_scope,
                "states": [self._shape_state_snapshot(state) for state in states],
                "elements": [
                    self._shape_element_snapshot(element, state_by_id.get(element.state_id))
                    for element in elements
                ],
            }
        finally:
            if owns_session:
                db.close()

    def compute_memory_delta(
        self,
        baseline: dict[str, Any] | None = None,
        *,
        baseline_session_id: str | None = None,
        current_session_id: str | None = None,
        url_scope: str | None = None,
        limit: int = 500,
        include_unchanged: bool = False,
        locator_score_drop_threshold: float = 0.15,
    ) -> dict[str, Any]:
        """Compare a mission/run baseline with current browser memory.

        Callers can persist the output of ``capture_memory_baseline`` at mission
        start and pass it back here after a run. If no baseline dict is supplied,
        ``baseline_session_id`` is used to build one from existing rows.
        """
        owns_session = self.session is None
        db = self._session()
        try:
            baseline_snapshot = baseline or self.capture_memory_baseline(
                session_id=baseline_session_id,
                url_scope=url_scope,
                limit=limit,
                db=db,
            )
            current_snapshot = self.capture_memory_baseline(
                session_id=current_session_id,
                url_scope=url_scope,
                limit=limit,
                db=db,
            )
            return self._diff_memory_snapshots(
                baseline_snapshot,
                current_snapshot,
                include_unchanged=include_unchanged,
                locator_score_drop_threshold=locator_score_drop_threshold,
            )
        finally:
            if owns_session:
                db.close()

    def get_frontier_work(
        self,
        *,
        query: str = "",
        limit: int = 10,
        risk_max: str = "medium",
        url_scope: str | None = None,
        include_leased: bool = False,
        db: Session | None = None,
    ) -> list[dict[str, Any]]:
        """Return actionable, ranked frontier work with state and locator context."""
        owns_session = db is None
        db = db or self._session()
        try:
            now = _utcnow()
            due_statuses = ["queued", "in_progress"]
            rows = db.exec(
                select(BrowserFrontierItem)
                .where(BrowserFrontierItem.project_id == self.project_id)
                .where(col(BrowserFrontierItem.status).in_(due_statuses))
                .order_by(col(BrowserFrontierItem.priority_score).desc(), col(BrowserFrontierItem.updated_at).asc())
                .limit(max(limit * 6, limit))
            ).all()

            ranked: list[tuple[float, dict[str, Any]]] = []
            for item in rows:
                if item.status == "queued" and item.next_due_at and item.next_due_at > now:
                    continue
                if item.status == "in_progress" and not include_leased and item.lease_until and item.lease_until > now:
                    continue
                state = db.get(BrowserPageState, item.state_id)
                if not state or state.status != "active":
                    continue
                if url_scope and url_scope not in (state.url or "") and url_scope not in (state.url_template or ""):
                    continue
                element = db.get(BrowserElement, item.element_id) if item.element_id else None
                risk_level = self._risk_level(item.action_type, element.name if element else "")
                if self._risk_rank(risk_level) > self._risk_rank(risk_max):
                    continue
                shaped = self._shape_frontier_item(item=item, state=state, element=element, risk_level=risk_level)
                score = self._rank_frontier_item(item=item, state=state, element=element, query=query, risk_level=risk_level)
                shaped["rank_score"] = round(score, 3)
                ranked.append((score, shaped))

            ranked.sort(key=lambda pair: pair[0], reverse=True)
            return [item for _, item in ranked[:limit]]
        finally:
            if owns_session:
                db.close()

    def claim_frontier_items(
        self,
        *,
        worker_id: str,
        limit: int = 5,
        lease_seconds: int = 900,
        query: str = "",
        risk_max: str = "medium",
        url_scope: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lease queued frontier items so 24/7 agents do not duplicate work."""
        owns_session = self.session is None
        db = self._session()
        try:
            candidates = self.get_frontier_work(
                query=query,
                limit=limit,
                risk_max=risk_max,
                url_scope=url_scope,
                include_leased=False,
                db=db,
            )
            now = _utcnow()
            lease_until = now + timedelta(seconds=max(30, lease_seconds))
            claimed: list[dict[str, Any]] = []
            for candidate in candidates:
                item = db.get(BrowserFrontierItem, candidate["id"])
                if not item or item.status not in {"queued", "in_progress"}:
                    continue
                if item.status == "in_progress" and item.lease_until and item.lease_until > now:
                    continue
                item.status = "in_progress"
                item.lease_owner = worker_id
                item.lease_until = lease_until
                item.last_attempted_at = now
                item.attempts = (item.attempts or 0) + 1
                item.updated_at = now
                db.add(item)
                candidate.update(
                    {
                        "status": item.status,
                        "attempts": item.attempts,
                        "lease_owner": item.lease_owner,
                        "lease_until": item.lease_until.isoformat(),
                    }
                )
                claimed.append(candidate)
            if claimed:
                db.commit()
            return claimed
        finally:
            if owns_session:
                db.close()

    def complete_frontier_item(
        self,
        frontier_id: str,
        *,
        transition_id: str | None = None,
        outcome: str | None = None,
    ) -> dict[str, Any] | None:
        return self._update_frontier_status(
            frontier_id,
            status="completed",
            transition_id=transition_id,
            block_reason=outcome,
            clear_lease=True,
        )

    def fail_frontier_item(
        self,
        frontier_id: str,
        *,
        error: str,
        retry_after_seconds: int = 300,
        max_attempts: int = 3,
    ) -> dict[str, Any] | None:
        owns_session = self.session is None
        db = self._session()
        try:
            item = db.get(BrowserFrontierItem, frontier_id)
            if not item or item.project_id != self.project_id:
                return None
            now = _utcnow()
            item.block_reason = _clip(error, 240)
            item.lease_owner = None
            item.lease_until = None
            item.updated_at = now
            item.status = "blocked" if (item.attempts or 0) >= max_attempts else "queued"
            item.next_due_at = None if item.status == "blocked" else now + timedelta(seconds=max(30, retry_after_seconds))
            db.add(item)
            db.commit()
            db.refresh(item)
            return self._shape_frontier_item(item=item, state=db.get(BrowserPageState, item.state_id), element=db.get(BrowserElement, item.element_id) if item.element_id else None)
        finally:
            if owns_session:
                db.close()

    def skip_frontier_item(self, frontier_id: str, *, reason: str) -> dict[str, Any] | None:
        return self._update_frontier_status(frontier_id, status="skipped", block_reason=reason, clear_lease=True)

    def _upsert_elements(
        self,
        db: Session,
        page_state: BrowserPageState,
        elements: list[dict[str, Any]],
        *,
        source_fidelity: str = "live_snapshot",
    ) -> list[BrowserElement]:
        rows: list[BrowserElement] = []
        now = _utcnow()
        for element in elements:
            element_key = _hash(
                "|".join(
                    [
                        page_state.state_key,
                        str(element.get("role") or ""),
                        str(element.get("name") or "").lower(),
                        str(element.get("ordinal") or 0),
                    ]
                ),
                32,
            )
            existing = db.exec(
                select(BrowserElement)
                .where(BrowserElement.project_id == self.project_id)
                .where(BrowserElement.state_id == page_state.id)
                .where(BrowserElement.element_key == element_key)
            ).first()
            if existing:
                existing.last_seen_at = now
                existing.seen_count = (existing.seen_count or 0) + 1
                existing.locator_candidates_json = element.get("locator_candidates") or existing.locator_candidates_json
                existing.importance_score = max(
                    existing.importance_score or 0,
                    (element.get("importance_score") or 0) * self._source_fidelity_score(source_fidelity),
                )
                attrs = dict(existing.attributes_json or {})
                attrs["source_fidelity"] = source_fidelity
                existing.attributes_json = attrs
                db.add(existing)
                rows.append(existing)
                continue
            attributes = {"source_fidelity": source_fidelity}
            if element.get("ref"):
                attributes["snapshot_ref"] = element.get("ref")
            row = BrowserElement(
                id=f"bpelem-{_hash(f'{self.project_id}|{page_state.id}|{element_key}', 16)}",
                project_id=self.project_id,
                state_id=page_state.id,
                element_key=element_key,
                role=element.get("role"),
                name=element.get("name"),
                text=element.get("text"),
                element_type=element.get("role"),
                locator_candidates_json=element.get("locator_candidates") or [],
                attributes_json=attributes,
                importance_score=(element.get("importance_score") or 0.5)
                * self._source_fidelity_score(source_fidelity),
                stability_score=0.7 if source_fidelity == "live_snapshot" else 0.35,
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(row)
            rows.append(row)
        if rows:
            db.commit()
            for row in rows:
                db.refresh(row)
        return rows

    def _upsert_frontier_item(self, db: Session, state: BrowserPageState, element: BrowserElement) -> None:
        if not element.id or (element.importance_score or 0) <= 0.15:
            return
        action_type = self._default_action_for_role(element.role)
        existing = db.exec(
            select(BrowserFrontierItem)
            .where(BrowserFrontierItem.project_id == self.project_id)
            .where(BrowserFrontierItem.state_id == state.id)
            .where(BrowserFrontierItem.element_id == element.id)
            .where(BrowserFrontierItem.action_type == action_type)
        ).first()
        if existing:
            return
        now = _utcnow()
        item = BrowserFrontierItem(
            id=f"bpfront-{_hash(f'{state.id}|{element.id}|{action_type}', 16)}",
            project_id=self.project_id,
            state_id=state.id,
            element_id=element.id,
            action_type=action_type,
            priority_score=self._frontier_priority(element),
            next_due_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(item)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()

    def _upsert_cluster(self, db: Session, page_state: BrowserPageState, state: CanonicalState) -> None:
        cluster_key = _hash(f"{state.page_key}|{state.simhash[:8]}", 24)
        existing = db.exec(
            select(BrowserStateCluster)
            .where(BrowserStateCluster.project_id == self.project_id)
            .where(BrowserStateCluster.cluster_key == cluster_key)
        ).first()
        now = _utcnow()
        if existing:
            existing.member_count = max(existing.member_count or 0, 1) + 1
            existing.updated_at = now
            db.add(existing)
        else:
            db.add(
                BrowserStateCluster(
                    id=f"bpclus-{cluster_key[:16]}",
                    project_id=self.project_id,
                    cluster_key=cluster_key,
                    representative_state_id=page_state.id,
                    member_count=1,
                    summary=state.embedding_text,
                    created_at=now,
                    updated_at=now,
                )
            )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()

    def _find_matching_element(self, db: Session, state_id: str, target: str | None) -> BrowserElement | None:
        if not target:
            return None
        target_norm = target.strip().lower()
        rows = db.exec(
            select(BrowserElement)
            .where(BrowserElement.project_id == self.project_id)
            .where(BrowserElement.state_id == state_id)
        ).all()
        return next((row for row in rows if (row.name or "").strip().lower() == target_norm), None)

    def _complete_matching_frontier(
        self,
        db: Session,
        *,
        transition: BrowserTransition,
        element: BrowserElement,
    ) -> None:
        item = db.exec(
            select(BrowserFrontierItem)
            .where(BrowserFrontierItem.project_id == self.project_id)
            .where(BrowserFrontierItem.state_id == transition.from_state_id)
            .where(BrowserFrontierItem.element_id == element.id)
            .where(BrowserFrontierItem.action_type == transition.action_type)
            .where(col(BrowserFrontierItem.status).in_(["queued", "in_progress"]))
        ).first()
        if not item:
            return
        item.status = "completed"
        item.block_reason = f"transition:{transition.id}"
        item.lease_owner = None
        item.lease_until = None
        item.updated_at = _utcnow()
        db.add(item)
        db.commit()

    def _update_frontier_status(
        self,
        frontier_id: str,
        *,
        status: str,
        transition_id: str | None = None,
        block_reason: str | None = None,
        clear_lease: bool = False,
    ) -> dict[str, Any] | None:
        owns_session = self.session is None
        db = self._session()
        try:
            item = db.get(BrowserFrontierItem, frontier_id)
            if not item or item.project_id != self.project_id:
                return None
            item.status = status
            if transition_id:
                item.block_reason = f"transition:{transition_id}"
            elif block_reason:
                item.block_reason = _clip(block_reason, 240)
            if clear_lease:
                item.lease_owner = None
                item.lease_until = None
            item.updated_at = _utcnow()
            db.add(item)
            db.commit()
            db.refresh(item)
            state = db.get(BrowserPageState, item.state_id)
            element = db.get(BrowserElement, item.element_id) if item.element_id else None
            return self._shape_frontier_item(item=item, state=state, element=element)
        finally:
            if owns_session:
                db.close()

    def _shape_frontier_item(
        self,
        *,
        item: BrowserFrontierItem,
        state: BrowserPageState | None,
        element: BrowserElement | None,
        risk_level: str | None = None,
    ) -> dict[str, Any]:
        best_locator = (element.locator_candidates_json or [{}])[0] if element else {}
        success_count = int(element.success_count or 0) if element else 0
        tested_count = int(element.tested_count or 0) if element else 0
        success_rate = success_count / tested_count if tested_count else None
        risk = risk_level or self._risk_level(item.action_type, element.name if element else "")
        return {
            "id": item.id,
            "state_id": item.state_id,
            "state_url": state.url if state else None,
            "state_url_template": state.url_template if state else None,
            "state_title": state.title if state else None,
            "state_last_seen_at": state.last_seen_at.isoformat() if state and state.last_seen_at else None,
            "state_visit_count": state.visit_count if state else 0,
            "state_source_fidelity": self._state_source_fidelity(state) if state else "unknown",
            "element_id": item.element_id,
            "role": element.role if element else None,
            "name": element.name if element else None,
            "text": element.text if element else None,
            "best_locator": best_locator,
            "locator_score": round(float(best_locator.get("score") or 0), 3) if isinstance(best_locator, dict) else 0,
            "action_type": item.action_type,
            "priority_score": round(float(item.priority_score or 0), 3),
            "risk_level": risk,
            "status": item.status,
            "attempts": item.attempts or 0,
            "success_rate": round(success_rate, 3) if success_rate is not None else None,
            "tested_count": tested_count,
            "importance_score": round(float(element.importance_score or 0), 3) if element else 0,
            "stability_score": round(float(element.stability_score or 0), 3) if element else 0,
            "next_due_at": item.next_due_at.isoformat() if item.next_due_at else None,
            "last_attempted_at": item.last_attempted_at.isoformat() if item.last_attempted_at else None,
            "lease_owner": item.lease_owner,
            "lease_until": item.lease_until.isoformat() if item.lease_until else None,
            "block_reason": item.block_reason,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }

    def _shape_state_snapshot(self, state: BrowserPageState) -> dict[str, Any]:
        return {
            "id": state.id,
            "project_id": state.project_id,
            "session_id": state.session_id,
            "page_key": state.page_key,
            "state_key": state.state_key,
            "url": state.url,
            "url_template": state.url_template,
            "title": state.title,
            "source_fidelity": self._state_source_fidelity(state),
            "auth_state": state.auth_state,
            "viewport": state.viewport,
            "locale": state.locale,
            "exact_hash": state.exact_hash,
            "simhash": state.simhash,
            "snapshot_ref": state.snapshot_ref,
            "visit_count": state.visit_count,
            "importance_score": round(float(state.importance_score or 0), 3),
            "novelty_score": round(float(state.novelty_score or 0), 3),
            "decay_score": round(float(state.decay_score or 0), 3),
            "status": state.status,
            "first_seen_at": state.first_seen_at.isoformat() if state.first_seen_at else None,
            "last_seen_at": state.last_seen_at.isoformat() if state.last_seen_at else None,
        }

    def _shape_element_snapshot(
        self,
        element: BrowserElement,
        state: BrowserPageState | None,
    ) -> dict[str, Any]:
        locator_candidates = element.locator_candidates_json or []
        best_locator = locator_candidates[0] if locator_candidates else {}
        logical_key = self._element_logical_key(
            page_key=state.page_key if state else "",
            role=element.role,
            name=element.name,
            text=element.text,
            element_type=element.element_type,
        )
        return {
            "id": element.id,
            "project_id": element.project_id,
            "state_id": element.state_id,
            "page_key": state.page_key if state else None,
            "state_key": state.state_key if state else None,
            "element_key": element.element_key,
            "logical_key": logical_key,
            "role": element.role,
            "name": element.name,
            "text": element.text,
            "element_type": element.element_type,
            "locator_candidates": locator_candidates,
            "best_locator": best_locator,
            "locator_signature": self._locator_signature(locator_candidates),
            "attributes": element.attributes_json or {},
            "form_context": element.form_context_json or {},
            "seen_count": element.seen_count,
            "tested_count": element.tested_count,
            "success_count": element.success_count,
            "failure_count": element.failure_count,
            "importance_score": round(float(element.importance_score or 0), 3),
            "stability_score": round(float(element.stability_score or 0), 3),
            "status": element.status,
            "first_seen_at": element.first_seen_at.isoformat() if element.first_seen_at else None,
            "last_seen_at": element.last_seen_at.isoformat() if element.last_seen_at else None,
        }

    def _diff_memory_snapshots(
        self,
        baseline: dict[str, Any],
        current: dict[str, Any],
        *,
        include_unchanged: bool,
        locator_score_drop_threshold: float,
    ) -> dict[str, Any]:
        baseline_states = self._latest_states_by_page_key(baseline.get("states") or [])
        current_states = self._latest_states_by_page_key(current.get("states") or [])
        page_changes: dict[str, list[dict[str, Any]]] = {
            "new": [],
            "changed": [],
            "removed": [],
        }
        if include_unchanged:
            page_changes["unchanged"] = []

        for page_key in sorted(set(baseline_states) | set(current_states)):
            baseline_state = baseline_states.get(page_key)
            current_state = current_states.get(page_key)
            if baseline_state is None and current_state is not None:
                page_changes["new"].append({"page_key": page_key, "current": current_state})
                continue
            if current_state is None and baseline_state is not None:
                page_changes["removed"].append({"page_key": page_key, "baseline": baseline_state})
                continue
            changed_fields = self._changed_fields(
                baseline_state or {},
                current_state or {},
                ["state_key", "exact_hash", "simhash", "url_template", "title", "source_fidelity", "status"],
            )
            if changed_fields:
                page_changes["changed"].append(
                    {
                        "page_key": page_key,
                        "baseline": baseline_state,
                        "current": current_state,
                        "changed_fields": changed_fields,
                    }
                )
            elif include_unchanged:
                page_changes["unchanged"].append(
                    {"page_key": page_key, "baseline": baseline_state, "current": current_state}
                )

        element_changes = self._diff_memory_elements(
            baseline=baseline,
            current=current,
            baseline_states_by_page=baseline_states,
            current_states_by_page=current_states,
            include_unchanged=include_unchanged,
            locator_score_drop_threshold=locator_score_drop_threshold,
        )
        summary = {
            "new_page_states": len(page_changes["new"]),
            "changed_page_states": len(page_changes["changed"]),
            "removed_page_states": len(page_changes["removed"]),
            "new_elements": len(element_changes["new"]),
            "changed_elements": len(element_changes["changed"]),
            "removed_elements": len(element_changes["removed"]),
            "locator_drift": len(element_changes["locator_drift"]),
        }
        if include_unchanged:
            summary["unchanged_page_states"] = len(page_changes["unchanged"])
            summary["unchanged_elements"] = len(element_changes["unchanged"])
        return {
            "project_id": current.get("project_id") or baseline.get("project_id") or self.project_id,
            "baseline_captured_at": baseline.get("captured_at"),
            "current_captured_at": current.get("captured_at"),
            "baseline_session_id": baseline.get("session_id"),
            "current_session_id": current.get("session_id"),
            "summary": summary,
            "page_states": page_changes,
            "elements": element_changes,
        }

    def _diff_memory_elements(
        self,
        *,
        baseline: dict[str, Any],
        current: dict[str, Any],
        baseline_states_by_page: dict[str, dict[str, Any]],
        current_states_by_page: dict[str, dict[str, Any]],
        include_unchanged: bool,
        locator_score_drop_threshold: float,
    ) -> dict[str, list[dict[str, Any]]]:
        baseline_elements = self._elements_for_latest_states(baseline.get("elements") or [], baseline_states_by_page)
        current_elements = self._elements_for_latest_states(current.get("elements") or [], current_states_by_page)
        changes: dict[str, list[dict[str, Any]]] = {
            "new": [],
            "changed": [],
            "removed": [],
            "locator_drift": [],
        }
        if include_unchanged:
            changes["unchanged"] = []

        baseline_by_id = {item.get("id"): item for item in baseline_elements if item.get("id")}
        current_by_id = {item.get("id"): item for item in current_elements if item.get("id")}
        baseline_by_logical = {item.get("logical_key"): item for item in baseline_elements if item.get("logical_key")}
        current_by_logical = {item.get("logical_key"): item for item in current_elements if item.get("logical_key")}
        paired: list[tuple[dict[str, Any], dict[str, Any], str]] = []
        used_baseline_ids: set[str] = set()
        used_current_ids: set[str] = set()

        for element_id, baseline_element in baseline_by_id.items():
            current_element = current_by_id.get(element_id)
            if current_element:
                paired.append((baseline_element, current_element, "id"))
                used_baseline_ids.add(element_id)
                used_current_ids.add(element_id)

        for logical_key, baseline_element in baseline_by_logical.items():
            baseline_id = str(baseline_element.get("id") or "")
            if baseline_id in used_baseline_ids:
                continue
            current_element = current_by_logical.get(logical_key)
            current_id = str((current_element or {}).get("id") or "")
            if not current_element or current_id in used_current_ids:
                continue
            paired.append((baseline_element, current_element, "logical_key"))
            used_baseline_ids.add(baseline_id)
            used_current_ids.add(current_id)

        for baseline_element, current_element, match_type in paired:
            changed_fields = self._changed_fields(
                baseline_element,
                current_element,
                ["role", "name", "text", "element_type", "status", "importance_score", "stability_score"],
            )
            locator_drift = self._locator_drift(baseline_element, current_element, locator_score_drop_threshold)
            if changed_fields:
                changes["changed"].append(
                    {
                        "match_type": match_type,
                        "baseline": baseline_element,
                        "current": current_element,
                        "changed_fields": changed_fields,
                    }
                )
            if locator_drift:
                changes["locator_drift"].append(
                    {
                        "match_type": match_type,
                        "baseline": baseline_element,
                        "current": current_element,
                        "drift": locator_drift,
                    }
                )
            if include_unchanged and not changed_fields and not locator_drift:
                changes["unchanged"].append(
                    {"match_type": match_type, "baseline": baseline_element, "current": current_element}
                )

        for element in current_elements:
            if str(element.get("id") or "") not in used_current_ids:
                changes["new"].append({"current": element})
        for element in baseline_elements:
            if str(element.get("id") or "") not in used_baseline_ids:
                changes["removed"].append({"baseline": element})
        return changes

    @classmethod
    def _elements_for_latest_states(
        cls,
        elements: list[dict[str, Any]],
        states_by_page: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        latest_state_ids = {state.get("id") for state in states_by_page.values()}
        return [element for element in elements if element.get("state_id") in latest_state_ids]

    @classmethod
    def _latest_states_by_page_key(cls, states: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for state in states:
            page_key = str(state.get("page_key") or "")
            if not page_key:
                continue
            existing = latest.get(page_key)
            if existing is None or str(state.get("last_seen_at") or "") > str(existing.get("last_seen_at") or ""):
                latest[page_key] = state
        return latest

    @staticmethod
    def _changed_fields(
        baseline: dict[str, Any],
        current: dict[str, Any],
        fields: list[str],
    ) -> dict[str, dict[str, Any]]:
        changed: dict[str, dict[str, Any]] = {}
        for field in fields:
            if baseline.get(field) != current.get(field):
                changed[field] = {"from": baseline.get(field), "to": current.get(field)}
        return changed

    @staticmethod
    def _locator_drift(
        baseline: dict[str, Any],
        current: dict[str, Any],
        locator_score_drop_threshold: float,
    ) -> dict[str, Any]:
        baseline_best = baseline.get("best_locator") or {}
        current_best = current.get("best_locator") or {}
        baseline_score = float(baseline_best.get("score") or 0) if isinstance(baseline_best, dict) else 0.0
        current_score = float(current_best.get("score") or 0) if isinstance(current_best, dict) else 0.0
        drift: dict[str, Any] = {}
        if baseline.get("locator_signature") != current.get("locator_signature"):
            drift["locator_candidates"] = {
                "from": baseline.get("locator_candidates") or [],
                "to": current.get("locator_candidates") or [],
            }
        for field in ["strategy", "locator", "durable"]:
            if isinstance(baseline_best, dict) and isinstance(current_best, dict) and baseline_best.get(field) != current_best.get(field):
                drift[f"best_locator.{field}"] = {"from": baseline_best.get(field), "to": current_best.get(field)}
        score_delta = round(current_score - baseline_score, 3)
        if score_delta <= -abs(locator_score_drop_threshold):
            drift["best_locator.score_delta"] = score_delta
        return drift

    @staticmethod
    def _locator_signature(locator_candidates: list[dict[str, Any]]) -> str:
        normalized = [
            {
                "strategy": candidate.get("strategy"),
                "locator": candidate.get("locator"),
                "durable": candidate.get("durable"),
                "score": round(float(candidate.get("score") or 0), 3),
            }
            for candidate in locator_candidates or []
        ]
        return _hash(json.dumps(normalized, sort_keys=True, separators=(",", ":")), 32)

    @staticmethod
    def _element_logical_key(
        *,
        page_key: str,
        role: str | None,
        name: str | None,
        text: str | None,
        element_type: str | None,
    ) -> str:
        bits = [
            page_key or "",
            (role or "").strip().lower(),
            re.sub(r"\s+", " ", (name or "").strip().lower()),
            re.sub(r"\s+", " ", (text or "").strip().lower()),
            (element_type or "").strip().lower(),
        ]
        return "|".join(bits)

    def _rank_frontier_item(
        self,
        *,
        item: BrowserFrontierItem,
        state: BrowserPageState,
        element: BrowserElement | None,
        query: str,
        risk_level: str,
    ) -> float:
        now = _utcnow()
        age_hours = max(0.0, (now - (item.updated_at or item.created_at or now)).total_seconds() / 3600)
        recency = 1.0 / (1.0 + age_hours / 168.0)
        best_locator = (element.locator_candidates_json or [{}])[0] if element else {}
        locator_score = float(best_locator.get("score") or 0.0) if isinstance(best_locator, dict) else 0.0
        tested_count = int(element.tested_count or 0) if element else 0
        success_rate = (float(element.success_count or 0) / tested_count) if element and tested_count else 0.55
        coverage_gap = 1.0 if not tested_count else 0.25
        query_text = " ".join(
            [
                state.url or "",
                state.url_template or "",
                state.title or "",
                element.role if element else "",
                element.name if element else "",
                element.text if element else "",
                item.action_type or "",
            ]
        ).lower()
        query_terms = {term for term in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(term) > 2}
        query_match = sum(1 for term in query_terms if term in query_text) / max(1, len(query_terms))
        risk_penalty = {0: 0.0, 1: 0.08, 2: 0.22}.get(self._risk_rank(risk_level), 0.3)
        lease_penalty = 0.15 if item.status == "in_progress" else 0.0
        fidelity_score = self._source_fidelity_score(self._state_source_fidelity(state))
        return (
            float(item.priority_score or 0) * 0.32
            + (float(element.importance_score or 0.0) if element else 0.0) * 0.18
            + locator_score * 0.14
            + success_rate * 0.10
            + coverage_gap * 0.12
            + recency * 0.08
            + query_match * 0.12
            + fidelity_score * 0.08
            - risk_penalty
            - lease_penalty
            - min(0.18, (item.attempts or 0) * 0.04)
        )

    def _index_page_state(self, state: BrowserPageState, document: str) -> None:
        try:
            from .vector_store import get_vector_store

            get_vector_store(project_id=self.project_id).add_browser_page_state(
                state.id,
                document,
                {
                    "project_id": self.project_id,
                    "page_key": state.page_key,
                    "state_key": state.state_key,
                    "url": state.url,
                    "status": state.status,
                },
            )
        except Exception:
            pass

    def _index_element(self, element: BrowserElement, state: BrowserPageState) -> None:
        try:
            from .vector_store import get_vector_store

            locator = (element.locator_candidates_json or [{}])[0].get("locator", "")
            document = f"{element.role or ''} {element.name or element.text or ''} on {state.url_template} {locator}".strip()
            get_vector_store(project_id=self.project_id).add_browser_element(
                element.id,
                document,
                {
                    "project_id": self.project_id,
                    "state_id": state.id,
                    "page_key": state.page_key,
                    "role": element.role or "",
                    "name": element.name or "",
                    "importance_score": float(element.importance_score or 0),
                    "status": element.status,
                },
            )
        except Exception:
            pass

    def _project_state_to_graph(self, state: BrowserPageState, elements: list[BrowserElement]) -> None:
        try:
            from .graph_store import get_graph_store

            graph = get_graph_store(project_id=self.project_id)
            graph.add_page_state(
                state.id,
                url=state.url,
                page_key=state.page_key,
                state_key=state.state_key,
                title=state.title,
                metadata={"visit_count": state.visit_count, "importance_score": state.importance_score},
            )
            for element in elements:
                graph.add_state_element(
                    state.id,
                    element.id,
                    element_type=element.element_type or element.role or "element",
                    selector=(element.locator_candidates_json or [{}])[0],
                    text=element.name or element.text,
                    metadata={"importance_score": element.importance_score},
                )
            graph.save()
        except Exception:
            pass

    def _project_transition_to_graph(
        self, transition: BrowserTransition, from_state: BrowserPageState, to_state: BrowserPageState
    ) -> None:
        try:
            from .graph_store import get_graph_store

            graph = get_graph_store(project_id=self.project_id)
            graph.add_state_transition(
                from_state.id,
                to_state.id,
                action_type=transition.action_type,
                trigger=transition.element_id,
                metadata={"success_count": transition.success_count, "risk_level": transition.risk_level},
            )
            graph.save()
        except Exception:
            pass

    @staticmethod
    def _state_source_fidelity(state: BrowserPageState | None) -> str:
        if not state:
            return "unknown"
        canonical = state.canonical_json or {}
        return str(canonical.get("source_fidelity") or state.page_type or "unknown")

    @staticmethod
    def _source_fidelity_score(source_fidelity: str | None) -> float:
        return {
            "live_snapshot": 1.0,
            "snapshot": 0.9,
            "action_trace": 0.45,
            "url_only": 0.25,
        }.get((source_fidelity or "unknown").lower(), 0.5)

    @staticmethod
    def _state_importance(elements: list[dict[str, Any]]) -> float:
        if not elements:
            return 0.25
        return round(min(1.0, sum(float(e.get("importance_score") or 0) for e in elements[:20]) / 5), 3)

    @staticmethod
    def _frontier_priority(element: BrowserElement) -> float:
        novelty = 0.3
        importance = 0.2 * float(element.importance_score or 0.5)
        coverage_gap = 0.15 if not element.tested_count else 0
        success_probability = 0.05
        duplicate_penalty = 0.0
        risk_penalty = 0.2 if any(term in (element.name or "").lower() for term in RISKY_TERMS) else 0
        return round(max(0.0, min(1.0, novelty + importance + coverage_gap + success_probability - duplicate_penalty - risk_penalty)), 3)

    @staticmethod
    def _action_signature(action_type: str, target: str | None, element_id: str | None) -> str:
        return _hash(f"{action_type or 'unknown'}|{(target or '').lower()}|{element_id or ''}", 32)

    @staticmethod
    def _role_for_action(action_type: str) -> str:
        if action_type in {"fill", "type"}:
            return "textbox"
        if action_type in {"select"}:
            return "combobox"
        if action_type in {"check", "uncheck"}:
            return "checkbox"
        return "button"

    @staticmethod
    def _default_action_for_role(role: str | None) -> str:
        if role in {"textbox"}:
            return "fill"
        if role in {"combobox"}:
            return "select"
        if role in {"checkbox", "radio", "switch"}:
            return "check"
        return "click"

    @staticmethod
    def _risk_level(action_type: str | None, target: str | None) -> str:
        target_norm = (target or "").lower()
        if any(term in target_norm for term in RISKY_TERMS):
            return "high"
        if action_type in {"file_upload", "drag"}:
            return "medium"
        return "low"

    @staticmethod
    def _risk_rank(risk_level: str | None) -> int:
        return {"low": 0, "medium": 1, "high": 2}.get((risk_level or "medium").lower(), 1)


def get_exploration_memory_service(
    session: Session | None = None, project_id: str | None = None
) -> ExplorationMemoryService:
    return ExplorationMemoryService(session=session, project_id=project_id)
