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
import re
import subprocess
import sys
import threading
import time
from importlib.util import find_spec
from pathlib import Path
from dataclasses import dataclass, field

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
from orchestrator.services.autonomous_events import create_event_for_work_item
from orchestrator.services.agent_run_events import create_agent_run_event
from orchestrator.services.browser_pool import OperationType as BrowserOpType
from orchestrator.services.browser_pool import get_browser_pool
from orchestrator.utils.browser_cleanup import kill_autopilot_process_tree, kill_test_run_process_tree
from orchestrator.utils.token_budget import build_agent_token_telemetry, extract_provider_usage

def _resolve_claude_cli_path() -> str:
    """Resolve the bundled Claude CLI from the active Python environment."""
    try:
        import claude_agent_sdk

        cli_path = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
        if cli_path.exists():
            return str(cli_path)
    except Exception:
        pass
    spec = find_spec("claude_agent_sdk")
    if spec and spec.origin:
        cli_path = Path(spec.origin).parent / "_bundled" / "claude"
        if cli_path.exists():
            return str(cli_path)
    return "/usr/local/lib/python3.10/dist-packages/claude_agent_sdk/_bundled/claude"


# Claude CLI path
CLAUDE_CLI_PATH = _resolve_claude_cli_path()

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


def _short_tool_name(tool_name: str) -> str:
    return tool_name.rsplit("__", 1)[-1] if "__" in tool_name else tool_name


