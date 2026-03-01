"""
Exporter Workflow - Converts execution traces to Playwright test code
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# Load Claude credentials
from load_env import setup_claude_env

setup_claude_env()

from claude_agent_sdk import ClaudeAgentOptions, query

from utils.json_utils import extract_json_from_markdown, save_json, validate_json_schema

# Memory system integration
try:
    from memory import get_memory_manager

    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False


class Exporter:
    """Converts test execution traces into Playwright test code"""

    def __init__(
        self, schema_path: str = "schemas/export.schema.json", use_memory: bool = True, project_id: str | None = None
    ):
        self.schema_path = schema_path
        self.use_memory = use_memory and MEMORY_AVAILABLE
        self.project_id = project_id

        # Initialize memory manager if available
        self.memory_manager = None
        if self.use_memory:
            try:
                self.memory_manager = get_memory_manager(project_id=project_id)
                logger.info("[Memory] Exporter initialized with memory system")
            except Exception as e:
                logger.warning(f"[Memory] System unavailable: {e}")
                self.use_memory = False
        else:
            logger.info("[Memory] Disabled for this run")

    async def export(self, run: dict, test_dir: str = "tests/generated") -> dict:
        """
        Convert a run trace to Playwright test code.

        Args:
            run: Execution trace from Operator
            test_dir: Directory to save test files

        Returns:
            Dict containing export result (test path, code, etc.)
        """
        logger.info(f"Generating test code for: {run.get('testName', 'Unnamed')}")
        logger.info(f"   Steps to convert: {len(run.get('steps', []))}")

        # Build the export prompt
        prompt = self._build_export_prompt(run)

        # Query the agent
        export_result = await self._query_agent(prompt)

        # Validate against schema
        logger.info("Validating export against schema...")
        validate_json_schema(export_result, self.schema_path)

        # Determine test file path
        test_path = export_result.get("testFilePath")

        # OVERRIDE: If we know the original spec filename, use it to generate a deterministic test filename
        # This prevents collisions when users copy specs but don't change the H1 header.
        if run.get("specFileName"):
            import re

            spec_name = run.get("specFileName")
            # Remove extension
            stem = spec_name.rsplit(".", 1)[0]
            # Slugify: Lowercase, replace non-alphanumeric with hyphens
            slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
            test_path = f"{test_dir}/{slug}.spec.ts"
            export_result["testFilePath"] = test_path

        # Remove test_dir prefix if already in the path
        if test_path.startswith(test_dir):
            test_path = test_path
        elif not test_path.startswith("/") and not test_path.startswith("./"):
            test_path = str(Path(test_dir) / test_path)

        # Save the test file
        test_file = Path(test_path)
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(export_result["code"])

        logger.info("Test code generated")
        logger.info(f"   File: {test_path}")
        logger.info(f"   Dependencies: {', '.join(export_result.get('dependencies', []))}")

        if export_result.get("notes"):
            logger.info("   Notes:")
            for note in export_result["notes"]:
                logger.info(f"     - {note}")

        # Store patterns to memory if available
        if self.use_memory and self.memory_manager:
            await self._store_patterns_from_run(run)
        elif self.use_memory:
            logger.warning("[Memory] Memory enabled but manager not initialized")

        return export_result

    def _parse_playwright_selector(self, selector: str) -> dict[str, str]:
        """
        Parse Playwright selector string to extract structured metadata.

        Examples:
          "page.getByRole('button', { name: 'Sign In' })"
            → {"strategy": "role", "element_role": "button", "element_name": "Sign In"}

          "page.getByLabel('Email')"
            → {"strategy": "label", "element_label": "Email"}

          "page.locator('.btn-primary')"
            → {"strategy": "locator", "css_selector": ".btn-primary"}
        """
        import re

        result = {"strategy": "unknown"}

        if not selector or not isinstance(selector, str):
            return result

        # getByRole('role', { name: 'Name' }) or getByRole('role', { name: /regex/ })
        role_match = re.search(r"getByRole\(['\"](\w+)['\"](?:,\s*\{[^}]*name:\s*['\"/]([^'\"\/]+))?", selector)
        if role_match:
            result["strategy"] = "role"
            result["element_role"] = role_match.group(1)
            if role_match.group(2):
                result["element_name"] = role_match.group(2)
            return result

        # getByLabel('Label')
        label_match = re.search(r"getByLabel\(['\"]([^'\"]+)['\"]", selector)
        if label_match:
            result["strategy"] = "label"
            result["element_label"] = label_match.group(1)
            return result

        # getByText('Text')
        text_match = re.search(r"getByText\(['\"]([^'\"]+)['\"]", selector)
        if text_match:
            result["strategy"] = "text"
            result["element_text"] = text_match.group(1)
            return result

        # getByPlaceholder('Placeholder')
        placeholder_match = re.search(r"getByPlaceholder\(['\"]([^'\"]+)['\"]", selector)
        if placeholder_match:
            result["strategy"] = "placeholder"
            result["element_placeholder"] = placeholder_match.group(1)
            return result

        # getByTestId('test-id')
        testid_match = re.search(r"getByTestId\(['\"]([^'\"]+)['\"]", selector)
        if testid_match:
            result["strategy"] = "testid"
            result["element_testid"] = testid_match.group(1)
            return result

        # locator('selector')
        locator_match = re.search(r"locator\(['\"]([^'\"]+)['\"]", selector)
        if locator_match:
            result["strategy"] = "locator"
            result["css_selector"] = locator_match.group(1)
            return result

        # goto('url')
        goto_match = re.search(r"goto\(['\"]([^'\"]+)['\"]", selector)
        if goto_match:
            result["strategy"] = "goto"
            result["url"] = goto_match.group(1)
            return result

        return result

    async def _store_patterns_from_run(self, run: dict) -> None:
        """
        Store successful test patterns from the run to memory.

        Args:
            run: Execution trace with steps
        """
        if not self.memory_manager:
            logger.warning("[Memory] Manager not available for pattern storage")
            return

        test_name = run.get("testName", "unknown")
        steps = run.get("steps", [])
        spec_file = run.get("specFileName", "")

        logger.info(f"[Memory] Processing {len(steps)} steps from '{test_name}'")

        # Track current page URL from navigation steps
        current_page_url = None

        stored_count = 0
        skipped_count = 0
        for step in steps:
            # Update page URL when we navigate
            if step.get("action") == "navigate":
                current_page_url = step.get("target")

            # Only store successful steps
            # Check both "success" (boolean) and "result" (string "success")
            is_success = step.get("success") or step.get("result") == "success"
            if is_success and step.get("action") and step.get("target"):
                try:
                    # Get the RAW selector string (the actual Playwright code)
                    playwright_selector = step.get("selector", "")
                    selector_type = step.get("selectorType", "unknown")

                    # If selector is a dict, extract the value
                    if isinstance(playwright_selector, dict):
                        playwright_selector = playwright_selector.get("value", "")

                    # Parse selector to extract structured metadata
                    parsed = self._parse_playwright_selector(playwright_selector)

                    # Build selector dict with parsed metadata
                    selector = {
                        "type": selector_type,
                        "value": playwright_selector,  # Full Playwright code
                        **parsed,  # strategy, element_role, element_name, etc.
                    }

                    self.memory_manager.store_test_pattern(
                        test_name=test_name,
                        step_number=step.get("stepNumber", 0),
                        action=step.get("action"),
                        target=step.get("target"),
                        selector=selector,
                        success=True,
                        duration_ms=int(step.get("duration", 0) * 1000) if step.get("duration") else 0,
                        metadata={
                            "page_url": current_page_url,
                            "playwright_selector": playwright_selector,  # Store explicitly
                            "screenshot": step.get("screenshot"),
                            "spec_file": spec_file,
                        },
                    )
                    stored_count += 1
                except Exception as e:
                    # Log errors for debugging
                    logger.error(f"[Memory] Failed to store pattern: {e}")
            else:
                skipped_count += 1

        if stored_count > 0:
            logger.info(
                f"[Memory] Stored {stored_count} patterns from '{test_name}' (skipped {skipped_count} unsuccessful)"
            )
            # Save memory to disk
            try:
                self.memory_manager.save()
                logger.info("[Memory] Saved to disk")
            except Exception as e:
                logger.error(f"[Memory] Save failed: {e}")
        else:
            logger.info("[Memory] No patterns to store (0 successful steps)")

    def _build_export_prompt(self, run: dict) -> str:
        """Build the prompt for the agent"""
        import json

        prompt = (
            """You are a test code generation expert. Convert this test execution trace into production-ready Playwright test code in TypeScript.

