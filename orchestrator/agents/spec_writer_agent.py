from typing import Any

from utils.json_utils import extract_json_from_markdown

from .base_agent import BaseAgent


class SpecWriterAgent(BaseAgent):
    """
    Agent that generates Playwright Test Specs (markdown) from:
    1. A URL (original mode - explores and generates spec)
    2. Exploration results (from_exploration mode - converts to specs)
    """

    async def run(self, config: dict[str, Any]) -> dict[str, Any]:
        mode = config.get("mode", "url")

        if mode == "from_exploration":
            return await self._run_from_exploration(config)
        else:
            return await self._run_from_url(config)

    async def _run_from_url(self, config: dict[str, Any]) -> dict[str, Any]:
        """Original mode: Generate spec from URL"""
        url = config.get("url")
        instructions = config.get("instructions", "Generate a test spec for the main feature of this page.")

        print(f"✍️ Starting Spec Writer Agent (URL mode) on {url}")

        prompt = f"""You are a Test Specification Writer.
Target URL: {url}
Instructions: {instructions}

GOAL:
1. Navigate to the URL.
2. Understand the page's purpose.
3. Generate a high-quality Markdown Test Specification (like the examples in specs/ directory).

REQUIREMENTS:
- The spec must use standard steps: Navigate, Click, Fill, Assert.
- Use placeholders `{{{{VAR_NAME}}}}` for secrets (like passwords).
- Structure:
  # Test: [Title]
  ## Description
  ...
  ## Steps
  1. ...
  2. ...

Step 1: Navigate to {url} to understand the page.
Step 2: Generate the markdown spec.

Return the result as JSON:
```json
{{
  "spec_title": "...",
  "spec_content": "# Test: ... (full markdown content)...",
  "summary": "Generated spec for login page."
}}
```
"""

        result = await self._query_agent(prompt)

        try:
            data = extract_json_from_markdown(result)
            return data
        except Exception:
            # If agent just returned markdown, wrap it
            return {"spec_content": str(result), "summary": "Agent returned raw content."}

    async def _run_from_exploration(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        New mode: Generate comprehensive .md specs from ChromeExploratoryAgent results.
        Creates separate specs for happy paths and edge cases.
        """
        exploration_results = config.get("exploration_results")
        target_url = config.get("url", "")

        if not exploration_results:
            return {"summary": "No exploration results provided", "error": "exploration_results is required in config"}

        print("✍️ Starting Spec Writer Agent (Exploration mode)")
        print(f"   Discovered flows: {len(exploration_results.get('discovered_flows', []))}")

        # Format exploration results for the prompt
        exploration_summary = self._format_exploration_results(exploration_results)

        prompt = f"""You are an E2E Test Specification Writer.

You have been given exploration results from an autonomous testing agent that explored {target_url}.

EXPLORATION RESULTS:
{exploration_summary}

YOUR TASK:
Generate COMPREHENSIVE .md test specs for all discovered flows.

REQUIREMENTS:
1. Create SEPARATE specs for:
   - HAPPY PATH tests: Each major user flow working correctly
   - EDGE CASE tests: Boundary conditions, negative scenarios

2. Each spec should follow this structure:
   ```markdown
   # Test: [Feature Name] - [Happy Path / Edge Cases]

   ## Description
   [Brief description of what this tests]

   ## Steps
   1. Navigate to [URL]
   2. Click [element]
   3. Fill [field] with [value]
   4. Assert [expected outcome]

   ## Expected Outcome
   - [Expected result 1]
   - [Expected result 2]
   ```

3. IMPORTANT:
   - Focus on MULTI-PAGE flows (not single page tests)
   - Use standard step format: Navigate, Click, Fill, Assert, Select, Check, etc.
   - Use placeholders `{{{{VAR_NAME}}}}` for secrets/passwords
   - Include both happy path and edge case scenarios

4. For happy paths: Test the complete successful user journey
5. For edge cases: Test boundary values, empty fields, invalid inputs, etc.

OUTPUT FORMAT (return ONLY JSON):
```json
{{
  "specs": {{
    "happy_path": {{
      "[filename].md": "Full spec content here...",
      "[another_filename].md": "Full spec content here..."
    }},
    "edge_cases": {{
      "[filename].md": "Full spec content here...",
      "[another_filename].md": "Full spec content here..."
    }}
  }},
  "summary": "Generated X happy path specs and Y edge case specs covering Z flows",
  "total_specs": 0,
  "flows_covered": ["Flow 1", "Flow 2"]
}}
```

Now generate the specs based on the exploration results above."""

        result = await self._query_agent(prompt)

        try:
            data = extract_json_from_markdown(result)
            # Add metadata
            data["source_url"] = target_url
            data["generated_at"] = exploration_results.get("elapsed_time_seconds", "unknown")
            return data
        except Exception as e:
            return {"summary": f"Failed to parse generated specs: {str(e)}", "raw_output": str(result), "error": str(e)}

    def _format_exploration_results(self, results: dict[str, Any]) -> str:
        """Format exploration results for the prompt."""
        lines = []

        # Summary
        lines.append(f"Summary: {results.get('summary', 'N/A')}")
        lines.append("")

        # Discovered flows
        flows = results.get("discovered_flows", [])
        if flows:
            lines.append("DISCOVERED FLOWS:")
            for i, flow in enumerate(flows, 1):
                lines.append(f"\n{i}. {flow.get('name', 'Unnamed Flow')}")
                if flow.get("pages"):
                    lines.append(f"   Pages: {' → '.join(flow['pages'])}")
                if flow.get("steps"):
                    lines.append(f"   Steps: {' → '.join(flow['steps'])}")
                if flow.get("happy_path"):
                    lines.append(f"   Happy Path: {flow['happy_path']}")
                if flow.get("edge_cases"):
                    lines.append(f"   Edge Cases: {', '.join(flow['edge_cases'])}")
            lines.append("")

        # Action trace (abbreviated)
        action_trace = results.get("action_trace", [])
        if action_trace:
            lines.append("ACTION TRACE (sample):")
            for action in action_trace[:20]:  # Limit to first 20
                step = action.get("step", "?")
                act = action.get("action", "unknown")
                target = action.get("target", "N/A")
                outcome = action.get("outcome", "N/A")
                lines.append(f"  [{step}] {act} {target} → {outcome}")
            if len(action_trace) > 20:
                lines.append(f"  ... and {len(action_trace) - 20} more actions")
            lines.append("")

        # Happy paths found
        happy_paths = results.get("happy_paths_found", [])
        if happy_paths:
            lines.append(f"HAPPY PATHS FOUND: {', '.join(happy_paths)}")
            lines.append("")

        # Edge cases found
        edge_cases = results.get("edge_cases_found", [])
        if edge_cases:
            lines.append(f"EDGE CASES FOUND: {', '.join(edge_cases)}")
            lines.append("")

        return "\n".join(lines)
