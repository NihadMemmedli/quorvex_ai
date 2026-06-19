"""
Security Testing Router

Provides endpoints for managing security scan specs, running quick/nuclei/zap scans,
tracking background jobs, querying run history, and managing findings.
"""

import asyncio
import json
import logging
import os
import shutil
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlmodel import Session, select

from orchestrator.services.browser_pool import OperationType
from orchestrator.services.browser_slots import browser_operation_slot

from .db import engine
from .models_db import DiscoveredApiEndpoint, ExplorationSession, SecurityFinding, SecurityScanRun

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = BASE_DIR / "specs"

router = APIRouter(prefix="/security-testing", tags=["security-testing"])

# ========== In-Memory Job Tracking ==========
_security_jobs: dict[str, dict] = {}
_security_tasks: dict[str, asyncio.Task] = {}
MAX_TRACKED_JOBS = 200


def _cleanup_old_jobs():
    """Remove completed/failed jobs older than 1 hour."""
    try:
        now = time.time()
        to_remove = []
        for job_id, job in _security_jobs.items():
            if job["status"] in ("completed", "failed", "cancelled"):
                completed_at = job.get("completed_at", 0)
                if now - completed_at > 3600:
                    to_remove.append(job_id)
        for job_id in to_remove:
            del _security_jobs[job_id]
        # Enforce hard cap
        if len(_security_jobs) > MAX_TRACKED_JOBS:
            sorted_jobs = sorted(_security_jobs.items(), key=lambda x: x[1].get("started_at", 0))
            for job_id, _ in sorted_jobs[: len(_security_jobs) - MAX_TRACKED_JOBS]:
                del _security_jobs[job_id]
    except Exception as e:
        logger.warning(f"Job cleanup error: {e}")


# ========== Pydantic Models ==========


class CreateSecuritySpecRequest(BaseModel):
    name: str
    content: str
    project_id: str


class UpdateSecuritySpecRequest(BaseModel):
    content: str


class SecurityAuthConfig(BaseModel):
    enabled: bool = False
    auth_type: str = "login"
    login_url: str | None = None
    username_key: str | None = None
    password_key: str | None = None
    username_selector: str | None = None
    password_selector: str | None = None
    submit_selector: str | None = None


class BaseScanRequest(BaseModel):
    target_url: str
    project_id: str
    auth_config: SecurityAuthConfig | None = None
    login_url: str | None = None
    username_key: str | None = None
    password_key: str | None = None
    scope: str | None = "origin"
    excluded_paths: list[str] = Field(default_factory=list)
    active_scan_level: str = "safe"  # passive, safe, full


class QuickScanRequest(BaseScanRequest):
    pass


class NucleiScanRequest(BaseScanRequest):
    severity_filter: str | None = None  # "critical,high"
    templates: list[str] | None = None


class ZapScanRequest(BaseScanRequest):
    scan_policy: str | None = None


class FullScanRequest(BaseScanRequest):
    severity_filter: str | None = None
    templates: list[str] | None = None


class UpdateFindingStatusRequest(BaseModel):
    status: str  # open, false_positive, fixed, accepted_risk
    notes: str | None = None


class AnalyzeRequest(BaseModel):
    project_id: str


class GenerateSpecRequest(BaseModel):
    session_id: str
    project_id: str


# ========== Helper Functions ==========


def _get_specs_dir(project_id: str = "default") -> Path:
    """Get security specs directory, optionally scoped by project."""
    if project_id and project_id != "default":
        d = SPECS_DIR / project_id / "security"
    else:
        d = SPECS_DIR / "security"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _scan_security_specs(project_id: str = "default") -> list[dict]:
    """Scan for security test spec markdown files, scoped to a single project."""
    specs = []
    d = _get_specs_dir(project_id)

    if not d.exists():
        return specs

    for md_file in sorted(d.rglob("*.md")):
        try:
            specs.append(
                {
                    "name": md_file.name,
                    "path": str(md_file.relative_to(BASE_DIR)),
                    "modified_at": datetime.fromtimestamp(md_file.stat().st_mtime).isoformat(),
                }
            )
        except Exception as e:
            logger.warning(f"Error scanning security spec {md_file}: {e}")

    return specs


def _project_scope(model, project_id: str):
    if project_id == "default":
        return (model.project_id == "default") | (model.project_id == None)
    return model.project_id == project_id


def _get_scan_run_for_project(session: Session, run_id: str, project_id: str) -> SecurityScanRun | None:
    return session.exec(
        select(SecurityScanRun).where(SecurityScanRun.id == run_id, _project_scope(SecurityScanRun, project_id))
    ).first()


def _get_finding_for_project(session: Session, finding_id: int, project_id: str) -> SecurityFinding | None:
    return session.exec(
        select(SecurityFinding).where(SecurityFinding.id == finding_id, _project_scope(SecurityFinding, project_id))
    ).first()


def _get_exploration_session_for_project(
    session: Session, session_id: str, project_id: str
) -> ExplorationSession | None:
    return session.exec(
        select(ExplorationSession).where(
            ExplorationSession.id == session_id,
            _project_scope(ExplorationSession, project_id),
        )
    ).first()


def _get_spec_path_for_project(name: str, project_id: str) -> Path | None:
    specs_dir = _get_specs_dir(project_id)
    if specs_dir.exists():
        for md_file in specs_dir.rglob("*.md"):
            if md_file.name == name:
                return md_file
    return None


def _generate_run_id() -> str:
    return f"sec-{uuid.uuid4().hex[:8]}"


def _valid_active_scan_level(level: str | None) -> str:
    level = (level or "safe").lower()
    if level not in {"passive", "safe", "full"}:
        raise HTTPException(status_code=400, detail="active_scan_level must be one of: passive, safe, full")
    return level


def _normalize_auth_config(req: BaseScanRequest) -> SecurityAuthConfig | None:
    auth = req.auth_config
    if not auth and (req.login_url or req.username_key or req.password_key):
        auth = SecurityAuthConfig(
            enabled=True,
            login_url=req.login_url,
            username_key=req.username_key,
            password_key=req.password_key,
        )
    if auth and auth.enabled:
        if auth.auth_type != "login":
            raise HTTPException(status_code=400, detail="Only login auth is supported for security scans")
        if not auth.login_url or not auth.username_key or not auth.password_key:
            raise HTTPException(
                status_code=400,
                detail="Authenticated scans require login_url, username_key, and password_key",
            )
        return auth
    return None


