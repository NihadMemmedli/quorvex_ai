"""Durable status helpers for Temporal-managed domain jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Session

from orchestrator.api.db import engine
from orchestrator.api.models_db import DomainJob


def _now() -> datetime:
    return datetime.utcnow()


def create_domain_job(
    *,
    job_id: str,
    job_type: str,
    project_id: str | None,
    payload: dict[str, Any],
    progress: dict[str, Any] | None = None,
) -> DomainJob:
    """Create a durable job record before starting its Temporal workflow."""
    now = _now()
    with Session(engine) as session:
        job = DomainJob(
            id=job_id,
            job_type=job_type,
            project_id=project_id,
            status="queued",
            created_at=now,
            updated_at=now,
        )
        job.payload = payload
        job.progress = progress or {}
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def get_domain_job(job_id: str) -> DomainJob | None:
    with Session(engine) as session:
        job = session.get(DomainJob, job_id)
        if not job:
            return None
        session.expunge(job)
        return job


def update_domain_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    temporal_workflow_id: str | None = None,
    temporal_run_id: str | None = None,
    started: bool = False,
    completed: bool = False,
) -> DomainJob | None:
    """Patch a durable job status record idempotently."""
    now = _now()
    with Session(engine) as session:
        job = session.get(DomainJob, job_id)
        if not job:
            return None
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = progress
        if result is not None:
            job.result = result
        if error is not None:
            job.error = error
        if temporal_workflow_id is not None:
            job.temporal_workflow_id = temporal_workflow_id
        if temporal_run_id is not None:
            job.temporal_run_id = temporal_run_id
        if started and job.started_at is None:
            job.started_at = now
        if completed and job.completed_at is None:
            job.completed_at = now
        job.updated_at = now
        session.add(job)
        session.commit()
        session.refresh(job)
        session.expunge(job)
        return job


def domain_job_to_dict(job: DomainJob) -> dict[str, Any]:
    payload = job.payload
    progress = job.progress
    result = job.result
    response: dict[str, Any] = {
        "job_id": job.id,
        "status": job.status,
        "project_id": job.project_id,
        "temporal_workflow_id": job.temporal_workflow_id,
        "temporal_run_id": job.temporal_run_id,
    }
    sensitive_keys = {"credentials", "password", "token", "secret", "api_key"}
    response.update(
        {
            key: value
            for key, value in payload.items()
            if key not in response and key.lower() not in sensitive_keys
        }
    )
    if progress:
        response.update(progress)
    if job.status == "completed" and result is not None:
        response["result"] = result
    if job.status == "failed" and job.error:
        response["error"] = job.error
    return response
