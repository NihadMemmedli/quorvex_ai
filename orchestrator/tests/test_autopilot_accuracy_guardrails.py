import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import Session, SQLModel, select

from orchestrator.api import db as db_module
from orchestrator.api.db import engine
from orchestrator.api.models_db import AutoPilotSpecTask, AutoPilotTestTask, Project, Requirement, RtmEntry
from orchestrator.memory.exploration_store import get_exploration_store
from orchestrator.utils.agent_runner import AgentResult, ToolCall
from orchestrator.workflows.autopilot_pipeline import AutoPilotConfig, AutoPilotPipeline
from orchestrator.workflows.requirements_generator import RequirementsGenerator
from orchestrator.workflows.rtm_generator import RtmGenerator
from orchestrator.workflows.spec_scenario_builder import E2EScenario


def _ensure_tables() -> None:
    SQLModel.metadata.create_all(engine, checkfirst=True)
    db_module._run_migrations()


def test_requirements_parser_rejects_schema_invalid_or_unbacked_items():
    generator = RequirementsGenerator(project_id="default")

    parsed = generator._parse_requirements_response(
        json.dumps(
            {
                "requirements": [
                    {
                        "title": "Checkout accepts saved cart",
                        "description": "The system shall let users check out a saved cart.",
                        "category": "checkout",
                        "priority": "urgent",
                        "acceptance_criteria": ["Checkout confirmation is shown."],
                        "source_flows": ["Checkout flow"],
                        "confidence": 0.91,
                    },
                    {
                        "title": "Invented behavior",
                        "description": "No evidence is attached.",
                        "acceptance_criteria": ["Something happens."],
                    },
                    {
                        "title": "",
                        "description": "Missing title.",
                        "source_flows": ["Flow"],
                    },
                ]
            }
        )
    )

    assert len(parsed) == 1
    assert parsed[0].title == "Checkout accepts saved cart"
    assert parsed[0].category == "other"
    assert parsed[0].priority == "medium"


def test_selected_verification_requires_successful_navigate_and_snapshot():
    generator = RequirementsGenerator(project_id="default")
    good = AgentResult(
        success=True,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__browser_navigate",
                timestamp=datetime.now(),
                success=True,
                input={"url": "https://example.test/app"},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_snapshot",
                timestamp=datetime.now(),
                success=True,
                input={},
            ),
        ],
    )
    no_snapshot = AgentResult(
        success=True,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__browser_navigate",
                timestamp=datetime.now(),
                success=True,
                input={"url": "https://example.test/app"},
            )
        ],
    )
    failed_navigation = AgentResult(
        success=True,
        tool_calls=[
            ToolCall(
                name="mcp__playwright-test__browser_navigate",
                timestamp=datetime.now(),
                success=False,
                input={"url": "https://example.test/app"},
            ),
            ToolCall(
                name="mcp__playwright-test__browser_snapshot",
                timestamp=datetime.now(),
                success=True,
                input={},
            ),
        ],
    )

    assert generator._verification_has_browser_evidence(good, "https://example.test/app/")
    assert not generator._verification_has_browser_evidence(no_snapshot, "https://example.test/app")
    assert not generator._verification_has_browser_evidence(failed_navigation, "https://example.test/app")


def test_spec_task_metadata_renders_evidence_and_test_data_refs():
    pipeline = AutoPilotPipeline(session_id="guardrail-render", project_id="default")
    scenario = E2EScenario(
        title="Checkout",
        description="Validate checkout.",
        steps=["Navigate to checkout"],
        expected_outcomes=["Checkout renders."],
    )

    pipeline._apply_spec_task_evidence_to_scenario(
        scenario,
        evidence_metadata={
            "source_session_id": "explore-123",
            "source_flows": ["Checkout flow"],
            "source_api_endpoints": ["/api/checkout"],
            "evidence_refs": ["evidence:checkout:flow:Checkout flow"],
            "target_url": "https://example.test/checkout",
            "confidence": 0.82,
            "readiness": "ready",
            "test_data_refs": ["checkout.valid-user"],
        },
        config=AutoPilotConfig(entry_urls=["https://example.test"]),
    )

    assert '@testdata "checkout.valid-user"' in scenario.test_data
    assert "Target URL: https://example.test/checkout" in scenario.test_data
    assert "Source exploration session: explore-123" in scenario.source_notes
    assert "Observed API endpoint(s): /api/checkout" in scenario.source_notes