def _cookie_header_from_playwright(cookies: list[dict]) -> str:
    pairs = []
    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if name and value is not None:
            pairs.append(f"{name}={value}")
    return "; ".join(pairs)


async def _build_auth_headers(req: BaseScanRequest, project_id: str, proxy_url: str | None = None) -> dict[str, str]:
    """Log in with stored project credentials and return headers usable by HTTP scanners."""
    auth = _normalize_auth_config(req)
    if not auth:
        return {}

    with Session(engine) as session:
        from .credentials import get_merged_credentials

        credentials = get_merged_credentials(project_id, session)

    username = credentials.get(auth.username_key or "")
    password = credentials.get(auth.password_key or "")
    if not username or not password:
        raise RuntimeError("Configured credential keys were not found or could not be decrypted")

    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        raise RuntimeError(f"Playwright is required for authenticated security scans: {e}")

    username_selectors = [
        auth.username_selector,
        'input[name="username"]',
        'input[name="email"]',
        'input[type="email"]',
        'input[autocomplete="username"]',
        'input[id*="user" i]',
        'input[id*="email" i]',
    ]
    password_selectors = [
        auth.password_selector,
        'input[name="password"]',
        'input[type="password"]',
        'input[autocomplete="current-password"]',
    ]
    submit_selectors = [
        auth.submit_selector,
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Sign in")',
        'button:has-text("Log in")',
        'button:has-text("Login")',
    ]

    slot_request_id = f"security-auth:{project_id}:{uuid.uuid4().hex[:8]}"
    async with browser_operation_slot(
        request_id=slot_request_id,
        operation_type=OperationType.SECURITY,
        description=f"Security auth preflight for {req.target_url}",
        max_operation_duration=180,
    ):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context_kwargs = {"ignore_https_errors": True}
                if proxy_url:
                    context_kwargs["proxy"] = {"server": proxy_url}
                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()
                await page.goto(auth.login_url or req.target_url, wait_until="domcontentloaded", timeout=30_000)

                async def fill_first(selectors: list[str | None], value: str, label: str) -> None:
                    for selector in selectors:
                        if not selector:
                            continue
                        locator = page.locator(selector).first
                        try:
                            if await locator.count():
                                await locator.fill(value, timeout=5_000)
                                return
                        except Exception:
                            continue
                    raise RuntimeError(f"Could not find {label} field during login preflight")

                await fill_first(username_selectors, username, "username")
                await fill_first(password_selectors, password, "password")

                clicked = False
                for selector in submit_selectors:
                    if not selector:
                        continue
                    locator = page.locator(selector).first
                    try:
                        if await locator.count():
                            await locator.click(timeout=5_000)
                            clicked = True
                            break
                    except Exception:
                        continue
                if not clicked:
                    await page.keyboard.press("Enter")

                await page.wait_for_load_state("networkidle", timeout=20_000)
                await page.goto(req.target_url, wait_until="networkidle", timeout=30_000)
                cookies = await context.cookies()
                cookie_header = _cookie_header_from_playwright(cookies)
                return {"Cookie": cookie_header} if cookie_header else {}
            finally:
                await browser.close()


def _run_to_dict(run: SecurityScanRun) -> dict:
    return {
        "id": run.id,
        "spec_name": run.spec_name,
        "target_url": run.target_url,
        "scan_type": run.scan_type,
        "status": run.status,
        "project_id": run.project_id,
        "total_findings": run.total_findings,
        "critical_count": run.critical_count,
        "high_count": run.high_count,
        "medium_count": run.medium_count,
        "low_count": run.low_count,
        "info_count": run.info_count,
        "quick_scan_completed": run.quick_scan_completed,
        "nuclei_scan_completed": run.nuclei_scan_completed,
        "zap_scan_completed": run.zap_scan_completed,
        "current_stage": run.current_stage,
        "stage_message": run.stage_message,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "duration_seconds": run.duration_seconds,
    }


def _finding_to_dict(f: SecurityFinding) -> dict:
    return {
        "id": f.id,
        "scan_id": f.scan_id,
        "severity": f.severity,
        "finding_type": f.finding_type,
        "category": f.category,
        "scanner": f.scanner,
        "title": f.title,
        "description": f.description,
        "url": f.url,
        "evidence": f.evidence,
        "remediation": f.remediation,
        "reference_urls": f.reference_urls,
        "reference_urls_json": f.reference_urls_json,
        "template_id": f.template_id,
        "zap_alert_ref": f.zap_alert_ref,
        "zap_cweid": f.zap_cweid,
        "finding_hash": f.finding_hash,
        "status": f.status,
        "notes": f.notes,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    }


def _filter_excluded_findings(findings: list[dict], excluded_paths: list[str]) -> list[dict]:
    normalized = [p if p.startswith("/") else f"/{p}" for p in excluded_paths if p.strip()]
    if not normalized:
        return findings
    filtered = []
    for finding in findings:
        path = urlparse(finding.get("url") or "").path or "/"
        if any(path.startswith(excluded) for excluded in normalized):
            continue
        filtered.append(finding)
    return filtered


def _track_task(job_id: str, task: asyncio.Task) -> None:
    _security_tasks[job_id] = task

    def _discard(_task: asyncio.Task) -> None:
        _security_tasks.pop(job_id, None)

    task.add_done_callback(_discard)


async def _get_capabilities() -> dict:
    nuclei_path = shutil.which("nuclei")
    zap_available = False
    zap_version = None
    zap_error = None
    try:
        from services.security.zap_client import get_zap_version

        zap_version = await get_zap_version()
        zap_available = bool(zap_version)
    except Exception as e:
        zap_error = str(e)

    return {
        "quick": {
            "available": True,
            "message": "Built-in checks are available",
        },
        "nuclei": {
            "available": bool(nuclei_path),
            "path": nuclei_path,
            "message": "Nuclei binary found" if nuclei_path else "Nuclei binary not found in PATH",
        },
        "zap": {
            "available": zap_available,
            "version": zap_version,
            "host": os.environ.get("ZAP_HOST", "localhost"),
            "port": int(os.environ.get("ZAP_PORT", "8090")),
            "message": f"ZAP {zap_version} reachable" if zap_available else "ZAP daemon is not reachable",
            "error": zap_error,
        },
        "defaults": {
            "active_scan_level": "safe",
            "security_scan_timeout": int(os.environ.get("SECURITY_SCAN_TIMEOUT", "1800")),
            "nuclei_timeout": int(os.environ.get("NUCLEI_TIMEOUT_SECONDS", "600")),
        },
    }


