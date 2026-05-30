"""
Test Idea Generator Workflow

Turns exploration data and generated requirements into spec-ready test ideas.
This makes "what should we test next?" a first-class agent output instead of
only a coverage-gap heuristic.
"""

import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from load_env import setup_claude_env

setup_claude_env()

from memory.exploration_store import get_exploration_store
from orchestrator.ai.context import SOURCE_FALLBACK, SOURCE_OBSERVED, ContextBundle
from orchestrator.ai.prompt_registry import attach_prompt_metadata, build_prompt_metadata
from utils.json_utils import extract_json_from_markdown

logger = logging.getLogger(__name__)


VALID_CATEGORIES = {
    "happy_path",
    "negative",
    "edge_case",
    "security",
    "accessibility",
    "api",
    "regression",
    "coverage",
}
VALID_PRIORITIES = {"critical", "high", "medium", "low"}
VALID_READINESS = {"ready", "needs_data", "needs_auth", "blocked"}


@dataclass
class GeneratedTestIdea:
    """A traceable, spec-ready test idea derived from exploration evidence."""

    title: str
    description: str
    category: str = "coverage"
    priority: str = "medium"
    source_flows: list[str] = field(default_factory=list)
    source_requirements: list[str] = field(default_factory=list)
    source_api_endpoints: list[str] = field(default_factory=list)
    suggested_steps: list[str] = field(default_factory=list)
    expected_outcomes: list[str] = field(default_factory=list)
    spec_readiness: str = "ready"
    confidence: float = 0.6


@dataclass
class TestIdeaGenerationResult:
    """Result of test idea generation."""

    ideas: list[GeneratedTestIdea]
    source_exploration_session: str | None
    generated_at: datetime
    total_ideas: int
    by_category: dict[str, int]
    by_priority: dict[str, int]


