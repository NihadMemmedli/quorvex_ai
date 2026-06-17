"""Legacy test-run queue manager support exposed from main."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

RuntimeFactory = Callable[[], Any]

_runtime_factory: RuntimeFactory | None = None


def configure_runtime(runtime_factory: RuntimeFactory) -> None:
    """Configure the live runtime module used by QueueManager."""
    global _runtime_factory
    _runtime_factory = runtime_factory


def _runtime() -> Any:
    if _runtime_factory is None:
        raise RuntimeError("QueueManager runtime has not been configured")
    return _runtime_factory()


class QueueManager:
    """Manages test execution queue with configurable parallelism."""

    _instance: QueueManager | None = None
    _lock: Any | None = None

    def __init__(self):
        self._semaphore: Any | None = None
        self._parallelism: int = 2
        self._parallel_mode_enabled: bool = False

    @classmethod
    async def get_instance(cls) -> QueueManager:
        """Get or create the singleton QueueManager instance."""
        if cls._instance is None:
            cls._instance = cls()
            await cls._instance.initialize()
        return cls._instance

    async def initialize(self):
        """Initialize the queue manager from database settings or environment defaults."""
        runtime = _runtime()

        # Read environment defaults
        env_parallelism = int(runtime.os.environ.get("DEFAULT_PARALLELISM", "4"))
        env_parallel_enabled = runtime.os.environ.get("PARALLEL_MODE_ENABLED", "false").lower() == "true"

        with runtime.Session(runtime.engine) as session:
            settings = session.get(runtime.DBExecutionSettings, 1)
            if settings:
                self._parallelism = settings.parallelism
                self._parallel_mode_enabled = settings.parallel_mode_enabled
            else:
                # Use environment defaults when no DB settings exist
                self._parallelism = max(1, min(10, env_parallelism))
                self._parallel_mode_enabled = env_parallel_enabled and runtime.is_parallel_mode_available()
                runtime.logger.info(
                    f"Using environment defaults: parallelism={self._parallelism}, enabled={self._parallel_mode_enabled}"
                )

        self._semaphore = runtime.asyncio.Semaphore(self._parallelism)
        runtime.logger.info(
            f"QueueManager initialized: parallelism={self._parallelism}, enabled={self._parallel_mode_enabled}"
        )

    async def reload_settings(self):
        """Reload settings from database and update semaphore if needed."""
        runtime = _runtime()

        with runtime.Session(runtime.engine) as session:
            settings = session.get(runtime.DBExecutionSettings, 1)
            if settings:
                new_parallelism = settings.parallelism
                self._parallel_mode_enabled = settings.parallel_mode_enabled

                # Only recreate semaphore if parallelism changed
                if new_parallelism != self._parallelism:
                    self._parallelism = new_parallelism
                    self._semaphore = runtime.asyncio.Semaphore(self._parallelism)
                    runtime.logger.info(f"QueueManager updated: parallelism={self._parallelism}")

    @property
    def parallelism(self) -> int:
        return self._parallelism

    @property
    def parallel_mode_enabled(self) -> bool:
        return self._parallel_mode_enabled

    async def acquire(self):
        """Acquire a slot for test execution."""
        if self._semaphore:
            await self._semaphore.acquire()

    def release(self):
        """Release a slot after test execution."""
        if self._semaphore:
            self._semaphore.release()

    def get_queue_position(self, run_id: str) -> int | None:
        """Get the queue position for a run (based on waiting count)."""
        runtime = _runtime()

        with runtime.Session(runtime.engine) as session:
            # Count runs that are queued (status='queued') and were queued before this run
            run = session.get(runtime.DBTestRun, run_id)
            if not run or run.status != "queued":
                return None

            statement = runtime.select(runtime.DBTestRun).where(
                runtime.DBTestRun.status == "queued",
                runtime.DBTestRun.queued_at < run.queued_at,
            )
            earlier_runs = session.exec(statement).all()
            return len(earlier_runs) + 1  # 1-indexed position

    def get_queue_status(self) -> dict[str, Any]:
        """Get current queue status with orphan detection and auto-cleanup."""
        runtime = _runtime()
        orphan_age_seconds = 120

        with runtime.Session(runtime.engine) as session:
            running = session.exec(
                runtime.select(runtime.DBTestRun).where(runtime.DBTestRun.status.in_(["running", "in_progress"]))
            ).all()
            queued = session.exec(runtime.select(runtime.DBTestRun).where(runtime.DBTestRun.status == "queued")).all()

            # Detect orphaned runs: in DB as running but no active process
            orphaned_running = [
                r for r in running if not r.temporal_workflow_id and not runtime.is_process_active(r.id)
            ]

            # Auto-clean orphans that have been orphaned for >120 seconds
            auto_cleaned_count = 0
            batch_ids_to_update = set()
            now = runtime.datetime.utcnow()
            for r in orphaned_running:
                age_ref = r.started_at or r.queued_at
                if age_ref and (now - age_ref).total_seconds() > orphan_age_seconds:
                    r.status = "stopped"
                    r.completed_at = now
                    r.queue_position = None
                    session.add(r)

                    run_dir = runtime.RUNS_DIR / r.id
                    if run_dir.exists():
                        (run_dir / "status.txt").write_text("stopped")

                    if r.batch_id:
                        batch_ids_to_update.add(r.batch_id)

                    auto_cleaned_count += 1
                    runtime.logger.warning(
                        f"Auto-cleaned orphaned run {r.id} (age={int((now - age_ref).total_seconds())}s)"
                    )

            if auto_cleaned_count > 0:
                session.commit()
                for batch_id in batch_ids_to_update:
                    try:
                        runtime.update_batch_stats(batch_id)
                    except Exception as e:
                        runtime.logger.error(f"Failed to update batch stats for {batch_id} after orphan cleanup: {e}")

            # Detect orphaned queued entries: queued in DB but no backing asyncio task
            orphaned_queued = [
                r
                for r in queued
                if not (
                    r.temporal_workflow_id
                    or (
                        runtime.PROCESS_MANAGER
                        and r.id in runtime.PROCESS_MANAGER._asyncio_tasks
                        and not runtime.PROCESS_MANAGER._asyncio_tasks[r.id].done()
                    )
                )
                and r.queued_at
                and (runtime.datetime.utcnow() - r.queued_at).total_seconds() > 60
            ]

            return {
                "running_count": len(running) - len(orphaned_running),
                "queued_count": len(queued),
                "parallelism_limit": self._parallelism,
                "database_type": runtime.get_database_type(),
                "parallel_mode_enabled": self._parallel_mode_enabled,
                "orphaned_running_count": len(orphaned_running),
                "active_process_count": runtime.get_active_process_count(),
                "orphaned_queued_count": len(orphaned_queued),
                "auto_cleaned_count": auto_cleaned_count,
            }