# ========== Background Job Runners ==========


async def _run_quick_scan_job(job_id: str, run_id: str, req: QuickScanRequest, project_id: str):
    """Background task for quick security scan."""
    _security_jobs[job_id]["status"] = "running"
    _security_jobs[job_id]["started_at"] = time.time()

    try:
        # Update DB status
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.status = "running"
                run.started_at = datetime.utcnow()
                run.current_stage = "quick_scan"
                run.stage_message = "Running security header checks..."
                session.add(run)
                session.commit()

        auth_headers = await _build_auth_headers(req, project_id)

        # Import and run scanner
        from services.security.quick_scanner import run_quick_scan

        findings = _filter_excluded_findings(
            await run_quick_scan(req.target_url, headers=auth_headers or None),
            req.excluded_paths,
        )

        # Save findings to DB
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}

            for f in findings:
                finding = SecurityFinding(
                    scan_id=run_id,
                    project_id=project_id,
                    severity=f["severity"],
                    finding_type=f["finding_type"],
                    category=f["category"],
                    scanner="quick",
                    title=f["title"],
                    description=f["description"],
                    url=f["url"],
                    evidence=f.get("evidence"),
                    remediation=f.get("remediation"),
                    reference_urls_json=json.dumps(f.get("reference_urls", [])),
                    finding_hash=f["finding_hash"],
                )
                session.add(finding)
                severity_counts[f["severity"]] = severity_counts.get(f["severity"], 0) + 1

            if run:
                run.status = "completed"
                run.completed_at = datetime.utcnow()
                run.quick_scan_completed = True
                run.total_findings = len(findings)
                run.critical_count = severity_counts["critical"]
                run.high_count = severity_counts["high"]
                run.medium_count = severity_counts["medium"]
                run.low_count = severity_counts["low"]
                run.info_count = severity_counts["info"]
                run.current_stage = "done"
                run.stage_message = f"Found {len(findings)} issues"
                session.add(run)
            session.commit()

        _security_jobs[job_id]["status"] = "completed"
        _security_jobs[job_id]["completed_at"] = time.time()
        _security_jobs[job_id]["result"] = {"total_findings": len(findings)}

    except asyncio.CancelledError:
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.status = "cancelled"
                run.completed_at = datetime.utcnow()
                run.current_stage = "cancelled"
                run.stage_message = "Cancelled by user"
                session.add(run)
                session.commit()
        _security_jobs[job_id]["status"] = "cancelled"
        _security_jobs[job_id]["completed_at"] = time.time()
        raise
    except Exception as e:
        logger.error(f"Quick scan failed: {e}")
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.status = "failed"
                run.error_message = str(e)
                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()
        _security_jobs[job_id]["status"] = "failed"
        _security_jobs[job_id]["error"] = str(e)
        _security_jobs[job_id]["completed_at"] = time.time()


async def _run_nuclei_scan_job(
    job_id: str, run_id: str, req: NucleiScanRequest, project_id: str
):
    """Background task for Nuclei scan."""
    _security_jobs[job_id]["status"] = "running"
    _security_jobs[job_id]["started_at"] = time.time()

    try:
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.status = "running"
                run.started_at = datetime.utcnow()
                run.current_stage = "nuclei_scan"
                run.stage_message = "Running Nuclei vulnerability scan..."
                session.add(run)
                session.commit()

        auth_headers = await _build_auth_headers(req, project_id)

        from services.security.nuclei_runner import run_nuclei_scan

        findings = _filter_excluded_findings(
            await run_nuclei_scan(
                req.target_url,
                severity_filter=req.severity_filter,
                templates=req.templates,
                headers=auth_headers or None,
            ),
            req.excluded_paths,
        )

        # Save findings to DB
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}

            for f in findings:
                finding = SecurityFinding(
                    scan_id=run_id,
                    project_id=project_id,
                    severity=f["severity"],
                    finding_type=f["finding_type"],
                    category=f["category"],
                    scanner="nuclei",
                    title=f["title"],
                    description=f["description"],
                    url=f["url"],
                    evidence=f.get("evidence"),
                    remediation=f.get("remediation"),
                    reference_urls_json=json.dumps(f.get("reference_urls", [])),
                    finding_hash=f["finding_hash"],
                    template_id=f.get("template_id"),
                )
                session.add(finding)
                severity_counts[f["severity"]] = severity_counts.get(f["severity"], 0) + 1

            if run:
                run.status = "completed"
                run.completed_at = datetime.utcnow()
                run.nuclei_scan_completed = True
                run.total_findings = len(findings)
                run.critical_count = severity_counts["critical"]
                run.high_count = severity_counts["high"]
                run.medium_count = severity_counts["medium"]
                run.low_count = severity_counts["low"]
                run.info_count = severity_counts["info"]
                run.current_stage = "done"
                run.stage_message = f"Found {len(findings)} issues"
                session.add(run)
            session.commit()

        _security_jobs[job_id]["status"] = "completed"
        _security_jobs[job_id]["completed_at"] = time.time()
        _security_jobs[job_id]["result"] = {"total_findings": len(findings)}

    except asyncio.CancelledError:
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.status = "cancelled"
                run.completed_at = datetime.utcnow()
                run.current_stage = "cancelled"
                run.stage_message = "Cancelled by user"
                session.add(run)
                session.commit()
        _security_jobs[job_id]["status"] = "cancelled"
        _security_jobs[job_id]["completed_at"] = time.time()
        raise
    except Exception as e:
        logger.error(f"Nuclei scan failed: {e}")
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.status = "failed"
                run.error_message = str(e)
                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()
        _security_jobs[job_id]["status"] = "failed"
        _security_jobs[job_id]["error"] = str(e)
        _security_jobs[job_id]["completed_at"] = time.time()


