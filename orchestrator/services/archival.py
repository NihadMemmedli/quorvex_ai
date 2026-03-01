"""
Archival Service - Run Artifact Retention Management

This service implements the retention policy for test run artifacts:
- Hot storage (0-30 days): All artifacts kept locally
- Warm storage (30-90 days): Core artifacts moved to MinIO, screenshots deleted
- Cold (90+ days): All artifacts deleted, only metadata in database

Core artifacts preserved during warm storage:
- plan.json (test plan)
- validation.json (validation results)
- report.html (execution report)

Artifacts deleted during archival:
- Screenshots (*.png, *.jpg)
- Trace files (*.zip)
- Raw execution logs

Usage:
    # Run archival manually
    python -m orchestrator.services.archival --run-now

    # Dry run to see what would be archived
    python -m orchestrator.services.archival --dry-run

    # Custom retention periods
    python -m orchestrator.services.archival --hot-days 14 --total-days 60
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Add orchestrator to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlmodel import Session, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import ArchiveJob, RunArtifact, TestRun

logger = logging.getLogger(__name__)


# Artifacts to preserve during warm storage (moved to MinIO)
PRESERVED_ARTIFACTS = {
    "plan.json",
    "validation.json",
    "report.html",
    "run.json",  # Execution trace
}

# Artifact extensions to delete during archival (not preserved)
DELETABLE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webm",
    ".zip",  # Trace files
}


class ArchivalService:
    """Manages artifact retention and archival to MinIO."""

    def __init__(
        self,
        hot_days: int = 30,
        total_days: int = 90,
        runs_dir: str | None = None,
        dry_run: bool = False,
    ):
        """Initialize the archival service.

        Args:
            hot_days: Days to keep artifacts in hot (local) storage.
            total_days: Total days to keep artifacts (including MinIO).
            runs_dir: Local runs directory path.
            dry_run: If True, only log what would be done without making changes.
        """
        self.hot_days = int(os.environ.get("ARCHIVE_HOT_DAYS", hot_days))
        self.total_days = int(os.environ.get("ARCHIVE_TOTAL_DAYS", total_days))
        self.runs_dir = Path(runs_dir or os.environ.get("RUNS_DIR", "/app/runs"))
        self.dry_run = dry_run

        # Import storage service
        from orchestrator.services.storage import get_storage_service

        self.storage = get_storage_service()

        # Statistics for the current job
        self.stats = {
            "artifacts_processed": 0,
            "artifacts_archived": 0,
            "artifacts_deleted": 0,
            "bytes_archived": 0,
            "bytes_freed": 0,
            "errors": [],
        }

    def get_runs_to_archive(self, session: Session) -> list[TestRun]:
        """Get runs that need archival (older than hot_days).

        Args:
            session: Database session.

        Returns:
            List of TestRun objects to archive.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.hot_days)

        # Get completed runs older than hot retention
        statement = select(TestRun).where(
            TestRun.created_at < cutoff,
            TestRun.status.in_(["passed", "failed", "stopped", "completed"]),
        )

        runs = session.exec(statement).all()
        return list(runs)

    def get_runs_to_delete(self, session: Session) -> list[TestRun]:
        """Get runs that should have artifacts fully deleted (older than total_days).

        Args:
            session: Database session.

        Returns:
            List of TestRun objects to delete artifacts from.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.total_days)

        statement = select(TestRun).where(
            TestRun.created_at < cutoff,
            TestRun.status.in_(["passed", "failed", "stopped", "completed"]),
        )

        runs = session.exec(statement).all()
        return list(runs)

    def get_local_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        """Get list of local artifacts for a run.

        Args:
            run_id: The run ID.

        Returns:
            List of artifact info dictionaries.
        """
        run_dir = self.runs_dir / run_id
        if not run_dir.exists():
            return []

        artifacts = []
        for file_path in run_dir.iterdir():
            if file_path.is_file():
                stat = file_path.stat()
                artifacts.append(
                    {
                        "name": file_path.name,
                        "path": str(file_path),
                        "size_bytes": stat.st_size,
                        "extension": file_path.suffix.lower(),
                        "is_preserved": file_path.name in PRESERVED_ARTIFACTS,
                        "is_deletable": file_path.suffix.lower() in DELETABLE_EXTENSIONS,
                    }
                )

        return artifacts

    def archive_run_artifacts(
        self,
        session: Session,
        run: TestRun,
    ) -> tuple[int, int]:
        """Archive artifacts for a single run to MinIO.

        Preserved artifacts are moved to MinIO.
        Deletable artifacts are removed.

        Args:
            session: Database session.
            run: The TestRun to archive.

        Returns:
            Tuple of (bytes_archived, bytes_freed).
        """
        run_id = run.id
        artifacts = self.get_local_artifacts(run_id)

        bytes_archived = 0
        bytes_freed = 0

        for artifact in artifacts:
            try:
                self.stats["artifacts_processed"] += 1

                if artifact["is_preserved"]:
                    # Archive to MinIO
                    if self.dry_run:
                        logger.info(f"[DRY RUN] Would archive: {run_id}/{artifact['name']}")
                        bytes_archived += artifact["size_bytes"]
                    else:
                        key, size = self.storage.archive_artifact(
                            run_id,
                            artifact["name"],
                            delete_local=True,
                        )

                        # Track in database
                        db_artifact = RunArtifact(
                            run_id=run_id,
                            artifact_type=self._get_artifact_type(artifact["name"]),
                            artifact_name=artifact["name"],
                            storage_path=key,
                            storage_type="minio",
                            size_bytes=size,
                            archived_at=datetime.now(timezone.utc),
                            expires_at=datetime.now(timezone.utc) + timedelta(days=self.total_days - self.hot_days),
                        )
                        session.add(db_artifact)

                        bytes_archived += size
                        self.stats["artifacts_archived"] += 1

                    bytes_freed += artifact["size_bytes"]

                elif artifact["is_deletable"]:
                    # Delete directly
                    if self.dry_run:
                        logger.info(f"[DRY RUN] Would delete: {run_id}/{artifact['name']}")
                    else:
                        self.storage.delete_locally(run_id, artifact["name"])
                        self.stats["artifacts_deleted"] += 1

                    bytes_freed += artifact["size_bytes"]

                else:
                    # Other artifacts - archive but mark as lower priority
                    if self.dry_run:
                        logger.info(f"[DRY RUN] Would archive (other): {run_id}/{artifact['name']}")
                        bytes_archived += artifact["size_bytes"]
                    else:
                        key, size = self.storage.archive_artifact(
                            run_id,
                            artifact["name"],
                            delete_local=True,
                        )

                        db_artifact = RunArtifact(
                            run_id=run_id,
                            artifact_type=self._get_artifact_type(artifact["name"]),
                            artifact_name=artifact["name"],
                            storage_path=key,
                            storage_type="minio",
                            size_bytes=size,
                            archived_at=datetime.now(timezone.utc),
                            expires_at=datetime.now(timezone.utc) + timedelta(days=self.total_days - self.hot_days),
                        )
                        session.add(db_artifact)

                        bytes_archived += size
                        self.stats["artifacts_archived"] += 1

                    bytes_freed += artifact["size_bytes"]

            except Exception as e:
                error_msg = f"Failed to process {run_id}/{artifact['name']}: {e}"
                logger.error(error_msg)
                self.stats["errors"].append(error_msg)

        # Clean up empty run directory
        run_dir = self.runs_dir / run_id
        if run_dir.exists() and not any(run_dir.iterdir()):
            if not self.dry_run:
                run_dir.rmdir()
            logger.info(f"Removed empty run directory: {run_id}")

        return bytes_archived, bytes_freed

    def delete_expired_artifacts(self, session: Session, run: TestRun) -> int:
        """Delete all artifacts for a run that has exceeded total retention.

        Args:
            session: Database session.
            run: The TestRun to clean up.

        Returns:
            Bytes freed.
        """
        run_id = run.id
        bytes_freed = 0

        # Delete local artifacts
        for artifact in self.get_local_artifacts(run_id):
            try:
                if self.dry_run:
                    logger.info(f"[DRY RUN] Would delete local: {run_id}/{artifact['name']}")
                else:
                    self.storage.delete_locally(run_id, artifact["name"])
                    self.stats["artifacts_deleted"] += 1

                bytes_freed += artifact["size_bytes"]

            except Exception as e:
                error_msg = f"Failed to delete local {run_id}/{artifact['name']}: {e}"
                logger.error(error_msg)
                self.stats["errors"].append(error_msg)

        # Delete MinIO artifacts
        try:
            # Query tracked artifacts from database
            statement = select(RunArtifact).where(
                RunArtifact.run_id == run_id,
                RunArtifact.storage_type == "minio",
            )
            db_artifacts = session.exec(statement).all()

            for db_artifact in db_artifacts:
                try:
                    if self.dry_run:
                        logger.info(f"[DRY RUN] Would delete from MinIO: {db_artifact.storage_path}")
                    else:
                        self.storage.delete_from_minio(run_id, db_artifact.artifact_name)
                        db_artifact.deleted_at = datetime.now(timezone.utc)
                        session.add(db_artifact)
                        self.stats["artifacts_deleted"] += 1

                    bytes_freed += db_artifact.size_bytes or 0

                except Exception as e:
                    error_msg = f"Failed to delete from MinIO {db_artifact.storage_path}: {e}"
                    logger.error(error_msg)
                    self.stats["errors"].append(error_msg)

        except Exception as e:
            logger.error(f"Failed to query archived artifacts for {run_id}: {e}")

        # Clean up empty run directory
        run_dir = self.runs_dir / run_id
        if run_dir.exists() and not any(run_dir.iterdir()):
            if not self.dry_run:
                run_dir.rmdir()
            logger.info(f"Removed empty run directory: {run_id}")

        return bytes_freed

    def _get_artifact_type(self, filename: str) -> str:
        """Determine artifact type from filename."""
        name_lower = filename.lower()

        if "plan" in name_lower:
            return "plan"
        elif "validation" in name_lower:
            return "validation"
        elif "report" in name_lower:
            return "report"
        elif "trace" in name_lower or filename.endswith(".zip"):
            return "trace"
        elif filename.endswith((".png", ".jpg", ".jpeg")):
            return "screenshot"
        elif "run" in name_lower:
            return "trace"
        else:
            return "other"

    def run_archival(self) -> ArchiveJob:
        """Run the full archival process.

        Returns:
            ArchiveJob with results.
        """
        logger.info("=" * 60)
        logger.info("Starting archival process")
        logger.info(f"  Hot retention: {self.hot_days} days")
        logger.info(f"  Total retention: {self.total_days} days")
        logger.info(f"  Dry run: {self.dry_run}")
        logger.info("=" * 60)

        # Create archive job record
        job = ArchiveJob(
            job_type="archival",
            status="running",
            started_at=datetime.now(timezone.utc),
            config={
                "hot_days": self.hot_days,
                "total_days": self.total_days,
                "dry_run": self.dry_run,
            },
        )

        try:
            with Session(engine) as session:
                if not self.dry_run:
                    session.add(job)
                    session.commit()
                    session.refresh(job)

                # Phase 1: Archive runs older than hot retention
                logger.info("\n--- Phase 1: Archiving to warm storage ---")
                runs_to_archive = self.get_runs_to_archive(session)
                logger.info(f"Found {len(runs_to_archive)} runs to archive")

                for run in runs_to_archive:
                    logger.info(f"Processing run: {run.id} (created: {run.created_at})")
                    archived, freed = self.archive_run_artifacts(session, run)
                    self.stats["bytes_archived"] += archived
                    self.stats["bytes_freed"] += freed

                # Phase 2: Delete runs older than total retention
                logger.info("\n--- Phase 2: Deleting expired artifacts ---")
                runs_to_delete = self.get_runs_to_delete(session)
                logger.info(f"Found {len(runs_to_delete)} runs to delete artifacts from")

                for run in runs_to_delete:
                    logger.info(f"Deleting artifacts for run: {run.id} (created: {run.created_at})")
                    freed = self.delete_expired_artifacts(session, run)
                    self.stats["bytes_freed"] += freed

                # Update job status
                job.status = "completed"
                job.completed_at = datetime.now(timezone.utc)
                job.artifacts_processed = self.stats["artifacts_processed"]
                job.artifacts_archived = self.stats["artifacts_archived"]
                job.artifacts_deleted = self.stats["artifacts_deleted"]
                job.bytes_archived = self.stats["bytes_archived"]
                job.bytes_freed = self.stats["bytes_freed"]

                if self.stats["errors"]:
                    job.error_details = [{"message": e} for e in self.stats["errors"]]

                if not self.dry_run:
                    session.add(job)
                    session.commit()

        except Exception as e:
            logger.error(f"Archival failed: {e}")
            job.status = "failed"
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)

            if not self.dry_run:
                with Session(engine) as session:
                    session.add(job)
                    session.commit()

            raise

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("Archival Summary")
        logger.info("=" * 60)
        logger.info(f"  Artifacts processed: {self.stats['artifacts_processed']}")
        logger.info(f"  Artifacts archived:  {self.stats['artifacts_archived']}")
        logger.info(f"  Artifacts deleted:   {self.stats['artifacts_deleted']}")
        logger.info(
            f"  Bytes archived:      {self.stats['bytes_archived']:,} ({self.stats['bytes_archived'] / 1024 / 1024:.2f} MB)"
        )
        logger.info(
            f"  Bytes freed:         {self.stats['bytes_freed']:,} ({self.stats['bytes_freed'] / 1024 / 1024:.2f} MB)"
        )
        logger.info(f"  Errors:              {len(self.stats['errors'])}")

        if self.stats["errors"]:
            logger.warning("\nErrors encountered:")
            for error in self.stats["errors"][:10]:  # Show first 10 errors
                logger.warning(f"  - {error}")
            if len(self.stats["errors"]) > 10:
                logger.warning(f"  ... and {len(self.stats['errors']) - 10} more")

        return job


def main():
    """CLI entry point for archival service."""
    parser = argparse.ArgumentParser(description="Archive old test run artifacts based on retention policy")
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run archival immediately",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be archived without making changes",
    )
    parser.add_argument(
        "--hot-days",
        type=int,
        default=30,
        help="Days to keep artifacts in hot (local) storage (default: 30)",
    )
    parser.add_argument(
        "--total-days",
        type=int,
        default=90,
        help="Total days to keep artifacts including MinIO (default: 90)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not args.run_now and not args.dry_run:
        parser.print_help()
        print("\nUse --run-now to execute archival or --dry-run to preview changes.")
        sys.exit(1)

    # Run archival
    service = ArchivalService(
        hot_days=args.hot_days,
        total_days=args.total_days,
        dry_run=args.dry_run,
    )

    try:
        job = service.run_archival()
        if job.status == "completed":
            print("\nArchival completed successfully!")
            sys.exit(0)
        else:
            print(f"\nArchival completed with status: {job.status}")
            sys.exit(1)
    except Exception as e:
        print(f"\nArchival failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
