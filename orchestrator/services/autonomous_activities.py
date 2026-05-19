"""Temporal activities for persistent autonomous testing missions."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from orchestrator.api.db import engine
from orchestrator.api.models_db import (
    AutonomousApproval,
    AutonomousFinding,
    AutonomousMission,
    AutonomousMissionRun,
    AutonomousTestProposal,
    CoverageGap,
)
from orchestrator.utils.string_utils import slugify

logger = logging.getLogger(__name__)

MAX_PROPOSALS_PER_ITERATION = 5
VALID_TEST_TYPES = {"e2e", "api", "regression", "security", "accessibility", "unit"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _mission_snapshot(mission: AutonomousMission) -> dict[str, Any]:
    return {
        "id": mission.id,
        "project_id": mission.project_id,
        "mission_type": mission.mission_type,
        "status": mission.status,
        "target_urls": mission.target_urls,
        "schedule_cron": mission.schedule_cron,
        "timezone": mission.timezone,
        "max_iterations": mission.max_iterations,
        "max_runtime_minutes": mission.max_runtime_minutes,
        "max_llm_budget_usd": mission.max_llm_budget_usd,
        "budget_used_usd": mission.budget_used_usd,
        "approval_policy": mission.approval_policy,
        "autonomy_level": mission.autonomy_level,
    }


def load_mission_policy(mission_id: str) -> dict[str, Any]:
    """Load mission state for deterministic workflow decisions."""
    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        if not mission:
            raise ValueError(f"Autonomous mission not found: {mission_id}")
        return _mission_snapshot(mission)


def create_mission_run(payload: dict[str, Any]) -> str:
    """Create a mission run row for one Temporal iteration."""
    mission_id = payload["mission_id"]
    workflow_id = payload.get("workflow_id")
    trigger_type = payload.get("trigger_type", "temporal")
    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        if not mission:
            raise ValueError(f"Autonomous mission not found: {mission_id}")

        run_id = f"amrun-{uuid.uuid4().hex[:12]}"
        now = _utcnow()
        run = AutonomousMissionRun(
            id=run_id,
            mission_id=mission.id,
            project_id=mission.project_id,
            workflow_id=workflow_id,
            mission_type=mission.mission_type,
            trigger_type=trigger_type,
            status="running",
            current_stage="planning",
            started_at=now,
            updated_at=now,
        )
        mission.status = "running"
        mission.latest_workflow_id = workflow_id
        mission.latest_run_id = run_id
        mission.last_run_at = now
        mission.total_runs += 1
        mission.last_error = None
        mission.updated_at = now
        session.add(run)
        session.add(mission)
        session.commit()
        return run_id


def execute_mission_iteration(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one bounded autonomous mission iteration.

    The first implementation intentionally records internal, approval-gated
    findings from existing project truth. Follow-up activities can add direct
    AutoPilot, regression, and bug-report execution without changing workflow
    state semantics.
    """
    mission_id = payload["mission_id"]
    run_id = payload["run_id"]
    workflow_id = payload.get("workflow_id")

    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        run = session.get(AutonomousMissionRun, run_id)
        if not mission or not run:
            raise ValueError(f"Autonomous mission/run not found: {mission_id}/{run_id}")

        now = _utcnow()
        run.current_stage = "analyzing"
        run.updated_at = now
        session.add(run)
        session.commit()

        summary: dict[str, Any] = {
            "workflow_id": workflow_id,
            "mission_type": mission.mission_type,
            "target_urls": mission.target_urls,
            "findings_created": 0,
            "approvals_created": 0,
            "test_proposals_created": 0,
            "notes": [],
        }

        if mission.mission_type in {"coverage", "mixed", "exploration"}:
            coverage_summary = _create_coverage_gap_artifacts(session, mission, run)
            summary["findings_created"] += coverage_summary["findings_created"]
            summary["approvals_created"] += coverage_summary["approvals_created"]
            summary["test_proposals_created"] += coverage_summary["test_proposals_created"]
            if coverage_summary["test_proposals_created"]:
                summary["notes"].append(
                    f"Generated {coverage_summary['test_proposals_created']} pending test proposal(s) from coverage gaps."
                )
            else:
                summary["notes"].append("No unresolved coverage gaps were available for this project.")

        approved_finding_count = _create_proposals_for_approved_findings(session, mission, run)
        summary["test_proposals_created"] += approved_finding_count
        if approved_finding_count:
            summary["notes"].append(f"Generated {approved_finding_count} pending test proposal(s) from approved findings.")

        if mission.mission_type in {"regression", "mixed"}:
            summary["notes"].append("Regression mission ledger is ready; existing batch execution can be attached as a next activity.")

        if mission.mission_type in {"flake_triage", "mixed"}:
            summary["notes"].append("Flake triage will use parsed Playwright JSON retries and historical TestExecutionHistory.")

        if mission.mission_type not in {"coverage", "exploration", "regression", "flake_triage", "mixed"}:
            summary["notes"].append(f"Unknown mission type '{mission.mission_type}' recorded without execution.")

        return summary