async def _run_zap_scan_job(job_id: str, run_id: str, req: ZapScanRequest, project_id: str):
    """Background task for ZAP DAST scan."""
    _security_jobs[job_id]["status"] = "running"
    _security_jobs[job_id]["started_at"] = time.time()

    try:
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.status = "running"
                run.started_at = datetime.utcnow()
                run.current_stage = "zap_spider"
                run.stage_message = "ZAP spidering target..."
                session.add(run)
                session.commit()

        active_scan_level = _valid_active_scan_level(req.active_scan_level)
        proxy_url = f"http://{os.environ.get('ZAP_HOST', 'localhost')}:{int(os.environ.get('ZAP_PORT', '8090'))}"
        auth_headers = await _build_auth_headers(req, project_id, proxy_url=proxy_url)

        from services.security.zap_client import run_zap_scan

        findings = _filter_excluded_findings(
            await run_zap_scan(
                req.target_url,
                scan_policy=req.scan_policy,
                active_scan_enabled=active_scan_level == "full",
                active_scan_level=active_scan_level,
                auth_context={"headers": auth_headers} if auth_headers else None,
            ),
            req.excluded_paths,
        )

        # Save findings to DB
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}

            for f in findings:
                finding = SecurityFinding(
                    scan_id=run_id,
                    project_id=project_id,
                    severity=f["severity"],
                    finding_type=f["finding_type"],
                    category=f["category"],
                    scanner="zap",
                    title=f["title"],
                    description=f["description"],
                    url=f["url"],
                    evidence=f.get("evidence"),
                    remediation=f.get("remediation"),
                    reference_urls_json=json.dumps(f.get("reference_urls", [])),
                    finding_hash=f["finding_hash"],
                    zap_alert_ref=f.get("zap_alert_ref"),
                    zap_cweid=f.get("zap_cweid"),
                )
                session.add(finding)
                severity_counts[f["severity"]] = severity_counts.get(f["severity"], 0) + 1

            if run:
                run.status = "completed"
                run.completed_at = datetime.utcnow()
                run.zap_scan_completed = True
                run.total_findings = len(findings)
                run.critical_count = severity_counts["critical"]
                run.high_count = severity_counts["high"]
                run.medium_count = severity_counts["medium"]
                run.low_count = severity_counts["low"]
                run.info_count = severity_counts["info"]
                run.current_stage = "done"
                run.stage_message = f"Found {len(findings)} issues"
                session.add(run)
            session.commit()

        _security_jobs[job_id]["status"] = "completed"
        _security_jobs[job_id]["completed_at"] = time.time()
        _security_jobs[job_id]["result"] = {"total_findings": len(findings)}

    except asyncio.CancelledError:
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.status = "cancelled"
                run.completed_at = datetime.utcnow()
                run.current_stage = "cancelled"
                run.stage_message = "Cancelled by user"
                session.add(run)
                session.commit()
        _security_jobs[job_id]["status"] = "cancelled"
        _security_jobs[job_id]["completed_at"] = time.time()
        raise
    except Exception as e:
        logger.error(f"ZAP scan failed: {e}")
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.status = "failed"
                run.error_message = str(e)
                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()
        _security_jobs[job_id]["status"] = "failed"
        _security_jobs[job_id]["error"] = str(e)
        _security_jobs[job_id]["completed_at"] = time.time()


async def _run_full_scan_job(job_id: str, run_id: str, req: FullScanRequest, project_id: str):
    """Background task for full scan (quick -> nuclei -> zap sequentially)."""
    _security_jobs[job_id]["status"] = "running"
    _security_jobs[job_id]["started_at"] = time.time()

    quick_findings = []
    nuclei_findings = []
    zap_findings = []
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}

    try:
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.status = "running"
                run.started_at = datetime.utcnow()
                session.add(run)
                session.commit()

        # Phase 1: Quick scan
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.current_stage = "quick_scan"
                run.stage_message = "Running security header checks..."
                session.add(run)
                session.commit()

        try:
            auth_headers = await _build_auth_headers(req, project_id)

            from services.security.quick_scanner import run_quick_scan

            quick_findings = _filter_excluded_findings(
                await run_quick_scan(req.target_url, headers=auth_headers or None),
                req.excluded_paths,
            )
            for finding in quick_findings:
                finding["scanner"] = "quick"

            with Session(engine) as session:
                run = _get_scan_run_for_project(session, run_id, project_id)
                if run:
                    run.quick_scan_completed = True
                    session.add(run)
                session.commit()
        except Exception as e:
            logger.warning(f"Quick scan phase failed for full scan {run_id}: {e}")

        # Phase 2: Nuclei scan
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.current_stage = "nuclei_scan"
                run.stage_message = "Running Nuclei vulnerability scan..."
                session.add(run)
                session.commit()

        try:
            auth_headers = await _build_auth_headers(req, project_id)

            from services.security.nuclei_runner import run_nuclei_scan

            nuclei_findings = _filter_excluded_findings(
                await run_nuclei_scan(
                    req.target_url,
                    severity_filter=req.severity_filter,
                    templates=req.templates,
                    headers=auth_headers or None,
                ),
                req.excluded_paths,
            )
            for finding in nuclei_findings:
                finding["scanner"] = "nuclei"

            with Session(engine) as session:
                run = _get_scan_run_for_project(session, run_id, project_id)
                if run:
                    run.nuclei_scan_completed = True
                    session.add(run)
                session.commit()
        except Exception as e:
            logger.warning(f"Nuclei scan phase failed for full scan {run_id}: {e}")

        # Phase 3: ZAP scan
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.current_stage = "zap_spider"
                run.stage_message = "ZAP spidering target..."
                session.add(run)
                session.commit()

        try:
            active_scan_level = _valid_active_scan_level(req.active_scan_level)
            proxy_url = f"http://{os.environ.get('ZAP_HOST', 'localhost')}:{int(os.environ.get('ZAP_PORT', '8090'))}"
            auth_headers = await _build_auth_headers(req, project_id, proxy_url=proxy_url)

            from services.security.zap_client import run_zap_scan

            zap_findings = _filter_excluded_findings(
                await run_zap_scan(
                    req.target_url,
                    active_scan_enabled=active_scan_level == "full",
                    active_scan_level=active_scan_level,
                    auth_context={"headers": auth_headers} if auth_headers else None,
                ),
                req.excluded_paths,
            )
            for finding in zap_findings:
                finding["scanner"] = "zap"

            with Session(engine) as session:
                run = _get_scan_run_for_project(session, run_id, project_id)
                if run:
                    run.zap_scan_completed = True
                    session.add(run)
                session.commit()
        except Exception as e:
            logger.warning(f"ZAP scan phase failed for full scan {run_id}: {e}")

        from services.security.finding_deduplicator import merge_scanner_findings

        all_findings = merge_scanner_findings(quick_findings, nuclei_findings, zap_findings)

        # Save all findings to DB
        with Session(engine) as session:
            for f in all_findings:
                finding = SecurityFinding(
                    scan_id=run_id,
                    project_id=project_id,
                    severity=f["severity"],
                    finding_type=f["finding_type"],
                    category=f["category"],
                    scanner=f.get("scanner", "quick"),
                    title=f["title"],
                    description=f["description"],
                    url=f["url"],
                    evidence=f.get("evidence"),
                    remediation=f.get("remediation"),
                    reference_urls_json=json.dumps(f.get("reference_urls", [])),
                    finding_hash=f["finding_hash"],
                    template_id=f.get("template_id"),
                    zap_alert_ref=f.get("zap_alert_ref"),
                    zap_cweid=f.get("zap_cweid"),
                )
                session.add(finding)
                severity_counts[f["severity"]] = severity_counts.get(f["severity"], 0) + 1

            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.status = "completed"
                run.completed_at = datetime.utcnow()
                run.total_findings = len(all_findings)
                run.critical_count = severity_counts["critical"]
                run.high_count = severity_counts["high"]
                run.medium_count = severity_counts["medium"]
                run.low_count = severity_counts["low"]
                run.info_count = severity_counts["info"]
                run.current_stage = "done"
                run.stage_message = f"Found {len(all_findings)} issues across all scanners"
                session.add(run)
            session.commit()

        _security_jobs[job_id]["status"] = "completed"
        _security_jobs[job_id]["completed_at"] = time.time()
        _security_jobs[job_id]["result"] = {"total_findings": len(all_findings)}

    except asyncio.CancelledError:
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.status = "cancelled"
                run.completed_at = datetime.utcnow()
                run.current_stage = "cancelled"
                run.stage_message = "Cancelled by user"
                session.add(run)
                session.commit()
        _security_jobs[job_id]["status"] = "cancelled"
        _security_jobs[job_id]["completed_at"] = time.time()
        raise
    except Exception as e:
        logger.error(f"Full scan failed: {e}")
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.status = "failed"
                run.error_message = str(e)
                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()
        _security_jobs[job_id]["status"] = "failed"
        _security_jobs[job_id]["error"] = str(e)
        _security_jobs[job_id]["completed_at"] = time.time()


