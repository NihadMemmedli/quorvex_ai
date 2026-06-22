"""Runtime-bound compatibility helpers for agent execution support aliases."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path
from typing import Any

from . import agent_run_runtime_support


def _runtime(runtime: Any | None = None) -> Any:
    if runtime is not None:
        return runtime
    import sys

    return sys.modules.get("orchestrator.api.main") or sys.modules.get("api.main") or import_module("orchestrator.api.main")


def _resolve_agent_browser_auth_storage_path(
    *,
    run_id: str,
    project_id: str | None,
    config: dict[str, Any],
    run_dir: Path,
    preflight_enabled: bool = False,
    runtime: Any | None = None,
) -> Path | None:
    rt = _runtime(runtime)
    return agent_run_runtime_support._resolve_agent_browser_auth_storage_path(
        run_id=run_id,
        project_id=project_id,
        config=config,
        run_dir=run_dir,
        resolve_browser_auth_for_run=rt.resolve_browser_auth_for_run,
        update_progress=rt._update_agent_run_progress,
        preflight_enabled=preflight_enabled,
    )


def _prepare_custom_agent_mcp_config(
    run_id: str,
    storage_state_path: Path | str | None = None,
    *,
    include_browser_tools: bool = True,
    include_agent_note_tool: bool = False,
    runtime: Any | None = None,
) -> Path:
    rt = _runtime(runtime)
    return agent_run_runtime_support._prepare_custom_agent_mcp_config(
        run_id,
        storage_state_path=storage_state_path,
        include_browser_tools=include_browser_tools,
        include_agent_note_tool=include_agent_note_tool,
        update_progress=rt._update_agent_run_progress,
    )


def _probe_custom_agent_browser(
    timeout_seconds: int = 30,
    *,
    runtime: Any | None = None,
) -> tuple[bool, str]:
    rt = _runtime(runtime)
    env = rt.os.environ.copy()
    env.setdefault("PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT", "300000")
    executable_path = rt._resolve_playwright_chromium_executable()
    try:
        result = rt.subprocess.run(
            [
                "node",
                "-e",
                rt._playwright_chromium_probe_script(str(executable_path) if executable_path else None),
            ],
            cwd=str(rt.BASE_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except rt.subprocess.TimeoutExpired as exc:
        output = "\n".join(
            str(value)
            for value in (getattr(exc, "stdout", None), getattr(exc, "stderr", None))
            if value
        ).strip()
        return False, output or f"Timed out after {timeout_seconds}s launching Playwright Chromium"

    combined_output = f"{result.stdout}\n{result.stderr}".strip()
    return result.returncode == 0, combined_output


async def _probe_custom_agent_browser_with_slot(
    run_id: str,
    timeout_seconds: int = 30,
    *,
    runtime: Any | None = None,
) -> tuple[bool, str]:
    rt = _runtime(runtime)

    async def _run_probe() -> tuple[bool, str]:
        loop = asyncio.get_running_loop()
        if timeout_seconds == 30:
            return await loop.run_in_executor(None, rt._probe_custom_agent_browser)
        return await loop.run_in_executor(None, rt._probe_custom_agent_browser, timeout_seconds)

    try:
        pool = rt.BROWSER_POOL or await rt.get_browser_pool()
        if await pool.is_running(run_id):
            return await _run_probe()
    except Exception as exc:
        rt.logger.debug("Could not verify existing agent browser slot for %s: %s", run_id, exc)

    async with rt.browser_operation_slot(
        request_id=f"agent-probe:{run_id}",
        operation_type=rt.BrowserOpType.AGENT,
        description=f"Custom agent browser readiness probe {run_id}",
        timeout=timeout_seconds,
        max_operation_duration=timeout_seconds + 15,
    ):
        return await _run_probe()


async def _ensure_custom_agent_browser_available(
    run_id: str,
    *,
    force_direct_execution: bool = False,
    runtime: Any | None = None,
) -> None:
    """Fail fast if the Playwright browser required by @playwright/mcp is unavailable."""
    rt = _runtime(runtime)
    if rt._custom_agent_browser_runs_via_queue() and not force_direct_execution:
        rt._update_agent_run_progress(
            run_id,
            {
                **rt.browser_runtime_status(),
                "phase": "browser_delegated",
                "message": "Browser execution delegated to agent worker",
            },
        )
        return

    rt._update_agent_run_progress(
        run_id,
        {
            "phase": "browser_setup",
            "message": "Checking local Playwright browser availability",
        },
    )
    rt._update_agent_run_progress(run_id, rt.browser_runtime_status())

    available, output = await rt._probe_custom_agent_browser_with_slot(run_id)
    if not available:
        rt._update_agent_run_progress(
            run_id,
            {
                "phase": "failed",
                "message": "Playwright Chromium is not installed or cannot launch in the local execution container",
                "browser_probe_output": output[-2000:],
            },
        )
        raise RuntimeError(
            "Playwright Chromium is not installed or cannot launch in the local execution container. "
            "Custom agent browser tools require Chromium to be present before a direct run starts. "
            "For `make start`, rebuild/recreate the backend image so Dockerfile's "
            "`npx playwright install chromium` step runs, or enable USE_AGENT_QUEUE=true "
            "to delegate browser execution to an agent worker. "
            f"Browser probe output: {output[-1000:]}"
        )

    rt._update_agent_run_progress(
        run_id,
        {
            "phase": "browser_ready",
            "message": "Local Playwright browser is ready",
        },
    )


@asynccontextmanager
async def _worker_managed_agent_browser_slot(runtime: Any | None = None):
    """No-op slot context for queued agents that acquire browser slots in workers."""
    yield True


def _resolve_agent_execution_test_data_context(
    *,
    project_id: str | None,
    refs: list[Any] | None = None,
    markdown: str | None = None,
    runtime: Any | None = None,
) -> dict[str, Any]:
    rt = _runtime(runtime)
    try:
        from orchestrator.services.test_data_resolver import (
            resolve_test_data_execution_context,
        )

        with rt.Session(rt.engine) as session:
            return resolve_test_data_execution_context(
                session,
                project_id=project_id or "default",
                refs=[str(ref) for ref in (refs or [])],
                markdown=markdown or "",
            )
    except Exception as exc:
        rt.logger.warning("Failed to resolve agent execution test data: %s", exc)
        return {}
