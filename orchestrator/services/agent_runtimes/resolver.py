"""Runtime resolver for Quorvex agent execution."""

from __future__ import annotations

from .base import AgentRuntime, AgentRuntimeName, normalize_agent_runtime
from .claude import ClaudeAgentSdkRuntime
from .hermes import HermesRuntime


def get_agent_runtime(runtime: str | None = None) -> AgentRuntime:
    name: AgentRuntimeName = normalize_agent_runtime(runtime)
    if name == "hermes":
        return HermesRuntime()
    return ClaudeAgentSdkRuntime()