async def _run_ai_analysis_job(job_id: str, run_id: str, project_id: str):
    """Background task for AI remediation analysis."""
    _security_jobs[job_id]["status"] = "running"
    _security_jobs[job_id]["started_at"] = time.time()

    try:
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.current_stage = "ai_analysis"
                run.stage_message = "AI analyzing findings for remediation..."
                session.add(run)
                session.commit()

        # Fetch findings for analysis
        with Session(engine) as session:
            statement = select(SecurityFinding).where(SecurityFinding.scan_id == run_id)
            findings = session.exec(statement).all()
            findings_data = [
                {
                    "id": f.id,
                    "severity": f.severity,
                    "title": f.title,
                    "description": f.description,
                    "url": f.url,
                    "evidence": f.evidence,
                    "category": f.category,
                    "finding_type": f.finding_type,
                }
                for f in findings
            ]

        from workflows.security_analyzer import analyze_findings

        results = await analyze_findings(findings_data, project_id=project_id)

        # Update findings with AI remediation
        with Session(engine) as session:
            for result in results:
                finding = _get_finding_for_project(session, result["finding_id"], project_id)
                if finding:
                    finding.remediation = result.get("remediation")
                    session.add(finding)
            run = _get_scan_run_for_project(session, run_id, project_id)
            if run:
                run.current_stage = "done"
                run.stage_message = "AI analysis complete"
                session.add(run)
            session.commit()

        _security_jobs[job_id]["status"] = "completed"
        _security_jobs[job_id]["completed_at"] = time.time()
        _security_jobs[job_id]["result"] = {"analyzed_findings": len(results)}

    except Exception as e:
        logger.error(f"AI analysis failed for run {run_id}: {e}")
        _security_jobs[job_id]["status"] = "failed"
        _security_jobs[job_id]["error"] = str(e)
        _security_jobs[job_id]["completed_at"] = time.time()


# ========== Discovery / Capability Endpoints ==========


@router.get("/capabilities")
async def get_capabilities():
    """Report scanner availability so the UI can guide users before running scans."""
    return await _get_capabilities()


@router.get("/targets")
async def list_security_targets(project_id: str = Query(...), limit: int = Query(25, ge=1, le=100)):
    """Suggest scan targets from recent exploration sessions and discovered API endpoints."""
    with Session(engine) as session:
        sessions = session.exec(
            select(ExplorationSession)
            .where(ExplorationSession.project_id == project_id)
            .order_by(ExplorationSession.created_at.desc())
            .limit(limit)
        ).all()
        endpoints = session.exec(
            select(DiscoveredApiEndpoint)
            .where(DiscoveredApiEndpoint.project_id == project_id)
            .order_by(DiscoveredApiEndpoint.first_seen.desc())
            .limit(limit * 4)
        ).all()

    target_map: dict[str, dict] = {}

    def add_target(url: str, source: str, method: str | None = None, session_id: str | None = None) -> None:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return
        origin = f"{parsed.scheme}://{parsed.netloc}"
        item = target_map.setdefault(
            origin,
            {
                "url": origin,
                "host": parsed.netloc,
                "sources": set(),
                "endpoint_count": 0,
                "sample_endpoints": [],
                "latest_session_id": session_id,
            },
        )
        item["sources"].add(source)
        if session_id and not item.get("latest_session_id"):
            item["latest_session_id"] = session_id
        if method:
            item["endpoint_count"] += 1
            if len(item["sample_endpoints"]) < 5:
                item["sample_endpoints"].append({"method": method, "url": url})

    for exploration in sessions:
        add_target(exploration.entry_url, "exploration", session_id=exploration.id)
    for endpoint in endpoints:
        add_target(endpoint.url, "api", method=endpoint.method, session_id=endpoint.session_id)

    targets = []
    for item in target_map.values():
        item["sources"] = sorted(item["sources"])
        targets.append(item)

    targets.sort(key=lambda t: (len(t["sources"]), t["endpoint_count"]), reverse=True)
    return {"targets": targets[:limit], "project_id": project_id}


# ========== Spec Endpoints ==========


