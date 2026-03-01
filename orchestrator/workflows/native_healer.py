"""
Native Healer Workflow - Debugs and Fixes Failing Playwright Tests

This workflow uses the Playwright Test Healer agent to:
1. Run failing tests and analyze error output
2. Analyze errors with browser snapshot context
3. Fix selectors, timing issues, or assertion failures
4. Verify the fix passes
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class HealerTimeoutError(Exception):
    """Raised when the healer agent times out."""

    pass


# Add orchestrator to path
sys.path.append(str(Path(__file__).parent.parent.parent))

# Load Claude credentials and SDK
from orchestrator.load_env import setup_claude_env

setup_claude_env()

# Use run-specific config directory if set (for parallel execution isolation)
config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
if config_dir:
    os.chdir(config_dir)

from claude_agent_sdk import ClaudeAgentOptions, query

from orchestrator.utils.agent_runner import build_allowed_tools
from orchestrator.utils.browser_cleanup import kill_new_children, snapshot_child_pids

# Playwright MCP tools matching .claude/agents/playwright-test-healer.md
HEALER_MCP_TOOLS = [
    "browser_close",
    "browser_console_messages",
    "browser_evaluate",
    "browser_generate_locator",
    "browser_handle_dialog",
    "browser_network_requests",
    "browser_snapshot",
    "test_list",
    "test_run",
]


class NativeHealer:
    """
    Playwright Test Healer that automatically fixes failing tests.

    Flow:
    1. Run test_run to identify failing tests
    2. Analyze the error output from test_run
    3. Use diagnostic tools (browser_snapshot, console_messages, network_requests) if needed
    4. Edit the test code to fix the issue
    5. Re-run to verify the fix
    """

    def __init__(self):
        pass

    async def heal_test(
        self,
        test_file: str,
        error_log: str | None = None,
        timeout_seconds: int | None = None,
    ) -> str | None:
        """
        Attempt to heal a failing test.

        Args:
            test_file: Path to the failing test file
            error_log: Optional error output from previous run

        Returns:
            Fixed test content or None if healing failed
        """
        path_obj = Path(test_file)
        if not path_obj.exists():
            raise FileNotFoundError(f"Test file not found: {test_file}")

        test_content = path_obj.read_text()

        logger.info(f"Healing test: {test_file}")

        # Build prompt for the Healer agent
        prompt = self._build_healer_prompt(test_file=test_file, test_content=test_content, error_log=error_log)

        # Invoke the Healer Agent
        logger.info("Invoking Playwright Healer Agent...")
        result = await self._query_healer_agent(prompt, timeout_seconds=timeout_seconds)

        if self._last_timed_out:
            raise HealerTimeoutError(f"Healer timed out after {timeout_seconds or 'default'}s")

        # Check if file was modified by the agent
        new_content = path_obj.read_text()
        if new_content != test_content:
            logger.info(f"Test healed and saved: {test_file}")
            return new_content

        # Fallback: If agent returned fixed code but didn't write it
        if result and ("test(" in result or "test.describe" in result):
            fixed_code = self._extract_code(result)
            if fixed_code:
                path_obj.write_text(fixed_code)
                logger.info(f"Applied fix to: {test_file}")
                return fixed_code

        logger.warning("Healing completed but no changes detected")
        return None

    def _build_healer_prompt(self, test_file: str, test_content: str, error_log: str | None) -> str:
        """Build prompt for the playwright-test-healer agent."""

        error_section = ""
        if error_log:
            error_section = f"""
## Previous Error Output
```
{error_log[:5000]}
```
"""

        prompt = f"""You are the Playwright Test Healer.

# Task: Debug and Fix Failing Test

## Test File: {test_file}

```typescript
{test_content}
```

{error_section}

## Your Workflow

1. **Run the test**: Use `test_run` to execute the test and see current failures
2. **Analyze the error**: Parse the error output from `test_run` (error message, stack trace, failed assertions)
3. **Deep investigation** (if error is unclear): Use diagnostic tools:
   - `browser_snapshot` to see the current page state and available elements
   - `browser_console_messages` to check for JavaScript errors
   - `browser_network_requests` to verify API calls
   - `browser_generate_locator` to find correct selectors
4. **Diagnose**: Determine the root cause:
   - Element selectors that may have changed
   - Timing and synchronization issues
   - Assertion failures
   - Data dependencies
5. **Fix the code**: Use `Edit` or `MultiEdit` to update the test
6. **Verify**: Run the test again to confirm the fix

## Dialog Handling (CRITICAL)
When browser dialogs appear (alerts, confirms, or "Leave site?" beforeunload dialogs):
- Use `browser_handle_dialog` with `accept: true` IMMEDIATELY
- For "Leave site?" dialogs: Always accept to continue navigation
- After handling a dialog, take a `browser_snapshot` to verify page state

## Key Principles

