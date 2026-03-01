"""
Native API Generator Workflow - Converts API Test Specs to Playwright Code

This workflow generates Playwright API tests using the `request` fixture.
Unlike the browser generator, it does NOT need browser MCP tools - it generates
code directly from the spec using AI.
"""

import asyncio
import logging
import os
import re
import sys
from pathlib import Path

# Add orchestrator to path
sys.path.append(str(Path(__file__).parent.parent.parent))

# Store project base directory BEFORE any chdir() calls
BASE_DIR = Path(__file__).resolve().parent.parent.parent

logger = logging.getLogger(__name__)

# Load Claude credentials and SDK
from orchestrator.load_env import setup_claude_env

setup_claude_env()

# Use run-specific config directory if set (for parallel execution isolation)
config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
if config_dir:
    os.chdir(config_dir)

from orchestrator.utils.agent_runner import AgentRunner, get_default_timeout


class NativeApiGenerator:
    """
    Playwright API Test Generator that converts API specs to executable test code.

    Unlike the browser NativeGenerator, this does NOT use browser MCP tools.
    It generates code directly from the spec since API tests don't need
    browser exploration to discover selectors.

    Flow:
    1. Read the markdown spec file
    2. Extract base URL, auth pattern, and API steps
    3. Build prompt with API generation instructions
    4. Run agent via AgentRunner (no MCP tools needed)
    5. Extract TypeScript code from response
    6. Write to tests/generated/{name}.api.spec.ts
    """

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        if project_id and project_id != "default":
            self.tests_dir = BASE_DIR / "tests" / "generated" / project_id
        else:
            self.tests_dir = BASE_DIR / "tests" / "generated"
        self.tests_dir.mkdir(parents=True, exist_ok=True)

    async def generate_test(
        self, spec_path: str, target_url: str | None = None, output_name: str | None = None
    ) -> Path:
        """
        Generate a Playwright API test from a markdown spec.

        Args:
            spec_path: Path to the markdown spec file
            target_url: Base URL override (optional, extracted from spec if not given)
            output_name: Override for output test file name (without extension)

        Returns:
            Path to the generated test file
        """
        spec_path_obj = Path(spec_path)
        if not spec_path_obj.exists():
            raise FileNotFoundError(f"Spec file not found: {spec_path}")

        spec_content = spec_path_obj.read_text()
        spec_name = output_name if output_name else spec_path_obj.stem

        # Determine output path
        output_path = self.tests_dir / f"{spec_name}.api.spec.ts"

        logger.info(f"Generating API test from: {spec_path}")
        logger.info(f"   Output: {output_path}")

        # Extract API-specific metadata from spec
        base_url = target_url or self._extract_base_url(spec_content)
        auth_pattern = self._extract_auth(spec_content)

        # Build prompt for the API test generator agent
        prompt = self._build_generator_prompt(
            spec_path=spec_path,
            spec_content=spec_content,
            spec_name=spec_name,
            output_path=str(output_path),
            base_url=base_url,
            auth_pattern=auth_pattern,
        )

        # Invoke the API Generator Agent
        logger.info("Invoking API Test Generator Agent...")
        result = await self._query_agent(prompt)

        # Check if agent wrote the file directly
        if output_path.exists():
            content = output_path.read_text()
            if "test(" in content or "test.describe" in content:
                logger.info(f"API test generated: {output_path}")
                return output_path

        # Fallback: Extract code from agent response and write it
        if result:
            code = self._extract_code(result)
            if code:
                logger.info(f"Saving generated API test code to: {output_path}")
                output_path.write_text(code)
                return output_path

        logger.warning(f"Generator finished but test file not found at: {output_path}")
        return output_path

    def _extract_base_url(self, spec_content: str) -> str | None:
        """Extract base URL from spec content."""
        patterns = [
            r"##\s+Base\s+URL:\s*(https?://[^\s]+)",
            r"Base\s+URL:\s*(https?://[^\s]+)",
            r"POST\s+(https?://[^\s/]+)",
            r"GET\s+(https?://[^\s/]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, spec_content, re.IGNORECASE)
            if match:
                url = match.group(1).rstrip(".")
                # For full URLs in POST/GET, extract just the base
                if "/api/" in url or "/v1/" in url:
                    from urllib.parse import urlparse

                    parsed = urlparse(url)
                    return f"{parsed.scheme}://{parsed.netloc}"
                return url
        return None

    def _extract_auth(self, spec_content: str) -> str | None:
        """Extract auth pattern from spec content."""
        patterns = [
            r"##\s+Auth:\s*(.+)",
            r"Auth(?:orization)?:\s*(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, spec_content, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_credential_placeholders(self, spec_content: str) -> dict:
        """Extract {{VAR}} placeholders from spec and resolve their values."""
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
        self,
        spec_path: str,
        spec_content: str,
        spec_name: str,
        output_path: str,
        base_url: str | None,
        auth_pattern: str | None,
    ) -> str:
        """Build prompt for the API test generator agent."""

        test_suite = spec_name.replace("prd-", "").replace("-", " ").title()

        base_url_section = ""
        if base_url:
            base_url_section = f"\nBase URL: {base_url}"

        auth_section = ""
        if auth_pattern:
            auth_section = f"\nAuth Pattern: {auth_pattern}"

        # Extract and resolve credential placeholders
        credentials = self._extract_credential_placeholders(spec_content)
        credentials_section = ""
        if credentials:
            cred_lines = []
            for var_name in credentials:
                cred_lines.append(f"- `{{{{{var_name}}}}}` -> Use `process.env.{var_name}!` in generated code")
            credentials_section = f"""

## Credentials (IMPORTANT)
The spec contains credential placeholders. In the generated code, use `process.env.VAR_NAME!` instead of hardcoding.

{chr(10).join(cred_lines)}
"""

        prompt = f"""You are the Playwright API Test Generator.

Context: Generate automated API tests from the following spec using Playwright's `request` fixture.

<test-suite>{test_suite}</test-suite>
<test-file>{output_path}</test-file>
{base_url_section}
{auth_section}
{credentials_section}
<spec-content file="{spec_path}">
{spec_content}
</spec-content>

## Instructions

Generate a complete Playwright TypeScript test file that:

1. Uses `import {{ test, expect }} from '@playwright/test'`
2. Uses the `request` fixture (NOT `page`): `async ({{ request }}) => {{ ... }}`
3. Tests each API endpoint/step described in the spec
4. Chains requests when the spec uses variable storage (e.g., "Store response.body.id as $userId")
5. Uses `test.describe.serial()` for CRUD flows where tests depend on each other
6. Handles authentication via headers (Bearer, Basic, API Key) as specified

## Code Generation Requirements

- Generate COMPLETE TypeScript code - not pseudocode
- Use `test.describe('{test_suite}', () => {{ ... }})` to group all tests
- Use `test.describe.serial()` when tests depend on shared state
- Add comments with the step text from the spec before each action
- Include proper `await` statements for all async operations
- Use `expect()` for all assertions
- For credential placeholders `{{{{VAR_NAME}}}}`, use `process.env.VAR_NAME!` in code
- Handle response parsing with `await response.json()` before assertions
- Set base URL as a shared variable in the describe block

## HTTP Method Mapping

- `POST /path with body {{...}}` -> `request.post(url, {{ data: {{...}} }})`
- `GET /path` -> `request.get(url)`
- `PUT /path with body {{...}}` -> `request.put(url, {{ data: {{...}} }})`
- `PATCH /path with body {{...}}` -> `request.patch(url, {{ data: {{...}} }})`
- `DELETE /path` -> `request.delete(url)`

## Assertion Mapping

- `Verify response status is X` -> `expect(response.status()).toBe(X)`
- `Verify response body has "field"` -> `expect(body).toHaveProperty('field')`
- `Verify response body.X equals Y` -> `expect(body.X).toBe(Y)`
- `Verify response body contains "text"` -> `expect(JSON.stringify(body)).toContain('text')`

## Output

Write the generated test file to: {output_path}

Return ONLY the TypeScript code inside a ```typescript code block.
"""
        return prompt

    async def _query_agent(self, prompt: str) -> str:
        """Query the API Test Generator agent using AgentRunner."""
        timeout = int(os.environ.get("GENERATOR_TIMEOUT_SECONDS", get_default_timeout()))

        logger.info(f"   Timeout: {timeout}s ({timeout // 60} minutes)")

        runner = AgentRunner(
            timeout_seconds=timeout,
            allowed_tools=["Glob", "Grep", "Read", "LS", "Write"],
            log_tools=True,
        )

        result = await runner.run(prompt)

        # Log diagnostics
        logger.info(
            f"   Agent stats: {result.messages_received} messages, "
            f"{len(result.tool_calls)} tool calls, "
            f"{result.duration_seconds:.1f}s"
        )

        if result.timed_out:
            logger.warning("   Agent timed out")

        if not result.success and result.error:
            logger.warning(f"   Agent error: {result.error}")

        return result.output

    def _extract_code(self, text: str) -> str | None:
        """Extract TypeScript code from markdown response."""
        patterns = [
            r"```typescript\n(.*?)```",
            r"```ts\n(.*?)```",
            r"```\n(.*?)```",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                code = match.group(1).strip()
                # Validate it looks like a Playwright test
                if "test(" in code or "test.describe" in code:
                    return code

        # Fallback: if the entire response looks like code
        if text.strip().startswith("import") and ("test(" in text or "test.describe" in text):
            return text.strip()

        return None


if __name__ == "__main__":
    from orchestrator.logging_config import setup_logging

    setup_logging()

    import argparse

    parser = argparse.ArgumentParser(description="Generate Playwright API tests from specs")
    parser.add_argument("--spec", help="Specific spec file to generate")
    parser.add_argument("--url", help="Base URL override (optional)")
    args = parser.parse_args()

    async def main():
        generator = NativeApiGenerator()
        if args.spec:
            await generator.generate_test(args.spec, target_url=args.url)
        else:
            logger.error("Usage: --spec <path>")

    try:
        asyncio.run(main())
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass
        else:
            raise