@router.get("/specs")
async def list_security_specs(project_id: str = Query(...)):
    """List all security test specifications."""
    return _scan_security_specs(project_id)


@router.get("/specs/{name:path}")
async def get_security_spec(name: str, project_id: str = Query(...)):
    """Get a single security spec content."""
    target = _get_spec_path_for_project(name, project_id)

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Security spec '{name}' not found")

    content = target.read_text(encoding="utf-8")
    return {
        "name": target.name,
        "path": str(target.relative_to(BASE_DIR)),
        "content": content,
    }


@router.post("/specs")
async def create_security_spec(req: CreateSecuritySpecRequest):
    """Create a new security test spec file."""
    name = req.name if req.name.endswith(".md") else f"{req.name}.md"

    specs_dir = _get_specs_dir(req.project_id)
    target = specs_dir / name

    if target.exists():
        raise HTTPException(status_code=409, detail=f"Spec '{name}' already exists")

    target.write_text(req.content, encoding="utf-8")
    logger.info(f"Created security spec: {target}")
    return {
        "name": target.name,
        "path": str(target.relative_to(BASE_DIR)),
        "message": "Security spec created",
    }


@router.put("/specs/{name:path}")
async def update_security_spec(name: str, req: UpdateSecuritySpecRequest, project_id: str = Query(...)):
    """Update an existing security spec."""
    target = _get_spec_path_for_project(name, project_id)

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Security spec '{name}' not found")

    target.write_text(req.content, encoding="utf-8")
    return {"name": target.name, "path": str(target.relative_to(BASE_DIR)), "message": "Spec updated"}


@router.delete("/specs/{name:path}")
async def delete_security_spec(name: str, project_id: str = Query(...)):
    """Delete a security spec."""
    target = _get_spec_path_for_project(name, project_id)

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Security spec '{name}' not found")

    target.unlink()
    return {"message": f"Spec '{name}' deleted"}


# ========== Scan Execution Endpoints ==========


@router.post("/scan/quick")
async def start_quick_scan(req: QuickScanRequest):
    """Start a quick security scan (headers, cookies, CORS, info disclosure)."""
    _cleanup_old_jobs()
    _valid_active_scan_level(req.active_scan_level)
    _normalize_auth_config(req)

    run_id = _generate_run_id()
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    project_id = req.project_id

    # Create DB record
    with Session(engine) as session:
        run = SecurityScanRun(
            id=run_id,
            target_url=req.target_url,
            scan_type="quick",
            status="pending",
            project_id=project_id,
            current_stage="pending",
            stage_message="Queued for quick scan",
        )
        session.add(run)
        session.commit()

    # Track job
    _security_jobs[job_id] = {
        "job_id": job_id,
        "run_id": run_id,
        "scan_type": "quick",
        "target_url": req.target_url,
        "status": "pending",
        "created_at": time.time(),
        "project_id": project_id,
    }

    # Start background task
    _track_task(job_id, asyncio.create_task(_run_quick_scan_job(job_id, run_id, req, project_id)))

    return {"job_id": job_id, "run_id": run_id, "status": "pending"}


@router.post("/scan/nuclei")
async def start_nuclei_scan(req: NucleiScanRequest):
    """Start a Nuclei vulnerability scan."""
    _cleanup_old_jobs()
    _valid_active_scan_level(req.active_scan_level)
    _normalize_auth_config(req)

    run_id = _generate_run_id()
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    project_id = req.project_id

    with Session(engine) as session:
        run = SecurityScanRun(
            id=run_id,
            target_url=req.target_url,
            scan_type="nuclei",
            status="pending",
            project_id=project_id,
            current_stage="pending",
            stage_message="Queued for Nuclei scan",
        )
        session.add(run)
        session.commit()

    _security_jobs[job_id] = {
        "job_id": job_id,
        "run_id": run_id,
        "scan_type": "nuclei",
        "target_url": req.target_url,
        "status": "pending",
        "created_at": time.time(),
        "project_id": project_id,
    }

    _track_task(job_id, asyncio.create_task(_run_nuclei_scan_job(job_id, run_id, req, project_id)))

    return {"job_id": job_id, "run_id": run_id, "status": "pending"}


@router.post("/scan/zap")
async def start_zap_scan(req: ZapScanRequest):
    """Start a ZAP DAST scan."""
    _cleanup_old_jobs()
    _valid_active_scan_level(req.active_scan_level)
    _normalize_auth_config(req)

    run_id = _generate_run_id()
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    project_id = req.project_id

    with Session(engine) as session:
        run = SecurityScanRun(
            id=run_id,
            target_url=req.target_url,
            scan_type="zap",
            status="pending",
            project_id=project_id,
            current_stage="pending",
            stage_message="Queued for ZAP scan",
        )
        session.add(run)
        session.commit()

    _security_jobs[job_id] = {
        "job_id": job_id,
        "run_id": run_id,
        "scan_type": "zap",
        "target_url": req.target_url,
        "status": "pending",
        "created_at": time.time(),
        "project_id": project_id,
    }

    _track_task(job_id, asyncio.create_task(_run_zap_scan_job(job_id, run_id, req, project_id)))

    return {"job_id": job_id, "run_id": run_id, "status": "pending"}


