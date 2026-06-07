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

from orchestrator.ai.prompt_registry import attach_prompt_metadata, build_prompt_metadata
from orchestrator.memory import get_memory_manager
from orchestrator.utils.agent_runner import AgentRunner, get_default_timeout
from orchestrator.utils.agent_tool_allowlists import get_agent_allowed_tools
from orchestrator.utils.string_utils import slugify


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
            prd_context = "No specific PRD context available. Generate based on feature name."
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

        agent_result = await self._query_planner_agent(prompt, target_url=target_url)
        if target_url:
            self._validate_live_plan_tool_sequence(agent_result, target_url)

        # 4. Check if spec was saved by the agent directly to disk or as a run artifact.
        saved_plan_path = self._recover_saved_plan(output_path)
        if saved_plan_path:
            logger.info(f"Spec saved by agent: {saved_plan_path}")
            return saved_plan_path

        # 5. Extract the actual plan content from agent tool calls or output
        plan_content = self._extract_plan_content(agent_result)
        if plan_content:
            logger.info(f"Saving extracted plan as spec: {output_path}")
            output_path.write_text(plan_content)
            return output_path

        repaired_plan_path = await self._attempt_repair_plan(
            subject_type="feature",
            subject_name=feature_name,
            agent_result=agent_result,
            expected_output_path=output_path,
        )
        if repaired_plan_path:
            return repaired_plan_path

        logger.error(f"Agent produced no usable output for feature: {feature_name}")
        raise self._build_no_output_error(
            subject_type="feature",
            subject_name=feature_name,
            agent_result=agent_result,
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
    ) -> str:
        """Build the prompt that combines PRD context with browser exploration instructions."""

        split_tc_section = self._split_tc_scope_section(
            feature_name=feature_name,
            feature_slug=feature_slug,
            prd_context=prd_context,
            output_path=output_path,
        )

        browser_section = ""
        if target_url:
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
- Use `browser_handle_dialog` with `accept: true` IMMEDIATELY when any dialog appears
- After handling a dialog, take a `browser_snapshot` to verify page state
- Document any dialogs encountered (they indicate user flows that need testing)
"""
        else:
            browser_section = """
## Note: No Target URL Provided
Generate the test plan based on the PRD requirements below.
The test steps should be generalized and will need selector updates during code generation.
Do not use browser tools or repository inspection tools for this PRD-only plan.
"""

        if target_url:
            save_section = f"""
## Save the Plan
After creating the test plan:
1. Save it using `planner_save_plan` tool to: **{output_path}**
2. ALSO output the COMPLETE test plan as text in your response (not just a summary)
3. Call `browser_close` to close the browser before finishing
"""
        else:
            save_section = f"""
