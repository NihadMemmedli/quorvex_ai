import sys
import types
import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

memory_stub = types.ModuleType("memory")
memory_stub.__path__ = []
exploration_store_stub = types.ModuleType("memory.exploration_store")
exploration_store_stub.get_exploration_store = lambda *args, **kwargs: None
sys.modules.setdefault("memory", memory_stub)
sys.modules.setdefault("memory.exploration_store", exploration_store_stub)

from orchestrator.workflows.requirements_generator import (
    GeneratedRequirement as _GeneratedRequirement,
    RequirementsGenerator as _RequirementsGenerator,
)
from orchestrator.workflows.autopilot_pipeline import (
    AutoPilotPipeline as _AutoPilotPipeline,
)
from orchestrator.ai.context import SOURCE_OBSERVED
from orchestrator.workflows.app_explorer import AppExplorer as _AppExplorer
from orchestrator.workflows.app_explorer import ExplorationConfig as _ExplorationConfig
from orchestrator.workflows.app_explorer import PageRecord as _PageRecord
from orchestrator.workflows.spec_scenario_builder import (
    conservative_page_scenarios,
    render_scenario_markdown,
    scenario_from_test_idea,
)
from orchestrator.workflows.test_idea_generator import (
    TestIdeaGenerator as _TestIdeaGenerator,
)
from orchestrator.utils import agent_runner as _agent_runner_module
from orchestrator.utils.agent_runner import AgentRunner as _AgentRunner


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
                    {
                        "action": "fill",
                        "element": "Email input",
                        "value": "user@example.com",
                    },
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


