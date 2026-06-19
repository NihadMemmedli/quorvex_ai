"""Compatibility support for legacy agent helpers exposed from main."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_
from sqlmodel import Session, select

from utils.agent_report import _as_report_list as _agent_report_as_report_list
from utils.agent_report import _clean_text as _agent_report_clean_text

from . import (
    agent_background_runner_support,
    agent_definition_support,
    agent_dependency_support,
    agent_run_control,
    agent_run_observability,
    agent_run_report_support,
    agent_run_runtime,
    agent_run_runtime_support,
    agent_runtime_alias_support,
)


def sync_agent_run_observability_runs_dir(runtime: Any) -> None:
    agent_run_observability.RUNS_DIR = runtime.RUNS_DIR
    agent_run_runtime_support.RUNS_DIR = runtime.RUNS_DIR


def collect_agent_run_artifacts(runtime: Any, run_id: str) -> list[dict[str, Any]]:
    return agent_run_observability._collect_agent_run_artifacts(run_id)


def read_run_text_artifact(runtime: Any, run_id: str, name: str, max_chars: int | None = None) -> str:
    sync_agent_run_observability_runs_dir(runtime)
    return agent_run_observability._read_run_text_artifact(run_id, name, max_chars)


def read_run_json_artifact(runtime: Any, run_id: str, name: str) -> Any:
    sync_agent_run_observability_runs_dir(runtime)
    return agent_run_observability._read_run_json_artifact(run_id, name)


def run_artifact_counts(
    runtime: Any,
    run_id: str,
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sync_agent_run_observability_runs_dir(runtime)
    return agent_run_observability._run_artifact_counts(run_id, artifacts)


def jsonl_latest_url(runtime: Any, path: Path) -> str | None:
    return agent_run_observability._jsonl_latest_url(path)


def latest_observed_url_for_run(runtime: Any, run: Any) -> str | None:
    sync_agent_run_observability_runs_dir(runtime)
    return agent_run_observability._latest_observed_url_for_run(run)


def recover_custom_agent_partial_result(runtime: Any, run: Any, error: Exception | str) -> dict[str, Any] | None:
    agent_run_runtime_support.RUNS_DIR = runtime.RUNS_DIR
    return agent_run_runtime_support._recover_custom_agent_partial_result(run, error)


def agent_run_summary(runtime: Any, run: Any) -> str | None:
    return agent_run_runtime_support._agent_run_summary(run)


def exploratory_result_is_zero_evidence_failure(runtime: Any, result: Any) -> bool:
    return agent_run_runtime_support._exploratory_result_is_zero_evidence_failure(result)


def exploratory_result_is_terminal_failure(runtime: Any, result: Any) -> bool:
    return agent_run_runtime_support._exploratory_result_is_terminal_failure(result)


def exploratory_result_has_usable_evidence(runtime: Any, result: Any) -> bool:
    return agent_run_runtime_support._exploratory_result_has_usable_evidence(result)


def merge_agent_failure_into_result(
    runtime: Any,
    result: Any,
    error: Exception | str,
    *,
    failure_reason: str,
) -> dict[str, Any]:
    return agent_run_runtime_support._merge_agent_failure_into_result(result, error, failure_reason=failure_reason)


def recover_exploratory_partial_result(
    runtime: Any,
    run_id: str,
    config: dict[str, Any],
    error: Exception | str,
) -> dict[str, Any] | None:
    agent_run_runtime_support.RUNS_DIR = runtime.RUNS_DIR
    return agent_run_runtime_support._recover_exploratory_partial_result(run_id, config, error)


def filter_agent_run_project(runtime: Any, run: Any, project_id: str | None) -> None:
    agent_run_observability._filter_agent_run_project(run, project_id)


def agent_report_project_filter(runtime: Any, project_id: str):
    if project_id == "default":
        return or_(runtime.AgentRun.project_id == None, runtime.AgentRun.project_id == "default")
    return or_(runtime.AgentRun.project_id == None, runtime.AgentRun.project_id == project_id)


def get_agent_report_run(runtime: Any, session: Session, run_id: str, project_id: str) -> Any:
    run = session.exec(
        select(runtime.AgentRun).where(
            runtime.AgentRun.id == run_id,
            runtime._agent_report_project_filter(project_id),
        )
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def coerce_progress_int(runtime: Any, value: Any, default: int = 0) -> int:
    return agent_run_observability._coerce_progress_int(value, default)


def normalize_agent_run_progress(runtime: Any, progress: dict[str, Any] | None) -> dict[str, Any]:
    return agent_run_observability._normalize_agent_run_progress(progress)


def record_agent_run_event(
    runtime: Any,
    run_id: str,
    *,
    event_type: str,
    message: str,
    level: str = "info",
    payload: dict[str, Any] | None = None,
    agent_task_id: str | None = None,
    session: Session | None = None,
) -> None:
    agent_run_runtime.record_agent_run_event(
        run_id,
        event_type=event_type,
        message=message,
        level=level,
        payload=payload,
        agent_task_id=agent_task_id,
        session=session,
    )


async def start_agent_run_temporal_or_fail(
    runtime: Any,
    run: Any,
    session: Session,
    *,
    workflow_attempt: int | None = None,
) -> None:
    await agent_run_runtime.start_agent_run_temporal_or_fail(
        run,
        session,
        workflow_attempt=workflow_attempt,
    )


async def agent_run_temporal_payload(runtime: Any, run: Any) -> dict[str, Any]:
    return await agent_run_observability._agent_run_temporal_payload(run)


async def signal_agent_run_temporal(runtime: Any, run: Any, signal_name: str, *args) -> None:
    await agent_run_control._signal_agent_run_temporal(run, signal_name, *args)


async def cancel_agent_run_queue_task(runtime: Any, run: Any) -> dict[str, Any] | None:
    return await agent_run_control._cancel_agent_run_queue_task(run)


async def wait_if_agent_run_paused(runtime: Any, run_id: str, poll_interval: float = 0.5) -> bool:
    return await agent_run_control._wait_if_agent_run_paused(run_id, poll_interval)


def mark_agent_run_paused(runtime: Any, run: Any, message: str = "Agent is paused") -> None:
    agent_run_control._mark_agent_run_paused(run, message)


def mark_agent_run_cancelled(runtime: Any, run: Any, message: str = "Agent cancelled") -> None:
    agent_run_control._mark_agent_run_cancelled(run, message)


def agent_run_health(runtime: Any, run: Any, session: Session | None = None) -> dict[str, Any]:
    return agent_run_observability._agent_run_health(run, session)


def serialize_agent_run(runtime: Any, run: Any, session: Session | None = None) -> dict[str, Any]:
    return agent_run_observability._serialize_agent_run(run, session)


def safe_json_dict(runtime: Any, value: str | None) -> dict[str, Any]:
    return agent_run_observability._safe_json_dict(value)


def compact_agent_run_config(runtime: Any, config: dict[str, Any]) -> dict[str, Any]:
    return agent_run_observability._compact_agent_run_config(config)


def compact_agent_run_summary(runtime: Any, progress: dict[str, Any]) -> str | None:
    return agent_run_observability._compact_agent_run_summary(progress)


def encode_agent_run_cursor(runtime: Any, created_at: datetime, run_id: str) -> str:
    return agent_run_observability._encode_agent_run_cursor(created_at, run_id)


def decode_agent_run_cursor(runtime: Any, cursor: str | None) -> tuple[datetime, str] | None:
    return agent_run_observability._decode_agent_run_cursor(cursor)


def agent_run_project_filters(runtime: Any, project_id: str | None) -> list[Any]:
    return agent_run_observability._agent_run_project_filters(project_id)


def agent_run_search_filter(runtime: Any, q: str | None) -> Any | None:
    return agent_run_observability._agent_run_search_filter(q)


def agent_run_status_filter(runtime: Any, status: str | None) -> Any | None:
    return agent_run_observability._agent_run_status_filter(status)


def agent_run_type_filter(runtime: Any, agent_type: str | None) -> Any | None:
    return agent_run_observability._agent_run_type_filter(agent_type)


def agent_run_history_filters(
    runtime: Any,
    *,
    project_id: str | None,
    status: str | None = None,
    agent_type: str | None = None,
    q: str | None = None,
) -> list[Any]:
    return agent_run_observability._agent_run_history_filters(
        project_id=project_id,
        status=status,
        agent_type=agent_type,
        q=q,
    )


def agent_run_history_counts(runtime: Any, session: Session, *, project_id: str | None, q: str | None) -> dict[str, Any]:
    return agent_run_observability._agent_run_history_counts(session, project_id=project_id, q=q)


def serialize_agent_run_summary_row(runtime: Any, row: Any) -> dict[str, Any]:
    return agent_run_observability._serialize_agent_run_summary_row(row)


async def live_agent_queue_progress(runtime: Any, run: Any) -> dict[str, Any]:
    return await agent_run_observability._live_agent_queue_progress(run)


async def serialize_agent_run_live(runtime: Any, run: Any, session: Session | None = None) -> dict[str, Any]:
    return await agent_run_observability._serialize_agent_run_live(run, session)


def clean_text(runtime: Any, value: Any, max_len: int = 2000) -> str:
    return _agent_report_clean_text(value, max_len)


def as_report_list(runtime: Any, value: Any) -> list[Any]:
    return _agent_report_as_report_list(value)


def report_confidence(runtime: Any, value: str | None) -> float:
    return agent_run_report_support._report_confidence(value)


def report_importance(runtime: Any, value: str | None) -> float:
    return agent_run_report_support._report_importance(value)


def report_requirement_confidence(runtime: Any, value: Any) -> float:
    return agent_run_report_support._report_requirement_confidence(value)


def report_requirement_acceptance_criteria(runtime: Any, item: dict[str, Any]) -> list[str]:
    return agent_run_report_support._report_requirement_acceptance_criteria(item)


def requirement_create_body_from_report_item(runtime: Any, item: dict[str, Any]) -> dict[str, Any]:
    return agent_run_report_support._requirement_create_body_from_report_item(item)


def normalize_report_item_type(runtime: Any, item_type: str | None) -> str:
    return agent_run_report_support._normalize_report_item_type(item_type)


def stored_custom_agent_report(runtime: Any, run: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    return agent_run_report_support._stored_custom_agent_report(run)


def normalize_report_patch_value(runtime: Any, field: str, value: Any) -> Any:
    return agent_run_report_support._normalize_report_patch_value(field, value)


def editable_report_item_patch(runtime: Any, item_type: str, patch: dict[str, Any]) -> dict[str, Any]:
    return agent_run_report_support._editable_report_item_patch(item_type, patch)


def find_report_item(runtime: Any, report: dict[str, Any], item_type: str, item_id: str) -> dict[str, Any]:
    return agent_run_report_support._find_report_item(report, item_type, item_id)


def capture_custom_agent_report_memory(
    runtime: Any,
    *,
    run_id: str,
    project_id: str | None,
    structured_report: dict[str, Any],
    config: dict[str, Any],
) -> list[str]:
    return agent_run_report_support._capture_custom_agent_report_memory(
        run_id=run_id,
        project_id=project_id,
        structured_report=structured_report,
        config=config,
    )


def sync_agent_tool_catalog(runtime: Any, session: Session) -> list[Any]:
    return agent_definition_support._sync_agent_tool_catalog(session)


def serialize_agent_tool(runtime: Any, tool: Any) -> dict[str, Any]:
    return agent_definition_support._serialize_agent_tool(tool)


def serialize_agent_definition(
    runtime: Any,
    definition: Any,
    tools_by_id: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return agent_definition_support._serialize_agent_definition(definition, tools_by_id)


def get_agent_definition_or_404(runtime: Any, definition_id: str, project_id: str | None, session: Session) -> Any:
    return agent_definition_support._get_agent_definition_or_404(definition_id, project_id, session)


async def ensure_agent_write_access(runtime: Any, project_id: str | None, current_user: Any, session: Session) -> None:
    await agent_definition_support._ensure_agent_write_access(project_id, current_user, session)


def resolve_agent_tools(runtime: Any, tool_ids: list[str], session: Session) -> tuple[list[str], list[dict[str, Any]]]:
    return agent_definition_support._resolve_agent_tools(tool_ids, session)


def browser_auth_selection(runtime: Any, config: dict[str, Any]) -> tuple[str | None, bool]:
    return agent_run_runtime_support._browser_auth_selection(config)


def browser_auth_request_fields_set(runtime: Any, request: Any) -> set[str]:
    return agent_run_runtime_support._browser_auth_request_fields_set(request)


def without_spec_generation_auth(runtime: Any, config: dict[str, Any]) -> dict[str, Any]:
    return agent_run_runtime_support._without_spec_generation_auth(config)


def apply_report_spec_browser_auth_request(
    runtime: Any,
    inherited_config: dict[str, Any],
    request: Any | None,
) -> tuple[dict[str, Any], bool]:
    return agent_run_runtime_support._apply_report_spec_browser_auth_request(inherited_config, request)


def resolve_agent_browser_auth_storage_path(
    runtime: Any,
    *,
    run_id: str,
    project_id: str | None,
    config: dict[str, Any],
    run_dir: Path,
) -> Path | None:
    return agent_runtime_alias_support._resolve_agent_browser_auth_storage_path(
        run_id=run_id,
        project_id=project_id,
        config=config,
        run_dir=run_dir,
        runtime=runtime,
    )


def prepare_custom_agent_mcp_config(
    runtime: Any,
    run_id: str,
    storage_state_path: Path | str | None = None,
) -> Path:
    return agent_runtime_alias_support._prepare_custom_agent_mcp_config(
        run_id,
        storage_state_path=storage_state_path,
        runtime=runtime,
    )


def prepare_spec_generation_mcp_config(
    runtime: Any,
    run_dir: Path,
    storage_state_path: Path | str | None = None,
) -> dict[str, Any]:
    return agent_run_runtime_support._prepare_spec_generation_mcp_config(run_dir, storage_state_path)


def safe_inherited_auth_config(runtime: Any, value: Any) -> dict[str, Any]:
    return agent_run_runtime_support._safe_inherited_auth_config(value)


def build_spec_generation_source_config(
    runtime: Any,
    source_config: dict[str, Any],
    *,
    target_url: str,
    project_id: str | None,
) -> dict[str, Any]:
    return agent_run_runtime_support._build_spec_generation_source_config(
        source_config,
        target_url=target_url,
        project_id=project_id,
    )


def spec_generation_auth_metadata(runtime: Any, config: dict[str, Any], *, inherited: bool = True) -> dict[str, Any]:
    return agent_run_runtime_support._spec_generation_auth_metadata(config, inherited=inherited)


def resolve_playwright_chromium_executable(runtime: Any) -> Path | None:
    return agent_run_runtime_support._resolve_playwright_chromium_executable()


def playwright_chromium_probe_script(runtime: Any, executable_path: str | None = None) -> str:
    return agent_run_runtime_support._playwright_chromium_probe_script(executable_path)


def probe_custom_agent_browser(runtime: Any, timeout_seconds: int = 30) -> tuple[bool, str]:
    return agent_runtime_alias_support._probe_custom_agent_browser(timeout_seconds, runtime=runtime)


async def probe_custom_agent_browser_with_slot(
    runtime: Any,
    run_id: str,
    timeout_seconds: int = 30,
) -> tuple[bool, str]:
    return await agent_runtime_alias_support._probe_custom_agent_browser_with_slot(
        run_id,
        timeout_seconds,
        runtime=runtime,
    )


def custom_agent_uses_browser_tools(runtime: Any, allowed_tools: list[Any]) -> bool:
    return agent_run_runtime_support._custom_agent_uses_browser_tools(allowed_tools)


def custom_agent_browser_runs_via_queue(runtime: Any) -> bool:
    return agent_run_runtime_support._custom_agent_browser_runs_via_queue()


def agent_run_has_browser_tools(runtime: Any, agent_type: str, config: dict[str, Any]) -> bool:
    return agent_run_runtime_support._agent_run_has_browser_tools(agent_type, config)


async def ensure_custom_agent_browser_available(
    runtime: Any,
    run_id: str,
    *,
    force_direct_execution: bool = False,
) -> None:
    await agent_runtime_alias_support._ensure_custom_agent_browser_available(
        run_id,
        force_direct_execution=force_direct_execution,
        runtime=runtime,
    )


def worker_managed_agent_browser_slot(runtime: Any):
    return agent_runtime_alias_support._worker_managed_agent_browser_slot(runtime=runtime)


def short_tool_name(runtime: Any, tool_name: str | None) -> str:
    if not tool_name:
        return ""
    return str(tool_name).rsplit("__", 1)[-1] if "__" in str(tool_name) else str(tool_name)


def update_agent_run_progress(runtime: Any, run_id: str, patch: dict[str, Any]) -> None:
    agent_run_runtime_support.update_agent_run_progress(run_id, patch)


def generic_agent_runtime_prompt(runtime: Any, agent_type: str, config: dict[str, Any]) -> str:
    return agent_run_runtime_support._generic_agent_runtime_prompt(agent_type, config)


def agent_tool_profile_for_run(runtime: Any, agent_type: str, config: dict[str, Any]) -> str | None:
    return agent_run_runtime_support._agent_tool_profile_for_run(agent_type, config)


def resolve_known_agent_allowed_tools(
    runtime: Any,
    agent_type: str,
    config: dict[str, Any],
    *,
    mcp_config_dir: Path | str | None = None,
) -> list[str] | None:
    return agent_run_runtime_support._resolve_known_agent_allowed_tools(
        agent_type,
        config,
        mcp_config_dir=mcp_config_dir,
    )


def resolve_agent_execution_test_data_context(
    runtime: Any,
    *,
    project_id: str | None,
    refs: list[Any] | None = None,
    markdown: str | None = None,
) -> dict[str, Any]:
    return agent_runtime_alias_support._resolve_agent_execution_test_data_context(
        project_id=project_id,
        refs=refs,
        markdown=markdown,
        runtime=runtime,
    )


def agent_background_runner_dependencies(runtime: Any) -> agent_background_runner_support.AgentBackgroundRunnerDependencies:
    return agent_dependency_support.agent_background_runner_dependencies(runtime)
