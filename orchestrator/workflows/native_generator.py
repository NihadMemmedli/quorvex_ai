"""
Native Generator Workflow - Converts Test Specs to Playwright Code

This workflow uses the Playwright Test Generator agent to:
1. Read a markdown test spec
2. Execute each step in a live browser to validate selectors
3. Generate the final Playwright TypeScript test code
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _optional_env_float(name: str) -> float | None:
    value = os.environ.get(name)
    if not value:
        return None
    return float(value)


# Add orchestrator to path
sys.path.append(str(Path(__file__).parent.parent.parent))

# Store project base directory BEFORE any chdir() calls
# This ensures tests_dir always resolves to /app/tests/generated/ in Docker
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load Claude credentials and SDK
from orchestrator.load_env import setup_claude_env

setup_claude_env()

from orchestrator.ai.prompt_registry import (
    attach_prompt_metadata,
    build_prompt_metadata,
)
from orchestrator.services.handoff_manifest import (
    record_artifact,
    record_attempt,
    record_consumption,
)
from orchestrator.utils.agent_runner import (
    AgentResult,
    AgentRunner,
    get_default_timeout,
)
from orchestrator.utils.agent_tool_allowlists import get_agent_tool_config
from orchestrator.utils.text_utils import truncate_middle
from orchestrator.utils.token_budget import (
    context_budget_for_stage,
    truncate_text_to_tokens,
)


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

    def __init__(
        self,
        on_tool_use: Callable[[str, dict[str, Any]], None] | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        on_task_enqueued: Callable[[str], None] | None = None,
        owner_type: str | None = None,
        owner_id: str | None = None,
        owner_label: str | None = None,
        model_tier: str = "tool_deep",
        project_id: str | None = None,
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
        self.project_id = project_id
        self.env_vars = dict(env_vars or {})
        self.cwd = Path(cwd) if cwd else None
        self.last_handoff_consumption: dict[str, Any] = {}
        self.last_coverage_warnings: list[str] = []
        self.last_agent_result: AgentResult | None = None
        self.last_self_run_result: dict[str, Any] | None = None
        self.last_self_heal_attempts: int = 0
        self.last_self_heal_passed: bool = False
        self.last_self_heal_artifact_path: Path | None = None
        # Use absolute path to project's tests directory (not relative to cwd)
        # This fixes Docker issue where cwd changes to run directory
        self.tests_dir = BASE_DIR / "tests" / "generated"
        self.tests_dir.mkdir(parents=True, exist_ok=True)

    async def generate_test(
        self,
        spec_path: str,
        target_url: str | None = None,
        output_name: str | None = None,
        design_context: str | None = None,
        memory_run_id: str | None = None,
        auth_context: dict[str, Any] | None = None,
        execution_credentials: dict[str, str] | None = None,
        plan_path: Path | None = None,
        planner_draft_script_path: Path | None = None,
        handoff_manifest_path: Path | None = None,
        self_run_browser: str | None = None,
        self_run_output_dir: Path | None = None,
        self_heal_max_attempts: int = 3,
        enable_self_run: bool = True,
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
        self.last_self_run_result = None
        self.last_self_heal_attempts = 0
        self.last_self_heal_passed = False
        self.last_self_heal_artifact_path = None

        spec_content = spec_path_obj.read_text()
        # Use provided output_name or fall back to spec file stem
        spec_name = output_name if output_name else spec_path_obj.stem

        # Determine output path
        output_path = self.tests_dir / f"{spec_name}.spec.ts"
        if output_path.exists():
            logger.info(
                f"Removing stale generated test before regeneration: {output_path}"
            )
            output_path.unlink()

        logger.info(f"Generating test from: {spec_path}")
        logger.info(f"   Output: {output_path}")

        handoff_consumption: dict[str, Any] = {
            "received_planner_plan": bool(plan_path),
            "received_planner_draft_script": bool(planner_draft_script_path),
            "planner_plan_status": "not_provided",
            "planner_draft_script_status": "not_provided",
        }

        plan_content = None
        if plan_path and plan_path.exists():
            try:
                plan_content = plan_path.read_text()
                handoff_consumption["planner_plan_status"] = "used"
            except OSError as exc:
                logger.warning(f"Could not read planner artifact {plan_path}: {exc}")
                handoff_consumption["planner_plan_status"] = "rejected"
                handoff_consumption["planner_plan_reason"] = str(exc)
        elif plan_path:
            handoff_consumption["planner_plan_status"] = "missing"
            handoff_consumption["planner_plan_reason"] = "plan path does not exist"

        planner_draft_script_content = None
        if planner_draft_script_path and planner_draft_script_path.exists():
            try:
                planner_draft_script_content = planner_draft_script_path.read_text()
                handoff_consumption["planner_draft_script_status"] = "used"
            except OSError as exc:
                logger.warning(
                    f"Could not read planner draft script {planner_draft_script_path}: {exc}"
                )
                handoff_consumption["planner_draft_script_status"] = "rejected"
                handoff_consumption["planner_draft_script_reason"] = str(exc)
        elif planner_draft_script_path:
            handoff_consumption["planner_draft_script_status"] = "missing"
            handoff_consumption["planner_draft_script_reason"] = (
                "draft script path does not exist"
            )

        if handoff_manifest_path:
            if plan_path:
                record_consumption(
                    handoff_manifest_path,
                    "generator",
                    "planner_plan",
                    status=handoff_consumption["planner_plan_status"],
                    reason=handoff_consumption.get("planner_plan_reason"),
                    metadata={"path": str(plan_path)},
                )
            if planner_draft_script_path:
                record_consumption(
                    handoff_manifest_path,
                    "generator",
                    "planner_draft_script",
                    status=handoff_consumption["planner_draft_script_status"],
                    reason=handoff_consumption.get("planner_draft_script_reason"),
                    metadata={"path": str(planner_draft_script_path)},
                )
        self.last_handoff_consumption = handoff_consumption

        # Build prompt in the format expected by playwright-test-generator agent
        prompt = self._build_generator_prompt(
            spec_path=spec_path,
            spec_content=spec_content,
            spec_name=spec_name,
            output_path=str(output_path),
            target_url=target_url,
            design_context=design_context,
            memory_run_id=memory_run_id,
            auth_context=auth_context,
            execution_credentials=execution_credentials,
            plan_content=plan_content,
            planner_draft_script_content=planner_draft_script_content,
        )

        # Invoke the Generator Agent
        logger.info("Invoking Playwright Generator Agent...")
        result = await self._query_generator_agent(prompt)
        agent_result = self.last_agent_result

        # Check if the agent created the file
        if output_path.exists():
            validation_error = self._generated_test_validation_error(output_path)
            if not validation_error:
                logger.info(f"Test generated: {output_path}")
                self._record_generation_coverage(spec_content, output_path)
                await self._self_run_generated_test_if_enabled(
                    output_path=output_path,
                    browser=self_run_browser,
                    output_dir=self_run_output_dir,
                    self_heal_max_attempts=self_heal_max_attempts,
                    enable_self_run=enable_self_run,
                    previous_result=agent_result,
                    handoff_manifest_path=handoff_manifest_path,
                )
                self._record_generated_test_handoff(
                    handoff_manifest_path=handoff_manifest_path,
                    output_path=output_path,
                    handoff_consumption=handoff_consumption,
                )
                return output_path
            logger.warning(
                "Generated test failed format validation: %s", validation_error
            )
            if await self._retry_generator_format(
                output_path=output_path,
                validation_error=validation_error,
                previous_output=result,
                previous_result=agent_result,
            ):
                self._record_generation_coverage(spec_content, output_path)
                await self._self_run_generated_test_if_enabled(
                    output_path=output_path,
                    browser=self_run_browser,
                    output_dir=self_run_output_dir,
                    self_heal_max_attempts=self_heal_max_attempts,
                    enable_self_run=enable_self_run,
                    previous_result=agent_result,
                    handoff_manifest_path=handoff_manifest_path,
                )
                self._record_generated_test_handoff(
                    handoff_manifest_path=handoff_manifest_path,
                    output_path=output_path,
                    handoff_consumption=handoff_consumption,
                    source="schema_retry",
                )
                return output_path

        # Fallback: If agent returned code but didn't write it
        fixed_code = self._extract_code(result or "")
        if fixed_code:
            logger.info(f"Saving generated code to: {output_path}")
            output_path.write_text(fixed_code.rstrip() + "\n")
            self._record_generation_coverage(spec_content, output_path)
            await self._self_run_generated_test_if_enabled(
                output_path=output_path,
                browser=self_run_browser,
                output_dir=self_run_output_dir,
                self_heal_max_attempts=self_heal_max_attempts,
                enable_self_run=enable_self_run,
                previous_result=agent_result,
                handoff_manifest_path=handoff_manifest_path,
            )
            self._record_generated_test_handoff(
                handoff_manifest_path=handoff_manifest_path,
                output_path=output_path,
                handoff_consumption=handoff_consumption,
                source="agent_response_fallback",
            )
            return output_path

        recovered_tool_code = self._recover_generator_write_test_code(agent_result)
        if recovered_tool_code:
            logger.info(
                "Recovering generated code from generator_write_test telemetry: %s",
                output_path,
            )
            output_path.write_text(recovered_tool_code.rstrip() + "\n")
            validation_error = self._generated_test_validation_error(output_path)
            if not validation_error:
                self._record_generation_coverage(spec_content, output_path)
                await self._self_run_generated_test_if_enabled(
                    output_path=output_path,
                    browser=self_run_browser,
                    output_dir=self_run_output_dir,
                    self_heal_max_attempts=self_heal_max_attempts,
                    enable_self_run=enable_self_run,
                    previous_result=agent_result,
                    handoff_manifest_path=handoff_manifest_path,
                )
                self._record_generated_test_handoff(
                    handoff_manifest_path=handoff_manifest_path,
                    output_path=output_path,
                    handoff_consumption=handoff_consumption,
                    source="generator_write_test_telemetry",
                )
                return output_path
            logger.warning(
                "Recovered generator_write_test content failed validation: %s",
                validation_error,
            )

        if self._is_provider_overload_result(agent_result):
            status = getattr(agent_result, "api_error_status", None)
            error = getattr(agent_result, "error", None) or "provider overloaded"
            raise RuntimeError(
                "Native generator failed because the LLM provider was temporarily "
                f"unavailable{f' (status {status})' if status else ''}: {error}"
            )

        validation_error = "agent did not write a valid Playwright TypeScript test or return one in a code block"
        if await self._retry_generator_format(
            output_path=output_path,
            validation_error=validation_error,
            previous_output=result,
            previous_result=agent_result,
        ):
            self._record_generation_coverage(spec_content, output_path)
            await self._self_run_generated_test_if_enabled(
                output_path=output_path,
                browser=self_run_browser,
                output_dir=self_run_output_dir,
                self_heal_max_attempts=self_heal_max_attempts,
                enable_self_run=enable_self_run,
                previous_result=agent_result,
                handoff_manifest_path=handoff_manifest_path,
            )
            self._record_generated_test_handoff(
                handoff_manifest_path=handoff_manifest_path,
                output_path=output_path,
                handoff_consumption=handoff_consumption,
                source="schema_retry",
            )
            return output_path

        logger.warning(f"Generator finished but test file not found at: {output_path}")
        return output_path

    @staticmethod
    def _is_provider_overload_result(agent_result: AgentResult | None) -> bool:
        if agent_result is None:
            return False
        error_type = getattr(agent_result, "error_type", None)
        status = getattr(agent_result, "api_error_status", None)
        return error_type == "provider_overloaded" or status == 529 or (
            isinstance(status, int) and 500 <= status <= 599
        )

    def _recover_generator_write_test_code(self, agent_result: AgentResult | None) -> str | None:
        if agent_result is None:
            return None
        for call in reversed(getattr(agent_result, "tool_calls", []) or []):
            name = str(getattr(call, "name", "") or "")
            if not name.endswith("generator_write_test"):
                continue
            tool_input = getattr(call, "input", None)
            if not isinstance(tool_input, dict):
                continue
            for key in ("code", "source", "content", "test_code", "testCode"):
                value = tool_input.get(key)
                if isinstance(value, str) and self._looks_like_playwright_test(value):
                    return value
        return None

    def _record_generated_test_handoff(
        self,
        *,
        handoff_manifest_path: Path | None,
        output_path: Path,
        handoff_consumption: dict[str, Any],
        source: str | None = None,
    ) -> None:
        if not handoff_manifest_path:
            return
        metadata = dict(handoff_consumption)
        if source:
            metadata["source"] = source
        if self.last_self_run_result:
            metadata["generator_self_run_status"] = self.last_self_run_result.get(
                "final_status"
            )
            metadata["generator_self_heal_attempts"] = self.last_self_heal_attempts
            if self.last_self_heal_artifact_path:
                metadata["generator_self_heal_artifact"] = str(
                    self.last_self_heal_artifact_path
                )
        else:
            metadata["generator_self_run_status"] = "disabled"
            metadata["generator_self_heal_attempts"] = 0

        record_artifact(
            handoff_manifest_path,
            "generated_test",
            output_path,
            kind="playwright_test",
            producer_stage="generator",
            required=True,
            consumers=["test_run", "healer"],
            validation_status="valid",
            metadata=metadata,
        )

    def _generated_test_validation_error(self, output_path: Path) -> str | None:
        try:
            code = output_path.read_text()
        except OSError as exc:
            return f"could not read generated test file: {exc}"
        if not code.strip():
            return "generated test file is empty"
        if not self._looks_like_playwright_test(code):
            return "generated file is not a valid Playwright TypeScript test"
        return None

    @staticmethod
    def _generator_schema_max_attempts() -> int:
        raw_value = os.environ.get("GENERATOR_SCHEMA_MAX_ATTEMPTS", "2")
        try:
            return min(5, max(1, int(raw_value)))
        except ValueError:
            return 2

    async def _retry_generator_format(
        self,
        *,
        output_path: Path,
        validation_error: str,
        previous_output: str,
        previous_result: AgentResult | None,
    ) -> bool:
        max_attempts = self._generator_schema_max_attempts()
        if max_attempts <= 1 or previous_result is None:
            return False

        previous_file = ""
        if output_path.exists():
            try:
                previous_file = output_path.read_text()
            except OSError:
                previous_file = ""

        current_error = validation_error
        current_output = previous_output or ""

        for attempt_number in range(2, max_attempts + 1):
            logger.info(
                "Retrying generator output format after validation failure (%s/%s)",
                attempt_number,
                max_attempts,
            )
            prompt = self._build_generator_format_retry_prompt(
                output_path=output_path,
                validation_error=current_error,
                previous_output=current_output,
                previous_file=previous_file,
            )
            retry_result = await self._query_generator_format_retry_agent(
                prompt,
            )
            current_output = retry_result.output or ""
            fixed_code = self._extract_code(current_output)
            if not fixed_code:
                current_error = "retry output did not contain a valid Playwright TypeScript code block"
                continue
            output_path.write_text(fixed_code.rstrip() + "\n")
            file_error = self._generated_test_validation_error(output_path)
            if not file_error:
                logger.info("Generator format retry accepted: %s", output_path)
                return True
            current_error = file_error
            previous_file = fixed_code
        logger.warning("Generator format retry failed: %s", current_error)
        return False

    def _build_generator_format_retry_prompt(
        self,
        *,
        output_path: Path,
        validation_error: str,
        previous_output: str,
        previous_file: str,
    ) -> str:
        previous_sections = []
        if previous_file.strip():
            previous_sections.append(
                "## Rejected File Content\n```typescript\n"
                + truncate_middle(previous_file, head=5000, tail=5000)
                + "\n```"
            )
        if previous_output.strip():
            previous_sections.append(
                "## Previous Agent Output\n```text\n"
                + truncate_middle(previous_output, head=4000, tail=4000)
                + "\n```"
            )
        context = (
            "\n\n".join(previous_sections) or "No usable previous output was captured."
        )
        return f"""You are correcting a rejected Playwright test generation result.