def test_requirement_without_flow_gets_conservative_companion_ideas():
    generator = object.__new__(_TestIdeaGenerator)
    ideas = generator._fallback_ideas(
        {
            "entry_url": "https://example.com/lifeEvents",
            "requirements": [
                {
                    "code": "REQ-010",
                    "title": "Life Events page reachable",
                    "description": "Page returned HTTP 200 and rendered as life_events.",
                    "priority": "medium",
                    "acceptance_criteria": ["Life events page reachable"],
                }
            ],
            "flows": [],
            "issues": [],
        }
    )

    assert [idea.category for idea in ideas] == [
        "happy_path",
        "regression",
        "accessibility",
        "edge_case",
    ]
    assert all("Life Events page reachable" in idea.title for idea in ideas)
    assert ideas[1].suggested_steps[0] == "Navigate to https://example.com/lifeEvents"


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

    steps = pipeline._normalize_flow_steps(
        ["Navigate to homepage", {"action": "click", "element": "Login"}]
    )

    assert steps == [
        {"action": "step", "element": "Navigate to homepage"},
        {
            "action": "click",
            "element": "Login",
            "ref": None,
            "role": None,
            "value": None,
        },
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


def test_requirements_parser_preserves_confidence_uncertainty_and_evidence_refs():
    generator = object.__new__(_RequirementsGenerator)

    requirements = generator._parse_requirements_response(
        """
```json
{
  "requirements": [
    {
      "title": "User Login",
      "description": "The system shall support login.",
      "category": "authentication",
      "priority": "high",
      "acceptance_criteria": ["Login form is available"],
      "source_flows": ["User Login"],
      "evidence_refs": ["evidence:authentication:flow:User Login"],
      "confidence": 0.82,
      "uncertainty_reason": "Credentials were not available."
    }
  ]
}
```
"""
    )

    assert len(requirements) == 1
    assert requirements[0].confidence == 0.82
    assert requirements[0].uncertainty_reason == "Credentials were not available."
    assert requirements[0].evidence_refs == ["evidence:authentication:flow:User Login"]


@pytest.mark.asyncio
async def test_requirements_critic_rejects_unsupported_and_dedupes_candidates():
    generator = object.__new__(_RequirementsGenerator)
    packets = [
        {
            "id": "evidence:authentication",
            "category": "authentication",
            "evidence_refs": ["evidence:authentication:flow:User Login"],
        }
    ]
    candidates = [
        _GeneratedRequirement(
            req_code="REQ-001",
            title="User Login",
            description="The system shall support login.",
            category="authentication",
            priority="high",
            acceptance_criteria=["Login form is available"],
            source_flows=["User Login"],
            evidence_refs=["evidence:authentication:flow:User Login"],
            confidence=0.8,
        ),
        _GeneratedRequirement(
            req_code="REQ-002",
            title="User Login",
            description="Duplicate.",
            category="authentication",
            priority="high",
            acceptance_criteria=["Duplicate"],
            source_flows=["User Login"],
            evidence_refs=["evidence:authentication:flow:User Login"],
            confidence=0.8,
        ),
        _GeneratedRequirement(
            req_code="REQ-003",
            title="Invented Checkout",
            description="Unsupported.",
            category="crud",
            priority="high",
            acceptance_criteria=["Checkout succeeds"],
            confidence=0.9,
        ),
    ]

    requirements = await generator._critic_synthesize_requirements(candidates, packets)

    assert [req.title for req in requirements] == ["User Login"]


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


def test_requirements_fallback_uses_page_artifacts_for_sparse_flows():
    generator = object.__new__(_RequirementsGenerator)

    requirements = generator._generate_fallback_requirements(
        {
            "entry_url": "https://my.gov.az/entities/1",
            "pages_discovered": 12,
            "flows_discovered": 1,
            "flows": [
                {
                    "name": "Entity Detail Browse",
                    "category": "navigation",
                    "description": "Entity detail page is reachable.",
                    "start_url": "https://my.gov.az/entities/1",
                    "end_url": "https://my.gov.az/entities/1",
                    "steps": [{"action": "navigate", "element": "entity detail"}],
                }
            ],
            "pages": [
                {
                    "url": "https://my.gov.az/entities/1",
                    "title": "Entity Detail",
                    "pageType": "entity_detail",
                    "purpose": "Shows ministry services and life events.",
                    "actions": ["Open related life event"],
                },
                {
                    "url": "https://my.gov.az/lifeEvents/2",
                    "title": "Life Event Detail",
                    "pageType": "life_event_detail",
                    "purpose": "Shows related public services.",
                    "actions": ["Open service detail"],
                },
                {
                    "url": "https://my.gov.az/services/3",
                    "title": "Service Detail",
                    "pageType": "service_detail",
                    "purpose": "Shows service information and application action.",
                    "forms": [{"name": "Document verification", "submit": "Check"}],
                },
            ],
            "transitions": [],
            "api_endpoints": [],
        }
    )

    titles = [req.title for req in requirements]
    assert "Entity Detail Browse" in titles
    assert "Life Event Detail Page Access" in titles
    assert "Service Detail Form Submission" in titles
    assert len(requirements) >= 3


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

    assert len(ideas) == 4
    assert ideas[0].title == "Validate application entry page availability"
    assert ideas[0].suggested_steps[0] == "Navigate to https://example.com"
    assert {idea.category for idea in ideas} == {
        "coverage",
        "regression",
        "accessibility",
        "edge_case",
    }


def test_scenario_builder_renders_runnable_spec_from_test_idea():
    scenario = scenario_from_test_idea(
        {
            "title": "Login accepts valid credentials",
            "description": "Validate the primary login path.",
            "category": "happy_path",
            "priority": "critical",
            "source_flows": ["User Login"],
            "source_requirements": ["REQ-001"],
            "source_api_endpoints": ["/api/auth/login"],
            "suggested_steps": ["Enter valid credentials", "Click the Login button"],
            "expected_outcomes": ["Dashboard is visible"],
            "spec_readiness": "needs_auth",
        },
        target_url="https://example.com/login",
        fallback_title="Login",
    )

    markdown = render_scenario_markdown(scenario, scenario_id="TC-001")

    assert "# Test: Login accepts valid credentials" in markdown
    assert "## Prerequisites" in markdown
    assert "Authenticated user credentials are available" in markdown
    assert "1. Navigate to https://example.com/login" in markdown
    assert "- Dashboard is visible" in markdown
    assert "Observed API endpoint(s): /api/auth/login" in markdown


def test_conservative_page_scenarios_do_not_invent_business_behavior():
    scenarios = conservative_page_scenarios(
        title="Life Events",
        target_url="https://my.gov.az/lifeEvents",
        max_scenarios=4,
    )

    assert [scenario.category for scenario in scenarios] == [
        "happy_path",
        "regression",
        "accessibility",
        "edge_case",
    ]
    combined_steps = " ".join(step for scenario in scenarios for step in scenario.steps)
    assert "life event application" not in combined_steps.lower()
    assert "Navigate to https://my.gov.az/lifeEvents" in combined_steps


def test_autopilot_effective_priority_threshold_honors_checkpoint_answers():
    pipeline = object.__new__(_AutoPilotPipeline)
    pipeline._checkpoint_answers = {
        "review_requirements": "Focus on critical and high only"
    }

    class Config:
        priority_threshold = "low"

    assert pipeline._effective_priority_threshold(Config()) == "high"


def test_autopilot_treats_many_pages_one_flow_as_weak_exploration():
    pipeline = object.__new__(_AutoPilotPipeline)

    assert pipeline._is_weak_exploration(total_pages=38, total_flows=1)
    assert not pipeline._is_weak_exploration(total_pages=2, total_flows=1)


def test_autopilot_auto_retry_only_when_no_usable_evidence():
    pipeline = object.__new__(_AutoPilotPipeline)

    assert (
        pipeline._auto_retry_reason(
            total_pages=0,
            total_flows=0,
            total_transitions=0,
            total_api_endpoints=0,
        )
        == "no_usable_exploration_evidence"
    )
    assert (
        pipeline._auto_retry_reason(
            total_pages=38,
            total_flows=1,
            total_transitions=0,
            total_api_endpoints=0,
        )
        is None
    )
    assert (
        pipeline._auto_retry_reason(
            total_pages=0,
            total_flows=0,
            total_transitions=3,
            total_api_endpoints=0,
        )
        is None
    )


def test_autopilot_chat_style_priority_guidance_does_not_leave_medium_tasks_pending(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    pipeline = object.__new__(_AutoPilotPipeline)
    pipeline.session_id = "autopilot_unit"
    pipeline._checkpoint_answers = {}
    pipeline._cancelled = SimpleNamespace(is_set=lambda: False)

    tasks = [
        SimpleNamespace(
            id=1, priority="high", requirement_title="Validate Login Browse"
        ),
        SimpleNamespace(
            id=2, priority="medium", requirement_title="Validate Entities Browse"
        ),
        SimpleNamespace(
            id=3, priority="medium", requirement_title="Validate Services Browse"
        ),
    ]
    statuses = {task.id: "pending" for task in tasks}
    skipped: list[int] = []

    pipeline._load_open_spec_tasks = lambda: tasks
    pipeline._generate_spec_from_task = lambda task, _specs_dir, _config: Path(
        f"{task.requirement_title}.md"
    )
    pipeline._update_spec_task = (
        lambda task_id, status, spec_path=None, error=None: statuses.__setitem__(
            task_id, status
        )
    )
    pipeline._skip_spec_tasks = lambda task_ids, _reason: (
        skipped.extend(task_ids),
        [statuses.__setitem__(tid, "skipped") for tid in task_ids],
    )
    pipeline._count_pending_spec_tasks = lambda: sum(
        1 for status in statuses.values() if status == "pending"
    )
    pipeline._count_completed_spec_tasks = lambda: sum(
        1 for status in statuses.values() if status == "completed"
    )
    pipeline._update_session_field = lambda *_args, **_kwargs: None
    pipeline._update_phase_step = lambda *_args, **_kwargs: None

    class Config:
        priority_threshold = "high"
        max_specs = 50

    result = asyncio.run(pipeline._run_spec_generation_phase(Config(), phase_id=1))

    assert result["specs_generated"] == 1
    assert result["filtered_by_priority"] == 2
    assert result["remaining_pending_tasks"] == 0
    assert skipped == [2, 3]
    assert statuses == {1: "completed", 2: "skipped", 3: "skipped"}


def test_autopilot_spec_generation_continues_on_partial_success(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    pipeline = object.__new__(_AutoPilotPipeline)
    pipeline.session_id = "autopilot_unit"
    pipeline._checkpoint_answers = {}
    pipeline._cancelled = SimpleNamespace(is_set=lambda: False)

    tasks = [
        SimpleNamespace(id=idx, priority="high", requirement_title=f"Spec task {idx}")
        for idx in range(1, 11)
    ]
    statuses = {task.id: "pending" for task in tasks}
    errors: dict[int, str] = {}

    def generate(task, _specs_dir, _config):
        if task.id == 10:
            raise RuntimeError("LLM returned invalid markdown")
        return Path(f"{task.requirement_title}.md")

    def update_task(task_id, status, spec_path=None, error=None):
        statuses[task_id] = status
        if error:
            errors[task_id] = error

    pipeline._load_open_spec_tasks = lambda: tasks
    pipeline._generate_spec_from_task = generate
    pipeline._update_spec_task = update_task
    pipeline._skip_spec_tasks = lambda *_args, **_kwargs: None
    pipeline._count_pending_spec_tasks = lambda: sum(
        1 for status in statuses.values() if status == "pending"
    )
    pipeline._count_completed_spec_tasks = lambda: sum(
        1 for status in statuses.values() if status == "completed"
    )
    pipeline._update_session_field = lambda *_args, **_kwargs: None
    pipeline._update_phase_step = lambda *_args, **_kwargs: None

    class Config:
        priority_threshold = "high"
        max_specs = 10

    result = asyncio.run(pipeline._run_spec_generation_phase(Config(), phase_id=1))

    assert result["status"] == "completed"
    assert result["specs_generated"] == 9
    assert result["batch_specs_generated"] == 9
    assert result["failed_selected_tasks"] == 1
    assert result["partial_success"] is True
    assert (
        result["warning"]
        == "Generated 9/10 selected specs; continuing with completed specs"
    )
    assert statuses[10] == "failed"
    assert "invalid markdown" in errors[10]


def test_autopilot_spec_generation_still_fails_when_no_specs_exist(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    pipeline = object.__new__(_AutoPilotPipeline)
    pipeline.session_id = "autopilot_unit"
    pipeline._checkpoint_answers = {}
    pipeline._cancelled = SimpleNamespace(is_set=lambda: False)

    tasks = [
        SimpleNamespace(id=1, priority="high", requirement_title="Spec task 1"),
        SimpleNamespace(id=2, priority="high", requirement_title="Spec task 2"),
    ]
    statuses = {task.id: "pending" for task in tasks}

    pipeline._load_open_spec_tasks = lambda: tasks
    pipeline._generate_spec_from_task = lambda *_args, **_kwargs: None
    pipeline._update_spec_task = (
        lambda task_id, status, spec_path=None, error=None: statuses.__setitem__(
            task_id, status
        )
    )
    pipeline._skip_spec_tasks = lambda *_args, **_kwargs: None
    pipeline._count_pending_spec_tasks = lambda: sum(
        1 for status in statuses.values() if status == "pending"
    )
    pipeline._count_completed_spec_tasks = lambda: sum(
        1 for status in statuses.values() if status == "completed"
    )
    pipeline._update_session_field = lambda *_args, **_kwargs: None
    pipeline._update_phase_step = lambda *_args, **_kwargs: None

    class Config:
        priority_threshold = "high"
        max_specs = 10

    with pytest.raises(RuntimeError, match="Spec generation produced 0 specs"):
        asyncio.run(pipeline._run_spec_generation_phase(Config(), phase_id=1))


def test_autopilot_spec_generation_updates_cumulative_total_on_retry(
    monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    pipeline = object.__new__(_AutoPilotPipeline)
    pipeline.session_id = "autopilot_unit"
    pipeline._checkpoint_answers = {}
    pipeline._cancelled = SimpleNamespace(is_set=lambda: False)

    retry_task = SimpleNamespace(
        id=10, priority="high", requirement_title="Retried spec task"
    )
    statuses = {idx: "completed" for idx in range(1, 10)}
    statuses[retry_task.id] = "failed"
    session_updates: dict[str, int] = {}

    pipeline._load_open_spec_tasks = lambda: [retry_task]
    pipeline._generate_spec_from_task = lambda task, _specs_dir, _config: Path(
        f"{task.requirement_title}.md"
    )
    pipeline._update_spec_task = (
        lambda task_id, status, spec_path=None, error=None: statuses.__setitem__(
            task_id, status
        )
    )
    pipeline._skip_spec_tasks = lambda *_args, **_kwargs: None
    pipeline._count_pending_spec_tasks = lambda: sum(
        1 for status in statuses.values() if status == "pending"
    )
    pipeline._count_completed_spec_tasks = lambda: sum(
        1 for status in statuses.values() if status == "completed"
    )
    pipeline._update_session_field = lambda field, value: session_updates.__setitem__(
        field, value
    )
    pipeline._update_phase_step = lambda *_args, **_kwargs: None

    class Config:
        priority_threshold = "high"
        max_specs = 10

    result = asyncio.run(pipeline._run_spec_generation_phase(Config(), phase_id=1))

    assert result["specs_generated"] == 10
    assert result["batch_specs_generated"] == 1
    assert result["failed_selected_tasks"] == 0
    assert result["partial_success"] is False
    assert session_updates["total_specs_generated"] == 10


def test_autopilot_unique_spec_filenames_include_task_id(monkeypatch, tmp_path):
    pipeline = object.__new__(_AutoPilotPipeline)
    pipeline.session_id = "autopilot_unit"
    pipeline._get_session_exploration_ids = lambda: []
    pipeline._get_test_idea_for_task = lambda *_args, **_kwargs: None

    class Store:
        def get_requirements(self):
            return []

    monkeypatch.setattr(
        "orchestrator.memory.exploration_store.get_exploration_store",
        lambda **_kwargs: Store(),
    )

    class Config:
        project_id = "default"
        entry_urls = ["https://example.com"]

    long_title = "Validate " + ("shared service discovery title " * 5)
    first = SimpleNamespace(id=101, requirement_id=None, requirement_title=long_title)
    second = SimpleNamespace(id=102, requirement_id=None, requirement_title=long_title)

    first_path = pipeline._generate_spec_from_task(first, tmp_path, Config())
    second_path = pipeline._generate_spec_from_task(second, tmp_path, Config())

    assert first_path != second_path
    assert first_path.name.endswith("-101.md")
    assert second_path.name.endswith("-102.md")


def test_autopilot_generated_spec_registers_project_metadata(monkeypatch):
    from sqlmodel import Session, SQLModel, select

    from orchestrator.api.db import _run_migrations, engine
    from orchestrator.api.models_db import Project, SpecMetadata

    SQLModel.metadata.create_all(engine, checkfirst=True)
    _run_migrations()

    session_id = f"autopilot_unit_{datetime.utcnow().timestamp():.0f}".replace(".", "_")
    project_id = "wetravel-project"
    specs_dir = PROJECT_ROOT / "specs" / "autopilot" / session_id
    spec_path = None
    created_project = False

    with Session(engine) as db:
        if not db.get(Project, project_id):
            db.add(Project(id=project_id, name="Wetravel"))
            db.commit()
            created_project = True

    pipeline = object.__new__(_AutoPilotPipeline)
    pipeline.session_id = session_id
    pipeline._get_session_exploration_ids = lambda: []
    pipeline._get_test_idea_for_task = lambda *_args, **_kwargs: None

    class Store:
        def get_requirements(self):
            return []

    monkeypatch.setattr(
        "orchestrator.memory.exploration_store.get_exploration_store",
        lambda **_kwargs: Store(),
    )

    class Config:
        project_id = "wetravel-project"
        entry_urls = ["https://example.com"]

    try:
        specs_dir.mkdir(parents=True, exist_ok=True)
        task = SimpleNamespace(id=301, requirement_id=None, requirement_title="Wetravel booking checkout")
        spec_path = pipeline._generate_spec_from_task(task, specs_dir, Config())

        assert spec_path.exists()
        relative_name = f"autopilot/{session_id}/{spec_path.name}"

        with Session(engine) as db:
            metadata = db.exec(select(SpecMetadata).where(SpecMetadata.spec_name == relative_name)).first()
            assert metadata is not None
            assert metadata.project_id == "wetravel-project"
            assert metadata.tags == []
            assert metadata.last_modified is not None
    finally:
        if spec_path:
            spec_path.unlink(missing_ok=True)
        try:
            specs_dir.rmdir()
        except OSError:
            pass
        with Session(engine) as db:
            for row in db.exec(select(SpecMetadata).where(SpecMetadata.spec_name.like(f"autopilot/{session_id}/%"))).all():
                db.delete(row)
            if created_project:
                project = db.get(Project, project_id)
                if project:
                    db.delete(project)
            db.commit()


def test_autopilot_expected_spec_tasks_deduplicates_requirement_titles():
    pipeline = object.__new__(_AutoPilotPipeline)
    requirements = [
        SimpleNamespace(title="Service Categories Browse"),
        SimpleNamespace(title="Service Categories Browse"),
        SimpleNamespace(title="Validate Homepage Browse"),
        SimpleNamespace(title="Homepage Browse"),
    ]

    assert pipeline._count_unique_requirement_targets(requirements) == 2


def test_autopilot_spec_tasks_keep_distinct_ideas_for_same_requirement(monkeypatch):
    pipeline = object.__new__(_AutoPilotPipeline)
    pipeline.session_id = "autopilot_unit"
    pipeline._lookup_requirement_id_for_test_idea = lambda _idea: 42
    added = []

    class ExecResult:
        def all(self):
            return []

    class FakeSession:
        def __init__(self, _engine):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def exec(self, _stmt):
            return ExecResult()

        def add(self, value):
            added.append(value)

        def commit(self):
            pass

    monkeypatch.setattr(
        "orchestrator.workflows.autopilot_pipeline.Session", FakeSession
    )

    created = pipeline._create_spec_tasks_from_test_ideas(
        [
            SimpleNamespace(title="Validate login success", priority="critical"),
            SimpleNamespace(title="Reject invalid login", priority="high"),
        ]
    )

    assert created == 2
    assert [task.requirement_title for task in added] == [
        "Validate login success",
        "Reject invalid login",
    ]
    assert {task.requirement_id for task in added} == {42}


def test_autopilot_uses_native_generation_for_actionable_weak_evidence_spec(tmp_path):
    pipeline = object.__new__(_AutoPilotPipeline)
    pipeline._get_session_config = lambda: {
        "ai_quality": {"exploration": {"degraded_mode": True}}
    }
    spec_path = tmp_path / "login.md"
    spec_path.write_text(
        "\n".join(
            [
                "# Test: Login redirect",
                "",
                "## Steps",
                "1. Navigate to https://example.com/login",
                "2. Fill user@example.com into the email field",
                "3. Click the Login button",
                "",
                "## Expected Outcome",
                "- Dashboard is visible",
            ]
        )
    )

    assert pipeline._spec_has_actionable_e2e_steps(str(spec_path))
    assert not pipeline._should_use_conservative_test_generation(str(spec_path))


def test_autopilot_uses_smoke_generation_for_page_load_only_weak_evidence_spec(
    tmp_path,
):
    pipeline = object.__new__(_AutoPilotPipeline)
    pipeline._get_session_config = lambda: {
        "ai_quality": {"exploration": {"degraded_mode": True}}
    }
    spec_path = tmp_path / "reachable.md"
    spec_path.write_text(
        "\n".join(
            [
                "# Test: Page reachable",
                "",
                "## Steps",
                "1. Navigate to https://example.com",
                "2. Wait for the page to finish loading",
                "3. Verify the response status is 200",
                "4. Verify the page renders without server errors",
            ]
        )
    )

    assert not pipeline._spec_has_actionable_e2e_steps(str(spec_path))
    assert pipeline._should_use_conservative_test_generation(str(spec_path))


def test_explorer_synthesizes_page_flows_when_flow_density_is_sparse():
    explorer = object.__new__(_AppExplorer)
    existing = []
    pages = [
        _PageRecord(
            url="https://my.gov.az/entities/1",
            title="Entity Detail",
            page_type="entity_detail",
            purpose="Shows ministry services and life events.",
            actions=["Open related life event"],
        ),
        _PageRecord(
            url="https://my.gov.az/services/3",
            title="Service Detail",
            page_type="service_detail",
            forms=[{"name": "Document verification", "submit": "Check"}],
        ),
    ]

    flows = explorer._synthesize_flows_from_pages(pages, existing, limit=2)

    assert [flow.name for flow in flows] == [
        "Browse Entity Detail (synthesized)",
        "Service Detail Form Submission (synthesized)",
    ]
    assert flows[1].category == "form_submission"
    assert flows[1].steps[-1]["element"] == "Check"


def test_explorer_prompt_is_goal_bounded_not_queue_exhaustive():
    explorer = object.__new__(_AppExplorer)
    prompt = explorer._build_exploration_prompt(
        _ExplorationConfig(entry_url="https://my.gov.az/", max_interactions=50)
    )

    assert "Target Page Records" in prompt
    assert "Target Flow Records" in prompt
    assert "Do not attempt to crawl every link" in prompt
    assert "Stop and emit final summary" in prompt
    assert "You MUST visit every URL" not in prompt
    assert "UNVISITED_QUEUE is empty" not in prompt


def test_explorer_identifies_browser_budget_stop():
    assert _AppExplorer._is_budget_stop("Browser tool budget reached (50/50)")
    assert not _AppExplorer._is_budget_stop("Agent timed out")


def test_explorer_parses_transition_with_string_action_element():
    explorer = _AppExplorer(project_id="test")

    result = explorer._parse_exploration_output(
        "agent output",
        "session_string_element",
        "https://example.com",
        pre_extracted_json=[
            {
                "transition": {
                    "sequence": 1,
                    "action": {"type": "click", "element": "Sign in", "value": None},
                    "before": {"url": "https://example.com", "pageType": "home", "keyElements": ["Sign in"]},
                    "after": {"url": "https://example.com/login", "pageType": "login", "keyElements": ["Email"]},
                    "transitionType": "navigation",
                    "apiCalls": [],
                }
            }
        ],
    )

    assert result.transitions[0].action_element == {"name": "Sign in"}
    assert result.elements_discovered == 2


def test_explorer_preserves_dict_action_element_fields():
    explorer = _AppExplorer(project_id="test")
    element = {"ref": "e1", "role": "button", "name": "Submit"}

    result = explorer._parse_exploration_output(
        "agent output",
        "session_dict_element",
        "https://example.com",
        pre_extracted_json=[
            {
                "transition": {
                    "sequence": 1,
                    "action": {"type": "click", "element": element},
                    "before": {"url": "https://example.com/form", "pageType": "form", "keyElements": []},
                    "after": {"url": "https://example.com/done", "pageType": "success", "keyElements": []},
                    "transitionType": "navigation",
                    "apiCalls": [],
                }
            }
        ],
    )

    assert result.transitions[0].action_element is element
    assert result.transitions[0].action_element["ref"] == "e1"


def test_explorer_ignores_or_coerces_malformed_api_call_entries():
    explorer = _AppExplorer(project_id="test")

    result = explorer._parse_exploration_output(
        "agent output",
        "session_malformed_api",
        "https://example.com",
        pre_extracted_json=[
            {
                "transition": {
                    "sequence": 1,
                    "action": {"type": "click", "element": "Load"},
                    "before": {"url": "https://example.com", "pageType": "home", "keyElements": []},
                    "after": {"url": "https://example.com", "pageType": "home", "keyElements": []},
                    "transitionType": "inline_update",
                    "richApiCalls": [
                        "https://example.com/api/loose",
                        {"method": "POST", "url": "/api/search", "status": 200},
                    ],
                    "apiCalls": ["not-a-dict", {"method": "GET", "url": "/api/basic", "status": 200}],
                }
            }
        ],
    )

    assert {endpoint["url"] for endpoint in result.api_endpoints} == {
        "https://example.com/api/loose",
        "/api/search",
    }
    assert result.transitions[0].api_calls[0]["url"] == "not-a-dict"


def test_explorer_error_transition_with_string_element_creates_issue():
    explorer = _AppExplorer(project_id="test")

    result = explorer._parse_exploration_output(
        "agent output",
        "session_error_string_element",
        "https://example.com",
        pre_extracted_json=[
            {
                "transition": {
                    "sequence": 1,
                    "action": {"type": "click", "element": "Delete account"},
                    "before": {"url": "https://example.com/settings", "pageType": "settings", "keyElements": []},
                    "after": {"url": "https://example.com/error", "pageType": "error", "keyElements": []},
                    "transitionType": "error",
                    "apiCalls": [],
                }
            }
        ],
    )

    assert result.issues[0].element == "Delete account"
    assert result.issues[0].issue_type == "error_page"


@pytest.mark.asyncio
async def test_explorer_rejects_unverified_output_without_fallback(
    tmp_path, monkeypatch
):
    explorer = _AppExplorer(project_id="test")
    explorer.output_dir = tmp_path

    async def fake_run(_prompt, _session_dir, _config):
        explorer._last_agent_stats = {
            "tool_calls": 1,
            "browser_tool_calls": 1,
            "successful_browser_tool_calls": 1,
        }
        return "I do not have browser tools, so this is based on prior exploration knowledge."

    monkeypatch.setattr(explorer, "_run_explorer_agent", fake_run)

    result = await explorer.explore(
        _ExplorationConfig(entry_url="https://example.com/custom-start"),
        "session_unverified",
    )

    assert result.status == "failed"
    assert result.pages_discovered == 0
    assert result.flows == []
    assert "live browser tools were unavailable" in (result.error_message or "")


@pytest.mark.asyncio
async def test_explorer_rejects_output_without_successful_browser_tools(
    tmp_path, monkeypatch
):
    explorer = _AppExplorer(project_id="test")
    explorer.output_dir = tmp_path

    async def fake_run(_prompt, _session_dir, _config):
        explorer._last_agent_stats = {
            "tool_calls": 0,
            "browser_tool_calls": 0,
            "successful_browser_tool_calls": 0,
        }
        return """
```json
{"flow": {"name": "Static Browse", "category": "navigation", "steps": [{"action": "navigate"}], "startUrl": "/", "endUrl": "/", "outcome": "Done", "isSuccessPath": true}}
```
"""

    monkeypatch.setattr(explorer, "_run_explorer_agent", fake_run)

    async def no_ai_synthesis(*_args, **_kwargs):
        return []

    monkeypatch.setattr(explorer, "_run_flow_synthesis_pass", no_ai_synthesis)

    result = await explorer.explore(
        _ExplorationConfig(entry_url="https://example.com/custom-start"),
        "session_no_tools",
    )

    assert result.status == "failed"
    assert "did not perform successful live browser exploration" in (
        result.error_message or ""
    )


@pytest.mark.asyncio
async def test_explorer_accepts_verified_browser_output(tmp_path, monkeypatch):
    explorer = _AppExplorer(project_id="test")
    explorer.output_dir = tmp_path

    async def fake_run(_prompt, _session_dir, _config):
        explorer._last_agent_stats = {
            "tool_calls": 2,
            "browser_tool_calls": 2,
            "successful_browser_tool_calls": 2,
        }
        return """
```json
{"page": {"url": "https://example.com/custom-start", "title": "Custom Start", "pageType": "content", "purpose": "Shows custom content", "keyElements": ["Custom page"], "actions": ["Open details"], "forms": [], "links": []}}
```
```json
{"transition": {"sequence": 1, "action": {"type": "navigate", "element": {"role": "page", "name": "Custom"}, "value": "https://example.com/custom-start"}, "before": {"url": "about:blank", "pageType": "blank", "keyElements": []}, "after": {"url": "https://example.com/custom-start", "pageType": "content", "keyElements": ["Custom page"]}, "transitionType": "navigation", "apiCalls": []}}
```
```json
{"flow": {"name": "Custom Start Browse", "category": "navigation", "steps": [{"action": "navigate", "element": "URL", "value": "https://example.com/custom-start"}], "startUrl": "https://example.com/custom-start", "endUrl": "https://example.com/custom-start", "outcome": "Custom page opened", "isSuccessPath": true}}
```
```json
{"summary": {"pagesDiscovered": 1, "flowsDiscovered": 1, "elementsInteracted": 1, "apiEndpointsFound": 0, "issuesFound": 0, "status": "completed"}}
```
"""

    monkeypatch.setattr(explorer, "_run_explorer_agent", fake_run)

    result = await explorer.explore(
        _ExplorationConfig(entry_url="https://example.com/custom-start"),
        "session_verified",
    )

    assert result.status == "completed"
    assert result.pages_discovered == 1
    assert result.pages[0].title == "Custom Start"
    assert [flow.name for flow in result.flows] == ["Custom Start Browse"]
    assert result.quality_summary["source_type"] == SOURCE_OBSERVED
    assert "fallback_used" not in result.quality_summary
    assert (tmp_path / "session_verified" / "pages.json").exists()


@pytest.mark.asyncio
async def test_explorer_accepts_artifact_verified_output_when_queue_telemetry_missing(
    tmp_path, monkeypatch
):
    explorer = _AppExplorer(project_id="test")
    explorer.output_dir = tmp_path

    async def fake_run(_prompt, session_dir, _config):
        explorer._last_agent_stats = {
            "tool_calls": 0,
            "browser_tool_calls": 0,
            "successful_browser_tool_calls": 0,
        }
        artifacts = session_dir / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "page-2026-05-26T18-54-44-400Z.yml").write_text("url: https://example.com/custom-start\n")
        (session_dir / "live-step-001.png").write_bytes(b"png")
        return """
```json
{"page": {"url": "https://example.com/custom-start", "title": "Custom Start", "pageType": "content", "purpose": "Shows custom content", "keyElements": ["Custom page"], "actions": ["Open details"], "forms": [], "links": []}}
```
```json
{"flow": {"name": "Custom Start Browse", "category": "navigation", "steps": [{"action": "navigate", "element": "URL", "value": "https://example.com/custom-start"}], "startUrl": "https://example.com/custom-start", "endUrl": "https://example.com/custom-start", "outcome": "Custom page opened", "isSuccessPath": true}}
```
```json
{"summary": {"pagesDiscovered": 1, "flowsDiscovered": 1, "elementsInteracted": 1, "apiEndpointsFound": 0, "issuesFound": 0, "status": "completed"}}
```
"""

    monkeypatch.setattr(explorer, "_run_explorer_agent", fake_run)

    result = await explorer.explore(
        _ExplorationConfig(entry_url="https://example.com/custom-start"),
        "session_artifact_verified",
    )

    assert result.status == "completed"
    assert result.pages_discovered == 1
    assert [flow.name for flow in result.flows] == ["Custom Start Browse"]
    assert explorer._last_agent_stats["successful_browser_tool_calls"] >= 2
    assert explorer._last_agent_stats["artifact_browser_evidence"] >= 2


@pytest.mark.asyncio
async def test_explorer_marks_budget_stopped_output_as_partial_success(
    tmp_path, monkeypatch
):
    explorer = _AppExplorer(project_id="test")
    explorer.output_dir = tmp_path

    async def fake_run(_prompt, _session_dir, _config):
        explorer._last_agent_stats = {
            "tool_calls": 3,
            "browser_tool_calls": 3,
            "successful_browser_tool_calls": 3,
            "budget_stopped": True,
            "max_browser_tool_calls": 3,
        }
        return """
```json
{"page": {"url": "https://example.com/a", "title": "A", "pageType": "content", "keyElements": ["A"]}}
```
```json
{"transition": {"sequence": 1, "action": {"type": "navigate", "element": {"name": "A"}, "value": "https://example.com/a"}, "before": {"url": "about:blank", "pageType": "blank", "keyElements": []}, "after": {"url": "https://example.com/a", "pageType": "content", "keyElements": ["A"]}, "transitionType": "navigation", "apiCalls": []}}
```
```json
{"summary": {"pagesDiscovered": 1, "flowsDiscovered": 0, "elementsInteracted": 1, "apiEndpointsFound": 0, "issuesFound": 0, "status": "completed"}}
```
"""

    monkeypatch.setattr(explorer, "_run_explorer_agent", fake_run)

    async def no_ai_synthesis(*_args, **_kwargs):
        return []

    monkeypatch.setattr(explorer, "_run_flow_synthesis_pass", no_ai_synthesis)

    result = await explorer.explore(
        _ExplorationConfig(entry_url="https://example.com/a", max_interactions=3),
        "session_budget_partial",
    )

    assert result.status == "completed_partial"
    assert "browser tool budget" in (result.error_message or "")
    assert result.pages_discovered == 1
    assert (tmp_path / "session_budget_partial" / "summary.json").exists()


def test_autopilot_phase_output_guards_empty_spec_generation():
    pipeline = object.__new__(_AutoPilotPipeline)

    assert pipeline._phase_has_resumable_output(
        "spec_generation", {"specs_generated": 1}
    )
    assert not pipeline._phase_has_resumable_output(
        "spec_generation", {"specs_generated": 0}
    )
    assert not pipeline._phase_has_resumable_output(
        "exploration",
        {"exploration_ids": ["static"], "total_pages": 0, "total_flows": 0},
    )
    assert pipeline._phase_has_resumable_output(
        "exploration",
        {"exploration_ids": ["observed"], "total_pages": 1, "total_flows": 0},
    )
    assert (
        pipeline._phase_output_error("spec_generation", {})
        == "Spec generation produced 0 specs"
    )


def test_autopilot_allows_legacy_category_only_validation_failure():
    pipeline = object.__new__(_AutoPilotPipeline)
    summary = {
        "quality": {"quality_score": 78, "source_type": SOURCE_OBSERVED},
        "validation": {
            "valid": False,
            "invalid_records": [
                {
                    "record_type": "flow",
                    "index": 2,
                    "message": "invalid category information-retrieval",
                },
                {
                    "record_type": "flow",
                    "index": 3,
                    "message": "invalid category static-content",
                },
            ],
        },
    }

    assert pipeline._is_legacy_category_validation_only(summary)


def test_autopilot_does_not_allow_legacy_category_override_for_fallback():
    pipeline = object.__new__(_AutoPilotPipeline)
    summary = {
        "quality": {"quality_score": 78, "source_type": "fallback"},
        "validation": {
            "valid": False,
            "invalid_records": [
                {
                    "record_type": "flow",
                    "index": 2,
                    "message": "invalid category information-retrieval",
                },
            ],
        },
    }

    assert not pipeline._is_legacy_category_validation_only(summary)


def test_agent_runner_fails_fast_when_mcp_config_missing(tmp_path):
    runner = _AgentRunner(
        allowed_tools=["mcp__playwright-test__browser_navigate"],
        session_dir=tmp_path,
    )

    with pytest.raises(RuntimeError, match="no .mcp.json exists"):
        runner._validate_mcp_config_for_allowed_tools(tmp_path)


def test_agent_runner_accepts_matching_local_mcp_config(tmp_path):
    mcp_command = tmp_path / "mcp-server-playwright"
    mcp_command.write_text("#!/bin/sh\n")
    (tmp_path / ".mcp.json").write_text(
        """
{
  "mcpServers": {
    "playwright-test": {
      "command": "%s",
      "args": ["--browser", "chromium"]
    }
  }
}
"""
        % str(mcp_command)
    )
    runner = _AgentRunner(
        allowed_tools=["mcp__playwright-test__browser_navigate"],
        session_dir=tmp_path,
    )

    runner._validate_mcp_config_for_allowed_tools(tmp_path)


def test_agent_runner_disables_tools_for_explicit_no_tool_calls():
    runner = _AgentRunner(allowed_tools=[], log_tools=False)

    assert runner._effective_tools() == []
    assert runner._effective_permission_mode() == "dontAsk"

    kwargs = runner._claude_options_kwargs()
    assert kwargs["tools"] == []
    assert kwargs["allowed_tools"] == []
    assert kwargs["permission_mode"] == "dontAsk"


def test_agent_runner_uses_allowed_tools_as_availability_list():
    tools = ["Glob", "Grep", "Read", "LS", "mcp__playwright-test__browser_snapshot"]
    runner = _AgentRunner(allowed_tools=tools, log_tools=False)

    assert runner._effective_tools() == tools
    assert runner._effective_permission_mode() == "bypassPermissions"


def test_agent_runner_attaches_strict_local_mcp_config(tmp_path, monkeypatch):
    mcp_command = tmp_path / "mcp-server-playwright"
    mcp_command.write_text("#!/bin/sh\n")
    (tmp_path / ".mcp.json").write_text(
        """
{
  "mcpServers": {
    "playwright-test": {
      "command": "%s"
    }
  }
}
"""
        % str(mcp_command)
    )
    monkeypatch.chdir(tmp_path)

    runner = _AgentRunner(
        allowed_tools=["mcp__playwright-test__browser_snapshot"],
        log_tools=False,
    )

    kwargs = runner._claude_options_kwargs()
    assert kwargs["mcp_servers"] == tmp_path / ".mcp.json"
    if _agent_runner_module.AgentRunner._claude_options_accepts("strict_mcp_config"):
        assert kwargs["strict_mcp_config"] is True
    else:
        assert kwargs["extra_args"]["strict-mcp-config"] is None


@pytest.mark.asyncio
async def test_agent_runner_tracks_nested_sdk_tool_events(monkeypatch):
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "mcp__playwright-test__browser_navigate",
                        "input": {"url": "https://example.com"},
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "content": "navigated",
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "done"}]},
        },
    ]

    async def fake_query(*args, **kwargs):
        for event in events:
            yield event

    progress = []
    tools = []
    monkeypatch.setattr(_agent_runner_module, "query", fake_query)
    monkeypatch.setattr(_agent_runner_module, "ClaudeAgentOptions", lambda **kwargs: kwargs)
    monkeypatch.setattr(_agent_runner_module, "AGENT_QUEUE_AVAILABLE", False)

    runner = _AgentRunner(
        allowed_tools=[],
        log_tools=False,
        on_tool_use=lambda name, tool_input: tools.append((name, tool_input)),
        on_progress=progress.append,
        inject_memory=False,
        capture_memory=False,
    )

    result = await runner.run("browse")

    assert result.success is True
    assert result.output == "done"
    assert [call.name for call in result.tool_calls] == ["mcp__playwright-test__browser_navigate"]
    assert tools == [("mcp__playwright-test__browser_navigate", {"url": "https://example.com"})]
    assert progress[-1]["tool_calls"] == 1
    assert progress[-1]["browser_tool_calls"] == 1
    assert progress[-1]["last_tool"] == "mcp__playwright-test__browser_navigate"


