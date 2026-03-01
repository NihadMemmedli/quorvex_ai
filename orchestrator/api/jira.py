"""
Jira Integration API — Config, connection test, bug report generation, issue creation.

Stores Jira credentials in Project.settings["integrations"]["jira"]
with encrypted API token. Generates AI-powered bug reports from test failure
data and creates Jira issues with screenshot attachments.
"""

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session, select

from .credentials import decrypt_credential, encrypt_credential, mask_credential
from .db import get_session
from .middleware.auth import get_current_user_optional
from .models_auth import User
from .models_db import JiraIssueMapping, Project
from .models_db import TestRun as DBTestRun

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jira", tags=["jira"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = BASE_DIR / "runs"

# ── In-Memory Job Tracking ────────────────────────────────────

_bug_report_jobs: dict[str, dict] = {}
MAX_TRACKED_JOBS = 100


def _cleanup_old_jobs():
    """Remove completed/failed jobs older than 1 hour."""
    try:
        now = time.time()
        to_remove = []
        for job_id, job in _bug_report_jobs.items():
            if job["status"] in ("completed", "failed"):
                completed_at = job.get("completed_at", 0)
                if now - completed_at > 3600:
                    to_remove.append(job_id)
        for job_id in to_remove:
            del _bug_report_jobs[job_id]
        if len(_bug_report_jobs) > MAX_TRACKED_JOBS:
            sorted_jobs = sorted(_bug_report_jobs.items(), key=lambda x: x[1].get("started_at", 0))
            for job_id, _ in sorted_jobs[: len(_bug_report_jobs) - MAX_TRACKED_JOBS]:
                del _bug_report_jobs[job_id]
    except Exception as e:
        logger.warning(f"Job cleanup error: {e}")


# ── Request / Response Models ─────────────────────────────────


class JiraConfigRequest(BaseModel):
    base_url: str
    email: str
    api_token: str | None = None  # None means keep existing token
    project_key: str | None = None
    issue_type_id: str | None = None


class CreateIssueRequest(BaseModel):
    run_id: str
    title: str
    description: str
    project_key: str
    issue_type_id: str
    priority_name: str | None = None
    labels: list[str] | None = None
    attach_screenshots: bool = True


# ── Helpers ───────────────────────────────────────────────────


def _get_jira_config(project: Project) -> dict[str, Any] | None:
    """Read the Jira config block from project settings."""
    if not project.settings:
        return None
    return (project.settings.get("integrations") or {}).get("jira")


def _save_jira_config(project: Project, config: dict[str, Any], session: Session):
    """Write the Jira config block into project settings and persist."""
    if not project.settings:
        project.settings = {}
    integrations = project.settings.setdefault("integrations", {})
    integrations["jira"] = config
    flag_modified(project, "settings")
    session.add(project)
    session.commit()


def _require_project(project_id: str, session: Session) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _build_client(project: Project):
    """Build a JiraClient from the project config. Raises 400 if not configured."""
    from services.jira_client import JiraClient

    config = _get_jira_config(project)
    if not config:
        raise HTTPException(status_code=400, detail="Jira not configured for this project")

    api_token = decrypt_credential(config.get("api_token_encrypted", ""))
    if not api_token:
        raise HTTPException(status_code=400, detail="Jira API token could not be decrypted")

    return JiraClient(
        base_url=config["base_url"],
        email=config["email"],
        api_token=api_token,
    )


# ── Config Endpoints ──────────────────────────────────────────


