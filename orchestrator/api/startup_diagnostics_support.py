"""Startup diagnostics support for legacy helpers exposed from main."""

from __future__ import annotations

from typing import Any


async def _log_startup_diagnostics(runtime: Any) -> None:
    """Log system diagnostics at startup for early problem detection."""
    diagnostics = []

    db_type = runtime.get_database_type()
    diagnostics.append(f"Database: {db_type}")
    if db_type == "postgresql":
        diagnostics.append("  Pool: size=30, max_overflow=60, timeout=30s, statement_timeout=30s")

    redis_status = "unavailable"
    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE

        if REDIS_AVAILABLE:
            redis_status = "connected"
    except Exception:
        pass
    diagnostics.append(f"Redis: {redis_status}")

    minio_status = "not configured"
    try:
        minio_endpoint = runtime.os.environ.get("MINIO_ENDPOINT")
        if minio_endpoint:
            from orchestrator.services.storage import StorageService

            storage = StorageService()
            if await runtime.asyncio.to_thread(storage.health_check):
                minio_status = f"connected ({minio_endpoint})"
            else:
                minio_status = f"unhealthy ({minio_endpoint})"
    except Exception:
        minio_status = "error"
    diagnostics.append(f"MinIO: {minio_status}")

    try:
        stat = runtime.shutil.disk_usage(str(runtime.RUNS_DIR))
        free_gb = stat.free / (1024**3)
        total_gb = stat.total / (1024**3)
        pct_free = (stat.free / stat.total) * 100
        level = "OK" if pct_free > 10 else "LOW" if pct_free > 5 else "CRITICAL"
        diagnostics.append(f"Disk: {free_gb:.1f}GB free / {total_gb:.1f}GB total ({pct_free:.0f}% free) [{level}]")
    except Exception:
        diagnostics.append("Disk: unknown")

    max_browsers = int(runtime.os.environ.get("MAX_BROWSER_INSTANCES", "5"))
    diagnostics.append(f"Browser pool: max_instances={max_browsers}")

    optional_vars = {
        "OPENAI_API_KEY": "memory system embeddings",
        "MINIO_ENDPOINT": "artifact archival",
        "REDIS_URL": "distributed queue/rate limiting",
    }
    missing = [f"{k} ({v})" for k, v in optional_vars.items() if not runtime.os.environ.get(k)]
    if missing:
        diagnostics.append(f"Optional env vars not set: {', '.join(missing)}")

    runtime.logger.info("=== Startup Diagnostics ===\n  " + "\n  ".join(diagnostics))