@router.post("/scan/full")
async def start_full_scan(req: FullScanRequest):
    """Start a full security scan (quick -> nuclei -> zap sequentially)."""
    _cleanup_old_jobs()
    _valid_active_scan_level(req.active_scan_level)
    _normalize_auth_config(req)

    run_id = _generate_run_id()
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    project_id = req.project_id

    with Session(engine) as session:
        run = SecurityScanRun(
            id=run_id,
            target_url=req.target_url,
            scan_type="full",
            status="pending",
            project_id=project_id,
            current_stage="pending",
            stage_message="Queued for full security scan",
        )
        session.add(run)
        session.commit()

    _security_jobs[job_id] = {
        "job_id": job_id,
        "run_id": run_id,
        "scan_type": "full",
        "target_url": req.target_url,
        "status": "pending",
        "created_at": time.time(),
        "project_id": project_id,
    }

    _track_task(job_id, asyncio.create_task(_run_full_scan_job(job_id, run_id, req, project_id)))

    return {"job_id": job_id, "run_id": run_id, "status": "pending"}


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str, project_id: str = Query(...)):
    """Poll job status."""
    job = _security_jobs.get(job_id)
    if job and job.get("project_id") and job.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    if not job:
        # Fallback: check DB for completed security scan runs
        # Security jobs store run_id in the job dict; after a restart we lose that mapping.
        # Try to find a matching SecurityScanRun by searching for the job_id hash fragment.
        try:
            with Session(engine) as session:
                # Direct lookup: job_id itself might be a run_id
                db_run = _get_scan_run_for_project(session, job_id, project_id)
                if not db_run:
                    # Security job IDs are "job-<hex8>"; run IDs are "sec-<hex8>".
                    # Try replacing the prefix to find the associated run.
                    hex_part = job_id.replace("job-", "")
                    candidate_run_id = f"sec-{hex_part}"
                    db_run = _get_scan_run_for_project(session, candidate_run_id, project_id)
                if not db_run:
                    # Last resort: search for runs whose ID contains the hex fragment
                    statement = (
                        select(SecurityScanRun)
                        .where(SecurityScanRun.id.contains(hex_part), _project_scope(SecurityScanRun, project_id))
                        .order_by(SecurityScanRun.created_at.desc())
                        .limit(1)
                    )
                    db_run = session.exec(statement).first()
                if db_run:
                    return {
                        "job_id": job_id,
                        "run_id": db_run.id,
                        "scan_type": db_run.scan_type,
                        "target_url": db_run.target_url,
                        "status": db_run.status,
                        "result": {"total_findings": db_run.total_findings},
                        "error": db_run.error_message,
                    }
        except Exception as e:
            logger.warning(f"DB fallback lookup failed for security job {job_id}: {e}")
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    enriched = dict(job)
    try:
        with Session(engine) as session:
            run = _get_scan_run_for_project(session, job.get("run_id"), project_id)
            if run:
                enriched.update(
                    {
                        "status": run.status,
                        "stage": run.current_stage,
                        "current_stage": run.current_stage,
                        "message": run.stage_message,
                        "stage_message": run.stage_message,
                        "error": run.error_message,
                        "error_message": run.error_message,
                        "result": {"total_findings": run.total_findings},
                        "quick_scan_completed": run.quick_scan_completed,
                        "nuclei_scan_completed": run.nuclei_scan_completed,
                        "zap_scan_completed": run.zap_scan_completed,
                    }
                )
    except Exception as e:
        logger.warning(f"DB enrich failed for security job {job_id}: {e}")
    return enriched