def test_autopilot_resume_metadata_allows_failed_phase_retry(monkeypatch):
    pytest.importorskip("slowapi")
    from orchestrator.api import autopilot as _autopilot_api
    from orchestrator.api.models_db import AutoPilotSession as _AutoPilotSession

    monkeypatch.setattr(
        _autopilot_api,
        "_get_failed_phase",
        lambda _session, _session_id: "spec_generation",
    )
    _autopilot_api._running_pipelines.clear()
    session = _AutoPilotSession(
        id="autopilot_test", status="failed", current_phase="spec_generation"
    )

    can_resume, reason, failed_phase = _autopilot_api._get_resume_metadata(
        session, session=object()
    )

    assert can_resume is True
    assert failed_phase == "spec_generation"
    assert "spec generation" in reason


def test_autopilot_resume_metadata_rejects_completed_session(monkeypatch):
    pytest.importorskip("slowapi")
    from orchestrator.api import autopilot as _autopilot_api
    from orchestrator.api.models_db import AutoPilotSession as _AutoPilotSession

    monkeypatch.setattr(
        _autopilot_api, "_get_failed_phase", lambda _session, _session_id: None
    )
    session = _AutoPilotSession(id="autopilot_done", status="completed")

    can_resume, reason, failed_phase = _autopilot_api._get_resume_metadata(
        session, session=object()
    )

    assert can_resume is False
    assert reason is None
    assert failed_phase is None


