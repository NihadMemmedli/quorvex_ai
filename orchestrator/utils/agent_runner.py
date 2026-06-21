"""
Unified Agent Runner - Executes Claude agents with logging, timeouts, and error handling.

This module provides a consistent interface for running Claude agents across
all workflows (exploration, planning, generation, etc.) with:
- Explicit timeout support
- Comprehensive message logging
- Tool call tracking
- Graceful SDK cleanup error handling
- Queue-based execution for uvicorn compatibility
"""

import asyncio
import hashlib
import inspect
import json
import logging
import os
import sys
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator.services.ai_runtime_config import (
    RuntimeModelTier,
    apply_runtime_env_aliases,
    resolve_runtime_ai_selection,
)
from orchestrator.utils.browser_dialog_policy import append_browser_dialog_recovery_policy
from orchestrator.utils.claude_stream import (
    ParsedToolResult,
    ParsedToolUse,
    event_text_blocks,
    event_tool_results,
    event_tool_uses,
    event_type,
    tool_result_text,
)
from orchestrator.utils.token_budget import (
    build_agent_token_telemetry,
    estimate_tokens,
    extract_provider_usage,
)

# Setup logging
logger = logging.getLogger(__name__)

# Import SDK (loaded by caller via setup_claude_env)
try:
    from claude_agent_sdk import ClaudeAgentOptions, query
except ImportError:
    logger.warning("claude_agent_sdk not available - agent_runner will fail at runtime")
    query = None
    ClaudeAgentOptions = None

# Import API key rotator for multi-key failover
try:
    from orchestrator.services.api_key_rotator import (
        get_api_key_rotator,
        is_rate_limit_error,
        is_transient_provider_error,
        parse_api_error_status,
        parse_retry_after,
        provider_retry_attempts,
        provider_retry_delay_seconds,
    )
except ImportError:
    try:
        from services.api_key_rotator import (
            get_api_key_rotator,
            is_rate_limit_error,
            is_transient_provider_error,
            parse_api_error_status,
            parse_retry_after,
            provider_retry_attempts,
            provider_retry_delay_seconds,
        )
    except ImportError:
        get_api_key_rotator = None

        def is_rate_limit_error(text):
            return False

        def is_transient_provider_error(error):
            return False

        def parse_api_error_status(error):
            return None

        def parse_retry_after(text):
            return None

        def provider_retry_attempts():
            return 1

        def provider_retry_delay_seconds(attempt):
            return 0.0


# Import agent queue for Redis-based execution
try:
    # Add parent path for imports
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from services.agent_queue import get_agent_queue, should_use_agent_queue

    AGENT_QUEUE_AVAILABLE = True
except ImportError:
    AGENT_QUEUE_AVAILABLE = False

    def should_use_agent_queue():
        return False


# Browser cleanup utilities
try:
    from orchestrator.utils.browser_cleanup import (
        kill_new_children,
        snapshot_child_pids,
    )
except ImportError:
    try:
        from utils.browser_cleanup import kill_new_children, snapshot_child_pids
    except ImportError:
        # Fallback no-ops if cleanup module unavailable
        def snapshot_child_pids() -> set:
            return set()

        def kill_new_children(before_pids: set, grace_seconds: float = 2.0) -> int:
            return 0


def _resolve_mcp_config_path(
    *,
    mcp_config_dir: Path | str | None = None,
    mcp_config_path: Path | str | None = None,
) -> Path:
    if mcp_config_path is not None:
        path = Path(mcp_config_path)
        return path / ".mcp.json" if path.is_dir() else path
    if mcp_config_dir is not None:
        return Path(mcp_config_dir) / ".mcp.json"
    return Path(".mcp.json")


def get_mcp_tool_prefix(
    server_hint: str = "playwright",
    *,
    mcp_config_dir: Path | str | None = None,
    mcp_config_path: Path | str | None = None,
) -> str:
    """Detect MCP server name from .mcp.json to build tool names.

    The MCP server name varies by context:
    - Dashboard/Docker: server named "playwright-test" -> tools prefixed mcp__playwright-test__
    - CLI direct: server named "playwright" -> tools prefixed mcp__playwright__
    - Mobile: server named "appium-mcp" -> tools prefixed mcp__appium-mcp__
    """
    import json as _json

    mcp_path = _resolve_mcp_config_path(mcp_config_dir=mcp_config_dir, mcp_config_path=mcp_config_path)
    if mcp_path.exists():
        try:
            config = _json.loads(mcp_path.read_text())
            for name in config.get("mcpServers", {}):
                if server_hint in name:
                    return f"mcp__{name}__"
        except Exception as e:
            logger.debug(f"MCP config read failed, using default prefix: {e}")
    if server_hint == "appium":
        return "mcp__appium-mcp__"
    return "mcp__playwright-test__"  # default (dashboard/production)


def build_allowed_tools(
    base_tools: list,
    mcp_tools: list,
    *,
    mcp_config_dir: Path | str | None = None,
    mcp_config_path: Path | str | None = None,
) -> list:
    """Build allowed_tools list with correct MCP prefix.

    Args:
        base_tools: Non-MCP tool names (e.g. ["Glob", "Grep", "Read", "LS"])
        mcp_tools: MCP tool suffixes (e.g. ["browser_click", "browser_snapshot"])

    Returns:
        Combined list with MCP tools properly prefixed.
    """
    prefix = get_mcp_tool_prefix(
        "playwright",
        mcp_config_dir=mcp_config_dir,
        mcp_config_path=mcp_config_path,
    )
    return base_tools + [f"{prefix}{t}" for t in mcp_tools]


def build_mcp_allowed_tools(
    server_hint: str,
    base_tools: list,
    mcp_tools: list,
    *,
    mcp_config_dir: Path | str | None = None,
    mcp_config_path: Path | str | None = None,
) -> list:
    """Build allowed_tools for a named MCP server family."""
    prefix = get_mcp_tool_prefix(
        server_hint,
        mcp_config_dir=mcp_config_dir,
        mcp_config_path=mcp_config_path,
    )
    return base_tools + [f"{prefix}{t}" for t in mcp_tools]


@dataclass
class ToolCall:
    """Record of a single tool invocation."""

    name: str
    timestamp: datetime
    duration_ms: float | None = None
    success: bool = True
    error: str | None = None
    input: dict[str, Any] | None = None
    result_preview: str | None = None


class UnproductiveAgentStreamError(RuntimeError):
    """Raised when SDK events keep arriving without parsed output/tool activity."""

    def __init__(self, progress: dict[str, Any]):
        self.progress = dict(progress)
        messages = self.progress.get("messages_received", 0)
        elapsed = self.progress.get("elapsed_seconds", 0)
        super().__init__(
            "Agent stream produced "
            f"{messages} messages over {elapsed:.0f}s but no parsed text, tool calls, or output."
        )


SENSITIVE_INPUT_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "credential",
    "private_key",
)

NATIVE_TEST_MCP_TOOL_SUFFIXES = {
    "planner_setup_page",
    "planner_save_plan",
    "generator_setup_page",
    "generator_read_log",
    "generator_write_test",
    "test_debug",
    "test_run",
    "test_list",
}


@dataclass(frozen=True)
class AgentSdkFeaturePolicy:
    """Resolve Claude Agent SDK feature flags against provider capabilities."""

    tool_search: str | None = None

    _DISABLED = frozenset({"", "0", "false", "no", "off", "disabled", "none"})
    _FORCED = frozenset({"1", "true", "yes", "on", "force", "forced"})

    def resolve_tool_search(
        self,
        *,
        env_vars: dict[str, str] | None,
        heavy_mcp_run: bool,
    ) -> tuple[str | None, dict[str, Any]]:
        explicit = self.tool_search
        explicit_source = "constructor" if explicit is not None else None
        if explicit is None:
            if env_vars and "ENABLE_TOOL_SEARCH" in env_vars:
                explicit = env_vars.get("ENABLE_TOOL_SEARCH")
                explicit_source = "env_vars"
            elif "ENABLE_TOOL_SEARCH" in os.environ:
                explicit = os.environ.get("ENABLE_TOOL_SEARCH")
                explicit_source = "environment"

        if explicit is not None:
            normalized = str(explicit).strip()
            lowered = normalized.lower()
            if lowered in self._DISABLED:
                return None, {
                    "policy": normalized or "off",
                    "source": explicit_source,
                    "reason": "explicit_disabled",
                    "provider_supported": None,
                    "heavy_mcp_run": heavy_mcp_run,
                }
            if lowered in self._FORCED:
                return "true", {
                    "policy": normalized,
                    "source": explicit_source,
                    "reason": "explicit_enabled",
                    "provider_supported": None,
                    "heavy_mcp_run": heavy_mcp_run,
                }
            return normalized, {
                "policy": normalized,
                "source": explicit_source,
                "reason": "explicit_enabled",
                "provider_supported": None,
                "heavy_mcp_run": heavy_mcp_run,
            }

        provider_supported = self._supports_tool_references(env_vars)
        if heavy_mcp_run and provider_supported:
            return "auto:5", {
                "policy": "auto:5",
                "source": "auto",
                "reason": "heavy_mcp_first_party",
                "provider_supported": True,
                "heavy_mcp_run": heavy_mcp_run,
            }
        return None, {
            "policy": "auto:5",
            "source": "auto",
            "reason": "not_heavy_mcp_run" if not heavy_mcp_run else "provider_not_first_party",
            "provider_supported": provider_supported,
            "heavy_mcp_run": heavy_mcp_run,
        }

    @staticmethod
    def _supports_tool_references(env_vars: dict[str, str] | None) -> bool:
        try:
            selection = resolve_runtime_ai_selection("tool_deep", env_vars=env_vars)
        except Exception:
            return False
        if selection.provider != "anthropic_compatible":
            return False
        return "anthropic.com" in (selection.base_url or "").lower()


def classify_agent_error_type(error: Any, fallback: str | None = None) -> str | None:
    if isinstance(error, UnproductiveAgentStreamError):
        return "unproductive_stream"
    text = str(error or "")
    lowered = text.lower()
    if "no conversation found" in lowered and "session id" in lowered:
        return "invalid_session_resume"
    if "processerror" in lowered or "process error" in lowered:
        return "agent_process_error"
    if "heartbeat lost" in lowered:
        return "heartbeat_lost"
    if "browser" in lowered and "timeout" in lowered:
        return "browser_tool_timeout"
    if is_transient_provider_error(error):
        return "provider_overloaded"
    return fallback


def _is_sensitive_input_key(key: str | None) -> bool:
    lowered = str(key or "").lower()
    return any(part in lowered for part in SENSITIVE_INPUT_KEY_PARTS)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _json_length(value: Any) -> int:
    try:
        return len(json.dumps(value, default=str, ensure_ascii=False))
    except Exception:
        return len(str(value))


def _safe_input_preview(value: Any, *, key: str | None = None, depth: int = 0) -> Any:
    if _is_sensitive_input_key(key):
        return "[REDACTED]"
    if depth > 4:
        return "[TRUNCATED_DEPTH]"
    if isinstance(value, str):
        max_chars = 1000
        if len(value) <= max_chars:
            return value
        return value[:max_chars] + f"...[truncated {len(value) - max_chars} chars]"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        items = list(value.items())
        preview = {
            str(k): _safe_input_preview(v, key=str(k), depth=depth + 1)
            for k, v in items[:25]
        }
        if len(items) > 25:
            preview["__truncated_keys"] = len(items) - 25
        return preview
    if isinstance(value, list):
        preview = [_safe_input_preview(item, key=key, depth=depth + 1) for item in value[:25]]
        if len(value) > 25:
            preview.append(f"[truncated {len(value) - 25} items]")
        return preview
    return str(value)[:1000]


