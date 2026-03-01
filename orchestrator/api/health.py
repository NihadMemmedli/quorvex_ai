"""
Health API - Storage and System Health Checks

Provides detailed health information about:
- PostgreSQL database
- MinIO object storage
- Local storage (runs, specs, tests)
- Backup status
- System alerts

Endpoints:
- GET /health/storage - Detailed storage health
- GET /health/backup - Backup status and age
- GET /health/alerts - Active alerts
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, func, select

from orchestrator.config import settings as app_settings

from .db import engine, get_database_type, get_session
from .models_db import ArchiveJob, StorageStats, TestRun

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


# =============================================================================
# Response Models
# =============================================================================


class DatabaseHealth(BaseModel):
    healthy: bool
    type: str  # postgresql or sqlite
    size_mb: float | None = None
    testrun_count: int = 0
    connection_pool: dict[str, Any] | None = None
    error: str | None = None


class MinIOHealth(BaseModel):
    healthy: bool
    configured: bool
    endpoint: str | None = None
    buckets: list[str] | None = None
    backups_bucket_exists: bool = False
    artifacts_bucket_exists: bool = False
    backups_size_mb: float = 0.0
    backups_count: int = 0
    artifacts_size_mb: float = 0.0
    artifacts_count: int = 0
    error: str | None = None


class LocalStorageHealth(BaseModel):
    healthy: bool
    runs_dir: str
    runs_count: int = 0
    runs_size_mb: float = 0.0
    specs_count: int = 0
    tests_count: int = 0
    prds_count: int = 0
    error: str | None = None


class BackupHealth(BaseModel):
    healthy: bool
    last_backup_at: datetime | None = None
    backup_age_hours: float | None = None
    backup_count: int = 0
    latest_backup_size_mb: float = 0.0
    warning: str | None = None
    error: str | None = None


class Alert(BaseModel):
    severity: str  # warning, critical
    message: str
    metric: str
    value: Any
    threshold: Any


class RedisHealth(BaseModel):
    configured: bool = False
    healthy: bool = False
    queues: dict[str, bool] = {}
    error: str | None = None


class StorageHealthResponse(BaseModel):
    timestamp: datetime
    overall_healthy: bool
    database: DatabaseHealth
    minio: MinIOHealth
    local_storage: LocalStorageHealth
    backup: BackupHealth
    redis: RedisHealth
    alerts: list[Alert]


# =============================================================================
# Alert Thresholds
# =============================================================================

THRESHOLDS = {
    "runs_size_mb_warning": 5000,  # 5 GB
    "runs_size_mb_critical": 10000,  # 10 GB
    "backup_age_hours_warning": 36,
    "backup_age_hours_critical": 48,
    "postgres_size_mb_warning": 5000,  # 5 GB
    "postgres_size_mb_critical": 10000,  # 10 GB
    "disk_usage_pct_warning": 80,
    "disk_usage_pct_critical": 90,
}


# =============================================================================
# Health Check Functions
# =============================================================================


def check_database_health(session: Session) -> DatabaseHealth:
    """Check PostgreSQL/SQLite database health."""
    try:
        db_type = get_database_type()

        # Verify DB connectivity with a simple query
        from sqlalchemy import text

        session.exec(text("SELECT 1"))

        # Count test runs
        count = session.exec(select(func.count()).select_from(TestRun)).one()

        # Get database size (PostgreSQL only)
        size_mb = None
        connection_pool = None

        if db_type == "postgresql":
            try:
                from sqlalchemy import text

                result = session.exec(text("SELECT pg_database_size(current_database())")).one()
                size_mb = round(result / (1024 * 1024), 2)
            except Exception as e:
                logger.warning(f"Could not get database size: {e}")

            # Get connection pool stats
            try:
                pool = engine.pool
                connection_pool = {
                    "size": pool.size(),
                    "checked_in": pool.checkedin(),
                    "checked_out": pool.checkedout(),
                    "overflow": pool.overflow(),
                }
            except Exception:
                pass
        else:
            # SQLite pool info
            try:
                pool = engine.pool
                connection_pool = {
                    "type": "sqlite",
                    "pool_class": type(pool).__name__,
                    "checked_out": pool.checkedout() if hasattr(pool, "checkedout") else 0,
                }
            except Exception:
                connection_pool = {"type": "sqlite", "note": "single-connection mode"}

        return DatabaseHealth(
            healthy=True,
            type=db_type,
            size_mb=size_mb,
            testrun_count=count,
            connection_pool=connection_pool,
        )

    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return DatabaseHealth(
            healthy=False,
            type=get_database_type(),
            error=str(e),
        )


def check_minio_health() -> MinIOHealth:
    """Check MinIO object storage health."""
    try:
        from orchestrator.services.storage import get_storage_service

        storage = get_storage_service()

        if not storage.is_minio_configured:
            return MinIOHealth(
                healthy=False,
                configured=False,
                error="MinIO not configured",
            )

        health = storage.check_minio_health()

        if not health.get("healthy"):
            return MinIOHealth(
                healthy=False,
                configured=True,
                endpoint=storage.minio_endpoint,
                error=health.get("error"),
            )

        # Get bucket stats
        backups_stats = storage.get_minio_storage_stats(storage.minio_bucket_backups)
        artifacts_stats = storage.get_minio_storage_stats(storage.minio_bucket_artifacts)

        return MinIOHealth(
            healthy=True,
            configured=True,
            endpoint=storage.minio_endpoint,
            buckets=health.get("buckets", []),
            backups_bucket_exists=health.get("backups_bucket_exists", False),
            artifacts_bucket_exists=health.get("artifacts_bucket_exists", False),
            backups_size_mb=backups_stats.get("total_size_mb", 0.0),
            backups_count=backups_stats.get("object_count", 0),
            artifacts_size_mb=artifacts_stats.get("total_size_mb", 0.0),
            artifacts_count=artifacts_stats.get("object_count", 0),
        )

    except ImportError:
        return MinIOHealth(
            healthy=False,
            configured=False,
            error="minio package not installed",
        )
    except Exception as e:
        logger.error(f"MinIO health check failed: {e}")
        return MinIOHealth(
            healthy=False,
            configured=True,
            error=str(e),
        )


def check_local_storage_health() -> LocalStorageHealth:
    """Check local filesystem storage health."""
    try:
        base_dir = Path(app_settings.base_dir or "/app")
        runs_dir = base_dir / "runs"
        specs_dir = base_dir / "specs"
        tests_dir = base_dir / "tests"
        prds_dir = base_dir / "prds"

        # Count runs and calculate size
        runs_count = 0
        runs_size = 0

        if runs_dir.exists():
            for run_dir in runs_dir.iterdir():
                if run_dir.is_dir():
                    runs_count += 1
                    for file in run_dir.rglob("*"):
                        if file.is_file():
                            runs_size += file.stat().st_size

        # Count specs
        specs_count = 0
        if specs_dir.exists():
            specs_count = len(list(specs_dir.rglob("*.md")))

        # Count tests
        tests_count = 0
        if tests_dir.exists():
            tests_count = len(list(tests_dir.rglob("*.spec.ts")))

        # Count PRDs
        prds_count = 0
        if prds_dir.exists():
            prds_count = len(list(prds_dir.rglob("*.pdf"))) + len(list(prds_dir.rglob("*.md")))

        return LocalStorageHealth(
            healthy=True,
            runs_dir=str(runs_dir),
            runs_count=runs_count,
            runs_size_mb=round(runs_size / (1024 * 1024), 2),
            specs_count=specs_count,
            tests_count=tests_count,
            prds_count=prds_count,
        )

    except Exception as e:
        logger.error(f"Local storage health check failed: {e}")
        return LocalStorageHealth(
            healthy=False,
            runs_dir=str(Path(app_settings.base_dir or "/app") / "runs"),
            error=str(e),
        )


def check_backup_health() -> BackupHealth:
    """Check backup status and age."""
    try:
        backup_dir = Path(os.environ.get("BACKUP_DIR", "/backups"))

        if not backup_dir.exists():
            return BackupHealth(
                healthy=False,
                warning="Backup directory does not exist",
            )

        # Find manifest files (indicate successful backups)
        manifests = list(backup_dir.glob("*_manifest.json"))

        if not manifests:
            return BackupHealth(
                healthy=False,
                backup_count=0,
                warning="No backups found",
            )

        # Get latest backup
        latest = max(manifests, key=lambda p: p.stat().st_mtime)
        latest_time = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - latest_time).total_seconds() / 3600

        # Calculate latest backup size
        timestamp = latest.stem.replace("_manifest", "")
        backup_files = list(backup_dir.glob(f"{timestamp}_*"))
        backup_size = sum(f.stat().st_size for f in backup_files if f.is_file())

        warning = None
        if age_hours > THRESHOLDS["backup_age_hours_critical"]:
            warning = f"Backup is critically old ({age_hours:.1f} hours)"
        elif age_hours > THRESHOLDS["backup_age_hours_warning"]:
            warning = f"Backup is getting old ({age_hours:.1f} hours)"

        return BackupHealth(
            healthy=age_hours < THRESHOLDS["backup_age_hours_critical"],
            last_backup_at=latest_time,
            backup_age_hours=round(age_hours, 1),
            backup_count=len(manifests),
            latest_backup_size_mb=round(backup_size / (1024 * 1024), 2),
            warning=warning,
        )

    except Exception as e:
        logger.error(f"Backup health check failed: {e}")
        return BackupHealth(
            healthy=False,
            error=str(e),
        )


def generate_alerts(
    database: DatabaseHealth,
    minio: MinIOHealth,
    local_storage: LocalStorageHealth,
    backup: BackupHealth,
    redis: RedisHealth = None,
) -> list[Alert]:
    """Generate alerts based on health checks."""
    alerts = []

    # Database alerts
    if not database.healthy:
        alerts.append(
            Alert(
                severity="critical",
                message="Database is unhealthy",
                metric="database_healthy",
                value=False,
                threshold=True,
            )
        )

    if database.size_mb and database.size_mb > THRESHOLDS["postgres_size_mb_critical"]:
        alerts.append(
            Alert(
                severity="critical",
                message=f"Database size is critically large ({database.size_mb} MB)",
                metric="postgres_size_mb",
                value=database.size_mb,
                threshold=THRESHOLDS["postgres_size_mb_critical"],
            )
        )
    elif database.size_mb and database.size_mb > THRESHOLDS["postgres_size_mb_warning"]:
        alerts.append(
            Alert(
                severity="warning",
                message=f"Database size is getting large ({database.size_mb} MB)",
                metric="postgres_size_mb",
                value=database.size_mb,
                threshold=THRESHOLDS["postgres_size_mb_warning"],
            )
        )

    # MinIO alerts
    if minio.configured and not minio.healthy:
        alerts.append(
            Alert(
                severity="critical",
                message="MinIO is configured but unhealthy",
                metric="minio_healthy",
                value=False,
                threshold=True,
            )
        )

    # Local storage alerts
    if local_storage.runs_size_mb > THRESHOLDS["runs_size_mb_critical"]:
        alerts.append(
            Alert(
                severity="critical",
                message=f"Runs directory is critically large ({local_storage.runs_size_mb} MB)",
                metric="runs_size_mb",
                value=local_storage.runs_size_mb,
                threshold=THRESHOLDS["runs_size_mb_critical"],
            )
        )
    elif local_storage.runs_size_mb > THRESHOLDS["runs_size_mb_warning"]:
        alerts.append(
            Alert(
                severity="warning",
                message=f"Runs directory is getting large ({local_storage.runs_size_mb} MB)",
                metric="runs_size_mb",
                value=local_storage.runs_size_mb,
                threshold=THRESHOLDS["runs_size_mb_warning"],
            )
        )

    # Backup alerts
    if not backup.healthy:
        alerts.append(
            Alert(
                severity="critical",
                message=backup.warning or backup.error or "Backup is unhealthy",
                metric="backup_healthy",
                value=False,
                threshold=True,
            )
        )
    elif backup.backup_age_hours and backup.backup_age_hours > THRESHOLDS["backup_age_hours_warning"]:
        alerts.append(
            Alert(
                severity="warning",
                message=f"Backup is {backup.backup_age_hours:.1f} hours old",
                metric="backup_age_hours",
                value=backup.backup_age_hours,
                threshold=THRESHOLDS["backup_age_hours_warning"],
            )
        )

    # Redis alerts
    if redis and redis.configured and not redis.healthy:
        alerts.append(
            Alert(
                severity="warning",
                message="Redis is configured but unhealthy",
                metric="redis_healthy",
                value=False,
                threshold=True,
            )
        )

    # Disk space alerts
    try:
        import shutil

        base_dir = Path(app_settings.base_dir or "/app")
        disk = shutil.disk_usage(str(base_dir))
        disk_pct = round((disk.used / disk.total) * 100, 1)
        if disk_pct >= THRESHOLDS["disk_usage_pct_critical"]:
            alerts.append(
                Alert(
                    severity="critical",
                    message=f"Disk usage is critically high ({disk_pct}%)",
                    metric="disk_usage_pct",
                    value=disk_pct,
                    threshold=THRESHOLDS["disk_usage_pct_critical"],
                )
            )
        elif disk_pct >= THRESHOLDS["disk_usage_pct_warning"]:
            alerts.append(
                Alert(
                    severity="warning",
                    message=f"Disk usage is high ({disk_pct}%)",
                    metric="disk_usage_pct",
                    value=disk_pct,
                    threshold=THRESHOLDS["disk_usage_pct_warning"],
                )
            )
    except Exception:
        pass

    return alerts


async def check_redis_health() -> RedisHealth:
    """Check Redis connectivity across all queues."""
    result = RedisHealth()
    try:
        from orchestrator.services.agent_queue import REDIS_AVAILABLE

        if not REDIS_AVAILABLE:
            return result
        result.configured = True

        try:
            from orchestrator.services.agent_queue import get_agent_queue

            queue = get_agent_queue()
            result.queues["agent"] = await queue.health_check()
        except Exception:
            result.queues["agent"] = False

        try:
            from orchestrator.services.k6_queue import get_k6_queue

            queue = get_k6_queue()
            result.queues["k6"] = await queue.health_check()
        except Exception:
            result.queues["k6"] = False

        try:
            from orchestrator.services.job_queue import get_job_queue

            queue = get_job_queue()
            result.queues["job"] = await queue.health_check()
        except Exception:
            result.queues["job"] = False

        result.healthy = any(result.queues.values())
    except Exception as e:
        result.error = str(e)
    return result


# =============================================================================
# API Endpoints
# =============================================================================


@router.get("/storage", response_model=StorageHealthResponse)
async def get_storage_health(
    session: Session = Depends(get_session),
) -> StorageHealthResponse:
    """Get detailed storage health status.

    Returns comprehensive information about:
    - Database health and size
    - MinIO connectivity and storage usage
    - Local storage usage
    - Backup status
    - Active alerts
    """
    database = check_database_health(session)
    minio = check_minio_health()
    local_storage = check_local_storage_health()
    backup = check_backup_health()
    redis = await check_redis_health()
    alerts = generate_alerts(database, minio, local_storage, backup, redis=redis)

    overall_healthy = (
        database.healthy
        and local_storage.healthy
        and backup.healthy
        and (not minio.configured or minio.healthy)
        and (not redis.configured or redis.healthy)
    )

    return StorageHealthResponse(
        timestamp=datetime.now(timezone.utc),
        overall_healthy=overall_healthy,
        database=database,
        minio=minio,
        local_storage=local_storage,
        backup=backup,
        redis=redis,
        alerts=alerts,
    )


@router.get("/backup")
async def get_backup_status() -> BackupHealth:
    """Get backup status and age."""
    return check_backup_health()


@router.get("/alerts")
async def get_active_alerts(
    session: Session = Depends(get_session),
) -> list[Alert]:
    """Get active health alerts."""
    database = check_database_health(session)
    minio = check_minio_health()
    local_storage = check_local_storage_health()
    backup = check_backup_health()

    return generate_alerts(database, minio, local_storage, backup)


@router.get("/archival/stats")
async def get_archival_stats(
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Get archival job statistics."""
    try:
        # Get latest archival job
        statement = select(ArchiveJob).order_by(ArchiveJob.created_at.desc()).limit(1)
        latest_job = session.exec(statement).first()

        # Get stats from last 30 days
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        statement = select(ArchiveJob).where(ArchiveJob.created_at > cutoff)
        recent_jobs = session.exec(statement).all()

        total_archived = sum(j.artifacts_archived for j in recent_jobs)
        total_deleted = sum(j.artifacts_deleted for j in recent_jobs)
        total_bytes_freed = sum(j.bytes_freed for j in recent_jobs)

        return {
            "latest_job": {
                "id": latest_job.id if latest_job else None,
                "status": latest_job.status if latest_job else None,
                "completed_at": latest_job.completed_at if latest_job else None,
                "artifacts_archived": latest_job.artifacts_archived if latest_job else 0,
                "artifacts_deleted": latest_job.artifacts_deleted if latest_job else 0,
                "bytes_freed": latest_job.bytes_freed if latest_job else 0,
            }
            if latest_job
            else None,
            "last_30_days": {
                "jobs_run": len(recent_jobs),
                "total_archived": total_archived,
                "total_deleted": total_deleted,
                "total_bytes_freed": total_bytes_freed,
                "total_mb_freed": round(total_bytes_freed / (1024 * 1024), 2),
            },
        }

    except Exception as e:
        logger.error(f"Failed to get archival stats: {e}")
        return {
            "error": str(e),
            "latest_job": None,
            "last_30_days": None,
        }


