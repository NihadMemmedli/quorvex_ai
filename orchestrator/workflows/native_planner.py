"""
Native Planner Workflow - Hybrid Mode: PRD Context + Browser Exploration

This workflow uses the Playwright Test Planner agent with:
1. PRD context from RAG (ChromaDB)
2. Live browser exploration via MCP tools
3. SDK-based agent invocation
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

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
from orchestrator.memory import get_memory_manager
from orchestrator.utils.agent_runner import AgentRunner, get_default_timeout
from orchestrator.utils.agent_tool_allowlists import (
    PRD_LIVE_PLANNER_DISALLOWED_MCP_TOOLS,
    get_agent_tool_config,
)
from orchestrator.utils.string_utils import clean_extracted_url, slugify
from orchestrator.utils.token_budget import (
    context_budget_for_stage,
    truncate_text_to_tokens,
)

try:
    from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
except ImportError:  # pragma: no cover - SDK optional in unit tests
    PermissionResultAllow = None
    PermissionResultDeny = None


class SpecGenerationError(Exception):
    """Raised when spec generation fails to produce valid output."""

    def __init__(self, message: str, diagnostics: dict[str, Any] | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


class NativePlanner:
    """
    Hybrid Planner that combines PRD context with live browser exploration.

    Flow:
    1. Retrieve PRD context for the feature from ChromaDB
    2. Build a prompt with PRD requirements + target URL
    3. Invoke the Playwright Test Planner agent
    4. Agent explores the live app and generates a test plan
    5. Save the resulting spec to specs/prd-{feature}.md
    """

    def __init__(
        self,
        project_id: str = "default",
        on_tool_use: Callable[[str, dict[str, Any]], None] | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        on_task_enqueued: Callable[[str], None] | None = None,
        owner_type: str | None = None,
        owner_id: str | None = None,
        owner_label: str | None = None,
        model_tier: str = "tool_deep",
        session_dir: Path | None = None,
        cwd: Path | str | None = None,
        env_vars: dict[str, str] | None = None,
    ):
        self.project_id = project_id
        self.on_tool_use = on_tool_use
        self.on_progress = on_progress
        self.on_task_enqueued = on_task_enqueued
        self.owner_type = owner_type
        self.owner_id = owner_id
        self.owner_label = owner_label
        self.model_tier = model_tier
        self.session_dir = Path(session_dir) if session_dir else None
        self.cwd = Path(cwd) if cwd else self.session_dir
        self.env_vars = dict(env_vars or {})
        self.last_draft_script_path: Path | None = None
        self.last_agent_result = None
        self.memory_manager = get_memory_manager(project_id=project_id)
        # Use absolute path relative to project root (up from orchestrator/workflows/native_planner.py)
        self.specs_dir = Path(__file__).resolve().parent.parent.parent / "specs"
        self.specs_dir.mkdir(exist_ok=True)

    async def generate_spec_for_feature(
        self,
        feature_name: str,
        prd_project: str,
        target_url: str | None = None,
        login_url: str | None = None,
        credentials: dict[str, str] | None = None,
        additional_context: str | None = None,
    ) -> Path:
        """
        Generate a test spec for a specific feature using Hybrid Mode.

        Args:
            feature_name: Name of the feature (e.g. "Section Management")
            prd_project: Project ID where PRD chunks are stored
            target_url: URL of the live application to explore (optional)
            login_url: URL of the login page (optional, defaults to target_url if not provided)
            credentials: Dict with 'username' and 'password' for login (optional)

        Returns:
            Path to the generated spec file
        """
        target_url = self._normalize_url_for_prompt(target_url)
        login_url = self._normalize_url_for_prompt(login_url)
        feature_slug = slugify(feature_name)
        # Organize specs into project-specific folders
        project_dir = self.specs_dir / prd_project
        project_dir.mkdir(parents=True, exist_ok=True)
        output_path = project_dir / f"{feature_slug}.md"

        # 1. Retrieve PRD context from RAG
        logger.info(f"Retrieving PRD context for: {feature_name}")
        chunks = self.memory_manager.vector_store.search_prd_context(
            query=feature_name, project_id=prd_project, n_results=5
        )

        prd_context = self._build_context_text(chunks)

        if not prd_context.strip():
            logger.warning(f"No PRD context found for {feature_name}")
            prd_context = (
                "No specific PRD context available. Generate based on feature name."
            )
        if additional_context:
            prd_context = f"{prd_context.rstrip()}\n\n{additional_context.strip()}"

        # 2. Build the hybrid prompt
        prompt = self._build_hybrid_prompt(
            feature_name=feature_name,
            feature_slug=feature_slug,
            prd_context=prd_context,
            target_url=target_url,
            login_url=login_url,
            credentials=credentials,
            output_path=str(output_path),
        )

        # 3. Invoke the Playwright Planner Agent via SDK
        logger.info(f"Invoking Playwright Planner Agent for: {feature_name}")
        if target_url:
            logger.info(f"   Target URL: {target_url}")

        return await self._run_planner_with_retry(
            subject_type="feature",
            subject_name=feature_name,
            prompt=prompt,
            target_url=target_url,
            expected_output_path=output_path,
        )

    def _build_hybrid_prompt(
        self,
        feature_name: str,
        feature_slug: str,
        prd_context: str,
        target_url: str | None,
        login_url: str | None,
        credentials: dict[str, str] | None,
        output_path: str,
        auth_context: dict[str, Any] | None = None,
    ) -> str:
        """Build the prompt that combines PRD context with browser exploration instructions."""

        target_url = self._normalize_url_for_prompt(target_url)
        login_url = self._normalize_url_for_prompt(login_url)
        split_tc_section = self._split_tc_scope_section(
            feature_name=feature_name,
            feature_slug=feature_slug,
            prd_context=prd_context,
            output_path=output_path,
        )

        browser_section = ""
        if target_url:
            auth_prompt_context = (
                "" if credentials else self._browser_auth_prompt_context(auth_context)
            )
            # Build login section if credentials provided
            login_section = ""
            if credentials:
                actual_login_url = login_url or target_url
                username = credentials.get("username", "")
                password = credentials.get("password", "")
                # Get environment variable names if provided
                username_var = credentials.get("username_var", "LOGIN_USERNAME")
                password_var = credentials.get("password_var", "LOGIN_PASSWORD")
                test_data_ref = credentials.get("test_data_ref")
                ref_instruction = ""
                if test_data_ref:
                    ref_instruction = f"""
## Test Data Directive Preservation
The source spec referenced `@testdata "{test_data_ref}"`.
Preserve that exact directive or an equivalent **Test Data** note in every generated TC that depends on these credentials.
Generated steps must use placeholders `{{{{{username_var}}}}}` and `{{{{{password_var}}}}}`, not plaintext credential values.
"""
                login_section = f"""
## Step 1: Login to the Application
Before exploring the feature, you MUST login first:

1. Navigate to: {actual_login_url}
2. Look for the login form (email/username field + password field)
3. Enter username/email: `{username}` (use this value NOW for browser execution)
4. Enter password: `{password}` (use this value NOW for browser execution)
5. Click the login/submit button
6. Wait for the dashboard or home page to load
7. Verify you are logged in (look for user menu, avatar, or logout button)

**CRITICAL**: Do not proceed to the feature URL until login is successful.

## Credential Placeholders for Generated Spec
When writing the test spec, use these PLACEHOLDERS (not actual values):
- For username/email: `{{{{{username_var}}}}}`
- For password: `{{{{{password_var}}}}}`

Example in spec: `Enter "{{{{{username_var}}}}}" into the email field`
{ref_instruction}
"""

            browser_section = f"""
## Browser Exploration (REQUIRED)
You MUST open a browser and explore the live application.

{auth_prompt_context}

{login_section}

## Step {"2" if credentials else "1"}: Navigate and Explore the Feature
- **Target URL**: {target_url}

Use the Playwright MCP tools to:
1. Call `planner_setup_page` with `seedFile: "tests/seed.spec.ts"` to initialize the browser
2. **IMMEDIATELY** call `browser_navigate` to go to: {target_url}
   (Do NOT rely on any default page - the default is example.com. Navigate explicitly!)
3. Use `browser_snapshot` to see the current page state
4. Explore the interface related to "{feature_name}"
5. Identify all interactive elements, buttons, forms, and user flows
6. Record the EXACT selectors you find (getByRole, getByText, etc.)
7. Take additional snapshots as you navigate
8. Periodically call `browser_take_screenshot` with filenames like `live-step-001.png`,
   `live-step-002.png`, etc. so the dashboard can show live visual evidence while you work

**MANDATORY ORDER BEFORE WRITING THE PLAN**:
`planner_setup_page` → `browser_navigate` to the exact Target URL above → `browser_snapshot`.
Do not call `planner_save_plan` until after those three actions have happened in that order.

**IMPORTANT**: Include the actual selectors you discover in the test plan.

