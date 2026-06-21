"""Support runner for background AgentRun execution."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentBackgroundRunnerDependencies:
    runs_dir: Path
    browser_pool: Any | None
    get_browser_pool: Callable[..., Any]
    browser_op_type: Any
    worker_managed_agent_browser_slot: Callable[..., Any]
    db_session_factory: Callable[..., Any]
    db_engine: Any
    agent_run_model: type[Any]
    logger: logging.Logger
    check_system_available: Callable[..., Any]
    normalize_agent_runtime: Callable[[Any], str]
    wait_if_agent_run_paused: Callable[..., Any]
    owner_is_cancelled_sync: Callable[[str, str], bool]
    agent_run_has_browser_tools: Callable[[str, dict[str, Any]], bool]
    custom_agent_browser_runs_via_queue: Callable[[], bool]
    custom_agent_uses_browser_tools: Callable[[list[Any]], bool]
    update_agent_run_progress: Callable[[str, dict[str, Any]], None]
    record_agent_run_event: Callable[..., None]
    short_tool_name: Callable[[str | None], str]
    resolve_agent_browser_auth_storage_path: Callable[..., Path | None]
    prepare_custom_agent_mcp_config: Callable[..., Path]
    ensure_custom_agent_browser_available: Callable[..., Any]
    resolve_known_agent_allowed_tools: Callable[..., list[str] | None]
    resolve_agent_execution_test_data_context: Callable[..., dict[str, Any]]
    agent_tool_profile_for_run: Callable[[str, dict[str, Any]], str | None]
    derive_project_id_from_url: Callable[[str | None], str | None]
    browser_runtime_status: Callable[[], dict[str, Any]]
    exploration_module: Any
    custom_agent_report_instructions: str
    build_custom_agent_structured_report: Callable[..., dict[str, Any]]
    capture_custom_agent_report_memory: Callable[..., list[str]]
    collect_agent_run_artifacts: Callable[[str], list[dict[str, Any]]]
    read_run_text_artifact: Callable[..., str]
    run_artifact_counts: Callable[..., dict[str, Any]]
    agent_partial_status: str
    agent_terminal_statuses: set[str]
    exploratory_result_is_terminal_failure: Callable[[Any], bool]
    exploratory_result_has_usable_evidence: Callable[[Any], bool]
    recover_custom_agent_partial_result: Callable[..., dict[str, Any] | None]
    recover_exploratory_partial_result: Callable[..., dict[str, Any] | None]
    merge_agent_failure_into_result: Callable[..., dict[str, Any]]
    agent_run_summary: Callable[[Any], str | None]
    agent_run_finalizer_factory: Callable[..., Any]
    default_repo_root: Path
    coding_artifact_patch: str
    build_coding_agent_prompt: Callable[..., str]
    build_coding_tool_permission_guard: Callable[..., Any]
    coding_agent_allowed_tools: Callable[[], list[str]]
    coding_agent_subagents: Callable[[], Any]
    validate_patch_for_repo: Callable[..., Any]
    write_coding_artifacts: Callable[..., dict[str, Any]]
    agent_runtime_context_class: type[Any]
    get_agent_runtime: Callable[[str], Any]
    ensure_trace_snapshot: Callable[..., Any]
    record_trace_span: Callable[..., None]
    record_tool_result_spans: Callable[..., None]


async def execute_agent_background(
    run_id: str,
    agent_type: str,
    config: dict[str, Any],
    *,
    deps: AgentBackgroundRunnerDependencies,
) -> None:
    """Execute an agent in the background with unified browser pool management.

    Uses BrowserResourcePool to limit concurrent browser operations across
    ALL operation types (test runs, explorations, agents, PRD).
    """
    Session = deps.db_session_factory
    engine = deps.db_engine
    AgentRun = deps.agent_run_model
    RUNS_DIR = deps.runs_dir
    BROWSER_POOL = deps.browser_pool
    BrowserOpType = deps.browser_op_type
    AgentRuntimeContext = deps.agent_runtime_context_class
    AgentRunFinalizer = deps.agent_run_finalizer_factory
    AGENT_PARTIAL_STATUS = deps.agent_partial_status
    AGENT_TERMINAL_STATUSES = deps.agent_terminal_statuses
    CODING_ARTIFACT_PATCH = deps.coding_artifact_patch
    CUSTOM_AGENT_REPORT_INSTRUCTIONS = deps.custom_agent_report_instructions
    DEFAULT_REPO_ROOT = deps.default_repo_root

    logger = deps.logger
    get_browser_pool = deps.get_browser_pool
    normalize_agent_runtime = deps.normalize_agent_runtime
    owner_is_cancelled_sync = deps.owner_is_cancelled_sync
    check_system_available = deps.check_system_available
    get_agent_runtime = deps.get_agent_runtime
    ensure_trace_snapshot = deps.ensure_trace_snapshot
    record_trace_span = deps.record_trace_span
    record_tool_result_spans = deps.record_tool_result_spans
    exploration = deps.exploration_module
    derive_project_id_from_url = deps.derive_project_id_from_url
    browser_runtime_status = deps.browser_runtime_status
    build_coding_agent_prompt = deps.build_coding_agent_prompt
    build_coding_tool_permission_guard = deps.build_coding_tool_permission_guard
    coding_agent_allowed_tools = deps.coding_agent_allowed_tools
    coding_agent_subagents = deps.coding_agent_subagents
    validate_patch_for_repo = deps.validate_patch_for_repo
    write_coding_artifacts = deps.write_coding_artifacts

    _wait_if_agent_run_paused = deps.wait_if_agent_run_paused
    _agent_run_has_browser_tools = deps.agent_run_has_browser_tools
    _worker_managed_agent_browser_slot = deps.worker_managed_agent_browser_slot
    _custom_agent_browser_runs_via_queue = deps.custom_agent_browser_runs_via_queue
    _resolve_agent_browser_auth_storage_path = deps.resolve_agent_browser_auth_storage_path
    _resolve_known_agent_allowed_tools = deps.resolve_known_agent_allowed_tools
    _resolve_agent_execution_test_data_context = deps.resolve_agent_execution_test_data_context
    _agent_tool_profile_for_run = deps.agent_tool_profile_for_run
    _update_agent_run_progress = deps.update_agent_run_progress
    _short_tool_name = deps.short_tool_name
    _record_agent_run_event = deps.record_agent_run_event
    _read_run_text_artifact = deps.read_run_text_artifact
    _custom_agent_uses_browser_tools = deps.custom_agent_uses_browser_tools
    _ensure_custom_agent_browser_available = deps.ensure_custom_agent_browser_available
    _prepare_custom_agent_mcp_config = deps.prepare_custom_agent_mcp_config
    _collect_agent_run_artifacts = deps.collect_agent_run_artifacts
    _build_custom_agent_structured_report = deps.build_custom_agent_structured_report
    _capture_custom_agent_report_memory = deps.capture_custom_agent_report_memory
    _exploratory_result_is_terminal_failure = deps.exploratory_result_is_terminal_failure
    _agent_run_summary = deps.agent_run_summary
    _recover_custom_agent_partial_result = deps.recover_custom_agent_partial_result
    _exploratory_result_has_usable_evidence = deps.exploratory_result_has_usable_evidence
    _merge_agent_failure_into_result = deps.merge_agent_failure_into_result
    _recover_exploratory_partial_result = deps.recover_exploratory_partial_result
    _run_artifact_counts = deps.run_artifact_counts

    await check_system_available("agent run")

    try:
        runtime_name = normalize_agent_runtime(config.get("runtime"))
        if not await _wait_if_agent_run_paused(run_id):
            return
        def _agent_run_cancelled() -> bool:
            return owner_is_cancelled_sync("agent_run", run_id)

        uses_worker_browser_slot = (
            _agent_run_has_browser_tools(agent_type, config)
            and not bool(config.get("_force_direct_agent_execution"))
            and _custom_agent_browser_runs_via_queue()
        )
        if uses_worker_browser_slot:
            slot_context = _worker_managed_agent_browser_slot()
        else:
            pool = BROWSER_POOL or await get_browser_pool()
            slot_context = pool.browser_slot(
                request_id=run_id,
                operation_type=BrowserOpType.AGENT,
                description=f"Agent: {agent_type}",
            )

        async with slot_context as acquired:
            if not acquired:
                # Timeout waiting for slot
                logger.warning(f"Agent {run_id} failed to acquire browser slot (timeout)")
                raise TimeoutError("Timeout waiting for browser slot")

            if not await _wait_if_agent_run_paused(run_id):
                return

            # Update status to "running" now that we have a slot
            with Session(engine) as session:
                run = session.get(AgentRun, run_id)
                if run and run.status == "queued":
                    runtime_name = normalize_agent_runtime(getattr(run, "runtime", None) or config.get("runtime"))
                    run.status = "running"
                    run.started_at = run.started_at or datetime.utcnow()
                    session.add(run)
                    session.commit()

            logger.info(f"Browser slot acquired for agent {run_id}")

            # Use relative imports since server runs from orchestrator/ directory
            from orchestrator.agents.exploratory_agent import ExploratoryAgent
            from orchestrator.agents.spec_synthesis_agent import SpecSynthesisAgent
            from orchestrator.agents.spec_writer_agent import SpecWriterAgent

            result = {}
            if agent_type == "exploratory":
                agent = ExploratoryAgent()
                agent.owner_type = "agent_run"
                agent.owner_id = run_id
                agent.owner_label = f"Agent run {run_id}"
                run_dir = RUNS_DIR / run_id
                storage_state_path = _resolve_agent_browser_auth_storage_path(
                    run_id=run_id,
                    project_id=config.get("project_id"),
                    config=config,
                    run_dir=run_dir,
                )
                run_dir = exploration._prepare_exploration_mcp_config(run_id, storage_state_path=storage_state_path)
                agent.agent_cwd = str(run_dir)
                resolved_allowed_tools = _resolve_known_agent_allowed_tools(
                    agent_type,
                    config,
                    mcp_config_dir=run_dir,
                )
                if resolved_allowed_tools is not None:
                    config["allowed_tools"] = resolved_allowed_tools
                agent.agent_tool_profile = config.get("agent_tool_profile") or "app-explorer-basic"
                agent.on_task_enqueued = lambda task_id: _update_agent_run_progress(
                    run_id,
                    {
                        "phase": "queued",
                        "message": "Agent task queued for worker",
                        "agent_task_id": task_id,
                    },
                )

                # Inject project_id from URL if not present
                if "project_id" not in config:
                    config["project_id"] = derive_project_id_from_url(config.get("url"))

                # Pass run_id to agent for file storage
                config["run_id"] = run_id
                test_data_refs = config.get("test_data_refs") if isinstance(config.get("test_data_refs"), list) else []
                if test_data_refs:
                    resolved_test_data = _resolve_agent_execution_test_data_context(
                        project_id=config.get("project_id"),
                        refs=test_data_refs,
                        markdown=json.dumps(config, default=str),
                    )
                    runtime_fixtures = resolved_test_data.get("runtime_fixtures") or {}
                    if runtime_fixtures:
                        merged_test_data = config.get("test_data") if isinstance(config.get("test_data"), dict) else {}
                        for ref, fixture in runtime_fixtures.items():
                            if not isinstance(fixture, dict):
                                continue
                            if fixture.get("data") is not None:
                                merged_test_data[ref] = fixture.get("data")
                            elif fixture.get("text"):
                                merged_test_data[ref] = fixture.get("text")
                        config["test_data"] = merged_test_data
                    if resolved_test_data.get("prompt_markdown"):
                        existing_context = str(config.get("browser_memory_context") or "").strip()
                        test_data_context = (
                            f"{resolved_test_data['prompt_markdown']}\n\n"
                            "If you delegate work to subagents, copy the relevant test-data ref names and plaintext values needed for execution "
                            "into each delegated prompt. Subagents do not automatically inherit this full parent context."
                        )
                        config["browser_memory_context"] = "\n\n".join(
                            part for part in [existing_context, test_data_context] if part
                        )
                if not await _wait_if_agent_run_paused(run_id):
                    return
                result = await agent.run(config)

                # Note: Persistence is now handled within ExploratoryAgent.run() -> _process_results()

                # Auto-analyze prerequisites after exploration completes
                try:
                    from pathlib import Path

                    from agents.prerequisites_agent import PrerequisitesAgent

                    logger.info(f"Auto-analyzing prerequisites for run {run_id}")

                    project_root = Path(__file__).parent.parent.parent
                    flows_file = project_root / "runs" / run_id / "flows.json"

                    if flows_file.exists():
                        with open(flows_file) as f:
                            flows_data = json.load(f)

                        flows = flows_data.get("flows", [])
                        if flows:
                            prereq_agent = PrerequisitesAgent()
                            prereq_result = await prereq_agent.run(
                                {
                                    "flows": flows,
                                    "action_trace": result.get("action_trace", []),
                                    "exploration_url": config.get("url", ""),
                                    "auth_config": config.get("auth", {}),
                                    "test_data": config.get("test_data", {}),
                                }
                            )

                            # Save enriched flows back to flows.json
                            enriched_flows = prereq_result.get("enriched_flows", flows)
                            with open(flows_file, "w") as f:
                                json.dump(
                                    {
                                        "flows": enriched_flows,
                                        "flow_graph": prereq_result.get("flow_graph", {}),
                                        "entities_discovered": prereq_result.get("entities_discovered", []),
                                        "prerequisites_analyzed_at": prereq_result.get("analyzed_at"),
                                    },
                                    f,
                                    indent=2,
                                )

                            # Add prerequisites summary to result
                            result["prerequisites_analysis"] = {
                                "summary": prereq_result.get("summary"),
                                "entities_discovered": prereq_result.get("entities_discovered", []),
                                "flow_graph": prereq_result.get("flow_graph", {}),
                            }
                            logger.info(f"Prerequisites analysis complete: {prereq_result.get('summary')}")
                        else:
                            logger.warning("No flows found to analyze")
                    else:
                        logger.debug(f"flows.json not found at {flows_file}")

                except Exception as prereq_error:
                    logger.warning(f"Prerequisites auto-analysis failed: {prereq_error}")
                    # Don't fail the whole run, just log the error
                    result["prerequisites_analysis"] = {"error": str(prereq_error)}

            elif agent_type == "writer":
                agent = SpecWriterAgent()
                agent.owner_type = "agent_run"
                agent.owner_id = run_id
                agent.owner_label = f"Agent run {run_id}"
                agent.agent_tool_profile = _agent_tool_profile_for_run(agent_type, config)
                result = await agent.run(config)
            elif agent_type == "spec-synthesis":
                agent = SpecSynthesisAgent()
                agent.owner_type = "agent_run"
                agent.owner_id = run_id
                agent.owner_label = f"Agent run {run_id}"
                agent.agent_tool_profile = _agent_tool_profile_for_run(agent_type, config)
                result = await agent.run(config)
            elif agent_type == "coding":
                repo_root = DEFAULT_REPO_ROOT
                run_dir = RUNS_DIR / run_id
                run_dir.mkdir(parents=True, exist_ok=True)
                task_prompt = str(config.get("prompt") or config.get("task") or "").strip()
                if not task_prompt:
                    raise ValueError("Coding agent prompt is required")

                allowed_tools = coding_agent_allowed_tools()
                final_prompt = build_coding_agent_prompt(task_prompt, repo_root)
                trace_snapshot = ensure_trace_snapshot(
                    run_id=run_id,
                    prompt=final_prompt,
                    context=None,
                    runtime=runtime_name,
                    model=config.get("model"),
                    model_tier=config.get("model_tier") or "tool_deep",
                    allowed_tools=allowed_tools,
                    test_data_refs=[],
                    runtime_diagnostics={
                        "runtime": runtime_name,
                        "agent_type": "coding",
                        "repo_root": str(repo_root),
                        "mode": "propose_diff_only",
                    },
                )

                _update_agent_run_progress(
                    run_id,
                    {
                        "phase": "starting",
                        "message": "Starting coding agent in propose-diff-only mode",
                        "runtime": runtime_name,
                        "repo_root": str(repo_root),
                        "autonomy_mode": "propose_diff_only",
                    },
                )

                def _on_coding_tool_use(tool_name: str, tool_input: dict[str, Any]) -> None:
                    _update_agent_run_progress(
                        run_id,
                        {
                            "phase": "tool_use",
                            "message": f"Using {_short_tool_name(tool_name)}",
                            "runtime": runtime_name,
                            "last_tool": tool_name,
                            "last_tool_input": tool_input,
                            "autonomy_mode": "propose_diff_only",
                        },
                    )
                    _record_agent_run_event(
                        run_id,
                        event_type="tool_call",
                        message=f"Using {_short_tool_name(tool_name)}.",
                        payload={
                            "tool_name": tool_name,
                            "tool_label": _short_tool_name(tool_name),
                        },
                    )

                def _on_coding_progress(progress: dict[str, Any]) -> None:
                    last_tool = progress.get("last_tool")
                    record_trace_span(
                        run_id=run_id,
                        trace_id=trace_snapshot.id if trace_snapshot else None,
                        span_type="provider_event",
                        name=str(progress.get("phase") or "coding progress"),
                        message=str(progress.get("message") or "Coding agent runtime progress."),
                        tool_name=str(last_tool) if last_tool else None,
                        payload={"progress": progress, "runtime": runtime_name},
                    )
                    _update_agent_run_progress(
                        run_id,
                        {
                            **progress,
                            "runtime": runtime_name,
                            "phase": progress.get("phase") or "running",
                            "message": f"Using {_short_tool_name(str(last_tool))}" if last_tool else "Coding agent is running",
                            "autonomy_mode": "propose_diff_only",
                        },
                    )

                runtime_adapter = get_agent_runtime(runtime_name)
                runtime_context = AgentRuntimeContext(
                    timeout_seconds=int(config.get("timeout_seconds") or 1800),
                    allowed_tools=allowed_tools,
                    tools=allowed_tools,
                    permission_mode=str(config.get("permission_mode") or "plan"),
                    session_dir=run_dir,
                    on_tool_use=_on_coding_tool_use,
                    on_progress=_on_coding_progress,
                    cwd=repo_root,
                    owner_type="agent_run",
                    owner_id=run_id,
                    owner_label=f"Coding agent run {run_id}",
                    memory_project_id=config.get("project_id"),
                    memory_agent_type="CodingAgent",
                    memory_source_type="coding_agent_run",
                    memory_source_id=run_id,
                    memory_stage="coding_agent",
                    inject_memory=False,
                    capture_memory=False,
                    force_direct_execution=True,
                    model=config.get("model"),
                    model_tier=config.get("model_tier") or "tool_deep",
                    enable_file_checkpointing=True,
                    agents=coding_agent_subagents(),
                    tool_permission_guard=build_coding_tool_permission_guard(),
                    agent_name="CodingAgent",
                    metadata={
                        "agent_type": "coding",
                        "run_id": run_id,
                        "repo_root": str(repo_root),
                        "autonomy_mode": "propose_diff_only",
                    },
                    trace_id=trace_snapshot.id if trace_snapshot else None,
                    prompt_hash=trace_snapshot.prompt_hash if trace_snapshot else None,
                    agent_run_id=run_id,
                    is_cancelled=_agent_run_cancelled,
                )
                if not await _wait_if_agent_run_paused(run_id):
                    return
                agent_result = await runtime_adapter.run(final_prompt, runtime_context)
                if agent_result.cancelled:
                    raise asyncio.CancelledError("Agent run cancelled")
                record_tool_result_spans(run_id, agent_result.tool_calls)
                raw_output = agent_result.output or ""
                (run_dir / "raw_output.txt").write_text(raw_output, encoding="utf-8")
                artifact_info = write_coding_artifacts(run_dir, raw_output)
                patch_text = _read_run_text_artifact(run_id, CODING_ARTIFACT_PATCH)
                patch_valid = False
                patch_validation_error = None
                if patch_text:
                    try:
                        validate_patch_for_repo(patch_text, repo_root)
                        patch_valid = True
                    except Exception as validation_error:
                        patch_validation_error = str(validation_error)

                result = {
                    "summary": artifact_info.get("summary") or (raw_output[:500] if raw_output else agent_result.error),
                    "output": raw_output,
                    "review": artifact_info.get("review"),
                    "tests": artifact_info.get("tests"),
                    "affected_files": artifact_info.get("affected_files") or [],
                    "patch_artifact": artifact_info.get("patch_path"),
                    "patch_bytes": artifact_info.get("patch_bytes") or 0,
                    "patch_valid": patch_valid,
                    "patch_validation_error": patch_validation_error,
                    "autonomy_mode": "propose_diff_only",
                    "repo_root": str(repo_root),
                    "error": agent_result.error,
                    "duration_seconds": agent_result.duration_seconds,
                    "runtime": runtime_name,
                    "session_id": agent_result.session_id,
                    "total_cost_usd": agent_result.total_cost_usd,
                    "tool_calls": [
                        {
                            "name": call.name,
                            "timestamp": call.timestamp.isoformat(),
                            "duration_ms": call.duration_ms,
                            "success": call.success,
                            "error": call.error,
                            "input": call.input,
                        }
                        for call in agent_result.tool_calls
                    ],
                    "messages_received": agent_result.messages_received,
                    "text_blocks_received": agent_result.text_blocks_received,
                    "timed_out": agent_result.timed_out,
                }
                if not patch_valid:
                    result["partial_results"] = True
                if not agent_result.success:
                    raise RuntimeError(agent_result.error or "Coding agent failed")
                _update_agent_run_progress(
                    run_id,
                    {
                        "phase": "completed" if patch_valid else AGENT_PARTIAL_STATUS,
                        "status": "completed" if patch_valid else AGENT_PARTIAL_STATUS,
                        "message": "Coding agent proposed a patch" if patch_valid else "Coding agent completed without a valid patch",
                        "runtime": runtime_name,
                        "tool_calls": len(agent_result.tool_calls),
                        "interactions": len(agent_result.tool_calls),
                        "affected_files": artifact_info.get("affected_files") or [],
                        "patch_artifact": artifact_info.get("patch_path"),
                        "patch_valid": patch_valid,
                        "autonomy_mode": "propose_diff_only",
                    },
                )
            elif agent_type == "custom":
                allowed_tools = config.get("allowed_tools") or []
                run_dir = None
                has_browser_tools = _custom_agent_uses_browser_tools(allowed_tools)
                has_screenshot_tool = any(str(tool).endswith("__browser_take_screenshot") for tool in allowed_tools)
                force_direct_execution = bool(config.get("_force_direct_agent_execution"))
                runtime = browser_runtime_status() if has_browser_tools else {}
                with Session(engine) as session:
                    custom_run = session.get(AgentRun, run_id)
                    custom_project_id = custom_run.project_id if custom_run else None
                if any(str(tool).startswith("mcp__") for tool in allowed_tools):
                    if has_browser_tools:
                        await _ensure_custom_agent_browser_available(
                            run_id,
                            force_direct_execution=force_direct_execution,
                        )
                    candidate_run_dir = RUNS_DIR / run_id
                    storage_state_path = _resolve_agent_browser_auth_storage_path(
                        run_id=run_id,
                        project_id=custom_project_id or config.get("project_id"),
                        config=config,
                        run_dir=candidate_run_dir,
                    )
                    run_dir = _prepare_custom_agent_mcp_config(run_id, storage_state_path=storage_state_path)
                    runtime = browser_runtime_status()

                _update_agent_run_progress(
                    run_id,
                    {
                        "phase": "starting",
                        "message": "Starting custom agent",
                        "tool_calls": 0,
                        "browser_tool_calls": 0,
                            "interactions": 0,
                            "has_browser_tools": has_browser_tools,
                            "force_direct_execution": force_direct_execution,
                            **runtime,
                        },
                    )

                task_prompt = config.get("prompt", "")
                target_url = config.get("url")
                custom_config = config.get("custom_config") or {}
                prompt_parts = [
                    config.get("system_prompt") or "You are a focused QA automation agent.",
                    "",
                    "Run this task using only the tools you have been granted.",
                    CUSTOM_AGENT_REPORT_INSTRUCTIONS,
                ]
                if has_screenshot_tool:
                    prompt_parts.append(
                        "While working in the browser, periodically call browser_take_screenshot with filenames "
                        "like live-step-001.png, live-step-002.png, etc. so the UI can show your current state."
                    )
                if target_url:
                    if has_browser_tools:
                        prompt_parts.append(
                            f"Start by calling browser_navigate for this target URL before inspecting the page: {target_url}"
                        )
                    prompt_parts.append(f"Target URL: {target_url}")
                if custom_config:
                    prompt_parts.append(f"Additional config JSON:\n{json.dumps(custom_config, indent=2)}")
                retry_context = config.get("retry_context") if isinstance(config.get("retry_context"), dict) else {}
                if retry_context:
                    context_lines = [
                        "Retry continuation context:",
                        f"- This is retry attempt {retry_context.get('attempt')} for the same AgentRun id `{run_id}`.",
                        "- Resume from the saved browser auth/session artifacts and prior findings; do not restart discovery unless the saved page is unavailable.",
                    ]
                    if retry_context.get("last_observed_url"):
                        context_lines.append(f"- Last observed browser URL: {retry_context['last_observed_url']}")
                    if retry_context.get("raw_output_chars"):
                        context_lines.append(f"- Previous raw output artifact contains {retry_context['raw_output_chars']} characters.")
                    if retry_context.get("artifact_count"):
                        context_lines.append(
                            f"- Preserved artifacts: {retry_context['artifact_count']} total, "
                            f"{retry_context.get('screenshot_count', 0)} screenshots."
                        )
                    if retry_context.get("storage_state_reused"):
                        context_lines.append("- Browser auth storage state is available in the run directory.")
                    prompt_parts.append("\n".join(context_lines))
                test_data_refs = config.get("test_data_refs") if isinstance(config.get("test_data_refs"), list) else []
                resolved_test_data = _resolve_agent_execution_test_data_context(
                    project_id=custom_project_id or config.get("project_id"),
                    refs=test_data_refs,
                    markdown="\n".join(str(part) for part in [task_prompt, json.dumps(custom_config, default=str)]),
                )
                markdown = resolved_test_data.get("prompt_markdown")
                if markdown:
                    prompt_parts.extend(["", markdown])
                    prompt_parts.append(
                        "If you delegate work to subagents, copy the relevant test-data ref names and plaintext values needed for execution into each delegated prompt. Subagents do not automatically inherit this full parent context."
                    )
                prompt_parts.extend(["", "Task:", task_prompt])
                final_prompt = "\n".join(prompt_parts)
                trace_snapshot = ensure_trace_snapshot(
                    run_id=run_id,
                    prompt=final_prompt,
                    context=markdown,
                    runtime=runtime_name,
                    model=config.get("model"),
                    model_tier=config.get("model_tier") or "tool_deep",
                    allowed_tools=allowed_tools,
                    test_data_refs=test_data_refs,
                    runtime_diagnostics={
                        "runtime": runtime_name,
                        "agent_type": "custom",
                        "has_browser_tools": has_browser_tools,
                        "force_direct_execution": force_direct_execution,
                    },
                )

                def _on_custom_task_enqueued(task_id: str) -> None:
                    ensure_trace_snapshot(run_id=run_id, agent_task_id=task_id, runtime=runtime_name)
                    queued_message = "Agent task queued for worker"
                    runtime_metadata = runtime if has_browser_tools else {}
                    runtime_message = runtime_metadata.get(
                        "runtime_message",
                        "Browser execution is running in an agent worker. Screenshots are shown as fallback.",
                    )
                    _update_agent_run_progress(
                        run_id,
                        {
                            **runtime_metadata,
                            "phase": "queued",
                            "runtime": runtime_name,
                            "message": queued_message,
                            "agent_task_id": task_id,
                            "runtime_message": runtime_message,
                        },
                    )

                def _on_custom_tool_use(tool_name: str, tool_input: dict[str, Any]) -> None:
                    _update_agent_run_progress(
                        run_id,
                        {
                            "phase": "tool_use",
                            "message": f"Using {_short_tool_name(tool_name)}",
                            "runtime": runtime_name,
                            "last_tool": tool_name,
                            "last_tool_input": tool_input,
                            "has_browser_tools": has_browser_tools,
                            **runtime,
                        },
                    )
                    _record_agent_run_event(
                        run_id,
                        event_type="browser_action" if str(tool_name).startswith("mcp__playwright") else "tool_call",
                        message=f"Using {_short_tool_name(tool_name)}.",
                        payload={
                            "tool_name": tool_name,
                            "tool_label": _short_tool_name(tool_name),
                            "tool_input": tool_input,
                        },
                    )

                def _on_custom_progress(progress: dict[str, Any]) -> None:
                    last_tool = progress.get("last_tool")
                    record_trace_span(
                        run_id=run_id,
                        trace_id=trace_snapshot.id if trace_snapshot else None,
                        span_type="provider_event",
                        name=str(progress.get("phase") or "runtime progress"),
                        message=str(progress.get("message") or "Agent runtime progress."),
                        tool_name=str(last_tool) if last_tool else None,
                        payload={"progress": progress, "runtime": runtime_name},
                    )
                    _update_agent_run_progress(
                        run_id,
                        {
                            **progress,
                            "runtime": runtime_name,
                            "phase": progress.get("phase") or "running",
                            "message": f"Using {_short_tool_name(str(last_tool))}" if last_tool else "Agent is running",
                            "has_browser_tools": has_browser_tools,
                            **runtime,
                        },
                    )

                runtime_adapter = get_agent_runtime(runtime_name)
                runtime_context = AgentRuntimeContext(
                    timeout_seconds=int(config.get("timeout_seconds") or 1800),
                    allowed_tools=allowed_tools,
                    tools=allowed_tools,
                    session_dir=run_dir,
                    on_task_enqueued=_on_custom_task_enqueued,
                    on_tool_use=_on_custom_tool_use,
                    on_progress=_on_custom_progress,
                    cwd=run_dir,
                    owner_type="agent_run",
                    owner_id=run_id,
                    owner_label=f"Agent run {run_id}",
                    memory_project_id=custom_project_id,
                    memory_agent_type="CustomAgent",
                    memory_source_type="custom_agent_run",
                    memory_source_id=run_id,
                    memory_stage="custom_agent",
                    inject_memory=True,
                    capture_memory=False,
                    force_direct_execution=force_direct_execution,
                    model=config.get("model"),
                    model_tier=config.get("model_tier") or "tool_deep",
                    agent_name=config.get("agent_name") or "CustomAgent",
                    metadata={
                        "agent_type": "custom",
                        "agent_definition_id": config.get("agent_definition_id"),
                        "run_id": run_id,
                    },
                    trace_id=trace_snapshot.id if trace_snapshot else None,
                    prompt_hash=trace_snapshot.prompt_hash if trace_snapshot else None,
                    agent_run_id=run_id,
                    env_vars=None,
                    is_cancelled=_agent_run_cancelled,
                )
                if not await _wait_if_agent_run_paused(run_id):
                    return
                agent_result = await runtime_adapter.run(final_prompt, runtime_context)
                if agent_result.cancelled:
                    raise asyncio.CancelledError("Agent run cancelled")
                record_tool_result_spans(run_id, agent_result.tool_calls)
                artifacts = _collect_agent_run_artifacts(run_id)
                structured_report = _build_custom_agent_structured_report(
                    agent_result.output or "",
                    config,
                    artifacts,
                )
                captured_memory_ids = _capture_custom_agent_report_memory(
                    run_id=run_id,
                    project_id=custom_project_id,
                    structured_report=structured_report,
                    config=config,
                )
                result = {
                    "summary": structured_report.get("summary")
                    or (agent_result.output[:500] if agent_result.output else agent_result.error),
                    "output": agent_result.output,
                    "structured_report": structured_report,
                    "captured_memory_ids": captured_memory_ids,
                    "error": agent_result.error,
                    "duration_seconds": agent_result.duration_seconds,
                    "runtime": runtime_name,
                    "session_id": agent_result.session_id,
                    "total_cost_usd": agent_result.total_cost_usd,
                    "tool_calls": [
                        {
                            "name": call.name,
                            "timestamp": call.timestamp.isoformat(),
                            "duration_ms": call.duration_ms,
                            "success": call.success,
                            "error": call.error,
                            "input": call.input,
                        }
                        for call in agent_result.tool_calls
                    ],
                    "messages_received": agent_result.messages_received,
                    "text_blocks_received": agent_result.text_blocks_received,
                    "timed_out": agent_result.timed_out,
                }
                if not agent_result.success:
                    raise RuntimeError(agent_result.error or "Custom agent failed")
                _update_agent_run_progress(
                    run_id,
                    {
                        "phase": "completed",
                        "status": "completed",
                        "message": "Custom agent completed",
                        "runtime": runtime_name,
                        "tool_calls": len(agent_result.tool_calls),
                        "browser_tool_calls": len(
                            [call for call in agent_result.tool_calls if call.name.startswith("mcp__playwright")]
                        ),
                        "interactions": len(agent_result.tool_calls),
                    },
                )

            # Update DB success
            with Session(engine) as session:
                run = session.get(AgentRun, run_id)
                if run and run.status not in AGENT_TERMINAL_STATUSES:
                    finalized = None
                    if agent_type in {"custom", "exploratory"} and isinstance(result, dict):
                        try:
                            finalized = AgentRunFinalizer().finalize(
                                run_id=run_id,
                                agent_type=agent_type,
                                config=config,
                                raw_model_output=result.get("output") or result.get("raw_output_preview"),
                                tool_calls=result.get("tool_calls") if isinstance(result.get("tool_calls"), list) else [],
                                runtime_diagnostics={
                                    "runtime": runtime_name,
                                    "source": "execute_agent_background",
                                },
                                artifacts=_collect_agent_run_artifacts(run_id)
                                if agent_type in {"custom", "exploratory"}
                                else [],
                                existing_result=result,
                            )
                            result = finalized.result
                        except Exception as finalizer_error:
                            logger.warning("Agent result finalizer failed for %s: %s", run_id, finalizer_error)

                    exploratory_failed = (
                        finalized.status == "failed"
                        if finalized is not None
                        else agent_type == "exploratory" and _exploratory_result_is_terminal_failure(result)
                    )
                    failure_reason = result.get("failure_reason") if isinstance(result, dict) else None
                    partial_result = (
                        finalized.status == AGENT_PARTIAL_STATUS
                        if finalized is not None
                        else isinstance(result, dict) and bool(result.get("partial_results"))
                    )
                    run.status = (
                        finalized.status
                        if finalized is not None
                        else "failed" if exploratory_failed else AGENT_PARTIAL_STATUS if partial_result else "completed"
                    )
                    run.completed_at = datetime.utcnow()
                    run.result = result
                    if exploratory_failed:
                        run.progress = {
                            **(run.progress or {}),
                            "phase": "failed",
                            "status": "failed",
                            "message": result.get(
                                "summary",
                                "Exploration completed but result parsing failed and no structured data recovered.",
                            ),
                            "updated_at": datetime.utcnow().isoformat(),
                        }
                    session.add(run)
                    session.commit()
                    _record_agent_run_event(
                        run_id,
                        event_type="error" if exploratory_failed else "complete",
                        level="error" if exploratory_failed else "info",
                        message=(
                            result.get("summary")
                            if exploratory_failed and failure_reason == "runtime_auth_failed"
                            else "Exploratory agent run failed: result parsing failed and no structured data recovered."
                            if exploratory_failed
                            else "Agent run completed."
                        ),
                        payload={
                            "status": run.status,
                            "summary": _agent_run_summary(run),
                            "failure_reason": failure_reason,
                        },
                        agent_task_id=run.agent_task_id,
                        session=session,
                    )

    except asyncio.CancelledError:
        logger.info(f"Agent {run_id} cancelled")
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            if run:
                run.status = "cancelled"
                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()
                _record_agent_run_event(
                    run_id,
                    event_type="cancel",
                    message="Agent run cancelled.",
                    payload={"status": run.status},
                    agent_task_id=run.agent_task_id,
                    session=session,
                )
        raise

    except Exception as e:
        import traceback

        traceback.print_exc()
        logger.error(f"Agent {run_id} failed with exception: {e}")
        retry_via_temporal = os.environ.get("QUORVEX_AGENT_TEMPORAL_ACTIVITY") == "true"
        should_reraise = retry_via_temporal
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            if run and run.status not in AGENT_TERMINAL_STATUSES:
                recovered = None
                if agent_type == "custom":
                    recovered = _recover_custom_agent_partial_result(run, e)
                elif agent_type == "exploratory":
                    if _exploratory_result_has_usable_evidence(run.result):
                        recovered = _merge_agent_failure_into_result(
                            run.result,
                            e,
                            failure_reason="runtime_failed_after_evidence",
                        )
                    else:
                        recovered = _recover_exploratory_partial_result(run_id, config, e)

                if recovered is not None:
                    should_reraise = False
                    run.status = AGENT_PARTIAL_STATUS
                    run.completed_at = datetime.utcnow()
                    run.result = recovered
                    run.progress = {
                        **(run.progress or {}),
                        "phase": AGENT_PARTIAL_STATUS,
                        "status": AGENT_PARTIAL_STATUS,
                        "message": recovered.get("summary")
                        or (
                            "Recovered partial custom agent evidence after runtime failure."
                            if agent_type == "custom"
                            else "Recovered partial Explorer evidence after runtime failure."
                        ),
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    event_type = "partial"
                    event_level = "warning"
                    event_message = "Exploratory agent recovered partial evidence after runtime failure."
                    if agent_type == "custom":
                        event_message = "Custom agent recovered partial evidence after runtime failure."
                    event_payload = {
                        "status": run.status,
                        "error": str(e),
                        "summary": _agent_run_summary(run),
                        "failure_reason": recovered.get("failure_reason"),
                        "artifact_recovery": _run_artifact_counts(run_id),
                    }
                elif should_reraise:
                    run.progress = {
                        **(run.progress or {}),
                        "phase": "retrying",
                        "status": run.status,
                        "message": f"Agent execution failed and will be retried by Temporal: {e}",
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    event_type = "retry"
                    event_level = "warning"
                    event_message = f"Agent run failed; Temporal will retry if attempts remain: {e}"
                    event_payload = {"status": run.status, "error": str(e), "retryable": True}
                else:
                    run.status = "failed"
                    run.completed_at = datetime.utcnow()
                    existing_result = run.result if isinstance(run.result, dict) else {}
                    run.result = {**existing_result, "error": str(e)}
                    run.progress = {
                        **(run.progress or {}),
                        "phase": "failed",
                        "status": "failed",
                        "message": str(e),
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    event_type = "error"
                    event_level = "error"
                    event_message = f"Agent run failed: {e}"
                    event_payload = {"status": run.status, "error": str(e)}
                session.add(run)
                session.commit()
                _record_agent_run_event(
                    run_id,
                    event_type=event_type,
                    level=event_level,
                    message=event_message,
                    payload=event_payload,
                    agent_task_id=run.agent_task_id,
                    session=session,
                )
        if should_reraise:
            raise
