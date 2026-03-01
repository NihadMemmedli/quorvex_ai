"""
Security Testing Router

Provides endpoints for managing security scan specs, running quick/nuclei/zap scans,
tracking background jobs, querying run history, and managing findings.
"""

import asyncio
import json
import logging
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from .db import engine
from .models_db import SecurityFinding, SecurityScanRun

sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SPECS_DIR = BASE_DIR / "specs"

router = APIRouter(prefix="/security-testing", tags=["security-testing"])

# ========== In-Memory Job Tracking ==========
_security_jobs: dict[str, dict] = {}
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
    project_id: str | None = "default"


class UpdateSecuritySpecRequest(BaseModel):
    content: str


class QuickScanRequest(BaseModel):
    target_url: str
    project_id: str | None = "default"


class NucleiScanRequest(BaseModel):
    target_url: str
    severity_filter: str | None = None  # "critical,high"
    templates: list[str] | None = None
    project_id: str | None = "default"


class ZapScanRequest(BaseModel):
    target_url: str
    scan_policy: str | None = None
    project_id: str | None = "default"


class FullScanRequest(BaseModel):
    target_url: str
    project_id: str | None = "default"


class UpdateFindingStatusRequest(BaseModel):
    status: str  # open, false_positive, fixed, accepted_risk
    notes: str | None = None


class AnalyzeRequest(BaseModel):
    project_id: str | None = "default"


class GenerateSpecRequest(BaseModel):
    session_id: str
    project_id: str | None = "default"


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


def _generate_run_id() -> str:
    return f"sec-{uuid.uuid4().hex[:8]}"


# ========== Background Job Runners ==========


async def _run_quick_scan_job(job_id: str, run_id: str, target_url: str, project_id: str):
    """Background task for quick security scan."""
    _security_jobs[job_id]["status"] = "running"
    _security_jobs[job_id]["started_at"] = time.time()

    try:
        # Update DB status
        with Session(engine) as session:
            run = session.get(SecurityScanRun, run_id)
            if run:
                run.status = "running"
                run.started_at = datetime.utcnow()
                run.current_stage = "quick_scan"
                run.stage_message = "Running security header checks..."
                session.add(run)
                session.commit()

        # Import and run scanner
        from services.security.quick_scanner import run_quick_scan

        findings = await run_quick_scan(target_url)

        # Save findings to DB
        with Session(engine) as session:
            run = session.get(SecurityScanRun, run_id)
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

    except Exception as e:
        logger.error(f"Quick scan failed: {e}")
        with Session(engine) as session:
            run = session.get(SecurityScanRun, run_id)
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
    job_id: str, run_id: str, target_url: str, severity_filter: str | None, templates: list[str] | None, project_id: str
):
    """Background task for Nuclei scan."""
    _security_jobs[job_id]["status"] = "running"
    _security_jobs[job_id]["started_at"] = time.time()

    try:
        with Session(engine) as session:
            run = session.get(SecurityScanRun, run_id)
            if run:
                run.status = "running"
                run.started_at = datetime.utcnow()
                run.current_stage = "nuclei_scan"
                run.stage_message = "Running Nuclei vulnerability scan..."
                session.add(run)
                session.commit()

        from services.security.nuclei_scanner import run_nuclei_scan

        findings = await run_nuclei_scan(target_url, severity_filter=severity_filter, templates=templates)

        # Save findings to DB
        with Session(engine) as session:
            run = session.get(SecurityScanRun, run_id)
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

    except Exception as e:
        logger.error(f"Nuclei scan failed: {e}")
        with Session(engine) as session:
            run = session.get(SecurityScanRun, run_id)
            if run:
                run.status = "failed"
                run.error_message = str(e)
                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()
        _security_jobs[job_id]["status"] = "failed"
        _security_jobs[job_id]["error"] = str(e)
        _security_jobs[job_id]["completed_at"] = time.time()


async def _run_zap_scan_job(job_id: str, run_id: str, target_url: str, scan_policy: str | None, project_id: str):
    """Background task for ZAP DAST scan."""
    _security_jobs[job_id]["status"] = "running"
    _security_jobs[job_id]["started_at"] = time.time()

    try:
        with Session(engine) as session:
            run = session.get(SecurityScanRun, run_id)
            if run:
                run.status = "running"
                run.started_at = datetime.utcnow()
                run.current_stage = "zap_spider"
                run.stage_message = "ZAP spidering target..."
                session.add(run)
                session.commit()

        from services.security.zap_scanner import run_zap_scan

        findings = await run_zap_scan(target_url, scan_policy=scan_policy)

        # Save findings to DB
        with Session(engine) as session:
            run = session.get(SecurityScanRun, run_id)
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

    except Exception as e:
        logger.error(f"ZAP scan failed: {e}")
        with Session(engine) as session:
            run = session.get(SecurityScanRun, run_id)
            if run:
                run.status = "failed"
                run.error_message = str(e)
                run.completed_at = datetime.utcnow()
                session.add(run)
                session.commit()
        _security_jobs[job_id]["status"] = "failed"
        _security_jobs[job_id]["error"] = str(e)
        _security_jobs[job_id]["completed_at"] = time.time()