def _tool_content_value(tool_input: dict[str, Any] | None) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    for key in ("content", "plan", "markdown", "prompt", "text"):
        value = tool_input.get(key)
        if isinstance(value, str) and not _is_sensitive_input_key(key):
            return value
    return None


def build_safe_tool_input_metadata(tool_input: dict[str, Any] | None) -> dict[str, Any]:
    """Return redacted/truncated metadata for persisted tool-call diagnostics."""
    if not isinstance(tool_input, dict):
        return {
            "input_preview": None,
            "input_length": 0,
            "input_content_length": 0,
            "content_hash": None,
        }
    preview = _safe_input_preview(tool_input)
    content_value = _tool_content_value(tool_input)
    try:
        preview_serialized = json.dumps(preview, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        preview_serialized = str(preview)
    return {
        "input_preview": preview,
        "input_length": _json_length(tool_input),
        "input_content_length": len(content_value) if content_value is not None else 0,
        "content_hash": _sha256_text(content_value if content_value is not None else preview_serialized),
    }


@dataclass
class AgentResult:
    """Result of an agent execution."""

    success: bool
    output: str = ""
    error: str | None = None
    error_type: str | None = None
    duration_seconds: float = 0.0
    tool_calls: list[ToolCall] = field(default_factory=list)
    messages_received: int = 0
    text_blocks_received: int = 0
    timed_out: bool = False
    cancelled: bool = False
    api_error_status: int | None = None
    stop_reason: str | None = None
    session_id: str | None = None
    total_cost_usd: float | None = None
    hook_events_received: int = 0
    token_telemetry: dict[str, Any] = field(default_factory=dict)


class AgentRunner:
    """
    Unified runner for Claude agents with comprehensive logging and timeout support.

    Usage:
        runner = AgentRunner(timeout_seconds=1800, log_tools=True, model_tier="tool_deep")
        result = await runner.run(prompt="Your prompt here")
        if result.success:
            print(result.output)
        else:
            print(f"Failed: {result.error}")
    """

    def __init__(
        self,
        timeout_seconds: int = 1800,
        allowed_tools: list[str] | None = None,
        tools: list[str] | dict[str, str] | None = None,
        disallowed_tools: list[str] | None = None,
        permission_mode: str | None = None,
        strict_mcp_config: bool = True,
        max_budget_usd: float | None = None,
        task_budget: dict[str, int] | None = None,
        include_hook_events: bool = False,
        include_partial_messages: bool = False,
        output_format: dict[str, Any] | None = None,
        resume_session_id: str | None = None,
        continue_conversation: bool = False,
        max_turns: int | None = None,
        log_tools: bool = True,
        on_tool_use: Callable[[str, dict], None] | None = None,
        tool_permission_guard: Callable[[str, dict[str, Any], Any], Any] | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        session_dir: Path | None = None,
        on_task_enqueued: Callable[[str], None] | None = None,
        cwd: Path | str | None = None,
        max_browser_tool_calls: int | None = None,
        owner_type: str | None = None,
        owner_id: str | None = None,
        owner_label: str | None = None,
        requires_live_browser: bool = False,
        is_cancelled: Callable[[], Any] | None = None,
        memory_project_id: str | None = None,
        memory_agent_type: str | None = None,
        memory_source_type: str | None = None,
        memory_source_id: str | None = None,
        memory_stage: str | None = None,
        inject_memory: bool = True,
        capture_memory: bool = True,
        force_direct_execution: bool = False,
        model: str | None = None,
        fallback_model: str | None = None,
        model_tier: RuntimeModelTier | None = None,
        reasoning_budget: int | None = None,
        max_buffer_size: int | None = None,
        betas: list[str] | None = None,
        user: str | None = None,
        permission_prompt_tool_name: str | None = None,
        enable_file_checkpointing: bool = False,
        sandbox: dict[str, Any] | None = None,
        hooks: dict[str, Any] | None = None,
        agents: dict[str, Any] | None = None,
        skills: list[str] | str | None = None,
        plugins: list[Any] | None = None,
        session_store: Any | None = None,
        fork_session: bool = False,
        tool_search_policy: str | None = None,
        env_vars: dict[str, str] | None = None,
        trace_id: str | None = None,
        trace_prompt_hash: str | None = None,
        trace_agent_run_id: str | None = None,
        preserve_browser_on_failure: bool = False,
        autopilot_retry_enabled: bool = False,
        autopilot_session_id: str | None = None,
        autopilot_stable_key: str | None = None,
        autopilot_agent_kind: str | None = None,
        autopilot_source_type: str | None = None,
        autopilot_source_id: str | None = None,
        autopilot_checklist_title: str | None = None,
        autopilot_phase_name: str | None = None,
        autopilot_checklist_kind: str | None = None,
    ):
        """
        Initialize the agent runner.

        Args:
            timeout_seconds: Maximum time to wait for agent completion (default 30 min)
            allowed_tools: Tools auto-approved without prompting (default ["*"] for back-compat)
            tools: Base set of tools available to Claude. If omitted, explicit
                allowed_tools lists are also used as the availability list.
            disallowed_tools: Tools hidden from the model even if otherwise available
            permission_mode: Claude permission mode. Defaults to "dontAsk" for
                no-tool calls and "bypassPermissions" otherwise.
            strict_mcp_config: Use only the run-local MCP config when one is present
            max_budget_usd: Optional per-run spend cap passed to Claude Code
            task_budget: Optional token budget, e.g. {"total": 50000}
            include_hook_events: Include hook lifecycle events in the SDK stream
            include_partial_messages: Include partial stream chunks when supported
            output_format: Optional native SDK output format contract.
            resume_session_id: Optional Claude session ID to resume.
            continue_conversation: Continue the most recent Claude conversation when supported.
            max_turns: Optional SDK maximum turn count.
            log_tools: Whether to log tool invocations to console
            on_tool_use: Optional callback when a tool is used
            tool_permission_guard: Optional SDK permission callback for denying tool use before execution.
            on_progress: Optional callback receiving live progress snapshots
            session_dir: Optional directory to save debug output
            on_task_enqueued: Optional callback fired with task_id when queued (for progress tracking)
            cwd: Optional working directory for MCP config discovery and queued execution
            max_browser_tool_calls: Optional hard cap for completed browser tool calls
            owner_type: Optional logical owner type for queue lifecycle cleanup
            owner_id: Optional logical owner ID for queue lifecycle cleanup
            owner_label: Optional human-readable owner label for queue diagnostics
            requires_live_browser: Route queued tasks only to workers that can provide a headed/VNC browser.
            is_cancelled: Optional callback checked during direct runtime execution.
            memory_project_id: Optional project scope for prompt memory
            memory_agent_type: Optional memory actor label
            memory_source_type: Optional memory source type for capture/telemetry
            memory_source_id: Optional memory source ID for capture/telemetry
            memory_stage: Optional telemetry stage for memory injection
            inject_memory: Whether to inject memory context into prompts
            capture_memory: Whether to extract memory candidates from run output
            force_direct_execution: Bypass the Redis queue for this run even
                when global queue mode is enabled.
            model: Optional model override for this run.
            fallback_model: Optional fallback model for overloaded/unavailable primary models.
            model_tier: Optional canonical model tier for this run.
            reasoning_budget: Optional provider reasoning budget for compatible models.
            max_buffer_size: Optional SDK stream buffer limit.
            betas: Optional SDK/API beta headers.
            user: Optional SDK user identifier for attribution.
            permission_prompt_tool_name: Optional SDK permission prompt tool.
            enable_file_checkpointing: Enable SDK file checkpoints for rewind-capable runs.
            sandbox: Optional SDK sandbox settings.
            hooks: Optional SDK hook configuration.
            agents: Optional SDK subagent definitions.
            skills: Optional SDK skill allowlist or "all".
            plugins: Optional SDK plugin configuration.
            session_store: Optional SDK durable session store.
            fork_session: Fork a resumed SDK session when supported.
            tool_search_policy: Tool search policy: off, auto, auto:N, or force.
            env_vars: Explicit environment variables to expose to direct and queued execution.
            trace_id: Optional deep trace ID for agent observability.
            trace_prompt_hash: Optional upstream prompt hash.
            trace_agent_run_id: AgentRun ID to link trace records and memory injection telemetry.
            preserve_browser_on_failure: Leave child browser/MCP processes running
                after failed or timed-out browser debug runs for post-failure inspection.
            autopilot_retry_enabled: Enable AutoPilot-only durable retry/resume wrapper.
            autopilot_session_id: AutoPilot session ID for attempt persistence.
            autopilot_stable_key: Stable checklist/attempt key for this agent call.
            autopilot_agent_kind: Compact kind label for attempt diagnostics.
            autopilot_source_type/source_id: Existing checklist source row to update.
            autopilot_checklist_title/phase/kind: Checklist row metadata.
        """
        self.timeout_seconds = timeout_seconds
        self.allowed_tools = ["*"] if allowed_tools is None else allowed_tools
        self.tools = tools
        self.disallowed_tools = disallowed_tools or []
        self.permission_mode = permission_mode
        self.strict_mcp_config = strict_mcp_config
        self.max_budget_usd = max_budget_usd
        self.task_budget = task_budget
        self.include_hook_events = include_hook_events
        self.include_partial_messages = include_partial_messages
        self.output_format = output_format
        self.resume_session_id = resume_session_id
        self.continue_conversation = continue_conversation
        self.max_turns = max_turns
        self.log_tools = log_tools
        self.on_tool_use = on_tool_use
        self.tool_permission_guard = tool_permission_guard
        self.on_progress = on_progress
        self.session_dir = session_dir
        self.on_task_enqueued = on_task_enqueued
        self.cwd = Path(cwd) if cwd else None
        self.max_browser_tool_calls = max_browser_tool_calls
        self.owner_type = owner_type
        self.owner_id = owner_id
        self.owner_label = owner_label
        self.requires_live_browser = requires_live_browser
        self.is_cancelled = is_cancelled
        self.memory_project_id = memory_project_id
        self.memory_agent_type = memory_agent_type or "AgentRunner"
        self.memory_source_type = memory_source_type or "agent_run"
        self.memory_source_id = memory_source_id
        self.memory_stage = memory_stage or "agent_runner"
        self.inject_memory = inject_memory
        self.capture_memory = capture_memory
        self.force_direct_execution = force_direct_execution
        self.model = model
        self.fallback_model = fallback_model
        self.model_tier = model_tier if model_tier in {"light", "standard", "deep", "tool_deep", "chat", "embedding"} else self._infer_model_tier()
        self.reasoning_budget = reasoning_budget
        self.max_buffer_size = max_buffer_size
        self.betas = list(betas or [])
        self.user = user
        self.permission_prompt_tool_name = permission_prompt_tool_name
        self.enable_file_checkpointing = enable_file_checkpointing
        self.sandbox = sandbox
        self.hooks = hooks
        self.agents = agents
        self.skills = skills
        self.plugins = plugins
        self.session_store = session_store
        self.fork_session = fork_session
        self.tool_search_policy = tool_search_policy
        self.env_vars = {str(key): str(value) for key, value in (env_vars or {}).items() if key and value is not None}
        self.trace_id = trace_id
        self.trace_prompt_hash = trace_prompt_hash
        self.trace_agent_run_id = trace_agent_run_id or owner_id
        self.preserve_browser_on_failure = preserve_browser_on_failure
        self.autopilot_retry_enabled = autopilot_retry_enabled
        self.autopilot_session_id = autopilot_session_id or (owner_id if owner_type == "autopilot" else None)
        self.autopilot_stable_key = autopilot_stable_key
        self.autopilot_agent_kind = autopilot_agent_kind
        self.autopilot_source_type = autopilot_source_type
        self.autopilot_source_id = autopilot_source_id
        self.autopilot_checklist_title = autopilot_checklist_title
        self.autopilot_phase_name = autopilot_phase_name
        self.autopilot_checklist_kind = autopilot_checklist_kind
        self._autopilot_retry_inner = False
        (
            self._resolved_tool_search_env,
            self._resolved_tool_search_details,
        ) = AgentSdkFeaturePolicy(self.tool_search_policy).resolve_tool_search(
            env_vars=self.env_vars,
            heavy_mcp_run=self._native_mcp_heavy_run(),
        )
        tool_search = self._effective_tool_search_env()
        if tool_search and "ENABLE_TOOL_SEARCH" not in self.env_vars:
            self.env_vars["ENABLE_TOOL_SEARCH"] = tool_search
        self._last_memory_injected = False
        self._last_memory_context = ""
        self.unproductive_stream_min_messages = self._env_int(
            "AGENT_UNPRODUCTIVE_STREAM_MIN_MESSAGES",
            500,
            minimum=1,
        )
        self.unproductive_stream_seconds = self._env_int(
            "AGENT_UNPRODUCTIVE_STREAM_SECONDS",
            180,
            minimum=0,
        )

    @staticmethod
    def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
        try:
            value = int(os.environ.get(name, str(default)))
        except (TypeError, ValueError):
            value = default
        if minimum is not None:
            value = max(minimum, value)
        return value

    def _effective_tools(self) -> list[str] | dict[str, str] | None:
        """Build the SDK/CLI tool availability set.

        Newer Claude Agent SDKs distinguish tools that are available from tools
        that are pre-approved. Most of this codebase historically used
        allowed_tools for both, so preserve that meaning for explicit lists.
        """
        if self.tools is not None:
            return self.tools
        if self.allowed_tools == []:
            return []
        if "*" in self.allowed_tools:
            return None
        return list(self.allowed_tools)

    def _effective_permission_mode(self) -> str:
        if self.permission_mode:
            return self.permission_mode
        if self._effective_tools() == []:
            return "dontAsk"
        return "bypassPermissions"

    def diagnostics(self, *, agent_class: str | None = None, prompt: str | None = None) -> dict[str, Any]:
        """Return resolved runtime/tool/memory diagnostics for observability tests and logs."""

        selection = apply_runtime_env_aliases(self.env_vars or None, tier=self.model_tier, model_override=self.model)
        mcp_prefixes = sorted(
            {
                "__".join(str(tool).split("__")[:2])
                for tool in self._requested_mcp_tools()
                if len(str(tool).split("__")) >= 3
            }
        )
        prompt_hash = None
        if prompt is not None:
            try:
                import hashlib

                prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            except Exception:
                prompt_hash = None
        return {
            "agent_class": agent_class or self.memory_agent_type,
            "provider": selection.provider,
            "runtime": selection.runtime,
            "tier": selection.tier,
            "model": selection.model,
            "api_key_set": bool(selection.api_key),
            "api_key_env": selection.api_key_env,
            "allowed_tools": list(self.allowed_tools),
            "tools": self._effective_tools(),
            "mcp_prefixes": mcp_prefixes,
            "memory": {
                "inject": self.inject_memory,
                "capture": self.capture_memory,
                "agent_type": self.memory_agent_type,
                "stage": self.memory_stage,
                "source_type": self.memory_source_type,
                "source_id": self.memory_source_id,
            },
            "requires_live_browser": self.requires_live_browser,
            "preserve_browser_on_failure": self.preserve_browser_on_failure,
            "tool_permission_guard": bool(self.tool_permission_guard),
            "sdk_options": {
                "fallback_model": self.fallback_model,
                "reasoning_budget": self.reasoning_budget,
                "include_partial_messages": self.include_partial_messages,
                "max_buffer_size": self.max_buffer_size,
                "betas": list(self.betas),
                "user": self.user,
                "permission_prompt_tool_name": self.permission_prompt_tool_name,
                "enable_file_checkpointing": self.enable_file_checkpointing,
                "sandbox": bool(self.sandbox),
                "hooks": bool(self.hooks),
                "agents": sorted(self.agents.keys()) if isinstance(self.agents, dict) else None,
                "skills": self.skills,
                "plugins": bool(self.plugins),
                "session_store": bool(self.session_store),
                "fork_session": self.fork_session,
            },
            "tool_search": self._tool_search_diagnostics(),
            "prompt": {
                "provided": prompt is not None,
                "hash": prompt_hash,
                "chars": len(prompt or ""),
                "estimated_tokens": estimate_tokens(prompt),
            },
        }

    def _build_token_telemetry(
        self,
        *,
        prompt: str | None,
        output: str | None,
        provider_usage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return build_agent_token_telemetry(
            prompt=prompt,
            output=output,
            memory_context=self._last_memory_context,
            stage=self.memory_stage,
            agent_type=self.memory_agent_type,
            model=self.model,
            model_tier=self.model_tier,
            provider_usage=provider_usage,
        )

    def _requested_mcp_tools(self) -> list[str]:
        requested: list[str] = []
        for source in (self.allowed_tools, self._effective_tools()):
            if isinstance(source, list):
                requested.extend(
                    str(tool) for tool in source if str(tool).startswith("mcp__")
                )
        return requested

    def _native_mcp_heavy_run(self) -> bool:
        mcp_tools = self._requested_mcp_tools()
        if len(mcp_tools) < 5:
            return False
        for tool in mcp_tools:
            parts = str(tool).split("__", 2)
            if len(parts) >= 3 and parts[1] == "playwright-test":
                return True
            if len(parts) >= 3 and parts[2] in NATIVE_TEST_MCP_TOOL_SUFFIXES:
                return True
        return False

    def _effective_tool_search_env(self) -> str | None:
        return self._resolved_tool_search_env

    def _tool_search_diagnostics(self) -> dict[str, Any]:
        value = self._resolved_tool_search_env
        details = self._resolved_tool_search_details
        return {
            "requested": bool(value),
            "enable_tool_search": value,
            "accepted": "unknown_until_sdk_or_cli_start",
            **details,
        }

    def _is_browser_mcp_run(self) -> bool:
        if self.requires_live_browser:
            return True
        return any(str(tool).startswith("mcp__playwright") for tool in self._requested_mcp_tools())

    def _should_preserve_browser_processes(self, result: AgentResult | None) -> bool:
        if not self.preserve_browser_on_failure or not result:
            return False
        if result.cancelled or result.success:
            return False
        return self._is_browser_mcp_run()

    def _emit_progress(self, progress: dict[str, Any]) -> None:
        progress = {
            "agent_type": self.memory_agent_type,
            "stage": self.memory_stage,
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
            **progress,
        }
        self._write_latest_progress(progress)
        if not self.on_progress:
            return
        try:
            self.on_progress(progress)
        except Exception as exc:
            logger.debug(f"Agent progress callback failed: {exc}")

    def _write_latest_progress(self, progress: dict[str, Any]) -> None:
        if not self.session_dir:
            return
        try:
            path = Path(self.session_dir) / "agent_progress.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(progress, indent=2, sort_keys=True, default=str))
        except Exception as exc:
            logger.debug("Could not write latest agent progress: %s", exc)

    async def _check_cancelled(self) -> bool:
        if not self.is_cancelled:
            return False
        try:
            result = self.is_cancelled()
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        except Exception as exc:
            logger.debug("Agent cancellation check failed: %s", exc)
            return False

    def _cancelled_result(
        self,
        *,
        start_time: datetime,
        output_parts: list[str] | None = None,
        tool_calls: list[ToolCall] | None = None,
        messages_received: int = 0,
        text_blocks_received: int = 0,
        api_error_status: int | None = None,
        stop_reason: str | None = None,
        session_id: str | None = None,
        total_cost_usd: float | None = None,
        hook_events_received: int = 0,
        token_telemetry: dict[str, Any] | None = None,
    ) -> AgentResult:
        return AgentResult(
            success=False,
            output="\n".join(output_parts or []),
            error="Agent run cancelled",
            error_type="cancelled",
            duration_seconds=(datetime.now() - start_time).total_seconds(),
            tool_calls=tool_calls or [],
            messages_received=messages_received,
            text_blocks_received=text_blocks_received,
            timed_out=False,
            cancelled=True,
            api_error_status=api_error_status,
            stop_reason=stop_reason,
            session_id=session_id,
            total_cost_usd=total_cost_usd,
            hook_events_received=hook_events_received,
            token_telemetry=token_telemetry or {},
        )

    def _should_attach_mcp_config(self, cwd: Path | None = None) -> bool:
        base_dir = cwd or Path.cwd()
        if not (base_dir / ".mcp.json").exists():
            return False
        return "*" in self.allowed_tools or bool(self._requested_mcp_tools())

    def _claude_options_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "allowed_tools": self.allowed_tools,
            "setting_sources": ["project"],
            "permission_mode": self._effective_permission_mode(),
        }

        tools = self._effective_tools()
        if tools is not None:
            kwargs["tools"] = tools
        if self.disallowed_tools:
            kwargs["disallowed_tools"] = self.disallowed_tools
        if self.max_budget_usd is not None:
            kwargs["max_budget_usd"] = self.max_budget_usd
        if self.task_budget is not None:
            kwargs["task_budget"] = self.task_budget
        if self.cwd is not None and self._claude_options_accepts("cwd"):
            kwargs["cwd"] = self.cwd
        if self.include_hook_events:
            kwargs["include_hook_events"] = True
        if self.include_partial_messages and self._claude_options_accepts("include_partial_messages"):
            kwargs["include_partial_messages"] = True
        if self.output_format is not None and self._claude_options_accepts("output_format"):
            kwargs["output_format"] = self.output_format
        if self.resume_session_id and self._claude_options_accepts("resume"):
            kwargs["resume"] = self.resume_session_id
        if self.continue_conversation and self._claude_options_accepts("continue_conversation"):
            kwargs["continue_conversation"] = True
        if self.max_turns is not None and self._claude_options_accepts("max_turns"):
            kwargs["max_turns"] = self.max_turns
        if self.model:
            kwargs["model"] = self.model
        if self.fallback_model and self._claude_options_accepts("fallback_model"):
            kwargs["fallback_model"] = self.fallback_model
        if self.reasoning_budget is not None and self._claude_options_accepts("max_thinking_tokens"):
            kwargs["max_thinking_tokens"] = self.reasoning_budget
        if self.max_buffer_size is not None and self._claude_options_accepts("max_buffer_size"):
            kwargs["max_buffer_size"] = self.max_buffer_size
        if self.betas and self._claude_options_accepts("betas"):
            kwargs["betas"] = self.betas
        if self.user and self._claude_options_accepts("user"):
            kwargs["user"] = self.user
        if self.permission_prompt_tool_name and self._claude_options_accepts("permission_prompt_tool_name"):
            kwargs["permission_prompt_tool_name"] = self.permission_prompt_tool_name
        if self.enable_file_checkpointing and self._claude_options_accepts("enable_file_checkpointing"):
            kwargs["enable_file_checkpointing"] = True
        if self.sandbox and self._claude_options_accepts("sandbox"):
            kwargs["sandbox"] = self.sandbox
        if self.tool_permission_guard and self._claude_options_accepts("can_use_tool"):
            kwargs["can_use_tool"] = self.tool_permission_guard
        if self.hooks and self._claude_options_accepts("hooks"):
            kwargs["hooks"] = self.hooks
        if self.agents and self._claude_options_accepts("agents"):
            kwargs["agents"] = self.agents
        if self.skills is not None and self._claude_options_accepts("skills"):
            kwargs["skills"] = self.skills
        if self.plugins and self._claude_options_accepts("plugins"):
            kwargs["plugins"] = self.plugins
        if self.fork_session and self._claude_options_accepts("fork_session"):
            kwargs["fork_session"] = True
        if self.session_store and self._claude_options_accepts("session_store"):
            kwargs["session_store"] = self.session_store

        if self._should_attach_mcp_config(self.cwd):
            kwargs["mcp_servers"] = (self.cwd or Path.cwd()) / ".mcp.json"
            if self._claude_options_accepts("strict_mcp_config"):
                kwargs["strict_mcp_config"] = self.strict_mcp_config
            elif self.strict_mcp_config:
                kwargs.setdefault("extra_args", {})["strict-mcp-config"] = None

        return kwargs

    @staticmethod
    def _claude_options_accepts(option_name: str) -> bool:
        if ClaudeAgentOptions is None:
            return False
        try:
            signature = inspect.signature(ClaudeAgentOptions)
        except (TypeError, ValueError):
            return True
        if option_name in signature.parameters:
            return True
        return any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())

    def _requires_direct_sdk_execution(self) -> bool:
        """Return true when a requested option has no queue/CLI equivalent."""
        return bool(
            self.tool_permission_guard
            or self.reasoning_budget is not None
            or self.max_buffer_size is not None
            or self.user
            or self.permission_prompt_tool_name
            or self.enable_file_checkpointing
            or self.sandbox
            or self.hooks
            or self.agents
            or self.skills is not None
            or self.plugins
            or self.session_store
            or self.fork_session
        )

    def _infer_model_tier(self) -> RuntimeModelTier:
        tools = self._effective_tools()
        sources: list[Any] = [self.allowed_tools]
        if isinstance(tools, list):
            sources.append(tools)
        requested = [str(tool) for source in sources if isinstance(source, list) for tool in source]
        if any("playwright" in tool or "browser" in tool for tool in requested):
            return "tool_deep"
        if tools == []:
            return "standard"
        return "deep" if requested else "standard"

    @staticmethod
    def _apply_active_ai_settings(
        model: str | None = None,
        model_tier: RuntimeModelTier = "standard",
    ) -> None:
        """Apply the runtime AI settings before invoking the SDK.

        The Settings UI persists the selected provider/model/key into .env and
        applies it to the API process. Long-running workflows and queued workers
        may start after that process state changes, so refresh the env aliases
        here before every agent call.
        """
        try:
            from orchestrator.api import settings as settings_api

            env_vars = settings_api.runtime_env_vars()
            settings_api._apply_runtime_settings(env_vars)
            apply_runtime_env_aliases(env_vars, tier=model_tier, model_override=model)
        except Exception as exc:
            logger.debug(
                f"Unable to refresh active AI settings for agent runner: {exc}"
            )

    def _validate_mcp_config_for_allowed_tools(self, cwd: Path | None = None) -> None:
        """Fail fast when MCP tools are requested but no matching server is configured."""
        mcp_tools = self._requested_mcp_tools()
        if not mcp_tools:
            return

        base_dir = cwd or Path.cwd()
        mcp_path = base_dir / ".mcp.json"
        if not mcp_path.exists():
            raise RuntimeError(
                f"MCP tools were requested but no .mcp.json exists in {base_dir}. "
                "Create a per-run MCP config before invoking the agent."
            )

        try:
            config = json.loads(mcp_path.read_text())
        except Exception as exc:
            raise RuntimeError(f"Invalid MCP config at {mcp_path}: {exc}") from exc

        servers = config.get("mcpServers") or {}
        if not isinstance(servers, dict) or not servers:
            raise RuntimeError(
                f"MCP config at {mcp_path} does not define any mcpServers"
            )

        configured_prefixes = {f"mcp__{name}__" for name in servers}
        missing_prefixes = sorted(
            {
                tool.split("__", 2)[0] + "__" + tool.split("__", 2)[1] + "__"
                for tool in mcp_tools
                if len(tool.split("__", 2)) >= 3
            }
            - configured_prefixes
        )
        if missing_prefixes:
            raise RuntimeError(
                f"Allowed MCP tools do not match configured MCP servers in {mcp_path}. "
                f"Missing prefixes: {', '.join(missing_prefixes)}; configured: {', '.join(sorted(configured_prefixes))}"
            )

        for server_name, server in servers.items():
            command = (server or {}).get("command")
            if not command:
                raise RuntimeError(
                    f"MCP server '{server_name}' in {mcp_path} has no command"
                )
            if os.path.isabs(command) and not Path(command).exists():
                raise RuntimeError(
                    f"MCP server '{server_name}' command does not exist: {command}. "
                    "Install dependencies or set PLAYWRIGHT_MCP_COMMAND."
                )

        suffixes_by_server: dict[str, set[str]] = {}
        for tool in mcp_tools:
            parts = str(tool).split("__", 2)
            if len(parts) >= 3:
                suffixes_by_server.setdefault(parts[1], set()).add(parts[2])

        for server_name, suffixes in suffixes_by_server.items():
            custom_suffixes = suffixes & NATIVE_TEST_MCP_TOOL_SUFFIXES
            if not custom_suffixes:
                continue
            server = servers.get(server_name) or {}
            args_text = " ".join(str(arg) for arg in server.get("args") or [])
            if server_name != "playwright-test" or "run-test-mcp-server" not in args_text:
                raise RuntimeError(
                    "Native planner/generator/healer tools require the run-local "
                    "`playwright-test` MCP server created by write_playwright_test_mcp_config(). "
                    f"Requested custom tools {sorted(custom_suffixes)} on server '{server_name}' "
                    f"from {mcp_path}; this looks like root @playwright/mcp."
                )

        suffixes = {suffix for values in suffixes_by_server.values() for suffix in values}
        required_groups: list[tuple[str, set[str]]] = []
        if {"planner_setup_page", "planner_save_plan"} & suffixes:
            required_groups.append(
                (
                    "planner",
                    {
                        "planner_setup_page",
                        "planner_save_plan",
                        "generator_write_test",
                        "browser_navigate",
                        "browser_snapshot",
                        "test_debug",
                        "test_run",
                    },
                )
            )
        generator_profile_requested = bool(
            {"generator_setup_page", "generator_read_log"} & suffixes
            or ("generator_write_test" in suffixes and "planner_setup_page" not in suffixes)
        )
        if generator_profile_requested:
            required_groups.append(
                (
                    "generator",
                    {
                        "generator_setup_page",
                        "generator_read_log",
                        "generator_write_test",
                        "test_debug",
                        "test_run",
                    },
                )
            )
        if ({"Edit", "MultiEdit", "Write"} & {str(tool) for tool in self.allowed_tools}) and {"test_debug", "test_run"} & suffixes:
            required_groups.append(
                (
                    "healer",
                    {
                        "test_debug",
                        "test_run",
                        "test_list",
                        "browser_snapshot",
                        "browser_console_messages",
                        "browser_network_requests",
                    },
                )
            )
        for stage, required in required_groups:
            missing = sorted(required - suffixes)
            if missing:
                raise RuntimeError(
                    f"Native {stage} MCP tool profile is incomplete for {mcp_path}. "
                    f"Missing required tools: {', '.join(missing)}"
                )

    async def run(
        self,
        prompt: str,
        timeout_override: int | None = None,
    ) -> AgentResult:
        """
        Run the agent with the given prompt.

        Args:
            prompt: The prompt to send to the agent
            timeout_override: Override the default timeout for this call

        Returns:
            AgentResult with success status, output, and diagnostics
        """
        if self.autopilot_retry_enabled and not getattr(self, "_autopilot_retry_inner", False):
            from orchestrator.services.autopilot_agent_reliability import run_agent_with_retries

            return await run_agent_with_retries(self, prompt, timeout_override=timeout_override)

        timeout = timeout_override or self.timeout_seconds
        start_time = datetime.now()
        if await self._check_cancelled():
            return self._cancelled_result(start_time=start_time)
        self._apply_active_ai_settings(self.model, self.model_tier)
        selection = apply_runtime_env_aliases(None, tier=self.model_tier, model_override=self.model)
        if not self.model:
            self.model = selection.model
        self._validate_mcp_config_for_allowed_tools(self.cwd)
        original_prompt = prompt
        final_prompt_for_telemetry: str | None = None
        self._last_memory_injected = False
        self._last_memory_context = ""
        prompt = append_browser_dialog_recovery_policy(
            prompt,
            self.allowed_tools,
            self._effective_tools(),
            disallowed_tools=self.disallowed_tools,
        )
        prompt = self._augment_prompt_with_agent_memory(prompt)
        try:
            from orchestrator.ai.prompt_registry import attach_delivered_prompt_metadata

            prompt = attach_delivered_prompt_metadata(prompt, memory_injected=self._last_memory_injected)
        except Exception as exc:
            logger.debug("Delivered prompt metadata skipped: %s", exc)
        final_prompt_for_telemetry = prompt
        if self.trace_agent_run_id:
            try:
                from orchestrator.services.agent_trace import ensure_trace_snapshot

                snapshot = ensure_trace_snapshot(
                    run_id=self.trace_agent_run_id,
                    prompt=prompt,
                    memory_context=self._last_memory_context or None,
                    runtime="claude_sdk",
                    model=self.model,
                    model_tier=self.model_tier,
                    allowed_tools=self.allowed_tools,
                    runtime_diagnostics=self.diagnostics(prompt=prompt),
                )
                if snapshot:
                    self.trace_id = snapshot.id
                    self.trace_prompt_hash = snapshot.prompt_hash or _sha256_text(prompt)
            except Exception as exc:
                logger.debug("Agent trace prompt snapshot skipped: %s", exc)

        # First, try agent queue if Redis is available
        # This offloads execution to a separate worker process outside uvicorn
        if (
            AGENT_QUEUE_AVAILABLE
            and should_use_agent_queue()
            and not self.force_direct_execution
            and not self._requires_direct_sdk_execution()
        ):
            logger.info(f"Using agent queue for execution (timeout={timeout}s)")
            queued_result = await self._run_via_queue(prompt, timeout)
            if not queued_result.token_telemetry:
                queued_result.token_telemetry = self._build_token_telemetry(
                    prompt=final_prompt_for_telemetry,
                    output=queued_result.output,
                )
            self._append_cost_log(queued_result)
            self._capture_agent_memory(original_prompt, queued_result)
            return queued_result

        if query is None:
            unavailable_result = AgentResult(
                success=False,
                error="claude_agent_sdk not available",
            )
            self._append_cost_log(unavailable_result)
            return unavailable_result
        result_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        messages_received = 0
        text_blocks_received = 0
        hook_events_received = 0
        api_error_status: int | None = None
        stop_reason: str | None = None
        session_id: str | None = None
        total_cost_usd: float | None = None
        provider_usage: dict[str, Any] = {}
        pending_tools: dict[str, tuple[str, datetime, dict[str, Any]]] = {}
        pending_tool_counter = 0

        # Snapshot child PIDs before query for orphan cleanup
        pre_query_pids = snapshot_child_pids()
        agent_result: AgentResult | None = None
        debug_output_saved = False

        try:
            # Wrap the query in a timeout
            async def _run_query():
                nonlocal pending_tool_counter
                nonlocal messages_received, text_blocks_received, result_parts
                nonlocal tool_calls, pending_tools
                nonlocal hook_events_received, api_error_status, stop_reason, session_id, total_cost_usd, provider_usage

                def _field(item: Any, name: str, default: Any = None) -> Any:
                    if isinstance(item, dict):
                        return item.get(name, default)
                    return getattr(item, name, default)

                def _browser_tool_count(include_pending: bool = False) -> int:
                    completed = len(
                        [tc for tc in tool_calls if tc.name.startswith("mcp__playwright")]
                    )
                    if not include_pending:
                        return completed
                    return completed + len(
                        [
                            name
                            for name, _started_at, _tool_input in pending_tools.values()
                            if name.startswith("mcp__playwright")
                        ]
                    )

                def _progress_snapshot(phase: str = "streaming") -> dict[str, Any]:
                    elapsed = (datetime.now() - start_time).total_seconds()
                    output_chars = sum(len(part) for part in result_parts)
                    parsed_tool_count = len(tool_calls) + len(pending_tools)
                    unproductive = (
                        messages_received >= self.unproductive_stream_min_messages
                        and elapsed >= self.unproductive_stream_seconds
                        and text_blocks_received == 0
                        and parsed_tool_count == 0
                        and output_chars == 0
                    )
                    return {
                        "phase": phase,
                        "status": "running",
                        "messages_received": messages_received,
                        "text_blocks_received": text_blocks_received,
                        "tool_calls": parsed_tool_count,
                        "completed_tool_calls": len(tool_calls),
                        "pending_tool_calls": len(pending_tools),
                        "browser_tool_calls": _browser_tool_count(include_pending=True),
                        "output_chars": output_chars,
                        "elapsed_seconds": elapsed,
                        "unproductive_stream": unproductive,
                        "unproductive_stream_min_messages": self.unproductive_stream_min_messages,
                        "unproductive_stream_seconds": self.unproductive_stream_seconds,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }

                def _check_unproductive_stream() -> None:
                    progress = _progress_snapshot("unproductive_stream")
                    if not progress.get("unproductive_stream"):
                        return
                    logger.warning(
                        "Agent stream is unproductive: %s messages, %s text blocks, "
                        "%s tools, %s chars after %.1fs",
                        progress["messages_received"],
                        progress["text_blocks_received"],
                        progress["tool_calls"],
                        progress["output_chars"],
                        progress["elapsed_seconds"],
                    )
                    progress["status"] = "failed"
                    progress["error_type"] = "unproductive_stream"
                    progress["message"] = (
                        "Agent stream is receiving SDK events but has produced no "
                        "parsed text, tool calls, or output."
                    )
                    self._emit_progress(progress)
                    raise UnproductiveAgentStreamError(progress)

                def _handle_tool_use(tool_use: ParsedToolUse) -> None:
                    nonlocal pending_tool_counter
                    tool_name = tool_use.name
                    tool_input = dict(tool_use.input or {})
                    pending_tool_counter += 1
                    tool_use_id = tool_use.id or f"pending-tool-{pending_tool_counter}"
                    pending_tools[tool_use_id] = (tool_name, datetime.now(), tool_input)

                    if self.log_tools:
                        if tool_name.startswith("mcp__playwright"):
                            action = tool_name.split("__")[-1] if "__" in tool_name else tool_name
                            print(f"   🔧 {action}...", flush=True)
                        else:
                            print(f"   🔧 {tool_name}...", flush=True)

                    if self.on_tool_use:
                        self.on_tool_use(tool_name, tool_input)
                    self._emit_progress(
                        {
                            "phase": "tool_use",
                            "tool_calls": len(tool_calls) + len(pending_tools),
                            "browser_tool_calls": _browser_tool_count(include_pending=True),
                            "interactions": len(tool_calls) + len(pending_tools),
                            "last_tool": tool_name,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )

                def _pop_pending_tool(tool_result: ParsedToolResult) -> tuple[str, datetime, dict[str, Any]] | None:
                    if tool_result.tool_use_id and tool_result.tool_use_id in pending_tools:
                        return pending_tools.pop(tool_result.tool_use_id)
                    if not tool_result.tool_use_id and len(pending_tools) == 1:
                        key = next(iter(pending_tools))
                        return pending_tools.pop(key)
                    return None

                def _handle_tool_result(tool_result: ParsedToolResult) -> None:
                    pending_tool = _pop_pending_tool(tool_result)
                    if pending_tool:
                        tool_name, tool_start, tool_input = pending_tool
                        duration = (datetime.now() - tool_start).total_seconds() * 1000
                        tool_calls.append(
                            ToolCall(
                                name=tool_name,
                                timestamp=tool_start,
                                duration_ms=duration,
                                success=not tool_result.is_error,
                                error=tool_result_text(tool_result.content)[:200] if tool_result.is_error else None,
                                input=tool_input,
                                result_preview=tool_result_text(tool_result.content)[:1000],
                            )
                        )
                        completed_browser_calls = len(
                            [
                                tc
                                for tc in tool_calls
                                if tc.success and tc.name.startswith("mcp__") and "__browser_" in tc.name
                            ]
                        )
                        self._emit_progress(
                            {
                                "phase": "tool_result",
                                "tool_calls": len(tool_calls),
                                "browser_tool_calls": _browser_tool_count(),
                                "interactions": len(tool_calls),
                                "last_tool": tool_name,
                                "updated_at": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                        if (
                            self.max_browser_tool_calls is not None
                            and completed_browser_calls >= self.max_browser_tool_calls
                        ):
                            raise RuntimeError(
                                f"Browser tool budget reached ({completed_browser_calls}/"
                                f"{self.max_browser_tool_calls})"
                            )

                options_kwargs = self._claude_options_kwargs()

                async def _stream_user_prompt():
                    yield {
                        "type": "user",
                        "message": {"role": "user", "content": prompt},
                        "parent_tool_use_id": None,
                        "session_id": "default",
                    }

                sdk_prompt = _stream_user_prompt() if options_kwargs.get("can_use_tool") else prompt

                async for message in query(
                    prompt=sdk_prompt,
                    options=ClaudeAgentOptions(**options_kwargs),
                ):
                    if await self._check_cancelled():
                        raise asyncio.CancelledError("Agent run cancelled")
                    messages_received += 1

                    # Log message type for debugging
                    msg_type = event_type(message)
                    logger.debug(
                        f"Message #{messages_received}: type={msg_type}, "
                        f"has_result={hasattr(message, 'result')}, "
                        f"has_content={hasattr(message, 'content') or hasattr(message, 'message')}"
                    )

                    # Print periodic progress for long-running agents
                    if messages_received == 1:
                        print(
                            "   📨 First message received (agent is responding)",
                            flush=True,
                        )
                    elif messages_received % 50 == 0:
                        elapsed = (datetime.now() - start_time).total_seconds()
                        print(
                            f"   📨 {messages_received} messages ({elapsed:.0f}s elapsed)",
                            flush=True,
                        )

                    # Handle tool use
                    if msg_type:
                        if msg_type == "hook_event":
                            hook_events_received += 1

                        for tool_use in event_tool_uses(message):
                            _handle_tool_use(tool_use)

                        for tool_result in event_tool_results(message):
                            _handle_tool_result(tool_result)

                        text_blocks = event_text_blocks(message)
                        if text_blocks:
                            result_parts.extend(text_blocks)
                            text_blocks_received += len(text_blocks)
                            if text_blocks_received == len(text_blocks):
                                logger.info(
                                    f"Agent: first text output received at msg #{messages_received}"
                                )

                    # Capture content blocks
                    if hasattr(message, "content"):
                        content = message.content
                        if isinstance(content, str):
                            result_parts.append(content)
                            text_blocks_received += 1

                    # Capture the final result
                    if hasattr(message, "result"):
                        result_parts.append(message.result)

                    message_api_error_status = getattr(
                        message, "api_error_status", None
                    )
                    if message_api_error_status is not None:
                        api_error_status = message_api_error_status
                    message_stop_reason = getattr(message, "stop_reason", None)
                    if message_stop_reason is not None:
                        stop_reason = message_stop_reason
                    message_session_id = getattr(message, "session_id", None)
                    if message_session_id is not None:
                        session_id = message_session_id
                    message_total_cost_usd = getattr(message, "total_cost_usd", None)
                    if message_total_cost_usd is not None:
                        total_cost_usd = message_total_cost_usd
                    message_usage = extract_provider_usage(message)
                    if message_usage:
                        provider_usage.update(message_usage)

                    # Periodic progress logging
                    if messages_received > 0 and messages_received % 25 == 0:
                        total_chars = sum(len(p) for p in result_parts)
                        logger.info(
                            f"Agent progress: {messages_received} msgs, {text_blocks_received} text, "
                            f"{len(tool_calls)} tools, {total_chars} chars"
                        )
                        self._emit_progress(_progress_snapshot())
                        _check_unproductive_stream()

            # Run with timeout, retrying with key rotation on 429
            rotator = get_api_key_rotator() if get_api_key_rotator else None
            max_rotation_attempts = (
                rotator.key_count if rotator and rotator.key_count > 1 else 0
            )
            max_provider_attempts = provider_retry_attempts()
            slot = None
            query_completed = False

            for _rotation_attempt in range(max_rotation_attempts + 1):
                if rotator and rotator.key_count > 0:
                    slot = rotator.get_active_key()
                    if slot:
                        rotator.activate_key(slot)

                provider_attempt = 1
                rotate_key = False
                while provider_attempt <= max_provider_attempts:
                    try:
                        with self._scoped_explicit_env():
                            await asyncio.wait_for(_run_query(), timeout=timeout)

                        # Report success
                        if rotator and rotator.key_count > 0:
                            rotator.get_active_key()
                            # We already advanced round-robin, report on the slot we used
                            if slot:
                                rotator.report_success(slot)

                        query_completed = True
                        break  # Success — exit provider retry loop
                    except Exception as rotation_exc:
                        error_text = str(rotation_exc)
                        parsed_status = parse_api_error_status(rotation_exc)
                        if parsed_status is not None:
                            api_error_status = parsed_status
                        if (
                            is_transient_provider_error(rotation_exc)
                            and provider_attempt < max_provider_attempts
                        ):
                            result_parts.clear()
                            tool_calls.clear()
                            messages_received = 0
                            text_blocks_received = 0
                            hook_events_received = 0
                            api_error_status = parsed_status
                            stop_reason = None
                            session_id = None
                            total_cost_usd = None
                            provider_usage.clear()
                            pending_tools.clear()
                            wait_seconds = provider_retry_delay_seconds(provider_attempt)
                            logger.warning(
                                "Transient provider error during SDK agent run "
                                "(status=%s, attempt %s/%s); retrying in %.1fs",
                                api_error_status,
                                provider_attempt + 1,
                                max_provider_attempts,
                                wait_seconds,
                            )
                            self._emit_progress(
                                {
                                    "phase": "llm_retry",
                                    "status": "running",
                                    "message": (
                                        "LLM provider is temporarily unavailable; "
                                        f"retrying in {int(wait_seconds)}s."
                                    ),
                                    "retry_attempt": provider_attempt + 1,
                                    "retry_max_attempts": max_provider_attempts,
                                    "retry_reason": "provider_overloaded",
                                    "retry_error_status": api_error_status,
                                    "retry_wait_seconds": wait_seconds,
                                    "updated_at": datetime.now(timezone.utc).isoformat(),
                                }
                            )
                            await asyncio.sleep(wait_seconds)
                            provider_attempt += 1
                            continue
                        if (
                            is_rate_limit_error(error_text)
                            and rotator
                            and rotator.key_count > 1
                            and _rotation_attempt < max_rotation_attempts
                        ):
                            retry_after = parse_retry_after(error_text)
                            rotator.report_rate_limit(slot, retry_after)
                            logger.warning(
                                f"Rate limit hit on key {slot.masked}, "
                                f"rotating to next key (attempt {_rotation_attempt + 2}/{max_rotation_attempts + 1})"
                            )
                            # Reset accumulators for fresh attempt with new key
                            result_parts.clear()
                            tool_calls.clear()
                            messages_received = 0
                            text_blocks_received = 0
                            hook_events_received = 0
                            api_error_status = None
                            stop_reason = None
                            session_id = None
                            total_cost_usd = None
                            pending_tools.clear()
                            rotate_key = True
                            break
                        raise  # Non-retryable error or no more retries — propagate
                if query_completed:
                    break
                if rotate_key:
                    continue
                if provider_attempt > max_provider_attempts:
                    continue

            # Calculate duration
            duration = (datetime.now() - start_time).total_seconds()
            output = "\n".join(result_parts)
            token_telemetry = self._build_token_telemetry(
                prompt=final_prompt_for_telemetry,
                output=output,
                provider_usage=provider_usage,
            )

            # Save debug output if session_dir provided
            if self.session_dir:
                self._save_debug_output(output, tool_calls, messages_received)
                debug_output_saved = True

            logger.info(
                f"Agent completed: {messages_received} messages, {len(tool_calls)} tool calls, {duration:.1f}s"
            )

            agent_result = AgentResult(
                success=True,
                output=output,
                duration_seconds=duration,
                tool_calls=tool_calls,
                messages_received=messages_received,
                text_blocks_received=text_blocks_received,
                api_error_status=api_error_status,
                stop_reason=stop_reason,
                session_id=session_id,
                total_cost_usd=total_cost_usd,
                hook_events_received=hook_events_received,
                token_telemetry=token_telemetry,
            )

        except asyncio.TimeoutError:
            duration = (datetime.now() - start_time).total_seconds()
            error_msg = f"Agent timed out after {timeout} seconds"
            logger.warning(error_msg)
            print(f"⚠️ {error_msg}", flush=True)

            agent_result = AgentResult(
                success=False,
                output="\n".join(result_parts),  # Return partial output
                error=error_msg,
                error_type="timeout",
                duration_seconds=duration,
                tool_calls=tool_calls,
                messages_received=messages_received,
                text_blocks_received=text_blocks_received,
                timed_out=True,
                api_error_status=api_error_status,
                stop_reason=stop_reason,
                session_id=session_id,
                total_cost_usd=total_cost_usd,
                hook_events_received=hook_events_received,
                token_telemetry=self._build_token_telemetry(
                    prompt=final_prompt_for_telemetry,
                    output="\n".join(result_parts),
                    provider_usage=provider_usage,
                ),
            )

        except asyncio.CancelledError:
            logger.info("Agent run cancelled cooperatively")
            agent_result = self._cancelled_result(
                start_time=start_time,
                output_parts=result_parts,
                tool_calls=tool_calls,
                messages_received=messages_received,
                text_blocks_received=text_blocks_received,
                api_error_status=api_error_status,
                stop_reason=stop_reason,
                session_id=session_id,
                total_cost_usd=total_cost_usd,
                hook_events_received=hook_events_received,
                token_telemetry=self._build_token_telemetry(
                    prompt=final_prompt_for_telemetry,
                    output="\n".join(result_parts),
                    provider_usage=provider_usage,
                ),
            )

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            error_str = str(e).lower()
            parsed_status = parse_api_error_status(e)
            if parsed_status is not None:
                api_error_status = parsed_status
            error_type = (
                classify_agent_error_type(e)
                or (
                    "provider_overloaded"
                    if is_transient_provider_error(e)
                    else type(e).__name__
                )
            )

            # Handle known SDK cleanup errors gracefully
            if "cancel scope" in error_str or "cancelled" in error_str:
                output = "\n".join(result_parts)
                has_output = bool(output.strip())
                logger.info(
                    f"SDK cleanup warning (ignored): {type(e).__name__} "
                    f"(output={'present' if has_output else 'EMPTY'}, "
                    f"{messages_received} msgs, {len(tool_calls)} tool calls)"
                )
                print("ℹ️ SDK cleanup warning (ignored)", flush=True)
                agent_result = AgentResult(
                    success=has_output,
                    output=output,
                    error=(
                        None
                        if has_output
                        else "Agent completed via cancel scope but produced no text output"
                    ),
                    error_type=None if has_output else "sdk_cleanup_empty_output",
                    duration_seconds=duration,
                    tool_calls=tool_calls,
                    messages_received=messages_received,
                    text_blocks_received=text_blocks_received,
                    api_error_status=api_error_status,
                    stop_reason=stop_reason,
                    session_id=session_id,
                    total_cost_usd=total_cost_usd,
                    hook_events_received=hook_events_received,
                    token_telemetry=self._build_token_telemetry(
                        prompt=final_prompt_for_telemetry,
                        output=output,
                        provider_usage=provider_usage,
                    ),
                )
            else:
                # Actual error
                logger.error(f"Agent error: {e}")
                print(f"❌ Agent error: {e}", flush=True)

                agent_result = AgentResult(
                    success=False,
                    output="\n".join(result_parts),
                    error=str(e),
                    error_type=error_type,
                    duration_seconds=duration,
                    tool_calls=tool_calls,
                    messages_received=messages_received,
                    text_blocks_received=text_blocks_received,
                    api_error_status=api_error_status,
                    stop_reason=stop_reason,
                    session_id=session_id,
                    total_cost_usd=total_cost_usd,
                    hook_events_received=hook_events_received,
                    token_telemetry=self._build_token_telemetry(
                        prompt=final_prompt_for_telemetry,
                        output="\n".join(result_parts),
                        provider_usage=provider_usage,
                    ),
                )

        finally:
            if self._should_preserve_browser_processes(agent_result):
                logger.info(
                    "Preserving browser/MCP child processes for failed debug inspection"
                )
            else:
                # Clean up orphaned browser/MCP processes after successful, cancelled,
                # and non-browser runs.
                try:
                    killed = kill_new_children(pre_query_pids, grace_seconds=2.0)
                    if killed > 0:
                        logger.info(f"Cleaned up {killed} orphaned browser/MCP process(es)")
                except Exception:
                    pass  # Non-fatal - don't let cleanup errors mask real results

        if agent_result and not agent_result.tool_calls and agent_result.session_id:
            recovered_tool_calls = self._recover_tool_calls_from_session_jsonl(
                agent_result.session_id
            )
            if recovered_tool_calls:
                agent_result.tool_calls = recovered_tool_calls
                tool_calls[:] = recovered_tool_calls
                debug_output_saved = False
                logger.info(
                    "Recovered %d tool call(s) from Claude session JSONL for %s",
                    len(recovered_tool_calls),
                    agent_result.session_id,
                )

        if self.session_dir and agent_result and not debug_output_saved:
            self._save_debug_output(agent_result.output, agent_result.tool_calls, agent_result.messages_received)

        if agent_result:
            self._emit_progress(
                {
                    "phase": "completed" if agent_result.success else "failed",
                    "status": "completed" if agent_result.success else "failed",
                    "messages_received": agent_result.messages_received,
                    "text_blocks_received": agent_result.text_blocks_received,
                    "tool_calls": len(agent_result.tool_calls),
                    "completed_tool_calls": len(agent_result.tool_calls),
                    "pending_tool_calls": 0,
                    "output_chars": len(agent_result.output or ""),
                    "elapsed_seconds": agent_result.duration_seconds,
                    "unproductive_stream": agent_result.error_type == "unproductive_stream",
                    "error_type": agent_result.error_type,
                    "error": agent_result.error,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        self._append_cost_log(agent_result)
        self._capture_agent_memory(original_prompt, agent_result)
        return agent_result

    def _recover_tool_calls_from_session_jsonl(self, session_id: str) -> list[ToolCall]:
        """Recover SDK tool calls from Claude's session JSONL when streaming omitted them."""
        for path in self._session_jsonl_candidates(session_id):
            recovered = self._parse_tool_calls_from_jsonl(path)
            if recovered:
                return recovered
        return []

    def _session_jsonl_candidates(self, session_id: str) -> list[Path]:
        roots: list[Path] = []
        for value in (
            self.session_dir,
            self.cwd,
            self.env_vars.get("CLAUDE_CONFIG_DIR"),
            os.environ.get("CLAUDE_CONFIG_DIR"),
            Path.cwd(),
        ):
            if not value:
                continue
            path = Path(value)
            if path not in roots:
                roots.append(path)

        home_projects = Path.home() / ".claude" / "projects"
        if home_projects.exists() and home_projects not in roots:
            roots.append(home_projects)

        candidates: list[Path] = []
        seen: set[Path] = set()
        for root in roots:
            search_roots = [root / "projects"] if (root / "projects").exists() else []
            if root.name == "projects" and root.exists():
                search_roots.append(root)
            for search_root in search_roots:
                try:
                    matches = list(search_root.rglob(f"{session_id}.jsonl"))
                except OSError:
                    continue
                for match in matches:
                    resolved = match.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        candidates.append(match)
        return candidates

    def _parse_tool_calls_from_jsonl(self, path: Path) -> list[ToolCall]:
        pending: dict[str, tuple[str, datetime, dict[str, Any]]] = {}
        completed: list[ToolCall] = []
        fallback_counter = 0
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            for tool_use in event_tool_uses(event):
                fallback_counter += 1
                tool_use_id = tool_use.id or f"recovered-tool-{fallback_counter}"
                pending[tool_use_id] = (
                    tool_use.name,
                    datetime.now(),
                    dict(tool_use.input or {}),
                )

            for tool_result in event_tool_results(event):
                pending_item = None
                if tool_result.tool_use_id and tool_result.tool_use_id in pending:
                    pending_item = pending.pop(tool_result.tool_use_id)
                elif not tool_result.tool_use_id and len(pending) == 1:
                    key = next(iter(pending))
                    pending_item = pending.pop(key)
                if not pending_item:
                    continue
                tool_name, started_at, tool_input = pending_item
                completed.append(
                        ToolCall(
                            name=tool_name,
                            timestamp=started_at,
                            duration_ms=0.0,
                            success=not tool_result.is_error,
                            error=tool_result_text(tool_result.content)[:200]
                            if tool_result.is_error
                            else None,
                            input=tool_input,
                            result_preview=tool_result_text(tool_result.content)[:1000],
                        )
                    )

        for tool_name, started_at, tool_input in pending.values():
            completed.append(
                    ToolCall(
                        name=tool_name,
                        timestamp=started_at,
                        duration_ms=None,
                        success=True,
                        input=tool_input,
                )
            )

        return completed

    def _append_cost_log(self, result: AgentResult | None) -> None:
        """Best-effort per-agent cost telemetry for pipeline run artifacts."""
        if result is None:
            return
        path_value = self.env_vars.get("AGENT_COST_LOG") or os.environ.get("AGENT_COST_LOG")
        if not path_value:
            return
        try:
            path = Path(path_value)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "stage": self.memory_stage,
                "agent_type": self.memory_agent_type,
                "cost_usd": result.total_cost_usd,
                "tool_calls": len(result.tool_calls),
                "duration_seconds": result.duration_seconds,
                "timed_out": result.timed_out,
                "ts": datetime.now(timezone.utc).isoformat(),
                **(result.token_telemetry or {}),
            }
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
        except Exception as exc:
            logger.debug("Agent cost log append skipped: %s", exc)

    def _agent_memory_project_id(self) -> str | None:
        return self.memory_project_id or os.environ.get("MEMORY_PROJECT_ID") or os.environ.get("PROJECT_ID")

    def _augment_prompt_with_agent_memory(self, prompt: str) -> str:
        self._last_memory_injected = False
        self._last_memory_context = ""
        try:
            from orchestrator.memory.prompt_augmentation import augment_prompt_with_agent_memory

            augmented = augment_prompt_with_agent_memory(
                prompt,
                inject_memory=self.inject_memory,
                project_id=self._agent_memory_project_id(),
                agent_type=self.memory_agent_type,
                stage=self.memory_stage,
                source_type=self.memory_source_type,
                source_id=self.memory_source_id or self.owner_id,
                owner_type=self.owner_type,
                owner_id=self.owner_id,
                trace_agent_run_id=self.trace_agent_run_id,
                trace_id=self.trace_id,
                runtime="claude_sdk",
                model=self.model,
                model_tier=self.model_tier,
                allowed_tools=self.allowed_tools,
            )
            self._last_memory_context = augmented.context_text
            self._last_memory_injected = augmented.injected
            self.trace_id = augmented.trace_id or self.trace_id
            return augmented.prompt
        except Exception as exc:
            logger.debug("Agent memory retrieval skipped: %s", exc)
            return prompt

    def _capture_agent_memory(self, prompt: str, result: AgentResult | None) -> None:
        if not self.capture_memory or os.environ.get("MEMORY_ENABLED", "true").lower() != "true":
            return
        project_id = self._agent_memory_project_id()
        if not project_id or result is None:
            return
        text = result.output or ""
        if "remember" in prompt.lower():
            text = f"{prompt[:1200]}\n{text}"
        if not text.strip():
            return
        try:
            from orchestrator.memory.agent_memory import get_agent_memory_service

            get_agent_memory_service().capture_candidates(
                text,
                project_id=project_id,
                source_type=self.memory_source_type,
                source_id=self.memory_source_id or result.session_id,
                agent_type=self.memory_agent_type,
            )
        except Exception as exc:
            logger.debug("Agent memory capture skipped: %s", exc)

    def _collect_api_env_vars(self) -> dict:
        """Collect API-related env vars to pass through the queue to the worker.

        The pipeline loads credentials from the database into os.environ,
        but the worker runs in a separate process and only reads .env.
        This bridges the gap by forwarding current env vars with the task.
        """
        keys = [
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_AUTH_TOKENS",
            "ANTHROPIC_API_KEY",
            "ZAI_API_KEY",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            "ANTHROPIC_CHAT_MODEL",
            "QUORVEX_LLM_PROVIDER",
            "QUORVEX_LLM_BASE_URL",
            "QUORVEX_LLM_API_KEY",
            "QUORVEX_LLM_API_KEYS",
            "QUORVEX_LLM_LIGHT_MODEL",
            "QUORVEX_LLM_STANDARD_MODEL",
            "QUORVEX_LLM_DEEP_MODEL",
            "QUORVEX_LLM_TOOL_DEEP_MODEL",
            "QUORVEX_LLM_CHAT_MODEL",
            "QUORVEX_EMBEDDING_MODEL",
            "API_TIMEOUT_MS",
            "DISPLAY",
            "VNC_ENABLED",
            "HEADLESS",
            "PLAYWRIGHT_HEADLESS",
            "PLAYWRIGHT_BROWSERS_PATH",
            "PLAYWRIGHT_WORKERS",
            "PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT",
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
            "PLAYWRIGHT_MCP_EXECUTABLE_PATH",
            "QUORVEX_TEST_DATA_FILE",
            "CLAUDE_CODE_ENABLE_TELEMETRY",
            "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA",
            "ENABLE_ENHANCED_TELEMETRY_BETA",
            "CLAUDE_CODE_PROPAGATE_TRACEPARENT",
            "TRACEPARENT",
            "TRACESTATE",
            "OTEL_METRICS_EXPORTER",
            "OTEL_LOGS_EXPORTER",
            "OTEL_TRACES_EXPORTER",
            "OTEL_EXPORTER_OTLP_PROTOCOL",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_HEADERS",
            "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL",
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
            "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
            "OTEL_METRIC_EXPORT_INTERVAL",
            "OTEL_LOGS_EXPORT_INTERVAL",
            "OTEL_TRACES_EXPORT_INTERVAL",
            "OTEL_SERVICE_NAME",
            "OTEL_RESOURCE_ATTRIBUTES",
            "OTEL_LOG_USER_PROMPTS",
            "OTEL_LOG_TOOL_DETAILS",
            "OTEL_LOG_TOOL_CONTENT",
            "ENABLE_TOOL_SEARCH",
        ]
        env_vars: dict[str, str] = {}
        for key in keys:
            val = os.environ.get(key)
            if val:
                env_vars[key] = val
        env_vars.update(
            {
                key: value
                for key, value in self.env_vars.items()
                if not key.startswith("TESTDATA_")
            }
        )
        try:
            selection = apply_runtime_env_aliases(
                env_vars or None,
                tier=self.model_tier,
                model_override=self.model,
            )
            env_vars["ANTHROPIC_MODEL"] = selection.model
            env_vars["QUORVEX_LLM_ACTIVE_TIER"] = selection.tier
            env_vars["QUORVEX_LLM_ACTIVE_MODEL"] = selection.model
            if selection.api_key:
                env_vars["QUORVEX_LLM_API_KEY"] = selection.api_key
                if selection.provider == "anthropic_compatible":
                    env_vars["ANTHROPIC_AUTH_TOKEN"] = selection.api_key
                    env_vars["ANTHROPIC_API_KEY"] = selection.api_key
        except Exception as exc:
            logger.debug("Unable to collect resolved model env vars: %s", exc)
        tool_search = self._effective_tool_search_env()
        if tool_search:
            env_vars["ENABLE_TOOL_SEARCH"] = tool_search
        else:
            env_vars.pop("ENABLE_TOOL_SEARCH", None)
        return env_vars if env_vars else None

    @contextmanager
    def _scoped_explicit_env(self):
        effective_env = dict(self.env_vars)
        tool_search = self._effective_tool_search_env()
        if tool_search:
            effective_env.setdefault("ENABLE_TOOL_SEARCH", tool_search)
        if not effective_env:
            yield
            return
        saved_env: dict[str, str | None] = {}
        for key, value in effective_env.items():
            if key.startswith("TESTDATA_"):
                continue
            saved_env[key] = os.environ.get(key)
            os.environ[key] = value
        try:
            yield
        finally:
            for key, original in saved_env.items():
                if original is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = original

    def _queue_owner_metadata(self) -> tuple[str | None, str | None, str | None, str | None, str | None]:
        """Return explicit queue owner plus parent browser-slot metadata."""
        browser_slot_parent_owner_type = os.environ.get("BROWSER_SLOT_PARENT_OWNER_TYPE")
        browser_slot_parent_run_id = os.environ.get("BROWSER_SLOT_PARENT_RUN_ID")
        owner_type = self.owner_type
        owner_id = self.owner_id
        owner_label = self.owner_label
        if (
            not owner_type
            and not owner_id
            and browser_slot_parent_owner_type == "test_run"
            and browser_slot_parent_run_id
        ):
            owner_type = "test_run"
            owner_id = browser_slot_parent_run_id
            owner_label = owner_label or f"Test run {browser_slot_parent_run_id}"
        return (
            owner_type,
            owner_id,
            owner_label,
            browser_slot_parent_owner_type,
            browser_slot_parent_run_id,
        )

    async def _run_via_queue(self, prompt: str, timeout: int) -> AgentResult:
        """
        Run agent via Redis queue (executed by separate worker process).

        This method offloads agent execution to a separate worker process that
        runs outside of uvicorn's context, solving subprocess I/O issues.
        """
        start_time = datetime.now()
        queue = None
        task_id: str | None = None

        try:
            queue = get_agent_queue()
            await queue.connect()
            if await self._check_cancelled():
                return self._cancelled_result(start_time=start_time)

            # Pre-enqueue diagnostics: check worker availability
            try:
                metrics = await queue.get_metrics()
                workers = metrics.get("workers_alive", 0)
                queue_depth = metrics.get("queue_length", 0)
                running = metrics.get("running", 0)
                live_workers = 0
                if self.requires_live_browser:
                    capabilities = await queue.worker_capability_summary()
                    live_workers = int(capabilities.get("live_browser_worker_count") or 0)
                if workers == 0:
                    logger.warning(
                        f"No agent workers alive — task will likely get stuck. "
                        f"queue_depth={queue_depth}, running={running}"
                    )
                    print(
                        "   ⚠️ No agent workers detected — task may wait indefinitely",
                        flush=True,
                    )
                elif self.requires_live_browser and live_workers == 0:
                    logger.warning(
                        "No live-browser-capable agent workers alive — live task will not be claimed. "
                        "workers=%s, queue_depth=%s, running=%s",
                        workers,
                        queue_depth,
                        running,
                    )
                    print(
                        "   ⚠️ No live-browser-capable agent workers detected — check DISPLAY/VNC worker setup",
                        flush=True,
                    )
                elif queue_depth > 0:
                    logger.info(
                        f"Queue status: {workers} worker(s), {queue_depth} queued, {running} running"
                    )
            except Exception as diag_err:
                logger.debug(f"Pre-enqueue diagnostics failed (non-fatal): {diag_err}")

            logger.info(f"Enqueueing task via agent queue (timeout={timeout}s)")
            print("   📤 Enqueueing agent task...", flush=True)

            (
                owner_type,
                owner_id,
                owner_label,
                browser_slot_parent_owner_type,
                browser_slot_parent_run_id,
            ) = self._queue_owner_metadata()

            task_id = await queue.enqueue_task(
                prompt=prompt,
                timeout_seconds=timeout,
                agent_type="AgentRunner",
                operation_type="run",
                cwd=str(self.cwd) if self.cwd else os.getcwd(),
                env_vars=self._collect_api_env_vars(),
                allowed_tools=self.allowed_tools,
                tools=self._effective_tools(),
                disallowed_tools=self.disallowed_tools,
                permission_mode=self._effective_permission_mode(),
                strict_mcp_config=self.strict_mcp_config,
                max_budget_usd=self.max_budget_usd,
                task_budget=self.task_budget,
                include_hook_events=self.include_hook_events,
                include_partial_messages=self.include_partial_messages,
                output_format=self.output_format,
                resume_session_id=self.resume_session_id,
                continue_conversation=self.continue_conversation,
                max_turns=self.max_turns,
                fallback_model=self.fallback_model,
                betas=self.betas,
                owner_type=owner_type,
                owner_id=owner_id,
                owner_label=owner_label,
                browser_slot_parent_owner_type=browser_slot_parent_owner_type,
                browser_slot_parent_run_id=browser_slot_parent_run_id,
                requires_live_browser=self.requires_live_browser,
            )

            logger.info(f"Task enqueued: {task_id}, waiting for result...")
            print(f"   ⏳ Task {task_id} enqueued, waiting for worker...", flush=True)

            # Notify caller of task_id for progress tracking
            if self.on_task_enqueued:
                try:
                    self.on_task_enqueued(task_id)
                except Exception as cb_err:
                    logger.warning(f"on_task_enqueued callback error: {cb_err}")
            if await self._check_cancelled():
                await queue.cancel_task(task_id)
                return self._cancelled_result(start_time=start_time)

            # Progress callback to surface worker activity in logs
            def _on_progress(progress: dict):
                tool_calls = progress.get("tool_calls", 0)
                last_tool = progress.get("last_tool", "")
                interactions = progress.get("interactions", 0)
                short_tool = (
                    last_tool.rsplit("__", 1)[-1] if "__" in last_tool else last_tool
                )
                print(
                    f"   🔄 Worker progress: {tool_calls} tools, {interactions} interactions, last={short_tool}",
                    flush=True,
                )
                self._emit_progress(progress)

            result = await queue.wait_for_result(
                task_id,
                timeout=timeout,
                poll_interval=0.5,
                on_progress=_on_progress,
                is_cancelled=self._check_cancelled if self.is_cancelled else None,
            )
            completed_task = await queue.get_task(task_id)
            telemetry = completed_task.telemetry if completed_task else {}

            duration = (datetime.now() - start_time).total_seconds()
            result_len = len(result) if result else 0
            logger.info(
                f"Task completed via queue: {result_len} chars in {duration:.1f}s"
            )

            # Warn on empty or suspiciously short results
            if not result or not result.strip():
                logger.warning(
                    f"Agent queue returned empty result after {duration:.1f}s — worker may have failed silently"
                )
            elif result_len < 100:
                logger.warning(
                    f"Agent queue returned very short result ({result_len} chars): {result[:100]}"
                )

            print(f"   ✅ Agent completed via queue ({duration:.1f}s)", flush=True)

            output = result or ""
            stripped_output = output.strip()
            has_output = bool(stripped_output)

            # Stricter validation: very short output is suspicious
            is_short = has_output and len(stripped_output) < 50
            has_error_markers = is_short and any(
                marker in stripped_output.lower()
                for marker in ("error", "failed", "exception", "traceback")
            )
            invalid_session_output = classify_agent_error_type(stripped_output) == "invalid_session_resume"

            tool_call_count = int(telemetry.get("tool_calls", 0) or 0)
            tool_names = telemetry.get("tool_names") or []
            if not isinstance(tool_names, list):
                tool_names = []
            tool_call_records = telemetry.get("tool_call_records") or []
            if not isinstance(tool_call_records, list):
                tool_call_records = []
            browser_tool_count = int(telemetry.get("browser_tool_calls", 0) or 0)
            if len(tool_names) < tool_call_count:
                tool_names = [
                    *[str(name) for name in tool_names],
                    *(
                        [str(telemetry.get("last_tool") or "queue_tool_call")]
                        * (tool_call_count - len(tool_names))
                    ),
                ]
            if not tool_names and browser_tool_count > 0:
                tool_names = ["mcp__playwright-test__browser_tool"] * browser_tool_count
            synthetic_tool_calls: list[ToolCall] = []
            if tool_call_records:
                for record in tool_call_records[: tool_call_count or len(tool_call_records)]:
                    if not isinstance(record, dict):
                        continue
                    record_input = record.get("input")
                    synthetic_tool_calls.append(
                        ToolCall(
                            name=str(record.get("name") or "queue_tool_call"),
                            timestamp=start_time,
                            duration_ms=float(record["duration_ms"])
                            if record.get("duration_ms") is not None
                            else None,
                            success=record.get("success") is not False,
                            error=str(record.get("error") or "") or None,
                            input=record_input if isinstance(record_input, dict) else None,
                            result_preview=str(record.get("result_preview") or "")[:1000]
                            or None,
                        )
                    )
            if not synthetic_tool_calls:
                synthetic_tool_calls = [
                    ToolCall(
                        name=str(name),
                        timestamp=start_time,
                        success=True,
                    )
                    for name in tool_names[: tool_call_count or len(tool_names)]
                ]
            messages_received = int(
                telemetry.get("assistant_messages")
                or telemetry.get("stream_events")
                or 1
            )
            text_blocks_received = int(
                telemetry.get("text_blocks") or (1 if has_output else 0)
            )
            api_error_status = telemetry.get("api_error_status")
            if api_error_status is not None:
                try:
                    api_error_status = int(api_error_status)
                except (TypeError, ValueError):
                    api_error_status = None
            hook_events_received = int(telemetry.get("hook_events", 0) or 0)
            error_type = (
                str(telemetry.get("error_type"))
                if telemetry.get("error_type")
                else classify_agent_error_type(output)
            )
            total_cost_usd = telemetry.get("total_cost_usd")
            try:
                total_cost_usd = (
                    float(total_cost_usd) if total_cost_usd is not None else None
                )
            except (TypeError, ValueError):
                total_cost_usd = None
            token_telemetry = {
                key: telemetry[key]
                for key in (
                    "stage",
                    "agent_type",
                    "model",
                    "model_tier",
                    "prompt_hash",
                    "prompt_chars",
                    "estimated_input_tokens",
                    "output_chars",
                    "estimated_output_tokens",
                    "memory_chars",
                    "estimated_memory_tokens",
                    "input_tokens",
                    "output_tokens",
                    "cached_input_tokens",
                    "provider_input_tokens",
                    "provider_output_tokens",
                    "provider_cached_input_tokens",
                    "provider_cache_creation_input_tokens",
                )
                if key in telemetry
            }
            if not token_telemetry:
                token_telemetry = self._build_token_telemetry(prompt=prompt, output=output)

            # Save debug output if session_dir provided
            if self.session_dir:
                self._save_debug_output(output, synthetic_tool_calls, messages_received)

            if has_error_markers or invalid_session_output:
                logger.warning(
                    f"Short output appears to be an error message ({len(stripped_output)} chars): "
                    f"{stripped_output[:100]}"
                )
                return AgentResult(
                    success=False,
                    output=output,
                    error=f"Agent returned error-like output: {stripped_output[:200]}",
                    error_type=error_type or classify_agent_error_type(stripped_output) or "error_like_output",
                    duration_seconds=duration,
                    tool_calls=synthetic_tool_calls,
                    messages_received=messages_received,
                    text_blocks_received=text_blocks_received,
                    api_error_status=api_error_status,
                    stop_reason=(
                        str(telemetry.get("stop_reason"))
                        if telemetry.get("stop_reason")
                        else None
                    ),
                    session_id=(
                        str(telemetry.get("session_id"))
                        if telemetry.get("session_id")
                        else None
                    ),
                    total_cost_usd=total_cost_usd,
                    hook_events_received=hook_events_received,
                    token_telemetry=token_telemetry,
                )

            if is_short:
                logger.warning(
                    f"Agent returned suspiciously short output ({len(stripped_output)} chars): {stripped_output[:100]}"
                )

            return AgentResult(
                success=has_output,
                output=output,
                error=(
                    None
                    if has_output
                    else "Agent queue returned empty result — worker may have failed"
                ),
                error_type=None if has_output else (error_type or "empty_queue_result"),
                duration_seconds=duration,
                tool_calls=synthetic_tool_calls,
                messages_received=messages_received,
                text_blocks_received=text_blocks_received,
                api_error_status=api_error_status,
                stop_reason=(
                    str(telemetry.get("stop_reason"))
                    if telemetry.get("stop_reason")
                    else None
                ),
                session_id=(
                    str(telemetry.get("session_id"))
                    if telemetry.get("session_id")
                    else None
                ),
                total_cost_usd=total_cost_usd,
                hook_events_received=hook_events_received,
                token_telemetry=token_telemetry,
            )

        except asyncio.TimeoutError:
            duration = (datetime.now() - start_time).total_seconds()
            error_msg = f"Agent timed out after {timeout} seconds (queue mode)"
            logger.warning(error_msg)
            print(f"⚠️ {error_msg}", flush=True)

            return AgentResult(
                success=False,
                output="",
                error=error_msg,
                error_type="timeout",
                duration_seconds=duration,
                timed_out=True,
            )

        except RuntimeError as e:
            duration = (datetime.now() - start_time).total_seconds()
            error_msg = str(e)
            if "cancelled" in error_msg.lower() or "canceled" in error_msg.lower():
                return AgentResult(
                    success=False,
                    output="",
                    error=error_msg,
                    error_type="cancelled",
                    duration_seconds=duration,
                    cancelled=True,
                )
            telemetry: dict[str, Any] = {}
            if queue is not None and task_id:
                try:
                    completed_task = await queue.get_task(task_id)
                    telemetry = completed_task.telemetry if completed_task else {}
                except Exception as exc:
                    logger.debug("Could not load failed queue task telemetry: %s", exc)
            api_error_status = telemetry.get("api_error_status") or parse_api_error_status(error_msg)
            if api_error_status is not None:
                try:
                    api_error_status = int(api_error_status)
                except (TypeError, ValueError):
                    api_error_status = None
            error_type = (
                str(telemetry.get("error_type"))
                if telemetry.get("error_type")
                else (
                    classify_agent_error_type(error_msg)
                    or (
                        "provider_overloaded"
                        if is_transient_provider_error(error_msg)
                        else "queue_runtime_error"
                    )
                )
            )
            tool_call_records = telemetry.get("tool_call_records") or []
            if not isinstance(tool_call_records, list):
                tool_call_records = []
            synthetic_tool_calls = [
                ToolCall(
                    name=str(record.get("name") or "queue_tool_call"),
                    timestamp=start_time,
                    duration_ms=float(record["duration_ms"])
                    if record.get("duration_ms") is not None
                    else None,
                    success=record.get("success") is not False,
                    error=str(record.get("error") or "") or None,
                    input=record.get("input") if isinstance(record.get("input"), dict) else None,
                    result_preview=str(record.get("result_preview") or "")[:1000]
                    or None,
                )
                for record in tool_call_records
                if isinstance(record, dict)
            ]

            # Classify the error for clearer user feedback
            if (
                "stuck in QUEUED" in error_msg
                or "no agent workers" in error_msg.lower()
            ):
                logger.error(f"Agent task not picked up: {error_msg}")
                print(f"❌ No worker picked up the task: {error_msg}", flush=True)
            elif "heartbeat lost" in error_msg.lower():
                logger.error(f"Agent worker crashed: {error_msg}")
                print(f"❌ Agent worker crashed mid-execution: {error_msg}", flush=True)
            elif "rate limit" in error_msg.lower() or "429" in error_msg:
                logger.error(f"Agent rate limited: {error_msg}")
                print(f"❌ Rate limited: {error_msg}", flush=True)
            else:
                logger.error(f"Agent failed via queue: {error_msg}")
                print(f"❌ Agent failed: {error_msg}", flush=True)

            return AgentResult(
                success=False,
                output="",
                error=error_msg,
                error_type=error_type,
                duration_seconds=duration,
                tool_calls=synthetic_tool_calls,
                messages_received=int(telemetry.get("assistant_messages") or telemetry.get("stream_events") or 0),
                text_blocks_received=int(telemetry.get("text_blocks") or 0),
                api_error_status=api_error_status,
                stop_reason=(
                    str(telemetry.get("stop_reason"))
                    if telemetry.get("stop_reason")
                    else None
                ),
                session_id=(
                    str(telemetry.get("session_id"))
                    if telemetry.get("session_id")
                    else None
                ),
            )

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"Unexpected queue error: {e}", exc_info=True)
            print(f"❌ Queue error: {e}", flush=True)

            return AgentResult(
                success=False,
                output="",
                error=str(e),
                error_type=classify_agent_error_type(e) or type(e).__name__,
                duration_seconds=duration,
            )

    def _save_debug_output(
        self,
        output: str,
        tool_calls: list[ToolCall],
        messages_received: int,
    ):
        """Save debug information to session directory."""
        if not self.session_dir:
            return

        try:
            self.session_dir.mkdir(parents=True, exist_ok=True)

            # Save raw output
            (self.session_dir / "raw_output.txt").write_text(output)

            # Save tool call log
            import json

            tool_log = [
                {
                    "name": tc.name,
                    "timestamp": tc.timestamp.isoformat(),
                    "duration_ms": tc.duration_ms,
                    "success": tc.success,
                    "error": tc.error,
                    "result_preview": tc.result_preview,
                    **build_safe_tool_input_metadata(tc.input),
                }
                for tc in tool_calls
            ]
            (self.session_dir / "tool_calls.json").write_text(
                json.dumps(tool_log, indent=2)
            )

            # Save summary
            summary = {
                "messages_received": messages_received,
                "tool_calls": len(tool_calls),
                "output_length": len(output),
            }
            (self.session_dir / "agent_summary.json").write_text(
                json.dumps(summary, indent=2)
            )

        except Exception as e:
            logger.warning(f"Failed to save debug output: {e}")


async def run_agent_with_logging(
    prompt: str,
    timeout_seconds: int = 1800,
    allowed_tools: list[str] | None = None,
    on_tool_use: Callable[[str, dict], None] | None = None,
    session_dir: Path | None = None,
    model_tier: str | None = None,
) -> AgentResult:
    """
    Convenience function to run an agent with logging.

    This is a simpler interface when you don't need to reuse the runner.

    Args:
        prompt: The prompt to send to the agent
        timeout_seconds: Maximum time to wait (default 30 min)
        allowed_tools: List of allowed tool patterns (default ["*"])
        on_tool_use: Optional callback when a tool is used
        session_dir: Optional directory to save debug output
        model_tier: Optional routing tier from runtime AI settings

    Returns:
        AgentResult with success status, output, and diagnostics
    """
    runner = AgentRunner(
        timeout_seconds=timeout_seconds,
        allowed_tools=allowed_tools,
        on_tool_use=on_tool_use,
        session_dir=session_dir,
        model_tier=model_tier,
    )
    return await runner.run(prompt)


def get_default_timeout() -> int:
    """Get the default agent timeout from environment or use 1800 seconds (30 min)."""
    return int(os.environ.get("AGENT_TIMEOUT_SECONDS", "1800"))
