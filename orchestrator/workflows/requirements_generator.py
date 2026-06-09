"""
Requirements Generator Workflow

Analyzes exploration data (transitions, flows, API endpoints) to infer
functional requirements. Uses an AI agent to intelligently interpret
the discovered application behavior and generate structured requirements.

The generated requirements can then be used for:
- RTM (Requirements Traceability Matrix) creation
- Coverage gap analysis
- Test planning
"""

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Add both project root and orchestrator package dir for package and standalone execution.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load Claude credentials and SDK
from load_env import setup_claude_env

setup_claude_env()

import logging

from memory.exploration_store import get_exploration_store
from orchestrator.ai.context import SOURCE_FALLBACK, SOURCE_OBSERVED, ContextBundle
from orchestrator.ai.prompt_registry import (
    attach_prompt_metadata,
    build_prompt_metadata,
)

logger = logging.getLogger(__name__)


@dataclass
class GeneratedRequirement:
    """A requirement inferred from exploration data."""

    req_code: str
    title: str
    description: str
    category: str
    priority: str
    acceptance_criteria: list[str]
    source_flows: list[str] = field(default_factory=list)
    source_elements: list[str] = field(default_factory=list)
    source_api_endpoints: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float = 0.7
    uncertainty_reason: str | None = None


@dataclass
class RequirementsGenerationTelemetry:
    """Progress metadata for visible requirements analysis phases."""

    mode: str = "single_agent"
    subagents: list[dict[str, Any]] = field(default_factory=list)
    evidence_packets: int = 0
    requirements_generated: int = 0
    verification_status: str = "off"


@dataclass
class RequirementsGenerationResult:
    """Result of requirements generation."""

    requirements: list[GeneratedRequirement]
    session_id: str | None
    source_exploration_session: str | None
    generated_at: datetime
    total_requirements: int
    by_category: dict[str, int]
    by_priority: dict[str, int]
    telemetry: RequirementsGenerationTelemetry = field(default_factory=RequirementsGenerationTelemetry)


