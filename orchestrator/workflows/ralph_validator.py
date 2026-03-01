"""
Ralph Validator Workflow - Enhanced validator with Ralph-style iteration
For complex test scenarios that need deeper debugging and architectural changes
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

from agents.base_agent import BaseAgent
from utils.json_utils import extract_json_from_markdown


class RalphValidator(BaseAgent):
    """
    Ralph-style validator with persistent iteration context.

    Key differences from standard Validator:
    - Higher max iterations (default 20 vs 3)
    - Maintains conversation history across attempts
    - Can make architectural changes if needed
    - Tracks detailed attempt history
    - Uses Ralph-style completion promises
    """

    def __init__(
        self,
        max_iterations: int = 20,
        completion_promise: str = "TESTS_PASSING",
        persistent_context: bool = True,
        use_native_healer: bool = False,
        hybrid_mode: bool = False,
        native_phase_iterations: int = 3,
    ):
        super().__init__()  # Initialize BaseAgent
        self.max_iterations = max_iterations
        self.completion_promise = completion_promise
        self.persistent_context = persistent_context
        self.use_native_healer = use_native_healer
        self.hybrid_mode = hybrid_mode
        self.native_phase_iterations = native_phase_iterations
        self.current_phase = "native" if hybrid_mode else None
        self.phase_transition_iteration = None
        self.conversation_history: list[dict] = []
        self.attempt_history: list[dict] = []

    async def validate_and_fix(
        self,
        test_file: str,
        output_dir: str = None,
        browser: str = "chromium",
        spec_file: str = None,
        plan_file: str = None,
    ) -> dict:
        """
        Run a test and fix any failures using Ralph-style iteration.

        Args:
            test_file: Path to the Playwright test file
            output_dir: Directory to save validation results
            browser: Browser project to run (chromium, firefox, webkit)
            spec_file: Optional original spec for context

        Returns:
            Dict containing validation results with full attempt history
        """
        logger.info("Ralph Validator initialized")
        logger.info(f"   Test: {test_file}")
        logger.info(f"   Browser: {browser}")
        logger.info(f"   Max iterations: {self.max_iterations}")
        logger.info(f"   Mode: {'Native Healer (test_run)' if self.use_native_healer else 'Ralph Loop'}")

        # Use native Playwright healer if enabled
        if self.use_native_healer:
            return await self._run_native_healer(test_file, output_dir, browser, spec_file, plan_file)

        # Read the test file
        test_path = Path(test_file)
        if not test_path.exists():
            raise FileNotFoundError(f"Test file not found: {test_file}")

        # Read original spec if available
        spec_context = ""
        if spec_file and Path(spec_file).exists():
            spec_context = Path(spec_file).read_text()

        # Read plan if available
        plan_context = ""
        if plan_file and Path(plan_file).exists():
            try:
                plan_data = json.loads(Path(plan_file).read_text())
                # Format plan steps for display
                steps = plan_data.get("steps", [])
                plan_lines = [f"Test: {plan_data.get('testName', 'Unknown')}"]
                for step in steps[:20]:  # Limit to first 20 steps
                    plan_lines.append(
                        f"  {step.get('step', '?')}. {step.get('action', 'unknown')} {step.get('target', '')}: {step.get('value', '')}"
                    )
                if len(steps) > 20:
                    plan_lines.append(f"  ... and {len(steps) - 20} more steps")
                plan_context = "\n".join(plan_lines)
                logger.info(f"   Loaded plan with {len(steps)} steps")
            except Exception as e:
                plan_context = f"(Failed to read plan: {e})"
                logger.warning(f"   Failed to load plan: {e}")
        else:
            if plan_file:
                logger.warning(f"   Plan file not found: {plan_file}")
            else:
                logger.info("   No plan file provided")

        validation_result = None
        conversation_context = self._build_initial_context(test_path, spec_context)
        test_code = test_path.read_text()  # Initialize test_code for change detection

        try:
            for iteration in range(1, self.max_iterations + 1):
                logger.info(f"\n{'─' * 80}")

                # Hybrid mode: Phase detection and transition
                if self.hybrid_mode:
                    if iteration <= self.native_phase_iterations:
                        self.current_phase = "native"
                        logger.info(
                            f"ITERATION {iteration}/{self.max_iterations} - PHASE: Native Healing ({iteration}/{self.native_phase_iterations})"
                        )
                    else:
                        if self.current_phase == "native":
                            # PHASE TRANSITION
                            logger.info(f"\n{'=' * 80}")
                            logger.info("PHASE TRANSITION: Native -> Ralph")
                            logger.info("   Native healing exhausted, escalating to Ralph mode")
                            logger.info(f"   Ralph iterations: {iteration}-{self.max_iterations}")
                            logger.info(f"{'=' * 80}\n")
                            self.current_phase = "ralph"
                            self.phase_transition_iteration = iteration
                            # Clear conversation history for fresh Ralph context
                            self.conversation_history = []
                        logger.info(
                            f"ITERATION {iteration}/{self.max_iterations} - PHASE: Ralph ({iteration - self.native_phase_iterations}/{self.max_iterations - self.native_phase_iterations})"
                        )
                else:
                    logger.info(f"ITERATION {iteration}/{self.max_iterations}")

                logger.info(f"{'─' * 80}")

                # Run the test
                logger.info("  -> Running test...")
                result = await self._run_test(test_file, output_dir, browser)

                # Record attempt
                attempt_record = {
                    "iteration": iteration,
                    "timestamp": datetime.now().isoformat(),
                    "passed": result.get("passed", False),
                    "exitCode": result.get("exitCode"),
                    "errorSummary": self._summarize_error(result.get("output", "")),
                }
                self.attempt_history.append(attempt_record)

                if result.get("passed"):
                    logger.info("PASSED")
                    validation_result = {
                        "status": "success",
                        "mode": "hybrid" if self.hybrid_mode else "ralph",
                        "iterations": iteration,
                        "testFile": test_file,
                        "browser": browser,
                        "message": f"Test passed after {iteration} iterations",
                        "attemptHistory": self.attempt_history,
                        "timestamp": datetime.now().isoformat(),
                    }

                    # Add hybrid-specific metadata
                    if self.hybrid_mode:
                        validation_result["phaseSucceeded"] = self.current_phase
                        validation_result["nativeIterations"] = min(iteration, self.native_phase_iterations)
                        if self.current_phase == "ralph":
                            validation_result["ralphIterations"] = iteration - self.native_phase_iterations

                    break

                # Test failed, attempt Ralph-style fix
                logger.error(f"FAILED (exit: {result.get('exitCode')})")
                error_summary = self._summarize_error(result.get("output", ""))
                logger.error(f"  -> Error: {error_summary[:80]}{'...' if len(error_summary) > 80 else ''}")

                if iteration < self.max_iterations:
                    logger.info("  -> Applying fix...")

                    try:
                        # Choose fixing strategy based on phase
                        if self.hybrid_mode and self.current_phase == "native":
                            # Phase 1: Native healing approach (fast)
                            fix_result = await self._native_fix_iteration(
                                test_file=test_file,
                                iteration=iteration,
                                result=result,
                                spec_context=spec_context,
                                plan_context=plan_context,
                            )
                        else:
                            # Phase 2 (Ralph) or standard Ralph mode (deep)
                            # Build context for this iteration
                            iteration_prompt = self._build_iteration_prompt(
                                test_file=test_file,
                                iteration=iteration,
                                result=result,
                                conversation_context=conversation_context,
                                attempt_history=self.attempt_history,
                                spec_context=spec_context,
                                plan_context=plan_context,
                            )

                            # Log prompt size for debugging
                            prompt_size = len(iteration_prompt)
                            if prompt_size > 10000:
                                logger.info(f" [large prompt: {prompt_size} chars]")

                            # Get agent response with persistent context
                            fix_result = await self._ralph_fix(
                                test_file=test_file, prompt=iteration_prompt, conversation_context=conversation_context
                            )

                        # Update conversation context if enabled
                        if self.persistent_context and fix_result.get("agent_response"):
                            conversation_context["history"].append(
                                {
                                    "role": "assistant",
                                    "content": fix_result.get("agent_response"),
                                    "iteration": iteration,
                                    "fixes_applied": fix_result.get("fixes", []),
                                }
                            )

                        if fix_result.get("status") == "fixed":
                            # Check if file was actually modified
                            new_code = test_path.read_text()
                            if new_code == test_code:
                                logger.warning("'Fixed' reported but file unchanged!")
                            else:
                                logger.info("Fixed, retrying...")
                                test_code = new_code  # Update for next iteration
                        else:
                            issues = fix_result.get("remainingIssues", ["Unknown issue"])
                            # Handle both list and string formats
                            if isinstance(issues, str):
                                issue_str = issues[:60] + "..." if len(issues) > 60 else issues
                            else:
                                issue_str = (
                                    str(issues[0])[:60] + "..."
                                    if issues and len(str(issues[0])) > 60
                                    else str(issues[0])
                                    if issues
                                    else "Unknown"
                                )
                            logger.warning(f"Fix failed: {issue_str}")
                    except Exception as fix_error:
                        import traceback

                        logger.error(f"Fix attempt crashed: {type(fix_error).__name__}: {str(fix_error)[:50]}")
                        # Continue to next iteration instead of crashing completely
                        continue
            else:
                # All iterations failed
                validation_result = {
                    "status": "failed",
                    "mode": "ralph",
                    "iterations": self.max_iterations,
                    "testFile": test_file,
                    "browser": browser,
                    "message": f"Failed after {self.max_iterations} Ralph iterations",
                    "lastError": result.get("output"),
                    "attemptHistory": self.attempt_history,
                    "timestamp": datetime.now().isoformat(),
                }
        except Exception as e:
            # Unexpected error during Ralph loop - capture it and save
            import traceback

            logger.error(f"Unexpected error in Ralph loop: {e}")
            validation_result = {
                "status": "crashed",
                "mode": "ralph",
                "iterations": len(self.attempt_history),
                "testFile": test_file,
                "browser": browser,
                "message": f"Ralph loop crashed: {str(e)}",
                "error": str(e),
                "traceback": traceback.format_exc(),
                "attemptHistory": self.attempt_history,
                "timestamp": datetime.now().isoformat(),
            }

        # Save validation result with full history (even if crashed)
        if output_dir:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Choose filename based on mode
            if self.hybrid_mode:
                validation_file = output_path / "hybrid_validation.json"
            elif self.use_native_healer:
                validation_file = output_path / "native_healer_validation.json"
            else:
                validation_file = output_path / "ralph_validation.json"

            with open(validation_file, "w") as f:
                json.dump(validation_result, f, indent=2)

            logger.info(f"Results saved: {validation_file}")

        return validation_result

    async def _native_fix_iteration(
        self, test_file: str, iteration: int, result: dict, spec_context: str, plan_context: str
    ) -> dict:
        """
        Single iteration of native healing using test_run + diagnostic tools.
        Lightweight, no persistent context, focused on quick selector fixes.
        """
        error_output = result.get("output", "")
        test_path = Path(test_file)
        test_path.read_text()

        native_prompt = f"""You are a Playwright test healer. Fix this failing test QUICKLY using test_run output analysis.