## Dialog Handling (CRITICAL)
When navigating between pages or away from forms/editors, "Leave site?" dialogs may appear:
- Use `browser_handle_dialog` with `accept: true` IMMEDIATELY to accept Leave and continue navigation
- Treat unsaved changes and beforeunload prompts as "Leave site?" dialogs unless the user explicitly asked you to preserve draft data
- After handling a dialog, call `browser_snapshot` or `browser_take_screenshot` to verify page state
- Document any dialogs encountered (they indicate user flows that need testing)
"""
        else:
            browser_section = """
## Note: No Target URL Provided
Generate the test plan based on the PRD requirements below.
The test steps should be generalized and will need selector updates during code generation.
Do not use browser tools or repository inspection tools for this PRD-only plan.
"""

        draft_output_path = Path(output_path).with_suffix(".draft.spec.ts")

        if target_url:
            save_section = f"""
## Save the Plan
After creating the test plan:
1. Save it using `planner_save_plan` tool to: **{output_path}**
2. Include a `## Draft Playwright Script` section in the saved markdown plan
3. In that section, include one fenced `typescript` code block with a draft Playwright test script
4. Write the same draft script to **{draft_output_path}** using `generator_write_test`
5. Run/debug the draft with `test_debug` first, then use `test_run` scoped to **{draft_output_path}** for final pass/fail evidence when practical
6. ALSO output the COMPLETE test plan as text in your response (not just a summary)
7. Do not call `browser_close`; the system will validate the saved plan and handle browser cleanup after acceptance or final failure
"""
        else:
            save_section = f"""
## Return the Plan
Return the COMPLETE test plan as markdown in your final response.
The system will write your final markdown to: **{output_path}**
Do not call `planner_save_plan` or `browser_close`.
Include a `## Draft Playwright Script` section with one fenced `typescript` code block.
"""

        if split_tc_section:
            output_requirements = f"""
## Output Requirements
{split_tc_section}

Return exactly one independently runnable TC section for "{feature_name}":
- `### TC-XXX: [Scenario Name]`
- `**Description:** ...`
- `**Preconditions:** ...`
- `**Steps:**` numbered action steps with ACTUAL SELECTORS if discovered
- `**Expected Result:**` concrete assertions or observable outcomes
- `**Test Data:**` preserve required placeholders, URLs, and `@testdata` refs

Then add:
- `## Draft Playwright Script`
- one fenced `typescript` code block containing draft Playwright code for that TC
"""
            critical_scope = (
                "**CRITICAL**: Preserve exactly one scenario. Do NOT add extra "
                "negative/login-reset/mobile/accessibility/responsive cases unless "
                "the input split spec explicitly asks for them."
            )
        else:
            output_requirements = """
## Output Requirements
Create balanced E2E scenario specs for "{feature_name}". Prefer 6-12 scenarios when the evidence supports it. Each scenario must be specific enough to run through the existing markdown-to-Playwright pipeline.

Cover these categories where evidence exists:
1. **Happy Path** - Normal user journeys that should work
2. **Navigation/State Transitions** - Multi-page or state-changing paths
3. **Negative/Error Scenarios** - Invalid, missing, unauthorized, or failed states
4. **Edge Cases** - Boundary conditions and unusual inputs
5. **Accessibility** - Keyboard and accessible-name checks
6. **Responsive/Runtime Regression** - Mobile viewport and critical console-error checks
7. **API-backed Assertions** - Only when API/network evidence was observed

## Test Spec Format
Return a split-ready plan with TC-XXX sections. Every TC must be independently runnable after splitting:
- `### TC-XXX: [Scenario Name]`
- `**Description:** ...`
- `**Preconditions:** ...`
- `**Steps:**` numbered action steps with ACTUAL SELECTORS if discovered
- `**Expected Result:**` concrete assertions or observable outcomes
- `**Test Data:**` optional placeholders and URLs

Then add:
- `## Draft Playwright Script`
- one fenced `typescript` code block containing a draft Playwright test file that covers the TC sections
""".format(
                feature_name=feature_name
            )
            critical_scope = (
                "**CRITICAL**: Your final text response MUST contain the full test "
                "plan with all TC-XXX test cases, steps, and expected results. "
                'Do NOT output just a summary like "I created 24 test cases". '
                'Do NOT create a single shallow spec with only "Navigate" and "Verify".'
            )

        prompt = f"""You are the Playwright Test Planner agent.

# Task: Generate Test Plan for "{feature_name}"

{browser_section}

## PRD Requirements Context
The following requirements were extracted from the Product Requirements Document:

{prd_context}

{output_requirements}

## Evidence Rules
- Do not invent unsupported business behavior.
- If evidence is thin, generate conservative page/journey checks: reachability, no blocking errors, accessibility basics, responsive rendering, and stable navigation.
- Use observed selectors, text, URLs, and API endpoints when available.
- Mark auth or data needs in Preconditions instead of hardcoding secrets.

## Draft Script Rules
- The draft script is required. It is a handoff artifact for the generator agent.
- Use Playwright locators and assertions based on what you observed, for example `page.getByRole(...)` and `await expect(...).toBeVisible()`.
- Add durable waits after navigations or async actions with `await expect(page).toHaveURL(...)`, `await page.waitForURL(...)`, web-first assertions, or `page.waitForResponse(...)` when API evidence supports it.
- Do not use `page.waitForTimeout()` or arbitrary sleeps.
- Keep credential values as `process.env.VAR_NAME!` or project test-data fixture placeholders; never hardcode secrets.
- Make the draft script executable as a standalone Playwright spec. Use the correct MCP tools for each phase:
  - `generator_write_test` creates or updates `{draft_output_path}` with the draft TypeScript spec.
  - `test_debug` runs the draft in paused debug mode and is the required tool when you need failure-state evidence.
  - After `test_debug` pauses, inspect with `browser_snapshot`, `browser_console_messages`, `browser_network_requests`, `browser_generate_locator`, and `browser_evaluate` as needed.
  - Use `browser_resume` only after you have captured paused-state evidence and need the same run to continue to the next action, assertion, or failure.
  - Use `test_run` scoped to `{draft_output_path}` for final pass/fail evidence when practical before handing it to the generator.
- Plan for paused-state debugging: the generator/healer will use the same `test_debug` -> browser diagnostic tools -> optional `browser_resume` flow when failures need investigation.
- Do not include script cleanup that closes the browser. The runner owns cleanup; preserving the paused debug browser state is part of the handoff.
- If a draft flow may fail because of dynamic data or app state, describe the expected paused-state evidence and the diagnostic tool that should confirm it.

{save_section}

{critical_scope}

Start the test plan with:
# Test Plan: {feature_name}
"""
        metadata = build_prompt_metadata(
            prompt_id="native_planner.hybrid",
            version="2026-05-13.1",
            stage="test_planning",
            schema_name="playwright_test_plan.v1",
            rendered_prompt=prompt,
        )
        return attach_prompt_metadata(prompt, metadata)

    @staticmethod
    def _browser_auth_prompt_context(context: dict[str, Any] | None = None) -> str:
        if not context or not context.get("storage_state_attached"):
            return ""
        session_name = (
            context.get("browser_auth_session_name")
            or context.get("browser_auth_session_id")
            or "selected session"
        )
        return (
            "## Browser Authentication Context\n"
            f"The browser starts authenticated with saved session `{session_name}`. "
            "Do not generate login steps unless the scenario explicitly tests login, logout, or authentication failure."
        )

    @staticmethod
    def _split_tc_scope_section(
        *,
        feature_name: str,
        feature_slug: str,
        prd_context: str,
        output_path: str,
    ) -> str:
        candidates = " ".join(
            [
                feature_name or "",
                feature_slug or "",
                Path(output_path).name if output_path else "",
                prd_context[:1000] if prd_context else "",
            ]
        ).lower()
        match = re.search(r"\btc[-_ ]?(\d{3})\b", candidates)
        if not match:
            return ""
        tc_id = f"TC-{match.group(1)}"
        extra = ""
        if match.group(1) == "001":
            extra = (
                "\nFor TC-001 valid-login specs, wrong-password exploration belongs "
                "only in a different negative TC unless the input split spec explicitly "
                "asks for wrong-password behavior."
            )
        return f"""## Split TC Scope Control
