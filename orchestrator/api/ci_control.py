"""Provider-neutral CI/CD control center API.

This router keeps the UI away from provider-specific endpoint differences while
the existing /github and /gitlab APIs remain available for compatibility.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from .credentials import decrypt_credential
from .db import get_session
from .github_ci import (
    _build_client as _build_github_client,
    _get_github_config,
    _require_project,
    _update_mapping_from_run,
)
from .gitlab_ci import _build_client as _build_gitlab_client
from .gitlab_ci import _get_gitlab_config
from .middleware.auth import get_current_user_optional
from .middleware.permissions import EDIT_ROLES, VIEW_ROLES, check_project_access
from .models_auth import User
from .models_db import CiAuditEvent, CiPipelineMapping, CiWorkflowChangeRequest
from ..services.github_client import GithubError

router = APIRouter(prefix="/projects/{project_id}/ci", tags=["ci-control"])

Provider = Literal["github", "gitlab"]


class DispatchWorkflowRequest(BaseModel):
    provider: Provider = "github"
    workflow_id: str | None = None
    ref: str | None = None
    inputs: dict[str, str] | None = None


class RerunRunRequest(BaseModel):
    failed_only: bool = False


class SyncRunsRequest(BaseModel):
    provider: Provider | Literal["all"] = "all"
    workflow_id: str | None = None
    per_page: int = 20


class WorkflowGenerateRequest(BaseModel):
    provider: Provider = "github"
    workflow_name: str = "Quorvex Test Automation"
    template: Literal["pr-quality-gate", "playwright-smoke", "nightly-regression", "release-gate"] = "pr-quality-gate"
    prompt: str | None = None
    ref: str | None = None
    target_url_secret: str = "APP_BASE_URL"
    api_url_secret: str = "QUORVEX_API_URL"
    api_token_secret: str = "QUORVEX_API_TOKEN"
    project_id_variable: str = "QUORVEX_PROJECT_ID"
    branches: list[str] | None = None
    browsers: list[str] | None = None
    artifact_retention_days: int = 14


class WorkflowPullRequestRequest(BaseModel):
    base_ref: str | None = None
    branch_name: str | None = None
    title: str | None = None
    body: str | None = None
    commit_message: str | None = None
    draft: bool = True


def _actor(user: User | None) -> tuple[str | None, str | None]:
    if not user:
        return None, None
    return user.id, user.email


def _audit(
    session: Session,
    *,
    project_id: str,
    provider: str,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    status: str = "ok",
    user: User | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    actor_id, actor_email = _actor(user)
    session.add(
        CiAuditEvent(
            project_id=project_id,
            provider=provider,
            action=action,
            target_type=target_type,
            target_id=target_id,
            status=status,
            actor_id=actor_id,
            actor_email=actor_email,
            event_metadata=metadata,
        )
    )


async def _require_view(project_id: str, user: User | None, session: Session) -> None:
    await check_project_access(project_id, user, VIEW_ROLES, session)


async def _require_edit(project_id: str, user: User | None, session: Session) -> None:
    await check_project_access(project_id, user, EDIT_ROLES, session)


def _serialize_mapping(mapping: CiPipelineMapping, provider: str | None = None) -> dict[str, Any]:
    return {
        "id": mapping.id,
        "provider": provider or mapping.provider,
        "external_pipeline_id": mapping.external_pipeline_id,
        "external_project_id": mapping.external_project_id,
        "external_url": mapping.external_url,
        "ref": mapping.ref,
        "status": mapping.status,
        "triggered_from": mapping.triggered_from,
        "stages": mapping.stages,
        "name": mapping.external_pipeline_id,
        "total_tests": mapping.total_tests,
        "passed_tests": mapping.passed_tests,
        "failed_tests": mapping.failed_tests,
        "test_report_url": mapping.test_report_url,
        "artifacts": mapping.artifacts,
        "action_availability": _action_availability(mapping),
        "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
        "started_at": mapping.started_at.isoformat() if mapping.started_at else None,
        "completed_at": mapping.completed_at.isoformat() if mapping.completed_at else None,
    }


def _github_repo(config: dict[str, Any]) -> tuple[str, str]:
    owner = config.get("owner", "")
    repo = config.get("repo", "")
    if not owner or not repo:
        raise HTTPException(status_code=400, detail="GitHub owner and repo must be configured")
    return owner, repo


def _gitlab_project(config: dict[str, Any]) -> int:
    project_id = config.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="GitLab project ID must be configured")
    return int(project_id)


def _latest_run_after_dispatch(runs: list[dict[str, Any]], workflow_id: str, ref: str) -> dict[str, Any] | None:
    workflow_key = str(workflow_id)
    candidates = []
    for run in runs:
        if run.get("head_branch") != ref:
            continue
        run_workflow_id = str(run.get("workflow_id") or "")
        run_path = str(run.get("path") or "")
        if run_workflow_id == workflow_key or run_path.endswith(workflow_key) or workflow_key in run_path:
            candidates.append(run)
    return candidates[0] if candidates else (runs[0] if runs else None)


def _latest_sync_at(session: Session, project_id: str, provider: str) -> str | None:
    stmt = (
        select(CiPipelineMapping)
        .where(CiPipelineMapping.project_id == project_id, CiPipelineMapping.provider == provider)
        .order_by(CiPipelineMapping.created_at.desc())
        .limit(1)
    )
    mapping = session.exec(stmt).first()
    return mapping.created_at.isoformat() if mapping and mapping.created_at else None


def _action_availability(mapping: CiPipelineMapping) -> dict[str, Any]:
    status = (mapping.status or "").lower()
    has_provider_id = bool(mapping.external_pipeline_id) and not str(mapping.external_pipeline_id).startswith("pending-")
    active = status in {"pending", "running", "queued", "waiting", "in_progress"}
    failed = status in {"failed", "failure"}
    complete = status in {"success", "completed", "failed", "failure", "canceled", "cancelled", "skipped"}
    disabled_reason = None if has_provider_id else "Provider run ID is not available yet. Refresh after the provider creates the run."
    return {
        "can_open_details": True,
        "can_open_provider": bool(mapping.external_url),
        "can_cancel": has_provider_id and active,
        "can_rerun": has_provider_id and complete,
        "can_rerun_failed": has_provider_id and mapping.provider == "github" and failed,
        "can_fetch_logs": has_provider_id,
        "disabled_reason": disabled_reason,
    }


def _upsert_pipeline_mapping(
    session: Session,
    *,
    project_id: str,
    provider: str,
    external_pipeline_id: str,
    defaults: dict[str, Any],
) -> tuple[CiPipelineMapping, bool]:
    stmt = select(CiPipelineMapping).where(
        CiPipelineMapping.project_id == project_id,
        CiPipelineMapping.provider == provider,
        CiPipelineMapping.external_pipeline_id == external_pipeline_id,
    )
    mapping = session.exec(stmt).first()
    created = mapping is None
    if mapping is None:
        mapping = CiPipelineMapping(
            project_id=project_id,
            provider=provider,
            external_pipeline_id=external_pipeline_id,
            **defaults,
        )
    else:
        for key, value in defaults.items():
            if key == "triggered_from":
                continue
            if value is not None:
                setattr(mapping, key, value)
    session.add(mapping)
    return mapping, created


def _apply_gitlab_pipeline(mapping: CiPipelineMapping, pipeline: dict[str, Any]) -> None:
    mapping.status = pipeline.get("status", mapping.status)
    mapping.external_url = pipeline.get("web_url", mapping.external_url)
    mapping.ref = pipeline.get("ref", mapping.ref)
    created_at = pipeline.get("created_at")
    if created_at:
        try:
            mapping.created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass
    updated_at = pipeline.get("updated_at") or pipeline.get("finished_at")
    if mapping.status in {"success", "failed", "canceled", "cancelled", "skipped"} and updated_at:
        try:
            mapping.completed_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass


def _provider_setup(
    *,
    provider: Provider,
    config: dict[str, Any],
    session: Session,
    project_id: str,
) -> dict[str, Any]:
    missing: list[str] = []
    recommended: dict[str, str] | None = None
    configured = bool(config)

    if provider == "github":
        if not configured:
            missing.append("connect_github")
            recommended = {"label": "Connect GitHub", "action": "open_settings", "href": "/settings"}
            status = "not_configured"
        elif not config.get("owner") or not config.get("repo"):
            missing.append("select_repository")
            recommended = {"label": "Select repository", "action": "open_settings", "href": "/settings"}
            status = "needs_repository"
        elif not config.get("default_workflow"):
            missing.append("select_or_generate_workflow")
            recommended = {"label": "Generate workflow draft", "action": "generate_workflow"}
            status = "needs_workflow"
        else:
            status = "ready"
            recommended = {"label": "Run default workflow", "action": "open_trigger"}
        if configured and not config.get("webhook_secret_encrypted"):
            missing.append("configure_webhook")
    else:
        if not configured:
            missing.append("connect_gitlab")
            recommended = {"label": "Connect GitLab", "action": "open_settings", "href": "/settings"}
            status = "not_configured"
        elif not config.get("project_id"):
            missing.append("select_project")
            recommended = {"label": "Select GitLab project", "action": "open_settings", "href": "/settings"}
            status = "needs_project"
        elif not config.get("trigger_token_encrypted"):
            missing.append("add_trigger_token")
            recommended = {"label": "Add trigger token", "action": "open_settings", "href": "/settings"}
            status = "needs_trigger_token"
        else:
            status = "ready"
            recommended = {"label": "Run GitLab pipeline", "action": "open_trigger"}
        if configured and not config.get("webhook_secret"):
            missing.append("configure_webhook")

    return {
        "setup_status": status,
        "missing_requirements": missing,
        "recommended_next_action": recommended,
        "last_sync_at": _latest_sync_at(session, project_id, provider),
    }


@router.get("/providers")
async def list_providers(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_view(project_id, current_user, session)
    project = _require_project(project_id, session)
    github = _get_github_config(project) or {}
    gitlab = _get_gitlab_config(project) or {}
    return [
        {
            "provider": "github",
            "configured": bool(github),
            "repository": f"{github.get('owner', '')}/{github.get('repo', '')}".strip("/"),
            "default_ref": github.get("default_ref", "main"),
            "capabilities": ["workflows", "dispatch", "cancel", "rerun", "logs", "artifacts", "workflow_generation"],
            **_provider_setup(provider="github", config=github, session=session, project_id=project_id),
        },
        {
            "provider": "gitlab",
            "configured": bool(gitlab),
            "repository": str(gitlab.get("project_id") or ""),
            "base_url": gitlab.get("base_url", ""),
            "default_ref": gitlab.get("default_ref", "main"),
            "capabilities": ["dispatch", "cancel", "rerun", "jobs", "job_logs"],
            **_provider_setup(provider="gitlab", config=gitlab, session=session, project_id=project_id),
        },
    ]


@router.get("/workflows")
async def list_workflows(
    project_id: str,
    provider: Provider = "github",
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_view(project_id, current_user, session)
    project = _require_project(project_id, session)
    if provider == "gitlab":
        config = _get_gitlab_config(project)
        if not config:
            return []
        return [
            {
                "id": "pipeline",
                "name": "GitLab Pipeline",
                "path": ".gitlab-ci.yml",
                "state": "active",
                "provider": "gitlab",
            }
        ]

    config = _get_github_config(project)
    if not config:
        return []
    owner, repo = _github_repo(config)
    client = await _build_github_client(project)
    try:
        workflows = await client.list_workflows(owner, repo)
        return [
            {
                "id": str(w.get("id")),
                "name": w.get("name", ""),
                "path": w.get("path", ""),
                "state": w.get("state", ""),
                "provider": "github",
            }
            for w in workflows
        ]
    finally:
        await client.close()


@router.get("/runs")
async def list_runs(
    project_id: str,
    provider: Provider | Literal["all"] = "all",
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_view(project_id, current_user, session)
    _require_project(project_id, session)
    stmt = select(CiPipelineMapping).where(CiPipelineMapping.project_id == project_id)
    if provider != "all":
        stmt = stmt.where(CiPipelineMapping.provider == provider)
    stmt = stmt.order_by(CiPipelineMapping.created_at.desc())
    return [_serialize_mapping(m) for m in session.exec(stmt).all()]


@router.post("/runs/sync")
async def sync_runs(
    project_id: str,
    request: SyncRunsRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    project = _require_project(project_id, session)
    per_page = max(1, min(int(request.per_page or 20), 100))
    summary: dict[str, dict[str, int]] = {}

    if request.provider in {"all", "github"}:
        config = _get_github_config(project)
        if config:
            owner, repo = _github_repo(config)
            client = await _build_github_client(project)
            created = updated = 0
            try:
                runs = await client.get_workflow_runs(owner, repo, workflow_id=request.workflow_id, per_page=per_page)
                for run in runs:
                    run_id = str(run.get("id") or "")
                    if not run_id:
                        continue
                    mapping, is_created = _upsert_pipeline_mapping(
                        session,
                        project_id=project_id,
                        provider="github",
                        external_pipeline_id=run_id,
                        defaults={
                            "external_project_id": f"{owner}/{repo}",
                            "external_url": run.get("html_url", ""),
                            "ref": run.get("head_branch", ""),
                            "triggered_from": "sync",
                        },
                    )
                    _update_mapping_from_run(mapping, run)
                    created += 1 if is_created else 0
                    updated += 0 if is_created else 1
            finally:
                await client.close()
            summary["github"] = {"created": created, "updated": updated}

    if request.provider in {"all", "gitlab"}:
        config = _get_gitlab_config(project)
        if config:
            gitlab_project_id = _gitlab_project(config)
            client = await _build_gitlab_client(project)
            created = updated = 0
            try:
                pipelines = await client.list_pipelines(gitlab_project_id, per_page=per_page)
                for pipeline in pipelines:
                    pipeline_id = str(pipeline.get("id") or "")
                    if not pipeline_id:
                        continue
                    mapping, is_created = _upsert_pipeline_mapping(
                        session,
                        project_id=project_id,
                        provider="gitlab",
                        external_pipeline_id=pipeline_id,
                        defaults={
                            "external_project_id": str(gitlab_project_id),
                            "external_url": pipeline.get("web_url", ""),
                            "ref": pipeline.get("ref", ""),
                            "triggered_from": "sync",
                        },
                    )
                    _apply_gitlab_pipeline(mapping, pipeline)
                    created += 1 if is_created else 0
                    updated += 0 if is_created else 1
            finally:
                await client.close()
            summary["gitlab"] = {"created": created, "updated": updated}

    session.commit()
    _audit(
        session,
        project_id=project_id,
        provider=request.provider,
        action="sync_runs",
        target_type="pipeline",
        user=current_user,
        metadata=summary,
    )
    session.commit()
    return {"status": "ok", "providers": summary}


@router.post("/workflows/dispatch")
async def dispatch_workflow(
    project_id: str,
    request: DispatchWorkflowRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    project = _require_project(project_id, session)

    if request.provider == "gitlab":
        config = _get_gitlab_config(project)
        if not config:
            raise HTTPException(status_code=400, detail="GitLab is not configured")
        gitlab_project_id = _gitlab_project(config)
        ref = request.ref or config.get("default_ref") or "main"
        client = await _build_gitlab_client(project)
        try:
            trigger_token = decrypt_credential(config.get("trigger_token_encrypted", ""))
            pipeline = await client.trigger_pipeline(
                project_id=gitlab_project_id,
                ref=ref,
                variables=request.inputs,
                trigger_token=trigger_token or None,
            )
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
            _audit(
                session,
                project_id=project_id,
                provider="gitlab",
                action="dispatch",
                target_type="pipeline",
                target_id=str(pipeline.get("id")),
                user=current_user,
                metadata={"ref": ref, "variables": sorted((request.inputs or {}).keys())},
            )
            session.commit()
            session.refresh(mapping)
            return {"status": "triggered", "run": _serialize_mapping(mapping)}
        finally:
            await client.close()

    config = _get_github_config(project)
    if not config:
        raise HTTPException(status_code=400, detail="GitHub is not configured")
    owner, repo = _github_repo(config)
    workflow_id = request.workflow_id or config.get("default_workflow")
    ref = request.ref or config.get("default_ref") or "main"
    if not workflow_id:
        raise HTTPException(status_code=400, detail="workflow_id is required")
    client = await _build_github_client(project)
    try:
        await client.trigger_workflow(owner, repo, workflow_id, ref, inputs=request.inputs)
        runs = await client.get_workflow_runs(owner, repo, workflow_id=workflow_id, per_page=5)
        latest = _latest_run_after_dispatch(runs, workflow_id, ref)
        mapping = CiPipelineMapping(
            project_id=project_id,
            provider="github",
            external_pipeline_id=str((latest or {}).get("id") or f"pending-{workflow_id}-{ref}-{datetime.utcnow().timestamp()}"),
            external_project_id=f"{owner}/{repo}",
            external_url=(latest or {}).get("html_url", ""),
            ref=ref,
            triggered_from="dashboard",
            status="pending",
        )
        if latest:
            _update_mapping_from_run(mapping, latest)
        session.add(mapping)
        _audit(
            session,
            project_id=project_id,
            provider="github",
            action="dispatch",
            target_type="workflow",
            target_id=str(workflow_id),
            user=current_user,
            metadata={"ref": ref, "input_keys": sorted((request.inputs or {}).keys())},
        )
        session.commit()
        session.refresh(mapping)
        return {"status": "triggered", "run": _serialize_mapping(mapping)}
    finally:
        await client.close()


@router.get("/runs/{provider}/{mapping_id}")
async def get_run_detail(
    project_id: str,
    provider: Provider,
    mapping_id: int,
    refresh: bool = False,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_view(project_id, current_user, session)
    project = _require_project(project_id, session)
    mapping = session.get(CiPipelineMapping, mapping_id)
    if not mapping or mapping.project_id != project_id or mapping.provider != provider:
        raise HTTPException(status_code=404, detail="CI run not found")

    jobs: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    if refresh and mapping.external_pipeline_id and not mapping.external_pipeline_id.startswith("pending-"):
        if provider == "github":
            config = _get_github_config(project)
            if config:
                owner, repo = _github_repo(config)
                client = await _build_github_client(project)
                try:
                    run = await client.get_run(owner, repo, int(mapping.external_pipeline_id))
                    _update_mapping_from_run(mapping, run)
                    jobs = await client.get_run_jobs(owner, repo, int(mapping.external_pipeline_id))
                    artifacts = await client.list_run_artifacts(owner, repo, int(mapping.external_pipeline_id))
                    mapping.stages = [
                        {
                            "id": str(job.get("id", "")),
                            "name": job.get("name", ""),
                            "status": job.get("conclusion") or job.get("status", ""),
                            "started_at": job.get("started_at"),
                            "completed_at": job.get("completed_at"),
                            "html_url": job.get("html_url"),
                        }
                        for job in jobs
                    ]
                    mapping.artifacts = [
                        {
                            "id": str(item.get("id", "")),
                            "name": item.get("name", ""),
                            "size_in_bytes": item.get("size_in_bytes"),
                            "expired": item.get("expired", False),
                            "archive_download_url": item.get("archive_download_url"),
                        }
                        for item in artifacts
                    ]
                    session.add(mapping)
                    session.commit()
                    session.refresh(mapping)
                finally:
                    await client.close()
        else:
            config = _get_gitlab_config(project)
            if config:
                gitlab_project_id = _gitlab_project(config)
                client = await _build_gitlab_client(project)
                try:
                    pipeline = await client.get_pipeline(gitlab_project_id, int(mapping.external_pipeline_id))
                    mapping.status = pipeline.get("status", mapping.status)
                    mapping.external_url = pipeline.get("web_url", mapping.external_url)
                    jobs = await client.get_pipeline_jobs(gitlab_project_id, int(mapping.external_pipeline_id))
                    mapping.stages = [
                        {
                            "id": str(job.get("id", "")),
                            "name": job.get("name", ""),
                            "stage": job.get("stage", ""),
                            "status": job.get("status", ""),
                            "started_at": job.get("started_at"),
                            "completed_at": job.get("finished_at"),
                            "web_url": job.get("web_url"),
                            "artifacts": job.get("artifacts", []),
                        }
                        for job in jobs
                    ]
                    session.add(mapping)
                    session.commit()
                    session.refresh(mapping)
                finally:
                    await client.close()

    return {"run": _serialize_mapping(mapping), "jobs": jobs or mapping.stages, "artifacts": artifacts or mapping.artifacts}


@router.post("/runs/{provider}/{mapping_id}/cancel")
async def cancel_run(
    project_id: str,
    provider: Provider,
    mapping_id: int,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    project = _require_project(project_id, session)
    mapping = session.get(CiPipelineMapping, mapping_id)
    if not mapping or mapping.project_id != project_id or mapping.provider != provider:
        raise HTTPException(status_code=404, detail="CI run not found")
    if mapping.external_pipeline_id.startswith("pending-"):
        raise HTTPException(status_code=400, detail="Provider run ID is not available yet")

    if provider == "github":
        config = _get_github_config(project)
        owner, repo = _github_repo(config or {})
        client = await _build_github_client(project)
        try:
            await client.cancel_run(owner, repo, int(mapping.external_pipeline_id))
        finally:
            await client.close()
    else:
        config = _get_gitlab_config(project)
        gitlab_project_id = _gitlab_project(config or {})
        client = await _build_gitlab_client(project)
        try:
            await client.cancel_pipeline(gitlab_project_id, int(mapping.external_pipeline_id))
        finally:
            await client.close()

    mapping.status = "canceled"
    session.add(mapping)
    _audit(
        session,
        project_id=project_id,
        provider=provider,
        action="cancel",
        target_type="run",
        target_id=mapping.external_pipeline_id,
        user=current_user,
    )
    session.commit()
    return {"status": "cancelled", "run": _serialize_mapping(mapping)}


@router.post("/runs/{provider}/{mapping_id}/rerun")
async def rerun_run(
    project_id: str,
    provider: Provider,
    mapping_id: int,
    request: RerunRunRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    project = _require_project(project_id, session)
    mapping = session.get(CiPipelineMapping, mapping_id)
    if not mapping or mapping.project_id != project_id or mapping.provider != provider:
        raise HTTPException(status_code=404, detail="CI run not found")
    if mapping.external_pipeline_id.startswith("pending-"):
        raise HTTPException(status_code=400, detail="Provider run ID is not available yet")

    if provider == "github":
        config = _get_github_config(project)
        owner, repo = _github_repo(config or {})
        client = await _build_github_client(project)
        try:
            await client.rerun_run(owner, repo, int(mapping.external_pipeline_id), failed_only=request.failed_only)
        finally:
            await client.close()
    else:
        config = _get_gitlab_config(project)
        gitlab_project_id = _gitlab_project(config or {})
        client = await _build_gitlab_client(project)
        try:
            await client.retry_pipeline(gitlab_project_id, int(mapping.external_pipeline_id))
        finally:
            await client.close()

    _audit(
        session,
        project_id=project_id,
        provider=provider,
        action="rerun_failed" if request.failed_only else "rerun",
        target_type="run",
        target_id=mapping.external_pipeline_id,
        user=current_user,
    )
    session.commit()
    return {"status": "rerun_requested", "run": _serialize_mapping(mapping)}


@router.get("/runs/{provider}/{mapping_id}/logs")
async def get_run_logs(
    project_id: str,
    provider: Provider,
    mapping_id: int,
    job_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_view(project_id, current_user, session)
    project = _require_project(project_id, session)
    mapping = session.get(CiPipelineMapping, mapping_id)
    if not mapping or mapping.project_id != project_id or mapping.provider != provider:
        raise HTTPException(status_code=404, detail="CI run not found")

    if provider == "github":
        if mapping.external_pipeline_id.startswith("pending-"):
            return {"type": "message", "content": "Logs are not available until the provider run ID is known."}
        config = _get_github_config(project)
        owner, repo = _github_repo(config or {})
        client = await _build_github_client(project)
        try:
            logs_url = await client.get_run_logs_url(owner, repo, int(mapping.external_pipeline_id))
            return {"type": "archive_url", "url": logs_url}
        finally:
            await client.close()

    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required for GitLab job logs")
    config = _get_gitlab_config(project)
    gitlab_project_id = _gitlab_project(config or {})
    client = await _build_gitlab_client(project)
    try:
        trace = await client.get_job_trace(gitlab_project_id, int(job_id))
        return {"type": "text", "content": trace[-20000:]}
    finally:
        await client.close()


def _safe_workflow_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return slug or "quorvex-ci"


def _safe_branch_segment(value: str) -> str:
    segment = re.sub(r"[^a-zA-Z0-9._/-]+", "-", value.strip().lower()).strip("-/.")
    segment = re.sub(r"/+", "/", segment)
    return segment or "workflow"


def _workflow_can_open_pr(change: CiWorkflowChangeRequest, github_config: dict[str, Any] | None) -> bool:
    return (
        change.provider == "github"
        and change.status != "opened"
        and not (change.validation_errors or [])
        and bool(github_config and github_config.get("owner") and github_config.get("repo"))
    )


def _serialize_workflow_change(change: CiWorkflowChangeRequest, github_config: dict[str, Any] | None = None) -> dict[str, Any]:
    can_open_pr = _workflow_can_open_pr(change, github_config)
    next_actions = [
        "Review the generated YAML.",
        "Open a draft pull request from Quorvex.",
        "Review and merge the pull request in GitHub.",
        "Set this workflow as the default workflow in Settings after it is merged.",
    ] if can_open_pr else [
        "Review the generated YAML.",
        f"Add it to {change.workflow_path} in your repository.",
        "Add the required Quorvex secrets and variables in GitHub.",
        "Set this workflow as the default workflow in Settings when it is merged.",
    ]
    return {
        "id": change.id,
        "provider": change.provider,
        "workflow_name": change.workflow_name,
        "workflow_path": change.workflow_path,
        "status": change.status,
        "install_status": "opened" if change.status == "opened" else "draft",
        "can_open_pr": can_open_pr,
        "pull_request_url": change.pull_request_url,
        "pull_request_number": change.pull_request_number,
        "branch": change.pull_request_branch,
        "base_ref": change.pull_request_base_ref,
        "commit_sha": change.commit_sha,
        "last_error": change.last_error,
        "next_actions": next_actions,
        "generated_yaml": change.generated_yaml,
        "validation_errors": change.validation_errors or [],
        "validation_warnings": change.validation_warnings or [],
        "created_at": change.created_at.isoformat() if change.created_at else None,
    }


def _workflow_pr_body(change: CiWorkflowChangeRequest) -> str:
    return (
        "This draft PR was generated from Quorvex AI's CI/CD workflow generator.\n\n"
        f"Workflow path: `{change.workflow_path}`\n\n"
        "Before merging, confirm these repository settings exist when the workflow needs them:\n"
        "- `APP_BASE_URL` secret for Playwright-based workflow templates\n"
        "- `QUORVEX_API_URL` secret for PR quality gate workflows\n"
        "- `QUORVEX_API_TOKEN` secret for PR quality gate workflows\n"
        "- `QUORVEX_PROJECT_ID` repository variable when the project is not `default`\n\n"
        "After this PR is merged, select the workflow as the project default in Quorvex Settings."
    )


def _branches(branches: list[str] | None) -> list[str]:
    cleaned = [b.strip() for b in branches or ["main"] if b and b.strip()]
    return cleaned[:8] or ["main"]


def _browsers(browsers: list[str] | None) -> list[str]:
    allowed = {"chromium", "firefox", "webkit"}
    cleaned = [b for b in browsers or ["chromium"] if b in allowed]
    return cleaned or ["chromium"]


def _validate_workflow_request(request: WorkflowGenerateRequest) -> list[str]:
    errors: list[str] = []
    if "\n" in request.workflow_name or "\r" in request.workflow_name:
        errors.append("Workflow name must be a single line.")
    for label, value in {
        "target_url_secret": request.target_url_secret,
        "api_url_secret": request.api_url_secret,
        "api_token_secret": request.api_token_secret,
        "project_id_variable": request.project_id_variable,
    }.items():
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,99}", value or ""):
            errors.append(f"{label} must be an uppercase GitHub secret or variable name.")
    for branch in _branches(request.branches):
        if not re.fullmatch(r"[A-Za-z0-9._/\-]{1,128}", branch):
            errors.append(f"Branch '{branch}' contains unsupported characters.")
    return errors


def _render_github_workflow(request: WorkflowGenerateRequest) -> tuple[str, str]:
    name = request.workflow_name.strip() or "Quorvex Test Automation"
    path = f".github/workflows/{_safe_workflow_slug(name)}.yml"
    branches = ", ".join(_branches(request.branches))
    retention = max(1, min(int(request.artifact_retention_days), 90))
    if request.template == "pr-quality-gate":
        yaml = f"""name: {name}