- Be systematic - fix one error at a time
- Prefer robust, maintainable solutions
- Use Playwright best practices
- If a test cannot be fixed, mark it with `test.fixme()` and explain why
- Never use deprecated APIs like `waitForNetworkIdle`

## Cleanup (IMPORTANT)
After you have finished verifying the fix (or determined the test cannot be fixed),
call `browser_close` to close the browser before finishing.

Start by running the test to see the current state.
"""
        return prompt

    async def _query_healer_agent(self, prompt: str, timeout_seconds: int | None = None) -> str:
        """
        Query the Playwright Healer agent using the SDK.

        Handles the known cancel scope cleanup error gracefully.
        Cleans up orphaned browser/MCP processes in a finally block.
        """
        result = ""
        self._last_timed_out = False
        pre_query_pids = snapshot_child_pids()

        effective_timeout = timeout_seconds or int(
            os.environ.get("HEALER_TIMEOUT_SECONDS", os.environ.get("AGENT_TIMEOUT_SECONDS", "1800"))
        )

        try:

            async def _run_healer_query():
                nonlocal result
                async for message in query(
                    prompt=prompt,
                    options=ClaudeAgentOptions(
                        allowed_tools=build_allowed_tools(
                            ["Glob", "Grep", "Read", "LS", "Edit", "MultiEdit", "Write"],
                            HEALER_MCP_TOOLS,
                        ),
                        setting_sources=["project"],  # Load .claude/ and .mcp.json
                        permission_mode="bypassPermissions",  # Auto-approve tools
                    ),
                ):
                    # Log tool uses for real-time feedback
                    if hasattr(message, "type"):
                        if message.type == "tool_use":
                            tool_name = getattr(message, "name", "unknown")
                            if tool_name.startswith("mcp__playwright"):
                                action = tool_name.split("__")[-1] if "__" in tool_name else tool_name
                                logger.info(f"   {action}...")
                            else:
                                logger.info(f"   {tool_name}...")

                    if hasattr(message, "result"):
                        result = message.result

            try:
                await asyncio.wait_for(_run_healer_query(), timeout=effective_timeout)
            except asyncio.TimeoutError:
                logger.warning(f"Healer agent timed out after {effective_timeout}s, returning partial result")
                self._last_timed_out = True
                return result

            return result

        except Exception as e:
            error_str = str(e).lower()
            if "cancel scope" in error_str or "cancelled" in error_str:
                logger.info(f"SDK cleanup warning (ignored): {type(e).__name__}")
                return result
            else:
                logger.error(f"Healer agent error: {e}")
                raise

        finally:
            try:
                kill_new_children(pre_query_pids, grace_seconds=2.0)
            except Exception:
                pass  # Non-fatal

    def _extract_code(self, text: str) -> str | None:
        """Extract TypeScript code from markdown response."""
        import re

        # Try typescript/ts code blocks
        patterns = [
            r"```typescript\n(.*?)```",
            r"```ts\n(.*?)```",
            r"```\n(.*?)```",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return match.group(1).strip()

        return None

    async def heal_all_failing(self, test_dir: str = "tests/generated") -> dict:
        """
        Run all tests and attempt to heal failures.

        Args:
            test_dir: Directory containing test files

        Returns:
            Dict with healing results
        """
        logger.info(f"Running all tests in {test_dir} and healing failures...")

        # This would ideally run `npx playwright test` and parse failures
        # For now, we'll let the agent handle everything

        prompt = f"""You are the Playwright Test Healer.

# Task: Run All Tests and Heal Failures

1. Use `test_list` to see available tests in {test_dir}
2. Use `test_run` to run all tests
3. For each failing test, follow the healing workflow:
   - Analyze the error output from `test_run` (error message, stack trace, failed assertions)
   - If needed, use `browser_snapshot`, `browser_console_messages`, `browser_network_requests` for deeper investigation
   - Use `browser_generate_locator` to find correct selectors
   - Fix the code with `Edit`
   - Re-run to verify

Continue until all tests pass or are marked as `test.fixme()`.
"""

        result = await self._query_healer_agent(prompt)

        return {"status": "completed", "result": result}


if __name__ == "__main__":
    from orchestrator.logging_config import setup_logging

    setup_logging()

    import argparse

    parser = argparse.ArgumentParser(description="Heal failing Playwright tests")
    parser.add_argument("test_file", nargs="?", help="Path to failing test file")
    parser.add_argument("--log", help="Path to error log file")
    parser.add_argument("--all", action="store_true", help="Run and heal all tests")
    args = parser.parse_args()

    async def main():
        healer = NativeHealer()
        if args.all:
            await healer.heal_all_failing()
        elif args.test_file:
            error_log = None
            if args.log:
                error_log = Path(args.log).read_text()
            await healer.heal_test(args.test_file, error_log)
        else:
            logger.info("Usage: native_healer.py <test_file> [--log <error.log>] or --all")

    try:
        asyncio.run(main())
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass
        else:
            raise
