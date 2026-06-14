"""
Spec Synthesis Agent

Takes exploration results from the Enhanced ExploratoryAgent
and synthesizes them into production-ready .md test specs
that work with the existing 5-stage pipeline.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

# Import using absolute path (sys.path is set in base_agent.py)
from utils.json_utils import extract_json_from_markdown
from workflows.spec_scenario_builder import (
    E2EScenario,
    conservative_page_scenarios,
    scenario_from_requirement,
    write_scenarios,
)

from .base_agent import BaseAgent


class SpecSynthesisAgent(BaseAgent):
    """
    Synthesizes exploration results into .md test specs.

    Process:
    1. Analyze exploration results
    2. Identify distinct user flows
    3. Group discoveries by feature/risk
    4. Generate .md specs (happy path + edge cases)
    5. Output specs in existing format
    """

    async def run(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Synthesize exploration results into .md specs.

        Config:
        - exploration_results: Results from ExploratoryAgent
        - url: Base URL of explored application
        - output_dir: Directory to save specs (optional)
        - run_id: Run ID to read full flows from flows.json
        """
        exploration_results = config.get("exploration_results")
        base_url = config.get("url", "")
        output_dir = Path(config.get("output_dir", "specs/generated"))
        run_id = config.get("run_id")
        output_dir.mkdir(parents=True, exist_ok=True)

        if not exploration_results:
            return {"summary": "No exploration results provided", "error": "exploration_results is required"}

        # Load full flows from flows.json if available
        discovered_flows = []
        if run_id:
            discovered_flows = self._load_flows_from_file(run_id)
            print(f"   Loaded {len(discovered_flows)} flows from flows.json")

        # Fallback to discovered_flows in exploration_results (old format)
        if not discovered_flows:
            discovered_flows = exploration_results.get("discovered_flows", [])

        print("✍️ Starting Spec Synthesis Agent")
        print(f"   Discovered flows: {len(discovered_flows)}")
        print(f"   Output directory: {output_dir}")

        # Get project_id for database registration
        project_id = config.get("project_id")

        # Analyze and synthesize
        synthesis_result = await self._synthesize_specs(
            exploration_results, discovered_flows, base_url, output_dir, project_id
        )

        return synthesis_result

    async def _synthesize_specs(
        self,
        exploration_results: dict[str, Any],
        discovered_flows: list[dict],
        base_url: str,
        output_dir: Path,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Synthesize specs from exploration results.

        This can be done via:
        1. Direct generation (Python logic)
        2. Agent-assisted generation (AI-powered)

        We'll use agent-assisted for better quality.
        """
        # Build synthesis prompt
        prompt = self._build_synthesis_prompt(exploration_results, discovered_flows, base_url)

        # Query agent
        result = await self._query_agent(prompt)

        # Parse and save specs
        try:
            data = extract_json_from_markdown(result)

            # Save specs to files and register in DB
            saved_specs = {}
            for category, files in data.get("specs", {}).items():
                saved_specs[category] = {}
                for filename, content in files.items():
                    filepath = output_dir / filename
                    filepath.write_text(content)
                    saved_specs[category][filename] = str(filepath)

                    # Register spec in database with project association
                    self._register_spec_in_db(filepath, project_id)

            return {
                "summary": data.get("summary", "Spec synthesis complete"),
                "specs": saved_specs,
                "total_specs": sum(len(v) for v in saved_specs.values()),
                "flows_covered": data.get("flows_covered", []),
                "exploration_url": base_url,
                "generated_at": datetime.now().isoformat(),
            }

        except Exception:
            # Fallback: generate specs directly
            return await self._generate_specs_directly(
                exploration_results, discovered_flows, base_url, output_dir, project_id
            )

    async def _generate_specs_directly(
        self,
        exploration_results: dict[str, Any],
        discovered_flows: list[dict],
        base_url: str,
        output_dir: Path,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Direct spec generation (fallback without agent).

        Generates specs based on exploration results using Python logic.
        """
        scenarios: list[E2EScenario] = []
        flows_covered = []

        for flow in discovered_flows:
            flow_name = flow.get("title", flow.get("name", "Unknown Flow"))
            flows_covered.append(flow_name)
            steps = [str(step) for step in flow.get("steps", []) if str(step).strip()]
            pages = [str(page) for page in flow.get("pages", []) if str(page).strip()]
            if not steps and pages:
                steps = [f"Navigate to {page}" for page in pages]

            scenarios.append(
                scenario_from_requirement(
                    title=f"{flow_name} happy path",
                    description=flow.get("happy_path") or f"Validate the successful {flow_name} journey.",
                    target_url=flow.get("entry_point") or base_url,
                    flow_steps=steps,
                    acceptance_criteria=[
                        f"User successfully completes the {flow_name}",
                        "No blocking errors are displayed",
                    ],
                    category="happy_path",
                    priority="high" if flow.get("complexity") == "high" else "medium",
                    source_flows=[flow_name],
                )
            )

            edge_cases = flow.get("edge_cases", [])
            for edge_case in edge_cases[:4]:
                scenarios.append(
                    E2EScenario(
                        title=f"{flow_name} handles {edge_case}",
                        description=f"Validate edge-case handling for {flow_name}: {edge_case}.",
                        category="edge_case",
                        priority="medium",
                        preconditions=["Fresh browser session", "Required data for the flow is available"],
                        steps=[
                            f"Navigate to {flow.get('entry_point') or base_url}",
                            f"Start the {flow_name} flow",
                            f"Exercise edge case: {edge_case}",
                            "Attempt to continue or submit the flow",
                        ],
                        expected_outcomes=[
                            "The application handles the edge case without crashing",
                            "A clear validation, empty state, or safe fallback is shown when applicable",
                        ],
                        test_data=[f"Target URL: {flow.get('entry_point') or base_url}"],
                        source_notes=[f"Source flow: {flow_name}"],
                    )
                )

        if not scenarios:
            scenarios = conservative_page_scenarios(
                title="Application entry page",
                target_url=base_url or exploration_results.get("url") or "the application",
                max_scenarios=4,
            )

        generated_files = write_scenarios(scenarios[:12], output_dir)

        saved_specs: dict[str, dict[str, str]] = {}
        for scenario, filepath in zip(scenarios, generated_files, strict=False):
            category = scenario.category or "coverage"
            saved_specs.setdefault(category, {})[filepath.name] = str(filepath)
            self._register_spec_in_db(filepath, project_id)

        return {
            "summary": f"Generated {len(generated_files)} individual E2E scenario specs",
            "specs": saved_specs,
            "total_specs": sum(len(v) for v in saved_specs.values()),
            "flows_covered": flows_covered,
            "exploration_url": base_url,
            "generated_at": datetime.now().isoformat(),
        }

    def _generate_happy_path_spec(self, flow: dict[str, Any], base_url: str, action_trace: list[dict]) -> str:
        """Generate a happy path spec for a flow."""
        flow_name = flow.get("title", flow.get("name", "Unknown Flow"))
        pages = flow.get("pages", [])
        steps = flow.get("steps", [])
        happy_path = flow.get("happy_path", "")

        # Build steps from trace
        spec_steps = []
        spec_steps.append(f"1. Navigate to {base_url}")

        if steps:
            for i, step in enumerate(steps, 2):
                spec_steps.append(f"{i}. {step}")
        else:
            # Generate from pages
            for i, page in enumerate(pages, 2):
                spec_steps.append(f"{i}. Navigate to {page}")

        spec_steps.append(f"{len(spec_steps) + 1}. Verify successful completion")

        return f"""# Test: {flow_name} - Happy Path

## Description
Tests the successful completion of the {flow_name} flow.

{happy_path if happy_path else f"This test verifies that users can successfully complete the {flow_name} flow."}

## Steps
{chr(10).join(spec_steps)}

## Expected Outcome
- User successfully completes the {flow_name}
- All pages load correctly
- No errors are displayed
- User is redirected to the expected success page

## Test Data
- URL: {base_url}
"""

    def _generate_edge_cases_spec(self, flow: dict[str, Any], base_url: str, action_trace: list[dict]) -> str:
        """Generate an edge cases spec for a flow."""
        flow_name = flow.get("title", flow.get("name", "Unknown Flow"))
        edge_cases = flow.get("edge_cases", [])

        if not edge_cases:
            edge_cases = ["Empty fields", "Invalid input format", "Special characters", "Boundary values"]

        # Build test scenarios
        scenarios = []
        for i, case in enumerate(edge_cases, 1):
            scenarios.append(f"""
### Scenario {i}: {case}

**Steps:**
1. Navigate to {base_url}
2. Start the {flow_name} flow
3. {case} - enter test data
4. Attempt to proceed

**Expected Outcome:**
- Appropriate validation error is shown OR
- Field is highlighted as invalid OR
- User is prevented from proceeding with invalid data
""")

        return f"""# Test: {flow_name} - Edge Cases

## Description
Tests edge cases and validation for the {flow_name} flow.

## Scenarios
{"".join(scenarios)}

## Test Data
- Valid test data for comparison
- Invalid data formats (empty, special chars, boundary values)
- URL: {base_url}

## Expected Outcome
- All edge cases are properly validated
- Clear error messages are displayed
- Invalid data cannot be submitted
"""

    def _build_synthesis_prompt(
        self, exploration_results: dict[str, Any], discovered_flows: list[dict], base_url: str
    ) -> str:
        """Build the synthesis prompt for the agent."""
        action_trace = exploration_results.get("action_trace", [])
        happy_paths = exploration_results.get("happy_paths_found", [])
        edge_cases = exploration_results.get("edge_cases_found", [])

        flows_section = ""
        if discovered_flows:
            flows_section = "DISCOVERED FLOWS:\n"
            for flow in discovered_flows:
                flow_title = flow.get("title", flow.get("name", "Unnamed"))
                flow_desc = flow.get("happy_path", "No description")
                flows_section += f"\n- {flow_title}: {flow_desc}"
                if flow.get("pages"):
                    flows_section += f"\n  Pages: {' → '.join(flow['pages'])}"
                if flow.get("edge_cases"):
                    flows_section += f"\n  Edge Cases: {', '.join(flow['edge_cases'])}"
                if flow.get("test_ideas"):
                    flows_section += f"\n  Test Ideas: {', '.join(flow['test_ideas'][:3])}"  # Show first 3
            flows_section += "\n"

        trace_section = ""
        if action_trace:
            trace_section = "\nACTION TRACE (sample):\n"
            for action in action_trace[:15]:
                trace_section += f"- [{action.get('step', '?')}] {action.get('action', 'unknown')} {action.get('target', 'N/A')}: {action.get('outcome', 'N/A')}\n"
            if len(action_trace) > 15:
                trace_section += f"... and {len(action_trace) - 15} more actions\n"

        return f"""You are a Test Specification Synthesis Agent.

You have been given exploration results from an autonomous testing agent that explored {base_url}.

{flows_section}
{trace_section}

HAPPY PATHS FOUND: {", ".join(happy_paths) if happy_paths else "None"}
EDGE CASES FOUND: {", ".join(edge_cases) if edge_cases else "None"}

YOUR TASK:
Generate COMPREHENSIVE individual .md E2E scenario specs for all discovered flows.

REQUIREMENTS:
1. Create SEPARATE runnable specs, one file per scenario:
   - Happy path: each major user flow working correctly
   - Navigation/state transition: multi-page or state-changing paths
   - Negative/error: invalid, missing, unauthorized, failed, or empty states
   - Edge case: boundary values, unusual input, responsive/mobile
   - Accessibility/runtime regression: accessible labels, keyboard focus, console errors

2. Each spec must follow this EXACT format:
   ```markdown
   # Test: [Feature Name] - [Scenario Name]

   ## Description
   [Brief description of what this tests]

   ## Prerequisites
   [Required auth/data/state, or Fresh browser session]

   ## Steps
   1. Navigate to [URL]
   2. Click [element]
   3. Fill [field] with [value]
   4. Assert [expected outcome]

   ## Expected Outcome
   - [Expected result 1]
   - [Expected result 2]

   ## Test Data
   - [Any test data requirements]
   ```

3. IMPORTANT:
   - Prefer MULTI-PAGE flows when observed, but do not invent unsupported business behavior
   - If evidence is thin, generate conservative page/journey checks only
   - Use standard step format: Navigate, Click, Fill, Assert, Select, Check
   - Use placeholders `{{{{VAR_NAME}}}}` for secrets/passwords
   - Include specific URLs and element descriptions
   - Make specs actionable and clear
   - Do not return summary-only output

OUTPUT FORMAT (return ONLY JSON):
```json
{{
  "specs": {{
    "happy_path": {{
      "tc-001-checkout-happy-path.md": "# Test: Checkout - Happy Path\\n\\n## Description\\n..."
    }},
    "negative": {{
      "tc-002-checkout-invalid-payment.md": "# Test: Checkout - Invalid Payment\\n\\n..."
    }},
    "accessibility": {{
      "tc-003-checkout-accessible-controls.md": "# Test: Checkout - Accessible Controls\\n\\n..."
    }}
  }},
  "summary": "Generated X individual E2E scenario specs",
  "flows_covered": ["Flow 1", "Flow 2"],
  "total_specs": 0
}}
```

Now generate the specs based on the exploration results above."""

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use as a filename."""
        # Remove special characters, replace spaces with underscores
        name = re.sub(r"[^\w\s-]", "", name)
        name = re.sub(r"[-\s]+", "_", name)
        return name.lower().strip("_")

    def _load_flows_from_file(self, run_id: str) -> list[dict[str, Any]]:
        """
        Load full flows from the flows.json file created during exploration.

        Args:
            run_id: The run ID to load flows from

        Returns:
            List of discovered flows with full details, or empty list if file not found
        """
        from pathlib import Path

        # Get project root (2 levels up from this file)
        project_root = Path(__file__).parent.parent.parent
        flows_file = project_root / "runs" / run_id / "flows.json"

        if not flows_file.exists():
            print(f"   ⚠️  flows.json not found at {flows_file}")
            return []

        try:
            with open(flows_file) as f:
                data = json.load(f)
                flows = data.get("flows", [])
                print(f"   ✅ Loaded {len(flows)} flows from {flows_file}")
                return flows
        except Exception as e:
            print(f"   ❌ Error loading flows.json: {e}")
            return []

    def _infer_test_ideas(self, exploration_results: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Infer additional test ideas from exploration results.

        Analyzes what was tested and suggests what wasn't tested.
        """
        ideas = []

        exploration_results.get("discovered_flows", [])
        action_trace = exploration_results.get("action_trace", [])

        # Check for common untested scenarios
        tested_urls = set()
        for action in action_trace:
            target = action.get("target", "")
            if "navigate" in target.lower() or "url" in target.lower():
                tested_urls.add(target)

        # Ideas based on coverage gaps
        ideas.append(
            {
                "category": "coverage",
                "idea": "Test all navigation items",
                "priority": "medium",
                "rationale": "Ensure all menu items and links work",
            }
        )

        ideas.append(
            {
                "category": "error_handling",
                "idea": "Test error states and validation",
                "priority": "high",
                "rationale": "Verify proper error messages and validation",
            }
        )

        return ideas

    def _register_spec_in_db(self, filepath: Path, project_id: str | None = None):
        """
        Register a generated spec in the database with project association.

        This ensures the spec appears in the correct project's spec list
        in the web dashboard.

        Args:
            filepath: Full path to the spec file
            project_id: Optional project ID to associate the spec with
        """
        try:
            # Get the specs directory to calculate relative path
            project_root = Path(__file__).parent.parent.parent
            specs_dir = project_root / "specs"

            # Calculate spec_name as relative path from specs_dir
            try:
                spec_name = str(filepath.relative_to(specs_dir))
            except ValueError:
                # filepath is not under specs_dir, use filename only
                spec_name = filepath.name

            # Import database dependencies
            from sqlmodel import Session

            from orchestrator.api.db import engine
            from orchestrator.api.models_db import SpecMetadata as DBSpecMetadata
            from orchestrator.api.models_db import get_spec_metadata

            with Session(engine) as session:
                # Check if spec already exists
                existing = get_spec_metadata(session, spec_name, project_id)
                if not existing:
                    # Create new metadata record
                    meta = DBSpecMetadata(spec_name=spec_name, project_id=project_id, tags_json="[]")
                    session.add(meta)
                    print(f"   ✅ Registered spec: {spec_name} (project: {project_id or 'default'})")
                else:
                    # Update project association if different
                    if existing.project_id != project_id:
                        existing.project_id = project_id
                        print(f"   🔄 Updated spec project: {spec_name} -> {project_id or 'default'}")
                session.commit()

        except Exception as e:
            # Don't fail the entire synthesis if DB registration fails
            print(f"   ⚠️  Failed to register spec {filepath.name} in database: {e}")