## TEST FILE: {test_file}

## CURRENT ERROR (Native Phase - Iteration {iteration}/3)
```
{error_output[:2000]}
```

## WORKFLOW
1. Analyze the error output above to identify the root cause (selector mismatch, timeout, assertion failure)
2. If needed, use browser_snapshot to inspect the current page state
3. Use browser_generate_locator to find correct selectors
4. Edit the test file with the fix
5. Output JSON result

## PRINCIPLES
- Focus ONLY on selector/timing fixes (use getByRole, getByLabel)
- Be FAST - don't overthink
- If issue is complex (not a selector), return {{"status": "failed"}} to escalate
- Never use deprecated APIs

## OUTPUT
```json
{{
  "status": "fixed",
  "fixApplied": "Changed login button selector from .btn to getByRole('button', {{name: 'Login'}})"
}}
```

OR if cannot fix quickly:
```json
{{
  "status": "failed",
  "remainingIssues": ["Complex architectural issue requiring Ralph"]
}}
```

Begin.
"""

        try:
            logger.info("    [NATIVE] Using test_run + diagnostics for quick fix...")

            agent_response = await self._query_agent(
                prompt=native_prompt,
                timeout_seconds=180,  # 3 minute timeout (increased from 2)
            )

            if agent_response and not agent_response.startswith("__TIMEOUT_PARTIAL__"):
                fix_data = extract_json_from_markdown(agent_response)
                return {
                    "status": fix_data.get("status", "fixed"),
                    "agent_response": agent_response,
                    "summary": fix_data.get("fixApplied", ""),
                    **fix_data,
                }
            else:
                return {"status": "failed", "remainingIssues": ["Native healer timed out"]}

        except Exception as e:
            logger.error(f"    [NATIVE ERROR] {str(e)}")
            return {"status": "failed", "remainingIssues": [f"Native fix error: {str(e)}"]}

    async def _run_native_healer(
        self,
        test_file: str,
        output_dir: str = None,
        browser: str = "chromium",
        spec_file: str = None,
        plan_file: str = None,
    ) -> dict:
        """
        Run Playwright's native healer using test_run + diagnostic MCP tools.

        This uses the Playwright Test Agents' approach:
        1. Run test_run to identify failures and error output
        2. Analyze errors, use browser_snapshot/console/network for deeper investigation
        3. Edit the test file to fix issues
        4. Continue until tests pass or skip unfixable tests
        """
        logger.info("Native Healer Mode - Using Playwright test_run + diagnostics")

        # Build prompt based on the healer agent definition
        healer_prompt = f"""You are the Playwright Test Healer, an expert test automation engineer.

