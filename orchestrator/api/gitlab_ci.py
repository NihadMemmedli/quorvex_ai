"""
GitLab CI/CD Integration API — Config, connection test, pipeline triggers, webhooks.

Stores GitLab credentials in Project.settings["integrations"]["gitlab"]
with encrypted access token and trigger token. Triggers pipelines, tracks
their status, and receives webhook updates.
"""

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session, select

from .credentials import decrypt_credential, encrypt_credential, mask_credential
from .db import get_session
from .middleware.auth import get_current_user_optional
from .models_auth import User
from .models_db import CiPipelineMapping, Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gitlab", tags=["gitlab"])


# -- Request / Response Models ------------------------------------


class GitlabConfigRequest(BaseModel):
    base_url: str
    token: str | None = None  # None means keep existing
    trigger_token: str | None = None  # None means keep existing
    project_id: int | None = None  # GitLab project ID
    default_ref: str | None = None
    webhook_secret: str | None = None


class TriggerPipelineRequest(BaseModel):
    ref: str | None = None  # Falls back to config default_ref
    variables: dict[str, str] | None = None


# -- Helpers ------------------------------------------------------


def _get_gitlab_config(project: Project) -> dict[str, Any] | None:
    """Read the GitLab config block from project settings."""
    if not project.settings:
        return None
    return (project.settings.get("integrations") or {}).get("gitlab")


def _save_gitlab_config(project: Project, config: dict[str, Any], session: Session):
    """Write the GitLab config block into project settings and persist."""
    if not project.settings:
        project.settings = {}
    integrations = project.settings.setdefault("integrations", {})
    integrations["gitlab"] = config
    flag_modified(project, "settings")
    session.add(project)
    session.commit()


def _require_project(project_id: str, session: Session) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _build_client(project: Project):
    """Build a GitlabClient from the project config. Raises 400 if not configured."""
    from services.gitlab_client import GitlabClient

    config = _get_gitlab_config(project)
    if not config:
        raise HTTPException(status_code=400, detail="GitLab not configured for this project")

    token = decrypt_credential(config.get("token_encrypted", ""))
    if not token:
        raise HTTPException(status_code=400, detail="GitLab access token could not be decrypted")

    return GitlabClient(
        base_url=config["base_url"],
        token=token,
    )


# -- Config Endpoints ---------------------------------------------