@router.get("/{project_id}/config")
def get_config(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Get Jira config for a project (API token masked)."""
    project = _require_project(project_id, session)
    config = _get_jira_config(project)
    if not config:
        return {"configured": False}

    api_token = decrypt_credential(config.get("api_token_encrypted", ""))
    return {
        "configured": True,
        "base_url": config.get("base_url", ""),
        "email": config.get("email", ""),
        "api_token_masked": mask_credential(api_token),
        "project_key": config.get("project_key"),
        "issue_type_id": config.get("issue_type_id"),
    }


@router.post("/{project_id}/config")
def save_config(
    project_id: str,
    request: JiraConfigRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Save Jira config for a project."""
    project = _require_project(project_id, session)

    if not request.base_url or not request.email:
        raise HTTPException(status_code=400, detail="base_url and email are required")

    existing = _get_jira_config(project)

    if request.api_token:
        api_token_encrypted = encrypt_credential(request.api_token)
    elif existing and existing.get("api_token_encrypted"):
        api_token_encrypted = existing["api_token_encrypted"]
    else:
        raise HTTPException(status_code=400, detail="API token is required for initial setup")

    config = {
        "base_url": request.base_url.rstrip("/"),
        "email": request.email,
        "api_token_encrypted": api_token_encrypted,
        "project_key": request.project_key,
        "issue_type_id": request.issue_type_id,
    }
    _save_jira_config(project, config, session)
    return {"status": "ok"}


@router.delete("/{project_id}/config")
def delete_config(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Remove Jira config from a project."""
    project = _require_project(project_id, session)
    if project.settings and "integrations" in project.settings:
        project.settings["integrations"].pop("jira", None)
        flag_modified(project, "settings")
        session.add(project)
        session.commit()
    return {"status": "ok"}


# ── Connection Test ───────────────────────────────────────────


@router.post("/{project_id}/test-connection")
async def test_connection(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Test the Jira connection using stored credentials."""
    project = _require_project(project_id, session)
    client = await _build_client(project)
    try:
        user_info = await client.test_connection()
        return {
            "status": "ok",
            "user": user_info.get("displayName", user_info.get("name", "Unknown")),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {e}")
    finally:
        await client.close()


# ── Remote Browse ─────────────────────────────────────────────


@router.get("/{project_id}/remote-projects")
async def list_remote_projects(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List Jira projects accessible with stored credentials."""
    project = _require_project(project_id, session)
    client = await _build_client(project)
    try:
        projects = await client.get_projects()
        return [
            {
                "key": p.get("key", ""),
                "name": p.get("name", ""),
                "id": p.get("id", ""),
            }
            for p in projects
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        await client.close()


@router.get("/{project_id}/remote-issue-types/{jira_project_key}")
async def list_remote_issue_types(
    project_id: str,
    jira_project_key: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List issue types for a Jira project."""
    project = _require_project(project_id, session)
    client = await _build_client(project)
    try:
        issue_types = await client.get_issue_types(jira_project_key)
        return [
            {
                "id": it.get("id", ""),
                "name": it.get("name", ""),
                "subtask": it.get("subtask", False),
            }
            for it in issue_types
            if not it.get("subtask", False)  # Exclude subtask types
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        await client.close()


# ── Bug Report Generation ────────────────────────────────────


async def _run_bug_report_generation(job_id: str, run_id: str, project_id: str):
    """Background task: generate AI bug report from failure data."""
    _bug_report_jobs[job_id]["status"] = "running"
    _bug_report_jobs[job_id]["started_at"] = time.time()

    try:
        from workflows.bug_report_generator import generate_bug_report

        # Load failure data from filesystem
        run_dir = RUNS_DIR / run_id
        spec_name = ""
        target_url = ""
        error_message = ""
        validation_data = None
        run_data = None
        execution_log = ""
        generated_code = ""

        # Read run.json
        run_json_path = run_dir / "run.json"
        if run_json_path.exists():
            try:
                run_data = json.loads(run_json_path.read_text())
                spec_name = run_data.get("spec_name", "")
                target_url = run_data.get("target_url", "")
                error_message = run_data.get("error_message", "")
            except Exception:
                pass

        # Read validation.json
        validation_path = run_dir / "validation.json"
        if validation_path.exists():
            try:
                validation_data = json.loads(validation_path.read_text())
                if not error_message and validation_data.get("error"):
                    error_message = validation_data["error"]
            except Exception:
                pass

        # Read execution log (last 3000 chars)
        log_path = run_dir / "execution.log"
        if log_path.exists():
            try:
                log_content = log_path.read_text()
                execution_log = log_content[-3000:] if len(log_content) > 3000 else log_content
            except Exception:
                pass

        # Read generated code
        for code_file in run_dir.glob("*.spec.ts"):
            try:
                generated_code = code_file.read_text()
                break
            except Exception:
                pass

        # Also try from DB if filesystem data is sparse
        if not spec_name or not target_url:
            try:
                from sqlmodel import Session as _Session

                # Use a fresh session for background task
                from .db import engine

                with _Session(engine) as bg_session:
                    db_run = bg_session.get(DBTestRun, run_id)
                    if db_run:
                        spec_name = spec_name or db_run.spec_name or ""
                        error_message = error_message or db_run.error_message or ""
                        target_url = target_url or db_run.target_url or ""
            except Exception:
                pass

        if not spec_name:
            spec_name = run_id

        result = await generate_bug_report(
            spec_name=spec_name,
            target_url=target_url or "Unknown",
            error_message=error_message,
            validation_data=validation_data,
            run_data=run_data,
            execution_log=execution_log,
            generated_code=generated_code,
        )

        _bug_report_jobs[job_id]["status"] = "completed"
        _bug_report_jobs[job_id]["completed_at"] = time.time()
        _bug_report_jobs[job_id]["result"] = result

    except Exception as e:
        logger.error(f"Bug report generation failed for run {run_id}: {e}")
        _bug_report_jobs[job_id]["status"] = "failed"
        _bug_report_jobs[job_id]["error"] = str(e)
        _bug_report_jobs[job_id]["completed_at"] = time.time()


@router.post("/{project_id}/generate-bug-report/{run_id}")
async def generate_bug_report_endpoint(
    project_id: str,
    run_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Start AI bug report generation for a failed run."""
    _require_project(project_id, session)

    _cleanup_old_jobs()

    job_id = f"bug-{uuid.uuid4().hex[:8]}"
    _bug_report_jobs[job_id] = {
        "status": "queued",
        "run_id": run_id,
        "project_id": project_id,
        "created_at": time.time(),
    }

    asyncio.create_task(_run_bug_report_generation(job_id, run_id, project_id))

    return {"job_id": job_id, "status": "queued"}


@router.get("/{project_id}/bug-report-jobs/{job_id}")
async def get_bug_report_job(
    project_id: str,
    job_id: str,
    current_user: User | None = Depends(get_current_user_optional),
):
    """Poll bug report generation job status."""
    job = _bug_report_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    response: dict[str, Any] = {"job_id": job_id, "status": job["status"]}
    if job["status"] == "completed":
        response["result"] = job.get("result")
    elif job["status"] == "failed":
        response["error"] = job.get("error", "Unknown error")

    return response


# ── Issue Creation ────────────────────────────────────────────


@router.post("/{project_id}/create-issue")
async def create_issue(
    project_id: str,
    request: CreateIssueRequest,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Create a Jira issue from a bug report and optionally attach screenshots."""
    project = _require_project(project_id, session)
    client = await _build_client(project)

    try:
        # Build issue fields
        fields: dict[str, Any] = {
            "project": {"key": request.project_key},
            "issuetype": {"id": request.issue_type_id},
            "summary": request.title,
            "description": request.description,
        }

        if request.priority_name:
            fields["priority"] = {"name": request.priority_name}

        if request.labels:
            fields["labels"] = request.labels

        # Create the issue
        result = await client.create_issue(fields)
        issue_key = result.get("key", "")
        issue_id = str(result.get("id", ""))

        # Build issue URL
        config = _get_jira_config(project)
        base_url = (config or {}).get("base_url", "")
        issue_url = f"{base_url}/browse/{issue_key}" if base_url else ""

        # Attach screenshots if requested
        attachments_added = 0
        if request.attach_screenshots:
            run_dir = RUNS_DIR / request.run_id
            if run_dir.exists():
                for img_path in sorted(run_dir.glob("*.png")):
                    try:
                        img_data = img_path.read_bytes()
                        await client.add_attachment(issue_key, img_path.name, img_data)
                        attachments_added += 1
                    except Exception as e:
                        logger.warning(f"Failed to attach {img_path.name}: {e}")

        # Save mapping to database
        mapping = JiraIssueMapping(
            project_id=project_id,
            run_id=request.run_id,
            jira_issue_key=issue_key,
            jira_issue_id=issue_id,
            jira_project_key=request.project_key,
            issue_type="Bug",
            summary=request.title,
            status="open",
            jira_url=issue_url,
            bug_report_json=json.dumps({"title": request.title, "description": request.description}),
        )
        session.add(mapping)
        session.commit()

        return {
            "issue_key": issue_key,
            "issue_id": issue_id,
            "issue_url": issue_url,
            "attachments_added": attachments_added,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create issue: {e}")
    finally:
        await client.close()


# ── Issue Queries ─────────────────────────────────────────────


@router.get("/{project_id}/issues")
def list_issues(
    project_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """List all Jira issues created for this project."""
    _require_project(project_id, session)
    stmt = (
        select(JiraIssueMapping)
        .where(JiraIssueMapping.project_id == project_id)
        .order_by(JiraIssueMapping.created_at.desc())
    )
    mappings = session.exec(stmt).all()
    return [
        {
            "id": m.id,
            "run_id": m.run_id,
            "jira_issue_key": m.jira_issue_key,
            "jira_project_key": m.jira_project_key,
            "summary": m.summary,
            "status": m.status,
            "jira_url": m.jira_url,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in mappings
    ]


@router.get("/{project_id}/issues/{run_id}")
def get_issue_for_run(
    project_id: str,
    run_id: str,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Check if a Jira issue exists for a specific run."""
    stmt = select(JiraIssueMapping).where(
        JiraIssueMapping.project_id == project_id,
        JiraIssueMapping.run_id == run_id,
    )
    mapping = session.exec(stmt).first()
    if not mapping:
        return {"exists": False}

    return {
        "exists": True,
        "jira_issue_key": mapping.jira_issue_key,
        "jira_url": mapping.jira_url,
        "summary": mapping.summary,
        "status": mapping.status,
        "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
    }
