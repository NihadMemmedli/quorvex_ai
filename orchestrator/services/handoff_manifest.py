"""Run-local handoff manifest helpers for native pipeline stages."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = "handoff_manifest.v1"
MANIFEST_FILENAME = "handoff_manifest.json"
UTC = timezone.utc


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def artifact_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_path(run_dir: Path) -> Path:
    return Path(run_dir) / MANIFEST_FILENAME


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "created_at": utc_timestamp(),
            "updated_at": utc_timestamp(),
            "stages": {},
            "artifacts": {},
            "artifact_history": {},
            "attempt_history": [],
            "events": [],
        }
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("created_at", utc_timestamp())
    data.setdefault("stages", {})
    data.setdefault("artifacts", {})
    data.setdefault("artifact_history", {})
    data.setdefault("attempt_history", [])
    data.setdefault("events", [])
    return data


def write_manifest(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    manifest["schema_version"] = SCHEMA_VERSION
    manifest["updated_at"] = utc_timestamp()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(manifest, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        tmp_name = handle.name
        handle.write(content)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_name, path)
    return manifest


def load_manifest(run_dir_or_path: Path | str) -> dict[str, Any]:
    path = Path(run_dir_or_path)
    if path.name != MANIFEST_FILENAME:
        path = manifest_path(path)
    return _read_manifest(path)


def init_manifest(run_dir: Path | str, *, pipeline_type: str = "browser") -> Path:
    path = manifest_path(Path(run_dir))
    data = _read_manifest(path)
    data.setdefault("pipeline_type", pipeline_type)
    write_manifest(path, data)
    return path


def record_stage(
    manifest_file: Path | str,
    stage: str,
    *,
    status: str,
    metadata: dict[str, Any] | None = None,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    path = Path(manifest_file)
    data = _read_manifest(path)
    stages = data.setdefault("stages", {})
    current = stages.setdefault(stage, {})
    current.update(
        {
            "status": status,
            "updated_at": utc_timestamp(),
        }
    )
    if metadata:
        current.setdefault("metadata", {}).update(metadata)
    if failure_reason:
        current["failure_reason"] = failure_reason
    write_manifest(path, data)
    return current


def record_artifact(
    manifest_file: Path | str,
    artifact_id: str,
    artifact_path: Path | str,
    *,
    kind: str,
    producer_stage: str,
    required: bool = True,
    consumers: list[str] | None = None,
    validation_status: str | None = None,
    failure_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(manifest_file)
    file_path = Path(artifact_path)
    exists = file_path.exists()
    item: dict[str, Any] = {
        "id": artifact_id,
        "kind": kind,
        "path": str(file_path),
        "producer_stage": producer_stage,
        "consumers": consumers or [],
        "required": required,
        "exists": exists,
        "validation_status": validation_status or ("valid" if exists else "missing"),
        "failure_reason": failure_reason,
        "updated_at": utc_timestamp(),
    }
    if exists and file_path.is_file():
        stat = file_path.stat()
        item.update(
            {
                "hash": artifact_hash(file_path),
                "size_bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat().replace("+00:00", "Z"),
            }
        )
    if metadata:
        item["metadata"] = metadata

    data = _read_manifest(path)
    data.setdefault("artifacts", {})[artifact_id] = item
    data.setdefault("artifact_history", {}).setdefault(artifact_id, []).append(item)
    data.setdefault("stages", {}).setdefault(producer_stage, {}).setdefault(
        "artifacts_produced", []
    )
    produced = data["stages"][producer_stage]["artifacts_produced"]
    if artifact_id not in produced:
        produced.append(artifact_id)
    write_manifest(path, data)
    return item


def record_attempt(
    manifest_file: Path | str,
    stage: str,
    *,
    stage_attempt: int,
    status: str,
    attempt_id: str | None = None,
    agent_session_id: str | None = None,
    executor_mode: str | None = None,
    model_tier: str | None = None,
    timeout_seconds: int | None = None,
    error_type: str | None = None,
    tool_call_summary: dict[str, Any] | None = None,
    input_artifact_hashes: dict[str, str | None] | None = None,
    output_artifact_hash: str | None = None,
    parent_attempt_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append immutable attempt metadata for a stage run or retry."""
    path = Path(manifest_file)
    data = _read_manifest(path)
    if not attempt_id:
        attempt_id = f"{stage}-{stage_attempt}-{len(data.setdefault('attempt_history', [])) + 1}"
    item: dict[str, Any] = {
        "id": attempt_id,
        "stage": stage,
        "stage_attempt": stage_attempt,
        "status": status,
        "agent_session_id": agent_session_id,
        "executor_mode": executor_mode,
        "model_tier": model_tier,
        "timeout_seconds": timeout_seconds,
        "error_type": error_type,
        "tool_call_summary": tool_call_summary or {},
        "input_artifact_hashes": input_artifact_hashes or {},
        "output_artifact_hash": output_artifact_hash,
        "parent_attempt_id": parent_attempt_id,
        "metadata": metadata or {},
        "created_at": utc_timestamp(),
    }
    data.setdefault("attempt_history", []).append(item)
    stage_data = data.setdefault("stages", {}).setdefault(stage, {})
    stage_data.setdefault("attempts", []).append(attempt_id)
    write_manifest(path, data)
    return item


