"""
Native Planner Workflow - Hybrid Mode: PRD Context + Browser Exploration

This workflow uses the Playwright Test Planner agent with:
1. PRD context from RAG (ChromaDB)
2. Live browser exploration via MCP tools
3. SDK-based agent invocation
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

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

from orchestrator.memory import get_memory_manager
from orchestrator.utils.agent_runner import AgentRunner, build_allowed_tools, get_default_timeout
from orchestrator.utils.string_utils import slugify


class SpecGenerationError(Exception):
    """Raised when spec generation fails to produce valid output."""

    pass


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

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
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

        agent_result = await self._query_planner_agent(prompt)

        # 4. Check if spec was saved by the agent directly to disk
        if output_path.exists():
            # Verify it's not just a narrative summary
            existing = output_path.read_text()
            if "TC-" in existing or "Test Case" in existing or "## Steps" in existing:
                logger.info(f"Spec saved by agent: {output_path}")
                return output_path

        # 5. Extract the actual plan content from agent tool calls or output
        plan_content = self._extract_plan_content(agent_result)
        if plan_content:
            logger.info(f"Saving extracted plan as spec: {output_path}")
            output_path.write_text(plan_content)
            return output_path

        # 6. Last resort: save full output
        if agent_result.output:
            logger.info(f"Saving agent response as spec (no structured plan found): {output_path}")
            output_path.write_text(agent_result.output)
            return output_path

        # Raise error instead of creating placeholder - callers should handle this
        logger.error(f"Agent produced no output for feature: {feature_name}")
        raise SpecGenerationError(f"Failed to generate spec for feature '{feature_name}': Agent produced no output")

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
"""

            browser_section = f"""
## Browser Exploration (REQUIRED)
You MUST open a browser and explore the live application.

{login_section}

## Step {"2" if credentials else "1"}: Navigate and Explore the Feature
- **Target URL**: {target_url}

Use the Playwright MCP tools to:
1. Call `planner_setup_page` to initialize the browser
2. **IMMEDIATELY** call `browser_navigate` to go to: {target_url}
   (Do NOT rely on any default page - the default is example.com. Navigate explicitly!)
3. Use `browser_snapshot` to see the current page state
4. Explore the interface related to "{feature_name}"
5. Identify all interactive elements, buttons, forms, and user flows
6. Record the EXACT selectors you find (getByRole, getByText, etc.)
7. Take additional snapshots as you navigate

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
"""

        prompt = f"""You are the Playwright Test Planner agent.

# Task: Generate Test Plan for "{feature_name}"

{browser_section}

## PRD Requirements Context
The following requirements were extracted from the Product Requirements Document:

{prd_context}

## Output Requirements
Create a comprehensive test plan that covers:

1. **Happy Path Tests** - Normal user flows that should work
2. **Edge Cases** - Boundary conditions and unusual inputs
3. **Error Scenarios** - What happens when things go wrong
4. **Accessibility** - Basic accessibility checks if applicable

## Test Plan Format
Each test case should include:
- **Test ID**: TC-XXX format
- **Description**: What is being tested
- **Preconditions**: Required state before test (including login)
- **Steps**: Numbered action steps with ACTUAL SELECTORS if discovered
- **Expected Result**: What should happen

## Save the Plan
After creating the test plan:
1. Save it using `planner_save_plan` tool to: **{output_path}**
2. ALSO output the COMPLETE test plan as text in your response (not just a summary)
3. Call `browser_close` to close the browser before finishing

**CRITICAL**: Your final text response MUST contain the full test plan with all TC-XXX test cases, steps, and expected results. Do NOT output just a summary like "I created 24 test cases" - output the actual test cases themselves.

Start the test plan with:
# Test Plan: {feature_name}
"""
        return prompt

    # Playwright MCP tools matching .claude/agents/playwright-test-planner.md
    PLANNER_MCP_TOOLS = [
        "browser_click",
        "browser_close",
        "browser_console_messages",
        "browser_drag",
        "browser_evaluate",
        "browser_file_upload",
        "browser_handle_dialog",
        "browser_hover",
        "browser_navigate",
        "browser_navigate_back",
        "browser_network_requests",
        "browser_press_key",
        "browser_select_option",
        "browser_snapshot",
        "browser_take_screenshot",
        "browser_type",
        "browser_wait_for",
        "planner_setup_page",
        "planner_save_plan",
    ]

    async def _query_planner_agent(self, prompt: str):
        """
        Query the Playwright Planner agent using the unified AgentRunner.

        Uses explicit timeout and comprehensive logging.
        Returns the full AgentResult (with tool_calls for plan extraction).
        """
        timeout = int(os.environ.get("PLANNER_TIMEOUT_SECONDS", get_default_timeout()))

        logger.info(f"Timeout: {timeout}s ({timeout // 60} minutes)")

        runner = AgentRunner(
            timeout_seconds=timeout,
            allowed_tools=build_allowed_tools(
                ["Glob", "Grep", "Read", "LS"],
                self.PLANNER_MCP_TOOLS,
            ),
            log_tools=True,
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
    def _extract_plan_content(agent_result) -> str | None:
        """
        Extract the test plan content from an agent result.

        Checks three sources in priority order:
        1. planner_save_plan tool call input (most reliable - the actual plan)
        2. Structured content from output (# Test Plan: header)
        3. Full output as last resort
        """
        # 1. Check if planner_save_plan was called and extract its content
        for tc in reversed(agent_result.tool_calls):
            if "planner_save_plan" in tc.name or "save_plan" in tc.name:
                if tc.input and isinstance(tc.input, dict):
                    # The tool takes content/plan as an argument
                    content = tc.input.get("content") or tc.input.get("plan") or tc.input.get("markdown")
                    if content and len(content) > 100:
                        logger.info(f"Extracted plan from planner_save_plan tool call ({len(content)} chars)")
                        return content

        # 2. Try to extract structured content from output (skip narrative preamble)
        output = agent_result.output or ""
        if output:
            import re

            # Look for "# Test Plan:" header which marks the actual plan
            plan_match = re.search(r"(# Test Plan:.*)", output, re.DOTALL)
            if plan_match:
                plan_content = plan_match.group(1).strip()
                if len(plan_content) > 200:
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
                    if len(plan_content) > 200:
                        logger.info(f"Extracted plan from TC-XXX patterns ({len(plan_content)} chars)")
                        return plan_content

        return None

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

        agent_result = await self._query_planner_agent(prompt)

        # Check if spec was saved by the agent directly to disk
        if output_path.exists():
            # Verify it's not just a narrative summary
            existing = output_path.read_text()
            if "TC-" in existing or "Test Case" in existing or "## Steps" in existing:
                logger.info(f"Spec saved by agent: {output_path}")
                return output_path

        # Extract the actual plan content from agent tool calls or output
        plan_content = self._extract_plan_content(agent_result)
        if plan_content:
            logger.info(f"Saving extracted plan as spec: {output_path}")
            output_path.write_text(plan_content)
            return output_path

        # Last resort: save full output
        if agent_result.output:
            logger.info(f"Saving agent response as spec (no structured plan found): {output_path}")
            output_path.write_text(agent_result.output)
            return output_path

        # Raise error instead of creating placeholder - callers should handle this
        logger.error(f"Agent produced no output for flow: {flow_title}")
        raise SpecGenerationError(f"Failed to generate spec for flow '{flow_title}': Agent produced no output")

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
