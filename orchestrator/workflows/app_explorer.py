"""
App Explorer Workflow - AI-Powered Application Discovery

This workflow uses an AI agent with Playwright MCP tools to autonomously
explore a web application, discovering:
- Pages and their structure
- User flows (multi-step interactions)
- API endpoints
- Form behaviors
- Error states

The exploration data is stored in the database and can be used for:
- Requirements generation
- RTM (Requirements Traceability Matrix) creation
- Test coverage analysis
"""

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Use run-specific config directory if set (for parallel execution isolation)
# This also helps avoid root context issues in Docker when spawning Claude CLI
config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
if config_dir:
    os.makedirs(config_dir, exist_ok=True)
    os.chdir(config_dir)

# Load Claude credentials and SDK
from load_env import setup_claude_env

setup_claude_env()

import logging

from utils.agent_runner import AgentRunner, build_allowed_tools, get_default_timeout
from utils.json_utils import extract_json_from_markdown

logger = logging.getLogger(__name__)


@dataclass
class ExplorationConfig:
    """Configuration for app exploration."""

    entry_url: str
    max_interactions: int = 50  # Maximum interactions before stopping
    max_depth: int = 10  # Maximum navigation depth from entry
    strategy: str = "goal_directed"  # goal_directed, breadth_first, depth_first
    timeout_minutes: int = 30  # Maximum exploration time
    credentials: dict[str, str] | None = None  # Login credentials if needed
    login_url: str | None = None  # Login page URL
    exclude_patterns: list[str] = field(default_factory=list)  # URL patterns to skip
    focus_areas: list[str] = field(default_factory=list)  # Areas to prioritize
    additional_instructions: str | None = None  # Custom instructions for AI


@dataclass
class TransitionRecord:
    """Record of a single state transition during exploration."""

    sequence: int
    action_type: str
    action_element: dict[str, Any]
    action_value: str | None
    before_url: str
    before_page_type: str | None
    before_elements: list[str]
    after_url: str
    after_page_type: str | None
    after_elements: list[str]
    transition_type: str  # navigation, modal_open, modal_close, inline_update, error, no_change
    api_calls: list[dict[str, Any]]
    changes_description: str | None = None


@dataclass
class FlowRecord:
    """Record of a discovered user flow."""

    name: str
    category: str  # authentication, crud, navigation, form_submission, search
    steps: list[dict[str, Any]]
    start_url: str
    end_url: str
    outcome: str
    is_success_path: bool = True
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)


@dataclass
class IssueRecord:
    """Record of a discovered issue during exploration."""

    issue_type: str  # broken_link, error_page, accessibility, performance, usability, security, missing_content
    severity: str  # critical, high, medium, low
    url: str
    description: str
    element: str | None = None
    evidence: str | None = None


@dataclass
class ExplorationResult:
    """Result of an exploration session."""

    session_id: str
    entry_url: str
    status: str  # completed, failed, timeout, stopped
    transitions: list[TransitionRecord] = field(default_factory=list)
    flows: list[FlowRecord] = field(default_factory=list)
    api_endpoints: list[dict[str, Any]] = field(default_factory=list)
    issues: list[IssueRecord] = field(default_factory=list)
    pages_discovered: int = 0
    elements_discovered: int = 0
    error_message: str | None = None
    duration_seconds: int = 0


