import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestrator.memory.manager import get_memory_manager

# Import using absolute path (sys.path is set in base_agent.py)
from orchestrator.utils.json_utils import extract_json_from_markdown

from .base_agent import CLAUDE_AUTH_FAILURE_MESSAGE, BaseAgent
from .explorer_result_synthesizer import (
    ExplorerResultSynthesizer,
    parse_event_records,
    read_event_log,
    synthesize_browser_events_from_tool_calls,
    write_event_log,
)


@dataclass
class Observation:
    """A single observation during exploration."""

    step_number: int
    action: str
    target: str
    outcome: str
    timestamp: float
    screenshot_path: str | None = None
    console_errors: list[str] = field(default_factory=list)
    interest_score: float = 0.0
    is_new_discovery: bool = False


@dataclass
class ExplorationState:
    """Tracks exploration state to avoid loops."""

    visited_urls: set[str] = field(default_factory=set)
    visited_elements: dict[str, set[str]] = field(default_factory=dict)  # url -> element IDs
    current_flow: list[dict] = field(default_factory=list)
    completed_flows: list[dict] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    last_new_discovery_time: float = 0
    steps_since_last_discovery: int = 0
    total_steps: int = 0
    start_time: float = 0


@dataclass
class CoverageGoals:
    """Tracks coverage goals during exploration."""

    navigation_explored: bool = False
    forms_interacted: int = 0
    flows_discovered: int = 0
    pages_visited: int = 0
    errors_found: int = 0
    unique_elements_found: int = 0

    def coverage_score(self) -> float:
        """Calculate overall coverage score (0-1)."""
        score = 0.0
        if self.navigation_explored:
            score += 0.2
        score += min(self.forms_interacted / 5, 0.2)  # Up to 0.2 for forms
        score += min(self.flows_discovered / 3, 0.3)  # Up to 0.3 for flows
        score += min(self.pages_visited / 10, 0.2)  # Up to 0.2 for pages
        score += min(self.errors_found / 3, 0.1)  # Up to 0.1 for errors
        return min(score, 1.0)