@router.post("/runs/{run_id}/stop")
async def stop_scan(run_id: str, project_id: str = Query(...)):
    """Stop a running scan."""
    with Session(engine) as session:
        run = _get_scan_run_for_project(session, run_id, project_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        if run.status != "running":
            raise HTTPException(status_code=400, detail=f"Run is not running (status: {run.status})")

        run.status = "cancelled"
        run.completed_at = datetime.utcnow()
        run.stage_message = "Cancelled by user"
        session.add(run)
        session.commit()

    # Update in-memory job tracker and cancel the underlying task when this process owns it.
    for _job_id, job in _security_jobs.items():
        if job.get("run_id") == run_id:
            job["status"] = "cancelled"
            job["completed_at"] = time.time()
            task = _security_tasks.get(_job_id)
            if task and not task.done():
                task.cancel()
            break

    return {"message": f"Scan {run_id} cancelled", "status": "cancelled"}


# ========== Run History Endpoints ==========


@router.get("/runs")
async def list_scan_runs(
    project_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List scan run history."""
    with Session(engine) as session:
        statement = select(SecurityScanRun).where(SecurityScanRun.project_id == project_id)
        statement = statement.order_by(SecurityScanRun.created_at.desc()).offset(offset).limit(limit)
        runs = session.exec(statement).all()

        # Count total
        count_stmt = select(func.count()).select_from(SecurityScanRun).where(SecurityScanRun.project_id == project_id)
        total = session.exec(count_stmt).one()

    return {
        "runs": [_run_to_dict(r) for r in runs],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/runs/compare")
async def compare_runs(
    run_ids: str = Query(..., description="Comma-separated run IDs"),
    project_id: str = Query(...),
):
    """Compare two or more scan runs."""
    ids = [r.strip() for r in run_ids.split(",") if r.strip()]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="At least two run IDs required for comparison")

    with Session(engine) as session:
        runs_data = []
        for rid in ids:
            run = _get_scan_run_for_project(session, rid, project_id)
            if not run:
                raise HTTPException(status_code=404, detail=f"Run '{rid}' not found")

            findings_stmt = select(SecurityFinding).where(
                SecurityFinding.scan_id == rid,
                _project_scope(SecurityFinding, project_id),
            )
            findings = session.exec(findings_stmt).all()

            by_scanner = {}
            for f in findings:
                by_scanner.setdefault(f.scanner, 0)
                by_scanner[f.scanner] += 1

            run_data = _run_to_dict(run)
            run_data["by_scanner"] = by_scanner
            runs_data.append(run_data)

        return {"runs": runs_data}


@router.get("/runs/{run_id}")
async def get_scan_run(run_id: str, project_id: str = Query(...)):
    """Get scan run with findings summary."""
    with Session(engine) as session:
        run = _get_scan_run_for_project(session, run_id, project_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

        # Fetch findings
        statement = select(SecurityFinding).where(
            SecurityFinding.scan_id == run_id,
            _project_scope(SecurityFinding, project_id),
        )
        findings = session.exec(statement).all()

        data = _run_to_dict(run)
        data["findings_count"] = len(findings)
        return data


# ========== Findings Endpoints ==========


@router.get("/findings")
async def list_project_findings(
    project_id: str = Query(...),
    severity: str | None = Query(None, description="Filter by severity: critical,high,medium,low,info"),
    status: str | None = Query(None, description="Filter by status: open,false_positive,fixed,accepted_risk"),
    scanner: str | None = Query(None, description="Filter by scanner: quick,nuclei,zap"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List findings across project runs with server-side filters."""
    severity_rank = case(
        (SecurityFinding.severity == "critical", 0),
        (SecurityFinding.severity == "high", 1),
        (SecurityFinding.severity == "medium", 2),
        (SecurityFinding.severity == "low", 3),
        else_=4,
    )
    with Session(engine) as session:
        statement = select(SecurityFinding).where(SecurityFinding.project_id == project_id)
        count_stmt = select(func.count()).select_from(SecurityFinding).where(SecurityFinding.project_id == project_id)
        if severity:
            severity_list = [s.strip().lower() for s in severity.split(",")]
            statement = statement.where(SecurityFinding.severity.in_(severity_list))
            count_stmt = count_stmt.where(SecurityFinding.severity.in_(severity_list))
        if status:
            status_list = [s.strip().lower() for s in status.split(",")]
            statement = statement.where(SecurityFinding.status.in_(status_list))
            count_stmt = count_stmt.where(SecurityFinding.status.in_(status_list))
        if scanner:
            scanner_list = [s.strip().lower() for s in scanner.split(",")]
            statement = statement.where(SecurityFinding.scanner.in_(scanner_list))
            count_stmt = count_stmt.where(SecurityFinding.scanner.in_(scanner_list))

        statement = statement.order_by(severity_rank, SecurityFinding.created_at.desc()).offset(offset).limit(limit)
        findings = session.exec(statement).all()
        total = session.exec(count_stmt).one()

    return {
        "findings": [_finding_to_dict(f) for f in findings],
        "total": total,
        "limit": limit,
        "offset": offset,
        "project_id": project_id,
    }


@router.get("/runs/{run_id}/findings")
async def get_findings(
    run_id: str,
    project_id: str = Query(...),
    severity: str | None = Query(None, description="Filter by severity: critical,high,medium,low,info"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """Get findings for a scan run, optionally filtered by severity."""
    with Session(engine) as session:
        run = _get_scan_run_for_project(session, run_id, project_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

        statement = select(SecurityFinding).where(
            SecurityFinding.scan_id == run_id,
            _project_scope(SecurityFinding, project_id),
        )
        if severity:
            severity_list = [s.strip().lower() for s in severity.split(",")]
            statement = statement.where(SecurityFinding.severity.in_(severity_list))
        severity_rank = case(
            (SecurityFinding.severity == "critical", 0),
            (SecurityFinding.severity == "high", 1),
            (SecurityFinding.severity == "medium", 2),
            (SecurityFinding.severity == "low", 3),
            else_=4,
        )
        statement = statement.order_by(severity_rank, SecurityFinding.created_at.desc())
        findings = session.exec(statement.offset(offset).limit(limit)).all()

        return [_finding_to_dict(f) for f in findings]


@router.patch("/findings/{finding_id}/status")
async def update_finding_status(
    finding_id: int,
    req: UpdateFindingStatusRequest,
    project_id: str = Query(...),
):
    """Update finding status (mark false_positive, fixed, accepted_risk, open)."""
    valid_statuses = {"open", "false_positive", "fixed", "accepted_risk"}
    if req.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    with Session(engine) as session:
        finding = _get_finding_for_project(session, finding_id, project_id)
        if not finding:
            raise HTTPException(status_code=404, detail=f"Finding '{finding_id}' not found")

        finding.status = req.status
        if req.notes is not None:
            finding.notes = req.notes
        session.add(finding)
        session.commit()
        session.refresh(finding)

        return {
            "id": finding.id,
            "status": finding.status,
            "notes": finding.notes,
            "message": f"Finding status updated to '{req.status}'",
        }


@router.get("/findings/summary")
async def get_findings_summary(project_id: str = Query(...)):
    """Get aggregated severity counts for a project."""
    with Session(engine) as session:
        statement = select(
            SecurityFinding.severity,
            func.count(SecurityFinding.id).label("count"),
        ).where(
            SecurityFinding.status == "open",
            SecurityFinding.project_id == project_id,
        )

        statement = statement.group_by(SecurityFinding.severity)
        results = session.exec(statement).all()

        summary = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        total = 0
        for severity, count in results:
            summary[severity] = count
            total += count

        status_stmt = (
            select(SecurityFinding.status, func.count(SecurityFinding.id).label("count"))
            .where(SecurityFinding.project_id == project_id)
            .group_by(SecurityFinding.status)
        )
        status_results = session.exec(status_stmt).all()
        by_status = {"open": 0, "false_positive": 0, "fixed": 0, "accepted_risk": 0}
        for status, count in status_results:
            by_status[status] = count

        return {
            "total_open": total,
            "by_severity": summary,
            "by_status": by_status,
            "project_id": project_id,
        }


# ========== AI Analysis Endpoints ==========


@router.post("/analyze/{run_id}")
async def start_ai_analysis(run_id: str, req: AnalyzeRequest):
    """Start AI remediation analysis for a scan run."""
    _cleanup_old_jobs()

    with Session(engine) as session:
        run = _get_scan_run_for_project(session, run_id, req.project_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        if run.status not in ("completed", "failed"):
            raise HTTPException(status_code=400, detail="Scan must be completed before analysis")

    job_id = f"job-{uuid.uuid4().hex[:8]}"
    project_id = req.project_id

    _security_jobs[job_id] = {
        "job_id": job_id,
        "run_id": run_id,
        "scan_type": "ai_analysis",
        "status": "pending",
        "created_at": time.time(),
        "project_id": project_id,
    }

    asyncio.create_task(_run_ai_analysis_job(job_id, run_id, project_id))

    return {"job_id": job_id, "run_id": run_id, "status": "pending"}


@router.post("/generate-spec")
async def generate_security_spec(req: GenerateSpecRequest):
    """AI generates security spec from exploration session data."""
    try:
        with Session(engine) as session:
            exploration = _get_exploration_session_for_project(session, req.session_id, req.project_id)
            if not exploration:
                raise HTTPException(status_code=404, detail=f"Exploration session '{req.session_id}' not found")

        from workflows.security_spec_generator import generate_security_spec_from_session

        result = await generate_security_spec_from_session(req.session_id, project_id=req.project_id)

        if not result:
            raise HTTPException(status_code=500, detail="Failed to generate security spec")

        # Save generated spec
        specs_dir = _get_specs_dir(req.project_id)
        spec_name = result.get("name", f"generated-{uuid.uuid4().hex[:8]}.md")
        if not spec_name.endswith(".md"):
            spec_name = f"{spec_name}.md"
        target = specs_dir / spec_name
        target.write_text(result["content"], encoding="utf-8")

        return {
            "name": spec_name,
            "path": str(target.relative_to(BASE_DIR)),
            "content": result["content"],
            "message": "Security spec generated from exploration session",
        }

    except ImportError:
        raise HTTPException(status_code=501, detail="Security spec generator not yet implemented")
    except Exception as e:
        logger.error(f"Security spec generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