CRITICAL INSTRUCTIONS:
1. Follow Playwright best practices
2. Use role-based selectors (getByRole, getByLabel, getByText)
3. Group related steps with test.step()
4. Add helpful comments
5. Output ONLY valid JSON in a ```json code block

EXECUTION TRACE:
```json
"""
            + json.dumps(run, indent=2)
            + """
```

CODE STYLE REQUIREMENTS:
- Use async/await properly
- Use getByRole() for buttons, links, headings
- Use getByLabel() for form inputs
- Use getByText() for text content
- Add proper assertions with expect()
- **VISUAL REGRESSION**: If a step implies verifying layout, "check visual", or "screenshot", use `await expect(page).toHaveScreenshot('name.png')`.
- Group steps with test.step() when logical
- Make code readable and maintainable

OUTPUT FORMAT:
```json
{
  "testFilePath": "tests/generated/test-name.spec.ts",
  "code": "import { test, expect } from '@playwright/test';\\n\\ntest.describe(...",
  "dependencies": ["@playwright/test"],
  "notes": ["Brief note about the code"]
}
```

SELECTOR MAPPING:
- **CRITICAL**: If the execution trace has a "selector" field, USE IT EXACTLY. Do not invent a new one.
- Navigate: page.goto('URL')
- Manual Fallback (only if selector missing):
  - Button: page.getByRole('button', { name: '...' })
  - Field: page.getByLabel('...')
  - Text: page.getByText('...')

CREDENTIAL HANDLING:
- **CRITICAL**: For credentials (emails, passwords, secrets), use `process.env.VAR_NAME!` format
- If you see `process.env.APP_LOGIN_EMAIL!` in the trace, keep it exactly
- If you see a placeholder like `[APP_LOGIN_EMAIL]`, convert to `process.env.APP_LOGIN_EMAIL!`
- Example: `await page.fill('...', process.env.APP_LOGIN_PASSWORD!);`
- For non-sensitive values (URLs, button text, etc.), use the actual values from the trace

Now convert the execution trace to Playwright code and return the result as JSON. No other text.
"""
        )

        return prompt

    async def _query_agent(self, prompt: str) -> dict:
        """Query the agent"""
        try:
            async for message in query(
                prompt=prompt,
                options=ClaudeAgentOptions(allowed_tools=["Write"], setting_sources=["project"]),
            ):
                # Log tool uses for real-time feedback
                if hasattr(message, "type"):
                    if message.type == "tool_use":
                        tool_name = getattr(message, "name", "unknown")
                        logger.info(f"   {tool_name}...")

                if hasattr(message, "result"):
                    result = message.result
                    # Extract JSON from markdown
                    export_data = extract_json_from_markdown(result)
                    return export_data

        except Exception as e:
            error_msg = str(e)
            if "cancel scope" not in error_msg.lower():
                raise RuntimeError(f"Failed to export test: {e}")


# Convenience function for testing
async def export_from_file(run_path: str, test_dir: str = "tests/generated") -> dict:
    """
    Export a test from a run trace file.

    Args:
        run_path: Path to the run JSON file
        test_dir: Directory to save test files

    Returns:
        Export result
    """
    # Get project_id from environment
    project_id = os.environ.get("MEMORY_PROJECT_ID")
    memory_enabled = os.environ.get("MEMORY_ENABLED", "true").lower() == "true"

    exporter = Exporter(use_memory=memory_enabled, project_id=project_id)

    run_file = Path(run_path)
    if not run_file.exists():
        raise FileNotFoundError(f"Run file not found: {run_path}")

    run = json.loads(run_file.read_text())

    return await exporter.export(run, test_dir)


# Test the exporter
async def main():
    """Test the exporter with a real run"""
    if len(sys.argv) < 2:
        logger.error("Usage: python exporter.py <run.json>")
        sys.exit(1)

    run_path = sys.argv[1]

    try:
        export_result = await export_from_file(run_path)

        # Save export metadata
        export_file = Path(run_path).parent / "export.json"
        save_json(export_result, str(export_file))

        logger.info(f"Export metadata saved to: {export_file}")

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    from orchestrator.logging_config import setup_logging

    setup_logging()
    asyncio.run(main())