on:
  pull_request:
    branches: [{branches}]
    types: [opened, synchronize, reopened, ready_for_review]
  workflow_dispatch:

permissions:
  contents: read
  statuses: write
  pull-requests: write

jobs:
  quorvex-quality-gate:
    if: github.event_name != 'pull_request' || github.event.pull_request.draft == false
    runs-on: ubuntu-latest
    steps:
      - name: Start Quorvex PR quality gate
        if: github.event_name == 'pull_request'
        env:
          QUORVEX_API_URL: ${{{{ secrets.{request.api_url_secret} }}}}
          QUORVEX_API_TOKEN: ${{{{ secrets.{request.api_token_secret} }}}}
          QUORVEX_PROJECT_ID: ${{{{ vars.{request.project_id_variable} || 'default' }}}}
        run: |
          curl -fsS -X POST "$QUORVEX_API_URL/github/$QUORVEX_PROJECT_ID/quality-gates/pr/start" \\
            -H "Authorization: Bearer $QUORVEX_API_TOKEN" \\
            -H "Content-Type: application/json" \\
            -d '{{"pr_number": ${{{{ github.event.pull_request.number }}}}, "head_sha": "${{{{ github.event.pull_request.head.sha }}}}", "ensure_indexed": true, "run_recommended": true, "post_feedback": true, "create_commit_status": true}}'
