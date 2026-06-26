"""Runtime support for legacy test-run helpers exposed from main."""

from __future__ import annotations

import asyncio
import json
import signal as _signal
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from orchestrator.utils.playwright_mcp import (
    display_aware_headless,
    display_capable_vnc_enabled,
    requested_headless_from_env,
)

_STARTUP_IMPORT_FAILURE_MESSAGE = (
    "Transient Docker bind-mount import failure while starting the test runner (Errno 35)."
)


def ensure_linked_agent_run_for_test_run(
    runtime: Any,
    *,
    session: Any,
    run_id: str,
    spec_name: str | None,
    project_id: str | None,
    status: str = "running",
) -> Any | None:
    """Create or update the AgentRun row that owns native test-run notes."""
    try:
        agent_run = session.get(runtime.AgentRun, run_id)
        now = runtime.datetime.utcnow()
        progress = {
            "source": "test_run",
            "test_run_id": run_id,
            "spec_name": spec_name,
            "phase": "native_test_run",
        }
        config = {
            "source": "test_run",
            "test_run_id": run_id,
            "spec_name": spec_name,
        }
        if not agent_run:
            agent_run = runtime.AgentRun(
                id=run_id,
                agent_type="spec_generation",
                status=status,
                project_id=project_id,
                started_at=now if status in ("running", "in_progress") else None,
            )
            agent_run.config = config
        else:
            agent_run.agent_type = "spec_generation"
            agent_run.project_id = project_id
            agent_run.status = status
            if not agent_run.started_at and status in ("running", "in_progress"):
                agent_run.started_at = now
        agent_run.progress = {**(agent_run.progress or {}), **progress}
        agent_run.updated_at = now
        session.add(agent_run)
        session.commit()
        return agent_run
    except Exception as exc:
        runtime.logger.debug("Could not ensure linked AgentRun for test run %s: %s", run_id, exc)
        try:
            session.rollback()
        except Exception:
            pass
        return None


def finalize_linked_agent_run_for_test_run(
    runtime: Any,
    *,
    session: Any,
    run_id: str,
    test_status: str | None,
    error_message: str | None = None,
) -> None:
    try:
        agent_run = session.get(runtime.AgentRun, run_id)
        if not agent_run:
            return
        now = runtime.datetime.utcnow()
        normalized = str(test_status or "").lower()
        if normalized in {"passed", "completed", "success"}:
            agent_status = "completed"
        elif normalized in {"stopped", "cancelled"}:
            agent_status = "cancelled"
        elif normalized in {"failed", "error"}:
            agent_status = "failed"
        else:
            agent_status = agent_run.status
        agent_run.status = agent_status
        if agent_status in {"completed", "failed", "cancelled"}:
            agent_run.completed_at = now
        agent_run.updated_at = now
        agent_run.progress = {
            **(agent_run.progress or {}),
            "test_status": test_status,
            **({"error_message": error_message} if error_message else {}),
        }
        session.add(agent_run)
        session.commit()
    except Exception as exc:
        runtime.logger.debug("Could not finalize linked AgentRun for test run %s: %s", run_id, exc)
        try:
            session.rollback()
        except Exception:
            pass


def record_startup_import_failure(runtime: Any, run_id: str, run_dir_path: Path, *, retrying: bool) -> None:
    message = (
        f"{_STARTUP_IMPORT_FAILURE_MESSAGE} Retrying test runner."
        if retrying
        else f"{_STARTUP_IMPORT_FAILURE_MESSAGE} Retry attempts exhausted."
    )
    try:
        with runtime.Session(runtime.engine) as session:
            run = session.get(runtime.DBTestRun, run_id)
            if run:
                if not retrying:
                    run.status = "error"
                    run.error_message = message
                    run.completed_at = runtime.datetime.utcnow()
                run.current_stage = "startup"
                run.stage_message = message
                session.add(run)
                session.commit()
    except Exception as exc:
        runtime.logger.debug(
            "Could not record startup import failure status for %s: %s",
            run_id,
            exc,
        )

    if not retrying:
        try:
            (run_dir_path / "status.txt").write_text("error")
            (run_dir_path / "pipeline_error.json").write_text(
                json.dumps({"stage": "startup", "error": message}, indent=2)
            )
        except OSError:
            pass


