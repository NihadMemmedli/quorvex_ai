"""
Native Generator Workflow - Converts Test Specs to Playwright Code

This workflow uses the Playwright Test Generator agent to:
1. Read a markdown test spec
2. Execute each step in a live browser to validate selectors
3. Generate the final Playwright TypeScript test code
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Add orchestrator to path
sys.path.append(str(Path(__file__).parent.parent.parent))

# Store project base directory BEFORE any chdir() calls
# This ensures tests_dir always resolves to /app/tests/generated/ in Docker
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load Claude credentials and SDK
from orchestrator.load_env import setup_claude_env

setup_claude_env()

# Use run-specific config directory if set (for parallel execution isolation)
config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
if config_dir:
    os.chdir(config_dir)

from orchestrator.utils.agent_runner import AgentRunner, build_allowed_tools, get_default_timeout


class NativeGenerator:
    """
    Playwright Test Generator that converts specs to executable test code.

    Flow:
    1. Read the markdown spec file
    2. Parse test cases from the spec
    3. For each test case:
       - Call generator_setup_page
       - Execute steps with browser_* tools
       - Read the log with generator_read_log
       - Write the test with generator_write_test
    """

    def __init__(self):
        # Use absolute path to project's tests directory (not relative to cwd)
        # This fixes Docker issue where cwd changes to run directory
        self.tests_dir = BASE_DIR / "tests" / "generated"
        self.tests_dir.mkdir(parents=True, exist_ok=True)

    async def generate_test(
        self, spec_path: str, target_url: str | None = None, output_name: str | None = None
    ) -> Path:
        """
        Generate a Playwright test from a markdown spec.

        Args:
            spec_path: Path to the markdown spec file
            target_url: URL of the application to test (optional)
            output_name: Override for output test file name (without extension)

        Returns:
            Path to the generated test file
        """
        spec_path_obj = Path(spec_path)
        if not spec_path_obj.exists():
            raise FileNotFoundError(f"Spec file not found: {spec_path}")

        spec_content = spec_path_obj.read_text()
        # Use provided output_name or fall back to spec file stem
        spec_name = output_name if output_name else spec_path_obj.stem

        # Determine output path
        output_path = self.tests_dir / f"{spec_name}.spec.ts"

        logger.info(f"Generating test from: {spec_path}")
        logger.info(f"   Output: {output_path}")

        # Build prompt in the format expected by playwright-test-generator agent
        prompt = self._build_generator_prompt(
            spec_path=spec_path,
            spec_content=spec_content,
            spec_name=spec_name,
            output_path=str(output_path),
            target_url=target_url,
        )

        # Invoke the Generator Agent
        logger.info("Invoking Playwright Generator Agent...")
        result = await self._query_generator_agent(prompt)

        # Check if the agent created the file
        if output_path.exists():
            logger.info(f"Test generated: {output_path}")
            return output_path

        # Fallback: If agent returned code but didn't write it
        if result and ("test(" in result or "test.describe" in result):
            logger.info(f"Saving generated code to: {output_path}")
            output_path.write_text(result)
            return output_path

        logger.warning(f"Generator finished but test file not found at: {output_path}")
        return output_path

    def _extract_credential_placeholders(self, spec_content: str) -> dict:
        """Extract {{VAR}} placeholders from spec and resolve their values."""
        import re

        placeholders = {}
        matches = re.findall(r"\{\{([^}]+)\}\}", spec_content)
        for var_name in set(matches):
            env_val = os.environ.get(var_name)
            if env_val:
                placeholders[var_name] = env_val
            else:
                logger.warning(f"Environment variable {var_name} not found!")
        return placeholders

    def _build_generator_prompt(
        self, spec_path: str, spec_content: str, spec_name: str, output_path: str, target_url: str | None
    ) -> str:
        """Build prompt matching the playwright-test-generator agent format."""

        # Extract test suite and first test case from spec for the expected format
        test_suite = spec_name.replace("prd-", "").replace("-", " ").title()

        url_section = ""
        if target_url:
            url_section = f"\nTarget URL: {target_url}"

        # Extract and resolve credential placeholders
        credentials = self._extract_credential_placeholders(spec_content)
        credentials_section = ""
        if credentials:
            cred_lines = []
            for var_name, value in credentials.items():
                cred_lines.append(
                    f"- `{{{{{var_name}}}}}` → Use value: `{value}` during execution, but write `process.env.{var_name}!` in generated code"
                )
            credentials_section = f"""

## Credentials (IMPORTANT)
The spec contains credential placeholders. During browser execution, use the ACTUAL values shown below.
In the generated code, use `process.env.VAR_NAME!` instead of hardcoding.

{chr(10).join(cred_lines)}
"""

        prompt = f"""You are the Playwright Test Generator.

Context: User wants to generate automated tests from the following test plan.

<test-suite>{test_suite}</test-suite>
<test-file>{output_path}</test-file>
<seed-file>tests/seed.spec.ts</seed-file>
{url_section}
{credentials_section}
<spec-content file="{spec_path}">
{spec_content}
</spec-content>