## Return the Plan
Return the COMPLETE test plan as markdown in your final response.
The system will write your final markdown to: **{output_path}**
Do not call `planner_save_plan` or `browser_close`.
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
""".format(feature_name=feature_name)
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

        runner = AgentRunner(
            timeout_seconds=timeout,
            allowed_tools=get_agent_allowed_tools(profile_name, mcp_config_dir=self.cwd),
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

        return result

    @staticmethod
    def _normalize_url_for_prompt(target_url: str | None) -> str | None:
        if not target_url:
            return None
        stripped = target_url.strip()
        return stripped or None

    @staticmethod
    def _canonical_url(value: str | None) -> str | None:
        if not value:
            return None
        value = value.strip()
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
    def _validate_live_plan_tool_sequence(cls, agent_result: Any, target_url: str) -> None:
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
        return None

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
            end = tc_matches[idx + 1].start() if idx + 1 < len(tc_matches) else len(content)
            block = content[match.start() : end]
            missing = [field for field in required_fields if field not in block]
            if missing:
                title = match.group(0).strip()
                return False, f"{title} missing required fields: {', '.join(missing)}"
            steps_start = block.find("**Steps:**")
            expected_start = block.find("**Expected Result:**")
            steps_block = block[steps_start:expected_start] if expected_start > steps_start else block[steps_start:]
            if not re.search(r"(?m)^\s*\d+\.\s+\S", steps_block):
                title = match.group(0).strip()
                return False, f"{title} missing numbered steps"

        return True, None

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
                candidates.extend(sorted(root.rglob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True))
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
                logger.info("Recovered saved plan artifact %s to %s", path, expected_output_path)
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
                content = NativePlanner._extract_plan_payload(getattr(tc, "input", None))
                if content and len(content) > 100 and NativePlanner._is_valid_test_plan(content):
                    logger.info(f"Extracted plan from planner_save_plan tool call ({len(content)} chars)")
                    return content

        # 2. Try to extract structured content from output (skip narrative preamble)
        output = getattr(agent_result, "output", "") or ""
        if output:
            import re

            # Look for "# Test Plan:" header which marks the actual plan
            plan_match = re.search(r"(# Test Plan:.*)", output, re.DOTALL)
            if plan_match:
                plan_content = plan_match.group(1).strip()
                if len(plan_content) > 200 and NativePlanner._is_valid_test_plan(plan_content):
                    logger.info(f"Extracted plan from '# Test Plan:' header ({len(plan_content)} chars)")
                    return plan_content

            # Look for TC-XXX patterns indicating structured test cases
            tc_matches = re.findall(r"(?:^|\n)(##?\s+(?:TC-\d+|Test Case \d+).*)", output)
            if len(tc_matches) >= 2:
                # Output contains structured test cases, find where they start
                first_tc = re.search(r"(##?\s+(?:TC-\d+|Test Case \d+))", output)
                if first_tc:
                    # Find a header before the first TC
                    header_match = re.search(r"(# .+\n)", output[: first_tc.start()])
                    start = header_match.start() if header_match else first_tc.start()
                    plan_content = output[start:].strip()
                    if len(plan_content) > 200 and NativePlanner._is_valid_test_plan(plan_content):
                        logger.info(f"Extracted plan from TC-XXX patterns ({len(plan_content)} chars)")
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
                candidates.extend(sorted(root.rglob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True))
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

    def _collect_repair_evidence(self, agent_result: Any, expected_output_path: Path) -> dict[str, Any]:
        rejected_artifacts: list[dict[str, Any]] = []
        artifact_contents: list[tuple[str, str]] = []
        for path in self._plan_candidate_paths(expected_output_path):
            try:
                if not path.exists() or not path.is_file():
                    continue
                content = path.read_text()
            except OSError:
                continue
            valid, reason = self._validate_test_plan_schema(content)
            if valid:
                continue
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
                if not valid:
                    payload_contents.append((tool_name, self._redact_sensitive_text(payload)))
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

        useful = bool(save_plan_observed or rejected_artifacts or rejected_payloads or raw_output.strip())
        return {
            "useful_evidence": useful,
            "save_plan_observed": save_plan_observed,
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
            key: value
            for key, value in attempt.items()
            if not key.startswith("_")
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
    def _append_evidence_section(parts: list[str], title: str, source: str, content: str, budget: int) -> int:
        if budget <= 0 or not content.strip():
            return budget
        excerpt = content if len(content) <= budget else content[:budget]
        parts.append(f"\n## Evidence: {title}\nSource: {source}\n\n```markdown\n{excerpt}\n```")
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
            "",
            "Return only the markdown plan.",
        ]
        budget = 60000
        for source, content in evidence.get("_payload_contents", []):
            budget = self._append_evidence_section(parts, "Rejected save-plan payload", source, content, budget)
        for source, content in evidence.get("_artifact_contents", []):
            budget = self._append_evidence_section(parts, "Rejected markdown artifact", source, content, budget)
        raw_output = evidence.get("_raw_output_content", "")
        self._append_evidence_section(parts, "Raw planner output", "agent final output", raw_output, budget)
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
    ) -> Path | None:
        evidence = self._collect_repair_evidence(agent_result, expected_output_path)
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
            expected_output_path.parent.mkdir(parents=True, exist_ok=True)
            expected_output_path.write_text(repaired_content)
            attempt["accepted"] = True
            attempt["repaired_output"] = {
                "length": len(repaired_content),
                "content_hash": self._content_hash(repaired_content),
                "preview": self._content_preview(repaired_content),
            }
            self._write_repair_attempt_artifact(attempt)
            logger.info("Accepted repaired planner output for %s '%s'", subject_type, subject_name)
            return expected_output_path

        output = str(getattr(repair_result, "output", "") or "")
        if output.strip():
            candidate_match = re.search(r"(# Test Plan:.*)", output, re.DOTALL)
            candidate = candidate_match.group(1).strip() if candidate_match else output.strip()
            _valid, reason = self._validate_test_plan_schema(candidate)
            attempt["validation_failure_reason"] = reason or "repair output did not contain a valid test plan"
            attempt["repaired_output"] = {
                "length": len(candidate),
                "content_hash": self._content_hash(candidate),
                "preview": self._content_preview(candidate),
            }
        else:
            attempt["validation_failure_reason"] = str(getattr(repair_result, "error", None) or "repair produced no output")
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
                "planner_repair_validation_failure": attempt["validation_failure_reason"],
                "planner_repair_artifact_path": str(artifact_path) if artifact_path else None,
                "rejected_artifact_count": len(evidence["rejected_artifacts"]),
                "rejected_save_plan_payload_count": len(evidence["rejected_save_plan_payloads"]),
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
            "planner_save_plan" in getattr(tc, "name", "") or "save_plan" in getattr(tc, "name", "")
            for tc in tool_calls
        )

        diagnostics = {
            "agent_success": bool(getattr(agent_result, "success", False)),
            "timed_out": timed_out,
            "agent_error": agent_error,
            "messages_received": int(getattr(agent_result, "messages_received", 0) or 0),
            "text_blocks_received": int(getattr(agent_result, "text_blocks_received", 0) or 0),
            "tool_calls": len(tool_calls),
            "planner_save_plan_observed": planner_save_plan_observed,
            "valid_saved_plan_observed": False,
            "expected_output_path": str(expected_output_path),
        }

        if timed_out:
            diagnostics["next_action"] = "Retry with a longer planner timeout or reduce the feature scope."
        elif agent_error:
            diagnostics["next_action"] = "Check agent worker logs and SDK/queue runtime errors."
        elif not tool_calls:
            diagnostics["next_action"] = "Verify the MCP/browser runtime and planner tool allowlist."
        elif not planner_save_plan_observed:
            diagnostics["next_action"] = "Check whether the planner reached the save-plan step."
        else:
            diagnostics["next_action"] = "Retry generation and inspect raw_output.txt and tool_calls.json."

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
        for _i, chunk in enumerate(chunks):
            content = chunk.get("content", "")
            # Sanitize: remove null bytes and control characters
            content = content.replace("\x00", " ")
            content = "".join(c if c.isprintable() or c in "\n\r\t" else " " for c in content)

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
            output_dir: Where to save the spec (defaults to specs/explorer-{timestamp})

        Returns:
            Path to the generated spec file
        """
        from datetime import datetime

        feature_slug = slugify(flow_title)

        # Use provided output_dir or default
        if output_dir is None:
            output_dir = self.specs_dir / f"explorer-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

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
            output_path=str(output_path),
        )

        # Invoke the Playwright Planner Agent via SDK
        logger.info(f"Invoking Playwright Planner Agent for flow: {flow_title}")
        logger.info(f"   Target URL: {target_url}")

        agent_result = await self._query_planner_agent(prompt, target_url=target_url)
        if target_url:
            self._validate_live_plan_tool_sequence(agent_result, target_url)

        # Check if spec was saved by the agent directly to disk or as a run artifact.
        saved_plan_path = self._recover_saved_plan(output_path)
        if saved_plan_path:
            logger.info(f"Spec saved by agent: {saved_plan_path}")
            return saved_plan_path

        # Extract the actual plan content from agent tool calls or output
        plan_content = self._extract_plan_content(agent_result)
        if plan_content:
            logger.info(f"Saving extracted plan as spec: {output_path}")
            output_path.write_text(plan_content)
            return output_path

        repaired_plan_path = await self._attempt_repair_plan(
            subject_type="flow",
            subject_name=flow_title,
            agent_result=agent_result,
            expected_output_path=output_path,
        )
        if repaired_plan_path:
            return repaired_plan_path

        logger.error(f"Agent produced no usable output for flow: {flow_title}")
        raise self._build_no_output_error(
            subject_type="flow",
            subject_name=flow_title,
            agent_result=agent_result,
            expected_output_path=output_path,
        )

    async def generate_all_specs(self, prd_project: str, target_url: str | None = None) -> list[Path]:
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
                feature_name=feature_name, prd_project=prd_project, target_url=target_url
            )
            results.append(path)

        return results


if __name__ == "__main__":
    from orchestrator.logging_config import setup_logging

    setup_logging()

    import argparse

    parser = argparse.ArgumentParser(description="Generate test specs from PRD using Playwright Planner")
    parser.add_argument("--project", required=True, help="PRD Project Name")
    parser.add_argument("--feature", help="Specific feature to generate (optional)")
    parser.add_argument("--url", help="Target URL for browser exploration (optional)")
    args = parser.parse_args()

    async def main():
        planner = NativePlanner(project_id=args.project)
        if args.feature:
            await planner.generate_spec_for_feature(args.feature, args.project, target_url=args.url)
        else:
            await planner.generate_all_specs(args.project, target_url=args.url)

    try:
        asyncio.run(main())
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass  # Ignore SDK cleanup error
        else:
            raise
