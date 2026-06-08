"""Structured report parsing for UI-created custom agent runs."""

from __future__ import annotations

import json
import re
from typing import Any


CUSTOM_AGENT_REPORT_INSTRUCTIONS = """
Final output contract:
After your concise human-readable summary, include exactly one fenced JSON block with a top-level
`structured_report` object. Use this shape:
{
  "structured_report": {
    "summary": "short actionable summary",
    "scope": "what was tested or inspected",
    "pages_checked": [{"url": "/path-or-url", "status": "loaded|issue|unknown", "notes": "optional"}],
    "findings": [{
      "title": "issue or observation",
      "severity": "critical|high|medium|low|info",
      "confidence": "high|medium|low",
      "page": "/path-or-url",
      "description": "what happened",
      "evidence": "specific observed evidence",
      "suggested_action": "what to do next"
    }],
    "test_ideas": [{
      "title": "test idea",
      "priority": "critical|high|medium|low",
      "page": "/path-or-url",
      "steps": ["step 1", "step 2"],
      "expected": "expected result",
      "source_finding_id": "optional"
    }],
    "requirements": [{
      "title": "candidate requirement",
      "description": "intended behavior inferred from observed evidence",
      "category": "authentication|navigation|crud|validation|functional|security|performance|accessibility|other",
      "priority": "critical|high|medium|low",
      "acceptance_criteria": ["criterion 1", "criterion 2"],
      "page": "/path-or-url",
      "evidence": "specific observed evidence",
      "confidence": 0.7
    }],
    "evidence": [{"type": "screenshot|network|console|note|artifact", "label": "short label", "value": "path or text"}],
    "follow_up_actions": [{"label": "action label", "action": "create_spec|rerun_agent|inspect_page", "target": "id or URL"}]
  }
}
Use empty arrays when nothing was found. Requirements are candidate requirements for human review; do not
invent requirements that are not supported by observed evidence.
"""


def _clean_text(value: Any, max_len: int = 2000) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:max_len].strip()


def _as_report_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _extract_custom_report_candidate(output: str) -> dict[str, Any] | None:
    if not output:
        return None

    code_blocks = re.findall(r"```(?:json)?\s*(.*?)\s*```", output, flags=re.DOTALL | re.IGNORECASE)
    candidates = [block.strip() for block in code_blocks if block.strip()]
    stripped = output.strip()
    if stripped.startswith("{"):
        candidates.append(stripped)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                from utils.json_utils import extract_json_from_markdown

                parsed = extract_json_from_markdown(f"```json\n{candidate}\n```")
            except Exception:
                continue
        if isinstance(parsed, dict):
            if isinstance(parsed.get("structured_report"), dict):
                return parsed["structured_report"]
            if any(key in parsed for key in ("summary", "findings", "test_ideas", "pages_checked")):
                return parsed
    return None


def _normalize_report_item(
    item: Any,
    prefix: str,
    index: int,
    *,
    default_page: str = "",
    default_priority: str = "medium",
) -> dict[str, Any]:
    if isinstance(item, dict):
        normalized = dict(item)
    else:
        normalized = {"title": _clean_text(item, 180), "description": _clean_text(item)}

    normalized["id"] = _clean_text(normalized.get("id") or f"{prefix}-{index:03d}", 40)
    normalized["title"] = _clean_text(normalized.get("title") or normalized.get("label") or normalized.get("description"), 180)
    normalized["description"] = _clean_text(normalized.get("description") or normalized.get("notes") or normalized.get("evidence"))
    normalized["page"] = _clean_text(normalized.get("page") or normalized.get("url") or default_page, 500)
    if prefix == "F":
        severity = _clean_text(normalized.get("severity") or default_priority, 20).lower()
        normalized["severity"] = severity if severity in {"critical", "high", "medium", "low", "info"} else "medium"
        confidence = _clean_text(normalized.get("confidence") or "medium", 20).lower()
        normalized["confidence"] = confidence if confidence in {"high", "medium", "low"} else "medium"
        normalized["suggested_action"] = _clean_text(normalized.get("suggested_action") or "Create or update coverage for this behavior.")
    else:
        priority = _clean_text(normalized.get("priority") or normalized.get("severity") or default_priority, 20).lower()
        normalized["priority"] = priority if priority in {"critical", "high", "medium", "low"} else "medium"
        steps = normalized.get("steps")
        normalized["steps"] = [_clean_text(step, 300) for step in _as_report_list(steps) if _clean_text(step, 300)]
        normalized["expected"] = _clean_text(normalized.get("expected") or normalized.get("expected_result") or normalized.get("assertion"))
    return normalized


def _normalize_requirement_confidence(value: Any) -> float:
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


