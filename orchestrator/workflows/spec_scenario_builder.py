"""Shared helpers for rendering richer runnable E2E spec scenarios."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_BALANCED_MAX = 12


@dataclass
class E2EScenario:
    """One runnable browser E2E scenario rendered as a markdown spec."""

    title: str
    description: str
    steps: list[str]
    expected_outcomes: list[str]
    category: str = "coverage"
    priority: str = "medium"
    preconditions: list[str] = field(default_factory=list)
    test_data: list[str] = field(default_factory=list)
    selectors: list[str] = field(default_factory=list)
    source_notes: list[str] = field(default_factory=list)


def sanitize_filename(value: str, fallback: str = "scenario") -> str:
    """Return a deterministic markdown-safe slug."""

    cleaned = re.sub(r"[^\w\s-]", "", value or "")
    cleaned = re.sub(r"[-\s]+", "-", cleaned).strip("-").lower()
    return (cleaned or fallback)[:90]


def render_scenario_markdown(scenario: E2EScenario, scenario_id: str | None = None) -> str:
    """Render one scenario in the standard runnable spec format."""

    lines = [f"# Test: {scenario.title}", ""]
    if scenario_id:
        lines.extend([f"ID: {scenario_id}", ""])

    lines.extend(["## Description", scenario.description.strip() or scenario.title, ""])

    lines.append("## Prerequisites")
    prerequisites = scenario.preconditions or ["Fresh browser session"]
    lines.extend(f"- {item}" for item in prerequisites)
    lines.append("")

    lines.append("## Steps")
    for idx, step in enumerate(_normalize_steps(scenario.steps), 1):
        lines.append(f"{idx}. {step}")
    lines.append("")

    lines.append("## Expected Outcome")
    for outcome in _normalize_outcomes(scenario.expected_outcomes):
        lines.append(f"- {outcome}")

    if scenario.test_data:
        lines.extend(["", "## Test Data"])
        lines.extend(f"- {item}" for item in _dedupe_strings(scenario.test_data))

    if scenario.selectors:
        lines.extend(["", "## Selectors"])
        lines.extend(f"- `{item}`" for item in _dedupe_strings(scenario.selectors))

    if scenario.source_notes:
        lines.extend(["", "## Source Evidence"])
        lines.extend(f"- {item}" for item in _dedupe_strings(scenario.source_notes))

    return "\n".join(lines).rstrip() + "\n"


def write_scenarios(
    scenarios: list[E2EScenario],
    output_dir: Path,
    *,
    start_index: int = 1,
) -> list[Path]:
    """Write one markdown file per scenario and return generated paths."""

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for offset, scenario in enumerate(scenarios, start_index):
        scenario_id = f"TC-{offset:03d}"
        filename = f"{scenario_id.lower()}-{sanitize_filename(scenario.title)}.md"
        path = output_dir / filename
        path.write_text(render_scenario_markdown(scenario, scenario_id=scenario_id))
        paths.append(path)
    return paths


def scenario_from_test_idea(
    idea: dict[str, Any],
    *,
    target_url: str,
    fallback_title: str,
) -> E2EScenario:
    """Build a runnable scenario from a persisted/generated test idea."""

    title = str(idea.get("title") or fallback_title).strip()
    steps = _string_list(idea.get("suggested_steps"))
    if not steps:
        steps = [f"Navigate to {target_url}", f"Verify {title}"]
    steps = _ensure_navigation(steps, target_url)

    source_notes = []
    source_requirements = _string_list(idea.get("source_requirements"))
    source_flows = _string_list(idea.get("source_flows"))
    source_api_endpoints = _string_list(idea.get("source_api_endpoints"))
    if source_requirements:
        source_notes.append(f"Source requirement(s): {', '.join(source_requirements[:5])}")
    if source_flows:
        source_notes.append(f"Source flow(s): {', '.join(source_flows[:5])}")
    if source_api_endpoints:
        source_notes.append(f"Observed API endpoint(s): {', '.join(source_api_endpoints[:5])}")

    readiness = str(idea.get("spec_readiness") or "").strip()
    preconditions = ["Fresh browser session"]
    if readiness == "needs_auth":
        preconditions.append("Authenticated user credentials are available")
    elif readiness == "needs_data":
        preconditions.append("Required test data exists")

    return E2EScenario(
        title=title,
        description=str(idea.get("description") or f"Validate {title}.").strip(),
        category=str(idea.get("category") or "coverage"),
        priority=str(idea.get("priority") or "medium"),
        preconditions=preconditions,
        steps=steps,
        expected_outcomes=_string_list(idea.get("expected_outcomes")) or [f"{title} works as expected"],
        test_data=[f"Target URL: {target_url}"],
        source_notes=source_notes,
    )


def scenario_from_requirement(
    *,
    title: str,
    description: str,
    target_url: str,
    acceptance_criteria: list[str] | None = None,
    flow_steps: list[str] | None = None,
    priority: str = "medium",
    category: str = "coverage",
    source_flows: list[str] | None = None,
) -> E2EScenario:
    """Build a richer scenario from requirement and flow evidence."""

    steps = _ensure_navigation(flow_steps or [f"Verify {title}"], target_url)
    if not any(_looks_like_assertion(step) for step in steps):
        steps.append(f"Verify {title}")

    source_notes = []
    if source_flows:
        source_notes.append(f"Source flow(s): {', '.join(source_flows[:5])}")

    return E2EScenario(
        title=title,
        description=description or f"Validate {title}.",
        category=category,
        priority=priority,
        preconditions=["Fresh browser session"],
        steps=steps,
        expected_outcomes=acceptance_criteria or [f"{title} works as expected"],
        test_data=[f"Target URL: {target_url}"],
        source_notes=source_notes,
    )


def conservative_page_scenarios(
    *,
    title: str,
    target_url: str,
    description: str | None = None,
    max_scenarios: int = 4,
) -> list[E2EScenario]:
    """Return generic but useful checks when only page-level evidence exists."""

    base_description = description or f"Validate page-level behavior for {title}."
    scenarios = [
        E2EScenario(
            title=f"{title} page is reachable",
            description=base_description,
            category="happy_path",
            priority="medium",
            steps=[
                f"Navigate to {target_url}",
                "Wait for the page to finish loading",
                "Verify the page renders without a blocking error",
            ],
            expected_outcomes=[
                "The page is reachable",
                "A usable page state is rendered",
                "No 404, access-denied, or blank page is shown",
            ],
            test_data=[f"Target URL: {target_url}"],
            source_notes=["Conservative page-level scenario from limited exploration evidence"],
        ),
        E2EScenario(
            title=f"{title} has no critical console errors",
            description=f"Check runtime stability for {title} without assuming specific business behavior.",
            category="regression",
            priority="medium",
            steps=[
                f"Navigate to {target_url}",
                "Wait for the page to finish loading",
                "Observe browser console messages",
                "Verify no critical JavaScript runtime errors are present",
            ],
            expected_outcomes=[
                "No uncaught JavaScript exception blocks the page",
                "The page remains interactive after load",
            ],
            test_data=[f"Target URL: {target_url}"],
            source_notes=["Conservative runtime-stability scenario from limited exploration evidence"],
        ),
        E2EScenario(
            title=f"{title} exposes accessible interactive elements",
            description=f"Check basic accessibility affordances on {title}.",
            category="accessibility",
            priority="medium",
            steps=[
                f"Navigate to {target_url}",
                "Take a browser snapshot",
                "Verify primary interactive elements have readable labels or accessible names",
                "Verify keyboard focus can move through visible interactive elements",
            ],
            expected_outcomes=[
                "Visible controls expose accessible labels",
                "Keyboard focus is not trapped on page load",
            ],
            test_data=[f"Target URL: {target_url}"],
            source_notes=["Conservative accessibility scenario from limited exploration evidence"],
        ),
        E2EScenario(
            title=f"{title} works on a mobile viewport",
            description=f"Check responsive rendering for {title}.",
            category="edge_case",
            priority="medium",
            steps=[
                "Set viewport to a mobile size",
                f"Navigate to {target_url}",
                "Wait for the page to finish loading",
                "Verify the primary content is visible without horizontal overflow",
            ],
            expected_outcomes=[
                "Primary content remains visible on mobile",
                "No major layout overlap blocks interaction",
            ],
            test_data=[f"Target URL: {target_url}", "Viewport: mobile"],
            source_notes=["Conservative responsive scenario from limited exploration evidence"],
        ),
    ]
    return scenarios[: max(1, min(max_scenarios, len(scenarios)))]


def _normalize_steps(steps: list[str]) -> list[str]:
    normalized = [str(step).strip() for step in steps if str(step).strip()]
    return normalized or ["Verify the expected behavior"]


def _normalize_outcomes(outcomes: list[str]) -> list[str]:
    normalized = [str(outcome).strip() for outcome in outcomes if str(outcome).strip()]
    return normalized or ["The expected behavior is observed"]


def _ensure_navigation(steps: list[str], target_url: str) -> list[str]:
    if any("navigate" in step.lower() or step.lower().startswith(("open ", "go to ")) for step in steps):
        return steps
    return [f"Navigate to {target_url}", *steps]


def _looks_like_assertion(step: str) -> bool:
    lowered = step.lower()
    return any(token in lowered for token in ("verify", "assert", "observe", "expect", "check"))


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value.strip())
    return result