The input is an already split single test-case spec (`{tc_id}`). Enhance only that TC.
- Preserve exactly one scenario and keep the same `{tc_id}` identity.
- Do not generate extra negative/login-reset/mobile/accessibility/responsive/regression cases.
- Preserve any canonical `@testdata` reference from the source spec, including `@testdata "wetravel-auth.valid-user"` when present.
- Use browser exploration only to strengthen selectors and assertions for this one scenario.{extra}
"""

    async def _query_planner_agent(self, prompt: str, target_url: str | None = None):
        """
        Query the Playwright Planner agent using the unified AgentRunner.

        Uses explicit timeout and comprehensive logging.
        Returns the full AgentResult (with tool_calls for plan extraction).
        """
        timeout = int(os.environ.get("PLANNER_TIMEOUT_SECONDS", get_default_timeout()))

        logger.info(f"Timeout: {timeout}s ({timeout // 60} minutes)")

        target_url = self._normalize_url_for_prompt(target_url)
        profile_name = "prd-live-planner" if target_url else "prd-only-planner"
        tool_config = get_agent_tool_config(profile_name, mcp_config_dir=self.cwd)

        runner = AgentRunner(
            timeout_seconds=timeout,
            allowed_tools=tool_config.get("allowed_tools"),
            tools=tool_config.get("tools"),
            disallowed_tools=tool_config.get("disallowed_tools"),
            log_tools=True,
            on_tool_use=self.on_tool_use,
            on_progress=self.on_progress,
            on_task_enqueued=self.on_task_enqueued,
            session_dir=self.session_dir,
            cwd=self.cwd,
            owner_type=self.owner_type,
            owner_id=self.owner_id,
            owner_label=self.owner_label,
            requires_live_browser=bool(target_url),
            model_tier=self.model_tier,
            env_vars=self.env_vars,
            resume_session_id=getattr(self, "_planner_retry_session_id", None),
            continue_conversation=bool(
                getattr(self, "_planner_retry_continue_conversation", False)
                and not getattr(self, "_planner_retry_session_id", None)
            ),
            tool_permission_guard=(
                self._build_live_plan_permission_guard(target_url)
                if target_url
                else None
            ),
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

        return result

    @staticmethod
    def _planner_max_attempts() -> int:
        raw_value = os.environ.get("PLANNER_MAX_ATTEMPTS", "5")
        try:
            return min(5, max(1, int(raw_value)))
        except ValueError:
            return 5

    async def _run_planner_with_retry(
        self,
        *,
        subject_type: str,
        subject_name: str,
        prompt: str,
        target_url: str | None,
        expected_output_path: Path,
    ) -> Path:
        max_attempts = self._planner_max_attempts()
        current_prompt = prompt
        last_error: SpecGenerationError | None = None
        self.last_draft_script_path = None
        require_draft_script = bool(target_url)
        retry_session_id: str | None = None

        for attempt_number in range(1, max_attempts + 1):
            if attempt_number > 1:
                logger.info(
                    "Retrying planner for %s '%s' after rejected attempt %s/%s",
                    subject_type,
                    subject_name,
                    attempt_number - 1,
                    max_attempts,
                )

            self._planner_retry_session_id = retry_session_id
            self._planner_retry_continue_conversation = (
                attempt_number > 1 and not retry_session_id
            )
            try:
                agent_result = await self._query_planner_agent(
                    current_prompt, target_url=target_url
                )
            finally:
                self._planner_retry_session_id = None
                self._planner_retry_continue_conversation = False
            retry_session_id = (
                getattr(agent_result, "session_id", None) or retry_session_id
            )
            try:
                live_sequence_error: SpecGenerationError | None = None
                if target_url:
                    try:
                        self._validate_live_plan_tool_sequence(agent_result, target_url)
                    except SpecGenerationError as exc:
                        live_sequence_error = exc

                saved_plan_path = self._recover_saved_plan(expected_output_path)
                if saved_plan_path:
                    logger.info(f"Spec saved by agent: {saved_plan_path}")
                    finalized_path = await self._finalize_or_repair_plan_artifact(
                        plan_path=saved_plan_path,
                        expected_output_path=expected_output_path,
                        require_draft_script=require_draft_script,
                        subject_type=subject_type,
                        subject_name=subject_name,
                        agent_result=agent_result,
                    )
                    if live_sequence_error:
                        self._record_live_sequence_warning(
                            error=live_sequence_error,
                            expected_output_path=expected_output_path,
                            generated_plan_path=finalized_path,
                        )
                    return finalized_path

                plan_content = self._extract_plan_content(agent_result)
                if plan_content:
                    logger.info(
                        f"Saving extracted plan as spec: {expected_output_path}"
                    )
                    expected_output_path.parent.mkdir(parents=True, exist_ok=True)
                    expected_output_path.write_text(plan_content)
                    finalized_path = await self._finalize_or_repair_plan_artifact(
                        plan_path=expected_output_path,
                        expected_output_path=expected_output_path,
                        require_draft_script=require_draft_script,
                        subject_type=subject_type,
                        subject_name=subject_name,
                        agent_result=agent_result,
                    )
                    if live_sequence_error:
                        self._record_live_sequence_warning(
                            error=live_sequence_error,
                            expected_output_path=expected_output_path,
                            generated_plan_path=finalized_path,
                        )
                    return finalized_path

                repaired_plan_path = await self._attempt_repair_plan(
                    subject_type=subject_type,
                    subject_name=subject_name,
                    agent_result=agent_result,
                    expected_output_path=expected_output_path,
                    require_draft_script=require_draft_script,
                )
                if repaired_plan_path:
                    finalized_path = self._finalize_plan_artifact(
                        plan_path=repaired_plan_path,
                        expected_output_path=expected_output_path,
                        require_draft_script=require_draft_script,
                    )
                    if live_sequence_error:
                        self._record_live_sequence_warning(
                            error=live_sequence_error,
                            expected_output_path=expected_output_path,
                            generated_plan_path=finalized_path,
                        )
                    return finalized_path

                if live_sequence_error:
                    raise live_sequence_error

                logger.error(
                    "Agent produced no usable output for %s: %s",
                    subject_type,
                    subject_name,
                )
                raise self._build_no_output_error(
                    subject_type=subject_type,
                    subject_name=subject_name,
                    agent_result=agent_result,
                    expected_output_path=expected_output_path,
                )
            except SpecGenerationError as exc:
                last_error = exc
                if attempt_number >= max_attempts:
                    raise
                current_prompt = self._build_planner_retry_prompt(
                    original_prompt=prompt,
                    subject_type=subject_type,
                    subject_name=subject_name,
                    error=exc,
                    target_url=target_url,
                    expected_output_path=expected_output_path,
                    agent_result=agent_result,
                )
                if not exc.diagnostics.get("planner_repair_attempted"):
                    self._discard_rejected_plan_artifact(expected_output_path)

        if last_error:
            raise last_error
        raise SpecGenerationError(
            f"Failed to generate spec for {subject_type} '{subject_name}'."
        )

    @staticmethod
    def _discard_rejected_plan_artifact(expected_output_path: Path) -> None:
        try:
            if expected_output_path.exists() and expected_output_path.is_file():
                expected_output_path.unlink()
            draft_path = NativePlanner._draft_script_path_for_plan(expected_output_path)
            if draft_path.exists() and draft_path.is_file():
                draft_path.unlink()
        except OSError as exc:
            logger.debug(
                "Could not discard rejected planner artifact %s: %s",
                expected_output_path,
                exc,
            )

    def _record_live_sequence_warning(
        self,
        *,
        error: SpecGenerationError,
        expected_output_path: Path,
        generated_plan_path: Path,
    ) -> None:
        diagnostics = dict(error.diagnostics)
        diagnostics.update(
            {
                "expected_output_path": str(expected_output_path),
                "generated_plan_path": str(generated_plan_path),
                "valid_saved_plan_observed": True,
                "warning": self._redact_sensitive_text(str(error)),
            }
        )
        logger.warning(
            "Accepting valid saved planner output despite live-browser sequence warning: %s",
            diagnostics["warning"],
        )
        if not self.session_dir:
            return
        try:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            (self.session_dir / "planner_live_sequence_warning.json").write_text(
                json.dumps(diagnostics, indent=2, sort_keys=True, default=str)
            )
        except OSError:
            logger.debug(
                "Could not write planner live sequence warning artifact", exc_info=True
            )

    def _build_planner_retry_prompt(
        self,
        *,
        original_prompt: str,
        subject_type: str,
        subject_name: str,
        error: SpecGenerationError,
        target_url: str | None,
        expected_output_path: Path,
        agent_result: Any | None = None,
    ) -> str:
        diagnostics = self._redact_sensitive_text(
            json.dumps(error.diagnostics, indent=2, sort_keys=True, default=str)
        )
        previous_context = self._build_retry_context(
            agent_result=agent_result,
            expected_output_path=expected_output_path,
        )
        target_instruction = ""
        if target_url:
            target_instruction = (
                "\nFor this retry, the browser contract still must be satisfied. Call "
                "`planner_setup_page`, then `browser_navigate` to the exact Target URL "
                f"`{target_url}`, then `browser_snapshot` before calling `planner_save_plan`."
            )
        return f"""You are retrying a rejected Playwright planner attempt.

The previous attempt for {subject_type} "{subject_name}" was rejected. Do not repeat its failed tool sequence, but reuse the useful observations and selectors summarized below.

Rejection:
{self._redact_sensitive_text(str(error))}

Diagnostics:
```json
{diagnostics}
```
{target_instruction}
{previous_context}

