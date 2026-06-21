"""Shared AgentRunner construction for prompt-native AI workflows."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from orchestrator.utils.agent_runner import AgentRunner

_UNSET = object()


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
    default_agent_kind: str | None,
    enable_for_autopilot_owner: bool = True,
    autopilot_retry_enabled: bool | None | object = _UNSET,
    autopilot_session_id: str | None | object = _UNSET,
    autopilot_stable_key: str | None | object = _UNSET,
    autopilot_agent_kind: str | None | object = _UNSET,
    autopilot_source_type: str | None | object = _UNSET,
    autopilot_source_id: str | None | object = _UNSET,
    autopilot_checklist_title: str | None | object = _UNSET,
    autopilot_phase_name: str | None | object = _UNSET,
    autopilot_checklist_kind: str | None | object = _UNSET,
) -> dict[str, Any]:
    retry_enabled = (
        bool(getattr(source, "autopilot_retry_enabled", False))
        if autopilot_retry_enabled is _UNSET
        else autopilot_retry_enabled
    )
    if (
        autopilot_retry_enabled is _UNSET
        and enable_for_autopilot_owner
        and owner_type == "autopilot"
    ):
        retry_enabled = True

    session_id = (
        getattr(source, "autopilot_session_id", None)
        if autopilot_session_id is _UNSET
        else autopilot_session_id
    )
    if (
        autopilot_session_id is _UNSET
        and session_id is None
        and enable_for_autopilot_owner
    ):
        session_id = owner_id

    return {
        "autopilot_retry_enabled": retry_enabled,
        "autopilot_session_id": session_id,
        "autopilot_stable_key": (
            getattr(source, "autopilot_stable_key", None)
            if autopilot_stable_key is _UNSET
            else autopilot_stable_key
        ),
        "autopilot_agent_kind": (
            getattr(source, "autopilot_agent_kind", default_agent_kind)
            if autopilot_agent_kind is _UNSET
            else autopilot_agent_kind
        ),
        "autopilot_source_type": (
            getattr(source, "autopilot_source_type", None)
            if autopilot_source_type is _UNSET
            else autopilot_source_type
        ),
        "autopilot_source_id": (
            getattr(source, "autopilot_source_id", None)
            if autopilot_source_id is _UNSET
            else autopilot_source_id
        ),
        "autopilot_checklist_title": (
            getattr(source, "autopilot_checklist_title", None)
            if autopilot_checklist_title is _UNSET
            else autopilot_checklist_title
        ),
        "autopilot_phase_name": (
            getattr(source, "autopilot_phase_name", None)
            if autopilot_phase_name is _UNSET
            else autopilot_phase_name
        ),
        "autopilot_checklist_kind": (
            getattr(source, "autopilot_checklist_kind", None)
            if autopilot_checklist_kind is _UNSET
            else autopilot_checklist_kind
        ),
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
    memory_agent_type: str | None,
    memory_source_type: str | None,
    memory_stage: str | None,
    inject_memory: bool = False,
    capture_memory: bool | None = None,
    requires_live_browser: bool = False,
    preserve_browser_on_failure: bool = False,
    force_direct_execution: bool = False,
    resume_session_id: str | None = None,
    continue_conversation: bool = False,
    max_budget_env: str | None = None,
    task_budget: dict[str, int] | None = None,
    autopilot_agent_kind: str | None | object = _UNSET,
    enable_autopilot_for_owner: bool = True,
    cwd: Any = None,
    owner_label: str | None = None,
    model_tier: str | None = None,
    env_vars: dict[str, str] | None = None,
    owner_type: str | None = None,
    owner_id: str | None = None,
    autopilot_retry_enabled: bool | None | object = _UNSET,
    autopilot_session_id: str | None | object = _UNSET,
    autopilot_stable_key: str | None | object = _UNSET,
    autopilot_source_type: str | None | object = _UNSET,
    autopilot_source_id: str | None | object = _UNSET,
    autopilot_checklist_title: str | None | object = _UNSET,
    autopilot_phase_name: str | None | object = _UNSET,
    autopilot_checklist_kind: str | None | object = _UNSET,
    include_tool_use_callback: bool = True,
    runner_cls: type[AgentRunner] | None = None,
    session_dir: Any = None,
    tool_permission_guard: Callable[[str, dict[str, Any], Any], Any] | None = None,
) -> AgentRunner:
    owner_type = getattr(source, "owner_type", None) if owner_type is None else owner_type
    owner_id = getattr(source, "owner_id", None) if owner_id is None else owner_id
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
        "cwd": getattr(source, "cwd", None) if cwd is None else cwd,
        "owner_type": owner_type,
        "owner_id": owner_id,
        "owner_label": getattr(source, "owner_label", None) if owner_label is None else owner_label,
        "requires_live_browser": requires_live_browser,
        "model_tier": getattr(source, "model_tier", None) if model_tier is None else model_tier,
        "task_budget": task_budget,
        "memory_agent_type": memory_agent_type,
        "memory_source_type": memory_source_type,
        "memory_stage": memory_stage,
        "inject_memory": inject_memory,
        "env_vars": getattr(source, "env_vars", None) if env_vars is None else env_vars,
        "resume_session_id": resume_session_id,
        "continue_conversation": continue_conversation,
        "force_direct_execution": force_direct_execution,
        "preserve_browser_on_failure": preserve_browser_on_failure,
        **build_autopilot_retry_kwargs(
            source,
            owner_type=owner_type,
            owner_id=owner_id,
            default_agent_kind=None if autopilot_agent_kind is _UNSET else autopilot_agent_kind,
            enable_for_autopilot_owner=enable_autopilot_for_owner,
            autopilot_retry_enabled=autopilot_retry_enabled,
            autopilot_session_id=autopilot_session_id,
            autopilot_stable_key=autopilot_stable_key,
            autopilot_agent_kind=autopilot_agent_kind,
            autopilot_source_type=autopilot_source_type,
            autopilot_source_id=autopilot_source_id,
            autopilot_checklist_title=autopilot_checklist_title,
            autopilot_phase_name=autopilot_phase_name,
            autopilot_checklist_kind=autopilot_checklist_kind,
        ),
    }
    if capture_memory is not None:
        runner_kwargs["capture_memory"] = capture_memory
    if max_budget_env:
        runner_kwargs["max_budget_usd"] = optional_env_float(max_budget_env)
    if tool_permission_guard is not None:
        runner_kwargs["tool_permission_guard"] = tool_permission_guard

    return (runner_cls or AgentRunner)(**runner_kwargs)