def test_autopilot_live_artifacts_cover_exploration_and_test_run_dirs(
    monkeypatch, tmp_path
):
    pytest.importorskip("slowapi")
    from orchestrator.api import autopilot as _autopilot_api

    runs_dir = tmp_path / "runs"
    exploration_artifacts = runs_dir / "explorations" / "explore_live" / "artifacts"
    test_artifacts = runs_dir / "run_live" / "artifacts"
    exploration_artifacts.mkdir(parents=True)
    test_artifacts.mkdir(parents=True)
    (exploration_artifacts / "live-step-001.png").write_text("png")
    (test_artifacts / "trace.webm").write_text("webm")

    monkeypatch.setattr(_autopilot_api, "RUNS_DIR", runs_dir)

    artifacts = _autopilot_api._collect_live_artifacts(
        exploration_session_id="explore_live",
        run_id="run_live",
    )

    paths = {artifact.path for artifact in artifacts}
    assert "/artifacts/explorations/explore_live/artifacts/live-step-001.png" in paths
    assert "/artifacts/run_live/artifacts/trace.webm" in paths
    assert artifacts[0].type == "image"


def test_autopilot_live_state_merges_agent_queue_progress(monkeypatch):
    slowapi_stub = types.ModuleType("slowapi")
    slowapi_errors_stub = types.ModuleType("slowapi.errors")
    slowapi_util_stub = types.ModuleType("slowapi.util")

    class _Limiter:
        def __init__(self, *args, **kwargs):
            pass

    class _RateLimitExceeded(Exception):
        pass

    slowapi_stub.Limiter = _Limiter
    slowapi_errors_stub.RateLimitExceeded = _RateLimitExceeded
    slowapi_util_stub.get_remote_address = lambda request: "127.0.0.1"
    monkeypatch.setitem(sys.modules, "slowapi", slowapi_stub)
    monkeypatch.setitem(sys.modules, "slowapi.errors", slowapi_errors_stub)
    monkeypatch.setitem(sys.modules, "slowapi.util", slowapi_util_stub)

    from orchestrator.api import autopilot as _autopilot_api
    from orchestrator.services import agent_queue as _agent_queue

    class _FakeTask:
        telemetry = {}

    class _FakeQueue:
        async def connect(self):
            return None

        async def get_task_progress(self, task_id):
            assert task_id == "agent-live"
            return {
                "phase": "tool_use",
                "message": "Using browser click",
                "tool_calls": 4,
                "browser_tool_calls": 3,
                "interactions": 2,
                "last_tool": "mcp__playwright-test__browser_click",
                "updated_at": "2026-05-25T12:00:00",
            }

        async def get_task(self, task_id):
            assert task_id == "agent-live"
            return _FakeTask()

    monkeypatch.setattr(_agent_queue, "REDIS_AVAILABLE", True)
    monkeypatch.setattr(_agent_queue, "get_agent_queue", lambda: _FakeQueue())

    live = asyncio.run(
        _autopilot_api._merge_live_agent_progress(
            {
                "agent_task_id": "agent-live",
                "tool_calls": 0,
                "browser_tool_calls": 0,
                "interactions": 0,
            }
        )
    )

    assert live["tool_calls"] == 4
    assert live["browser_tool_calls"] == 3
    assert live["interactions"] == 2
    assert live["last_tool_label"] == "browser click"
    assert live["recent_tools"][-1]["name"] == "mcp__playwright-test__browser_click"


