"""
Validator Workflow - Runs generated tests and fixes failures automatically
Enhanced with spec/plan context and improved error filtering.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# Load Claude credentials
from load_env import setup_claude_env

setup_claude_env()

from claude_agent_sdk import ClaudeAgentOptions, query

from utils.json_utils import extract_json_from_markdown


class Validator:
    """Validates and fixes generated Playwright tests"""

    def __init__(self, max_attempts: int = 7):
        self.max_attempts = max_attempts

    def _filter_error_output(self, output: str) -> str:
        """Remove noise like dotenv logs from error output."""
        lines = output.split("\n")
        filtered = []
        for line in lines:
            # Skip dotenv messages
            if line.startswith("[dotenv"):
                continue
            # Skip tip messages
            if "tip:" in line.lower() and ("dotenv" in line.lower() or "https://dotenvx.com" in line):
                continue
            filtered.append(line)
        return "\n".join(filtered)

    def _extract_key_error(self, output: str) -> str:
        """Extract the key error message from Playwright output."""
        filtered = self._filter_error_output(output)

        # Find the main error patterns

        key_lines = []
        for line in filtered.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Include error lines
            if "Error:" in line or "TimeoutError:" in line:
                key_lines.append(line)
            # Include the failing code line
            if line.startswith(">") or line.startswith("at "):
                key_lines.append(line)
            # Include failed assertion info
            if "expect(" in line or "Locator" in line:
                key_lines.append(line)

        return "\n".join(key_lines[:20])  # Limit to prevent token bloat

    async def validate_and_fix(
        self,
        test_file: str,
        output_dir: str = None,
        browser: str = "chromium",
        spec_file: str = None,
        plan_file: str = None,
    ) -> dict:
        """
        Run a test and fix any failures automatically.

        Args:
            test_file: Path to the Playwright test file
            output_dir: Directory to save validation results
            browser: Browser project to run (chromium, firefox, webkit)
            spec_file: Optional path to original spec file for context
            plan_file: Optional path to test plan JSON for context

        Returns:
            Dict containing validation results
        """
        logger.info(f"Validating test: {test_file} on {browser}")
        logger.info(f"   Max attempts: {self.max_attempts}")

        # Load context files
        spec_context = ""
        plan_context = ""

        if spec_file:
            spec_path = Path(spec_file)
            if spec_path.exists():
                spec_context = spec_path.read_text()
                logger.info(f"   Spec context loaded: {spec_file}")

        if plan_file:
            plan_path = Path(plan_file)
            if plan_path.exists():
                try:
                    plan_data = json.loads(plan_path.read_text())
                    plan_context = json.dumps(plan_data, indent=2)
                    logger.info(f"   Plan context loaded: {plan_file}")
                except Exception:
                    pass

        # Read the test file
        test_path = Path(test_file)
        if not test_path.exists():
            raise FileNotFoundError(f"Test file not found: {test_file}")

        test_code = test_path.read_text()
        validation_result = None

        for attempt in range(1, self.max_attempts + 1):
            logger.info(f"\n{'=' * 80}")
            logger.info(f"Attempt {attempt}/{self.max_attempts}")
            logger.info(f"{'=' * 80}\n")

            # Run the test
            logger.info(f"Running test on {browser}...")
            result = await self._run_test(test_file, output_dir, browser)

            if result.get("passed"):
                logger.info("Test passed!")
                validation_result = {
                    "status": "success",
                    "attempts": attempt,
                    "testFile": test_file,
                    "browser": browser,
                    "message": "Test passed successfully",
                    "timestamp": datetime.now().isoformat(),
                }
                break

            # Test failed, try to fix it
            filtered_output = self._filter_error_output(result.get("output", ""))
            key_error = self._extract_key_error(result.get("output", ""))

            logger.error(f"Test failed (exit code: {result.get('exitCode')})")
            logger.error(f"Key Error:\n{key_error}")

            if attempt < self.max_attempts:
                logger.info(f"Attempting to fix (attempt {attempt}/{self.max_attempts})...")
                fix_result = await self._fix_test(
                    test_file,
                    filtered_output,  # Use filtered output
                    test_code,
                    spec_context,
                    plan_context,
                    attempt,
                )

                if fix_result.get("status") == "fixed":
                    logger.info(f"Fix applied: {fix_result.get('fixApplied', 'unknown')}")
                    logger.info("   Re-running test...")
                    test_code = test_path.read_text()  # Read updated code
                else:
                    logger.warning(f"Could not fix automatically: {fix_result.get('remainingIssues')}")
                    # Don't break - continue trying
        else:
            # All attempts failed
            validation_result = {
                "status": "failed",
                "attempts": self.max_attempts,
                "testFile": test_file,
                "browser": browser,
                "message": f"Failed after {self.max_attempts} attempts",
                "lastError": self._extract_key_error(result.get("output", "")),
                "timestamp": datetime.now().isoformat(),
            }

        # Save validation result
        if output_dir and validation_result:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            validation_file = output_path / "validation.json"
            with open(validation_file, "w") as f:
                json.dump(validation_result, f, indent=2)
            logger.info(f"Validation result saved to: {validation_file}")

        return validation_result

    async def _run_test(self, test_file: str, output_dir: str = None, browser: str = "chromium") -> dict:
        """Run a Playwright test and return the result"""
        import subprocess

        try:
            cmd = f"npx playwright test '{test_file}' --reporter=list,html --project {browser}"
            if output_dir:
                results_dir = Path(output_dir) / "test-results"
                report_dir = Path(output_dir) / "report"
                cmd = f"PLAYWRIGHT_OUTPUT_DIR='{results_dir}' PLAYWRIGHT_HTML_REPORT='{report_dir}' {cmd}"

            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=90,  # Increased timeout for slow sites
            )

            output = result.stdout + result.stderr

            # Check if test passed
            passed = result.returncode == 0 and ("passed" in output)

            return {"passed": passed, "exitCode": result.returncode, "output": output}

        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "exitCode": -1,
                "output": "Test timed out after 90 seconds",
            }
        except Exception as e:
            return {"passed": False, "exitCode": -1, "output": str(e)}

    async def _fix_test(
        self,
        test_file: str,
        error_output: str,
        test_code: str,
        spec_context: str = "",
        plan_context: str = "",
        attempt: int = 1,
    ) -> dict:
        """Use Agent to fix the test based on error output"""
        test_path = Path(test_file)

        # Build context section
        context_section = ""
        if spec_context:
            context_section += f"""
