"""
Coverage Analyzer Workflow - Analyzes test coverage and identifies gaps
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add utils to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load Claude credentials
from load_env import setup_claude_env

setup_claude_env()

import logging

from claude_agent_sdk import ClaudeAgentOptions, query

from utils.json_utils import extract_json_from_markdown

logger = logging.getLogger(__name__)


class CoverageAnalyzer:
    """Analyzes application coverage and identifies gaps"""

    def __init__(self, schema_path: str = "schemas/coverage_report.schema.json"):
        self.schema_path = schema_path

    async def analyze_coverage(
        self, url: str, existing_tests: list[dict[str, Any]] | None = None, use_browser: bool = True
    ) -> dict:
        """
        Analyze test coverage for a given URL.

        Args:
            url: URL to analyze
            existing_tests: Optional list of existing test patterns
            use_browser: Whether to use Playwright to discover elements

        Returns:
            Coverage report with gaps and suggestions
        """
        logger.info(f"Analyzing coverage for {url}...")

        if use_browser:
            # Use Playwright MCP to discover elements
            report = await self._analyze_with_browser(url, existing_tests)
        else:
            # Use spec-based analysis
            report = await self._analyze_from_spec(url, existing_tests)

        logger.info("Coverage analysis complete")
        logger.info(f"   Elements: {report.get('coverage_summary', {}).get('total_elements', 0)}")
        logger.info(f"   Coverage: {report.get('coverage_summary', {}).get('coverage_percentage', 0):.1f}%")

        return report

    async def _analyze_with_browser(self, url: str, existing_tests: list[dict[str, Any]] | None = None) -> dict:
        """Analyze coverage using Playwright to discover elements"""

        # Build prompt for the agent
        prompt = self._build_browser_prompt(url, existing_tests)

        # Query the coverage analyzer agent with Playwright access
        report = await self._query_coverage_agent(prompt=prompt, allowed_tools=["Read", "mcp__playwright__*"])

        # Add metadata
        report["analyzed_at"] = datetime.now().isoformat()
        report["analysis_method"] = "browser_discovery"

        return report

    async def _analyze_from_spec(self, url: str, existing_tests: list[dict[str, Any]] | None = None) -> dict:
        """Analyze coverage from existing test specifications"""

        # Build prompt for the agent
        prompt = self._build_spec_prompt(url, existing_tests)

        # Query the coverage analyzer agent (read-only)
        report = await self._query_coverage_agent(prompt=prompt, allowed_tools=["Read"])

        # Add metadata
        report["analyzed_at"] = datetime.now().isoformat()
        report["analysis_method"] = "spec_analysis"

        return report

    def _build_browser_prompt(self, url: str, existing_tests: list[dict[str, Any]] | None) -> str:
        """Build prompt for browser-based analysis"""
        prompt = f"""You are a test coverage analyst. Analyze the application at {url} and identify coverage gaps.

INSTRUCTIONS:
1. Use Playwright to navigate to {url}
2. Take a snapshot to see the page structure
3. Identify all interactive elements (buttons, inputs, links, forms, etc.)
4. For each element, determine if it's likely tested based on the existing test patterns below
5. Generate a comprehensive coverage report

EXISTING TEST PATTERNS:
"""
        if existing_tests:
            for test in existing_tests:
                prompt += f"\n- {test.get('action', '')} on {test.get('target', '')}"
        else:
            prompt += "\n(No existing test patterns provided - assume no coverage)"

        prompt += f"""

After analyzing the page, output ONLY the coverage report JSON in a code block.
Use this format:

```json
{{
  "url": "{url}",
  "page_title": "Page title from the page",
  "discovered_elements": [
    {{
      "element_type": "button",
      "selector": {{"type": "role", "value": "button", "name": "Submit"}},
      "text": "Submit",
      "is_tested": false,
      "test_coverage": "none"
    }}
  ],
  "coverage_summary": {{
    "total_elements": 0,
    "tested_elements": 0,
    "coverage_percentage": 0.0,
    "breakdown": {{}}
  }},
  "coverage_gaps": [],
  "suggested_tests": []
}}
```

Begin your analysis now.
"""
        return prompt

    def _build_spec_prompt(self, url: str, existing_tests: list[dict[str, Any]] | None) -> str:
        """Build prompt for spec-based analysis"""
        prompt = f"""You are a test coverage analyst. Based on the existing test patterns, identify likely coverage gaps for {url}.

EXISTING TEST PATTERNS:
"""
        if existing_tests:
            for test in existing_tests:
                prompt += f"\n- {test.get('action', '')} on {test.get('target', '')}"
        else:
            prompt += "\n(No existing test patterns provided)"

        prompt += f"""

Based on common web application patterns for {url}, suggest:
1. Likely untested elements
2. Missing test scenarios (negative tests, edge cases)
3. Suggested test cases

Output ONLY the coverage report JSON in a code block.
"""
        return prompt

    async def _query_coverage_agent(self, prompt: str, allowed_tools: list[str]) -> dict:
        """Query the coverage analyzer agent"""
        try:
            async for message in query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    allowed_tools=allowed_tools,
                    setting_sources=["project"],
                ),
            ):
                if hasattr(message, "result"):
                    result = message.result
                    report = extract_json_from_markdown(result)

                    # Ensure required fields exist
                    if "coverage_summary" not in report:
                        report["coverage_summary"] = {
                            "total_elements": 0,
                            "tested_elements": 0,
                            "coverage_percentage": 0.0,
                        }

                    if "coverage_gaps" not in report:
                        report["coverage_gaps"] = []

                    if "suggested_tests" not in report:
                        report["suggested_tests"] = []

                    if "discovered_elements" not in report:
                        report["discovered_elements"] = []

                    return report

        except Exception as e:
            raise RuntimeError(f"Failed to query coverage analyzer agent: {e}")

        raise RuntimeError("No valid response from coverage analyzer agent")


# Convenience functions
async def analyze_url(url: str, existing_tests: list[dict[str, Any]] | None = None, use_browser: bool = True) -> dict:
    """
    Analyze coverage for a URL.

    Args:
        url: URL to analyze
        existing_tests: Optional list of existing test patterns
        use_browser: Whether to use browser for element discovery

    Returns:
        Coverage report
    """
    analyzer = CoverageAnalyzer()
    return await analyzer.analyze_coverage(url, existing_tests, use_browser)


async def main():
    """Test the coverage analyzer"""
    if len(sys.argv) < 2:
        print("Usage: python coverage_analyzer.py <url> [--no-browser]")
        sys.exit(1)

    url = sys.argv[1]
    use_browser = "--no-browser" not in sys.argv

    try:
        report = await analyze_url(url, use_browser=use_browser)

        # Save the report
        output_dir = Path("runs") / datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir.mkdir(parents=True, exist_ok=True)

        import json

        output_file = output_dir / "coverage_report.json"
        with open(output_file, "w") as f:
            json.dump(report, f, indent=2)

        logger.info(f"Coverage report saved to: {output_file}")

        # Print summary
        logger.info("Coverage Summary:")
        summary = report.get("coverage_summary", {})
        logger.info(f"   Total Elements: {summary.get('total_elements', 0)}")
        logger.info(f"   Tested Elements: {summary.get('tested_elements', 0)}")
        logger.info(f"   Coverage: {summary.get('coverage_percentage', 0):.1f}%")
        logger.info(f"   Gaps Identified: {len(report.get('coverage_gaps', []))}")
        logger.info(f"   Tests Suggested: {len(report.get('suggested_tests', []))}")

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    from orchestrator.logging_config import setup_logging

    setup_logging()
    asyncio.run(main())