def _create_coverage_gap_artifacts(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
) -> dict[str, int]:
    summary = {"findings_created": 0, "approvals_created": 0, "test_proposals_created": 0}
    statement = (
        select(CoverageGap)
        .where(CoverageGap.resolved == False)  # noqa: E712
        .order_by(CoverageGap.created_at.desc())
        .limit(MAX_PROPOSALS_PER_ITERATION)
    )
    gaps = session.exec(statement).all()
    gaps = [gap for gap in gaps if _coverage_gap_matches_mission(gap, mission)]
    if not gaps:
        return summary

    for gap in gaps:
        raw_key = f"{mission.project_id}|coverage_gap|{gap.id}|{gap.description}|{gap.url or ''}"
        dedupe_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:32]
        finding = session.exec(
            select(AutonomousFinding).where(
                AutonomousFinding.project_id == mission.project_id,
                AutonomousFinding.dedupe_key == dedupe_key,
            )
        ).first()
        approval: AutonomousApproval | None = None
        now = _utcnow()
        if not finding:
            finding_id = f"amfind-{uuid.uuid4().hex[:12]}"
            title = gap.description[:120] if gap.description else "Autonomous coverage gap"
            evidence = {
                "coverage_gap_id": gap.id,
                "url": gap.url,
                "suggested_test": gap.suggested_test,
                "extra_data": gap.extra_data or {},
            }
            finding = AutonomousFinding(
                id=finding_id,
                mission_id=mission.id,
                run_id=run.id,
                project_id=mission.project_id,
                finding_type="coverage_gap",
                severity=gap.severity or "medium",
                title=title,
                description=gap.suggested_test or gap.description,
                status="awaiting_approval",
                confidence=0.72,
                dedupe_key=dedupe_key,
                evidence_json=json.dumps(evidence),
                source_type="coverage_gap",
                source_id=str(gap.id),
                approval_required=True,
                created_at=now,
                updated_at=now,
            )
            approval = AutonomousApproval(
                id=f"amappr-{uuid.uuid4().hex[:12]}",
                mission_id=mission.id,
                run_id=run.id,
                finding_id=finding_id,
                project_id=mission.project_id,
                action_type="persist_test",
                status="pending",
                requested_payload_json=json.dumps(
                    {
                        "finding_id": finding_id,
                        "action": "Review the generated test proposal for this coverage gap.",
                        "suggested_test": gap.suggested_test,
                        "approval_policy": mission.approval_policy,
                    }
                ),
                requested_at=now,
            )
            mission.total_findings += 1
            summary["findings_created"] += 1
            summary["approvals_created"] += 1
            session.add(finding)
            session.add(approval)

        proposal = _create_test_proposal(
            session,
            mission,
            run,
            source_type="coverage_gap",
            source_id=str(gap.id),
            title=gap.description or "Autonomous coverage gap",
            rationale=gap.suggested_test or gap.description,
            target_url=gap.url or _default_target_url(mission),
            risk_level=gap.severity or "medium",
            finding_id=finding.id if finding else None,
            coverage_gap_id=gap.id,
            approval_id=approval.id if approval else None,
            source_metadata={"gap_type": gap.gap_type, "extra_data": gap.extra_data or {}},
        )
        if proposal:
            summary["test_proposals_created"] += 1
            if approval:
                approval.requested_payload = {
                    **approval.requested_payload,
                    "proposal_id": proposal.id,
                    "suggested_file_path": proposal.suggested_file_path,
                    "test_type": proposal.test_type,
                }

    session.add(mission)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return {"findings_created": 0, "approvals_created": 0, "test_proposals_created": 0}
    return summary


