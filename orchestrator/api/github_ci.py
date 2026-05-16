"""
GitHub Actions CI/CD Integration API - Config, connection test, workflow triggers, webhooks.

Stores GitHub credentials in Project.settings["integrations"]["github"]
with encrypted token and webhook secret. Supports triggering workflows,
tracking pipeline runs, and receiving webhook events.
"""

import logging
import os
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
from .models_db import (
    CiPipelineMapping,
    PrImpactAnalysis,
    PrSelectedTest,
    Project,
    RegressionBatch,
    RepoIndexSnapshot,
    TestRun as DBTestRun,
)

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


class PrAdvisorAnalyzeRequest(BaseModel):
    pr_number: int
    ensure_indexed: bool = True
    force_reindex: bool = False


class PrAdvisorRunRequest(BaseModel):
    browser: str = "chromium"
    hybrid: bool = False
    max_iterations: int = 20


class PrQualityGateStartRequest(BaseModel):
    pr_number: int
    head_sha: str | None = None
    ensure_indexed: bool = True
    force_reindex: bool = False
    run_recommended: bool = True
    post_feedback: bool = True
    create_commit_status: bool = True
    browser: str = "chromium"
    hybrid: bool = False
    max_iterations: int = 20


class RepositoryIndexRequest(BaseModel):
    ref: str | None = None
    force: bool = False


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


# -- Repository Index ----------------------------------------------


def _serialize_repo_index(snapshot: RepoIndexSnapshot, derived_impact_maps: int | None = None) -> dict[str, Any]:
    return {
        "status": snapshot.status,
        "snapshot_id": snapshot.id,
        "owner": snapshot.owner,
        "repo": snapshot.repo,
        "ref": snapshot.ref,
        "commit_sha": snapshot.commit_sha,
        "file_count": snapshot.indexed_files_count,
        "source_files_count": snapshot.source_files_count,
        "test_files_count": snapshot.test_files_count,
        "route_count": snapshot.route_count,
        "derived_impact_maps": derived_impact_maps,
        "summary": snapshot.summary,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "completed_at": snapshot.completed_at.isoformat() if snapshot.completed_at else None,
    }


def _should_index_path(path: str, size: int | None = None) -> bool:
    if size and size > 250_000:
        return False
    lower = path.lower()
    if lower.startswith(("node_modules/", ".next/", "dist/", "build/", ".git/", "test-results/", "runs/")):
        return False
    return lower.endswith((
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".py",
        ".md",
        ".json",
        ".yaml",
        ".yml",
    ))


async def _build_repository_index(
    *,
    project_id: str,
    owner: str,
    repo: str,
    ref: str,
    client,
    session: Session,
    force: bool = False,
):
    from orchestrator.services.pr_test_advisor import RepoFileInput, index_repository_snapshot, latest_repo_index

    tree = await client.get_tree(owner, repo, ref, recursive=True)
    commit_sha = None
    if tree:
        commit_sha = next((item.get("sha") for item in tree if item.get("path") == "package.json"), None)
    existing = latest_repo_index(project_id, owner, repo, ref, session, commit_sha=commit_sha) if not force else None
    if existing:
        return existing, None

    selected_files = [
        item
        for item in tree
        if item.get("type") == "blob" and _should_index_path(item.get("path", ""), item.get("size"))
    ][:800]
    repo_files = []
    for item in selected_files:
        path = item.get("path", "")
        content = await client.get_file_content(owner, repo, path, ref=ref)
        if content is None:
            continue
        repo_files.append(
            RepoFileInput(
                path=path,
                sha=item.get("sha"),
                size=item.get("size"),
                content=content,
            )
        )
    result = index_repository_snapshot(
        project_id=project_id,
        owner=owner,
        repo=repo,
        ref=ref,
        commit_sha=commit_sha,
        files=repo_files,
        session=session,
    )
    return result.snapshot, result.derived_impact_maps