def run_test_cli_subprocess_with_retry(
    runtime: Any,
    *,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    run_id: str,
    run_dir_path: Path,
    spec_name: str,
    batch_id: str | None,
    append_workflow_log,
    timeout_seconds: int = 3600,
) -> int | None:
    """Run the CLI subprocess, retrying only early Errno 35 import failures."""
    from orchestrator.services.test_run_subprocess_retry import run_test_cli_subprocess_with_retry

    return run_test_cli_subprocess_with_retry(
        cmd=cmd,
        cwd=cwd,
        env=env,
        run_id=run_id,
        run_dir_path=run_dir_path,
        spec_name=spec_name,
        batch_id=batch_id,
        append_workflow_log=append_workflow_log,
        register_process=runtime.register_process,
        unregister_process=runtime.unregister_process,
        process_manager=runtime.PROCESS_MANAGER,
        logger=runtime.logger,
        record_startup_import_failure=runtime._record_startup_import_failure,
        timeout_seconds=timeout_seconds,
    )


def resolve_run_headless_mode(
    *,
    env: dict[str, str] | None = None,
    execution_settings: Any | None = None,
) -> bool:
    """Resolve browser visibility for server-triggered test runs."""
    explicit_headless = requested_headless_from_env(env)
    if explicit_headless is not None:
        return display_aware_headless(explicit_headless, env)

    settings_headless = getattr(execution_settings, "headless_in_parallel", None)
    if settings_headless is not None:
        return display_aware_headless(bool(settings_headless), env)

    if display_capable_vnc_enabled(env):
        return False
    return True