class ExploratoryAgent(BaseAgent):
    """
    Enhanced E2E Exploratory Testing Agent.

    Features:
    - State tracking to avoid loops
    - Coverage goals for guided exploration
    - Observation capture with interest scoring
    - Smart termination (time + diminishing returns)
    - Auth support (credentials, session, none)
    - Test data integration
    """

    def __init__(self):
        super().__init__()
        self.state: ExplorationState | None = None
        self.coverage: CoverageGoals | None = None

    async def run(self, config: dict[str, Any]) -> dict[str, Any]:
        """Run exploratory testing."""
        url = config.get("url")
        instructions = config.get("instructions", "")
        time_limit_minutes = config.get("time_limit_minutes", 15)
        auth_config = config.get("auth") or {"type": "none"}
        test_data = config.get("test_data") or {}
        focus_areas = config.get("focus_areas") or []
        excluded_patterns = config.get("excluded_patterns") or []
        browser_memory_context = config.get("browser_memory_context") or ""
        advanced_tools = bool(config.get("advanced_tools") or config.get("record_video") or config.get("capture_video"))

        # Initialize state and coverage
        self.state = ExplorationState(start_time=time.time())
        self.coverage = CoverageGoals()

        print(f"🕵️‍♂️ Starting Enhanced Exploratory Agent on {url}")
        print(f"   Time limit: {time_limit_minutes} minutes")
        print(f"   Auth type: {auth_config.get('type', 'none')}")
        print(f"   Focus areas: {focus_areas if focus_areas else 'All'}")

        # Build the enhanced prompt
        prompt = self._build_exploration_prompt(
            url=url,
            instructions=instructions,
            time_limit_minutes=time_limit_minutes,
            auth_config=auth_config,
            test_data=test_data,
            focus_areas=focus_areas,
            excluded_patterns=excluded_patterns,
            browser_memory_context=browser_memory_context,
            advanced_tools=advanced_tools,
        )
        if self.owner_type == "agent_run" and self.owner_id:
            try:
                from orchestrator.services.agent_trace import ensure_trace_snapshot

                ensure_trace_snapshot(
                    run_id=self.owner_id,
                    prompt=prompt,
                    context=browser_memory_context or None,
                    runtime=str(config.get("runtime") or "claude_sdk"),
                    model=config.get("model"),
                    model_tier=config.get("model_tier"),
                    allowed_tools=config.get("allowed_tools") or self.allowed_tools,
                    runtime_diagnostics={
                        "agent_type": "exploratory",
                        "path": "classic",
                    },
                    test_data_refs=config.get("test_data_refs") if isinstance(config.get("test_data_refs"), list) else [],
                )
            except Exception as exc:
                print(f"⚠️ Trace prompt snapshot skipped: {exc}")

        # Execute exploration with timeout
        # Add 30 second buffer for processing time
        timeout_seconds = (time_limit_minutes * 60) + 30
        print(f"   Timeout: {timeout_seconds} seconds ({time_limit_minutes}min + 30s buffer)")

        try:
            result = await self._query_agent(prompt, timeout_seconds=timeout_seconds)
            print(f"   Agent returned result type: {type(result)}")
            print(f"   Result preview: {str(result)[:500]}...")
        except RuntimeError as e:
            if self._is_runtime_auth_failure_text(str(e)):
                return self._runtime_auth_failure_result(config, str(e))
            raise
        except asyncio.TimeoutError:
            # Return partial results on timeout - but include what we have!
            print("⏱️ Timeout reached, but preserving partial results...")

            # Try to extract whatever result we have so far
            elapsed = time.time() - self.state.start_time
            print(f"   Steps taken: {self.state.total_steps}")
            print(f"   Observations: {len(self.state.observations)}")
            print(f"   Flows completed: {len(self.state.completed_flows)}")

            processed = self._process_results(
                {
                    "summary": f"Exploration timed out after {time_limit_minutes} minutes",
                    "termination_reason": "timeout",
                    "timeout": True,
                    "partial_results": True,
                },
                config,
            )
            processed.update(
                {
                    "elapsed_time_seconds": round(elapsed, 2),
                    "elapsed_time_minutes": round(elapsed / 60, 2),
                    "termination_reason": "timeout",
                    "timeout": True,
                    "partial_results": True,
                }
            )
            return processed

        # Check if result is a partial timeout response
        if isinstance(result, str) and result.startswith("__TIMEOUT_PARTIAL__\n"):
            print("⏱️ Processing partial content from timeout...")
            # Extract the actual content
            partial_content = result.replace("__TIMEOUT_PARTIAL__\n", "", 1)
            print(f"   Partial content length: {len(partial_content)} characters")
            print(f"   Preview: {partial_content[:300]}...")

            # Try to parse JSON from the partial content
            try:
                parsed = extract_json_from_markdown(partial_content)
                if parsed and isinstance(parsed, dict):
                    print("   ✅ Successfully parsed JSON from partial content!")
                    # Mark as timeout/partial but use the parsed data
                    parsed["timeout"] = True
                    parsed["partial_results"] = True
                    parsed["termination_reason"] = "timeout"
                    if "summary" not in parsed:
                        parsed["summary"] = (
                            f"Exploration timed out after {time_limit_minutes} minutes (partial results recovered)"
                        )
                    # Process and return normally
                    return self._process_results(partial_content, config)
            except Exception as e:
                print(f"   ⚠️ Could not parse JSON from partial content: {e}")

            # If parsing failed, fall through to normal processing with the raw partial content
            result = partial_content

        # Process and return results
        return self._process_results(result, config)

    @staticmethod
    def _is_runtime_auth_failure_text(value: Any) -> bool:
        text = str(value or "").lower()
        return (
            "not logged in" in text
            and "please run /login" in text
        ) or CLAUDE_AUTH_FAILURE_MESSAGE.lower() in text

    def _runtime_auth_failure_result(self, config: dict[str, Any], raw_output: Any = "") -> dict[str, Any]:
        elapsed = time.time() - self.state.start_time if self.state else 0.0
        raw_preview = str(raw_output or "")[:500]
        return {
            "status": "failed",
            "exploration_failed": True,
            "failure_reason": "runtime_auth_failed",
            "summary": CLAUDE_AUTH_FAILURE_MESSAGE,
            "error": CLAUDE_AUTH_FAILURE_MESSAGE,
            "raw_output_preview": raw_preview,
            "parsing_failed": False,
            "elapsed_time_seconds": round(elapsed, 2),
            "elapsed_time_minutes": round(elapsed / 60, 2),
            "config": {
                "url": config.get("url"),
                "time_limit_minutes": config.get("time_limit_minutes", 15),
                "auth_type": (config.get("auth") or {}).get("type", "none"),
                "project_id": config.get("project_id"),
            },
            "coverage": {
                "navigation_explored": False,
                "forms_interacted": 0,
                "flows_discovered": 0,
                "inferred_opportunities": 0,
                "pages_visited": 0,
                "errors_found": 0,
                "blockers_found": 0,
                "coverage_score": 0.0,
            },
            "action_trace": [],
            "inferred_flows": [],
            "blockers": [],
            "issues": [],
            "pages_visited": [],
            "screenshots": [],
            "event_counts": {},
            "meaningful_interactions": 0,
            "discovered_flow_summaries": [],
            "total_flows_discovered": 0,
        }

    def _build_exploration_prompt(
        self,
        url: str,
        instructions: str,
        time_limit_minutes: int,
        auth_config: dict[str, Any],
        test_data: dict[str, Any],
        focus_areas: list[str],
        excluded_patterns: list[str],
        browser_memory_context: str = "",
        advanced_tools: bool = False,
    ) -> str:
        """Build the enhanced exploration prompt."""

        # Build auth section
        auth_section = ""
        if auth_config.get("type") == "credentials":
            creds = auth_config.get("credentials", {})
            login_url = auth_config.get("login_url", "/login")
            # Resolve relative login URL against base URL
            if login_url and not login_url.startswith("http"):
                from urllib.parse import urlparse

                parsed = urlparse(url)
                login_url = f"{parsed.scheme}://{parsed.netloc}{login_url}"
            auth_section = f"""
AUTHENTICATION (REQUIRED - DO THIS FIRST):
1. Navigate to: {login_url}
2. Find the username/email field and enter: {creds.get("username", "")}
3. Find the password field and enter: {creds.get("password", "")}
4. Click the login/sign in/submit button
5. Wait for the page to load after login
6. Verify you are logged in (look for user menu, avatar, logout button, or dashboard)

IMPORTANT: Do NOT proceed with exploration until login is successful.
If login fails, document the error and try alternative login methods if visible.
"""
        elif auth_config.get("type") == "session":
            auth_section = """
AUTHENTICATION:
- Session is already authenticated (cookies loaded)
- Proceed directly with exploration
"""

        # Build test data section
        test_data_section = ""
        if test_data:
            test_data_section = "\nTEST DATA TO USE:\n"
            for key, values in test_data.items():
                if isinstance(values, list):
                    test_data_section += f"- {key}: {', '.join(str(v) for v in values)}\n"
                else:
                    test_data_section += f"- {key}: {values}\n"

        # Build focus areas section
        focus_section = ""
        if focus_areas:
            focus_section = "\nPRIORITY AREAS (explore these first):\n"
            focus_section += "\n".join(f"- {area}" for area in focus_areas)

        # Build exclusion section
        exclusion_section = ""
        if excluded_patterns:
            exclusion_section = "\nURL PATTERNS TO AVOID:\n"
            exclusion_section += "\n".join(f"- DO NOT visit: {pattern}" for pattern in excluded_patterns)

        memory_section = ""
        if browser_memory_context:
            memory_section = f"""
CONTEXT-ENGINEERED BROWSER MEMORY:
{browser_memory_context}

BROWSER MEMORY RULES:
1. Stored memory is advisory. Live browser_snapshot output and user instructions are authoritative.
2. Start with a fresh snapshot after navigation, then compare the live page to any remembered state before acting.
3. Prefer frontier work only when the live URL, role/name, and locator still match.
4. Validate remembered locators before use; if a locator is stale, rediscover from the live snapshot and continue.
5. Avoid high-risk actions such as delete/reset/logout/cancel unless explicitly required by the user.
6. Record stale, skipped, or completed frontier work in the action_trace outcome.
"""

        video_section = ""
        if advanced_tools:
            video_section = """
OPTIONAL VIDEO RECORDING:
1. If video tools are available, call browser_start_video with filename "exploration.webm" before navigation.
2. Add browser_video_chapter markers only for major phases.
3. Call browser_stop_video before the final summary.
4. If video tools fail or are unavailable, continue without video.
"""

        return f"""You are an Enhanced E2E Exploration Agent with a {time_limit_minutes}-minute budget.

OUTPUT CONTRACT:
Your result has two parts and no conversational prose.
1. Exploration event records as line-delimited JSON. Each event must be one complete JSON object on one line.
2. A final small JSON summary in a ```json fenced block.

Allowed event_type values:
- page_observed
- action_attempted
- action_result
- flow_candidate
- network_observed
- issue_observed
- blocker

Event requirements:
- Every event must include "id" and "event_type".
- For page_observed, include url, title or summary, and screenshot_path when a screenshot was taken.
- For action_attempted, include action and target.
- For action_result, include action, target, success, outcome, and url when known.
- For flow_candidate, include title, step_event_ids, evidence_event_ids, entry_point, exit_point, edge_cases, and test_ideas.
- A completed flow_candidate must reference action_result/page_observed ids for every step. Do not invent event ids.
- Emit page_observed and action_result records before any flow_candidate that cites them.
- If you have not emitted the supporting page_observed/action_result ids, omit flow_candidate entirely and describe the gap in the final summary.
- Use blocker when authentication, navigation, permissions, app errors, or tool failures prevent useful exploration.

Example event lines:
{{"id":"evt_001","event_type":"page_observed","url":"https://app.example/","title":"Home","summary":"Landing page with sign-in link","screenshot_path":"live-step-001.png"}}
{{"id":"evt_002","event_type":"action_result","action":"click","target":"Sign in","success":true,"outcome":"Login form opened","url":"https://app.example/login"}}
{{"id":"evt_003","event_type":"flow_candidate","title":"Open sign-in form","step_event_ids":["evt_001","evt_002"],"evidence_event_ids":["evt_001","evt_002"],"entry_point":"https://app.example/","exit_point":"https://app.example/login","edge_cases":[],"test_ideas":["Verify sign-in opens from the home page."]}}

FINAL SUMMARY JSON FORMAT:
```json
{{
  "summary": "One sentence overview (max 150 chars)",
  "coverage_notes": "Brief note on what was and was not covered",
  "blocker_status": "none|blocked|partial",
  "event_counts": {{"page_observed": 0, "action_result": 0, "flow_candidate": 0}},
  "termination_reason": "completed|blocked|time_limit_reached|no_new_discoveries"
}}
```
{video_section}

LIVE VIEW SCREENSHOTS:
1. Save screenshots after initial navigation, after authentication, at flow boundaries, and on blockers.
2. Use browser_take_screenshot with filenames like "live-step-001.png", "live-step-004.png".
3. Do not take screenshots of pages that visibly contain passwords or secret tokens.
4. If screenshot capture fails, emit an issue_observed event and continue.

TARGET URL: {url}
{auth_section}
INSTRUCTIONS: {instructions if instructions else "Explore the application thoroughly."}
{memory_section}

EXPLORATION STRATEGY:
1. DISCOVER: Start by exploring the site structure and emit page_observed events.
2. IDENTIFY: User flows from observed pages and actions only.
3. EXPLORE: For each high-value flow, sample one happy path and one safe edge case.
4. AVOID LOOPS: Track visited pages and elements; do not revisit same states.
5. CAPTURE: Emit compact evidence events as you go.

COVERAGE GOALS:
- Minimum useful result: 3 observed pages or 1 observed flow, unless blocked.
- Prefer reliable observed flows over exhaustive crawling.
- Find and document blockers or error states.
{focus_section}
{test_data_section}
{exclusion_section}

SMART TERMINATION:
You should stop exploring when:
- Time limit is reached ({time_limit_minutes} minutes)
- 5 consecutive meaningful interactions yield no new discoveries
- You have at least 3 observed pages and 1 observed flow
- A blocker prevents further progress

IMPORTANT EXPLORATION RULES:
1. Focus on MULTI-PAGE flows (not single page tests)
2. Edge cases must be safe: no destructive submits, purchases, deletes, or external sends unless explicitly requested
3. Track every meaningful action with action_attempted and action_result events
4. Be thorough but efficient - don't waste time on repetitive actions
5. CRITICAL: BROWSER DIALOG HANDLING
   - When a "Leave site?", unsaved changes, or beforeunload dialog appears, use browser_handle_dialog with accept: true immediately to accept Leave and continue navigation
   - Use browser_handle_dialog tool immediately for alerts/confirms/prompts
   - After handling any dialog, call browser_snapshot or browser_take_screenshot to verify page state
   - Preserve draft data only if the user explicitly requested it

CONSTRAINTS:
- Event lines: compact, no HTML dumps, max 300 chars per string
- Flow candidates: include only observed or page-evidence-backed flows
- Do not put discovered_flows or action_trace in the final summary JSON

Begin exploration now:
Step 1: {"Clear cookies/localStorage if tools allow and start fresh" if auth_config.get("type") != "session" else "Use the pre-authenticated session"}
Step 2: {"Navigate to login and authenticate" if auth_config.get("type") == "credentials" else f"Navigate to {url} and observe the first page"}
Step 3: Emit page_observed for the first loaded page and save the first screenshot
Step 4: Explore navigation and main features, emitting events after each observation/action
Step 5: Emit flow_candidate records only after evidence event ids exist
Step 6: Return the final summary JSON when done"""

    def _process_results(self, result: Any, config: dict[str, Any]) -> dict[str, Any]:
        """Process exploration results, save full flows to file, and persist to memory."""
        elapsed = time.time() - self.state.start_time
        run_id = config.get("run_id")
        run_dir = self._run_dir(run_id) if run_id else None
        event_log_path = run_dir / "exploration_events.jsonl" if run_dir else None
        runtime_tool_calls = config.get("_runtime_tool_calls") or []
        runtime_diagnostics = {
            **getattr(self, "last_agent_diagnostics", {}),
            **(config.get("_runtime_diagnostics") or {}),
        }
        if not runtime_tool_calls and isinstance(runtime_diagnostics.get("tool_call_records"), list):
            runtime_tool_calls = runtime_diagnostics.get("tool_call_records") or []

        memory_manager = None
        memory_enabled = os.getenv("MEMORY_ENABLED", "true").lower() == "true"
        if memory_enabled and os.getenv("OPENAI_API_KEY"):
            try:
                memory_manager = get_memory_manager(project_id=config.get("project_id"))
            except Exception as e:
                print(f"⚠️ Memory unavailable, continuing without persistence: {e}")

        parsed_data: dict[str, Any] = result if isinstance(result, dict) else {}
        parsing_failed = False
        error_details = None
        raw_output_preview = ""
        zero_evidence_failure = False

        if self._is_runtime_auth_failure_text(result) or parsed_data.get("failure_reason") == "runtime_auth_failed":
            return self._runtime_auth_failure_result(config, result)

        if not isinstance(result, dict):
            try:
                parsed = extract_json_from_markdown(result)
                if not parsed or not isinstance(parsed, dict):
                    raise ValueError("Extracted result is not a dictionary")
                parsed_data = parsed
            except Exception as e:
                parsing_failed = True
                error_details = str(e)
                raw_output_preview = str(result)[:500]
                print(f"⚠️ Final summary parsing failed; recovering from event evidence if available: {e}")

        event_records: list[dict[str, Any]] = []
        if event_log_path:
            event_records.extend(read_event_log(event_log_path))
        event_records.extend(
            synthesize_browser_events_from_tool_calls(
                runtime_tool_calls,
                target_url=config.get("url"),
                start_index=len(event_records) + 1,
            )
        )
        event_records.extend(parse_event_records(result))
        event_records.extend(parse_event_records(parsed_data))

        # Merge by event id while preserving first-seen order. This lets timeout
        # recovery combine an existing file with partial model output.
        merged_events: list[dict[str, Any]] = []
        seen_event_ids: set[str] = set()
        for index, event in enumerate(event_records, start=1):
            event_id = str(event.get("id") or event.get("event_id") or f"event_{index:03d}")
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
            item = dict(event)
            item["id"] = event_id
            merged_events.append(item)

        if event_log_path and merged_events:
            normalized_events = ExplorerResultSynthesizer(merged_events, config.get("url")).normalized_events()
            write_event_log(event_log_path, normalized_events)

        synthesis = ExplorerResultSynthesizer(merged_events, config.get("url")).synthesize()
        diagnostics = ExplorerResultSynthesizer(merged_events, config.get("url")).diagnostics(
            tool_calls=runtime_tool_calls,
            extra=runtime_diagnostics,
            synthesis=synthesis,
        )
        action_trace = synthesis["action_trace"]
        discovered_flows = synthesis["discovered_flows"]
        inferred_flows = synthesis["inferred_flows"]
        unsupported_flow_candidates = synthesis["unsupported_flow_candidates"]
        coverage = synthesis["coverage"]

        if not synthesis["events"]:
            zero_evidence_failure = True
            coverage = {
                "navigation_explored": False,
                "forms_interacted": 0,
                "flows_discovered": 0,
                "inferred_opportunities": 0,
                "pages_visited": 0,
                "errors_found": 0,
                "blockers_found": 0,
                "coverage_score": 0.0,
            }

        contract_warning = self._contract_warning(result, parsed_data, discovered_flows, synthesis["events"], diagnostics)

        # --- PERSISTENCE TO MEMORY ---
        if zero_evidence_failure:
            print("⚠️ Memory persistence skipped because exploration produced no recoverable evidence")
        elif memory_manager is None:
            print("ℹ️ Memory persistence skipped (MEMORY_ENABLED=false or OPENAI_API_KEY not set)")
        else:
            try:
                print(f"💾 Starting persistence for project: {config.get('project_id')}")

                # 1. Store discovered elements AND Pages
                try:
                    # We need to track the current page to link elements to it
                    current_page_url = config.get("url")  # Start with initial URL
                    current_page_id = hashlib.md5(current_page_url.encode()).hexdigest()

                    # Ensure start page exists
                    memory_manager.graph_store.add_page(current_page_id, current_page_url)

                    for _action_idx, action in enumerate(action_trace):
                        act_type = action.get("action", "").lower()
                        target = action.get("target", "")

                        if not target or target == "unknown":
                            continue

                        if act_type == "navigate":
                            # This action IS a page visit
                            new_page_url = target
                            new_page_id = hashlib.md5(new_page_url.encode()).hexdigest()
                            memory_manager.graph_store.add_page(new_page_id, new_page_url)

                            memory_manager.graph_store.add_navigation(
                                from_page=current_page_id,
                                to_page=new_page_id,
                                trigger="navigation",
                                metadata={"step": action.get("step")},
                            )

                            current_page_url = new_page_url
                            current_page_id = new_page_id

                        elif act_type in ["click", "fill", "select", "check", "uncheck"]:
                            # Create a pseudo-selector
                            selector = {"type": "text_or_selector", "value": target}

                            element_id = memory_manager.store_discovered_element(
                                url=current_page_url,
                                element_type="interactive_element",
                                selector=selector,
                                text=target,
                                page_id=current_page_id,
                            )

                            memory_manager.record_element_tested(
                                element_id, test_name=f"Exploratory Run {run_id or 'Manual'}"
                            )

                    # 1b. Robustly store ALL pages mentioned in discovered flows
                    # This catches pages that were visited but didn't have explicit "Navigate" actions in the trace
                    for flow in discovered_flows:
                        pages = flow.get("pages", [])
                        for page_url in pages:
                            if page_url and len(page_url) > 1:
                                pid = hashlib.md5(page_url.encode()).hexdigest()
                                memory_manager.graph_store.add_page(pid, page_url)
                except Exception as e:
                    print(f"⚠️ Error storing elements/pages: {e}")

                # 2. Store Discovered Flows
                try:
                    for flow in discovered_flows:
                        flow_pages = flow.get("pages", [])

                        memory_manager.store_discovered_flow(
                            title=flow.get("title", "Untitled Flow"),
                            steps=action_trace,
                            happy_path=flow.get("happy_path"),
                            pages=flow_pages,
                            metadata=flow,
                        )

                        memory_manager.store_test_idea(
                            description=f"Automated Flow: {flow.get('title')}", category="discovered_flow", metadata=flow
                        )
                except Exception as e:
                    print(f"⚠️ Error storing flows: {e}")

                # 3. Store Test Patterns
                try:
                    test_name = f"Exploratory Test: {config.get('project_id')}"
                    for action in action_trace:
                        outcome = action.get("outcome", "").lower()
                        if outcome in ["failed", "error"]:
                            continue

                        target = action.get("target", "")
                        if not target or len(target) < 2:
                            continue

                        memory_manager.store_test_pattern(
                            test_name=test_name,
                            step_number=action.get("step", 0),
                            action=action.get("action", ""),
                            target=target,
                            selector={"type": "exploratory", "value": target},
                            success=True,
                            duration_ms=0,
                        )
                except Exception as e:
                    print(f"⚠️ Error storing patterns: {e}")

            except Exception as mem_err:
                print(f"⚠️ Critical Memory persistence failure: {mem_err}")
            finally:
                try:
                    memory_manager.graph_store.save()
                    print(f"💾 Persisted graph data: {len(action_trace)} actions, {len(discovered_flows)} flows")
                except Exception as save_err:
                    print(f"❌ Failed to save graph to disk: {save_err}")

        # --- Final Response Construction ---
        response_data = {
            key: value
            for key, value in (parsed_data if isinstance(parsed_data, dict) else {}).items()
            if key not in {"discovered_flows", "action_trace", "events", "exploration_events", "coverage"}
        }

        response_data.update(
            {
                "elapsed_time_seconds": round(elapsed, 2),
                "elapsed_time_minutes": round(elapsed / 60, 2),
                "config": {
                    "url": config.get("url"),
                    "time_limit_minutes": config.get("time_limit_minutes", 15),
                    "auth_type": (config.get("auth") or {}).get("type", "none"),
                    "project_id": config.get("project_id"),  # Propagate project isolation
                },
                "coverage": coverage,
                "action_trace": action_trace,
                "inferred_flows": inferred_flows,
                "unsupported_flow_candidates": unsupported_flow_candidates,
                "blockers": synthesis["blockers"],
                "issues": synthesis["issues"],
                "pages_visited": synthesis["pages_visited"],
                "screenshots": synthesis["screenshots"],
                "event_counts": synthesis["event_counts"],
                "meaningful_interactions": synthesis["meaningful_interactions"],
                "event_log_path": str(event_log_path) if event_log_path else None,
                "parsing_failed": parsing_failed,
                "diagnostics": diagnostics,
            }
        )

        if contract_warning:
            response_data["contract_warning"] = contract_warning
            if not discovered_flows:
                response_data["exploration_status"] = "contract_violation"

        if parsing_failed:
            response_data.update(
                {
                    "summary": (
                        "Exploration failed: result parsing failed and no event evidence was recovered."
                        if zero_evidence_failure
                        else "Exploration completed. Final summary parsing failed, but event evidence was recovered."
                    ),
                    "preview": f"{raw_output_preview[:200]}..." if raw_output_preview else "",
                    "raw_output_preview": raw_output_preview,
                    "error_details": error_details,
                    "parsing_failed": True,
                }
            )
            if zero_evidence_failure:
                response_data.update(
                    {
                        "status": "failed",
                        "exploration_failed": True,
                        "failure_reason": "zero_evidence_parse_fallback",
                    }
                )
        elif zero_evidence_failure:
            response_data.update(
                {
                    "summary": response_data.get("summary")
                    or "Exploration failed: no event evidence was recovered.",
                    "status": "failed",
                    "exploration_failed": True,
                    "failure_reason": "zero_evidence",
                }
            )

        if not zero_evidence_failure and not discovered_flows:
            response_data.setdefault(
                "summary",
                "Exploration completed with evidence, but no completed flows were observed.",
            )
            response_data["exploration_status"] = "blocked" if synthesis["blockers"] else "no_flows_observed"

        # Save flows to file and generate summaries
        if run_id:
            flow_summaries = self._save_flows_and_generate_summaries(
                discovered_flows,
                run_id,
                inferred_flows=inferred_flows,
                events=synthesis["events"],
                blockers=synthesis["blockers"],
                coverage=coverage,
            )
            response_data["discovered_flow_summaries"] = flow_summaries
            response_data["total_flows_discovered"] = len(discovered_flows)
            if "discovered_flows" in response_data:
                del response_data["discovered_flows"]
        else:
            response_data["discovered_flow_summaries"] = [
                self._create_flow_summary(flow, i) for i, flow in enumerate(discovered_flows)
            ]
            response_data["total_flows_discovered"] = len(discovered_flows)

        return response_data

    def _contract_warning(
        self,
        raw_result: Any,
        parsed_data: dict[str, Any],
        discovered_flows: list[dict[str, Any]],
        events: list[dict[str, Any]],
        diagnostics: dict[str, Any],
    ) -> str | None:
        if discovered_flows:
            return None
        text = ""
        if isinstance(raw_result, str):
            text = raw_result
        elif isinstance(parsed_data, dict):
            text = json.dumps(parsed_data, default=str)
        claims_flows = bool(
            text
            and (
                re.search(r"\b(discovered|documented|found|identified|covered)\b.{0,80}\bflows?\b", text, re.I)
                or re.search(r"\b\d+\s+flows?\b", text, re.I)
            )
        )
        if claims_flows:
            return (
                "The model output claimed flow coverage, but no structured evidence-backed flow summaries were "
                "created. Prose claims were not converted into flows."
            )
        if int(diagnostics.get("browser_tool_calls") or 0) > 0 and int(diagnostics.get("successful_browser_tool_calls") or 0) == 0:
            return "Browser tools were attempted, but none completed successfully."
        if events and not discovered_flows:
            return "Evidence was captured, but it did not contain both a page observation and a meaningful successful action."
        return None

    def _run_dir(self, run_id: str) -> Path:
        project_root = Path(__file__).parent.parent.parent
        return project_root / "runs" / run_id

    def _save_flows_and_generate_summaries(
        self,
        flows: list[dict],
        run_id: str,
        *,
        inferred_flows: list[dict] | None = None,
        events: list[dict] | None = None,
        blockers: list[dict] | None = None,
        coverage: dict[str, Any] | None = None,
    ) -> list[dict]:
        """Save full flows to file and return summaries."""
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        # Save full flows to JSON file
        flows_file = run_dir / "flows.json"
        with open(flows_file, "w") as f:
            json.dump(
                {
                    "flows": flows,
                    "inferred_flows": inferred_flows or [],
                    "events_count": len(events or []),
                    "blockers": blockers or [],
                    "coverage": coverage or {},
                },
                f,
                indent=2,
            )

        print(f"💾 Saved {len(flows)} flows to {flows_file}")

        # Generate summaries
        return [self._create_flow_summary(flow, i) for i, flow in enumerate(flows)]

    def _create_flow_summary(self, flow: dict, index: int) -> dict:
        """Create a summary from a full flow."""
        return {
            "id": flow.get("id", f"flow_{index + 1}"),
            "title": flow.get("title", f"Flow {index + 1}"),
            "pages": flow.get("pages", []),
            "steps_count": flow.get("steps_count", len(flow.get("pages", []))),
            "has_happy_path": bool(flow.get("happy_path")),
            "has_edge_cases": bool(flow.get("edge_cases") and len(flow.get("edge_cases", [])) > 0),
            "entry_point": flow.get("entry_point", ""),
            "exit_point": flow.get("exit_point", ""),
            "complexity": flow.get("complexity", "unknown"),
        }

    def _get_termination_reason(self, elapsed: float, time_limit_minutes: int) -> str:
        """Determine why exploration terminated."""
        time_limit_seconds = time_limit_minutes * 60

        if elapsed >= time_limit_seconds * 0.95:
            return "time_limit_reached"
        elif self.state.steps_since_last_discovery >= 5:
            return "no_new_discoveries"
        elif self.coverage.coverage_score() >= 0.8:
            return "coverage_goals_met"
        else:
            return "completed"


# Legacy compatibility - keep old max_steps interface working
async def run_legacy(config: dict[str, Any]) -> dict[str, Any]:
    """Legacy interface for backward compatibility."""
    # Convert old max_steps config to new time-based config
    if "max_steps" in config:
        # Approximate: 10 steps ≈ 2 minutes
        time_limit = max(2, config["max_steps"] // 5)
        config["time_limit_minutes"] = time_limit

    agent = ExploratoryAgent()
    return await agent.run(config)
