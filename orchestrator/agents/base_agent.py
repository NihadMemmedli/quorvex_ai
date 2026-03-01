import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to sys.path for imports
project_root = Path(__file__).parent.parent
project_root_str = str(project_root.resolve())
if project_root_str not in sys.path:
    sys.path.insert(0, project_root_str)

# Configure logging to show in Docker logs
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.info(f"base_agent.py: project_root={project_root_str}")
logger.info(f"base_agent.py: utils exists={(project_root / 'utils' / 'json_utils.py').exists()}")

from claude_agent_sdk import ClaudeAgentOptions, query

from load_env import setup_claude_env

# Import API key rotator for multi-key failover
try:
    from services.api_key_rotator import get_api_key_rotator
except ImportError:
    get_api_key_rotator = None

# Path to bundled Claude CLI
CLAUDE_CLI_PATH = "/usr/local/lib/python3.10/dist-packages/claude_agent_sdk/_bundled/claude"

# Import agent queue for Redis-based execution
try:
    from services.agent_queue import get_agent_queue, should_use_agent_queue

    AGENT_QUEUE_AVAILABLE = True
except ImportError:
    AGENT_QUEUE_AVAILABLE = False

    def should_use_agent_queue():
        return False


def _run_cli_with_pty(cmd_list, env_dict, work_dir, timeout_secs, result_queue):
    """Worker function to run CLI subprocess with PTY in a separate process.

    This function runs in a separate process via multiprocessing to isolate
    from uvicorn's event loop context which interferes with subprocess I/O.
    """
    import os as o
    import pty
    import select
    import subprocess
    import time as t

    # Debug: Log worker environment
    print(f"[WORKER] PID={o.getpid()}, CWD={work_dir}", flush=True)
    print(f"[WORKER] DISPLAY={env_dict.get('DISPLAY', 'not set')}", flush=True)
    print(f"[WORKER] cmd[0]={cmd_list[0]}", flush=True)
    print(f"[WORKER] timeout={timeout_secs}s", flush=True)

    actual_timeout = timeout_secs if timeout_secs else 3600
    start_time = t.time()
    output_chunks = []
    exit_code = -1
    error_msg = None

    try:
        # Create a pseudo-terminal
        master_fd, slave_fd = pty.openpty()
        print(f"[WORKER] PTY created: master={master_fd}, slave={slave_fd}", flush=True)

        proc = subprocess.Popen(
            cmd_list,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env_dict,
            cwd=work_dir,
            close_fds=True,
        )
        print(f"[WORKER] Process started, PID={proc.pid}", flush=True)

        # Close slave fd in parent
        o.close(slave_fd)

        # Read output from master fd
        read_count = 0
        while True:
            elapsed = t.time() - start_time
            if elapsed > actual_timeout:
                proc.kill()
                proc.wait()
                error_msg = f"timeout after {elapsed:.1f}s"
                break

            # Check if process exited
            poll_result = proc.poll()
            if poll_result is not None:
                # Read any remaining output
                while True:
                    readable, _, _ = select.select([master_fd], [], [], 0.1)
                    if not readable:
                        break
                    try:
                        chunk = o.read(master_fd, 4096)
                        if not chunk:
                            break
                        output_chunks.append(chunk.decode("utf-8", errors="replace"))
                    except OSError:
                        break
                exit_code = poll_result
                print(
                    f"[WORKER] Process exited with code {exit_code}, total output={sum(len(c) for c in output_chunks)} chars",
                    flush=True,
                )
                break

            # Read available output
            readable, _, _ = select.select([master_fd], [], [], 1.0)
            if readable:
                try:
                    chunk = o.read(master_fd, 4096)
                    if chunk:
                        output_chunks.append(chunk.decode("utf-8", errors="replace"))
                        read_count += 1
                        if read_count <= 5:
                            print(f"[WORKER] Read chunk #{read_count}: {len(chunk)} bytes", flush=True)
                except OSError as e:
                    print(f"[WORKER] Read OSError: {e}", flush=True)
                    break

        o.close(master_fd)

    except Exception as e:
        error_msg = str(e)

    # Put result in queue with diagnostics
    diag = f"PID={o.getpid()}, CWD={work_dir}, CLI_exists={o.path.exists(cmd_list[0]) if cmd_list else False}"
    result_queue.put(
        {"stdout": "".join(output_chunks), "stderr": "", "returncode": exit_code, "error": error_msg, "diag": diag}
    )