def _positive_int(value: Any, *, default: int, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(1, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def resolve_test_run_playwright_workers(
    *,
    env: dict[str, str] | None = None,
    headless: bool,
) -> int:
    """Resolve per-run Playwright workers for generated test subprocesses."""
    if not headless:
        return 1
    source = env or {}
    return _positive_int(source.get("TEST_RUN_PLAYWRIGHT_WORKERS"), default=1, maximum=10)


def resolve_effective_browser_parallelism(
    *,
    requested_parallelism: int,
    env: dict[str, str] | None = None,
    execution_settings: Any | None = None,
) -> dict[str, Any]:
    """Resolve browser pool capacity with shared VNC display safety applied."""
    requested = _positive_int(requested_parallelism, default=1)
    headless = resolve_run_headless_mode(env=env, execution_settings=execution_settings)
    shared_vnc_display = display_capable_vnc_enabled(env) and not headless
    effective = 1 if shared_vnc_display else requested
    return {
        "requested_parallelism": requested,
        "effective_parallelism": effective,
        "headless": headless,
        "browser_runtime_mode": "headless" if headless else "headed_vnc" if shared_vnc_display else "headed",
        "parallelism_clamp_reason": "shared_vnc_display" if effective < requested else None,
    }


async def apply_browser_pool_parallelism(
    pool: Any,
    *,
    requested_parallelism: int,
    env: dict[str, str] | None = None,
    execution_settings: Any | None = None,
) -> dict[str, Any]:
    """Apply effective browser pool capacity and attach diagnostics to the pool."""
    resolved = resolve_effective_browser_parallelism(
        requested_parallelism=requested_parallelism,
        env=env,
        execution_settings=execution_settings,
    )
    pool.requested_max_browsers = resolved["requested_parallelism"]
    pool.effective_max_browsers = resolved["effective_parallelism"]
    pool.browser_runtime_mode = resolved["browser_runtime_mode"]
    pool.parallelism_clamp_reason = resolved["parallelism_clamp_reason"]
    await pool.update_max_browsers(resolved["effective_parallelism"])
    return resolved


def execute_run_task(
    runtime: Any,
    spec_path: str,
    run_dir: str,
    run_id: str,
    try_code_path: str = None,
    browser: str = "chromium",
    hybrid: bool = False,
    max_iterations: int = 20,
    headless: bool = False,
    memory_enabled: bool = True,
    spec_name: str = "",
    batch_id: str = None,
    project_id: str = None,
    model_tier: str | None = None,
    storage_state_path: str | None = None,
    browser_auth_context: dict[str, Any] | None = None,
    test_data_refs: list[str] | None = None,
):
    """Execute the native pipeline with optional hybrid healing mode."""
    headless = display_aware_headless(headless, runtime.os.environ)

    def _append_workflow_log(message: str, **payload: Any) -> None:
        try:
            run_dir_path = Path(run_dir)
            run_dir_path.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": runtime.datetime.utcnow().isoformat() + "Z",
                "message": message,
                **payload,
            }
            with (run_dir_path / "workflow.log").open("a", encoding="utf-8") as log:
                log.write(json.dumps(entry, default=str) + "\n")
        except Exception:
            pass

    _append_workflow_log("Subprocess preparing.", run_id=run_id, spec_path=spec_path)

    with runtime.Session(runtime.engine) as session:
        run = session.get(runtime.DBTestRun, run_id)
        if run and run.status in ("stopped", "cancelled"):
            runtime.logger.info(f"Run {run_id} was {run.status} before subprocess start. Aborting.")
            _append_workflow_log("Subprocess aborted before start.", status=run.status)
            return
        if run:
            ensure_linked_agent_run_for_test_run(
                runtime,
                session=session,
                run_id=run_id,
                spec_name=spec_name or run.spec_name,
                project_id=project_id if project_id is not None else run.project_id,
                status="running",
            )

    cmd = [runtime.sys.executable, "orchestrator/cli.py", spec_path, "--run-dir", run_dir, "--browser", browser]
    if try_code_path:
        cmd.extend(["--try-code", try_code_path])
    if hybrid:
        cmd.extend(["--hybrid", "--max-iterations", str(max_iterations)])

    run_dir_path = Path(run_dir)
    runtime._write_run_browser_metadata(
        run_dir_path,
        runtime._build_run_browser_metadata(headless=headless, phase="executing"),
    )

    runtime.copy_claude_project_config(runtime.BASE_DIR / ".claude", run_dir_path / ".claude")

    playwright_config_src = runtime.BASE_DIR / "playwright.config.ts"
    playwright_config_dst = run_dir_path / "playwright.config.ts"
    if playwright_config_src.exists() and not playwright_config_dst.exists():
        config_content = runtime.prepare_run_playwright_config_content(
            playwright_config_src.read_text(),
            base_dir=runtime.BASE_DIR,
            run_dir=run_dir_path,
            headless=headless,
            storage_state_path=storage_state_path,
        )
        playwright_config_dst.write_text(config_content)

    runtime_metadata = runtime.write_playwright_test_mcp_config(
        run_dir=run_dir_path,
        server_name="playwright-test",
        config_path=playwright_config_dst,
        headless=headless,
        storage_state_path=storage_state_path,
        agent_run_id=run_id,
    )
    runtime._write_run_browser_metadata(
        run_dir_path,
        runtime._merge_run_browser_metadata(
            runtime._build_run_browser_metadata(headless=headless, phase="executing"),
            runtime_metadata,
            headless=headless,
            phase="executing",
        ),
    )
    runtime.logger.info(
        "Created Playwright Test MCP config for run %s (headless=%s, args=%s)",
        run_id,
        headless,
        runtime_metadata.get("mcp_args"),
    )

    target_url = runtime._extract_run_target_url(spec_path)
    seed_dst = runtime._write_run_seed_spec(run_dir_path, target_url)
    runtime.logger.debug(f"Wrote run seed file: {seed_dst} (target_url={target_url or 'about:blank'})")

    env = runtime.os.environ.copy()
    env["HEADLESS"] = "true" if headless else "false"
    env["PLAYWRIGHT_HEADLESS"] = "true" if headless else "false"
    env["PLAYWRIGHT_WORKERS"] = str(resolve_test_run_playwright_workers(env=env, headless=headless))
    if not headless:
        env["CI"] = ""
    env["MEMORY_ENABLED"] = "true" if memory_enabled else "false"
    env["QUORVEX_RUN_MODEL_TIER"] = model_tier or "tool_deep"
    env["BROWSER_SLOT_PARENT_OWNER_TYPE"] = "test_run"
    env["BROWSER_SLOT_PARENT_RUN_ID"] = run_id
    env["CLAUDE_CONFIG_DIR"] = str(run_dir_path)
    if project_id:
        env["PROJECT_ID"] = project_id
        env["MEMORY_PROJECT_ID"] = project_id
    env["QUORVEX_AGENT_RUN_ID"] = run_id
    if browser_auth_context:
        env["QUORVEX_BROWSER_AUTH_CONTEXT"] = json.dumps(browser_auth_context)
    normalized_test_data_refs = runtime._normalize_request_test_data_refs(test_data_refs)
    if normalized_test_data_refs:
        env["QUORVEX_TEST_DATA_REFS"] = json.dumps(normalized_test_data_refs)

    with runtime.Session(runtime.engine) as session:
        run = session.get(runtime.DBTestRun, run_id)
        if run and run.status in ("stopped", "cancelled"):
            runtime.logger.info(f"Run {run_id} was {run.status} before process spawn. Aborting.")
            _append_workflow_log("Subprocess aborted before process spawn.", status=run.status)
            return

    runtime._run_test_cli_subprocess_with_retry(
        cmd=cmd,
        cwd=runtime.BASE_DIR,
        env=env,
        run_id=run_id,
        run_dir_path=run_dir_path,
        spec_name=spec_name,
        batch_id=batch_id,
        append_workflow_log=_append_workflow_log,
        timeout_seconds=3600,
    )


async def execute_run_task_wrapper(
    runtime: Any,
    spec_path: str,
    run_dir: str,
    run_id: str,
    try_code_path: str = None,
    browser: str = "chromium",
    hybrid: bool = False,
    max_iterations: int = 20,
    batch_id: str = None,
    spec_name: str = "",
    project_id: str = None,
    model_tier: str | None = None,
    storage_state_path: str | None = None,
    browser_auth_context: dict[str, Any] | None = None,
    test_data_refs: list[str] | None = None,
):
    """Async wrapper for execute_run_task with unified browser queue management."""

    def _append_workflow_log(message: str, **payload: Any) -> None:
        try:
            run_dir_path = Path(run_dir)
            run_dir_path.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": runtime.datetime.utcnow().isoformat() + "Z",
                "message": message,
                **payload,
            }
            with (run_dir_path / "workflow.log").open("a", encoding="utf-8") as log:
                log.write(json.dumps(entry, default=str) + "\n")
        except Exception:
            pass

    _append_workflow_log("Test run wrapper started.", run_id=run_id, spec_path=spec_path)

    headless = True
    memory_enabled = True
    with runtime.Session(runtime.engine) as session:
        settings = session.get(runtime.DBExecutionSettings, 1)
        if settings:
            headless = resolve_run_headless_mode(
                env=runtime.os.environ,
                execution_settings=settings,
            )
            memory_enabled = settings.memory_enabled
        else:
            headless = resolve_run_headless_mode(env=runtime.os.environ)

    pool = runtime.BROWSER_POOL or await runtime.get_browser_pool()
    try:
        stale_cleaned = await pool.cleanup_stale(max_age_minutes=60)
        if stale_cleaned:
            _append_workflow_log("Cleaned stale browser slots before acquisition.", cleaned_slots=stale_cleaned)
    except Exception as exc:
        _append_workflow_log("Browser slot cleanup before acquisition failed.", error=str(exc))

    from orchestrator.services.load_test_lock import check_system_available

    await check_system_available("test run")

    try:
        _append_workflow_log("Waiting for browser slot.", browser_slot_request_id=run_id)
        async with pool.browser_slot(
            request_id=run_id,
            operation_type=runtime.BrowserOpType.TEST_RUN,
            description=f"Test: {spec_name or spec_path}",
            max_operation_duration=7200,
        ) as acquired:
            if not acquired:
                runtime.logger.warning(f"Run {run_id} failed to acquire browser slot (timeout)")
                with runtime.Session(runtime.engine) as session:
                    run = session.get(runtime.DBTestRun, run_id)
                    if run:
                        run.status = "error"
                        run.error_message = "Timeout waiting for browser slot"
                        run.queue_position = None
                        run.completed_at = runtime.datetime.utcnow()
                        session.add(run)
                        session.commit()
                status_file = Path(run_dir) / "status.txt"
                status_file.write_text("error")
                if batch_id:
                    runtime.update_batch_stats(batch_id)
                return

            _append_workflow_log("Browser slot acquired.", browser_slot_request_id=run_id)

            with runtime.Session(runtime.engine) as session:
                run = session.get(runtime.DBTestRun, run_id)
                if run:
                    if run.status in ("stopped", "cancelled"):
                        runtime.logger.info(f"Run {run_id} was {run.status} while queued. Aborting.")
                        _append_workflow_log("Run aborted after browser slot acquisition.", status=run.status)
                        if batch_id:
                            runtime.update_batch_stats(batch_id)
                        return
                    run.status = "running"
                    run.started_at = runtime.datetime.utcnow()
                    run.queue_position = None
                    session.add(run)
                    session.commit()
                    ensure_linked_agent_run_for_test_run(
                        runtime,
                        session=session,
                        run_id=run_id,
                        spec_name=spec_name or run.spec_name,
                        project_id=project_id if project_id is not None else run.project_id,
                        status="running",
                    )

            if batch_id:
                runtime.update_batch_stats(batch_id)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                runtime.execute_run_task,
                spec_path,
                run_dir,
                run_id,
                try_code_path,
                browser,
                hybrid,
                max_iterations,
                headless,
                memory_enabled,
                spec_name,
                batch_id,
                project_id,
                model_tier,
                storage_state_path,
                browser_auth_context,
                test_data_refs,
            )
            _append_workflow_log("Native run executor returned.", run_id=run_id)

            with runtime.Session(runtime.engine) as session:
                run = session.get(runtime.DBTestRun, run_id)
                if run:
                    try:
                        status_file = Path(run_dir) / "status.txt"
                        if status_file.exists():
                            file_status = status_file.read_text().strip()
                            if file_status:
                                run.status = file_status
                                runtime.logger.debug(f"[{run_id}] Status from status.txt: {file_status}")

                        run_file = Path(run_dir) / "run.json"
                        if run_file.exists():
                            try:
                                run_data = json.loads(run_file.read_text())
                                if "finalState" in run_data:
                                    run.status = run_data["finalState"]
                                run.steps_completed = len(run_data.get("steps", []))

                                if run.status == "failed":
                                    for step in run_data.get("steps", []):
                                        if step.get("error"):
                                            run.error_message = step.get("error")[:500]
                                            break
                            except json.JSONDecodeError:
                                pass

                        plan_file = Path(run_dir) / "plan.json"
                        if plan_file.exists():
                            try:
                                plan_data = json.loads(plan_file.read_text())
                                if "testName" in plan_data:
                                    run.test_name = plan_data["testName"]
                                if "steps" in plan_data:
                                    run.total_steps = len(plan_data["steps"])
                            except json.JSONDecodeError:
                                pass

                        error_file = Path(run_dir) / "pipeline_error.json"
                        if error_file.exists():
                            try:
                                error_data = json.loads(error_file.read_text())
                                if error_data.get("error"):
                                    error_msg = str(error_data["error"])[:500]
                                    stage = str(error_data.get("stage", "") or "")
                                    if stage == "test_data_resolution":
                                        run.stage_message = f"{stage}: {error_msg}"
                                    if not run.error_message:
                                        if stage:
                                            run.error_message = f"[{stage}] {error_msg}"
                                        else:
                                            run.error_message = error_msg
                            except json.JSONDecodeError:
                                pass

                        if run.status in ("running", "queued"):
                            runtime.logger.warning(
                                f"[{run_id}] Process exited but status still '{run.status}'. Forcing to 'error'."
                            )
                            run.status = "error"
                            if not run.error_message:
                                run.error_message = (
                                    "Process exited without writing status. Check execution.log for details."
                                )
                            try:
                                (Path(run_dir) / "status.txt").write_text("error")
                            except Exception:
                                pass

                        run.completed_at = runtime.datetime.utcnow()

                        if run.status in ("passed", "completed"):
                            runtime.invalidate_code_path_cache(run.spec_name)

                    except Exception as e:
                        runtime.logger.warning(f"Error reading status files for {run_id}: {e}")

                    session.add(run)
                    session.commit()
                    finalize_linked_agent_run_for_test_run(
                        runtime,
                        session=session,
                        run_id=run_id,
                        test_status=run.status,
                        error_message=run.error_message,
                    )
                    runtime.logger.info(f"[{run_id}] Final DB status: {run.status}")
                    _append_workflow_log("Final DB status recorded.", status=run.status)

            if batch_id:
                runtime.update_batch_stats(batch_id)

    except asyncio.CancelledError:
        runtime.logger.info(f"Run {run_id} cancelled")
        _append_workflow_log("Run wrapper cancelled.")
        with runtime.Session(runtime.engine) as session:
            run = session.get(runtime.DBTestRun, run_id)
            if run and run.status not in ("stopped", "cancelled", "passed", "failed", "error", "completed"):
                run.status = "cancelled"
                run.queue_position = None
                run.completed_at = runtime.datetime.utcnow()
                session.add(run)
                session.commit()
        status_file = Path(run_dir) / "status.txt"
        status_file.write_text("cancelled")
        if batch_id:
            runtime.update_batch_stats(batch_id)
        raise

    except Exception as e:
        runtime.logger.error(f"Run {run_id} failed with exception: {e}", exc_info=True)
        _append_workflow_log("Run wrapper failed.", error=str(e))
        with runtime.Session(runtime.engine) as session:
            run = session.get(runtime.DBTestRun, run_id)
            if run:
                run.status = "error"
                run.error_message = str(e)[:500]
                run.completed_at = runtime.datetime.utcnow()
                session.add(run)
                session.commit()
        status_file = Path(run_dir) / "status.txt"
        status_file.write_text("error")
        if batch_id:
            runtime.update_batch_stats(batch_id)


