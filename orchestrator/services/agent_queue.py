"""
Redis-based queue for agent execution tasks.

This module provides a queue for distributing agent execution tasks to a separate
worker process that runs outside of uvicorn's context, solving the subprocess I/O
issues that occur when spawning the Claude CLI from within uvicorn workers.

Architecture:
    API (uvicorn) → Redis Queue → Agent Worker (supervisord)
                  ← Results ←

The worker runs as a separate supervisord program, giving it a clean process
environment without uvicorn's event loop modifications.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

try:
    import redis.asyncio as aioredis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class AgentTaskStatus(str, Enum):
    """Status of an agent task."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


@dataclass
class AgentTask:
    """Represents an agent execution task."""

    id: str
    prompt: str
    system_prompt: str | None = None
    timeout_seconds: int = 1800
    status: AgentTaskStatus = AgentTaskStatus.QUEUED
    worker_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: str | None = None
    error: str | None = None
    # Metadata for tracking
    agent_type: str | None = None
    operation_type: str | None = None
    cwd: str | None = None  # Working directory for CLI execution
    env_vars: dict[str, str] | None = None  # API credentials to pass to worker
    allowed_tools: list[str] | None = None  # Claude allowed tools for this task
    tools: list[str] | dict[str, str] | None = None  # Base available tool set
    disallowed_tools: list[str] | None = None  # Claude tools hidden from this task
    permission_mode: str | None = None  # Claude permission mode
    strict_mcp_config: bool = True  # Use only task-local MCP config when present
    max_budget_usd: float | None = None  # Optional spend cap
    task_budget: dict[str, int] | None = None  # Optional token budget
    include_hook_events: bool = False  # Stream hook lifecycle events
    include_partial_messages: bool = False  # Stream partial message chunks
    output_format: dict[str, Any] | None = None  # Optional native SDK output contract
    resume_session_id: str | None = None  # Optional Claude session to resume
    continue_conversation: bool = False
    max_turns: int | None = None
    fallback_model: str | None = None
    reasoning_budget: int | None = None
    max_buffer_size: int | None = None
    betas: list[str] | None = None
    user: str | None = None
    permission_prompt_tool_name: str | None = None
    enable_file_checkpointing: bool = False
    sandbox: dict[str, Any] | None = None
    owner_type: str | None = None  # Logical owner, e.g. autopilot or agent_run
    owner_id: str | None = None
    owner_label: str | None = None
    browser_slot_parent_owner_type: str | None = None
    browser_slot_parent_run_id: str | None = None
    requires_live_browser: bool = False
    telemetry: dict[str, Any] = field(
        default_factory=dict
    )  # Structured execution diagnostics

    def to_dict(self) -> dict:
        """Convert to dictionary for Redis storage."""
        return {
            "id": self.id,
            "prompt": self.prompt,
            "system_prompt": self.system_prompt,
            "timeout_seconds": self.timeout_seconds,
            "status": self.status.value,
            "worker_id": self.worker_id,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "result": self.result,
            "error": self.error,
            "agent_type": self.agent_type,
            "operation_type": self.operation_type,
            "cwd": self.cwd,
            "env_vars": self.env_vars,
            "allowed_tools": self.allowed_tools,
            "tools": self.tools,
            "disallowed_tools": self.disallowed_tools,
            "permission_mode": self.permission_mode,
            "strict_mcp_config": self.strict_mcp_config,
            "max_budget_usd": self.max_budget_usd,
            "task_budget": self.task_budget,
            "include_hook_events": self.include_hook_events,
            "include_partial_messages": self.include_partial_messages,
            "output_format": self.output_format,
            "resume_session_id": self.resume_session_id,
            "continue_conversation": self.continue_conversation,
            "max_turns": self.max_turns,
            "fallback_model": self.fallback_model,
            "reasoning_budget": self.reasoning_budget,
            "max_buffer_size": self.max_buffer_size,
            "betas": self.betas,
            "user": self.user,
            "permission_prompt_tool_name": self.permission_prompt_tool_name,
            "enable_file_checkpointing": self.enable_file_checkpointing,
            "sandbox": self.sandbox,
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
            "owner_label": self.owner_label,
            "browser_slot_parent_owner_type": self.browser_slot_parent_owner_type,
            "browser_slot_parent_run_id": self.browser_slot_parent_run_id,
            "requires_live_browser": self.requires_live_browser,
            "telemetry": self.telemetry,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentTask":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            prompt=data["prompt"],
            system_prompt=data.get("system_prompt"),
            timeout_seconds=data.get("timeout_seconds", 1800),
            status=AgentTaskStatus(data.get("status", "queued")),
            worker_id=data.get("worker_id"),
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if data.get("created_at")
                else datetime.utcnow()
            ),
            started_at=(
                datetime.fromisoformat(data["started_at"])
                if data.get("started_at")
                else None
            ),
            completed_at=(
                datetime.fromisoformat(data["completed_at"])
                if data.get("completed_at")
                else None
            ),
            result=data.get("result"),
            error=data.get("error"),
            agent_type=data.get("agent_type"),
            operation_type=data.get("operation_type"),
            cwd=data.get("cwd"),
            env_vars=data.get("env_vars"),
            allowed_tools=data.get("allowed_tools"),
            tools=data.get("tools"),
            disallowed_tools=data.get("disallowed_tools"),
            permission_mode=data.get("permission_mode"),
            strict_mcp_config=data.get("strict_mcp_config", True),
            max_budget_usd=data.get("max_budget_usd"),
            task_budget=data.get("task_budget"),
            include_hook_events=bool(data.get("include_hook_events", False)),
            include_partial_messages=bool(data.get("include_partial_messages", False)),
            output_format=data.get("output_format"),
            resume_session_id=data.get("resume_session_id"),
            continue_conversation=bool(data.get("continue_conversation", False)),
            max_turns=data.get("max_turns"),
            fallback_model=data.get("fallback_model"),
            reasoning_budget=data.get("reasoning_budget"),
            max_buffer_size=data.get("max_buffer_size"),
            betas=data.get("betas"),
            user=data.get("user"),
            permission_prompt_tool_name=data.get("permission_prompt_tool_name"),
            enable_file_checkpointing=bool(data.get("enable_file_checkpointing", False)),
            sandbox=data.get("sandbox"),
            owner_type=data.get("owner_type"),
            owner_id=data.get("owner_id"),
            owner_label=data.get("owner_label"),
            browser_slot_parent_owner_type=data.get("browser_slot_parent_owner_type"),
            browser_slot_parent_run_id=data.get("browser_slot_parent_run_id"),
            requires_live_browser=bool(data.get("requires_live_browser", False)),
            telemetry=data.get("telemetry") or {},
        )


