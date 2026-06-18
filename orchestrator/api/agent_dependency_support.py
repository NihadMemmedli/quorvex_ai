"""Dependency factories for agent execution support modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.agent_tool_allowlists import get_agent_allowed_tools

from . import agent_background_runner_support, agent_exploratory
from .models_db import SpecMetadata as DBSpecMetadata
from .models_db import get_spec_metadata as get_db_spec_metadata


def _main_runtime() -> Any:
    from . import main

    return main


def agent_background_runner_dependencies(
    runtime: Any | None = None,
) -> agent_background_runner_support.AgentBackgroundRunnerDependencies:
    if runtime is None:
        runtime = _main_runtime()

    from orchestrator.services.agent_cancellation import owner_is_cancelled_sync
    from orchestrator.services.agent_run_finalizer import AgentRunFinalizer
    from orchestrator.services.agent_runtimes import AgentRuntimeContext, get_agent_runtime
    from orchestrator.services.agent_trace import (
        ensure_trace_snapshot,
        record_tool_result_spans,
        record_trace_span,
    )
    from orchestrator.services.load_test_lock import check_system_available

    return agent_background_runner_support.AgentBackgroundRunnerDependencies(
        runs_dir=runtime.RUNS_DIR,
        browser_pool=runtime.BROWSER_POOL,
        get_browser_pool=runtime.get_browser_pool,
        browser_op_type=runtime.BrowserOpType,
        worker_managed_agent_browser_slot=runtime._worker_managed_agent_browser_slot,
        db_session_factory=runtime.Session,
        db_engine=runtime.engine,
        agent_run_model=runtime.AgentRun,
        logger=runtime.logger,
        check_system_available=check_system_available,
        normalize_agent_runtime=runtime.normalize_agent_runtime,
        wait_if_agent_run_paused=runtime._wait_if_agent_run_paused,
        owner_is_cancelled_sync=owner_is_cancelled_sync,
        agent_run_has_browser_tools=runtime._agent_run_has_browser_tools,
        custom_agent_browser_runs_via_queue=runtime._custom_agent_browser_runs_via_queue,
        custom_agent_uses_browser_tools=runtime._custom_agent_uses_browser_tools,
        update_agent_run_progress=runtime._update_agent_run_progress,
        record_agent_run_event=runtime._record_agent_run_event,
        short_tool_name=runtime._short_tool_name,
        resolve_agent_browser_auth_storage_path=runtime._resolve_agent_browser_auth_storage_path,
        prepare_custom_agent_mcp_config=runtime._prepare_custom_agent_mcp_config,
        ensure_custom_agent_browser_available=runtime._ensure_custom_agent_browser_available,
        resolve_known_agent_allowed_tools=runtime._resolve_known_agent_allowed_tools,
        resolve_agent_execution_test_data_context=runtime._resolve_agent_execution_test_data_context,
        agent_tool_profile_for_run=runtime._agent_tool_profile_for_run,
        derive_project_id_from_url=runtime.derive_project_id_from_url,
        browser_runtime_status=runtime.browser_runtime_status,
        exploration_module=runtime.exploration,
        custom_agent_report_instructions=runtime.CUSTOM_AGENT_REPORT_INSTRUCTIONS,
        build_custom_agent_structured_report=runtime._build_custom_agent_structured_report,
        capture_custom_agent_report_memory=runtime._capture_custom_agent_report_memory,
        collect_agent_run_artifacts=runtime._collect_agent_run_artifacts,
        read_run_text_artifact=runtime._read_run_text_artifact,
        run_artifact_counts=runtime._run_artifact_counts,
        agent_partial_status=runtime.AGENT_PARTIAL_STATUS,
        agent_terminal_statuses=runtime.AGENT_TERMINAL_STATUSES,
        exploratory_result_is_terminal_failure=runtime._exploratory_result_is_terminal_failure,
        exploratory_result_has_usable_evidence=runtime._exploratory_result_has_usable_evidence,
        recover_custom_agent_partial_result=runtime._recover_custom_agent_partial_result,
        recover_exploratory_partial_result=runtime._recover_exploratory_partial_result,
        merge_agent_failure_into_result=runtime._merge_agent_failure_into_result,
        agent_run_summary=runtime._agent_run_summary,
        agent_run_finalizer_factory=AgentRunFinalizer,
        default_repo_root=runtime.DEFAULT_REPO_ROOT,
        coding_artifact_patch=runtime.CODING_ARTIFACT_PATCH,
        build_coding_agent_prompt=runtime.build_coding_agent_prompt,
        build_coding_tool_permission_guard=runtime.build_coding_tool_permission_guard,
        coding_agent_allowed_tools=runtime.coding_agent_allowed_tools,
        coding_agent_subagents=runtime.coding_agent_subagents,
        validate_patch_for_repo=runtime.validate_patch_for_repo,
        write_coding_artifacts=runtime.write_coding_artifacts,
        agent_runtime_context_class=AgentRuntimeContext,
        get_agent_runtime=get_agent_runtime,
        ensure_trace_snapshot=ensure_trace_snapshot,
        record_trace_span=record_trace_span,
        record_tool_result_spans=record_tool_result_spans,
    )


def agent_exploratory_dependencies(runtime: Any | None = None) -> agent_exploratory.AgentExploratoryDependencies:
    if runtime is None:
        runtime = _main_runtime()

    project_root = Path(__file__).parent.parent.parent
    return agent_exploratory.AgentExploratoryDependencies(
        agent_run_model=runtime.AgentRun,
        db_session_factory=runtime.Session,
        db_engine=runtime.engine,
        runs_dir=runtime.RUNS_DIR,
        project_root=project_root,
        flow_spec_jobs=runtime._flow_spec_jobs,
        max_flow_spec_jobs=runtime.MAX_FLOW_SPEC_JOBS,
        agent_partial_status=runtime.AGENT_PARTIAL_STATUS,
        agent_browser_auth_resolution_error=runtime.AgentBrowserAuthResolutionError,
        browser_runtime_status=runtime.browser_runtime_status,
        record_agent_run_event=runtime._record_agent_run_event,
        start_agent_run_temporal_or_fail=runtime._start_agent_run_temporal_or_fail,
        get_agent_report_run=runtime._get_agent_report_run,
        serialize_agent_run=runtime._serialize_agent_run,
        build_spec_generation_source_config=runtime._build_spec_generation_source_config,
        apply_report_spec_browser_auth_request=runtime._apply_report_spec_browser_auth_request,
        spec_generation_auth_metadata=runtime._spec_generation_auth_metadata,
        resolve_agent_browser_auth_storage_path=runtime._resolve_agent_browser_auth_storage_path,
        prepare_spec_generation_mcp_config=runtime._prepare_spec_generation_mcp_config,
        update_agent_run_progress=runtime._update_agent_run_progress,
        get_spec_metadata=get_db_spec_metadata,
        spec_metadata_model=DBSpecMetadata,
        short_tool_name=runtime._short_tool_name,
        run_flow_spec_generation=runtime._run_flow_spec_generation,
        normalize_agent_runtime=runtime.normalize_agent_runtime,
        get_agent_allowed_tools=get_agent_allowed_tools,
        logger_override=runtime.logger,
    )
