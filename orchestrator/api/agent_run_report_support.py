"""Shared helpers for custom-agent structured reports."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from utils.agent_report import _as_report_list, _clean_text

from .models_db import AgentRun

logger = logging.getLogger(__name__)


def _report_confidence(value: str | None) -> float:
    normalized = str(value or "").lower()
    if normalized == "high":
        return 0.86
    if normalized == "low":
        return 0.58
    return 0.72


def _report_importance(value: str | None) -> float:
    normalized = str(value or "").lower()
    if normalized == "critical":
        return 0.95
    if normalized == "high":
        return 0.84
    if normalized == "low":
        return 0.54
    if normalized == "info":
        return 0.42
    return 0.7


def _report_requirement_confidence(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(float(value), 1.0))
    normalized = _clean_text(value, 20).lower()
    if normalized == "high":
        return 0.86
    if normalized == "low":
        return 0.58
    if normalized == "medium":
        return 0.72
    try:
        return max(0.0, min(float(normalized), 1.0))
    except (TypeError, ValueError):
        return 0.7


def _report_requirement_acceptance_criteria(item: dict[str, Any]) -> list[str]:
    criteria = [
        _clean_text(criterion, 500)
        for criterion in _as_report_list(item.get("acceptance_criteria") or item.get("criteria"))
        if _clean_text(criterion, 500)
    ]
    if not criteria:
        expected = _clean_text(item.get("expected") or item.get("expected_result"), 500)
        if expected:
            criteria.append(expected)
    if not criteria and item.get("evidence"):
        criteria.append(f"Evidence reviewed: {_clean_text(item.get('evidence'), 450)}")
    return criteria[:10]


def _requirement_create_body_from_report_item(item: dict[str, Any]) -> dict[str, Any]:
    priority = _clean_text(item.get("priority") or item.get("severity") or "medium", 20).lower()
    if priority not in {"critical", "high", "medium", "low"}:
        priority = "medium"
    description_parts = [
        _clean_text(item.get("description") or item.get("summary"), 2000),
        f"Page: {_clean_text(item.get('page') or item.get('url'), 500)}" if item.get("page") or item.get("url") else "",
        f"Evidence: {_clean_text(item.get('evidence'), 1200)}" if item.get("evidence") else "",
    ]
    description = " ".join(part for part in description_parts if part).strip() or None
    return {
        "title": _clean_text(item.get("title") or item.get("name") or item.get("requirement"), 180),
        "description": description,
        "category": _clean_text(item.get("category") or "functional", 80).lower() or "functional",
        "priority": priority,
        "acceptance_criteria": _report_requirement_acceptance_criteria(item),
        "truth_state": "candidate_requirement",
        "source_type": "custom_agent_run",
        "confidence": _report_requirement_confidence(item.get("confidence")),
        "uncertainty_reason": "Imported from a custom agent report; agent-derived requirement requires human review.",
    }


REPORT_ITEM_COLLECTIONS = {
    "finding": "findings",
    "test_idea": "test_ideas",
    "requirement": "requirements",
}

REPORT_ITEM_EDITABLE_FIELDS = {
    "finding": {"title", "severity", "page", "description", "evidence", "suggested_action", "confidence"},
    "test_idea": {"title", "priority", "page", "steps", "expected", "source_finding_id"},
    "requirement": {
        "title",
        "description",
        "category",
        "priority",
        "acceptance_criteria",
        "page",
        "evidence",
        "confidence",
    },
}

REPORT_ITEM_LIST_FIELDS = {"steps", "acceptance_criteria"}
REPORT_ITEM_PROTECTED_FIELDS = {"id", "imported_requirement_id", "imported_requirement_code", "imported_at"}


def _normalize_report_item_type(item_type: str | None) -> str:
    normalized = (item_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "findings": "finding",
        "test": "test_idea",
        "test_ideas": "test_idea",
        "tests": "test_idea",
        "requirement": "requirement",
        "requirements": "requirement",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in REPORT_ITEM_COLLECTIONS:
        raise HTTPException(status_code=400, detail="item_type must be finding, test_idea, or requirement")
    return normalized


def _stored_custom_agent_report(run: AgentRun) -> tuple[dict[str, Any], dict[str, Any]]:
    if run.agent_type != "custom":
        raise HTTPException(status_code=400, detail="Only custom agent reports can be edited")
    result = run.result or {}
    report = result.get("structured_report") if isinstance(result, dict) else None
    if not isinstance(report, dict):
        raise HTTPException(status_code=400, detail="This run does not have a stored structured report")
    return result, report


def _normalize_report_patch_value(field: str, value: Any) -> Any:
    if field in REPORT_ITEM_LIST_FIELDS:
        return [_clean_text(item, 1000) for item in _as_report_list(value) if _clean_text(item, 1000)]
    if value is None:
        return None
    if field == "confidence" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    max_length = 2000 if field in {"description", "evidence", "suggested_action", "expected"} else 500
    if field in {"title"}:
        max_length = 220
    if field in {"severity", "priority", "category", "source_finding_id"}:
        max_length = 80
    return _clean_text(value, max_length)


def _editable_report_item_patch(item_type: str, patch: dict[str, Any]) -> dict[str, Any]:
    allowed = REPORT_ITEM_EDITABLE_FIELDS[item_type]
    blocked = sorted(field for field in patch if field not in allowed or field in REPORT_ITEM_PROTECTED_FIELDS)
    if blocked:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Report item patch contains uneditable fields",
                "fields": blocked,
                "allowed_fields": sorted(allowed),
            },
        )
    return {
        field: _normalize_report_patch_value(field, value)
        for field, value in patch.items()
    }


def _find_report_item(report: dict[str, Any], item_type: str, item_id: str) -> dict[str, Any]:
    collection = REPORT_ITEM_COLLECTIONS[item_type]
    for item in _as_report_list(report.get(collection)):
        if isinstance(item, dict) and str(item.get("id") or "") == item_id:
            return item
    raise HTTPException(status_code=404, detail=f"Report {item_type} item {item_id} not found")


def _capture_custom_agent_report_memory(
    *,
    run_id: str,
    project_id: str | None,
    structured_report: dict[str, Any],
    config: dict[str, Any],
) -> list[str]:
    """Store review-gated memories from a custom agent's normalized report."""
    if not project_id or not isinstance(structured_report, dict):
        return []

    try:
        from orchestrator.memory.agent_memory import get_agent_memory_service
    except Exception as exc:
        logger.debug("Custom agent memory capture unavailable for %s: %s", run_id, exc)
        return []

    service = get_agent_memory_service()
    stored_ids: list[str] = []
    agent_name = _clean_text(config.get("agent_name") or "Custom agent", 120)
    source_type = "custom_agent_run"

    def store(
        *,
        kind: str,
        content: str,
        summary: str,
        tags: list[str],
        confidence: float,
        importance: float,
        extra_data: dict[str, Any],
    ) -> None:
        try:
            memory = service.create_memory(
                kind=kind,
                content=content,
                project_id=project_id,
                summary=summary,
                tags=["custom-agent", *tags],
                confidence=confidence,
                importance=importance,
                source_type=source_type,
                source_id=run_id,
                agent_type="CustomAgent",
                review_required=True,
                extra_data={"agent_run_id": run_id, "agent_name": agent_name, **extra_data},
            )
            if memory and memory.id not in stored_ids:
                stored_ids.append(memory.id)
        except Exception as exc:
            logger.debug("Skipped custom agent memory candidate for %s: %s", run_id, exc)

    summary = _clean_text(structured_report.get("summary"), 500)
    scope = _clean_text(structured_report.get("scope") or config.get("prompt") or config.get("url"), 500)
    if summary:
        store(
            kind="project_fact",
            content=f"{agent_name} summary: {summary}" + (f" Scope: {scope}" if scope else ""),
            summary=f"{agent_name}: {summary}",
            tags=["summary"],
            confidence=0.68,
            importance=0.5,
            extra_data={"report_section": "summary"},
        )

    findings = _as_report_list(structured_report.get("findings"))[:5]
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        title = _clean_text(finding.get("title"), 180)
        if not title:
            continue
        severity = _clean_text(finding.get("severity") or "medium", 30).lower()
        page = _clean_text(finding.get("page"), 300)
        description = _clean_text(finding.get("description"), 600)
        evidence = _clean_text(finding.get("evidence"), 500)
        suggested_action = _clean_text(finding.get("suggested_action"), 400)
        content = (
            f"Custom agent finding: {title}. "
            f"Severity: {severity}. "
            f"{f'Page: {page}. ' if page else ''}"
            f"{f'Description: {description}. ' if description else ''}"
            f"{f'Evidence: {evidence}. ' if evidence else ''}"
            f"{f'Suggested action: {suggested_action}.' if suggested_action else ''}"
        )
        store(
            kind="project_fact" if severity == "info" else "failure_pattern",
            content=content,
            summary=f"{title} ({severity})",
            tags=["finding", severity],
            confidence=_report_confidence(str(finding.get("confidence") or "")),
            importance=_report_importance(severity),
            extra_data={"report_section": "findings", "finding_id": finding.get("id")},
        )

    test_ideas = _as_report_list(structured_report.get("test_ideas"))[:5]
    for idea in test_ideas:
        if not isinstance(idea, dict):
            continue
        title = _clean_text(idea.get("title"), 180)
        if not title:
            continue
        priority = _clean_text(idea.get("priority") or "medium", 30).lower()
        page = _clean_text(idea.get("page"), 300)
        steps = [_clean_text(step, 220) for step in _as_report_list(idea.get("steps")) if _clean_text(step, 220)]
        expected = _clean_text(idea.get("expected"), 400)
        steps_text = "; ".join(steps[:5])
        content = (
            f"Custom agent test idea: {title}. "
            f"Priority: {priority}. "
            f"{f'Page: {page}. ' if page else ''}"
            f"{f'Steps: {steps_text}. ' if steps_text else ''}"
            f"{f'Expected: {expected}.' if expected else ''}"
        )
        store(
            kind="workflow_decision",
            content=content,
            summary=f"Test idea: {title}",
            tags=["test-idea", priority],
            confidence=0.72,
            importance=_report_importance(priority),
            extra_data={"report_section": "test_ideas", "test_idea_id": idea.get("id")},
        )

    return stored_ids
