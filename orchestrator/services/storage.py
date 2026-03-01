"""
Storage Service - MinIO/Local Storage Abstraction

Provides a unified interface for storing and retrieving artifacts from:
- Local filesystem (hot storage for recent artifacts)
- MinIO (S3-compatible storage for archived artifacts and backups)

This service enables the archival workflow:
1. New artifacts stored locally in runs/<run_id>/
2. After hot retention period (30 days), artifacts moved to MinIO
3. After total retention period (90 days), artifacts deleted from MinIO

Usage:
    storage = StorageService()

    # Store artifact
    storage.store_artifact(run_id, "report.html", content)

    # Retrieve artifact (works for both local and MinIO)
    content = storage.get_artifact(run_id, "report.html")

    # Archive to MinIO
    storage.archive_artifact(run_id, "report.html")
"""

import hashlib
import io
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Base exception for storage operations."""

    pass


class MinIONotConfiguredError(StorageError):
    """Raised when MinIO is required but not configured."""

    pass


class ArtifactNotFoundError(StorageError):
    """Raised when an artifact cannot be found."""

    pass


class StorageService:
    """Unified storage service for local and MinIO storage."""

    def __init__(
        self,
        runs_dir: str | None = None,
        minio_endpoint: str | None = None,
        minio_access_key: str | None = None,
        minio_secret_key: str | None = None,
        minio_bucket_backups: str = "playwright-backups",
        minio_bucket_artifacts: str = "playwright-artifacts",
        minio_secure: bool = False,
    ):
        """Initialize the storage service.

        Args:
            runs_dir: Local runs directory path. Defaults to /app/runs or ./runs.
            minio_endpoint: MinIO server endpoint (e.g., "minio:9000").
            minio_access_key: MinIO access key.
            minio_secret_key: MinIO secret key.
            minio_bucket_backups: Bucket name for backups.
            minio_bucket_artifacts: Bucket name for archived artifacts.
            minio_secure: Whether to use HTTPS for MinIO.
        """
        # Local storage configuration
        self.runs_dir = Path(runs_dir or os.environ.get("RUNS_DIR", "/app/runs"))

        # MinIO configuration from environment or parameters
        self.minio_endpoint = minio_endpoint or os.environ.get("MINIO_ENDPOINT", "")
        self.minio_access_key = minio_access_key or os.environ.get("MINIO_ROOT_USER", "")
        self.minio_secret_key = minio_secret_key or os.environ.get("MINIO_ROOT_PASSWORD", "")
        self.minio_bucket_backups = minio_bucket_backups or os.environ.get("MINIO_BUCKET", "playwright-backups")
        self.minio_bucket_artifacts = minio_bucket_artifacts or os.environ.get(
            "MINIO_BUCKET_ARTIFACTS", "playwright-artifacts"
        )
        self.minio_secure = minio_secure

        # Strip protocol from endpoint if present
        if self.minio_endpoint.startswith("http://"):
            self.minio_endpoint = self.minio_endpoint[7:]
            self.minio_secure = False
        elif self.minio_endpoint.startswith("https://"):
            self.minio_endpoint = self.minio_endpoint[8:]
            self.minio_secure = True

        # MinIO client (lazy initialized)
        self._minio_client = None

    @property
    def is_minio_configured(self) -> bool:
        """Check if MinIO is configured."""
        return bool(self.minio_endpoint and self.minio_access_key and self.minio_secret_key)

    @property
    def minio_client(self):
        """Get or create MinIO client (lazy initialization)."""
        if self._minio_client is None:
            if not self.is_minio_configured:
                raise MinIONotConfiguredError(
                    "MinIO not configured. Set MINIO_ENDPOINT, MINIO_ROOT_USER, and MINIO_ROOT_PASSWORD."
                )

            try:
                from minio import Minio

                self._minio_client = Minio(
                    self.minio_endpoint,
                    access_key=self.minio_access_key,
                    secret_key=self.minio_secret_key,
                    secure=self.minio_secure,
                )
            except ImportError:
                raise StorageError("minio package not installed. Run: pip install minio")

        return self._minio_client

    def ensure_buckets_exist(self) -> None:
        """Create MinIO buckets if they don't exist."""
        if not self.is_minio_configured:
            logger.warning("MinIO not configured, skipping bucket creation")
            return

        try:
            client = self.minio_client

            for bucket in [self.minio_bucket_backups, self.minio_bucket_artifacts]:
                if not client.bucket_exists(bucket):
                    client.make_bucket(bucket)
                    logger.info(f"Created MinIO bucket: {bucket}")
        except Exception as e:
            logger.error(f"Failed to create MinIO buckets: {e}")
            raise StorageError(f"Failed to create MinIO buckets: {e}")

    # =========================================================================
    # Local Storage Operations
    # =========================================================================

    def get_local_path(self, run_id: str, artifact_name: str) -> Path:
        """Get the local filesystem path for an artifact."""
        return self.runs_dir / run_id / artifact_name

    def artifact_exists_locally(self, run_id: str, artifact_name: str) -> bool:
        """Check if an artifact exists in local storage."""
        return self.get_local_path(run_id, artifact_name).exists()

    def store_locally(
        self,
        run_id: str,
        artifact_name: str,
        content: bytes,
    ) -> Path:
        """Store an artifact in local storage.

        Args:
            run_id: The run ID.
            artifact_name: Name of the artifact file.
            content: Binary content to store.

        Returns:
            Path to the stored file.
        """
        path = self.get_local_path(run_id, artifact_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        logger.debug(f"Stored locally: {path}")
        return path

    def get_locally(self, run_id: str, artifact_name: str) -> bytes:
        """Retrieve an artifact from local storage.

        Args:
            run_id: The run ID.
            artifact_name: Name of the artifact file.

        Returns:
            Binary content of the artifact.

        Raises:
            ArtifactNotFoundError: If the artifact doesn't exist.
        """
        path = self.get_local_path(run_id, artifact_name)
        if not path.exists():
            raise ArtifactNotFoundError(f"Artifact not found locally: {path}")
        return path.read_bytes()

    def delete_locally(self, run_id: str, artifact_name: str) -> bool:
        """Delete an artifact from local storage.

        Args:
            run_id: The run ID.
            artifact_name: Name of the artifact file.

        Returns:
            True if deleted, False if not found.
        """
        path = self.get_local_path(run_id, artifact_name)
        if path.exists():
            path.unlink()
            logger.debug(f"Deleted locally: {path}")
            return True
        return False

    def list_local_artifacts(self, run_id: str) -> list[str]:
        """List all artifacts for a run in local storage.

        Args:
            run_id: The run ID.

        Returns:
            List of artifact filenames.
        """
        run_dir = self.runs_dir / run_id
        if not run_dir.exists():
            return []
        return [f.name for f in run_dir.iterdir() if f.is_file()]

    def get_local_artifact_info(self, run_id: str, artifact_name: str) -> dict[str, Any]:
        """Get metadata about a local artifact.

        Args:
            run_id: The run ID.
            artifact_name: Name of the artifact file.

        Returns:
            Dictionary with size, modified time, and checksum.
        """
        path = self.get_local_path(run_id, artifact_name)
        if not path.exists():
            raise ArtifactNotFoundError(f"Artifact not found: {path}")

        stat = path.stat()
        content = path.read_bytes()
        checksum = hashlib.sha256(content).hexdigest()

        return {
            "name": artifact_name,
            "path": str(path),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            "checksum": checksum,
        }

    # =========================================================================
    # MinIO Storage Operations
    # =========================================================================

    def get_minio_key(self, run_id: str, artifact_name: str) -> str:
        """Get the MinIO object key for an artifact."""
        return f"runs/{run_id}/{artifact_name}"

    def artifact_exists_in_minio(self, run_id: str, artifact_name: str) -> bool:
        """Check if an artifact exists in MinIO."""
        if not self.is_minio_configured:
            return False

        try:
            key = self.get_minio_key(run_id, artifact_name)
            self.minio_client.stat_object(self.minio_bucket_artifacts, key)
            return True
        except Exception as e:
            logger.debug(f"MinIO exists check failed: {e}")
            return False

    def store_in_minio(
        self,
        run_id: str,
        artifact_name: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Store an artifact in MinIO.

        Args:
            run_id: The run ID.
            artifact_name: Name of the artifact file.
            content: Binary content to store.
            content_type: MIME type of the content.

        Returns:
            MinIO object key.
        """
        key = self.get_minio_key(run_id, artifact_name)

        self.minio_client.put_object(
            self.minio_bucket_artifacts,
            key,
            io.BytesIO(content),
            length=len(content),
            content_type=content_type,
        )

        logger.debug(f"Stored in MinIO: {self.minio_bucket_artifacts}/{key}")
        return key

    def get_from_minio(self, run_id: str, artifact_name: str) -> bytes:
        """Retrieve an artifact from MinIO.

        Args:
            run_id: The run ID.
            artifact_name: Name of the artifact file.

        Returns:
            Binary content of the artifact.

        Raises:
            ArtifactNotFoundError: If the artifact doesn't exist.
        """
        try:
            key = self.get_minio_key(run_id, artifact_name)
            response = self.minio_client.get_object(self.minio_bucket_artifacts, key)
            content = response.read()
            response.close()
            response.release_conn()
            return content
        except Exception as e:
            raise ArtifactNotFoundError(f"Artifact not found in MinIO: {run_id}/{artifact_name}: {e}")

    def delete_from_minio(self, run_id: str, artifact_name: str) -> bool:
        """Delete an artifact from MinIO.

        Args:
            run_id: The run ID.
            artifact_name: Name of the artifact file.

        Returns:
            True if deleted, False if not found.
        """
        try:
            key = self.get_minio_key(run_id, artifact_name)
            self.minio_client.remove_object(self.minio_bucket_artifacts, key)
            logger.debug(f"Deleted from MinIO: {key}")
            return True
        except Exception as e:
            logger.warning(f"MinIO delete failed: {e}")
            return False

    def get_minio_artifact_info(self, run_id: str, artifact_name: str) -> dict[str, Any]:
        """Get metadata about a MinIO artifact.

        Args:
            run_id: The run ID.
            artifact_name: Name of the artifact file.

        Returns:
            Dictionary with size, modified time, and etag.
        """
        try:
            key = self.get_minio_key(run_id, artifact_name)
            stat = self.minio_client.stat_object(self.minio_bucket_artifacts, key)

            return {
                "name": artifact_name,
                "key": key,
                "size_bytes": stat.size,
                "modified_at": stat.last_modified,
                "etag": stat.etag,
            }
        except Exception as e:
            raise ArtifactNotFoundError(f"Artifact not found in MinIO: {run_id}/{artifact_name}: {e}")

    # =========================================================================
    # Unified Operations
    # =========================================================================

    def get_artifact(
        self,
        run_id: str,
        artifact_name: str,
        prefer_local: bool = True,
    ) -> bytes:
        """Get an artifact from local storage or MinIO.

        Args:
            run_id: The run ID.
            artifact_name: Name of the artifact file.
            prefer_local: If True, check local first, then MinIO.

        Returns:
            Binary content of the artifact.

        Raises:
            ArtifactNotFoundError: If artifact not found in either location.
        """
        if prefer_local and self.artifact_exists_locally(run_id, artifact_name):
            return self.get_locally(run_id, artifact_name)

        if self.is_minio_configured and self.artifact_exists_in_minio(run_id, artifact_name):
            return self.get_from_minio(run_id, artifact_name)

        if not prefer_local and self.artifact_exists_locally(run_id, artifact_name):
            return self.get_locally(run_id, artifact_name)

        raise ArtifactNotFoundError(f"Artifact not found: {run_id}/{artifact_name}")

    def archive_artifact(
        self,
        run_id: str,
        artifact_name: str,
        delete_local: bool = True,
    ) -> tuple[str, int]:
        """Archive a local artifact to MinIO.

        Args:
            run_id: The run ID.
            artifact_name: Name of the artifact file.
            delete_local: Whether to delete the local copy after archiving.

        Returns:
            Tuple of (MinIO key, size in bytes).

        Raises:
            MinIONotConfiguredError: If MinIO is not configured.
            ArtifactNotFoundError: If local artifact doesn't exist.
        """
        if not self.is_minio_configured:
            raise MinIONotConfiguredError("MinIO not configured for archival")

        # Get local content
        content = self.get_locally(run_id, artifact_name)
        size = len(content)

        # Determine content type
        content_type = self._guess_content_type(artifact_name)

        # Store in MinIO
        key = self.store_in_minio(run_id, artifact_name, content, content_type)

        # Optionally delete local copy
        if delete_local:
            self.delete_locally(run_id, artifact_name)
            logger.info(f"Archived and deleted local: {run_id}/{artifact_name}")
        else:
            logger.info(f"Archived (kept local): {run_id}/{artifact_name}")

        return key, size

    def restore_artifact(self, run_id: str, artifact_name: str) -> Path:
        """Restore an artifact from MinIO to local storage.

        Args:
            run_id: The run ID.
            artifact_name: Name of the artifact file.

        Returns:
            Path to the restored local file.

        Raises:
            ArtifactNotFoundError: If artifact not found in MinIO.
        """
        content = self.get_from_minio(run_id, artifact_name)
        return self.store_locally(run_id, artifact_name, content)

    def _guess_content_type(self, filename: str) -> str:
        """Guess the content type based on file extension."""
        ext = Path(filename).suffix.lower()
        content_types = {
            ".json": "application/json",
            ".html": "text/html",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webm": "video/webm",
            ".zip": "application/zip",
            ".txt": "text/plain",
            ".log": "text/plain",
            ".ts": "text/typescript",
            ".js": "application/javascript",
        }
        return content_types.get(ext, "application/octet-stream")

    # =========================================================================
    # Storage Stats
    # =========================================================================

    def get_local_storage_stats(self) -> dict[str, Any]:
        """Get statistics about local storage.

        Returns:
            Dictionary with run count, total size, etc.
        """
        if not self.runs_dir.exists():
            return {
                "run_count": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0.0,
            }

        run_count = 0
        total_size = 0

        for run_dir in self.runs_dir.iterdir():
            if run_dir.is_dir():
                run_count += 1
                for file in run_dir.rglob("*"):
                    if file.is_file():
                        total_size += file.stat().st_size

        return {
            "run_count": run_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        }

    def get_minio_storage_stats(self, bucket: str | None = None) -> dict[str, Any]:
        """Get statistics about MinIO storage.

        Args:
            bucket: Specific bucket to check. If None, checks artifacts bucket.

        Returns:
            Dictionary with object count, total size, etc.
        """
        if not self.is_minio_configured:
            return {
                "connected": False,
                "object_count": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0.0,
            }

        bucket = bucket or self.minio_bucket_artifacts

        try:
            objects = self.minio_client.list_objects(bucket, recursive=True)
            count = 0
            total_size = 0

            for obj in objects:
                count += 1
                total_size += obj.size or 0

            return {
                "connected": True,
                "bucket": bucket,
                "object_count": count,
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
            }
        except Exception as e:
            logger.error(f"Failed to get MinIO stats: {e}")
            return {
                "connected": False,
                "error": str(e),
                "object_count": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0.0,
            }

    def check_minio_health(self) -> dict[str, Any]:
        """Check MinIO connectivity and health.

        Returns:
            Dictionary with health status.
        """
        if not self.is_minio_configured:
            return {
                "healthy": False,
                "configured": False,
                "error": "MinIO not configured",
            }

        try:
            # Try to list buckets to verify connectivity
            buckets = self.minio_client.list_buckets()
            bucket_names = [b.name for b in buckets]

            return {
                "healthy": True,
                "configured": True,
                "endpoint": self.minio_endpoint,
                "buckets": bucket_names,
                "backups_bucket_exists": self.minio_bucket_backups in bucket_names,
                "artifacts_bucket_exists": self.minio_bucket_artifacts in bucket_names,
            }
        except Exception as e:
            return {
                "healthy": False,
                "configured": True,
                "endpoint": self.minio_endpoint,
                "error": str(e),
            }


# Singleton instance for convenience
_storage_service: StorageService | None = None


def get_storage_service() -> StorageService:
    """Get the singleton storage service instance."""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service
