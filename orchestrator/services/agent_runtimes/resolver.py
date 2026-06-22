"""Runtime resolver for Quorvex agent execution."""

from __future__ import annotations

from .base import AgentRuntime, normalize_agent_runtime
from .claude import ClaudeAgentSdkRuntime


def get_agent_runtime(runtime: str | None = None) -> AgentRuntime:
    normalized = normalize_agent_runtime(runtime)
    if normalized == "claude_sdk":
        return ClaudeAgentSdkRuntime()
    raise ValueError(f"Unsupported agent runtime {normalized!r}.")
