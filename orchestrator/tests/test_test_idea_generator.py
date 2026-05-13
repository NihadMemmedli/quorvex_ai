import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

memory_stub = types.ModuleType("memory")
memory_stub.__path__ = []
exploration_store_stub = types.ModuleType("memory.exploration_store")
exploration_store_stub.get_exploration_store = lambda *args, **kwargs: None
sys.modules.setdefault("memory", memory_stub)
sys.modules.setdefault("memory.exploration_store", exploration_store_stub)

from orchestrator.workflows.requirements_generator import RequirementsGenerator as _RequirementsGenerator
from orchestrator.workflows.autopilot_pipeline import AutoPilotPipeline as _AutoPilotPipeline
from orchestrator.workflows.test_idea_generator import TestIdeaGenerator as _TestIdeaGenerator


def test_parse_response_normalizes_valid_ai_output():
    generator = object.__new__(_TestIdeaGenerator)
    response = """
```json
{
  "test_ideas": [
    {
      "title": "Login accepts valid credentials",
      "description": "Validate the primary login path.",
      "category": "happy_path",
      "priority": "critical",
      "source_flows": ["User Login"],
      "source_requirements": ["REQ-001"],
      "source_api_endpoints": ["/api/auth/login"],
      "suggested_steps": ["Navigate to login", "Submit valid credentials"],
      "expected_outcomes": ["Dashboard is visible"],
      "spec_readiness": "needs_auth",
      "confidence": 0.91
    }
  ]
}
```
"""

    ideas = generator._parse_response(response)

    assert len(ideas) == 1
    assert ideas[0].title == "Login accepts valid credentials"
    assert ideas[0].category == "happy_path"
    assert ideas[0].priority == "critical"
    assert ideas[0].spec_readiness == "needs_auth"
    assert ideas[0].confidence == 0.91


def test_fallback_ideas_use_requirements_and_flow_steps():
    generator = object.__new__(_TestIdeaGenerator)
    summary = {
        "entry_url": "https://example.com/login",
        "requirements": [
            {
                "code": "REQ-001",
                "title": "User Login",
                "description": "Users can sign in.",
                "priority": "high",
                "acceptance_criteria": [
                    "Valid credentials redirect to dashboard",
                    "Invalid credentials show an error",
                ],
            }
        ],
        "flows": [
            {
                "name": "User Login",
                "steps": [
                    {"action": "fill", "element": "Email input", "value": "user@example.com"},
                    {"action": "click", "element": "Login button"},
                ],
            }
        ],
        "issues": [],
    }

    ideas = generator._fallback_ideas(summary)

    assert [idea.title for idea in ideas] == [
        "Validate User Login",
        "Reject invalid input for User Login",
    ]
    assert ideas[0].source_flows == ["User Login"]
    assert ideas[0].source_requirements == ["REQ-001"]
    assert "Fill user@example.com in Email input" in ideas[0].suggested_steps
    assert ideas[1].category == "negative"


def test_requirements_fallback_creates_requirement_per_flow():
    generator = object.__new__(_RequirementsGenerator)
    summary = {
        "flows": [
            {
                "name": "User Login",
                "category": "authentication",
                "description": "User signs in and reaches the dashboard.",
                "is_success_path": True,
                "postconditions": ["Dashboard is visible"],
                "steps": [
                    {"action": "fill", "element": "Email input"},
                    {"action": "click", "element": "Login button"},
                ],
            }
        ],
        "api_endpoints": [
            {"url": "/api/auth/login", "triggered_by": "User Login submit"}
        ],
    }

    requirements = generator._generate_fallback_requirements(summary)

    assert len(requirements) == 1
    assert requirements[0].title == "User Login"
    assert requirements[0].category == "authentication"
    assert requirements[0].priority == "high"
    assert requirements[0].source_flows == ["User Login"]
    assert requirements[0].source_api_endpoints == ["/api/auth/login"]