def _create_proposals_for_approved_findings(session: Session, mission: AutonomousMission, run: AutonomousMissionRun) -> int:
    findings = session.exec(
        select(AutonomousFinding)
        .where(
            AutonomousFinding.project_id == mission.project_id,
            AutonomousFinding.status == "approved",
        )
        .order_by(col(AutonomousFinding.updated_at).desc())
        .limit(MAX_PROPOSALS_PER_ITERATION)
    ).all()
    created = 0
    for finding in findings:
        evidence = finding.evidence
        proposal = _create_test_proposal(
            session,
            mission,
            run,
            source_type="autonomous_finding",
            source_id=finding.id,
            title=finding.title,
            rationale=finding.description,
            target_url=str(evidence.get("url") or _default_target_url(mission)),
            risk_level=finding.severity or "medium",
            finding_id=finding.id,
            coverage_gap_id=_as_int(evidence.get("coverage_gap_id")),
            source_metadata={
                "finding_type": finding.finding_type,
                "confidence": finding.confidence,
                "evidence": evidence,
            },
        )
        if proposal:
            created += 1
    if created:
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return 0
    return created


def _create_test_proposal(
    session: Session,
    mission: AutonomousMission,
    run: AutonomousMissionRun,
    *,
    source_type: str,
    source_id: str,
    title: str,
    rationale: str | None,
    target_url: str | None,
    risk_level: str,
    finding_id: str | None = None,
    coverage_gap_id: int | None = None,
    approval_id: str | None = None,
    source_metadata: dict[str, Any] | None = None,
) -> AutonomousTestProposal | None:
    test_type = _infer_test_type(source_type, title, rationale or "", target_url)
    route = _route_from_url(target_url)
    proposal_key = f"{mission.project_id}|{source_type}|{source_id}|{test_type}|{target_url or route or ''}"
    dedupe_key = hashlib.sha256(proposal_key.encode("utf-8")).hexdigest()[:32]
    existing = session.exec(
        select(AutonomousTestProposal).where(
            AutonomousTestProposal.project_id == mission.project_id,
            AutonomousTestProposal.dedupe_key == dedupe_key,
        )
    ).first()
    if existing:
        return None

    safe_title = title[:140] if title else "Autonomous test proposal"
    suggested_file_path = _suggested_file_path(test_type, safe_title)
    generated_spec_content = _generate_spec_content(
        test_type=test_type,
        title=safe_title,
        rationale=rationale or safe_title,
        target_url=target_url or _default_target_url(mission),
        route=route,
    )
    now = _utcnow()
    proposal = AutonomousTestProposal(
        id=f"amprop-{uuid.uuid4().hex[:12]}",
        mission_id=mission.id,
        run_id=run.id,
        project_id=mission.project_id,
        finding_id=finding_id,
        coverage_gap_id=coverage_gap_id,
        approval_id=approval_id,
        title=safe_title,
        target_url=target_url,
        route=route,
        test_type=test_type,
        rationale=rationale or safe_title,
        generated_spec_content=generated_spec_content,
        suggested_file_path=suggested_file_path,
        risk_level=_normalize_risk(risk_level),
        approval_status="pending",
        dedupe_key=dedupe_key,
        source_type=source_type,
        source_id=source_id,
        source_metadata_json=json.dumps(source_metadata or {}),
        created_at=now,
        updated_at=now,
    )
    session.add(proposal)
    return proposal


