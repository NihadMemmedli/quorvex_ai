"""
Prerequisites Analysis Agent

Analyzes exploration results to identify prerequisites for each discovered flow.
Enriches flow data with:
- Authentication requirements
- Data dependencies (must have existing entities)
- Flow dependencies (must complete flow A before B)
- Application state requirements
- Setup steps needed before running the test
"""

from datetime import datetime
from typing import Any

from utils.json_utils import extract_json_from_markdown

from .base_agent import BaseAgent


class PrerequisitesAgent(BaseAgent):
    """
    Analyzes discovered flows and enriches them with prerequisites information.

    This agent examines:
    1. Action trace to understand what steps were taken before each flow
    2. Flow patterns to identify entity lifecycles (create → edit → delete)
    3. Authentication patterns (login forms, protected routes)
    4. Data requirements (edit/delete implies existing data)
    """

    async def run(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Analyze exploration results and enrich flows with prerequisites.

        Config:
        - flows: List of discovered flows from exploration
        - action_trace: Full action trace from exploration
        - exploration_url: Base URL of the explored application
        - auth_config: Authentication config used during exploration (if any)
        - test_data: Test data used during exploration (if any)
        """
        flows = config.get("flows", [])
        action_trace = config.get("action_trace", [])
        exploration_url = config.get("exploration_url", "")
        auth_config = config.get("auth_config", {})
        test_data = config.get("test_data", {})

        if not flows:
            return {
                "enriched_flows": [],
                "flow_graph": {},
                "summary": "No flows to analyze",
                "analyzed_at": datetime.now().isoformat(),
            }

        print("🔍 Prerequisites Analysis Agent")
        print(f"   Analyzing {len(flows)} flows")
        print(f"   Action trace: {len(action_trace)} actions")
        print(f"   Auth type: {auth_config.get('type', 'none')}")

        # Build the analysis prompt
        prompt = self._build_analysis_prompt(
            flows=flows,
            action_trace=action_trace,
            exploration_url=exploration_url,
            auth_config=auth_config,
            test_data=test_data,
        )

        # Query the agent
        result = await self._query_agent(prompt)

        # Parse and return results
        return self._process_results(result, flows)

    def _build_analysis_prompt(
        self, flows: list[dict], action_trace: list[dict], exploration_url: str, auth_config: dict, test_data: dict
    ) -> str:
        """Build the analysis prompt for prerequisites detection."""

        # Format flows for analysis
        flows_text = ""
        for i, flow in enumerate(flows, 1):
            flows_text += f"""
### Flow {i}: {flow.get("title", "Unnamed")}
- ID: {flow.get("id", f"flow_{i}")}
- Pages: {" → ".join(flow.get("pages", []))}
- Entry Point: {flow.get("entry_point", "N/A")}
- Exit Point: {flow.get("exit_point", "N/A")}
- Happy Path: {flow.get("happy_path", "N/A")}
- Edge Cases: {", ".join(flow.get("edge_cases", [])[:5])}
- Test Ideas: {", ".join(flow.get("test_ideas", [])[:3])}
"""

        # Format action trace (summarized)
        trace_text = ""
        if action_trace:
            trace_text = "\n### Action Trace (chronological order):\n"
            for action in action_trace[:40]:  # Limit to first 40 actions
                step = action.get("step", "?")
                act = action.get("action", "unknown")
                target = action.get("target", "N/A")[:80]
                trace_text += f"- Step {step}: {act} → {target}\n"
            if len(action_trace) > 40:
                trace_text += f"... and {len(action_trace) - 40} more actions\n"

        # Auth context
        auth_text = ""
        if auth_config and auth_config.get("type") != "none":
            auth_text = f"""
### Authentication Used During Exploration:
- Type: {auth_config.get("type")}
- Login URL: {auth_config.get("login_url", "N/A")}
- User Type: {auth_config.get("credentials", {}).get("user_type", "standard")}
"""

        # Test data context
        test_data_text = ""
        if test_data:
            test_data_text = "\n### Test Data Used:\n"
            for key, value in test_data.items():
                test_data_text += f"- {key}: {value}\n"

        return f"""You are a Prerequisites Analysis Agent for test automation.

Your task is to analyze discovered user flows and identify ALL prerequisites needed to run each flow as an independent test.

## Application Context
- Base URL: {exploration_url}
{auth_text}
{test_data_text}

## Discovered Flows
{flows_text}

{trace_text}

## Your Analysis Task

For EACH flow, identify:

### 1. Authentication Requirements
- Does this flow require the user to be logged in?
- What user type/role is needed? (guest, user, admin, organizer, etc.)
- What permissions are required?

### 2. Data Prerequisites
- What data must ALREADY EXIST before this flow can run?
- Examples: "Must have existing trip", "Must have items in cart", "Must have saved payment method"
- Think about: Does this flow EDIT, DELETE, or VIEW something? If so, that thing must exist first.

### 3. Flow Dependencies
- Must another flow complete BEFORE this one can run?
- Example: "Edit Trip" requires "Create Trip" to have completed
- Build a dependency graph

### 4. Application State
- What state must the application be in?
- Starting page, modal state, wizard step, etc.

### 5. Setup Steps
- What are the ACTIONABLE steps to reach the starting point of this flow?
- Be specific: "Login as organizer", "Navigate to /my_trips", "Click Create button"

### 6. What This Flow Produces
- What entities/data does this flow CREATE?
- What other flows does completing this flow ENABLE?

## CRITICAL ANALYSIS RULES

1. **CRUD Detection**:
   - "Create X" flows usually have NO data prerequisites
   - "Edit X", "Update X", "Manage X" flows REQUIRE X to exist
   - "Delete X", "Remove X" flows REQUIRE X to exist
   - "View X details", "X history" flows REQUIRE X to exist

2. **Authentication Patterns**:
   - If login was performed before the flow, the flow requires authentication
   - Look for protected URLs (/dashboard, /admin, /my_*, /user/*)
   - Guest flows typically start from public pages

3. **Flow Sequencing**:
   - Look at the action trace ORDER to understand what happened before each flow
   - If actions for Flow B always followed Flow A actions, B may depend on A

4. **Entity Lifecycle**:
   - Identify entities (trip, booking, user, order, etc.)
   - Map their lifecycle: create → view → edit → delete
   - Each stage depends on previous stages

## Output Format

Return ONLY valid JSON:

```json
{{
  "enriched_flows": [
    {{
      "id": "flow_1",
      "title": "Original Flow Title",
      "prerequisites": {{
        "authentication": {{
          "required": true,
          "user_type": "organizer",
          "permissions": ["create_trip"],
          "login_url": "/login"
        }},
        "data_requirements": [
          {{
            "entity": "account",
            "state": "verified",
            "description": "User account must be verified"
          }}
        ],
        "prior_flows": [],
        "application_state": {{
          "starting_page": "/my_trips",
          "required_state": null
        }},
        "setup_steps": [
          "Login as organizer user",
          "Navigate to My Trips page"
        ]
      }},
      "produces": {{
        "entities": ["trip"],
        "enables_flows": ["trip_editing", "itinerary_management"]
      }},
      "dependency_reason": null
    }},
    {{
      "id": "flow_2",
      "title": "Edit Trip Flow",
      "prerequisites": {{
        "authentication": {{
          "required": true,
          "user_type": "organizer",
          "permissions": ["edit_trip"],
          "login_url": "/login"
        }},
        "data_requirements": [
          {{
            "entity": "trip",
            "state": "created",
            "description": "Must have at least one trip created"
          }}
        ],
        "prior_flows": ["flow_1"],
        "application_state": {{
          "starting_page": "/my_trips",
          "required_state": "trip_exists"
        }},
        "setup_steps": [
          "Login as organizer user",
          "Ensure at least one trip exists (run Create Trip flow first)",
          "Navigate to My Trips page",
          "Select an existing trip"
        ]
      }},
      "produces": {{
        "entities": [],
        "enables_flows": []
      }},
      "dependency_reason": "Editing requires an existing trip to be created first"
    }}
  ],
  "flow_graph": {{
    "nodes": ["flow_1", "flow_2"],
    "edges": [
      {{"from": "flow_1", "to": "flow_2", "reason": "Edit requires created trip"}}
    ],
    "root_flows": ["flow_1"],
    "leaf_flows": ["flow_2"]
  }},
  "entities_discovered": ["trip", "itinerary", "booking"],
  "summary": "Analyzed X flows. Y require authentication. Z have data dependencies."
}}
```

Now analyze the flows and return the enriched data."""

    def _process_results(self, result: Any, original_flows: list[dict]) -> dict[str, Any]:
        """Process the agent's analysis results."""
        try:
            parsed = extract_json_from_markdown(result)

            if not parsed or not isinstance(parsed, dict):
                raise ValueError("Failed to parse analysis result")

            enriched_flows = parsed.get("enriched_flows", [])

            # Merge enriched data back into original flows
            flow_map = {f.get("id"): f for f in original_flows}

            for enriched in enriched_flows:
                flow_id = enriched.get("id")
                if flow_id and flow_id in flow_map:
                    # Add prerequisites to original flow
                    flow_map[flow_id]["prerequisites"] = enriched.get("prerequisites", {})
                    flow_map[flow_id]["produces"] = enriched.get("produces", {})
                    flow_map[flow_id]["dependency_reason"] = enriched.get("dependency_reason")

            return {
                "enriched_flows": list(flow_map.values()),
                "flow_graph": parsed.get("flow_graph", {}),
                "entities_discovered": parsed.get("entities_discovered", []),
                "summary": parsed.get("summary", "Analysis complete"),
                "analyzed_at": datetime.now().isoformat(),
            }

        except Exception as e:
            print(f"⚠️ Prerequisites analysis parsing failed: {e}")

            # Return original flows with empty prerequisites
            for flow in original_flows:
                if "prerequisites" not in flow:
                    flow["prerequisites"] = {
                        "authentication": {"required": False},
                        "data_requirements": [],
                        "prior_flows": [],
                        "setup_steps": [],
                    }
                if "produces" not in flow:
                    flow["produces"] = {"entities": [], "enables_flows": []}

            return {
                "enriched_flows": original_flows,
                "flow_graph": {},
                "entities_discovered": [],
                "summary": f"Analysis failed: {str(e)}",
                "analyzed_at": datetime.now().isoformat(),
                "error": str(e),
            }
