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
import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

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
        parse_retry_after,
    )
except ImportError:
    try:
        from services.api_key_rotator import (
            get_api_key_rotator,
            is_rate_limit_error,
            parse_retry_after,
        )
    except ImportError:
        get_api_key_rotator = None

        def is_rate_limit_error(text):
            return False

        def parse_retry_after(text):
            return None


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
    from orchestrator.utils.browser_cleanup import kill_new_children, snapshot_child_pids
except ImportError:
    try:
        from utils.browser_cleanup import kill_new_children, snapshot_child_pids
    except ImportError:
        # Fallback no-ops if cleanup module unavailable
        def snapshot_child_pids() -> set:
            return set()

        def kill_new_children(before_pids: set, grace_seconds: float = 2.0) -> int:
            return 0


def get_mcp_tool_prefix(server_hint: str = "playwright") -> str:
    """Detect MCP server name from .mcp.json to build tool names.

    The MCP server name varies by context:
    - Dashboard/Docker: server named "playwright-test" -> tools prefixed mcp__playwright-test__
    - CLI direct: server named "playwright" -> tools prefixed mcp__playwright__
    - Mobile: server named "appium-mcp" -> tools prefixed mcp__appium-mcp__
    """
    import json as _json

    mcp_path = Path(".mcp.json")
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


def build_allowed_tools(base_tools: list, mcp_tools: list) -> list:
    """Build allowed_tools list with correct MCP prefix.

    Args:
        base_tools: Non-MCP tool names (e.g. ["Glob", "Grep", "Read", "LS"])
        mcp_tools: MCP tool suffixes (e.g. ["browser_click", "browser_snapshot"])

    Returns:
        Combined list with MCP tools properly prefixed.
    """
    prefix = get_mcp_tool_prefix("playwright")
    return base_tools + [f"{prefix}{t}" for t in mcp_tools]


def build_mcp_allowed_tools(server_hint: str, base_tools: list, mcp_tools: list) -> list:
    """Build allowed_tools for a named MCP server family."""
    prefix = get_mcp_tool_prefix(server_hint)
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


@dataclass
class AgentResult:
    """Result of an agent execution."""

    success: bool
    output: str = ""
    error: str | None = None
    duration_seconds: float = 0.0
    tool_calls: list[ToolCall] = field(default_factory=list)
    messages_received: int = 0
    text_blocks_received: int = 0
    timed_out: bool = False
    api_error_status: int | None = None
    stop_reason: str | None = None
    session_id: str | None = None
    total_cost_usd: float | None = None
    hook_events_received: int = 0