def _tool_result_text(content: object) -> str:
    """Extract text from common Claude stream-json tool_result shapes."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if content.get("type") == "text":
            return str(content.get("text") or "")
        if content.get("type") == "tool_result":
            return _tool_result_text(content.get("content"))
        for key in ("content", "text", "result"):
            if key in content:
                text = _tool_result_text(content.get(key))
                if text:
                    return text
        return ""
    if isinstance(content, list):
        parts = [_tool_result_text(item) for item in content]
        return "\n".join(part for part in parts if part)
    return str(content)


def _event_content_items(evt: dict[str, object]) -> list[object]:
    """Return Claude stream content items across common event shapes."""
    message = evt.get("message") if isinstance(evt.get("message"), dict) else {}
    content = message.get("content") if isinstance(message, dict) else None
    if content is None:
        content = evt.get("content")
    if isinstance(content, list):
        return content
    if isinstance(content, dict):
        return [content]
    return []


def _iter_items_by_type(value: object, item_type: str):
    """Yield nested dict items matching a Claude content block type."""
    if isinstance(value, dict):
        if value.get("type") == item_type:
            yield value
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from _iter_items_by_type(child, item_type)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_items_by_type(child, item_type)


def _event_tool_uses(evt: dict[str, object]) -> list[dict[str, object]]:
    return [item for content in _event_content_items(evt) for item in _iter_items_by_type(content, "tool_use")]


def _event_tool_results(evt: dict[str, object]) -> list[dict[str, object]]:
    return [item for content in _event_content_items(evt) for item in _iter_items_by_type(content, "tool_result")]


@dataclass
class _BrowserToolCall:
    tool_use_id: str
    tool_name: str
    short_name: str
    input: dict[str, object] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class _PendingBrowserInteraction:
    action_type: str
    target: str
    from_state: object | None
    started_at: float = field(default_factory=time.time)


class BrowserObservationRecorder:
    """Best-effort runtime memory capture for exploration browser tool streams."""

    SNAPSHOT_URL_RE = re.compile(r"\bhttps?://[^\s\"'<>),]+")
    SNAPSHOT_TITLE_RE = re.compile(r"(?im)^\s*(?:title|page title)\s*[:=]\s*(.+)$")

    def __init__(
        self,
        *,
        session_id: str,
        cwd: str | None = None,
        service_factory=None,
        artifact_path: Path | None = None,
    ):
        self.session_id = session_id
        self.cwd = Path(cwd) if cwd else None
        self.service_factory = service_factory or self._default_service_factory
        self.artifact_path = artifact_path or ((self.cwd / "browser-memory-observations.jsonl") if self.cwd else None)
        self.event_log_path = (self.cwd / "exploration_events.jsonl") if self.cwd else None
        self.pending_tool_calls: dict[str, _BrowserToolCall] = {}
        self.latest_state = None
        self.pending_interaction: _PendingBrowserInteraction | None = None
        self.last_url: str | None = None
        self.project_id: str | None = None
        self.event_counter = 0
        self.stats = {"snapshots": 0, "transitions": 0, "errors": 0}

    def observe_event(self, evt: dict[str, object]) -> None:
        try:
            evt_type = evt.get("type")
            if evt_type == "assistant":
                for item in _event_tool_uses(evt):
                    self.observe_tool_use(item)
            elif evt_type == "user":
                for item in _event_tool_results(evt):
                    self.observe_tool_result(item)
        except Exception as exc:
            self._record_error("observe_event", exc)

    def observe_tool_use(self, item: dict[str, object]) -> None:
        tool_name = str(item.get("name") or "")
        short_name = _short_tool_name(tool_name)
        if not short_name.startswith("browser_"):
            return
        tool_use_id = str(item.get("id") or f"{short_name}-{time.time_ns()}")
        raw_input = item.get("input") if isinstance(item.get("input"), dict) else {}
        call = _BrowserToolCall(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            short_name=short_name,
            input=dict(raw_input),
        )
        self.pending_tool_calls[tool_use_id] = call
        if short_name == "browser_navigate":
            url = self._input_target(call.input)
            if url:
                self.last_url = url
        if short_name in INTERACTION_TOOLS:
            self._write_evidence_event(
                {
                    "event_type": "action_attempted",
                    "action": short_name.replace("browser_", ""),
                    "target": self._input_target(call.input),
                    "url": self.last_url,
                    "source": "browser_tool_stream",
                    "tool_use_id": tool_use_id,
                }
            )
            self.pending_interaction = _PendingBrowserInteraction(
                action_type=short_name.replace("browser_", ""),
                target=self._input_target(call.input),
                from_state=self.latest_state,
            )
        self._write_artifact({"event": "tool_use", "tool": short_name, "input": call.input})

    def observe_tool_result(self, item: dict[str, object]) -> None:
        tool_use_id = str(item.get("tool_use_id") or "")
        call = self.pending_tool_calls.pop(tool_use_id, None)
        if not call:
            return
        result_text = _tool_result_text(item.get("content"))
        is_error = bool(item.get("is_error") or item.get("error"))
        if call.short_name == "browser_snapshot":
            self._persist_snapshot(result_text)
        elif call.short_name == "browser_navigate":
            url = self._input_target(call.input) or self._extract_url(result_text)
            if url:
                self.last_url = url
                if not is_error:
                    self._write_evidence_event(
                        {
                            "event_type": "page_observed",
                            "url": url,
                            "title": url,
                            "summary": "Observed after browser_navigate.",
                            "source": "browser_tool_stream",
                            "tool_use_id": tool_use_id,
                        }
                    )
        elif call.short_name in {"browser_take_screenshot", "browser_screenshot"} and not is_error:
            filename = self._input_value(call.input, "filename") or self._input_value(call.input, "path")
            self._write_evidence_event(
                {
                    "event_type": "page_observed",
                    "url": self.last_url,
                    "title": self.last_url,
                    "summary": "Observed via screenshot.",
                    "screenshot_path": filename,
                    "source": "browser_tool_stream",
                    "tool_use_id": tool_use_id,
                }
            )
        if call.short_name in INTERACTION_TOOLS:
            target = self._input_target(call.input)
            if call.short_name == "browser_navigate" and target:
                self.last_url = target
            self._write_evidence_event(
                {
                    "event_type": "action_result",
                    "action": call.short_name.replace("browser_", ""),
                    "target": target or call.short_name,
                    "success": not is_error,
                    "outcome": "Browser tool completed." if not is_error else "Browser tool failed.",
                    "url": self.last_url,
                    "source": "browser_tool_stream",
                    "tool_use_id": tool_use_id,
                }
            )
        self._write_artifact(
            {
                "event": "tool_result",
                "tool": call.short_name,
                "tool_use_id": tool_use_id,
                "chars": len(result_text),
            }
        )

    def telemetry(self) -> dict[str, int]:
        return {
            "browser_memory_snapshots": int(self.stats["snapshots"]),
            "browser_memory_transitions": int(self.stats["transitions"]),
            "browser_memory_errors": int(self.stats["errors"]),
        }

    def flush_pending(self) -> None:
        for tool_use_id, call in list(self.pending_tool_calls.items()):
            if call.short_name in INTERACTION_TOOLS:
                self._write_evidence_event(
                    {
                        "event_type": "action_result",
                        "action": call.short_name.replace("browser_", ""),
                        "target": self._input_target(call.input) or call.short_name,
                        "success": False,
                        "outcome": "Browser tool did not return before the agent stopped.",
                        "url": self.last_url,
                        "source": "browser_tool_stream",
                        "tool_use_id": tool_use_id,
                    }
                )
        self._write_artifact(
            {
                "event": "flush",
                "pending_tool_calls": len(self.pending_tool_calls),
                "has_pending_interaction": self.pending_interaction is not None,
                **self.telemetry(),
            }
        )
        self.pending_tool_calls.clear()
        self.pending_interaction = None

    def _persist_snapshot(self, snapshot_text: str) -> None:
        url = self._extract_url(snapshot_text) or self.last_url or "about:blank"
        title = self._extract_title(snapshot_text) or url
        service = self.service_factory()
        state = service.upsert_page_state(
            session_id=self.session_id,
            url=url,
            snapshot_text=snapshot_text,
            title=title,
            snapshot_ref=f"agent-worker:{self.session_id}:{self.stats['snapshots'] + 1}",
            source_fidelity="live_snapshot",
        )
        self.stats["snapshots"] += 1
        pending = self.pending_interaction
        if pending and pending.from_state is not None:
            service.record_transition(
                session_id=self.session_id,
                from_state=pending.from_state,
                to_state=state,
                action_type=pending.action_type,
                target=pending.target,
                success=True,
                duration_ms=max(0.0, (time.time() - pending.started_at) * 1000),
            )
            self.stats["transitions"] += 1
            self.pending_interaction = None
        self.latest_state = state
        self.last_url = url
        self._write_evidence_event(
            {
                "event_type": "page_observed",
                "url": url,
                "title": title,
                "summary": "Observed from browser_snapshot.",
                "source": "browser_tool_stream",
            }
        )
        self._write_artifact({"event": "snapshot", "url": url, "state_id": state.id, **self.telemetry()})

    def _default_service_factory(self):
        from orchestrator.api.db import engine
        from orchestrator.api.models_db import ExplorationSession
        from orchestrator.memory.browser_memory import get_exploration_memory_service
        from sqlmodel import Session

        if self.project_id is None:
            try:
                with Session(engine) as session:
                    exploration = session.get(ExplorationSession, self.session_id)
                    self.project_id = exploration.project_id if exploration else "default"
            except Exception:
                self.project_id = "default"
        return get_exploration_memory_service(project_id=self.project_id or "default")

    def _write_artifact(self, payload: dict[str, object]) -> None:
        if not self.artifact_path:
            return
        try:
            self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
            with self.artifact_path.open("a") as f:
                f.write(json.dumps({"ts": time.time(), **payload}, default=str) + "\n")
        except Exception:
            pass

    def _write_evidence_event(self, payload: dict[str, object]) -> None:
        if not self.event_log_path:
            return
        try:
            self.event_counter += 1
            event = {"id": f"runtime_evt_{self.event_counter:03d}", "created_at": time.time(), **payload}
            self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.event_log_path.open("a") as f:
                f.write(json.dumps(event, sort_keys=True, default=str) + "\n")
        except Exception as exc:
            self._record_error("write_evidence_event", exc)

    def _record_error(self, stage: str, exc: Exception) -> None:
        self.stats["errors"] += 1
        logger.debug("Browser memory recorder skipped %s: %s", stage, exc)
        self._write_artifact({"event": "error", "stage": stage, "error": str(exc)})

    def _input_target(self, tool_input: dict[str, object]) -> str:
        for key in ("url", "target", "element", "text", "selector", "key"):
            value = self._input_value(tool_input, key)
            if value:
                return value
        return self._input_value(tool_input, "values")

    @staticmethod
    def _input_value(tool_input: dict[str, object], key: str) -> str:
        value = tool_input.get(key)
        if value is not None:
            return str(value)
        return ""

    def _extract_url(self, text: str) -> str | None:
        match = self.SNAPSHOT_URL_RE.search(text or "")
        return match.group(0) if match else None

    def _extract_title(self, text: str) -> str | None:
        match = self.SNAPSHOT_TITLE_RE.search(text or "")
        return match.group(1).strip()[:160] if match else None


class AgentWorker:
    """Worker that executes agent tasks from Redis queue."""

    def __init__(self):
        self.queue: AgentQueue = None
        self.worker_id = os.environ.get("AGENT_WORKER_ID", f"agent-worker-{os.getpid()}")
        self.running = False
        self.cwd = str(project_root)
        # Live progress tracking (updated by reader thread, read by heartbeat loop)
        self._progress_lock = threading.RLock()
        self._current_progress = self._empty_progress()
        self._process_lock = threading.Lock()
        self._running_processes: dict[str, subprocess.Popen] = {}
        self._cancelled_task_ids: set[str] = set()
        self._pause_lock = threading.Lock()
        self._paused_task_ids: set[str] = set()
        self._pause_started_at: dict[str, float] = {}
        self._paused_duration_seconds: dict[str, float] = {}
        self._last_execution_telemetry: dict[str, object] = {}

        # Setup environment
        setup_claude_env()

    @staticmethod
    def _empty_progress() -> dict[str, object]:
        return {
            "tool_calls": 0,
            "browser_tool_calls": 0,
            "last_tool": "",
            "last_tool_label": "",
            "current_tool": "",
            "current_tool_label": "",
            "tool_names": [],
            "tool_call_records": [],
            "chars": 0,
            "interactions": 0,
            "phase": "running",
            "message": "Agent is running",
        }

    def _emit_autonomous_event(
        self,
        *,
        owner_type: str | None,
        owner_id: str | None,
        task_id: str,
        event_type: str,
        message: str,
        level: str = "info",
        payload: dict[str, object] | None = None,
    ) -> None:
        if owner_type != "autonomous_work_item" or not owner_id:
            return
        try:
            create_event_for_work_item(
                owner_id,
                agent_task_id=task_id,
                event_type=event_type,
                level=level,
                message=message,
                payload=payload or {},
            )
        except Exception as exc:
            logger.debug("Failed to emit autonomous event for task %s: %s", task_id, exc)

    def _emit_agent_run_event(
        self,
        *,
        owner_type: str | None,
        owner_id: str | None,
        task_id: str,
        event_type: str,
        message: str,
        level: str = "info",
        payload: dict[str, object] | None = None,
    ) -> None:
        if owner_type != "agent_run" or not owner_id:
            return
        try:
            create_agent_run_event(
                run_id=owner_id,
                agent_task_id=task_id,
                event_type=event_type,
                level=level,
                message=message,
                payload=payload or {},
            )
        except Exception as exc:
            logger.debug("Failed to emit agent run event for task %s: %s", task_id, exc)

    def _emit_prd_generation_event(
        self,
        *,
        owner_type: str | None,
        owner_id: str | None,
        task_id: str,
        event_type: str,
        message: str,
        level: str = "info",
        payload: dict[str, object] | None = None,
    ) -> None:
        if owner_type != "prd_generation" or not owner_id:
            return
        def _redact(value: object, depth: int = 0, key: str = "") -> object:
            lowered = key.lower()
            if any(marker in lowered for marker in ("password", "secret", "token", "credential", "api_key", "authorization", "cookie")):
                return "<redacted>"
            if depth > 4:
                return "<truncated>"
            if isinstance(value, dict):
                return {str(item_key): _redact(item_value, depth + 1, str(item_key)) for item_key, item_value in list(value.items())[:40]}
            if isinstance(value, list):
                return [_redact(item, depth + 1, key) for item in value[:40]]
            if isinstance(value, str):
                return value if len(value) <= 1200 else value[:1200] + "...<truncated>"
            if isinstance(value, (int, float, bool)) or value is None:
                return value
            return str(value)[:1200]

        try:
            from sqlalchemy import func
            from sqlmodel import Session, select

            from orchestrator.api.db import engine
            from orchestrator.api.models_db import PrdGenerationEvent, PrdGenerationResult

            generation_id = int(owner_id)
            event_payload = {
                "agent_task_id": task_id,
                "agent_worker_id": self.worker_id,
                **(payload or {}),
            }
            redacted_payload = _redact(event_payload)
            event_payload = redacted_payload if isinstance(redacted_payload, dict) else {}
            with Session(engine) as session:
                generation = session.get(PrdGenerationResult, generation_id)
                if not generation:
                    return
                generation.agent_task_id = generation.agent_task_id or task_id
                generation.agent_worker_id = self.worker_id
                generation.queue_telemetry = {
                    **generation.queue_telemetry,
                    "agent_task_id": task_id,
                    "agent_worker_id": self.worker_id,
                    "last_worker_event_type": event_type,
                    "last_worker_event_message": message,
                }
                max_sequence = session.exec(
                    select(func.max(PrdGenerationEvent.sequence)).where(
                        PrdGenerationEvent.generation_id == generation_id
                    )
                ).one()
                event = PrdGenerationEvent(
                    generation_id=generation_id,
                    sequence=int(max_sequence or 0) + 1,
                    role="agent_worker",
                    event_type=event_type,
                    level=level,
                    message=message if len(message) <= 1200 else message[:1200] + "...",
                )
                event.payload = event_payload
                session.add(generation)
                session.add(event)
                session.commit()
        except Exception as exc:
            logger.debug("Failed to emit PRD generation event for task %s: %s", task_id, exc)

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

        self.running = True
        try:
            cleaned = await self.queue.cleanup_stale_tasks()
            if cleaned:
                logger.info("Initial agent queue cleanup cleared %s stale task(s)", cleaned)
        except Exception as e:
            logger.warning("Initial agent queue cleanup failed (non-fatal): %s", e)

        try:
            browser_pool = await get_browser_pool()
            stale_slots = await browser_pool.cleanup_stale(max_age_minutes=60)
            if stale_slots:
                logger.info("Initial browser slot cleanup cleared %s stale slot(s)", len(stale_slots))
        except Exception as e:
            logger.warning("Initial browser slot cleanup failed (non-fatal): %s", e)

        worker_heartbeat = asyncio.create_task(self._worker_heartbeat_loop())
        cleanup_loop = asyncio.create_task(self.queue.start_cleanup_loop())
        consecutive_empty = 0

        try:
            while self.running:
                try:
                    # Refresh once here as well so the first heartbeat is not delayed.
                    await self.queue.update_worker_heartbeat(
                        self.worker_id,
                        capabilities={"live_browser": self.queue._worker_supports_live_browser()},
                    )

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
        finally:
            cleanup_loop.cancel()
            try:
                await cleanup_loop
            except asyncio.CancelledError:
                pass
            worker_heartbeat.cancel()
            try:
                await worker_heartbeat
            except asyncio.CancelledError:
                pass

        await self.queue.disconnect()
        logger.info("Worker stopped")

    async def stop(self):
        """Stop the worker."""
        self.running = False

    async def _heartbeat_loop(self, task_id: str, interval: int = 3):
        """Send periodic heartbeat updates for a running task with progress data."""
        try:
            while True:
                with self._progress_lock:
                    progress_snapshot = dict(self._current_progress)
                await self.queue.update_heartbeat(task_id, progress=progress_snapshot)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    async def _worker_heartbeat_loop(self, interval: int = 10):
        """Keep the worker-level heartbeat fresh even while a long task is running."""
        try:
            while True:
                await self.queue.update_worker_heartbeat(
                    self.worker_id,
                    capabilities={"live_browser": self.queue._worker_supports_live_browser()},
                )
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    async def _cancel_monitor_loop(self, task_id: str, interval: float = 1.0):
        """Terminate the active CLI process when the Redis cancel flag is set."""
        try:
            while True:
                if await self.queue.is_cancelled(task_id):
                    logger.info(f"Task {task_id} cancellation detected; terminating Claude CLI process")
                    task = await self.queue.get_task(task_id)
                    with self._process_lock:
                        proc = self._running_processes.get(task_id)
                        self._cancelled_task_ids.add(task_id)

                    if proc and proc.poll() is None:
                        import signal

                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                        except (ProcessLookupError, OSError):
                            try:
                                proc.terminate()
                            except (ProcessLookupError, OSError):
                                pass
                        await asyncio.sleep(3)
                        if proc.poll() is None:
                            try:
                                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                            except (ProcessLookupError, OSError):
                                try:
                                    proc.kill()
                                except (ProcessLookupError, OSError):
                                    pass
                    if task and task.owner_type == "autopilot" and task.owner_id:
                        try:
                            cleanup = await asyncio.to_thread(
                                kill_autopilot_process_tree,
                                task.owner_id,
                            )
                            if cleanup.get("matched"):
                                logger.info(
                                    "AutoPilot cleanup for %s after cancellation: %s",
                                    task.owner_id,
                                    cleanup,
                                )
                        except Exception as exc:
                            logger.warning(
                                "Failed AutoPilot cleanup for cancelled task %s: %s",
                                task_id,
                                exc,
                            )
                    test_run_id = None
                    if task and task.owner_type == "test_run" and task.owner_id:
                        test_run_id = task.owner_id
                    elif (
                        task
                        and task.browser_slot_parent_owner_type == "test_run"
                        and task.browser_slot_parent_run_id
                    ):
                        test_run_id = task.browser_slot_parent_run_id
                    if test_run_id:
                        try:
                            cleanup = await asyncio.to_thread(
                                kill_test_run_process_tree,
                                test_run_id,
                            )
                            if cleanup.get("matched"):
                                logger.info(
                                    "Test run cleanup for %s after cancellation: %s",
                                    test_run_id,
                                    cleanup,
                                )
                        except Exception as exc:
                            logger.warning(
                                "Failed test run cleanup for cancelled task %s: %s",
                                task_id,
                                exc,
                            )
                    return
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    async def _pause_monitor_loop(self, task_id: str, interval: float = 0.5):
        """Suspend/resume the active CLI process when the Redis pause flag changes."""
        import signal

        try:
            while True:
                paused_requested = await self.queue.is_paused(task_id)
                with self._process_lock:
                    proc = self._running_processes.get(task_id)

                if paused_requested:
                    if proc and proc.poll() is None:
                        with self._pause_lock:
                            already_paused = task_id in self._paused_task_ids
                            if not already_paused:
                                self._paused_task_ids.add(task_id)
                                self._pause_started_at[task_id] = time.time()
                        if not already_paused:
                            logger.info(f"Task {task_id} pause detected; sending SIGSTOP to Claude CLI process group")
                            try:
                                os.killpg(os.getpgid(proc.pid), signal.SIGSTOP)
                            except (ProcessLookupError, OSError):
                                try:
                                    proc.send_signal(signal.SIGSTOP)
                                except (ProcessLookupError, OSError):
                                    pass

                    with self._progress_lock:
                        self._current_progress.update(
                            {
                                "status": "paused",
                                "phase": "paused",
                                "message": "Agent is paused",
                            }
                        )
                        progress_snapshot = {
                            **dict(self._current_progress),
                        }
                    await self.queue.update_heartbeat(task_id, progress=progress_snapshot)
                    await asyncio.sleep(interval)
                    continue

                with self._pause_lock:
                    was_paused = task_id in self._paused_task_ids
                    pause_started = self._pause_started_at.pop(task_id, None)
                    if was_paused:
                        self._paused_task_ids.discard(task_id)
                        if pause_started is not None:
                            self._paused_duration_seconds[task_id] = (
                                self._paused_duration_seconds.get(task_id, 0.0)
                                + max(0.0, time.time() - pause_started)
                            )

                if was_paused and proc and proc.poll() is None:
                    logger.info(f"Task {task_id} resume detected; sending SIGCONT to Claude CLI process group")
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGCONT)
                    except (ProcessLookupError, OSError):
                        try:
                            proc.send_signal(signal.SIGCONT)
                        except (ProcessLookupError, OSError):
                            pass
                    with self._progress_lock:
                        self._current_progress.update(
                            {
                                "status": "running",
                                "phase": "running",
                                "message": "Agent is running",
                            }
                        )

                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    def _effective_elapsed_seconds(self, task_id: str, start_time: float) -> float:
        """Return elapsed runtime excluding paused duration."""
        now = time.time()
        with self._pause_lock:
            paused_duration = self._paused_duration_seconds.get(task_id, 0.0)
            pause_started = self._pause_started_at.get(task_id)
            if pause_started is not None:
                paused_duration += max(0.0, now - pause_started)
        return max(0.0, now - start_time - paused_duration)

    def _task_requires_browser_slot(self, task: AgentTask) -> bool:
        """Return True when a queued agent task can consume browser capacity."""
        if task.owner_type == "prd_generation":
            # PRD generations own their live Playwright/VNC workspace separately.
            # Reserving the shared browser pool here can block the planner before
            # it has a chance to open the run-local browser.
            return False

        browser_owner_types = {
            "agent_run",
            "autonomous_work_item",
            "autopilot",
            "exploration_session",
        }
        if task.owner_type in browser_owner_types:
            return True

        if task.tools == []:
            return False

        tool_sources: list[object] = []
        if task.allowed_tools is None:
            # The CLI default grants broad tool access, so treat it as browser-capable.
            return True
        tool_sources.extend(task.allowed_tools or [])
        if isinstance(task.tools, list):
            tool_sources.extend(task.tools)
        elif isinstance(task.tools, dict):
            tool_sources.extend(task.tools.values())
        tool_sources.extend(task.disallowed_tools or [])

        return any(
            "browser" in str(tool).lower() or "playwright" in str(tool).lower()
            for tool in tool_sources
        )

    @staticmethod
    def _builtin_cli_tools(tools: list[str]) -> list[str]:
        """Return Claude CLI built-in tools, excluding MCP tool names."""
        return [str(tool) for tool in tools if not str(tool).startswith("mcp__")]

    @staticmethod
    def _unsupported_cli_options(task: AgentTask) -> list[str]:
        unsupported: list[str] = []
        if task.reasoning_budget is not None:
            unsupported.append("reasoning_budget/max_thinking_tokens")
        if task.max_buffer_size is not None:
            unsupported.append("max_buffer_size")
        if task.user:
            unsupported.append("user")
        if task.permission_prompt_tool_name:
            unsupported.append("permission_prompt_tool_name")
        if task.enable_file_checkpointing:
            unsupported.append("enable_file_checkpointing")
        if task.sandbox:
            unsupported.append("sandbox")
        return unsupported

    def _parent_test_run_slot_id(self, task: AgentTask) -> str | None:
        """Return the parent test-run slot id for a queued child agent, if any."""
        parent_owner_type = (
            task.browser_slot_parent_owner_type
            or (task.env_vars or {}).get("BROWSER_SLOT_PARENT_OWNER_TYPE")
            or ("test_run" if (task.env_vars or {}).get("BROWSER_SLOT_PARENT_RUN_ID") else None)
        )
        parent_run_id = task.browser_slot_parent_run_id or (task.env_vars or {}).get("BROWSER_SLOT_PARENT_RUN_ID")
        if parent_owner_type == "test_run" and parent_run_id:
            return str(parent_run_id)
        if task.owner_type == "test_run" and task.owner_id:
            return str(task.owner_id)
        return None

    async def _can_reuse_parent_browser_slot(self, task: AgentTask, browser_pool) -> bool:
        """Reuse a parent test-run slot only when the pool confirms it is running."""
        parent_run_id = self._parent_test_run_slot_id(task)
        if not parent_run_id:
            return False
        try:
            return bool(await browser_pool.is_running(parent_run_id))
        except Exception as exc:
            logger.debug(
                "Could not validate parent browser slot %s for task %s: %s",
                parent_run_id,
                task.id,
                exc,
            )
            return False

    async def _execute_task(self, task: AgentTask):
        """Execute an agent task using the Claude CLI with 429 retry and key rotation."""
        # Reset progress tracking for this task
        with self._progress_lock:
            self._current_progress = self._empty_progress()
            self._last_execution_telemetry = {}
        # Start heartbeat to signal we're alive
        heartbeat = asyncio.create_task(self._heartbeat_loop(task.id))
        cancel_monitor = asyncio.create_task(self._cancel_monitor_loop(task.id))
        pause_monitor = asyncio.create_task(self._pause_monitor_loop(task.id))
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
                if key.startswith("TESTDATA_"):
                    continue
                saved_env[key] = os.environ.get(key)  # None if not set
                os.environ[key] = value
            logger.info(f"Applied {len(task.env_vars)} env var(s) from task: {list(task.env_vars.keys())}")

        max_retries = 3
        rotator = get_api_key_rotator()
        # Re-initialize rotator so it picks up any new tokens from task env vars
        if task.env_vars:
            rotator.initialize()

        _result_submitted = False
        browser_pool = None
        browser_slot_request_id = None
        browser_slot_acquired = False
        try:
            unsupported_cli_options = self._unsupported_cli_options(task)
            if unsupported_cli_options:
                error = (
                    "Queued Claude CLI execution does not support SDK-only option(s): "
                    + ", ".join(unsupported_cli_options)
                    + ". Route this run through direct SDK execution."
                )
                telemetry = self._build_task_telemetry(task, 0, error_type="unsupported_cli_options")
                await self.queue.submit_result(task.id, "", success=False, error=error, telemetry=telemetry)
                _result_submitted = True
                return

            if self._task_requires_browser_slot(task):
                browser_pool = await get_browser_pool()
                parent_slot_id = self._parent_test_run_slot_id(task)
                if parent_slot_id and await self._can_reuse_parent_browser_slot(task, browser_pool):
                    with self._progress_lock:
                        self._current_progress.update(
                            {
                                "status": "running",
                                "phase": "running",
                                "message": "Using browser slot held by parent test run.",
                                "browser_slot_parent_run_id": parent_slot_id,
                            }
                        )
                    logger.info(
                        "Task %s is reusing parent test-run browser slot %s",
                        task.id,
                        parent_slot_id,
                    )
                    self._emit_agent_run_event(
                        owner_type=task.owner_type,
                        owner_id=task.owner_id,
                        task_id=task.id,
                        event_type="lifecycle",
                        message="Agent task is reusing the browser slot held by its parent test run.",
                        payload={"browser_slot_parent_run_id": parent_slot_id},
                    )
                else:
                    browser_slot_request_id = f"agent:{task.id}"
                    if parent_slot_id:
                        logger.warning(
                            "Task %s has parent test-run slot %s, but the slot is not active; acquiring its own slot.",
                            task.id,
                            parent_slot_id,
                        )
                    with self._progress_lock:
                        self._current_progress.update(
                            {
                                "status": "queued",
                                "phase": "browser_slot",
                                "message": "Waiting for global browser concurrency slot.",
                                **({"browser_slot_parent_run_id": parent_slot_id} if parent_slot_id else {}),
                            }
                        )
                    self._emit_agent_run_event(
                        owner_type=task.owner_type,
                        owner_id=task.owner_id,
                        task_id=task.id,
                        event_type="queued",
                        message="Agent task is waiting for a global browser concurrency slot.",
                        payload={
                            "browser_slot_request_id": browser_slot_request_id,
                            **({"browser_slot_parent_run_id": parent_slot_id} if parent_slot_id else {}),
                        },
                    )
                    try:
                        cleaned_slots = await browser_pool.cleanup_stale(max_age_minutes=60)
                        if cleaned_slots:
                            logger.info(
                                "Cleaned %s stale browser slot(s) before agent task %s waited: %s",
                                len(cleaned_slots),
                                task.id,
                                cleaned_slots,
                            )
                    except Exception as exc:
                        logger.debug("Browser slot cleanup before agent wait failed for task %s: %s", task.id, exc)
                    slot_timeout = float(os.environ.get("AGENT_BROWSER_SLOT_TIMEOUT_SECONDS", task.timeout_seconds))
                    slot_deadline = time.monotonic() + slot_timeout
                    while not browser_slot_acquired:
                        if await self.queue.is_cancelled(task.id):
                            telemetry = self._build_task_telemetry(task, 0, error_type="cancelled")
                            await self.queue.submit_result(task.id, "", success=False, error="Task cancelled", telemetry=telemetry)
                            _result_submitted = True
                            return

                        remaining = slot_deadline - time.monotonic()
                        if remaining <= 0:
                            break

                        browser_slot_acquired = await browser_pool.acquire(
                            request_id=browser_slot_request_id,
                            operation_type=BrowserOpType.AGENT,
                            description=task.owner_label or task.agent_type or task.operation_type or "Agent task",
                            timeout=min(5.0, remaining),
                            max_operation_duration=task.timeout_seconds + 300,
                        )
                    if not browser_slot_acquired:
                        error = "Timeout waiting for global browser concurrency slot"
                        telemetry = self._build_task_telemetry(task, 0, error_type="browser_slot_timeout")
                        self._emit_agent_run_event(
                            owner_type=task.owner_type,
                            owner_id=task.owner_id,
                            task_id=task.id,
                            event_type="error",
                            level="error",
                            message=error,
                            payload={"telemetry": telemetry, "browser_slot_request_id": browser_slot_request_id},
                        )
                        await self.queue.submit_result(task.id, "", success=False, error=error, telemetry=telemetry)
                        _result_submitted = True
                        return
                    if await self.queue.is_cancelled(task.id):
                        await browser_pool.release(browser_slot_request_id, success=False, error="Task cancelled")
                        browser_slot_acquired = False
                        telemetry = self._build_task_telemetry(task, 0, error_type="cancelled")
                        await self.queue.submit_result(task.id, "", success=False, error="Task cancelled", telemetry=telemetry)
                        _result_submitted = True
                        return
                    with self._progress_lock:
                        self._current_progress.update(
                            {
                                "status": "running",
                                "phase": "running",
                                "message": "Agent is running.",
                            }
                        )

            self._emit_autonomous_event(
                owner_type=task.owner_type,
                owner_id=task.owner_id,
                task_id=task.id,
                event_type="lifecycle",
                message="Agent task started.",
                payload={"agent_type": task.agent_type, "operation_type": task.operation_type},
            )
            self._emit_agent_run_event(
                owner_type=task.owner_type,
                owner_id=task.owner_id,
                task_id=task.id,
                event_type="lifecycle",
                message="Agent task started.",
                payload={
                    "agent_type": task.agent_type,
                    "operation_type": task.operation_type,
                    "worker_id": self.worker_id,
                },
            )
            self._emit_prd_generation_event(
                owner_type=task.owner_type,
                owner_id=task.owner_id,
                task_id=task.id,
                event_type="lifecycle",
                message="Agent task started.",
                payload={
                    "agent_type": task.agent_type,
                    "operation_type": task.operation_type,
                    "worker_id": self.worker_id,
                },
            )
            for attempt in range(1, max_retries + 1):
                # Select API key before each attempt
                slot = rotator.get_active_key()
                if slot:
                    rotator.activate_key(slot)

                try:
                    # Reset progress on retry
                    if attempt > 1:
                        with self._progress_lock:
                            self._current_progress = self._empty_progress()

                    result = await self._run_claude_cli(
                        task_id=task.id,
                        prompt=task.prompt,
                        system_prompt=task.system_prompt,
                        timeout_seconds=task.timeout_seconds,
                        cwd=task_cwd,
                        allowed_tools=task.allowed_tools,
                        tools=task.tools,
                        disallowed_tools=task.disallowed_tools,
                        permission_mode=task.permission_mode,
                        strict_mcp_config=task.strict_mcp_config,
                        max_budget_usd=task.max_budget_usd,
                        task_budget=task.task_budget,
                        include_hook_events=task.include_hook_events,
                        include_partial_messages=task.include_partial_messages,
                        output_format=task.output_format,
                        resume_session_id=task.resume_session_id,
                        continue_conversation=task.continue_conversation,
                        max_turns=task.max_turns,
                        fallback_model=task.fallback_model,
                        betas=task.betas,
                        owner_type=task.owner_type,
                        owner_id=task.owner_id,
                    )

                    # Success — report and submit
                    if slot:
                        rotator.report_success(slot)
                    telemetry = self._build_task_telemetry(task, attempt)
                    self._emit_autonomous_event(
                        owner_type=task.owner_type,
                        owner_id=task.owner_id,
                        task_id=task.id,
                        event_type="complete",
                        message="Agent task completed.",
                        payload={"telemetry": telemetry, "result_preview": result[:1200]},
                    )
                    self._emit_agent_run_event(
                        owner_type=task.owner_type,
                        owner_id=task.owner_id,
                        task_id=task.id,
                        event_type="complete",
                        message="Agent task completed.",
                        payload={"telemetry": telemetry, "result_preview": result[:1200]},
                    )
                    self._emit_prd_generation_event(
                        owner_type=task.owner_type,
                        owner_id=task.owner_id,
                        task_id=task.id,
                        event_type="complete",
                        message="Agent task completed.",
                        payload={"telemetry": telemetry, "result_preview": result[:1200]},
                    )
                    await self.queue.submit_result(task.id, result, success=True, telemetry=telemetry)
                    _result_submitted = True
                    return

                except asyncio.TimeoutError as e:
                    # Timeouts are not retryable
                    logger.error(f"Task {task.id} timed out: {e}")
                    telemetry = self._build_task_telemetry(task, attempt, error_type="timeout")
                    self._emit_autonomous_event(
                        owner_type=task.owner_type,
                        owner_id=task.owner_id,
                        task_id=task.id,
                        event_type="error",
                        level="error",
                        message=f"Agent task timed out: {e}",
                        payload={"telemetry": telemetry},
                    )
                    self._emit_agent_run_event(
                        owner_type=task.owner_type,
                        owner_id=task.owner_id,
                        task_id=task.id,
                        event_type="error",
                        level="error",
                        message=f"Agent task timed out: {e}",
                        payload={"telemetry": telemetry},
                    )
                    self._emit_prd_generation_event(
                        owner_type=task.owner_type,
                        owner_id=task.owner_id,
                        task_id=task.id,
                        event_type="error",
                        level="error",
                        message=f"Agent task timed out: {e}",
                        payload={"telemetry": telemetry},
                    )
                    await self.queue.submit_result(task.id, "", success=False, error=str(e), telemetry=telemetry)
                    _result_submitted = True
                    return

                except RuntimeError as e:
                    error_str = str(e)
                    if "cancelled" in error_str.lower():
                        logger.info(f"Task {task.id} cancelled during execution")
                        telemetry = self._build_task_telemetry(task, attempt, error_type="cancelled")
                        self._emit_autonomous_event(
                            owner_type=task.owner_type,
                            owner_id=task.owner_id,
                            task_id=task.id,
                            event_type="lifecycle",
                            message="Agent task cancelled.",
                            payload={"telemetry": telemetry},
                        )
                        self._emit_agent_run_event(
                            owner_type=task.owner_type,
                            owner_id=task.owner_id,
                            task_id=task.id,
                            event_type="lifecycle",
                            message="Agent task cancelled.",
                            payload={"telemetry": telemetry},
                        )
                        self._emit_prd_generation_event(
                            owner_type=task.owner_type,
                            owner_id=task.owner_id,
                            task_id=task.id,
                            event_type="lifecycle",
                            level="warning",
                            message="Agent task cancelled.",
                            payload={"telemetry": telemetry},
                        )
                        await self.queue.submit_result(task.id, "", success=False, error="Task cancelled", telemetry=telemetry)
                        _result_submitted = True
                        return
                    if is_rate_limit_error(error_str):
                        retry_after = parse_retry_after(error_str)
                        hard_quota_reset = (
                            "usage limit reached" in error_str.lower()
                            or "limit will reset" in error_str.lower()
                            or (retry_after is not None and retry_after >= task.timeout_seconds)
                        )

                        if slot:
                            rotator.report_rate_limit(slot, retry_after)

                        if hard_quota_reset and rotator.key_count <= 1:
                            telemetry = self._build_task_telemetry(task, attempt, error_type="rate_limit_exhausted")
                            message = (
                                "LLM provider quota is exhausted; the agent cannot start until the provider limit resets."
                            )
                            if retry_after:
                                message = f"{message} Retry after approximately {int(retry_after)} seconds."
                            logger.error("Task %s failed due to provider quota exhaustion: %s", task.id, error_str)
                            with self._progress_lock:
                                self._current_progress.update(
                                    {
                                        "status": "failed",
                                        "phase": "failed",
                                        "message": message,
                                        "retry_reason": "rate_limited",
                                        "retry_error_status": 429,
                                        "retry_after_seconds": retry_after,
                                    }
                                )
                            self._emit_agent_run_event(
                                owner_type=task.owner_type,
                                owner_id=task.owner_id,
                                task_id=task.id,
                                event_type="error",
                                level="error",
                                message=message,
                                payload={
                                    "telemetry": telemetry,
                                    "retry_after_seconds": retry_after,
                                    "provider_error": error_str[:2000],
                                },
                            )
                            self._emit_prd_generation_event(
                                owner_type=task.owner_type,
                                owner_id=task.owner_id,
                                task_id=task.id,
                                event_type="error",
                                level="error",
                                message=message,
                                payload={
                                    "telemetry": telemetry,
                                    "retry_after_seconds": retry_after,
                                    "provider_error": error_str[:2000],
                                },
                            )
                            await self.queue.submit_result(task.id, "", success=False, error=message, telemetry=telemetry)
                            _result_submitted = True
                            return

                        if attempt >= max_retries:
                            break

                        wait_seconds = min(retry_after or 30, 120)

                        logger.warning(
                            f"Task {task.id}: 429 on key "
                            f"{slot.masked if slot else '?'}, "
                            f"waiting {wait_seconds:.0f}s before retry "
                            f"{attempt + 1}/{max_retries}"
                        )
                        self._emit_agent_run_event(
                            owner_type=task.owner_type,
                            owner_id=task.owner_id,
                            task_id=task.id,
                            event_type="retry",
                            level="warning",
                            message=f"Agent task rate limited; retrying attempt {attempt + 1}/{max_retries}.",
                            payload={"retry_attempt": attempt + 1, "retry_wait_seconds": wait_seconds},
                        )
                        self._emit_prd_generation_event(
                            owner_type=task.owner_type,
                            owner_id=task.owner_id,
                            task_id=task.id,
                            event_type="retry",
                            level="warning",
                            message=f"Agent task rate limited; retrying attempt {attempt + 1}/{max_retries}.",
                            payload={"retry_attempt": attempt + 1, "retry_wait_seconds": wait_seconds},
                        )
                        # Surface retry state in heartbeat so frontend can show it
                        with self._progress_lock:
                            self._current_progress = self._empty_progress()
                            self._current_progress.update(
                                {
                                    "phase": "llm_retry",
                                    "status": "running",
                                    "message": f"LLM provider rate limited the request; retrying in {int(wait_seconds)}s.",
                                    "retry_attempt": attempt + 1,
                                    "retry_reason": "rate_limited",
                                    "retry_error_status": 429,
                                    "retry_wait_seconds": wait_seconds,
                                }
                            )
                        await asyncio.sleep(wait_seconds)
                        continue  # retry with rotated key
                    else:
                        # Non-429 RuntimeError or final attempt — fail
                        logger.error(f"Task {task.id} failed: {e}", exc_info=True)
                        telemetry = self._build_task_telemetry(task, attempt, error_type="runtime_error")
                        self._emit_autonomous_event(
                            owner_type=task.owner_type,
                            owner_id=task.owner_id,
                            task_id=task.id,
                            event_type="error",
                            level="error",
                            message=f"Agent task failed: {error_str}",
                            payload={"telemetry": telemetry},
                        )
                        self._emit_agent_run_event(
                            owner_type=task.owner_type,
                            owner_id=task.owner_id,
                            task_id=task.id,
                            event_type="error",
                            level="error",
                            message=f"Agent task failed: {error_str}",
                            payload={"telemetry": telemetry},
                        )
                        self._emit_prd_generation_event(
                            owner_type=task.owner_type,
                            owner_id=task.owner_id,
                            task_id=task.id,
                            event_type="error",
                            level="error",
                            message=f"Agent task failed: {error_str}",
                            payload={"telemetry": telemetry},
                        )
                        await self.queue.submit_result(task.id, "", success=False, error=error_str, telemetry=telemetry)
                        _result_submitted = True
                        return

                except Exception as e:
                    # Any other exception — fail immediately
                    logger.error(f"Task {task.id} failed: {e}", exc_info=True)
                    telemetry = self._build_task_telemetry(task, attempt, error_type=type(e).__name__)
                    self._emit_autonomous_event(
                        owner_type=task.owner_type,
                        owner_id=task.owner_id,
                        task_id=task.id,
                        event_type="error",
                        level="error",
                        message=f"Agent task failed: {e}",
                        payload={"telemetry": telemetry},
                    )
                    self._emit_agent_run_event(
                        owner_type=task.owner_type,
                        owner_id=task.owner_id,
                        task_id=task.id,
                        event_type="error",
                        level="error",
                        message=f"Agent task failed: {e}",
                        payload={"telemetry": telemetry},
                    )
                    self._emit_prd_generation_event(
                        owner_type=task.owner_type,
                        owner_id=task.owner_id,
                        task_id=task.id,
                        event_type="error",
                        level="error",
                        message=f"Agent task failed: {e}",
                        payload={"telemetry": telemetry},
                    )
                    await self.queue.submit_result(task.id, "", success=False, error=str(e), telemetry=telemetry)
                    _result_submitted = True
                    return

            # Exhausted all retries (shouldn't normally reach here)
            telemetry = self._build_task_telemetry(task, max_retries, error_type="rate_limit_exhausted")
            self._emit_autonomous_event(
                owner_type=task.owner_type,
                owner_id=task.owner_id,
                task_id=task.id,
                event_type="error",
                level="error",
                message=f"Agent task exhausted {max_retries} retries due to rate limiting.",
                payload={"telemetry": telemetry},
            )
            self._emit_agent_run_event(
                owner_type=task.owner_type,
                owner_id=task.owner_id,
                task_id=task.id,
                event_type="error",
                level="error",
                message=f"Agent task exhausted {max_retries} retries due to rate limiting.",
                payload={"telemetry": telemetry},
            )
            self._emit_prd_generation_event(
                owner_type=task.owner_type,
                owner_id=task.owner_id,
                task_id=task.id,
                event_type="error",
                level="error",
                message=f"Agent task exhausted {max_retries} retries due to rate limiting.",
                payload={"telemetry": telemetry},
            )
            await self.queue.submit_result(
                task.id,
                "",
                success=False,
                error=f"Exhausted {max_retries} retries due to rate limiting",
                telemetry=telemetry,
            )
            _result_submitted = True

        finally:
            cancel_monitor.cancel()
            pause_monitor.cancel()
            heartbeat.cancel()
            try:
                await cancel_monitor
            except asyncio.CancelledError:
                pass
            try:
                await pause_monitor
            except asyncio.CancelledError:
                pass
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            with self._pause_lock:
                self._paused_task_ids.discard(task.id)
                self._pause_started_at.pop(task.id, None)
                self._paused_duration_seconds.pop(task.id, None)
            # Emergency submit if result was never recorded
            if not _result_submitted:
                logger.warning(f"Task {task.id}: result not submitted, emergency submit")
                try:
                    await self.queue.submit_result(task.id, "", success=False, error="Worker failed to submit result")
                except Exception:
                    logger.error(f"Emergency submit failed for {task.id}")
            if browser_slot_acquired and browser_pool and browser_slot_request_id:
                try:
                    await browser_pool.release(browser_slot_request_id, success=_result_submitted)
                except Exception as exc:
                    logger.warning("Failed to release browser slot for task %s: %s", task.id, exc)
            # Restore environment variables to pre-task state
            for key, original_value in saved_env.items():
                if original_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = original_value
            if saved_env:
                logger.debug(f"Restored {len(saved_env)} env var(s) after task {task.id}")

    def _build_task_telemetry(
        self,
        task: AgentTask,
        attempt: int,
        error_type: str | None = None,
    ) -> dict[str, object]:
        """Build compact task telemetry from live progress and CLI stream stats."""
        with self._progress_lock:
            progress = dict(self._current_progress)
            execution = dict(self._last_execution_telemetry)
        telemetry: dict[str, object] = {
            "worker_id": self.worker_id,
            "attempt": attempt,
            "agent_type": task.agent_type,
            "stage": task.operation_type,
            "operation_type": task.operation_type,
            "timeout_seconds": task.timeout_seconds,
            "tool_calls": int(progress.get("tool_calls", 0) or 0),
            "browser_tool_calls": int(progress.get("browser_tool_calls", 0) or 0),
            "interactions": int(progress.get("interactions", 0) or 0),
            "last_tool": progress.get("last_tool", ""),
            "tool_names": progress.get("tool_names", []),
            "tool_call_records": progress.get("tool_call_records", []),
            "chars": int(progress.get("chars", 0) or 0),
            "allowed_tools_count": len(task.allowed_tools or []),
            "tools_count": len(task.tools) if isinstance(task.tools, list) else None,
            **execution,
        }
        telemetry["tool_calls"] = max(
            int(progress.get("tool_calls", 0) or 0),
            int(execution.get("tool_calls", 0) or 0),
        )
        telemetry["browser_tool_calls"] = max(
            int(progress.get("browser_tool_calls", 0) or 0),
            int(execution.get("browser_tool_calls", 0) or 0),
        )
        telemetry["interactions"] = max(
            int(progress.get("interactions", 0) or 0),
            int(execution.get("interactions", 0) or 0),
        )
        progress_tool_names = progress.get("tool_names", [])
        execution_tool_names = execution.get("tool_names", [])
        telemetry["tool_names"] = (
            execution_tool_names
            if isinstance(execution_tool_names, list) and execution_tool_names
            else progress_tool_names
        )
        telemetry["last_tool"] = execution.get("last_tool") or progress.get("last_tool", "")
        progress_tool_records = progress.get("tool_call_records", [])
        execution_tool_records = execution.get("tool_call_records", [])
        telemetry["tool_call_records"] = (
            execution_tool_records
            if isinstance(execution_tool_records, list) and execution_tool_records
            else progress_tool_records
        )
        if error_type:
            telemetry["error_type"] = error_type
        if telemetry.get("stage") != task.operation_type:
            telemetry["stage"] = task.operation_type
        if task.env_vars:
            telemetry.setdefault("model", task.env_vars.get("QUORVEX_LLM_ACTIVE_MODEL") or task.env_vars.get("ANTHROPIC_MODEL"))
            telemetry.setdefault("model_tier", task.env_vars.get("QUORVEX_LLM_ACTIVE_TIER"))
        if task.started_at:
            telemetry["duration_seconds"] = (time.time() - task.started_at.timestamp())
        return telemetry

    async def _run_claude_cli(
        self,
        task_id: str,
        prompt: str,
        system_prompt: str = None,
        timeout_seconds: int = 1800,
        cwd: str = None,
        allowed_tools: list[str] | None = None,
        tools: list[str] | dict[str, str] | None = None,
        disallowed_tools: list[str] | None = None,
        permission_mode: str | None = None,
        strict_mcp_config: bool = True,
        max_budget_usd: float | None = None,
        task_budget: dict[str, int] | None = None,
        include_hook_events: bool = False,
        include_partial_messages: bool = False,
        output_format: dict[str, object] | None = None,
        resume_session_id: str | None = None,
        continue_conversation: bool = False,
        max_turns: int | None = None,
        fallback_model: str | None = None,
        betas: list[str] | None = None,
        owner_type: str | None = None,
        owner_id: str | None = None,
    ) -> str:
        """Run Claude CLI and capture output."""
        loop = asyncio.get_event_loop()

        effective_cwd = cwd or self.cwd

        # Run blocking CLI in thread pool
        result = await loop.run_in_executor(
            None,
            self._run_cli_sync,
            task_id,
            prompt,
            system_prompt,
            timeout_seconds,
            effective_cwd,
            allowed_tools,
            tools,
            disallowed_tools,
            permission_mode,
            strict_mcp_config,
            max_budget_usd,
            task_budget,
            include_hook_events,
            include_partial_messages,
            output_format,
            resume_session_id,
            continue_conversation,
            max_turns,
            fallback_model,
            betas,
            owner_type,
            owner_id,
        )

        return result

    def _run_cli_sync(
        self,
        task_id: str,
        prompt: str,
        system_prompt: str = None,
        timeout_seconds: int = 1800,
        cwd: str = None,
        allowed_tools: list[str] | None = None,
        tools: list[str] | dict[str, str] | None = None,
        disallowed_tools: list[str] | None = None,
        permission_mode: str | None = None,
        strict_mcp_config: bool = True,
        max_budget_usd: float | None = None,
        task_budget: dict[str, int] | None = None,
        include_hook_events: bool = False,
        include_partial_messages: bool = False,
        output_format: dict[str, object] | None = None,
        resume_session_id: str | None = None,
        continue_conversation: bool = False,
        max_turns: int | None = None,
        fallback_model: str | None = None,
        betas: list[str] | None = None,
        owner_type: str | None = None,
        owner_id: str | None = None,
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
        effective_allowed_tools = ["*"] if allowed_tools is None else allowed_tools
        effective_permission_mode = permission_mode or ("dontAsk" if tools == [] else "bypassPermissions")
        logger.info(f"[CLI]   Allowed tools: {effective_allowed_tools}")
        logger.info(f"[CLI]   Tools: {tools}")
        logger.info(f"[CLI]   Permission mode: {effective_permission_mode}")

        start_time = time.time()
        output_chunks = []
        last_logged_chunks = 0
        stream_stats = {
            "stream_events": 0,
            "assistant_messages": 0,
            "system_messages": 0,
            "result_events": 0,
            "text_blocks": 0,
            "hook_events": 0,
            "api_error_status": None,
            "stop_reason": None,
            "session_id": None,
            "total_cost_usd": None,
            "parse_errors": 0,
            "api_retries": 0,
            "exit_code": None,
        }
        browser_recorder = (
            BrowserObservationRecorder(session_id=owner_id, cwd=effective_cwd)
            if owner_type in {"exploration_session", "agent_run"} and owner_id
            else None
        )

        # Build CLI command
        cli_args = [
            CLAUDE_CLI_PATH,
            "--output-format",
            "stream-json",
            "--verbose",
            "--system-prompt",
            "",
        ]
        if tools is not None:
            if isinstance(tools, list):
                builtin_tools = self._builtin_cli_tools(tools)
                if builtin_tools or tools == []:
                    cli_args.extend(["--tools", ",".join(builtin_tools)])
            elif isinstance(tools, dict) and tools.get("preset") == "claude_code":
                cli_args.extend(["--tools", "default"])
        if effective_allowed_tools:
            cli_args.extend(["--allowedTools", ",".join(effective_allowed_tools)])
        if disallowed_tools:
            cli_args.extend(["--disallowedTools", ",".join(disallowed_tools)])
        if max_budget_usd is not None:
            cli_args.extend(["--max-budget-usd", str(max_budget_usd)])
        if task_budget is not None and task_budget.get("total") is not None:
            cli_args.extend(["--task-budget", str(task_budget["total"])])
        selected_model = env.get("QUORVEX_LLM_ACTIVE_MODEL") or env.get("ANTHROPIC_MODEL")
        if selected_model:
            cli_args.extend(["--model", selected_model])
            logger.info(f"[CLI]   Model: {selected_model}")
        if fallback_model:
            cli_args.extend(["--fallback-model", fallback_model])
            logger.info("[CLI]   Fallback model configured")
        if betas:
            cli_args.extend(["--betas", ",".join(str(beta) for beta in betas)])
        if resume_session_id:
            cli_args.extend(["--resume", resume_session_id])
            logger.info("[CLI]   Resuming Claude session")
        elif continue_conversation:
            cli_args.append("--continue")
            logger.info("[CLI]   Continuing Claude conversation")
        if max_turns is not None:
            cli_args.extend(["--max-turns", str(max_turns)])

        mcp_config_path = Path(effective_cwd) / ".mcp.json"
        requested_tool_names = []
        for tool_source in (effective_allowed_tools, tools if isinstance(tools, list) else []):
            requested_tool_names.extend(str(tool) for tool in tool_source)
        if mcp_config_path.exists():
            self._validate_mcp_config(mcp_config_path, requested_tool_names)
            cli_args.extend(["--mcp-config", str(mcp_config_path)])
            if strict_mcp_config:
                cli_args.append("--strict-mcp-config")
        elif any(str(tool).startswith("mcp__") for tool in requested_tool_names):
            raise RuntimeError(
                f"MCP tools were requested but no .mcp.json exists in {effective_cwd}. "
                "Create a per-run MCP config before enqueueing the task."
            )
        if include_hook_events:
            cli_args.append("--include-hook-events")
        if include_partial_messages:
            cli_args.append("--include-partial-messages")
        if output_format:
            schema = output_format.get("schema") if isinstance(output_format, dict) else None
            if not schema:
                raise RuntimeError("Queued Claude CLI structured output requires output_format.schema")
            cli_args.extend(["--json-schema", json.dumps(schema)])
        cli_args.extend(
            [
                "--permission-mode",
                effective_permission_mode,
                "--setting-sources",
                "project",
                "--print",
                "--",
                full_prompt,
            ]
        )

        proc = None
        stream_file = None
        try:
            if owner_type in {"agent_run", "prd_generation"} and owner_id:
                try:
                    artifact_path = Path(effective_cwd) / "agent-stream.jsonl"
                    artifact_path.parent.mkdir(parents=True, exist_ok=True)
                    stream_file = artifact_path.open("a", encoding="utf-8")
                except Exception as exc:
                    logger.debug("Failed to open agent stream artifact for task %s: %s", task_id, exc)

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
            with self._process_lock:
                self._running_processes[task_id] = proc
                self._cancelled_task_ids.discard(task_id)
            logger.info(f"[CLI] Process started: PID={proc.pid}")

            # Read output with timeout using threads
            def read_output():
                try:
                    for line in iter(proc.stdout.readline, b""):
                        if line:
                            decoded = line.decode("utf-8", errors="replace")
                            output_chunks.append(decoded)
                            if stream_file is not None:
                                try:
                                    stream_file.write(decoded)
                                    stream_file.flush()
                                except Exception:
                                    pass
                            # Track tool_use events in stream-json for progress
                            stripped = decoded.strip()
                            if stripped and stripped.startswith("{"):
                                try:
                                    evt = json.loads(stripped)
                                    stream_stats["stream_events"] += 1
                                    evt_type = evt.get("type")
                                    if evt_type == "assistant":
                                        stream_stats["assistant_messages"] += 1
                                    elif evt_type == "system":
                                        stream_stats["system_messages"] += 1
                                        if evt.get("subtype") == "api_retry":
                                            attempt = int(evt.get("attempt") or 0)
                                            max_retries = int(evt.get("max_retries") or 0)
                                            error_status = evt.get("error_status")
                                            retry_delay_ms = evt.get("retry_delay_ms")
                                            stream_stats["api_retries"] = max(
                                                int(stream_stats.get("api_retries") or 0),
                                                attempt,
                                            )
                                            stream_stats["api_error_status"] = error_status
                                            retry_message = (
                                                f"LLM provider rate limited the request"
                                                f" (retry {attempt}/{max_retries})"
                                            )
                                            with self._progress_lock:
                                                self._current_progress.update(
                                                    {
                                                        "phase": "llm_retry",
                                                        "status": "running",
                                                        "message": retry_message,
                                                        "retry_attempt": attempt,
                                                        "retry_max_attempts": max_retries,
                                                        "retry_reason": evt.get("error") or "rate_limit",
                                                        "retry_error_status": error_status,
                                                        "retry_delay_ms": retry_delay_ms,
                                                    }
                                                )
                                            self._emit_agent_run_event(
                                                owner_type=owner_type,
                                                owner_id=owner_id,
                                                task_id=task_id,
                                                event_type="retry",
                                                level="warning",
                                                message=retry_message,
                                                payload={
                                                    "attempt": attempt,
                                                    "max_retries": max_retries,
                                                    "error_status": error_status,
                                                    "error": evt.get("error"),
                                                    "retry_delay_ms": retry_delay_ms,
                                                },
                                            )
                                            self._emit_prd_generation_event(
                                                owner_type=owner_type,
                                                owner_id=owner_id,
                                                task_id=task_id,
                                                event_type="retry",
                                                level="warning",
                                                message=retry_message,
                                                payload={
                                                    "attempt": attempt,
                                                    "max_retries": max_retries,
                                                    "error_status": error_status,
                                                    "error": evt.get("error"),
                                                    "retry_delay_ms": retry_delay_ms,
                                                },
                                            )
                                    elif evt_type == "result":
                                        stream_stats["result_events"] += 1
                                        stream_stats["api_error_status"] = evt.get("api_error_status")
                                        stream_stats["stop_reason"] = evt.get("stop_reason")
                                        stream_stats["session_id"] = evt.get("session_id")
                                        stream_stats["total_cost_usd"] = evt.get("total_cost_usd")
                                        usage = extract_provider_usage(evt)
                                        if usage:
                                            stream_stats["provider_usage"] = {
                                                **(stream_stats.get("provider_usage") or {}),
                                                **usage,
                                            }
                                    elif evt_type == "hook_event":
                                        stream_stats["hook_events"] += 1
                                    if browser_recorder is not None:
                                        browser_recorder.observe_event(evt)
                                    with self._progress_lock:
                                        if evt.get("type") == "assistant":
                                            for item in _event_content_items(evt):
                                                if isinstance(item, dict) and item.get("type") == "text":
                                                    stream_stats["text_blocks"] += 1
                                                    text = str(item.get("text") or "").strip()
                                                    if text:
                                                        self._current_progress["last_message"] = text[:500]
                                                        self._emit_autonomous_event(
                                                            owner_type=owner_type,
                                                            owner_id=owner_id,
                                                            task_id=task_id,
                                                            event_type="assistant_output",
                                                            message=text,
                                                            payload={"chars": len(text)},
                                                        )
                                                        self._emit_agent_run_event(
                                                            owner_type=owner_type,
                                                            owner_id=owner_id,
                                                            task_id=task_id,
                                                            event_type="assistant_output",
                                                            message=text,
                                                            payload={"chars": len(text)},
                                                        )
                                                        self._emit_prd_generation_event(
                                                            owner_type=owner_type,
                                                            owner_id=owner_id,
                                                            task_id=task_id,
                                                            event_type="assistant_output",
                                                            message=text[:1200],
                                                            payload={"chars": len(text)},
                                                        )
                                            for item in _event_tool_uses(evt):
                                                tool_name = str(item.get("name") or "")
                                                self._current_progress["tool_calls"] += 1
                                                self._current_progress["phase"] = "tool_use"
                                                self._current_progress["message"] = f"Using {_short_tool_name(tool_name) or tool_name}"
                                                self._current_progress["last_tool"] = tool_name
                                                self._current_progress["current_tool"] = tool_name
                                                tool_names = self._current_progress.setdefault("tool_names", [])
                                                if isinstance(tool_names, list) and len(tool_names) < 200:
                                                    tool_names.append(tool_name)
                                                tool_records = self._current_progress.setdefault("tool_call_records", [])
                                                if isinstance(tool_records, list) and len(tool_records) < 200:
                                                    tool_records.append(
                                                        {
                                                            "name": tool_name,
                                                            "tool_use_id": item.get("id"),
                                                            "input": item.get("input") or {},
                                                            "success": None,
                                                            "error": None,
                                                            "started_at": time.time(),
                                                        }
                                                    )
                                                # Strip MCP prefix: mcp__playwright-test__browser_click -> browser_click
                                                short_name = _short_tool_name(tool_name)
                                                self._current_progress["last_tool_label"] = short_name
                                                self._current_progress["current_tool_label"] = short_name
                                                if tool_name.startswith("mcp__") and short_name.startswith("browser_"):
                                                    self._current_progress["browser_tool_calls"] += 1
                                                    event_type = "browser_action"
                                                else:
                                                    event_type = "tool_call"
                                                if short_name in INTERACTION_TOOLS:
                                                    self._current_progress["interactions"] += 1
                                                self._emit_autonomous_event(
                                                    owner_type=owner_type,
                                                    owner_id=owner_id,
                                                    task_id=task_id,
                                                    event_type=event_type,
                                                    message=f"Tool call: {short_name or tool_name}",
                                                    payload={
                                                        "tool_name": tool_name,
                                                        "short_name": short_name,
                                                        "tool_label": short_name,
                                                        "current_tool": tool_name,
                                                        "current_tool_label": short_name,
                                                        "input": item.get("input") or {},
                                                    },
                                                )
                                                self._emit_agent_run_event(
                                                    owner_type=owner_type,
                                                    owner_id=owner_id,
                                                    task_id=task_id,
                                                    event_type=event_type,
                                                    message=f"Tool call: {short_name or tool_name}",
                                                    payload={
                                                        "tool_name": tool_name,
                                                        "short_name": short_name,
                                                        "tool_label": short_name,
                                                        "current_tool": tool_name,
                                                        "current_tool_label": short_name,
                                                        "input": item.get("input") or {},
                                                    },
                                                )
                                                self._emit_prd_generation_event(
                                                    owner_type=owner_type,
                                                    owner_id=owner_id,
                                                    task_id=task_id,
                                                    event_type=event_type,
                                                    message=f"Tool call: {short_name or tool_name}",
                                                    payload={
                                                        "tool_name": tool_name,
                                                        "short_name": short_name,
                                                        "tool_label": short_name,
                                                        "current_tool": tool_name,
                                                        "current_tool_label": short_name,
                                                        "input": item.get("input") or {},
                                                    },
                                                )
                                                self._current_progress["chars"] = sum(len(c) for c in output_chunks)
                                        elif evt.get("type") == "user":
                                            for item in _event_tool_results(evt):
                                                tool_use_id = item.get("tool_use_id")
                                                if not tool_use_id:
                                                    continue
                                                is_error = bool(item.get("is_error") or item.get("error"))
                                                result_text = _tool_result_text(item.get("content"))
                                                tool_records = self._current_progress.setdefault("tool_call_records", [])
                                                if isinstance(tool_records, list):
                                                    for record in reversed(tool_records):
                                                        if not isinstance(record, dict):
                                                            continue
                                                        if record.get("tool_use_id") != tool_use_id:
                                                            continue
                                                        record["success"] = not is_error
                                                        record["error"] = str(item.get("error") or "") if is_error else None
                                                        record["duration_ms"] = int(
                                                            max(0.0, (time.time() - float(record.get("started_at") or time.time())) * 1000)
                                                        )
                                                        record["result_preview"] = result_text[:500]
                                                        break
                                            self._current_progress["chars"] = sum(len(c) for c in output_chunks)
                                except (json.JSONDecodeError, TypeError):
                                    stream_stats["parse_errors"] += 1
                                    pass
                except Exception as e:
                    logger.error(f"[CLI] Read error: {e}")

            reader_thread = threading.Thread(target=read_output, daemon=False)
            reader_thread.start()

            # Wait for process with timeout
            while True:
                elapsed = self._effective_elapsed_seconds(task_id, start_time)
                if elapsed > timeout_seconds:
                    logger.warning(f"[CLI] Timeout after {elapsed:.1f}s active runtime, killing process group")
                    if browser_recorder is not None:
                        browser_recorder.flush_pending()
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
                    if task_id in self._cancelled_task_ids:
                        logger.info(f"[CLI] Process for task {task_id} exited after cancellation")
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
        finally:
            if stream_file is not None:
                try:
                    stream_file.close()
                except Exception:
                    pass
            with self._process_lock:
                self._running_processes.pop(task_id, None)

        raw_output = "".join(output_chunks)
        if browser_recorder is not None:
            browser_recorder.flush_pending()
        elapsed = self._effective_elapsed_seconds(task_id, start_time)
        with self._pause_lock:
            paused_duration = self._paused_duration_seconds.get(task_id, 0.0)
        exit_code = proc.returncode if proc else None
        stream_stats["exit_code"] = exit_code
        stream_stats["paused_duration_seconds"] = paused_duration
        logger.info(f"[CLI] Completed in {elapsed:.1f}s, exit_code={exit_code}, collected {len(raw_output)} chars")

        parsed_output = self._parse_cli_output(raw_output)
        with self._progress_lock:
            final_progress = dict(self._current_progress)
            self._last_execution_telemetry = {
                **stream_stats,
                **(browser_recorder.telemetry() if browser_recorder is not None else {}),
                **build_agent_token_telemetry(
                    prompt=full_prompt,
                    output=parsed_output,
                    stage=(owner_type or "agent_worker"),
                    agent_type="AgentRunner",
                    model=selected_model,
                    model_tier=env.get("QUORVEX_LLM_ACTIVE_TIER"),
                    provider_usage=stream_stats.get("provider_usage") if isinstance(stream_stats.get("provider_usage"), dict) else {},
                ),
                "tool_calls": int(final_progress.get("tool_calls", 0) or 0),
                "browser_tool_calls": int(final_progress.get("browser_tool_calls", 0) or 0),
                "interactions": int(final_progress.get("interactions", 0) or 0),
                "last_tool": final_progress.get("last_tool", ""),
                "tool_names": list(final_progress.get("tool_names") or []),
                "tool_call_records": list(final_progress.get("tool_call_records") or []),
                "raw_output_chars": len(raw_output),
                "cli_elapsed_seconds": elapsed,
            }
        if owner_type in {"agent_run", "prd_generation"} and owner_id:
            try:
                artifact_dir = Path(effective_cwd)
                artifact_dir.mkdir(parents=True, exist_ok=True)
                (artifact_dir / "raw_output.txt").write_text(raw_output, encoding="utf-8")
                (artifact_dir / "tool_calls.json").write_text(
                    json.dumps(final_progress.get("tool_call_records") or [], indent=2, default=str),
                    encoding="utf-8",
                )
                (artifact_dir / "agent_summary.json").write_text(
                    json.dumps(self._last_execution_telemetry, indent=2, default=str),
                    encoding="utf-8",
                )
                if owner_type == "agent_run":
                    self._emit_agent_run_event(
                        owner_type=owner_type,
                        owner_id=owner_id,
                        task_id=task_id,
                        event_type="telemetry",
                        message="Agent telemetry artifacts captured.",
                        payload={"telemetry": self._last_execution_telemetry},
                    )
                else:
                    self._emit_prd_generation_event(
                        owner_type=owner_type,
                        owner_id=owner_id,
                        task_id=task_id,
                        event_type="telemetry",
                        message="Agent telemetry artifacts captured.",
                        payload={"telemetry": self._last_execution_telemetry},
                    )
            except Exception as exc:
                logger.debug("Failed to write agent artifacts for task %s: %s", task_id, exc)

        if task_id in self._cancelled_task_ids:
            self._cancelled_task_ids.discard(task_id)
            raise RuntimeError("Task cancelled")

        # Log non-zero exit codes with output context
        if exit_code is not None and exit_code != 0:
            output_snippet = raw_output[-500:] if len(raw_output) > 500 else raw_output
            logger.error(f"[CLI] Non-zero exit code {exit_code}. Last 500 chars of output:\n{output_snippet}")

        # Log first 2000 chars for debugging
        if len(raw_output) < 100:
            logger.warning(f"[CLI] Very little output ({len(raw_output)} chars). Raw output:\n{raw_output}")
        else:
            logger.debug(f"[CLI] First 2000 chars:\n{raw_output[:2000]}")

        return parsed_output

    def _validate_mcp_config(self, mcp_config_path: Path, allowed_tools: list[str]) -> None:
        """Validate queued-worker MCP config before launching Claude CLI."""
        if not any(str(tool).startswith("mcp__") for tool in allowed_tools):
            return

        try:
            config = json.loads(mcp_config_path.read_text())
        except Exception as exc:
            raise RuntimeError(f"Invalid MCP config at {mcp_config_path}: {exc}") from exc

        servers = config.get("mcpServers") or {}
        if not isinstance(servers, dict) or not servers:
            raise RuntimeError(f"MCP config at {mcp_config_path} does not define any mcpServers")

        configured_prefixes = {f"mcp__{name}__" for name in servers}
        requested_prefixes = set()
        for tool in allowed_tools:
            parts = str(tool).split("__", 2)
            if len(parts) >= 3 and parts[0] == "mcp":
                requested_prefixes.add(f"mcp__{parts[1]}__")
        missing_prefixes = sorted(requested_prefixes - configured_prefixes)
        if missing_prefixes:
            raise RuntimeError(
                f"Allowed MCP tools do not match configured MCP servers in {mcp_config_path}. "
                f"Missing prefixes: {', '.join(missing_prefixes)}; configured: {', '.join(sorted(configured_prefixes))}"
            )

        for server_name, server in servers.items():
            command = (server or {}).get("command")
            if not command:
                raise RuntimeError(f"MCP server '{server_name}' in {mcp_config_path} has no command")
            if os.path.isabs(command) and not Path(command).exists():
                raise RuntimeError(
                    f"MCP server '{server_name}' command does not exist: {command}. "
                    "Install dependencies or set PLAYWRIGHT_MCP_COMMAND."
                )

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
                    api_error_status = data.get("api_error_status")
                    logger.info(f"[CLI] Got result ({len(result_text)} chars), is_error={is_error}")
                    if is_error:
                        status_suffix = f" (status {api_error_status})" if api_error_status else ""
                        raise RuntimeError(f"CLI returned error{status_suffix}: {result_text[:2000]}")

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
