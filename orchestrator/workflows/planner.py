"""
Planner Workflow - Converts test specs to structured JSON plans
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add utils to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# Load Claude credentials
from load_env import setup_claude_env

setup_claude_env()

from claude_agent_sdk import ClaudeAgentOptions, query

from utils.json_utils import extract_json_from_markdown, validate_json_schema

# Memory system integration
try:
    from memory import get_memory_manager

    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False


class Planner:
    """Converts natural language test specifications into structured JSON plans"""

    def __init__(
        self, schema_path: str = "schemas/plan.schema.json", use_memory: bool = True, project_id: str | None = None
    ):
        self.schema_path = schema_path
        self.use_memory = use_memory and MEMORY_AVAILABLE
        self.project_id = project_id

        # Initialize memory manager if available
        self.memory_manager = None
        if self.use_memory:
            try:
                self.memory_manager = get_memory_manager(project_id=project_id)
            except Exception as e:
                logger.warning(f"Memory system unavailable: {e}")
                self.use_memory = False

    async def create_plan(self, spec_content: str, spec_path: str = None) -> dict:
        """
        Convert a test specification to a structured JSON plan.

        Args:
            spec_content: The markdown specification content
            spec_path: Optional path to the spec file (for context)

        Returns:
            Dict containing the structured test plan
        """
        logger.info("Creating test plan from specification...")

        # 1. Preprocess spec (handle includes & reused automation context)
        processed_content, reused_context = await self._preprocess_spec(spec_content, spec_path)

        # Gather memory context if available
        memory_context = await self._gather_memory_context(processed_content)

        # Build the prompt with JSON formatting requirements
        prompt = self._build_prompt(processed_content, spec_path, memory_context, reused_context)

        # Query the agent
        plan = await self._query_agent(prompt)

        # Inject reusable context into plan for Operator to use
        if reused_context:
            plan["reusableContext"] = reused_context

        # Validate against schema
        logger.info("Validating plan against schema...")
        validate_json_schema(plan, self.schema_path)

        logger.info(f"Plan created: {plan.get('testName', 'Unnamed')}")
        logger.info(f"   Steps: {len(plan.get('steps', []))}")

        return plan

    async def _preprocess_spec(self, content: str, spec_path: str = None) -> tuple[str, dict]:
        """
        Handle @include directives and extract context from automated templates.
        Returns: (processed_content, reused_context)
        """
        import re

        processed_lines = []
        reused_context = {}  # { "Login Step": { "action": "click", "selector": "..." } }

        base_dir = Path("specs")
        if spec_path:
            base_dir = Path(spec_path).parent

        lines = content.split("\n")
        for line in lines:
            # Check for @include "path/to/file.md"
            match = re.search(r'@include\s+"([^"]+)"', line)
            if match:
                ref_path = match.group(1)

                # Resolve path
                # Try multiple resolution strategies:
                # 1. Relative to current spec directory
                # 2. From project root (if path starts with specs/)
                # 3. Relative to specs/ directory
                target_file = base_dir / ref_path
                if not target_file.exists():
                    # Try from project root (handles "specs/templates/..." includes)
                    target_file = Path(ref_path)
                if not target_file.exists():
                    target_file = Path("specs") / ref_path

                if target_file.exists():
                    logger.info(f"   Including template: {ref_path}")
                    template_content = target_file.read_text()

                    # Recursively process the include (in case it includes others)
                    # Note: Simple recursion, no cycle detection yet
                    sub_content, sub_context = await self._preprocess_spec(template_content, str(target_file))
                    processed_lines.append(
                        f"\n# --- Included from {ref_path} ---\n{sub_content}\n# --- End Include ---\n"
                    )
                    reused_context.update(sub_context)

                    # Check for existing automation for this template
                    await self._extract_automation_context(ref_path, target_file, reused_context)
                else:
                    logger.warning(f"   Include file not found: {ref_path}")
                    processed_lines.append(f"<!-- MISSING INCLUDE: {ref_path} -->")
            else:
                processed_lines.append(line)

        return "\n".join(processed_lines), reused_context

    async def _extract_automation_context(self, ref_name: str, file_path: Path, context: dict):
        """
        Check if an automated test exists for this template and extract selectors.
        """
        try:
            # Clean name for file search
            stem = file_path.stem

            # Slugify ref_name for robust matching (matches Operator logic)
            import re

            slug = re.sub(r"[^a-z0-9]+", "-", ref_name.lower()).strip("-")

            # Common locations - check both generated and templates folders
            candidates = [
                f"tests/templates/{slug}.spec.ts",
                f"tests/generated/{slug}.spec.ts",
                f"tests/templates/{stem}.spec.ts",
                f"tests/generated/{stem}.spec.ts",
                f"tests/{stem}.spec.ts",
            ]

            found_code = None
            for c in candidates:
                if Path(c).exists():
                    found_code = Path(c).read_text()
                    break

            if found_code:
                logger.info(f"   found existing automation for {ref_name}, extracting selectors...")
                # Simple extraction of action calls
                # Look for await page.getByRole(..).click() or fill()
                import re

                # Extract simple actions to build a 'known steps' list
                # This is heuristic-based
                matches = re.finditer(
                    r"await page\.(getBy[a-zA-Z]+)\(([^)]+)\)\.(click|fill|check|selectOption)", found_code
                )

                steps_found = []
                for m in matches:
                    selector_method = m.group(1)
                    selector_args = m.group(2)
                    action = m.group(3)

                    # Store as a "Known Good Step" hint
                    steps_found.append(
                        {
                            "automation_id": f"{ref_name}",
                            "hint": f"Use page.{selector_method}({selector_args}) for {action}",
                        }
                    )

                if steps_found:
                    if "automated_templates" not in context:
                        context["automated_templates"] = {}
                    context["automated_templates"][ref_name] = steps_found

        except Exception as e:
            logger.warning(f"   Failed to extract automation context: {e}")

    async def _gather_memory_context(self, spec_content: str) -> dict:
        """Gather relevant context from memory"""
        if not self.use_memory or not self.memory_manager:
            return {}

        context = {"similar_tests": [], "successful_selectors": [], "coverage_gaps": []}

        try:
            # Extract potential URL from spec
            import re

            url_match = re.search(r"https?://[^\s\)]+", spec_content)
            url = url_match.group(0) if url_match else None

            # Find similar tests
            similar = self.memory_manager.find_similar_tests(
                description=spec_content[:500],  # Use first part of spec as query
                n_results=3,
                min_success_rate=0.6,
            )
            context["similar_tests"] = [
                {
                    "test_name": s["metadata"].get("test_name"),
                    "action": s["metadata"].get("action"),
                    "target": s["metadata"].get("target"),
                    "success_rate": s["metadata"].get("success_rate"),
                }
                for s in similar
            ]

            # Get coverage gaps for the URL
            if url:
                gaps = self.memory_manager.get_coverage_gaps(url=url, max_results=5)
                context["coverage_gaps"] = [
                    {"type": g["type"], "element_type": g.get("element_type"), "description": g["description"]}
                    for g in gaps
                ]

        except Exception as e:
            logger.warning(f"Error gathering memory context: {e}")

        return context

    def _build_prompt(
        self, spec_content: str, spec_path: str = None, memory_context: dict = None, reused_context: dict = None
    ) -> str:
        """Build the prompt for the agent"""
        prompt = """You are a test planning expert. Convert this test specification into a structured JSON plan.

