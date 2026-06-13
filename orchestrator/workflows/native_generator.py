"""
Native Generator Workflow - Converts Test Specs to Playwright Code

This workflow uses the Playwright Test Generator agent to:
1. Read a markdown test spec
2. Execute each step in a live browser to validate selectors
3. Generate the final Playwright TypeScript test code
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

# Use run-specific config directory if set (for parallel execution isolation)
config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
if config_dir:
    os.chdir(config_dir)

from orchestrator.ai.prompt_registry import (
    attach_prompt_metadata,
    build_prompt_metadata,
)
from orchestrator.services.handoff_manifest import (
    record_artifact,
    record_consumption,
)
from orchestrator.utils.agent_runner import AgentRunner, get_default_timeout
from orchestrator.utils.agent_tool_allowlists import get_agent_allowed_tools
from orchestrator.utils.token_budget import context_budget_for_stage, truncate_text_to_tokens
from orchestrator.utils.text_utils import truncate_middle


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
            handoff_consumption["planner_draft_script_reason"] = "draft script path does not exist"

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

        # Check if the agent created the file
        if output_path.exists():
            logger.info(f"Test generated: {output_path}")
            self._record_generation_coverage(spec_content, output_path)
            if handoff_manifest_path:
                record_artifact(
                    handoff_manifest_path,
                    "generated_test",
                    output_path,
                    kind="playwright_test",
                    producer_stage="generator",
                    required=True,
                    consumers=["test_run", "healer"],
                    validation_status="valid",
                    metadata=handoff_consumption,
                )
            return output_path

        # Fallback: If agent returned code but didn't write it
        fixed_code = self._extract_code(result or "")
        if fixed_code:
            logger.info(f"Saving generated code to: {output_path}")
            output_path.write_text(fixed_code)
            self._record_generation_coverage(spec_content, output_path)
            if handoff_manifest_path:
                record_artifact(
                    handoff_manifest_path,
                    "generated_test",
                    output_path,
                    kind="playwright_test",
                    producer_stage="generator",
                    required=True,
                    consumers=["test_run", "healer"],
                    validation_status="valid",
                    metadata={**handoff_consumption, "source": "agent_response_fallback"},
                )
            return output_path

        logger.warning(f"Generator finished but test file not found at: {output_path}")
        return output_path

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
            key: value for key, value in credentials.items() if not key.startswith("TESTDATA_")
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
            mode = os.environ.get("GENERATOR_PLAN_EVIDENCE_MODE", "summary").strip().lower()
            if mode not in {"summary", "full"}:
                mode = "summary"
            plan_budget = context_budget_for_stage("generator_plan", 1600 if mode == "summary" else 2400)
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
            rendered_draft = truncate_text_to_tokens(planner_draft_script_content, draft_budget)
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

## Cleanup (IMPORTANT)
After writing the test file, call `browser_close` to close the browser before finishing.

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
        username_field = (execution_credentials or {}).get("username_field") or "username"
        password_field = (execution_credentials or {}).get("password_field") or "password"

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
            if re.match(r"^#{1,3}\s+", line) or line.startswith(("**Steps:**", "**Expected Result:**", "**Test Data:**")):
                lines.append(line)
            elif any(marker in lower for marker in ("selector", "getby", "observed url", "screenshot", "confidence", "source:", "await expect", "page.")):
                lines.append(line)
            elif re.match(r"^\d+\.\s+", line) and any(marker in lower for marker in ("click", "fill", "navigate", "verify", "expect", "visible", "select", "submit")):
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
        logger.warning("Generator spec coverage warnings for %s: %s", output_path, "; ".join(warnings[:5]))
        artifact = output_path.with_suffix(".coverage.json")
        try:
            artifact.write_text(json.dumps({"warnings": warnings}, indent=2))
        except Exception:
            logger.debug("Could not write generator coverage artifact", exc_info=True)
        if os.environ.get("GENERATOR_ENFORCE_SPEC_COVERAGE", "0") == "1":
            raise RuntimeError(f"Generated test appears to miss spec coverage: {'; '.join(warnings[:5])}")

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
        expected_blocks = re.findall(r"\*\*Expected Result:\*\*\s*(.+)", spec_content or "", flags=re.IGNORECASE)
        for label, values in (("step", step_lines), ("expected result", expected_blocks)):
            for idx, text in enumerate(values, start=1):
                keys = sorted(keywords(text), key=len, reverse=True)[:4]
                if keys and not any(key in generated_lower for key in keys):
                    warnings.append(f"Missing apparent {label} coverage #{idx}: {text[:180]}")
        if "expect(" not in generated_code and "test.fixme" not in generated_code:
            warnings.append("Generated code has no Playwright expect() assertion or explicit test.fixme().")
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

        runner = AgentRunner(
            timeout_seconds=timeout,
            allowed_tools=get_agent_allowed_tools("playwright-test-generator", mcp_config_dir=self.cwd),
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