def test_spec_task_promotion_gate_blocks_weak_or_blocked_tasks():
    pipeline = AutoPilotPipeline(session_id="guardrail-gate", project_id="default")

    ok, reason = pipeline._spec_task_promotion_gate(
        SimpleNamespace(
            evidence_metadata={
                "source_session_id": "explore-1",
                "target_url": "https://example.test",
                "confidence": 0.75,
                "readiness": "ready",
            }
        )
    )
    assert ok is True
    assert reason == ""

    ok, reason = pipeline._spec_task_promotion_gate(
        SimpleNamespace(
            evidence_metadata={
                "source_session_id": "explore-1",
                "target_url": "https://example.test",
                "confidence": 0.31,
                "readiness": "ready",
            }
        )
    )
    assert ok is False
    assert "confidence" in reason

    ok, reason = pipeline._spec_task_promotion_gate(
        SimpleNamespace(
            evidence_metadata={
                "source_session_id": "explore-1",
                "confidence": 0.8,
                "readiness": "blocked",
            }
        )
    )
    assert ok is False
    assert "readiness=blocked" in reason


def test_autopilot_spec_task_evidence_metadata_persists():
    _ensure_tables()
    session_id = "guardrail-metadata"
    with Session(engine) as db:
        for row in db.exec(
            select(AutoPilotSpecTask).where(AutoPilotSpecTask.session_id == session_id)
        ).all():
            db.delete(row)
        task = AutoPilotSpecTask(
            session_id=session_id,
            requirement_title="Checkout",
            priority="high",
        )
        task.evidence_metadata = {
            "source_session_id": "explore-1",
            "target_url": "https://example.test/checkout",
            "test_data_refs": ["checkout.valid-user"],
        }
        db.add(task)
        db.commit()
        task_id = task.id

    with Session(engine) as db:
        loaded = db.get(AutoPilotSpecTask, task_id)
        assert loaded.evidence_metadata["source_session_id"] == "explore-1"
        assert loaded.evidence_metadata["test_data_refs"] == ["checkout.valid-user"]


def test_rtm_generation_clears_only_current_spec_paths(tmp_path: Path):
    _ensure_tables()
    project_id = "guardrail-rtm"
    with Session(engine) as db:
        if not db.get(Project, project_id):
            db.add(Project(id=project_id, name="Guardrail RTM"))
            db.commit()
        for entry in db.exec(select(RtmEntry).where(RtmEntry.project_id == project_id)).all():
            db.delete(entry)
        for req in db.exec(select(Requirement).where(Requirement.project_id == project_id)).all():
            db.delete(req)
        db.commit()

    store = get_exploration_store(project_id=project_id)
    req = store.store_requirement(
        req_code="REQ-001",
        title="Checkout",
        category="checkout",
        description="Checkout can complete.",
        priority="high",
        acceptance_criteria=["Order confirmation appears."],
    )
    store.store_rtm_entry(
        requirement_id=req.id,
        test_spec_name="old-current",
        test_spec_path=str(tmp_path / "current.md"),
        mapping_type="partial",
        confidence=0.6,
    )
    store.store_rtm_entry(
        requirement_id=req.id,
        test_spec_name="unrelated",
        test_spec_path=str(tmp_path / "unrelated.md"),
        mapping_type="full",
        confidence=0.9,
    )

    current_spec = tmp_path / "current.md"
    current_spec.write_text(
        "# Test: Checkout\n\n## Steps\n1. Complete checkout\n\n## Expected Outcome\n- Order confirmation appears\n"
    )

    generator = RtmGenerator(project_id=project_id)
    result = __import__("asyncio").run(
        generator.generate_rtm(specs_paths=[str(current_spec)], use_ai_matching=False)
    )

    with Session(engine) as db:
        entries = db.exec(select(RtmEntry).where(RtmEntry.project_id == project_id)).all()
    unrelated = [entry for entry in entries if entry.test_spec_name == "unrelated"]
    current = [entry for entry in entries if entry.test_spec_path == str(current_spec)]
    assert unrelated
    assert current
    assert result.mappings