def _infer_test_type(source_type: str, title: str, rationale: str, target_url: str | None) -> str:
    text = f"{source_type} {title} {rationale} {target_url or ''}".lower()
    if "accessibility" in text or "a11y" in text or "aria" in text:
        return "accessibility"
    if "security" in text or "xss" in text or "csrf" in text or "auth" in text:
        return "security"
    if "unit" in text:
        return "unit"
    if "/api/" in text or " endpoint" in text or "http " in text or "json" in text:
        return "api"
    if "regression" in text:
        return "regression"
    return "e2e"


def _generate_spec_content(*, test_type: str, title: str, rationale: str, target_url: str, route: str | None) -> str:
    if test_type in {"api", "unit"}:
        return _generate_pytest_content(title=title, rationale=rationale, target_url=target_url, route=route)
    return _generate_playwright_content(test_type=test_type, title=title, rationale=rationale, target_url=target_url)


def _generate_playwright_content(*, test_type: str, title: str, rationale: str, target_url: str) -> str:
    suite = _title_case(title)
    test_name = f"{test_type} coverage for {title}".strip()
    return f"""import {{ test, expect }} from '@playwright/test';

test.describe({json.dumps(suite)}, () => {{
  test({json.dumps(test_name)}, async ({{ page }}) => {{
    page.on('dialog', async dialog => {{
      await dialog.accept();
    }});

    const response = await page.goto({json.dumps(target_url)}, {{
      waitUntil: 'domcontentloaded',
      timeout: 60000,
    }});

    expect(response, 'navigation response should exist').not.toBeNull();
    expect(response!.status(), 'page should return a non-error HTTP status').toBeLessThan(500);

    await expect(page.locator('body')).toBeVisible();
    const bodyText = (await page.locator('body').innerText()).trim();
    expect(bodyText.length, {json.dumps(rationale[:120] or 'page should render visible content')}).toBeGreaterThan(0);
  }});
}});
"""