@router.post("/storage/record")
async def record_storage_stats(
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Record current storage statistics for historical tracking.

    This endpoint should be called periodically (e.g., daily) to
    build a history of storage usage for trend analysis.
    """
    try:
        database = check_database_health(session)
        minio = check_minio_health()
        local_storage = check_local_storage_health()
        backup = check_backup_health()
        alerts = generate_alerts(database, minio, local_storage, backup)

        stats = StorageStats(
            postgres_size_mb=database.size_mb or 0.0,
            testrun_count=database.testrun_count,
            runs_dir_size_mb=local_storage.runs_size_mb,
            runs_dir_count=local_storage.runs_count,
            specs_count=local_storage.specs_count,
            tests_count=local_storage.tests_count,
            minio_backups_size_mb=minio.backups_size_mb,
            minio_backups_count=minio.backups_count,
            minio_artifacts_size_mb=minio.artifacts_size_mb,
            minio_artifacts_count=minio.artifacts_count,
            last_backup_at=backup.last_backup_at,
            backup_age_hours=backup.backup_age_hours,
            minio_connected=minio.healthy if minio.configured else False,
            postgres_connected=database.healthy,
            alerts=[a.message for a in alerts],
        )

        session.add(stats)
        session.commit()

        return {"status": "recorded", "timestamp": str(stats.recorded_at)}

    except Exception as e:
        logger.error(f"Failed to record storage stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
