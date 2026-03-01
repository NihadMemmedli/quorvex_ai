"""
GitHub Actions CI/CD Integration API - Config, connection test, workflow triggers, webhooks.

Stores GitHub credentials in Project.settings["integrations"]["github"]
with encrypted token and webhook secret. Supports triggering workflows,
tracking pipeline runs, and receiving webhook events.
"""

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

router = APIRouter(prefix="/github", tags=["github"])


# -- Request / Response Models ------------------------------------


class GithubConfigRequest(BaseModel):
    owner: str
    repo: str | None = ""  # Optional for initial setup (save owner+token first, pick repo later)
    token: str | None = None  # None means keep existing
    default_workflow: str | None = None
    default_ref: str | None = None
    webhook_secret: str | None = None  # None means keep existing


class TriggerWorkflowRequest(BaseModel):
    workflow_id: str | None = None  # Falls back to default_workflow
    ref: str | None = None  # Falls back to default_ref
    inputs: dict[str, str] | None = None


class SyncRunsRequest(BaseModel):
    workflow_id: str | None = None  # None = fetch all workflows
    per_page: int = 20


# -- Helpers -------------------------------------------------------


def _get_github_config(project: Project) -> dict[str, Any] | None:
    """Read the GitHub config block from project settings."""
    if not project.settings:
        return None
    return (project.settings.get("integrations") or {}).get("github")


def _save_github_config(project: Project, config: dict[str, Any], session: Session):
    """Write the GitHub config block into project settings and persist."""
    if not project.settings:
        project.settings = {}
    integrations = project.settings.setdefault("integrations", {})
    integrations["github"] = config
    flag_modified(project, "settings")
    session.add(project)
    session.commit()


def _require_project(project_id: str, session: Session) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _build_client(project: Project):
    """Build a GithubClient from the project config. Raises 400 if not configured."""
    from services.github_client import GithubClient

    config = _get_github_config(project)
    if not config:
        raise HTTPException(status_code=400, detail="GitHub not configured for this project")

    token = decrypt_credential(config.get("token_encrypted", ""))
    if not token:
        raise HTTPException(status_code=400, detail="GitHub token could not be decrypted")

    return GithubClient(token=token)


# -- Config Endpoints ----------------------------------------------