def test_autopilot_stale_live_state_detects_terminal_agent_task(monkeypatch):
    slowapi_stub = types.ModuleType("slowapi")
    slowapi_errors_stub = types.ModuleType("slowapi.errors")
    slowapi_util_stub = types.ModuleType("slowapi.util")

    class _Limiter:
        def __init__(self, *args, **kwargs):
            pass

    class _RateLimitExceeded(Exception):
        pass

    slowapi_stub.Limiter = _Limiter
    slowapi_errors_stub.RateLimitExceeded = _RateLimitExceeded
    slowapi_util_stub.get_remote_address = lambda request: "127.0.0.1"
    monkeypatch.setitem(sys.modules, "slowapi", slowapi_stub)
    monkeypatch.setitem(sys.modules, "slowapi.errors", slowapi_errors_stub)
    monkeypatch.setitem(sys.modules, "slowapi.util", slowapi_util_stub)

    from orchestrator.api import autopilot as _autopilot_api
    from orchestrator.api.models_db import AutoPilotSession as _AutoPilotSession
    from orchestrator.services import agent_queue as _agent_queue

    class _FakeQueue:
        async def connect(self):
            return None

        async def get_task(self, task_id):
            assert task_id == "agent-stale"
            return SimpleNamespace(status=SimpleNamespace(value="failed"))

    monkeypatch.setattr(_agent_queue, "REDIS_AVAILABLE", True)
    monkeypatch.setattr(_agent_queue, "get_agent_queue", lambda: _FakeQueue())
    monkeypatch.setattr(_autopilot_api, "find_session_processes", lambda _session_id: [])

    session = _AutoPilotSession(
        id="autopilot_2026-05-25_16-33-34",
        status="running",
    )
    session.config = {
        "live_browser": {
            "active": True,
            "agent_task_id": "agent-stale",
            "updated_at": "2026-05-25T12:00:00",
        }
    }

    assert (
        asyncio.run(
            _autopilot_api._is_stale_live_browser_async(
                session,
                now=datetime(2026, 5, 25, 12, 3, 0),
            )
        )
        is True
    )


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
