import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory.manager import get_memory_manager

# Import using absolute path (sys.path is set in base_agent.py)
from utils.json_utils import extract_json_from_markdown

from .base_agent import BaseAgent


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
        )

        # Execute exploration with timeout
        # Add 30 second buffer for processing time
        timeout_seconds = (time_limit_minutes * 60) + 30
        print(f"   Timeout: {timeout_seconds} seconds ({time_limit_minutes}min + 30s buffer)")

        try:
            result = await self._query_agent(prompt, timeout_seconds=timeout_seconds)
            print(f"   Agent returned result type: {type(result)}")
            print(f"   Result preview: {str(result)[:500]}...")
        except asyncio.TimeoutError:
            # Return partial results on timeout - but include what we have!
            print("⏱️ Timeout reached, but preserving partial results...")

            # Try to extract whatever result we have so far
            elapsed = time.time() - self.state.start_time
            print(f"   Steps taken: {self.state.total_steps}")
            print(f"   Observations: {len(self.state.observations)}")
            print(f"   Flows completed: {len(self.state.completed_flows)}")

            return {
                "summary": f"Exploration timed out after {time_limit_minutes} minutes",
                "elapsed_time_seconds": round(elapsed, 2),
                "elapsed_time_minutes": round(elapsed / 60, 2),
                "termination_reason": "timeout",
                "discovered_flows": self.state.completed_flows,
                "action_trace": [
                    {
                        "step": obs.step_number,
                        "action": obs.action,
                        "target": obs.target,
                        "outcome": obs.outcome,
                        "is_new_discovery": obs.is_new_discovery,
                    }
                    for obs in self.state.observations
                ],
                "coverage": {"coverage_score": self.coverage.coverage_score(), **self.coverage.__dict__},
                "timeout": True,
                "partial_results": True,
            }

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
                    return self._process_results(parsed, config)
            except Exception as e:
                print(f"   ⚠️ Could not parse JSON from partial content: {e}")

            # If parsing failed, fall through to normal processing with the raw partial content
            result = partial_content

        # Process and return results
        return self._process_results(result, config)

    def _build_exploration_prompt(
        self,
        url: str,
        instructions: str,
        time_limit_minutes: int,
        auth_config: dict[str, Any],
        test_data: dict[str, Any],
        focus_areas: list[str],
        excluded_patterns: list[str],
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

        return f"""You are an Enhanced E2E Exploration Agent with a {time_limit_minutes}-minute budget.

CRITICAL OUTPUT INSTRUCTIONS:
You MUST return the result in strictly valid JSON format.
DO NOT include any conversational text, intro, or outro.
DO NOT use markdown formatting outside the JSON block.
Your ENTIRE response must be parseable as JSON.

REQUIRED JSON OUTPUT FORMAT:
```json
{{
  "summary": "One sentence overview (max 150 chars)",
  "discovered_flows": [
    {{
      "id": "flow_1",
      "title": "Flow Name (descriptive)",
      "pages": ["page1", "page2"],
      "steps_count": 5,
      "happy_path": "Complete happy path description",
      "edge_cases": ["case1", "case2"],
      "test_ideas": ["idea1", "idea2"],
      "entry_point": "/start-url",
      "exit_point": "/end-url",
      "complexity": "medium"
    }}
  ],
  "action_trace": [
    {{"step": 1, "action": "navigate", "target": "url", "outcome": "ok", "is_new_discovery": false}}
  ],
  "happy_paths_found": ["Flow1"],
  "edge_cases_found": ["case1"],
  "coverage": {{
    "navigation_explored": true,
    "forms_interacted": 2,
    "flows_discovered": 1,
    "pages_visited": 3,
    "errors_found": 0
  }},
  "total_actions": 5
}}
```

TARGET URL: {url}
{auth_section}
INSTRUCTIONS: {instructions if instructions else "Explore the application thoroughly."}

EXPLORATION STRATEGY:
1. DISCOVER: Start by exploring the site structure (navigation, main sections)
2. IDENTIFY: User flows (multi-step journeys like: browse → cart → checkout)
3. EXPLORE: Each flow with BOTH valid data AND edge cases
4. AVOID LOOPS: Track visited pages and elements, don't revisit same states
5. CAPTURE: Document all discoveries with clear action descriptions

COVERAGE GOALS (aim for these):
- Visit all navigation items
- Interact with all forms (submit valid + invalid data)
- Complete at least 3 end-to-end flows
- Visit 10+ unique pages
- Find and document any error states
{focus_section}
{test_data_section}
{exclusion_section}

SMART TERMINATION:
You should stop exploring when:
- Time limit is reached ({time_limit_minutes} minutes)
- 5 consecutive actions yield no new discoveries (diminishing returns)
- Coverage goals are met

IMPORTANT EXPLORATION RULES:
1. Focus on MULTI-PAGE flows (not single page tests)
2. For each flow, test:
   - HAPPY PATH: Complete the flow successfully
   - EDGE CASES: Empty fields, special chars, boundary values
3. Track every action for test spec generation
4. Be thorough but efficient - don't waste time on repetitive actions
5. CRITICAL: JAVASCRIPT ALERT HANDLING
   - Use browser_handle_dialog tool immediately for alerts/confirms/prompts
   - Accept alerts, test confirm/dismiss, handle prompts
   - Take snapshot after handling

CONSTRAINTS:
- action_trace: MAX 30 entries (significant actions only)
- discovered_flows: Include ALL complete flows
- String fields: MAX 300 chars
- NO string dumps or HTML content in JSON values

Begin exploration now:
Step 0: {"Clear ALL cookies and localStorage to ensure a fresh start" if auth_config.get("type") != "session" else "Load session data (Pre-authenticated)"}
Step 1: {"Navigate to login and authenticate" if auth_config.get("type") == "credentials" else f"Navigate to {url} and discover site structure"}
Step 2: Explore navigation and main features
Step 3: Identify and test user flows
Step 4: Return JSON summary when done"""

    def _process_results(self, result: Any, config: dict[str, Any]) -> dict[str, Any]:
        """Process exploration results, save full flows to file, and persist to memory."""
        elapsed = time.time() - self.state.start_time
        run_id = config.get("run_id")

        # Get memory manager for persistence
        memory_manager = get_memory_manager(project_id=config.get("project_id"))

        parsed_data = {}
        action_trace = []
        parsing_failed = False
        error_details = None

        try:
            parsed_data = extract_json_from_markdown(result)
            if not parsed_data or not isinstance(parsed_data, dict):
                raise ValueError("Extracted result is not a dictionary")

            # Extract action trace from parsed data if available
            action_trace = parsed_data.get("action_trace", [])

        except Exception as e:
            parsing_failed = True
            error_details = str(e)
            result_str = str(result)

            print(f"⚠️ Result parsing failed: {e}")

            # Enhanced Regex Fallback
            import re

            action_patterns = [
                r'(Navigate|Click|Fill|Select|Check|Uncheck|Assert|Hover|Drag|Visit|Go)\s+(?:to|on|in|with)?\s+["\']?([^"\':\n]+)["\']?',
                r"Step\s+\d+:\s*(?:I will |I am |)(\w+)\s+(.+?)(?:\n|$)",
                r"Action:\s*(\w+)\s*Target:\s*(.+?)(?:\n|$)",
                r"\[(\w+)\]\s+(.+?)(?:\n|$)",
                r'(Visiting|Opening)\s+["\']?([^"\':\n]+)["\']?',
            ]

            for pattern in action_patterns:
                matches = re.findall(pattern, result_str, re.IGNORECASE)
                for match in matches:  # No limit, capture all
                    if isinstance(match, tuple):
                        action = match[0] if len(match) > 0 else "unknown"
                        target = match[-1] if len(match) > 1 else match[0]
                    else:
                        action = "unknown"
                        target = match

                    # Clean up
                    action = action.strip().lower()
                    target = target.strip()

                    # Normalize "visiting/go/opening" to "navigate"
                    if action in ["visiting", "go", "opening", "visit"]:
                        action = "navigate"

                    # Remove common prepositions from start of target
                    for prep in ["to ", "on ", "in ", "with ", "into "]:
                        if target.lower().startswith(prep):
                            target = target[len(prep) :].strip()

                    # Filter out common false positives and long garbage
                    if action in ["the", "a", "an", "step", "note"] or len(target) < 2:
                        continue

                    # CRITICAL: Filter out long/messy targets (likely page dumps or non-elements)
                    if len(target) > 100 or "\n" in target or "page state" in target.lower():
                        continue

                    action_trace.append(
                        {
                            "step": len(action_trace) + 1,
                            "action": action,
                            "target": target[:100],  # Enforce hard limit
                            "outcome": "ok",
                            "is_new_discovery": False,
                        }
                    )

            # Check for specific keywords to estimate stats if regex failing
            if not action_trace:
                # Last resort: try to estimate from text content
                nav_count = len(re.findall(r"navigate", result_str, re.IGNORECASE))
                form_count = len(re.findall(r"form|input|submit", result_str, re.IGNORECASE))
                if nav_count > 0:
                    action_trace.append({"step": 1, "action": "navigate", "target": "inferred", "outcome": "ok"})

            # Deduplicate actions based on action+target signature
            unique_trace = []
            seen = set()
            for _i, act in enumerate(action_trace):
                # Normalize values
                a_val = act.get("action", "").lower()
                t_val = act.get("target", "").lower()
                sig = (a_val, t_val)

                if sig not in seen:
                    seen.add(sig)
                    # Re-assign proper step number
                    act["step"] = len(unique_trace) + 1
                    unique_trace.append(act)

            action_trace = unique_trace

        # --- Construct Final Data ---

        # Base stats
        pages_visited = len([a for a in action_trace if "navigate" in a.get("action", "").lower()])
        forms_interacted = len(
            [
                a
                for a in action_trace
                if any(x in a.get("action", "").lower() for x in ["fill", "select", "check", "submit"])
            ]
        )

        # Force pages_visited to at least 1 if we have any interactions (we must be ON a page)
        if pages_visited == 0 and len(action_trace) > 0:
            pages_visited = 1

        # Handle Flows - Try to infer if not parsed
        discovered_flows = parsed_data.get("discovered_flows", [])
        if parsing_failed and not discovered_flows:
            # Try to infer at least one flow from the trace if it's long enough
            if len(action_trace) >= 3:
                discovered_flows = [
                    {
                        "id": "inferred_flow_1",
                        "title": "Explored User Path",
                        "pages": [config.get("url")] + [a["target"] for a in action_trace if a["action"] == "navigate"],
                        "steps_count": len(action_trace),
                        "happy_path": "Inferred from execution trace",
                        "entry_point": config.get("url"),
                        "feature": "General Exploration",
                    }
                ]

        # Use parsed coverage if valid, otherwise calculate from trace
        if not parsing_failed and "coverage" in parsed_data:
            coverage = parsed_data["coverage"]
        else:
            # Dynamic coverage score calculation
            score = 0.0
            if pages_visited > 0:
                score += 0.2
            if forms_interacted > 0:
                score += 0.2
            if len(discovered_flows) > 0:
                score += 0.3
            if len(action_trace) > 10:
                score += 0.2
            if len(action_trace) > 20:
                score += 0.1

            coverage = {
                "navigation_explored": pages_visited > 1,
                "forms_interacted": forms_interacted,
                "flows_discovered": len(discovered_flows),
                "pages_visited": pages_visited,
                "errors_found": len([a for a in action_trace if "error" in a.get("action", "").lower()]),
                "coverage_score": min(1.0, score),
            }

        # --- PERSISTENCE TO MEMORY ---
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
            # CRITICAL: Save graph changes to disk ALWAYS
            try:
                memory_manager.graph_store.save()
                print(f"💾 Persisted graph data: {len(action_trace)} actions, {len(discovered_flows)} flows")
            except Exception as save_err:
                print(f"❌ Failed to save graph to disk: {save_err}")

        # --- Final Response Construction ---
        response_data = parsed_data if not parsing_failed else {}

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
            }
        )

        if parsing_failed:
            response_data.update(
                {
                    "summary": "Exploration completed. Result parsing required fallback.",
                    "preview": f"{result_str[:200]}..." if "result_str" in locals() else "",
                    "parsing_failed": True,
                }
            )

        # Save flows to file and generate summaries
        if run_id:
            flow_summaries = self._save_flows_and_generate_summaries(discovered_flows, run_id)
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

    def _save_flows_and_generate_summaries(self, flows: list[dict], run_id: str) -> list[dict]:
        """Save full flows to file and return summaries."""
        # Get project root (2 levels up from this file)
        project_root = Path(__file__).parent.parent.parent
        runs_dir = project_root / "runs"
        runs_dir.mkdir(exist_ok=True)

        # Create run-specific directory
        run_dir = runs_dir / run_id
        run_dir.mkdir(exist_ok=True)

        # Save full flows to JSON file
        flows_file = run_dir / "flows.json"
        with open(flows_file, "w") as f:
            json.dump({"flows": flows}, f, indent=2)

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