@router.get("/{project_id}/config")
def get_config(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Get GitLab config for a project (tokens masked)."""
    project = _require_project(project_id, session)
    config = _get_gitlab_config(project)
    if not config:
        return {"configured": False}

    token = decrypt_credential(config.get("token_encrypted", ""))
    trigger_token = decrypt_credential(config.get("trigger_token_encrypted", ""))
    return {
        "configured": True,
        "base_url": config.get("base_url", ""),
        "token_masked": mask_credential(token),
        "trigger_token_masked": mask_credential(trigger_token),
        "project_id": config.get("project_id"),
        "default_ref": config.get("default_ref", "main"),
        "has_webhook_secret": bool(config.get("webhook_secret")),
    }


@router.post("/{project_id}/config")
def save_config(
    project_id: str,
    request: GitlabConfigRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Save GitLab config for a project."""
    project = _require_project(project_id, session)

    if not request.base_url:
        raise HTTPException(status_code=400, detail="base_url is required")

    existing = _get_gitlab_config(project)

    # Handle access token - encrypt new or preserve existing
    if request.token:
        token_encrypted = encrypt_credential(request.token)
    elif existing and existing.get("token_encrypted"):
        token_encrypted = existing["token_encrypted"]
    else:
        raise HTTPException(status_code=400, detail="Access token is required for initial setup")

    # Handle trigger token - encrypt new or preserve existing
    if request.trigger_token:
        trigger_token_encrypted = encrypt_credential(request.trigger_token)
    elif existing and existing.get("trigger_token_encrypted"):
        trigger_token_encrypted = existing["trigger_token_encrypted"]
    else:
        trigger_token_encrypted = ""

    config = {
        "base_url": request.base_url.rstrip("/"),
        "token_encrypted": token_encrypted,
        "trigger_token_encrypted": trigger_token_encrypted,
        "project_id": request.project_id,
        "default_ref": request.default_ref or "main",
        "webhook_secret": request.webhook_secret or (existing or {}).get("webhook_secret", ""),
    }
    _save_gitlab_config(project, config, session)
    return {"status": "ok"}


@router.delete("/{project_id}/config")
def delete_config(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Remove GitLab config from a project."""
    project = _require_project(project_id, session)
    if project.settings and "integrations" in project.settings:
        project.settings["integrations"].pop("gitlab", None)
        flag_modified(project, "settings")
        session.add(project)
        session.commit()
    return {"status": "ok"}


# -- Connection Test ----------------------------------------------


@router.post("/{project_id}/test-connection")
async def test_connection(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Test the GitLab connection using stored credentials."""
    project = _require_project(project_id, session)
    client = await _build_client(project)
    try:
        user_info = await client.test_connection()
        return {
            "status": "ok",
            "user": user_info.get("name", user_info.get("username", "Unknown")),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {e}")
    finally:
        await client.close()


# -- Remote Browse ------------------------------------------------


@router.get("/{project_id}/remote-projects")
async def list_remote_projects(
    project_id: str,
    search: str | None = None,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List GitLab projects accessible with stored credentials."""
    project = _require_project(project_id, session)
    client = await _build_client(project)
    try:
        projects = await client.list_projects(search=search)
        return [
            {
                "id": p.get("id"),
                "name": p.get("name", ""),
                "path_with_namespace": p.get("path_with_namespace", ""),
                "web_url": p.get("web_url", ""),
                "default_branch": p.get("default_branch", "main"),
            }
            for p in projects
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        await client.close()


# -- Pipeline Trigger ---------------------------------------------


@router.post("/{project_id}/trigger-pipeline")
async def trigger_pipeline(
    project_id: str,
    request: TriggerPipelineRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Trigger a GitLab CI/CD pipeline."""
    project = _require_project(project_id, session)
    config = _get_gitlab_config(project)
    if not config:
        raise HTTPException(status_code=400, detail="GitLab not configured")

    gitlab_project_id = config.get("project_id")
    if not gitlab_project_id:
        raise HTTPException(status_code=400, detail="GitLab project ID not set in config")

    ref = request.ref or config.get("default_ref", "main")

    client = await _build_client(project)
    try:
        # Get trigger token if available
        trigger_token = decrypt_credential(config.get("trigger_token_encrypted", ""))

        pipeline = await client.trigger_pipeline(
            project_id=gitlab_project_id,
            ref=ref,
            variables=request.variables,
            trigger_token=trigger_token or None,
        )

        # Create tracking record
        mapping = CiPipelineMapping(
            project_id=project_id,
            provider="gitlab",
            external_pipeline_id=str(pipeline["id"]),
            external_project_id=str(gitlab_project_id),
            external_url=pipeline.get("web_url", ""),
            ref=ref,
            triggered_from="dashboard",
            status=pipeline.get("status", "pending"),
        )
        session.add(mapping)
        session.commit()
        session.refresh(mapping)

        return {
            "pipeline_id": pipeline["id"],
            "web_url": pipeline.get("web_url", ""),
            "status": pipeline.get("status", "pending"),
            "ref": ref,
            "mapping_id": mapping.id,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to trigger pipeline: {e}")
    finally:
        await client.close()


# -- Pipeline Queries ---------------------------------------------


@router.get("/{project_id}/pipelines")
def list_pipelines(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List tracked GitLab pipelines for a project."""
    _require_project(project_id, session)
    stmt = (
        select(CiPipelineMapping)
        .where(
            CiPipelineMapping.project_id == project_id,
            CiPipelineMapping.provider == "gitlab",
        )
        .order_by(CiPipelineMapping.created_at.desc())
    )
    mappings = session.exec(stmt).all()
    return [
        {
            "id": m.id,
            "external_pipeline_id": m.external_pipeline_id,
            "external_project_id": m.external_project_id,
            "external_url": m.external_url,
            "ref": m.ref,
            "triggered_from": m.triggered_from,
            "status": m.status,
            "stages": m.stages,
            "total_tests": m.total_tests,
            "passed_tests": m.passed_tests,
            "failed_tests": m.failed_tests,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "started_at": m.started_at.isoformat() if m.started_at else None,
            "completed_at": m.completed_at.isoformat() if m.completed_at else None,
        }
        for m in mappings
    ]


@router.get("/{project_id}/pipelines/{mapping_id}")
async def get_pipeline_detail(
    project_id: str,
    mapping_id: int,
    refresh: bool = False,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Get pipeline detail, optionally refreshing from GitLab API."""
    _require_project(project_id, session)
    mapping = session.get(CiPipelineMapping, mapping_id)
    if not mapping or mapping.project_id != project_id or mapping.provider != "gitlab":
        raise HTTPException(status_code=404, detail="Pipeline mapping not found")

    # Optionally refresh status from GitLab
    if refresh and mapping.status not in ("success", "failed", "canceled"):
        project = _require_project(project_id, session)
        try:
            client = await _build_client(project)
            try:
                gitlab_project_id = int(mapping.external_project_id or 0)
                pipeline_id = int(mapping.external_pipeline_id)
                pipeline = await client.get_pipeline(gitlab_project_id, pipeline_id)

                mapping.status = pipeline.get("status", mapping.status)
                mapping.external_url = pipeline.get("web_url", mapping.external_url)

                # Update timestamps
                if pipeline.get("started_at"):
                    try:
                        mapping.started_at = datetime.fromisoformat(pipeline["started_at"].replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        pass
                if pipeline.get("finished_at"):
                    try:
                        mapping.completed_at = datetime.fromisoformat(pipeline["finished_at"].replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        pass

                # Try to get jobs for stage info
                try:
                    jobs = await client.get_pipeline_jobs(gitlab_project_id, pipeline_id)
                    stages = []
                    seen_stages: dict[str, dict[str, Any]] = {}
                    for job in jobs:
                        stage_name = job.get("stage", "unknown")
                        if stage_name not in seen_stages:
                            seen_stages[stage_name] = {
                                "name": stage_name,
                                "status": job.get("status", "unknown"),
                            }
                        else:
                            # If any job in a stage failed, mark stage as failed
                            if job.get("status") == "failed":
                                seen_stages[stage_name]["status"] = "failed"
                    stages = list(seen_stages.values())
                    mapping.stages_json = json.dumps(stages)
                except Exception:
                    pass

                # Try to get test report
                try:
                    report = await client.get_pipeline_test_report(gitlab_project_id, pipeline_id)
                    mapping.total_tests = report.get("total_count", 0)
                    mapping.passed_tests = report.get("success_count", 0)
                    mapping.failed_tests = report.get("failed_count", 0)
                except Exception:
                    pass  # Test report may not exist

                session.add(mapping)
                session.commit()
                session.refresh(mapping)
            finally:
                await client.close()
        except HTTPException:
            pass  # Can't refresh, return stale data
        except Exception as e:
            logger.warning("Failed to refresh pipeline %d: %s", mapping_id, e)

    return {
        "id": mapping.id,
        "external_pipeline_id": mapping.external_pipeline_id,
        "external_project_id": mapping.external_project_id,
        "external_url": mapping.external_url,
        "ref": mapping.ref,
        "triggered_from": mapping.triggered_from,
        "status": mapping.status,
        "stages": mapping.stages,
        "total_tests": mapping.total_tests,
        "passed_tests": mapping.passed_tests,
        "failed_tests": mapping.failed_tests,
        "batch_id": mapping.batch_id,
        "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
        "started_at": mapping.started_at.isoformat() if mapping.started_at else None,
        "completed_at": mapping.completed_at.isoformat() if mapping.completed_at else None,
    }


# -- Webhook ------------------------------------------------------


async def _process_pipeline_webhook(payload: dict[str, Any]):
    """Background task: update pipeline mapping from webhook payload."""
    try:
        from sqlmodel import Session as SyncSession

        from .db import engine

        attrs = payload.get("object_attributes", {})
        pipeline_id = str(attrs.get("id", ""))
        if not pipeline_id:
            return

        with SyncSession(engine) as session:
            stmt = select(CiPipelineMapping).where(
                CiPipelineMapping.provider == "gitlab",
                CiPipelineMapping.external_pipeline_id == pipeline_id,
            )
            mapping = session.exec(stmt).first()
            if not mapping:
                logger.debug("No mapping found for GitLab pipeline %s", pipeline_id)
                return

            # Update status
            mapping.status = attrs.get("status", mapping.status)

            # Update timestamps
            if attrs.get("created_at"):
                try:
                    mapping.created_at = datetime.fromisoformat(attrs["created_at"].replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass
            if attrs.get("finished_at"):
                try:
                    mapping.completed_at = datetime.fromisoformat(attrs["finished_at"].replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

            # Update stages from builds array
            builds = payload.get("builds", [])
            if builds:
                seen_stages: dict[str, dict[str, Any]] = {}
                for build in builds:
                    stage_name = build.get("stage", "unknown")
                    if stage_name not in seen_stages:
                        seen_stages[stage_name] = {
                            "name": stage_name,
                            "status": build.get("status", "unknown"),
                        }
                    else:
                        if build.get("status") == "failed":
                            seen_stages[stage_name]["status"] = "failed"
                mapping.stages_json = json.dumps(list(seen_stages.values()))

            session.add(mapping)
            session.commit()
            logger.info(
                "Updated pipeline %s status to %s via webhook",
                pipeline_id,
                mapping.status,
            )

    except Exception as e:
        logger.error("Failed to process GitLab webhook: %s", e)


@router.post("/webhook/gitlab")
async def gitlab_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Receive GitLab webhook events for pipeline status updates.

    Validates the X-Gitlab-Token header against stored webhook secrets.
    Handles Pipeline Hook events to update CiPipelineMapping records.
    Returns 200 immediately, processing happens in background.
    """
    # Validate webhook token
    gitlab_token = request.headers.get("X-Gitlab-Token", "")
    event_type = request.headers.get("X-Gitlab-Event", "")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Only handle pipeline events
    if event_type != "Pipeline Hook":
        return {"status": "ignored", "event": event_type}

    # Validate token against stored webhook secrets
    # We need to find which project this webhook belongs to
    attrs = payload.get("object_attributes", {})
    pipeline_id = str(attrs.get("id", ""))

    if gitlab_token:
        # Try to validate against known project webhook secrets
        from sqlmodel import Session as SyncSession

        from .db import engine

        token_valid = False
        with SyncSession(engine) as session:
            # Look up the pipeline mapping to find the project
            if pipeline_id:
                stmt = select(CiPipelineMapping).where(
                    CiPipelineMapping.provider == "gitlab",
                    CiPipelineMapping.external_pipeline_id == pipeline_id,
                )
                mapping = session.exec(stmt).first()
                if mapping and mapping.project_id:
                    project = session.get(Project, mapping.project_id)
                    if project:
                        config = _get_gitlab_config(project)
                        if config and config.get("webhook_secret") == gitlab_token:
                            token_valid = True

            # If no mapping found yet, check all projects with gitlab config
            if not token_valid:
                stmt = select(Project)
                projects = session.exec(stmt).all()
                for proj in projects:
                    config = _get_gitlab_config(proj)
                    if config and config.get("webhook_secret") == gitlab_token:
                        token_valid = True
                        break

        if not token_valid:
            raise HTTPException(status_code=401, detail="Invalid webhook token")

    # Process in background
    background_tasks.add_task(_process_pipeline_webhook, payload)

    return {"status": "ok"}