def _generate_pytest_content(*, title: str, rationale: str, target_url: str, route: str | None) -> str:
    parsed = urlparse(target_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "http://localhost:8000"
    route_path = route or parsed.path or "/"
    test_name = slugify(title).replace("-", "_") or "autonomous_api_proposal"
    if test_name[0].isdigit():
        test_name = f"autonomous_{test_name}"
    rationale_comment = _python_comment_block("Rationale", rationale)
    return f'''"""Generated autonomous test proposal."""

import os
from urllib import request as urllib_request

{rationale_comment}

def test_{test_name}_responds_successfully():
    base_url = os.environ.get("AUTONOMOUS_API_BASE_URL", {json.dumps(base_url)})
    url = base_url.rstrip("/") + {json.dumps(route_path)}

    with urllib_request.urlopen(url, timeout=30) as response:
        assert response.status < 500
'''


def _python_comment_block(label: str, value: str) -> str:
    lines = str(value or "").splitlines() or [""]
    safe_lines = [line.replace("\r", " ").replace("\t", " ") for line in lines]
    return "\n".join(f"# {label}: {line}" if index == 0 else f"# {line}" for index, line in enumerate(safe_lines))


def _suggested_file_path(test_type: str, title: str) -> str:
    slug = (slugify(title) or "autonomous-test")[:90].strip("-") or "autonomous-test"
    if test_type in {"api", "unit"}:
        return f"orchestrator/tests/generated/test_{slug.replace('-', '_')}.py"
    suffix = ".api.spec.ts" if test_type == "api" else ".spec.ts"
    return f"tests/generated/{slug}{suffix}"


def _route_from_url(target_url: str | None) -> str | None:
    if not target_url:
        return None
    parsed = urlparse(target_url)
    route = parsed.path or "/"
    return f"{route}?{parsed.query}" if parsed.query else route


def _coverage_gap_matches_mission(gap: CoverageGap, mission: AutonomousMission) -> bool:
    target_urls = mission.target_urls
    if not target_urls:
        return True
    if not gap.url:
        return False
    gap_parsed = urlparse(gap.url)
    if not gap_parsed.scheme or not gap_parsed.netloc:
        return False
    for target_url in target_urls:
        target_parsed = urlparse(target_url)
        if not target_parsed.scheme or not target_parsed.netloc:
            continue
        if gap_parsed.netloc != target_parsed.netloc:
            continue
        target_path = (target_parsed.path or "/").rstrip("/")
        gap_path = gap_parsed.path or "/"
        if target_path in {"", "/"} or gap_path == target_path or gap_path.startswith(f"{target_path}/"):
            return True
    return False


def _default_target_url(mission: AutonomousMission) -> str:
    return (mission.target_urls or ["http://localhost:3000"])[0]


def _normalize_risk(value: str | None) -> str:
    normalized = (value or "medium").lower()
    return normalized if normalized in {"critical", "high", "medium", "low", "info"} else "medium"


def _title_case(value: str) -> str:
    return " ".join(word.capitalize() for word in (slugify(value).replace("-", " ").split() or ["Autonomous", "Test"]))


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def complete_mission_run(payload: dict[str, Any]) -> None:
    run_id = payload["run_id"]
    summary = payload.get("summary") or {}
    with Session(engine) as session:
        run = session.get(AutonomousMissionRun, run_id)
        if not run:
            return
        now = _utcnow()
        run.status = "completed"
        run.current_stage = "completed"
        run.summary = summary
        run.completed_at = now
        run.updated_at = now
        mission = session.get(AutonomousMission, run.mission_id)
        if mission:
            mission.status = "running"
            mission.last_error = None
            mission.updated_at = now
            session.add(mission)
        session.add(run)
        session.commit()


def fail_mission_run(payload: dict[str, Any]) -> None:
    run_id = payload.get("run_id")
    mission_id = payload.get("mission_id")
    error = payload.get("error") or "Autonomous mission failed"
    with Session(engine) as session:
        now = _utcnow()
        if run_id:
            run = session.get(AutonomousMissionRun, run_id)
            if run:
                run.status = "failed"
                run.current_stage = "failed"
                run.error_message = error
                run.completed_at = now
                run.updated_at = now
                session.add(run)
        if mission_id:
            mission = session.get(AutonomousMission, mission_id)
            if mission:
                mission.status = "error"
                mission.last_error = error
                mission.updated_at = now
                session.add(mission)
        session.commit()


def update_mission_status(payload: dict[str, Any]) -> None:
    mission_id = payload["mission_id"]
    status = payload["status"]
    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        if not mission:
            return
        mission.status = status
        mission.updated_at = _utcnow()
        session.add(mission)
        session.commit()


def compute_next_delay_seconds(mission_id: str) -> int:
    """Return the delay before the next mission iteration."""
    with Session(engine) as session:
        mission = session.get(AutonomousMission, mission_id)
        if not mission:
            return 0
        if not mission.schedule_cron:
            return 24 * 60 * 60
        try:
            from orchestrator.services.scheduler import get_next_n_run_times

            next_runs = get_next_n_run_times(mission.schedule_cron, mission.timezone, count=1)
            if not next_runs:
                return 24 * 60 * 60
            next_run = next_runs[0]
            now = datetime.now(timezone.utc)
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=timezone.utc)
            mission.next_run_at = next_run.replace(tzinfo=None)
            mission.updated_at = _utcnow()
            session.add(mission)
            session.commit()
            return max(1, int((next_run - now).total_seconds()))
        except Exception as exc:
            logger.warning("Failed to compute next autonomous mission delay for %s: %s", mission_id, exc)
            return 24 * 60 * 60