@router.get("/{project_id}/config")
def get_config(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Get GitHub config for a project (token masked)."""
    project = _require_project(project_id, session)
    config = _get_github_config(project)
    if not config:
        return {"configured": False}

    token = decrypt_credential(config.get("token_encrypted", ""))
    webhook_secret = decrypt_credential(config.get("webhook_secret_encrypted", ""))

    return {
        "configured": True,
        "owner": config.get("owner", ""),
        "repo": config.get("repo", ""),
        "token_masked": mask_credential(token),
        "default_workflow": config.get("default_workflow"),
        "default_ref": config.get("default_ref"),
        "webhook_secret_masked": mask_credential(webhook_secret) if webhook_secret else None,
    }


@router.post("/{project_id}/config")
def save_config(
    project_id: str,
    request: GithubConfigRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Save GitHub config for a project."""
    project = _require_project(project_id, session)

    if not request.owner:
        raise HTTPException(status_code=400, detail="owner is required")

    existing = _get_github_config(project)

    # Handle token encryption
    if request.token:
        token_encrypted = encrypt_credential(request.token)
    elif existing and existing.get("token_encrypted"):
        token_encrypted = existing["token_encrypted"]
    else:
        raise HTTPException(status_code=400, detail="Token is required for initial setup")

    # Handle webhook secret encryption
    webhook_secret_encrypted = None
    if request.webhook_secret:
        webhook_secret_encrypted = encrypt_credential(request.webhook_secret)
    elif existing and existing.get("webhook_secret_encrypted"):
        webhook_secret_encrypted = existing["webhook_secret_encrypted"]

    config = {
        "owner": request.owner,
        "repo": request.repo or "",
        "token_encrypted": token_encrypted,
        "default_workflow": request.default_workflow,
        "default_ref": request.default_ref or "main",
        "webhook_secret_encrypted": webhook_secret_encrypted,
    }
    _save_github_config(project, config, session)
    return {"status": "ok"}


@router.delete("/{project_id}/config")
def delete_config(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Remove GitHub config from a project."""
    project = _require_project(project_id, session)
    if project.settings and "integrations" in project.settings:
        project.settings["integrations"].pop("github", None)
        flag_modified(project, "settings")
        session.add(project)
        session.commit()
    return {"status": "ok"}


# -- Connection Test -----------------------------------------------


@router.post("/{project_id}/test-connection")
async def test_connection(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Test the GitHub connection using stored credentials."""
    project = _require_project(project_id, session)
    client = await _build_client(project)
    try:
        user_info = await client.test_connection()
        return {
            "status": "ok",
            "user": user_info.get("login", "Unknown"),
            "name": user_info.get("name"),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {e}")
    finally:
        await client.close()


# -- Remote Browse -------------------------------------------------


@router.get("/{project_id}/remote-repos")
async def list_remote_repos(
    project_id: str,
    search: str | None = None,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List GitHub repositories accessible with stored credentials."""
    project = _require_project(project_id, session)
    client = await _build_client(project)
    try:
        repos = await client.list_repos(search=search)
        return [
            {
                "full_name": r.get("full_name", ""),
                "name": r.get("name", ""),
                "owner": r.get("owner", {}).get("login", ""),
                "private": r.get("private", False),
                "default_branch": r.get("default_branch", "main"),
                "html_url": r.get("html_url", ""),
            }
            for r in repos
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        await client.close()


@router.get("/{project_id}/remote-workflows")
async def list_remote_workflows(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List GitHub Actions workflows for the configured repository."""
    project = _require_project(project_id, session)
    config = _get_github_config(project)
    if not config:
        raise HTTPException(status_code=400, detail="GitHub not configured for this project")

    owner = config.get("owner", "")
    repo = config.get("repo", "")
    if not owner or not repo:
        raise HTTPException(status_code=400, detail="owner and repo must be configured")

    client = await _build_client(project)
    try:
        workflows = await client.list_workflows(owner, repo)
        return [
            {
                "id": w.get("id"),
                "name": w.get("name", ""),
                "path": w.get("path", ""),
                "state": w.get("state", ""),
            }
            for w in workflows
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        await client.close()


# -- Trigger Workflow ----------------------------------------------


@router.post("/{project_id}/trigger-workflow")
async def trigger_workflow(
    project_id: str,
    request: TriggerWorkflowRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Trigger a GitHub Actions workflow_dispatch event."""
    project = _require_project(project_id, session)
    config = _get_github_config(project)
    if not config:
        raise HTTPException(status_code=400, detail="GitHub not configured for this project")

    owner = config.get("owner", "")
    repo = config.get("repo", "")
    workflow_id = request.workflow_id or config.get("default_workflow")
    ref = request.ref or config.get("default_ref", "main")

    if not owner or not repo:
        raise HTTPException(status_code=400, detail="owner and repo must be configured")
    if not workflow_id:
        raise HTTPException(
            status_code=400,
            detail="workflow_id is required (or set default_workflow in config)",
        )

    client = await _build_client(project)
    try:
        await client.trigger_workflow(
            owner=owner,
            repo=repo,
            workflow_id=workflow_id,
            ref=ref,
            inputs=request.inputs,
        )

        # Fetch the latest run for this workflow to get external_pipeline_id
        # GitHub creates the run asynchronously, so we fetch recent runs
        runs = await client.get_workflow_runs(owner=owner, repo=repo, workflow_id=workflow_id, per_page=1)

        external_pipeline_id = ""
        external_url = ""
        if runs:
            latest = runs[0]
            external_pipeline_id = str(latest.get("id", ""))
            external_url = latest.get("html_url", "")

        # Create tracking record
        mapping = CiPipelineMapping(
            project_id=project_id,
            provider="github",
            external_pipeline_id=external_pipeline_id or f"pending-{workflow_id}-{ref}",
            external_project_id=f"{owner}/{repo}",
            external_url=external_url,
            ref=ref,
            triggered_from="dashboard",
            status="pending",
        )
        session.add(mapping)
        session.commit()
        session.refresh(mapping)

        return {
            "status": "triggered",
            "mapping_id": mapping.id,
            "workflow_id": workflow_id,
            "ref": ref,
            "external_pipeline_id": external_pipeline_id,
            "external_url": external_url,
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to trigger workflow: {e}")
    finally:
        await client.close()


# -- Pipeline Tracking ---------------------------------------------


@router.get("/{project_id}/pipelines")
def list_pipelines(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List tracked GitHub pipeline mappings for this project."""
    _require_project(project_id, session)
    stmt = (
        select(CiPipelineMapping)
        .where(
            CiPipelineMapping.project_id == project_id,
            CiPipelineMapping.provider == "github",
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
            "status": m.status,
            "triggered_from": m.triggered_from,
            "stages": m.stages,
            "name": m.external_pipeline_id,
            "total_tests": m.total_tests,
            "passed_tests": m.passed_tests,
            "failed_tests": m.failed_tests,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "started_at": m.started_at.isoformat() if m.started_at else None,
            "completed_at": m.completed_at.isoformat() if m.completed_at else None,
        }
        for m in mappings
    ]


@router.post("/{project_id}/sync-runs")
async def sync_runs(
    project_id: str,
    request: SyncRunsRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Sync workflow runs from GitHub into local CiPipelineMapping records.

    Fetches recent runs from GitHub API, creates new mappings for runs not
    already tracked, and refreshes status of active (pending/running) runs.
    """
    project = _require_project(project_id, session)
    config = _get_github_config(project)
    if not config:
        raise HTTPException(status_code=400, detail="GitHub not configured for this project")

    owner = config.get("owner", "")
    repo = config.get("repo", "")
    if not owner or not repo:
        raise HTTPException(status_code=400, detail="owner and repo must be configured")

    client = await _build_client(project)
    try:
        runs = await client.get_workflow_runs(
            owner=owner,
            repo=repo,
            workflow_id=request.workflow_id,
            per_page=request.per_page,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch runs: {e}")
    finally:
        await client.close()

    # Load existing external_pipeline_ids for dedup
    stmt = select(CiPipelineMapping.external_pipeline_id).where(
        CiPipelineMapping.project_id == project_id,
        CiPipelineMapping.provider == "github",
    )
    existing_ids = set(session.exec(stmt).all())

    # Also load active mappings for status refresh
    active_stmt = select(CiPipelineMapping).where(
        CiPipelineMapping.project_id == project_id,
        CiPipelineMapping.provider == "github",
        CiPipelineMapping.status.in_(["pending", "running"]),
    )
    active_mappings = {m.external_pipeline_id: m for m in session.exec(active_stmt).all()}

    created = 0
    updated = 0

    for run in runs:
        run_id_str = str(run.get("id", ""))
        if not run_id_str:
            continue

        if run_id_str not in existing_ids:
            # Parse created_at from GitHub
            gh_created = run.get("created_at", "")
            created_dt = datetime.utcnow()
            if gh_created:
                try:
                    created_dt = datetime.fromisoformat(gh_created.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

            mapping = CiPipelineMapping(
                project_id=project_id,
                provider="github",
                external_pipeline_id=run_id_str,
                external_project_id=f"{owner}/{repo}",
                external_url=run.get("html_url", ""),
                ref=run.get("head_branch", ""),
                triggered_from="sync",
                status="pending",
                created_at=created_dt,
            )
            _update_mapping_from_run(mapping, run)
            session.add(mapping)
            created += 1
        elif run_id_str in active_mappings:
            # Refresh status for active pipelines
            _update_mapping_from_run(active_mappings[run_id_str], run)
            session.add(active_mappings[run_id_str])
            updated += 1

    session.commit()
    logger.info("Synced GitHub runs for project %s: created=%d, updated=%d", project_id, created, updated)
    return {"status": "ok", "created": created, "updated": updated}


@router.get("/{project_id}/pipelines/{pipeline_mapping_id}")
async def get_pipeline_detail(
    project_id: str,
    pipeline_mapping_id: int,
    refresh: bool = False,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Get pipeline detail with optional refresh from GitHub API."""
    project = _require_project(project_id, session)
    mapping = session.get(CiPipelineMapping, pipeline_mapping_id)
    if not mapping or mapping.project_id != project_id or mapping.provider != "github":
        raise HTTPException(status_code=404, detail="Pipeline mapping not found")

    # Optionally refresh status from GitHub
    if refresh and mapping.external_pipeline_id and not mapping.external_pipeline_id.startswith("pending-"):
        config = _get_github_config(project)
        if config:
            owner = config.get("owner", "")
            repo = config.get("repo", "")
            if owner and repo:
                client = await _build_client(project)
                try:
                    run_data = await client.get_run(owner, repo, int(mapping.external_pipeline_id))
                    _update_mapping_from_run(mapping, run_data)

                    # Fetch jobs for stage details
                    jobs = await client.get_run_jobs(owner, repo, int(mapping.external_pipeline_id))
                    if jobs:
                        import json

                        mapping.stages_json = json.dumps(
                            [
                                {
                                    "name": j.get("name", ""),
                                    "status": j.get("conclusion") or j.get("status", ""),
                                    "started_at": j.get("started_at"),
                                    "completed_at": j.get("completed_at"),
                                }
                                for j in jobs
                            ]
                        )

                    session.add(mapping)
                    session.commit()
                    session.refresh(mapping)
                except Exception as e:
                    logger.warning("Failed to refresh pipeline %s: %s", mapping.id, e)
                finally:
                    await client.close()

    return {
        "id": mapping.id,
        "external_pipeline_id": mapping.external_pipeline_id,
        "external_project_id": mapping.external_project_id,
        "external_url": mapping.external_url,
        "ref": mapping.ref,
        "status": mapping.status,
        "triggered_from": mapping.triggered_from,
        "stages": mapping.stages,
        "total_tests": mapping.total_tests,
        "passed_tests": mapping.passed_tests,
        "failed_tests": mapping.failed_tests,
        "test_report_url": mapping.test_report_url,
        "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
        "started_at": mapping.started_at.isoformat() if mapping.started_at else None,
        "completed_at": mapping.completed_at.isoformat() if mapping.completed_at else None,
    }


# -- Webhook -------------------------------------------------------


def _update_mapping_from_run(mapping: CiPipelineMapping, run_data: dict[str, Any]):
    """Update a CiPipelineMapping from a GitHub workflow_run payload."""
    # Map GitHub status/conclusion to our status
    gh_status = run_data.get("status", "")
    gh_conclusion = run_data.get("conclusion")

    if gh_status == "completed":
        if gh_conclusion == "success":
            mapping.status = "success"
        elif gh_conclusion == "failure":
            mapping.status = "failed"
        elif gh_conclusion == "cancelled":
            mapping.status = "cancelled"
        else:
            mapping.status = gh_conclusion or "failed"
    elif gh_status == "in_progress":
        mapping.status = "running"
    elif gh_status == "queued":
        mapping.status = "pending"

    mapping.external_url = run_data.get("html_url", mapping.external_url)

    # Parse timestamps
    run_started = run_data.get("run_started_at")
    if run_started:
        try:
            mapping.started_at = datetime.fromisoformat(run_started.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    updated_at = run_data.get("updated_at")
    if gh_status == "completed" and updated_at:
        try:
            mapping.completed_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass


async def _process_webhook(
    payload: dict[str, Any],
    session_factory,
):
    """Background task to process a GitHub webhook event."""
    try:
        payload.get("action", "")
        workflow_run = payload.get("workflow_run", {})
        run_id = str(workflow_run.get("id", ""))

        if not run_id:
            logger.debug("Webhook payload missing workflow_run.id, skipping")
            return

        from sqlmodel import Session as _Session

        from .db import engine

        with _Session(engine) as session:
            # Find matching pipeline mapping
            stmt = select(CiPipelineMapping).where(
                CiPipelineMapping.provider == "github",
                CiPipelineMapping.external_pipeline_id == run_id,
            )
            mapping = session.exec(stmt).first()

            if not mapping:
                logger.debug("No pipeline mapping found for GitHub run %s, skipping", run_id)
                return

            _update_mapping_from_run(mapping, workflow_run)
            session.add(mapping)
            session.commit()

            logger.info(
                "Updated pipeline mapping %s from webhook: status=%s",
                mapping.id,
                mapping.status,
            )

    except Exception as e:
        logger.error("Error processing GitHub webhook: %s", e)


@router.post("/webhook/github")
async def handle_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Receive GitHub webhook events.

    Validates X-Hub-Signature-256 using HMAC-SHA256 if a webhook secret
    is configured. Handles workflow_run events to update pipeline status.
    """
    body = await request.body()
    event_type = request.headers.get("X-GitHub-Event", "")
    signature = request.headers.get("X-Hub-Signature-256", "")

    # Try to validate signature if any project has a webhook secret configured
    # We validate signature per-project since different projects may have different secrets
    if signature:
        from sqlmodel import Session as _Session

        from services.github_client import verify_webhook_signature

        from .db import engine

        validated = False
        with _Session(engine) as session:
            projects = session.exec(select(Project)).all()
            for project in projects:
                config = _get_github_config(project)
                if not config:
                    continue
                secret_encrypted = config.get("webhook_secret_encrypted")
                if not secret_encrypted:
                    continue
                secret = decrypt_credential(secret_encrypted)
                if secret and verify_webhook_signature(body, signature, secret):
                    validated = True
                    break

        if not validated:
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Only process workflow_run events
    if event_type != "workflow_run":
        return {"status": "ignored", "event": event_type}

    try:
        import json

        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    background_tasks.add_task(_process_webhook, payload, None)
    return {"status": "ok"}