## TEST FILE
{test_file}

## WORKFLOW
1. First, run `test_run` to identify failing tests and capture error output
2. Analyze the error output (error messages, stack traces, failed assertions)
3. If the error is unclear, use diagnostic tools for deeper investigation:
   - `browser_snapshot` to inspect the page state and available elements
   - `browser_console_messages` to check for JavaScript errors
   - `browser_network_requests` to verify API calls and responses
4. Use `browser_generate_locator` to find correct selectors
5. Edit the test file using the Write tool to fix issues
6. Re-run with `test_run` to verify the fix
7. Continue until the test passes

## AVAILABLE MCP TOOLS
- mcp__playwright-test__test_run - Run tests and capture error output
- mcp__playwright-test__browser_snapshot - Get page DOM snapshot
- mcp__playwright-test__browser_console_messages - Check browser console for errors
- mcp__playwright-test__browser_network_requests - Inspect network activity
- mcp__playwright-test__browser_generate_locator - Generate locator for element
- Write - Edit files

## PRINCIPLES
- Be systematic and thorough
- Prefer robust, maintainable solutions
- If test cannot be fixed, mark with test.fixme()
- Do not ask questions, fix the test

## BEGIN
Start by running: mcp__playwright-test__test_run with project="{browser}"
"""

        try:
            logger.info("  -> Invoking native healer agent...")

            # Use BaseAgent's query method with extended timeout
            agent_response = await self._query_agent(
                prompt=healer_prompt,
                timeout_seconds=600,  # 10 minutes for complex healing
            )

            # Parse result
            if agent_response:
                # Check for success indicators
                if "test passes" in agent_response.lower() or "all tests passed" in agent_response.lower():
                    logger.info("  Native healer succeeded")
                    validation_result = {
                        "status": "success",
                        "mode": "native_healer",
                        "testFile": test_file,
                        "browser": browser,
                        "message": "Test healed using Playwright native healer",
                        "agent_response": agent_response[:2000],  # Truncate for storage
                        "timestamp": datetime.now().isoformat(),
                    }
                elif "test.fixme" in agent_response.lower():
                    logger.warning("  Test marked as fixme (functionality broken)")
                    validation_result = {
                        "status": "skipped",
                        "mode": "native_healer",
                        "testFile": test_file,
                        "browser": browser,
                        "message": "Test marked as fixme - functionality broken",
                        "agent_response": agent_response[:2000],
                        "timestamp": datetime.now().isoformat(),
                    }
                else:
                    logger.error("  Native healer could not fix test")
                    validation_result = {
                        "status": "failed",
                        "mode": "native_healer",
                        "testFile": test_file,
                        "browser": browser,
                        "message": "Native healer could not resolve issues",
                        "agent_response": agent_response[:2000],
                        "timestamp": datetime.now().isoformat(),
                    }
            else:
                validation_result = {
                    "status": "failed",
                    "mode": "native_healer",
                    "testFile": test_file,
                    "browser": browser,
                    "message": "No response from native healer agent",
                    "timestamp": datetime.now().isoformat(),
                }

        except Exception as e:
            import traceback

            logger.error(f"  Native healer error: {e}")
            validation_result = {
                "status": "crashed",
                "mode": "native_healer",
                "testFile": test_file,
                "browser": browser,
                "message": f"Native healer crashed: {str(e)}",
                "error": str(e),
                "traceback": traceback.format_exc(),
                "timestamp": datetime.now().isoformat(),
            }

        # Save validation result
        if output_dir:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            validation_file = output_path / "native_healer_validation.json"
            with open(validation_file, "w") as f:
                json.dump(validation_result, f, indent=2)

        return validation_result

    def _build_initial_context(self, test_path: Path, spec_context: str) -> dict:
        """Build initial context for Ralph iteration"""
        return {
            "testFile": str(test_path),
            "originalCode": test_path.read_text(),
            "spec": spec_context,
            "history": [],
            "startTime": datetime.now().isoformat(),
        }

    def _build_iteration_prompt(
        self,
        test_file: str,
        iteration: int,
        result: dict,
        conversation_context: dict,
        attempt_history: list[dict],
        spec_context: str,
        plan_context: str = "",
    ) -> str:
        """Build the prompt for each Ralph iteration - uses test_run + diagnostic tools"""

        # Read current test code
        current_code = Path(test_file).read_text()

        # Analyze previous attempts
        previous_attempts_summary = ""
        if attempt_history:
            recent_failures = attempt_history[-5:]  # Last 5 attempts
            previous_attempts_summary = "\n".join(
                [f"  - Attempt {a['iteration']}: {a['errorSummary']}" for a in recent_failures]
            )

        # Truncate large outputs to prevent prompt overflow
        raw_output = result.get("output", "No output")
        noise_patterns = [
            "[dotenv",
            "injecting env",
            "Running 1 test",
            "using 1 worker",
            "tip:",
            "──────────",
        ]

        # Filter and keep meaningful lines
        filtered_lines = []
        for line in raw_output.split("\n"):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            if any(noise in line_stripped for noise in noise_patterns):
                continue
            filtered_lines.append(line)

        error_output = "\n".join(filtered_lines)
        if not error_output.strip():
            error_output = raw_output

        if len(error_output) > 3000:
            error_output = error_output[:3000] + "\n... (truncated)"

        # Truncate spec if too large
        spec_display = spec_context or "No spec provided"
        if len(spec_display) > 1500:
            spec_display = spec_display[:1500] + "\n... (spec truncated)"

        # Truncate code if too large
        code_display = current_code
        if len(current_code) > 4000:
            code_display = current_code[:2000] + "\n... (code truncated)\n" + current_code[-2000:]

        # Build Ralph-mode prompt using native tools
        prompt = f"""You are the Playwright test healer in DEEP REPAIR mode (Ralph Phase). Fix this failing test with thorough debugging and architectural changes if needed.