@pytest.mark.asyncio
async def test_test_generation_runtime_preflight_blocks_task_creation(monkeypatch, tmp_path: Path):
    _ensure_tables()
    session_id = "guardrail-runtime-preflight"
    spec_path = tmp_path / "protected-route.md"
    spec_path.write_text(
        "# Test Plan: Protected route\n\n"
        "### TC-001: Protected route redirects\n"
        "**Description:** Unauthenticated users are blocked.\n"
        "**Preconditions:** None.\n"
        "**Steps:**\n"
        "1. Navigate to https://example.test/operator/profile.\n"
        "**Expected Result:** The login page is visible.\n"
    )

    with Session(engine) as db:
        for model in (AutoPilotTestTask, AutoPilotSpecTask):
            for row in db.exec(select(model).where(model.session_id == session_id)).all():
                db.delete(row)
        db.add(
            AutoPilotSpecTask(
                session_id=session_id,
                requirement_title="Protected route",
                priority="high",
                status="completed",
                spec_name="protected-route",
                spec_path=str(spec_path),
            )
        )
        db.commit()

    async def fake_preflight(**_kwargs):
        return {
            "ready": False,
            "status": "runtime_failed",
            "errors": ["No live-browser-capable agent worker is available."],
            "checks": {"agent_queue": {"live_browser_worker_count": 0}},
        }

    pipeline = AutoPilotPipeline(session_id=session_id, project_id="default")
    monkeypatch.setattr(pipeline, "_preflight_test_generation_runtime", fake_preflight)

    result = await pipeline._run_test_generation_phase(
        AutoPilotConfig(entry_urls=["https://example.test"], project_id="default"),
        phase_id=0,
    )

    assert result["status"] == "runtime_failed"
    with Session(engine) as db:
        test_tasks = db.exec(
            select(AutoPilotTestTask).where(AutoPilotTestTask.session_id == session_id)
        ).all()
    assert test_tasks == []


@pytest.mark.asyncio
async def test_test_generation_planner_smoke_requires_live_tool_evidence(
    monkeypatch, tmp_path: Path
):
    pipeline = AutoPilotPipeline(session_id="guardrail-smoke", project_id="default")

    monkeypatch.setattr(
        "orchestrator.utils.agent_tool_allowlists.get_agent_tool_config",
        lambda *_args, **_kwargs: {
            "allowed_tools": ["mcp__playwright-test__planner_setup_page"],
            "tools": [],
            "disallowed_tools": [],
        },
    )

    async def fake_run_success(self, prompt):
        return AgentResult(
            success=True,
            output="runtime_smoke: passed",
            messages_received=1,
            tool_calls=[
                ToolCall(
                    name="mcp__playwright-test__planner_setup_page",
                    timestamp=datetime.now(),
                    input={},
                ),
                ToolCall(
                    name="mcp__playwright-test__browser_navigate",
                    timestamp=datetime.now(),
                    input={"url": "https://example.test"},
                ),
                ToolCall(
                    name="mcp__playwright-test__browser_snapshot",
                    timestamp=datetime.now(),
                    input={},
                ),
                ToolCall(
                    name="mcp__playwright-test__planner_save_plan",
                    timestamp=datetime.now(),
                    input={"content": "# Smoke"},
                ),
            ],
        )

    monkeypatch.setattr("orchestrator.utils.agent_runner.AgentRunner.run", fake_run_success)
    ok = await pipeline._run_test_generation_planner_smoke(
        preflight_dir=tmp_path,
        target_url="https://example.test",
    )
    assert ok["ready"] is True
    assert ok["sdk_first_message_received"] is True
    assert ok["missing_tools"] == []

    async def fake_run_missing_snapshot(self, prompt):
        return AgentResult(
            success=True,
            output="runtime_smoke: passed",
            messages_received=1,
            tool_calls=[
                ToolCall(
                    name="mcp__playwright-test__planner_setup_page",
                    timestamp=datetime.now(),
                    input={},
                ),
                ToolCall(
                    name="mcp__playwright-test__browser_navigate",
                    timestamp=datetime.now(),
                    input={"url": "https://example.test"},
                ),
                ToolCall(
                    name="mcp__playwright-test__planner_save_plan",
                    timestamp=datetime.now(),
                    input={"content": "# Smoke"},
                ),
            ],
        )

    monkeypatch.setattr(
        "orchestrator.utils.agent_runner.AgentRunner.run",
        fake_run_missing_snapshot,
    )
    failed = await pipeline._run_test_generation_planner_smoke(
        preflight_dir=tmp_path,
        target_url="https://example.test",
    )
    assert failed["ready"] is False
    assert failed["missing_tools"] == ["browser_snapshot"]
