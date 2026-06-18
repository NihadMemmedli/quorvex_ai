"""Main-compatible aliases for legacy agent helper delegates."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session

from . import (
    agent_compat_support,
    agent_run_observability,
    agent_run_report_support,
    agent_run_runtime_support,
)


def _runtime() -> Any:
    from . import main

    return main._agent_compat_runtime()


def _sync_agent_run_observability_runs_dir() -> None:
    agent_compat_support.sync_agent_run_observability_runs_dir(_runtime())


_collect_agent_run_artifacts = agent_run_observability._collect_agent_run_artifacts


def _read_run_text_artifact(run_id: str, name: str, max_chars: int | None = None) -> str:
    return agent_compat_support.read_run_text_artifact(_runtime(), run_id, name, max_chars)


def _read_run_json_artifact(run_id: str, name: str) -> Any:
    return agent_compat_support.read_run_json_artifact(_runtime(), run_id, name)


def _run_artifact_counts(run_id: str, artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return agent_compat_support.run_artifact_counts(_runtime(), run_id, artifacts)


_jsonl_latest_url = agent_run_observability._jsonl_latest_url


def _latest_observed_url_for_run(run: Any) -> str | None:
    return agent_compat_support.latest_observed_url_for_run(_runtime(), run)


def _recover_custom_agent_partial_result(run: Any, error: Exception | str) -> dict[str, Any] | None:
    return agent_compat_support.recover_custom_agent_partial_result(_runtime(), run, error)


_agent_run_summary = agent_run_runtime_support._agent_run_summary
_exploratory_result_is_zero_evidence_failure = agent_run_runtime_support._exploratory_result_is_zero_evidence_failure
_exploratory_result_is_terminal_failure = agent_run_runtime_support._exploratory_result_is_terminal_failure
_exploratory_result_has_usable_evidence = agent_run_runtime_support._exploratory_result_has_usable_evidence
_merge_agent_failure_into_result = agent_run_runtime_support._merge_agent_failure_into_result


def _recover_exploratory_partial_result(run_id: str, config: dict[str, Any], error: Exception | str) -> dict[str, Any] | None:
    return agent_compat_support.recover_exploratory_partial_result(_runtime(), run_id, config, error)


_filter_agent_run_project = agent_run_observability._filter_agent_run_project


def _agent_report_project_filter(project_id: str):
    return agent_compat_support.agent_report_project_filter(_runtime(), project_id)


def _get_agent_report_run(session: Session, run_id: str, project_id: str) -> Any:
    return agent_compat_support.get_agent_report_run(_runtime(), session, run_id, project_id)


AGENT_PARTIAL_STATUS = agent_run_observability.AGENT_PARTIAL_STATUS
AGENT_TERMINAL_STATUSES = agent_run_observability.AGENT_TERMINAL_STATUSES
AGENT_ACTIVE_STATUSES = agent_run_observability.AGENT_ACTIVE_STATUSES


_coerce_progress_int = agent_run_observability._coerce_progress_int
_normalize_agent_run_progress = agent_run_observability._normalize_agent_run_progress


def _record_agent_run_event(
    run_id: str,
    *,
    event_type: str,
    message: str,
    level: str = "info",
    payload: dict[str, Any] | None = None,
    agent_task_id: str | None = None,
    session: Session | None = None,
) -> None:
    agent_compat_support.record_agent_run_event(
        _runtime(),
        run_id,
        event_type=event_type,
        message=message,
        level=level,
        payload=payload,
        agent_task_id=agent_task_id,
        session=session,
    )


async def _start_agent_run_temporal_or_fail(run: Any, session: Session, *, workflow_attempt: int | None = None) -> None:
    await agent_compat_support.start_agent_run_temporal_or_fail(
        _runtime(),
        run,
        session,
        workflow_attempt=workflow_attempt,
    )


async def _agent_run_temporal_payload(run: Any) -> dict[str, Any]:
    return await agent_compat_support.agent_run_temporal_payload(_runtime(), run)


async def _signal_agent_run_temporal(run: Any, signal_name: str, *args: Any) -> None:
    await agent_compat_support.signal_agent_run_temporal(_runtime(), run, signal_name, *args)


async def _cancel_agent_run_queue_task(run: Any) -> dict[str, Any] | None:
    return await agent_compat_support.cancel_agent_run_queue_task(_runtime(), run)


async def _wait_if_agent_run_paused(run_id: str, poll_interval: float = 0.5) -> bool:
    return await agent_compat_support.wait_if_agent_run_paused(_runtime(), run_id, poll_interval)


def _mark_agent_run_paused(run: Any, message: str = "Agent is paused") -> None:
    agent_compat_support.mark_agent_run_paused(_runtime(), run, message)


def _mark_agent_run_cancelled(run: Any, message: str = "Agent cancelled") -> None:
    agent_compat_support.mark_agent_run_cancelled(_runtime(), run, message)


def _agent_run_health(run: Any, session: Session | None = None) -> dict[str, Any]:
    return agent_compat_support.agent_run_health(_runtime(), run, session)


def _serialize_agent_run(run: Any, session: Session | None = None) -> dict[str, Any]:
    return agent_compat_support.serialize_agent_run(_runtime(), run, session)


def _safe_json_dict(value: str | None) -> dict[str, Any]:
    return agent_compat_support.safe_json_dict(_runtime(), value)


def _compact_agent_run_config(config: dict[str, Any]) -> dict[str, Any]:
    return agent_compat_support.compact_agent_run_config(_runtime(), config)


def _compact_agent_run_summary(progress: dict[str, Any]) -> str | None:
    return agent_compat_support.compact_agent_run_summary(_runtime(), progress)


def _encode_agent_run_cursor(created_at: datetime, run_id: str) -> str:
    return agent_compat_support.encode_agent_run_cursor(_runtime(), created_at, run_id)


def _decode_agent_run_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    return agent_compat_support.decode_agent_run_cursor(_runtime(), cursor)


def _agent_run_project_filters(project_id: str | None) -> list[Any]:
    return agent_compat_support.agent_run_project_filters(_runtime(), project_id)


def _agent_run_search_filter(q: str | None) -> Any | None:
    return agent_compat_support.agent_run_search_filter(_runtime(), q)


def _agent_run_status_filter(status: str | None) -> Any | None:
    return agent_compat_support.agent_run_status_filter(_runtime(), status)


def _agent_run_type_filter(agent_type: str | None) -> Any | None:
    return agent_compat_support.agent_run_type_filter(_runtime(), agent_type)


def _agent_run_history_filters(
    *,
    project_id: str | None,
    status: str | None = None,
    agent_type: str | None = None,
    q: str | None = None,
) -> list[Any]:
    return agent_compat_support.agent_run_history_filters(
        _runtime(),
        project_id=project_id,
        status=status,
        agent_type=agent_type,
        q=q,
    )


def _agent_run_history_counts(session: Session, *, project_id: str | None, q: str | None) -> dict[str, Any]:
    return agent_compat_support.agent_run_history_counts(_runtime(), session, project_id=project_id, q=q)


def _serialize_agent_run_summary_row(row: Any) -> dict[str, Any]:
    return agent_compat_support.serialize_agent_run_summary_row(_runtime(), row)


async def _live_agent_queue_progress(run: Any) -> dict[str, Any]:
    return await agent_compat_support.live_agent_queue_progress(_runtime(), run)


async def _serialize_agent_run_live(run: Any, session: Session | None = None) -> dict[str, Any]:
    return await agent_compat_support.serialize_agent_run_live(_runtime(), run, session)


REPORT_ITEM_COLLECTIONS = agent_run_report_support.REPORT_ITEM_COLLECTIONS
REPORT_ITEM_EDITABLE_FIELDS = agent_run_report_support.REPORT_ITEM_EDITABLE_FIELDS
REPORT_ITEM_LIST_FIELDS = agent_run_report_support.REPORT_ITEM_LIST_FIELDS
REPORT_ITEM_PROTECTED_FIELDS = agent_run_report_support.REPORT_ITEM_PROTECTED_FIELDS


def _report_confidence(value: str | None) -> float:
    return agent_compat_support.report_confidence(_runtime(), value)


def _report_importance(value: str | None) -> float:
    return agent_compat_support.report_importance(_runtime(), value)


def _report_requirement_confidence(value: Any) -> float:
    return agent_compat_support.report_requirement_confidence(_runtime(), value)


def _report_requirement_acceptance_criteria(item: dict[str, Any]) -> list[str]:
    return agent_compat_support.report_requirement_acceptance_criteria(_runtime(), item)


def _requirement_create_body_from_report_item(item: dict[str, Any]) -> dict[str, Any]:
    return agent_compat_support.requirement_create_body_from_report_item(_runtime(), item)


def _normalize_report_item_type(item_type: str | None) -> str:
    return agent_compat_support.normalize_report_item_type(_runtime(), item_type)


def _stored_custom_agent_report(run: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    return agent_compat_support.stored_custom_agent_report(_runtime(), run)


def _normalize_report_patch_value(field: str, value: Any) -> Any:
    return agent_compat_support.normalize_report_patch_value(_runtime(), field, value)


def _editable_report_item_patch(item_type: str, patch: dict[str, Any]) -> dict[str, Any]:
    return agent_compat_support.editable_report_item_patch(_runtime(), item_type, patch)


def _find_report_item(report: dict[str, Any], item_type: str, item_id: str) -> dict[str, Any]:
    return agent_compat_support.find_report_item(_runtime(), report, item_type, item_id)


def _capture_custom_agent_report_memory(
    *,
    run_id: str,
    project_id: str | None,
    structured_report: dict[str, Any],
    config: dict[str, Any],
) -> list[str]:
    return agent_compat_support.capture_custom_agent_report_memory(
        _runtime(),
        run_id=run_id,
        project_id=project_id,
        structured_report=structured_report,
        config=config,
    )


def _sync_agent_tool_catalog(session: Session) -> list[Any]:
    return agent_compat_support.sync_agent_tool_catalog(_runtime(), session)


def _serialize_agent_tool(tool: Any) -> dict[str, Any]:
    return agent_compat_support.serialize_agent_tool(_runtime(), tool)


def _serialize_agent_definition(definition: Any, tools_by_id: dict[str, Any] | None = None) -> dict[str, Any]:
    return agent_compat_support.serialize_agent_definition(_runtime(), definition, tools_by_id)


def _get_agent_definition_or_404(definition_id: str, project_id: str | None, session: Session) -> Any:
    return agent_compat_support.get_agent_definition_or_404(_runtime(), definition_id, project_id, session)


async def _ensure_agent_write_access(project_id: str | None, current_user: Any, session: Session) -> None:
    await agent_compat_support.ensure_agent_write_access(_runtime(), project_id, current_user, session)


def _resolve_agent_tools(tool_ids: list[str], session: Session) -> tuple[list[str], list[dict[str, Any]]]:
    return agent_compat_support.resolve_agent_tools(_runtime(), tool_ids, session)


AgentBrowserAuthResolutionError = agent_run_runtime_support.AgentBrowserAuthResolutionError


def _browser_auth_selection(config: dict[str, Any]) -> tuple[str | None, bool]:
    return agent_compat_support.browser_auth_selection(_runtime(), config)


def _browser_auth_request_fields_set(request: Any) -> set[str]:
    return agent_compat_support.browser_auth_request_fields_set(_runtime(), request)


def _without_spec_generation_auth(config: dict[str, Any]) -> dict[str, Any]:
    return agent_compat_support.without_spec_generation_auth(_runtime(), config)


def _apply_report_spec_browser_auth_request(
    inherited_config: dict[str, Any],
    request: Any | None,
) -> tuple[dict[str, Any], bool]:
    return agent_compat_support.apply_report_spec_browser_auth_request(_runtime(), inherited_config, request)


def _resolve_agent_browser_auth_storage_path(
    *,
    run_id: str,
    project_id: str | None,
    config: dict[str, Any],
    run_dir: Path,
) -> Path | None:
    return agent_compat_support.resolve_agent_browser_auth_storage_path(
        _runtime(),
        run_id=run_id,
        project_id=project_id,
        config=config,
        run_dir=run_dir,
    )


def _prepare_custom_agent_mcp_config(
    run_id: str,
    storage_state_path: Path | str | None = None,
) -> Path:
    return agent_compat_support.prepare_custom_agent_mcp_config(
        _runtime(),
        run_id,
        storage_state_path=storage_state_path,
    )


def _prepare_spec_generation_mcp_config(
    run_dir: Path,
    storage_state_path: Path | str | None = None,
) -> dict[str, Any]:
    return agent_compat_support.prepare_spec_generation_mcp_config(
        _runtime(),
        run_dir,
        storage_state_path,
    )


def _safe_inherited_auth_config(value: Any) -> dict[str, Any]:
    return agent_compat_support.safe_inherited_auth_config(_runtime(), value)


def _build_spec_generation_source_config(
    source_config: dict[str, Any],
    *,
    target_url: str,
    project_id: str | None,
) -> dict[str, Any]:
    return agent_compat_support.build_spec_generation_source_config(
        _runtime(),
        source_config,
        target_url=target_url,
        project_id=project_id,
    )


def _spec_generation_auth_metadata(config: dict[str, Any], *, inherited: bool = True) -> dict[str, Any]:
    return agent_compat_support.spec_generation_auth_metadata(_runtime(), config, inherited=inherited)


def _resolve_playwright_chromium_executable() -> Path | None:
    return agent_compat_support.resolve_playwright_chromium_executable(_runtime())


def _playwright_chromium_probe_script(executable_path: str | None = None) -> str:
    return agent_compat_support.playwright_chromium_probe_script(_runtime(), executable_path)


def _probe_custom_agent_browser(timeout_seconds: int = 30) -> tuple[bool, str]:
    return agent_compat_support.probe_custom_agent_browser(_runtime(), timeout_seconds)


async def _probe_custom_agent_browser_with_slot(run_id: str, timeout_seconds: int = 30) -> tuple[bool, str]:
    return await agent_compat_support.probe_custom_agent_browser_with_slot(
        _runtime(),
        run_id,
        timeout_seconds,
    )


def _custom_agent_uses_browser_tools(allowed_tools: list[Any]) -> bool:
    return agent_compat_support.custom_agent_uses_browser_tools(_runtime(), allowed_tools)


def _custom_agent_browser_runs_via_queue() -> bool:
    return agent_compat_support.custom_agent_browser_runs_via_queue(_runtime())


def _agent_run_has_browser_tools(agent_type: str, config: dict[str, Any]) -> bool:
    return agent_compat_support.agent_run_has_browser_tools(_runtime(), agent_type, config)


async def _ensure_custom_agent_browser_available(
    run_id: str,
    *,
    force_direct_execution: bool = False,
) -> None:
    await agent_compat_support.ensure_custom_agent_browser_available(
        _runtime(),
        run_id,
        force_direct_execution=force_direct_execution,
    )


def _worker_managed_agent_browser_slot():
    return agent_compat_support.worker_managed_agent_browser_slot(_runtime())


def _short_tool_name(tool_name: str | None) -> str:
    return agent_compat_support.short_tool_name(_runtime(), tool_name)


def _update_agent_run_progress(run_id: str, patch: dict[str, Any]) -> None:
    agent_compat_support.update_agent_run_progress(_runtime(), run_id, patch)


def _generic_agent_runtime_prompt(agent_type: str, config: dict[str, Any]) -> str:
    return agent_compat_support.generic_agent_runtime_prompt(_runtime(), agent_type, config)


def _agent_tool_profile_for_run(agent_type: str, config: dict[str, Any]) -> str | None:
    return agent_compat_support.agent_tool_profile_for_run(_runtime(), agent_type, config)


def _resolve_known_agent_allowed_tools(
    agent_type: str,
    config: dict[str, Any],
    *,
    mcp_config_dir: Path | str | None = None,
) -> list[str] | None:
    return agent_compat_support.resolve_known_agent_allowed_tools(
        _runtime(),
        agent_type,
        config,
        mcp_config_dir=mcp_config_dir,
    )


def _resolve_agent_execution_test_data_context(
    *,
    project_id: str | None,
    refs: list[Any] | None = None,
    markdown: str | None = None,
) -> dict[str, Any]:
    return agent_compat_support.resolve_agent_execution_test_data_context(
        _runtime(),
        project_id=project_id,
        refs=refs,
        markdown=markdown,
    )