class AppExplorer:
    """
    AI-Powered Application Explorer.

    Uses a Claude agent with Playwright MCP tools to autonomously
    explore web applications and discover their structure and behavior.
    """

    def __init__(self, project_id: str = "default", on_task_enqueued=None):
        self.project_id = project_id
        self.on_task_enqueued = on_task_enqueued
        self.output_dir = self._ensure_output_dir()

    def _ensure_output_dir(self) -> Path:
        """Ensure output directory exists with fallback paths.

        Tries multiple candidate paths to handle both local development
        and Docker container environments.
        """
        # Calculate project root from this file's location
        project_root = Path(__file__).resolve().parent.parent.parent

        candidates = [
            project_root / "runs" / "explorations",  # Primary: project-relative path
            Path("/app/runs/explorations"),  # Docker path
            Path.cwd() / "runs" / "explorations",  # Fallback: cwd-relative
        ]

        for path in candidates:
            try:
                path.mkdir(parents=True, exist_ok=True)
                # Verify we can write to this directory
                test_file = path / ".write_test"
                test_file.write_text("test")
                test_file.unlink()
                logger.info(f"Using output directory: {path}")
                return path
            except (PermissionError, OSError) as e:
                logger.warning(f"Cannot use {path}: {e}")
                continue

        # Last resort: use temp directory
        import tempfile

        temp_dir = Path(tempfile.mkdtemp(prefix="explorations_"))
        logger.warning(f"Using temporary directory: {temp_dir}")
        return temp_dir

    async def explore(self, config: ExplorationConfig, session_id: str | None = None) -> ExplorationResult:
        """
        Start an exploration session.

        Args:
            config: Exploration configuration
            session_id: Optional session ID (auto-generated if not provided)

        Returns:
            ExplorationResult with all discovered data
        """
        if session_id is None:
            session_id = f"explore_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"

        # Create output directory for this session
        session_dir = self.output_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        logger.info("=" * 80)
        logger.info("AI-POWERED APP EXPLORATION")
        logger.info("=" * 80)
        logger.info(f"   Session: {session_id}")
        logger.info(f"   Entry URL: {config.entry_url}")
        logger.info(f"   Strategy: {config.strategy}")
        logger.info(f"   Max Interactions: {config.max_interactions}")
        logger.info(f"   Max Depth: {config.max_depth}")
        if config.credentials:
            logger.info("   Authentication: Enabled")
        logger.info("")

        # Save config
        config_data = {
            "entry_url": config.entry_url,
            "max_interactions": config.max_interactions,
            "max_depth": config.max_depth,
            "strategy": config.strategy,
            "timeout_minutes": config.timeout_minutes,
            "has_credentials": bool(config.credentials),
            "login_url": config.login_url,
            "exclude_patterns": config.exclude_patterns,
            "focus_areas": config.focus_areas,
        }
        (session_dir / "config.json").write_text(json.dumps(config_data, indent=2))

        start_time = datetime.now()

        try:
            # Build the exploration prompt
            prompt = self._build_exploration_prompt(config)

            # Invoke the explorer agent
            logger.info("Starting AI Explorer Agent...")

            raw_output = await self._run_explorer_agent(prompt, session_dir)

            # Log output diagnostics
            output_len = len(raw_output) if raw_output else 0
            if output_len == 0:
                logger.error("Explorer agent returned empty output")
            elif output_len < 200:
                logger.warning(f"Explorer agent returned very short output ({output_len} chars): {raw_output[:200]}")
            else:
                logger.info(f"   Agent output: {output_len} chars")

            # Parse the exploration output
            logger.info("Processing exploration results...")

            result = self._parse_exploration_output(
                raw_output=raw_output, session_id=session_id, entry_url=config.entry_url
            )

            # AI-powered JSON recovery when regex parsing found zero objects
            if (
                result.status == "failed"
                and not result.transitions
                and not result.flows
                and raw_output
                and len(raw_output) > 500
            ):
                logger.info("   Initial parsing found zero JSON — attempting AI-powered recovery...")
                recovered_objects = await self._run_ai_json_recovery(raw_output, session_dir)
                if recovered_objects:
                    result = self._parse_exploration_output(
                        raw_output=raw_output,
                        session_id=session_id,
                        entry_url=config.entry_url,
                        pre_extracted_json=recovered_objects,
                    )
                    if result.transitions or result.flows:
                        logger.info(
                            f"   AI recovery successful: {len(result.transitions)} transitions, "
                            f"{len(result.flows)} flows"
                        )

            # Run AI flow synthesis pass if too few flows relative to transitions
            min_expected = max(1, len(result.transitions) // 5)
            if len(result.transitions) >= 1 and len(result.flows) < min_expected:
                logger.info(
                    f"   Running AI flow synthesis pass "
                    f"({len(result.flows)} flows from {len(result.transitions)} transitions)..."
                )
                synthesized = await self._run_flow_synthesis_pass(result.transitions, result.flows, session_dir)
                if synthesized:
                    # Deduplicate against existing flows
                    existing_keys = {
                        (
                            f.name.replace(" (inferred)", "").replace(" (synthesized)", "").strip().lower(),
                            f.start_url.strip().rstrip("/").lower(),
                            f.end_url.strip().rstrip("/").lower(),
                        )
                        for f in result.flows
                    }
                    new_flows = []
                    for sf in synthesized:
                        key = (
                            sf.name.replace(" (synthesized)", "").strip().lower(),
                            sf.start_url.strip().rstrip("/").lower(),
                            sf.end_url.strip().rstrip("/").lower(),
                        )
                        if key not in existing_keys:
                            new_flows.append(sf)
                            existing_keys.add(key)
                    if new_flows:
                        logger.info(f"   Synthesized {len(new_flows)} additional flows")
                        result.flows.extend(new_flows)

            # Text-based flow synthesis fallback: when no transitions were parsed
            # but raw output is substantial, use AI to extract flows from prose
            if len(result.flows) == 0 and len(result.transitions) == 0 and raw_output and len(raw_output) > 2000:
                logger.info(
                    "   No structured transitions found — attempting text-based flow synthesis from raw output..."
                )
                text_flows = await self._run_text_flow_synthesis(raw_output, session_dir)
                if text_flows:
                    logger.info(f"   Text synthesis produced {len(text_flows)} flows")
                    result.flows.extend(text_flows)

                    # Fix status: text synthesis recovered usable data
                    if result.status == "failed" and text_flows:
                        result.status = "completed"
                        result.error_message = (
                            f"No structured JSON parsed, but text synthesis recovered {len(text_flows)} flows."
                        )

            # Calculate duration
            end_time = datetime.now()
            result.duration_seconds = int((end_time - start_time).total_seconds())

            # Save results
            self._save_results(result, session_dir)

            logger.info("Exploration Complete!")
            logger.info(f"   Pages Discovered: {result.pages_discovered}")
            logger.info(f"   Flows Discovered: {len(result.flows)}")
            logger.info(f"   Transitions Recorded: {len(result.transitions)}")
            logger.info(f"   API Endpoints Found: {len(result.api_endpoints)}")
            logger.info(f"   Duration: {result.duration_seconds}s")
            logger.info(f"   Results saved to: {session_dir}")

            return result

        except asyncio.TimeoutError:
            logger.warning(f"Exploration timed out after {config.timeout_minutes} minutes")
            return ExplorationResult(
                session_id=session_id,
                entry_url=config.entry_url,
                status="timeout",
                error_message=f"Timeout after {config.timeout_minutes} minutes",
            )
        except Exception as e:
            logger.error(f"Exploration failed: {e}")
            import traceback

            traceback.print_exc()
            return ExplorationResult(
                session_id=session_id, entry_url=config.entry_url, status="failed", error_message=str(e)
            )

    def _load_agent_prompt(self, agent_name: str) -> str | None:
        """Load agent prompt from .claude/agents/{agent_name}.md, stripping YAML frontmatter."""
        project_root = Path(__file__).resolve().parent.parent.parent
        agent_file = project_root / ".claude" / "agents" / f"{agent_name}.md"
        if not agent_file.exists():
            logger.warning(f"Agent file not found: {agent_file}")
            return None
        content = agent_file.read_text()
        # Strip YAML frontmatter (--- ... ---)
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                content = content[end + 3 :].strip()
        return content

    def _build_rules_section(self, using_md_agent: bool) -> str:
        """Build the Important Rules section, avoiding duplication when .md agent is loaded."""
        if using_md_agent:
            # The api-explorer.md already has comprehensive rules (12 rules).
            # Only append credential placeholder rules not covered by the .md file.
            return """## Additional Rules

1. ALWAYS use actual credential values during browser interaction
2. ALWAYS use placeholder syntax (e.g. {{LOGIN_USERNAME}}) in recorded output

Begin exploration now!"""
        else:
            return """## Important Rules

1. ALWAYS record transitions after each interaction
2. ALWAYS output a flow JSON record when you complete a sequence of related actions
3. ALWAYS use actual credential values during browser interaction
4. ALWAYS use placeholder syntax in recorded output
5. Do NOT re-output flow records in the final summary - only include counts
6. NEVER click logout until you've fully explored authenticated areas
7. NEVER execute truly destructive actions (delete all data, etc.)
8. Handle dialogs immediately with `browser_handle_dialog`
9. If stuck, try `browser_navigate_back` or return to entry URL

Begin exploration now!"""

    def _get_site_type_instructions(self, entry_url: str) -> str:
        """Return site-type-specific instructions based on URL patterns."""
        gov_patterns = [".gov", ".gov.", "government", "portal", "e-gov", "citizen", "mygov"]
        if any(p in entry_url.lower() for p in gov_patterns):
            return """
## Government Portal Instructions
This appears to be a government portal. Apply these specific rules:
1. Expect slow page loads (5-15 seconds). ALWAYS use `browser_wait_for(time: 5)` after navigation.
2. Dismiss any language selector immediately by selecting the primary language.
3. Accept all cookie/consent banners on first encounter.
4. Use `browser_hover` on ALL top-level menu items — government megamenus are often not in the initial snapshot.
5. Use `browser_evaluate` to extract all hrefs — many government links are JavaScript-rendered.
6. Many links may open PDF documents — record these URLs but do not navigate into them.
7. If a page redirects to a login page, record the redirect and continue with other URLs in your queue.
8. Government sites often have dozens of pages — make sure your UNVISITED_QUEUE captures them all.
"""
        return ""

    def _build_exploration_prompt(self, config: ExplorationConfig) -> str:
        """Build the prompt for the exploration agent."""

        # Build authentication section
        auth_section = ""
        if config.credentials:
            login_url = config.login_url or config.entry_url
            username = config.credentials.get("username", "")
            password = config.credentials.get("password", "")

            auth_section = f"""
## Step 1: Authentication Required

Before exploring, you MUST log in first:

1. Navigate to: {login_url}
2. Find the login form (email/username field + password field)
3. Enter username/email: `{username}` (use this ACTUAL value)
4. Enter password: `{password}` (use this ACTUAL value)
5. Click the login/submit button
6. Wait for authentication to complete
7. Verify login succeeded (look for dashboard, user menu, or logout button)

**CRITICAL**: Do not proceed until login is successful.

When recording credentials in output, use placeholders:
- Username: `{{{{LOGIN_USERNAME}}}}`
- Password: `{{{{LOGIN_PASSWORD}}}}`
"""

        # Build focus areas section
        focus_section = ""
        if config.focus_areas:
            focus_section = f"""
## Priority Areas
Focus your exploration on these areas first:
{chr(10).join(f"- {area}" for area in config.focus_areas)}
"""

        # Build exclude patterns section
        exclude_section = ""
        if config.exclude_patterns:
            exclude_section = f"""
## URLs to Skip
Do not explore URLs matching these patterns:
{chr(10).join(f"- {pattern}" for pattern in config.exclude_patterns)}
"""

        # Build additional instructions section
        instructions_section = ""
        if config.additional_instructions:
            instructions_section = f"""
## Additional Instructions
{config.additional_instructions}
"""

        strategy_instructions = {
            "goal_directed": """
**Goal-Directed Strategy**: Explore intelligently based on importance, but cover ALL discovered URLs:
- Build your UNVISITED_QUEUE first by mapping ALL links from the entry page
- Visit high-priority pages first (forms, actions, login) from the queue
- Then visit medium-priority pages (settings, help, profiles)
- Then visit remaining pages in the queue
- On each page: interact with forms and primary buttons before moving to next URL
- You MUST visit every URL in your queue before you can stop
""",
            "breadth_first": """
**Breadth-First Strategy — STRICTLY ENFORCED**:
Exploration proceeds in LEVELS. You MUST complete each level before moving to the next:

LEVEL 0: The entry URL — visit it and build your UNVISITED_QUEUE from all discovered links
LEVEL 1: Every URL discovered directly from LEVEL 0 — visit ALL before any LEVEL 2
LEVEL 2: Every NEW URL discovered from LEVEL 1 pages — visit ALL before any LEVEL 3
LEVEL 3+: Continue the pattern

ENFORCEMENT RULE: At each step, check "Have I visited ALL URLs at the current level?"
- NO -> Visit the next unvisited URL at the current level
- YES -> Advance to the next level

On each page: take a snapshot, record links, interact with 2-3 important elements, then move on.
Track your level in each status report.
""",
            "depth_first": """
**Depth-First Strategy**: Follow paths deeply before backtracking:
- Pick one user flow from UNVISITED_QUEUE and follow it completely through all sub-pages
- Record all transitions and flows along the path
- When the path ends (dead end or loops back), backtrack and pick the next queued URL
- Prioritize completing flows over breadth
- You MUST still visit every URL in your queue — just in depth-first order
""",
            "api_focused": """
**API-Focused Strategy**: Maximize API endpoint discovery with rich data capture:
- After EVERY interaction, call browser_network_requests to capture all API calls
- Parse the network log to extract full request/response details (headers, bodies, status codes)
- Prioritize form submissions, button clicks, and navigation that trigger API calls
- Try multiple input variations to discover different API behaviors and error responses
- Document authentication patterns (Bearer tokens, cookies, API keys)
- Filter out static assets (js, css, images, fonts) and third-party requests before reporting
- Focus on breadth of API discovery over depth of individual flow exploration
""",
        }

        # Build API-focused specific sections
        is_api_focused = config.strategy == "api_focused"

        # Try loading the rich api-explorer agent prompt from .md file
        api_explorer_prompt = self._load_agent_prompt("api-explorer") if is_api_focused else None

        if is_api_focused and api_explorer_prompt:
            # Use the comprehensive api-explorer.md protocol instead of inline instructions.
            # The .md file contains 6 phases, filtering rules, data masking tables, test data
            # strategy, and detailed output format — much richer than the inline version.
            mission_section = api_explorer_prompt
            output_section = ""  # Already included in the .md content
        elif is_api_focused:
            # Fallback: inline prompt if api-explorer.md is not found
            mission_section = """## Your Mission

Systematically explore this web application to discover ALL API endpoints with rich request/response data:
1. **API endpoints with full details** (headers, request bodies, response bodies) - THIS IS THE PRIMARY GOAL
2. Authentication patterns (Bearer tokens, cookies, API keys)
3. User flows that trigger API calls
4. Error responses and validation behaviors
5. All pages and their data-loading endpoints

## API Data Capture (CRITICAL)

**Capturing rich API data is your MOST IMPORTANT objective.** After EVERY interaction:
1. Call `browser_network_requests` to get the network log
2. Parse the output to identify API calls (filter out static assets like .js, .css, images, fonts)
3. For each API call, extract method, URL, status, request headers, request body, and response body
4. Include this data in the `richApiCalls` array of your transition record
5. Truncate response bodies to ~2000 characters
6. Mask sensitive data (passwords, tokens) with `***`

## Flow Detection

Also output flow records when you complete user journeys (secondary goal):
- Output a `{"flow": ...}` JSON record after completing any user journey
- Focus especially on flows that involve API interactions"""

            output_section = """## Output Format

After EACH interaction, output a transition record with rich API data:

```json
{"transition": {
  "sequence": 1,
  "action": {
    "type": "click",
    "element": {"ref": "btn1", "role": "button", "name": "Submit"},
    "value": null
  },
  "before": {
    "url": "https://example.com/login",
    "pageType": "login",
    "keyElements": ["Email input", "Password input", "Login button"]
  },
  "after": {
    "url": "https://example.com/dashboard",
    "pageType": "dashboard",
    "keyElements": ["Welcome message", "Navigation menu"],
    "changes": ["Navigated to dashboard", "User is now authenticated"]
  },
  "transitionType": "navigation",
  "apiCalls": [{"method": "POST", "url": "/api/auth/login", "status": 200}],
  "richApiCalls": [
    {
      "method": "POST",
      "url": "https://example.com/api/auth/login",
      "status": 200,
      "requestHeaders": {"Content-Type": "application/json", "Authorization": "Bearer ***"},
      "requestBody": "{\\"email\\":\\"***\\",\\"password\\":\\"***\\"}",
      "responseBody": "{\\"token\\":\\"***\\",\\"user\\":{...}}",
      "contentType": "application/json"
    }
  ]
}}
```

When you complete a user flow, output:

```json
{"flow": {
  "name": "User Login",
  "category": "authentication",
  "steps": [
    {"action": "fill", "element": "Email input", "value": "{{LOGIN_EMAIL}}"},
    {"action": "fill", "element": "Password input", "value": "{{LOGIN_PASSWORD}}"},
    {"action": "click", "element": "Login button"}
  ],
  "startUrl": "/login",
  "endUrl": "/dashboard",
  "outcome": "User authenticated and redirected to dashboard",
  "isSuccessPath": true,
  "preconditions": ["User not logged in"],
  "postconditions": ["User authenticated", "Session created"]
}}
```

At the END of exploration, output a summary with COUNTS ONLY:

```json
{"summary": {
  "pagesDiscovered": 10,
  "flowsDiscovered": 5,
  "elementsInteracted": 47,
  "apiEndpointsFound": 25,
  "issuesFound": 2,
  "status": "completed"
}}
```"""
        else:
            mission_section = """## Your Mission

Systematically explore this web application to discover:
1. **User flows** (sequences of actions that accomplish tasks) - THIS IS THE PRIMARY GOAL
2. All pages and their purposes
3. Form behaviors (what happens when submitted)
4. API endpoints (from network requests)
5. Error states (what happens with invalid input)

## Flow Detection (CRITICAL)

**Discovering user flows is your MOST IMPORTANT objective.** A flow is any sequence of related actions that accomplish a user task (logging in, submitting a form, navigating to find information, searching, etc.).

**Rules for flow detection:**
- Output a `{"flow": ...}` JSON record IMMEDIATELY after completing any user journey
- After every 5 interactions, stop and ask yourself: "Did I just complete a flow?" If yes, output it NOW
- It is BETTER to output overlapping or redundant flows than to MISS a flow
- Even simple sequences count: navigating to a page and reading content is a "Page Browse" flow
- Every form submission (success or failure) is a flow
- Every navigation path through 2+ pages is a flow"""

            output_section = """## Output Format

After EACH interaction, output a transition record:

```json
{"transition": {
  "sequence": 1,
  "action": {
    "type": "click",
    "element": {"ref": "btn1", "role": "button", "name": "Submit"},
    "value": null
  },
  "before": {
    "url": "https://example.com/login",
    "pageType": "login",
    "keyElements": ["Email input", "Password input", "Login button"]
  },
  "after": {
    "url": "https://example.com/dashboard",
    "pageType": "dashboard",
    "keyElements": ["Welcome message", "Navigation menu", "Logout button"],
    "changes": ["Navigated to dashboard", "User is now authenticated"]
  },
  "transitionType": "navigation",
  "apiCalls": [{"method": "POST", "url": "/api/auth/login", "status": 200}]
}}
```

When you complete a user flow (IMMEDIATELY after the last step), output:

```json
{"flow": {
  "name": "User Login",
  "category": "authentication",
  "steps": [
    {"action": "fill", "element": "Email input", "value": "{{LOGIN_EMAIL}}"},
    {"action": "fill", "element": "Password input", "value": "{{LOGIN_PASSWORD}}"},
    {"action": "click", "element": "Login button"}
  ],
  "startUrl": "/login",
  "endUrl": "/dashboard",
  "outcome": "User authenticated and redirected to dashboard",
  "isSuccessPath": true,
  "preconditions": ["User not logged in"],
  "postconditions": ["User authenticated", "Session created"]
}}
```

When you discover an issue or bug, output an issue record:

```json
{"issue": {
  "type": "broken_link|error_page|accessibility|performance|usability|security|missing_content",
  "severity": "critical|high|medium|low",
  "url": "https://example.com/broken-page",
  "description": "Description of the issue found",
  "element": "Element that triggered the issue",
  "evidence": "Console error, HTTP status, or visual evidence"
}}
```

At the END of exploration, output a summary with COUNTS ONLY (do NOT re-output flow or issue records that were already output above):

```json
{"summary": {
  "pagesDiscovered": 10,
  "flowsDiscovered": 5,
  "elementsInteracted": 47,
  "apiEndpointsFound": 12,
  "issuesFound": 2,
  "status": "completed"
}}
```"""

        prompt = f"""You are the App Explorer Agent.

# Task: Explore the Web Application

**Entry URL**: {config.entry_url}
**Max Interactions**: {config.max_interactions}
**Max Depth**: {config.max_depth} navigation levels from entry

{auth_section}

## Exploration Strategy
{strategy_instructions.get(config.strategy, strategy_instructions["goal_directed"])}

{focus_section}
{exclude_section}
{instructions_section}
{self._get_site_type_instructions(config.entry_url)}
{mission_section}

## Execution Steps

### Step 1: Map the Site (Phase 0 — MANDATORY)
1. Call `browser_navigate` to go to: {config.entry_url}
2. Handle any popups (cookie consent, language selector) immediately
3. Call `browser_snapshot` to see the page structure
4. Call `browser_evaluate` with `() => Array.from(document.querySelectorAll('a[href]')).map(a => ({{text: a.textContent.trim().slice(0,50), href: a.href}})).filter(a => a.href && !a.href.startsWith('javascript:') && a.text)` to extract ALL links
5. Hover over top-level navigation items to reveal dropdown menus, take snapshot after each hover
6. Build your UNVISITED_QUEUE from all discovered links
7. Output your queue before proceeding

### Step 2: Explore Each Page in the Queue
For each URL in UNVISITED_QUEUE:
1. Navigate to it, wait for load (`browser_wait_for` with 5s)
2. Take snapshot + extract links (add new ones to queue)
3. Interact with important elements (forms, buttons, search)
4. Call `browser_network_requests` after interactions to find API calls
5. Record transition for each interaction
6. **Check: Did this complete a user flow? If yes, output a flow record NOW**

### Step 3: Budget-Aware Loop
After each interaction, report your status and check the loop contract:

```
STEP [N of {config.max_interactions}] — Budget remaining: [Y]
UNVISITED_QUEUE: [M URLs remaining]
Continue: [reason]
```

You MUST continue until EITHER:
a. You have used all {config.max_interactions} interactions
b. Your UNVISITED_QUEUE is empty AND 3 consecutive actions found nothing new

If you reach interaction {config.max_interactions // 2} (halfway) and have only visited
{max(2, config.max_interactions // 10)} or fewer unique pages, switch to breadth-first:
visit your queued URLs before exploring the current page further.

{output_section}

{self._build_rules_section(api_explorer_prompt is not None)}
"""
        return prompt

    async def _run_explorer_agent(self, prompt: str, session_dir: Path) -> str:
        """Run the exploration agent and capture output using AgentRunner."""
        # Get timeout from environment or use 30 minutes default
        timeout = int(os.environ.get("EXPLORATION_TIMEOUT_SECONDS", get_default_timeout()))

        logger.info(f"   Timeout: {timeout}s ({timeout // 60} minutes)")

        # Create per-session MCP config for browser isolation
        # This mirrors the pattern from main.py:3948-3968 for test runs
        headless = os.environ.get("HEADLESS", "true").lower() != "false"
        mcp_args = ["@playwright/mcp", "--browser", "chromium"]
        if headless:
            mcp_args.append("--headless")

        mcp_config = {"mcpServers": {"playwright-test": {"command": "npx", "args": mcp_args}}}
        mcp_config_path = session_dir / ".mcp.json"
        mcp_config_path.write_text(json.dumps(mcp_config, indent=2))
        logger.info(f"   Created MCP config (headless={headless}): {mcp_config_path}")

        # Copy .claude/ agents directory for isolation
        import shutil

        project_root = Path(__file__).resolve().parent.parent.parent
        claude_src = project_root / ".claude"
        claude_dst = session_dir / ".claude"
        if claude_src.exists() and not claude_dst.exists():
            shutil.copytree(claude_src, claude_dst, dirs_exist_ok=True)

        # Change CWD to session_dir so the SDK finds our .mcp.json
        original_cwd = os.getcwd()
        os.chdir(session_dir)
        logger.info(f"   CWD set to: {session_dir}")

        try:
            # Track interactions for progress reporting
            interaction_count = [0]

            def on_tool_use(tool_name: str, tool_input: dict):
                """Callback when a tool is used."""
                if tool_name.startswith("mcp__playwright"):
                    interaction_count[0] += 1
                    if interaction_count[0] % 10 == 0:
                        logger.info(f"   Interactions: {interaction_count[0]}")

            # Playwright MCP tools matching .claude/agents/app-explorer.md (and api-explorer.md for api_focused strategy)
            EXPLORER_MCP_TOOLS = [
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
            ]

            # Use the unified AgentRunner
            runner = AgentRunner(
                timeout_seconds=timeout,
                allowed_tools=build_allowed_tools(
                    ["Glob", "Grep", "Read", "LS"],
                    EXPLORER_MCP_TOOLS,
                ),
                log_tools=True,
                on_tool_use=on_tool_use,
                session_dir=session_dir,
                on_task_enqueued=self.on_task_enqueued,
            )

            result = await runner.run(prompt)

            # Log diagnostics
            logger.info(
                f"   Agent stats: {result.messages_received} messages, "
                f"{len(result.tool_calls)} tool calls, "
                f"{result.duration_seconds:.1f}s"
            )

            if result.timed_out:
                if not result.output or not result.output.strip():
                    raise RuntimeError(
                        f"Explorer agent timed out after {result.duration_seconds:.0f}s "
                        f"without producing any output. "
                        f"Messages: {result.messages_received}, Tool calls: {len(result.tool_calls)}. "
                        f"This usually means the MCP server failed to start or the model returned no response."
                    )
                logger.warning(f"   Agent timed out - returning partial results ({len(result.output)} chars)")
                return result.output

            # Raise on agent failure (mirrors requirements_generator.py pattern)
            if not result.success and result.error:
                raise RuntimeError(f"Explorer agent failed: {result.error}")

            # Raise on empty output (agent ran but produced nothing)
            if not result.output or not result.output.strip():
                raise RuntimeError(
                    "Explorer agent returned empty output — likely an authentication, "
                    "MCP configuration, or model connectivity issue. "
                    "Check backend logs for details."
                )

            return result.output
        finally:
            # Always restore CWD
            os.chdir(original_cwd)
            logger.info(f"   CWD restored to: {original_cwd}")

    def _deduplicate_flows(self, flows: list[FlowRecord]) -> list[FlowRecord]:
        """Deduplicate flows by normalized (name, start_url, end_url) tuple. Keeps first occurrence."""
        seen = set()
        unique_flows = []
        for flow in flows:
            key = (
                flow.name.strip().lower(),
                flow.start_url.strip().rstrip("/").lower(),
                flow.end_url.strip().rstrip("/").lower(),
            )
            if key not in seen:
                seen.add(key)
                unique_flows.append(flow)
        return unique_flows

    def _deduplicate_transitions(self, transitions: list[TransitionRecord]) -> list[TransitionRecord]:
        """Deduplicate transitions by key fields. Keeps first occurrence."""
        seen = set()
        unique = []
        for t in transitions:
            elem_name = (t.action_element or {}).get("name", "")
            key = (
                t.sequence,
                t.before_url.strip().rstrip("/").lower(),
                t.after_url.strip().rstrip("/").lower(),
                t.action_type.strip().lower(),
                elem_name.strip().lower(),
            )
            if key not in seen:
                seen.add(key)
                unique.append(t)
        return unique

    def _extract_json_objects(self, raw_output: str) -> list[dict]:
        """Extract all JSON objects from agent output using multiple strategies.

        Strategy 1: ```json ... ``` code blocks (existing)
        Strategy 2: Bare JSON objects starting with known prefixes
        """
        results = []
        seen_json = set()

        # Strategy 1: Extract from code blocks using boundary detection
        # Find ```json or ``` markers and extract content between them
        code_block_pattern = r"```(?:json)?\s*\n(.*?)\n\s*```"
        for json_str in re.findall(code_block_pattern, raw_output, re.DOTALL):
            json_str = json_str.strip()
            if not json_str.startswith("{"):
                continue
            try:
                data = json.loads(json_str)
                # Use a normalized representation to deduplicate
                key = json.dumps(data, sort_keys=True)
                if key not in seen_json:
                    seen_json.add(key)
                    results.append(data)
            except json.JSONDecodeError:
                # Try fix truncated JSON
                try:
                    data = extract_json_from_markdown(f"```json\n{json_str}\n```")
                    key = json.dumps(data, sort_keys=True)
                    if key not in seen_json:
                        seen_json.add(key)
                        results.append(data)
                except (ValueError, json.JSONDecodeError):
                    continue

        # Strategy 2: Find bare JSON objects with known prefixes outside code blocks
        # Remove code blocks first to avoid double-counting
        stripped = re.sub(r"```(?:json)?\s*\n.*?\n\s*```", "", raw_output, flags=re.DOTALL)

        # Look for JSON objects starting with known keys
        bare_pattern = r'(\{"(?:transition|flow|summary|issue)"\s*:)'
        for match in re.finditer(bare_pattern, stripped):
            start = match.start()
            # Use brace-depth counting to find the matching close brace
            depth = 0
            in_string = False
            escape_next = False
            end = start
            for i in range(start, len(stripped)):
                ch = stripped[i]
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\" and in_string:
                    escape_next = True
                    continue
                if ch == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if not in_string:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
            if depth == 0 and end > start:
                json_str = stripped[start:end]
                try:
                    data = json.loads(json_str)
                    key = json.dumps(data, sort_keys=True)
                    if key not in seen_json:
                        seen_json.add(key)
                        results.append(data)
                except json.JSONDecodeError:
                    continue

        # Strategy 3: Rescue parse — case-insensitive keys + truncated JSON recovery
        # Only runs when Strategies 1+2 found nothing
        if not results:
            rescue_pattern = r'(\{"(?:[Tt]ransition|[Ff]low|[Ss]ummary|[Ii]ssue)"\s*:)'
            for match in re.finditer(rescue_pattern, raw_output):
                start = match.start()
                # Brace-depth counting to find matching close brace
                depth = 0
                in_string = False
                escape_next = False
                end = start
                for i in range(start, min(start + 50000, len(raw_output))):
                    ch = raw_output[i]
                    if escape_next:
                        escape_next = False
                        continue
                    if ch == "\\" and in_string:
                        escape_next = True
                        continue
                    if ch == '"' and not escape_next:
                        in_string = not in_string
                        continue
                    if not in_string:
                        if ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                            if depth == 0:
                                end = i + 1
                                break
                if depth == 0 and end > start:
                    json_str = raw_output[start:end]
                    try:
                        data = json.loads(json_str)
                    except json.JSONDecodeError:
                        # Try truncated JSON recovery
                        try:
                            data = extract_json_from_markdown(f"```json\n{json_str}\n```")
                        except (ValueError, json.JSONDecodeError):
                            continue
                    if isinstance(data, dict):
                        # Normalize top-level key to lowercase
                        normalized = {}
                        for k, v in data.items():
                            normalized[k.lower()] = v
                        key = json.dumps(normalized, sort_keys=True)
                        if key not in seen_json:
                            seen_json.add(key)
                            results.append(normalized)
                elif depth > 0:
                    # Truncated JSON — try extract_json_from_markdown recovery
                    json_str = raw_output[start : min(start + 50000, len(raw_output))]
                    try:
                        data = extract_json_from_markdown(f"```json\n{json_str}\n```")
                        if isinstance(data, dict):
                            normalized = {k.lower(): v for k, v in data.items()}
                            key = json.dumps(normalized, sort_keys=True)
                            if key not in seen_json:
                                seen_json.add(key)
                                results.append(normalized)
                    except (ValueError, json.JSONDecodeError):
                        continue

            if results:
                logger.info(f"Strategy 3 (rescue parse) recovered {len(results)} JSON objects")

        return results

    def _parse_exploration_output(
        self,
        raw_output: str,
        session_id: str,
        entry_url: str,
        pre_extracted_json: list[dict] = None,
    ) -> ExplorationResult:
        """Parse the exploration agent's output into structured data.

        Args:
            pre_extracted_json: If provided, skip regex extraction and use
                these objects directly (e.g. from AI JSON recovery).
        """

        transitions = []
        flows = []
        api_endpoints = []
        issues = []
        pages_seen = set()

        # Handle empty input
        if not raw_output or not raw_output.strip():
            return ExplorationResult(
                session_id=session_id,
                entry_url=entry_url,
                status="failed",
                error_message="Agent returned empty output — no exploration data to parse",
            )

        # Use pre-extracted objects (from AI recovery) or extract via regex strategies
        all_json_objects = (
            pre_extracted_json if pre_extracted_json is not None else self._extract_json_objects(raw_output)
        )

        for data in all_json_objects:
            try:
                # Parse transition records
                if "transition" in data:
                    t = data["transition"]
                    action = t.get("action") or {}
                    before = t.get("before") or {}
                    after = t.get("after") or {}

                    transition = TransitionRecord(
                        sequence=t.get("sequence") or len(transitions) + 1,
                        action_type=action.get("type") or "unknown",
                        action_element=action.get("element") or {},
                        action_value=action.get("value"),
                        before_url=before.get("url") or "",
                        before_page_type=before.get("pageType"),
                        before_elements=before.get("keyElements") or [],
                        after_url=after.get("url") or "",
                        after_page_type=after.get("pageType"),
                        after_elements=after.get("keyElements") or [],
                        transition_type=t.get("transitionType") or "unknown",
                        api_calls=t.get("apiCalls") or [],
                        changes_description=", ".join(after.get("changes") or []),
                    )
                    transitions.append(transition)

                    # Track pages
                    if before.get("url"):
                        pages_seen.add(before["url"])
                    if after.get("url"):
                        pages_seen.add(after["url"])

                    # Extract API endpoints - prefer richApiCalls for detailed data
                    rich_calls = t.get("richApiCalls") or []
                    basic_calls = t.get("apiCalls") or []
                    action_element = action.get("element") or {}
                    triggered_by = f"{action.get('type') or 'unknown'} on {action_element.get('name') or 'element'}"

                    if rich_calls:
                        for api_call in rich_calls:
                            endpoint = {
                                "method": api_call.get("method") or "GET",
                                "url": api_call.get("url") or "",
                                "status": api_call.get("status"),
                                "triggered_by": triggered_by,
                                "request_headers": api_call.get("requestHeaders"),
                                "request_body": api_call.get("requestBody"),
                                "response_body": api_call.get("responseBody"),
                            }
                            # Deduplicate by method+url, but update with rich data if already seen
                            existing = next(
                                (
                                    e
                                    for e in api_endpoints
                                    if e["method"] == endpoint["method"] and e["url"] == endpoint["url"]
                                ),
                                None,
                            )
                            if existing:
                                # Merge rich data into existing entry if it was missing
                                if endpoint.get("request_headers") and not existing.get("request_headers"):
                                    existing["request_headers"] = endpoint["request_headers"]
                                if endpoint.get("request_body") and not existing.get("request_body"):
                                    existing["request_body"] = endpoint["request_body"]
                                if endpoint.get("response_body") and not existing.get("response_body"):
                                    existing["response_body"] = endpoint["response_body"]
                            else:
                                api_endpoints.append(endpoint)
                    else:
                        for api_call in basic_calls:
                            endpoint = {
                                "method": api_call.get("method") or "GET",
                                "url": api_call.get("url") or "",
                                "status": api_call.get("status"),
                                "triggered_by": triggered_by,
                            }
                            if not any(
                                e["method"] == endpoint["method"] and e["url"] == endpoint["url"] for e in api_endpoints
                            ):
                                api_endpoints.append(endpoint)

                # Parse flow records
                elif "flow" in data:
                    f = data["flow"]
                    flow = FlowRecord(
                        name=f.get("name") or "Unnamed Flow",
                        category=f.get("category") or "unknown",
                        steps=f.get("steps") or [],
                        start_url=f.get("startUrl") or "",
                        end_url=f.get("endUrl") or "",
                        outcome=f.get("outcome") or "",
                        is_success_path=f.get("isSuccessPath", True),
                        preconditions=f.get("preconditions") or [],
                        postconditions=f.get("postconditions") or [],
                    )
                    flows.append(flow)

                # Parse issue records
                elif "issue" in data:
                    iss = data["issue"]
                    issue = IssueRecord(
                        issue_type=iss.get("type") or "unknown",
                        severity=iss.get("severity") or "medium",
                        url=iss.get("url") or "",
                        description=iss.get("description") or "",
                        element=iss.get("element"),
                        evidence=iss.get("evidence"),
                    )
                    issues.append(issue)

                # Parse summary
                elif "summary" in data:
                    summary = data["summary"]
                    # Use summary data to augment page count — never undercount
                    summary_pages = summary.get("pagesDiscovered") or 0
                    if summary_pages > len(pages_seen):
                        # Add placeholder entries to reach the summary count
                        for i in range(summary_pages - len(pages_seen)):
                            pages_seen.add(f"__summary_page_{i}")

            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        # Auto-create issues from error transitions
        for t in transitions:
            if t.transition_type == "error":
                issues.append(
                    IssueRecord(
                        issue_type="error_page",
                        severity="high",
                        url=t.after_url or t.before_url,
                        description=t.changes_description or f"Error encountered during {t.action_type}",
                        element=(t.action_element or {}).get("name"),
                    )
                )

        # URL text mining fallback: extract URLs from prose text matching entry domain
        try:
            from urllib.parse import urlparse

            entry_domain = urlparse(entry_url).netloc
            if entry_domain:
                url_pattern = re.compile(r'https?://[^\s<>"\')\]]+', re.IGNORECASE)
                for url_match in url_pattern.finditer(raw_output):
                    found_url = url_match.group(0).rstrip(".,;:")
                    try:
                        if urlparse(found_url).netloc == entry_domain:
                            pages_seen.add(found_url)
                    except Exception:
                        continue
        except Exception:
            pass

        # Deduplicate flows and transitions
        flows = self._deduplicate_flows(flows)
        transitions = self._deduplicate_transitions(transitions)

        # Infer flows from transitions if agent didn't emit enough
        inferred = self._infer_flows_from_transitions(transitions, flows)
        if inferred:
            logger.info(f"   Inferred {len(inferred)} additional flows from transitions")
            flows.extend(inferred)

        # Calculate elements discovered from transitions
        elements_discovered = set()
        for t in transitions:
            action_elem = t.action_element or {}
            if action_elem.get("name"):
                elements_discovered.add(action_elem["name"])
            elements_discovered.update(t.before_elements or [])
            elements_discovered.update(t.after_elements or [])

        # Determine status based on results quality
        status = "completed"
        error_message = None

        if not all_json_objects and raw_output.strip():
            # Agent produced output but no structured JSON data
            logger.warning(f"Zero JSON objects from {len(raw_output)}-char output. First 500:\n{raw_output[:500]}")
            if len(raw_output) > 500:
                logger.warning(f"Last 500:\n{raw_output[-500:]}")
            status = "failed"
            error_message = (
                "Agent produced output but no structured JSON data was found. "
                "The agent may have encountered navigation issues or been blocked by the target site."
            )
        elif not transitions and not flows and not api_endpoints:
            # JSON was found but nothing useful was extracted
            status = "failed"
            error_message = (
                "Exploration completed but discovered zero transitions, flows, and API endpoints. "
                "The target site may have blocked automated access or the agent couldn't interact with the page."
            )

        return ExplorationResult(
            session_id=session_id,
            entry_url=entry_url,
            status=status,
            transitions=transitions,
            flows=flows,
            api_endpoints=api_endpoints,
            issues=issues,
            pages_discovered=len(pages_seen),
            elements_discovered=len(elements_discovered),
            error_message=error_message,
        )

    def _infer_flows_from_transitions(
        self, transitions: list[TransitionRecord], existing_flows: list[FlowRecord]
    ) -> list[FlowRecord]:
        """Infer user flows from transition patterns when the agent didn't emit flow JSON.

        Segments transitions into logical groups and pattern-matches against
        known flow archetypes (authentication, form submission, navigation, search).

        Returns only flows that don't duplicate existing flow names.
        """
        if len(transitions) < 2:
            return []

        existing_names = {f.name.strip().lower() for f in existing_flows}
        # Also track by (start_url, end_url) to avoid semantic duplicates
        existing_keys = {
            (f.start_url.strip().rstrip("/").lower(), f.end_url.strip().rstrip("/").lower()) for f in existing_flows
        }

        inferred_flows = []

        # Segment transitions into groups by detecting boundaries
        segments = self._segment_transitions(transitions)

        for segment in segments:
            if len(segment) < 2:
                continue

            flow = self._classify_segment(segment)
            if flow is None:
                continue

            # Check for duplicates against existing flows
            name_key = flow.name.replace(" (inferred)", "").strip().lower()
            url_key = (
                flow.start_url.strip().rstrip("/").lower(),
                flow.end_url.strip().rstrip("/").lower(),
            )
            if name_key in existing_names or url_key in existing_keys:
                continue

            existing_names.add(name_key)
            existing_keys.add(url_key)
            inferred_flows.append(flow)

        return inferred_flows

    def _segment_transitions(self, transitions: list[TransitionRecord]) -> list[list[TransitionRecord]]:
        """Segment transitions into logical flow groups.

        Boundaries are detected by:
        - URL discontinuity (after_url of prev != before_url of next)
        - Navigation back to entry/home page
        - Large gaps in sequence numbers
        """
        if not transitions:
            return []

        segments = []
        current_segment = [transitions[0]]

        for i in range(1, len(transitions)):
            prev = transitions[i - 1]
            curr = transitions[i]

            # Detect boundary conditions
            url_discontinuity = (
                prev.after_url
                and curr.before_url
                and prev.after_url.strip().rstrip("/").lower() != curr.before_url.strip().rstrip("/").lower()
            )
            sequence_gap = curr.sequence - prev.sequence > 3

            if url_discontinuity or sequence_gap:
                # Close current segment and start new one
                if len(current_segment) >= 2:
                    segments.append(current_segment)
                current_segment = [curr]
            else:
                current_segment.append(curr)

        # Don't forget the last segment
        if len(current_segment) >= 2:
            segments.append(current_segment)

        return segments

    async def _run_flow_synthesis_pass(
        self,
        transitions: list[TransitionRecord],
        existing_flows: list[FlowRecord],
        session_dir: Path,
    ) -> list[FlowRecord]:
        """Run a second AI pass to identify flows from transitions when too few were found.

        This is a pure text-analysis call (no browser tools needed) with a short timeout.
        """
        if not transitions:
            return []

        # Build a compact text representation of transitions
        transition_lines = []
        for t in transitions:
            elem = t.action_element or {}
            elem_desc = elem.get("name") or elem.get("role") or "element"
            val = f' "{t.action_value}"' if t.action_value else ""
            api_desc = ""
            if t.api_calls:
                api_desc = " | APIs: " + ", ".join(
                    f"{a.get('method', '?')} {a.get('url', '?')} -> {a.get('status', '?')}" for a in t.api_calls
                )
            transition_lines.append(
                f"  {t.sequence}. {t.action_type} on '{elem_desc}'{val} | "
                f"{t.before_url} ({t.before_page_type or '?'}) -> "
                f"{t.after_url} ({t.after_page_type or '?'}) "
                f"[{t.transition_type}]{api_desc}"
            )

        existing_names = [f.name for f in existing_flows]

        prompt = f"""Analyze these browser interaction transitions and identify ALL distinct user flows.

## Transitions Recorded
{chr(10).join(transition_lines)}

## Already Identified Flows
{json.dumps(existing_names) if existing_names else "None"}

## Task
Identify user flows (sequences of related actions that accomplish a task) from the transitions above.
Do NOT repeat flows already identified. Look for:
- Authentication flows (login, logout, registration)
- Form submissions (filling fields + submit)
- Navigation patterns (browsing through sections)
- Search flows (entering query + viewing results)
- CRUD operations (create, read, update, delete)
- Any other meaningful user journeys

## Output Format
Return ONLY a JSON array of flow objects. No other text.

```json
[
  {{
    "name": "Flow Name",
    "category": "authentication|crud|navigation|form_submission|search|settings",
    "steps": [
      {{"action": "fill", "element": "Element Name", "value": "value"}},
      {{"action": "click", "element": "Button Name"}}
    ],
    "startUrl": "/start-page",
    "endUrl": "/end-page",
    "outcome": "What the flow accomplishes",
    "isSuccessPath": true,
    "preconditions": ["Required state before flow"],
    "postconditions": ["State after flow completes"]
  }}
]
```
"""

        try:
            runner = AgentRunner(
                timeout_seconds=120,
                allowed_tools=[],  # No tools needed - pure text analysis
                log_tools=False,
                session_dir=session_dir,
            )

            result = await runner.run(prompt)

            if not result.success or not result.output:
                return []

            # Parse the response - try extract_json_from_markdown first
            flow_data = None
            try:
                flow_data = extract_json_from_markdown(result.output)
                # If it returned a dict, might be wrapped
                if isinstance(flow_data, dict) and "flows" in flow_data:
                    flow_data = flow_data["flows"]
                elif isinstance(flow_data, dict):
                    flow_data = [flow_data]
            except (ValueError, json.JSONDecodeError):
                pass

            # Fallback: try to find a JSON array in the output
            if not flow_data:
                array_match = re.search(r"\[[\s\S]*\]", result.output)
                if array_match:
                    try:
                        flow_data = json.loads(array_match.group(0))
                    except json.JSONDecodeError:
                        pass

            if not flow_data or not isinstance(flow_data, list):
                return []

            # Convert to FlowRecord objects
            synthesized = []
            for f in flow_data:
                if not isinstance(f, dict):
                    continue
                name = f.get("name", "Unnamed Flow")
                if not name.endswith("(synthesized)"):
                    name = f"{name} (synthesized)"
                flow = FlowRecord(
                    name=name,
                    category=f.get("category", "unknown"),
                    steps=f.get("steps", []),
                    start_url=f.get("startUrl", ""),
                    end_url=f.get("endUrl", ""),
                    outcome=f.get("outcome", ""),
                    is_success_path=f.get("isSuccessPath", True),
                    preconditions=f.get("preconditions", []),
                    postconditions=f.get("postconditions", []),
                )
                synthesized.append(flow)

            return self._deduplicate_flows(synthesized)

        except Exception as e:
            logger.warning(f"   Flow synthesis pass failed: {e}")
            return []

    async def _run_text_flow_synthesis(
        self,
        raw_output: str,
        session_dir: Path,
    ) -> list[FlowRecord]:
        """Extract flows from raw prose output when no structured JSON was parsed.

        This is a fallback for when the agent produced descriptive text but
        didn't emit properly formatted JSON transition/flow records.
        """
        # Truncate to avoid token limits — use last portion (most likely has summary info)
        max_chars = 8000
        text_excerpt = raw_output[-max_chars:] if len(raw_output) > max_chars else raw_output

        prompt = f"""Analyze this browser exploration output and identify ALL user flows the agent performed.

## Raw Exploration Output (excerpt)
{text_excerpt}

## Task
Extract any user flows (sequences of related actions that accomplish a task) from the text above.
Look for descriptions of:
- Pages visited and navigation between them
- Forms filled and submitted
- Buttons clicked and their results
- Authentication attempts
- Search interactions
- Any multi-step user journey

## Output Format
Return ONLY a JSON array of flow objects. No other text.

```json
[
  {{
    "name": "Flow Name",
    "category": "authentication|crud|navigation|form_submission|search|settings",
    "steps": [
      {{"action": "navigate", "element": "page", "value": "URL"}},
      {{"action": "click", "element": "Button Name"}}
    ],
    "startUrl": "/start-page",
    "endUrl": "/end-page",
    "outcome": "What the flow accomplishes",
    "isSuccessPath": true,
    "preconditions": [],
    "postconditions": []
  }}
]
```
"""

        try:
            runner = AgentRunner(
                timeout_seconds=120,
                allowed_tools=[],
                log_tools=False,
                session_dir=session_dir,
            )

            result = await runner.run(prompt)
            if not result.success or not result.output:
                return []

            # Parse the response
            flow_data = None
            try:
                flow_data = extract_json_from_markdown(result.output)
                if isinstance(flow_data, dict) and "flows" in flow_data:
                    flow_data = flow_data["flows"]
                elif isinstance(flow_data, dict):
                    flow_data = [flow_data]
            except (ValueError, json.JSONDecodeError):
                pass

            if not flow_data:
                array_match = re.search(r"\[[\s\S]*\]", result.output)
                if array_match:
                    try:
                        flow_data = json.loads(array_match.group(0))
                    except json.JSONDecodeError:
                        pass

            if not flow_data or not isinstance(flow_data, list):
                return []

            synthesized = []
            for f in flow_data:
                if not isinstance(f, dict):
                    continue
                name = f.get("name", "Unnamed Flow")
                if not name.endswith("(synthesized)"):
                    name = f"{name} (synthesized)"
                flow = FlowRecord(
                    name=name,
                    category=f.get("category", "unknown"),
                    steps=f.get("steps", []),
                    start_url=f.get("startUrl", ""),
                    end_url=f.get("endUrl", ""),
                    outcome=f.get("outcome", ""),
                    is_success_path=f.get("isSuccessPath", True),
                    preconditions=f.get("preconditions", []),
                    postconditions=f.get("postconditions", []),
                )
                synthesized.append(flow)

            return self._deduplicate_flows(synthesized)

        except Exception as e:
            logger.warning(f"   Text flow synthesis failed: {e}")
            return []

    async def _run_ai_json_recovery(
        self,
        raw_output: str,
        session_dir: Path,
    ) -> list[dict]:
        """Use AI to extract structured JSON objects from raw exploration output.

        Called when regex-based extraction (Strategies 1-3) found zero objects.
        Processes the FULL output without truncation by chunking with overlap.

        Returns a list of dicts with keys like "transition", "flow", "issue", "summary".
        """
        if not raw_output or len(raw_output) < 200:
            return []

        CHUNK_SIZE = 25000  # chars per chunk (~8k tokens)
        OVERLAP = 3000  # overlap to avoid splitting JSON at boundaries

        # Build chunks covering the entire output
        chunks = []
        if len(raw_output) <= CHUNK_SIZE:
            chunks = [raw_output]
        else:
            pos = 0
            while pos < len(raw_output):
                end = min(pos + CHUNK_SIZE, len(raw_output))
                chunks.append(raw_output[pos:end])
                pos = end - OVERLAP
                if pos >= len(raw_output):
                    break

        logger.info(f"   AI JSON recovery: processing {len(raw_output)} chars in {len(chunks)} chunk(s)")

        all_recovered = []
        seen_json = set()

        for i, chunk in enumerate(chunks):
            chunk_label = f"chunk {i + 1}/{len(chunks)}" if len(chunks) > 1 else "full output"

            prompt = f"""You are a JSON extraction specialist. The following text is output from a browser exploration agent that was supposed to emit structured JSON records but may have formatted them incorrectly, used wrong casing, or embedded them in prose text.

## Your Task
Extract ALL structured JSON objects from the text below. Look for:
1. **Transition records**: Objects with a "transition" key containing action, before, after, transitionType, apiCalls
2. **Flow records**: Objects with a "flow" key containing name, category, steps, startUrl, endUrl, outcome
3. **Issue records**: Objects with an "issue" key containing type, severity, url, description
4. **Summary records**: Objects with a "summary" key containing pagesDiscovered, flowsDiscovered, etc.

## Rules
- Extract EVERY instance you find, even if the JSON is malformed — fix the structure
- If the agent described browser actions in prose but did NOT emit JSON, CREATE the appropriate transition and flow JSON records from those descriptions
- Use lowercase top-level keys: "transition", "flow", "issue", "summary"
- Preserve all nested data exactly as found (URLs, element names, API calls, steps)
- Output ONLY a JSON array of objects, no other text before or after
- If you find absolutely nothing extractable, output: []

## Expected JSON Structures

Transition: {{"transition": {{"sequence": 1, "action": {{"type": "click", "element": {{"ref": "...", "role": "button", "name": "Submit"}}, "value": null}}, "before": {{"url": "...", "pageType": "...", "keyElements": [...]}}, "after": {{"url": "...", "pageType": "...", "keyElements": [...], "changes": [...]}}, "transitionType": "navigation", "apiCalls": [...]}}}}

Flow: {{"flow": {{"name": "...", "category": "authentication|crud|navigation|form_submission|search", "steps": [...], "startUrl": "...", "endUrl": "...", "outcome": "...", "isSuccessPath": true, "preconditions": [...], "postconditions": [...]}}}}

Issue: {{"issue": {{"type": "broken_link|error_page|accessibility|performance|usability|security|missing_content", "severity": "critical|high|medium|low", "url": "...", "description": "..."}}}}

Summary: {{"summary": {{"pagesDiscovered": 10, "flowsDiscovered": 5, "elementsInteracted": 47, "apiEndpointsFound": 12, "issuesFound": 2, "status": "completed"}}}}

## Exploration Output ({chunk_label}, {len(chunk)} chars)
{chunk}
"""

            try:
                runner = AgentRunner(
                    timeout_seconds=180,
                    allowed_tools=[],  # Pure text analysis
                    log_tools=False,
                    session_dir=session_dir,
                )

                result = await runner.run(prompt)

                if not result.success or not result.output:
                    logger.warning(f"   AI JSON recovery {chunk_label}: no output")
                    continue

                # Parse AI response
                recovered = None
                try:
                    recovered = extract_json_from_markdown(result.output)
                    if isinstance(recovered, dict):
                        recovered = [recovered]
                except (ValueError, json.JSONDecodeError):
                    pass

                if not recovered:
                    array_match = re.search(r"\[[\s\S]*\]", result.output)
                    if array_match:
                        try:
                            recovered = json.loads(array_match.group(0))
                        except json.JSONDecodeError:
                            pass

                if recovered and isinstance(recovered, list):
                    chunk_count = 0
                    for obj in recovered:
                        if isinstance(obj, dict):
                            # Normalize top-level keys to lowercase
                            normalized = {k.lower(): v for k, v in obj.items()}
                            key = json.dumps(normalized, sort_keys=True)
                            if key not in seen_json:
                                seen_json.add(key)
                                all_recovered.append(normalized)
                                chunk_count += 1
                    logger.info(f"   AI JSON recovery {chunk_label}: extracted {chunk_count} objects")
                else:
                    logger.warning(f"   AI JSON recovery {chunk_label}: could not parse response")

            except Exception as e:
                logger.warning(f"   AI JSON recovery {chunk_label} failed: {e}")
                continue

        logger.info(f"   AI JSON recovery total: {len(all_recovered)} unique objects")
        return all_recovered

    def _classify_segment(self, segment: list[TransitionRecord]) -> FlowRecord | None:
        """Classify a segment of transitions into a flow archetype.

        Returns a FlowRecord or None if no pattern matches.
        """
        actions = [t.action_type.lower() for t in segment]
        urls = [t.before_url.lower() for t in segment] + [segment[-1].after_url.lower()]
        all_elements = []
        for t in segment:
            elem = t.action_element or {}
            all_elements.append(elem.get("name", "").lower())
        api_methods = []
        for t in segment:
            for api in t.api_calls or []:
                api_methods.append(api.get("method", "").upper())

        start_url = segment[0].before_url
        end_url = segment[-1].after_url

        # Build steps from transitions
        steps = []
        for t in segment:
            elem = t.action_element or {}
            step = {
                "action": t.action_type,
                "element": elem.get("name", "unknown"),
            }
            if t.action_value:
                step["value"] = t.action_value
            steps.append(step)

        # Pattern: Authentication flow
        auth_keywords = ["login", "sign in", "signin", "auth", "password", "email", "username"]
        has_fill = actions.count("fill") >= 1
        has_auth_url = any(kw in url for url in urls for kw in ["login", "auth", "signin", "sign-in"])
        has_auth_element = any(kw in elem for elem in all_elements for kw in auth_keywords)
        has_post = "POST" in api_methods

        if has_fill and (has_auth_url or has_auth_element) and has_post:
            return FlowRecord(
                name="Authentication Flow (inferred)",
                category="authentication",
                steps=steps,
                start_url=start_url,
                end_url=end_url,
                outcome=f"User navigated from {start_url} to {end_url}",
                is_success_path=True,
                preconditions=["User not authenticated"],
                postconditions=["User authenticated"],
            )

        # Pattern: Form submission (2+ fills followed by click/submit)
        fill_count = actions.count("fill")
        has_click = "click" in actions
        if fill_count >= 2 and has_click:
            # Determine form type from element names
            form_elements = [e for e, a in zip(all_elements, actions) if a == "fill" and e]
            form_name = "Form Submission"
            if form_elements:
                # Use first meaningful element name for context
                form_name = f"{form_elements[0].title()} Form Submission"

            return FlowRecord(
                name=f"{form_name} (inferred)",
                category="form_submission",
                steps=steps,
                start_url=start_url,
                end_url=end_url,
                outcome=f"Form submitted with {fill_count} fields",
                is_success_path=True,
                preconditions=[],
                postconditions=[],
            )

        # Pattern: Search (fill into search-like element + navigation/update)
        search_keywords = ["search", "query", "find", "filter"]
        has_search_element = any(kw in elem for elem in all_elements for kw in search_keywords)
        if has_fill and has_search_element:
            return FlowRecord(
                name="Search Flow (inferred)",
                category="search",
                steps=steps,
                start_url=start_url,
                end_url=end_url,
                outcome="Search performed and results displayed",
                is_success_path=True,
                preconditions=[],
                postconditions=["Search results visible"],
            )

        # Pattern: Navigation flow (2+ navigation transitions across different pages)
        unique_urls = set(urls)
        nav_transitions = sum(1 for t in segment if t.transition_type == "navigation")
        if nav_transitions >= 2 and len(unique_urls) >= 3:
            return FlowRecord(
                name=f"Navigation: {segment[0].before_page_type or 'page'} to {segment[-1].after_page_type or 'page'} (inferred)",
                category="navigation",
                steps=steps,
                start_url=start_url,
                end_url=end_url,
                outcome=f"Navigated through {len(unique_urls)} pages",
                is_success_path=True,
                preconditions=[],
                postconditions=[],
            )

        # Pattern: Generic interaction flow (fallback for 3+ diverse actions)
        if len(segment) >= 3 and len(set(actions)) >= 2:
            return FlowRecord(
                name=f"User Interaction: {segment[0].before_page_type or 'page'} (inferred)",
                category="navigation",
                steps=steps,
                start_url=start_url,
                end_url=end_url,
                outcome=f"Completed {len(segment)} interactions",
                is_success_path=True,
                preconditions=[],
                postconditions=[],
            )

        return None

    def _save_results(self, result: ExplorationResult, session_dir: Path):
        """Save exploration results to files."""

        # Save transitions
        transitions_data = []
        for t in result.transitions:
            transitions_data.append(
                {
                    "sequence": t.sequence,
                    "action": {"type": t.action_type, "element": t.action_element, "value": t.action_value},
                    "before": {"url": t.before_url, "pageType": t.before_page_type, "keyElements": t.before_elements},
                    "after": {"url": t.after_url, "pageType": t.after_page_type, "keyElements": t.after_elements},
                    "transitionType": t.transition_type,
                    "apiCalls": t.api_calls,
                    "changes": t.changes_description,
                }
            )
        (session_dir / "transitions.json").write_text(json.dumps(transitions_data, indent=2))

        # Save flows
        flows_data = []
        for f in result.flows:
            flows_data.append(
                {
                    "name": f.name,
                    "category": f.category,
                    "steps": f.steps,
                    "startUrl": f.start_url,
                    "endUrl": f.end_url,
                    "outcome": f.outcome,
                    "isSuccessPath": f.is_success_path,
                    "preconditions": f.preconditions,
                    "postconditions": f.postconditions,
                }
            )
        (session_dir / "flows.json").write_text(json.dumps(flows_data, indent=2))

        # Save API endpoints
        (session_dir / "api_endpoints.json").write_text(json.dumps(result.api_endpoints, indent=2))

        # Save issues
        issues_data = []
        for iss in result.issues:
            issues_data.append(
                {
                    "type": iss.issue_type,
                    "severity": iss.severity,
                    "url": iss.url,
                    "description": iss.description,
                    "element": iss.element,
                    "evidence": iss.evidence,
                }
            )
        (session_dir / "issues.json").write_text(json.dumps(issues_data, indent=2))

        # Save summary
        summary = {
            "sessionId": result.session_id,
            "entryUrl": result.entry_url,
            "status": result.status,
            "pagesDiscovered": result.pages_discovered,
            "flowsDiscovered": len(result.flows),
            "transitionsRecorded": len(result.transitions),
            "apiEndpointsFound": len(result.api_endpoints),
            "issuesFound": len(result.issues),
            "elementsDiscovered": result.elements_discovered,
            "durationSeconds": result.duration_seconds,
            "errorMessage": result.error_message,
        }
        (session_dir / "summary.json").write_text(json.dumps(summary, indent=2))


async def run_exploration(
    entry_url: str,
    project_id: str = "default",
    session_id: str | None = None,
    max_interactions: int = 50,
    max_depth: int = 10,
    strategy: str = "goal_directed",
    timeout_minutes: int = 30,
    credentials: dict[str, str] | None = None,
    login_url: str | None = None,
    exclude_patterns: list[str] | None = None,
    focus_areas: list[str] | None = None,
    additional_instructions: str | None = None,
) -> ExplorationResult:
    """
    Convenience function to run an exploration.

    Args:
        entry_url: URL to start exploration from
        project_id: Project ID for isolation
        session_id: Optional session ID
        max_interactions: Maximum number of interactions
        max_depth: Maximum navigation depth
        strategy: Exploration strategy (goal_directed, breadth_first, depth_first)
        timeout_minutes: Maximum exploration time
        credentials: Login credentials (dict with username, password, username_var, password_var)
        login_url: Login page URL
        exclude_patterns: URL patterns to skip
        focus_areas: Areas to prioritize

    Returns:
        ExplorationResult with all discovered data
    """
    config = ExplorationConfig(
        entry_url=entry_url,
        max_interactions=max_interactions,
        max_depth=max_depth,
        strategy=strategy,
        timeout_minutes=timeout_minutes,
        credentials=credentials,
        login_url=login_url,
        exclude_patterns=exclude_patterns or [],
        focus_areas=focus_areas or [],
        additional_instructions=additional_instructions,
    )

    explorer = AppExplorer(project_id=project_id)
    return await explorer.explore(config, session_id)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI-Powered App Exploration")
    parser.add_argument("url", help="Entry URL to explore")
    parser.add_argument("--project", default="default", help="Project ID")
    parser.add_argument("--session-id", help="Session ID (auto-generated if not provided)")
    parser.add_argument("--max-interactions", type=int, default=50, help="Maximum interactions")
    parser.add_argument("--max-depth", type=int, default=10, help="Maximum navigation depth")
    parser.add_argument(
        "--strategy",
        choices=["goal_directed", "breadth_first", "depth_first", "api_focused"],
        default="goal_directed",
        help="Exploration strategy",
    )
    parser.add_argument("--timeout", type=int, default=30, help="Timeout in minutes")
    parser.add_argument("--login-url", help="Login page URL if different from entry")
    parser.add_argument("--exclude", action="append", default=[], help="URL patterns to exclude")
    parser.add_argument("--focus", action="append", default=[], help="Areas to prioritize")

    args = parser.parse_args()

    # Check for credentials in environment
    credentials = None
    if os.environ.get("LOGIN_USERNAME") or os.environ.get("LOGIN_EMAIL"):
        username_var = "LOGIN_EMAIL" if os.environ.get("LOGIN_EMAIL") else "LOGIN_USERNAME"
        password_var = "LOGIN_PASSWORD"
        credentials = {
            "username": os.environ.get(username_var, ""),
            "password": os.environ.get(password_var, ""),
            "username_var": username_var,
            "password_var": password_var,
        }

    async def main():
        result = await run_exploration(
            entry_url=args.url,
            project_id=args.project,
            session_id=args.session_id,
            max_interactions=args.max_interactions,
            max_depth=args.max_depth,
            strategy=args.strategy,
            timeout_minutes=args.timeout,
            credentials=credentials,
            login_url=args.login_url,
            exclude_patterns=args.exclude,
            focus_areas=args.focus,
        )

        logger.info(f"Exploration Result: {result.status}")
        if result.error_message:
            logger.error(f"Error: {result.error_message}")

    try:
        from orchestrator.logging_config import setup_logging

        setup_logging()
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exploration stopped by user")
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass
        else:
            raise
