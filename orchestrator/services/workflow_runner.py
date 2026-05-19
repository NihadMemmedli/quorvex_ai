"""Runner for user-defined custom workflows."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import WorkflowDefinition, WorkflowRun, WorkflowRunStep

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_STATUSES = {"queued", "running", "awaiting_input", "paused"}
SECRET_RE = re.compile(r"(password|token|secret|api[_-]?key|authorization|credential)", re.IGNORECASE)
TEMPLATE_RE = re.compile(r"{{\s*([^{}]+?)\s*}}")

STEP_CATALOG: dict[str, dict[str, Any]] = {
    "start_autopilot": {
        "label": "Start Auto Pilot",
        "description": "Start the existing Auto Pilot pipeline.",
        "required": ["entry_urls"],
        "external_kind": "autopilot",
    },
    "start_exploration": {
        "label": "Start Exploration",
        "description": "Start an exploration session.",
        "required": ["entry_url"],
        "external_kind": "exploration",
    },
    "generate_requirements": {
        "label": "Generate Requirements",
        "description": "Generate requirements from an exploration session.",
        "required": ["exploration_session_id"],
        "external_kind": "requirements_job",
    },
    "generate_specs_from_requirements": {
        "label": "Generate Specs From Requirements",
        "description": "Bulk-generate specs for uncovered requirements.",
        "required": ["target_url"],
        "external_kind": "bulk_specs_job",
    },
    "run_spec": {
        "label": "Run Spec",
        "description": "Run one saved spec.",
        "required": ["spec_name"],
        "external_kind": "test_run",
    },
    "run_regression_batch": {
        "label": "Run Regression Batch",
        "description": "Run a regression batch.",
        "required": [],
        "external_kind": "regression_batch",
    },
    "start_custom_agent": {
        "label": "Start Custom Agent",
        "description": "Start a saved custom agent definition.",
        "required": ["definition_id", "prompt"],
        "external_kind": "agent_run",
    },
    "wait_for_status": {
        "label": "Wait For Status",
        "description": "Wait for a previously started child job to finish.",
        "required": ["source_step"],
    },
    "review_gate": {
        "label": "Review Gate",
        "description": "Pause until the user resumes the workflow.",
        "required": ["question"],
    },
}


def workflow_step_catalog() -> list[dict[str, Any]]:
    return [{"type": step_type, **config} for step_type, config in STEP_CATALOG.items()]


def validate_workflow_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not steps:
        raise ValueError("Workflow must include at least one step")
    if len(steps) > 50:
        raise ValueError("Workflow can include at most 50 steps")

    normalized: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for index, raw in enumerate(steps):
        if not isinstance(raw, dict):
            raise ValueError(f"Step {index + 1} must be an object")
        step_type = str(raw.get("type") or "").strip()
        if step_type not in STEP_CATALOG:
            raise ValueError(f"Unsupported workflow step type: {step_type or '(missing)'}")

        key = str(raw.get("key") or f"step_{index + 1}").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            raise ValueError(f"Step key must use letters, numbers, dashes, or underscores: {key}")
        if key in seen_keys:
            raise ValueError(f"Duplicate step key: {key}")
        seen_keys.add(key)

        inputs = raw.get("input") or raw.get("inputs") or {}
        if not isinstance(inputs, dict):
            raise ValueError(f"Step {key} input must be an object")
        _reject_inline_secrets(inputs, path=f"steps.{key}.input")

        missing = [name for name in STEP_CATALOG[step_type]["required"] if inputs.get(name) in (None, "")]
        if missing:
            raise ValueError(f"Step {key} missing required input(s): {', '.join(missing)}")

        normalized.append(
            {
                "key": key,
                "type": step_type,
                "label": str(raw.get("label") or STEP_CATALOG[step_type]["label"]),
                "input": inputs,
                "continue_on_error": bool(raw.get("continue_on_error", False)),
            }
        )
    return normalized


def _reject_inline_secrets(value: Any, *, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if SECRET_RE.search(str(key)) and child not in (None, "", False):
                raise ValueError(f"Do not store secrets in workflow definitions: {child_path}")
            _reject_inline_secrets(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_inline_secrets(child, path=f"{path}[{index}]")


def create_workflow_run_steps(
    session: Session,
    definition: WorkflowDefinition,
    run: WorkflowRun,
    *,
    start_step_key: str | None = None,
) -> int:
    start_index = 0
    if start_step_key:
        matching_indexes = [index for index, step in enumerate(definition.steps) if step.get("key") == start_step_key]
        if not matching_indexes:
            raise ValueError(f"Workflow step not found: {start_step_key}")
        start_index = matching_indexes[0]

    now = datetime.utcnow()
    for index, step in enumerate(definition.steps):
        run_step = WorkflowRunStep(
            run_id=run.id,
            definition_id=definition.id,
            workflow_id=definition.id,
            step_index=index,
            step_order=index,
            step_id=step["key"],
            step_key=step["key"],
            step_type=step["type"],
            name=step["label"],
            label=step["label"],
            continue_on_error=bool(step.get("continue_on_error", False)),
        )
        run_step.input = step.get("input") or {}
        if index < start_index:
            run_step.status = "skipped"
            run_step.output = {"skipped": True, "reason": "run_started_from_later_step"}
            run_step.completed_at = now
            run_step.updated_at = now
        session.add(run_step)
    run.current_step_index = start_index
    run.progress = start_index / max(len(definition.steps), 1)
    run.updated_at = now
    session.add(run)
    session.commit()
    return start_index


def duplicate_workflow_definition_record(
    definition: WorkflowDefinition,
    *,
    created_by: str | None = None,
) -> WorkflowDefinition:
    clone = WorkflowDefinition(
        project_id=definition.project_id,
        name=f"{definition.name} Copy",
        description=definition.description,
        created_by=created_by,
    )
    clone.steps = validate_workflow_steps(definition.steps)
    return clone


def reset_workflow_run_for_step_retry(session: Session, run: WorkflowRun, step: WorkflowRunStep) -> None:
    if run.status != "failed":
        raise ValueError("Only failed workflow runs can retry a step")
    if step.run_id != run.id:
        raise ValueError("Workflow step does not belong to this run")
    if step.status != "failed":
        raise ValueError("Only failed workflow steps can be retried")

    steps = session.exec(
        select(WorkflowRunStep).where(WorkflowRunStep.run_id == run.id).order_by(WorkflowRunStep.step_order)
    ).all()
    now = datetime.utcnow()
    for candidate in steps:
        if candidate.step_order < step.step_order or candidate.status == "skipped":
            continue
        candidate.status = "pending"
        candidate.output = None
        candidate.error_message = None
        candidate.external_kind = None
        candidate.external_id = None
        candidate.started_at = None
        candidate.completed_at = None
        candidate.updated_at = now
        session.add(candidate)

    run.status = "queued"
    run.current_step_index = step.step_order
    run.progress = step.step_order / max(len(steps), 1)
    run.error_message = None
    run.result = None
    run.completed_at = None
    run.context = _context_for_completed_steps(steps, before_order=step.step_order)
    run.updated_at = now
    session.add(run)
    session.commit()


async def launch_workflow_run(run_id: str) -> None:
    task = asyncio.create_task(run_workflow(run_id))
    task.add_done_callback(_log_task_exception)


def _log_task_exception(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Workflow runner task failed")


async def run_workflow(run_id: str) -> None:
    while True:
        with Session(engine) as session:
            run = session.get(WorkflowRun, run_id)
            if not run or run.status in TERMINAL_STATUSES:
                return
            if run.status == "paused":
                return
            definition = session.get(WorkflowDefinition, run.definition_id)
            if not definition:
                _fail_run(session, run, "Workflow definition not found")
                return
            steps = session.exec(
                select(WorkflowRunStep)
                .where(WorkflowRunStep.run_id == run_id)
                .order_by(WorkflowRunStep.step_order)
            ).all()
            next_step = next((step for step in steps if step.status in {"pending", "running"}), None)
            if not next_step:
                if any(step.status == "awaiting_input" for step in steps):
                    run.status = "awaiting_input"
                    run.updated_at = datetime.utcnow()
                    session.add(run)
                    session.commit()
                    return
                run.status = "completed"
                run.progress = 1.0
                run.completed_at = datetime.utcnow()
                run.updated_at = datetime.utcnow()
                run.result = {"steps": {step.step_key: step.output for step in steps}}
                session.add(run)
                session.commit()
                return
            next_step_id = next_step.id
            if run.status in {"queued", "awaiting_input"}:
                run.status = "running"
            run.started_at = run.started_at or datetime.utcnow()
            run.current_step_index = next_step.step_order
            run.progress = next_step.step_order / max(len(steps), 1)
            run.updated_at = datetime.utcnow()
            session.add(run)
            session.commit()

        try:
            await _execute_step(run_id, next_step_id)
        except Exception as exc:
            logger.exception("Workflow step failed")
            with Session(engine) as session:
                step = session.get(WorkflowRunStep, next_step_id)
                run = session.get(WorkflowRun, run_id)
                if not run or not step:
                    return
                step.status = "failed"
                step.error_message = str(exc)
                step.completed_at = datetime.utcnow()
                step.updated_at = datetime.utcnow()
                session.add(step)
                if step.continue_on_error:
                    session.commit()
                    continue
                _fail_run(session, run, str(exc))
                return


async def _execute_step(run_id: str, step_id: int | None) -> None:
    if step_id is None:
        return
    with Session(engine) as session:
        step = session.get(WorkflowRunStep, step_id)
        run = session.get(WorkflowRun, run_id)
        if not step or not run or run.status in TERMINAL_STATUSES:
            return
        if run.status == "paused":
            return
        context = _build_context(session, run_id, run)
        rendered_input = _render_templates(copy.deepcopy(step.input), context)
        step_type = step.step_type
        run_project_id = run.project_id
        step.status = "running"
        step.started_at = step.started_at or datetime.utcnow()
        step.updated_at = datetime.utcnow()
        session.add(step)
        session.commit()

    result = await _dispatch_step(step_type, rendered_input, run_project_id, context)

    with Session(engine) as session:
        step = session.get(WorkflowRunStep, step_id)
        run = session.get(WorkflowRun, run_id)
        if not step or not run:
            return
        if result.get("awaiting_input"):
            step.status = "awaiting_input"
            step.output = result
            run.status = "awaiting_input"
        else:
            step.status = "completed"
            step.output = result
            step.external_kind = result.get("external_kind")
            step.external_id = result.get("external_id")
            step.completed_at = datetime.utcnow()
            run.context = _merge_step_output(run.context, step.step_key, result)
        step.updated_at = datetime.utcnow()
        run.progress = (step.step_order + 1) / max(_step_count(session, run_id), 1)
        run.updated_at = datetime.utcnow()
        session.add(step)
        session.add(run)
        session.commit()


async def _dispatch_step(
    step_type: str,
    data: dict[str, Any],
    project_id: str | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    if step_type == "review_gate":
        return {
            "awaiting_input": True,
            "question": data.get("question"),
            "suggested_answers": data.get("suggested_answers") or [],
            "external_kind": "review_gate",
        }
    if step_type == "wait_for_status":
        return await _wait_for_status(data, context)
    if step_type == "start_autopilot":
        return await _post_json(
            "/autopilot/start",
            {**data, "project_id": project_id or data.get("project_id") or "default"},
            expected_kind="autopilot",
        )
    if step_type == "start_exploration":
        return await _post_json(
            "/exploration/start",
            {**data, "project_id": project_id or data.get("project_id") or "default"},
            expected_kind="exploration",
        )
    if step_type == "generate_requirements":
        session_id = data.get("exploration_session_id")
        return await _post_json(
            f"/requirements/generate?project_id={project_id or 'default'}",
            {"exploration_session_id": session_id},
            expected_kind="requirements_job",
        )
    if step_type == "generate_specs_from_requirements":
        return await _post_json(
            f"/requirements/bulk-generate-specs?project_id={project_id or 'default'}",
            data,
            expected_kind="bulk_specs_job",
        )
    if step_type == "run_spec":
        return await _post_json(
            "/runs",
            {**data, "project_id": project_id or data.get("project_id") or "default"},
            expected_kind="test_run",
        )
    if step_type == "run_regression_batch":
        return await _post_json(
            "/runs/bulk",
            {**data, "project_id": project_id or data.get("project_id") or "default"},
            expected_kind="regression_batch",
        )
    if step_type == "start_custom_agent":
        definition_id = data.pop("definition_id")
        return await _post_json(
            f"/api/agents/definitions/{definition_id}/runs",
            {**data, "project_id": project_id or "default"},
            expected_kind="agent_run",
        )
    raise RuntimeError(f"Unsupported step type: {step_type}")


async def _post_json(path: str, body: dict[str, Any], *, expected_kind: str | None = None) -> dict[str, Any]:
    # Import lazily to avoid importing the FastAPI app during model initialization.
    import httpx

    from orchestrator.api.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://workflow.local", timeout=30.0) as client:
        response = await client.post(path, json=body)
    if response.status_code >= 400:
        raise RuntimeError(response.text)
    payload = response.json()
    payload = payload if isinstance(payload, dict) else {"result": payload}
    return {**payload, **_external_ref(payload, expected_kind=expected_kind)}


async def _wait_for_status(data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    source_key = data.get("source_step")
    timeout_seconds = int(data.get("timeout_seconds") or 3600)
    poll_seconds = max(1, min(int(data.get("poll_seconds") or 5), 60))
    source = ((context.get("steps") or {}).get(source_key) or {}) if source_key else {}
    external = _external_ref(source)
    if not external.get("external_kind") or not external.get("external_id"):
        raise RuntimeError(f"Step {source_key!r} has no external job to wait for")

    import httpx

    from orchestrator.api.main import app

    deadline = asyncio.get_event_loop().time() + timeout_seconds
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://workflow.local", timeout=30.0) as client:
        while True:
            status_payload = await _read_external_status(client, external["external_kind"], external["external_id"], data)
            status = str(status_payload.get("status") or "").lower()
            if status in {"completed", "passed", "failed", "cancelled", "error", "timeout"}:
                return {
                    **external,
                    "status": status,
                    "result": status_payload,
                }
            if asyncio.get_event_loop().time() >= deadline:
                raise RuntimeError(f"Timed out waiting for {external['external_kind']} {external['external_id']}")
            await asyncio.sleep(poll_seconds)


async def _read_external_status(client: Any, kind: str, external_id: str, data: dict[str, Any]) -> dict[str, Any]:
    if kind == "autopilot":
        path = f"/autopilot/{external_id}"
    elif kind == "exploration":
        path = f"/exploration/{external_id}"
    elif kind == "requirements_job":
        path = f"/requirements/generate-jobs/{external_id}"
    elif kind == "bulk_specs_job":
        path = f"/requirements/bulk-generate-jobs/{external_id}"
    elif kind == "test_run":
        path = f"/runs/{external_id}"
    elif kind == "regression_batch":
        path = f"/regression/batches/{external_id}"
    elif kind == "agent_run":
        path = f"/api/agents/runs/{external_id}"
    else:
        raise RuntimeError(f"Cannot wait for external kind: {kind}")
    response = await client.get(path)
    if response.status_code >= 400:
        raise RuntimeError(response.text)
    payload = response.json()
    return payload if isinstance(payload, dict) else {"result": payload}


def _external_ref(payload: dict[str, Any], *, expected_kind: str | None = None) -> dict[str, str | None]:
    candidates = [
        ("session_id", expected_kind),
        ("run_id", "agent_run"),
        ("id", None),
        ("job_id", None),
        ("batch_id", "regression_batch"),
    ]
    for key, explicit_kind in candidates:
        if payload.get(key):
            value = str(payload[key])
            kind = explicit_kind or _infer_kind(value, payload) or expected_kind
            return {"external_kind": kind, "external_id": value}
    return {"external_kind": None, "external_id": None}


def _infer_kind(value: str, payload: dict[str, Any]) -> str | None:
    if value.startswith("autopilot_"):
        return "autopilot"
    if value.startswith("explore_"):
        return "exploration"
    if "total_requirements" in payload or payload.get("session_id"):
        return "requirements_job"
    return payload.get("external_kind")


def _build_context(session: Session, run_id: str, run: WorkflowRun) -> dict[str, Any]:
    steps = session.exec(
        select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id).order_by(WorkflowRunStep.step_order)
    ).all()
    return {
        "run": {"id": run.id, "inputs": run.inputs, "project_id": run.project_id},
        "inputs": run.inputs,
        "steps": {step.step_key: (step.output or {}) for step in steps},
    }


def _render_templates(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _render_templates(child, context) for key, child in value.items()}
    if isinstance(value, list):
        return [_render_templates(child, context) for child in value]
    if not isinstance(value, str):
        return value
    full = TEMPLATE_RE.fullmatch(value.strip())
    if full:
        resolved = _lookup_path(context, full.group(1))
        return resolved if resolved is not None else value
    return TEMPLATE_RE.sub(lambda match: str(_lookup_path(context, match.group(1)) or ""), value)


def _lookup_path(context: dict[str, Any], path: str) -> Any:
    current: Any = context
    for part in path.split("."):
        part = part.strip()
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _merge_step_output(context: dict[str, Any], key: str, output: dict[str, Any]) -> dict[str, Any]:
    merged = dict(context or {})
    steps = dict(merged.get("steps") or {})
    steps[key] = output
    merged["steps"] = steps
    return merged


def _context_for_completed_steps(steps: list[WorkflowRunStep], *, before_order: int) -> dict[str, Any]:
    return {
        "steps": {
            step.step_key: step.output or {}
            for step in steps
            if step.step_order < before_order and step.status == "completed"
        }
    }


def _step_count(session: Session, run_id: str) -> int:
    return len(session.exec(select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id)).all())


def _fail_run(session: Session, run: WorkflowRun, message: str) -> None:
    run.status = "failed"
    run.error_message = message
    run.completed_at = datetime.utcnow()
    run.updated_at = datetime.utcnow()
    session.add(run)
    session.commit()
