"""Hermes Agent API runtime adapter."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any

import httpx

from orchestrator.utils.agent_runner import AgentResult, ToolCall

from .base import AgentRuntime, AgentRuntimeContext

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "canceled", "timeout"}
TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _persisted_runtime_env() -> dict[str, str]:
    try:
        from orchestrator.api import settings as settings_api

        read_env_file = getattr(settings_api, "_read_env_file", None)
        if os.environ.get("QUORVEX_SETTINGS_ENV_FILE") and callable(read_env_file):
            return read_env_file()
        env_vars = settings_api.runtime_env_vars()
        if env_vars:
            return env_vars
        if callable(read_env_file):
            return read_env_file()
        return {}
    except Exception:
        return {}


def _runtime_env_value(key: str, default: str = "") -> str:
    persisted = _persisted_runtime_env()
    return persisted.get(key) or os.environ.get(key, default)


def _hermes_enabled() -> bool:
    return _runtime_env_value("HERMES_ENABLED", "false").strip().lower() in TRUTHY_VALUES


class HermesRuntimeError(RuntimeError):
    pass


class HermesClient:
    """Small client for the public Hermes API server runs surface."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        raw_url = base_url or _runtime_env_value("HERMES_API_URL", "http://127.0.0.1:8642")
        self.base_url = raw_url.rstrip("/")
        self.api_key = api_key if api_key is not None else _runtime_env_value("HERMES_API_KEY", "")

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def create_run(self, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=min(max(timeout_seconds, 30), 120)) as client:
            response = await client.post(
                f"{self.base_url}/v1/runs",
                headers={**self.headers, "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not data.get("run_id"):
                raise HermesRuntimeError(f"Hermes did not return a run_id: {data!r}")
            return data

    async def get_run(self, run_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.base_url}/v1/runs/{run_id}", headers=self.headers)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {"status": "failed", "output": str(data)}

    async def stop_run(self, run_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{self.base_url}/v1/runs/{run_id}/stop", headers=self.headers)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {"status": "stopping"}

    async def iter_events(self, run_id: str):
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", f"{self.base_url}/v1/runs/{run_id}/events", headers=self.headers) as response:
                response.raise_for_status()
                event_name = "message"
                data_lines: list[str] = []
                async for line in response.aiter_lines():
                    if line == "":
                        if data_lines:
                            yield _decode_sse_event(event_name, "\n".join(data_lines))
                        event_name = "message"
                        data_lines = []
                        continue
                    if line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip() or "message"
                    elif line.startswith("data:"):
                        data_lines.append(line.split(":", 1)[1].lstrip())
                if data_lines:
                    yield _decode_sse_event(event_name, "\n".join(data_lines))


def _decode_sse_event(event_name: str, data: str) -> dict[str, Any]:
    try:
        payload = json.loads(data)
        if isinstance(payload, dict):
            return {"event": event_name, **payload}
        return {"event": event_name, "data": payload}
    except json.JSONDecodeError:
        return {"event": event_name, "data": data}


def _extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("output", "text", "content"):
            if key in value:
                text = _extract_text(value.get(key))
                if text:
                    parts.append(text)
        if parts:
            return "\n".join(parts)
        return ""
    if isinstance(value, list):
        return "\n".join(part for part in (_extract_text(item) for item in value) if part)
    return str(value)


def _event_status(event: dict[str, Any]) -> str | None:
    status = event.get("status") or event.get("state")
    return str(status).lower() if status else None


def _event_tool_name(event: dict[str, Any]) -> str | None:
    for key in ("tool_name", "name", "tool"):
        if event.get(key):
            return str(event[key])
    item = event.get("item") if isinstance(event.get("item"), dict) else {}
    if item.get("name"):
        return str(item["name"])
    return None


class HermesRuntime(AgentRuntime):
    name = "hermes"

    def __init__(self, client: HermesClient | None = None):
        self.client = client or HermesClient()

    async def _is_cancelled(self, context: AgentRuntimeContext) -> bool:
        if not context.is_cancelled:
            return False
        try:
            result = context.is_cancelled()
            if hasattr(result, "__await__"):
                result = await result
            return bool(result)
        except Exception as exc:
            logger.debug("Hermes cancellation check failed: %s", exc)
            return False

    def _cancelled_result(
        self,
        *,
        start_time: datetime,
        run_id: str | None,
        output_parts: list[str],
        tool_calls: list[ToolCall],
        messages_received: int,
        text_blocks_received: int,
        total_cost_usd: float | None = None,
    ) -> AgentResult:
        return AgentResult(
            success=False,
            output="\n".join(output_parts),
            error="Hermes run cancelled",
            duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
            tool_calls=tool_calls,
            messages_received=messages_received,
            text_blocks_received=text_blocks_received,
            cancelled=True,
            session_id=run_id,
            total_cost_usd=total_cost_usd,
        )

    async def run(self, prompt: str, context: AgentRuntimeContext) -> AgentResult:
        if not _hermes_enabled():
            return AgentResult(success=False, error="Hermes runtime is disabled. Set HERMES_ENABLED=true.")
        if await self._is_cancelled(context):
            return self._cancelled_result(
                start_time=datetime.utcnow(),
                run_id=None,
                output_parts=[],
                tool_calls=[],
                messages_received=0,
                text_blocks_received=0,
            )

        timeout_seconds = max(30, int(context.timeout_seconds or 1800))
        start_time = datetime.utcnow()
        output_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        messages_received = 0
        text_blocks_received = 0
        run_id: str | None = None
        total_cost_usd: float | None = None

        payload = self._run_payload(prompt, context)
        try:
            created = await self.client.create_run(payload, timeout_seconds)
            run_id = str(created["run_id"])
            if context.on_task_enqueued:
                context.on_task_enqueued(run_id)
            self._emit_progress(
                context,
                {
                    "runtime": "hermes",
                    "hermes_run_id": run_id,
                    "phase": "queued",
                    "message": "Hermes run started.",
                },
            )

            async def _watch_events() -> None:
                nonlocal messages_received, text_blocks_received
                async for event in self.client.iter_events(str(run_id)):
                    if await self._is_cancelled(context):
                        try:
                            await self.client.stop_run(str(run_id))
                        except Exception:
                            logger.debug("Failed to stop cancelled Hermes run %s", run_id, exc_info=True)
                        raise asyncio.CancelledError("Hermes run cancelled")
                    messages_received += 1
                    self._handle_event(event, context, output_parts, tool_calls)
                    if _extract_text(event):
                        text_blocks_received += 1
                    if _event_status(event) in TERMINAL_STATUSES:
                        break

            try:
                await asyncio.wait_for(_watch_events(), timeout=timeout_seconds)
            except asyncio.CancelledError:
                return self._cancelled_result(
                    start_time=start_time,
                    run_id=run_id,
                    output_parts=output_parts,
                    tool_calls=tool_calls,
                    messages_received=messages_received,
                    text_blocks_received=text_blocks_received,
                    total_cost_usd=total_cost_usd,
                )
            except (httpx.HTTPError, asyncio.TimeoutError) as exc:
                logger.debug("Hermes event stream ended for %s: %s", run_id, exc)
            if await self._is_cancelled(context):
                try:
                    await self.client.stop_run(str(run_id))
                except Exception:
                    logger.debug("Failed to stop cancelled Hermes run %s", run_id, exc_info=True)
                return self._cancelled_result(
                    start_time=start_time,
                    run_id=run_id,
                    output_parts=output_parts,
                    tool_calls=tool_calls,
                    messages_received=messages_received,
                    text_blocks_received=text_blocks_received,
                    total_cost_usd=total_cost_usd,
                )

            final_state = await self.client.get_run(str(run_id))
            status = str(final_state.get("status") or "").lower()
            final_output = _extract_text(final_state.get("output")) or "\n".join(output_parts)
            usage = final_state.get("usage") if isinstance(final_state.get("usage"), dict) else {}
            if usage.get("total_cost_usd") is not None:
                try:
                    total_cost_usd = float(usage.get("total_cost_usd"))
                except (TypeError, ValueError):
                    total_cost_usd = None
            duration = (datetime.utcnow() - start_time).total_seconds()
            success = status not in {"failed", "cancelled", "canceled", "timeout"} and bool(final_output.strip())
            error = None if success else str(final_state.get("error") or final_state.get("message") or "Hermes run failed")
            self._emit_progress(
                context,
                {
                    "runtime": "hermes",
                    "hermes_run_id": run_id,
                    "phase": "completed" if success else "failed",
                    "status": "completed" if success else "failed",
                    "message": "Hermes run completed." if success else error,
                    "tool_calls": len(tool_calls),
                },
            )
            return AgentResult(
                success=success,
                output=final_output,
                error=error,
                duration_seconds=duration,
                tool_calls=tool_calls,
                messages_received=messages_received or 1,
                text_blocks_received=text_blocks_received or (1 if final_output else 0),
                timed_out=status == "timeout",
                cancelled=status in {"cancelled", "canceled"},
                session_id=run_id,
                total_cost_usd=total_cost_usd,
            )
        except asyncio.TimeoutError:
            if run_id:
                try:
                    await self.client.stop_run(run_id)
                except Exception:
                    logger.debug("Failed to stop timed-out Hermes run %s", run_id, exc_info=True)
            return AgentResult(
                success=False,
                output="\n".join(output_parts),
                error=f"Hermes run timed out after {timeout_seconds} seconds",
                duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
                tool_calls=tool_calls,
                messages_received=messages_received,
                text_blocks_received=text_blocks_received,
                timed_out=True,
                session_id=run_id,
            )
        except Exception as exc:
            return AgentResult(
                success=False,
                output="\n".join(output_parts),
                error=str(exc),
                duration_seconds=(datetime.utcnow() - start_time).total_seconds(),
                tool_calls=tool_calls,
                messages_received=messages_received,
                text_blocks_received=text_blocks_received,
                session_id=run_id,
            )

    def _run_payload(self, prompt: str, context: AgentRuntimeContext) -> dict[str, Any]:
        metadata = {
            "runtime": "hermes",
            "owner_type": context.owner_type,
            "owner_id": context.owner_id,
            "owner_label": context.owner_label,
            "project_id": context.memory_project_id,
            "agent_name": context.agent_name,
            **(context.metadata or {}),
        }
        instructions = _extract_text(context.metadata.get("instructions")) if context.metadata else ""
        model = context.model or _runtime_env_value("HERMES_MODEL", "hermes-agent")
        conversation = context.hermes_conversation or context.owner_id or context.memory_source_id
        payload: dict[str, Any] = {
            "input": prompt,
            "model": model,
            "session_id": conversation,
            "metadata": metadata,
        }
        if instructions:
            payload["instructions"] = instructions
        if context.hermes_profile:
            payload["profile"] = context.hermes_profile
        if context.env_vars:
            payload["env"] = {str(key): str(value) for key, value in context.env_vars.items()}
        return payload

    def _handle_event(
        self,
        event: dict[str, Any],
        context: AgentRuntimeContext,
        output_parts: list[str],
        tool_calls: list[ToolCall],
    ) -> None:
        event_type = str(event.get("event") or event.get("type") or "message")
        text = _extract_text(event)
        if text and event_type not in {"hermes.tool.progress", "tool"}:
            output_parts.append(text)

        tool_name = _event_tool_name(event)
        if tool_name and ("tool" in event_type or event.get("tool_name") or event.get("tool")):
            tool_input = event.get("input") if isinstance(event.get("input"), dict) else {}
            tool_calls.append(
                ToolCall(
                    name=tool_name,
                    timestamp=datetime.utcnow(),
                    success=not bool(event.get("error")),
                    error=str(event.get("error")) if event.get("error") else None,
                    input=tool_input,
                )
            )
            if context.on_tool_use:
                context.on_tool_use(tool_name, tool_input)

        progress = {
            "runtime": "hermes",
            "phase": "tool_use" if tool_name else _event_status(event) or "running",
            "message": str(event.get("message") or event_type),
            "tool_calls": len(tool_calls),
            "last_tool": tool_name,
            "hermes_event_type": event_type,
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._emit_progress(context, progress)

    @staticmethod
    def _emit_progress(context: AgentRuntimeContext, progress: dict[str, Any]) -> None:
        if not context.on_progress:
            return
        try:
            context.on_progress(progress)
        except Exception as exc:
            logger.debug("Hermes progress callback failed: %s", exc)