"""
    elif request.template == "nightly-regression":
        yaml = f"""name: {name}

on:
  schedule:
    - cron: '0 2 * * *'
  workflow_dispatch:

permissions:
  contents: read

jobs:
  quorvex-nightly-regression:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
      - run: npm ci
      - run: npx playwright install --with-deps
      - name: Run Quorvex generated tests
        env:
          APP_BASE_URL: ${{{{ secrets.{request.target_url_secret} }}}}
        run: npx playwright test tests/generated
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: playwright-report
          path: playwright-report/
          retention-days: {retention}
"""
    elif request.template == "release-gate":
        yaml = f"""name: {name}

on:
  workflow_dispatch:
    inputs:
      environment:
        description: Target environment
        required: true
        default: staging

permissions:
  contents: read
  deployments: write

jobs:
  quorvex-release-gate:
    runs-on: ubuntu-latest
    environment: ${{{{ inputs.environment }}}}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: npm ci
      - run: npx playwright install --with-deps
      - name: Run release gate suite
        env:
          APP_BASE_URL: ${{{{ secrets.{request.target_url_secret} }}}}
        run: npx playwright test --grep @release
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: release-gate-evidence
          path: |
            playwright-report/
            test-results/
          retention-days: {retention}
"""
    else:
        browsers = ", ".join(_browsers(request.browsers))
        yaml = f"""name: {name}

