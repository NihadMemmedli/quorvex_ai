"""
Native Mixed Generator - Handles specs with both browser and API steps.

Mixed specs contain regular browser steps alongside [API] prefixed steps.
The generated test uses both `page` and `request` fixtures.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

# Add orchestrator to path
sys.path.append(str(Path(__file__).parent.parent.parent))

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load Claude credentials and SDK
from orchestrator.load_env import setup_claude_env

setup_claude_env()

config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
if config_dir:
    os.chdir(config_dir)

import logging

from orchestrator.utils.agent_runner import AgentRunner, build_allowed_tools, get_default_timeout

logger = logging.getLogger(__name__)


class NativeMixedGenerator:
    """
    Generator for mixed browser + API test specs.

    Handles specs where some steps use the browser (page fixture)
    and others are prefixed with [API] (request fixture).

    Generated tests use both fixtures:
    ```typescript
    test('mixed test', async ({ page, request }) => { ... });
    ```
    """

    def __init__(self):
        self.tests_dir = BASE_DIR / "tests" / "generated"
        self.tests_dir.mkdir(parents=True, exist_ok=True)

    async def generate_test(
        self, spec_path: str, target_url: str | None = None, output_name: str | None = None
    ) -> Path:
        """
        Generate a mixed browser + API test from a spec.

        Args:
            spec_path: Path to the spec file
            target_url: Application URL
            output_name: Output file name override

        Returns:
            Path to the generated test file
        """
        spec_path_obj = Path(spec_path)
        if not spec_path_obj.exists():
            raise FileNotFoundError(f"Spec file not found: {spec_path}")

        spec_content = spec_path_obj.read_text()
        spec_name = output_name if output_name else spec_path_obj.stem
        output_path = self.tests_dir / f"{spec_name}.mixed.spec.ts"

        logger.info(f"Generating mixed browser+API test from: {spec_path}")
        logger.info(f"   Output: {output_path}")

        # Analyze step types
        browser_steps, api_steps = self._categorize_steps(spec_content)
        logger.info(f"   Browser steps: {len(browser_steps)}, API steps: {len(api_steps)}")

        prompt = self._build_prompt(
            spec_path=spec_path,
            spec_content=spec_content,
            spec_name=spec_name,
            output_path=str(output_path),
            target_url=target_url,
        )

        logger.info("Invoking Mixed Test Generator Agent...")
        result = await self._query_agent(prompt)

        # Check if agent wrote the file
        if output_path.exists():
            content = output_path.read_text()
            if "test(" in content or "test.describe" in content:
                logger.info(f"Mixed test generated: {output_path}")
                return output_path

        # Extract code from response
        if result:
            code = self._extract_code(result)
            if code:
                output_path.write_text(code)
                logger.info(f"Mixed test generated: {output_path}")
                return output_path

        logger.warning(f"Generator finished but test file not found at: {output_path}")
        return output_path

    def _categorize_steps(self, spec_content: str):
        """Separate browser steps from API steps."""
        browser_steps = []
        api_steps = []

        for line in spec_content.split("\n"):
            step_match = re.match(r"\s*\d+\.\s+(.*)", line)
            if step_match:
                step_text = step_match.group(1)
                if step_text.startswith("[API]"):
                    api_steps.append(step_text[5:].strip())
                else:
                    browser_steps.append(step_text)

        return browser_steps, api_steps

    def _build_prompt(self, spec_path, spec_content, spec_name, output_path, target_url):
        """Build prompt for the mixed generator."""
        test_suite = spec_name.replace("-", " ").title()

        url_section = ""
        if target_url:
            url_section = f"\nTarget URL: {target_url}"

        return f"""You are a Playwright Mixed Test Generator.

Generate a test that uses BOTH the `page` fixture (for browser interactions)
AND the `request` fixture (for API calls).

<test-suite>{test_suite}</test-suite>
<test-file>{output_path}</test-file>
{url_section}

<spec-content file="{spec_path}">
{spec_content}
</spec-content>

## Key Rules

1. Steps WITHOUT [API] prefix are browser steps - use `page` fixture
2. Steps WITH [API] prefix are API steps - use `request` fixture
3. The test function signature must include BOTH fixtures:
   ```typescript
   test('test name', async ({{ page, request }}) => {{ ... }});
   ```
4. Browser steps use standard Playwright actions (click, fill, etc.)
5. API steps use request.get(), request.post(), etc.
6. Variables from API responses can be used in browser steps and vice versa

## Example Generated Code

```typescript
import {{ test, expect }} from '@playwright/test';

test.describe('{test_suite}', () => {{
  test('should create user via UI and verify via API', async ({{ page, request }}) => {{
    // Browser: Navigate to the app
    await page.goto('https://app.example.com/users');

    // Browser: Fill and submit form
    await page.getByLabel('Name').fill('Test User');
    await page.getByRole('button', {{ name: 'Submit' }}).click();

    // Browser: Verify success
    await expect(page.getByText('User created')).toBeVisible();

    // API: Verify the user was created
    const response = await request.get('https://api.example.com/users?name=Test+User');
    expect(response.status()).toBe(200);
    const users = await response.json();
    expect(users.length).toBeGreaterThan(0);
  }});
}});
```

## Output

Return the COMPLETE TypeScript code inside a ```typescript code block.
Write the file to: {output_path}
"""

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

    async def _query_agent(self, prompt: str) -> str:
        """Query the agent."""
        timeout = int(os.environ.get("GENERATOR_TIMEOUT_SECONDS", get_default_timeout()))
        logger.info(f"   Timeout: {timeout}s ({timeout // 60} minutes)")

        runner = AgentRunner(
            timeout_seconds=timeout,
            allowed_tools=build_allowed_tools(
                ["Glob", "Grep", "Read", "LS"],
                self.GENERATOR_MCP_TOOLS,
            ),
            log_tools=True,
        )
        result = await runner.run(prompt)

        logger.info(
            f"   Agent stats: {result.messages_received} messages, "
            f"{len(result.tool_calls)} tool calls, "
            f"{result.duration_seconds:.1f}s"
        )

        return result.output

    def _extract_code(self, text: str) -> str | None:
        """Extract TypeScript code from response."""
        for pattern in [r"```typescript\n(.*?)```", r"```ts\n(.*?)```", r"```\n(.*?)```"]:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                code = match.group(1).strip()
                if "test(" in code or "test.describe" in code:
                    return code
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate mixed browser+API tests")
    parser.add_argument("--spec", required=True, help="Spec file path")
    parser.add_argument("--url", help="Target URL")
    args = parser.parse_args()

    async def main():
        gen = NativeMixedGenerator()
        await gen.generate_test(args.spec, target_url=args.url)

    try:
        asyncio.run(main())
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass
        else:
            raise
