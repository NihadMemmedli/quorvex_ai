"""
Native API Healer Workflow - Fixes Failing Playwright API Tests

Lighter healer than browser tests - no MCP tools needed.
1. Run test: `npx playwright test {file}`
2. If fails, extract error (wrong status, missing field, timeout, auth error)
3. Send error + original spec + current code to AI
4. AI fixes the code (adjust assertions, add auth headers, fix URLs)
5. Retry up to 3 attempts
"""

import asyncio
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

# Add orchestrator to path
sys.path.append(str(Path(__file__).parent.parent.parent))

logger = logging.getLogger(__name__)

# Load Claude credentials and SDK
from orchestrator.load_env import setup_claude_env

setup_claude_env()

# Use run-specific config directory if set (for parallel execution isolation)
config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
if config_dir:
    os.chdir(config_dir)

from orchestrator.utils.agent_runner import AgentRunner


class NativeApiHealer:
    """
    Playwright API Test Healer that fixes failing API tests.

    Unlike the browser NativeHealer, this does NOT use Playwright MCP tools.
    It analyzes test errors and fixes code using AI without browser interaction.

    Flow:
    1. Run the failing test with npx playwright test
    2. Parse the error output
    3. Send error + spec + code to AI for fixing
    4. Write fixed code
    5. Re-run and verify
    """

    def __init__(self):
        pass

    async def heal_test(
        self, test_file: str, error_log: str | None = None, spec_content: str | None = None
    ) -> str | None:
        """
        Attempt to heal a failing API test.

        Args:
            test_file: Path to the failing test file
            error_log: Optional error output from previous run
            spec_content: Optional original spec content for context

        Returns:
            Fixed test content or None if healing failed
        """
        path_obj = Path(test_file)
        if not path_obj.exists():
            raise FileNotFoundError(f"Test file not found: {test_file}")

        test_content = path_obj.read_text()

        logger.info(f"Healing API test: {test_file}")

        # Build prompt for the healer agent
        prompt = self._build_healer_prompt(
            test_file=test_file, test_content=test_content, error_log=error_log, spec_content=spec_content
        )

        # Invoke the Healer Agent
        logger.info("Invoking API Test Healer Agent...")
        result = await self._query_agent(prompt)

        # Check if the agent wrote the fixed code
        if result:
            fixed_code = self._extract_code(result)
            if fixed_code and fixed_code != test_content:
                path_obj.write_text(fixed_code)
                logger.info(f"API test healed and saved: {test_file}")
                return fixed_code

        # Check if file was modified directly by the agent
        new_content = path_obj.read_text()
        if new_content != test_content:
            logger.info(f"API test healed (agent wrote directly): {test_file}")
            return new_content

        logger.warning("Healing completed but no changes detected")
        return None

    def _build_healer_prompt(
        self, test_file: str, test_content: str, error_log: str | None, spec_content: str | None
    ) -> str:
        """Build prompt for the API test healer agent."""

        error_section = ""
        if error_log:
            # Truncate very long error logs
            truncated = error_log[:5000]
            error_section = f"""
## Error Output from Test Run
```
{truncated}
```
"""

        spec_section = ""
        if spec_content:
            spec_section = f"""
## Original Spec
```markdown
{spec_content[:3000]}
```
"""

        prompt = f"""You are the Playwright API Test Healer.

# Task: Fix a Failing API Test

## Test File: {test_file}

```typescript
{test_content}
```

{error_section}
{spec_section}

## Your Workflow

1. **Analyze the error** - Identify the root cause:
   - Wrong status code assertion (e.g., got 200 expected 201)
   - Missing or wrong response body field
   - Authentication failure (missing/invalid token)
   - URL not found (404 - wrong endpoint path)
   - Timeout (endpoint too slow)
   - JSON parse error (response not JSON)
   - Variable reference error (undefined variable from previous test)

2. **Fix the code** - Apply targeted fixes:
   - Adjust status code assertions to match actual API behavior
   - Fix request body structure to match API schema
   - Add missing auth headers
   - Fix endpoint URLs/paths
   - Add proper error handling for non-JSON responses
   - Fix variable scoping for chained tests
   - Add retry logic for flaky endpoints
   - Add proper Content-Type headers

3. **Return the COMPLETE fixed code** - Not just the changed lines

## Key Principles

- Fix one error at a time - don't change things that aren't broken
- Prefer minimal, targeted fixes over rewrites
- Keep the test structure and intent from the original spec
- Use Playwright best practices for API testing
- If a test cannot be fixed (e.g., endpoint doesn't exist), mark with `test.fixme()`

## Common API Test Fixes

### Status Code Mismatch
```typescript
// Before: expect(response.status()).toBe(201);
// After (if API returns 200 for creates):
expect(response.status()).toBe(200);
```

### Missing Auth Header
```typescript
// Add Authorization header
const response = await request.get(url, {{
  headers: {{
    'Authorization': `Bearer ${{process.env.API_TOKEN!}}`
  }}
}});
```

### Response Not JSON
```typescript
// Safely parse response
const text = await response.text();
let body;
try {{
  body = JSON.parse(text);
}} catch {{
  throw new Error(`Expected JSON response, got: ${{text.substring(0, 200)}}`);
}}
```

Return the COMPLETE fixed TypeScript code inside a ```typescript code block.
"""
        return prompt

    async def _query_agent(self, prompt: str) -> str:
        """Query the API Test Healer agent using AgentRunner."""
        timeout = int(os.environ.get("HEALER_TIMEOUT_SECONDS", os.environ.get("AGENT_TIMEOUT_SECONDS", "600")))

        logger.info(f"   Timeout: {timeout}s ({timeout // 60} minutes)")

        runner = AgentRunner(
            timeout_seconds=timeout,
            allowed_tools=["Glob", "Grep", "Read", "LS", "Write", "Edit"],
            log_tools=True,
        )

        result = await runner.run(prompt)

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
                if "test(" in code or "test.describe" in code:
                    return code

        return None

    def run_test(self, test_file: str, browser: str = "chromium") -> dict:
        """
        Run an API test and return the result.

        Returns:
            Dict with 'passed', 'exit_code', 'output', 'error_summary'
        """
        try:
            cmd = f"npx playwright test '{test_file}' --reporter=list --project {browser} --timeout=60000"

            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )

            output = result.stdout + result.stderr
            passed = result.returncode == 0 and "passed" in output

            return {
                "passed": passed,
                "exit_code": result.returncode,
                "output": output,
                "error_summary": self._summarize_error(output) if not passed else "",
            }

        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "exit_code": -1,
                "output": "Test timed out after 120 seconds",
                "error_summary": "Timeout",
            }
        except Exception as e:
            return {"passed": False, "exit_code": -1, "output": str(e), "error_summary": str(e)[:100]}

    def _summarize_error(self, output: str) -> str:
        """Extract a brief error summary from full output."""
        error_patterns = [
            r"Expected status: \d+, Received: \d+",
            r"expect\(.+\)\..+",
            r"TimeoutError:.*",
            r"Error:.*",
            r"ECONNREFUSED.*",
            r"401 Unauthorized.*",
            r"403 Forbidden.*",
            r"404 Not Found.*",
        ]

        for pattern in error_patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                return match.group(0)[:120]

        for line in output.split("\n"):
            if re.search(r"(error|fail|timeout)", line, re.IGNORECASE):
                return line.strip()[:120]

        return "Unknown error"


if __name__ == "__main__":
    from orchestrator.logging_config import setup_logging

    setup_logging()

    import argparse

    parser = argparse.ArgumentParser(description="Heal failing Playwright API tests")
    parser.add_argument("test_file", nargs="?", help="Path to failing test file")
    parser.add_argument("--log", help="Path to error log file")
    parser.add_argument("--spec", help="Path to original spec file")
    args = parser.parse_args()

    async def main():
        healer = NativeApiHealer()
        if args.test_file:
            error_log = None
            spec_content = None
            if args.log:
                error_log = Path(args.log).read_text()
            if args.spec:
                spec_content = Path(args.spec).read_text()
            await healer.heal_test(args.test_file, error_log, spec_content)
        else:
            logger.error("Usage: native_api_healer.py <test_file> [--log <error.log>] [--spec <spec.md>]")

    try:
        asyncio.run(main())
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass
        else:
            raise
