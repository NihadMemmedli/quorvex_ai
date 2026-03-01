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

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load Claude credentials and SDK
from load_env import setup_claude_env

setup_claude_env()

import logging

from memory.exploration_store import get_exploration_store
from utils.agent_runner import AgentRunner

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

    async def generate_from_exploration(self, exploration_session_id: str) -> RequirementsGenerationResult:
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

        # Pre-flight check: Verify AI credentials
        anthropic_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
        if not anthropic_token:
            raise RuntimeError("ANTHROPIC_AUTH_TOKEN not set. Configure AI credentials in .env file or settings.")

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
            session=session, transitions=transitions, flows=flows, api_endpoints=api_endpoints
        )

        # Generate requirements using AI
        logger.info("Generating requirements with AI analysis...")

        requirements = await self._generate_requirements_with_ai(exploration_summary)

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
            )
            stored_requirements.append(stored)

            # Link requirement to source flows
            for flow_name in req.source_flows:
                flow_id = flow_name_to_id.get(flow_name)
                if flow_id is not None:
                    try:
                        self.store.link_requirement_source(
                            requirement_id=stored.id, source_type="flow", source_id=flow_id, confidence=1.0
                        )
                    except Exception as e:
                        logger.warning(f"Failed to link flow source '{flow_name}': {e}")
                else:
                    logger.debug(f"Flow '{flow_name}' not found in session, skipping source link")

            # Link requirement to source API endpoints
            for endpoint in req.source_api_endpoints:
                endpoint_id = endpoint_url_to_id.get(endpoint)
                if endpoint_id is not None:
                    try:
                        self.store.link_requirement_source(
                            requirement_id=stored.id, source_type="api_endpoint", source_id=endpoint_id, confidence=1.0
                        )
                    except Exception as e:
                        logger.warning(f"Failed to link API endpoint source '{endpoint}': {e}")
                else:
                    logger.debug(f"API endpoint '{endpoint}' not found in session, skipping source link")

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
        )

        logger.info("Requirements Generation Complete!")
        logger.info(f"   Total Requirements: {result.total_requirements}")
        logger.info(f"   By Category: {json.dumps(by_category)}")
        logger.info(f"   By Priority: {json.dumps(by_priority)}")

        return result

    async def generate_from_flows(self, flows_data: list[dict[str, Any]]) -> RequirementsGenerationResult:
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
            "entry_url": flows_data[0].get("startUrl", "unknown") if flows_data else "unknown",
            "flows": flows_data,
            "transitions": [],
            "api_endpoints": [],
            "pages_discovered": len(
                set(f.get("startUrl", "") for f in flows_data) | set(f.get("endUrl", "") for f in flows_data)
            ),
            "flows_discovered": len(flows_data),
        }

        # Generate requirements using AI
        logger.info("Generating requirements with AI analysis...")

        requirements = await self._generate_requirements_with_ai(exploration_summary)

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

    def _build_exploration_summary(self, session, transitions, flows, api_endpoints) -> dict[str, Any]:
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
                    "steps": [{"action": s.action_type, "element": s.element_name, "value": s.value} for s in steps],
                }
            )

        # Summarize API endpoints
        endpoint_summaries = []
        for e in api_endpoints:
            endpoint_summaries.append(
                {"method": e.method, "url": e.url, "status": e.response_status, "triggered_by": e.triggered_by_action}
            )

        return {
            "entry_url": session.entry_url,
            "pages_discovered": session.pages_discovered,
            "flows_discovered": session.flows_discovered,
            "elements_discovered": session.elements_discovered,
            "transitions": transition_summaries,
            "flows": flow_summaries,
            "api_endpoints": endpoint_summaries,
        }

    async def _generate_requirements_with_ai(self, exploration_summary: dict[str, Any]) -> list[GeneratedRequirement]:
        """Use AI to generate requirements from exploration data."""

        prompt = f"""You are a Requirements Analyst AI. Analyze the following application exploration data and generate functional requirements.

## Exploration Data

**Entry URL**: {exploration_summary.get("entry_url", "unknown")}
**Pages Discovered**: {exploration_summary.get("pages_discovered", 0)}
**Flows Discovered**: {exploration_summary.get("flows_discovered", 0)}

### Discovered User Flows
```json
{json.dumps(exploration_summary.get("flows", []), indent=2)}
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

Generate the requirements now:
"""

        logger.info("   Calling AI for requirements analysis...")

        # Use AgentRunner which automatically routes through Redis agent queue
        # when running inside uvicorn (avoids subprocess I/O hang)
        runner = AgentRunner(
            timeout_seconds=300,  # 5 min timeout for requirements analysis
            allowed_tools=[],  # No tools needed for analysis
            log_tools=False,
        )
        result = await runner.run(prompt)

        if not result.success:
            error_msg = result.error or "Unknown error"
            if result.timed_out:
                raise RuntimeError(f"AI request timed out - try again or check API status: {error_msg}")
            raise RuntimeError(f"AI requirements generation failed: {error_msg}")

        result_text = result.output

        if not result_text or not result_text.strip():
            raise RuntimeError("AI returned empty response - check API credentials and connectivity")

        logger.info(f"   AI response received ({len(result_text)} chars)")

        # Parse requirements from response
        requirements = self._parse_requirements_response(result_text)

        if not requirements:
            preview = result_text[:500] if len(result_text) > 500 else result_text
            raise RuntimeError(
                f"AI responded but 0 requirements could be parsed. "
                f"Response preview ({len(result_text)} chars):\n{preview}"
            )

        # Reassign requirement codes using the store to avoid collisions
        # across sessions (AI always starts at REQ-001)
        for req in requirements:
            req.req_code = self.store.get_next_requirement_code()

        return requirements

    def _parse_requirements_response(self, response_text: str) -> list[GeneratedRequirement]:
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

    parser = argparse.ArgumentParser(description="Generate Requirements from Exploration")
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
