"""Shared types for agent runtime adapters."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from orchestrator.utils.agent_runner import AgentResult

AgentRuntimeName = Literal["claude_sdk", "hermes"]
SUPPORTED_AGENT_RUNTIMES = {"claude_sdk", "hermes"}


def normalize_agent_runtime(value: str | None, *, default: str | None = None) -> AgentRuntimeName:
    """Normalize user/env runtime names to the internal runtime identifiers."""

    raw = (value or default or os.environ.get("QUORVEX_AGENT_RUNTIME") or "claude_sdk").strip().lower()
    aliases = {
        "claude": "claude_sdk",
        "claude-agent-sdk": "claude_sdk",
        "claude_agent_sdk": "claude_sdk",
        "hermes-agent": "hermes",
        "hermes_agent": "hermes",
    }
    normalized = aliases.get(raw, raw)
    if normalized not in SUPPORTED_AGENT_RUNTIMES:
        return "claude_sdk"
    return normalized  # type: ignore[return-value]


@dataclass
class AgentRuntimeContext:
    """Execution context passed to runtime adapters."""

    timeout_seconds: int = 1800
    allowed_tools: list[str] | None = None
    tools: list[str] | dict[str, str] | None = None
    disallowed_tools: list[str] | None = None
    permission_mode: str | None = None
    strict_mcp_config: bool = True
    max_budget_usd: float | None = None
    task_budget: dict[str, int] | None = None
    include_hook_events: bool = False
    include_partial_messages: bool = False
    output_format: dict[str, Any] | None = None
    resume_session_id: str | None = None
    continue_conversation: bool = False
    max_turns: int | None = None
    session_dir: Path | None = None
    cwd: Path | str | None = None
    owner_type: str | None = None
    owner_id: str | None = None
    owner_label: str | None = None
    memory_project_id: str | None = None
    memory_agent_type: str | None = None
    memory_source_type: str | None = None
    memory_source_id: str | None = None
    memory_stage: str | None = None
    inject_memory: bool = True
    capture_memory: bool = True
    force_direct_execution: bool = False
    model: str | None = None
    fallback_model: str | None = None
    model_tier: str | None = None
    reasoning_budget: int | None = None
    max_buffer_size: int | None = None
    betas: list[str] | None = None
    user: str | None = None
    permission_prompt_tool_name: str | None = None
    enable_file_checkpointing: bool = False
    sandbox: dict[str, Any] | None = None
    env_vars: dict[str, str] | None = None
    agent_name: str | None = None
    hermes_profile: str | None = None
    hermes_conversation: str | None = None
    metadata: dict[str, Any] | None = None
    trace_id: str | None = None
    prompt_hash: str | None = None
    agent_run_id: str | None = None
    on_task_enqueued: Callable[[str], None] | None = None
    on_tool_use: Callable[[str, dict[str, Any]], None] | None = None
    tool_permission_guard: Callable[[str, dict[str, Any], Any], Any] | None = None
    on_progress: Callable[[dict[str, Any]], None] | None = None
    is_cancelled: Callable[[], Any] | None = None


class AgentRuntime:
    """Runtime adapter protocol implemented as a base class for simple typing."""

    name: AgentRuntimeName

    async def run(self, prompt: str, context: AgentRuntimeContext) -> AgentResult:
        raise NotImplementedError