def execute_mobile_run_task(
    runtime: Any,
    spec_path: str,
    run_dir: str,
    run_id: str,
    platform: str = "ios",
    appium_server_url: str | None = None,
    capabilities_file: str | None = None,
    spec_name: str = "",
    batch_id: str = None,
    project_id: str = None,
):
    """Execute the Appium mobile pipeline in an isolated subprocess."""
    from orchestrator.workflows.mobile_appium import MobileAppiumConfig, build_appium_mcp_config

    with runtime.Session(runtime.engine) as session:
        run = session.get(runtime.DBTestRun, run_id)
        if run and run.status in ("stopped", "cancelled"):
            runtime.logger.info(f"Mobile run {run_id} was {run.status} before subprocess start. Aborting.")
            return

    run_dir_path = Path(run_dir)
    run_dir_path.mkdir(parents=True, exist_ok=True)

    config = MobileAppiumConfig.from_env(
        platform=platform,
        appium_server_url=appium_server_url,
        capabilities_file=capabilities_file,
    )

    mcp_output_dir = run_dir_path / "appium-mcp-output"
    mcp_output_dir.mkdir(parents=True, exist_ok=True)
    config.screenshots_dir = str(mcp_output_dir)
    run_mcp_config_path = run_dir_path / ".mcp.json"
    run_mcp_config_path.write_text(json.dumps(build_appium_mcp_config(config), indent=2))
    runtime.logger.info(f"Created Appium MCP config for mobile run {run_id}")

    runtime.copy_claude_project_config(runtime.BASE_DIR / ".claude", run_dir_path / ".claude")

    cmd = [
        runtime.sys.executable,
        "orchestrator/cli.py",
        spec_path,
        "--run-dir",
        run_dir,
        "--target",
        "mobile",
        "--platform",
        platform,
    ]
    if appium_server_url:
        cmd.extend(["--appium-server-url", appium_server_url])
    if capabilities_file:
        cmd.extend(["--capabilities-file", capabilities_file])

    env = runtime.os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(run_dir_path)
    env["APPIUM_SCREENSHOTS_DIR"] = str(mcp_output_dir)
    if appium_server_url:
        env["APPIUM_SERVER_URL"] = appium_server_url
    if capabilities_file:
        env["APPIUM_CAPABILITIES_CONFIG"] = capabilities_file
    if project_id:
        env["PROJECT_ID"] = project_id
        env["MEMORY_PROJECT_ID"] = project_id

    with runtime.Session(runtime.engine) as session:
        run = session.get(runtime.DBTestRun, run_id)
        if run and run.status in ("stopped", "cancelled"):
            runtime.logger.info(f"Mobile run {run_id} was {run.status} before process spawn. Aborting.")
            return

    log_file = run_dir_path / "execution.log"
    with open(log_file, "w") as f:
        process = runtime.subprocess.Popen(
            cmd,
            cwd=runtime.BASE_DIR,
            stdout=f,
            stderr=runtime.subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )

        try:
            pgid = runtime.os.getpgid(process.pid)
        except (ProcessLookupError, OSError):
            pgid = process.pid

        runtime.register_process(run_id, process)
        if runtime.PROCESS_MANAGER:
            runtime.PROCESS_MANAGER.register(
                run_id=run_id,
                pid=process.pid,
                pgid=pgid,
                spec_name=spec_name,
                batch_id=batch_id,
            )

        runtime.logger.info(f"Started mobile process for {run_id}: pid={process.pid}, pgid={pgid}")
        try:
            process.wait(timeout=1800)
        except runtime.subprocess.TimeoutExpired:
            runtime.logger.warning(f"Mobile process for {run_id} timed out after 1800s")
            try:
                runtime.os.killpg(runtime.os.getpgid(process.pid), _signal.SIGKILL)
            except (ProcessLookupError, OSError):
                try:
                    process.kill()
                except (ProcessLookupError, OSError):
                    pass
            process.wait(timeout=10)
        finally:
            runtime.unregister_process(run_id)
            if runtime.PROCESS_MANAGER:
                runtime.PROCESS_MANAGER.unregister(run_id)
            runtime.logger.info(f"Mobile process completed for {run_id}: exit_code={process.returncode}")