## TEST FILE
{test_file}

## CURRENT ERROR (Ralph Phase - Iteration {iteration}/{self.max_iterations})
```
{error_output}
```

## CURRENT TEST CODE
```typescript
{code_display}
```

## TEST SPEC
{spec_display}

## TEST PLAN
{plan_context or "(Analyze test code to understand intended flow)"}

## PREVIOUS ATTEMPTS
{previous_attempts_summary or "(First Ralph attempt)"}

## RALPH MODE WORKFLOW

You have MORE flexibility than Native mode. You can:
- Make architectural changes to the test structure
- Add waits, retries, and error handling
- Refactor test logic if needed
- Add debugging steps

**STEP 1: Run the test**
Run: test_run to execute the test and capture the full error output
- Parse the error message, stack trace, and failed assertions carefully

**STEP 2: Deep investigation (if error is unclear)**
Use: browser_snapshot to see all available elements on the page
Use: browser_console_messages to check for JavaScript errors
Use: browser_network_requests to verify API calls and responses
Use: browser_generate_locator to find robust selectors

**STEP 3: Analyze the root cause**
Consider:
- Is the selector wrong?
- Is there a timing issue (element not ready)?
- Is the test flow incorrect (missing steps)?
- Does the test need architectural changes?

**STEP 4: Apply comprehensive fix**
Use: Write tool to update {test_file}
You can:
- Fix selectors
- Add waitForLoadState, waitForSelector
- Restructure test steps
- Add try-catch blocks
- Add screenshots for debugging

