"""Runner for user-defined custom workflows."""

from __future__ import annotations

import asyncio
import copy
import logging
import re
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import WorkflowDefinition, WorkflowRun, WorkflowRunStep, WorkflowSchedule
from orchestrator.services.workflow_operations import emit_workflow_event
from orchestrator.services.workflow_output_contract import normalize_step_output, validate_output_contract
from orchestrator.services.workflow_step_registry import (
    get_step_type_metadata,
    list_workflow_step_types,
    validate_input_schema,
)

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_STATUSES = {"queued", "running", "awaiting_input", "paused"}
RECOVERY_ACTIONS = {"fail", "retry", "skip", "pause", "notify"}
SECRET_RE = re.compile(r"(password|token|secret|api[_-]?key|authorization|credential)", re.IGNORECASE)
TEMPLATE_RE = re.compile(r"{{\s*([^{}]+?)\s*}}")


class WorkflowPaused(RuntimeError):
    """Raised when a workflow is paused during a cooperative wait."""


class WorkflowCancelled(RuntimeError):
    """Raised when a workflow is cancelled during a cooperative wait."""

def workflow_step_catalog(session: Session | None = None, project_id: str | None = None) -> list[dict[str, Any]]:
    return list_workflow_step_types(session, project_id)


def validate_workflow_steps(
    steps: list[dict[str, Any]],
    *,
    session: Session | None = None,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
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
        metadata = get_step_type_metadata(step_type, session, project_id)
        if not metadata:
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

        missing = [name for name in metadata.get("required", []) if inputs.get(name) in (None, "")]
        if missing:
            raise ValueError(f"Step {key} missing required input(s): {', '.join(missing)}")
        validate_input_schema(key, metadata, inputs)

        normalized_step = {
            "key": key,
            "type": step_type,
            "label": str(raw.get("label") or metadata["label"]),
            "input": inputs,
            "continue_on_error": bool(raw.get("continue_on_error", False)),
        }
        if isinstance(raw.get("recovery_policy"), dict) and raw.get("recovery_policy"):
            normalized_step["recovery_policy"] = _normalize_recovery_policy(raw["recovery_policy"], step_key=key)
        normalized.append(normalized_step)
    _validate_template_references(normalized, session=session, project_id=project_id)
    _validate_wait_source_steps(normalized, session=session, project_id=project_id)
    return normalized


def validate_workflow_definition_payload(
    *,
    name: str,
    steps: list[dict[str, Any]],
    session: Session | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Return structured validation results for workflow builder UX."""
    form_errors: list[dict[str, str]] = []
    step_errors: dict[int, list[dict[str, str]]] = {}
    warnings: dict[int, list[dict[str, str]]] = {}

    if not str(name or "").strip():
        form_errors.append({"code": "required", "message": "Workflow name is required."})
    if not steps:
        form_errors.append({"code": "required", "message": "Add at least one step before saving."})

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(steps or []):
        errors: list[dict[str, str]] = []
        if not isinstance(raw, dict):
            step_errors[index] = [{"field": "", "code": "invalid_step", "message": "Step must be an object."}]
            continue
        step_type = str(raw.get("type") or "").strip()
        metadata = get_step_type_metadata(step_type, session, project_id)
        key = str(raw.get("key") or f"step_{index + 1}").strip()
        if not metadata:
            errors.append({"field": "type", "code": "unknown_type", "message": f"Unsupported workflow step type: {step_type or '(missing)'}"})
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            errors.append({"field": "key", "code": "invalid_key", "message": "Step key must use letters, numbers, dashes, or underscores."})
        if key in seen:
            errors.append({"field": "key", "code": "duplicate_key", "message": f"Duplicate step key: {key}"})
        seen.add(key)
        inputs = raw.get("input") or raw.get("inputs") or {}
        if not isinstance(inputs, dict):
            errors.append({"field": "input", "code": "invalid_input", "message": "Step input must be an object."})
            inputs = {}
        try:
            _reject_inline_secrets(inputs, path=f"steps.{key}.input")
        except ValueError as exc:
            errors.append({"field": "input", "code": "inline_secret", "message": str(exc)})
        if metadata:
            for field in metadata.get("required", []):
                if inputs.get(field) in (None, ""):
                    field_name = str(field)
                    errors.append({
                        "field": field_name,
                        "code": "required",
                        "message": _workflow_input_error_message(step_type, field_name, f"Missing required input: {field_name}."),
                    })
            try:
                validate_input_schema(key, metadata, inputs)
            except ValueError as exc:
                field_name = _field_from_schema_error(str(exc), key)
                errors.append({
                    "field": field_name,
                    "code": "schema",
                    "message": _workflow_input_error_message(step_type, field_name, str(exc)),
                })
            if metadata.get("is_async"):
                next_step = steps[index + 1] if index + 1 < len(steps) and isinstance(steps[index + 1], dict) else {}
                next_input = next_step.get("input") or {}
                if next_step.get("type") != "wait_for_status" or next_input.get("source_step") != key:
                    warnings.setdefault(index, []).append(
                        {"code": "async_without_wait", "message": "Async step is not followed by a wait step."}
                    )
        normalized_step = {
            "key": key,
            "type": step_type,
            "label": str(raw.get("label") or (metadata or {}).get("label") or step_type),
            "input": inputs,
            "continue_on_error": bool(raw.get("continue_on_error", False)),
        }
        if isinstance(raw.get("recovery_policy"), dict) and raw.get("recovery_policy"):
            try:
                normalized_step["recovery_policy"] = _normalize_recovery_policy(raw["recovery_policy"], step_key=key)
            except ValueError as exc:
                errors.append({"field": "recovery_policy", "code": "recovery_policy", "message": str(exc)})
        if errors:
            step_errors[index] = errors
        normalized.append(normalized_step)

    try:
        _validate_template_references(normalized, session=session, project_id=project_id)
    except ValueError as exc:
        _attach_cross_step_error(step_errors, normalized, str(exc), "reference")
    try:
        _validate_wait_source_steps(normalized, session=session, project_id=project_id)
    except ValueError as exc:
        _attach_cross_step_error(step_errors, normalized, str(exc), "wait_source")

    return {
        "valid": not form_errors and not step_errors,
        "form_errors": form_errors,
        "step_errors": {str(key): value for key, value in step_errors.items()},
        "warnings": {str(key): value for key, value in warnings.items()},
    }


def _field_from_schema_error(message: str, step_key: str) -> str:
    marker = f"Step {step_key} input invalid at "
    if marker not in message:
        return "input"
    return message.split(marker, 1)[1].split(":", 1)[0] or "input"


def _workflow_input_error_message(step_type: str, field: str, fallback: str) -> str:
    if step_type == "start_custom_agent" and field == "definition_id":
        return "Choose an agent before creating this workflow."
    if step_type == "generate_requirements" and field == "exploration_session_id":
        return "Add Start Exploration before Generate Requirements, then insert its External ID token."
    if step_type == "wait_for_status" and field == "source_step":
        return "Choose the earlier step this wait should monitor."
    return fallback


def _attach_cross_step_error(step_errors: dict[int, list[dict[str, str]]], steps: list[dict[str, Any]], message: str, code: str) -> None:
    target = 0
    match = re.search(r"Step ([A-Za-z0-9_-]+) ", message)
    if match:
        target_key = match.group(1)
        target = next((index for index, step in enumerate(steps) if step.get("key") == target_key), 0)
    step_errors.setdefault(target, []).append({"field": "input", "code": code, "message": message})


def _validate_template_references(
    steps: list[dict[str, Any]],
    *,
    session: Session | None = None,
    project_id: str | None = None,
) -> None:
    previous: dict[str, set[str]] = {}
    for step in steps:
        key = step["key"]
        for path in _iter_template_paths(step.get("input") or {}):
            parts = [part.strip() for part in path.split(".") if part.strip()]
            if len(parts) < 3 or parts[0] != "steps":
                continue
            source_key = parts[1]
            token_path = ".".join(parts[2:])
            if source_key not in previous:
                raise ValueError(f"Step {key} references unknown or later step: {source_key}")
            allowed_tokens = previous[source_key]
            if token_path not in allowed_tokens:
                raise ValueError(f"Step {key} references unsupported output token: steps.{source_key}.{token_path}")
        metadata = get_step_type_metadata(step["type"], session, project_id) or {}
        previous[key] = _output_token_paths(metadata)


def _output_token_paths(metadata: dict[str, Any]) -> set[str]:
    output_schema = metadata.get("output_schema") or {}
    tokens = {str(token) for token in output_schema.get("tokens") or []}
    catalog_paths = {str(item.get("path")) for item in output_schema.get("token_catalog") or [] if item.get("path")}
    return tokens | catalog_paths


def _validate_wait_source_steps(
    steps: list[dict[str, Any]],
    *,
    session: Session | None = None,
    project_id: str | None = None,
) -> None:
    previous: dict[str, dict[str, Any]] = {}
    for step in steps:
        if step["type"] == "wait_for_status":
            source_key = str((step.get("input") or {}).get("source_step") or "").strip()
            source = previous.get(source_key)
            if not source:
                raise ValueError(f"Step {step['key']} wait source must reference an earlier step: {source_key or '(missing)'}")
            metadata = get_step_type_metadata(source["type"], session, project_id) or {}
            tokens = _output_token_paths(metadata)
            if not metadata.get("is_async") and not {"external_kind", "external_id"}.issubset(tokens):
                raise ValueError(f"Step {step['key']} wait source does not expose an external job: {source_key}")
        previous[step["key"]] = step


def _iter_template_paths(value: Any) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            paths.extend(_iter_template_paths(child))
    elif isinstance(value, list):
        for child in value:
            paths.extend(_iter_template_paths(child))
    elif isinstance(value, str):
        paths.extend(match.group(1) for match in TEMPLATE_RE.finditer(value))
    return paths


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


def _normalize_recovery_policy(policy: dict[str, Any] | None, *, step_key: str = "workflow") -> dict[str, Any]:
    if not policy:
        return {}
    action = str(policy.get("action") or "fail").strip().lower()
    if action not in RECOVERY_ACTIONS:
        raise ValueError(f"Step {step_key} recovery_policy.action must be one of: {', '.join(sorted(RECOVERY_ACTIONS))}")
    try:
        max_attempts = max(1, int(policy.get("max_attempts") or 1))
        retry_backoff_seconds = max(0, int(policy.get("retry_backoff_seconds") or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Step {step_key} recovery policy retry values must be numbers") from exc
    return {
        "action": action,
        "max_attempts": max_attempts,
        "retry_backoff_seconds": retry_backoff_seconds,
    }


def create_workflow_run_steps(
    session: Session,
    definition: WorkflowDefinition,
    run: WorkflowRun,
    *,
    start_step_key: str | None = None,
    steps_override: list[dict[str, Any]] | None = None,
) -> int:
    source_steps = steps_override if steps_override is not None else definition.steps
    start_index = 0
    if start_step_key:
        matching_indexes = [index for index, step in enumerate(source_steps) if step.get("key") == start_step_key]
        if not matching_indexes:
            raise ValueError(f"Workflow step not found: {start_step_key}")
        start_index = matching_indexes[0]

    now = datetime.utcnow()
    default_recovery_policy = _normalize_recovery_policy(run.recovery_policy, step_key="run")
    for index, step in enumerate(source_steps):
        metadata = get_step_type_metadata(step["type"], session, definition.project_id) or get_step_type_metadata(step["type"])
        step_config = {
            "type": step["type"],
            "version": int((metadata or {}).get("version") or 1),
            "handler_kind": (metadata or {}).get("handler_kind") or "builtin",
            "handler_config": copy.deepcopy((metadata or {}).get("handler_config") or {}),
            "output_schema": copy.deepcopy((metadata or {}).get("output_schema") or {}),
            "category": (metadata or {}).get("category") or "Utility",
            "risk_level": (metadata or {}).get("risk_level") or "low",
            "is_async": bool((metadata or {}).get("is_async", False)),
            "auto_wait_defaults": copy.deepcopy((metadata or {}).get("auto_wait_defaults") or {}),
        }
        run_step = WorkflowRunStep(
            run_id=run.id,
            definition_id=definition.id,
            workflow_id=definition.id,
            step_index=index,
            step_order=index,
            step_id=step["key"],
            step_key=step["key"],
            step_type=step["type"],
            step_type_version=step_config["version"],
            name=step["label"],
            label=step["label"],
            continue_on_error=bool(step.get("continue_on_error", False)),
        )
        recovery_policy = step.get("recovery_policy") or default_recovery_policy
        if isinstance(recovery_policy, dict):
            normalized_recovery = _normalize_recovery_policy(recovery_policy, step_key=step["key"])
            run_step.max_attempts = normalized_recovery.get("max_attempts") or 1
            run_step.retry_backoff_seconds = normalized_recovery.get("retry_backoff_seconds") or 0
            run_step.recovery_action = normalized_recovery.get("action") or "fail"
        run_step.input = step.get("input") or {}
        run_step.step_config = step_config
        if index < start_index:
            run_step.status = "skipped"
            run_step.output = {"skipped": True, "reason": "run_started_from_later_step"}
            run_step.completed_at = now
            run_step.updated_at = now
        session.add(run_step)
    run.current_step_index = start_index
    run.progress = start_index / max(len(source_steps), 1)
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
        prepared = prepare_next_workflow_step(run_id)
        action = prepared.get("action")
        if action != "execute":
            return
        next_step_id = prepared.get("step_id")

        result = await execute_workflow_step_once(run_id, next_step_id)
        if result["action"] == "completed":
            continue
        if result["action"] == "paused":
            logger.info("Workflow run %s paused during step execution", run_id)
            return
        if result["action"] == "cancelled":
            logger.info("Workflow run %s cancelled during step execution", run_id)
            return
        logger.error("Workflow step failed: %s", result.get("error_message") or "unknown error")
        recovery = handle_workflow_step_failure(run_id, next_step_id, result.get("error_message") or "Workflow step failed")
        if recovery["action"] == "retry" and recovery.get("backoff_seconds"):
            await asyncio.sleep(int(recovery["backoff_seconds"]))
        if recovery["action"] in {"retry", "continue"}:
            continue
        return


def prepare_next_workflow_step(run_id: str) -> dict[str, Any]:
    with Session(engine) as session:
        run = session.get(WorkflowRun, run_id)
        if not run:
            return {"action": "missing", "status": "missing", "error_message": "Workflow run disappeared"}
        if run.status in TERMINAL_STATUSES:
            return {"action": "stop", "status": run.status, "error_message": run.error_message}
        if run.status == "paused":
            return {"action": "paused", "status": "paused", "pause_reason": run.pause_reason}
        definition = session.get(WorkflowDefinition, run.definition_id)
        if not definition:
            _fail_run(session, run, "Workflow definition not found")
            return {"action": "failed", "status": "failed", "error_message": "Workflow definition not found"}
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
                emit_workflow_event(
                    session,
                    event_type="workflow.awaiting_input",
                    message=f"Workflow run {run.id} is awaiting review input.",
                    severity="warning",
                    run=run,
                    notify=_notify_for_run_event(session, run, "workflow.awaiting_input"),
                )
                session.commit()
                return {"action": "awaiting_input", "status": "awaiting_input"}
            run.status = "completed"
            run.progress = 1.0
            run.completed_at = datetime.utcnow()
            run.updated_at = datetime.utcnow()
            run.result = {"steps": {step.step_key: step.output for step in steps}}
            session.add(run)
            emit_workflow_event(
                session,
                event_type="workflow.completed",
                message=f"Workflow run {run.id} completed.",
                run=run,
                notify=_notify_for_run_event(session, run, "workflow.completed"),
            )
            session.commit()
            return {"action": "completed", "status": "completed"}
        if run.status in {"queued", "awaiting_input"}:
            run.status = "running"
            emit_workflow_event(
                session,
                event_type="workflow.started",
                message=f"Workflow run {run.id} started.",
                run=run,
                notify=False,
            )
        run.started_at = run.started_at or datetime.utcnow()
        run.heartbeat_at = datetime.utcnow()
        run.current_step_index = next_step.step_order
        run.progress = next_step.step_order / max(len(steps), 1)
        run.updated_at = datetime.utcnow()
        session.add(run)
        session.commit()
        return {
            "action": "execute",
            "status": run.status,
            "step_id": next_step.id,
            "step_key": next_step.step_key,
            "step_order": next_step.step_order,
        }


async def execute_workflow_step_once(run_id: str, step_id: int | None) -> dict[str, Any]:
    try:
        await _execute_step(run_id, step_id)
        with Session(engine) as session:
            run = session.get(WorkflowRun, run_id)
            step = session.get(WorkflowRunStep, step_id) if step_id is not None else None
            return {
                "action": "completed",
                "status": run.status if run else "missing",
                "step_status": step.status if step else None,
            }
    except WorkflowPaused as exc:
        return {"action": "paused", "status": "paused", "error_message": str(exc)}
    except WorkflowCancelled as exc:
        return {"action": "cancelled", "status": "cancelled", "error_message": str(exc)}
    except Exception as exc:
        return {"action": "failed", "status": "failed", "error_message": str(exc)}


def handle_workflow_step_failure(run_id: str, step_id: int | None, message: str) -> dict[str, Any]:
    with Session(engine) as session:
        step = session.get(WorkflowRunStep, step_id) if step_id is not None else None
        run = session.get(WorkflowRun, run_id)
        if not run or not step:
            return {"action": "missing", "status": "missing", "error_message": "Workflow run or step disappeared"}
        step.status = "failed"
        step.error_message = message
        step.completed_at = datetime.utcnow()
        step.updated_at = datetime.utcnow()
        session.add(step)
        emit_workflow_event(
            session,
            event_type="workflow.step_failed",
            message=f"Workflow step {step.step_key} failed: {message}",
            severity="error",
            run=run,
            step_id=step.id,
            payload={"step_key": step.step_key, "attempt_count": step.attempt_count},
            notify=_notify_for_run_event(session, run, "workflow.step_failed"),
        )
        if step.recovery_action == "retry" and step.attempt_count < step.max_attempts:
            step.status = "pending"
            step.completed_at = None
            session.add(step)
            session.commit()
            return {
                "action": "retry",
                "status": "queued",
                "backoff_seconds": min(step.retry_backoff_seconds, 300),
                "step_id": step.id,
            }
        if step.continue_on_error:
            session.commit()
            return {"action": "continue", "status": run.status, "step_id": step.id}
        if step.recovery_action == "skip":
            step.status = "skipped"
            step.skipped_reason = message
            step.output = {"skipped": True, "reason": message}
            step.completed_at = datetime.utcnow()
            step.updated_at = datetime.utcnow()
            run.context = _merge_step_output(run.context, step.step_key, step.output or {})
            session.add(step)
            session.add(run)
            session.commit()
            return {"action": "continue", "status": run.status, "step_id": step.id}
        if step.recovery_action == "pause":
            run.status = "paused"
            run.pause_reason = message
            run.updated_at = datetime.utcnow()
            session.add(run)
            emit_workflow_event(
                session,
                event_type="workflow.paused",
                message=f"Workflow run {run.id} paused after step {step.step_key} failed.",
                severity="warning",
                run=run,
                notify=True,
            )
            session.commit()
            return {"action": "paused", "status": "paused", "step_id": step.id}
        if step.recovery_action == "notify":
            emit_workflow_event(
                session,
                event_type="workflow.step_failed",
                message=f"Workflow step {step.step_key} requested notification after failure: {message}",
                severity="error",
                run=run,
                step_id=step.id,
                notify=True,
            )
        _fail_run(session, run, message)
        return {"action": "failed", "status": "failed", "step_id": step.id, "error_message": message}


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
        rendered_input, resolution = _render_templates_with_trace(copy.deepcopy(step.input), context)
        step_type = step.step_type
        run_project_id = run.project_id
        step_config = step.step_config
        step.status = "running"
        step.attempt_count += 1
        step.rendered_input = rendered_input
        step.context_snapshot = context
        step.input_resolution = resolution
        step.started_at = step.started_at or datetime.utcnow()
        step.updated_at = datetime.utcnow()
        session.add(step)
        session.commit()

    result = await _dispatch_step(step_type, rendered_input, run_project_id, context, step_config)
    output_errors = validate_output_contract(result)

    with Session(engine) as session:
        step = session.get(WorkflowRunStep, step_id)
        run = session.get(WorkflowRun, run_id)
        if not step or not run:
            return
        if run.status == "paused":
            step.status = "paused"
            step.updated_at = datetime.utcnow()
            session.add(step)
            session.commit()
            raise WorkflowPaused("Workflow paused")
        if run.status in TERMINAL_STATUSES:
            raise WorkflowCancelled("Workflow cancelled")
        if result.get("awaiting_input"):
            step.status = "awaiting_input"
            step.output = result
            run.status = "awaiting_input"
            emit_workflow_event(
                session,
                event_type="workflow.review_needed",
                message=f"Workflow step {step.step_key} needs review input.",
                severity="warning",
                run=run,
                step_id=step.id,
                notify=_notify_for_run_event(session, run, "workflow.review_needed"),
            )
        else:
            step.status = "completed"
            step.output = result
            step.output_validation_errors = output_errors
            step.external_kind = result.get("external_kind")
            step.external_id = result.get("external_id")
            step.completed_at = datetime.utcnow()
            run.context = _merge_step_output(run.context, step.step_key, result)
        step.updated_at = datetime.utcnow()
        run.heartbeat_at = datetime.utcnow()
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
    step_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    step_config = step_config or {}
    builtin_metadata = get_step_type_metadata(step_type)
    handler_kind = step_config.get("handler_kind") or (builtin_metadata or {}).get("handler_kind") or "builtin"
    handler_config = step_config.get("handler_config") or (builtin_metadata or {}).get("handler_config") or {}
    action = handler_config.get("action") or step_type

    if handler_kind == "review_gate" or action == "review_gate":
        return normalize_step_output({
            "awaiting_input": True,
            "status": "awaiting_input",
            "question": data.get("question"),
            "suggested_answers": data.get("suggested_answers") or [],
            "external_kind": "review_gate",
        }, status="awaiting_input", external_kind="review_gate")
    if handler_kind == "wait_for_status" or action == "wait_for_status":
        return normalize_step_output(await _wait_for_status(data, context))
    if handler_kind == "agent_run" or action == "start_custom_agent":
        definition_id = data.get("definition_id")
        if not definition_id:
            raise RuntimeError("Custom agent definition_id is required")
        body = {key: value for key, value in data.items() if key != "definition_id"}
        return normalize_step_output(await _post_json(
            f"/api/agents/definitions/{definition_id}/runs",
            {**body, "project_id": project_id or "default"},
            expected_kind="agent_run",
        ))
    if action == "start_autopilot":
        return normalize_step_output(await _post_json(
            "/autopilot/start",
            {**data, "project_id": project_id or data.get("project_id") or "default"},
            expected_kind="autopilot",
        ))
    if action == "start_exploration":
        return normalize_step_output(await _post_json(
            "/exploration/start",
            {**data, "project_id": project_id or data.get("project_id") or "default"},
            expected_kind="exploration",
        ))
    if action == "generate_requirements":
        session_id = data.get("exploration_session_id")
        return normalize_step_output(await _post_json(
            f"/requirements/generate?project_id={project_id or 'default'}",
            {"exploration_session_id": session_id},
            expected_kind="requirements_job",
        ))
    if action == "generate_specs_from_requirements":
        return normalize_step_output(await _post_json(
            f"/requirements/bulk-generate-specs?project_id={project_id or 'default'}",
            data,
            expected_kind="bulk_specs_job",
        ))
    if action == "run_spec":
        return normalize_step_output(await _post_json(
            "/runs",
            {**data, "project_id": project_id or data.get("project_id") or "default"},
            expected_kind="test_run",
        ))
    if action == "run_regression_batch":
        return normalize_step_output(await _post_json(
            "/runs/bulk",
            {**data, "project_id": project_id or data.get("project_id") or "default"},
            expected_kind="regression_batch",
        ))
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
    run_id = str((context.get("run") or {}).get("id") or "").strip()
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
            _raise_if_run_controlled(run_id)
            status_payload = await _read_external_status(client, external["external_kind"], external["external_id"], data)
            _raise_if_run_controlled(run_id)
            status = str(status_payload.get("status") or "").lower()
            if status in {"completed", "passed", "failed", "cancelled", "error", "timeout"}:
                result = {
                    **external,
                    "status": status,
                    "result": status_payload,
                }
                if external["external_kind"] == "agent_run":
                    agent_result = status_payload.get("result") if isinstance(status_payload.get("result"), dict) else {}
                    structured_report = agent_result.get("structured_report") if isinstance(agent_result, dict) else None
                    result.update(
                        {
                            "summary": status_payload.get("summary") or agent_result.get("summary"),
                            "structured_report": structured_report,
                            "findings": (structured_report or {}).get("findings") if isinstance(structured_report, dict) else None,
                            "test_ideas": (structured_report or {}).get("test_ideas") if isinstance(structured_report, dict) else None,
                            "artifacts": status_payload.get("artifacts") or agent_result.get("artifacts"),
                        }
                    )
                return result
            if asyncio.get_event_loop().time() >= deadline:
                raise RuntimeError(f"Timed out waiting for {external['external_kind']} {external['external_id']}")
            await asyncio.sleep(poll_seconds)


def _raise_if_run_controlled(run_id: str) -> None:
    if not run_id:
        return
    with Session(engine) as session:
        run = session.get(WorkflowRun, run_id)
        if not run:
            raise WorkflowCancelled("Workflow run disappeared")
        if run.status == "paused":
            steps = session.exec(
                select(WorkflowRunStep)
                .where(WorkflowRunStep.run_id == run_id)
                .where(WorkflowRunStep.status == "running")
            ).all()
            for step in steps:
                step.status = "paused"
                step.updated_at = datetime.utcnow()
                session.add(step)
            session.commit()
            raise WorkflowPaused("Workflow paused")
        if run.status in TERMINAL_STATUSES:
            raise WorkflowCancelled(f"Workflow {run.status}")


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
    if payload.get("external_id"):
        return {
            "external_kind": str(payload.get("external_kind") or expected_kind) if (payload.get("external_kind") or expected_kind) else None,
            "external_id": str(payload["external_id"]),
        }
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


def _render_templates_with_trace(value: Any, context: dict[str, Any]) -> tuple[Any, list[dict[str, Any]]]:
    trace: list[dict[str, Any]] = []

    def render(child: Any, path: str) -> Any:
        if isinstance(child, dict):
            return {key: render(value, f"{path}.{key}" if path else key) for key, value in child.items()}
        if isinstance(child, list):
            return [render(value, f"{path}[{index}]") for index, value in enumerate(child)]
        if not isinstance(child, str):
            return child
        full = TEMPLATE_RE.fullmatch(child.strip())
        if full:
            ref = full.group(1)
            resolved = _lookup_path(context, ref)
            trace.append({"path": path, "template": child, "reference": ref, "resolved": resolved, "status": "resolved" if resolved is not None else "missing"})
            return resolved if resolved is not None else child

        def replace(match: re.Match[str]) -> str:
            ref = match.group(1)
            resolved = _lookup_path(context, ref)
            trace.append({"path": path, "template": match.group(0), "reference": ref, "resolved": resolved, "status": "resolved" if resolved is not None else "missing"})
            return str(resolved or "")

        return TEMPLATE_RE.sub(replace, child)

    return render(value, ""), trace


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
    emit_workflow_event(
        session,
        event_type="workflow.failed",
        message=f"Workflow run {run.id} failed: {message}",
        severity="error",
        run=run,
        notify=_notify_for_run_event(session, run, "workflow.failed"),
    )
    session.commit()


def _notify_for_run_event(session: Session, run: WorkflowRun, event_type: str) -> bool | None:
    if run.trigger_type != "schedule" or not run.trigger_id:
        return None
    schedule = session.get(WorkflowSchedule, run.trigger_id)
    if not schedule:
        return None
    if event_type == "workflow.completed":
        return schedule.notify_on_completion
    if event_type in {"workflow.failed", "workflow.step_failed"}:
        return schedule.notify_on_failure
    if event_type in {"workflow.awaiting_input", "workflow.review_needed"}:
        return schedule.notify_on_review_needed
    return None