class TestIdeaGenerator:
    """Generate test ideas from exploration, requirements, issues, and APIs."""

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        self.store = get_exploration_store(project_id=project_id)

    async def generate_from_exploration(self, exploration_session_id: str) -> TestIdeaGenerationResult:
        """Generate and persist test ideas for an exploration session."""
        session = self.store.get_session(exploration_session_id)
        if not session:
            raise ValueError(f"Exploration session not found: {exploration_session_id}")

        summary = self._build_summary(exploration_session_id)
        ideas = await self._generate_with_ai(summary)

        if not ideas:
            ideas = self._fallback_ideas(summary)

        self._store_ideas(ideas, exploration_session_id)

        by_category: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        for idea in ideas:
            by_category[idea.category] = by_category.get(idea.category, 0) + 1
            by_priority[idea.priority] = by_priority.get(idea.priority, 0) + 1

        return TestIdeaGenerationResult(
            ideas=ideas,
            source_exploration_session=exploration_session_id,
            generated_at=datetime.utcnow(),
            total_ideas=len(ideas),
            by_category=by_category,
            by_priority=by_priority,
        )

    def _build_summary(self, exploration_session_id: str) -> dict[str, Any]:
        session = self.store.get_session(exploration_session_id)
        transitions = self.store.get_session_transitions(exploration_session_id)
        flows = self.store.get_session_flows(exploration_session_id)
        endpoints = self.store.get_session_api_endpoints(exploration_session_id)
        issues = self.store.get_session_issues(exploration_session_id)
        requirements = [
            r for r in self.store.get_requirements() if r.source_session_id == exploration_session_id
        ]

        flow_summaries = []
        for flow in flows:
            steps = self.store.get_flow_steps(flow.id)
            flow_summaries.append(
                {
                    "name": flow.flow_name,
                    "category": flow.flow_category,
                    "description": flow.description,
                    "start_url": flow.start_url,
                    "end_url": flow.end_url,
                    "is_success_path": flow.is_success_path,
                    "preconditions": flow.preconditions,
                    "postconditions": flow.postconditions,
                    "steps": [
                        {
                            "action": step.action_type,
                            "element": step.element_name or step.action_description,
                            "value": step.value,
                        }
                        for step in steps
                    ],
                }
            )
        if not flow_summaries:
            flow_summaries = self._load_flow_artifacts(exploration_session_id)

        quality = self._load_exploration_quality(exploration_session_id)

        return {
            "entry_url": session.entry_url if session else "",
            "source_session_id": exploration_session_id,
            "pages_discovered": session.pages_discovered if session else 0,
            "flows_discovered": session.flows_discovered if session else len(flow_summaries),
            "flows": flow_summaries,
            "requirements": [
                {
                    "code": r.req_code,
                    "title": r.title,
                    "description": r.description,
                    "category": r.category,
                    "priority": r.priority,
                    "acceptance_criteria": r.acceptance_criteria,
                }
                for r in requirements
            ],
            "transitions": [
                {
                    "sequence": t.sequence_number,
                    "action": t.action_type,
                    "element": t.action_target,
                    "before_url": t.before_url,
                    "after_url": t.after_url,
                    "transition_type": t.transition_type,
                    "changes": t.changes_description,
                }
                for t in transitions[:40]
            ],
            "api_endpoints": [
                {
                    "method": e.method,
                    "url": e.url,
                    "status": e.response_status,
                    "triggered_by": e.triggered_by_action,
                }
                for e in endpoints
            ],
            "issues": [
                {
                    "type": i.issue_type,
                    "severity": i.severity,
                    "url": i.url,
                    "description": i.description,
                    "evidence": i.evidence,
                }
                for i in issues
            ],
            "quality": quality,
        }

    async def _generate_with_ai(self, summary: dict[str, Any]) -> list[GeneratedTestIdea]:
        """Call the agent and parse generated ideas. Returns [] on recoverable failure."""
        if not (
            os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
        ):
            logger.info("No AI credential configured; using deterministic test idea fallback")
            return []

        source_type = SOURCE_OBSERVED
        if summary.get("quality", {}).get("fallback_used"):
            source_type = SOURCE_FALLBACK

        context = ContextBundle(stage="test_idea_generation")
        context.add(
            "exploration_and_requirements_summary",
            summary,
            source_type=source_type,
            confidence=(summary.get("quality", {}).get("quality_score", 100) or 100) / 100,
            notes="Only observed evidence should drive specific feature claims.",
        )

        prompt = f"""You are a senior test strategist. Generate traceable test ideas from the exploration data.

## Context Provenance
```json
{json.dumps(context.to_dict(), indent=2)}
```

Rules:
- Do not invent features that are not supported by the exploration data.
- If source_type is fallback or inferred, prefer broad availability/navigation checks over detailed behavioral tests.

Your output MUST be a single JSON object with a "test_ideas" array.

Each idea must include:
- title: concise test name
- description: what risk or behavior this validates
- category: one of happy_path, negative, edge_case, security, accessibility, api, regression, coverage
- priority: one of critical, high, medium, low
- source_flows: flow names that justify the idea
- source_requirements: requirement codes or titles that justify the idea
- source_api_endpoints: endpoint URLs if relevant
- suggested_steps: concrete test steps, ready for a markdown spec
- expected_outcomes: assertions or observable outcomes
- spec_readiness: ready, needs_data, needs_auth, or blocked
- confidence: number from 0 to 1 based on direct evidence

Prefer a small, high-signal set. Include happy path, negative/error, and API/edge coverage where evidence exists.
Do not invent features that are not supported by the exploration data.

Exploration data:
```json
{json.dumps(summary, indent=2)}
```

Output format:
```json
{{
  "test_ideas": [
    {{
      "title": "User can log in with valid credentials",
      "description": "Validates the primary authentication success path.",
      "category": "happy_path",
      "priority": "critical",
      "source_flows": ["User Login"],
      "source_requirements": ["REQ-001"],
      "source_api_endpoints": ["/api/auth/login"],
      "suggested_steps": ["Navigate to the login page", "Enter valid credentials", "Submit the form"],
      "expected_outcomes": ["The user reaches the dashboard"],
      "spec_readiness": "needs_auth",
      "confidence": 0.9
    }}
  ]
}}
```
"""
        metadata = build_prompt_metadata(
            prompt_id="test_idea_generator.from_exploration",
            version="2026-05-13.1",
            stage="test_idea_generation",
            schema_name="test_ideas.v1",
            rendered_prompt=prompt,
        )
        prompt = attach_prompt_metadata(prompt, metadata)

        try:
            from utils.agent_runner import AgentRunner

            runner = AgentRunner(timeout_seconds=300, allowed_tools=[], log_tools=False, model_tier="standard")
            result = await runner.run(prompt)
            if not result.success or not result.output.strip():
                logger.warning(f"AI test idea generation failed: {result.error}")
                return []
            return self._parse_response(result.output)
        except Exception as exc:
            logger.warning(f"AI test idea generation error: {exc}")
            return []

    def _load_exploration_quality(self, exploration_session_id: str) -> dict[str, Any]:
        candidates = [
            Path("runs") / "explorations" / exploration_session_id / "summary.json",
            Path("runs") / exploration_session_id / "summary.json",
            Path("/app/runs/explorations") / exploration_session_id / "summary.json",
            Path("/app/runs") / exploration_session_id / "summary.json",
        ]
        for path in candidates:
            if not path.exists():
                continue
            try:
                summary = json.loads(path.read_text())
                return summary.get("quality") or {
                    "quality_score": summary.get("qualityScore"),
                    "source_type": summary.get("sourceType"),
                }
            except Exception as exc:
                logger.debug(f"Failed to load exploration quality from {path}: {exc}")
                return {}
        return {}

    def _parse_response(self, response_text: str) -> list[GeneratedTestIdea]:
        data = extract_json_from_markdown(response_text)
        if isinstance(data, dict):
            raw_ideas = data.get("test_ideas", [])
        elif isinstance(data, list):
            raw_ideas = data
        else:
            raw_ideas = []
        if not isinstance(raw_ideas, list):
            return []
        return [self._normalize_idea(item) for item in raw_ideas if isinstance(item, dict)]

    def _fallback_ideas(self, summary: dict[str, Any]) -> list[GeneratedTestIdea]:
        """Produce useful deterministic ideas when AI output is unavailable."""
        ideas: list[GeneratedTestIdea] = []
        requirements = summary.get("requirements", [])
        flows = {flow.get("name"): flow for flow in summary.get("flows", []) if flow.get("name")}

        for req in requirements:
            title = req.get("title") or "Requirement behavior"
            priority = self._valid_priority(req.get("priority"))
            matching_flow_names = [
                name for name in flows if title.lower() in name.lower() or name.lower() in title.lower()
            ]
            steps = []
            for flow_name in matching_flow_names[:1]:
                for step in flows[flow_name].get("steps", [])[:8]:
                    action = step.get("action", "Interact")
                    element = step.get("element") or "the relevant element"
                    value = step.get("value")
                    if value:
                        steps.append(f"{action.capitalize()} {value} in {element}")
                    else:
                        steps.append(f"{action.capitalize()} {element}")

            if not steps:
                steps = [f"Navigate to {summary.get('entry_url', 'the application')}", f"Verify {title}"]

            ideas.append(
                GeneratedTestIdea(
                    title=f"Validate {title}",
                    description=req.get("description") or f"Validate requirement {title}.",
                    category="happy_path",
                    priority=priority,
                    source_flows=matching_flow_names,
                    source_requirements=[req.get("code") or title],
                    suggested_steps=steps,
                    expected_outcomes=req.get("acceptance_criteria") or [f"{title} works as expected"],
                    spec_readiness="ready",
                    confidence=0.7 if matching_flow_names else 0.5,
                )
            )

            if not matching_flow_names:
                entry_url = summary.get("entry_url", "the application")
                source_requirement = req.get("code") or title
                ideas.extend(
                    [
                        GeneratedTestIdea(
                            title=f"Validate {title} has no critical console errors",
                            description=(
                                f"Checks runtime stability for {title} without assuming unsupported "
                                "business behavior."
                            ),
                            category="regression",
                            priority=priority,
                            source_requirements=[source_requirement],
                            suggested_steps=[
                                f"Navigate to {entry_url}",
                                "Wait for the page to finish loading",
                                "Observe browser console messages",
                                "Verify no critical JavaScript runtime errors are present",
                            ],
                            expected_outcomes=[
                                "No uncaught JavaScript exception blocks the page",
                                "The page remains interactive after load",
                            ],
                            spec_readiness="ready",
                            confidence=0.4,
                        ),
                        GeneratedTestIdea(
                            title=f"Validate {title} accessibility basics",
                            description=f"Checks basic accessible structure for {title}.",
                            category="accessibility",
                            priority=priority,
                            source_requirements=[source_requirement],
                            suggested_steps=[
                                f"Navigate to {entry_url}",
                                "Take a browser snapshot",
                                "Verify visible interactive elements have readable labels or accessible names",
                                "Verify keyboard focus can move through visible interactive elements",
                            ],
                            expected_outcomes=[
                                "Visible controls expose accessible labels",
                                "Keyboard focus is not trapped on page load",
                            ],
                            spec_readiness="ready",
                            confidence=0.35,
                        ),
                        GeneratedTestIdea(
                            title=f"Validate {title} mobile rendering",
                            description=f"Checks responsive rendering for {title}.",
                            category="edge_case",
                            priority=priority,
                            source_requirements=[source_requirement],
                            suggested_steps=[
                                "Set viewport to a mobile size",
                                f"Navigate to {entry_url}",
                                "Wait for the page to finish loading",
                                "Verify the primary content is visible without horizontal overflow",
                            ],
                            expected_outcomes=[
                                "Primary content remains visible on mobile",
                                "No major layout overlap blocks interaction",
                            ],
                            spec_readiness="ready",
                            confidence=0.35,
                        ),
                    ]
                )

            criteria_text = " ".join(req.get("acceptance_criteria") or []).lower()
            if any(token in criteria_text for token in ("invalid", "error", "empty", "required", "validation")):
                ideas.append(
                    GeneratedTestIdea(
                        title=f"Reject invalid input for {title}",
                        description=f"Validates negative and validation behavior for {title}.",
                        category="negative",
                        priority=priority,
                        source_flows=matching_flow_names,
                        source_requirements=[req.get("code") or title],
                        suggested_steps=[
                            f"Navigate to {summary.get('entry_url', 'the application')}",
                            "Submit the relevant form or action with invalid or missing data",
                            "Observe the validation response",
                        ],
                        expected_outcomes=["The system prevents invalid completion", "A clear error is shown"],
                        spec_readiness="ready",
                        confidence=0.55,
                    )
                )

        for issue in summary.get("issues", []):
            ideas.append(
                GeneratedTestIdea(
                    title=f"Guard against {issue.get('type', 'discovered issue')}",
                    description=issue.get("description") or "Validates a discovered issue does not regress.",
                    category="regression",
                    priority=self._valid_priority(issue.get("severity")),
                    suggested_steps=[f"Navigate to {issue.get('url') or summary.get('entry_url', 'the affected page')}"],
                    expected_outcomes=[issue.get("description") or "The issue is not present"],
                    spec_readiness="ready",
                    confidence=0.65,
                )
            )

        if not ideas:
            for flow in summary.get("flows", []):
                name = flow.get("name") or "Discovered flow"
                steps = []
                for step in flow.get("steps", [])[:8]:
                    action = step.get("action", "Interact")
                    element = step.get("element") or "the relevant element"
                    value = step.get("value")
                    if value:
                        steps.append(f"{action.capitalize()} {value} in {element}")
                    else:
                        steps.append(f"{action.capitalize()} {element}")
                if not steps:
                    steps = [f"Navigate to {flow.get('start_url') or summary.get('entry_url', 'the application')}"]

                expected = flow.get("postconditions") or []
                if flow.get("description"):
                    expected.append(flow["description"])
                if not expected:
                    expected = [flow.get("outcome") or f"{name} completes with the expected result"]

                ideas.append(
                    GeneratedTestIdea(
                        title=f"Validate {name}",
                        description=flow.get("description") or f"Validate the discovered {name} flow.",
                        category="happy_path" if flow.get("is_success_path", True) else "negative",
                        priority="high" if flow.get("category") in {"authentication", "crud", "form_submission"} else "medium",
                        source_flows=[name],
                        suggested_steps=steps,
                        expected_outcomes=[str(item) for item in expected[:8]],
                        spec_readiness="ready",
                        confidence=0.6,
                    )
                )

        if not ideas and summary.get("transitions"):
            for idx, transition in enumerate(summary.get("transitions", [])[:10], 1):
                action = transition.get("action") or "navigate"
                element = transition.get("element") or "the discovered element"
                title = f"Validate discovered {str(action).replace('_', ' ')} path {idx}"
                ideas.append(
                    GeneratedTestIdea(
                        title=title,
                        description=transition.get("changes") or f"Validate the observed {action} interaction.",
                        category="negative" if transition.get("transition_type") == "error" else "happy_path",
                        priority="medium",
                        suggested_steps=[
                            f"Navigate to {transition.get('before_url') or summary.get('entry_url', 'the application')}",
                            f"{str(action).capitalize()} {element}",
                        ],
                        expected_outcomes=[
                            transition.get("changes")
                            or f"The application reaches {transition.get('after_url') or 'the expected state'}"
                        ],
                        spec_readiness="ready",
                        confidence=0.55,
                    )
                )

        if not ideas and summary.get("flows_discovered", 0) > 0:
            entry_url = summary.get("entry_url") or "the application"
            ideas.append(
                GeneratedTestIdea(
                    title="Validate discovered application journeys",
                    description=(
                        f"Exploration reported {summary.get('flows_discovered')} flows, "
                        "but detailed flow rows were unavailable."
                    ),
                    category="coverage",
                    priority="medium",
                    suggested_steps=[f"Navigate to {entry_url}", "Exercise the discovered primary journeys"],
                    expected_outcomes=["The discovered journeys remain reachable without unexpected errors"],
                    spec_readiness="ready",
                    confidence=0.4,
                )
            )

        if not ideas and (summary.get("pages_discovered", 0) > 0 or summary.get("entry_url")):
            entry_url = summary.get("entry_url") or "the application"
            ideas.extend(
                [
                    GeneratedTestIdea(
                        title="Validate application entry page availability",
                        description="Validates that the explored application entry point is reachable and renders.",
                        category="coverage",
                        priority="medium",
                        suggested_steps=[
                            f"Navigate to {entry_url}",
                            "Wait for the page to finish loading",
                            "Verify the page renders without a blocking error",
                        ],
                        expected_outcomes=[
                            "The application entry page is reachable",
                            "No 404, access-denied, blank page, or blocking application error is shown",
                        ],
                        spec_readiness="ready",
                        confidence=0.45,
                    ),
                    GeneratedTestIdea(
                        title="Validate entry page has no critical console errors",
                        description="Checks runtime stability without assuming unsupported business behavior.",
                        category="regression",
                        priority="medium",
                        suggested_steps=[
                            f"Navigate to {entry_url}",
                            "Wait for the page to finish loading",
                            "Observe browser console messages",
                            "Verify no critical JavaScript runtime errors are present",
                        ],
                        expected_outcomes=[
                            "No uncaught JavaScript exception blocks the page",
                            "The page remains interactive after load",
                        ],
                        spec_readiness="ready",
                        confidence=0.4,
                    ),
                    GeneratedTestIdea(
                        title="Validate entry page accessibility basics",
                        description="Checks basic accessible structure from page-level evidence.",
                        category="accessibility",
                        priority="medium",
                        suggested_steps=[
                            f"Navigate to {entry_url}",
                            "Take a browser snapshot",
                            "Verify visible interactive elements have readable labels or accessible names",
                            "Verify keyboard focus can move through visible interactive elements",
                        ],
                        expected_outcomes=[
                            "Visible controls expose accessible labels",
                            "Keyboard focus is not trapped on page load",
                        ],
                        spec_readiness="ready",
                        confidence=0.35,
                    ),
                    GeneratedTestIdea(
                        title="Validate entry page mobile rendering",
                        description="Checks responsive rendering from page-level evidence.",
                        category="edge_case",
                        priority="medium",
                        suggested_steps=[
                            "Set viewport to a mobile size",
                            f"Navigate to {entry_url}",
                            "Wait for the page to finish loading",
                            "Verify the primary content is visible without horizontal overflow",
                        ],
                        expected_outcomes=[
                            "Primary content remains visible on mobile",
                            "No major layout overlap blocks interaction",
                        ],
                        spec_readiness="ready",
                        confidence=0.35,
                    ),
                ]
            )

        return self._dedupe(ideas)

    def _load_flow_artifacts(self, exploration_session_id: str) -> list[dict[str, Any]]:
        """Load flows.json when DB flow rows are unavailable."""
        candidates = [
            Path("runs") / "explorations" / exploration_session_id / "flows.json",
            Path("runs") / exploration_session_id / "flows.json",
            Path("/app/runs/explorations") / exploration_session_id / "flows.json",
            Path("/app/runs") / exploration_session_id / "flows.json",
        ]
        for path in candidates:
            if not path.exists():
                continue
            try:
                raw = json.loads(path.read_text())
                data = raw.get("flows", raw) if isinstance(raw, dict) else raw
                if not isinstance(data, list):
                    return []
                return [self._normalize_artifact_flow(item, idx) for idx, item in enumerate(data, 1) if isinstance(item, dict)]
            except Exception as exc:
                logger.warning(f"Failed to load flow artifacts from {path}: {exc}")
                return []
        return []

    def _normalize_artifact_flow(self, flow: dict[str, Any], index: int) -> dict[str, Any]:
        return {
            "name": flow.get("name") or flow.get("title") or f"Discovered Flow {index}",
            "category": flow.get("category") or "navigation",
            "description": flow.get("description") or flow.get("outcome") or flow.get("happy_path"),
            "start_url": flow.get("startUrl") or flow.get("start_url") or flow.get("entry_point") or "",
            "end_url": flow.get("endUrl") or flow.get("end_url") or flow.get("exit_point") or "",
            "is_success_path": flow.get("isSuccessPath", flow.get("is_success_path", True)),
            "preconditions": flow.get("preconditions") or [],
            "postconditions": flow.get("postconditions") or [],
            "steps": self._normalize_steps(flow.get("steps") or flow.get("pages") or []),
        }

    def _normalize_steps(self, raw_steps: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_steps, list):
            return []
        steps: list[dict[str, Any]] = []
        for step in raw_steps:
            if isinstance(step, dict):
                action = step.get("action") or step.get("actionType") or step.get("action_type") or step.get("type") or "step"
                element = (
                    step.get("element")
                    or step.get("elementName")
                    or step.get("element_name")
                    or step.get("description")
                    or step.get("actionDescription")
                    or step.get("action_description")
                    or action
                )
                steps.append({"action": str(action), "element": str(element), "value": step.get("value")})
            elif step is not None:
                steps.append({"action": "step", "element": str(step)})
        return steps

    def _store_ideas(self, ideas: list[GeneratedTestIdea], exploration_session_id: str) -> None:
        try:
            from memory.manager import get_memory_manager

            manager = get_memory_manager(project_id=self.project_id)
            for idea in ideas:
                manager.store_test_idea(
                    description=idea.description,
                    priority=idea.priority,
                    category=idea.category,
                    metadata={
                        "title": idea.title,
                        "source_session_id": exploration_session_id,
                        "source_flows": idea.source_flows,
                        "source_requirements": idea.source_requirements,
                        "source_api_endpoints": idea.source_api_endpoints,
                        "suggested_steps": idea.suggested_steps,
                        "expected_outcomes": idea.expected_outcomes,
                        "spec_readiness": idea.spec_readiness,
                        "confidence": idea.confidence,
                        "generated_by": "test_idea_generator",
                    },
                )
        except Exception as exc:
            logger.warning(f"Failed to persist generated test ideas: {exc}")

    def _normalize_idea(self, raw: dict[str, Any]) -> GeneratedTestIdea:
        title = str(raw.get("title") or raw.get("name") or "Untitled test idea").strip()
        description = str(raw.get("description") or title).strip()
        confidence = raw.get("confidence", 0.6)
        try:
            confidence_float = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence_float = 0.6

        return GeneratedTestIdea(
            title=title[:160],
            description=description[:1000],
            category=self._valid_category(raw.get("category")),
            priority=self._valid_priority(raw.get("priority")),
            source_flows=self._string_list(raw.get("source_flows")),
            source_requirements=self._string_list(raw.get("source_requirements")),
            source_api_endpoints=self._string_list(raw.get("source_api_endpoints")),
            suggested_steps=self._string_list(raw.get("suggested_steps")),
            expected_outcomes=self._string_list(raw.get("expected_outcomes")),
            spec_readiness=self._valid_readiness(raw.get("spec_readiness")),
            confidence=confidence_float,
        )

    def _dedupe(self, ideas: list[GeneratedTestIdea]) -> list[GeneratedTestIdea]:
        seen: set[str] = set()
        deduped: list[GeneratedTestIdea] = []
        for idea in ideas:
            key = re.sub(r"\s+", " ", idea.title.lower()).strip()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(idea)
        return deduped

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()][:12]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    @staticmethod
    def _valid_category(value: Any) -> str:
        category = str(value or "coverage").strip().lower()
        return category if category in VALID_CATEGORIES else "coverage"

    @staticmethod
    def _valid_priority(value: Any) -> str:
        priority = str(value or "medium").strip().lower()
        return priority if priority in VALID_PRIORITIES else "medium"

    @staticmethod
    def _valid_readiness(value: Any) -> str:
        readiness = str(value or "ready").strip().lower()
        return readiness if readiness in VALID_READINESS else "ready"


async def generate_test_ideas_from_exploration(
    exploration_session_id: str, project_id: str = "default"
) -> TestIdeaGenerationResult:
    generator = TestIdeaGenerator(project_id=project_id)
    return await generator.generate_from_exploration(exploration_session_id)