Write a valid markdown test plan to `{expected_output_path}` with this exact schema:
- `# Test Plan: {subject_name}`
- One or more `### TC-XXX: <scenario>` sections
- Each TC must include `**Description:**`, `**Preconditions:**`, `**Steps:**` with numbered steps, and `**Expected Result:**`
- Include `## Draft Playwright Script` with one fenced `typescript` code block containing draft Playwright code
- The draft code must use web-first assertions/durable waits and must not use `page.waitForTimeout()`
- Use placeholders for credentials; do not include secrets.

Original task follows. Obey it, but correct the failure above.

---

{original_prompt}
"""

    def _build_retry_context(
        self,
        *,
        agent_result: Any | None,
        expected_output_path: Path,
    ) -> str:
        parts: list[str] = []
        if agent_result is not None:
            tool_calls = list(getattr(agent_result, "tool_calls", []) or [])
            stats = {
                "success": bool(getattr(agent_result, "success", False)),
                "timed_out": bool(getattr(agent_result, "timed_out", False)),
                "error": getattr(agent_result, "error", None),
                "messages_received": int(
                    getattr(agent_result, "messages_received", 0) or 0
                ),
                "text_blocks_received": int(
                    getattr(agent_result, "text_blocks_received", 0) or 0
                ),
                "tool_calls": len(tool_calls),
            }
            parts.extend(
                [
                    "",
                    "Previous attempt compact context:",
                    "```json",
                    self._redact_sensitive_text(
                        json.dumps(stats, indent=2, sort_keys=True, default=str)
                    ),
                    "```",
                ]
            )
            summary = self._tool_call_retry_summary(tool_calls)
            if summary:
                parts.extend(["", "Previous tool sequence:", "```text", summary, "```"])

            raw_output = str(getattr(agent_result, "output", "") or "").strip()
            if raw_output:
                parts.extend(
                    [
                        "",
                        "Previous raw output preview:",
                        "```markdown",
                        self._content_preview(raw_output, limit=3000),
                        "```",
                    ]
                )

        try:
            if expected_output_path.exists() and expected_output_path.is_file():
                content = expected_output_path.read_text()
                if content.strip():
                    parts.extend(
                        [
                            "",
                            "Rejected saved plan preview:",
                            "```markdown",
                            self._content_preview(content, limit=5000),
                            "```",
                        ]
                    )
        except OSError:
            logger.debug(
                "Could not read rejected plan preview from %s",
                expected_output_path,
                exc_info=True,
            )

        return "\n".join(parts)

    @classmethod
    def _tool_call_retry_summary(cls, tool_calls: list[Any]) -> str:
        lines: list[str] = []
        for idx, tool_call in enumerate(
            tool_calls[-40:], start=max(1, len(tool_calls) - 39)
        ):
            short_name = cls._tool_call_short_name(tool_call)
            tool_input = getattr(tool_call, "input", None)
            details: dict[str, Any] = {}
            if isinstance(tool_input, dict):
                for key in (
                    "url",
                    "target_url",
                    "targetUrl",
                    "seedFile",
                    "fileName",
                    "path",
                ):
                    value = tool_input.get(key)
                    if isinstance(value, str) and value.strip():
                        details[key] = cls._redact_sensitive_text(value)
                payload = cls._extract_plan_payload(tool_input)
                if payload:
                    details["payload_length"] = len(payload)
                    details["payload_preview"] = cls._content_preview(
                        payload, limit=500
                    )
            suffix = (
                f" {json.dumps(details, sort_keys=True, default=str)}"
                if details
                else ""
            )
            lines.append(f"{idx}. {short_name}{suffix}")
        if len(tool_calls) > 40:
            lines.insert(0, f"... omitted {len(tool_calls) - 40} earlier tool calls")
        return "\n".join(lines)

    def _build_live_plan_permission_guard(self, target_url: str | None):
        if (
            not target_url
            or PermissionResultAllow is None
            or PermissionResultDeny is None
        ):
            return None

        expected = self._canonical_url(target_url)
        state = {
            "setup_seen": False,
            "target_navigation_seen": False,
            "snapshot_after_navigation_seen": False,
        }

        async def guard(
            tool_name: str,
            tool_input: dict[str, Any],
            _context: Any,
        ):
            short_name = tool_name.split("__")[-1] if "__" in tool_name else tool_name

            if short_name == "browser_close":
                return PermissionResultDeny(
                    message=(
                        "browser_close is system-owned for live planner runs. Save the plan "
                        "with planner_save_plan and finish; the orchestrator validates the plan "
                        "and handles browser cleanup after acceptance or final failure."
                    )
                )
            if short_name in {"browser_run_code", "browser_file_upload"}:
                return PermissionResultDeny(
                    message=(
                        f"{short_name} is not available in live planner runs. Use visible "
                        "browser interactions, snapshots, locator generation, and verification tools."
                    )
                )
            if short_name in PRD_LIVE_PLANNER_DISALLOWED_MCP_TOOLS:
                return PermissionResultDeny(
                    message=(
                        f"{short_name} is not available in live planner runs. Use safe visible "
                        "browser interactions instead: planner_setup_page, browser_navigate, "
                        "browser_snapshot, browser_click, browser_type, browser_wait_for, "
                        "browser_take_screenshot, browser_handle_dialog, then planner_save_plan."
                    )
                )

            if short_name == "planner_save_plan":
                missing = []
                if not state["setup_seen"]:
                    missing.append("call `planner_setup_page`")
                if not state["target_navigation_seen"]:
                    missing.append(f"call `browser_navigate` to `{target_url}`")
                if not state["snapshot_after_navigation_seen"]:
                    missing.append("call `browser_snapshot` after target navigation")
                if missing:
                    return PermissionResultDeny(
                        message=(
                            "planner_save_plan is blocked until the live-browser "
                            f"planning contract is satisfied. Required next actions: {', '.join(missing)}."
                        )
                    )
                return PermissionResultAllow()

            if short_name == "planner_setup_page":
                state["setup_seen"] = True
            elif short_name == "browser_navigate":
                actual = self._canonical_url(
                    tool_input.get("url")
                    or tool_input.get("target_url")
                    or tool_input.get("targetUrl")
                )
                if actual == expected:
                    state["target_navigation_seen"] = True
                    state["snapshot_after_navigation_seen"] = False
            elif short_name == "browser_snapshot" and state["target_navigation_seen"]:
                state["snapshot_after_navigation_seen"] = True

            return PermissionResultAllow()

        return guard

    @staticmethod
    def _normalize_url_for_prompt(target_url: str | None) -> str | None:
        return clean_extracted_url(target_url)

    @staticmethod
    def _canonical_url(value: str | None) -> str | None:
        value = clean_extracted_url(value)
        if not value:
            return None
        try:
            parsed = urlsplit(value)
        except ValueError:
            return value.rstrip("/")
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/") or "/"
        query = parsed.query
        return urlunsplit((scheme, netloc, path, query, ""))

    @classmethod
    def _tool_call_short_name(cls, tool_call: Any) -> str:
        name = str(getattr(tool_call, "name", "") or "")
        return name.split("__")[-1] if "__" in name else name

    @classmethod
    def _tool_call_url(cls, tool_call: Any) -> str | None:
        tool_input = getattr(tool_call, "input", None)
        if not isinstance(tool_input, dict):
            return None
        for key in ("url", "target_url", "targetUrl"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    @classmethod
    def _validate_live_plan_tool_sequence(
        cls, agent_result: Any, target_url: str
    ) -> None:
        """Reject live PRD plans that were saved without first visiting Target URL."""
        expected = cls._canonical_url(target_url)
        tool_calls = list(getattr(agent_result, "tool_calls", []) or [])
        setup_seen = False
        navigate_seen = False
        snapshot_seen = False
        save_seen = False

        for tool_call in tool_calls:
            short_name = cls._tool_call_short_name(tool_call)
            if short_name == "planner_setup_page":
                setup_seen = True
            elif short_name == "browser_navigate":
                actual = cls._canonical_url(cls._tool_call_url(tool_call))
                if actual == expected:
                    navigate_seen = True
            elif short_name == "browser_snapshot" and navigate_seen:
                snapshot_seen = True
            elif short_name in {"planner_save_plan", "save_plan"}:
                save_seen = True
                if not (setup_seen and navigate_seen and snapshot_seen):
                    raise SpecGenerationError(
                        "Live-browser planner saved a plan before navigating to the Target URL and capturing a snapshot.",
                        diagnostics={
                            "expected_target_url": target_url,
                            "planner_setup_page_observed": setup_seen,
                            "target_navigation_observed": navigate_seen,
                            "browser_snapshot_after_navigation_observed": snapshot_seen,
                            "planner_save_plan_observed": True,
                        },
                    )

        if not navigate_seen:
            raise SpecGenerationError(
                f"Live-browser planner did not navigate to the Target URL before finishing: {target_url}",
                diagnostics={
                    "expected_target_url": target_url,
                    "planner_setup_page_observed": setup_seen,
                    "target_navigation_observed": False,
                    "browser_snapshot_after_navigation_observed": snapshot_seen,
                    "planner_save_plan_observed": save_seen,
                },
            )

    @staticmethod
    def _looks_like_test_plan(content: str) -> bool:
        """Return true when markdown contains real test-case structure."""
        return any(marker in content for marker in ("TC-", "Test Case", "## Steps"))

    @staticmethod
    def _redact_sensitive_text(content: str) -> str:
        patterns = (
            r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+",
            r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|credential)\b(\s*[:=]\s*)([^\s,;`]+)",
        )
        redacted = content
        for pattern in patterns:
            redacted = re.sub(
                pattern,
                lambda match: f"{match.group(1)}{match.group(2) if len(match.groups()) > 1 else ' '}[REDACTED]",
                redacted,
            )
        return redacted

    @classmethod
    def _content_preview(cls, content: str, limit: int = 2000) -> str:
        normalized = cls._redact_sensitive_text(content).replace("\x00", " ").strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit] + f"\n...[truncated {len(normalized) - limit} chars]"

    @staticmethod
    def _content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()

    @staticmethod
    def _extract_plan_payload(tool_input: Any) -> str | None:
        if not isinstance(tool_input, dict):
            return None
        for key in ("content", "plan", "markdown"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value
        rendered = NativePlanner._render_structured_plan_payload(tool_input)
        if rendered:
            return rendered
        return None

    @staticmethod
    def _render_structured_plan_payload(tool_input: dict[str, Any]) -> str | None:
        suites = tool_input.get("suites")
        if not isinstance(suites, list) or not suites:
            return None

        raw_name = str(tool_input.get("name") or "Generated Plan").strip()
        if raw_name.lower().startswith("test plan:"):
            title = raw_name
        else:
            title = f"Test Plan: {raw_name}"

        lines = [f"# {title}", ""]
        overview = str(tool_input.get("overview") or "").strip()
        if overview:
            lines.extend(["## Application Overview", "", overview, ""])

        tc_number = 1
        for suite in suites:
            if not isinstance(suite, dict):
                continue
            tests = suite.get("tests")
            if not isinstance(tests, list):
                continue
            for test_case in tests:
                if not isinstance(test_case, dict):
                    continue
                name = str(test_case.get("name") or f"Scenario {tc_number}").strip()
                steps = [
                    str(step).strip()
                    for step in (test_case.get("steps") or [])
                    if str(step).strip()
                ]
                expected_results = [
                    str(result).strip()
                    for result in (test_case.get("expectedResults") or [])
                    if str(result).strip()
                ]
                lines.extend(
                    [
                        f"### TC-{tc_number:03d}: {name}",
                        f"**Description:** {name}",
                        "**Preconditions:** Start from the state established by the source spec and planner seed.",
                        "**Steps:**",
                    ]
                )
                if steps:
                    lines.extend(
                        f"{idx}. {step}" for idx, step in enumerate(steps, start=1)
                    )
                else:
                    lines.append("1. Execute the scenario described by the planner.")
                expected = (
                    " ".join(expected_results)
                    if expected_results
                    else "The planned outcome is visible and stable."
                )
                lines.extend(["**Expected Result:** " + expected, ""])
                tc_number += 1

        if tc_number == 1:
            return None

        draft_script = NativePlanner._extract_draft_script(overview)
        if draft_script and "## Draft Playwright Script" not in "\n".join(lines):
            lines.extend(
                [
                    "## Draft Playwright Script",
                    "```typescript",
                    draft_script,
                    "```",
                    "",
                ]
            )

        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _draft_script_path_for_plan(plan_path: Path) -> Path:
        return plan_path.with_suffix(".draft.spec.ts")

    @staticmethod
    def _extract_draft_script(content: str) -> str | None:
        heading = re.search(
            r"(?im)^#{2,3}\s+Draft\s+(?:Playwright\s+)?(?:Test\s+)?Script\s*$",
            content,
        )
        search_region = content[heading.end() :] if heading else content
        match = re.search(
            r"```(?:typescript|ts)\s*\n(.*?)```",
            search_region,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return None
        return match.group(1).strip()

    @staticmethod
    def _validate_draft_script(script: str) -> tuple[bool, str | None]:
        if not script or not script.strip():
            return False, "empty draft script"
        if "page.waitForTimeout" in script:
            return False, "draft script uses page.waitForTimeout()"
        if "```" in script:
            return False, "draft script contains markdown fences"
        if "test(" not in script and "test.describe" not in script:
            return False, "draft script is missing Playwright test()"
        if "page." not in script:
            return False, "draft script is missing page interactions/assertions"
        if "expect(" not in script:
            return False, "draft script is missing Playwright expect() assertions"
        return True, None

    @classmethod
    def _draft_script_validation_failure(cls, content: str) -> str | None:
        draft_script = cls._extract_draft_script(content)
        if not draft_script:
            return "missing Draft Playwright Script fenced TypeScript block"
        valid, reason = cls._validate_draft_script(draft_script)
        return None if valid else reason

    @staticmethod
    def _is_draft_script_failure(error: SpecGenerationError) -> bool:
        return bool(error.diagnostics.get("planner_draft_script_validation_failure"))

    async def _finalize_or_repair_plan_artifact(
        self,
        *,
        plan_path: Path,
        expected_output_path: Path,
        require_draft_script: bool,
        subject_type: str,
        subject_name: str,
        agent_result: Any,
    ) -> Path:
        try:
            return self._finalize_plan_artifact(
                plan_path=plan_path,
                expected_output_path=expected_output_path,
                require_draft_script=require_draft_script,
            )
        except SpecGenerationError as exc:
            if not (require_draft_script and self._is_draft_script_failure(exc)):
                raise

            draft_failure = str(
                exc.diagnostics.get("planner_draft_script_validation_failure") or exc
            )
            logger.info(
                "Attempting planner repair for draft script handoff failure in %s '%s': %s",
                subject_type,
                subject_name,
                draft_failure,
            )
            repaired_plan_path = await self._attempt_repair_plan(
                subject_type=subject_type,
                subject_name=subject_name,
                agent_result=agent_result,
                expected_output_path=expected_output_path,
                draft_script_validation_failure=draft_failure,
                require_draft_script=require_draft_script,
            )
            if not repaired_plan_path:
                raise
            return self._finalize_plan_artifact(
                plan_path=repaired_plan_path,
                expected_output_path=expected_output_path,
                require_draft_script=require_draft_script,
            )

    def _finalize_plan_artifact(
        self,
        *,
        plan_path: Path,
        expected_output_path: Path,
        require_draft_script: bool,
    ) -> Path:
        try:
            content = plan_path.read_text()
        except OSError as exc:
            raise SpecGenerationError(
                f"Accepted planner artifact could not be read: {plan_path}",
                diagnostics={
                    "expected_output_path": str(expected_output_path),
                    "generated_plan_path": str(plan_path),
                    "planner_draft_script_observed": False,
                    "planner_draft_script_error": str(exc),
                },
            ) from exc
        warnings = self._planner_evidence_warnings(content)
        if warnings:
            logger.warning(
                "Planner evidence warnings for %s: %s", plan_path, "; ".join(warnings)
            )
            if self.session_dir:
                try:
                    warning_path = self.session_dir / "planner_evidence_warnings.json"
                    warning_path.write_text(
                        json.dumps(
                            {"plan_path": str(plan_path), "warnings": warnings},
                            indent=2,
                        )
                    )
                except OSError:
                    logger.debug(
                        "Could not write planner evidence warning artifact",
                        exc_info=True,
                    )

        draft_script = self._extract_draft_script(content)
        if not draft_script:
            if require_draft_script:
                raise SpecGenerationError(
                    "Live-browser planner produced a valid markdown plan but did not include a required Draft Playwright Script section.",
                    diagnostics={
                        "expected_output_path": str(expected_output_path),
                        "generated_plan_path": str(plan_path),
                        "planner_draft_script_observed": False,
                        "planner_draft_script_validation_failure": "missing Draft Playwright Script fenced TypeScript block",
                    },
                )
            self.last_draft_script_path = None
            return plan_path

        valid, reason = self._validate_draft_script(draft_script)
        if not valid:
            if require_draft_script:
                raise SpecGenerationError(
                    f"Live-browser planner produced an invalid Draft Playwright Script: {reason}.",
                    diagnostics={
                        "expected_output_path": str(expected_output_path),
                        "generated_plan_path": str(plan_path),
                        "planner_draft_script_observed": True,
                        "planner_draft_script_validation_failure": reason,
                    },
                )
            logger.warning(
                "Ignoring invalid optional planner draft script in %s: %s",
                plan_path,
                reason,
            )
            self.last_draft_script_path = None
            return plan_path

        draft_path = self._draft_script_path_for_plan(expected_output_path)
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(draft_script.rstrip() + "\n")
        self.last_draft_script_path = draft_path
        logger.info("Planner draft script saved: %s", draft_path)
        return plan_path

    @classmethod
    def _validate_test_plan_schema(cls, content: str) -> tuple[bool, str | None]:
        """Validate the markdown shape required by the PRD splitter/generator."""
        if not content or not content.strip():
            return False, "empty content"
        if not re.search(r"(?m)^#\s+Test Plan:\s+\S", content):
            return False, "missing '# Test Plan: <feature>' header"

        tc_matches = list(re.finditer(r"(?m)^###\s+TC-\d{3}:\s+.+", content))
        if not tc_matches:
            return False, "missing '### TC-XXX: <scenario>' sections"

        required_fields = (
            "**Description:**",
            "**Preconditions:**",
            "**Steps:**",
            "**Expected Result:**",
        )
        for idx, match in enumerate(tc_matches):
            end = (
                tc_matches[idx + 1].start()
                if idx + 1 < len(tc_matches)
                else len(content)
            )
            block = content[match.start() : end]
            missing = [field for field in required_fields if field not in block]
            if missing:
                title = match.group(0).strip()
                return False, f"{title} missing required fields: {', '.join(missing)}"
            steps_start = block.find("**Steps:**")
            expected_start = block.find("**Expected Result:**")
            steps_block = (
                block[steps_start:expected_start]
                if expected_start > steps_start
                else block[steps_start:]
            )
            if not re.search(r"(?m)^\s*\d+\.\s+\S", steps_block):
                title = match.group(0).strip()
                return False, f"{title} missing numbered steps"

        return True, None

    @classmethod
    def _planner_evidence_warnings(cls, content: str) -> list[str]:
        """Warn when UI-oriented TC blocks lack observable evidence fields."""
        warnings: list[str] = []
        tc_matches = list(re.finditer(r"(?m)^###\s+(TC-\d{3}):\s+(.+)", content or ""))
        evidence_terms = (
            "observed url",
            "source:",
            "selector",
            "getbyrole",
            "getbytext",
            "screenshot",
            "confidence",
            "browser_snapshot",
            "live-step-",
        )
        ui_terms = (
            "click",
            "navigate",
            "button",
            "field",
            "form",
            "page",
            "url",
            "screen",
            "visible",
        )
        for idx, match in enumerate(tc_matches):
            end = (
                tc_matches[idx + 1].start()
                if idx + 1 < len(tc_matches)
                else len(content)
            )
            block = content[match.start() : end]
            lower = block.lower()
            if any(term in lower for term in ui_terms) and not any(
                term in lower for term in evidence_terms
            ):
                warnings.append(
                    f"{match.group(1)} has UI steps but no explicit observed URL/selector/screenshot/source confidence evidence."
                )
        return warnings[:20]

    @classmethod
    def _is_valid_test_plan(cls, content: str) -> bool:
        valid, _reason = cls._validate_test_plan_schema(content)
        return valid

    def _recover_saved_plan(self, expected_output_path: Path) -> Path | None:
        """
        Recover a markdown plan saved by the agent.

        The expected output path wins. If it is absent or invalid, search run/session
        directories for a valid markdown plan artifact and copy it to the expected
        specs location so downstream spec registration remains stable.
        """
        candidates: list[Path] = [expected_output_path]
        search_roots = []
        for root in (self.session_dir, self.cwd):
            if root:
                root_path = Path(root)
                if root_path.exists() and root_path not in search_roots:
                    search_roots.append(root_path)

        for root in search_roots:
            try:
                candidates.extend(
                    sorted(
                        root.rglob("*.md"),
                        key=lambda path: path.stat().st_mtime,
                        reverse=True,
                    )
                )
            except OSError:
                logger.debug("Failed to search saved plan artifacts under %s", root)

        seen: set[Path] = set()
        for path in candidates:
            try:
                resolved = path.resolve()
                if resolved in seen or not path.exists() or not path.is_file():
                    continue
                seen.add(resolved)
                content = path.read_text()
            except OSError:
                continue

            valid, reason = self._validate_test_plan_schema(content)
            if not valid:
                logger.warning("Ignoring invalid saved plan %s: %s", path, reason)
                continue

            if path.resolve() != expected_output_path.resolve():
                expected_output_path.parent.mkdir(parents=True, exist_ok=True)
                expected_output_path.write_text(content)
                logger.info(
                    "Recovered saved plan artifact %s to %s", path, expected_output_path
                )
                return expected_output_path
            return path

        return None

    @staticmethod
    def _extract_plan_content(agent_result) -> str | None:
        """
        Extract the test plan content from an agent result.

        Checks three sources in priority order:
        1. planner_save_plan tool call input (most reliable - the actual plan)
        2. Structured content from output (# Test Plan: header)
        3. Full output as last resort
        """
        # 1. Check if planner_save_plan was called and extract its content
        for tc in reversed(list(getattr(agent_result, "tool_calls", []) or [])):
            tool_name = str(getattr(tc, "name", "") or "")
            if "planner_save_plan" in tool_name or "save_plan" in tool_name:
                content = NativePlanner._extract_plan_payload(
                    getattr(tc, "input", None)
                )
                if (
                    content
                    and len(content) > 100
                    and NativePlanner._is_valid_test_plan(content)
                ):
                    logger.info(
                        f"Extracted plan from planner_save_plan tool call ({len(content)} chars)"
                    )
                    return content

        # 2. Try to extract structured content from output (skip narrative preamble)
        output = getattr(agent_result, "output", "") or ""
        if output:
            import re

            # Look for "# Test Plan:" header which marks the actual plan
            plan_match = re.search(r"(# Test Plan:.*)", output, re.DOTALL)
            if plan_match:
                plan_content = plan_match.group(1).strip()
                if len(plan_content) > 200 and NativePlanner._is_valid_test_plan(
                    plan_content
                ):
                    logger.info(
                        f"Extracted plan from '# Test Plan:' header ({len(plan_content)} chars)"
                    )
                    return plan_content

            # Look for TC-XXX patterns indicating structured test cases
            tc_matches = re.findall(
                r"(?:^|\n)(##?\s+(?:TC-\d+|Test Case \d+).*)", output
            )
            if len(tc_matches) >= 2:
                # Output contains structured test cases, find where they start
                first_tc = re.search(r"(##?\s+(?:TC-\d+|Test Case \d+))", output)
                if first_tc:
                    # Find a header before the first TC
                    header_match = re.search(r"(# .+\n)", output[: first_tc.start()])
                    start = header_match.start() if header_match else first_tc.start()
                    plan_content = output[start:].strip()
                    if len(plan_content) > 200 and NativePlanner._is_valid_test_plan(
                        plan_content
                    ):
                        logger.info(
                            f"Extracted plan from TC-XXX patterns ({len(plan_content)} chars)"
                        )
                        return plan_content

        return None

    def _plan_candidate_paths(self, expected_output_path: Path) -> list[Path]:
        candidates: list[Path] = [expected_output_path]
        search_roots = []
        for root in (self.session_dir, self.cwd):
            if root:
                root_path = Path(root)
                if root_path.exists() and root_path not in search_roots:
                    search_roots.append(root_path)

        for root in search_roots:
            try:
                candidates.extend(
                    sorted(
                        root.rglob("*.md"),
                        key=lambda path: path.stat().st_mtime,
                        reverse=True,
                    )
                )
            except OSError:
                logger.debug("Failed to search saved plan artifacts under %s", root)

        seen: set[Path] = set()
        unique: list[Path] = []
        for path in candidates:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            unique.append(path)
        return unique

    def _collect_repair_evidence(
        self,
        agent_result: Any,
        expected_output_path: Path,
        *,
        draft_script_validation_failure: str | None = None,
    ) -> dict[str, Any]:
        rejected_artifacts: list[dict[str, Any]] = []
        artifact_contents: list[tuple[str, str]] = []
        try:
            expected_resolved = expected_output_path.resolve()
        except OSError:
            expected_resolved = expected_output_path
        for path in self._plan_candidate_paths(expected_output_path):
            try:
                if not path.exists() or not path.is_file():
                    continue
                content = path.read_text()
            except OSError:
                continue
            valid, reason = self._validate_test_plan_schema(content)
            if valid:
                try:
                    path_resolved = path.resolve()
                except OSError:
                    path_resolved = path
                if (
                    not draft_script_validation_failure
                    or path_resolved != expected_resolved
                ):
                    continue
                reason = draft_script_validation_failure
            artifact_contents.append((str(path), self._redact_sensitive_text(content)))
            rejected_artifacts.append(
                {
                    "path": str(path),
                    "length": len(content),
                    "content_hash": self._content_hash(content),
                    "preview": self._content_preview(content),
                    "validation_failure_reason": reason,
                }
            )

        rejected_payloads: list[dict[str, Any]] = []
        payload_contents: list[tuple[str, str]] = []
        save_plan_observed = False
        for tc in list(getattr(agent_result, "tool_calls", []) or []):
            tool_name = str(getattr(tc, "name", "") or "")
            if "planner_save_plan" not in tool_name and "save_plan" not in tool_name:
                continue
            save_plan_observed = True
            payload = self._extract_plan_payload(getattr(tc, "input", None))
            if payload:
                valid, reason = self._validate_test_plan_schema(payload)
                if valid and draft_script_validation_failure:
                    reason = draft_script_validation_failure
                if not valid or draft_script_validation_failure:
                    payload_contents.append(
                        (tool_name, self._redact_sensitive_text(payload))
                    )
                    rejected_payloads.append(
                        {
                            "tool_name": tool_name,
                            "length": len(payload),
                            "content_hash": self._content_hash(payload),
                            "preview": self._content_preview(payload),
                            "validation_failure_reason": reason,
                        }
                    )
            else:
                rejected_payloads.append(
                    {
                        "tool_name": tool_name,
                        "length": 0,
                        "content_hash": None,
                        "preview": "",
                        "validation_failure_reason": "planner_save_plan call had no markdown payload",
                    }
                )

        raw_output = str(getattr(agent_result, "output", "") or "")
        raw_output_meta = {
            "length": len(raw_output),
            "content_hash": self._content_hash(raw_output) if raw_output else None,
            "preview": self._content_preview(raw_output) if raw_output else "",
        }

        useful = bool(
            save_plan_observed
            or rejected_artifacts
            or rejected_payloads
            or raw_output.strip()
        )
        return {
            "useful_evidence": useful,
            "save_plan_observed": save_plan_observed,
            "draft_script_validation_failure": draft_script_validation_failure,
            "rejected_artifacts": rejected_artifacts,
            "rejected_save_plan_payloads": rejected_payloads,
            "raw_output": raw_output_meta,
            "_artifact_contents": artifact_contents,
            "_payload_contents": payload_contents,
            "_raw_output_content": self._redact_sensitive_text(raw_output),
        }

    def _write_repair_attempt_artifact(self, attempt: dict[str, Any]) -> Path | None:
        if not self.session_dir:
            return None
        artifact = {
            key: value for key, value in attempt.items() if not key.startswith("_")
        }
        try:
            self.session_dir.mkdir(parents=True, exist_ok=True)
            path = self.session_dir / "planner_repair_attempt.json"
            path.write_text(json.dumps(artifact, indent=2))
            return path
        except Exception as exc:
            logger.warning("Failed to write planner repair attempt artifact: %s", exc)
            return None

    @staticmethod
    def _append_evidence_section(
        parts: list[str], title: str, source: str, content: str, budget: int
    ) -> int:
        if budget <= 0 or not content.strip():
            return budget
        excerpt = content if len(content) <= budget else content[:budget]
        parts.append(
            f"\n## Evidence: {title}\nSource: {source}\n\n```markdown\n{excerpt}\n```"
        )
        return max(0, budget - len(excerpt))

    def _build_repair_prompt(self, subject_name: str, evidence: dict[str, Any]) -> str:
        parts = [
            "You are a bounded PRD planner formatter/repair agent.",
            "Transform only the evidence below into a valid markdown test plan.",
            "Do not browse, inspect files, call tools, or add unsupported business behavior.",
            "If details are thin, keep conservative reachability, navigation, accessibility, responsive, and error-state checks.",
            "",
            "Required output schema:",
            f"# Test Plan: {subject_name}",
            "### TC-XXX: <scenario>",
            "**Description:**",
            "**Preconditions:**",
            "**Steps:** numbered action steps",
            "**Expected Result:**",
            "Optional: **Test Data:**",
            "## Draft Playwright Script",
            "One fenced `typescript` code block with draft Playwright code using web-first assertions and no `page.waitForTimeout()`.",
            "",
            "Return only the markdown plan.",
        ]
        draft_failure = evidence.get("draft_script_validation_failure")
        if draft_failure:
            parts.extend(
                [
                    "",
                    f"Specific repair needed: the prior plan schema was valid, but its Draft Playwright Script failed validation: {draft_failure}.",
                    "Preserve the discovered scenario and selectors from the evidence, and repair only the markdown/script handoff contract.",
                ]
            )
        budget = 60000
        for source, content in evidence.get("_payload_contents", []):
            budget = self._append_evidence_section(
                parts, "Rejected save-plan payload", source, content, budget
            )
        for source, content in evidence.get("_artifact_contents", []):
            budget = self._append_evidence_section(
                parts, "Rejected markdown artifact", source, content, budget
            )
        raw_output = evidence.get("_raw_output_content", "")
        self._append_evidence_section(
            parts, "Raw planner output", "agent final output", raw_output, budget
        )
        return "\n".join(parts)

    async def _query_repair_agent(self, prompt: str):
        timeout = int(os.environ.get("PLANNER_REPAIR_TIMEOUT_SECONDS", "180"))
        runner = AgentRunner(
            timeout_seconds=timeout,
            allowed_tools=[],
            tools=[],
            log_tools=False,
            session_dir=None,
            cwd=self.cwd,
            owner_type=self.owner_type,
            owner_id=self.owner_id,
            owner_label=self.owner_label,
            requires_live_browser=False,
            model_tier=self.model_tier,
            inject_memory=False,
            capture_memory=False,
        )
        return await runner.run(prompt)

    async def _attempt_repair_plan(
        self,
        *,
        subject_type: str,
        subject_name: str,
        agent_result: Any,
        expected_output_path: Path,
        draft_script_validation_failure: str | None = None,
        require_draft_script: bool = False,
    ) -> Path | None:
        evidence = self._collect_repair_evidence(
            agent_result,
            expected_output_path,
            draft_script_validation_failure=draft_script_validation_failure,
        )
        attempt: dict[str, Any] = {
            **evidence,
            "attempted": False,
            "accepted": False,
            "validation_failure_reason": None,
            "expected_output_path": str(expected_output_path),
        }
        self._write_repair_attempt_artifact(attempt)
        if not evidence["useful_evidence"]:
            return None

        attempt["attempted"] = True
        logger.info("Attempting planner repair for %s '%s'", subject_type, subject_name)
        prompt = self._build_repair_prompt(subject_name, evidence)
        repair_result = await self._query_repair_agent(prompt)
        repaired_content = self._extract_plan_content(repair_result)
        if repaired_content:
            repaired_draft_failure = (
                self._draft_script_validation_failure(repaired_content)
                if require_draft_script
                else None
            )
            if repaired_draft_failure:
                attempt["validation_failure_reason"] = repaired_draft_failure
                attempt["repaired_output"] = {
                    "length": len(repaired_content),
                    "content_hash": self._content_hash(repaired_content),
                    "preview": self._content_preview(repaired_content),
                }
                artifact_path = self._write_repair_attempt_artifact(attempt)
                diagnostics = self._agent_diagnostics(
                    agent_result, expected_output_path
                )
                diagnostics.update(
                    {
                        "planner_repair_attempted": True,
                        "planner_repair_accepted": False,
                        "planner_repair_validation_failure": repaired_draft_failure,
                        "planner_repair_artifact_path": (
                            str(artifact_path) if artifact_path else None
                        ),
                        "rejected_artifact_count": len(evidence["rejected_artifacts"]),
                        "rejected_save_plan_payload_count": len(
                            evidence["rejected_save_plan_payloads"]
                        ),
                        "raw_output_length": evidence["raw_output"]["length"],
                        "planner_draft_script_validation_failure": repaired_draft_failure,
                    }
                )
                raise SpecGenerationError(
                    (
                        f"Failed to generate spec for {subject_type} '{subject_name}': planner repair produced "
                        f"a markdown plan, but the required Draft Playwright Script is still invalid. "
                        f"Validation failure: {repaired_draft_failure}."
                    ),
                    diagnostics=diagnostics,
                )
            expected_output_path.parent.mkdir(parents=True, exist_ok=True)
            expected_output_path.write_text(repaired_content)
            attempt["accepted"] = True
            attempt["repaired_output"] = {
                "length": len(repaired_content),
                "content_hash": self._content_hash(repaired_content),
                "preview": self._content_preview(repaired_content),
            }
            self._write_repair_attempt_artifact(attempt)
            logger.info(
                "Accepted repaired planner output for %s '%s'",
                subject_type,
                subject_name,
            )
            return expected_output_path

        output = str(getattr(repair_result, "output", "") or "")
        if output.strip():
            candidate_match = re.search(r"(# Test Plan:.*)", output, re.DOTALL)
            candidate = (
                candidate_match.group(1).strip() if candidate_match else output.strip()
            )
            _valid, reason = self._validate_test_plan_schema(candidate)
            attempt["validation_failure_reason"] = (
                reason or "repair output did not contain a valid test plan"
            )
            attempt["repaired_output"] = {
                "length": len(candidate),
                "content_hash": self._content_hash(candidate),
                "preview": self._content_preview(candidate),
            }
        else:
            attempt["validation_failure_reason"] = str(
                getattr(repair_result, "error", None) or "repair produced no output"
            )
            attempt["repaired_output"] = {
                "length": 0,
                "content_hash": None,
                "preview": "",
            }
        artifact_path = self._write_repair_attempt_artifact(attempt)
        diagnostics = self._agent_diagnostics(agent_result, expected_output_path)
        diagnostics.update(
            {
                "planner_repair_attempted": True,
                "planner_repair_accepted": False,
                "planner_repair_validation_failure": attempt[
                    "validation_failure_reason"
                ],
                "planner_repair_artifact_path": (
                    str(artifact_path) if artifact_path else None
                ),
                "rejected_artifact_count": len(evidence["rejected_artifacts"]),
                "rejected_save_plan_payload_count": len(
                    evidence["rejected_save_plan_payloads"]
                ),
                "raw_output_length": evidence["raw_output"]["length"],
            }
        )
        raise SpecGenerationError(
            (
                f"Failed to generate spec for {subject_type} '{subject_name}': planner evidence was present, "
                f"but repair did not produce a valid test plan. "
                f"Validation failure: {attempt['validation_failure_reason']}."
            ),
            diagnostics=diagnostics,
        )

    @staticmethod
    def _agent_diagnostics(agent_result, expected_output_path: Path) -> dict[str, Any]:
        tool_calls = list(getattr(agent_result, "tool_calls", []) or [])
        agent_error = getattr(agent_result, "error", None)
        timed_out = bool(getattr(agent_result, "timed_out", False))
        planner_save_plan_observed = any(
            "planner_save_plan" in getattr(tc, "name", "")
            or "save_plan" in getattr(tc, "name", "")
            for tc in tool_calls
        )

        diagnostics = {
            "agent_success": bool(getattr(agent_result, "success", False)),
            "timed_out": timed_out,
            "agent_error": agent_error,
            "messages_received": int(
                getattr(agent_result, "messages_received", 0) or 0
            ),
            "text_blocks_received": int(
                getattr(agent_result, "text_blocks_received", 0) or 0
            ),
            "tool_calls": len(tool_calls),
            "planner_save_plan_observed": planner_save_plan_observed,
            "valid_saved_plan_observed": False,
            "expected_output_path": str(expected_output_path),
        }

        if timed_out:
            diagnostics["next_action"] = (
                "Retry with a longer planner timeout or reduce the feature scope."
            )
        elif agent_error:
            diagnostics["next_action"] = (
                "Check agent worker logs and SDK/queue runtime errors."
            )
        elif not tool_calls:
            diagnostics["next_action"] = (
                "Verify the MCP/browser runtime and planner tool allowlist."
            )
        elif not planner_save_plan_observed:
            diagnostics["next_action"] = (
                "Check whether the planner reached the save-plan step."
            )
        else:
            diagnostics["next_action"] = (
                "Retry generation and inspect raw_output.txt and tool_calls.json."
            )

        return diagnostics

    @classmethod
    def _build_no_output_error(
        cls,
        *,
        subject_type: str,
        subject_name: str,
        agent_result,
        expected_output_path: Path,
    ) -> SpecGenerationError:
        diagnostics = cls._agent_diagnostics(agent_result, expected_output_path)
        output = getattr(agent_result, "output", "") or ""
        if diagnostics["timed_out"]:
            reason = "planner timed out before producing a valid test plan"
        elif diagnostics["agent_error"]:
            reason = f"planner failed: {diagnostics['agent_error']}"
        elif output.strip():
            reason = "planner returned text, but no valid test-case structure was found"
        else:
            reason = "agent produced no output"

        message = (
            f"Failed to generate spec for {subject_type} '{subject_name}': {reason}. "
            "No valid saved plan artifact was found.\n"
            f"Diagnostics: success={diagnostics['agent_success']}, timed_out={diagnostics['timed_out']}, "
            f"messages={diagnostics['messages_received']}, text_blocks={diagnostics['text_blocks_received']}, "
            f"tool_calls={diagnostics['tool_calls']}, "
            f"planner_save_plan_observed={diagnostics['planner_save_plan_observed']}, "
            f"valid_saved_plan_observed={diagnostics['valid_saved_plan_observed']}, "
            f"expected_output_path={diagnostics['expected_output_path']}.\n"
            f"Next action: {diagnostics['next_action']}"
        )
        return SpecGenerationError(message, diagnostics=diagnostics)

    def _build_context_text(self, chunks: list[dict]) -> str:
        """Combine RAG chunks into a single context string."""
        if not chunks:
            return ""

        text = []
        per_chunk_budget = context_budget_for_stage("planner_prd_chunk", 900)
        for _i, chunk in enumerate(chunks):
            content = chunk.get("content", "")
            # Sanitize: remove null bytes and control characters
            content = content.replace("\x00", " ")
            content = "".join(
                c if c.isprintable() or c in "\n\r\t" else " " for c in content
            )
            content = truncate_text_to_tokens(content, per_chunk_budget)

            meta = chunk.get("metadata", {})
            source = meta.get("feature", "PRD")

            text.append(f"### Source: {source}\n{content}\n")

        return "\n---\n".join(text)

    async def generate_spec_from_flow_context(
        self,
        flow_title: str,
        flow_context: str,
        target_url: str,
        login_url: str | None = None,
        credentials: dict[str, str] | None = None,
        auth_context: dict[str, Any] | None = None,
        output_dir: Path | None = None,
    ) -> Path:
        """
        Generate a test spec for a flow using provided context.

        Unlike generate_spec_for_feature() which retrieves context from ChromaDB,
        this method accepts the context directly. Used for exploration flows
        where context comes from flow discovery, not PRD documents.

        Args:
            flow_title: Name of the flow (e.g. "User Authentication Flow")
            flow_context: Pre-built context string with flow details
            target_url: URL to explore
            login_url: Login page URL if auth required
            credentials: Dict with username/password if auth required
            auth_context: Saved browser authentication context if the browser starts authenticated
            output_dir: Where to save the spec (defaults to specs/explorer-{timestamp})

        Returns:
            Path to the generated spec file
        """
        from datetime import datetime

        target_url = self._normalize_url_for_prompt(target_url) or target_url
        login_url = self._normalize_url_for_prompt(login_url)
        feature_slug = slugify(flow_title)

        # Use provided output_dir or default
        if output_dir is None:
            output_dir = (
                self.specs_dir / f"explorer-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            )

        # Ensure output_dir is a Path object
        if isinstance(output_dir, str):
            output_dir = Path(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{feature_slug}.md"

        logger.info(f"Using provided flow context for: {flow_title}")

        # Build the hybrid prompt with provided context (not from ChromaDB)
        prompt = self._build_hybrid_prompt(
            feature_name=flow_title,
            feature_slug=feature_slug,
            prd_context=flow_context,  # Flow context instead of PRD context
            target_url=target_url,
            login_url=login_url,
            credentials=credentials,
            auth_context=auth_context,
            output_path=str(output_path),
        )

        # Invoke the Playwright Planner Agent via SDK
        logger.info(f"Invoking Playwright Planner Agent for flow: {flow_title}")
        logger.info(f"   Target URL: {target_url}")

        return await self._run_planner_with_retry(
            subject_type="flow",
            subject_name=flow_title,
            prompt=prompt,
            target_url=target_url,
            expected_output_path=output_path,
        )

    async def generate_all_specs(
        self, prd_project: str, target_url: str | None = None
    ) -> list[Path]:
        """
        Generate specs for all features in the PRD.

        Args:
            prd_project: Project ID (folder name in prds/)
            target_url: Base URL of the application (optional)

        Returns:
            List of paths to generated spec files
        """
        metadata_path = Path("prds") / prd_project / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"PRD metadata not found for {prd_project}")

        data = json.loads(metadata_path.read_text())
        features = data.get("features", [])

        results = []
        for feature in features:
            # Handle both dict and string formats
            if isinstance(feature, dict):
                feature_name = feature.get("name", "Unknown")
            else:
                feature_name = str(feature)

            # Skip context-only features
            if feature_name in ["Full Document Context", "General PRD Context"]:
                continue

            logger.info("=" * 60)
            logger.info(f"Feature: {feature_name}")
            logger.info("=" * 60)

            path = await self.generate_spec_for_feature(
                feature_name=feature_name,
                prd_project=prd_project,
                target_url=target_url,
            )
            results.append(path)

        return results


if __name__ == "__main__":
    from orchestrator.logging_config import setup_logging

    setup_logging()

    import argparse

    parser = argparse.ArgumentParser(
        description="Generate test specs from PRD using Playwright Planner"
    )
    parser.add_argument("--project", required=True, help="PRD Project Name")
    parser.add_argument("--feature", help="Specific feature to generate (optional)")
    parser.add_argument("--url", help="Target URL for browser exploration (optional)")
    args = parser.parse_args()

    async def main():
        planner = NativePlanner(project_id=args.project)
        if args.feature:
            await planner.generate_spec_for_feature(
                args.feature, args.project, target_url=args.url
            )
        else:
            await planner.generate_all_specs(args.project, target_url=args.url)

    try:
        asyncio.run(main())
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass  # Ignore SDK cleanup error
        else:
            raise