class _QueryAccumulator:
    """Helper class to accumulate streaming content across task boundaries."""

    def __init__(self):
        self.content = ""

    def add_content(self, content):
        # Handle both string and list content from SDK
        if isinstance(content, list):
            self.content += "".join(str(c) for c in content)
        else:
            self.content += str(content)

    def get_content(self) -> str:
        return self.content


class BaseAgent:
    """Base class for autonomous agents"""

    def __init__(self):
        # Allow agents to use project settings
        setup_claude_env()
        # Optional callback fired after task is enqueued via Redis queue
        self.on_task_enqueued = None

    async def _query_agent_direct(self, prompt: str, system_prompt: str = None, timeout_seconds: int = None) -> Any:
        """Query the agent using subprocess.run in a thread pool executor.

        This method uses subprocess.run (blocking) inside run_in_executor to avoid
        issues with asyncio subprocess in FastAPI's event loop.
        """
        import concurrent.futures
        import time

        cwd = os.getcwd()
        mcp_path = Path(cwd) / ".mcp.json"

        logger.info("[DIRECT CLI] Starting direct CLI invocation (thread pool)")
        logger.info(f"[DIRECT CLI]   Working directory: {cwd}")
        logger.info(f"[DIRECT CLI]   DISPLAY: {os.environ.get('DISPLAY', 'not set')}")
        logger.info(f"[DIRECT CLI]   CLI path: {CLAUDE_CLI_PATH}")
        logger.info(f"[DIRECT CLI]   MCP config exists: {mcp_path.exists()}")

        full_prompt = prompt
        if system_prompt:
            sp_str = system_prompt if isinstance(system_prompt, str) else "".join(str(p) for p in system_prompt)
            full_prompt = f"{sp_str}\n\n{prompt}"

        # Build the base CLI command
        cli_args = [
            CLAUDE_CLI_PATH,
            "--output-format",
            "stream-json",
            "--verbose",
            "--system-prompt",
            "",
            "--allowedTools",
            "*",
            "--permission-mode",
            "bypassPermissions",
            "--setting-sources",
            "project",
            "--print",
            "--",
            full_prompt,
        ]

        # Check if running as root - if so, use su to run as agent user
        # (Claude CLI refuses bypassPermissions when running as root)
        import shlex

        is_root = os.geteuid() == 0
        logger.info(f"[DIRECT CLI] euid={os.geteuid()}, is_root={is_root}")
        if is_root:
            # Escape the prompt for shell
            escaped_args = " ".join(shlex.quote(arg) for arg in cli_args)
            cmd = ["su", "-s", "/bin/bash", "agent", "-c", escaped_args]
            logger.info("[DIRECT CLI] Running as root, switching to agent user via su")
        else:
            cmd = cli_args

        logger.info(f"[DIRECT CLI] Command prepared, prompt length: {len(full_prompt)}, cmd[0]={cmd[0]}")

        def run_subprocess():
            """Run CLI in fully detached background process via bash script."""
            import uuid

            logger.info("[BG] Starting fully detached background runner")

            actual_timeout = timeout_seconds if timeout_seconds else 3600

            # Create temp files
            script_file = f"/tmp/claude_run_{uuid.uuid4().hex[:8]}.sh"
            out_file = f"/tmp/claude_out_{uuid.uuid4().hex[:8]}.txt"
            done_file = f"/tmp/claude_done_{uuid.uuid4().hex[:8]}.txt"

            # Build command string with proper escaping
            import shlex

            cmd_str = " ".join(shlex.quote(arg) for arg in cmd)

            # Create bash script that runs CLI with setsid for full detachment
            script_content = f'''#!/bin/bash
export CLAUDE_CODE_ENTRYPOINT=sdk-py
cd {shlex.quote(cwd)}
# Use script command for PTY, setsid for new session
setsid script -q -f -c "{cmd_str}" {out_file} &
PID=$!
sleep 1
# Wait up to {actual_timeout} seconds
for i in $(seq 1 {actual_timeout}); do
    if ! kill -0 $PID 2>/dev/null; then
        break
    fi
    sleep 1
done
# Kill if still running
kill -9 $PID 2>/dev/null
echo "done" > {done_file}
'''
            with open(script_file, "w") as f:
                f.write(script_content)
            os.chmod(script_file, 0o755)
            logger.info(f"[BG] Script file: {script_file}")

            # Run the script in background with nohup
            subprocess.Popen(
                ["nohup", "bash", script_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )

            # Poll for completion
            start_time = time.time()
            while time.time() - start_time < actual_timeout + 30:
                if os.path.exists(done_file):
                    logger.info(f"[BG] Done file found after {time.time() - start_time:.1f}s")
                    break
                time.sleep(1)
            else:
                logger.warning("[BG] Timed out waiting for done file")

            # Read output
            stdout = ""
            try:
                if os.path.exists(out_file):
                    with open(out_file) as f:
                        stdout = f.read()
                    os.unlink(out_file)
                if os.path.exists(done_file):
                    os.unlink(done_file)
                if os.path.exists(script_file):
                    os.unlink(script_file)
            except Exception as e:
                logger.warning(f"[BG] Error reading files: {e}")

            logger.info(f"[BG] Final: {len(stdout)} chars")

            if not stdout:
                raise subprocess.TimeoutExpired(cmd, actual_timeout, output="", stderr="")

            class Result:
                pass

            result = Result()
            result.returncode = 0
            result.stdout = stdout
            result.stderr = ""
            return result

        try:
            loop = asyncio.get_event_loop()

            # Run subprocess in thread pool to avoid event loop blocking
            logger.info("[DIRECT CLI] Running in thread pool executor...")
            start_time = time.time()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                if timeout_seconds:
                    # Use asyncio timeout wrapper
                    result = await asyncio.wait_for(
                        loop.run_in_executor(executor, run_subprocess),
                        timeout=timeout_seconds + 10,  # Extra buffer for thread overhead
                    )
                else:
                    result = await loop.run_in_executor(executor, run_subprocess)

            elapsed = time.time() - start_time
            logger.info(f"[DIRECT CLI] Subprocess completed in {elapsed:.1f}s, return code: {result.returncode}")
            logger.info(f"[DIRECT CLI] Stdout: {len(result.stdout)} chars, Stderr: {len(result.stderr)} chars")

            if result.stderr:
                logger.info(f"[DIRECT CLI] STDERR: {result.stderr[:500]}")

            if result.returncode != 0:
                logger.error(f"[DIRECT CLI] Non-zero exit code: {result.returncode}")
                if result.stderr:
                    raise RuntimeError(f"CLI failed with code {result.returncode}: {result.stderr[:500]}")
                raise RuntimeError(f"CLI failed with code {result.returncode}")

            # Parse output
            result_text = ""
            accumulated_content = []

            for line_str in result.stdout.split("\n"):
                line_str = line_str.strip()
                if not line_str:
                    continue

                try:
                    data = json.loads(line_str)
                    msg_type = data.get("type")

                    logger.debug(f"[DIRECT CLI] Parsed message type: {msg_type}")

                    if msg_type == "result":
                        result_text = data.get("result", "")
                        is_error = data.get("is_error", False)
                        logger.info(f"[DIRECT CLI] Got result ({len(result_text)} chars), is_error={is_error}")
                    elif msg_type == "assistant":
                        message = data.get("message", {})
                        content = message.get("content", [])
                        for item in content:
                            if item.get("type") == "text":
                                text = item.get("text", "")
                                accumulated_content.append(text)
                    elif msg_type == "system":
                        logger.debug(f"[DIRECT CLI] System message: {data.get('subtype', 'unknown')}")
                except json.JSONDecodeError:
                    logger.debug(f"[DIRECT CLI] Non-JSON line: {line_str[:100]}")

            if not result_text and not accumulated_content:
                raise RuntimeError("CLI produced no parseable output")

            return result_text or "\n".join(accumulated_content)

        except asyncio.TimeoutError:
            logger.warning(f"[DIRECT CLI] Timed out after {timeout_seconds}s")
            raise
        except concurrent.futures.TimeoutError:
            logger.warning(f"[DIRECT CLI] Thread pool timeout after {timeout_seconds}s")
            raise asyncio.TimeoutError(f"CLI timed out after {timeout_seconds}s")
        except subprocess.TimeoutExpired as e:
            logger.warning(f"[DIRECT CLI] Subprocess timeout after {timeout_seconds}s")
            # Log any partial output from the timeout
            logger.info(
                f"[DIRECT CLI] TimeoutExpired attrs: output={getattr(e, 'output', 'N/A')}, stderr={getattr(e, 'stderr', 'N/A')}"
            )
            partial_out = getattr(e, "output", None)
            partial_err = getattr(e, "stderr", None)
            if partial_out:
                logger.info(f"[DIRECT CLI] Partial stdout: {len(partial_out)} chars - {partial_out[:500]}")
            else:
                logger.info("[DIRECT CLI] No partial stdout captured")
            if partial_err:
                logger.info(f"[DIRECT CLI] Partial stderr: {len(partial_err)} chars - {partial_err[:300]}")
            raise asyncio.TimeoutError(f"CLI timed out after {timeout_seconds}s")
        except Exception as e:
            logger.error(f"[DIRECT CLI] Error: {e}", exc_info=True)
            raise

    async def _query_agent_via_queue(self, prompt: str, system_prompt: str = None, timeout_seconds: int = None) -> Any:
        """Query the agent via Redis queue (executed by separate worker process).

        This method offloads agent execution to a separate worker process that
        runs outside of uvicorn's context, solving subprocess I/O issues.
        """
        if not AGENT_QUEUE_AVAILABLE:
            raise RuntimeError("Agent queue not available")

        queue = get_agent_queue()

        # Determine agent type for tracking
        agent_type = self.__class__.__name__
        operation_type = "agent_query"

        logger.info(f"[QUEUE] Enqueueing task (agent={agent_type}, timeout={timeout_seconds}s)")

        try:
            await queue.connect()

            # Pre-enqueue diagnostics: check worker availability
            try:
                metrics = await queue.get_metrics()
                workers = metrics.get("workers_alive", 0)
                queue_depth = metrics.get("queue_length", 0)
                running = metrics.get("running", 0)
                if workers == 0:
                    logger.warning(
                        f"[QUEUE] No agent workers alive — task will likely get stuck. "
                        f"queue_depth={queue_depth}, running={running}"
                    )
                elif queue_depth > 0:
                    logger.info(f"[QUEUE] Queue status: {workers} worker(s), {queue_depth} queued, {running} running")
            except Exception as diag_err:
                logger.debug(f"[QUEUE] Pre-enqueue diagnostics failed (non-fatal): {diag_err}")

            # Collect API credentials to forward to the worker process
            api_env_keys = [
                "ANTHROPIC_AUTH_TOKEN",
                "ANTHROPIC_AUTH_TOKENS",
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_BASE_URL",
                "ANTHROPIC_DEFAULT_SONNET_MODEL",
            ]
            env_vars = {k: os.environ[k] for k in api_env_keys if os.environ.get(k)}

            # Enqueue the task
            task_id = await queue.enqueue_task(
                prompt=prompt,
                system_prompt=system_prompt,
                timeout_seconds=timeout_seconds or 1800,
                agent_type=agent_type,
                operation_type=operation_type,
                cwd=os.getcwd(),
                env_vars=env_vars or None,
            )

            logger.info(f"[QUEUE] Task enqueued: {task_id}, waiting for result...")

            # Notify caller of task_id for progress tracking
            if self.on_task_enqueued:
                try:
                    self.on_task_enqueued(task_id)
                except Exception as e:
                    logger.warning(f"on_task_enqueued callback error: {e}")

            # Progress callback to surface worker activity in logs
            def _on_progress(progress: dict):
                tool_calls = progress.get("tool_calls", 0)
                last_tool = progress.get("last_tool", "")
                interactions = progress.get("interactions", 0)
                short_tool = last_tool.rsplit("__", 1)[-1] if "__" in last_tool else last_tool
                logger.info(
                    f"[QUEUE] Worker progress: {tool_calls} tools, {interactions} interactions, last={short_tool}"
                )

            # Wait for result
            result = await queue.wait_for_result(
                task_id,
                timeout=timeout_seconds or 1800,
                poll_interval=0.5,
                on_progress=_on_progress,
            )

            logger.info(f"[QUEUE] Task {task_id} completed, result length: {len(result) if result else 0}")
            return result

        except asyncio.TimeoutError:
            logger.warning(f"[QUEUE] Task timed out after {timeout_seconds}s")
            raise
        except RuntimeError as e:
            error_msg = str(e)
            # Classify the error for clearer logs
            if "stuck in QUEUED" in error_msg or "no agent workers" in error_msg.lower():
                logger.error(f"[QUEUE] Task not picked up: {error_msg}")
            elif "heartbeat lost" in error_msg.lower():
                logger.error(f"[QUEUE] Worker crashed: {error_msg}")
            elif "rate limit" in error_msg.lower() or "429" in error_msg:
                logger.error(f"[QUEUE] Rate limited: {error_msg}")
            else:
                logger.error(f"[QUEUE] Task failed: {error_msg}")
            raise
        except Exception as e:
            logger.error(f"[QUEUE] Unexpected error: {e}", exc_info=True)
            raise

    async def _query_agent(self, prompt: str, system_prompt: str = None, timeout_seconds: int = None) -> Any:
        """Query the agent with Playwright tools enabled

        Args:
            prompt: The prompt to send to the agent
            system_prompt: Optional system prompt
            timeout_seconds: Optional timeout in seconds (None = no timeout)

        This method tries multiple approaches in order:
        1. Agent queue (Redis) - offloads to separate worker process (most reliable from uvicorn)
        2. Direct CLI invocation - if USE_DIRECT_CLI=true
        3. SDK-based execution - fallback
        """
        # First, try agent queue if Redis is available
        # This offloads execution to a separate worker process outside uvicorn
        if AGENT_QUEUE_AVAILABLE and should_use_agent_queue():
            return await self._query_agent_via_queue(prompt, system_prompt, timeout_seconds)

        # Try direct CLI invocation if explicitly enabled
        use_direct = os.environ.get("USE_DIRECT_CLI", "false").lower() == "true"

        if use_direct:
            return await self._query_agent_direct(prompt, system_prompt, timeout_seconds)

        # Use SDK by default (it handles subprocess internally)

        # Original SDK-based implementation (kept for reference)
        accumulator = _QueryAccumulator()

        async def _do_query():
            try:
                # Pre-flight diagnostics - use logger to ensure visibility in Docker logs
                cwd = os.getcwd()
                mcp_path = Path(cwd) / ".mcp.json"
                logger.info("[SDK DEBUG] Pre-flight check:")
                logger.info(f"[SDK DEBUG]   Working directory: {cwd}")
                logger.info(f"[SDK DEBUG]   DISPLAY: {os.environ.get('DISPLAY', 'not set')}")
                logger.info(f"[SDK DEBUG]   HEADLESS: {os.environ.get('HEADLESS', 'not set')}")
                logger.info(f"[SDK DEBUG]   ANTHROPIC_AUTH_TOKEN set: {bool(os.environ.get('ANTHROPIC_AUTH_TOKEN'))}")
                logger.info(f"[SDK DEBUG]   ANTHROPIC_BASE_URL: {os.environ.get('ANTHROPIC_BASE_URL', 'not set')}")
                logger.info(f"[SDK DEBUG]   MCP config path: {mcp_path}")
                logger.info(f"[SDK DEBUG]   MCP config exists: {mcp_path.exists()}")

                if mcp_path.exists():
                    try:
                        with open(mcp_path) as f:
                            mcp_config = json.load(f)
                        logger.info(f"[SDK DEBUG]   MCP servers: {list(mcp_config.get('mcpServers', {}).keys())}")
                    except Exception as e:
                        logger.error(f"[SDK DEBUG]   MCP config read error: {e}")

                # Callback to capture stderr from the Claude CLI subprocess
                def stderr_callback(line: str):
                    logger.info(f"[SDK STDERR] {line}")

                options = ClaudeAgentOptions(
                    allowed_tools=["*"],  # Allow all tools (Playwright, etc)
                    setting_sources=["project"],
                    permission_mode="bypassPermissions",
                    stderr=stderr_callback,  # Capture CLI stderr
                )

                # Note: SDK currently doesn't support separate system_prompt in options easily
                # without constructing messages manually, so we prepend it to prompt if needed.
                full_prompt = prompt
                if system_prompt:
                    # Ensure system_prompt is a string (it might be a list from SDK)
                    sp_str = system_prompt if isinstance(system_prompt, str) else "".join(str(p) for p in system_prompt)
                    full_prompt = f"{sp_str}\n\n{prompt}"

                logger.info(f"[SDK DEBUG] Starting query, prompt length: {len(full_prompt)}")
                logger.info("[SDK DEBUG] Waiting for first message from agent...")
                message_count = 0
                query_start = datetime.now()
                first_message_time = None

                # Select API key before SDK call
                if get_api_key_rotator is not None:
                    _rotator = get_api_key_rotator()
                    _slot = _rotator.get_active_key()
                    if _slot:
                        _rotator.activate_key(_slot)

                logger.info("[SDK DEBUG] About to call query() - entering async iterator...")

                async for message in query(prompt=full_prompt, options=options):
                    message_count += 1
                    if first_message_time is None:
                        first_message_time = datetime.now()
                        elapsed = (first_message_time - query_start).total_seconds()
                        logger.info(f"[SDK DEBUG] First message received after {elapsed:.1f}s")

                    msg_type = type(message).__name__
                    has_result = hasattr(message, "result")
                    has_content = hasattr(message, "content")

                    # More detailed message info
                    extra_info = ""
                    if hasattr(message, "type"):
                        extra_info += f" msg.type={message.type}"
                    if hasattr(message, "error"):
                        extra_info += f" error={message.error}"

                    logger.info(
                        f"[SDK DEBUG] Message #{message_count}: type={msg_type}, has_result={has_result}, has_content={has_content}{extra_info}"
                    )

                    if hasattr(message, "result"):
                        result_preview = str(message.result)[:200] if message.result else "None"
                        logger.info(f"[SDK DEBUG] Got result: {result_preview}...")
                        return message.result
                    if hasattr(message, "content"):
                        # Accumulate streaming content for timeout recovery
                        accumulator.add_content(message.content)

                # If we exit the loop without result, return accumulated content
                logger.info(
                    f"[SDK DEBUG] Loop ended, returning accumulated content ({len(accumulator.get_content())} chars)"
                )
                return accumulator.get_content()

            except Exception as e:
                logger.error(f"Agent Query Error: {e}", exc_info=True)
                raise e

        # Apply timeout if specified
        if timeout_seconds:
            # Create a task to capture partial results
            query_task = asyncio.create_task(_do_query())

            try:
                return await asyncio.wait_for(query_task, timeout=timeout_seconds)
            except asyncio.TimeoutError:
                logger.warning(f"Agent query timed out after {timeout_seconds} seconds")
                # Try to get partial result from the task
                if not query_task.done():
                    query_task.cancel()
                    try:
                        await query_task
                    except asyncio.CancelledError:
                        pass
                # Return accumulated content for timeout recovery
                partial_content = accumulator.get_content()
                if partial_content:
                    logger.info(f"Recovered {len(partial_content)} characters of partial content")
                    # Wrap in special marker so caller knows it's partial
                    return f"__TIMEOUT_PARTIAL__\n{partial_content}"
                # Reraise if no partial content
                logger.error("No partial content recovered, re-raising timeout")
                raise

        return await _do_query()

    async def run(self, config: dict[str, Any]) -> dict[str, Any]:
        """Main execution method to be implemented by subclasses"""
        raise NotImplementedError