def test_autopilot_normalizes_string_flow_steps_for_persistence():
    pipeline = object.__new__(_AutoPilotPipeline)

    steps = pipeline._normalize_flow_steps(["Navigate to homepage", {"action": "click", "element": "Login"}])

    assert steps == [
        {"action": "step", "element": "Navigate to homepage"},
        {"action": "click", "element": "Login", "ref": None, "role": None, "value": None},
    ]


def test_requirements_artifact_flow_normalizes_string_steps():
    generator = object.__new__(_RequirementsGenerator)

    flow = generator._normalize_artifact_flow(
        {
            "name": "Birth Life Event Service Discovery",
            "category": "navigation",
            "steps": ["Navigate to life events page", "Click Birth category"],
            "startUrl": "https://my.gov.az/lifeEvents",
            "endUrl": "https://my.gov.az/lifeEvents/birth",
            "outcome": "Birth services displayed",
        },
        1,
    )

    assert flow["name"] == "Birth Life Event Service Discovery"
    assert flow["description"] == "Birth services displayed"
    assert flow["steps"] == [
        {"action": "step", "element": "Navigate to life events page"},
        {"action": "step", "element": "Click Birth category"},
    ]


def test_requirement_code_assignment_is_sequential():
    class Store:
        def get_next_requirement_code(self):
            return "REQ-007"

    generator = object.__new__(_RequirementsGenerator)
    generator.store = Store()
    requirements = generator._generate_fallback_requirements(
        {
            "flows": [
                {"name": "Flow A", "category": "navigation"},
                {"name": "Flow B", "category": "navigation"},
            ],
            "api_endpoints": [],
        }
    )

    generator._assign_requirement_codes(requirements)

    assert [req.req_code for req in requirements] == ["REQ-007", "REQ-008"]


def test_requirements_fallback_creates_entry_page_requirement_without_flows():
    generator = object.__new__(_RequirementsGenerator)

    requirements = generator._generate_fallback_requirements(
        {
            "entry_url": "https://example.com",
            "pages_discovered": 1,
            "flows_discovered": 0,
            "flows": [],
            "transitions": [],
            "api_endpoints": [],
        }
    )

    assert len(requirements) == 1
    assert requirements[0].title == "Application availability and primary page access"
    assert requirements[0].category == "navigation"
    assert "entry page is reachable" in " ".join(requirements[0].acceptance_criteria)


def test_test_idea_fallback_creates_entry_page_smoke_idea_without_flows():
    generator = object.__new__(_TestIdeaGenerator)

    ideas = generator._fallback_ideas(
        {
            "entry_url": "https://example.com",
            "pages_discovered": 1,
            "flows_discovered": 0,
            "requirements": [],
            "flows": [],
            "transitions": [],
            "issues": [],
        }
    )

    assert len(ideas) == 1
    assert ideas[0].title == "Validate application entry page availability"
    assert ideas[0].suggested_steps[0] == "Navigate to https://example.com"


def test_autopilot_effective_priority_threshold_honors_checkpoint_answers():
    pipeline = object.__new__(_AutoPilotPipeline)
    pipeline._checkpoint_answers = {"review_requirements": "Focus on critical and high only"}

    class Config:
        priority_threshold = "low"

    assert pipeline._effective_priority_threshold(Config()) == "high"


def test_normalize_idea_bounds_untrusted_fields():
    generator = object.__new__(_TestIdeaGenerator)

    idea = generator._normalize_idea(
        {
            "title": "Search with special characters",
            "description": "Validate search input handling.",
            "category": "unexpected",
            "priority": "urgent",
            "source_flows": "Search",
            "suggested_steps": ["Navigate", "Search for %%%"],
            "spec_readiness": "unknown",
            "confidence": 2,
        }
    )

    assert idea.category == "coverage"
    assert idea.priority == "medium"
    assert idea.source_flows == ["Search"]
    assert idea.spec_readiness == "ready"
    assert idea.confidence == 1.0