on:
  pull_request:
    branches: [{branches}]
  workflow_dispatch:

permissions:
  contents: read

jobs:
  quorvex-smoke:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        browser: [{browsers}]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
      - run: npm ci
      - run: npx playwright install --with-deps ${{{{ matrix.browser }}}}
      - name: Run smoke tests
        env:
          APP_BASE_URL: ${{{{ secrets.{request.target_url_secret} }}}}
        run: npx playwright test --project=${{{{ matrix.browser }}}} --grep @smoke
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: smoke-${{{{ matrix.browser }}}}
          path: |
            playwright-report/
            test-results/
          retention-days: {retention}
"""
    return path, yaml


def _validate_workflow_yaml(yaml: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    parsed: Any | None = None
    try:
        parsed = yaml_module_safe_load(yaml)
    except Exception as exc:
        errors.append(f"Generated workflow YAML is invalid: {exc}")
    deny_patterns = {
        "pull_request_target": "pull_request_target can expose secrets to untrusted code.",
        "curl | sh": "Pipe-to-shell install commands are not allowed in generated workflows.",
        "ACTIONS_STEP_DEBUG": "Debug tracing can leak sensitive data.",
    }
    for pattern, message in deny_patterns.items():
        if pattern in yaml:
            errors.append(message)
    if re.search(r"curl\s+.+\|\s*(bash|sh)", yaml):
        errors.append("Pipe-to-shell install commands are not allowed in generated workflows.")
    if "permissions:" not in yaml:
        errors.append("Generated workflow must declare minimal permissions.")
    if "actions/checkout@" in yaml and "actions/checkout@v4" not in yaml:
        warnings.append("Prefer current pinned major version for checkout.")
    if "upload-artifact" in yaml and "retention-days:" not in yaml:
        warnings.append("Artifact uploads should declare retention-days.")
    if "${{ secrets." in yaml and "echo ${{ secrets." in yaml:
        errors.append("Generated workflow must not echo secrets.")
    if parsed is not None:
        if not isinstance(parsed, dict):
            errors.append("Generated workflow must be a YAML mapping.")
        else:
            jobs = parsed.get("jobs")
            if not isinstance(jobs, dict) or not jobs:
                errors.append("Generated workflow must define at least one job.")
            permissions = parsed.get("permissions")
            if not isinstance(permissions, dict):
                errors.append("Generated workflow permissions must be an explicit mapping.")
            elif any(value == "write-all" for value in permissions.values()):
                errors.append("Generated workflow must not request write-all permissions.")
    return errors, warnings


def yaml_module_safe_load(content: str) -> Any:
    return yaml.safe_load(content)


@router.post("/workflow-change-requests")
async def create_workflow_change_request(
    project_id: str,
    request: WorkflowGenerateRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    _require_project(project_id, session)
    if request.provider != "github":
        raise HTTPException(status_code=400, detail="Workflow generation currently supports GitHub Actions only")
    path, yaml = _render_github_workflow(request)
    errors, warnings = _validate_workflow_yaml(yaml)
    errors = _validate_workflow_request(request) + errors
    actor_id, _actor_email = _actor(current_user)
    change = CiWorkflowChangeRequest(
        project_id=project_id,
        provider=request.provider,
        workflow_name=request.workflow_name,
        workflow_path=path,
        ref=request.ref,
        generated_yaml=yaml,
        prompt=request.prompt,
        validation_errors=errors,
        validation_warnings=warnings,
        created_by=actor_id,
    )
    session.add(change)
    _audit(
        session,
        project_id=project_id,
        provider=request.provider,
        action="generate_workflow",
        target_type="workflow_change_request",
        target_id=change.id,
        status="blocked" if errors else "ok",
        user=current_user,
        metadata={"template": request.template, "workflow_path": path},
    )
    session.commit()
    session.refresh(change)
    project = _require_project(project_id, session)
    return _serialize_workflow_change(change, _get_github_config(project))


@router.post("/workflow-change-requests/{change_id}/pull-request")
async def open_workflow_pull_request(
    project_id: str,
    change_id: str,
    request: WorkflowPullRequestRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_edit(project_id, current_user, session)
    project = _require_project(project_id, session)
    change = session.get(CiWorkflowChangeRequest, change_id)
    if not change or change.project_id != project_id:
        raise HTTPException(status_code=404, detail="Workflow change request not found")
    if change.provider != "github":
        raise HTTPException(status_code=400, detail="Workflow PR creation currently supports GitHub Actions only")
    if change.status == "opened":
        return {
            **_serialize_workflow_change(change, _get_github_config(project)),
            "change_request_id": change.id,
        }
    if change.validation_errors:
        raise HTTPException(status_code=400, detail="Fix workflow validation errors before opening a pull request")

    config = _get_github_config(project)
    if not config:
        raise HTTPException(status_code=400, detail="GitHub is not configured")
    owner, repo = _github_repo(config)
    base_ref = (request.base_ref or change.ref or config.get("default_ref") or "main").strip()
    if not base_ref:
        base_ref = "main"
    branch_name = change.pull_request_branch or request.branch_name or f"quorvex/ci-workflow-{_safe_branch_segment(change.workflow_name)}-{change.id[:8]}"
    branch_name = _safe_branch_segment(branch_name)
    title = request.title or f"Add {change.workflow_name}"
    commit_message = request.commit_message or f"Add {change.workflow_name} workflow"
    body = request.body or _workflow_pr_body(change)

    change.status = "proposed"
    change.pull_request_branch = branch_name
    change.pull_request_base_ref = base_ref
    change.last_error = None
    change.updated_at = datetime.utcnow()
    session.add(change)
    session.commit()

    client = await _build_github_client(project)
    try:
        base = await client.get_ref(owner, repo, f"heads/{base_ref}")
        base_sha = ((base.get("object") or {}).get("sha") or "").strip()
        if not base_sha:
            raise HTTPException(status_code=502, detail="GitHub base branch did not return a commit SHA")
        try:
            await client.create_ref(owner, repo, f"heads/{branch_name}", base_sha)
        except GithubError as exc:
            if exc.status_code != 422:
                raise

        existing_prs = await client.list_pull_requests(owner, repo, head=f"{owner}:{branch_name}", base=base_ref)
        if existing_prs:
            pr = existing_prs[0]
            update = {"commit": {"sha": change.commit_sha}}
        else:
            existing = await client.get_content_metadata(owner, repo, change.workflow_path, ref=branch_name)
            update = await client.create_or_update_file(
                owner,
                repo,
                change.workflow_path,
                content=change.generated_yaml,
                message=commit_message,
                branch=branch_name,
                sha=(existing or {}).get("sha"),
            )
            change.commit_sha = ((update.get("commit") or {}).get("sha") if isinstance(update, dict) else None)
            change.updated_at = datetime.utcnow()
            session.add(change)
            session.commit()

            try:
                pr = await client.create_pull_request(
                    owner,
                    repo,
                    title=title,
                    head=branch_name,
                    base=base_ref,
                    body=body,
                    draft=request.draft,
                )
            except GithubError as exc:
                if exc.status_code != 422:
                    raise
                existing_prs = await client.list_pull_requests(owner, repo, head=f"{owner}:{branch_name}", base=base_ref)
                if not existing_prs:
                    raise
                pr = existing_prs[0]
    except GithubError as exc:
        detail = str(exc)
        if exc.status_code == 403:
            detail = "GitHub rejected the request. Check that the token can write repository contents and pull requests."
        elif exc.status_code == 404:
            detail = "GitHub repository, branch, or workflow path was not found."
        elif exc.status_code == 422:
            detail = f"GitHub could not create the workflow pull request: {exc}"
        change.last_error = detail
        change.updated_at = datetime.utcnow()
        session.add(change)
        session.commit()
        raise HTTPException(status_code=502, detail=detail) from exc
    finally:
        await client.close()

    change.status = "opened"
    change.pull_request_url = pr.get("html_url")
    change.pull_request_number = pr.get("number")
    change.pull_request_branch = branch_name
    change.pull_request_base_ref = base_ref
    change.commit_sha = ((update.get("commit") or {}).get("sha") if isinstance(update, dict) else change.commit_sha)
    change.last_error = None
    change.updated_at = datetime.utcnow()
    session.add(change)
    _audit(
        session,
        project_id=project_id,
        provider="github",
        action="open_workflow_pr",
        target_type="workflow_change_request",
        target_id=change.id,
        user=current_user,
        metadata={
            "branch": branch_name,
            "base_ref": base_ref,
            "workflow_path": change.workflow_path,
            "pull_request_number": pr.get("number"),
            "pull_request_url": pr.get("html_url"),
        },
    )
    session.commit()
    session.refresh(change)
    return {
        **_serialize_workflow_change(change, config),
        "change_request_id": change.id,
        "branch": branch_name,
        "workflow_path": change.workflow_path,
        "pull_request_number": pr.get("number"),
        "pull_request_url": pr.get("html_url"),
        "commit_sha": ((update.get("commit") or {}).get("sha") if isinstance(update, dict) else None),
    }


@router.get("/audit-events")
async def list_audit_events(
    project_id: str,
    limit: int = 50,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    await _require_view(project_id, current_user, session)
    limit = max(1, min(limit, 100))
    stmt = (
        select(CiAuditEvent)
        .where(CiAuditEvent.project_id == project_id)
        .order_by(CiAuditEvent.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": event.id,
            "provider": event.provider,
            "action": event.action,
            "target_type": event.target_type,
            "target_id": event.target_id,
            "status": event.status,
            "actor_email": event.actor_email,
            "metadata": event.event_metadata,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
        for event in session.exec(stmt).all()
    ]
