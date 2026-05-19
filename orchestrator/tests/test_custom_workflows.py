import uuid

import pytest
from sqlmodel import Session, SQLModel, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import WorkflowDefinition, WorkflowRun, WorkflowRunStep
from orchestrator.services.workflow_runner import (
    create_workflow_run_steps,
    duplicate_workflow_definition_record,
    reset_workflow_run_for_step_retry,
    validate_workflow_steps,
)


def _ensure_tables() -> None:
    SQLModel.metadata.create_all(engine)


def _definition_steps() -> list[dict]:
    return validate_workflow_steps(
        [
            {"key": "first", "type": "review_gate", "input": {"question": "First?"}},
            {"key": "second", "type": "review_gate", "input": {"question": "Second?"}},
            {"key": "third", "type": "review_gate", "input": {"question": "Third?"}},
        ]
    )


def _create_definition(session: Session, *, name: str | None = None) -> WorkflowDefinition:
    definition = WorkflowDefinition(
        name=name or f"Workflow {uuid.uuid4()}",
        description="Test workflow",
    )
    definition.steps = _definition_steps()
    session.add(definition)
    session.commit()
    session.refresh(definition)
    return definition


def test_validate_workflow_steps_normalizes_review_gate():
    steps = validate_workflow_steps(
        [
            {
                "key": "approval",
                "type": "review_gate",
                "input": {"question": "Continue?"},
            }
        ]
    )

    assert steps == [
        {
            "key": "approval",
            "type": "review_gate",
            "label": "Review Gate",
            "input": {"question": "Continue?"},
            "continue_on_error": False,
        }
    ]


def test_validate_workflow_steps_rejects_inline_secret_values():
    with pytest.raises(ValueError, match="Do not store secrets"):
        validate_workflow_steps(
            [
                {
                    "key": "autopilot",
                    "type": "start_autopilot",
                    "input": {
                        "entry_urls": ["https://example.com"],
                        "credentials": {"password": "plaintext"},
                    },
                }
            ]
        )


def test_validate_workflow_steps_requires_supported_type_and_inputs():
    with pytest.raises(ValueError, match="Unsupported workflow step type"):
        validate_workflow_steps([{"key": "bad", "type": "unknown", "input": {}}])

    with pytest.raises(ValueError, match="missing required"):
        validate_workflow_steps([{"key": "run", "type": "run_spec", "input": {}}])


@pytest.mark.parametrize(
    "steps",
    [
        [
            {"key": "explore", "type": "start_exploration", "input": {"entry_url": "https://example.com", "max_interactions": 30}},
            {"key": "wait_explore", "type": "wait_for_status", "input": {"source_step": "explore", "timeout_seconds": 3600, "poll_seconds": 10}},
            {"key": "requirements", "type": "generate_requirements", "input": {"exploration_session_id": "{{steps.explore.external_id}}"}},
            {"key": "wait_requirements", "type": "wait_for_status", "input": {"source_step": "requirements", "timeout_seconds": 1800, "poll_seconds": 10}},
            {"key": "review", "type": "review_gate", "input": {"question": "Review requirements?", "suggested_answers": ["Continue"]}},
        ],
        [
            {"key": "bulk_specs", "type": "generate_specs_from_requirements", "input": {"target_url": "https://example.com"}},
            {"key": "wait_specs", "type": "wait_for_status", "input": {"source_step": "bulk_specs", "timeout_seconds": 3600, "poll_seconds": 10}},
            {"key": "review", "type": "review_gate", "input": {"question": "Review generated specs?"}},
        ],
        [
            {"key": "spec_run", "type": "run_spec", "input": {"spec_name": "examples/hello-world.md"}},
            {"key": "wait_spec_run", "type": "wait_for_status", "input": {"source_step": "spec_run", "timeout_seconds": 1800, "poll_seconds": 10}},
            {"key": "review", "type": "review_gate", "input": {"question": "Review spec run?"}},
        ],
        [
            {"key": "regression", "type": "run_regression_batch", "input": {"browser": "chromium", "automated_only": True}},
            {"key": "wait_regression", "type": "wait_for_status", "input": {"source_step": "regression", "timeout_seconds": 7200, "poll_seconds": 15}},
            {"key": "review", "type": "review_gate", "input": {"question": "Review regression?"}},
        ],
    ],
)
def test_validate_workflow_steps_accepts_qa_template_shapes(steps):
    normalized = validate_workflow_steps(steps)

    assert [step["key"] for step in normalized] == [step["key"] for step in steps]
    assert all("label" in step for step in normalized)