## ORIGINAL SPEC (What the test should do):
```markdown
{spec_context}
```
"""
        if plan_context:
            context_section += f"""
## TEST PLAN (Detailed steps):
```json
{plan_context}
```
"""

        prompt = f"""You are a Playwright test fixing expert. Fix this failing test.

{context_section}

## CURRENT TEST CODE:
```typescript
{test_code}
```

## ERROR OUTPUT (attempt {attempt}):
```
{error_output}
```

## INSTRUCTIONS:
1. **CRITICAL**: Clear ALL cookies/storage before debugging to ensure fresh state
2. Analyze the error carefully - understand WHY it failed
3. Use Playwright MCP tools to debug the page if needed (take snapshot, check elements)
4. Fix the test code by updating selectors, waits, or assertions
5. Write the fixed code back to the test file: {test_file}

## COMMON FIXES:
- **"strict mode violation"**: Use {{ exact: true }} or more specific selector
- **"element not found"**: Try different selector (getByRole, getByLabel, getByText with exact)
- **"timeout"**: Add waitForLoadState('networkidle') or increase timeout
- **"hidden"**: Wait for element to be visible first
- **"multiple elements"**: Use .first() or more specific text/role
- **"dialog blocking"**: If navigation times out, check for beforeunload dialogs:
  - Use `browser_handle_dialog` with `accept: true` to dismiss
  - Add dialog handler to test: `page.on('dialog', d => d.accept())`

## DEBUGGING TIPS:
- Use `mcp__playwright__browser_snapshot` to see current page state
- Check if element exists with different selector
- Verify page has finished loading

After fixing, output ONLY this JSON (no other text):
```json
{{
  "status": "fixed",
  "originalError": "Brief description of the error",
  "fixApplied": "Description of what was fixed",
  "codeChanges": "Summary of code changes"
}}
```

If you cannot fix it:
```json
{{
  "status": "failed",
  "originalError": "Description",
  "remainingIssues": ["Issue 1", "Issue 2"]
}}
```

Fix the test now.
"""

        try:
            logger.info("   AI analyzing failure and generating fix...")
            async for message in query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    allowed_tools=["*"],  # All tools including MCP and Write
                    setting_sources=["project"],
                    permission_mode="bypassPermissions",
                ),
            ):
                # Log tool uses for real-time feedback
                if hasattr(message, "type"):
                    if message.type == "tool_use":
                        tool_name = getattr(message, "name", "unknown")
                        if tool_name.startswith("mcp__playwright"):
                            action = tool_name.split("__")[-1] if "__" in tool_name else tool_name
                            logger.info(f"      {action}...")
                        else:
                            logger.info(f"      {tool_name}...")

                if hasattr(message, "result"):
                    result = message.result
                    fix_report = extract_json_from_markdown(result)

                    # Read the updated test code
                    updated_code = test_path.read_text()

                    if updated_code != test_code:
                        logger.info("Test file updated")
                        if fix_report.get("status") == "fixed":
                            logger.info(f"   Fix: {fix_report.get('fixApplied')}")

                    return fix_report

        except Exception as e:
            return {
                "status": "failed",
                "originalError": str(e),
                "remainingIssues": ["Validator error: " + str(e)],
            }


# Convenience function
async def validate_from_file(test_file: str, spec_file: str = None, plan_file: str = None) -> dict:
    """Validate and fix a test file"""
    validator = Validator()
    return await validator.validate_and_fix(test_file, spec_file=spec_file, plan_file=plan_file)


# CLI interface
async def main():
    """Run validator from command line"""
    if len(sys.argv) < 2:
        logger.error("Usage: python validator.py <test-file> [output-dir] [browser] [spec-file] [plan-file]")
        sys.exit(1)

    test_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) >= 3 else None
    browser = sys.argv[3] if len(sys.argv) >= 4 else "chromium"
    spec_file = sys.argv[4] if len(sys.argv) >= 5 else None
    plan_file = sys.argv[5] if len(sys.argv) >= 6 else None

    try:
        validator = Validator()
        result = await validator.validate_and_fix(
            test_file, output_dir, browser, spec_file=spec_file, plan_file=plan_file
        )

        logger.info("\n" + "=" * 80)
        logger.info("VALIDATION COMPLETE")
        logger.info("=" * 80)

        if result.get("status") == "success":
            logger.info(f"{result.get('message')}")
            logger.info(f"   Attempts: {result.get('attempts')}")
        else:
            logger.error(f"{result.get('message')}")
            if result.get("lastError"):
                logger.error(f"Last error:\n{result.get('lastError')}")

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    from orchestrator.logging_config import setup_logging

    setup_logging()
    asyncio.run(main())
