"""
Native Healer Workflow - Debugs and Fixes Failing Playwright Tests

This workflow uses the Playwright Test Healer agent to:
1. Run failing tests and analyze error output
2. Analyze errors with browser snapshot context
3. Fix selectors, timing issues, or assertion failures
4. Verify the fix passes
"""

import asyncio
import json
import logging
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class HealerTimeoutError(Exception):
    """Raised when the healer agent times out."""

    pass


def _optional_env_float(name: str) -> float | None:
    value = os.environ.get(name)
    if not value:
        return None
    return float(value)


# Add orchestrator to path
sys.path.append(str(Path(__file__).parent.parent.parent))

# Load Claude credentials and SDK
from orchestrator.load_env import setup_claude_env

setup_claude_env()

# Use run-specific config directory if set (for parallel execution isolation)
config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
if config_dir:
    os.chdir(config_dir)

from orchestrator.ai.prompt_registry import (
    attach_prompt_metadata,
    build_prompt_metadata,
)
from orchestrator.utils.agent_runner import AgentResult, AgentRunner
from orchestrator.utils.agent_tool_allowlists import get_agent_tool_config
from orchestrator.utils.token_budget import (
    context_budget_for_stage,
    truncate_text_to_tokens,
)
from orchestrator.utils.text_utils import truncate_middle