async def _run_full_scan_job(job_id: str, run_id: str, target_url: str, project_id: str):
    """Background task for full scan (quick -> nuclei -> zap sequentially)."""
    _security_jobs[job_id]["status"] = "running"
    _security_jobs[job_id]["started_at"] = time.time()

    all_findings = []
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}

    try:
        with Session(engine) as session:
            run = session.get(SecurityScanRun, run_id)
            if run:
                run.status = "running"
                run.started_at = datetime.utcnow()
                session.add(run)
                session.commit()

        # Phase 1: Quick scan
        with Session(engine) as session:
            run = session.get(SecurityScanRun, run_id)
            if run:
                run.current_stage = "quick_scan"
                run.stage_message = "Running security header checks..."
                session.add(run)
                session.commit()

        try:
            from services.security.quick_scanner import run_quick_scan

            quick_findings = await run_quick_scan(target_url)
            all_findings.extend(quick_findings)

            with Session(engine) as session:
                run = session.get(SecurityScanRun, run_id)
                if run:
                    run.quick_scan_completed = True
                    session.add(run)
                session.commit()
        except Exception as e:
            logger.warning(f"Quick scan phase failed for full scan {run_id}: {e}")

        # Phase 2: Nuclei scan
        with Session(engine) as session:
            run = session.get(SecurityScanRun, run_id)
            if run:
                run.current_stage = "nuclei_scan"
                run.stage_message = "Running Nuclei vulnerability scan..."
                session.add(run)
                session.commit()

        try:
            from services.security.nuclei_scanner import run_nuclei_scan

            nuclei_findings = await run_nuclei_scan(target_url)
            all_findings.extend(nuclei_findings)

            with Session(engine) as session:
                run = session.get(SecurityScanRun, run_id)
                if run:
                    run.nuclei_scan_completed = True
                    session.add(run)
                session.commit()
        except Exception as e:
            logger.warning(f"Nuclei scan phase failed for full scan {run_id}: {e}")

        # Phase 3: ZAP scan
        with Session(engine) as session:
            run = session.get(SecurityScanRun, run_id)
            if run:
                run.current_stage = "zap_spider"
                run.stage_message = "ZAP spidering target..."
                session.add(run)
                session.commit()

        try:
            from services.security.zap_scanner import run_zap_scan

            zap_findings = await run_zap_scan(target_url)
            all_findings.extend(zap_findings)

            with Session(engine) as session:
                run = session.get(SecurityScanRun, run_id)
                if run:
                    run.zap_scan_completed = True
                    session.add(run)
                session.commit()
        except Exception as e:
            logger.warning(f"ZAP scan phase failed for full scan {run_id}: {e}")

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

            run = session.get(SecurityScanRun, run_id)
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

    except Exception as e:
        logger.error(f"Full scan failed: {e}")
        with Session(engine) as session:
            run = session.get(SecurityScanRun, run_id)
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
            run = session.get(SecurityScanRun, run_id)
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
                finding = session.get(SecurityFinding, result["finding_id"])
                if finding:
                    finding.remediation = result.get("remediation")
                    session.add(finding)
            run = session.get(SecurityScanRun, run_id)
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


# ========== Spec Endpoints ==========


@router.get("/specs")
async def list_security_specs(project_id: str = Query("default")):
    """List all security test specifications."""
    return _scan_security_specs(project_id)


@router.get("/specs/{name:path}")
async def get_security_spec(name: str, project_id: str = Query("default")):
    """Get a single security spec content."""
    specs_dir = _get_specs_dir(project_id)
    target = None
    if specs_dir.exists():
        for md_file in specs_dir.rglob("*.md"):
            if md_file.name == name:
                target = md_file
                break

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
async def update_security_spec(name: str, req: UpdateSecuritySpecRequest, project_id: str = Query("default")):
    """Update an existing security spec."""
    specs_dir = _get_specs_dir(project_id)
    target = None
    if specs_dir.exists():
        for md_file in specs_dir.rglob("*.md"):
            if md_file.name == name:
                target = md_file
                break

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Security spec '{name}' not found")

    target.write_text(req.content, encoding="utf-8")
    return {"name": target.name, "path": str(target.relative_to(BASE_DIR)), "message": "Spec updated"}