async def execute_mobile_run_task_wrapper(
    runtime: Any,
    spec_path: str,
    run_dir: str,
    run_id: str,
    platform: str = "ios",
    appium_server_url: str | None = None,
    capabilities_file: str | None = None,
    batch_id: str = None,
    spec_name: str = "",
    project_id: str = None,
):
    """Async wrapper for Appium mobile runs."""
    try:
        with runtime.Session(runtime.engine) as session:
            run = session.get(runtime.DBTestRun, run_id)
            if run:
                if run.status in ("stopped", "cancelled"):
                    return
                run.status = "running"
                run.started_at = runtime.datetime.utcnow()
                run.queue_position = None
                session.add(run)
                session.commit()

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            runtime.execute_mobile_run_task,
            spec_path,
            run_dir,
            run_id,
            platform,
            appium_server_url,
            capabilities_file,
            spec_name,
            batch_id,
            project_id,
        )

        with runtime.Session(runtime.engine) as session:
            run = session.get(runtime.DBTestRun, run_id)
            if run:
                run_dir_path = Path(run_dir)
                status_file = run_dir_path / "status.txt"
                if status_file.exists():
                    file_status = status_file.read_text().strip()
                    if file_status:
                        run.status = file_status

                plan_file = run_dir_path / "plan.json"
                if plan_file.exists():
                    try:
                        plan_data = json.loads(plan_file.read_text())
                        run.test_name = plan_data.get("testName") or run.test_name
                        run.total_steps = len(plan_data.get("steps", []))
                    except json.JSONDecodeError:
                        pass

                error_file = run_dir_path / "pipeline_error.json"
                if error_file.exists():
                    try:
                        error_data = json.loads(error_file.read_text())
                        if error_data.get("error"):
                            error_msg = str(error_data["error"])[:500]
                            stage = str(error_data.get("stage", "") or "")
                            if stage == "test_data_resolution":
                                run.stage_message = f"{stage}: {error_msg}"
                            if not run.error_message:
                                run.error_message = f"[{stage}] {error_msg}" if stage else error_msg
                    except json.JSONDecodeError:
                        pass

                if run.status in ("running", "queued"):
                    run.status = "error"
                    run.error_message = run.error_message or "Mobile process exited without writing status."
                    try:
                        status_file.write_text("error")
                    except Exception:
                        pass

                run.completed_at = runtime.datetime.utcnow()
                session.add(run)
                session.commit()

        if batch_id:
            runtime.update_batch_stats(batch_id)

    except asyncio.CancelledError:
        with runtime.Session(runtime.engine) as session:
            run = session.get(runtime.DBTestRun, run_id)
            if run and run.status not in ("stopped", "cancelled", "passed", "failed", "error", "completed"):
                run.status = "cancelled"
                run.queue_position = None
                run.completed_at = runtime.datetime.utcnow()
                session.add(run)
                session.commit()
        Path(run_dir, "status.txt").write_text("cancelled")
        raise
    except Exception as e:
        runtime.logger.error(f"Mobile run {run_id} failed with exception: {e}", exc_info=True)
        with runtime.Session(runtime.engine) as session:
            run = session.get(runtime.DBTestRun, run_id)
            if run:
                run.status = "error"
                run.error_message = str(e)[:500]
                run.completed_at = runtime.datetime.utcnow()
                session.add(run)
                session.commit()
        Path(run_dir, "status.txt").write_text("error")
        if batch_id:
            runtime.update_batch_stats(batch_id)