class NativeHealer:
    """
    Playwright Test Healer that automatically fixes failing tests.

    Flow:
    1. Use test_debug to reproduce the exact failing test state
    2. Analyze the paused failure state with browser evidence
    3. Use diagnostic tools (browser_snapshot, console_messages, network_requests) if needed
    4. Edit the test code to fix the issue
    5. Re-run to verify the fix
    """

    def __init__(
        self,
        on_tool_use: Callable[[str, dict[str, Any]], None] | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        on_task_enqueued: Callable[[str], None] | None = None,
        owner_type: str | None = None,
        owner_id: str | None = None,
        owner_label: str | None = None,
        model_tier: str = "tool_deep",
        env_vars: dict[str, str] | None = None,
        cwd: Path | str | None = None,
    ):
        self.on_tool_use = on_tool_use
        self.on_progress = on_progress
        self.on_task_enqueued = on_task_enqueued
        self.owner_type = owner_type
        self.owner_id = owner_id
        self.owner_label = owner_label
        self.model_tier = model_tier
        self.env_vars = dict(env_vars or {})
        self.cwd = Path(cwd) if cwd else None
        self._last_timed_out = False
        self.last_agent_output: str | None = None
        self.last_agent_result: AgentResult | None = None
        self.last_tool_calls: list[dict[str, Any]] = []

    async def heal_test(
        self,
        test_file: str,
        error_log: str | None = None,
        timeout_seconds: int | None = None,
        diagnosis_context: str | None = None,
        memory_run_id: str | None = None,
        attempt_context: str | None = None,
        attempt_number: int | None = None,
        browser: str | None = None,
        failure_metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """
        Attempt to heal a failing test.

        Args:
            test_file: Path to the failing test file
            error_log: Optional error output from previous run
            attempt_context: Condensed history of prior healing attempts
            attempt_number: 1-based index of this healing attempt

        Returns:
            Fixed test content or None if healing failed
        """
        path_obj = Path(test_file)
        if not path_obj.exists():
            raise FileNotFoundError(f"Test file not found: {test_file}")

        test_content = path_obj.read_text()

        logger.info(f"Healing test: {test_file}")

        # Build prompt for the Healer agent
        prompt = self._build_healer_prompt(
            test_file=test_file,
            test_content=test_content,
            error_log=error_log,
            diagnosis_context=diagnosis_context,
            memory_run_id=memory_run_id,
            attempt_context=attempt_context,
            attempt_number=attempt_number,
            browser=browser,
            failure_metadata=failure_metadata,
        )

        # Invoke the Healer Agent
        logger.info("Invoking Playwright Healer Agent...")
        result = await self._query_healer_agent(prompt, timeout_seconds=timeout_seconds)
        self.last_agent_output = result
        agent_result = self.last_agent_result

        if self._last_timed_out:
            raise HealerTimeoutError(
                f"Healer timed out after {timeout_seconds or 'default'}s"
            )

        # Check if file was modified by the agent
        new_content = path_obj.read_text()
        if new_content != test_content:
            logger.info(f"Test healed and saved: {test_file}")
            self._capture_successful_healing_memory(
                test_file=test_file,
                error_log=error_log,
                diagnosis_context=diagnosis_context,
                healer_output=result,
                content_before=test_content,
                content_after=new_content,
            )
            return new_content

        # Fallback: If agent returned fixed code but didn't write it
        if result and ("test(" in result or "test.describe" in result):
            fixed_code = self._extract_code(result)
            if fixed_code:
                path_obj.write_text(fixed_code)
                logger.info(f"Applied fix to: {test_file}")
                self._capture_successful_healing_memory(
                    test_file=test_file,
                    error_log=error_log,
                    diagnosis_context=diagnosis_context,
                    healer_output=result,
                    content_before=test_content,
                    content_after=fixed_code,
                )
                return fixed_code

        retry_content = await self._retry_healer_format(
            test_file=path_obj,
            original_content=test_content,
            validation_error="healer did not modify the file or return a valid complete Playwright TypeScript test",
            previous_output=result or "",
            previous_result=agent_result,
        )
        if retry_content:
            self._capture_successful_healing_memory(
                test_file=test_file,
                error_log=error_log,
                diagnosis_context=diagnosis_context,
                healer_output=retry_content,
                content_before=test_content,
                content_after=retry_content,
            )
            return retry_content

        logger.warning("Healing completed but no changes detected")
        return None

    @staticmethod
    def _healer_schema_max_attempts() -> int:
        raw_value = os.environ.get("HEALER_SCHEMA_MAX_ATTEMPTS", "2")
        try:
            return min(5, max(1, int(raw_value)))
        except ValueError:
            return 2

    async def _retry_healer_format(
        self,
        *,
        test_file: Path,
        original_content: str,
        validation_error: str,
        previous_output: str,
        previous_result: AgentResult | None,
    ) -> str | None:
        max_attempts = self._healer_schema_max_attempts()
        if max_attempts <= 1 or previous_result is None:
            return None

        current_error = validation_error
        current_output = previous_output or ""
        for attempt_number in range(2, max_attempts + 1):
            logger.info(
                "Retrying healer output format after validation failure (%s/%s)",
                attempt_number,
                max_attempts,
            )
            prompt = self._build_healer_format_retry_prompt(
                test_file=test_file,
                original_content=original_content,
                validation_error=current_error,
                previous_output=current_output,
            )
            retry_result = await self._query_healer_format_retry_agent(
                prompt,
            )
            current_output = retry_result.output or ""
            fixed_code = self._extract_code(current_output)
            if not fixed_code or not self._looks_like_playwright_test(fixed_code):
                current_error = "retry output did not contain a valid complete Playwright TypeScript test"
                continue
            test_file.write_text(fixed_code.rstrip() + "\n")
            logger.info("Healer format retry accepted: %s", test_file)
            return fixed_code.rstrip() + "\n"
        logger.warning("Healer format retry failed: %s", current_error)
        return None

    @staticmethod
    def _looks_like_playwright_test(code: str) -> bool:
        return (
            ("test(" in code or "test.describe" in code)
            and ("@playwright/test" in code or "fixtures/test-data" in code)
            and "```" not in code
        )

    def _build_healer_format_retry_prompt(
        self,
        *,
        test_file: Path,
        original_content: str,
        validation_error: str,
        previous_output: str,
    ) -> str:
        return f"""You are correcting a rejected Playwright healing result.

This is a clean artifact-driven schema/format correction turn, not a new healing investigation.
Do not browse, do not call tools, do not run tests, do not start or close a browser, and do not depend on prior Claude conversation state.

Validation failure:
{validation_error}

Return exactly one complete fixed Playwright TypeScript test file for:
{test_file}

Rules:
- Return only a ```typescript code block.
- Preserve the original test intent and imports unless the previous output clearly repaired them.
- Include at least one `test(...)` or `test.describe(...)`.
- Do not include markdown outside the code block.

## Current Test File
```typescript
{truncate_middle(original_content, head=5000, tail=5000)}
```

## Previous Healer Output
```text
{truncate_middle(previous_output or "", head=4000, tail=4000)}
```
"""

    async def _query_healer_format_retry_agent(
        self,
        prompt: str,
        *,
        resume_session_id: str | None = None,
        continue_conversation: bool = False,
    ) -> AgentResult:
        timeout = int(os.environ.get("HEALER_SCHEMA_RETRY_TIMEOUT_SECONDS", "180"))
        runner = AgentRunner(
            timeout_seconds=timeout,
            allowed_tools=[],
            tools=[],
            log_tools=False,
            on_progress=self.on_progress,
            on_task_enqueued=self.on_task_enqueued,
            owner_type=self.owner_type,
            owner_id=self.owner_id,
            owner_label=self.owner_label,
            model_tier=self.model_tier,
            memory_agent_type="NativeHealer",
            memory_source_type="test_file",
            memory_stage="native_healer_schema_retry",
            inject_memory=False,
            capture_memory=False,
            env_vars=self.env_vars,
            cwd=self.cwd,
            requires_live_browser=False,
            resume_session_id=None,
            continue_conversation=False,
            force_direct_execution=True,
        )
        return await runner.run(prompt)

    def _build_healer_prompt(
        self,
        test_file: str,
        test_content: str,
        error_log: str | None,
        diagnosis_context: str | None = None,
        memory_run_id: str | None = None,
        attempt_context: str | None = None,
        attempt_number: int | None = None,
        browser: str | None = None,
        failure_metadata: dict[str, Any] | None = None,
    ) -> str:
        """Build prompt for the playwright-test-healer agent."""

        error_section = ""
        if error_log:
            error_budget = context_budget_for_stage("healer_error_log", 1800)
            error_section = f"""
## Previous Error Output
```
{truncate_text_to_tokens(error_log, error_budget)}
```
"""

        attempt_section = ""
        if attempt_number:
            attempt_section = f"\nThis is healing attempt {attempt_number} of 3.\n"
        if attempt_context:
            attempt_section += f"""
## Prior Healing Attempts (do not repeat failed fixes)
{attempt_context}
"""

        diagnosis_section = ""
        if diagnosis_context:
            diagnosis_section = f"""
## Failure Triage Context
Use this diagnosis to focus your investigation. If your live debugging contradicts it, prefer the live evidence and explain the correction in your final response.

{diagnosis_context}
"""

        failure_metadata = failure_metadata or {}
        failed_title = failure_metadata.get("title") or failure_metadata.get(
            "full_title"
        )
        failure_section = f"""
## Failed Test Target
- Browser/project: `{browser or failure_metadata.get("project") or "unknown"}`
- File: `{failure_metadata.get("file") or test_file}`
- Title: `{failed_title or "unknown"}`
- Retry: `{failure_metadata.get("retry", "unknown")}`
- Primary error: `{failure_metadata.get("primary_error") or "unknown"}`
"""

        test_data_section = ""
        fixture_file = (self.env_vars or {}).get("QUORVEX_TEST_DATA_FILE")
        if fixture_file:
            refs = self._runtime_fixture_refs(fixture_file)
            import_path = self._fixture_import_path(test_file)
            lines = [
                "## Project Test Data Fixture",
                f"Runtime fixture file: `{fixture_file}`",
                f"Import fixture test/expect from `{import_path}` when repairing test-data code.",
                "Use `testData.get('<canonical-ref>')` or `testData.field('<canonical-ref>', '<path>')` for project test data.",
                "Never write `process.env.TESTDATA_*` in the test file.",
            ]
            for ref in refs:
                lines.append(f"- Available ref: `{ref}`")
            test_data_section = "\n" + "\n".join(lines) + "\n"

        memory_section = self._build_memory_context_section(
            query=f"{test_file}\n{error_log or ''}\n{diagnosis_context or ''}\n{test_content[:1600]}",
            project_id=os.environ.get("MEMORY_PROJECT_ID")
            or os.environ.get("PROJECT_ID"),
            source_id=test_file,
            run_id=memory_run_id,
        )
        test_context = self._healer_test_context(test_content, error_log=error_log)

        prompt = f"""You are the Playwright Test Healer.

# Task: Debug and Fix Failing Test

## Test File: {test_file}

```typescript
{test_context}
```

{attempt_section}
{error_section}
{diagnosis_section}
{failure_section}
{test_data_section}
{memory_section}

## Your Workflow

1. **Identify the exact failed test first**: If the failed test id/title is present in the metadata above, use it. If it is unknown or ambiguous, call `test_list` scoped to this file and browser/project `{browser or "the failed project"}` to find the matching failed test id/title before debugging.
2. **Reproduce the exact failed state with `test_debug`**: When an exact failed test id/title is known, call `test_debug` scoped to this file, browser/project `{browser or "the failed project"}`, and title/id `{failed_title or "the failed title"}`. `test_debug` is the failure-state capture path because it pauses on the failed test state.
3. **Keep the paused debug browser open**: Do not call `browser_close`. Test runs may close automatically after completion, but a paused `test_debug` browser is evidence and must remain available until you have inspected it. The orchestrator owns cleanup after the attempt.
4. **Capture failure-state evidence before editing**: Only after `test_debug` has paused, use `browser_snapshot`, `browser_console_messages`, `browser_network_requests`, `browser_generate_locator`, `browser_evaluate`, or tracing tools as needed. Use `browser_resume` only after capturing paused-state evidence and only when you need the same paused script to continue to the next action, assertion, or failure.
5. **Use category-specific evidence before editing**:
   - Selector or timing failures: use `browser_snapshot` or `browser_generate_locator` before changing selectors, waits, or assertions.
   - Authentication, test-data, API, or server failures: use `browser_network_requests` or `browser_console_messages` before changing setup, data, navigation, or assertions.
6. **Analyze the error**: Parse the previous error output and `test_debug` failure details (error message, stack trace, failed assertions) and compare them to the paused browser evidence.
7. **Diagnose**: Determine the root cause:
   - Element selectors that may have changed
   - Timing and synchronization issues
   - Assertion failures
   - Data dependencies
8. **Fix the code**: Use `Edit` or `MultiEdit` to update the test only after the evidence above is captured.
9. **Verify**: Run the test again with `test_debug` when you still need paused-state evidence, or `test_run` for final pass/fail confirmation.

## Dialog Handling (CRITICAL)
When browser dialogs appear (alerts, confirms, or "Leave site?" beforeunload dialogs):
- Use `browser_handle_dialog` with `accept: true` IMMEDIATELY to accept Leave and continue navigation
- Treat unsaved changes and beforeunload prompts as "Leave site?" dialogs unless the user explicitly asked you to preserve draft data
- After handling a dialog, call `browser_snapshot` or `browser_take_screenshot` to verify page state

## Key Principles

- Be systematic - fix one error at a time
- Prefer robust, maintainable solutions
- Use Playwright best practices
- Preserve the debug browser state; do not close it manually after `test_debug`.
- Preserve test intent. Do not remove assertions to make the test pass. If the behavior is genuinely not testable, use an explicit `test.fixme()` with a reason.
- In your final response, include `strategy: ...`, `root_cause: ...`, and `changed_selectors: ...`.
- If a test cannot be fixed, mark it with `test.fixme()` and explain why
- Never use deprecated APIs like `waitForNetworkIdle`

Start with `test_list` only if needed to identify the failed test. Otherwise start with the exact scoped `test_debug`.
"""
        metadata = build_prompt_metadata(
            prompt_id="native_healer.playwright",
            version="2026-06-11.1",
            stage="test_healing",
            schema_name="playwright_healing.v1",
            rendered_prompt=prompt,
        )
        return attach_prompt_metadata(prompt, metadata)

    def _build_memory_context_section(
        self,
        *,
        query: str,
        project_id: str | None,
        source_id: str,
        run_id: str | None = None,
    ) -> str:
        if os.environ.get("MEMORY_ENABLED", "true").lower() != "true" or not project_id:
            return ""
        try:
            from orchestrator.memory.agent_memory import get_agent_memory_service
            from orchestrator.memory.context_builder import MemoryContextBuilder
            from orchestrator.memory.telemetry import record_memory_injection

            builder = MemoryContextBuilder(service=get_agent_memory_service())
            bundle = builder.build_bundle(
                query=query[:2000],
                project_id=project_id,
                agent_type="NativeHealer",
                limit=8,
            )
            token_budget = context_budget_for_stage("native_healer", 1200)
            context = builder.format_prompt_context(bundle, token_budget=token_budget)
            if not context:
                return ""
            bundle_dict = bundle.to_dict()
            ranking = (bundle_dict.get("unified") or {}).get("ranking") or {}
            record_memory_injection(
                project_id=project_id,
                actor_type="agent",
                stage="native_healer",
                query=query[:1000],
                bundle=bundle_dict,
                context_text=context,
                source_type="test_file",
                source_id=source_id,
                extra_data={
                    "test_path": source_id,
                    **({"run_id": run_id} if run_id else {}),
                    "empty_recall": not bool(ranking.get("selected_items")),
                    "memory_score_summary": ranking.get("score_summary", {}),
                    "context_budget_tokens": token_budget,
                },
            )
            return f"""
## Memory Context
Use this memory as advisory debugging context. If remembered selectors, routes, or fixes conflict with test_run/browser evidence, prefer the live evidence and update the test accordingly.

{context}
"""
        except Exception as exc:
            logger.debug("Healer memory context skipped: %s", exc)
            return ""

    @staticmethod
    def _healer_test_context(test_content: str, *, error_log: str | None = None) -> str:
        if os.environ.get("HEALER_FULL_FILE_CONTEXT", "0") == "1":
            return test_content
        lines = test_content.splitlines()
        if not lines:
            return ""
        target_line = NativeHealer._failed_line_number(error_log)
        if target_line is None:
            match = re.search(
                r"\b(?:Error|Timeout|expect|locator|click|fill|goto)\b",
                error_log or "",
                re.IGNORECASE,
            )
            target_line = 1 if match else min(len(lines), max(1, len(lines) // 2))
        radius = int(os.environ.get("HEALER_CODE_FRAME_RADIUS", "35") or "35")
        start = max(1, target_line - radius)
        end = min(len(lines), target_line + radius)
        framed = [f"{idx}: {lines[idx - 1]}" for idx in range(start, end + 1)]
        prefix = [
            f"// Compact healer context for {len(lines)}-line test file.",
            f"// Showing lines {start}-{end}. Set HEALER_FULL_FILE_CONTEXT=1 to include the full file.",
        ]
        return "\n".join(prefix + framed)

    @staticmethod
    def _failed_line_number(error_log: str | None) -> int | None:
        if not error_log:
            return None
        patterns = (
            r":(\d+):\d+\)?",
            r"line\s+(\d+)",
        )
        for pattern in patterns:
            match = re.search(pattern, error_log, re.IGNORECASE)
            if match:
                try:
                    return max(1, int(match.group(1)))
                except ValueError:
                    continue
        return None

    def _fixture_import_path(self, test_file: str) -> str:
        fixture_path = (
            Path(__file__).resolve().parent.parent.parent
            / "tests"
            / "fixtures"
            / "test-data"
        )
        relative = os.path.relpath(fixture_path, Path(test_file).parent)
        relative = Path(relative).as_posix()
        if not relative.startswith("."):
            relative = f"./{relative}"
        return relative

    def _runtime_fixture_refs(self, fixture_file: str) -> list[str]:
        try:
            payload = json.loads(Path(fixture_file).read_text())
            items = payload.get("items") if isinstance(payload, dict) else {}
            if isinstance(items, dict):
                return sorted(str(ref) for ref in items)
        except Exception as exc:
            logger.debug("Could not read runtime test data fixture refs: %s", exc)
        return []

    def _capture_successful_healing_memory(
        self,
        *,
        test_file: str,
        error_log: str | None,
        diagnosis_context: str | None,
        healer_output: str | None,
        content_before: str | None = None,
        content_after: str | None = None,
    ) -> None:
        project_id = os.environ.get("MEMORY_PROJECT_ID") or os.environ.get("PROJECT_ID")
        if os.environ.get("MEMORY_ENABLED", "true").lower() != "true" or not project_id:
            return
        try:
            from orchestrator.memory.agent_memory import get_agent_memory_service

            text = "\n".join(
                part
                for part in [
                    f"Root cause / failure pattern from healed test {test_file}.",
                    f"Previous error: {(error_log or '')[:1800]}",
                    f"Failure triage: {(diagnosis_context or '')[:1200]}",
                    f"Known fix is reflected in healer output: {(healer_output or '')[:1800]}",
                    "Lesson learned: next time, validate remembered selectors against live browser evidence before editing.",
                ]
                if part.strip()
            )
            service = get_agent_memory_service()
            service.create_memory(
                kind="failure_pattern",
                content=text[:1200],
                project_id=project_id,
                confidence=0.78,
                importance=0.7,
                tags=["healer", "failure"],
                source_type="native_healer",
                source_id=test_file,
                agent_type="NativeHealer",
                review_required=True,
            )
            selector_delta = self._selector_delta(content_before, content_after)
            if selector_delta:
                service.create_memory(
                    kind="agent_lesson",
                    content=f"Selector fix in {Path(test_file).name}: {selector_delta}"[
                        :1200
                    ],
                    project_id=project_id,
                    confidence=0.8,
                    importance=0.7,
                    tags=["healer", "selector_fix"],
                    source_type="native_healer",
                    source_id=test_file,
                    agent_type="NativeHealer",
                    review_required=True,
                )
            # Also let the consolidator extract any explicit lessons from the agent output.
            # Run the deterministic path synchronously by using existing heuristics directly.
            for memory in service.extract_candidates(
                healer_output or "", agent_type="NativeHealer"
            ):
                service.create_memory(
                    kind=memory.kind,
                    content=memory.content,
                    project_id=project_id,
                    tags=memory.tags,
                    confidence=memory.confidence,
                    source_type="native_healer",
                    source_id=test_file,
                    agent_type="NativeHealer",
                    review_required=True,
                )
        except Exception as exc:
            logger.debug("Healer memory capture skipped: %s", exc)

    @staticmethod
    def _selector_delta(
        content_before: str | None, content_after: str | None
    ) -> str | None:
        """Describe selector changes between pre- and post-heal test content."""
        if not content_before or not content_after:
            return None
        try:
            from orchestrator.memory.selector_writeback import extract_selectors

            before = {
                s["playwright_selector"] for s in extract_selectors(content_before)
            }
            after = {s["playwright_selector"] for s in extract_selectors(content_after)}
            removed = sorted(before - after)
            added = sorted(after - before)
            if not removed and not added:
                return None
            parts = []
            if removed and added:
                parts.append(f"{', '.join(removed[:3])} -> {', '.join(added[:3])}")
            elif added:
                parts.append(f"added {', '.join(added[:3])}")
            else:
                parts.append(f"removed {', '.join(removed[:3])}")
            return "; ".join(parts)
        except Exception as exc:
            logger.debug("Selector delta extraction skipped: %s", exc)
            return None

    async def _query_healer_agent(
        self, prompt: str, timeout_seconds: int | None = None
    ) -> str:
        """
        Query the Playwright Healer agent using the unified AgentRunner.
        """
        self._last_timed_out = False
        self.last_tool_calls = []

        effective_timeout = timeout_seconds or int(
            os.environ.get(
                "HEALER_TIMEOUT_SECONDS",
                os.environ.get("AGENT_TIMEOUT_SECONDS", "1800"),
            )
        )

        try:
            tool_config = get_agent_tool_config(
                "playwright-test-healer", mcp_config_dir=self.cwd
            )
            runner = AgentRunner(
                timeout_seconds=effective_timeout,
                allowed_tools=tool_config.get("allowed_tools") or [],
                tools=tool_config.get("tools"),
                disallowed_tools=tool_config.get("disallowed_tools"),
                log_tools=True,
                on_tool_use=self.on_tool_use,
                on_progress=self.on_progress,
                on_task_enqueued=self.on_task_enqueued,
                owner_type=self.owner_type,
                owner_id=self.owner_id,
                owner_label=self.owner_label,
                model_tier=self.model_tier,
                max_budget_usd=_optional_env_float("HEALER_MAX_BUDGET_USD"),
                memory_agent_type="NativeHealer",
                memory_source_type="test_file",
                memory_stage="native_healer",
                inject_memory=False,
                env_vars=self.env_vars,
                cwd=self.cwd,
                preserve_browser_on_failure=True,
            )
            result = await runner.run(prompt)
            self.last_agent_result = result
            self._last_timed_out = result.timed_out
            self.last_tool_calls = self._serialize_tool_calls(result.tool_calls)

            logger.info(
                f"Healer stats: {result.messages_received} messages, "
                f"{len(result.tool_calls)} tool calls, "
                f"{result.duration_seconds:.1f}s"
            )
            if result.timed_out:
                logger.warning(f"Healer agent timed out after {effective_timeout}s")
            if not result.success and result.error:
                logger.warning(f"Healer agent error: {result.error}")
            return result.output

        except asyncio.TimeoutError:
            logger.warning(f"Healer agent timed out after {effective_timeout}s")
            self._last_timed_out = True
            self.last_tool_calls = []
            return ""
        except Exception as exc:
            error_str = str(exc).lower()
            if "cancel scope" in error_str or "cancelled" in error_str:
                logger.info(f"SDK cleanup warning (ignored): {type(exc).__name__}")
                return ""
            logger.error(f"Healer agent error: {exc}")
            raise

    @staticmethod
    def _serialize_tool_calls(tool_calls: list[Any] | None) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        for call in tool_calls or []:
            if isinstance(call, str):
                serialized.append({"name": call})
                continue
            name = getattr(call, "name", None)
            if not name:
                continue
            timestamp = getattr(call, "timestamp", None)
            serialized.append(
                {
                    "name": str(name),
                    "timestamp": (
                        timestamp.isoformat()
                        if hasattr(timestamp, "isoformat")
                        else None
                    ),
                    "duration_ms": getattr(call, "duration_ms", None),
                    "success": getattr(call, "success", True),
                    "error": getattr(call, "error", None),
                    "input": NativeHealer._redact_tool_input(
                        getattr(call, "input", None)
                    ),
                }
            )
        return serialized

    @staticmethod
    def _redact_tool_input(
        value: Any, *, key: str | None = None, depth: int = 0
    ) -> Any:
        sensitive_parts = (
            "password",
            "passwd",
            "secret",
            "token",
            "api_key",
            "apikey",
            "authorization",
            "auth",
            "credential",
            "private_key",
        )
        if key and any(part in key.lower() for part in sensitive_parts):
            return "[REDACTED]"
        if depth > 4:
            return "[TRUNCATED_DEPTH]"
        if isinstance(value, str):
            return (
                value
                if len(value) <= 1000
                else value[:1000] + f"...[truncated {len(value) - 1000} chars]"
            )
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            items = list(value.items())
            redacted = {
                str(item_key): NativeHealer._redact_tool_input(
                    item_value, key=str(item_key), depth=depth + 1
                )
                for item_key, item_value in items[:25]
            }
            if len(items) > 25:
                redacted["__truncated_keys"] = len(items) - 25
            return redacted
        if isinstance(value, list):
            redacted_list = [
                NativeHealer._redact_tool_input(item, key=key, depth=depth + 1)
                for item in value[:25]
            ]
            if len(value) > 25:
                redacted_list.append(f"[truncated {len(value) - 25} items]")
            return redacted_list
        return str(value)[:1000]

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
            logger.info(
                "Usage: native_healer.py <test_file> [--log <error.log>] or --all"
            )

    try:
        asyncio.run(main())
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass
        else:
            raise
