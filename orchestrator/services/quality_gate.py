"""GitHub PR quality gate state, CI response, and feedback finalization."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from orchestrator.api.credentials import decrypt_credential
from orchestrator.api.models_db import (
    PrImpactAnalysis,
    Project,
    PrQualityGateRun,
    PrSelectedTest,
    RegressionBatch,
)
from orchestrator.api.models_db import TestRun as DBTestRun
from orchestrator.services.github_client import GithubClient
from orchestrator.services.pr_test_advisor import serialize_analysis

logger = logging.getLogger(__name__)

TERMINAL_RUN_STATUSES = {"passed", "completed", "failed", "error", "stopped", "cancelled", "canceled"}
FAILURE_RUN_STATUSES = {"failed", "error", "stopped", "cancelled", "canceled"}
ACTIVE_RUN_STATUSES = {"queued", "running", "in_progress", "pending"}

QUALITY_GATE_CONTEXT = "Quorvex Quality Gate"
QUALITY_GATE_COMMENT_MARKER = "<!-- quorvex-quality-gate -->"

DEFAULT_QUALITY_GATE_CONFIG: dict[str, Any] = {
    "enabled": True,
    "ensure_indexed": True,
    "run_recommended": True,
    "post_feedback": True,
    "create_commit_status": True,
    "force_reindex": False,
    "require_full_suite_on_low_confidence": True,
    "allow_empty_selection": False,
    "default_browser": "chromium",
    "hybrid": False,
    "max_iterations": 20,
    "timeout_minutes": 120,
}


def get_github_config(project: Project) -> dict[str, Any]:
    if not project.settings:
        return {}
    return (project.settings.get("integrations") or {}).get("github") or {}


def get_quality_gate_config(project: Project) -> dict[str, Any]:
    raw = get_github_config(project).get("quality_gate") or {}
    config = {**DEFAULT_QUALITY_GATE_CONFIG, **raw}
    config["enabled"] = bool(config.get("enabled", True))
    config["ensure_indexed"] = bool(config.get("ensure_indexed", True))
    config["run_recommended"] = bool(config.get("run_recommended", True))
    config["post_feedback"] = bool(config.get("post_feedback", True))
    config["create_commit_status"] = bool(config.get("create_commit_status", True))
    config["force_reindex"] = bool(config.get("force_reindex", False))
    config["require_full_suite_on_low_confidence"] = bool(config.get("require_full_suite_on_low_confidence", True))
    config["allow_empty_selection"] = bool(config.get("allow_empty_selection", False))
    if config.get("default_browser") not in {"chromium", "firefox", "webkit"}:
        config["default_browser"] = "chromium"
    try:
        config["max_iterations"] = max(1, min(int(config.get("max_iterations") or 20), 100))
    except (TypeError, ValueError):
        config["max_iterations"] = 20
    try:
        config["timeout_minutes"] = max(5, min(int(config.get("timeout_minutes") or 120), 720))
    except (TypeError, ValueError):
        config["timeout_minutes"] = 120
    return config


def quality_gate_app_url(path: str) -> str | None:
    base = os.getenv("WEB_BASE_URL") or os.getenv("FRONTEND_URL") or os.getenv("APP_BASE_URL")
    if not base:
        return None
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def batch_payload(batch: RegressionBatch | None, session: Session) -> dict[str, Any] | None:
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


def quality_gate_status(analysis: PrImpactAnalysis, batch: RegressionBatch | None, session: Session) -> dict[str, Any]:
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


def sync_gate_run_state(gate_run: PrQualityGateRun, analysis: PrImpactAnalysis, session: Session) -> dict[str, Any]:
    batch = session.get(RegressionBatch, gate_run.batch_id) if gate_run.batch_id else None
    status = quality_gate_status(analysis, batch, session)
    gate_run.status = status["state"]
    gate_run.github_state = status["github_state"]
    gate_run.updated_at = datetime.utcnow()
    if status["state"] in {"passed", "failed", "blocked", "needs-full-suite", "error"}:
        gate_run.completed_at = gate_run.completed_at or datetime.utcnow()
    session.add(gate_run)
    return status


def serialize_quality_gate(
    analysis: PrImpactAnalysis,
    session: Session,
    include_details: bool = True,
    gate_run: PrQualityGateRun | None = None,
) -> dict[str, Any]:
    batch = session.get(RegressionBatch, analysis.batch_id) if analysis.batch_id else None
    gate = quality_gate_status(analysis, batch, session)
    payload = serialize_analysis(analysis, session, include_details=include_details)
    gate_payload: dict[str, Any] = {
        **gate,
        "batch": batch_payload(batch, session),
        "analysis_url": quality_gate_app_url("pr-advisor"),
        "batch_url": quality_gate_app_url(f"regression/batches/{analysis.batch_id}") if analysis.batch_id else None,
    }
    if gate_run:
        gate_payload.update(
            {
                "gate_id": gate_run.id,
                "feedback_comment_url": gate_run.feedback_comment_url,
                "commit_status_url": gate_run.commit_status_url,
                "last_feedback_state": gate_run.last_feedback_state,
                "feedback_errors": gate_run.feedback_errors,
                "final_feedback_published_at": (
                    gate_run.final_feedback_published_at.isoformat() if gate_run.final_feedback_published_at else None
                ),
            }
        )
    payload["quality_gate"] = gate_payload
    if gate_run:
        payload["gate_id"] = gate_run.id
        payload["head_sha"] = gate_run.head_sha
    return payload


def ci_status_payload(
    analysis: PrImpactAnalysis,
    session: Session,
    gate_run: PrQualityGateRun | None = None,
) -> dict[str, Any]:
    payload = serialize_quality_gate(analysis, session, include_details=True, gate_run=gate_run)
    gate = payload["quality_gate"]
    state = gate["state"]
    terminal = state in {"passed", "failed", "blocked", "needs-full-suite", "error"}
    failed = state in {"failed", "blocked", "needs-full-suite", "error"}
    batch = gate.get("batch") or {}
    return {
        "gate_id": gate_run.id if gate_run else None,
        "analysis_id": analysis.id,
        "batch_id": analysis.batch_id,
        "pr_number": analysis.pr_number,
        "head_sha": gate_run.head_sha if gate_run else analysis.head_sha,
        "state": state,
        "github_state": gate["github_state"],
        "description": gate["description"],
        "terminal": terminal,
        "passed": state == "passed",
        "failed": failed,
        "blocked": state in {"blocked", "needs-full-suite", "error"},
        "exit_code": 0 if state == "passed" else (1 if terminal else None),
        "summary": analysis.summary,
        "poll_after_seconds": 10 if not terminal else None,
        "analysis_url": gate.get("analysis_url"),
        "batch_url": gate.get("batch_url"),
        "total_tests": batch.get("total_tests"),
        "passed_tests": batch.get("passed"),
        "failed_tests_count": batch.get("failed"),
        "failed_tests": batch.get("failed_tests") or [],
        "selected_tests_count": analysis.selected_tests_count,
        "total_candidate_tests": analysis.total_candidate_tests,
        "risk_level": analysis.risk_level,
        "confidence": analysis.confidence,
        "fallback_reason": analysis.fallback_reason,
    }


def quality_gate_comment(payload: dict[str, Any]) -> str:
    gate = payload["quality_gate"]
    selected = payload.get("selected_tests") or []
    failed = ((gate.get("batch") or {}).get("failed_tests") or [])
    selected_lines = "\n".join(
        f"- `{item['spec_name']}`: {item.get('reason', 'Selected by impact analysis')}" for item in selected[:12]
    )
    if len(selected) > 12:
        selected_lines += f"\n- ...and {len(selected) - 12} more"
    failed_lines = "\n".join(f"- `{item['spec_name']}`: {item.get('status')}" for item in failed[:10])
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


async def publish_quality_gate_feedback(
    *,
    project: Project,
    analysis: PrImpactAnalysis,
    payload: dict[str, Any],
    gate_run: PrQualityGateRun | None = None,
    post_feedback: bool = True,
    create_commit_status: bool = True,
) -> dict[str, Any]:
    config = get_github_config(project)
    owner = config.get("owner", "")
    repo = config.get("repo", "")
    errors: list[str] = []
    result: dict[str, Any] = {"comment": None, "commit_status": None, "errors": errors}
    if not owner or not repo:
        return result

    token = decrypt_credential(config.get("token_encrypted", ""))
    if not token:
        result["errors"].append("GitHub token could not be decrypted")
        return result

    client = GithubClient(token=token)
    try:
        if post_feedback:
            try:
                comments = await client.list_issue_comments(owner, repo, analysis.pr_number)
                existing = next((c for c in comments if QUALITY_GATE_COMMENT_MARKER in (c.get("body") or "")), None)
                body = quality_gate_comment(payload)
                if existing and existing.get("id"):
                    updated = await client.update_issue_comment(owner, repo, int(existing["id"]), body)
                    result["comment"] = {"action": "updated", "url": updated.get("html_url"), "id": updated.get("id")}
                else:
                    created = await client.create_issue_comment(owner, repo, analysis.pr_number, body)
                    result["comment"] = {"action": "created", "url": created.get("html_url"), "id": created.get("id")}
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

    if gate_run:
        comment = result.get("comment") or {}
        commit_status = result.get("commit_status") or {}
        if comment.get("id"):
            gate_run.feedback_comment_id = str(comment["id"])
        if comment.get("url"):
            gate_run.feedback_comment_url = comment["url"]
        if commit_status.get("url"):
            gate_run.commit_status_url = commit_status["url"]
        gate_run.last_feedback_state = payload["quality_gate"]["state"]
        gate_run.feedback_errors = errors
        gate_run.updated_at = datetime.utcnow()
    return result


async def finalize_quality_gate_for_batch(batch_id: str) -> int:
    """Publish final feedback for quality gates linked to a completed batch."""
    from orchestrator.api.db import engine

    finalized = 0
    with Session(engine) as session:
        gate_runs = session.exec(select(PrQualityGateRun).where(PrQualityGateRun.batch_id == batch_id)).all()
        for gate_run in gate_runs:
            if gate_run.final_feedback_published_at:
                continue
            analysis = session.get(PrImpactAnalysis, gate_run.analysis_id) if gate_run.analysis_id else None
            project = session.get(Project, gate_run.project_id) if gate_run.project_id else None
            if not analysis or not project:
                continue
            payload = serialize_quality_gate(analysis, session, include_details=True, gate_run=gate_run)
            sync_gate_run_state(gate_run, analysis, session)
            terminal = gate_run.status in {"passed", "failed", "blocked", "needs-full-suite", "error"}
            if not terminal:
                session.add(gate_run)
                continue
            await publish_quality_gate_feedback(
                project=project,
                analysis=analysis,
                payload=payload,
                gate_run=gate_run,
                post_feedback=gate_run.post_feedback,
                create_commit_status=gate_run.create_commit_status,
            )
            gate_run.final_feedback_published_at = datetime.utcnow()
            session.add(gate_run)
            finalized += 1
        session.commit()
    return finalized


async def finalize_stale_quality_gates(max_age_minutes: int = 5) -> int:
    """Catch completed gates whose final feedback was missed by a restart."""
    from orchestrator.api.db import engine

    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    batch_ids: set[str] = set()
    with Session(engine) as session:
        gate_runs = session.exec(
            select(PrQualityGateRun).where(
                PrQualityGateRun.batch_id != None,
                PrQualityGateRun.final_feedback_published_at == None,
                PrQualityGateRun.updated_at <= cutoff,
            )
        ).all()
        for gate_run in gate_runs:
            batch = session.get(RegressionBatch, gate_run.batch_id) if gate_run.batch_id else None
            if batch and batch.status == "completed":
                batch_ids.add(batch.id)

    finalized = 0
    for batch_id in batch_ids:
        finalized += await finalize_quality_gate_for_batch(batch_id)
    return finalized


def selected_specs_for_analysis(analysis_id: str, session: Session) -> list[str]:
    selected = session.exec(select(PrSelectedTest).where(PrSelectedTest.analysis_id == analysis_id)).all()
    return [row.spec_name for row in selected]