This is a clean artifact-driven schema/format correction turn, not a browser-generation run.
Do not browse, do not call tools, do not start or close a browser, and do not depend on prior Claude conversation state.

Validation failure:
{validation_error}

Return exactly one complete Playwright TypeScript test file for:
{output_path}

Rules:
- Return only a ```typescript code block.
- Include a valid `import {{ test, expect }} from '@playwright/test'` or the project fixture import already present in the rejected file.
- Include at least one `test(...)` or `test.describe(...)`.
- Do not include markdown outside the code block.
- Do not include backticks inside the TypeScript file.

{context}
"""

    async def _query_generator_format_retry_agent(
        self,
        prompt: str,
        *,
        resume_session_id: str | None = None,
        continue_conversation: bool = False,
    ) -> AgentResult:
        timeout = int(os.environ.get("GENERATOR_SCHEMA_RETRY_TIMEOUT_SECONDS", "180"))
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
            memory_agent_type="NativeGenerator",
            memory_source_type="spec",
            memory_stage="native_generator_schema_retry",
            inject_memory=False,
            capture_memory=False,
            env_vars=self.env_vars,
            cwd=self.cwd,
            requires_live_browser=False,
            resume_session_id=None,
            continue_conversation=False,
            force_direct_execution=True,
            autopilot_retry_enabled=(
                bool(getattr(self, "autopilot_retry_enabled", False))
                or self.owner_type == "autopilot"
            ),
            autopilot_session_id=getattr(self, "autopilot_session_id", None)
            or self.owner_id,
            autopilot_stable_key=getattr(self, "autopilot_stable_key", None),
            autopilot_agent_kind=getattr(self, "autopilot_agent_kind", "test_generation_schema_retry"),
            autopilot_source_type=getattr(self, "autopilot_source_type", None),
            autopilot_source_id=getattr(self, "autopilot_source_id", None),
            autopilot_checklist_title=getattr(self, "autopilot_checklist_title", None),
            autopilot_phase_name=getattr(self, "autopilot_phase_name", None),
            autopilot_checklist_kind=getattr(self, "autopilot_checklist_kind", None),
        )
        return await runner.run(prompt)

    @staticmethod
    def _file_sha256(path: Path) -> str | None:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None

    @staticmethod
    def _generator_self_heal_max_attempts(requested: int = 3) -> int:
        raw_value = os.environ.get("GENERATOR_SELF_HEAL_MAX_ATTEMPTS")
        try:
            value = int(raw_value) if raw_value is not None else int(requested)
        except (TypeError, ValueError):
            value = 3
        return min(3, max(0, value))

    async def _self_run_generated_test_if_enabled(
        self,
        *,
        output_path: Path,
        browser: str | None,
        output_dir: Path | None,
        self_heal_max_attempts: int,
        enable_self_run: bool,
        previous_result: AgentResult | None,
        handoff_manifest_path: Path | None = None,
    ) -> None:
        if not enable_self_run:
            self.last_self_run_result = {"status": "disabled"}
            self.last_self_heal_attempts = 0
            self.last_self_heal_passed = False
            return
        if not output_path.exists():
            return

        run_dir = Path(output_dir) if output_dir else output_path.parent
        run_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = run_dir / "generator_self_heal.json"
        self.last_self_heal_artifact_path = artifact_path
        max_attempts = self._generator_self_heal_max_attempts(self_heal_max_attempts)
        browser_project = browser or "chromium"
        generator_session_id = getattr(previous_result, "session_id", None)
        session_ids: list[str] = []
        records: list[dict[str, Any]] = []
        previous_fixes: list[str] = []

        artifact: dict[str, Any] = {
            "test_path": str(output_path),
            "browser": browser_project,
            "output_dir": str(run_dir),
            "max_self_heal_attempts": max_attempts,
            "initial_session_id": generator_session_id,
            "session_resume_policy": "clean_artifact_turns",
            "session_ids": session_ids,
            "attempt_count": 0,
            "attempts": records,
            "original_file_hash": self._file_sha256(output_path),
            "final_file_hash": self._file_sha256(output_path),
            "final_status": "running",
        }

        def write_artifact() -> None:
            artifact["attempt_count"] = self.last_self_heal_attempts
            artifact["final_file_hash"] = self._file_sha256(output_path)
            try:
                artifact_path.write_text(json.dumps(artifact, indent=2, default=str))
            except OSError as exc:
                logger.debug("Could not write generator self-heal artifact: %s", exc)

        logger.info(
            "Generator self-run: running generated test %s on %s",
            output_path,
            browser_project,
        )
        first_prompt = self._build_generator_self_run_prompt(
            output_path=output_path,
            browser=browser_project,
            output_dir=run_dir,
        )
        first_result = await self._query_generator_self_heal_agent(
            first_prompt,
        )
        if first_result.session_id:
            session_ids.append(first_result.session_id)
        status = self._parse_generator_self_run_status(first_result)
        failure_summary = self._summarize_agent_run_result(first_result)
        records.append(
            {
                "phase": "self_run",
                "status": status,
                "session_id": first_result.session_id,
                "run_result_summary": failure_summary,
                "accepted_file_hash": self._file_sha256(output_path)
                if status == "passed"
                else None,
            }
        )
        if status == "passed":
            artifact["final_status"] = "passed"
            self.last_self_run_result = artifact
            self.last_self_heal_attempts = 0
            self.last_self_heal_passed = True
            write_artifact()
            self._record_self_heal_artifact(
                handoff_manifest_path=handoff_manifest_path,
                artifact_path=artifact_path,
                status="passed",
            )
            return

        for attempt_number in range(1, max_attempts + 1):
            before_content = output_path.read_text()
            before_hash = self._file_sha256(output_path)
            prompt = self._build_generator_self_heal_prompt(
                output_path=output_path,
                browser=browser_project,
                output_dir=run_dir,
                attempt_number=attempt_number,
                max_attempts=max_attempts,
                failure_summary=failure_summary,
                previous_fixes=previous_fixes,
                current_file_content=before_content,
            )
            logger.info(
                "Generator self-heal attempt %s/%s for %s",
                attempt_number,
                max_attempts,
                output_path,
            )
            repair_result = await self._query_generator_self_heal_agent(
                prompt,
            )
            if repair_result.session_id and repair_result.session_id not in session_ids:
                session_ids.append(repair_result.session_id)
            after_hash = self._file_sha256(output_path)
            validation_error = self._generated_test_validation_error(output_path)
            status = self._parse_generator_self_run_status(repair_result)
            summary = self._summarize_agent_run_result(repair_result)
            record: dict[str, Any] = {
                "phase": "self_heal",
                "attempt": attempt_number,
                "status": status,
                "session_id": repair_result.session_id,
                "run_result_summary": summary,
                "before_file_hash": before_hash,
                "after_file_hash": after_hash,
                "accepted_file_hash": after_hash,
                "rejected_file_hash": None,
                "validation_error": validation_error,
            }
            self.last_self_heal_attempts = attempt_number

            if validation_error:
                record["status"] = "rejected_invalid_code"
                record["accepted_file_hash"] = before_hash
                record["rejected_file_hash"] = after_hash
                output_path.write_text(before_content)
                failure_summary = (
                    "Generator self-heal produced invalid Playwright code: "
                    f"{validation_error}"
                )
                previous_fixes.append(f"Attempt {attempt_number}: rejected invalid code.")
                records.append(record)
                artifact["final_status"] = "running"
                write_artifact()
                continue

            previous_fixes.append(
                f"Attempt {attempt_number}: {self._extract_self_heal_field(repair_result.output, 'root_cause') or summary[:300]}"
            )
            records.append(record)
            failure_summary = summary
            if status == "passed":
                artifact["final_status"] = "passed_after_self_heal"
                self.last_self_run_result = artifact
                self.last_self_heal_passed = True
                write_artifact()
                self._record_self_heal_artifact(
                    handoff_manifest_path=handoff_manifest_path,
                    artifact_path=artifact_path,
                    status="passed_after_self_heal",
                )
                return
            write_artifact()

        artifact["final_status"] = "exhausted"
        self.last_self_run_result = artifact
        self.last_self_heal_passed = False
        write_artifact()
        self._record_self_heal_artifact(
            handoff_manifest_path=handoff_manifest_path,
            artifact_path=artifact_path,
            status="exhausted",
        )

    def _record_self_heal_artifact(
        self,
        *,
        handoff_manifest_path: Path | None,
        artifact_path: Path,
        status: str,
    ) -> None:
        if not handoff_manifest_path or not artifact_path.exists():
            return
        record_artifact(
            handoff_manifest_path,
            "generator_self_heal",
            artifact_path,
            kind="generator_self_heal",
            producer_stage="generator",
            required=False,
            consumers=["test_run", "healer", "reporting"],
            validation_status=status,
            metadata={"status": status},
        )
        try:
            data = json.loads(artifact_path.read_text())
            for index, attempt in enumerate(data.get("attempts") or [], start=1):
                if isinstance(attempt, dict):
                    record_attempt(
                        handoff_manifest_path,
                        "generator_self_heal",
                        stage_attempt=index,
                        status=str(attempt.get("status") or data.get("final_status") or "unknown"),
                        agent_session_id=attempt.get("session_id"),
                        executor_mode="direct",
                        model_tier=self.model_tier,
                        error_type=attempt.get("status") if str(attempt.get("status", "")).startswith("failed") else None,
                        input_artifact_hashes={"generated_test": data.get("original_file_hash")},
                        output_artifact_hash=attempt.get("accepted_file_hash"),
                        metadata={key: value for key, value in attempt.items() if key != "run_result_summary"},
                    )
        except Exception as exc:
            logger.debug("Could not record generator self-heal attempts in manifest: %s", exc)

    def _build_generator_self_run_prompt(
        self,
        *,
        output_path: Path,
        browser: str,
        output_dir: Path,
    ) -> str:
        return f"""Run the generated Playwright test file now using the artifact context below.

Test path: {output_path}
Browser/project: {browser}
Output directory: {output_dir}

Instructions:
- Call `test_debug` for exactly this file and browser/project before handoff. Do not run any other test file.
- Do not edit the file in this turn.
- If the test fails, keep the paused browser state open long enough to inspect the failure summary needed to report the result.
- Do not call `browser_close`; the orchestrator owns cleanup after this turn.
- Stop immediately after the debug result is known.
- This is a clean execution turn. Do not rely on previous Claude conversation state.

Final response fields:
self_run_status: passed | failed
self_heal_attempts: 0
root_cause: one concise sentence, or "none" if passed
changed_selectors: []
"""

    def _build_generator_self_heal_prompt(
        self,
        *,
        output_path: Path,
        browser: str,
        output_dir: Path,
        attempt_number: int,
        max_attempts: int,
        failure_summary: str,
        previous_fixes: list[str],
        current_file_content: str,
    ) -> str:
        prior = "\n".join(f"- {item}" for item in previous_fixes) or "- none"
        return f"""Correct the generated Playwright test using the artifact context below.

Test path: {output_path}
Browser/project: {browser}
Output directory: {output_dir}
Self-heal attempt: {attempt_number} of {max_attempts}

Failure summary from the previous run:
```text
{truncate_middle(failure_summary or "No failure summary captured.", head=3500, tail=3500)}
```

Previous attempted fixes:
{prior}

Current file content:
```typescript
{truncate_middle(current_file_content, head=7000, tail=7000)}
```

Instructions:
- Fix exactly one root cause in the same output file: {output_path}
- Use `test_debug` scoped to this exact file and browser/project `{browser}` to reproduce the failed generated test state before editing. `test_debug` is the failure-state capture path because it pauses on the failed test state.
- Use diagnostic tools only after `test_debug` has paused: `browser_snapshot`,
  `browser_console_messages`, `browser_network_requests`, `browser_generate_locator`,
  `browser_evaluate`, or tracing tools. Use `browser_resume` only after capturing
  paused-state evidence and only when you need the same paused script to continue
  to the next action, assertion, or failure.
- Do not call `browser_close`; preserve the paused browser state until you have captured the evidence needed for the fix.
- Use `generator_write_test` to rewrite that same file with the complete corrected test.
- Rerun the same generated test with `test_debug` when you still need paused-state evidence, or `test_run` scoped to this exact file and browser/project `{browser}` for final verification.
- Stop immediately when the run passes.
- Do not switch files, do not run unrelated tests, and do not rely on prior Claude conversation state.
- If your correction would make the file invalid TypeScript/Playwright, do not write it.

Final response fields:
self_run_status: passed | failed
self_heal_attempts: {attempt_number}
root_cause: concise root cause fixed or still suspected
changed_selectors: JSON array of selector changes, or []
"""

    async def _query_generator_self_heal_agent(
        self,
        prompt: str,
        *,
        resume_session_id: str | None = None,
        continue_conversation: bool = False,
    ) -> AgentResult:
        timeout = int(os.environ.get("GENERATOR_SELF_HEAL_TIMEOUT_SECONDS", "300"))
        tool_config = get_agent_tool_config(
            "playwright-test-generator", mcp_config_dir=self.cwd
        )
        runner = AgentRunner(
            timeout_seconds=timeout,
            allowed_tools=tool_config.get("allowed_tools"),
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
            max_budget_usd=_optional_env_float("GENERATOR_MAX_BUDGET_USD"),
            memory_agent_type="NativeGenerator",
            memory_source_type="spec",
            memory_stage="native_generator_self_heal",
            inject_memory=False,
            capture_memory=False,
            env_vars=self.env_vars,
            cwd=self.cwd,
            resume_session_id=None,
            continue_conversation=False,
            force_direct_execution=True,
            preserve_browser_on_failure=True,
            autopilot_retry_enabled=(
                bool(getattr(self, "autopilot_retry_enabled", False))
                or self.owner_type == "autopilot"
            ),
            autopilot_session_id=getattr(self, "autopilot_session_id", None)
            or self.owner_id,
            autopilot_stable_key=getattr(self, "autopilot_stable_key", None),
            autopilot_agent_kind=getattr(self, "autopilot_agent_kind", "test_generation_self_heal"),
            autopilot_source_type=getattr(self, "autopilot_source_type", None),
            autopilot_source_id=getattr(self, "autopilot_source_id", None),
            autopilot_checklist_title=getattr(self, "autopilot_checklist_title", None),
            autopilot_phase_name=getattr(self, "autopilot_phase_name", None),
            autopilot_checklist_kind=getattr(self, "autopilot_checklist_kind", None),
        )
        return await runner.run(prompt)

    @staticmethod
    def _extract_self_heal_field(output: str | None, field: str) -> str | None:
        if not output:
            return None
        json_match = re.search(r"\{.*\}", output, flags=re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                value = data.get(field)
                if value is not None:
                    return json.dumps(value) if isinstance(value, (list, dict)) else str(value)
            except Exception:
                pass
        match = re.search(rf"(?im)^\s*{re.escape(field)}\s*:\s*(.+?)\s*$", output)
        return match.group(1).strip() if match else None

    def _parse_generator_self_run_status(self, result: AgentResult) -> str:
        raw_status = (
            self._extract_self_heal_field(result.output, "self_run_status")
            or self._extract_self_heal_field(result.output, "status")
            or ""
        ).strip().strip("\"'").lower()
        if raw_status in {"passed", "pass", "success", "fixed"}:
            return "passed"
        if raw_status in {"failed", "fail", "failure", "exhausted"}:
            return "failed"
        output_lower = (result.output or "").lower()
        if result.success and re.search(r"\bself_run_status\s*:\s*passed\b", output_lower):
            return "passed"
        if "self_run_status" in output_lower and "passed" in output_lower and "failed" not in output_lower:
            return "passed"
        return "failed"

    @staticmethod
    def _summarize_agent_run_result(result: AgentResult) -> str:
        pieces: list[str] = []
        if result.error:
            pieces.append(result.error)
        if result.output:
            pieces.append(result.output)
        if not pieces:
            pieces.append(
                f"Agent result success={result.success}, timed_out={result.timed_out}, "
                f"tool_calls={len(result.tool_calls)}"
            )
        return truncate_middle("\n\n".join(pieces), head=5000, tail=5000)

    def _extract_code(self, text: str) -> str | None:
        """Extract only TypeScript test code from an agent response."""
        import re

        patterns = [
            r"```typescript\n(.*?)```",
            r"```ts\n(.*?)```",
            r"```\n(.*?)```",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if not match:
                continue
            code = match.group(1).strip()
            if self._looks_like_playwright_test(code):
                return code

        stripped = text.strip()
        if stripped.startswith("import") and self._looks_like_playwright_test(stripped):
            return stripped
        return None

    @staticmethod
    def _looks_like_playwright_test(code: str) -> bool:
        import re

        def has_fixture_helper_import() -> bool:
            for match in re.finditer(
                r"import\s*\{(?P<names>[^}]+)\}\s*from\s*['\"](?P<source>[^'\"]+)['\"]",
                code,
            ):
                names = match.group("names")
                source = match.group("source").replace("\\", "/")
                if (
                    source.endswith("fixtures/test-data")
                    and re.search(r"\btest\b", names)
                    and re.search(r"\bexpect\b", names)
                    and ("testData" in code or "QUORVEX_TEST_DATA_FILE" in code)
                ):
                    return True
            return False

        return (
            ("test(" in code or "test.describe" in code)
            and ("@playwright/test" in code or has_fixture_helper_import())
            and "```" not in code
        )

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
        self,
        spec_path: str,
        spec_content: str,
        spec_name: str,
        output_path: str,
        target_url: str | None,
        design_context: str | None = None,
        memory_run_id: str | None = None,
        auth_context: dict[str, Any] | None = None,
        execution_credentials: dict[str, str] | None = None,
        plan_content: str | None = None,
        planner_draft_script_content: str | None = None,
    ) -> str:
        """Build prompt matching the playwright-test-generator agent format."""

        # Extract test suite and first test case from spec for the expected format
        test_suite = spec_name.replace("prd-", "").replace("-", " ").title()

        url_section = ""
        if target_url:
            url_section = f"\nTarget URL: {target_url}"

        # Extract and resolve credential placeholders
        credentials = self._extract_credential_placeholders(spec_content)
        test_data_ref = (execution_credentials or {}).get("test_data_ref")
        if execution_credentials and not test_data_ref:
            username_var = execution_credentials.get("username_var") or "LOGIN_USERNAME"
            password_var = execution_credentials.get("password_var") or "LOGIN_PASSWORD"
            if execution_credentials.get("username"):
                credentials[username_var] = execution_credentials["username"]
            if execution_credentials.get("password"):
                credentials[password_var] = execution_credentials["password"]
        env_vars = getattr(self, "env_vars", {})
        if env_vars:
            credentials.update(
                {
                    key: value
                    for key, value in env_vars.items()
                    if key.startswith("TESTDATA_")
                }
            )
        credentials = {
            key: value
            for key, value in credentials.items()
            if not key.startswith("TESTDATA_")
        }
        credentials_section = ""
        if credentials:
            cred_lines = []
            for var_name, value in credentials.items():
                cred_lines.append(
                    f"- `{{{{{var_name}}}}}` → Use value: `{value}` during execution, but write `process.env.{var_name}!` in generated code"
                )
            credentials_section = f"""

## Credentials (IMPORTANT)
The run has credential/test-data variables available. During browser execution, use the ACTUAL values shown below.
In the generated code, use `process.env.VAR_NAME!` instead of hardcoding.
This section is only for non-project-test-data placeholders. Project `@testdata` refs must use the fixture helper.

{chr(10).join(cred_lines)}
"""

        test_data_fixture_section = self._build_test_data_fixture_section(
            output_path=output_path,
            execution_credentials=execution_credentials,
        )

        design_section = ""
        if design_context:
            design_section = f"""

## Agentic Test Design Guidance
Use this design guidance to reduce flaky output. Treat it as advisory context from the planning quality gate:

{design_context}
"""

        plan_section = ""
        if plan_content:
            mode = (
                os.environ.get("GENERATOR_PLAN_EVIDENCE_MODE", "summary")
                .strip()
                .lower()
            )
            if mode not in {"summary", "full"}:
                mode = "summary"
            plan_budget = context_budget_for_stage(
                "generator_plan", 1600 if mode == "summary" else 2400
            )
            rendered_plan = (
                self._planner_evidence_summary(plan_content, token_budget=plan_budget)
                if mode == "summary"
                else truncate_text_to_tokens(plan_content, plan_budget)
            )
            if rendered_plan:
                plan_section = f"""

## Verified Test Plan (selectors discovered on the live app by the planner)
The planner explored the live application and verified these steps/selectors.
Prefer these selectors over guessing, but verify with browser_snapshot before
relying on them - the page may have changed since planning.

{rendered_plan}
"""

        draft_script_section = ""
        if planner_draft_script_content:
            draft_budget = context_budget_for_stage("generator_draft_script", 1800)
            rendered_draft = truncate_text_to_tokens(
                planner_draft_script_content, draft_budget
            )
            if rendered_draft:
                draft_script_section = f"""

## Planner Draft Script
The planner generated this draft Playwright script after live exploration.
Use it as starting code and selector evidence only. You must still validate the
steps with `generator_setup_page`, browser tools, and `generator_read_log`, then
write the final test with `generator_write_test`.

Keep or improve its wait strategy: no `page.waitForTimeout()`, use web-first
assertions such as `await expect(locator).toBeVisible()`, durable navigation
waits such as `await expect(page).toHaveURL(...)` or `await page.waitForURL(...)`,
and durable async waits such as visible result text, success toasts, list-count
changes, completed status, or `page.waitForResponse(...)` when appropriate.

```typescript
{rendered_draft}
```
"""

        auth_section = ""
        if auth_context and auth_context.get("storage_state_attached"):
            session_name = (
                auth_context.get("browser_auth_session_name")
                or auth_context.get("browser_auth_session_id")
                or "selected session"
            )
            auth_section = f"""

## Browser Authentication Context
The browser starts authenticated with saved session `{session_name}`.
Do not generate login steps unless the scenario explicitly tests login, logout, or authentication failure.
"""

        memory_section = self._build_memory_context_section(
            query=f"{target_url or ''}\n{spec_content}",
            project_id=os.environ.get("MEMORY_PROJECT_ID")
            or os.environ.get("PROJECT_ID"),
            source_id=spec_path,
            run_id=memory_run_id,
        )

        prompt = f"""You are the Playwright Test Generator.

Context: User wants to generate automated tests from the following test plan.

<test-suite>{test_suite}</test-suite>
<test-file>{output_path}</test-file>
<seed-file>tests/seed.spec.ts</seed-file>
{url_section}
{credentials_section}
{test_data_fixture_section}
<spec-content file="{spec_path}">
{spec_content}
</spec-content>
{design_section}
{plan_section}
{draft_script_section}
{auth_section}
{memory_section}

## Instructions

For each test case in the spec:
1. Call `generator_setup_page` with `seedFile: "tests/seed.spec.ts"` to initialize the browser
2. **IMMEDIATELY** call `browser_navigate` to go to the supplied target URL: `{target_url or "read the first explicit http(s) URL in the spec"}`
   - Navigate only to that supplied target URL at setup time unless a test step explicitly requires another route.
   - The default page is example.com - NOT your target. Navigate explicitly.
   - If no usable target URL exists, stop and report the missing URL instead of inventing one.
3. Execute each step interactively using `browser_*` tools to validate selectors
4. Retrieve the execution log using `generator_read_log`
5. Write the final test using `generator_write_test`
6. Immediately run the generated file with the correct verification tools:
   - Use `test_debug` scoped to `<test-file>{output_path}</test-file>` first when you need paused browser evidence.
   - After `test_debug` pauses, inspect with `browser_snapshot`, `browser_console_messages`, `browser_network_requests`, `browser_generate_locator`, and `browser_evaluate`.
   - Use `browser_resume` only after capturing paused-state evidence and only to continue the same debug run to the next action, assertion, or failure.
   - Use `test_run` scoped to `<test-file>{output_path}</test-file>` for final pass/fail verification.
   - Do not call `browser_close`; the runner owns browser cleanup.

## Dialog Handling (CRITICAL)
When browser dialogs appear (alerts, confirms, or "Leave site?" beforeunload dialogs):
- Use `browser_handle_dialog` with `accept: true` IMMEDIATELY to accept Leave and continue navigation
- Treat unsaved changes and beforeunload prompts as "Leave site?" dialogs unless the user explicitly asked you to preserve draft data
- After handling a dialog, call `browser_snapshot` or `browser_take_screenshot` to verify page state
- In generated code, include dialog handler for forms/editors:
  ```typescript
  page.on('dialog', async dialog => await dialog.accept());
  ```

## Code Generation Requirements

- Generate complete Playwright TypeScript test code
- If fixture test data is required, import `{{ test, expect }}` from the fixture helper path shown above instead of `@playwright/test`
- Use `test.describe('{test_suite}', () => {{ ... }})` to group all tests
- Each test case from the spec becomes a `test('...', async ({{ page, testData }}) => {{ ... }})` when fixture test data is used, otherwise `test('...', async ({{ page }}) => {{ ... }})`
- Include comments with the step text before each action
- Use the EXACT selectors discovered during browser execution
- Add proper `await` statements
- Use `expect()` for assertions
- Follow best practices from the seed file
- **CRITICAL**: Never write `process.env.TESTDATA_*` in generated code. Use `testData.get('<canonical-ref>')` or `testData.field('<canonical-ref>', '<path>')` for project test data.
- For non-TESTDATA legacy credentials with `{{{{VAR_NAME}}}}` placeholders, use `process.env.VAR_NAME!` in code (NOT hardcoded values)

## Robust Synchronization Requirements

- Do not use `page.waitForTimeout()` or hand-written sleeps.
- Prefer Playwright auto-waiting plus web-first assertions such as `await expect(locator).toBeVisible()`, `toHaveText()`, `toContainText()`, `toHaveURL()`, `toHaveValue()`, `toBeEnabled()`, and `toHaveCount()`.
- After actions that trigger navigation, wait for the durable destination with `await expect(page).toHaveURL(...)` or `await page.waitForURL(...)`.
- After actions that trigger async saves, uploads, searches, or list refreshes, wait for the durable result: a success toast, changed row/list count, visible record text, completed status, or the specific API response with `page.waitForResponse(...)`.
- Wait for loading indicators to become hidden only when they are part of the verified page behavior; do not wait for generic network idle unless the page has no better durable signal.
- If a control is disabled until data loads or validation completes, assert `await expect(control).toBeEnabled()` before interacting.
- Keep assertions tied to user-visible outcomes from the spec or verified plan; do not replace missing assertions with generic `body` visibility.

## Output

Save the generated test file to: {output_path}
"""
        metadata = build_prompt_metadata(
            prompt_id="native_generator.playwright",
            version="2026-05-13.1",
            stage="test_generation",
            schema_name="playwright_test_file.v1",
            rendered_prompt=prompt,
        )
        return attach_prompt_metadata(prompt, metadata)

    def _build_test_data_fixture_section(
        self,
        *,
        output_path: str,
        execution_credentials: dict[str, str] | None = None,
    ) -> str:
        ref = (execution_credentials or {}).get("test_data_ref")
        if not ref:
            return ""

        import_path = self._fixture_import_path(output_path)
        username = (execution_credentials or {}).get("username", "")
        password = (execution_credentials or {}).get("password", "")
        username_field = (execution_credentials or {}).get(
            "username_field"
        ) or "username"
        password_field = (execution_credentials or {}).get(
            "password_field"
        ) or "password"

        return f"""

## Project Test Data Fixture (IMPORTANT)
The source spec uses project test data ref `{ref}`. During browser execution, use these actual values:
- `{username_field}`: `{username}`
- `{password_field}`: `{password}`

Generated code must load these values from the Playwright fixture, not environment variables:
```typescript
import {{ test, expect }} from '{import_path}';

test('...', async ({{ page, testData }}) => {{
  const user = testData.get<{{ {username_field}: string; {password_field}: string }}>('{ref}');
  await page.getByLabel('Email').fill(user.{username_field});
  await page.getByLabel('Password').fill(user.{password_field});
}});
```

Do not write `process.env.TESTDATA_*` in generated code.
"""

    def _fixture_import_path(self, output_path: str) -> str:
        fixture_path = BASE_DIR / "tests" / "fixtures" / "test-data"
        relative = os.path.relpath(fixture_path, Path(output_path).parent)
        relative = Path(relative).as_posix()
        if not relative.startswith("."):
            relative = f"./{relative}"
        return relative

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
                agent_type="NativeGenerator",
                limit=8,
            )
            token_budget = context_budget_for_stage("native_generator", 1200)
            context = builder.format_prompt_context(bundle, token_budget=token_budget)
            if not context:
                return ""
            bundle_dict = bundle.to_dict()
            ranking = (bundle_dict.get("unified") or {}).get("ranking") or {}
            record_memory_injection(
                project_id=project_id,
                actor_type="agent",
                stage="native_generator",
                query=query[:1000],
                bundle=bundle_dict,
                context_text=context,
                source_type="spec",
                source_id=source_id,
                extra_data={
                    "spec_path": source_id,
                    **({"run_id": run_id} if run_id else {}),
                    "empty_recall": not bool(ranking.get("selected_items")),
                    "memory_score_summary": ranking.get("score_summary", {}),
                    "context_budget_tokens": token_budget,
                },
            )
            return f"""

## Memory Context
Use this memory only as advisory context. Validate remembered selectors, routes, and browser-state hints against the live browser before writing code.

{context}
"""
        except Exception as exc:
            logger.debug("Generator memory context skipped: %s", exc)
            return ""

    @staticmethod
    def _planner_evidence_summary(plan_content: str, *, token_budget: int) -> str:
        lines: list[str] = []
        for raw in (plan_content or "").splitlines():
            line = raw.strip()
            lower = line.lower()
            if not line:
                continue
            if re.match(r"^#{1,3}\s+", line) or line.startswith(
                ("**Steps:**", "**Expected Result:**", "**Test Data:**")
            ):
                lines.append(line)
            elif any(
                marker in lower
                for marker in (
                    "selector",
                    "getby",
                    "observed url",
                    "screenshot",
                    "confidence",
                    "source:",
                    "await expect",
                    "page.",
                )
            ):
                lines.append(line)
            elif re.match(r"^\d+\.\s+", line) and any(
                marker in lower
                for marker in (
                    "click",
                    "fill",
                    "navigate",
                    "verify",
                    "expect",
                    "visible",
                    "select",
                    "submit",
                )
            ):
                lines.append(line)
        summary = "\n".join(lines)
        return truncate_text_to_tokens(summary or plan_content, token_budget)

    def _record_generation_coverage(self, spec_content: str, output_path: Path) -> None:
        try:
            generated = output_path.read_text()
        except OSError:
            return
        warnings = self._coverage_warnings(spec_content, generated)
        self.last_coverage_warnings = warnings
        if not warnings:
            return
        logger.warning(
            "Generator spec coverage warnings for %s: %s",
            output_path,
            "; ".join(warnings[:5]),
        )
        artifact = output_path.with_suffix(".coverage.json")
        try:
            artifact.write_text(json.dumps({"warnings": warnings}, indent=2))
        except Exception:
            logger.debug("Could not write generator coverage artifact", exc_info=True)
        if os.environ.get("GENERATOR_ENFORCE_SPEC_COVERAGE", "0") == "1":
            raise RuntimeError(
                f"Generated test appears to miss spec coverage: {'; '.join(warnings[:5])}"
            )

    @staticmethod
    def _coverage_warnings(spec_content: str, generated_code: str) -> list[str]:
        def keywords(text: str) -> set[str]:
            words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", text.lower())
            stop = {
                "step",
                "steps",
                "expected",
                "result",
                "should",
                "with",
                "from",
                "into",
                "page",
                "user",
                "test",
                "case",
                "visible",
                "verify",
            }
            return {word for word in words if word not in stop}

        warnings: list[str] = []
        generated_lower = generated_code.lower()
        step_lines = [
            line.strip()
            for line in (spec_content or "").splitlines()
            if re.match(r"^\s*\d+\.\s+\S", line)
        ]
        expected_blocks = re.findall(
            r"\*\*Expected Result:\*\*\s*(.+)", spec_content or "", flags=re.IGNORECASE
        )
        for label, values in (
            ("step", step_lines),
            ("expected result", expected_blocks),
        ):
            for idx, text in enumerate(values, start=1):
                keys = sorted(keywords(text), key=len, reverse=True)[:4]
                if keys and not any(key in generated_lower for key in keys):
                    warnings.append(
                        f"Missing apparent {label} coverage #{idx}: {text[:180]}"
                    )
        if "expect(" not in generated_code and "test.fixme" not in generated_code:
            warnings.append(
                "Generated code has no Playwright expect() assertion or explicit test.fixme()."
            )
        return warnings[:25]

    async def _query_generator_agent(self, prompt: str) -> str:
        """
        Query the Playwright Generator agent using the unified AgentRunner.

        Uses explicit timeout and comprehensive logging.
        """
        timeout = int(
            os.environ.get("GENERATOR_TIMEOUT_SECONDS", get_default_timeout())
        )

        logger.info(f"Timeout: {timeout}s ({timeout // 60} minutes)")

        tool_config = get_agent_tool_config(
            "playwright-test-generator", mcp_config_dir=self.cwd
        )
        runner = AgentRunner(
            timeout_seconds=timeout,
            allowed_tools=tool_config.get("allowed_tools"),
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
            max_budget_usd=_optional_env_float("GENERATOR_MAX_BUDGET_USD"),
            memory_agent_type="NativeGenerator",
            memory_source_type="spec",
            memory_stage="native_generator",
            inject_memory=False,
            env_vars=self.env_vars,
            cwd=self.cwd,
            requires_live_browser=True,
            preserve_browser_on_failure=self.owner_type == "autopilot",
            autopilot_retry_enabled=(
                bool(getattr(self, "autopilot_retry_enabled", False))
                or self.owner_type == "autopilot"
            ),
            autopilot_session_id=getattr(self, "autopilot_session_id", None)
            or self.owner_id,
            autopilot_stable_key=getattr(self, "autopilot_stable_key", None),
            autopilot_agent_kind=getattr(self, "autopilot_agent_kind", "test_generation"),
            autopilot_source_type=getattr(self, "autopilot_source_type", None),
            autopilot_source_id=getattr(self, "autopilot_source_id", None),
            autopilot_checklist_title=getattr(self, "autopilot_checklist_title", None),
            autopilot_phase_name=getattr(self, "autopilot_phase_name", None),
            autopilot_checklist_kind=getattr(self, "autopilot_checklist_kind", None),
        )

        result = await runner.run(prompt)
        self.last_agent_result = result

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

    async def generate_all_tests(
        self, specs_dir: str = "specs", target_url: str | None = None
    ) -> list[Path]:
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
    parser.add_argument(
        "--all", action="store_true", help="Generate all prd-*.md specs"
    )
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
