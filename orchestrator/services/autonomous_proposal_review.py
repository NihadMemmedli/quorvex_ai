"""Review helpers for autonomous test proposal duplicate and stale checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlmodel import Session, col, select

from orchestrator.api.models_db import (
    AutonomousFinding,
    AutonomousTestProposal,
    BrowserPageState,
    CoverageGap,
    SpecMetadata,
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent

@dataclass
class ReviewRefreshResult:
    proposals: list[AutonomousTestProposal]
    counts: dict[str, int]


def _utc_iso() -> str:
    return datetime.utcnow().isoformat()


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (value or "").lower())).strip()


def _similarity(a: str | None, b: str | None) -> float:
    left = _normalize_text(a)
    right = _normalize_text(b)
    if not left or not right:
        return 0.0
    sequence_score = SequenceMatcher(None, left, right).ratio()
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    token_score = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    return max(sequence_score, token_score)


def _route_from_url(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        route = parsed.path or "/"
        return route.rstrip("/") or "/"
    return value.rstrip("/") or "/"


def _review_text(proposal: AutonomousTestProposal) -> str:
    return " ".join(
        part
        for part in [
            proposal.title,
            proposal.rationale,
            proposal.target_url,
            proposal.route,
            proposal.suggested_file_path,
            proposal.generated_spec_content[:1200] if proposal.generated_spec_content else "",
        ]
        if part
    )


def _safe_relative_path(value: str | None) -> Path | None:
    if not value:
        return None
    raw = value.strip()
    if not raw or "\\" in raw or "\n" in raw or "\r" in raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    return candidate


class AutonomousProposalReviewService:
    """Computes review context for autonomous test proposals."""

    def __init__(self, session: Session, *, base_dir: Path | None = None):
        self.session = session
        self.base_dir = base_dir or BASE_DIR
        self.generated_test_roots = (
            self.base_dir / "tests" / "generated",
            self.base_dir / "orchestrator" / "tests" / "generated",
        )

    def build_review_context(self, proposal: AutonomousTestProposal) -> dict[str, Any]:
        finding = self.session.get(AutonomousFinding, proposal.finding_id) if proposal.finding_id else None
        source_metadata = proposal.source_metadata or {}
        evidence = finding.evidence if finding else {}
        confidence = source_metadata.get("confidence")
        if confidence is None and finding:
            confidence = finding.confidence

        duplicate = self._duplicate_review(proposal)
        staleness = self._staleness_review(proposal, source_metadata)
        merge_gate = self._merge_gate(proposal)
        return {
            "provenance": {
                "source_type": proposal.source_type,
                "source_id": proposal.source_id,
                "finding_id": proposal.finding_id,
                "coverage_gap_id": proposal.coverage_gap_id,
                "confidence": confidence,
                "evidence": evidence,
            },
            "duplicate": duplicate,
            "staleness": staleness,
            "merge_gate": merge_gate,
        }

    def refresh_review(self, proposal: AutonomousTestProposal) -> dict[str, Any]:
        review = self.build_review_context(proposal)
        metadata = dict(proposal.source_metadata or {})
        metadata["review"] = {
            "duplicate": review["duplicate"],
            "staleness": review["staleness"],
            "checked_at": _utc_iso(),
        }
        proposal.source_metadata = metadata
        proposal.updated_at = datetime.utcnow()
        self.session.add(proposal)
        self.session.commit()
        self.session.refresh(proposal)
        return review

    def refresh_reviews(
        self,
        project_id: str,
        *,
        mission_id: str | None = None,
        status: str | None = None,
        stale_only: bool = False,
        duplicate_only: bool = False,
        limit: int = 200,
    ) -> ReviewRefreshResult:
        statement = select(AutonomousTestProposal).where(AutonomousTestProposal.project_id == project_id)
        if mission_id:
            statement = statement.where(AutonomousTestProposal.mission_id == mission_id)
        if status:
            statement = statement.where(AutonomousTestProposal.approval_status == status)
        proposals = self.session.exec(
            statement.order_by(col(AutonomousTestProposal.created_at).desc()).limit(limit)
        ).all()
        refreshed: list[AutonomousTestProposal] = []
        counts = {"total": 0, "blocking_duplicates": 0, "duplicate_warnings": 0, "stale": 0, "needs_review": 0}
        for proposal in proposals:
            review = self.build_review_context(proposal)
            duplicate = review.get("duplicate") or {}
            staleness = review.get("staleness") or {}
            is_duplicate = bool(duplicate.get("has_warning"))
            is_stale_or_review = staleness.get("status") in {"stale", "needs_review"}
            if duplicate_only and not is_duplicate:
                continue
            if stale_only and not is_stale_or_review:
                continue
            metadata = dict(proposal.source_metadata or {})
            metadata["review"] = {
                "duplicate": duplicate,
                "staleness": staleness,
                "checked_at": _utc_iso(),
            }
            proposal.source_metadata = metadata
            proposal.updated_at = datetime.utcnow()
            self.session.add(proposal)
            refreshed.append(proposal)
            counts["total"] += 1
            if duplicate.get("blocking"):
                counts["blocking_duplicates"] += 1
            elif duplicate.get("has_warning"):
                counts["duplicate_warnings"] += 1
            if staleness.get("status") == "stale":
                counts["stale"] += 1
            elif staleness.get("status") == "needs_review":
                counts["needs_review"] += 1
        if refreshed:
            self.session.commit()
            for proposal in refreshed:
                self.session.refresh(proposal)
        return ReviewRefreshResult(proposals=refreshed, counts=counts)

    def proposal_review_queue(self, project_id: str, *, limit: int = 200) -> dict[str, Any]:
        proposals = self.session.exec(
            select(AutonomousTestProposal)
            .where(AutonomousTestProposal.project_id == project_id)
            .order_by(col(AutonomousTestProposal.created_at).desc())
            .limit(limit)
        ).all()
        grouped: dict[str, list[dict[str, Any]]] = {
            "blocking_duplicates": [],
            "duplicate_warnings": [],
            "stale": [],
            "needs_review": [],
        }
        for proposal in proposals:
            review = self.build_review_context(proposal)
            shaped = {"proposal_id": proposal.id, "title": proposal.title, "review_context": review}
            duplicate = review.get("duplicate") or {}
            staleness = review.get("staleness") or {}
            if duplicate.get("blocking"):
                grouped["blocking_duplicates"].append(shaped)
            elif duplicate.get("has_warning"):
                grouped["duplicate_warnings"].append(shaped)
            if staleness.get("status") == "stale":
                grouped["stale"].append(shaped)
            elif staleness.get("status") == "needs_review":
                grouped["needs_review"].append(shaped)
        return {
            **grouped,
            "counts": {key: len(value) for key, value in grouped.items()},
        }

    def _duplicate_review(self, proposal: AutonomousTestProposal) -> dict[str, Any]:
        matches: list[dict[str, Any]] = []
        existing_path = self._materialization_path_exists(proposal.suggested_file_path)
        if existing_path:
            matches.append(
                {
                    "kind": "generated_test",
                    "id": proposal.suggested_file_path,
                    "path": proposal.suggested_file_path,
                    "title": "Existing generated test file",
                    "score": 1.0,
                    "status": "materialized",
                    "blocking": True,
                    "reasons": ["suggested file already exists"],
                }
            )

        for other in self._proposal_candidates(proposal):
            match = self._proposal_match(proposal, other)
            if match:
                matches.append(match)

        for match in self._generated_file_matches(proposal):
            matches.append(match)

        for match in self._spec_metadata_matches(proposal):
            matches.append(match)

        matches = self._dedupe_matches(matches)
        matches.sort(key=lambda item: (bool(item.get("blocking")), float(item.get("score") or 0)), reverse=True)
        blocking = any(bool(match.get("blocking")) for match in matches)
        has_warning = bool(matches)
        severity = "blocking" if blocking else "warning" if has_warning else "none"
        proposal_candidates = [match for match in matches if match.get("kind") == "proposal"]
        return {
            "has_warning": has_warning,
            "existing_file_conflict": existing_path,
            "blocking": blocking,
            "severity": severity,
            "matches": matches[:8],
            "candidates": [
                {
                    "id": match.get("id"),
                    "title": match.get("title"),
                    "status": match.get("status"),
                    "suggested_file_path": match.get("path"),
                    "score": match.get("score"),
                    "reasons": match.get("reasons") or [],
                }
                for match in proposal_candidates[:5]
            ],
        }

    def _proposal_candidates(self, proposal: AutonomousTestProposal) -> list[AutonomousTestProposal]:
        return self.session.exec(
            select(AutonomousTestProposal).where(
                AutonomousTestProposal.project_id == proposal.project_id,
                AutonomousTestProposal.id != proposal.id,
            )
        ).all()

    def _proposal_match(self, proposal: AutonomousTestProposal, other: AutonomousTestProposal) -> dict[str, Any] | None:
        reasons: list[str] = []
        score = 0.0
        blocking = False
        if proposal.suggested_file_path and proposal.suggested_file_path in {
            other.suggested_file_path,
            other.materialized_file_path,
        }:
            reasons.append("same file path")
            score = max(score, 1.0)
            blocking = other.approval_status == "materialized"
        if proposal.source_type and proposal.source_type == other.source_type and proposal.source_id and proposal.source_id == other.source_id:
            reasons.append("same source")
            score = max(score, 0.96)
            blocking = blocking or other.approval_status == "materialized"
        if self._same_target_and_type(proposal, other):
            reasons.append("same route and test type")
            score = max(score, 0.92)
            blocking = blocking or other.approval_status == "materialized"
        title_similarity = _similarity(proposal.title, other.title)
        if title_similarity >= 0.82:
            reasons.append("similar title")
            score = max(score, title_similarity)
        body_similarity = _similarity(_review_text(proposal), _review_text(other))
        if body_similarity >= 0.88:
            reasons.append("similar generated content")
            score = max(score, body_similarity)
        if not reasons:
            return None
        return {
            "kind": "proposal",
            "id": other.id,
            "path": other.materialized_file_path or other.suggested_file_path,
            "title": other.title,
            "score": round(score, 3),
            "status": other.approval_status,
            "blocking": blocking,
            "reasons": reasons,
        }

    def _same_target_and_type(self, proposal: AutonomousTestProposal, other: AutonomousTestProposal) -> bool:
        if proposal.test_type != other.test_type:
            return False
        proposal_route = _route_from_url(proposal.route or proposal.target_url)
        other_route = _route_from_url(other.route or other.target_url)
        return bool(proposal_route and other_route and proposal_route == other_route)

    def _generated_file_matches(self, proposal: AutonomousTestProposal) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        candidate_name = _normalize_text(Path(proposal.suggested_file_path or "").stem)
        title_text = _normalize_text(proposal.title)
        for root in self.generated_test_roots:
            if not root.exists():
                continue
            for path in root.rglob("*.py" if proposal.test_type in {"api", "unit"} else "*.spec.ts"):
                relative = path.relative_to(self.base_dir).as_posix()
                if relative == proposal.suggested_file_path:
                    continue
                similarity = max(_similarity(candidate_name, path.stem), _similarity(title_text, path.stem))
                if similarity < 0.88:
                    continue
                matches.append(
                    {
                        "kind": "generated_test",
                        "id": relative,
                        "path": relative,
                        "title": path.stem.replace("-", " "),
                        "score": round(similarity, 3),
                        "status": "materialized",
                        "blocking": False,
                        "reasons": ["similar generated test filename"],
                    }
                )
        return matches[:5]

    def _spec_metadata_matches(self, proposal: AutonomousTestProposal) -> list[dict[str, Any]]:
        rows = self.session.exec(
            select(SpecMetadata).where(
                (SpecMetadata.project_id == proposal.project_id) | (SpecMetadata.project_id.is_(None))
            )
        ).all()
        matches: list[dict[str, Any]] = []
        proposal_text = _normalize_text(f"{proposal.title} {proposal.rationale or ''} {proposal.suggested_file_path or ''}")
        for spec in rows[:500]:
            spec_text = _normalize_text(f"{spec.spec_name} {spec.description or ''} {' '.join(spec.tags)}")
            score = _similarity(proposal_text, spec_text)
            if score < 0.86:
                continue
            matches.append(
                {
                    "kind": "spec_metadata",
                    "id": spec.spec_name,
                    "path": spec.spec_name,
                    "title": spec.description or spec.spec_name,
                    "score": round(score, 3),
                    "status": "existing_spec",
                    "blocking": False,
                    "reasons": ["similar existing spec metadata"],
                }
            )
        matches.sort(key=lambda item: item["score"], reverse=True)
        return matches[:5]

    def _staleness_review(self, proposal: AutonomousTestProposal, source_metadata: dict[str, Any]) -> dict[str, Any]:
        reasons: list[dict[str, Any]] = []
        if source_metadata.get("stale") or source_metadata.get("stale_reason"):
            reasons.append(
                {
                    "source": "proposal_metadata",
                    "message": str(source_metadata.get("stale_reason") or "Proposal source metadata is marked stale."),
                    "confidence": 1.0,
                    "stale": True,
                }
            )
        if proposal.coverage_gap_id:
            gap = self.session.get(CoverageGap, proposal.coverage_gap_id)
            if gap and gap.resolved:
                reasons.append(
                    {
                        "source": "coverage_gap",
                        "message": "Source coverage gap has been resolved.",
                        "confidence": 1.0,
                        "entity_id": proposal.coverage_gap_id,
                        "stale": True,
                    }
                )
        if proposal.finding_id:
            finding = self.session.get(AutonomousFinding, proposal.finding_id)
            if finding and finding.status in {"resolved", "rejected"}:
                reasons.append(
                    {
                        "source": "finding",
                        "message": f"Linked finding is {finding.status}.",
                        "confidence": 0.9,
                        "entity_id": proposal.finding_id,
                        "stale": True,
                    }
                )

        browser_reasons = self._browser_memory_reasons(proposal, source_metadata)
        reasons.extend(browser_reasons)
        status = "fresh"
        if any(reason.get("stale") for reason in reasons):
            status = "stale"
        elif reasons:
            status = "needs_review"
        first_reason = reasons[0]["message"] if reasons else None
        return {
            "is_stale": status == "stale",
            "reason": first_reason,
            "status": status,
            "reasons": reasons,
            "last_checked_at": _utc_iso(),
        }

    def _browser_memory_reasons(self, proposal: AutonomousTestProposal, source_metadata: dict[str, Any]) -> list[dict[str, Any]]:
        if not proposal.project_id:
            return []
        route = _route_from_url(proposal.route or proposal.target_url)
        if not route:
            return []
        states = self.session.exec(
            select(BrowserPageState)
            .where(BrowserPageState.project_id == proposal.project_id)
            .where(BrowserPageState.status == "active")
            .order_by(col(BrowserPageState.last_seen_at).desc())
            .limit(500)
        ).all()
        if not states:
            return []
        matching = [state for state in states if self._state_matches_route(state, route)]
        has_exploration_source = bool(
            source_metadata.get("exploration_session_id")
            or source_metadata.get("source_session_id")
            or (proposal.source_type and "exploration" in proposal.source_type)
        )
        if not matching:
            return [
                {
                    "source": "browser_memory",
                    "message": f"Route {route} was not found in recent active browser memory.",
                    "confidence": 0.65,
                    "stale": False,
                }
            ]
        newest = matching[0]
        if has_exploration_source and newest.last_seen_at and proposal.created_at and newest.last_seen_at > proposal.created_at:
            return [
                {
                    "source": "browser_memory",
                    "message": f"Route {route} has newer browser observations than this proposal.",
                    "confidence": 0.72,
                    "entity_id": newest.id,
                    "stale": False,
                }
            ]
        return []

    def _state_matches_route(self, state: BrowserPageState, route: str) -> bool:
        state_route = _route_from_url(state.url_template or state.url)
        state_url_route = _route_from_url(state.url)
        return route in {state_route, state_url_route}

    def _materialization_path_exists(self, raw_path: str | None) -> bool:
        relative = _safe_relative_path(raw_path)
        if relative is None:
            return False
        try:
            target = (self.base_dir / relative).resolve()
            target.relative_to(self.base_dir.resolve())
            return target.exists()
        except ValueError:
            return False

    def _merge_gate(self, proposal: AutonomousTestProposal) -> str:
        if proposal.approval_status == "approved":
            return "ready_to_materialize"
        if proposal.approval_status == "materialized":
            return "ready_for_pr"
        if proposal.approval_status == "rejected":
            return "rejected"
        return "needs_approval"

    def _dedupe_matches(self, matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for match in matches:
            key = f"{match.get('kind')}:{match.get('id') or match.get('path')}"
            existing = seen.get(key)
            if existing is None or float(match.get("score") or 0) > float(existing.get("score") or 0):
                seen[key] = match
            elif existing:
                existing["blocking"] = bool(existing.get("blocking") or match.get("blocking"))
                existing["reasons"] = sorted(set((existing.get("reasons") or []) + (match.get("reasons") or [])))
        return list(seen.values())


def review_context_for_proposal(proposal: AutonomousTestProposal, session: Session) -> dict[str, Any]:
    return AutonomousProposalReviewService(session).build_review_context(proposal)


def review_snapshot_from_metadata(proposal: AutonomousTestProposal) -> dict[str, Any] | None:
    value = (proposal.source_metadata or {}).get("review")
    return value if isinstance(value, dict) else None