def test_create_workflow_run_steps_can_start_from_specific_step():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="queued")
        session.add(run)
        session.commit()
        session.refresh(run)

        start_index = create_workflow_run_steps(session, definition, run, start_step_key="second")

        steps = session.exec(
            select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id).order_by(WorkflowRunStep.step_order)
        ).all()
        session.refresh(run)

    assert start_index == 1
    assert [step.status for step in steps] == ["skipped", "pending", "pending"]
    assert run.current_step_index == 1
    assert run.progress == pytest.approx(1 / 3)


def test_create_workflow_run_steps_rejects_unknown_start_step():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="queued")
        session.add(run)
        session.commit()
        session.refresh(run)

        with pytest.raises(ValueError, match="Workflow step not found"):
            create_workflow_run_steps(session, definition, run, start_step_key="missing")


def test_reset_workflow_run_for_step_retry_preserves_prior_completed_context():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="queued")
        session.add(run)
        session.commit()
        session.refresh(run)
        create_workflow_run_steps(session, definition, run)
        steps = session.exec(
            select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id).order_by(WorkflowRunStep.step_order)
        ).all()
        steps[0].status = "completed"
        steps[0].output = {"external_kind": "review_gate", "answer": "yes"}
        steps[0].completed_at = steps[0].updated_at
        steps[1].status = "failed"
        steps[1].error_message = "boom"
        steps[1].external_kind = "review_gate"
        steps[1].external_id = "failed-external"
        run.status = "failed"
        run.error_message = "boom"
        run.result = {"stale": True}
        run.completed_at = run.updated_at
        run.context = {"steps": {"first": steps[0].output or {}, "second": {"stale": True}}}
        for step in steps:
            session.add(step)
        session.add(run)
        session.commit()

        reset_workflow_run_for_step_retry(session, run, steps[1])
        refreshed_steps = session.exec(
            select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id).order_by(WorkflowRunStep.step_order)
        ).all()
        session.refresh(run)

    assert [step.status for step in refreshed_steps] == ["completed", "pending", "pending"]
    assert refreshed_steps[1].error_message is None
    assert refreshed_steps[1].external_kind is None
    assert run.status == "queued"
    assert run.error_message is None
    assert run.result is None
    assert run.context == {"steps": {"first": {"external_kind": "review_gate", "answer": "yes"}}}


def test_reset_workflow_run_for_step_retry_rejects_non_failed_state():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session)
        run = WorkflowRun(definition_id=definition.id, project_id=definition.project_id, status="queued")
        session.add(run)
        session.commit()
        session.refresh(run)
        create_workflow_run_steps(session, definition, run)
        step = session.exec(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id)).first()

        with pytest.raises(ValueError, match="Only failed workflow runs"):
            reset_workflow_run_for_step_retry(session, run, step)


def test_duplicate_workflow_definition_record_copies_active_definition():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session, name=f"Duplicate Source {uuid.uuid4()}")
        definition_id = definition.id
        expected_name = definition.name
        expected_description = definition.description
        expected_steps = definition.steps

        clone = duplicate_workflow_definition_record(definition, created_by="user-1")
        session.add(clone)
        session.commit()
        session.refresh(clone)

    assert clone.id != definition_id
    assert clone.name == f"{expected_name} Copy"
    assert clone.description == expected_description
    assert clone.status == "active"
    assert clone.created_by == "user-1"
    assert clone.steps == expected_steps


def test_active_workflow_definition_query_hides_archived_by_default():
    _ensure_tables()
    with Session(engine) as session:
        definition = _create_definition(session, name=f"Archived {uuid.uuid4()}")
        definition_id = definition.id
        definition.status = "archived"
        session.add(definition)
        session.commit()

        listed = session.exec(select(WorkflowDefinition).where(WorkflowDefinition.status == "active")).all()

    assert all(item.id != definition_id for item in listed)