@router.delete("/specs/{name:path}")
async def delete_security_spec(name: str, project_id: str = Query("default")):
    """Delete a security spec."""
    specs_dir = _get_specs_dir(project_id)
    target = None
    if specs_dir.exists():
        for md_file in specs_dir.rglob("*.md"):
            if md_file.name == name:
                target = md_file
                break

    if not target or not target.exists():
        raise HTTPException(status_code=404, detail=f"Security spec '{name}' not found")

    target.unlink()
    return {"message": f"Spec '{name}' deleted"}


# ========== Scan Execution Endpoints ==========


@router.post("/scan/quick")
async def start_quick_scan(req: QuickScanRequest):
    """Start a quick security scan (headers, cookies, CORS, info disclosure)."""
    _cleanup_old_jobs()

    run_id = _generate_run_id()
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    project_id = req.project_id or "default"

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
    }

    # Start background task
    asyncio.create_task(_run_quick_scan_job(job_id, run_id, req.target_url, project_id))

    return {"job_id": job_id, "run_id": run_id, "status": "pending"}


@router.post("/scan/nuclei")
async def start_nuclei_scan(req: NucleiScanRequest):
    """Start a Nuclei vulnerability scan."""
    _cleanup_old_jobs()

    run_id = _generate_run_id()
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    project_id = req.project_id or "default"

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
    }

    asyncio.create_task(
        _run_nuclei_scan_job(job_id, run_id, req.target_url, req.severity_filter, req.templates, project_id)
    )

    return {"job_id": job_id, "run_id": run_id, "status": "pending"}


@router.post("/scan/zap")
async def start_zap_scan(req: ZapScanRequest):
    """Start a ZAP DAST scan."""
    _cleanup_old_jobs()

    run_id = _generate_run_id()
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    project_id = req.project_id or "default"

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
    }

    asyncio.create_task(_run_zap_scan_job(job_id, run_id, req.target_url, req.scan_policy, project_id))

    return {"job_id": job_id, "run_id": run_id, "status": "pending"}


