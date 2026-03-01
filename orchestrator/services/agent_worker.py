#!/usr/bin/env python3
"""
Agent Worker Service

This worker runs as a separate supervisord program, polling Redis for agent tasks
and executing the Claude CLI in a clean process environment.

Key features:
- Runs outside uvicorn's event loop context
- Clean subprocess I/O without uvicorn's modifications
- Uses PTY for proper TTY handling with Claude CLI

Usage:
    python -m orchestrator.services.agent_worker
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# Setup logging early
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("agent_worker")

# Add project root to path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from orchestrator.load_env import setup_claude_env
from orchestrator.services.agent_queue import AgentQueue, AgentTask, get_agent_queue
from orchestrator.services.api_key_rotator import (
    get_api_key_rotator,
    is_rate_limit_error,
    parse_retry_after,
)

# Claude CLI path
CLAUDE_CLI_PATH = "/usr/local/lib/python3.10/dist-packages/claude_agent_sdk/_bundled/claude"

# State-changing tools that count as logical "interactions"
# (vs. observation tools like snapshot/evaluate/screenshot)
INTERACTION_TOOLS = frozenset(
    {
        "browser_navigate",
        "browser_navigate_back",
        "browser_click",
        "browser_type",
        "browser_select_option",
        "browser_press_key",
        "browser_handle_dialog",
        "browser_drag",
        "browser_file_upload",
    }
)


class AgentWorker:
    """Worker that executes agent tasks from Redis queue."""

    def __init__(self):
        self.queue: AgentQueue = None
        self.worker_id = os.environ.get("AGENT_WORKER_ID", f"agent-worker-{os.getpid()}")
        self.running = False
        self.cwd = str(project_root)
        # Live progress tracking (updated by reader thread, read by heartbeat loop)
        self._progress_lock = threading.Lock()
        self._current_progress = {"tool_calls": 0, "last_tool": "", "chars": 0, "interactions": 0}

        # Setup environment
        setup_claude_env()

    async def start(self):
        """Start the worker loop."""
        logger.info(f"Starting agent worker: {self.worker_id}")
        logger.info(f"  Working directory: {self.cwd}")
        logger.info(f"  DISPLAY: {os.environ.get('DISPLAY', 'not set')}")
        logger.info(f"  CLI path: {CLAUDE_CLI_PATH}")
        logger.info(f"  CLI exists: {os.path.exists(CLAUDE_CLI_PATH)}")

        self.queue = get_agent_queue()
        await self.queue.connect()

        # Initialize API key rotator
        try:
            rotator = get_api_key_rotator()
            rotator.initialize()
            logger.info(f"API key rotator: {rotator.key_count} key(s) available")
        except Exception as e:
            logger.warning(f"API key rotator init failed (non-fatal): {e}")

        # Clean up orphaned "running" tasks from previous container/process
        try:
            orphaned = await self.queue.cleanup_orphaned_tasks()
            if orphaned:
                logger.info(f"Startup: cleaned {orphaned} orphaned tasks from previous run")
        except Exception as e:
            logger.warning(f"Startup cleanup failed (non-fatal): {e}")

        self.running = True
        consecutive_empty = 0

        while self.running:
            try:
                # Refresh worker-level heartbeat each iteration (~10s)
                await self.queue.update_worker_heartbeat(self.worker_id)

                # Dequeue task (blocking for up to 10 seconds)
                task = await self.queue.dequeue_task(timeout=10)

                if task:
                    consecutive_empty = 0
                    logger.info(f"Processing task {task.id} (type={task.agent_type}, op={task.operation_type})")
                    await self._execute_task(task)
                else:
                    consecutive_empty += 1
                    if consecutive_empty % 30 == 0:  # Log every 5 minutes
                        metrics = await self.queue.get_metrics()
                        logger.debug(f"Queue idle, metrics: {metrics}")

            except asyncio.CancelledError:
                logger.info("Worker cancelled")
                break
            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)
                await asyncio.sleep(5)  # Back off on error

        await self.queue.disconnect()
        logger.info("Worker stopped")

    async def stop(self):
        """Stop the worker."""
        self.running = False

    async def _heartbeat_loop(self, task_id: str, interval: int = 30):
        """Send periodic heartbeat updates for a running task with progress data."""
        try:
            while True:
                with self._progress_lock:
                    progress_snapshot = dict(self._current_progress)
                await self.queue.update_heartbeat(task_id, progress=progress_snapshot)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    async def _execute_task(self, task: AgentTask):
        """Execute an agent task using the Claude CLI with 429 retry and key rotation."""
        # Reset progress tracking for this task
        with self._progress_lock:
            self._current_progress = {"tool_calls": 0, "last_tool": "", "chars": 0, "interactions": 0}
        # Start heartbeat to signal we're alive
        heartbeat = asyncio.create_task(self._heartbeat_loop(task.id))
        # Send initial heartbeat immediately
        await self.queue.update_heartbeat(task.id, progress=dict(self._current_progress))

        # Use task-specific CWD if provided (e.g., exploration session dir),
        # otherwise fall back to project root
        task_cwd = task.cwd if task.cwd else self.cwd

        # Save and apply task-specific env vars with isolation.
        # The pipeline may load credentials from the database that the worker's
        # .env file doesn't have, so we forward them through the queue.
        saved_env = {}
        if task.env_vars:
            for key, value in task.env_vars.items():
                saved_env[key] = os.environ.get(key)  # None if not set
                os.environ[key] = value
            logger.info(f"Applied {len(task.env_vars)} env var(s) from task: {list(task.env_vars.keys())}")

        max_retries = 3
        rotator = get_api_key_rotator()
        # Re-initialize rotator so it picks up any new tokens from task env vars
        if task.env_vars:
            rotator.initialize()

        _result_submitted = False
        try:
            for attempt in range(1, max_retries + 1):
                # Select API key before each attempt
                slot = rotator.get_active_key()
                if slot:
                    rotator.activate_key(slot)

                try:
                    # Reset progress on retry
                    if attempt > 1:
                        with self._progress_lock:
                            self._current_progress = {"tool_calls": 0, "last_tool": "", "chars": 0, "interactions": 0}

                    result = await self._run_claude_cli(
                        prompt=task.prompt,
                        system_prompt=task.system_prompt,
                        timeout_seconds=task.timeout_seconds,
                        cwd=task_cwd,
                    )

                    # Success — report and submit
                    if slot:
                        rotator.report_success(slot)
                    await self.queue.submit_result(task.id, result, success=True)
                    _result_submitted = True
                    return

                except asyncio.TimeoutError as e:
                    # Timeouts are not retryable
                    logger.error(f"Task {task.id} timed out: {e}")
                    await self.queue.submit_result(task.id, "", success=False, error=str(e))
                    _result_submitted = True
                    return

                except RuntimeError as e:
                    error_str = str(e)
                    if is_rate_limit_error(error_str) and attempt < max_retries:
                        retry_after = parse_retry_after(error_str)
                        wait_seconds = min(retry_after or 30, 120)

                        if slot:
                            rotator.report_rate_limit(slot, retry_after)

                        logger.warning(
                            f"Task {task.id}: 429 on key "
                            f"{slot.masked if slot else '?'}, "
                            f"waiting {wait_seconds:.0f}s before retry "
                            f"{attempt + 1}/{max_retries}"
                        )
                        # Surface retry state in heartbeat so frontend can show it
                        with self._progress_lock:
                            self._current_progress = {
                                "tool_calls": 0,
                                "last_tool": "",
                                "chars": 0,
                                "interactions": 0,
                                "retry_attempt": attempt + 1,
                                "retry_reason": "rate_limited",
                                "retry_wait_seconds": wait_seconds,
                            }
                        await asyncio.sleep(wait_seconds)
                        continue  # retry with rotated key
                    else:
                        # Non-429 RuntimeError or final attempt — fail
                        logger.error(f"Task {task.id} failed: {e}", exc_info=True)
                        await self.queue.submit_result(task.id, "", success=False, error=error_str)
                        _result_submitted = True
                        return

                except Exception as e:
                    # Any other exception — fail immediately
                    logger.error(f"Task {task.id} failed: {e}", exc_info=True)
                    await self.queue.submit_result(task.id, "", success=False, error=str(e))
                    _result_submitted = True
                    return

            # Exhausted all retries (shouldn't normally reach here)
            await self.queue.submit_result(
                task.id, "", success=False, error=f"Exhausted {max_retries} retries due to rate limiting"
            )
            _result_submitted = True

        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            # Emergency submit if result was never recorded
            if not _result_submitted:
                logger.warning(f"Task {task.id}: result not submitted, emergency submit")
                try:
                    await self.queue.submit_result(task.id, "", success=False, error="Worker failed to submit result")
                except Exception:
                    logger.error(f"Emergency submit failed for {task.id}")
            # Restore environment variables to pre-task state
            for key, original_value in saved_env.items():
                if original_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = original_value
            if saved_env:
                logger.debug(f"Restored {len(saved_env)} env var(s) after task {task.id}")

    async def _run_claude_cli(
        self,
        prompt: str,
        system_prompt: str = None,
        timeout_seconds: int = 1800,
        cwd: str = None,
    ) -> str:
        """Run Claude CLI and capture output."""
        loop = asyncio.get_event_loop()

        effective_cwd = cwd or self.cwd

        # Run blocking CLI in thread pool
        result = await loop.run_in_executor(
            None,
            self._run_cli_sync,
            prompt,
            system_prompt,
            timeout_seconds,
            effective_cwd,
        )

        return result

    def _run_cli_sync(
        self,
        prompt: str,
        system_prompt: str = None,
        timeout_seconds: int = 1800,
        cwd: str = None,
    ) -> str:
        """Synchronous CLI execution using subprocess with direct PIPE capture."""
        import signal
        import threading

        full_prompt = prompt
        if system_prompt:
            sp_str = system_prompt if isinstance(system_prompt, str) else "".join(str(p) for p in system_prompt)
            full_prompt = f"{sp_str}\n\n{prompt}"

        env = os.environ.copy()
        env["CLAUDE_CODE_ENTRYPOINT"] = "sdk-py"
        # Force non-interactive mode
        env["TERM"] = "dumb"
        env["CI"] = "true"
        # Ensure HOME is correct for agent user
        if os.getuid() != 0:
            import pwd

            try:
                pw = pwd.getpwuid(os.getuid())
                env["HOME"] = pw.pw_dir
                env["USER"] = pw.pw_name
            except KeyError:
                env["HOME"] = "/home/agent"
                env["USER"] = "agent"

        effective_cwd = cwd or self.cwd
        logger.info("[CLI] Starting Claude CLI (direct subprocess)")
        logger.info(f"[CLI]   Prompt length: {len(full_prompt)}")
        logger.info(f"[CLI]   Timeout: {timeout_seconds}s")
        logger.info(f"[CLI]   DISPLAY: {env.get('DISPLAY', 'not set')}")
        logger.info(f"[CLI]   CWD: {effective_cwd}")
        logger.info(f"[CLI]   UID: {os.getuid()}, EUID: {os.geteuid()}")
        logger.info(f"[CLI]   HOME: {env.get('HOME', 'not set')}")

        start_time = time.time()
        output_chunks = []
        last_logged_chunks = 0

        # Build CLI command
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

        proc = None
        try:
            # Use Popen with subprocess.PIPE - no TTY needed for --print mode
            proc = subprocess.Popen(
                cli_args,
                env=env,
                cwd=effective_cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout
                start_new_session=True,  # New session (similar to setsid)
            )
            logger.info(f"[CLI] Process started: PID={proc.pid}")

            # Read output with timeout using threads
            def read_output():
                try:
                    for line in iter(proc.stdout.readline, b""):
                        if line:
                            decoded = line.decode("utf-8", errors="replace")
                            output_chunks.append(decoded)
                            # Track tool_use events in stream-json for progress
                            stripped = decoded.strip()
                            if stripped and stripped.startswith("{"):
                                try:
                                    evt = json.loads(stripped)
                                    with self._progress_lock:
                                        if evt.get("type") == "assistant":
                                            for item in evt.get("message", {}).get("content", []):
                                                if item.get("type") == "tool_use":
                                                    tool_name = item.get("name", "")
                                                    self._current_progress["tool_calls"] += 1
                                                    self._current_progress["last_tool"] = tool_name
                                                    # Strip MCP prefix: mcp__playwright-test__browser_click → browser_click
                                                    short_name = (
                                                        tool_name.rsplit("__", 1)[-1]
                                                        if "__" in tool_name
                                                        else tool_name
                                                    )
                                                    if short_name in INTERACTION_TOOLS:
                                                        self._current_progress["interactions"] += 1
                                        self._current_progress["chars"] = sum(len(c) for c in output_chunks)
                                except (json.JSONDecodeError, TypeError):
                                    pass
                except Exception as e:
                    logger.error(f"[CLI] Read error: {e}")

            reader_thread = threading.Thread(target=read_output, daemon=False)
            reader_thread.start()

            # Wait for process with timeout
            while True:
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    logger.warning(f"[CLI] Timeout after {elapsed:.1f}s, killing process group")
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        try:
                            proc.kill()
                        except (ProcessLookupError, OSError):
                            pass
                    proc.wait()
                    raise asyncio.TimeoutError(f"CLI timed out after {elapsed:.1f}s")

                poll_result = proc.poll()
                if poll_result is not None:
                    # Process finished - give reader thread time to finish
                    reader_thread.join(timeout=15.0)
                    if reader_thread.is_alive():
                        logger.warning("[CLI] Reader thread still alive after 15s, forcing stdout close")
                        try:
                            proc.stdout.close()
                        except Exception:
                            pass
                        reader_thread.join(timeout=5.0)
                        if reader_thread.is_alive():
                            logger.warning("[CLI] Reader thread still alive after forced close, proceeding anyway")
                    logger.info(f"[CLI] Process exited with code {poll_result} after {elapsed:.1f}s")
                    break

                # Log progress periodically (every 50 new chunks)
                current_chunks = len(output_chunks)
                if current_chunks > 0 and current_chunks >= last_logged_chunks + 50:
                    total_len = sum(len(c) for c in output_chunks)
                    logger.info(f"[CLI] Progress: {current_chunks} chunks, {total_len} chars")
                    last_logged_chunks = current_chunks

                time.sleep(0.5)

        except asyncio.TimeoutError:
            raise
        except Exception as e:
            logger.error(f"[CLI] Execution error: {e}", exc_info=True)
            if proc and proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    try:
                        proc.kill()
                    except Exception:
                        pass
            raise

        raw_output = "".join(output_chunks)
        elapsed = time.time() - start_time
        exit_code = proc.returncode if proc else None
        logger.info(f"[CLI] Completed in {elapsed:.1f}s, exit_code={exit_code}, collected {len(raw_output)} chars")

        # Log non-zero exit codes with output context
        if exit_code is not None and exit_code != 0:
            output_snippet = raw_output[-500:] if len(raw_output) > 500 else raw_output
            logger.error(f"[CLI] Non-zero exit code {exit_code}. Last 500 chars of output:\n{output_snippet}")

        # Log first 2000 chars for debugging
        if len(raw_output) < 100:
            logger.warning(f"[CLI] Very little output ({len(raw_output)} chars). Raw output:\n{raw_output}")
        else:
            logger.debug(f"[CLI] First 2000 chars:\n{raw_output[:2000]}")

        return self._parse_cli_output(raw_output)

    def _parse_cli_output(self, raw_output: str) -> str:
        """Parse stream-json output from Claude CLI."""
        result_text = ""
        accumulated_content = []

        for line in raw_output.split("\n"):
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
                msg_type = data.get("type")

                if msg_type == "result":
                    result_text = data.get("result", "")
                    is_error = data.get("is_error", False)
                    logger.info(f"[CLI] Got result ({len(result_text)} chars), is_error={is_error}")
                    if is_error:
                        raise RuntimeError(f"CLI returned error: {result_text[:2000]}")

                elif msg_type == "assistant":
                    message = data.get("message", {})
                    content = message.get("content", [])
                    for item in content:
                        if item.get("type") == "text":
                            text = item.get("text", "")
                            accumulated_content.append(text)

                elif msg_type == "system":
                    subtype = data.get("subtype", "unknown")
                    logger.debug(f"[CLI] System message: {subtype}")

            except json.JSONDecodeError:
                # Non-JSON line (could be escape sequences, etc.)
                pass

        final_result = result_text or "\n".join(accumulated_content)

        if not final_result:
            # Log first 1000 chars of raw output for debugging
            logger.error(f"[CLI] No parseable output. Raw (first 1000 chars):\n{raw_output[:1000]}")
            raise RuntimeError("CLI produced no parseable output")

        return final_result


async def main():
    """Main entry point."""
    worker = AgentWorker()

    # Handle shutdown signals
    import signal

    def handle_signal(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        worker.running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