async def start_test_run_temporal_or_fail(
    runtime: Any,
    run: Any,
    payload: dict[str, Any],
    session: Any,
    *,
    task_queue: str | None = None,
) -> None:
    from orchestrator.config import settings as app_settings
    from orchestrator.services.temporal_client import (
        TemporalUnavailableError,
        describe_temporal_task_queue,
        start_test_run_workflow,
    )

    selected_task_queue = task_queue or app_settings.temporal_browser_workflow_task_queue
    try:
        task_queue_status = await describe_temporal_task_queue(selected_task_queue)
        workflow_pollers = int((task_queue_status.get("workflow") or {}).get("poller_count") or 0)
        activity_pollers = int((task_queue_status.get("activity") or {}).get("poller_count") or 0)
        if workflow_pollers <= 0 or activity_pollers <= 0:
            raise TemporalUnavailableError(
                f"No Temporal pollers for task queue {selected_task_queue} "
                f"(workflow={workflow_pollers}, activity={activity_pollers})"
            )
        temporal = await start_test_run_workflow(run.id, payload, task_queue=selected_task_queue)
    except TemporalUnavailableError as exc:
        run.status = "error"
        run.queue_position = None
        run.completed_at = runtime.datetime.utcnow()
        run.error_message = f"Failed to start Temporal workflow: {exc}"
        run.stage_message = str(exc)
        session.add(run)
        session.commit()
        run_dir = runtime.RUNS_DIR / run.id
        if run_dir.exists():
            (run_dir / "status.txt").write_text("error")
        if run.batch_id:
            runtime.update_batch_stats(run.batch_id)
        raise HTTPException(status_code=503, detail=f"Temporal is required for test runs: {exc}") from exc

    run.temporal_workflow_id = temporal.workflow_id
    run.temporal_run_id = temporal.run_id
    session.add(run)
    session.commit()