def _normalize_report_requirement(
    item: Any,
    index: int,
    *,
    default_page: str = "",
) -> dict[str, Any]:
    if isinstance(item, dict):
        normalized = dict(item)
    else:
        normalized = {"title": _clean_text(item, 180), "description": _clean_text(item)}

    normalized["id"] = _clean_text(normalized.get("id") or f"R-{index:03d}", 40)
    normalized["title"] = _clean_text(
        normalized.get("title")
        or normalized.get("name")
        or normalized.get("requirement")
        or normalized.get("description"),
        180,
    )
    normalized["description"] = _clean_text(
        normalized.get("description") or normalized.get("summary") or normalized.get("evidence"),
        2000,
    )
    normalized["category"] = _clean_text(normalized.get("category") or "functional", 80).lower() or "functional"
    priority = _clean_text(normalized.get("priority") or normalized.get("severity") or "medium", 20).lower()
    normalized["priority"] = priority if priority in {"critical", "high", "medium", "low"} else "medium"
    criteria = normalized.get("acceptance_criteria") or normalized.get("criteria") or normalized.get("acceptanceCriteria")
    normalized["acceptance_criteria"] = [
        _clean_text(criterion, 500)
        for criterion in _as_report_list(criteria)
        if _clean_text(criterion, 500)
    ]
    if not normalized["acceptance_criteria"]:
        expected = _clean_text(normalized.get("expected") or normalized.get("expected_result"), 500)
        if expected:
            normalized["acceptance_criteria"] = [expected]
    normalized["page"] = _clean_text(normalized.get("page") or normalized.get("url") or default_page, 500)
    evidence = normalized.get("evidence")
    if isinstance(evidence, list):
        normalized["evidence"] = "; ".join(_clean_text(part, 300) for part in evidence if _clean_text(part, 300))
    else:
        normalized["evidence"] = _clean_text(evidence, 1200)
    normalized["confidence"] = _normalize_requirement_confidence(normalized.get("confidence"))
    return normalized


def _severity_from_text(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("crash", "security", "data loss", "cannot access")):
        return "critical"
    if any(token in lowered for token in ("failed", "empty body", "no content", "not working", "exception")):
        return "high"
    if any(token in lowered for token in ("error", "fallback", "validation", "404", "returns 200")):
        return "medium"
    return "low"


def _parse_pages_from_output(output: str) -> list[dict[str, Any]]:
    pages: dict[str, dict[str, Any]] = {}
    for match in re.finditer(r"`([^`]+)`", output or ""):
        value = match.group(1).strip()
        if not (value.startswith("/") or value.startswith("http://") or value.startswith("https://")):
            continue
        page = pages.setdefault(value, {"url": value, "status": "unknown", "notes": ""})
        line_start = output.rfind("\n", 0, match.start()) + 1
        line_end = output.find("\n", match.end())
        if line_end == -1:
            line_end = len(output)
        line = output[line_start:line_end]
        if any(token in line.lower() for token in ("crash", "failed", "empty", "no content", "error", "fallback")):
            page["status"] = "issue"
            page["notes"] = _clean_text(line, 500)
        elif "load" in line.lower():
            page["status"] = "loaded"
            page["notes"] = _clean_text(line, 500)
    return list(pages.values())


