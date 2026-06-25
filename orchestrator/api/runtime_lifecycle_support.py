"""Startup and shutdown support for the FastAPI runtime."""

from __future__ import annotations

from typing import Any


async def startup(runtime: Any) -> None:
    """Initialize runtime services and background loops."""
    # Initialize DB first (this also initializes ExecutionSettings)
    # NOTE: Alembic's env.py calls fileConfig(alembic.ini) which resets
    # the root logger to WARN level with only a stderr handler, wiping
    # any handlers setup_logging() attached at module-import time.
    runtime.init_db()

    # Re-apply logging AFTER init_db() so our handlers survive Alembic's
    # fileConfig() call.  This restores both the RotatingFileHandler
    # (/app/logs/orchestrator.log) and the coloured console handler,
    # and also overrides uvicorn's default LOGGING_CONFIG.
    runtime.setup_logging(level="INFO", console=True)
    runtime.logger.info("Logging re-initialized after uvicorn startup + Alembic migrations")

    try:
        from orchestrator.services.workflow_step_registry import sync_builtin_workflow_step_types

        with runtime.Session(runtime.engine) as session:
            synced_steps = sync_builtin_workflow_step_types(session)
        runtime.logger.info("Workflow step registry synced: %d built-in step types", len(synced_steps))
    except Exception as exc:
        runtime.logger.warning("Workflow step registry sync failed during startup: %s", exc)

    # Initialize ProcessManager and cleanup orphaned processes from previous runs
    runtime.PROCESS_MANAGER = runtime.get_process_manager()
    # Clear stale asyncio task references from previous server instance
    # (tasks don't survive uvicorn reload, so any references are dangling)
    runtime.PROCESS_MANAGER._asyncio_tasks.clear()
    orphans_cleaned = runtime.PROCESS_MANAGER.cleanup_orphans()
    if orphans_cleaned > 0:
        runtime.logger.info(f"Cleaned up {orphans_cleaned} orphaned processes from previous server instance")

    # Clean up orphaned runs in database before initializing queue (important for accurate queue status)
    runtime.cleanup_orphaned_runs()
    terminal_run_processes_cleaned = runtime.cleanup_terminal_test_run_processes()
    if terminal_run_processes_cleaned:
        runtime.logger.info(
            "Cleaned up %d browser process(es) from terminal test runs",
            terminal_run_processes_cleaned,
        )

    from orchestrator.api.test_run_runtime_support import apply_browser_pool_parallelism

    # Read parallelism from database settings (or use env default)
    db_max_browsers = int(runtime.os.environ.get("MAX_BROWSER_INSTANCES", "5"))
    execution_settings = None
    with runtime.Session(runtime.engine) as session:
        settings = session.get(runtime.DBExecutionSettings, 1)
        if settings:
            execution_settings = settings
            db_max_browsers = settings.parallelism
            runtime.logger.info(f"Using parallelism from database settings: {db_max_browsers}")
        else:
            runtime.logger.info(f"No database settings found, using default: {db_max_browsers}")

    # Initialize unified BrowserResourcePool with parallelism from DB
    runtime.BROWSER_POOL = await runtime.get_browser_pool(max_browsers=db_max_browsers)
    resolved_parallelism = await apply_browser_pool_parallelism(
        runtime.BROWSER_POOL,
        requested_parallelism=db_max_browsers,
        env=runtime.os.environ,
        execution_settings=execution_settings,
    )
    runtime.logger.info(
        "BrowserResourcePool initialized: requested=%s effective=%s mode=%s clamp=%s",
        resolved_parallelism["requested_parallelism"],
        resolved_parallelism["effective_parallelism"],
        resolved_parallelism["browser_runtime_mode"],
        resolved_parallelism["parallelism_clamp_reason"],
    )

    # Clean up any stale browser slots from previous server instance
    stale_cleaned = await runtime.BROWSER_POOL.cleanup_stale(max_age_minutes=60)
    if stale_cleaned:
        runtime.logger.info(f"Cleaned up {len(stale_cleaned)} stale browser slots")

    # Initialize QueueManager (DEPRECATED - kept for backward compatibility)
    runtime.QUEUE_MANAGER = await runtime.QueueManager.get_instance()

    # Initialize ResourceManager for agent/exploration/PRD concurrency control
    # DEPRECATED - use BROWSER_POOL instead for unified browser management
    runtime.RESOURCE_MANAGER = await runtime.ResourceManager.get_instance()
    runtime.logger.info(
        "ResourceManager initialized with limits: "
        f"agents={runtime.RESOURCE_MANAGER._max_agents}, "
        f"explorations={runtime.RESOURCE_MANAGER._max_explorations}, "
        f"prd={runtime.RESOURCE_MANAGER._max_prd}"
    )

    # Legacy semaphore for backward compatibility during transition
    runtime.EXECUTION_SEMAPHORE = runtime.asyncio.Semaphore(runtime.QUEUE_MANAGER.parallelism)

    # Run Sync in background or immediate? Immediate is safer for consistency on first load
    runtime.sync_data_from_files()

    # Start agent queue: clean orphaned tasks from previous run, then start cleanup loop
    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE, get_agent_queue, should_use_agent_queue

        if REDIS_AVAILABLE and should_use_agent_queue():
            queue = get_agent_queue()
            await queue.connect()
            # Flush orphaned "running" tasks from previous container/process
            orphaned = await queue.cleanup_orphaned_tasks()
            if orphaned:
                runtime.logger.info(f"Cleaned {orphaned} orphaned agent tasks from previous run")
            runtime._BACKGROUND_TASKS.append(
                runtime.asyncio.create_task(queue.start_cleanup_loop(interval_seconds=300))
            )
            runtime.logger.info("Started agent queue cleanup loop")
    except Exception as e:
        runtime.logger.warning(f"Could not start agent queue cleanup loop: {e}")

    # Start K6 queue stale task cleanup loop (every 5 minutes)
    try:
        from orchestrator.services.k6_queue import REDIS_AVAILABLE as K6_REDIS_AVAILABLE
        from orchestrator.services.k6_queue import get_k6_queue, should_use_k6_queue

        if K6_REDIS_AVAILABLE and should_use_k6_queue():
            k6_queue = get_k6_queue()
            await k6_queue.connect()
            runtime._BACKGROUND_TASKS.append(
                runtime.asyncio.create_task(k6_queue.start_cleanup_loop(interval_seconds=300))
            )
            runtime.logger.info("K6 distributed mode ACTIVE - started queue cleanup loop")
        else:
            runtime.logger.info("K6 distributed mode INACTIVE - load tests will run locally in backend container")
    except Exception as e:
        runtime.logger.warning(f"Could not start K6 queue cleanup loop: {e}")
        runtime.logger.info("K6 distributed mode INACTIVE - load tests will run locally in backend container")

    # Start job queue cleanup loop
    try:
        from orchestrator.services.job_queue import REDIS_AVAILABLE as JOB_REDIS_AVAILABLE
        from orchestrator.services.job_queue import get_job_queue

        if JOB_REDIS_AVAILABLE:
            jq = get_job_queue()
            await jq.connect()
            runtime._BACKGROUND_TASKS.append(runtime.asyncio.create_task(jq.start_cleanup_loop(interval_seconds=300)))
            runtime.logger.info("Started job queue cleanup loop")
    except Exception as e:
        runtime.logger.warning(f"Could not start job queue cleanup loop: {e}")

    # Start batch watchdog to detect and clean up stuck runs
    runtime._BACKGROUND_TASKS.append(runtime.asyncio.create_task(runtime._batch_watchdog()))
    runtime.logger.info("Started batch watchdog")

    # Start queue watchdog to detect orphaned queued entries after uvicorn reload
    runtime._BACKGROUND_TASKS.append(runtime.asyncio.create_task(runtime._queue_watchdog()))
    runtime.logger.info("Started queue watchdog (30s interval, 60s grace period)")

    # Start PR quality gate finalizer to recover missed GitHub feedback updates
    runtime._BACKGROUND_TASKS.append(runtime.asyncio.create_task(runtime._quality_gate_finalizer_loop()))
    runtime.logger.info("Started quality gate finalizer loop")

    # Start exploration cleanup loop to detect stuck explorations
    runtime._BACKGROUND_TASKS.append(runtime.asyncio.create_task(runtime._exploration_cleanup_loop()))
    runtime.logger.info("Started exploration cleanup loop")

    # Start periodic browser pool cleanup (every 10 min)
    runtime._BACKGROUND_TASKS.append(runtime.asyncio.create_task(runtime._browser_pool_cleanup_loop()))
    runtime.logger.info("Started browser pool cleanup loop (10 min interval)")

    # Start infrastructure maintenance (orphan/temp cleanup every 15 min, DB maintenance daily)
    runtime._BACKGROUND_TASKS.append(runtime.asyncio.create_task(runtime._infrastructure_maintenance_loop()))
    runtime.logger.info("Started infrastructure maintenance loop (15 min interval)")

    # Initialize cron scheduler
    try:
        from orchestrator.services.scheduler import (
            init_scheduler,
            reconcile_workflow_schedule_executions,
            restore_schedules_from_db,
        )

        init_scheduler(runtime.engine)
        await restore_schedules_from_db()
        await reconcile_workflow_schedule_executions()
        runtime._BACKGROUND_TASKS.append(runtime.asyncio.create_task(runtime._schedule_execution_watchdog()))
        runtime.logger.info("Started cron scheduler and execution watchdog")
    except Exception as e:
        runtime.logger.error(f"Failed to initialize scheduler: {e}")

    # Resume interrupted Auto Pilot sessions
    try:
        from .autopilot import resume_interrupted_sessions

        resumed = await resume_interrupted_sessions()
        if resumed:
            runtime.logger.info(f"Resumed {resumed} interrupted Auto Pilot session(s)")
    except Exception as e:
        runtime.logger.warning(f"Could not resume Auto Pilot sessions: {e}")

    # Log startup diagnostics
    await runtime._log_startup_diagnostics()

    runtime.logger.info("Server startup complete")