class AgentRunner:
    """
    Unified runner for Claude agents with comprehensive logging and timeout support.

    Usage:
        runner = AgentRunner(timeout_seconds=1800, log_tools=True)
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
        log_tools: bool = True,
        on_tool_use: Callable[[str, dict], None] | None = None,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        session_dir: Path | None = None,
        on_task_enqueued: Callable[[str], None] | None = None,
        cwd: Path | str | None = None,
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
            log_tools: Whether to log tool invocations to console
            on_tool_use: Optional callback when a tool is used
            on_progress: Optional callback receiving live progress snapshots
            session_dir: Optional directory to save debug output
            on_task_enqueued: Optional callback fired with task_id when queued (for progress tracking)
            cwd: Optional working directory for MCP config discovery and queued execution
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
        self.log_tools = log_tools
        self.on_tool_use = on_tool_use
        self.on_progress = on_progress
        self.session_dir = session_dir
        self.on_task_enqueued = on_task_enqueued
        self.cwd = Path(cwd) if cwd else None

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

    def _requested_mcp_tools(self) -> list[str]:
        requested: list[str] = []
        for source in (self.allowed_tools, self._effective_tools()):
            if isinstance(source, list):
                requested.extend(str(tool) for tool in source if str(tool).startswith("mcp__"))
        return requested

    def _emit_progress(self, progress: dict[str, Any]) -> None:
        if not self.on_progress:
            return
        try:
            self.on_progress(progress)
        except Exception as exc:
            logger.debug(f"Agent progress callback failed: {exc}")

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
        if self.include_hook_events:
            kwargs["include_hook_events"] = True

        if self._should_attach_mcp_config(self.cwd):
            kwargs["mcp_servers"] = (self.cwd or Path.cwd()) / ".mcp.json"
            kwargs["strict_mcp_config"] = self.strict_mcp_config

        return kwargs

    @staticmethod
    def _apply_active_ai_settings() -> None:
        """Apply the runtime AI settings before invoking the SDK.

        The Settings UI persists the selected provider/model/key into .env and
        applies it to the API process. Long-running workflows and queued workers
        may start after that process state changes, so refresh the env aliases
        here before every agent call.
        """
        try:
            from orchestrator.api import settings as settings_api

            env_vars = settings_api._read_env_file()
            settings_api._apply_runtime_settings(env_vars)
        except Exception as exc:
            logger.debug(f"Unable to refresh active AI settings for agent runner: {exc}")

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
            raise RuntimeError(f"MCP config at {mcp_path} does not define any mcpServers")

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
                raise RuntimeError(f"MCP server '{server_name}' in {mcp_path} has no command")
            if os.path.isabs(command) and not Path(command).exists():
                raise RuntimeError(
                    f"MCP server '{server_name}' command does not exist: {command}. "
                    "Install dependencies or set PLAYWRIGHT_MCP_COMMAND."
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
        timeout = timeout_override or self.timeout_seconds
        start_time = datetime.now()
        self._apply_active_ai_settings()
        self._validate_mcp_config_for_allowed_tools(self.cwd)

        # First, try agent queue if Redis is available
        # This offloads execution to a separate worker process outside uvicorn
        if AGENT_QUEUE_AVAILABLE and should_use_agent_queue():
            logger.info(f"Using agent queue for execution (timeout={timeout}s)")
            return await self._run_via_queue(prompt, timeout)

        if query is None:
            return AgentResult(
                success=False,
                error="claude_agent_sdk not available",
            )
        result_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        messages_received = 0
        text_blocks_received = 0
        hook_events_received = 0
        api_error_status: int | None = None
        stop_reason: str | None = None
        session_id: str | None = None
        total_cost_usd: float | None = None
        current_tool_start: datetime | None = None
        current_tool_name: str | None = None
        current_tool_input: dict[str, Any] | None = None

        # Snapshot child PIDs before query for orphan cleanup
        pre_query_pids = snapshot_child_pids()
        agent_result: AgentResult | None = None

        try:
            # Wrap the query in a timeout
            async def _run_query():
                nonlocal messages_received, text_blocks_received, result_parts
                nonlocal tool_calls, current_tool_start, current_tool_name, current_tool_input
                nonlocal hook_events_received, api_error_status, stop_reason, session_id, total_cost_usd

                async for message in query(
                    prompt=prompt,
                    options=ClaudeAgentOptions(**self._claude_options_kwargs()),
                ):
                    messages_received += 1

                    # Log message type for debugging
                    msg_type = getattr(message, "type", "unknown")
                    logger.debug(
                        f"Message #{messages_received}: type={msg_type}, "
                        f"has_result={hasattr(message, 'result')}, "
                        f"has_content={hasattr(message, 'content')}"
                    )

                    # Print periodic progress for long-running agents
                    if messages_received == 1:
                        print("   📨 First message received (agent is responding)", flush=True)
                    elif messages_received % 50 == 0:
                        elapsed = (datetime.now() - start_time).total_seconds()
                        print(f"   📨 {messages_received} messages ({elapsed:.0f}s elapsed)", flush=True)

                    # Handle tool use
                    if hasattr(message, "type"):
                        if message.type == "hook_event":
                            hook_events_received += 1

                        if message.type == "tool_use":
                            tool_name = getattr(message, "name", "unknown")
                            current_tool_name = tool_name
                            current_tool_start = datetime.now()
                            current_tool_input = getattr(message, "input", None)

                            # Log tool use
                            if self.log_tools:
                                if tool_name.startswith("mcp__playwright"):
                                    action = tool_name.split("__")[-1] if "__" in tool_name else tool_name
                                    print(f"   🔧 {action}...", flush=True)
                                else:
                                    print(f"   🔧 {tool_name}...", flush=True)

                            # Callback
                            if self.on_tool_use:
                                tool_input = getattr(message, "input", {})
                                self.on_tool_use(tool_name, tool_input)
                            self._emit_progress(
                                {
                                    "phase": "tool_use",
                                    "tool_calls": len(tool_calls) + 1,
                                    "browser_tool_calls": len([tc for tc in tool_calls if tc.name.startswith("mcp__playwright")])
                                    + (1 if str(tool_name).startswith("mcp__playwright") else 0),
                                    "interactions": len(tool_calls) + 1,
                                    "last_tool": tool_name,
                                    "updated_at": datetime.utcnow().isoformat(),
                                }
                            )

                        elif message.type == "tool_result":
                            # Record completed tool call
                            if current_tool_name and current_tool_start:
                                duration = (datetime.now() - current_tool_start).total_seconds() * 1000
                                is_error = getattr(message, "is_error", False)
                                tool_calls.append(
                                    ToolCall(
                                        name=current_tool_name,
                                        timestamp=current_tool_start,
                                        duration_ms=duration,
                                        success=not is_error,
                                        error=str(getattr(message, "content", ""))[:200] if is_error else None,
                                        input=current_tool_input,
                                    )
                                )
                                self._emit_progress(
                                    {
                                        "phase": "tool_result",
                                        "tool_calls": len(tool_calls),
                                        "browser_tool_calls": len(
                                            [tc for tc in tool_calls if tc.name.startswith("mcp__playwright")]
                                        ),
                                        "interactions": len(tool_calls),
                                        "last_tool": current_tool_name,
                                        "updated_at": datetime.utcnow().isoformat(),
                                    }
                                )
                            current_tool_name = None
                            current_tool_start = None
                            current_tool_input = None

                        elif message.type == "text":
                            text_content = getattr(message, "text", "")
                            if text_content:
                                result_parts.append(text_content)
                                text_blocks_received += 1
                                if text_blocks_received == 1:
                                    logger.info(f"Agent: first text output received at msg #{messages_received}")

                    # Capture content blocks
                    if hasattr(message, "content"):
                        content = message.content
                        if isinstance(content, list):
                            for block in content:
                                if hasattr(block, "text"):
                                    result_parts.append(block.text)
                                    text_blocks_received += 1
                        elif isinstance(content, str):
                            result_parts.append(content)
                            text_blocks_received += 1

                    # Capture the final result
                    if hasattr(message, "result"):
                        result_parts.append(message.result)

                    message_api_error_status = getattr(message, "api_error_status", None)
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

                    # Periodic progress logging
                    if messages_received > 0 and messages_received % 25 == 0:
                        total_chars = sum(len(p) for p in result_parts)
                        logger.info(
                            f"Agent progress: {messages_received} msgs, {text_blocks_received} text, "
                            f"{len(tool_calls)} tools, {total_chars} chars"
                        )

            # Run with timeout, retrying with key rotation on 429
            rotator = get_api_key_rotator() if get_api_key_rotator else None
            max_rotation_attempts = rotator.key_count if rotator and rotator.key_count > 1 else 0
            slot = None

            for _rotation_attempt in range(max_rotation_attempts + 1):
                if rotator and rotator.key_count > 0:
                    slot = rotator.get_active_key()
                    if slot:
                        rotator.activate_key(slot)

                try:
                    await asyncio.wait_for(_run_query(), timeout=timeout)

                    # Report success
                    if rotator and rotator.key_count > 0:
                        rotator.get_active_key()
                        # We already advanced round-robin, report on the slot we used
                        if slot:
                            rotator.report_success(slot)

                    break  # Success — exit rotation loop
                except Exception as rotation_exc:
                    error_text = str(rotation_exc)
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
                        continue
                    raise  # Non-429 error or no more keys — propagate

            # Calculate duration
            duration = (datetime.now() - start_time).total_seconds()
            output = "\n".join(result_parts)

            # Save debug output if session_dir provided
            if self.session_dir:
                self._save_debug_output(output, tool_calls, messages_received)

            logger.info(f"Agent completed: {messages_received} messages, {len(tool_calls)} tool calls, {duration:.1f}s")

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
            )

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            error_str = str(e).lower()

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
                    error=None if has_output else "Agent completed via cancel scope but produced no text output",
                    duration_seconds=duration,
                    tool_calls=tool_calls,
                    messages_received=messages_received,
                    text_blocks_received=text_blocks_received,
                    api_error_status=api_error_status,
                    stop_reason=stop_reason,
                    session_id=session_id,
                    total_cost_usd=total_cost_usd,
                    hook_events_received=hook_events_received,
                )
            else:
                # Actual error
                logger.error(f"Agent error: {e}")
                print(f"❌ Agent error: {e}", flush=True)

                agent_result = AgentResult(
                    success=False,
                    output="\n".join(result_parts),
                    error=str(e),
                    duration_seconds=duration,
                    tool_calls=tool_calls,
                    messages_received=messages_received,
                    text_blocks_received=text_blocks_received,
                    api_error_status=api_error_status,
                    stop_reason=stop_reason,
                    session_id=session_id,
                    total_cost_usd=total_cost_usd,
                    hook_events_received=hook_events_received,
                )

        finally:
            # Always clean up orphaned browser/MCP processes after query
            try:
                killed = kill_new_children(pre_query_pids, grace_seconds=2.0)
                if killed > 0:
                    logger.info(f"Cleaned up {killed} orphaned browser/MCP process(es)")
            except Exception:
                pass  # Non-fatal - don't let cleanup errors mask real results

        return agent_result

    @staticmethod
    def _collect_api_env_vars() -> dict:
        """Collect API-related env vars to pass through the queue to the worker.

        The pipeline loads credentials from the database into os.environ,
        but the worker runs in a separate process and only reads .env.
        This bridges the gap by forwarding current env vars with the task.
        """
        keys = [
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_AUTH_TOKENS",
            "ANTHROPIC_API_KEY",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
        ]
        env_vars = {}
        for key in keys:
            val = os.environ.get(key)
            if val:
                env_vars[key] = val
        return env_vars if env_vars else None

    async def _run_via_queue(self, prompt: str, timeout: int) -> AgentResult:
        """
        Run agent via Redis queue (executed by separate worker process).

        This method offloads agent execution to a separate worker process that
        runs outside of uvicorn's context, solving subprocess I/O issues.
        """
        start_time = datetime.now()

        try:
            queue = get_agent_queue()
            await queue.connect()

            # Pre-enqueue diagnostics: check worker availability
            try:
                metrics = await queue.get_metrics()
                workers = metrics.get("workers_alive", 0)
                queue_depth = metrics.get("queue_length", 0)
                running = metrics.get("running", 0)
                if workers == 0:
                    logger.warning(
                        f"No agent workers alive — task will likely get stuck. "
                        f"queue_depth={queue_depth}, running={running}"
                    )
                    print("   ⚠️ No agent workers detected — task may wait indefinitely", flush=True)
                elif queue_depth > 0:
                    logger.info(f"Queue status: {workers} worker(s), {queue_depth} queued, {running} running")
            except Exception as diag_err:
                logger.debug(f"Pre-enqueue diagnostics failed (non-fatal): {diag_err}")

            logger.info(f"Enqueueing task via agent queue (timeout={timeout}s)")
            print("   📤 Enqueueing agent task...", flush=True)

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
            )

            logger.info(f"Task enqueued: {task_id}, waiting for result...")
            print(f"   ⏳ Task {task_id} enqueued, waiting for worker...", flush=True)

            # Notify caller of task_id for progress tracking
            if self.on_task_enqueued:
                try:
                    self.on_task_enqueued(task_id)
                except Exception as cb_err:
                    logger.warning(f"on_task_enqueued callback error: {cb_err}")

            # Progress callback to surface worker activity in logs
            def _on_progress(progress: dict):
                tool_calls = progress.get("tool_calls", 0)
                last_tool = progress.get("last_tool", "")
                interactions = progress.get("interactions", 0)
                short_tool = last_tool.rsplit("__", 1)[-1] if "__" in last_tool else last_tool
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
            )
            completed_task = await queue.get_task(task_id)
            telemetry = completed_task.telemetry if completed_task else {}

            duration = (datetime.now() - start_time).total_seconds()
            result_len = len(result) if result else 0
            logger.info(f"Task completed via queue: {result_len} chars in {duration:.1f}s")

            # Warn on empty or suspiciously short results
            if not result or not result.strip():
                logger.warning(
                    f"Agent queue returned empty result after {duration:.1f}s — worker may have failed silently"
                )
            elif result_len < 100:
                logger.warning(f"Agent queue returned very short result ({result_len} chars): {result[:100]}")

            print(f"   ✅ Agent completed via queue ({duration:.1f}s)", flush=True)

            output = result or ""
            stripped_output = output.strip()
            has_output = bool(stripped_output)

            # Stricter validation: very short output is suspicious
            is_short = has_output and len(stripped_output) < 50
            has_error_markers = is_short and any(
                marker in stripped_output.lower() for marker in ("error", "failed", "exception", "traceback")
            )

            tool_call_count = int(telemetry.get("tool_calls", 0) or 0)
            tool_names = telemetry.get("tool_names") or []
            if not isinstance(tool_names, list):
                tool_names = []
            browser_tool_count = int(telemetry.get("browser_tool_calls", 0) or 0)
            if len(tool_names) < tool_call_count:
                tool_names = [
                    *[str(name) for name in tool_names],
                    *([str(telemetry.get("last_tool") or "queue_tool_call")] * (tool_call_count - len(tool_names))),
                ]
            if not tool_names and browser_tool_count > 0:
                tool_names = ["mcp__playwright-test__browser_tool"] * browser_tool_count
            synthetic_tool_calls = [
                ToolCall(
                    name=str(name),
                    timestamp=start_time,
                    success=True,
                )
                for name in tool_names[:tool_call_count or len(tool_names)]
            ]
            messages_received = int(
                telemetry.get("assistant_messages")
                or telemetry.get("stream_events")
                or 1
            )
            text_blocks_received = int(telemetry.get("text_blocks") or (1 if has_output else 0))
            api_error_status = telemetry.get("api_error_status")
            if api_error_status is not None:
                try:
                    api_error_status = int(api_error_status)
                except (TypeError, ValueError):
                    api_error_status = None
            hook_events_received = int(telemetry.get("hook_events", 0) or 0)
            total_cost_usd = telemetry.get("total_cost_usd")
            try:
                total_cost_usd = float(total_cost_usd) if total_cost_usd is not None else None
            except (TypeError, ValueError):
                total_cost_usd = None

            # Save debug output if session_dir provided
            if self.session_dir:
                self._save_debug_output(output, synthetic_tool_calls, messages_received)

            if has_error_markers:
                logger.warning(
                    f"Short output appears to be an error message ({len(stripped_output)} chars): "
                    f"{stripped_output[:100]}"
                )
                return AgentResult(
                    success=False,
                    output=output,
                    error=f"Agent returned error-like output: {stripped_output[:200]}",
                    duration_seconds=duration,
                    tool_calls=synthetic_tool_calls,
                    messages_received=messages_received,
                    text_blocks_received=text_blocks_received,
                    api_error_status=api_error_status,
                    stop_reason=str(telemetry.get("stop_reason")) if telemetry.get("stop_reason") else None,
                    session_id=str(telemetry.get("session_id")) if telemetry.get("session_id") else None,
                    total_cost_usd=total_cost_usd,
                    hook_events_received=hook_events_received,
                )

            if is_short:
                logger.warning(
                    f"Agent returned suspiciously short output ({len(stripped_output)} chars): {stripped_output[:100]}"
                )

            return AgentResult(
                success=has_output,
                output=output,
                error=None if has_output else "Agent queue returned empty result — worker may have failed",
                duration_seconds=duration,
                tool_calls=synthetic_tool_calls,
                messages_received=messages_received,
                text_blocks_received=text_blocks_received,
                api_error_status=api_error_status,
                stop_reason=str(telemetry.get("stop_reason")) if telemetry.get("stop_reason") else None,
                session_id=str(telemetry.get("session_id")) if telemetry.get("session_id") else None,
                total_cost_usd=total_cost_usd,
                hook_events_received=hook_events_received,
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
                duration_seconds=duration,
                timed_out=True,
            )

        except RuntimeError as e:
            duration = (datetime.now() - start_time).total_seconds()
            error_msg = str(e)

            # Classify the error for clearer user feedback
            if "stuck in QUEUED" in error_msg or "no agent workers" in error_msg.lower():
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
                duration_seconds=duration,
            )

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"Unexpected queue error: {e}", exc_info=True)
            print(f"❌ Queue error: {e}", flush=True)

            return AgentResult(
                success=False,
                output="",
                error=str(e),
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
                }
                for tc in tool_calls
            ]
            (self.session_dir / "tool_calls.json").write_text(json.dumps(tool_log, indent=2))

            # Save summary
            summary = {
                "messages_received": messages_received,
                "tool_calls": len(tool_calls),
                "output_length": len(output),
            }
            (self.session_dir / "agent_summary.json").write_text(json.dumps(summary, indent=2))

        except Exception as e:
            logger.warning(f"Failed to save debug output: {e}")


async def run_agent_with_logging(
    prompt: str,
    timeout_seconds: int = 1800,
    allowed_tools: list[str] | None = None,
    on_tool_use: Callable[[str, dict], None] | None = None,
    session_dir: Path | None = None,
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

    Returns:
        AgentResult with success status, output, and diagnostics
    """
    runner = AgentRunner(
        timeout_seconds=timeout_seconds,
        allowed_tools=allowed_tools,
        on_tool_use=on_tool_use,
        session_dir=session_dir,
    )
    return await runner.run(prompt)


def get_default_timeout() -> int:
    """Get the default agent timeout from environment or use 1800 seconds (30 min)."""
    return int(os.environ.get("AGENT_TIMEOUT_SECONDS", "1800"))
