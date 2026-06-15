"""Runtime resolver for Quorvex agent execution."""

from __future__ import annotations

from .base import AgentRuntime, normalize_agent_runtime
from .claude import ClaudeAgentSdkRuntime


def get_agent_runtime(runtime: str | None = None) -> AgentRuntime:
    normalize_agent_runtime(runtime)
    return ClaudeAgentSdkRuntime()