def record_consumption(
    manifest_file: Path | str,
    stage: str,
    artifact_id: str,
    *,
    status: str,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(manifest_file)
    data = _read_manifest(path)
    stages = data.setdefault("stages", {})
    stage_data = stages.setdefault(stage, {})
    consumed = stage_data.setdefault("artifacts_consumed", {})
    consumption_metadata = dict(metadata or {})
    consumed[artifact_id] = {
        "status": status,
        "reason": reason,
        "metadata": consumption_metadata,
        "updated_at": utc_timestamp(),
    }
    artifact = data.setdefault("artifacts", {}).get(artifact_id)
    if isinstance(artifact, dict):
        consumers = artifact.setdefault("consumers", [])
        if stage not in consumers:
            consumers.append(stage)
        file_path = Path(str(artifact.get("path") or ""))
        if status == "used" and file_path.exists() and file_path.is_file():
            current_hash = artifact_hash(file_path)
            recorded_hash = artifact.get("hash")
            freshness = "valid"
            if recorded_hash and recorded_hash != current_hash:
                freshness = "stale"
            artifact["current_hash"] = current_hash
            artifact["consumed_validation_status"] = freshness
            artifact["consumed_validated_at"] = utc_timestamp()
            consumption_metadata.setdefault("artifact_hash", current_hash)
            consumption_metadata.setdefault("freshness", freshness)
    write_manifest(path, data)
    return consumed[artifact_id]


def validate_artifact(
    manifest_file: Path | str,
    artifact_id: str,
    *,
    validator: Callable[[Path], tuple[bool, str | None]] | None = None,
) -> dict[str, Any]:
    path = Path(manifest_file)
    data = _read_manifest(path)
    artifact = data.setdefault("artifacts", {}).get(artifact_id)
    if not isinstance(artifact, dict):
        result = {
            "artifact_id": artifact_id,
            "validation_status": "missing",
            "failure_reason": "artifact is not recorded in manifest",
        }
        data.setdefault("events", []).append({"type": "artifact_validation", **result, "created_at": utc_timestamp()})
        write_manifest(path, data)
        return result

    file_path = Path(str(artifact.get("path") or ""))
    if not file_path.exists():
        status = "missing" if artifact.get("required", True) else "optional_missing"
        reason = "artifact path does not exist"
    else:
        current_hash = artifact_hash(file_path)
        if artifact.get("hash") and artifact.get("hash") != current_hash:
            status = "stale"
            reason = "artifact hash differs from manifest record"
        elif validator:
            valid, validation_reason = validator(file_path)
            status = "valid" if valid else "invalid"
            reason = validation_reason
        else:
            status = "valid"
            reason = None
        artifact["exists"] = True
        artifact["current_hash"] = current_hash
        stat = file_path.stat()
        artifact["current_size_bytes"] = stat.st_size

    artifact["validation_status"] = status
    artifact["failure_reason"] = reason
    artifact["validated_at"] = utc_timestamp()
    result = {
        "artifact_id": artifact_id,
        "validation_status": status,
        "failure_reason": reason,
        "hash": artifact.get("current_hash") or artifact.get("hash"),
    }
    data.setdefault("events", []).append({"type": "artifact_validation", **result, "created_at": utc_timestamp()})
    write_manifest(path, data)
    return result
