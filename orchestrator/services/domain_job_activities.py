"""Temporal activities for domain-specific background jobs."""

from __future__ import annotations

from typing import Any


async def execute_domain_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Run an existing domain job handler inside a Temporal activity."""
    job_type = str(payload.get("job_type") or "")
    job_id = str(payload.get("job_id") or "")
    if not job_type or not job_id:
        raise ValueError("Domain job payload requires job_type and job_id")

    if job_type == "requirements_generate":
        from orchestrator.api.requirements import _run_requirements_generation

        await _run_requirements_generation(
            job_id,
            str(payload["project_id"]),
            str(payload["session_id"]),
            str(payload.get("mode") or "single_agent"),
            int(payload.get("max_agents") or 3),
            str(payload.get("browser_verification") or "off"),
        )
    elif job_type == "requirements_bulk_generate":
        from orchestrator.api.requirements import _run_bulk_spec_generation

        await _run_bulk_spec_generation(
            job_id,
            str(payload["project_id"]),
            str(payload["target_url"]),
            payload.get("login_url"),
            payload.get("credentials"),
        )
    elif job_type == "rtm_generate":
        from orchestrator.api.rtm import _run_rtm_generation

        await _run_rtm_generation(
            job_id,
            str(payload["project_id"]),
            payload.get("specs_paths"),
            bool(payload.get("use_ai_matching", True)),
        )
    else:
        raise ValueError(f"Unsupported domain job type: {job_type}")

    return {"job_id": job_id, "job_type": job_type, "status": "completed"}
