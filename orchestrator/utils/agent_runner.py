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


def get_mcp_tool_prefix() -> str:
    """Detect MCP server name from .mcp.json to build tool names.

    The MCP server name varies by context:
    - Dashboard/Docker: server named "playwright-test" -> tools prefixed mcp__playwright-test__
    - CLI direct: server named "playwright" -> tools prefixed mcp__playwright__
    """
    import json as _json

    mcp_path = Path(".mcp.json")
    if mcp_path.exists():
        try:
            config = _json.loads(mcp_path.read_text())
            for name in config.get("mcpServers", {}):
                if "playwright" in name:
                    return f"mcp__{name}__"
        except Exception as e:
            logger.debug(f"MCP config read failed, using default prefix: {e}")
    return "mcp__playwright-test__"  # default (dashboard/production)


def build_allowed_tools(base_tools: list, mcp_tools: list) -> list:
    """Build allowed_tools list with correct MCP prefix.

    Args:
        base_tools: Non-MCP tool names (e.g. ["Glob", "Grep", "Read", "LS"])
        mcp_tools: MCP tool suffixes (e.g. ["browser_click", "browser_snapshot"])

    Returns:
        Combined list with MCP tools properly prefixed.
    """
    prefix = get_mcp_tool_prefix()
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
        log_tools: bool = True,
        on_tool_use: Callable[[str, dict], None] | None = None,
        session_dir: Path | None = None,
        on_task_enqueued: Callable[[str], None] | None = None,
    ):
        """
        Initialize the agent runner.

        Args:
            timeout_seconds: Maximum time to wait for agent completion (default 30 min)
            allowed_tools: List of allowed tool patterns (default ["*"])
            log_tools: Whether to log tool invocations to console
            on_tool_use: Optional callback when a tool is used
            session_dir: Optional directory to save debug output
            on_task_enqueued: Optional callback fired with task_id when queued (for progress tracking)
        """
        self.timeout_seconds = timeout_seconds
        self.allowed_tools = allowed_tools or ["*"]
        self.log_tools = log_tools
        self.on_tool_use = on_tool_use
        self.session_dir = session_dir
        self.on_task_enqueued = on_task_enqueued

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
        current_tool_start: datetime | None = None
        current_tool_name: str | None = None

        # Snapshot child PIDs before query for orphan cleanup
        pre_query_pids = snapshot_child_pids()
        agent_result: AgentResult | None = None

        try:
            # Wrap the query in a timeout
            async def _run_query():
                nonlocal messages_received, text_blocks_received, result_parts
                nonlocal tool_calls, current_tool_start, current_tool_name

                async for message in query(
                    prompt=prompt,
                    options=ClaudeAgentOptions(
                        allowed_tools=self.allowed_tools,
                        setting_sources=["project"],
                        permission_mode="bypassPermissions",
                    ),
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
            "ANTHROPIC_BASE_URL",
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
                cwd=os.getcwd(),
                env_vars=self._collect_api_env_vars(),
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

            result = await queue.wait_for_result(
                task_id,
                timeout=timeout,
                poll_interval=0.5,
                on_progress=_on_progress,
            )

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

            # Save debug output if session_dir provided
            if self.session_dir:
                self._save_debug_output(result, [], 1)

            output = result or ""
            stripped_output = output.strip()
            has_output = bool(stripped_output)

            # Stricter validation: very short output is suspicious
            is_short = has_output and len(stripped_output) < 50
            has_error_markers = is_short and any(
                marker in stripped_output.lower() for marker in ("error", "failed", "exception", "traceback")
            )

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
                    tool_calls=[],
                    messages_received=1,
                    text_blocks_received=1,
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
                tool_calls=[],  # Tool calls not tracked in queue mode
                messages_received=1,
                text_blocks_received=1 if has_output else 0,
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
