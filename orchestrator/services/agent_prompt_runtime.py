"""Shared AgentRunner construction for prompt-native AI workflows."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from orchestrator.utils.agent_runner import AgentRunner


def optional_env_float(name: str) -> float | None:
    value = os.environ.get(name)
    if not value:
        return None
    return float(value)


def build_autopilot_retry_kwargs(
    source: Any,
    *,
    owner_type: str | None,
    owner_id: str | None,
    default_agent_kind: str,
    enable_for_autopilot_owner: bool = True,
) -> dict[str, Any]:
    retry_enabled = bool(getattr(source, "autopilot_retry_enabled", False))
    if enable_for_autopilot_owner and owner_type == "autopilot":
        retry_enabled = True

    session_id = getattr(source, "autopilot_session_id", None)
    if session_id is None and enable_for_autopilot_owner:
        session_id = owner_id

    return {
        "autopilot_retry_enabled": retry_enabled,
        "autopilot_session_id": session_id,
        "autopilot_stable_key": getattr(source, "autopilot_stable_key", None),
        "autopilot_agent_kind": getattr(source, "autopilot_agent_kind", default_agent_kind),
        "autopilot_source_type": getattr(source, "autopilot_source_type", None),
        "autopilot_source_id": getattr(source, "autopilot_source_id", None),
        "autopilot_checklist_title": getattr(source, "autopilot_checklist_title", None),
        "autopilot_phase_name": getattr(source, "autopilot_phase_name", None),
        "autopilot_checklist_kind": getattr(source, "autopilot_checklist_kind", None),
    }


def create_agent_runner(
    source: Any,
    *,
    timeout_seconds: int,
    tool_config: Mapping[str, Any] | None = None,
    allowed_tools: list[str] | None = None,
    tools: list[str] | dict[str, str] | None = None,
    disallowed_tools: list[str] | None = None,
    log_tools: bool,
    memory_agent_type: str,
    memory_source_type: str,
    memory_stage: str,
    inject_memory: bool = False,
    capture_memory: bool | None = None,
    requires_live_browser: bool = False,
    preserve_browser_on_failure: bool = False,
    force_direct_execution: bool = False,
    resume_session_id: str | None = None,
    continue_conversation: bool = False,
    max_budget_env: str | None = None,
    autopilot_agent_kind: str,
    enable_autopilot_for_owner: bool = True,
    include_tool_use_callback: bool = True,
    runner_cls: type[AgentRunner] | None = None,
    session_dir: Any = None,
    tool_permission_guard: Callable[[str, dict[str, Any], Any], Any] | None = None,
) -> AgentRunner:
    owner_type = getattr(source, "owner_type", None)
    owner_id = getattr(source, "owner_id", None)
    runner_kwargs: dict[str, Any] = {
        "timeout_seconds": timeout_seconds,
        "allowed_tools": allowed_tools if allowed_tools is not None else (tool_config or {}).get("allowed_tools"),
        "tools": tools if tools is not None else (tool_config or {}).get("tools"),
        "disallowed_tools": disallowed_tools if disallowed_tools is not None else (tool_config or {}).get("disallowed_tools"),
        "log_tools": log_tools,
        "on_tool_use": getattr(source, "on_tool_use", None) if include_tool_use_callback else None,
        "on_progress": getattr(source, "on_progress", None),
        "on_task_enqueued": getattr(source, "on_task_enqueued", None),
        "session_dir": session_dir,
        "cwd": getattr(source, "cwd", None),
        "owner_type": owner_type,
        "owner_id": owner_id,
        "owner_label": getattr(source, "owner_label", None),
        "requires_live_browser": requires_live_browser,
        "model_tier": getattr(source, "model_tier", None),
        "memory_agent_type": memory_agent_type,
        "memory_source_type": memory_source_type,
        "memory_stage": memory_stage,
        "inject_memory": inject_memory,
        "env_vars": getattr(source, "env_vars", None),
        "resume_session_id": resume_session_id,
        "continue_conversation": continue_conversation,
        "force_direct_execution": force_direct_execution,
        "preserve_browser_on_failure": preserve_browser_on_failure,
        **build_autopilot_retry_kwargs(
            source,
            owner_type=owner_type,
            owner_id=owner_id,
            default_agent_kind=autopilot_agent_kind,
            enable_for_autopilot_owner=enable_autopilot_for_owner,
        ),
    }
    if capture_memory is not None:
        runner_kwargs["capture_memory"] = capture_memory
    if max_budget_env:
        runner_kwargs["max_budget_usd"] = optional_env_float(max_budget_env)
    if tool_permission_guard is not None:
        runner_kwargs["tool_permission_guard"] = tool_permission_guard

    return (runner_cls or AgentRunner)(**runner_kwargs)