class RequirementsGenerator:
    """
    Requirements Generator that infers requirements from exploration data.

    Uses AI to analyze:
    - Discovered user flows
    - State transitions
    - API endpoints
    - Form behaviors
    - Error states

    And generates structured functional requirements.
    """

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        self.store = get_exploration_store(project_id=project_id)

    async def generate_from_exploration(
        self,
        exploration_session_id: str,
        *,
        mode: str = "single_agent",
        max_agents: int = 3,
        browser_verification: str = "off",
        progress_callback: Any | None = None,
    ) -> RequirementsGenerationResult:
        """
        Generate requirements from an exploration session.

        Args:
            exploration_session_id: ID of the exploration session

        Returns:
            RequirementsGenerationResult with generated requirements

        Raises:
            ValueError: If session not found or has insufficient data
            RuntimeError: If AI credentials are missing or API call fails
        """
        logger.info("=" * 80)
        logger.info("REQUIREMENTS GENERATION")
        logger.info("=" * 80)
        logger.info(f"   Source Session: {exploration_session_id}")
        logger.info("")

        # Load exploration data
        session = self.store.get_session(exploration_session_id)
        if not session:
            raise ValueError(f"Exploration session not found: {exploration_session_id}")

        transitions = self.store.get_session_transitions(exploration_session_id)
        flows = self.store.get_session_flows(exploration_session_id)
        api_endpoints = self.store.get_session_api_endpoints(exploration_session_id)

        logger.info(f"   Transitions: {len(transitions)}")
        logger.info(f"   Flows: {len(flows)}")
        logger.info(f"   API Endpoints: {len(api_endpoints)}")
        logger.info("")

        # Build lookup maps for linking sources by name/url
        flow_name_to_id = {f.flow_name: f.id for f in flows}
        endpoint_url_to_id = {e.url: e.id for e in api_endpoints}

        # Build exploration summary for AI analysis
        exploration_summary = self._build_exploration_summary(
            session=session,
            transitions=transitions,
            flows=flows,
            api_endpoints=api_endpoints,
        )

        mode = mode if mode in {"single_agent", "multi_agent"} else "single_agent"
        browser_verification = (
            browser_verification if browser_verification in {"off", "selected"} else "off"
        )
        max_agents = max(1, min(int(max_agents or 3), 6))
        telemetry = RequirementsGenerationTelemetry(
            mode=mode,
            verification_status=browser_verification,
        )

        async def emit_progress(message: str, **patch: Any) -> None:
            for key, value in patch.items():
                if hasattr(telemetry, key):
                    setattr(telemetry, key, value)
            if progress_callback:
                maybe_result = progress_callback(
                    {
                        "message": message,
                        "mode": telemetry.mode,
                        "subagents": telemetry.subagents,
                        "items_total": telemetry.evidence_packets,
                        "requirements_generated": telemetry.requirements_generated,
                        "verification_status": telemetry.verification_status,
                    }
                )
                if asyncio.iscoroutine(maybe_result):
                    await maybe_result

        # Generate requirements using AI
        logger.info("Generating requirements with AI analysis...")
        await emit_progress("Analyzing exploration evidence")

        try:
            if mode == "multi_agent":
                requirements, telemetry = await self._generate_requirements_multi_agent(
                    exploration_summary,
                    max_agents=max_agents,
                    browser_verification=browser_verification,
                    telemetry=telemetry,
                    progress_callback=emit_progress,
                )
            else:
                requirements = await self._generate_requirements_with_ai(
                    exploration_summary
                )
                telemetry.requirements_generated = len(requirements)
        except Exception as exc:
            logger.warning(
                f"AI requirements generation failed, using flow-based fallback: {exc}"
            )
            requirements = self._generate_fallback_requirements(exploration_summary)
            telemetry.subagents = [
                {"name": "fallback", "status": "completed", "items_completed": len(requirements)}
            ]
            telemetry.requirements_generated = len(requirements)

        if not requirements:
            logger.warning(
                "AI requirements generation returned 0 requirements, using flow-based fallback"
            )
            requirements = self._generate_fallback_requirements(exploration_summary)
            telemetry.requirements_generated = len(requirements)
        elif self._requirements_are_sparse(requirements, exploration_summary):
            logger.info(
                "AI generated sparse requirements for broad exploration; augmenting from page/flow evidence"
            )
            requirements = self._augment_sparse_requirements(
                requirements, exploration_summary
            )
            telemetry.requirements_generated = len(requirements)

        self._assign_requirement_codes(requirements)

        # Store requirements
        logger.info(f"Storing {len(requirements)} requirements...")

        stored_requirements = []
        for req in requirements:
            stored = self.store.store_requirement(
                req_code=req.req_code,
                title=req.title,
                category=req.category,
                description=req.description,
                priority=req.priority,
                acceptance_criteria=req.acceptance_criteria,
                source_session_id=exploration_session_id,
                confidence=req.confidence,
                uncertainty_reason=req.uncertainty_reason,
                provenance_metadata={
                    "generation_mode": telemetry.mode,
                    "browser_verification": telemetry.verification_status,
                    "evidence_refs": req.evidence_refs,
                    "source_flows": req.source_flows,
                    "source_elements": req.source_elements,
                    "source_api_endpoints": req.source_api_endpoints,
                },
            )
            stored_requirements.append(stored)

            # Link requirement to source flows
            for flow_name in req.source_flows:
                flow_id = flow_name_to_id.get(flow_name)
                if flow_id is not None:
                    try:
                        self.store.link_requirement_source(
                            requirement_id=stored.id,
                            source_type="flow",
                            source_id=flow_id,
                            confidence=1.0,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to link flow source '{flow_name}': {e}")
                else:
                    logger.debug(
                        f"Flow '{flow_name}' not found in session, skipping source link"
                    )

            # Link requirement to source API endpoints
            for endpoint in req.source_api_endpoints:
                endpoint_id = endpoint_url_to_id.get(endpoint)
                if endpoint_id is not None:
                    try:
                        self.store.link_requirement_source(
                            requirement_id=stored.id,
                            source_type="api_endpoint",
                            source_id=endpoint_id,
                            confidence=1.0,
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to link API endpoint source '{endpoint}': {e}"
                        )
                else:
                    logger.debug(
                        f"API endpoint '{endpoint}' not found in session, skipping source link"
                    )

        # Calculate statistics
        by_category = {}
        by_priority = {}
        for req in requirements:
            by_category[req.category] = by_category.get(req.category, 0) + 1
            by_priority[req.priority] = by_priority.get(req.priority, 0) + 1

        result = RequirementsGenerationResult(
            requirements=requirements,
            session_id=None,  # Will be filled if we save a separate session
            source_exploration_session=exploration_session_id,
            generated_at=datetime.utcnow(),
            total_requirements=len(requirements),
            by_category=by_category,
            by_priority=by_priority,
            telemetry=telemetry,
        )

        logger.info("Requirements Generation Complete!")
        logger.info(f"   Total Requirements: {result.total_requirements}")
        logger.info(f"   By Category: {json.dumps(by_category)}")
        logger.info(f"   By Priority: {json.dumps(by_priority)}")

        return result

    async def generate_from_flows(
        self, flows_data: list[dict[str, Any]]
    ) -> RequirementsGenerationResult:
        """
        Generate requirements directly from flow data (without exploration session).

        Args:
            flows_data: List of flow dictionaries

        Returns:
            RequirementsGenerationResult
        """
        logger.info("=" * 80)
        logger.info("REQUIREMENTS GENERATION (from flows)")
        logger.info("=" * 80)
        logger.info(f"   Flows: {len(flows_data)}")
        logger.info("")

        # Build summary from raw flows
        exploration_summary = {
            "entry_url": (
                flows_data[0].get("startUrl", "unknown") if flows_data else "unknown"
            ),
            "flows": flows_data,
            "transitions": [],
            "api_endpoints": [],
            "pages_discovered": len(
                set(f.get("startUrl", "") for f in flows_data)
                | set(f.get("endUrl", "") for f in flows_data)
            ),
            "flows_discovered": len(flows_data),
        }

        # Generate requirements using AI
        logger.info("Generating requirements with AI analysis...")

        try:
            requirements = await self._generate_requirements_with_ai(
                exploration_summary
            )
        except Exception as exc:
            logger.warning(
                f"AI requirements generation failed, using flow-based fallback: {exc}"
            )
            requirements = self._generate_fallback_requirements(exploration_summary)

        if not requirements:
            requirements = self._generate_fallback_requirements(exploration_summary)

        self._assign_requirement_codes(requirements)

        # Calculate statistics
        by_category = {}
        by_priority = {}
        for req in requirements:
            by_category[req.category] = by_category.get(req.category, 0) + 1
            by_priority[req.priority] = by_priority.get(req.priority, 0) + 1

        return RequirementsGenerationResult(
            requirements=requirements,
            session_id=None,
            source_exploration_session=None,
            generated_at=datetime.utcnow(),
            total_requirements=len(requirements),
            by_category=by_category,
            by_priority=by_priority,
        )

    def _build_exploration_summary(
        self, session, transitions, flows, api_endpoints
    ) -> dict[str, Any]:
        """Build a summary of exploration data for AI analysis."""

        # Summarize transitions
        transition_summaries = []
        for t in transitions[:50]:  # Limit to avoid token overflow
            transition_summaries.append(
                {
                    "sequence": t.sequence_number,
                    "action": t.action_type,
                    "element": t.action_target,
                    "before_url": t.before_url,
                    "after_url": t.after_url,
                    "transition_type": t.transition_type,
                    "changes": t.changes_description,
                }
            )

        # Summarize flows
        flow_summaries = []
        for f in flows:
            steps = self.store.get_flow_steps(f.id)
            flow_summaries.append(
                {
                    "name": f.flow_name,
                    "category": f.flow_category,
                    "description": f.description,
                    "start_url": f.start_url,
                    "end_url": f.end_url,
                    "step_count": f.step_count,
                    "is_success_path": f.is_success_path,
                    "preconditions": f.preconditions,
                    "postconditions": f.postconditions,
                    "steps": [
                        {
                            "action": s.action_type,
                            "element": s.element_name,
                            "value": s.value,
                        }
                        for s in steps
                    ],
                }
            )
        if not flow_summaries:
            flow_summaries = self._load_flow_artifacts(session.id)

        page_summaries = self._load_page_artifacts(session.id)

        # Summarize API endpoints
        endpoint_summaries = []
        for e in api_endpoints:
            endpoint_summaries.append(
                {
                    "method": e.method,
                    "url": e.url,
                    "status": e.response_status,
                    "triggered_by": e.triggered_by_action,
                }
            )

        quality = self._load_exploration_quality(session.id)

        return {
            "entry_url": session.entry_url,
            "pages_discovered": session.pages_discovered,
            "flows_discovered": session.flows_discovered,
            "elements_discovered": session.elements_discovered,
            "transitions": transition_summaries,
            "flows": flow_summaries,
            "pages": page_summaries,
            "api_endpoints": endpoint_summaries,
            "quality": quality,
        }

    async def _generate_requirements_with_ai(
        self, exploration_summary: dict[str, Any]
    ) -> list[GeneratedRequirement]:
        """Use AI to generate requirements from exploration data."""

        anthropic_token = (
            os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
        )
        if not anthropic_token:
            raise RuntimeError("No AI credential configured")

        source_type = SOURCE_OBSERVED
        if exploration_summary.get("quality", {}).get("fallback_used"):
            source_type = SOURCE_FALLBACK

        context = ContextBundle(stage="requirements_generation")
        context.add(
            "exploration_summary",
            exploration_summary,
            source_type=source_type,
            confidence=(
                exploration_summary.get("quality", {}).get("quality_score", 100) or 100
            )
            / 100,
            notes="Exploration evidence is labeled so inferred/fallback data is not treated as browser-verified.",
        )

        prompt = f"""You are a Requirements Analyst AI. Analyze the following application exploration data and generate functional requirements.

## Context Provenance
```json
{json.dumps(context.to_dict(), indent=2)}
```

Rules:
- Treat source_type=observed as browser-verified evidence.
- Treat source_type=fallback or inferred as weaker evidence and avoid inventing specific behavior not directly supported.
- If evidence is weak, generate availability/navigation requirements instead of detailed feature requirements.

## Exploration Data

**Entry URL**: {exploration_summary.get("entry_url", "unknown")}
**Pages Discovered**: {exploration_summary.get("pages_discovered", 0)}
**Flows Discovered**: {exploration_summary.get("flows_discovered", 0)}

### Discovered User Flows
```json
{json.dumps(exploration_summary.get("flows", []), indent=2)}
```

### Discovered Pages
```json
{json.dumps(exploration_summary.get("pages", [])[:40], indent=2)}
```

### Discovered Transitions
```json
{json.dumps(exploration_summary.get("transitions", [])[:30], indent=2)}
```

### Discovered API Endpoints
```json
{json.dumps(exploration_summary.get("api_endpoints", []), indent=2)}
```

## Your Task

Analyze this exploration data and generate a list of functional requirements.

For each discovered flow or significant capability, create a requirement that captures:
1. What the user can do
2. What the system should provide
3. Expected behavior (acceptance criteria)

## Output Format

Output a JSON array of requirements. Each requirement should have:

```json
{{
  "requirements": [
    {{
      "req_code": "REQ-001",
      "title": "User Login",
      "description": "The system shall allow users to authenticate using email and password credentials.",
      "category": "authentication",
      "priority": "high",
      "acceptance_criteria": [
        "User can enter email and password",
        "Valid credentials redirect to dashboard",
        "Invalid credentials show error message",
        "Empty fields show validation error"
      ],
      "source_flows": ["User Login"],
      "source_elements": ["email input", "password input", "login button"],
      "source_api_endpoints": ["/api/auth/login"]
    }}
  ]
}}
```

## Requirement Categories
Use these categories:
- authentication: Login, logout, session management
- authorization: Permissions, access control
- navigation: Menu, routing, page access
- crud: Create, read, update, delete operations
- form_submission: Form handling, validation
- search: Search and filtering
- display: Data presentation, formatting
- integration: External services, APIs
- error_handling: Error states, recovery
- other: Anything else

## Requirement Priority
Assign priority based on:
- critical: Core functionality, security, data integrity
- high: Primary user flows, business-critical features
- medium: Secondary features, nice-to-have
- low: Edge cases, optional features

## Guidelines
1. Each distinct user capability should have its own requirement
2. Include both success and error scenarios in acceptance criteria
3. Map requirements to the flows/elements that revealed them
4. Be specific about expected behavior
5. Number requirements sequentially (REQ-001, REQ-002, etc.)
6. If pages greatly outnumber flows, derive requirements from distinct page purposes, forms, search/filter controls, service/detail navigation paths, and observed actions.
7. Use generic page availability requirements only when no richer page, transition, form, or flow evidence exists.

Generate the requirements now:
"""
        metadata = build_prompt_metadata(
            prompt_id="requirements_generator.from_exploration",
            version="2026-05-13.1",
            stage="requirements_generation",
            schema_name="requirements.v1",
            rendered_prompt=prompt,
        )
        prompt = attach_prompt_metadata(prompt, metadata)

        logger.info("   Calling AI for requirements analysis...")

        # Use AgentRunner which automatically routes through Redis agent queue
        # when running inside uvicorn (avoids subprocess I/O hang)
        from utils.agent_runner import AgentRunner

        runner = AgentRunner(
            timeout_seconds=300,  # 5 min timeout for requirements analysis
            allowed_tools=[],  # No tools needed for analysis
            log_tools=False,
            model_tier="deep",
        )
        result = await runner.run(prompt)

        if not result.success:
            error_msg = result.error or "Unknown error"
            if result.timed_out:
                raise RuntimeError(
                    f"AI request timed out - try again or check API status: {error_msg}"
                )
            raise RuntimeError(f"AI requirements generation failed: {error_msg}")

        result_text = result.output

        if not result_text or not result_text.strip():
            raise RuntimeError(
                "AI returned empty response - check API credentials and connectivity"
            )

        logger.info(f"   AI response received ({len(result_text)} chars)")

        # Parse requirements from response
        requirements = self._parse_requirements_response(result_text)

        if not requirements:
            preview = result_text[:500] if len(result_text) > 500 else result_text
            raise RuntimeError(
                f"AI responded but 0 requirements could be parsed. "
                f"Response preview ({len(result_text)} chars):\n{preview}"
            )

        return requirements

    async def _generate_requirements_multi_agent(
        self,
        exploration_summary: dict[str, Any],
        *,
        max_agents: int,
        browser_verification: str,
        telemetry: RequirementsGenerationTelemetry,
        progress_callback: Any,
    ) -> tuple[list[GeneratedRequirement], RequirementsGenerationTelemetry]:
        """Generate requirements through evidence curation, specialists, and critic."""
        packets = self._curate_evidence_packets(exploration_summary)
        telemetry.evidence_packets = len(packets)
        telemetry.subagents = [
            {"name": "evidence_curator", "status": "completed", "items_completed": len(packets)}
        ]
        await progress_callback(
            "Curated exploration evidence packets",
            evidence_packets=len(packets),
            subagents=telemetry.subagents,
        )

        if not packets:
            return [], telemetry

        selected_packets = packets
        specialist_status = [
            {
                "name": f"{packet['category']}_analyst",
                "status": "running",
                "surface": packet["category"],
                "items_total": 1,
                "items_completed": 0,
            }
            for packet in selected_packets
        ]
        telemetry.subagents = [telemetry.subagents[0], *specialist_status]
        await progress_callback("Specialist analysts drafting requirements", subagents=telemetry.subagents)

        semaphore = asyncio.Semaphore(max_agents)

        async def run_with_limit(packet: dict[str, Any]) -> list[GeneratedRequirement]:
            async with semaphore:
                return await self._run_requirement_specialist(packet, exploration_summary)

        tasks = [run_with_limit(packet) for packet in selected_packets]
        specialist_results = await asyncio.gather(*tasks, return_exceptions=True)
        candidates: list[GeneratedRequirement] = []
        completed_status: list[dict[str, Any]] = [telemetry.subagents[0]]
        for packet, result in zip(selected_packets, specialist_results, strict=False):
            status = {
                "name": f"{packet['category']}_analyst",
                "surface": packet["category"],
                "items_total": 1,
                "items_completed": 1,
            }
            if isinstance(result, Exception):
                logger.warning("Requirement specialist failed for %s: %s", packet["category"], result)
                status["status"] = "failed"
            else:
                status["status"] = "completed"
                status["requirements"] = len(result)
                candidates.extend(result)
            completed_status.append(status)
        telemetry.subagents = completed_status
        telemetry.requirements_generated = len(candidates)
        await progress_callback(
            "Specialist analysis complete",
            subagents=telemetry.subagents,
            requirements_generated=len(candidates),
        )

        if browser_verification == "selected":
            telemetry.verification_status = "selected_pending"
            await progress_callback("Selecting ambiguous requirements for browser verification")
            candidates = await self._verify_selected_requirements(candidates, exploration_summary)
            telemetry.verification_status = "selected_completed"
        else:
            telemetry.verification_status = "off"

        telemetry.subagents = [
            *telemetry.subagents,
            {"name": "critic_verifier", "status": "running", "items_total": len(candidates), "items_completed": 0},
        ]
        await progress_callback("Critic verifying support and deduplicating candidates", subagents=telemetry.subagents)
        requirements = await self._critic_synthesize_requirements(candidates, packets)
        telemetry.subagents[-1] = {
            "name": "critic_verifier",
            "status": "completed",
            "items_total": len(candidates),
            "items_completed": len(candidates),
            "requirements": len(requirements),
        }
        telemetry.subagents.append(
            {"name": "synthesizer", "status": "completed", "requirements": len(requirements)}
        )
        telemetry.requirements_generated = len(requirements)
        await progress_callback(
            "Requirements synthesis complete",
            subagents=telemetry.subagents,
            requirements_generated=len(requirements),
            verification_status=telemetry.verification_status,
        )
        return requirements, telemetry

    def _curate_evidence_packets(
        self, exploration_summary: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Compact exploration evidence by surface/category for specialist prompts."""
        packets_by_category: dict[str, dict[str, Any]] = {}

        def packet(category: str) -> dict[str, Any]:
            normalized = category if category in {
                "authentication",
                "authorization",
                "navigation",
                "crud",
                "form_submission",
                "search",
                "display",
                "integration",
                "error_handling",
                "other",
            } else "other"
            return packets_by_category.setdefault(
                normalized,
                {
                    "id": f"evidence:{normalized}",
                    "category": normalized,
                    "entry_url": exploration_summary.get("entry_url"),
                    "pages": [],
                    "flows": [],
                    "transitions": [],
                    "api_endpoints": [],
                    "quality": exploration_summary.get("quality") or {},
                },
            )

        for flow in exploration_summary.get("flows", []) or []:
            if not isinstance(flow, dict):
                continue
            category = str(flow.get("category") or "navigation")
            packet(category)["flows"].append(flow)

        for page in exploration_summary.get("pages", []) or []:
            if not isinstance(page, dict):
                continue
            derived = self._flow_from_page(page)
            category = str((derived or {}).get("category") or "display")
            packet(category)["pages"].append(page)

        for transition in exploration_summary.get("transitions", []) or []:
            if not isinstance(transition, dict):
                continue
            transition_type = str(transition.get("transition_type") or "")
            category = "error_handling" if transition_type == "error" else "navigation"
            packet(category)["transitions"].append(transition)

        for endpoint in exploration_summary.get("api_endpoints", []) or []:
            if not isinstance(endpoint, dict):
                continue
            packet("integration")["api_endpoints"].append(endpoint)

        packets = list(packets_by_category.values())
        for item in packets:
            item["evidence_refs"] = self._packet_evidence_refs(item)
            item["counts"] = {
                "pages": len(item["pages"]),
                "flows": len(item["flows"]),
                "transitions": len(item["transitions"]),
                "api_endpoints": len(item["api_endpoints"]),
            }
        return sorted(
            packets,
            key=lambda item: (
                -sum(item["counts"].values()),
                item["category"],
            ),
        )

    @staticmethod
    def _packet_evidence_refs(packet: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        for idx, flow in enumerate(packet.get("flows") or [], 1):
            name = flow.get("name") or f"flow-{idx}"
            refs.append(f"{packet['id']}:flow:{name}")
        for idx, page in enumerate(packet.get("pages") or [], 1):
            refs.append(f"{packet['id']}:page:{page.get('url') or idx}")
        for idx, endpoint in enumerate(packet.get("api_endpoints") or [], 1):
            method = endpoint.get("method") or "HTTP"
            refs.append(f"{packet['id']}:api:{method} {endpoint.get('url') or idx}")
        for idx, transition in enumerate(packet.get("transitions") or [], 1):
            refs.append(f"{packet['id']}:transition:{transition.get('sequence') or idx}")
        return refs[:20]

    async def _run_requirement_specialist(
        self,
        packet: dict[str, Any],
        exploration_summary: dict[str, Any],
    ) -> list[GeneratedRequirement]:
        prompt = f"""You are a specialist requirements analyst for the {packet['category']} surface.

Draft only requirements directly supported by this evidence packet. Do not infer business intent beyond observed pages, flows, transitions, and API calls.

Entry URL: {exploration_summary.get("entry_url", "unknown")}
Evidence packet:
```json
{json.dumps(packet, indent=2)}
```

Return JSON only:
{{
  "requirements": [
    {{
      "title": "Short capability title",
      "description": "The system shall ...",
      "category": "{packet['category']}",
      "priority": "critical|high|medium|low",
      "acceptance_criteria": ["Observable criterion"],
      "source_flows": ["Flow name from packet"],
      "source_elements": ["Observed element name"],
      "source_api_endpoints": ["Observed endpoint URL"],
      "evidence_refs": ["Evidence refs from packet"],
      "confidence": 0.0,
      "uncertainty_reason": "Why this is uncertain, or null"
    }}
  ]
}}
"""
        from utils.agent_runner import AgentRunner

        runner = AgentRunner(
            timeout_seconds=240,
            allowed_tools=[],
            log_tools=False,
            model_tier="deep",
        )
        result = await runner.run(prompt)
        if not result.success:
            raise RuntimeError(result.error or "specialist analysis failed")
        requirements = self._parse_requirements_response(result.output or "")
        fallback_refs = packet.get("evidence_refs") or [packet.get("id", "evidence")]
        for req in requirements:
            if not req.category:
                req.category = packet["category"]
            if not req.evidence_refs:
                req.evidence_refs = fallback_refs[:5]
            req.confidence = self._bounded_confidence(req.confidence)
            if req.confidence < 0.75 and not req.uncertainty_reason:
                req.uncertainty_reason = "Supported by limited exploration evidence and awaiting review."
        return requirements

    async def _critic_synthesize_requirements(
        self,
        candidates: list[GeneratedRequirement],
        packets: list[dict[str, Any]],
    ) -> list[GeneratedRequirement]:
        """Remove unsupported or duplicate candidates and keep the existing JSON shape."""
        supported_refs = {
            ref
            for packet in packets
            for ref in packet.get("evidence_refs", [])
        }
        supported_refs.add("browser_verification:selected")
        deduped: list[GeneratedRequirement] = []
        seen: set[str] = set()
        for req in candidates:
            title_key = self._normalize_title(req.title)
            if not title_key or title_key in seen:
                continue
            has_named_source = bool(req.source_flows or req.source_api_endpoints or req.source_elements)
            has_supported_ref = bool(set(req.evidence_refs or []) & supported_refs)
            if not has_named_source and not has_supported_ref:
                continue
            seen.add(title_key)
            req.evidence_refs = [ref for ref in req.evidence_refs if ref in supported_refs][:10]
            if not req.evidence_refs and supported_refs:
                req.confidence = min(req.confidence, 0.65)
                req.uncertainty_reason = req.uncertainty_reason or (
                    "Requirement is linked to named sources but lacks packet-level evidence refs."
                )
            req.confidence = self._bounded_confidence(req.confidence)
            deduped.append(req)
        return deduped

    async def _verify_selected_requirements(
        self,
        candidates: list[GeneratedRequirement],
        exploration_summary: dict[str, Any],
    ) -> list[GeneratedRequirement]:
        """Optionally ask a browser-enabled verifier to check selected uncertain claims."""
        selected = [
            req
            for req in candidates
            if req.priority in {"critical", "high"} or req.confidence < 0.7
        ][:3]
        if not selected:
            return candidates

        prompt = f"""Verify whether these requirement claims are visible from the app entry point.

Use browser tools only for the selected claims. Return JSON with title, verified boolean, confidence, and note.

Entry URL: {exploration_summary.get("entry_url", "unknown")}
Claims:
```json
{json.dumps([req.__dict__ for req in selected], indent=2, default=str)}
```
"""
        try:
            from utils.agent_runner import AgentRunner

            runner = AgentRunner(
                timeout_seconds=180,
                allowed_tools=[
                    "mcp__playwright-test__browser_navigate",
                    "mcp__playwright-test__browser_snapshot",
                    "mcp__playwright-test__browser_close",
                ],
                log_tools=True,
                model_tier="tool",
            )
            result = await runner.run(prompt)
            if not result.success or not result.output:
                return candidates
            verification = self._parse_verification_response(result.output)
        except Exception as exc:
            logger.warning("Selected browser verification failed: %s", exc)
            return candidates

        by_title = {self._normalize_title(item.get("title")): item for item in verification}
        for req in candidates:
            item = by_title.get(self._normalize_title(req.title))
            if not item:
                continue
            if item.get("verified") is True:
                req.confidence = max(req.confidence, self._bounded_confidence(item.get("confidence", 0.85)))
                req.evidence_refs = list(dict.fromkeys([*req.evidence_refs, "browser_verification:selected"]))
            elif item.get("verified") is False:
                req.confidence = min(req.confidence, self._bounded_confidence(item.get("confidence", 0.45)))
                req.uncertainty_reason = str(item.get("note") or "Selected browser verification did not confirm this claim.")
        return candidates

    @staticmethod
    def _parse_verification_response(response_text: str) -> list[dict[str, Any]]:
        from utils.json_utils import extract_json_from_markdown

        try:
            data = extract_json_from_markdown(response_text)
        except Exception:
            return []
        if isinstance(data, dict):
            items = data.get("verifications") or data.get("results") or []
        elif isinstance(data, list):
            items = data
        else:
            items = []
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _bounded_confidence(value: Any) -> float:
        try:
            return max(0.0, min(float(value), 1.0))
        except (TypeError, ValueError):
            return 0.7

    def _assign_requirement_codes(
        self, requirements: list[GeneratedRequirement]
    ) -> None:
        """Assign sequential requirement codes without duplicating within a batch."""
        if not requirements:
            return

        next_code = self.store.get_next_requirement_code()
        try:
            prefix, raw_num = next_code.split("-", 1)
            start = int(raw_num)
        except (ValueError, AttributeError):
            prefix = "REQ"
            start = 1

        for offset, req in enumerate(requirements):
            req.req_code = f"{prefix}-{start + offset:03d}"

    def _generate_fallback_requirements(
        self, exploration_summary: dict[str, Any]
    ) -> list[GeneratedRequirement]:
        """Generate basic requirements directly from discovered flows when AI is unavailable."""
        requirements: list[GeneratedRequirement] = []
        flows = exploration_summary.get("flows", []) or []
        endpoints = exploration_summary.get("api_endpoints", []) or []

        min_expected = self._minimum_expected_requirements(exploration_summary)
        if len(flows) < min_expected:
            flows = self._extend_flows_with_pages(
                flows,
                exploration_summary.get("pages", []) or [],
                limit=min_expected - len(flows),
            )
        if not flows and exploration_summary.get("transitions"):
            flows = self._flows_from_transitions(exploration_summary)
        if not flows and exploration_summary.get("flows_discovered", 0) > 0:
            flows = [self._count_based_flow(exploration_summary)]
        if not flows and (
            exploration_summary.get("pages_discovered", 0) > 0
            or exploration_summary.get("entry_url")
        ):
            flows = [self._page_based_flow(exploration_summary)]

        for idx, flow in enumerate(flows, 1):
            name = flow.get("name") or f"Discovered Flow {idx}"
            category = flow.get("category") or "navigation"
            if category not in {
                "authentication",
                "authorization",
                "navigation",
                "crud",
                "form_submission",
                "search",
                "display",
                "integration",
                "error_handling",
                "other",
            }:
                category = "other"

            is_success = bool(flow.get("is_success_path", True))
            priority = (
                "high"
                if is_success
                and category in {"authentication", "crud", "form_submission"}
                else "medium"
            )
            if not is_success:
                priority = "medium"

            criteria = []
            for postcondition in flow.get("postconditions") or []:
                criteria.append(str(postcondition))
            if flow.get("description"):
                criteria.append(str(flow["description"]))
            if not criteria:
                criteria = [
                    f"User can complete the {name} flow",
                    "The system reaches the expected end state without errors",
                ]
            if not is_success:
                criteria.append(
                    "The system presents a clear validation or error response"
                )

            source_endpoints = [
                e.get("url")
                for e in endpoints
                if e.get("url")
                and (
                    not e.get("triggered_by")
                    or name.lower() in str(e.get("triggered_by")).lower()
                )
            ][:5]

            requirements.append(
                GeneratedRequirement(
                    req_code=f"REQ-{idx:03d}",
                    title=name,
                    description=flow.get("description")
                    or f"The system shall support the {name} user flow.",
                    category=category,
                    priority=priority,
                    acceptance_criteria=criteria[:8],
                    source_flows=[name],
                    source_elements=self._source_elements(flow.get("steps", [])),
                    source_api_endpoints=source_endpoints,
                    evidence_refs=[
                        ref
                        for ref in (
                            f"flow:{name}",
                            f"page:{flow.get('start_url') or flow.get('startUrl') or ''}",
                        )
                        if ref and not ref.endswith(":")
                    ],
                    confidence=0.65,
                    uncertainty_reason="Generated deterministically from exploration evidence and awaiting human confirmation.",
                )
            )

        return requirements

    def _requirements_are_sparse(
        self,
        requirements: list[GeneratedRequirement],
        exploration_summary: dict[str, Any],
    ) -> bool:
        """Return True when broad exploration yielded too few requirements."""
        return len(requirements) < self._minimum_expected_requirements(
            exploration_summary
        )

    def _augment_sparse_requirements(
        self,
        requirements: list[GeneratedRequirement],
        exploration_summary: dict[str, Any],
    ) -> list[GeneratedRequirement]:
        """Append deterministic requirements from page/flow evidence without duplicating titles."""
        target = self._minimum_expected_requirements(exploration_summary)
        existing_titles = {self._normalize_title(req.title) for req in requirements}
        augmented = list(requirements)

        for candidate in self._generate_fallback_requirements(exploration_summary):
            if len(augmented) >= target:
                break
            key = self._normalize_title(candidate.title)
            if key in existing_titles:
                continue
            existing_titles.add(key)
            augmented.append(candidate)

        return augmented

    def _minimum_expected_requirements(
        self, exploration_summary: dict[str, Any]
    ) -> int:
        """Conservative expected requirement count for broad observed exploration."""
        pages = int(
            exploration_summary.get("pages_discovered", 0)
            or len(exploration_summary.get("pages", []) or [])
        )
        flow_count = len(exploration_summary.get("flows", []) or [])
        page_capabilities = self._count_page_capabilities(
            exploration_summary.get("pages", []) or []
        )
        if pages <= 1 and flow_count <= 1 and page_capabilities <= 1:
            return 1
        return max(1, min(15, max(flow_count, page_capabilities, pages // 4)))

    @staticmethod
    def _count_page_capabilities(pages: list[dict[str, Any]]) -> int:
        count = 0
        for page in pages:
            if not isinstance(page, dict):
                continue
            if page.get("url"):
                count += 1
            count += len(page.get("forms") or [])
            if page.get("actions"):
                count += 1
        return min(count, 15)

    def _extend_flows_with_pages(
        self,
        flows: list[dict[str, Any]],
        pages: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return flows
        existing = {
            (
                self._normalize_title(flow.get("name")),
                str(flow.get("start_url") or flow.get("startUrl") or "")
                .rstrip("/")
                .lower(),
            )
            for flow in flows
        }
        extended = list(flows)
        for page in pages:
            if len(extended) >= len(flows) + limit:
                break
            if not isinstance(page, dict):
                continue
            page_flow = self._flow_from_page(page)
            if not page_flow:
                continue
            key = (
                self._normalize_title(page_flow.get("name")),
                str(page_flow.get("start_url") or "").rstrip("/").lower(),
            )
            if key in existing:
                continue
            existing.add(key)
            extended.append(page_flow)
        return extended

    def _flow_from_page(self, page: dict[str, Any]) -> dict[str, Any] | None:
        url = str(page.get("url") or "").strip()
        if not url or url.startswith("__summary_page_"):
            return None
        label = self._page_label(page)
        forms = page.get("forms") or []
        actions = [str(item) for item in page.get("actions") or []]
        key_elements = [
            str(item)
            for item in page.get("keyElements") or page.get("key_elements") or []
        ]
        text = " ".join(
            [
                label,
                str(page.get("pageType") or page.get("page_type") or ""),
                str(page.get("purpose") or ""),
                *actions,
                *key_elements,
            ]
        ).lower()

        if forms:
            category = "form_submission"
            name = f"{label} Form Submission"
            steps = [
                {"action": "navigate", "element": url},
                {"action": "inspect", "element": self._first_form_name(forms)},
                {"action": "submit", "element": self._first_submit_name(forms)},
            ]
            description = f"Users can complete the primary form on {label}."
        elif any(token in text for token in ("search", "filter", "query")):
            category = "search"
            name = f"{label} Search or Filter"
            steps = [
                {"action": "navigate", "element": url},
                {
                    "action": "interact",
                    "element": self._first_matching(
                        actions + key_elements, ["search", "filter", "query"]
                    ),
                },
            ]
            description = f"Users can search or filter content on {label}."
        else:
            category = "navigation"
            name = f"{label} Page Access"
            steps = [{"action": "navigate", "element": url}]
            description = (
                page.get("purpose") or f"Users can access and inspect {label}."
            )

        return {
            "name": name,
            "category": category,
            "description": description,
            "start_url": url,
            "end_url": url,
            "is_success_path": True,
            "postconditions": [description],
            "steps": steps,
        }

    @staticmethod
    def _normalize_title(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())

    @staticmethod
    def _page_label(page: dict[str, Any]) -> str:
        raw = page.get("title") or page.get("pageType") or page.get("page_type") or ""
        if not raw:
            path = urlparse(str(page.get("url") or "")).path.strip("/")
            raw = path.split("/")[-1] or path or "application page"
        label = re.sub(r"[-_]+", " ", str(raw)).strip()
        label = re.sub(r"\s+", " ", label)
        return (label[:80] or "application page").title()

    @staticmethod
    def _first_form_name(forms: list[dict[str, Any]]) -> str:
        if not forms:
            return "form"
        form = forms[0] if isinstance(forms[0], dict) else {}
        return str(form.get("name") or form.get("title") or "form")

    @staticmethod
    def _first_submit_name(forms: list[dict[str, Any]]) -> str:
        if not forms:
            return "submit button"
        form = forms[0] if isinstance(forms[0], dict) else {}
        return str(form.get("submit") or form.get("submitButton") or "submit button")

    @staticmethod
    def _first_matching(values: list[str], keywords: list[str]) -> str:
        for value in values:
            lowered = value.lower()
            if any(keyword in lowered for keyword in keywords):
                return value
        return "relevant control"

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
                return [
                    self._normalize_artifact_flow(item, idx)
                    for idx, item in enumerate(data, 1)
                    if isinstance(item, dict)
                ]
            except Exception as exc:
                logger.warning(f"Failed to load flow artifacts from {path}: {exc}")
                return []
        return []

    def _load_page_artifacts(self, exploration_session_id: str) -> list[dict[str, Any]]:
        """Load observed page artifacts produced by the explorer."""
        candidates = [
            Path("runs") / "explorations" / exploration_session_id / "pages.json",
            Path("runs") / exploration_session_id / "pages.json",
            Path("/app/runs/explorations") / exploration_session_id / "pages.json",
            Path("/app/runs") / exploration_session_id / "pages.json",
        ]
        for path in candidates:
            if not path.exists():
                continue
            try:
                raw = json.loads(path.read_text())
                data = raw.get("pages", raw) if isinstance(raw, dict) else raw
                if not isinstance(data, list):
                    return []
                return [
                    item for item in data if isinstance(item, dict) and item.get("url")
                ]
            except Exception as exc:
                logger.warning(f"Failed to load page artifacts from {path}: {exc}")
                return []
        return []

    def _load_exploration_quality(self, exploration_session_id: str) -> dict[str, Any]:
        """Load exploration quality summary from saved artifacts when available."""
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

    def _normalize_artifact_flow(
        self, flow: dict[str, Any], index: int
    ) -> dict[str, Any]:
        name = flow.get("name") or flow.get("title") or f"Discovered Flow {index}"
        return {
            "name": name,
            "category": flow.get("category") or "navigation",
            "description": flow.get("description")
            or flow.get("outcome")
            or flow.get("happy_path"),
            "start_url": flow.get("startUrl")
            or flow.get("start_url")
            or flow.get("entry_point")
            or "",
            "end_url": flow.get("endUrl")
            or flow.get("end_url")
            or flow.get("exit_point")
            or "",
            "step_count": flow.get("step_count")
            or flow.get("steps_count")
            or len(flow.get("steps") or []),
            "is_success_path": flow.get(
                "isSuccessPath", flow.get("is_success_path", True)
            ),
            "preconditions": flow.get("preconditions") or [],
            "postconditions": flow.get("postconditions") or [],
            "steps": self._normalize_steps(
                flow.get("steps") or flow.get("pages") or []
            ),
        }

    def _normalize_steps(self, raw_steps: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_steps, list):
            return []
        steps: list[dict[str, Any]] = []
        for step in raw_steps:
            if isinstance(step, dict):
                action = (
                    step.get("action")
                    or step.get("actionType")
                    or step.get("action_type")
                    or step.get("type")
                    or "step"
                )
                element = (
                    step.get("element")
                    or step.get("elementName")
                    or step.get("element_name")
                    or step.get("description")
                    or step.get("actionDescription")
                    or step.get("action_description")
                    or action
                )
                steps.append(
                    {
                        "action": str(action),
                        "element": str(element),
                        "value": step.get("value"),
                    }
                )
            elif step is not None:
                steps.append({"action": "step", "element": str(step)})
        return steps

    def _source_elements(self, steps: Any) -> list[str]:
        elements: list[str] = []
        for step in self._normalize_steps(steps):
            element = step.get("element")
            if element:
                elements.append(str(element))
        return elements[:10]

    def _flows_from_transitions(
        self, exploration_summary: dict[str, Any]
    ) -> list[dict[str, Any]]:
        flows: list[dict[str, Any]] = []
        for idx, transition in enumerate(
            exploration_summary.get("transitions", [])[:20], 1
        ):
            before_url = transition.get("before_url") or exploration_summary.get(
                "entry_url", ""
            )
            after_url = transition.get("after_url") or before_url
            action = transition.get("action") or "navigate"
            element = transition.get("element") or "discovered element"
            title = f"{str(action).replace('_', ' ').title()} flow {idx}"
            flows.append(
                {
                    "name": title,
                    "category": "navigation",
                    "description": transition.get("changes")
                    or f"User can complete {title}.",
                    "start_url": before_url,
                    "end_url": after_url,
                    "is_success_path": transition.get("transition_type") != "error",
                    "postconditions": (
                        [transition.get("changes")] if transition.get("changes") else []
                    ),
                    "steps": [{"action": action, "element": element}],
                }
            )
        return flows

    def _count_based_flow(self, exploration_summary: dict[str, Any]) -> dict[str, Any]:
        entry_url = exploration_summary.get("entry_url") or "the application"
        flow_count = exploration_summary.get("flows_discovered", 0)
        page_count = exploration_summary.get("pages_discovered", 0)
        return {
            "name": "Discovered application journeys",
            "category": "navigation",
            "description": (
                f"Exploration discovered {flow_count} user journeys across {page_count} pages, "
                "but detailed flow rows were unavailable."
            ),
            "start_url": entry_url,
            "end_url": entry_url,
            "is_success_path": True,
            "postconditions": [
                "Discovered journeys remain reachable without unexpected errors"
            ],
            "steps": [{"action": "navigate", "element": entry_url}],
        }

    def _page_based_flow(self, exploration_summary: dict[str, Any]) -> dict[str, Any]:
        entry_url = exploration_summary.get("entry_url") or "the application"
        page_count = exploration_summary.get("pages_discovered", 0)
        return {
            "name": "Application availability and primary page access",
            "category": "navigation",
            "description": (
                f"Exploration reached {entry_url}"
                + (f" and discovered {page_count} page(s)." if page_count else ".")
            ),
            "start_url": entry_url,
            "end_url": entry_url,
            "is_success_path": True,
            "postconditions": [
                "The application entry page is reachable",
                "The page renders without a blocking application error",
            ],
            "steps": [{"action": "navigate", "element": entry_url}],
        }

    def _parse_requirements_response(
        self, response_text: str
    ) -> list[GeneratedRequirement]:
        """Parse requirements from AI response using robust JSON extraction."""
        from utils.json_utils import extract_json_from_markdown

        requirements = []
        req_list = None

        # Strategy 1: Use proven extract_json_from_markdown utility
        # Handles ```json blocks, ``` blocks, plain JSON, and truncated JSON
        try:
            data = extract_json_from_markdown(response_text)
            if isinstance(data, dict) and "requirements" in data:
                req_list = data["requirements"]
            elif isinstance(data, list):
                req_list = data
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"   Primary JSON extraction failed: {e}")

        # Strategy 2: Try extracting from multiple code blocks (AI may split output)
        if not req_list:
            json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
            matches = re.findall(json_pattern, response_text)
            for json_str in matches:
                try:
                    data = json.loads(json_str.strip())
                    if isinstance(data, dict) and "requirements" in data:
                        req_list = data["requirements"]
                        break
                    elif isinstance(data, list):
                        req_list = data
                        break
                except json.JSONDecodeError:
                    continue

        if not req_list:
            return requirements

        # Convert parsed dicts to GeneratedRequirement objects
        for req_data in req_list:
            if not isinstance(req_data, dict):
                continue
            req = GeneratedRequirement(
                req_code=req_data.get("req_code", f"REQ-{len(requirements) + 1:03d}"),
                title=req_data.get("title", "Unnamed Requirement"),
                description=req_data.get("description", ""),
                category=req_data.get("category", "other"),
                priority=req_data.get("priority", "medium"),
                acceptance_criteria=req_data.get("acceptance_criteria", []),
                source_flows=req_data.get("source_flows", []),
                source_elements=req_data.get("source_elements", []),
                source_api_endpoints=req_data.get("source_api_endpoints", []),
                evidence_refs=req_data.get("evidence_refs", []),
                confidence=self._bounded_confidence(req_data.get("confidence", 0.7)),
                uncertainty_reason=req_data.get("uncertainty_reason"),
            )
            requirements.append(req)

        return requirements


async def generate_requirements_from_exploration(
    exploration_session_id: str, project_id: str = "default"
) -> RequirementsGenerationResult:
    """
    Convenience function to generate requirements from an exploration session.

    Args:
        exploration_session_id: ID of the exploration session
        project_id: Project ID

    Returns:
        RequirementsGenerationResult
    """
    generator = RequirementsGenerator(project_id=project_id)
    return await generator.generate_from_exploration(exploration_session_id)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate Requirements from Exploration"
    )
    parser.add_argument("session_id", help="Exploration session ID")
    parser.add_argument("--project", default="default", help="Project ID")

    args = parser.parse_args()

    async def main():
        result = await generate_requirements_from_exploration(
            exploration_session_id=args.session_id, project_id=args.project
        )
        logger.info(f"Generated {result.total_requirements} requirements")

    try:
        from orchestrator.logging_config import setup_logging

        setup_logging()
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass
        else:
            raise
