"""Validation and quality scoring for AI-generated workflow artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from orchestrator.ai.context import SOURCE_FALLBACK, SOURCE_INFERRED, SOURCE_OBSERVED

VALID_FLOW_CATEGORIES = {
    "authentication",
    "crud",
    "navigation",
    "form_submission",
    "search",
    "checkout",
    "settings",
    "reporting",
    "api",
    "other",
}


@dataclass
class ValidationIssue:
    record_type: str
    index: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _has_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_valid_transition(record: Any) -> tuple[bool, str | None]:
    if not _has_text(getattr(record, "action_type", None)):
        return False, "missing action_type"
    if not _has_text(getattr(record, "before_url", None)) and not _has_text(getattr(record, "after_url", None)):
        return False, "missing before_url/after_url"
    return True, None


def is_valid_flow(record: Any) -> tuple[bool, str | None]:
    if not _has_text(getattr(record, "name", None)):
        return False, "missing name"
    if not _has_text(getattr(record, "start_url", None)) and not _has_text(getattr(record, "end_url", None)):
        return False, "missing start_url/end_url"
    steps = getattr(record, "steps", None)
    if steps is not None:
        if not isinstance(steps, list):
            return False, "steps must be a list"
        for idx, step in enumerate(steps, 1):
            if isinstance(step, dict):
                if not _has_text(step.get("action") or step.get("action_type") or step.get("type")):
                    return False, f"step {idx} missing action"
            elif not _has_text(step):
                return False, f"step {idx} is empty"
    return True, None


def is_valid_issue(record: Any) -> tuple[bool, str | None]:
    if not _has_text(getattr(record, "issue_type", None)):
        return False, "missing issue_type"
    if not _has_text(getattr(record, "description", None)):
        return False, "missing description"
    return True, None


def validate_exploration_result(result: Any) -> dict[str, Any]:
    """Validate parsed exploration records before persistence."""

    issues: list[ValidationIssue] = []
    valid_counts = {"transitions": 0, "flows": 0, "issues": 0, "api_endpoints": 0}

    for idx, transition in enumerate(getattr(result, "transitions", []) or [], 1):
        valid, message = is_valid_transition(transition)
        if valid:
            valid_counts["transitions"] += 1
        else:
            issues.append(ValidationIssue("transition", idx, message or "invalid transition"))

    for idx, flow in enumerate(getattr(result, "flows", []) or [], 1):
        valid, message = is_valid_flow(flow)
        if valid:
            valid_counts["flows"] += 1
        else:
            issues.append(ValidationIssue("flow", idx, message or "invalid flow"))

    for idx, issue in enumerate(getattr(result, "issues", []) or [], 1):
        valid, message = is_valid_issue(issue)
        if valid:
            valid_counts["issues"] += 1
        else:
            issues.append(ValidationIssue("issue", idx, message or "invalid issue"))

    valid_counts["api_endpoints"] = len(getattr(result, "api_endpoints", []) or [])

    return {
        "valid": not issues,
        "valid_counts": valid_counts,
        "invalid_records": [issue.to_dict() for issue in issues],
    }


def assess_exploration_quality(
    result: Any,
    *,
    fallback_used: bool = False,
    verified_tool_calls: int = 0,
    structured_records_count: int | None = None,
) -> dict[str, Any]:
    """Compute a compact reliability score for exploration evidence."""

    transitions = len(getattr(result, "transitions", []) or [])
    flows = len(getattr(result, "flows", []) or [])
    api_endpoints = len(getattr(result, "api_endpoints", []) or [])
    pages = int(getattr(result, "pages_discovered", 0) or 0)
    status = getattr(result, "status", "unknown")
    structured = structured_records_count if structured_records_count is not None else transitions + flows + api_endpoints

    score = 0
    score += min(25, transitions * 5)
    score += min(25, flows * 10)
    score += min(15, pages * 5)
    score += min(10, api_endpoints * 3)
    score += min(20, verified_tool_calls)
    score += 15 if status == "completed" else 0
    if fallback_used:
        score -= 35
    if transitions == 0 and flows == 0:
        score -= 25
    score = max(0, min(100, score))

    if fallback_used:
        source_type = SOURCE_FALLBACK
    elif transitions > 0 or verified_tool_calls > 0:
        source_type = SOURCE_OBSERVED
    else:
        source_type = SOURCE_INFERRED

    degraded_reasons: list[str] = []
    if fallback_used:
        degraded_reasons.append("deterministic_fallback_used")
    if transitions == 0:
        degraded_reasons.append("no_structured_transitions")
    if flows == 0:
        degraded_reasons.append("no_structured_flows")
    if status != "completed":
        degraded_reasons.append(f"status_{status}")

    return {
        "quality_score": score,
        "source_type": source_type,
        "verified_tool_calls": verified_tool_calls,
        "structured_records_count": structured,
        "fallback_used": fallback_used,
        "degraded_mode": score < 50,
        "degraded_mode_reason": ", ".join(degraded_reasons) if score < 50 else None,
    }


def should_gate_exploration(
    quality_summary: dict[str, Any] | None,
    validation_summary: dict[str, Any] | None,
    *,
    min_quality_score: int = 50,
    allow_fallback: bool = False,
) -> tuple[bool, str | None]:
    """Return whether downstream generation should stop for an exploration artifact."""

    quality_summary = quality_summary or {}
    validation_summary = validation_summary or {}

    if validation_summary and not validation_summary.get("valid", True):
        return True, "validation_failed"

    source_type = quality_summary.get("source_type")
    if source_type == SOURCE_FALLBACK and not allow_fallback:
        return True, "fallback_source"
    if source_type == SOURCE_INFERRED and not allow_fallback:
        return True, "inferred_source"

    try:
        score = int(quality_summary.get("quality_score", 100))
    except (TypeError, ValueError):
        score = 0
    if score < min_quality_score:
        return True, f"quality_below_{min_quality_score}"

    return False, None
