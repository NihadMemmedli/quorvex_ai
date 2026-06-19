"""Evidence-first synthesis for Enhanced Explorer agent runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

EVENT_TYPES = {
    "page_observed",
    "action_attempted",
    "action_result",
    "flow_candidate",
    "network_observed",
    "issue_observed",
    "blocker",
}

MEANINGFUL_ACTIONS = {"click", "type", "select", "press_key", "navigate", "file_upload"}
STEP_EVIDENCE_TYPES = {"action_result", "page_observed"}
BROWSER_TOOL_SHORT_NAMES = {
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_select_option",
    "browser_press_key",
    "browser_take_screenshot",
    "browser_screenshot",
}
INTERACTION_TOOL_SHORT_NAMES = {
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_select_option",
    "browser_press_key",
}


def _clean_str(value: Any, max_len: int = 300) -> str:
    text = str(value or "").strip()
    return text[:max_len]


def _short_tool_name(value: Any) -> str:
    name = str(value or "")
    return name.rsplit("__", 1)[-1] if "__" in name else name


def _normalized_url(value: Any) -> str:
    text = _clean_str(value, 800)
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return text.rstrip("/")
    if not parsed.scheme or not parsed.netloc:
        return text.rstrip("/")
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path.rstrip("/") or "/", "", ""))


def _input_target(tool_input: dict[str, Any] | None) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in ("url", "target", "element", "selector", "text", "key"):
        value = tool_input.get(key)
        if value:
            return _clean_str(value, 300)
    if "values" in tool_input:
        return _clean_str(tool_input.get("values"), 300)
    return ""


def _browser_action(short_name: str) -> str:
    mapping = {
        "browser_navigate": "navigate",
        "browser_snapshot": "observe_page",
        "browser_click": "click",
        "browser_type": "type",
        "browser_select_option": "select",
        "browser_press_key": "press_key",
        "browser_take_screenshot": "screenshot",
        "browser_screenshot": "screenshot",
    }
    return mapping.get(short_name, short_name.replace("browser_", ""))


def _tool_input(call: Any) -> dict[str, Any]:
    if isinstance(call, dict):
        value = call.get("input") or call.get("tool_input") or call.get("input_preview")
        return dict(value) if isinstance(value, dict) else {}
    value = getattr(call, "input", None)
    return dict(value) if isinstance(value, dict) else {}


def _tool_success(call: Any) -> bool:
    if isinstance(call, dict):
        if call.get("error"):
            return False
        if "success" in call:
            return bool(call.get("success"))
        status = str(call.get("status") or "").lower()
        return status in {"success", "succeeded", "completed", "ok"}
    if getattr(call, "error", None):
        return False
    if hasattr(call, "success"):
        return bool(call.success)
    status = str(getattr(call, "status", "") or "").lower()
    return status in {"success", "succeeded", "completed", "ok"}


def _tool_name(call: Any) -> str:
    if isinstance(call, dict):
        return str(call.get("name") or call.get("tool_name") or "")
    return str(getattr(call, "name", "") or "")


def browser_tool_diagnostics(tool_calls: list[Any] | None) -> dict[str, int]:
    calls = list(tool_calls or [])
    browser_calls = [call for call in calls if _short_tool_name(_tool_name(call)) in BROWSER_TOOL_SHORT_NAMES]
    successful = [call for call in browser_calls if _tool_success(call)]
    return {
        "tool_calls": len(calls),
        "browser_tool_calls": len(browser_calls),
        "successful_browser_tool_calls": len(successful),
    }


def synthesize_browser_events_from_tool_calls(
    tool_calls: list[Any] | None,
    *,
    target_url: str | None = None,
    start_index: int = 1,
) -> list[dict[str, Any]]:
    """Convert completed browser tool calls into conservative evidence events.

    These records intentionally avoid inferring business flows from prose. They
    only describe tool calls that actually happened and their immediate result.
    """

    events: list[dict[str, Any]] = []
    current_url = target_url or ""
    counter = start_index
    for call in tool_calls or []:
        name = _tool_name(call)
        short = _short_tool_name(name)
        if short not in BROWSER_TOOL_SHORT_NAMES:
            continue
        tool_input = _tool_input(call)
        target = _input_target(tool_input)
        success = _tool_success(call)
        action = _browser_action(short)
        if short == "browser_navigate" and target:
            current_url = target

        if short in INTERACTION_TOOL_SHORT_NAMES:
            attempted_id = f"auto_evt_{counter:03d}"
            counter += 1
            events.append(
                {
                    "id": attempted_id,
                    "event_type": "action_attempted",
                    "action": action,
                    "target": target or short,
                    "url": current_url,
                    "source": "browser_tool_call",
                }
            )
            result_id = f"auto_evt_{counter:03d}"
            counter += 1
            events.append(
                {
                    "id": result_id,
                    "event_type": "action_result",
                    "action": action,
                    "target": target or short,
                    "success": success,
                    "outcome": "Browser tool completed." if success else "Browser tool failed.",
                    "url": current_url if short != "browser_navigate" else target or current_url,
                    "source": "browser_tool_call",
                    "attempt_event_id": attempted_id,
                }
            )

        if short in {"browser_navigate", "browser_snapshot", "browser_take_screenshot", "browser_screenshot"} and success:
            screenshot_path = (
                _clean_str(tool_input.get("filename") or tool_input.get("path"), 500)
                if isinstance(tool_input, dict)
                else ""
            )
            events.append(
                {
                    "id": f"auto_evt_{counter:03d}",
                    "event_type": "page_observed",
                    "url": target if short == "browser_navigate" and target else current_url,
                    "title": target if short == "browser_navigate" and target else "",
                    "summary": f"Observed via {short}.",
                    "screenshot_path": screenshot_path,
                    "source": "browser_tool_call",
                }
            )
            counter += 1

    return events


def parse_event_records(raw: Any) -> list[dict[str, Any]]:
    """Extract JSONL-style exploration events from model output or parsed data."""
    if isinstance(raw, dict):
        events = raw.get("events") or raw.get("exploration_events") or []
        if isinstance(events, list):
            return [event for event in events if isinstance(event, dict)]
        return []

    if not isinstance(raw, str) or not raw.strip():
        return []

    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or not stripped.startswith("{") or not stripped.endswith("}"):
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        event_type = parsed.get("event_type") or parsed.get("type")
        if event_type in EVENT_TYPES:
            events.append(parsed)
    return events


def read_event_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and (parsed.get("event_type") or parsed.get("type")) in EVENT_TYPES:
            events.append(parsed)
    return events


def write_event_log(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for event in events:
            f.write(json.dumps(event, sort_keys=True) + "\n")


@dataclass
class ExplorerResultSynthesizer:
    """Convert recorded exploration events into reportable flows and coverage."""

    events: list[dict[str, Any]]
    target_url: str | None = None

    def normalized_events(self) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, event in enumerate(self.events, start=1):
            event_type = event.get("event_type") or event.get("type")
            if event_type not in EVENT_TYPES:
                continue
            item = dict(event)
            item["event_type"] = event_type
            item.pop("type", None)
            event_id = _clean_str(item.get("id") or item.get("event_id") or f"event_{index:03d}", 80)
            if event_id in seen_ids:
                event_id = f"{event_id}_{index:03d}"
            item["id"] = event_id
            seen_ids.add(event_id)
            normalized.append(item)
        return normalized

    def synthesize(self) -> dict[str, Any]:
        events = self.normalized_events()
        by_id = {event["id"]: event for event in events}
        action_results = [event for event in events if event.get("event_type") == "action_result"]
        page_events = [event for event in events if event.get("event_type") == "page_observed"]
        blockers = [event for event in events if event.get("event_type") == "blocker"]
        issues = [event for event in events if event.get("event_type") == "issue_observed"]
        screenshots = [
            _clean_str(event.get("screenshot_path") or event.get("screenshot"), 500)
            for event in events
            if event.get("screenshot_path") or event.get("screenshot")
        ]

        action_trace = self._build_action_trace(action_results)
        observed_flows, inferred_flows, unsupported_flows, dedupe_stats = self._build_flows(
            events,
            by_id,
            action_results,
            page_events,
        )
        pages = self._page_urls(page_events, action_results)
        meaningful_interactions = len(
            [
                event
                for event in action_results
                if _clean_str(event.get("action")).lower() in MEANINGFUL_ACTIONS
            ]
        )
        forms_interacted = len(
            [
                event
                for event in action_results
                if _clean_str(event.get("action")).lower() in {"type", "select", "submit"}
            ]
        )
        coverage = {
            "navigation_explored": len(pages) > 1,
            "forms_interacted": forms_interacted,
            "flows_discovered": len(observed_flows),
            "inferred_opportunities": len(inferred_flows),
            "pages_visited": len(pages),
            "errors_found": len(issues),
            "blockers_found": len(blockers),
            "coverage_score": self._coverage_score(len(pages), forms_interacted, len(observed_flows), len(issues)),
        }

        return {
            "events": events,
            "action_trace": action_trace,
            "discovered_flows": observed_flows,
            "inferred_flows": inferred_flows,
            "unsupported_flow_candidates": unsupported_flows,
            "blockers": [self._summarize_event(event) for event in blockers],
            "issues": [self._summarize_event(event) for event in issues],
            "pages_visited": pages,
            "screenshots": list(dict.fromkeys(path for path in screenshots if path)),
            "coverage": coverage,
            "event_counts": self._event_counts(events),
            "meaningful_interactions": meaningful_interactions,
            "dedupe_stats": dedupe_stats,
        }

    def _build_action_trace(self, action_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        trace: list[dict[str, Any]] = []
        for index, event in enumerate(action_results, start=1):
            trace.append(
                {
                    "step": index,
                    "event_id": event["id"],
                    "action": _clean_str(event.get("action") or "action", 80),
                    "target": _clean_str(event.get("target") or event.get("selector") or event.get("url"), 200),
                    "outcome": _clean_str(event.get("outcome") or event.get("result") or "observed", 300),
                    "success": bool(event.get("success", True)),
                    "is_new_discovery": bool(event.get("is_new_discovery", False)),
                }
            )
        return trace

    def _build_flows(
        self,
        events: list[dict[str, Any]],
        by_id: dict[str, dict[str, Any]],
        action_results: list[dict[str, Any]],
        page_events: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
        observed: list[dict[str, Any]] = []
        inferred: list[dict[str, Any]] = []
        unsupported: list[dict[str, Any]] = []
        dedupe_stats = {"duplicate_flows_removed": 0}
        candidates = [event for event in events if event.get("event_type") == "flow_candidate"]

        for index, candidate in enumerate(candidates, start=1):
            refs = self._candidate_refs(candidate)
            ref_events = [by_id[ref] for ref in refs if ref in by_id]
            missing_refs = [ref for ref in refs if ref not in by_id]
            evidence_complete = bool(refs) and len(ref_events) == len(refs)
            observed_complete = evidence_complete and all(
                event.get("event_type") in STEP_EVIDENCE_TYPES for event in ref_events
            )
            flow = self._flow_from_candidate(candidate, index, refs, ref_events)
            if not refs:
                flow["status"] = "unsupported"
                flow["missing_evidence_event_ids"] = []
                flow["reason"] = "No evidence_event_ids or step_event_ids were provided."
                unsupported.append(flow)
                continue
            if missing_refs:
                flow["status"] = "unsupported"
                flow["missing_evidence_event_ids"] = missing_refs
                flow["reason"] = "Referenced evidence event ids were not emitted."
                unsupported.append(flow)
                continue
            if observed_complete and any(event.get("event_type") == "action_result" for event in ref_events):
                flow["status"] = "observed"
                observed.append(flow)
            elif evidence_complete or ref_events:
                flow["status"] = "inferred"
                inferred.append(flow)

        observed, removed_observed = self._dedupe_flows(observed)
        inferred, removed_inferred = self._dedupe_flows(inferred)
        dedupe_stats["duplicate_flows_removed"] += removed_observed + removed_inferred

        meaningful_results = [
            event
            for event in action_results
            if _clean_str(event.get("action")).lower() in MEANINGFUL_ACTIONS
            and bool(event.get("success", True))
        ]
        if not observed and not candidates and page_events and meaningful_results:
            ref_events = self._fallback_flow_events(events)
            refs = [event["id"] for event in ref_events]
            observed.append(
                {
                    "id": "flow_1",
                    "title": "Observed user path",
                    "pages": self._page_urls(page_events, action_results),
                    "steps": self._steps_from_events(ref_events),
                    "step_event_ids": refs,
                    "evidence_event_ids": refs,
                    "steps_count": len(refs),
                    "happy_path": "Synthesized from observed browser action results.",
                    "edge_cases": [],
                    "test_ideas": ["Replay the observed path and assert each resulting page state."],
                    "entry_point": self.target_url or "",
                    "exit_point": self._exit_point(page_events, action_results),
                    "complexity": "medium" if len(refs) > 4 else "low",
                    "status": "observed",
                    "confidence": "medium",
                }
            )

        observed, removed_fallback = self._dedupe_flows(observed)
        dedupe_stats["duplicate_flows_removed"] += removed_fallback

        return observed, inferred, unsupported, dedupe_stats

    def _fallback_flow_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        has_page = False
        has_action = False
        for event in events:
            event_type = event.get("event_type")
            if event_type == "page_observed" and not has_page:
                evidence.append(event)
                has_page = True
            elif event_type == "action_result" and _clean_str(event.get("action")).lower() in MEANINGFUL_ACTIONS:
                evidence.append(event)
                has_action = True
            elif has_page and has_action and event_type == "page_observed":
                evidence.append(event)
            if len(evidence) >= 12:
                break
        return evidence

    def _dedupe_flows(self, flows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        removed = 0
        for flow in flows:
            signature = self._flow_signature(flow)
            if signature in seen:
                removed += 1
                continue
            seen.add(signature)
            unique.append(flow)
        return unique, removed

    def _flow_signature(self, flow: dict[str, Any]) -> str:
        pages = flow.get("pages") if isinstance(flow.get("pages"), list) else []
        normalized_pages = [_normalized_url(page) for page in pages if _normalized_url(page)]
        steps = flow.get("steps") if isinstance(flow.get("steps"), list) else []
        action_parts = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            action = _clean_str(step.get("action"), 80).lower()
            target = _clean_str(step.get("target"), 160).lower()
            action_parts.append(f"{action}:{target}")
        return "|".join(normalized_pages + action_parts) or _clean_str(flow.get("title"), 120).lower()

    def _candidate_refs(self, candidate: dict[str, Any]) -> list[str]:
        refs = candidate.get("step_event_ids") or candidate.get("steps_event_ids") or candidate.get("event_ids")
        if refs is None:
            refs = candidate.get("evidence_event_ids")
        if not isinstance(refs, list):
            return []
        return [_clean_str(ref, 80) for ref in refs if _clean_str(ref, 80)]

    def _flow_from_candidate(
        self,
        candidate: dict[str, Any],
        index: int,
        refs: list[str],
        ref_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        pages = [
            _clean_str(event.get("url") or event.get("page") or event.get("target"), 500)
            for event in ref_events
            if event.get("event_type") == "page_observed" or event.get("url")
        ]
        return {
            "id": _clean_str(candidate.get("flow_id") or f"flow_{index}", 80),
            "title": _clean_str(candidate.get("title") or f"Flow {index}", 120),
            "pages": list(dict.fromkeys(page for page in pages if page)),
            "steps": self._steps_from_events(ref_events),
            "step_event_ids": refs,
            "evidence_event_ids": refs,
            "steps_count": len(refs),
            "happy_path": _clean_str(candidate.get("happy_path") or candidate.get("description"), 500),
            "edge_cases": self._list_of_strings(candidate.get("edge_cases")),
            "test_ideas": self._list_of_strings(candidate.get("test_ideas")),
            "entry_point": _clean_str(candidate.get("entry_point") or (pages[0] if pages else self.target_url), 500),
            "exit_point": _clean_str(candidate.get("exit_point") or (pages[-1] if pages else ""), 500),
            "complexity": _clean_str(candidate.get("complexity") or "unknown", 30),
            "confidence": _clean_str(candidate.get("confidence") or "medium", 30),
        }

    def _steps_from_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        for event in events:
            if event.get("event_type") == "page_observed":
                steps.append(
                    {
                        "event_id": event["id"],
                        "action": "observe_page",
                        "target": _clean_str(event.get("url") or event.get("title"), 200),
                        "expected": _clean_str(event.get("summary") or event.get("outcome") or "Page is visible.", 300),
                    }
                )
            elif event.get("event_type") == "action_result":
                steps.append(
                    {
                        "event_id": event["id"],
                        "action": _clean_str(event.get("action") or "action", 80),
                        "target": _clean_str(event.get("target") or event.get("selector") or event.get("url"), 200),
                        "expected": _clean_str(event.get("outcome") or event.get("result") or "Action completed.", 300),
                    }
                )
        return steps

    def _page_urls(self, page_events: list[dict[str, Any]], action_results: list[dict[str, Any]]) -> list[str]:
        urls: list[str] = []
        for event in page_events:
            url = _clean_str(event.get("url") or event.get("page"), 500)
            if url:
                urls.append(url)
        for event in action_results:
            action = _clean_str(event.get("action")).lower()
            url = _clean_str(event.get("url") or (event.get("target") if action == "navigate" else ""), 500)
            if url:
                urls.append(url)
        if not urls and self.target_url:
            urls.append(self.target_url)
        return list(dict.fromkeys(urls))

    def _exit_point(self, page_events: list[dict[str, Any]], action_results: list[dict[str, Any]]) -> str:
        pages = self._page_urls(page_events, action_results)
        return pages[-1] if pages else ""

    def _event_counts(self, events: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in events:
            event_type = str(event.get("event_type"))
            counts[event_type] = counts.get(event_type, 0) + 1
        return counts

    def diagnostics(
        self,
        *,
        tool_calls: list[Any] | None = None,
        extra: dict[str, Any] | None = None,
        synthesis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        diag: dict[str, Any] = {}
        diag.update(browser_tool_diagnostics(tool_calls))
        if synthesis is not None:
            diag["evidence_event_count"] = len(synthesis.get("events") or [])
            diag["dedupe_stats"] = synthesis.get("dedupe_stats") or {}
            event_counts = synthesis.get("event_counts") if isinstance(synthesis.get("event_counts"), dict) else {}
            unsupported = synthesis.get("unsupported_flow_candidates") or []
            missing_ids: list[str] = []
            empty_ref_candidates = 0
            for candidate in unsupported:
                if not isinstance(candidate, dict):
                    continue
                if not (candidate.get("evidence_event_ids") or candidate.get("step_event_ids")):
                    empty_ref_candidates += 1
                for event_id in candidate.get("missing_evidence_event_ids") or []:
                    cleaned = _clean_str(event_id, 80)
                    if cleaned:
                        missing_ids.append(cleaned)
            diag["flow_candidate_records"] = int(event_counts.get("flow_candidate") or 0)
            diag["valid_flow_candidates"] = len(synthesis.get("discovered_flows") or [])
            diag["unsupported_flow_candidates"] = len(unsupported)
            diag["empty_evidence_ref_flow_candidates"] = empty_ref_candidates
            diag["missing_evidence_event_ids"] = list(dict.fromkeys(missing_ids))
        if extra:
            diag.update(extra)
        return diag

    def _coverage_score(self, pages: int, forms: int, flows: int, issues: int) -> float:
        score = 0.0
        if pages:
            score += min(pages / 3, 1.0) * 0.3
        if forms:
            score += min(forms / 2, 1.0) * 0.2
        if flows:
            score += min(flows / 2, 1.0) * 0.4
        if issues:
            score += 0.1
        return round(min(score, 1.0), 2)

    def _summarize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": event.get("id"),
            "type": event.get("event_type"),
            "title": _clean_str(event.get("title") or event.get("message") or event.get("summary"), 160),
            "url": _clean_str(event.get("url") or event.get("page"), 500),
            "details": _clean_str(event.get("details") or event.get("outcome") or event.get("error"), 500),
        }

    def _list_of_strings(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [_clean_str(item, 300) for item in value if _clean_str(item, 300)]
