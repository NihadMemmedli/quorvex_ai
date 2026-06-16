import gzip
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException

from logging_config import get_logger

from . import spec_files
from .db import get_database_type

logger = get_logger(__name__)
router = APIRouter()

BASE_DIR = spec_files.BASE_DIR


@router.post("/api/backup")
async def create_backup():
    """Trigger a manual database backup.

    Requires PostgreSQL database. For SQLite, use file-level backup.
    Returns the backup status and file path.
    """
    db_type = get_database_type()

    if db_type == "sqlite":
        # For SQLite, create a simple file copy
        data_dir = Path(__file__).resolve().parent.parent / "data"
        db_file = data_dir / "playwright_agent.db"

        if not db_file.exists():
            raise HTTPException(status_code=404, detail="SQLite database not found")

        backup_dir = data_dir / "backups"
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"backup_{timestamp}.db"

        try:
            shutil.copy2(db_file, backup_file)
            backup_size = backup_file.stat().st_size

            # Rotate old backups (keep last 30)
            backups = sorted(backup_dir.glob("backup_*.db"))
            while len(backups) > 30:
                oldest = backups.pop(0)
                oldest.unlink()
                logger.info(f"Rotated old backup: {oldest.name}")

            return {
                "status": "success",
                "database_type": "sqlite",
                "backup_file": str(backup_file),
                "backup_size_bytes": backup_size,
                "timestamp": timestamp,
            }
        except Exception as e:
            logger.error(f"SQLite backup failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

    else:
        # For PostgreSQL, use pg_dump via subprocess
        try:
            backup_dir = Path("/backups") if Path("/backups").exists() else BASE_DIR / "backups"
            backup_dir.mkdir(exist_ok=True)

            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup_file = backup_dir / f"backup_{timestamp}.sql.gz"

            # Get connection parameters from DATABASE_URL
            db_url = os.environ.get("DATABASE_URL", "")
            parsed = urlparse(db_url)

            env = os.environ.copy()
            env["PGPASSWORD"] = parsed.password or ""

            result = subprocess.run(
                [
                    "pg_dump",
                    "-h",
                    parsed.hostname or "localhost",
                    "-p",
                    str(parsed.port or 5432),
                    "-U",
                    parsed.username or "playwright",
                    "-d",
                    parsed.path.lstrip("/") or "playwright_agent",
                    "--no-owner",
                    "--no-privileges",
                ],
                capture_output=True,
                env=env,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                error_msg = result.stderr.decode()
                logger.error(f"pg_dump failed: {error_msg}")
                raise HTTPException(status_code=500, detail=f"pg_dump failed: {error_msg}")

            # Compress and save
            with gzip.open(backup_file, "wb") as f:
                f.write(result.stdout)

            backup_size = backup_file.stat().st_size

            return {
                "status": "success",
                "database_type": "postgresql",
                "backup_file": str(backup_file),
                "backup_size_bytes": backup_size,
                "timestamp": timestamp,
            }

        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="Backup timed out after 5 minutes")
        except FileNotFoundError:
            raise HTTPException(
                status_code=500, detail="pg_dump not found. Backup must be run from a container with PostgreSQL tools."
            )
        except Exception as e:
            logger.error(f"PostgreSQL backup failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/api/backup/status")
async def get_backup_status():
    """Get the status of database backups including recent backups and retention policy."""
    db_type = get_database_type()

    if db_type == "sqlite":
        backup_dir = Path(__file__).resolve().parent.parent / "data" / "backups"
    else:
        backup_dir = Path("/backups") if Path("/backups").exists() else BASE_DIR / "backups"

    if not backup_dir.exists():
        return {
            "database_type": db_type,
            "backup_dir": str(backup_dir),
            "backup_count": 0,
            "total_size_bytes": 0,
            "recent_backups": [],
            "retention_days": 30,
        }

    pattern = "backup_*.db" if db_type == "sqlite" else "backup_*.sql.gz"
    backups = sorted(backup_dir.glob(pattern), reverse=True)

    total_size = sum(b.stat().st_size for b in backups)

    recent_backups = []
    for backup in backups[:10]:  # Last 10 backups
        stat = backup.stat()
        recent_backups.append(
            {
                "filename": backup.name,
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        )

    return {
        "database_type": db_type,
        "backup_dir": str(backup_dir),
        "backup_count": len(backups),
        "total_size_bytes": total_size,
        "recent_backups": recent_backups,
        "retention_days": 30,
    }