def _heuristic_custom_report(output: str, config: dict[str, Any], artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    pages = _parse_pages_from_output(output)
    findings: list[dict[str, Any]] = []
    seen_lines: set[str] = set()
    issue_terms = ("crash", "failed", "empty body", "no content", "error", "fallback", "validation", "404", "returns 200")
    for raw_line in (output or "").splitlines():
        line = raw_line.strip().strip("|").strip()
        if not line or line in seen_lines or not any(term in line.lower() for term in issue_terms):
            continue
        seen_lines.add(line)
        page_match = re.search(r"`([^`]+)`", line)
        page = page_match.group(1) if page_match else _clean_text(config.get("url"), 500)
        title = re.sub(r"`([^`]+)`", r"\1", line)
        title = re.sub(r"\s*\|\s*", " - ", title)
        findings.append(
            _normalize_report_item(
                {
                    "title": title,
                    "severity": _severity_from_text(line),
                    "confidence": "medium",
                    "page": page,
                    "description": title,
                    "evidence": line,
                    "suggested_action": "Inspect this behavior and create regression coverage if it is expected to fail.",
                },
                "F",
                len(findings) + 1,
                default_page=page,
            )
        )

    test_ideas = [
        _normalize_report_item(
            {
                "title": f"Regression coverage for {finding['title'][:90]}",
                "priority": finding.get("severity", "medium"),
                "page": finding.get("page", ""),
                "steps": [
                    f"Navigate to {finding.get('page') or config.get('url') or 'the affected page'}",
                    "Perform the interaction or load path described in the finding",
                    "Assert the expected content, status, or validation behavior",
                ],
                "expected": "The page behaves consistently without the observed failure.",
                "source_finding_id": finding["id"],
            },
            "T",
            idx + 1,
            default_page=finding.get("page", ""),
            default_priority=finding.get("severity", "medium"),
        )
        for idx, finding in enumerate(findings[:20])
    ]

    evidence = [
        {
            "id": f"E-{idx + 1:03d}",
            "type": artifact.get("type") or "artifact",
            "label": artifact.get("name") or f"Artifact {idx + 1}",
            "value": artifact.get("path") or artifact.get("name") or "",
        }
        for idx, artifact in enumerate(artifacts[:20])
    ]

    summary = ""
    for line in (output or "").splitlines():
        cleaned = line.strip("# ").strip()
        if cleaned and not cleaned.startswith("|") and len(cleaned) > 20:
            summary = _clean_text(cleaned, 500)
            break
    if not summary:
        summary = "Custom agent completed. Review the raw output for details."

    return {
        "summary": summary,
        "scope": _clean_text(config.get("prompt") or config.get("url") or "Custom agent run", 500),
        "pages_checked": pages,
        "findings": findings,
        "test_ideas": test_ideas,
        "requirements": [],
        "evidence": evidence,
        "follow_up_actions": [
            {
                "id": f"A-{idx + 1:03d}",
                "label": f"Create coverage for {finding['id']}",
                "action": "create_spec",
                "target": finding["id"],
            }
            for idx, finding in enumerate(findings[:10])
        ],
        "parse_status": "heuristic",
    }


def _normalize_custom_agent_report(
    report: dict[str, Any] | None,
    output: str,
    config: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(report, dict):
        return _heuristic_custom_report(output, config, artifacts)

    pages = []
    for idx, page in enumerate(_as_report_list(report.get("pages_checked") or report.get("pages") or report.get("routes")), start=1):
        if isinstance(page, dict):
            url = _clean_text(page.get("url") or page.get("path") or page.get("page"), 500)
            if not url:
                continue
            pages.append(
                {
                    "id": _clean_text(page.get("id") or f"P-{idx:03d}", 40),
                    "url": url,
                    "status": _clean_text(page.get("status") or "unknown", 40),
                    "notes": _clean_text(page.get("notes") or page.get("description"), 700),
                }
            )
        else:
            url = _clean_text(page, 500)
            if url:
                pages.append({"id": f"P-{idx:03d}", "url": url, "status": "unknown", "notes": ""})

    findings = [
        _normalize_report_item(item, "F", idx + 1, default_page=_clean_text(config.get("url"), 500))
        for idx, item in enumerate(_as_report_list(report.get("findings")))
    ]
    findings = [item for item in findings if item.get("title")]

    test_ideas = [
        _normalize_report_item(item, "T", idx + 1, default_page=_clean_text(config.get("url"), 500))
        for idx, item in enumerate(_as_report_list(report.get("test_ideas") or report.get("tests")))
    ]
    test_ideas = [item for item in test_ideas if item.get("title")]

    requirements = [
        _normalize_report_requirement(item, idx + 1, default_page=_clean_text(config.get("url"), 500))
        for idx, item in enumerate(_as_report_list(report.get("requirements")))
    ]
    requirements = [item for item in requirements if item.get("title")]

    evidence = []
    for idx, item in enumerate(_as_report_list(report.get("evidence")), start=1):
        if isinstance(item, dict):
            evidence.append(
                {
                    "id": _clean_text(item.get("id") or f"E-{idx:03d}", 40),
                    "type": _clean_text(item.get("type") or "note", 40),
                    "label": _clean_text(item.get("label") or item.get("title") or f"Evidence {idx}", 160),
                    "value": _clean_text(item.get("value") or item.get("path") or item.get("text"), 1000),
                }
            )
        elif _clean_text(item):
            evidence.append({"id": f"E-{idx:03d}", "type": "note", "label": f"Evidence {idx}", "value": _clean_text(item, 1000)})
    for artifact in artifacts[:20]:
        value = artifact.get("path") or artifact.get("name") or ""
        if value and not any(existing.get("value") == value for existing in evidence):
            evidence.append(
                {
                    "id": f"E-{len(evidence) + 1:03d}",
                    "type": artifact.get("type") or "artifact",
                    "label": artifact.get("name") or f"Artifact {len(evidence) + 1}",
                    "value": value,
                }
            )

    follow_up_actions = []
    for idx, item in enumerate(_as_report_list(report.get("follow_up_actions")), start=1):
        if isinstance(item, dict):
            follow_up_actions.append(
                {
                    "id": _clean_text(item.get("id") or f"A-{idx:03d}", 40),
                    "label": _clean_text(item.get("label") or item.get("title") or "Follow up", 160),
                    "action": _clean_text(item.get("action") or "inspect_page", 80),
                    "target": _clean_text(item.get("target") or item.get("url") or item.get("finding_id"), 500),
                }
            )

    return {
        "summary": _clean_text(report.get("summary") or "Custom agent completed.", 800),
        "scope": _clean_text(report.get("scope") or report.get("target") or config.get("prompt") or config.get("url"), 800),
        "pages_checked": pages,
        "findings": findings,
        "test_ideas": test_ideas,
        "requirements": requirements,
        "evidence": evidence,
        "follow_up_actions": follow_up_actions,
        "parse_status": "structured",
    }


def _build_custom_agent_structured_report(
    output: str,
    config: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate = _extract_custom_report_candidate(output)
    return _normalize_custom_agent_report(candidate, output, config, artifacts)