**STEP 5: Report completion**
Output JSON:
```json
{{
  "status": "fixed",
  "fixApplied": "Detailed description of what was changed and why",
  "architecturalChanges": "true/false - did you restructure the test?"
}}
```

OR if you determine the test cannot be fixed (functionality is broken):
```json
{{
  "status": "failed",
  "remainingIssues": ["Detailed explanation of why test cannot pass"]
}}
```

## IMPORTANT NOTES
- Native mode already tried quick fixes and failed
- You have permission to make DEEP changes
- Take time to understand the root cause
- Don't just fix selectors - fix the underlying issue

Begin by running: test_run
"""
        return prompt

    def _format_conversation_history(self, history: list[dict]) -> str:
        """Format conversation history for prompt"""
        if not history:
            return "  (No previous conversation)"

        formatted = []
        for entry in history[-3:]:  # Last 3 entries
            role = entry.get("role", "unknown")
            iteration = entry.get("iteration", "?")
            content = entry.get("content", "")[:500]  # Truncate long content
            formatted.append(f"  [{role}] Iteration {iteration}: {content}...")

        return "\n".join(formatted)

    async def _ralph_fix(self, test_file: str, prompt: str, conversation_context: dict) -> dict:
        """Execute Ralph-style fix with agent using BaseAgent._query_agent"""

        try:
            # Debug: Log prompt size and first 500 chars
            logger.debug(f"Prompt length: {len(prompt)} chars")
            logger.debug(f"Prompt preview: {prompt[:300]}...")

            # Use BaseAgent's robust query method with a generous timeout
            logger.debug("Calling _query_agent with 420s timeout...")

            agent_response = await self._query_agent(
                prompt=prompt,
                timeout_seconds=420,  # 7 minutes for deep Ralph fixes (increased from 5)
            )

            # Debug: Log response
            response_preview = str(agent_response)[:500] if agent_response else "None"
            logger.debug(f"Agent response length: {len(str(agent_response)) if agent_response else 0}")
            logger.debug(f"Response preview: {response_preview}...")

            # Handle timeout partial responses
            if agent_response and agent_response.startswith("__TIMEOUT_PARTIAL__"):
                logger.warning("Agent timed out")
                return {"status": "failed", "remainingIssues": ["Agent query timed out after 5 minutes"]}

            if agent_response:
                fix_data = extract_json_from_markdown(agent_response)

                # Check if completion promise was output
                if self.completion_promise in agent_response:
                    logger.info(f"Completion promise detected: {self.completion_promise}")
                    fix_data["completion_detected"] = True

                return {
                    "status": fix_data.get("status", "fixed"),
                    "agent_response": agent_response,
                    "summary": fix_data.get("fixApplied", ""),
                    "fixes": fix_data.get("codeChanges", ""),
                    **fix_data,
                }

            return {
                "status": "failed",
                "agent_response": agent_response,
                "remainingIssues": ["No valid response from agent"],
            }

        except asyncio.CancelledError as ce:
            # Handle cancellation gracefully
            logger.warning(f"Agent query cancelled: {ce}")
            return {"status": "failed", "remainingIssues": [f"Agent cancelled: {str(ce)}"]}
        except Exception as e:
            import traceback

            error_msg = f"Agent error: {type(e).__name__}: {str(e)}"
            # Print first line of traceback for debugging
            tb_lines = traceback.format_exc().split("\n")
            for line in tb_lines:
                if "File" in line and "ralph_validator.py" not in line:
                    logger.error(f"    (at {line.strip()})")
                    break
            return {"status": "failed", "remainingIssues": [error_msg]}

    def _summarize_error(self, output: str) -> str:
        """Extract a brief error summary from full output"""
        import re

        # Lines to skip - these are noise, not actual errors
        skip_patterns = [
            r"Running \d+ test",
            r"using \d+ worker",
            r"\[dotenv",
            r"injecting env",
            r"^\s*$",
            r"^\s*\[",  # Lines starting with [
        ]

        # Priority error patterns - look for these first
        error_patterns = [
            (r"TimeoutError:.*", 10),
            (r"Error:.*", 9),
            (r"strict mode violation.*", 8),
            (r"element.*not found", 7),
            (r"Timeout \d+ms exceeded", 6),
            (r"locator\.\w+:.*", 5),
            (r"page\.\w+:.*Timeout", 4),
        ]

        lines = output.split("\n")

        # First pass: look for high-priority error patterns
        for pattern, _priority in sorted(error_patterns, key=lambda x: -x[1]):
            for line in lines:
                line_stripped = line.strip()
                # Skip noise lines
                if any(re.search(skip, line_stripped, re.IGNORECASE) for skip in skip_patterns):
                    continue
                if re.search(pattern, line_stripped, re.IGNORECASE):
                    # Clean up ANSI codes
                    clean_line = re.sub(r"\x1b\[[0-9;]*m", "", line_stripped)
                    return clean_line[:120] + "..." if len(clean_line) > 120 else clean_line

        # Second pass: look for lines with "Error" or "fail" keywords
        for line in lines:
            line_stripped = line.strip()
            if any(re.search(skip, line_stripped, re.IGNORECASE) for skip in skip_patterns):
                continue
            if re.search(r"(error|fail|timeout|exception)", line_stripped, re.IGNORECASE):
                clean_line = re.sub(r"\x1b\[[0-9;]*m", "", line_stripped)
                return clean_line[:120] + "..." if len(clean_line) > 120 else clean_line

        # Last resort: find any non-noise line
        for line in lines:
            line_stripped = line.strip()
            if any(re.search(skip, line_stripped, re.IGNORECASE) for skip in skip_patterns):
                continue
            if line_stripped:
                clean_line = re.sub(r"\x1b\[[0-9;]*m", "", line_stripped)
                return clean_line[:120] + "..." if len(clean_line) > 120 else clean_line

        return "Unknown error"

    async def _run_test(self, test_file: str, output_dir: str = None, browser: str = "chromium") -> dict:
        """Run a Playwright test and return the result"""
        import subprocess

        try:
            cmd = f"npx playwright test '{test_file}' --reporter=list,html --project {browser} --timeout=120000"
            if output_dir:
                results_dir = Path(output_dir) / "test-results"
                report_dir = Path(output_dir) / "report"
                cmd = f"PLAYWRIGHT_OUTPUT_DIR='{results_dir}' PLAYWRIGHT_HTML_REPORT='{report_dir}' {cmd}"

            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=150,  # Longer timeout for Ralph mode (120s test + 30s buffer)
            )

            output = result.stdout + result.stderr
            passed = result.returncode == 0 and ("passed" in output)

            return {"passed": passed, "exitCode": result.returncode, "output": output}

        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "exitCode": -1,
                "output": "Test timed out after 150 seconds",
            }
        except Exception as e:
            return {"passed": False, "exitCode": -1, "output": str(e)}


# Convenience function
async def ralph_validate(test_file: str, max_iterations: int = 20, completion_promise: str = "TESTS_PASSING") -> dict:
    """Validate and fix a test file using Ralph-style iteration"""
    validator = RalphValidator(max_iterations=max_iterations, completion_promise=completion_promise)
    return await validator.validate_and_fix(test_file)


# CLI interface
async def main():
    """Run Ralph validator from command line"""
    if len(sys.argv) < 2:
        logger.error(
            "Usage: python ralph_validator.py <test-file> [output-dir] [browser] [max-iterations] [plan-file] [spec-file] [native-healer] [hybrid]"
        )
        logger.error("Options:")
        logger.error("  test-file      Path to the Playwright test file")
        logger.error("  output-dir     Directory for results (default: runs/TIMESTAMP)")
        logger.error("  browser        Browser to run (chromium, firefox, webkit) - default: chromium")
        logger.error("  max-iterations Maximum iterations (default: 20)")
        logger.error("  plan-file      Path to plan.json for test context (optional)")
        logger.error("  spec-file      Path to spec.md for test context (optional)")
        logger.error("  native-healer  Use native healer mode (true/false) - default: false")
        logger.error("  hybrid         Use hybrid mode (true/false) - default: false")
        sys.exit(1)

    test_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) >= 3 else f"runs/ralph_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    browser = sys.argv[3] if len(sys.argv) >= 4 else "chromium"
    max_iterations = int(sys.argv[4]) if len(sys.argv) >= 5 else 20
    plan_file = sys.argv[5] if len(sys.argv) >= 6 else None
    spec_file = sys.argv[6] if len(sys.argv) >= 7 else None
    native_healer = sys.argv[7].lower() == "true" if len(sys.argv) >= 8 else False
    hybrid = sys.argv[8].lower() == "true" if len(sys.argv) >= 9 else False

    validator = None
    try:
        validator = RalphValidator(max_iterations=max_iterations, use_native_healer=native_healer, hybrid_mode=hybrid)
        result = await validator.validate_and_fix(
            test_file, output_dir, browser, plan_file=plan_file, spec_file=spec_file
        )

        # Final summary
        logger.info("\n" + "=" * 80)
        if result.get("status") == "success":
            mode_str = "Hybrid" if hybrid else ("Native" if native_healer else "Ralph")
            logger.info(f"{mode_str} Validation PASSED - {result.get('iterations')}/{max_iterations} iterations")

            if hybrid:
                phase = result.get("phaseSucceeded", "unknown")
                logger.info(f"   Phase: {phase.title()}")
                if phase == "ralph":
                    logger.info(f"   Native attempts: {result.get('nativeIterations', 0)}")
                    logger.info(f"   Ralph iterations: {result.get('ralphIterations', 0)}")
        else:
            mode_str = "Hybrid" if hybrid else ("Native" if native_healer else "Ralph")
            logger.error(f"{mode_str} Validation FAILED - exhausted {max_iterations} iterations")
        logger.info("=" * 80)

        # Show attempt summary
        logger.info("Attempt Summary:")
        for attempt in result.get("attemptHistory", []):
            status = "PASS" if attempt.get("passed") else "FAIL"
            logger.info(f"  {status} Iteration {attempt.get('iteration')}: {attempt.get('errorSummary', 'Success')}")

    except BaseException as e:
        # Catch ALL exceptions including SystemExit and KeyboardInterrupt
        logger.error(f"CRITICAL ERROR: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()

        # Emergency save if validator exists
        if validator and hasattr(validator, "attempt_history") and validator.attempt_history:
            try:
                logger.warning("Attempting emergency save of partial results...")
                output_path = Path(output_dir)
                output_path.mkdir(parents=True, exist_ok=True)
                validation_file = output_path / "ralph_validation.json"

                validation_result = {
                    "status": "crashed",
                    "mode": "ralph",
                    "iterations": len(validator.attempt_history),
                    "testFile": test_file,
                    "browser": browser,
                    "message": f"Ralph loop crashed (caught in main): {type(e).__name__}: {str(e)}",
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                    "attemptHistory": validator.attempt_history,
                    "timestamp": datetime.now().isoformat(),
                }
                with open(validation_file, "w") as f:
                    json.dump(validation_result, f, indent=2)
                logger.info(f"Partial result saved to: {validation_file}")
            except Exception as save_err:
                logger.error(f"Failed to save partial result: {save_err}")

        sys.exit(1)


if __name__ == "__main__":
    from orchestrator.logging_config import setup_logging

    setup_logging()
    asyncio.run(main())
