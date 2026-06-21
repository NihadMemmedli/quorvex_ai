"""AutoPilot agent retry/resume and attempt persistence helpers."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import AutoPilotAgentAttempt, AutoPilotChecklistItem
from orchestrator.services.autopilot_checklist import upsert_checklist_item
from orchestrator.utils.agent_runner import AgentResult, classify_agent_error_type

logger = logging.getLogger(__name__)

AUTOPILOT_RETRYABLE_ERROR_TYPES = {
    "agent_process_error",
    "provider_overloaded",
    "heartbeat_lost",
    "browser_tool_timeout",
    "stream_interrupted",
    "timeout",
}

AUTOPILOT_NON_RETRYABLE_ERROR_PARTS = (
    "cancelled",
    "canceled",
    "budget reached",
    "budget exhausted",
    "max_budget",
    "permission denied",
    "denied by user",
    "tool permission",
    "browser_close",
    "validation",
)

AUTOPILOT_DENIED_BROWSER_CLOSE_TOOLS = {
    "browser_close",
    "browser_reset",
    "browser_restart",
    "browser_new_context",
}

try:
    from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
except ImportError:  # pragma: no cover - SDK is optional in unit tests
    PermissionResultAllow = None
    PermissionResultDeny = None


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.environ.get(name, str(default))))
    except ValueError:
        return default


def max_attempts() -> int:
    return _env_int("AUTOPILOT_AGENT_MAX_ATTEMPTS", 3)


def retry_base_seconds() -> float:
    return _env_float("AUTOPILOT_AGENT_RETRY_BASE_SECONDS", 5.0)


def retry_max_seconds() -> float:
    return _env_float("AUTOPILOT_AGENT_RETRY_MAX_SECONDS", 60.0)


def deny_browser_close_enabled() -> bool:
    return str(os.environ.get("AUTOPILOT_DENY_BROWSER_CLOSE", "true")).lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _short_tool_name(tool_name: str) -> str:
    return tool_name.split("__")[-1] if "__" in tool_name else tool_name


def is_browser_close_tool(tool_name: str) -> bool:
    return _short_tool_name(str(tool_name)) in AUTOPILOT_DENIED_BROWSER_CLOSE_TOOLS


def _attempt_state_path(session_dir: Path | str | None) -> Path | None:
    if not session_dir:
        return None
    return Path(session_dir) / "agent-state.json"


def _stable_key(runner: Any) -> str:
    explicit = getattr(runner, "autopilot_stable_key", None)
    if explicit:
        return str(explicit)
    source_type = getattr(runner, "autopilot_source_type", None) or getattr(runner, "autopilot_agent_kind", None) or "agent"
    source_id = getattr(runner, "autopilot_source_id", None) or getattr(runner, "session_dir", None) or "default"
    return f"{source_type}:{source_id}"


def _source_type(runner: Any) -> str:
    return str(getattr(runner, "autopilot_source_type", None) or getattr(runner, "autopilot_agent_kind", None) or "agent")


def _source_id(runner: Any) -> str:
    return str(getattr(runner, "autopilot_source_id", None) or _stable_key(runner))


def _checklist_title(runner: Any) -> str:
    return str(
        getattr(runner, "autopilot_checklist_title", None)
        or f"{str(getattr(runner, 'autopilot_agent_kind', None) or 'Agent').replace('_', ' ').title()} agent"
    )


def _checklist_kind(runner: Any) -> str:
    return str(getattr(runner, "autopilot_checklist_kind", None) or "agent")


def _phase_name(runner: Any) -> str | None:
    value = getattr(runner, "autopilot_phase_name", None)
    return str(value) if value else None


def _metadata_for_result(result: AgentResult | None) -> dict[str, Any]:
    if result is None:
        return {}
    return {
        "sdk_session_id": result.session_id,
        "messages_received": result.messages_received,
        "text_blocks_received": result.text_blocks_received,
        "tool_calls": len(result.tool_calls or []),
        "timed_out": result.timed_out,
        "cancelled": result.cancelled,
        "api_error_status": result.api_error_status,
        "stop_reason": result.stop_reason,
        "total_cost_usd": result.total_cost_usd,
    }


def _write_state_file(
    *,
    runner: Any,
    attempt_number: int,
    status: str,
    error_type: str | None = None,
    retry_eligible: bool = False,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    path = _attempt_state_path(getattr(runner, "session_dir", None))
    if path is None:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "session_id": getattr(runner, "autopilot_session_id", None),
            "stable_key": _stable_key(runner),
            "source_type": _source_type(runner),
            "source_id": _source_id(runner),
            "agent_kind": getattr(runner, "autopilot_agent_kind", None) or "agent",
            "attempt": attempt_number,
            "max_attempts": max_attempts(),
            "status": status,
            "error_type": error_type,
            "retry_eligible": retry_eligible,
            "session_dir": str(getattr(runner, "session_dir", "")) if getattr(runner, "session_dir", None) else None,
            "updated_at": datetime.utcnow().isoformat(),
            "metadata": metadata or {},
        }
        path.write_text(json.dumps(payload, indent=2, default=str))
        return str(path)
    except Exception as exc:
        logger.debug("Unable to write AutoPilot agent state file: %s", exc)
        return None


def _merge_attempt_metadata(existing: str | None, incoming: dict[str, Any] | None) -> str:
    try:
        value = json.loads(existing or "{}")
        if not isinstance(value, dict):
            value = {}
    except json.JSONDecodeError:
        value = {}
    if incoming:
        value.update({key: val for key, val in incoming.items() if val is not None})
    return json.dumps(value, default=str)


def persist_attempt(
    *,
    runner: Any,
    attempt_number: int,
    status: str,
    error_type: str | None = None,
    retry_eligible: bool = False,
    claude_session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AutoPilotAgentAttempt | None:
    session_id = getattr(runner, "autopilot_session_id", None) or getattr(runner, "owner_id", None)
    if not session_id:
        return None
    now = datetime.utcnow()
    state_path = _write_state_file(
        runner=runner,
        attempt_number=attempt_number,
        status=status,
        error_type=error_type,
        retry_eligible=retry_eligible,
        metadata=metadata,
    )
    merged_metadata = dict(metadata or {})
    if state_path:
        merged_metadata["state_path"] = state_path
    with Session(engine) as db:
        stmt = (
            select(AutoPilotAgentAttempt)
            .where(AutoPilotAgentAttempt.session_id == session_id)
            .where(AutoPilotAgentAttempt.stable_key == _stable_key(runner))
            .where(AutoPilotAgentAttempt.attempt_number == attempt_number)
        )
        attempt = db.exec(stmt).first()
        if not attempt:
            attempt = AutoPilotAgentAttempt(
                session_id=session_id,
                stable_key=_stable_key(runner),
                source_type=_source_type(runner),
                source_id=_source_id(runner),
                agent_kind=str(getattr(runner, "autopilot_agent_kind", None) or "agent"),
                attempt_number=attempt_number,
                session_dir=str(getattr(runner, "session_dir", "")) if getattr(runner, "session_dir", None) else None,
                created_at=now,
                started_at=now,
            )
        attempt.status = status
        attempt.error_type = error_type
        attempt.retry_eligible = bool(retry_eligible)
        if claude_session_id:
            attempt.claude_session_id = claude_session_id
        attempt.metadata_json = _merge_attempt_metadata(attempt.metadata_json, merged_metadata)
        attempt.updated_at = now
        if status in {"succeeded", "failed", "cancelled", "not_retryable", "resume_invalid"}:
            attempt.completed_at = attempt.completed_at or now
        else:
            attempt.completed_at = None
        db.add(attempt)
        db.commit()
        db.refresh(attempt)
        return attempt


def update_checklist_from_attempt(
    *,
    runner: Any,
    attempt_number: int,
    status: str,
    detail: str | None = None,
    retry_reason: str | None = None,
    claude_session_id: str | None = None,
    last_tool: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session_id = getattr(runner, "autopilot_session_id", None) or getattr(runner, "owner_id", None)
    if not session_id:
        return
    state_path = str(_attempt_state_path(getattr(runner, "session_dir", None)) or "") or None
    row_metadata = {
        "stable_key": _stable_key(runner),
        "attempt": attempt_number,
        "max_attempts": max_attempts(),
        "retry_reason": retry_reason,
        "sdk_session_id": claude_session_id,
        "session_dir": str(getattr(runner, "session_dir", "")) if getattr(runner, "session_dir", None) else None,
        "last_tool": last_tool,
        "state_path": state_path,
    }
    row_metadata.update(metadata or {})
    upsert_checklist_item(
        session_id=session_id,
        source_type=_source_type(runner),
        source_id=_source_id(runner),
        title=_checklist_title(runner),
        kind=_checklist_kind(runner),
        phase_name=_phase_name(runner),
        status=status,
        detail=detail,
        metadata=row_metadata,
    )


def classify_retry(result: AgentResult) -> tuple[bool, str | None]:
    error_text = f"{result.error or ''} {result.error_type or ''}".lower()
    if result.cancelled or any(part in error_text for part in AUTOPILOT_NON_RETRYABLE_ERROR_PARTS):
        return False, result.error_type or "not_retryable"
    if result.api_error_status in {408, 409, 425, 429, 500, 502, 503, 504, 529}:
        return True, result.error_type or f"api_{result.api_error_status}"
    error_type = result.error_type or classify_agent_error_type(result.error)
    if error_type == "invalid_session_resume":
        return True, error_type
    if result.timed_out:
        return True, "timeout"
    if (
        not (result.output or "").strip()
        and not (result.tool_calls or [])
        and int(result.messages_received or 0) == 0
        and error_type in {"ProcessError", "agent_process_error"}
    ):
        return True, "agent_process_error"
    if error_type in AUTOPILOT_RETRYABLE_ERROR_TYPES:
        return True, error_type
    if any(part in error_text for part in ("rate limit", "overload", "5xx", "stream interrupted", "heartbeat lost")):
        return True, error_type or "transient"
    return False, error_type or "not_retryable"


def retry_delay_seconds(attempt_number: int) -> float:
    return min(retry_max_seconds(), retry_base_seconds() * (2 ** max(0, attempt_number - 1)))


async def _call_guard(guard: Any, tool_name: str, tool_input: dict[str, Any], context: Any) -> Any:
    result = guard(tool_name, tool_input, context)
    if inspect.isawaitable(result):
        return await result
    return result


def build_autopilot_browser_tool_guard(existing_guard: Any | None = None):
    if not deny_browser_close_enabled() and existing_guard is None:
        return None

    async def guard(tool_name: str, tool_input: dict[str, Any], context: Any):
        if deny_browser_close_enabled() and is_browser_close_tool(tool_name):
            message = (
                f"{_short_tool_name(tool_name)} is system-owned during AutoPilot runs. "
                "Leave the browser open; the orchestrator handles cleanup on explicit cancel or terminal cleanup."
            )
            if PermissionResultDeny is not None:
                return PermissionResultDeny(message=message)
            raise PermissionError(message)
        if existing_guard is not None:
            return await _call_guard(existing_guard, tool_name, tool_input, context)
        if PermissionResultAllow is not None:
            return PermissionResultAllow()
        return True

    return guard


def harden_browser_tools_for_autopilot(runner: Any) -> None:
    """Remove close/reset tools from availability lists and add explicit disallow entries."""
    def filtered(value: Any) -> Any:
        if isinstance(value, list):
            return [tool for tool in value if not is_browser_close_tool(str(tool))]
        return value

    runner.allowed_tools = filtered(getattr(runner, "allowed_tools", []))
    runner.tools = filtered(getattr(runner, "tools", None))
    disallowed = list(getattr(runner, "disallowed_tools", []) or [])
    existing = {str(item) for item in disallowed}
    prefixes = set()
    for source in (getattr(runner, "allowed_tools", []), getattr(runner, "tools", [])):
        if isinstance(source, list):
            for tool in source:
                text = str(tool)
                if text.startswith("mcp__") and "__" in text:
                    parts = text.split("__", 2)
                    if len(parts) == 3:
                        prefixes.add(f"{parts[0]}__{parts[1]}__")
    if not prefixes:
        prefixes.add("mcp__playwright-test__")
    for prefix in prefixes:
        for suffix in AUTOPILOT_DENIED_BROWSER_CLOSE_TOOLS:
            name = f"{prefix}{suffix}"
            if name not in existing:
                disallowed.append(name)
                existing.add(name)
    runner.disallowed_tools = disallowed
    runner.tool_permission_guard = build_autopilot_browser_tool_guard(
        getattr(runner, "tool_permission_guard", None)
    )
    runner.preserve_browser_on_failure = True
    runner.enable_file_checkpointing = True


async def run_agent_with_retries(runner: Any, prompt: str, timeout_override: int | None = None) -> AgentResult:
    attempts = max_attempts()
    original_resume_session_id = getattr(runner, "resume_session_id", None)
    original_on_progress = getattr(runner, "on_progress", None)
    original_on_tool_use = getattr(runner, "on_tool_use", None)
    original_inner = getattr(runner, "_autopilot_retry_inner", False)
    resume_session_id = original_resume_session_id
    force_fresh = False
    last_result: AgentResult | None = None

    harden_browser_tools_for_autopilot(runner)

    try:
        for attempt_number in range(1, attempts + 1):
            last_tool: str | None = None
            status = "running" if attempt_number == 1 else "retrying"
            detail = "Agent attempt running" if attempt_number == 1 else f"Retrying agent attempt {attempt_number}/{attempts}"
            persist_attempt(
                runner=runner,
                attempt_number=attempt_number,
                status=status,
                metadata={"resume_session_id": resume_session_id, "fresh_retry": force_fresh},
            )
            update_checklist_from_attempt(
                runner=runner,
                attempt_number=attempt_number,
                status=status,
                detail=detail,
                retry_reason="retry" if attempt_number > 1 else None,
                metadata={"resume_session_id": resume_session_id, "fresh_retry": force_fresh},
            )

            def on_tool_use(tool_name: str, tool_input: dict[str, Any]) -> None:
                nonlocal last_tool
                last_tool = str(tool_name)
                if original_on_tool_use:
                    original_on_tool_use(tool_name, tool_input)
                metadata = {"last_tool_input_keys": sorted([str(key) for key in (tool_input or {}).keys()])[:20]}
                persist_attempt(
                    runner=runner,
                    attempt_number=attempt_number,
                    status="running",
                    metadata={"last_tool": last_tool, **metadata},
                )
                update_checklist_from_attempt(
                    runner=runner,
                    attempt_number=attempt_number,
                    status="tool_use",
                    detail=f"Using {_short_tool_name(last_tool)}",
                    last_tool=last_tool,
                    metadata=metadata,
                )

            def on_progress(progress: dict[str, Any]) -> None:
                nonlocal last_tool
                if original_on_progress:
                    original_on_progress(progress)
                progress_last_tool = str(progress.get("last_tool") or "")
                if progress_last_tool:
                    last_tool = progress_last_tool
                metadata = {
                    key: progress.get(key)
                    for key in (
                        "tool_calls",
                        "browser_tool_calls",
                        "interactions",
                        "current_stage",
                        "agent_task_id",
                        "retry_attempt",
                        "retry_max_attempts",
                        "retry_error_status",
                    )
                    if progress.get(key) is not None
                }
                persist_attempt(
                    runner=runner,
                    attempt_number=attempt_number,
                    status=str(progress.get("phase") or "running"),
                    metadata={"last_tool": last_tool, **metadata},
                )
                update_checklist_from_attempt(
                    runner=runner,
                    attempt_number=attempt_number,
                    status=str(progress.get("phase") or "running"),
                    detail=str(progress.get("message") or "Agent is running")[:500],
                    last_tool=last_tool,
                    metadata=metadata,
                )

            runner.on_tool_use = on_tool_use
            runner.on_progress = on_progress
            runner.resume_session_id = None if force_fresh else resume_session_id
            runner._autopilot_retry_inner = True

            result = await runner.run(prompt, timeout_override=timeout_override)
            last_result = result
            resume_session_id = result.session_id or resume_session_id
            result_metadata = _metadata_for_result(result)
            retry_eligible, error_type = classify_retry(result)

            if result.success:
                persist_attempt(
                    runner=runner,
                    attempt_number=attempt_number,
                    status="succeeded",
                    claude_session_id=result.session_id,
                    metadata=result_metadata,
                )
                update_checklist_from_attempt(
                    runner=runner,
                    attempt_number=attempt_number,
                    status="running",
                    detail="Agent attempt completed",
                    claude_session_id=result.session_id,
                    last_tool=last_tool,
                    metadata=result_metadata,
                )
                return result

            if error_type == "invalid_session_resume" and attempt_number < attempts:
                persist_attempt(
                    runner=runner,
                    attempt_number=attempt_number,
                    status="resume_invalid",
                    error_type=error_type,
                    retry_eligible=True,
                    claude_session_id=result.session_id,
                    metadata=result_metadata,
                )
                force_fresh = True
                update_checklist_from_attempt(
                    runner=runner,
                    attempt_number=attempt_number,
                    status="retrying",
                    detail="Resume session was invalid; retrying fresh",
                    retry_reason="resume_invalid",
                    claude_session_id=result.session_id,
                    last_tool=last_tool,
                    metadata=result_metadata,
                )
                await asyncio.sleep(retry_delay_seconds(attempt_number))
                continue

            if not retry_eligible or attempt_number >= attempts:
                final_status = "failed" if retry_eligible else "not_retryable"
                persist_attempt(
                    runner=runner,
                    attempt_number=attempt_number,
                    status=final_status,
                    error_type=error_type,
                    retry_eligible=False,
                    claude_session_id=result.session_id,
                    metadata=result_metadata,
                )
                update_checklist_from_attempt(
                    runner=runner,
                    attempt_number=attempt_number,
                    status="failed",
                    detail=(result.error or error_type or "Agent failed")[:500],
                    retry_reason=error_type,
                    claude_session_id=result.session_id,
                    last_tool=last_tool,
                    metadata=result_metadata,
                )
                return result

            wait_seconds = retry_delay_seconds(attempt_number)
            persist_attempt(
                runner=runner,
                attempt_number=attempt_number,
                status="retrying",
                error_type=error_type,
                retry_eligible=True,
                claude_session_id=result.session_id,
                metadata={**result_metadata, "retry_wait_seconds": wait_seconds},
            )
            update_checklist_from_attempt(
                runner=runner,
                attempt_number=attempt_number,
                status="retrying",
                detail=f"Transient agent failure; retrying in {int(wait_seconds)}s",
                retry_reason=error_type,
                claude_session_id=result.session_id,
                last_tool=last_tool,
                metadata={**result_metadata, "retry_wait_seconds": wait_seconds},
            )
            force_fresh = False
            await asyncio.sleep(wait_seconds)

        return last_result or AgentResult(success=False, error="AutoPilot agent retry loop produced no result")
    finally:
        runner.on_progress = original_on_progress
        runner.on_tool_use = original_on_tool_use
        runner.resume_session_id = original_resume_session_id
        runner._autopilot_retry_inner = original_inner


def reconcile_autopilot_agent_attempts(session_id: str) -> None:
    """Reconcile live checklist rows with the latest persisted attempt state."""
    now = datetime.utcnow()
    with Session(engine) as db:
        attempts = db.exec(
            select(AutoPilotAgentAttempt)
            .where(AutoPilotAgentAttempt.session_id == session_id)
            .order_by(AutoPilotAgentAttempt.stable_key, AutoPilotAgentAttempt.attempt_number.desc())
        ).all()
        latest: dict[str, AutoPilotAgentAttempt] = {}
        for attempt in attempts:
            latest.setdefault(attempt.stable_key, attempt)
        for attempt in latest.values():
            if not attempt.source_type or not attempt.source_id:
                continue
            row = db.exec(
                select(AutoPilotChecklistItem)
                .where(AutoPilotChecklistItem.session_id == session_id)
                .where(AutoPilotChecklistItem.source_type == attempt.source_type)
                .where(AutoPilotChecklistItem.source_id == attempt.source_id)
            ).first()
            if not row or row.status in {"completed", "passed", "failed", "error", "skipped", "cancelled", "answered"}:
                continue
            age = now - (attempt.updated_at or attempt.created_at or now)
            next_status = row.status
            detail = row.detail
            if attempt.status in {"succeeded"}:
                next_status = "running"
                detail = detail or "Agent attempt completed"
            elif attempt.status in {"retrying"}:
                next_status = "retrying"
            elif attempt.status in {"failed", "not_retryable", "resume_invalid"}:
                next_status = "failed" if not attempt.retry_eligible else "retrying"
                detail = detail or attempt.error_type or "Agent attempt failed"
            elif attempt.status == "running" and age > timedelta(minutes=30):
                next_status = "retrying" if attempt.retry_eligible else "failed"
                detail = detail or "Agent attempt became stale"
            metadata = row.metadata_dict
            metadata.update(
                {
                    "stable_key": attempt.stable_key,
                    "attempt": attempt.attempt_number,
                    "max_attempts": max_attempts(),
                    "retry_reason": attempt.error_type,
                    "sdk_session_id": attempt.claude_session_id,
                    "session_dir": attempt.session_dir,
                    "state_path": str(_attempt_state_path(attempt.session_dir) or "") or None,
                }
            )
            row.status = next_status
            row.detail = detail
            row.metadata_dict = metadata
            row.updated_at = now
            db.add(row)
        db.commit()