async def signal_test_run_temporal(runtime: Any, run: Any, signal_name: str, *args) -> None:
    if not run.temporal_workflow_id:
        return
    from orchestrator.services.temporal_client import TemporalUnavailableError, signal_test_run_workflow

    try:
        await signal_test_run_workflow(run.temporal_workflow_id, signal_name, *args)
    except TemporalUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"Temporal is unavailable for test run control: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to signal test run workflow: {exc}") from exc


def has_browser_auth_selection(
    runtime: Any,
    *,
    browser_auth_session_id: str | None,
    use_project_default_browser_auth: bool,
) -> bool:
    return bool((browser_auth_session_id or "").strip() or use_project_default_browser_auth)


def validate_browser_auth_selection_for_project(
    runtime: Any,
    session: Any,
    project_id: str | None,
    *,
    browser_auth_session_id: str | None,
    use_project_default_browser_auth: bool,
) -> None:
    browser_auth_session_id = (browser_auth_session_id or "").strip() or None
    if not runtime._has_browser_auth_selection(
        browser_auth_session_id=browser_auth_session_id,
        use_project_default_browser_auth=use_project_default_browser_auth,
    ):
        return
    if not project_id:
        raise HTTPException(status_code=400, detail="Browser auth session selection requires a project")
    try:
        row = runtime.resolve_browser_auth_session_row(
            session,
            project_id,
            browser_auth_session_id=browser_auth_session_id,
            use_default=use_project_default_browser_auth,
        )
        if not row:
            raise runtime.BrowserAuthSessionError("Project default browser auth session was not found")
        runtime.ensure_browser_auth_session_usable(row)
    except runtime.BrowserAuthSessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def resolve_browser_auth_storage_state_for_run(
    runtime: Any,
    session: Any,
    project_id: str | None,
    *,
    run_dir: Path,
    browser_auth_session_id: str | None,
    use_project_default_browser_auth: bool,
) -> tuple[str | None, dict[str, Any]]:
    browser_auth_session_id = (browser_auth_session_id or "").strip() or None
    intent: dict[str, Any] = {
        "mode": "project_default" if use_project_default_browser_auth else ("session" if browser_auth_session_id else "none"),
        "requested_browser_auth_session_id": browser_auth_session_id,
        "browser_auth_session_id": None,
        "browser_auth_session_name": None,
        "use_project_default_browser_auth": bool(use_project_default_browser_auth),
        "project_default_used": False,
        "storage_state_attached": False,
    }
    if not runtime._has_browser_auth_selection(
        browser_auth_session_id=browser_auth_session_id,
        use_project_default_browser_auth=use_project_default_browser_auth,
    ):
        return None, intent
    try:
        resolved = runtime.resolve_browser_auth_for_run(
            session,
            project_id,
            run_dir=run_dir,
            browser_auth_session_id=browser_auth_session_id,
            use_default=use_project_default_browser_auth,
        )
    except runtime.BrowserAuthSessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not resolved:
        return None, intent
    intent.update(
        {
            "browser_auth_session_id": resolved.session_id,
            "browser_auth_session_name": resolved.session_name,
            "project_default_used": bool(use_project_default_browser_auth),
            "storage_state_attached": True,
        }
    )
    return str(resolved.storage_state_path), intent


def normalize_request_test_data_refs(runtime: Any, refs: list[str] | None) -> list[str]:
    from orchestrator.services.test_data_resolver import extract_test_data_refs_from_sources

    return extract_test_data_refs_from_sources(refs=refs or [])