@router.post("/scan/full")
async def start_full_scan(req: FullScanRequest):
    """Start a full security scan (quick -> nuclei -> zap sequentially)."""
    _cleanup_old_jobs()

    run_id = _generate_run_id()
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    project_id = req.project_id or "default"

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
    }

    asyncio.create_task(_run_full_scan_job(job_id, run_id, req.target_url, project_id))

    return {"job_id": job_id, "run_id": run_id, "status": "pending"}


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Poll job status."""
    job = _security_jobs.get(job_id)
    if not job:
        # Fallback: check DB for completed security scan runs
        # Security jobs store run_id in the job dict; after a restart we lose that mapping.
        # Try to find a matching SecurityScanRun by searching for the job_id hash fragment.
        try:
            with Session(engine) as session:
                # Direct lookup: job_id itself might be a run_id
                db_run = session.get(SecurityScanRun, job_id)
                if not db_run:
                    # Security job IDs are "job-<hex8>"; run IDs are "sec-<hex8>".
                    # Try replacing the prefix to find the associated run.
                    hex_part = job_id.replace("job-", "")
                    candidate_run_id = f"sec-{hex_part}"
                    db_run = session.get(SecurityScanRun, candidate_run_id)
                if not db_run:
                    # Last resort: search for runs whose ID contains the hex fragment
                    statement = (
                        select(SecurityScanRun)
                        .where(SecurityScanRun.id.contains(hex_part))
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
    return job


@router.post("/runs/{run_id}/stop")
async def stop_scan(run_id: str):
    """Stop a running scan."""
    with Session(engine) as session:
        run = session.get(SecurityScanRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        if run.status != "running":
            raise HTTPException(status_code=400, detail=f"Run is not running (status: {run.status})")

        run.status = "cancelled"
        run.completed_at = datetime.utcnow()
        run.stage_message = "Cancelled by user"
        session.add(run)
        session.commit()

    # Update in-memory job tracker
    for _job_id, job in _security_jobs.items():
        if job.get("run_id") == run_id:
            job["status"] = "cancelled"
            job["completed_at"] = time.time()
            break

    return {"message": f"Scan {run_id} cancelled", "status": "cancelled"}


# ========== Run History Endpoints ==========


@router.get("/runs")
async def list_scan_runs(
    project_id: str = Query("default"),
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
        "runs": [
            {
                "id": r.id,
                "spec_name": r.spec_name,
                "target_url": r.target_url,
                "scan_type": r.scan_type,
                "status": r.status,
                "project_id": r.project_id,
                "total_findings": r.total_findings,
                "critical_count": r.critical_count,
                "high_count": r.high_count,
                "medium_count": r.medium_count,
                "low_count": r.low_count,
                "info_count": r.info_count,
                "quick_scan_completed": r.quick_scan_completed,
                "nuclei_scan_completed": r.nuclei_scan_completed,
                "zap_scan_completed": r.zap_scan_completed,
                "current_stage": r.current_stage,
                "stage_message": r.stage_message,
                "error_message": r.error_message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "duration_seconds": r.duration_seconds,
            }
            for r in runs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/runs/{run_id}")
async def get_scan_run(run_id: str):
    """Get scan run with findings summary."""
    with Session(engine) as session:
        run = session.get(SecurityScanRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

        # Fetch findings
        statement = select(SecurityFinding).where(SecurityFinding.scan_id == run_id)
        findings = session.exec(statement).all()

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
            "findings_count": len(findings),
        }


# ========== Findings Endpoints ==========


@router.get("/runs/{run_id}/findings")
async def get_findings(
    run_id: str,
    severity: str | None = Query(None, description="Filter by severity: critical,high,medium,low,info"),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """Get findings for a scan run, optionally filtered by severity."""
    with Session(engine) as session:
        run = session.get(SecurityScanRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

        statement = select(SecurityFinding).where(SecurityFinding.scan_id == run_id)
        if severity:
            severity_list = [s.strip().lower() for s in severity.split(",")]
            statement = statement.where(SecurityFinding.severity.in_(severity_list))
        statement = statement.order_by(SecurityFinding.severity, SecurityFinding.created_at)
        findings = session.exec(statement.offset(offset).limit(limit)).all()

        return [
            {
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
                "template_id": f.template_id,
                "zap_alert_ref": f.zap_alert_ref,
                "zap_cweid": f.zap_cweid,
                "finding_hash": f.finding_hash,
                "status": f.status,
                "notes": f.notes,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in findings
        ]


@router.patch("/findings/{finding_id}/status")
async def update_finding_status(finding_id: int, req: UpdateFindingStatusRequest):
    """Update finding status (mark false_positive, fixed, accepted_risk, open)."""
    valid_statuses = {"open", "false_positive", "fixed", "accepted_risk"}
    if req.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    with Session(engine) as session:
        finding = session.get(SecurityFinding, finding_id)
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
async def get_findings_summary(project_id: str = Query("default")):
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

        return {
            "total_open": total,
            "by_severity": summary,
            "project_id": project_id,
        }


# ========== AI Analysis Endpoints ==========


@router.post("/analyze/{run_id}")
async def start_ai_analysis(run_id: str, req: AnalyzeRequest):
    """Start AI remediation analysis for a scan run."""
    _cleanup_old_jobs()

    with Session(engine) as session:
        run = session.get(SecurityScanRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        if run.status not in ("completed", "failed"):
            raise HTTPException(status_code=400, detail="Scan must be completed before analysis")

    job_id = f"job-{uuid.uuid4().hex[:8]}"
    project_id = req.project_id or "default"

    _security_jobs[job_id] = {
        "job_id": job_id,
        "run_id": run_id,
        "scan_type": "ai_analysis",
        "status": "pending",
        "created_at": time.time(),
    }

    asyncio.create_task(_run_ai_analysis_job(job_id, run_id, project_id))

    return {"job_id": job_id, "run_id": run_id, "status": "pending"}


@router.post("/generate-spec")
async def generate_security_spec(req: GenerateSpecRequest):
    """AI generates security spec from exploration session data."""
    try:
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


@router.get("/runs/compare")
async def compare_runs(run_ids: str = Query(..., description="Comma-separated run IDs")):
    """Compare two or more scan runs."""
    ids = [r.strip() for r in run_ids.split(",") if r.strip()]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="At least two run IDs required for comparison")

    with Session(engine) as session:
        runs_data = []
        for rid in ids:
            run = session.get(SecurityScanRun, rid)
            if not run:
                raise HTTPException(status_code=404, detail=f"Run '{rid}' not found")

            # Get findings by severity
            findings_stmt = select(SecurityFinding).where(SecurityFinding.scan_id == rid)
            findings = session.exec(findings_stmt).all()

            # Group by scanner
            by_scanner = {}
            for f in findings:
                by_scanner.setdefault(f.scanner, 0)
                by_scanner[f.scanner] += 1

            runs_data.append(
                {
                    "id": run.id,
                    "target_url": run.target_url,
                    "scan_type": run.scan_type,
                    "status": run.status,
                    "total_findings": run.total_findings,
                    "critical_count": run.critical_count,
                    "high_count": run.high_count,
                    "medium_count": run.medium_count,
                    "low_count": run.low_count,
                    "info_count": run.info_count,
                    "by_scanner": by_scanner,
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                    "duration_seconds": run.duration_seconds,
                }
            )

        return {"runs": runs_data}