CRITICAL: Output ONLY valid JSON. No explanations, no markdown formatting outside the code block.

OUTPUT FORMAT (copy this structure):
```json
{
  "testName": "Test name",
  "description": "What it tests",
  "baseUrl": "URL",
  "steps": [
    {
      "stepNumber": 1,
      "action": "navigate",
      "target": "https://example.com",
      "description": "Go to example.com"
    },
    {
      "stepNumber": 2,
      "action": "assert",
      "target": "Example Domain",
      "assertion": {"type": "visible", "expected": true},
      "description": "Verify heading visible"
    }
  ]
}
```

RULES:
1. For "navigate" actions: target = URL string
2. **SMART INCLUDE**: The spec contains included templates. The User has provided EXACT CODE HINTS for these.
   - You MUST use the provided selectors/actions for the included parts.
   - Do NOT invent new selectors if a hint is provided.
3. For "click"/"fill" actions: target = simple string describing the element
4. Number steps starting from 1

ACTION TYPES: navigate, click, fill, assert, screenshot
ASSERTION TYPES: visible, text
"""

        # Add memory context if available
        if memory_context and any(memory_context.values()):
            prompt += "\n\n## MEMORY CONTEXT (from previous tests):\n\n"

            if memory_context.get("similar_tests"):
                prompt += "### Similar Tests Found:\n"
                for test in memory_context["similar_tests"]:
                    if test.get("test_name"):
                        prompt += f"- {test['test_name']}: {test.get('action', '')} on {test.get('target', '')} "
                        prompt += f"(success rate: {test.get('success_rate', 0):.1%})\n"

        # Add Reused Automation Context
        if reused_context and reused_context.get("automated_templates"):
            prompt += "\n\n## 🤖 AUTOMATION CONTEXT (REUSE THESE SELECTORS):\n"
            prompt += "The following templates have existing automation. Use these exact interactions for their corresponding steps:\n"

            for template_name, hints in reused_context["automated_templates"].items():
                prompt += f"\n### Template: {template_name}\n"
                for hint in hints:
                    prompt += f"- {hint['hint']}\n"

            prompt += "\n**INSTRUCTION**: When you see steps from the above templates in the spec, map them to these exact Playwright actions/selectors.\n"

        prompt += "\nNow convert this specification to JSON:\n"

        if spec_path:
            prompt += f"\n# Spec File: {spec_path}\n\n"

        prompt += spec_content

        prompt += "\n\nOutput ONLY the JSON in a code block. No other text."

        return prompt

    async def _query_agent(self, prompt: str) -> dict:
        """Query the agent and extract JSON"""
        try:
            async for message in query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    allowed_tools=["Read"],
                    setting_sources=["project"],  # Enable .claude/ config
                ),
            ):
                # Log tool uses for real-time feedback
                if hasattr(message, "type"):
                    if message.type == "tool_use":
                        tool_name = getattr(message, "name", "unknown")
                        logger.info(f"   {tool_name}...")

                if hasattr(message, "result"):
                    result = message.result
                    # Extract JSON from markdown
                    plan = extract_json_from_markdown(result)
                    return plan

        except Exception as e:
            raise RuntimeError(f"Failed to query agent for planning: {e}")


# Convenience function for testing
async def plan_from_file(spec_path: str) -> dict:
    """
    Create a plan from a spec file.

    Args:
        spec_path: Path to the markdown spec file

    Returns:
        Structured test plan
    """
    # Get project_id from environment
    project_id = os.environ.get("MEMORY_PROJECT_ID")
    memory_enabled = os.environ.get("MEMORY_ENABLED", "true").lower() == "true"

    planner = Planner(use_memory=memory_enabled, project_id=project_id)

    spec_file = Path(spec_path)
    if not spec_file.exists():
        raise FileNotFoundError(f"Spec file not found: {spec_path}")

    spec_content = spec_file.read_text()

    return await planner.create_plan(spec_content, str(spec_file))


# Test the planner
async def main():
    """Test the planner with a real spec"""
    if len(sys.argv) < 2:
        logger.error("Usage: python planner.py <spec-file>")
        sys.exit(1)

    spec_path = sys.argv[1]

    try:
        plan = await plan_from_file(spec_path)

        # Save the plan
        output_file = Path("runs/test_plan.json")
        output_file.parent.mkdir(parents=True, exist_ok=True)

        import json

        with open(output_file, "w") as f:
            json.dump(plan, f, indent=2)

        logger.info(f"Plan saved to: {output_file}")
        logger.info("Plan preview:")
        logger.info(json.dumps(plan, indent=2))

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    from orchestrator.logging_config import setup_logging

    setup_logging()
    asyncio.run(main())