@router.post("/{project_id}/repository-index")
async def create_repository_index(
    project_id: str,
    request: RepositoryIndexRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Index the configured GitHub repository so PR Advisor can reason over repo context."""
    project = _require_project(project_id, session)
    config = _get_github_config(project)
    if not config:
        raise HTTPException(status_code=400, detail="GitHub not configured for this project")
    owner = config.get("owner", "")
    repo = config.get("repo", "")
    ref = request.ref or config.get("default_ref") or "main"
    if not owner or not repo:
        raise HTTPException(status_code=400, detail="owner and repo must be configured")

    client = await _build_client(project)
    try:
        snapshot, derived = await _build_repository_index(
            project_id=project_id,
            owner=owner,
            repo=repo,
            ref=ref,
            client=client,
            session=session,
            force=request.force,
        )
        return _serialize_repo_index(snapshot, derived_impact_maps=derived)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to index repository: {e}")
    finally:
        await client.close()


@router.get("/{project_id}/repository-index/latest")
def get_latest_repository_index(
    project_id: str,
    ref: str | None = None,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Return the latest completed repository index for this project."""
    project = _require_project(project_id, session)
    config = _get_github_config(project)
    owner = (config or {}).get("owner", "")
    repo = (config or {}).get("repo", "")
    target_ref = ref or (config or {}).get("default_ref") or "main"
    stmt = (
        select(RepoIndexSnapshot)
        .where(
            RepoIndexSnapshot.project_id == project_id,
            RepoIndexSnapshot.ref == target_ref,
            RepoIndexSnapshot.status == "completed",
        )
        .order_by(RepoIndexSnapshot.created_at.desc())
    )
    if owner:
        stmt = stmt.where(RepoIndexSnapshot.owner == owner)
    if repo:
        stmt = stmt.where(RepoIndexSnapshot.repo == repo)
    snapshot = session.exec(stmt).first()
    if not snapshot:
        return {"status": "missing", "ref": target_ref}
    return _serialize_repo_index(snapshot)


# -- PR Quality Gate -----------------------------------------------


TERMINAL_RUN_STATUSES = {"passed", "completed", "failed", "error", "stopped", "cancelled", "canceled"}
FAILURE_RUN_STATUSES = {"failed", "error", "stopped", "cancelled", "canceled"}
ACTIVE_RUN_STATUSES = {"queued", "running", "in_progress", "pending"}
QUALITY_GATE_CONTEXT = "Quorvex Quality Gate"
QUALITY_GATE_COMMENT_MARKER = "<!-- quorvex-quality-gate -->"


async def _analyze_configured_github_pr(
    *,
    project_id: str,
    request: PrQualityGateStartRequest | PrAdvisorAnalyzeRequest,
    session: Session,
) -> PrImpactAnalysis:
    """Analyze a configured GitHub PR and persist a PrImpactAnalysis."""
    from orchestrator.services.pr_test_advisor import analyze_pr_changes

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
        pr_data = await client.get_pull_request(owner, repo, request.pr_number)
        expected_sha = getattr(request, "head_sha", None)
        actual_sha = (pr_data.get("head") or {}).get("sha")
        if expected_sha and actual_sha and expected_sha != actual_sha:
            raise HTTPException(
                status_code=409,
                detail="PR head SHA changed before analysis could start; retry for the latest commit.",
            )

        base_ref = (pr_data.get("base") or {}).get("ref") or config.get("default_ref") or "main"
        snapshot = None
        if request.ensure_indexed:
            snapshot, _derived = await _build_repository_index(
                project_id=project_id,
                owner=owner,
                repo=repo,
                ref=base_ref,
                client=client,
                session=session,
                force=request.force_reindex,
            )
        changed_files = await client.list_pull_request_files(owner, repo, request.pr_number)
        return analyze_pr_changes(
            project_id=project_id,
            owner=owner,
            repo=repo,
            pr_number=request.pr_number,
            pr_data=pr_data,
            changed_files=changed_files,
            session=session,
            snapshot_id=snapshot.id if snapshot else None,
        )
    finally:
        await client.close()


def _start_recommended_batch(
    *,
    project_id: str,
    analysis: PrImpactAnalysis,
    request: PrAdvisorRunRequest | PrQualityGateStartRequest,
    session: Session,
) -> dict[str, Any]:
    """Create and start the regression batch selected by PR analysis."""
    selected = session.exec(select(PrSelectedTest).where(PrSelectedTest.analysis_id == analysis.id)).all()
    spec_names = [t.spec_name for t in selected]
    if not spec_names:
        return {"batch_created": False, "reason": "Analysis has no selected tests to run"}

    from orchestrator.services.batch_executor import BatchConfig, create_regression_batch

    config = BatchConfig(
        project_id=project_id,
        browser=request.browser,
        hybrid_mode=request.hybrid,
        max_iterations=request.max_iterations,
        automated_only=False,
        spec_names=spec_names,
        triggered_by="quality-gate",
        batch_name=f"PR #{analysis.pr_number} Quality Gate",
    )

    try:
        result = create_regression_batch(config, session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    import asyncio

    from .main import PROCESS_MANAGER, execute_run_task_wrapper

    for task_args in result.tasks_to_start:
        task = asyncio.ensure_future(
            execute_run_task_wrapper(
                spec_path=task_args["spec_path"],
                run_dir=task_args["run_dir"],
                run_id=task_args["run_id"],
                try_code_path=task_args.get("try_code_path"),
                browser=task_args["browser"],
                hybrid=task_args["hybrid"],
                max_iterations=task_args["max_iterations"],
                batch_id=task_args["batch_id"],
                spec_name=task_args["spec_name"],
                project_id=task_args["project_id"],
            )
        )
        if hasattr(PROCESS_MANAGER, "register_task"):
            PROCESS_MANAGER.register_task(task_args["run_id"], task)

    analysis.batch_id = result.batch_id
    analysis.updated_at = datetime.utcnow()
    session.add(analysis)
    session.commit()

    return {
        "batch_created": True,
        "batch_id": result.batch_id,
        "run_ids": result.run_ids,
        "count": len(result.run_ids),
    }


def _batch_payload(batch: RegressionBatch | None, session: Session) -> dict[str, Any] | None:
    if not batch:
        return None
    runs = session.exec(select(DBTestRun).where(DBTestRun.batch_id == batch.id)).all()
    failed_runs = [r for r in runs if r.status in FAILURE_RUN_STATUSES]
    return {
        "id": batch.id,
        "name": batch.name,
        "status": batch.status,
        "total_tests": batch.actual_total_tests if batch.actual_total_tests is not None else batch.total_tests,
        "passed": batch.actual_passed if batch.actual_passed is not None else batch.passed,
        "failed": batch.actual_failed if batch.actual_failed is not None else batch.failed,
        "stopped": batch.stopped,
        "running": batch.running,
        "queued": batch.queued,
        "success_rate": batch.success_rate,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
        "failed_tests": [
            {
                "run_id": r.id,
                "spec_name": r.spec_name,
                "status": r.status,
                "error_message": r.error_message,
            }
            for r in failed_runs[:20]
        ],
    }


def _quality_gate_status(analysis: PrImpactAnalysis, batch: RegressionBatch | None, session: Session) -> dict[str, Any]:
    if not analysis.selected_tests_count:
        return {
            "state": "blocked",
            "github_state": "error",
            "description": "No runnable Quorvex tests were selected",
        }
    if not batch:
        if analysis.fallback_reason:
            return {
                "state": "needs-full-suite",
                "github_state": "error",
                "description": "Full suite recommended before merge",
            }
        return {
            "state": "analyzed",
            "github_state": "pending",
            "description": "Quorvex selected PR tests; run is pending",
        }

    runs = session.exec(select(DBTestRun.status).where(DBTestRun.batch_id == batch.id)).all()
    has_active = any(status in ACTIVE_RUN_STATUSES for status in runs)
    has_failure = any(status in FAILURE_RUN_STATUSES for status in runs)
    all_terminal = bool(runs) and all(status in TERMINAL_RUN_STATUSES for status in runs)

    if has_active or batch.status in {"pending", "running"}:
        return {
            "state": "running",
            "github_state": "pending",
            "description": "Quorvex PR tests are running",
        }
    if has_failure or batch.failed > 0 or batch.stopped > 0:
        return {
            "state": "failed",
            "github_state": "failure",
            "description": "Quorvex PR tests failed",
        }
    if all_terminal and (batch.passed > 0 or (batch.actual_passed or 0) > 0):
        return {
            "state": "passed",
            "github_state": "success",
            "description": "Quorvex PR tests passed",
        }
    return {
        "state": "blocked",
        "github_state": "error",
        "description": "Quorvex could not determine a passing gate result",
    }


def _app_url(path: str) -> str | None:
    base = os.getenv("WEB_BASE_URL") or os.getenv("FRONTEND_URL") or os.getenv("APP_BASE_URL")
    if not base:
        return None
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _serialize_quality_gate(analysis: PrImpactAnalysis, session: Session, include_details: bool = True) -> dict[str, Any]:
    from orchestrator.services.pr_test_advisor import serialize_analysis

    batch = session.get(RegressionBatch, analysis.batch_id) if analysis.batch_id else None
    gate = _quality_gate_status(analysis, batch, session)
    payload = serialize_analysis(analysis, session, include_details=include_details)
    payload["quality_gate"] = {
        **gate,
        "batch": _batch_payload(batch, session),
        "analysis_url": _app_url(f"pr-advisor"),
        "batch_url": _app_url(f"regression/batches/{analysis.batch_id}") if analysis.batch_id else None,
    }
    return payload


def _quality_gate_comment(payload: dict[str, Any]) -> str:
    gate = payload["quality_gate"]
    selected = payload.get("selected_tests") or []
    failed = ((gate.get("batch") or {}).get("failed_tests") or [])
    selected_lines = "\n".join(
        f"- `{item['spec_name']}`: {item.get('reason', 'Selected by impact analysis')}" for item in selected[:12]
    )
    if len(selected) > 12:
        selected_lines += f"\n- ...and {len(selected) - 12} more"
    failed_lines = "\n".join(
        f"- `{item['spec_name']}`: {item.get('status')}" for item in failed[:10]
    )
    links = []
    if gate.get("batch_url"):
        links.append(f"[View regression batch]({gate['batch_url']})")
    if gate.get("analysis_url"):
        links.append(f"[Open PR Advisor]({gate['analysis_url']})")
    links_line = " | ".join(links)
    fallback = f"\n\n**Fallback:** {payload['fallback_reason']}" if payload.get("fallback_reason") else ""
    failures = f"\n\n**Failed tests**\n{failed_lines}" if failed_lines else ""
    return (
        f"{QUALITY_GATE_COMMENT_MARKER}\n"
        "## Quorvex Quality Gate\n\n"
        f"**Status:** `{gate['state']}`  \n"
        f"**Risk:** `{payload['risk_level']}`  \n"
        f"**Confidence:** `{payload['confidence']}`  \n"
        f"**Changed files:** {payload['changed_files_count']}  \n"
        f"**Selected tests:** {payload['selected_tests_count']} of {payload['total_candidate_tests']}  \n"
        f"**Estimated time saved:** {payload.get('saved_tests_count') or 0} tests skipped"
        f"{fallback}\n\n"
        f"**Recommended tests**\n{selected_lines or '- No tests selected'}"
        f"{failures}\n\n"
        f"{links_line}"
    )


async def _publish_quality_gate_feedback(
    *,
    project: Project,
    analysis: PrImpactAnalysis,
    payload: dict[str, Any],
    post_feedback: bool,
    create_commit_status: bool,
) -> dict[str, Any]:
    config = _get_github_config(project) or {}
    owner = config.get("owner", "")
    repo = config.get("repo", "")
    errors: list[str] = []
    result: dict[str, Any] = {"comment": None, "commit_status": None, "errors": errors}
    if not owner or not repo:
        return result

    client = await _build_client(project)
    try:
        if post_feedback:
            try:
                comments = await client.list_issue_comments(owner, repo, analysis.pr_number)
                existing = next((c for c in comments if QUALITY_GATE_COMMENT_MARKER in (c.get("body") or "")), None)
                body = _quality_gate_comment(payload)
                if existing and existing.get("id"):
                    updated = await client.update_issue_comment(owner, repo, int(existing["id"]), body)
                    result["comment"] = {"action": "updated", "url": updated.get("html_url")}
                else:
                    created = await client.create_issue_comment(owner, repo, analysis.pr_number, body)
                    result["comment"] = {"action": "created", "url": created.get("html_url")}
            except Exception as e:
                errors.append(f"PR comment failed: {e}")

        if create_commit_status and analysis.head_sha:
            try:
                gate = payload["quality_gate"]
                status = await client.create_commit_status(
                    owner,
                    repo,
                    analysis.head_sha,
                    state=gate["github_state"],
                    context=QUALITY_GATE_CONTEXT,
                    description=gate["description"],
                    target_url=gate.get("batch_url") or gate.get("analysis_url"),
                )
                result["commit_status"] = {"state": status.get("state"), "url": status.get("target_url")}
            except Exception as e:
                errors.append(f"Commit status failed: {e}")
    finally:
        await client.close()
    return result


@router.post("/{project_id}/quality-gates/pr/start")
async def start_pr_quality_gate(
    project_id: str,
    request: PrQualityGateStartRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Analyze a GitHub PR, optionally run selected tests, and publish quality-gate feedback."""
    project = _require_project(project_id, session)
    analysis = await _analyze_configured_github_pr(project_id=project_id, request=request, session=session)
    run_result = None
    if request.run_recommended:
        run_result = _start_recommended_batch(project_id=project_id, analysis=analysis, request=request, session=session)
        session.refresh(analysis)

    payload = _serialize_quality_gate(analysis, session, include_details=True)
    payload["run_request"] = run_result
    if request.post_feedback or request.create_commit_status:
        payload["feedback"] = await _publish_quality_gate_feedback(
            project=project,
            analysis=analysis,
            payload=payload,
            post_feedback=request.post_feedback,
            create_commit_status=request.create_commit_status,
        )
    return payload


@router.get("/{project_id}/quality-gates/pr/{analysis_id}")
async def get_pr_quality_gate(
    project_id: str,
    analysis_id: str,
    refresh_feedback: bool = False,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Return the current quality-gate state for a stored PR impact analysis."""
    project = _require_project(project_id, session)
    analysis = session.get(PrImpactAnalysis, analysis_id)
    if not analysis or analysis.project_id != project_id:
        raise HTTPException(status_code=404, detail="PR quality gate not found")
    payload = _serialize_quality_gate(analysis, session, include_details=True)
    if refresh_feedback:
        payload["feedback"] = await _publish_quality_gate_feedback(
            project=project,
            analysis=analysis,
            payload=payload,
            post_feedback=True,
            create_commit_status=True,
        )
    return payload


@router.get("/{project_id}/quality-gates/pr")
def list_pr_quality_gates(
    project_id: str,
    limit: int = 20,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List recent PR quality gates with current gate status."""
    _require_project(project_id, session)
    safe_limit = max(1, min(limit, 100))
    analyses = session.exec(
        select(PrImpactAnalysis)
        .where(PrImpactAnalysis.project_id == project_id)
        .order_by(PrImpactAnalysis.created_at.desc())
        .limit(safe_limit)
    ).all()
    return [_serialize_quality_gate(a, session, include_details=False) for a in analyses]


# -- PR Test Advisor -----------------------------------------------


@router.post("/{project_id}/pr-advisor/analyze")
async def analyze_pull_request_tests(
    project_id: str,
    request: PrAdvisorAnalyzeRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Analyze a GitHub PR and recommend impacted Quorvex tests."""
    from orchestrator.services.pr_test_advisor import serialize_analysis

    try:
        analysis = await _analyze_configured_github_pr(project_id=project_id, request=request, session=session)
        return serialize_analysis(analysis, session, include_details=True)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to analyze PR: {e}")


@router.get("/{project_id}/pr-advisor/analyses")
def list_pr_advisor_analyses(
    project_id: str,
    limit: int = 20,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List recent PR impact analyses for a project."""
    from orchestrator.services.pr_test_advisor import serialize_analysis

    _require_project(project_id, session)
    safe_limit = max(1, min(limit, 100))
    analyses = session.exec(
        select(PrImpactAnalysis)
        .where(PrImpactAnalysis.project_id == project_id)
        .order_by(PrImpactAnalysis.created_at.desc())
        .limit(safe_limit)
    ).all()
    return [serialize_analysis(a, session, include_details=False) for a in analyses]


@router.get("/{project_id}/pr-advisor/analyses/{analysis_id}")
def get_pr_advisor_analysis(
    project_id: str,
    analysis_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Get a stored PR impact analysis with changed files and selected tests."""
    from orchestrator.services.pr_test_advisor import serialize_analysis

    _require_project(project_id, session)
    analysis = session.get(PrImpactAnalysis, analysis_id)
    if not analysis or analysis.project_id != project_id:
        raise HTTPException(status_code=404, detail="PR impact analysis not found")
    return serialize_analysis(analysis, session, include_details=True)


@router.post("/{project_id}/pr-advisor/analyses/{analysis_id}/run")
async def run_pr_advisor_recommendation(
    project_id: str,
    analysis_id: str,
    request: PrAdvisorRunRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Run the tests selected by a PR impact analysis as a regression batch."""
    _require_project(project_id, session)
    analysis = session.get(PrImpactAnalysis, analysis_id)
    if not analysis or analysis.project_id != project_id:
        raise HTTPException(status_code=404, detail="PR impact analysis not found")

    result = _start_recommended_batch(project_id=project_id, analysis=analysis, request=request, session=session)
    if not result.get("batch_created"):
        raise HTTPException(status_code=400, detail=result.get("reason") or "Analysis has no selected tests to run")

    return {
        "batch_id": result["batch_id"],
        "run_ids": result["run_ids"],
        "count": result["count"],
        "analysis_id": analysis_id,
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