async def shutdown(runtime: Any) -> None:
    """Gracefully shut down all running processes."""
    runtime.logger.info("Server shutting down, stopping all processes...")

    # Shut down cron scheduler first
    try:
        from orchestrator.services.scheduler import shutdown_scheduler

        shutdown_scheduler()
    except Exception as e:
        runtime.logger.debug(f"Scheduler shutdown: {e}")

    if runtime.PROCESS_MANAGER:
        stopped = runtime.PROCESS_MANAGER.shutdown_all(timeout=10)
        runtime.logger.info(f"Stopped {stopped} processes during shutdown")

    # Update all running/queued runs to stopped in database
    with runtime.Session(runtime.engine) as session:
        stuck_runs = session.exec(
            runtime.select(runtime.DBTestRun).where(runtime.DBTestRun.status.in_(["running", "in_progress", "queued"]))
        ).all()

        for run in stuck_runs:
            run.status = "stopped"
            run.queue_position = None
            run.completed_at = runtime.datetime.utcnow()
            session.add(run)

            # Update status file
            run_dir = runtime.RUNS_DIR / run.id
            if run_dir.exists():
                (run_dir / "status.txt").write_text("stopped")

        session.commit()
        if stuck_runs:
            runtime.logger.info(f"Marked {len(stuck_runs)} runs as stopped during shutdown")

    # Cancel background tasks first (before Redis disconnect since tasks may use Redis)
    for task in runtime._BACKGROUND_TASKS:
        task.cancel()
    for task in runtime._BACKGROUND_TASKS:
        try:
            await task
        except (runtime.asyncio.CancelledError, Exception):
            pass
    runtime._BACKGROUND_TASKS.clear()
    runtime.logger.info("All background tasks cancelled")

    # Disconnect Redis connections to prevent connection leaks
    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE, get_agent_queue

        if REDIS_AVAILABLE:
            queue = get_agent_queue()
            await queue.disconnect()
            runtime.logger.info("Disconnected agent queue Redis connection")
    except Exception as e:
        runtime.logger.debug(f"Agent queue disconnect: {e}")

    try:
        from orchestrator.services.k6_queue import REDIS_AVAILABLE as K6_REDIS_AVAILABLE
        from orchestrator.services.k6_queue import get_k6_queue

        if K6_REDIS_AVAILABLE:
            k6q = get_k6_queue()
            await k6q.disconnect()
            runtime.logger.info("Disconnected K6 queue Redis connection")
    except Exception as e:
        runtime.logger.debug(f"K6 queue disconnect: {e}")

    try:
        from orchestrator.services.job_queue import REDIS_AVAILABLE as JOB_REDIS_AVAILABLE
        from orchestrator.services.job_queue import get_job_queue

        if JOB_REDIS_AVAILABLE:
            jq = get_job_queue()
            await jq.disconnect()
            runtime.logger.info("Disconnected job queue Redis connection")
    except Exception as e:
        runtime.logger.debug(f"Job queue disconnect: {e}")

    # Shut down browser pool
    try:
        pool = await runtime.get_browser_pool()
        await pool.shutdown()
        runtime.logger.info("Browser pool shut down")
    except Exception as e:
        runtime.logger.debug(f"Browser pool shutdown: {e}")

    # Dispose database engine connections
    try:
        runtime.engine.dispose()
        runtime.logger.info("Database engine disposed")
    except Exception as e:
        runtime.logger.debug(f"Engine dispose: {e}")

    runtime.logger.info("Shutdown complete")