class AgentQueue:
    """
    Redis-based queue for agent task execution.

    Used to offload agent execution from uvicorn workers to a separate
    process with a clean environment.
    """

    # Redis key prefixes
    QUEUE_KEY = "playwright:agents:queue"
    RUNNING_KEY = "playwright:agents:running"
    TASKS_KEY = "playwright:agents:tasks"
    RESULTS_KEY = "playwright:agents:results"
    CHANNEL_KEY = "playwright:agents:notifications"
    HEARTBEAT_PREFIX = "playwright:agents:heartbeat:"
    CANCEL_PREFIX = "playwright:agents:cancel:"
    PAUSE_PREFIX = "playwright:agents:pause:"
    WORKER_HEARTBEAT_PREFIX = "playwright:agents:worker_alive:"
    WORKER_HEARTBEAT_TTL_SECONDS = 30
    DEFAULT_STALE_OWNERLESS_QUEUE_MINUTES = 45

    def __init__(self, redis_url: str | None = None):
        """Initialize the agent queue."""
        if not REDIS_AVAILABLE:
            raise ImportError(
                "redis package not installed. Run: pip install redis[hiredis]"
            )

        self.redis_url = redis_url or os.environ.get(
            "REDIS_URL", "redis://localhost:6379/0"
        )
        self._redis: aioredis.Redis | None = None
        self._worker_id = os.environ.get(
            "AGENT_WORKER_ID", f"agent-worker-{uuid.uuid4().hex[:8]}"
        )
        self._last_ping_time: float = 0.0
        self._ping_interval: float = 5.0

    def _emit_agent_run_event(
        self,
        task: AgentTask | None,
        *,
        event_type: str,
        message: str,
        level: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> None:
        if not task or task.owner_type != "agent_run" or not task.owner_id:
            return
        try:
            from orchestrator.services.agent_run_events import create_agent_run_event

            create_agent_run_event(
                run_id=task.owner_id,
                agent_task_id=task.id,
                event_type=event_type,
                level=level,
                message=message,
                payload=payload or {},
            )
        except Exception as exc:
            logger.debug(
                "Failed to emit agent run event for task %s: %s",
                getattr(task, "id", None),
                exc,
            )

    async def connect(self) -> None:
        """Establish Redis connection."""
        if self._redis is None:
            self._redis = aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                retry_on_error=[ConnectionError, TimeoutError],
                health_check_interval=30,
            )
            await self._redis.ping()
            logger.info(f"AgentQueue connected to Redis: {self.redis_url}")

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    async def health_check(self) -> bool:
        """Check Redis connectivity."""
        try:
            if self._redis:
                await self._redis.ping()
                return True
            return False
        except Exception:
            return False

    async def _ensure_connected(self) -> aioredis.Redis:
        """Ensure Redis is connected and return client, with auto-reconnect."""
        now = time.monotonic()
        if (
            self._redis is not None
            and (now - self._last_ping_time) < self._ping_interval
        ):
            return self._redis

        if self._redis is not None:
            try:
                await asyncio.wait_for(self._redis.ping(), timeout=2.0)
                self._last_ping_time = now
                return self._redis
            except Exception:
                logger.warning("AgentQueue Redis connection lost, reconnecting...")
                try:
                    await self._redis.close()
                except Exception:
                    pass
                self._redis = None

        await self.connect()
        self._last_ping_time = time.monotonic()
        return self._redis

    # ==========================================
    # Producer Methods (API/uvicorn)
    # ==========================================

    async def enqueue_task(
        self,
        prompt: str,
        system_prompt: str | None = None,
        timeout_seconds: int = 1800,
        agent_type: str | None = None,
        operation_type: str | None = None,
        cwd: str | None = None,
        env_vars: dict[str, str] | None = None,
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
        fallback_model: str | None = None,
        reasoning_budget: int | None = None,
        max_buffer_size: int | None = None,
        betas: list[str] | None = None,
        user: str | None = None,
        permission_prompt_tool_name: str | None = None,
        enable_file_checkpointing: bool = False,
        sandbox: dict[str, Any] | None = None,
        owner_type: str | None = None,
        owner_id: str | None = None,
        owner_label: str | None = None,
        browser_slot_parent_owner_type: str | None = None,
        browser_slot_parent_run_id: str | None = None,
        requires_live_browser: bool = False,
    ) -> str:
        """
        Add an agent task to the queue.

        Args:
            prompt: The prompt to send to the agent
            system_prompt: Optional system prompt
            timeout_seconds: Execution timeout
            agent_type: Type of agent (explorer, planner, etc.)
            operation_type: Type of operation (exploration, prd, etc.)
            cwd: Working directory for CLI execution (defaults to project root)
            env_vars: API credentials to pass to worker process
            allowed_tools: Claude allowed tools for this task
            tools: Base tool availability set
            disallowed_tools: Tools hidden from this task
            permission_mode: Claude permission mode
            strict_mcp_config: Whether to isolate MCP config to the run-local file
            max_budget_usd: Optional spend cap
            task_budget: Optional token budget
            include_hook_events: Whether hook events should be emitted
            include_partial_messages: Whether partial message chunks should be emitted
            output_format: Optional native SDK output contract
            resume_session_id: Optional Claude session to resume
            continue_conversation: Continue the most recent conversation when supported
            max_turns: Optional maximum turn count
            fallback_model: Optional fallback model for overloaded/unavailable primary models
            reasoning_budget: Optional SDK thinking token budget
            max_buffer_size: Optional SDK stream buffer limit
            betas: Optional SDK/API beta headers
            user: Optional SDK user identifier
            permission_prompt_tool_name: Optional SDK permission prompt tool
            enable_file_checkpointing: Enable SDK file checkpoints
            sandbox: Optional SDK sandbox settings
            requires_live_browser: Whether this task requires a headed/VNC browser worker

        Returns:
            Task ID for tracking
        """
        redis = await self._ensure_connected()

        task = AgentTask(
            id=f"agent-{uuid.uuid4().hex[:12]}",
            prompt=prompt,
            system_prompt=system_prompt,
            timeout_seconds=timeout_seconds,
            agent_type=agent_type,
            operation_type=operation_type,
            cwd=cwd,
            env_vars=env_vars,
            allowed_tools=allowed_tools,
            tools=tools,
            disallowed_tools=disallowed_tools,
            permission_mode=permission_mode,
            strict_mcp_config=strict_mcp_config,
            max_budget_usd=max_budget_usd,
            task_budget=task_budget,
            include_hook_events=include_hook_events,
            include_partial_messages=include_partial_messages,
            output_format=output_format,
            resume_session_id=resume_session_id,
            continue_conversation=continue_conversation,
            max_turns=max_turns,
            fallback_model=fallback_model,
            reasoning_budget=reasoning_budget,
            max_buffer_size=max_buffer_size,
            betas=betas,
            user=user,
            permission_prompt_tool_name=permission_prompt_tool_name,
            enable_file_checkpointing=enable_file_checkpointing,
            sandbox=sandbox,
            owner_type=owner_type,
            owner_id=owner_id,
            owner_label=owner_label,
            browser_slot_parent_owner_type=browser_slot_parent_owner_type,
            browser_slot_parent_run_id=browser_slot_parent_run_id,
            requires_live_browser=requires_live_browser,
        )

        # Atomic store + enqueue
        async with redis.pipeline(transaction=True) as pipe:
            pipe.hset(self.TASKS_KEY, task.id, json.dumps(task.to_dict()))
            pipe.rpush(self.QUEUE_KEY, task.id)
            await pipe.execute()

        self._emit_agent_run_event(
            task,
            event_type="queued",
            message="Agent task queued.",
            payload={
                "agent_type": agent_type,
                "operation_type": operation_type,
                "timeout_seconds": timeout_seconds,
                "browser_slot_parent_owner_type": browser_slot_parent_owner_type,
                "browser_slot_parent_run_id": browser_slot_parent_run_id,
                "requires_live_browser": requires_live_browser,
            },
        )
        logger.info(
            f"Enqueued agent task {task.id} (type={agent_type}, op={operation_type})"
        )
        return task.id

    async def get_task(self, task_id: str) -> AgentTask | None:
        """Get task details by ID."""
        redis = await self._ensure_connected()
        task_data = await redis.hget(self.TASKS_KEY, task_id)
        if task_data:
            return AgentTask.from_dict(json.loads(task_data))
        return None

    async def update_heartbeat(
        self, task_id: str, progress: dict[str, Any] | None = None
    ) -> None:
        """Update the heartbeat timestamp for a running task.

        Args:
            task_id: Task ID
            progress: Optional progress dict (e.g. tool_calls count, last_tool name)
        """
        redis = await self._ensure_connected()
        heartbeat_data = json.dumps(
            {
                "ts": datetime.utcnow().isoformat(),
                "progress": progress or {},
            }
        )
        await redis.set(
            f"{self.HEARTBEAT_PREFIX}{task_id}",
            heartbeat_data,
            ex=120,  # Expire after 2 minutes if not refreshed
        )

    async def check_heartbeat(self, task_id: str, max_stale_seconds: int = 120) -> bool:
        """Check if a task's heartbeat is still fresh.

        Returns True if heartbeat is fresh (worker is alive), False if stale.
        Handles both legacy (bare timestamp string) and new (JSON dict) formats.
        """
        redis = await self._ensure_connected()
        heartbeat = await redis.get(f"{self.HEARTBEAT_PREFIX}{task_id}")
        if not heartbeat:
            return False
        try:
            # Try JSON format first (new)
            try:
                data = json.loads(heartbeat)
                ts_str = data.get("ts", heartbeat)
            except (json.JSONDecodeError, TypeError):
                ts_str = heartbeat  # Legacy: bare timestamp string
            last_beat = datetime.fromisoformat(ts_str)
            age = (datetime.utcnow() - last_beat).total_seconds()
            return age < max_stale_seconds
        except (ValueError, TypeError):
            return False

    async def check_worker_heartbeat(self, worker_id: str) -> bool:
        """Return whether a worker-level heartbeat key is still present."""
        if not worker_id:
            return False
        redis = await self._ensure_connected()
        heartbeat = await redis.get(f"{self.WORKER_HEARTBEAT_PREFIX}{worker_id}")
        return bool(heartbeat)

    async def get_task_progress(self, task_id: str) -> dict[str, Any] | None:
        """Get live progress data from a task's heartbeat.

        Returns the progress dict if available, or None.
        """
        heartbeat_data = await self.get_task_heartbeat(task_id)
        if not heartbeat_data:
            return None
        progress = heartbeat_data.get("progress")
        return progress if isinstance(progress, dict) else None

    async def get_task_heartbeat(self, task_id: str) -> dict[str, Any] | None:
        """Return parsed task heartbeat data, including timestamp and progress."""
        redis = await self._ensure_connected()
        heartbeat = await redis.get(f"{self.HEARTBEAT_PREFIX}{task_id}")
        if not heartbeat:
            return None
        try:
            data = json.loads(heartbeat)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            return {"ts": heartbeat, "progress": {}}
        return None

    @staticmethod
    def _worker_supports_live_browser() -> bool:
        """Return whether the current worker process can run headed browser work."""
        if os.environ.get("AGENT_WORKER_DISABLE_LIVE_BROWSER", "").lower() in {"1", "true", "yes"}:
            return False
        if os.environ.get("VNC_ENABLED", "").lower() in {"1", "true", "yes"}:
            return True
        return bool(os.environ.get("DISPLAY"))

    async def update_worker_heartbeat(self, worker_id: str, capabilities: dict[str, Any] | None = None) -> None:
        """Update worker-level heartbeat to signal the worker process is alive.

        Called periodically by the worker's main loop (not tied to any specific task).
        """
        redis = await self._ensure_connected()
        payload = {
            "ts": datetime.utcnow().isoformat(),
            "capabilities": capabilities
            if capabilities is not None
            else {"live_browser": self._worker_supports_live_browser()},
        }
        await redis.set(
            f"{self.WORKER_HEARTBEAT_PREFIX}{worker_id}",
            json.dumps(payload),
            ex=self.WORKER_HEARTBEAT_TTL_SECONDS,
        )

    async def worker_count(self) -> int:
        """Count alive workers by counting active worker heartbeat keys."""
        redis = await self._ensure_connected()
        count = 0
        async for _ in redis.scan_iter(f"{self.WORKER_HEARTBEAT_PREFIX}*"):
            count += 1
        return count

    async def worker_capability_summary(self) -> dict[str, Any]:
        """Return aggregate worker heartbeat capability counts."""
        redis = await self._ensure_connected()
        worker_count = 0
        live_browser_worker_count = 0
        workers: list[dict[str, Any]] = []
        async for key in redis.scan_iter(f"{self.WORKER_HEARTBEAT_PREFIX}*"):
            worker_count += 1
            raw = await redis.get(key)
            payload: dict[str, Any] = {}
            if raw:
                try:
                    parsed = json.loads(raw)
                    payload = parsed if isinstance(parsed, dict) else {}
                except (json.JSONDecodeError, TypeError):
                    payload = {}
            capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
            live_browser = bool(capabilities.get("live_browser"))
            if live_browser:
                live_browser_worker_count += 1
            worker_id = str(key).removeprefix(self.WORKER_HEARTBEAT_PREFIX)
            workers.append(
                {
                    "worker_id": worker_id,
                    "live_browser": live_browser,
                    "capabilities": capabilities,
                    "last_seen": payload.get("ts"),
                }
            )

        return {
            "worker_count": worker_count,
            "live_browser_worker_count": live_browser_worker_count,
            "non_live_browser_worker_count": max(0, worker_count - live_browser_worker_count),
            "workers": workers,
        }

    async def wait_for_result(
        self,
        task_id: str,
        timeout: float = 1800.0,
        poll_interval: float = 0.5,
        queued_timeout: float = 120.0,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
        is_cancelled: Callable[[], Any] | None = None,
    ) -> str | None:
        """
        Wait for a task to complete and return result.

        Monitors worker heartbeat to detect dead workers early rather than
        waiting for the full timeout.  Also detects tasks stuck in QUEUED
        state when no workers are alive to pick them up.

        NOTE: Uses polling instead of Redis pub/sub subscription for reliability.
        See submit_result() for the complementary publish that is kept for future use.

        Args:
            task_id: Task ID to wait for
            timeout: Maximum wait time in seconds
            poll_interval: Poll interval in seconds
            queued_timeout: Max seconds to stay in QUEUED before failing (default 120)
            on_progress: Optional callback receiving progress dicts during RUNNING

        Returns:
            Task result string or None if timeout/failed
        """
        redis = await self._ensure_connected()
        start_time = datetime.utcnow()
        paused_started_at: datetime | None = None
        paused_total_seconds = 0.0
        stale_heartbeat_checks = 0
        queued_warning_logged = False
        queued_busy_warning_logged = False
        last_progress_log = 0.0  # timestamp of last progress log
        last_progress_payload: dict[str, Any] | None = None

        while True:
            if is_cancelled:
                try:
                    cancelled = is_cancelled()
                    if hasattr(cancelled, "__await__"):
                        cancelled = await cancelled
                except Exception as exc:
                    logger.debug("Agent queue cancellation check failed for %s: %s", task_id, exc)
                    cancelled = False
                if cancelled:
                    await self.cancel_task(task_id)
                    raise RuntimeError("Task cancelled")

            now = datetime.utcnow()
            active_elapsed = (now - start_time).total_seconds() - paused_total_seconds
            if paused_started_at is not None:
                active_elapsed -= (now - paused_started_at).total_seconds()
            if active_elapsed >= timeout:
                break

            task = await self.get_task(task_id)
            if task:
                if task.status == AgentTaskStatus.PAUSED:
                    if paused_started_at is None:
                        paused_started_at = now
                elif paused_started_at is not None:
                    paused_total_seconds += (now - paused_started_at).total_seconds()
                    paused_started_at = None

                if task.status == AgentTaskStatus.COMPLETED:
                    return task.result
                elif task.status in (
                    AgentTaskStatus.FAILED,
                    AgentTaskStatus.TIMEOUT,
                    AgentTaskStatus.CANCELLED,
                ):
                    error_msg = task.error or f"Task {task.status.value}"
                    raise RuntimeError(error_msg)

                elapsed = max(0.0, active_elapsed)

                # --- QUEUED state monitoring ---
                if task.status == AgentTaskStatus.QUEUED:
                    if elapsed >= 30 and not queued_warning_logged:
                        workers = await self.worker_count()
                        queue_len = await self.queue_length()
                        running = await self.running_count()
                        logger.warning(
                            f"Task {task_id} still QUEUED after 30s — "
                            f"workers_alive={workers}, queue_depth={queue_len}, running={running}"
                        )
                        queued_warning_logged = True

                    if elapsed >= queued_timeout and not queued_busy_warning_logged:
                        workers = await self.worker_count()
                        queue_len = await self.queue_length()
                        running = await self.running_count()
                        capabilities = await self.worker_capability_summary()
                        live_workers = int(capabilities.get("live_browser_worker_count") or 0)
                        if task.requires_live_browser and workers > 0 and live_workers == 0:
                            await self.cancel_task(task_id)
                            raise RuntimeError(
                                "No live-browser-capable agent worker is available. "
                                "Restart the dashboard stack so the supervisor-managed agent_worker runs with DISPLAY=:99, "
                                "or start a worker profile that advertises live_browser=true."
                            )
                        health = await self.get_worker_health()
                        alive_running_tasks = int(health.get("alive_tasks") or 0)
                        # Cancel only when there is no evidence of worker capacity
                        # or in-flight task heartbeat. A busy worker can lose its
                        # worker-level heartbeat briefly while the task heartbeat
                        # remains fresh.
                        if workers == 0 and running == 0 and alive_running_tasks == 0:
                            await self.cancel_task(task_id)
                            raise RuntimeError(
                                f"Task stuck in QUEUED for {elapsed:.0f}s — no agent workers are alive. "
                                f"Check that the agent_worker process is running (supervisord)."
                            )
                        logger.warning(
                            f"Task {task_id} still QUEUED after {elapsed:.0f}s — "
                            f"worker_processes={workers}, live_browser_workers={live_workers}, running={running}, "
                            f"alive_running_tasks={alive_running_tasks}, queue_depth={queue_len}; "
                            "continuing to wait."
                        )
                        queued_busy_warning_logged = True

                # --- RUNNING state monitoring ---
                if task.status in (
                    AgentTaskStatus.RUNNING,
                    AgentTaskStatus.PAUSED,
                    AgentTaskStatus.CANCEL_REQUESTED,
                ):
                    progress = await self.get_task_progress(task_id)
                    if progress and progress != last_progress_payload:
                        last_progress_payload = progress
                        if on_progress:
                            try:
                                on_progress(progress)
                            except Exception:
                                pass

                    # Log progress every 30s
                    if elapsed - last_progress_log >= 30:
                        if progress:
                            tool_calls = progress.get("tool_calls", 0)
                            last_tool = progress.get("last_tool", "")
                            interactions = progress.get("interactions", 0)
                            # Strip MCP prefix for readability
                            short_tool = (
                                last_tool.rsplit("__", 1)[-1]
                                if "__" in last_tool
                                else last_tool
                            )
                            logger.info(
                                f"Task {task_id} progress: {tool_calls} tool calls, "
                                f"{interactions} interactions, last_tool={short_tool}"
                            )
                        last_progress_log = elapsed

                    # Check heartbeat (after initial grace period). A paused
                    # task still has an alive worker heartbeat even though the
                    # child process is SIGSTOPed.
                    if elapsed > 60:
                        is_alive = await self.check_heartbeat(task_id)
                        if not is_alive:
                            stale_heartbeat_checks += 1
                            # Require 5 consecutive stale checks (~7.5s) to avoid false positives
                            if stale_heartbeat_checks >= 5:
                                # Final re-check: worker may have submitted results between stale checks
                                final_task = await self.get_task(task_id)
                                if (
                                    final_task
                                    and final_task.status == AgentTaskStatus.COMPLETED
                                ):
                                    return final_task.result
                                elif final_task and final_task.status in (
                                    AgentTaskStatus.FAILED,
                                    AgentTaskStatus.TIMEOUT,
                                    AgentTaskStatus.CANCELLED,
                                ):
                                    error_msg = (
                                        final_task.error
                                        or f"Task {final_task.status.value}"
                                    )
                                    raise RuntimeError(error_msg)

                                logger.warning(
                                    f"Task {task_id} worker appears dead (no heartbeat after {stale_heartbeat_checks} checks). Marking as failed."
                                )
                                task.status = AgentTaskStatus.FAILED
                                task.completed_at = datetime.utcnow()
                                task.error = (
                                    "Worker heartbeat lost - worker may have crashed"
                                )
                                await redis.hset(
                                    self.TASKS_KEY, task_id, json.dumps(task.to_dict())
                                )
                                await redis.srem(self.RUNNING_KEY, task_id)
                                self._emit_agent_run_event(
                                    task,
                                    event_type="recovery",
                                    level="error",
                                    message=task.error,
                                    payload={"status": task.status.value},
                                )
                                raise RuntimeError(task.error)
                        else:
                            stale_heartbeat_checks = 0

            await asyncio.sleep(poll_interval)

        # Timeout - cancel the task
        await self.cancel_task(task_id)
        raise asyncio.TimeoutError(f"Agent task timed out after {timeout}s")

    async def pause_task(self, task_id: str) -> bool:
        """Pause a queued or running task.

        Queued tasks are removed from the FIFO and can be requeued on resume.
        Running tasks remain in the running set so the owning worker keeps
        responsibility for resuming or cancelling the child process.
        """
        redis = await self._ensure_connected()
        task = await self.get_task(task_id)
        if not task or task.status not in (
            AgentTaskStatus.QUEUED,
            AgentTaskStatus.RUNNING,
        ):
            return False

        if task.status == AgentTaskStatus.QUEUED:
            await redis.lrem(self.QUEUE_KEY, 0, task_id)
        task.status = AgentTaskStatus.PAUSED
        task.telemetry = {
            **(task.telemetry or {}),
            "pause_requested_at": datetime.utcnow().isoformat(),
            "paused_from": task.worker_id and "running" or "queued",
        }

        async with redis.pipeline(transaction=True) as pipe:
            pipe.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
            pipe.set(
                f"{self.PAUSE_PREFIX}{task_id}",
                "1",
                ex=max(task.timeout_seconds + 86400, 86400),
            )
            await pipe.execute()

        logger.info(f"Paused agent task {task_id}")
        self._emit_agent_run_event(
            task,
            event_type="pause",
            message="Agent task pause requested.",
            payload={"paused_from": task.telemetry.get("paused_from")},
        )
        return True

    async def resume_task(self, task_id: str) -> bool:
        """Resume a paused task."""
        redis = await self._ensure_connected()
        task = await self.get_task(task_id)
        if not task or task.status != AgentTaskStatus.PAUSED:
            return False

        was_running = bool(
            task.worker_id
            and task.started_at
            and await redis.sismember(self.RUNNING_KEY, task_id)
        )
        task.status = AgentTaskStatus.RUNNING if was_running else AgentTaskStatus.QUEUED
        task.telemetry = {
            **(task.telemetry or {}),
            "resume_requested_at": datetime.utcnow().isoformat(),
        }

        async with redis.pipeline(transaction=True) as pipe:
            pipe.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
            pipe.delete(f"{self.PAUSE_PREFIX}{task_id}")
            if not was_running:
                pipe.rpush(self.QUEUE_KEY, task_id)
            await pipe.execute()

        logger.info(f"Resumed agent task {task_id} as {task.status.value}")
        self._emit_agent_run_event(
            task,
            event_type="resume",
            message=f"Agent task resumed as {task.status.value}.",
            payload={"status": task.status.value},
        )
        return True

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a queued or running task."""
        redis = await self._ensure_connected()

        # Remove from queue if still queued
        await redis.lrem(self.QUEUE_KEY, 0, task_id)

        task = await self.get_task(task_id)
        if task and task.status in (
            AgentTaskStatus.QUEUED,
            AgentTaskStatus.RUNNING,
            AgentTaskStatus.PAUSED,
            AgentTaskStatus.CANCEL_REQUESTED,
        ):
            previous_status = task.status.value
            is_running = await redis.sismember(self.RUNNING_KEY, task_id)
            await redis.set(f"{self.CANCEL_PREFIX}{task_id}", "1", ex=3600)
            await redis.delete(f"{self.PAUSE_PREFIX}{task_id}")

            if is_running and task.status != AgentTaskStatus.QUEUED:
                task.status = AgentTaskStatus.CANCEL_REQUESTED
                task.error = "Task cancellation requested"
                task.telemetry = {
                    **(task.telemetry or {}),
                    "cancel_requested_at": datetime.utcnow().isoformat(),
                    "cancelled_from": previous_status,
                }
                await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                logger.info(f"Requested cancellation for running agent task {task_id}")
            else:
                task.status = AgentTaskStatus.CANCELLED
                task.completed_at = datetime.utcnow()
                task.error = "Task cancelled"
                await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                await redis.srem(self.RUNNING_KEY, task_id)
                logger.info(f"Cancelled queued agent task {task_id}")

            self._emit_agent_run_event(
                task,
                event_type="cancel",
                message="Agent task cancellation requested.",
                payload={"cancelled_from": previous_status},
            )
            return True
        return False

    async def is_cancelled(self, task_id: str) -> bool:
        """Check if a task has been cancelled."""
        redis = await self._ensure_connected()
        return await redis.exists(f"{self.CANCEL_PREFIX}{task_id}") > 0

    async def is_paused(self, task_id: str) -> bool:
        """Check if a task has been paused."""
        redis = await self._ensure_connected()
        return await redis.exists(f"{self.PAUSE_PREFIX}{task_id}") > 0

    # ==========================================
    # Consumer Methods (Agent Worker)
    # ==========================================

    async def dequeue_task(self, timeout: int = 30) -> AgentTask | None:
        """
        Get the next task from the queue (blocking).

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            AgentTask or None if timeout
        """
        redis = await self._ensure_connected()

        # Blocking pop from list (FIFO)
        result = await redis.blpop(self.QUEUE_KEY, timeout=timeout)

        if result:
            _, task_id = result

            try:
                # Get and update task data
                task_data = await redis.hget(self.TASKS_KEY, task_id)
                if task_data:
                    task = AgentTask.from_dict(json.loads(task_data))
                    if task.status == AgentTaskStatus.PAUSED:
                        logger.info(
                            f"Worker {self._worker_id} skipped paused task {task_id}"
                        )
                        return None
                    if task.status != AgentTaskStatus.QUEUED:
                        logger.info(
                            f"Worker {self._worker_id} skipped task {task_id} in status {task.status.value}"
                        )
                        return None

                    if task.requires_live_browser and not self._worker_supports_live_browser():
                        await redis.rpush(self.QUEUE_KEY, task_id)
                        logger.info(
                            "Worker %s skipped live-browser task %s because this worker has no display/VNC capability",
                            self._worker_id,
                            task_id,
                        )
                        await asyncio.sleep(1)
                        return None

                    invalid = await self._queued_task_invalid_reason(task)
                    if invalid:
                        status, _, message = invalid
                        await self._finish_task_for_cleanup(
                            redis,
                            task,
                            status,
                            message,
                        )
                        logger.warning(
                            "Worker %s skipped invalid queued task %s: %s",
                            self._worker_id,
                            task_id,
                            message,
                        )
                        return None

                    task.status = AgentTaskStatus.RUNNING
                    task.worker_id = self._worker_id
                    task.started_at = datetime.utcnow()

                    # Use pipeline for atomic state transition
                    async with redis.pipeline(transaction=True) as pipe:
                        pipe.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                        pipe.sadd(self.RUNNING_KEY, task_id)
                        await pipe.execute()

                    logger.info(f"Worker {self._worker_id} dequeued task {task_id}")
                    return task
                else:
                    logger.warning(f"Task {task_id} dequeued but not found in hash")
                    return None
            except Exception as e:
                logger.error(
                    f"Failed after dequeue for {task_id}: {e}. Re-pushing to queue."
                )
                try:
                    await redis.lpush(self.QUEUE_KEY, task_id)
                except Exception as re_err:
                    logger.error(f"Failed to re-push task {task_id}: {re_err}")
                return None

        return None

    async def submit_result(
        self,
        task_id: str,
        result: str,
        success: bool = True,
        error: str | None = None,
        telemetry: dict[str, Any] | None = None,
    ) -> None:
        """
        Submit result for a completed task.

        Args:
            task_id: Task ID
            result: Agent output text
            success: Whether execution succeeded
            error: Error message if failed
        """
        redis = await self._ensure_connected()

        task_data = await redis.hget(self.TASKS_KEY, task_id)
        if task_data:
            task = AgentTask.from_dict(json.loads(task_data))

            # Don't overwrite terminal states set by cancellation/cleanup.
            if task.status in (AgentTaskStatus.CANCELLED, AgentTaskStatus.TIMEOUT) or (
                task.status == AgentTaskStatus.FAILED and task.completed_at is not None
            ):
                logger.info(
                    f"Task {task_id} is already {task.status.value}, not overwriting with {'completed' if success else 'failed'}"
                )
                await redis.srem(self.RUNNING_KEY, task_id)
                return
            if task.status == AgentTaskStatus.PAUSED:
                logger.info(
                    f"Task {task_id} is paused, deferring {'completed' if success else 'failed'} result"
                )
                while await self.is_paused(task_id):
                    await asyncio.sleep(0.5)
                task = await self.get_task(task_id)
                if not task or task.status == AgentTaskStatus.CANCELLED:
                    await redis.srem(self.RUNNING_KEY, task_id)
                    return

            if task.status == AgentTaskStatus.CANCEL_REQUESTED and not success:
                task.status = AgentTaskStatus.CANCELLED
            else:
                task.status = (
                    AgentTaskStatus.COMPLETED if success else AgentTaskStatus.FAILED
                )
            task.completed_at = datetime.utcnow()
            task.result = result
            task.error = error
            if telemetry:
                task.telemetry = telemetry

            # Atomic state transition with retry
            for attempt in range(1, 4):
                try:
                    async with redis.pipeline(transaction=True) as pipe:
                        pipe.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                        pipe.srem(self.RUNNING_KEY, task_id)
                        pipe.delete(f"{self.CANCEL_PREFIX}{task_id}")
                        await pipe.execute()
                    break
                except Exception as e:
                    if attempt < 3:
                        logger.warning(
                            f"submit_result attempt {attempt} failed for {task_id}: {e}"
                        )
                        await asyncio.sleep(0.5 * attempt)
                        redis = await self._ensure_connected()
                    else:
                        logger.error(f"submit_result failed after 3 attempts: {e}")
                        raise

            # Non-critical notification
            try:
                await redis.publish(f"{self.CHANNEL_KEY}:{task_id}", "done")
            except Exception:
                pass

            logger.info(f"Task {task_id} {'completed' if success else 'failed'}")

    # ==========================================
    # Monitoring Methods
    # ==========================================

    async def queue_length(self) -> int:
        """Get current queue length."""
        redis = await self._ensure_connected()
        return await redis.llen(self.QUEUE_KEY)

    async def running_count(self) -> int:
        """Get count of running tasks."""
        redis = await self._ensure_connected()
        return await redis.scard(self.RUNNING_KEY)

    async def get_metrics(self) -> dict:
        """Get Redis-backed agent queue metrics."""
        redis = await self._ensure_connected()
        all_tasks = await redis.hgetall(self.TASKS_KEY)
        by_status: dict[str, int] = {}
        oldest_queued_age_seconds: float | None = None
        stale_running = 0
        now = datetime.utcnow()

        for task_id, task_data_str in all_tasks.items():
            try:
                task = AgentTask.from_dict(json.loads(task_data_str))
            except Exception:
                continue

            by_status[task.status.value] = by_status.get(task.status.value, 0) + 1

            if task.status == AgentTaskStatus.QUEUED:
                age = (now - task.created_at).total_seconds()
                if oldest_queued_age_seconds is None or age > oldest_queued_age_seconds:
                    oldest_queued_age_seconds = age
            elif task.status in (
                AgentTaskStatus.RUNNING,
                AgentTaskStatus.CANCEL_REQUESTED,
            ) and not await self.check_heartbeat(task_id):
                stale_running += 1

        capabilities = await self.worker_capability_summary()

        return {
            "queue_length": await self.queue_length(),
            "running": await self.running_count(),
            "workers_alive": capabilities["worker_count"],
            "live_browser_workers_alive": capabilities["live_browser_worker_count"],
            "non_live_browser_workers_alive": capabilities["non_live_browser_worker_count"],
            "by_status": by_status,
            "stale_running": stale_running,
            "oldest_queued_age_seconds": oldest_queued_age_seconds,
        }

    @staticmethod
    def _task_live_for_capacity(
        task: AgentTask | None,
        *,
        heartbeat_alive: bool,
        owner_state: dict[str, Any] | None,
    ) -> bool:
        """Return whether a running-set task should consume live capacity."""
        if not task:
            return False
        if owner_state and owner_state.get("terminal"):
            return False
        if task.status in (
            AgentTaskStatus.RUNNING,
            AgentTaskStatus.CANCEL_REQUESTED,
        ):
            return heartbeat_alive
        if task.status == AgentTaskStatus.PAUSED:
            return bool(owner_state and not owner_state.get("terminal"))
        return False

    async def get_running_task_summaries(self) -> list[dict[str, Any]]:
        """Return sanitized summaries for currently running tasks."""
        redis = await self._ensure_connected()
        running_ids = sorted(await redis.smembers(self.RUNNING_KEY))
        summaries: list[dict[str, Any]] = []

        for task_id in running_ids:
            task = await self.get_task(task_id)
            progress = await self.get_task_progress(task_id) or {}
            heartbeat_alive = await self.check_heartbeat(task_id)
            owner_state = await self._get_owner_state(task) if task else None

            progress_summary = {
                key: progress.get(key)
                for key in (
                    "phase",
                    "activity_label",
                    "status",
                    "message",
                    "current_stage",
                    "tool_calls",
                    "browser_tool_calls",
                    "interactions",
                    "last_tool",
                    "last_tool_label",
                )
                if key in progress and progress.get(key) is not None
            }
            live_for_capacity = self._task_live_for_capacity(
                task,
                heartbeat_alive=heartbeat_alive,
                owner_state=owner_state,
            )

            summaries.append(
                {
                    "id": task_id,
                    "status": (
                        task.status.value if task else AgentTaskStatus.RUNNING.value
                    ),
                    "worker_id": task.worker_id if task else None,
                    "agent_type": task.agent_type if task else None,
                    "operation_type": task.operation_type if task else None,
                    "created_at": (
                        task.created_at.isoformat()
                        if task and task.created_at
                        else None
                    ),
                    "started_at": (
                        task.started_at.isoformat()
                        if task and task.started_at
                        else None
                    ),
                    "timeout_seconds": task.timeout_seconds if task else None,
                    "heartbeat_alive": heartbeat_alive,
                    "owner_type": task.owner_type if task else None,
                    "owner_id": task.owner_id if task else None,
                    "owner_label": task.owner_label if task else None,
                    "owner_status": owner_state.get("status") if owner_state else None,
                    "owner_terminal": bool(owner_state and owner_state.get("terminal")),
                    "live": live_for_capacity,
                    "orphaned": not live_for_capacity,
                    "progress": progress_summary,
                }
            )

        return summaries

    async def get_worker_health(self) -> dict:
        """Check if any agent worker is alive using worker-level heartbeats."""
        try:
            redis = await self._ensure_connected()
            running_ids = await redis.smembers(self.RUNNING_KEY)

            # Count worker-level heartbeats (most reliable signal)
            capability_summary = await self.worker_capability_summary()
            worker_alive_count = int(capability_summary.get("worker_count") or 0)

            # Also count task-level heartbeats for running tasks
            alive_task_count = 0
            for task_id in running_ids:
                if await self.check_heartbeat(task_id):
                    alive_task_count += 1

            return {
                "workers_alive": worker_alive_count > 0,
                "worker_count": worker_alive_count,
                "live_browser_worker_count": capability_summary.get("live_browser_worker_count", 0),
                "non_live_browser_worker_count": capability_summary.get("non_live_browser_worker_count", 0),
                "worker_capabilities": capability_summary.get("workers", []),
                "running_tasks": len(running_ids),
                "alive_tasks": alive_task_count,
            }
        except Exception as e:
            logger.warning(f"Failed to check worker health: {e}")
            return {
                "workers_alive": False,
                "worker_count": 0,
                "running_tasks": 0,
                "alive_tasks": 0,
                "error": str(e),
            }

    async def _get_owner_state(self, task: AgentTask) -> dict[str, Any] | None:
        """Return lifecycle state for the task owner, if one is known."""
        if not task.owner_type or not task.owner_id:
            return None

        terminal_statuses = {"passed", "completed", "failed", "cancelled", "error", "stopped"}
        try:
            from sqlmodel import Session

            from orchestrator.api.db import engine
            from orchestrator.api.models_db import (
                AgentRun,
                AutoPilotSession,
                AutonomousAgentWorkItem,
                AutonomousMission,
                BrowserAuthSession,
                PrdGenerationResult,
                TestRun,
            )

            with Session(engine) as session:
                if task.owner_type == "autopilot":
                    owner = session.get(AutoPilotSession, task.owner_id)
                elif task.owner_type == "agent_run":
                    owner = session.get(AgentRun, task.owner_id)
                elif task.owner_type == "test_run":
                    owner = session.get(TestRun, task.owner_id)
                elif task.owner_type == "autonomous_work_item":
                    owner = session.get(AutonomousAgentWorkItem, task.owner_id)
                    if owner and owner.mission_id:
                        mission = session.get(AutonomousMission, owner.mission_id)
                        if mission and mission.status in {"cancelled", "completed"}:
                            return {
                                "type": task.owner_type,
                                "id": task.owner_id,
                                "label": task.owner_label,
                                "status": mission.status,
                                "terminal": True,
                            }
                elif task.owner_type == "prd_generation":
                    try:
                        owner = session.get(PrdGenerationResult, int(task.owner_id))
                    except (TypeError, ValueError):
                        owner = None
                elif task.owner_type == "browser_auth_session":
                    owner = session.get(BrowserAuthSession, task.owner_id)
                else:
                    owner = None

                if not owner:
                    return {
                        "type": task.owner_type,
                        "id": task.owner_id,
                        "label": task.owner_label,
                        "status": "missing",
                        "terminal": True,
                    }

                status = str(getattr(owner, "status", "") or "unknown")
                return {
                    "type": task.owner_type,
                    "id": task.owner_id,
                    "label": task.owner_label,
                    "status": status,
                    "terminal": status in terminal_statuses,
                }
        except Exception as exc:
            logger.debug("Failed to resolve owner for agent task %s: %s", task.id, exc)
            return None

    def _task_belongs_to_test_run(self, task: AgentTask, run_id: str) -> bool:
        return (
            (task.owner_type == "test_run" and task.owner_id == run_id)
            or (
                task.browser_slot_parent_owner_type == "test_run"
                and task.browser_slot_parent_run_id == run_id
            )
        )

    async def cancel_tasks_for_test_run(self, run_id: str) -> dict[str, Any]:
        """Cancel queued/running/paused agent tasks associated with a test run."""
        redis = await self._ensure_connected()
        all_tasks = await redis.hgetall(self.TASKS_KEY)
        summary: dict[str, Any] = {
            "run_id": run_id,
            "matched": 0,
            "cancelled": 0,
            "task_ids": [],
        }
        cancellable = {
            AgentTaskStatus.QUEUED,
            AgentTaskStatus.RUNNING,
            AgentTaskStatus.PAUSED,
            AgentTaskStatus.CANCEL_REQUESTED,
        }

        for task_id, task_data_str in all_tasks.items():
            try:
                task = AgentTask.from_dict(json.loads(task_data_str))
            except Exception:
                continue
            if not self._task_belongs_to_test_run(task, run_id):
                continue
            summary["matched"] += 1
            if task.status not in cancellable:
                continue
            if await self.cancel_task(task_id):
                summary["cancelled"] += 1
                summary["task_ids"].append(task_id)

        return summary

    async def _finish_task_for_cleanup(
        self,
        redis,
        task: AgentTask,
        status: AgentTaskStatus,
        error: str,
    ) -> None:
        """Move a queued/running task to a terminal state and signal any worker to stop."""
        now = datetime.utcnow()
        task.status = status
        task.completed_at = now
        task.error = error
        await redis.hset(self.TASKS_KEY, task.id, json.dumps(task.to_dict()))
        await redis.lrem(self.QUEUE_KEY, 0, task.id)
        await redis.srem(self.RUNNING_KEY, task.id)
        await redis.set(f"{self.CANCEL_PREFIX}{task.id}", "1", ex=3600)
        await redis.delete(f"{self.PAUSE_PREFIX}{task.id}")
        await redis.delete(f"{self.HEARTBEAT_PREFIX}{task.id}")
        self._emit_agent_run_event(
            task,
            event_type="recovery",
            level="warning" if status != AgentTaskStatus.CANCELLED else "info",
            message=error,
            payload={"status": status.value},
        )

    async def fail_stale_running_task(self, task_id: str, error: str) -> bool:
        """Move a stale running task to FAILED and signal any worker to stop."""
        redis = await self._ensure_connected()
        task = await self.get_task(task_id)
        if not task:
            await redis.srem(self.RUNNING_KEY, task_id)
            return False
        if task.status not in (
            AgentTaskStatus.RUNNING,
            AgentTaskStatus.CANCEL_REQUESTED,
        ):
            return False
        await self._finish_task_for_cleanup(redis, task, AgentTaskStatus.FAILED, error)
        return True

    def _stale_ownerless_queue_minutes(self) -> int:
        raw = os.environ.get("AGENT_QUEUE_STALE_OWNERLESS_MINUTES", "")
        try:
            return max(1, int(raw)) if raw else self.DEFAULT_STALE_OWNERLESS_QUEUE_MINUTES
        except ValueError:
            return self.DEFAULT_STALE_OWNERLESS_QUEUE_MINUTES

    def _task_age_minutes(self, task: AgentTask, now: datetime | None = None) -> float:
        reference = now or datetime.utcnow()
        return (
            (reference - task.created_at).total_seconds() / 60
            if task.created_at
            else 0.0
        )

    def _is_stale_ownerless_queued(
        self,
        task: AgentTask,
        now: datetime | None = None,
        max_age_minutes: int | None = None,
    ) -> bool:
        if task.status != AgentTaskStatus.QUEUED:
            return False
        if task.owner_type or task.owner_id:
            return False
        age_limit = (
            max_age_minutes
            if max_age_minutes is not None
            else self._stale_ownerless_queue_minutes()
        )
        return self._task_age_minutes(task, now) > max(1, int(age_limit))

    async def _queued_task_invalid_reason(
        self,
        task: AgentTask,
        now: datetime | None = None,
        max_age_minutes: int | None = None,
    ) -> tuple[AgentTaskStatus, str, str] | None:
        owner_state = await self._get_owner_state(task)
        if owner_state and owner_state.get("terminal"):
            owner_status = owner_state.get("status")
            status = (
                AgentTaskStatus.CANCELLED
                if owner_status == "cancelled"
                else AgentTaskStatus.FAILED
            )
            return (
                status,
                "terminal_owner",
                f"Agent task stopped because owner {task.owner_type}:{task.owner_id} is {owner_status}",
            )

        if self._is_stale_ownerless_queued(task, now, max_age_minutes):
            return (
                AgentTaskStatus.CANCELLED,
                "stale_ownerless_queued",
                (
                    "Stale ownerless queued task cancelled so linked agent runs "
                    "can continue"
                ),
            )

        return None

    async def cleanup_orphaned_and_stale_tasks(
        self, max_age_minutes: int = 45
    ) -> dict[str, int]:
        """Clean tasks whose worker, owner, or timeout state is no longer valid."""
        redis = await self._ensure_connected()
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=max_age_minutes)
        counts = {
            "cancelled_orphaned": 0,
            "timed_out": 0,
            "terminal_owner": 0,
            "orphaned_queued": 0,
            "stale_ownerless_queued": 0,
            "missing_task_refs": 0,
            "skipped_active": 0,
        }

        running_ids = await redis.smembers(self.RUNNING_KEY)
        for task_id in running_ids:
            task = await self.get_task(task_id)
            if not task:
                await redis.srem(self.RUNNING_KEY, task_id)
                counts["missing_task_refs"] += 1
                continue

            if task.status == AgentTaskStatus.PAUSED:
                owner_state = await self._get_owner_state(task)
                if owner_state and owner_state.get("terminal"):
                    owner_status = owner_state.get("status")
                    status = (
                        AgentTaskStatus.CANCELLED
                        if owner_status == "cancelled"
                        else AgentTaskStatus.FAILED
                    )
                    await self._finish_task_for_cleanup(
                        redis,
                        task,
                        status,
                        f"Agent task stopped because owner {task.owner_type}:{task.owner_id} is {owner_status}",
                    )
                    counts["terminal_owner"] += 1
                else:
                    counts["skipped_active"] += 1
                continue

            if task.status not in (
                AgentTaskStatus.RUNNING,
                AgentTaskStatus.CANCEL_REQUESTED,
            ):
                await redis.srem(self.RUNNING_KEY, task_id)
                counts["cancelled_orphaned"] += 1
                continue

            owner_state = await self._get_owner_state(task)
            owner_terminal = bool(owner_state and owner_state.get("terminal"))
            started_at = task.started_at or task.created_at
            elapsed_seconds = (now - started_at).total_seconds() if started_at else 0
            task_timeout = max(1, int(task.timeout_seconds or 1800))
            heartbeat_alive = await self.check_heartbeat(task_id)

            if owner_terminal:
                owner_status = owner_state.get("status") if owner_state else "terminal"
                status = (
                    AgentTaskStatus.CANCELLED
                    if owner_status == "cancelled"
                    else AgentTaskStatus.FAILED
                )
                await self._finish_task_for_cleanup(
                    redis,
                    task,
                    status,
                    f"Agent task stopped because owner {task.owner_type}:{task.owner_id} is {owner_status}",
                )
                counts["terminal_owner"] += 1
            elif elapsed_seconds > task_timeout:
                await self._finish_task_for_cleanup(
                    redis,
                    task,
                    AgentTaskStatus.TIMEOUT,
                    f"Agent task timed out after {task_timeout} seconds",
                )
                counts["timed_out"] += 1
            elif task.started_at and task.started_at < cutoff:
                await self._finish_task_for_cleanup(
                    redis,
                    task,
                    AgentTaskStatus.TIMEOUT,
                    f"Agent task timed out after {max_age_minutes} minutes (stale cleanup)",
                )
                counts["timed_out"] += 1
            elif not heartbeat_alive:
                await self._finish_task_for_cleanup(
                    redis,
                    task,
                    AgentTaskStatus.FAILED,
                    "Agent task heartbeat was lost",
                )
                counts["cancelled_orphaned"] += 1
            else:
                counts["skipped_active"] += 1

        all_tasks = await redis.hgetall(self.TASKS_KEY)
        queue_members = await redis.lrange(self.QUEUE_KEY, 0, -1)
        queue_set = set(queue_members)

        for task_id, task_data_str in all_tasks.items():
            try:
                task = AgentTask.from_dict(json.loads(task_data_str))
            except Exception:
                continue

            if task.status not in (AgentTaskStatus.QUEUED, AgentTaskStatus.PAUSED):
                continue

            invalid = await self._queued_task_invalid_reason(
                task, now, max_age_minutes
            )
            if invalid:
                status, count_key, message = invalid
                await self._finish_task_for_cleanup(
                    redis,
                    task,
                    status,
                    message,
                )
                counts[count_key] += 1
                continue

            if task.status == AgentTaskStatus.QUEUED and task_id not in queue_set:
                age_minutes = self._task_age_minutes(task, now)
                if age_minutes > 5:
                    await self._finish_task_for_cleanup(
                        redis,
                        task,
                        AgentTaskStatus.FAILED,
                        "Orphaned task: found in QUEUED state but missing from queue list",
                    )
                    counts["orphaned_queued"] += 1

        return counts

    async def cleanup_orphaned_tasks(self, grace_seconds: int = 15) -> int:
        """Clean up all 'running' tasks on startup.

        Called during application startup to clear tasks orphaned by a
        previous container/process that died without completing them.
        Any task marked 'running' at startup is guaranteed orphaned because
        no worker from the previous run is alive to complete it.

        Returns:
            Number of tasks cleaned up
        """
        redis = await self._ensure_connected()
        running_ids = await redis.smembers(self.RUNNING_KEY)
        cleaned = 0

        now = datetime.utcnow()
        for task_id in running_ids:
            task = await self.get_task(task_id)
            if task and task.status == AgentTaskStatus.RUNNING:
                if await self.check_heartbeat(task_id, max_stale_seconds=120):
                    logger.info(
                        f"Skipping running task {task_id}: heartbeat is still fresh"
                    )
                    continue
                if (
                    task.started_at
                    and (now - task.started_at).total_seconds() < grace_seconds
                ):
                    logger.info(
                        f"Skipping newly-started running task {task_id}: within startup grace period"
                    )
                    continue
                task.status = AgentTaskStatus.FAILED
                task.completed_at = now
                task.error = (
                    "Orphaned task cleaned up on startup — previous worker died"
                )
                await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                await redis.srem(self.RUNNING_KEY, task_id)
                await redis.delete(f"{self.HEARTBEAT_PREFIX}{task_id}")
                cleaned += 1
                logger.warning(
                    f"Cleaned orphaned task {task_id} (started={task.started_at})"
                )

        cleanup_counts = await self.cleanup_orphaned_and_stale_tasks()
        cleaned += sum(v for k, v in cleanup_counts.items() if k != "skipped_active")
        if cleaned:
            logger.info(
                f"Startup cleanup: cleared {cleaned} orphaned/stale agent tasks"
            )
        return cleaned

    async def flush_queue(self) -> dict:
        """Flush the entire agent queue — cancel queued tasks, fail running ones.

        Returns summary of what was cleaned.
        """
        redis = await self._ensure_connected()
        now = datetime.utcnow()
        queued_cancelled = 0
        running_failed = 0

        # Cancel all queued tasks
        while True:
            task_id = await redis.lpop(self.QUEUE_KEY)
            if not task_id:
                break
            task = await self.get_task(task_id)
            if task:
                task.status = AgentTaskStatus.CANCELLED
                task.completed_at = now
                task.error = "Queue flushed by admin"
                await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
                queued_cancelled += 1

        # Fail all running tasks
        running_ids = await redis.smembers(self.RUNNING_KEY)
        for task_id in running_ids:
            task = await self.get_task(task_id)
            if task:
                task.status = AgentTaskStatus.FAILED
                task.completed_at = now
                task.error = "Queue flushed by admin"
                await redis.hset(self.TASKS_KEY, task_id, json.dumps(task.to_dict()))
            await redis.srem(self.RUNNING_KEY, task_id)
            await redis.delete(f"{self.HEARTBEAT_PREFIX}{task_id}")
            running_failed += 1

        logger.info(
            f"Queue flushed: {queued_cancelled} queued cancelled, {running_failed} running failed"
        )
        return {
            "queued_cancelled": queued_cancelled,
            "running_failed": running_failed,
        }

    async def cleanup_stale_tasks(self, max_age_minutes: int = 45) -> int:
        """Clean up tasks running too long and orphaned queued tasks.

        Default 45 min, provides buffer above 30-min agent timeout.
        Also detects tasks in QUEUED status that are missing from the queue list.
        """
        counts = await self.cleanup_orphaned_and_stale_tasks(
            max_age_minutes=max_age_minutes
        )
        cleaned = sum(v for k, v in counts.items() if k != "skipped_active")
        if cleaned:
            logger.warning("Cleaned agent queue tasks: %s", counts)
        return cleaned

    async def cleanup_completed_tasks(self, max_age_hours: int = 24) -> int:
        """Remove completed/failed/cancelled/timeout tasks older than max_age_hours from Redis."""
        redis = await self._ensure_connected()
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        removed = 0

        all_tasks = await redis.hgetall(self.TASKS_KEY)
        for task_id, task_data_str in all_tasks.items():
            try:
                task_data = json.loads(task_data_str)
                status = task_data.get("status")
                if status in ("completed", "failed", "timeout", "cancelled"):
                    completed_at = task_data.get("completed_at")
                    if completed_at:
                        completed_dt = datetime.fromisoformat(completed_at)
                        if completed_dt < cutoff:
                            await redis.hdel(self.TASKS_KEY, task_id)
                            await redis.delete(f"{self.HEARTBEAT_PREFIX}{task_id}")
                            removed += 1
            except (json.JSONDecodeError, ValueError):
                continue

        if removed:
            logger.info(
                f"Cleaned up {removed} completed tasks older than {max_age_hours}h"
            )
        return removed

    async def start_cleanup_loop(self, interval_seconds: int = 300):
        """Run cleanup_stale_tasks() and cleanup_completed_tasks() periodically.

        Args:
            interval_seconds: How often to run cleanup (default: 5 minutes)
        """
        logger.info(f"Starting agent queue cleanup loop (every {interval_seconds}s)")
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                cleaned = await self.cleanup_stale_tasks()
                if cleaned > 0:
                    logger.info(f"Cleanup loop: cleaned {cleaned} stale agent tasks")
                removed = await self.cleanup_completed_tasks(max_age_hours=24)
                if removed > 0:
                    logger.info(f"Cleanup loop: removed {removed} old completed tasks")
            except asyncio.CancelledError:
                logger.info("Cleanup loop cancelled")
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}", exc_info=True)
                await asyncio.sleep(30)  # Back off on error


# Singleton instance
_queue_instance: AgentQueue | None = None


def get_agent_queue() -> AgentQueue:
    """Get or create the singleton AgentQueue instance."""
    global _queue_instance
    if _queue_instance is None:
        _queue_instance = AgentQueue()
    return _queue_instance


# Check if agent queue should be used
def should_use_agent_queue() -> bool:
    """Check if Redis is available and agent queue mode is enabled."""
    if not REDIS_AVAILABLE:
        return False
    # Agent queue is now legacy/opt-in. Temporal activities execute agents directly.
    redis_url = os.environ.get("REDIS_URL", "")
    use_queue = os.environ.get("USE_AGENT_QUEUE", "false").lower() == "true"
    return bool(redis_url) and use_queue
