"""Direct and queued execution helpers for autonomous work items."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from sqlmodel import Session, select

from orchestrator.api.models_db import AutonomousAgentWorkItem, AutonomousMission
from orchestrator.services import autonomous_activities as facade
from orchestrator.services.autonomous_events import create_autonomous_agent_event, emit_work_item_status_event


def _enqueue_agent_work_item(
    session: Session,
    mission: AutonomousMission,
    item: AutonomousAgentWorkItem,
) -> bool:
    return facade._execute_agent_work_item_direct(session, mission, item)


def _execute_agent_work_item_direct(
    session: Session,
    mission: AutonomousMission,
    item: AutonomousAgentWorkItem,
) -> bool:
    """Execute one autonomous work item inside the Temporal activity worker."""
    now = facade._utcnow()
    current_item = session.get(AutonomousAgentWorkItem, item.id)
    current_mission = session.get(AutonomousMission, mission.id)
    if (
        not current_item
        or current_item.status == "cancelled"
        or (current_mission and current_mission.status == "cancelled")
    ):
        return False
    timeout_seconds = max(300, min(mission.max_runtime_minutes * 60, 7200))
    run_dir, browser_runtime = facade._prepare_autonomous_work_item_runtime(mission, item)
    allowed_tools = facade._allowed_tools_for_work_item(item, mcp_config_dir=run_dir)
    has_browser_tools = any(facade._is_browser_tool(tool) for tool in allowed_tools)
    browser_handoff: dict[str, Any] | None = None
    child_browser_handoffs: list[dict[str, Any]] = []
    browser_handoff_mode = str((mission.config or {}).get("browser_handoff_mode") or "isolated")
    if has_browser_tools:
        facade._validate_browser_handoff_mode(item, mode=browser_handoff_mode)
        facade._assert_browser_lease_available(
            session,
            mission_id=mission.id,
            requested_owner_id=item.id,
            mode=browser_handoff_mode,
        )
        browser_handoff = facade._browser_context_handoff(
            mission=mission,
            item=item,
            run_dir=run_dir,
            runtime=browser_runtime,
            allowed_tools=allowed_tools,
            mode=browser_handoff_mode,
            storage_state_path=browser_runtime.get("storage_state_path"),
            auth_session_id=browser_runtime.get("auth_session_id"),
            auth_session_name=browser_runtime.get("auth_session_name"),
        )
    item.agent_task_id = None
    item.status = "running"
    item.attempt_count += 1
    item.started_at = item.started_at or now
    item.lease_until = now + timedelta(seconds=timeout_seconds)
    item.last_heartbeat_at = now
    item.updated_at = now
    item.progress = {
        **item.progress,
        "phase": "running",
        "message": "Agent work item is running in a Temporal activity.",
        "runtime": str((mission.config or {}).get("runtime") or "claude_sdk"),
        "has_browser_tools": has_browser_tools,
        "browser_context_handoff": browser_handoff,
        "browser_child_handoffs": child_browser_handoffs,
        **browser_runtime,
    }
    session.add(item)
    session.commit()
    emit_work_item_status_event(
        item,
        "Agent work item started in Temporal activity.",
        event_type="lifecycle",
    )

    try:
        from orchestrator.services.agent_runtimes import AgentRuntimeContext, get_agent_runtime, normalize_agent_runtime

        runtime_name = normalize_agent_runtime((mission.config or {}).get("runtime"))
        last_progress_signature: tuple[str, str, str] | None = None
        last_assistant_message: str | None = None

        def _emit_event(
            event_type: str, message: str, *, level: str = "info", payload: dict[str, Any] | None = None
        ) -> None:
            try:
                create_autonomous_agent_event(
                    project_id=item.project_id,
                    mission_id=item.mission_id,
                    run_id=item.run_id,
                    work_item_id=item.id,
                    agent_task_id=item.agent_task_id,
                    event_type=event_type,
                    level=level,
                    message=message,
                    payload=payload,
                )
            except Exception:
                facade.logger.debug("Failed to persist autonomous work item event", exc_info=True)

        def _on_tool_use(tool_name: str, tool_input: dict[str, Any]) -> None:
            short_name = facade._short_tool_name(tool_name)
            payload = {
                "status": "started",
                "tool_name": tool_name,
                "short_name": short_name,
                "tool_input": tool_input,
                "runtime": runtime_name,
            }
            _emit_event("tool_call", f"Tool started: {short_name}", payload=payload)
            if facade._is_browser_tool(tool_name):
                _emit_event("browser_action", f"Browser action: {short_name}", payload=payload)

        def _on_progress(progress: dict[str, Any]) -> None:
            nonlocal last_progress_signature, last_assistant_message
            try:
                current = session.get(AutonomousAgentWorkItem, item.id)
                if not current or current.status != "running":
                    return
                heartbeat_at = facade._utcnow()
                last_tool = progress.get("last_tool")
                progress_payload = {
                    **progress,
                    "runtime": runtime_name,
                    "has_browser_tools": has_browser_tools,
                    "browser_context_handoff": browser_handoff,
                    "browser_child_handoffs": child_browser_handoffs,
                    **browser_runtime,
                }
                current.progress = {
                    **(current.progress or {}),
                    **{key: value for key, value in progress_payload.items() if value is not None},
                    "runtime": runtime_name,
                    "phase": progress.get("phase") or "running",
                    "message": progress.get("message") or "Agent is running.",
                    "last_event_at": heartbeat_at.isoformat(),
                }
                current.last_heartbeat_at = heartbeat_at
                current.lease_until = heartbeat_at + timedelta(seconds=timeout_seconds)
                current.updated_at = heartbeat_at
                session.add(current)
                session.commit()
                phase = str(progress.get("phase") or "running")
                message = str(progress.get("message") or "Agent is running.")
                signature = (phase, message, str(last_tool or ""))
                if signature != last_progress_signature:
                    last_progress_signature = signature
                    _emit_event(
                        "progress",
                        message,
                        payload={
                            **progress_payload,
                            "phase": phase,
                            "status": current.status,
                            "work_item_progress": current.progress,
                        },
                    )
                if phase == "tool_result" and last_tool:
                    short_name = facade._short_tool_name(str(last_tool))
                    payload = {
                        **progress_payload,
                        "status": "completed",
                        "tool_name": str(last_tool),
                        "short_name": short_name,
                    }
                    _emit_event("tool_call", f"Tool completed: {short_name}", payload=payload)
                    if facade._is_browser_tool(str(last_tool)):
                        _emit_event("browser_action", f"Browser action completed: {short_name}", payload=payload)
                elif (
                    message
                    and message != last_assistant_message
                    and phase not in {"tool_use", "tool_result"}
                    and message not in {"Agent is running.", "Agent work item is running in a Temporal activity."}
                ):
                    last_assistant_message = message
                    _emit_event(
                        "assistant_output",
                        message,
                        payload={"preview": message, "phase": phase, "runtime": runtime_name},
                    )
            except Exception:
                facade.logger.debug("Failed to persist autonomous work item progress", exc_info=True)

        def _on_task_enqueued(task_id: str) -> None:
            try:
                current = session.get(AutonomousAgentWorkItem, item.id)
                if not current:
                    return
                current.agent_task_id = task_id
                current.progress = {
                    **(current.progress or {}),
                    "runtime": runtime_name,
                    "agent_task_id": task_id,
                    "phase": "running",
                    "message": "Agent task started.",
                    "has_browser_tools": has_browser_tools,
                    "browser_context_handoff": browser_handoff,
                    "browser_child_handoffs": child_browser_handoffs,
                    **browser_runtime,
                }
                current.updated_at = facade._utcnow()
                session.add(current)
                session.commit()
                _emit_event(
                    "lifecycle",
                    current.progress["message"],
                    payload={"agent_task_id": task_id, "runtime": runtime_name, **browser_runtime},
                )
            except Exception:
                facade.logger.debug("Failed to persist autonomous task id", exc_info=True)

        def _is_cancelled() -> bool:
            with Session(facade.engine) as check_session:
                current = check_session.get(AutonomousAgentWorkItem, item.id)
                current_mission = check_session.get(AutonomousMission, mission.id)
                return (
                    not current
                    or current.status == "cancelled"
                    or bool(current_mission and current_mission.status == "cancelled")
                )

        test_data_context = facade._autonomous_test_data_execution_context(mission)
        test_data_env_vars = {}
        native_output_format_supported = False
        if runtime_name == "claude_sdk":
            try:
                from orchestrator.utils.agent_runner import AgentRunner

                native_output_format_supported = AgentRunner._claude_options_accepts("output_format")
            except Exception:
                native_output_format_supported = False

        async def _run_agent():
            runtime = get_agent_runtime(runtime_name)
            structured_output_format = (
                facade.structured_agent_contract_output_format() if runtime_name == "claude_sdk" else None
            )
            configured_max_turns = facade._config_int(mission.config, "structured_guardrail_max_turns", 0)
            return await runtime.run(
                facade._agent_prompt_for_work_item(
                    mission,
                    item,
                    test_data_context,
                    browser_handoff=browser_handoff,
                    child_browser_handoffs=child_browser_handoffs,
                ),
                AgentRuntimeContext(
                    timeout_seconds=timeout_seconds,
                    allowed_tools=allowed_tools,
                    tools=list(allowed_tools),
                    max_budget_usd=mission.max_llm_budget_usd,
                    output_format=structured_output_format,
                    max_turns=configured_max_turns if configured_max_turns > 0 else None,
                    on_task_enqueued=_on_task_enqueued,
                    on_tool_use=_on_tool_use,
                    on_progress=_on_progress,
                    session_dir=run_dir,
                    cwd=run_dir,
                    owner_type="autonomous_work_item",
                    owner_id=item.id,
                    owner_label=f"{mission.name}: {item.role}",
                    memory_project_id=mission.project_id,
                    memory_agent_type=item.role,
                    memory_source_type="autonomous_work_item",
                    memory_source_id=item.id,
                    memory_stage="autonomous_mission",
                    model=(mission.config or {}).get("model"),
                    model_tier=(mission.config or {}).get("model_tier") or "tool_deep",
                    agent_name=item.role,
                    metadata={
                        "mission_id": mission.id,
                        "mission_run_id": item.run_id,
                        "role": item.role,
                        "planner_key": item.planner_key,
                        "browser_context_handoff": browser_handoff,
                        "browser_child_handoffs": child_browser_handoffs,
                    },
                    env_vars=test_data_env_vars or None,
                    is_cancelled=_is_cancelled,
                ),
            )

        result = asyncio.run(_run_agent())
    except Exception as exc:
        now = facade._utcnow()
        session.expire_all()
        item = session.get(AutonomousAgentWorkItem, item.id) or item
        current_mission = session.get(AutonomousMission, mission.id)
        if item.status == "cancelled" or (current_mission and current_mission.status == "cancelled"):
            item.status = "cancelled"
            item.error_message = item.error_message or "Mission cancelled"
            item.completed_at = item.completed_at or now
            item.updated_at = now
            item.last_heartbeat_at = now
            item.progress = {
                **(item.progress or {}),
                "phase": "cancelled",
                "message": item.error_message,
                "browser_context_handoff": browser_handoff,
                "browser_child_handoffs": child_browser_handoffs,
                **browser_runtime,
            }
            session.add(item)
            session.commit()
            emit_work_item_status_event(item, item.error_message, event_type="lifecycle")
            return False
        item.status = "failed"
        item.error_message = str(exc)
        item.completed_at = now
        item.updated_at = now
        item.last_heartbeat_at = now
        item.progress = {
            "phase": "failed",
            "message": item.error_message,
            "browser_context_handoff": browser_handoff,
            "browser_child_handoffs": child_browser_handoffs,
            **browser_runtime,
        }
        session.add(item)
        session.commit()
        emit_work_item_status_event(item, item.error_message, event_type="error")
        facade.logger.warning("Failed to execute autonomous work item %s: %s", item.id, exc)
        return False

    now = facade._utcnow()
    session.expire_all()
    item = session.get(AutonomousAgentWorkItem, item.id) or item
    current_mission = session.get(AutonomousMission, mission.id) or mission
    if item.status == "cancelled" or current_mission.status == "cancelled" or getattr(result, "cancelled", False):
        browser_observation_summary = (
            facade._record_browser_observations_for_work_item(
                mission=mission,
                item=item,
                result=result,
                browser_handoff=browser_handoff,
            )
            if has_browser_tools
            else {"states": 0, "transitions": 0, "app_map_states": 0}
        )
        item.status = "cancelled"
        item.error_message = item.error_message or "Agent work item cancelled"
        item.completed_at = item.completed_at or now
        item.updated_at = now
        item.last_heartbeat_at = now
        item.result = {
            **(item.result or {}),
            "output": getattr(result, "output", "") or "",
            "telemetry": {
                "runtime": str((mission.config or {}).get("runtime") or "claude_sdk"),
                "tool_calls": len(getattr(result, "tool_calls", []) or []),
                "messages_received": getattr(result, "messages_received", 0),
                "text_blocks_received": getattr(result, "text_blocks_received", 0),
                "duration_seconds": getattr(result, "duration_seconds", 0.0),
                "cancelled": True,
                "browser_observations": browser_observation_summary,
            },
        }
        item.progress = {
            **(item.progress or {}),
            "phase": "cancelled",
            "message": item.error_message,
            "browser_context_handoff": browser_handoff,
            "browser_child_handoffs": child_browser_handoffs,
            **browser_runtime,
        }
        session.add(item)
        session.commit()
        emit_work_item_status_event(item, item.error_message, event_type="lifecycle")
        return False
    browser_observation_summary = (
        facade._record_browser_observations_for_work_item(
            mission=mission,
            item=item,
            result=result,
            browser_handoff=browser_handoff,
        )
        if has_browser_tools
        else {"states": 0, "transitions": 0, "app_map_states": 0}
    )
    telemetry = {
        "runtime": str((mission.config or {}).get("runtime") or "claude_sdk"),
        "tool_calls": len(result.tool_calls),
        "messages_received": result.messages_received,
        "text_blocks_received": result.text_blocks_received,
        "duration_seconds": result.duration_seconds,
        "timed_out": result.timed_out,
        "total_cost_usd": result.total_cost_usd,
        "stop_reason": result.stop_reason,
        "session_id": result.session_id,
        "guardrail_used_native_output_format": native_output_format_supported,
        "browser_observations": browser_observation_summary,
    }
    if result.success:
        item.status = "completed"
        item.completed_at = now
        item.result = {
            "output": result.output or "",
            "telemetry": telemetry,
        }
        item.artifacts = [
            {
                "type": "agent_report",
                "label": f"{item.role} report",
                "content": result.output or "",
            }
        ]
        item.progress = {
            "phase": "completed",
            "message": "Agent completed this assignment.",
            "browser_context_handoff": browser_handoff,
            "browser_child_handoffs": child_browser_handoffs,
            **browser_runtime,
        }
        item.budget_used_usd = float(result.total_cost_usd or 0.0)
        item.updated_at = now
        item.last_heartbeat_at = now
        mission.budget_used_usd += item.budget_used_usd
        mission.updated_at = now
        session.add(item)
        session.add(mission)
        session.commit()
        if result.output:
            create_autonomous_agent_event(
                project_id=item.project_id,
                mission_id=item.mission_id,
                run_id=item.run_id,
                work_item_id=item.id,
                agent_task_id=item.agent_task_id,
                event_type="assistant_output",
                message=result.output,
                payload={"preview": result.output[:1000], "runtime": runtime_name},
            )
        emit_work_item_status_event(item, "Agent completed this assignment.", event_type="complete")
        return True

    item.status = "failed"
    item.error_message = result.error or "Agent work item failed"
    item.completed_at = now
    item.result = {"output": result.output or "", "telemetry": telemetry, "error": item.error_message}
    item.progress = {
        "phase": "failed",
        "message": item.error_message,
        "browser_context_handoff": browser_handoff,
        "browser_child_handoffs": child_browser_handoffs,
        **browser_runtime,
    }
    item.updated_at = now
    item.last_heartbeat_at = now
    item.budget_used_usd = float(result.total_cost_usd or 0.0)
    session.add(item)
    session.commit()
    if result.output:
        create_autonomous_agent_event(
            project_id=item.project_id,
            mission_id=item.mission_id,
            run_id=item.run_id,
            work_item_id=item.id,
            agent_task_id=item.agent_task_id,
            event_type="assistant_output",
            message=result.output,
            level="warning",
            payload={"preview": result.output[:1000], "runtime": telemetry["runtime"]},
        )
    emit_work_item_status_event(item, item.error_message, event_type="error")
    return False


def _enqueue_agent_work_item_legacy(
    session: Session,
    mission: AutonomousMission,
    item: AutonomousAgentWorkItem,
) -> bool:
    try:
        from orchestrator.services.agent_queue import get_agent_queue

        async def _enqueue() -> str:
            queue = get_agent_queue()
            await queue.connect()
            try:
                test_data_context = facade._autonomous_test_data_execution_context(mission)
                return await queue.enqueue_task(
                    prompt=facade._agent_prompt_for_work_item(mission, item, test_data_context),
                    timeout_seconds=max(300, min(mission.max_runtime_minutes * 60, 7200)),
                    agent_type=item.role,
                    operation_type="autonomous_mission",
                    env_vars=None,
                    allowed_tools=facade._allowed_tools_for_work_item(item),
                    max_budget_usd=mission.max_llm_budget_usd,
                    owner_type="autonomous_work_item",
                    owner_id=item.id,
                    owner_label=f"{mission.name}: {item.role}",
                )
            finally:
                await queue.disconnect()

        task_id = asyncio.run(_enqueue())
    except Exception as exc:
        now = facade._utcnow()
        item.status = "blocked"
        item.error_message = f"Unable to enqueue agent task: {exc}"
        item.completed_at = now
        item.updated_at = now
        item.progress = {"phase": "blocked", "message": item.error_message}
        session.add(item)
        session.commit()
        facade.logger.warning("Failed to enqueue autonomous work item %s: %s", item.id, exc)
        return False

    now = facade._utcnow()
    item.agent_task_id = task_id
    item.status = "running"
    item.attempt_count += 1
    item.started_at = item.started_at or now
    item.lease_until = now + timedelta(seconds=max(300, min(mission.max_runtime_minutes * 60, 7200)))
    item.last_heartbeat_at = now
    item.updated_at = now
    item.progress = {
        **item.progress,
        "phase": "queued",
        "message": "Agent task has been queued.",
        "agent_task_id": task_id,
    }
    session.add(item)
    session.commit()
    emit_work_item_status_event(item, "Agent task queued for autonomous work item.", event_type="lifecycle")
    return True


def _sync_agent_work_items(session: Session, mission: AutonomousMission) -> int:
    running_items = session.exec(
        select(AutonomousAgentWorkItem).where(
            AutonomousAgentWorkItem.mission_id == mission.id,
            AutonomousAgentWorkItem.status == "running",
            AutonomousAgentWorkItem.agent_task_id != None,  # noqa: E711
        )
    ).all()
    if not running_items:
        return 0
    try:
        from orchestrator.services.agent_queue import AgentTaskStatus, get_agent_queue

        async def _load_tasks(task_ids: list[str]):
            queue = get_agent_queue()
            await queue.connect()
            try:
                tasks = [await queue.get_task(task_id) for task_id in task_ids]
                progress = {task_id: await queue.get_task_progress(task_id) for task_id in task_ids}
                return tasks, progress
            finally:
                await queue.disconnect()

        tasks, progress_by_id = asyncio.run(
            _load_tasks([str(item.agent_task_id) for item in running_items if item.agent_task_id])
        )
        task_by_id = {task.id: task for task in tasks if task}
    except Exception as exc:
        facade.logger.debug("Unable to sync autonomous agent work items: %s", exc)
        return 0

    completed_count = 0
    now = facade._utcnow()
    for item in running_items:
        task = task_by_id.get(str(item.agent_task_id))
        if not task:
            continue
        live_progress = progress_by_id.get(str(item.agent_task_id)) or {}
        telemetry = task.telemetry or {}
        if task.status == AgentTaskStatus.PAUSED:
            item.progress = {
                **item.progress,
                "phase": "paused",
                "message": "Agent is paused.",
                **{key: value for key, value in live_progress.items() if value is not None},
                "last_event_at": now.isoformat(),
            }
            item.updated_at = now
            item.last_heartbeat_at = now
            session.add(item)
            continue
        if task.status.value == "running":
            item.progress = {
                **item.progress,
                "phase": "running",
                "message": "Agent is running.",
                "tool_calls": telemetry.get("tool_calls"),
                "last_tool": telemetry.get("last_tool"),
                **{key: value for key, value in live_progress.items() if value is not None},
                "last_event_at": now.isoformat(),
            }
            item.updated_at = now
            item.last_heartbeat_at = now
            item.lease_until = now + timedelta(minutes=30)
            session.add(item)
            continue
        if task.status == AgentTaskStatus.COMPLETED:
            item.status = "completed"
            item.completed_at = task.completed_at or now
            item.result = {
                "output": task.result or "",
                "telemetry": telemetry,
            }
            item.artifacts = [{"type": "agent_report", "label": f"{item.role} report", "content": task.result or ""}]
            item.progress = {"phase": "completed", "message": "Agent completed this assignment."}
            item.budget_used_usd = float(telemetry.get("total_cost_usd") or 0.0)
            item.updated_at = now
            item.last_heartbeat_at = now
            completed_count += 1
            session.add(item)
            emit_work_item_status_event(item, "Agent completed this assignment.", event_type="complete")
        elif task.status in {AgentTaskStatus.FAILED, AgentTaskStatus.TIMEOUT, AgentTaskStatus.CANCELLED}:
            item.status = "cancelled" if task.status == AgentTaskStatus.CANCELLED else "failed"
            item.error_message = task.error or f"Agent task {task.status.value}"
            item.completed_at = task.completed_at or now
            item.progress = {"phase": item.status, "message": item.error_message}
            item.updated_at = now
            item.last_heartbeat_at = now
            session.add(item)
            emit_work_item_status_event(item, item.error_message, event_type="error")
    if completed_count:
        mission.budget_used_usd += sum(item.budget_used_usd for item in running_items if item.status == "completed")
        mission.updated_at = now
        session.add(mission)
    session.commit()
    return completed_count