## Instructions

For each test case in the spec:
1. Call `generator_setup_page` to initialize the browser
2. **IMMEDIATELY** call `browser_navigate` to go to the target URL from the spec
   (The default page is example.com - NOT your target. Navigate explicitly!)
3. Execute each step interactively using `browser_*` tools to validate selectors
4. Retrieve the execution log using `generator_read_log`
5. Write the final test using `generator_write_test`

## Dialog Handling (CRITICAL)
When browser dialogs appear (alerts, confirms, or "Leave site?" beforeunload dialogs):
- Use `browser_handle_dialog` with `accept: true` IMMEDIATELY
- For "Leave site?" dialogs: Always accept to continue navigation
- After handling a dialog, take a `browser_snapshot` to verify page state
- In generated code, include dialog handler for forms/editors:
  ```typescript
  page.on('dialog', async dialog => await dialog.accept());
  ```

## Code Generation Requirements

- Generate complete Playwright TypeScript test code
- Use `test.describe('{test_suite}', () => {{ ... }})` to group all tests
- Each test case from the spec becomes a `test('...', async ({{ page }}) => {{ ... }})`
- Include comments with the step text before each action
- Use the EXACT selectors discovered during browser execution
- Add proper `await` statements
- Use `expect()` for assertions
- Follow best practices from the seed file
- **CRITICAL**: For credentials with `{{{{VAR_NAME}}}}` placeholders, use `process.env.VAR_NAME!` in code (NOT hardcoded values)

## Cleanup (IMPORTANT)
After writing the test file, call `browser_close` to close the browser before finishing.

## Output

Save the generated test file to: {output_path}
"""
        return prompt

    # Playwright MCP tools matching .claude/agents/playwright-test-generator.md
    GENERATOR_MCP_TOOLS = [
        "browser_click",
        "browser_close",
        "browser_drag",
        "browser_evaluate",
        "browser_file_upload",
        "browser_handle_dialog",
        "browser_hover",
        "browser_navigate",
        "browser_press_key",
        "browser_select_option",
        "browser_snapshot",
        "browser_type",
        "browser_verify_element_visible",
        "browser_verify_list_visible",
        "browser_verify_text_visible",
        "browser_verify_value",
        "browser_wait_for",
        "generator_read_log",
        "generator_setup_page",
        "generator_write_test",
    ]

    async def _query_generator_agent(self, prompt: str) -> str:
        """
        Query the Playwright Generator agent using the unified AgentRunner.

        Uses explicit timeout and comprehensive logging.
        """
        timeout = int(os.environ.get("GENERATOR_TIMEOUT_SECONDS", get_default_timeout()))

        logger.info(f"Timeout: {timeout}s ({timeout // 60} minutes)")

        runner = AgentRunner(
            timeout_seconds=timeout,
            allowed_tools=build_allowed_tools(
                ["Glob", "Grep", "Read", "LS"],
                self.GENERATOR_MCP_TOOLS,
            ),
            log_tools=True,
        )

        result = await runner.run(prompt)

        # Log diagnostics
        logger.info(
            f"Agent stats: {result.messages_received} messages, "
            f"{len(result.tool_calls)} tool calls, "
            f"{result.duration_seconds:.1f}s"
        )

        if result.timed_out:
            logger.warning("Agent timed out")

        if not result.success and result.error:
            logger.warning(f"Agent error: {result.error}")

        return result.output

    async def generate_all_tests(self, specs_dir: str = "specs", target_url: str | None = None) -> list[Path]:
        """
        Generate tests for all specs in a directory.

        Args:
            specs_dir: Directory containing spec files
            target_url: URL of the application to test (optional)

        Returns:
            List of paths to generated test files
        """
        # Find all PRD-based specs
        specs = list(Path(specs_dir).glob("prd-*.md"))

        logger.info(f"Found {len(specs)} specs to generate")

        results = []
        for spec in specs:
            logger.info("=" * 60)
            try:
                path = await self.generate_test(str(spec), target_url=target_url)
                results.append(path)
            except Exception as e:
                logger.error(f"Failed to generate test for {spec}: {e}")

        return results


if __name__ == "__main__":
    from orchestrator.logging_config import setup_logging

    setup_logging()

    import argparse

    parser = argparse.ArgumentParser(description="Generate Playwright tests from specs")
    parser.add_argument("--spec", help="Specific spec file to generate")
    parser.add_argument("--all", action="store_true", help="Generate all prd-*.md specs")
    parser.add_argument("--url", help="Target URL for browser validation (optional)")
    args = parser.parse_args()

    async def main():
        generator = NativeGenerator()
        if args.spec:
            await generator.generate_test(args.spec, target_url=args.url)
        elif args.all:
            await generator.generate_all_tests(target_url=args.url)
        else:
            logger.info("Usage: --spec <path> or --all")

    try:
        asyncio.run(main())
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass
        else:
            raise
