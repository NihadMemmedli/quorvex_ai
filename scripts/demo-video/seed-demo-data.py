#!/usr/bin/env python3
"""Seed a polished, repeatable local project for the demo-video workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import sys
import zlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlmodel import Session, select

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / ".env.prod", override=False)
except Exception:
    pass

from orchestrator.api.db import engine  # noqa: E402
from orchestrator.api.models_auth import ProjectMember, RefreshToken, User  # noqa: E402
from orchestrator.api.models_db import (  # noqa: E402
    AgentDefinition,
    AgentRun,
    AutoPilotPhase,
    AutoPilotQuestion,
    AutoPilotSession,
    AutonomousAgentEvent,
    AutonomousAgentWorkItem,
    AutonomousApproval,
    AutonomousFinding,
    AutonomousMission,
    AutonomousMissionRun,
    AutonomousTestProposal,
    BrowserElement,
    BrowserFrontierItem,
    BrowserPageState,
    BrowserStateCluster,
    BrowserTransition,
    CoverageMetric,
    DiscoveredApiEndpoint,
    DiscoveredElement,
    DiscoveredFlow,
    DiscoveredFlowReview,
    ExplorationSession,
    FlowStep,
    Project,
    RegressionBatch,
    Requirement,
    RequirementSource,
    RtmEntry,
    RtmSnapshot,
    SpecMetadata,
    TestRun,
)
from orchestrator.api.security import create_refresh_token  # noqa: E402

DEMO_PROJECT_ID = "quorvex-demo"
DEMO_PROJECT_NAME = "Quorvex Demo"
DEMO_EMAIL = "quorvex.demo+video@example.com"
DEMO_USER_ID = "demo-video-user"
DEMO_PREFIX = "demo-video"


def utcnow() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def clean_project(session: Session, project_id: str) -> None:
    run_ids = session.exec(select(TestRun.id).where(TestRun.project_id == project_id)).all()
    session_ids = session.exec(select(ExplorationSession.id).where(ExplorationSession.project_id == project_id)).all()
    flow_ids = session.exec(select(DiscoveredFlow.id).where(DiscoveredFlow.project_id == project_id)).all()
    req_ids = session.exec(select(Requirement.id).where(Requirement.project_id == project_id)).all()
    autopilot_ids = session.exec(select(AutoPilotSession.id).where(AutoPilotSession.project_id == project_id)).all()
    conv_ids = session.exec(
        select(ChatConversation.id).where(ChatConversation.project_id == project_id)  # type: ignore[name-defined]
    ).all()

    if conv_ids:
        session.exec(delete(ChatMessage).where(ChatMessage.conversation_id.in_(conv_ids)))  # type: ignore[name-defined]
        session.exec(delete(ChatConversation).where(ChatConversation.id.in_(conv_ids)))  # type: ignore[name-defined]

    if autopilot_ids:
        session.exec(delete(AutoPilotQuestion).where(AutoPilotQuestion.session_id.in_(autopilot_ids)))
        session.exec(delete(AutoPilotPhase).where(AutoPilotPhase.session_id.in_(autopilot_ids)))
    session.exec(delete(AutoPilotSession).where(AutoPilotSession.project_id == project_id))

    session.exec(delete(AutonomousTestProposal).where(AutonomousTestProposal.project_id == project_id))
    session.exec(delete(AutonomousApproval).where(AutonomousApproval.project_id == project_id))
    session.exec(delete(AutonomousFinding).where(AutonomousFinding.project_id == project_id))
    session.exec(delete(AutonomousAgentEvent).where(AutonomousAgentEvent.project_id == project_id))
    session.exec(delete(AutonomousAgentWorkItem).where(AutonomousAgentWorkItem.project_id == project_id))
    session.exec(delete(AutonomousMissionRun).where(AutonomousMissionRun.project_id == project_id))
    session.exec(delete(AutonomousMission).where(AutonomousMission.project_id == project_id))

    session.exec(delete(AgentRun).where(AgentRun.project_id == project_id))
    session.exec(delete(AgentDefinition).where(AgentDefinition.project_id == project_id))

    if run_ids:
        session.exec(delete(CoverageMetric).where(CoverageMetric.run_id.in_(run_ids)))
    session.exec(delete(TestRun).where(TestRun.project_id == project_id))
    session.exec(delete(RegressionBatch).where(RegressionBatch.project_id == project_id))

    if flow_ids:
        session.exec(delete(FlowStep).where(FlowStep.flow_id.in_(flow_ids)))
        session.exec(delete(DiscoveredFlowReview).where(DiscoveredFlowReview.flow_id.in_(flow_ids)))
    if session_ids:
        session.exec(delete(DiscoveredApiEndpoint).where(DiscoveredApiEndpoint.session_id.in_(session_ids)))
    session.exec(delete(DiscoveredFlow).where(DiscoveredFlow.project_id == project_id))
    session.exec(delete(ExplorationSession).where(ExplorationSession.project_id == project_id))

    if req_ids:
        session.exec(delete(RequirementSource).where(RequirementSource.requirement_id.in_(req_ids)))
    session.exec(delete(RtmEntry).where(RtmEntry.project_id == project_id))
    session.exec(delete(RtmSnapshot).where(RtmSnapshot.project_id == project_id))
    session.exec(delete(Requirement).where(Requirement.project_id == project_id))

    session.exec(delete(BrowserTransition).where(BrowserTransition.project_id == project_id))
    session.exec(delete(BrowserFrontierItem).where(BrowserFrontierItem.project_id == project_id))
    session.exec(delete(BrowserElement).where(BrowserElement.project_id == project_id))
    session.exec(delete(BrowserStateCluster).where(BrowserStateCluster.project_id == project_id))
    session.exec(delete(BrowserPageState).where(BrowserPageState.project_id == project_id))

    session.exec(delete(DiscoveredElement).where(DiscoveredElement.url.contains("demo.quorvex.local")))
    session.exec(delete(SpecMetadata).where(SpecMetadata.project_id == project_id))


# Chat imports are intentionally late so the model registry is already initialized.
from orchestrator.api.models_db import ChatConversation, ChatMessage  # noqa: E402


def upsert_project_and_user(session: Session) -> User:
    project = session.get(Project, DEMO_PROJECT_ID)
    if not project:
        project = Project(id=DEMO_PROJECT_ID, name=DEMO_PROJECT_NAME)
    project.name = DEMO_PROJECT_NAME
    project.base_url = "https://demo.quorvex.local"
    project.description = "Synthetic marketing demo project with healthy QA automation data."
    project.settings = {"demo": True, "seeded_by": "scripts/demo-video/seed-demo-data.py"}
    project.last_active = utcnow()
    session.add(project)

    user = session.exec(select(User).where(User.email == DEMO_EMAIL)).first()
    if not user:
        user = session.get(User, DEMO_USER_ID)
    if not user:
        user = User(
            id=DEMO_USER_ID,
            email=DEMO_EMAIL,
            password_hash="demo-refresh-token-auth",
            full_name="Quorvex Demo",
        )
    user.email = DEMO_EMAIL
    user.full_name = "Quorvex Demo"
    user.is_active = True
    user.is_superuser = True
    user.email_verified = True
    user.updated_at = utcnow()
    session.add(user)

    member = session.exec(
        select(ProjectMember).where(ProjectMember.project_id == DEMO_PROJECT_ID).where(ProjectMember.user_id == user.id)
    ).first()
    if not member:
        member = ProjectMember(project_id=DEMO_PROJECT_ID, user_id=user.id, role="admin", granted_by=user.id)
    member.role = "admin"
    session.add(member)
    return user


def write_auth_token(session: Session, user: User, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    token_id = f"{DEMO_PREFIX}-{secrets.token_hex(8)}"
    refresh_token = create_refresh_token(user.id, token_id)
    db_token = RefreshToken(
        id=token_id,
        user_id=user.id,
        token_hash=hashlib.sha256(refresh_token.encode()).hexdigest(),
        device_info="demo-video-recorder",
        expires_at=utcnow() + timedelta(days=7),
    )
    session.add(db_token)
    payload = {
        "email": user.email,
        "project_id": DEMO_PROJECT_ID,
        "project_name": DEMO_PROJECT_NAME,
        "refresh_token": refresh_token,
        "conversation_id": "demo-chat-custom-agent",
        "agent_run_id": "demo-agent-checkout-risk-scout",
        "exploration_run_id": "demo-agent-live-browser-preview",
    }
    (output_dir / "demo-auth.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def seed_specs(session: Session) -> list[str]:
    spec_dir = PROJECT_ROOT / "specs" / "demo-marketing"
    spec_dir.mkdir(parents=True, exist_ok=True)
    names = [
        "checkout-happy-path",
        "checkout-validation-states",
        "login-session-recovery",
        "role-based-dashboard-access",
        "catalog-search-and-filters",
        "cart-price-consistency",
        "payment-decline-recovery",
        "order-confirmation-email",
        "admin-reporting-export",
        "settings-permission-boundaries",
        "api-contract-products",
        "api-contract-orders",
        "mobile-checkout-smoke",
        "accessibility-critical-path",
        "security-auth-cookie-policy",
        "database-order-integrity",
        "load-checkout-peak-hour",
        "llm-support-response-grounding",
        "rtm-coverage-regression",
        "autonomous-agent-mission-health",
        "browser-memory-navigation",
        "ci-pr-impact-selection",
        "regression-suite-nightly",
        "requirements-gap-review",
        "live-browser-observability",
        "custom-agent-creation",
        "assistant-run-summary",
        "multi-project-isolation",
        "recording-to-spec",
        "template-reuse",
        "healing-selector-drift",
        "release-readiness-gate",
    ]
    spec_names: list[str] = []
    for index, slug in enumerate(names, start=1):
        rel = f"demo-marketing/{index:02d}-{slug}.md"
        spec_names.append(rel)
        path = PROJECT_ROOT / "specs" / rel
        title = slug.replace("-", " ").title()
        path.write_text(
            f"# {title}\n\n"
            f"Synthetic demo requirement coverage for {title.lower()}.\n\n"
            "## Acceptance Criteria\n\n"
            "- The core user journey completes without console or network errors.\n"
            "- The generated Playwright test uses resilient semantic selectors.\n"
            "- The run emits artifacts that can be reviewed by QA and engineering.\n",
            encoding="utf-8",
        )
        meta = SpecMetadata(
            spec_name=rel,
            project_id=DEMO_PROJECT_ID,
            description=f"Demo spec for {title.lower()}",
            author="Quorvex AI",
            last_modified=utcnow(),
        )
        meta.tags = ["demo", "ai-generated", "playwright"]
        session.add(meta)
    return spec_names


def seed_runs(session: Session, spec_names: list[str]) -> None:
    runs_root = PROJECT_ROOT / "runs"
    runs_root.mkdir(exist_ok=True)
    now = utcnow()
    batch_defs = [
        ("demo-batch-release-readiness", "Release readiness gate", 16, 16, 0, 6),
        ("demo-batch-autonomous-nightly", "Autonomous nightly coverage", 16, 16, 0, 4),
        ("demo-batch-pr-impact", "PR impact smoke suite", 16, 16, 0, 2),
    ]
    run_index = 0
    for batch_id, name, total, passed, failed, days_ago in batch_defs:
        started = now - timedelta(days=days_ago, hours=2)
        completed = started + timedelta(minutes=18)
        batch = RegressionBatch(
            id=batch_id,
            project_id=DEMO_PROJECT_ID,
            name=name,
            triggered_by="Quorvex AI",
            created_at=started,
            started_at=started,
            completed_at=completed,
            browser="chromium",
            total_tests=total,
            passed=passed,
            failed=failed,
            stopped=0,
            running=0,
            queued=0,
            status="completed",
            actual_total_tests=total,
            actual_passed=passed,
            actual_failed=failed,
        )
        batch.tags_used = ["demo", "critical-path"]
        session.add(batch)

        for offset in range(total):
            run_index += 1
            spec_name = spec_names[(run_index - 1) % len(spec_names)]
            run_started = started + timedelta(minutes=offset)
            run_completed = run_started + timedelta(seconds=42 + (offset % 5) * 11)
            status = "failed" if offset >= passed else "passed"
            run_id = f"{run_started:%Y-%m-%d_%H-%M-%S}_demo-{run_index:02d}"
            error_message = None
            if status == "failed":
                error_message = "Expected checkout confirmation copy to match approved release wording."
            run = TestRun(
                id=run_id,
                project_id=DEMO_PROJECT_ID,
                batch_id=batch_id,
                spec_name=spec_name,
                test_name=spec_name.replace("demo-marketing/", "").replace(".md", ""),
                status=status,
                browser="chromium",
                created_at=run_started,
                started_at=run_started,
                completed_at=run_completed,
                steps_completed=8 if status == "passed" else 7,
                total_steps=8,
                current_stage="completed",
                stage_message="Validated in Chromium with artifacts captured.",
                test_type="browser",
                error_message=error_message,
                agentic_summary={
                    "planner": "Generated resilient browser steps from requirement context.",
                    "validator": "Captured screenshots, console output, and network checks.",
                    "risk": "low" if status == "passed" else "review",
                },
            )
            session.add(run)
            run_dir = runs_root / run_id
            if run_dir.exists():
                shutil.rmtree(run_dir)
            run_dir.mkdir(parents=True)
            duration = int((run_completed - run_started).total_seconds())
            run_data = {
                "id": run_id,
                "testName": run.test_name,
                "specName": spec_name,
                "finalState": status,
                "duration": duration,
                "batch_id": batch_id,
                "steps": [
                    {"title": "Open target flow", "status": "passed"},
                    {"title": "Exercise business-critical path", "status": "passed"},
                    {"title": "Assert visible confirmation", "status": status, **({"error": error_message} if error_message else {})},
                ],
            }
            (run_dir / "run.json").write_text(json.dumps(run_data, indent=2), encoding="utf-8")
            validation = {"status": "success" if status == "passed" else "failed", "iterations": 0}
            if error_message:
                validation["error"] = error_message
            (run_dir / "validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")


def seed_exploration(session: Session) -> None:
    now = utcnow()
    sessions = [
        ("demo-explore-checkout", "https://demo.quorvex.local/checkout", 27, 8, 84, 12, 0, now - timedelta(hours=18)),
        ("demo-explore-admin", "https://demo.quorvex.local/admin", 19, 6, 61, 9, 1, now - timedelta(days=1, hours=3)),
        ("demo-explore-api", "https://demo.quorvex.local/api", 14, 4, 33, 16, 0, now - timedelta(days=2)),
    ]
    for session_id, url, pages, flows, elements, apis, issues, created in sessions:
        exp = ExplorationSession(
            id=session_id,
            project_id=DEMO_PROJECT_ID,
            entry_url=url,
            status="completed",
            strategy="goal_directed",
            started_at=created,
            completed_at=created + timedelta(minutes=14),
            pages_discovered=pages,
            flows_discovered=flows,
            elements_discovered=elements,
            api_endpoints_discovered=apis,
            issues_discovered=issues,
            created_at=created,
            progress_data=dumps({"stage": "completed", "message": "Exploration completed and converted into requirements."}),
        )
        exp.config = {"goal": "Map critical product flows for demo project", "demo": True}
        session.add(exp)
    session.flush()

    flow_specs = [
        ("Checkout from cart to confirmation", "checkout", "https://demo.quorvex.local/cart", "https://demo.quorvex.local/orders/confirmed", 7),
        ("Recover payment decline with saved cart", "checkout", "https://demo.quorvex.local/payment", "https://demo.quorvex.local/payment/retry", 6),
        ("Admin exports quality report", "reporting", "https://demo.quorvex.local/admin/reports", "https://demo.quorvex.local/admin/reports/export", 5),
        ("Assistant creates custom QA agent", "assistant", "https://demo.quorvex.local/assistant", "https://demo.quorvex.local/agents", 4),
        ("RTM gap review to generated test", "requirements", "https://demo.quorvex.local/rtm", "https://demo.quorvex.local/specs", 6),
        ("Live browser trace review", "observability", "https://demo.quorvex.local/agents", "https://demo.quorvex.local/runs/demo", 5),
    ]
    for idx, (name, category, start_url, end_url, steps) in enumerate(flow_specs, start=1):
        flow = DiscoveredFlow(
            session_id="demo-explore-checkout" if idx <= 4 else "demo-explore-admin",
            project_id=DEMO_PROJECT_ID,
            flow_name=name,
            flow_category=category,
            description=f"Autonomous agent discovered and validated the {name.lower()} journey.",
            start_url=start_url,
            end_url=end_url,
            step_count=steps,
            is_success_path=True,
            created_at=now - timedelta(hours=18, minutes=idx),
        )
        flow.preconditions = ["Authenticated demo account", "Seeded checkout data"]
        flow.postconditions = ["Expected state visible", "Network responses within policy"]
        session.add(flow)
        session.flush()
        for step in range(1, steps + 1):
            session.add(
                FlowStep(
                    flow_id=flow.id,
                    step_number=step,
                    action_type="click" if step % 2 else "verify",
                    action_description=f"Step {step}: validate {name.lower()} state",
                    element_role="button" if step % 2 else "heading",
                    element_name="Continue" if step % 2 else "Confirmation",
                )
            )
    for idx in range(1, 13):
        session.add(
            DiscoveredApiEndpoint(
                session_id="demo-explore-api",
                project_id=DEMO_PROJECT_ID,
                method="GET" if idx % 3 else "POST",
                url=f"https://demo.quorvex.local/api/v1/demo-endpoint-{idx}",
                response_status=200 if idx != 11 else 202,
                triggered_by_action="Browser agent observed network call during critical flow.",
                first_seen=now - timedelta(days=1, minutes=idx),
                call_count=idx + 2,
            )
        )


def seed_requirements_and_rtm(session: Session, spec_names: list[str]) -> None:
    now = utcnow()
    req_defs = [
        ("REQ-001", "Checkout completes from cart to confirmation", "checkout", "critical"),
        ("REQ-002", "Payment decline keeps cart recoverable", "checkout", "high"),
        ("REQ-003", "Login session recovers after refresh", "authentication", "high"),
        ("REQ-004", "Admin dashboard respects role access", "authorization", "critical"),
        ("REQ-005", "Catalog filters update results without reload", "navigation", "medium"),
        ("REQ-006", "Cart total remains consistent across API and UI", "data_integrity", "high"),
        ("REQ-007", "Order confirmation email is queued", "integration", "medium"),
        ("REQ-008", "Report export preserves selected filters", "reporting", "medium"),
        ("REQ-009", "Settings changes require editor permissions", "authorization", "high"),
        ("REQ-010", "Product API contract matches OpenAPI", "api", "high"),
        ("REQ-011", "Orders API returns traceable validation errors", "api", "high"),
        ("REQ-012", "Mobile checkout keeps primary actions visible", "mobile", "medium"),
        ("REQ-013", "Critical pages meet accessibility baseline", "accessibility", "high"),
        ("REQ-014", "Auth cookies use secure production policy", "security", "critical"),
        ("REQ-015", "Order database rows maintain referential integrity", "database", "high"),
        ("REQ-016", "Checkout handles peak-hour load budget", "performance", "medium"),
        ("REQ-017", "LLM support responses cite project context", "llm", "medium"),
        ("REQ-018", "RTM shows requirement-to-test lineage", "traceability", "high"),
        ("REQ-019", "Autonomous missions expose healthy progress", "autonomous", "high"),
        ("REQ-020", "Browser memory reuses stable navigation states", "memory", "medium"),
        ("REQ-021", "PR impact selects affected tests only", "ci", "medium"),
        ("REQ-022", "Nightly regression suite summarizes risk", "regression", "high"),
        ("REQ-023", "Live browser preview is available for agent work", "observability", "medium"),
        ("REQ-024", "Assistant can create custom agents from chat", "assistant", "critical"),
    ]
    req_ids: list[int] = []
    for idx, (code, title, category, priority) in enumerate(req_defs):
        req = Requirement(
            project_id=DEMO_PROJECT_ID,
            req_code=code,
            title=title,
            description=f"Demo requirement: {title}.",
            category=category,
            priority=priority,
            status="tested" if idx < 22 else "approved",
            truth_state="confirmed",
            source_type="autonomous_exploration",
            confidence=0.93 if idx < 20 else 0.82,
            confirmed_by="Quorvex AI",
            confirmed_at=now - timedelta(days=2),
            created_at=now - timedelta(days=6, minutes=idx),
            updated_at=now - timedelta(hours=6, minutes=idx),
        )
        req.acceptance_criteria = [
            "The behavior is covered by at least one generated Playwright or API test.",
            "Artifacts include enough evidence for a reviewer to approve the result.",
        ]
        session.add(req)
        session.flush()
        req_ids.append(req.id)

        if idx < 22:
            session.add(
                RtmEntry(
                    project_id=DEMO_PROJECT_ID,
                    requirement_id=req.id,
                    test_spec_name=spec_names[idx % len(spec_names)],
                    test_spec_path=f"specs/{spec_names[idx % len(spec_names)]}",
                    mapping_type="full",
                    confidence=0.91,
                    coverage_notes="Validated by autonomous browser run and regression batch.",
                )
            )
        elif idx == 22:
            session.add(
                RtmEntry(
                    project_id=DEMO_PROJECT_ID,
                    requirement_id=req.id,
                    test_spec_name=spec_names[idx % len(spec_names)],
                    test_spec_path=f"specs/{spec_names[idx % len(spec_names)]}",
                    mapping_type="partial",
                    confidence=0.76,
                    coverage_notes="Happy path covered; edge-case preview remains in review.",
                    gap_notes="Add one more browser-state assertion after live preview fallback.",
                )
            )

    snapshots = [
        ("Initial agent pass", 24, 17, 3, 4, now - timedelta(days=6)),
        ("RTM after spec generation", 24, 20, 2, 2, now - timedelta(days=3)),
        ("Demo release readiness", 24, 22, 1, 1, now - timedelta(hours=5)),
    ]
    for name, total, covered, partial, uncovered, created in snapshots:
        snap = RtmSnapshot(
            project_id=DEMO_PROJECT_ID,
            snapshot_name=name,
            total_requirements=total,
            covered_requirements=covered,
            partial_requirements=partial,
            uncovered_requirements=uncovered,
            coverage_percentage=round((covered / total) * 100, 1),
            created_at=created,
        )
        snap.snapshot_data = {"demo": True, "source": "autonomous_agents"}
        session.add(snap)


def seed_autopilot(session: Session) -> None:
    now = utcnow()
    active = AutoPilotSession(
        id="demo-autopilot-live-review",
        project_id=DEMO_PROJECT_ID,
        status="paused",
        current_phase="test_generation",
        current_phase_progress=68,
        overall_progress=72,
        total_pages_discovered=27,
        total_flows_discovered=8,
        total_requirements_generated=24,
        total_specs_generated=18,
        total_tests_generated=46,
        total_tests_passed=46,
        total_tests_failed=0,
        coverage_percentage=91.7,
        started_at=now - timedelta(minutes=38),
        created_at=now - timedelta(minutes=42),
        instructions="Keep checkout, RTM, and assistant-created custom agents ready for demo review.",
        triggered_by="AI Assistant",
    )
    active.entry_urls = ["https://demo.quorvex.local/checkout", "https://demo.quorvex.local/assistant"]
    active.phases_completed = ["exploration", "requirements"]
    active.exploration_session_ids = ["demo-explore-checkout"]
    active.config = {
        "live_browser": {
            "active": True,
            "agent_task_id": "demo-agent-live-browser-preview",
            "activity_label": "Reviewing checkout browser state",
            "message": "Paused at reviewer checkpoint with browser context captured.",
            "status": "paused",
        }
    }
    session.add(active)

    completed = AutoPilotSession(
        id="demo-autopilot-release-readiness",
        project_id=DEMO_PROJECT_ID,
        status="completed",
        current_phase="reporting",
        current_phase_progress=100,
        overall_progress=100,
        total_pages_discovered=31,
        total_flows_discovered=10,
        total_requirements_generated=24,
        total_specs_generated=32,
        total_tests_generated=48,
        total_tests_passed=48,
        total_tests_failed=0,
        coverage_percentage=91.7,
        started_at=now - timedelta(days=1, hours=3),
        completed_at=now - timedelta(days=1, hours=2, minutes=37),
        created_at=now - timedelta(days=1, hours=3, minutes=5),
        instructions="Run release readiness checks for checkout and admin reporting.",
        triggered_by="scheduled_mission",
    )
    completed.entry_urls = ["https://demo.quorvex.local"]
    completed.phases_completed = ["exploration", "requirements", "spec_generation", "test_generation", "reporting"]
    completed.exploration_session_ids = ["demo-explore-checkout", "demo-explore-admin"]
    completed.config = {"demo": True}
    session.add(completed)
    session.flush()

    for session_id in [active.id, completed.id]:
        for order, phase_name in enumerate(["exploration", "requirements", "spec_generation", "test_generation", "reporting"], start=1):
            status = "completed"
            progress = 100.0
            completed_at = now - timedelta(minutes=50 - order * 5)
            if session_id == active.id and phase_name in {"test_generation", "reporting"}:
                status = "paused" if phase_name == "test_generation" else "pending"
                progress = 68.0 if phase_name == "test_generation" else 0.0
                completed_at = None
            phase = AutoPilotPhase(
                session_id=session_id,
                phase_name=phase_name,
                phase_order=order,
                status=status,
                progress=progress,
                current_step="Waiting for reviewer to approve generated custom-agent specs." if status == "paused" else "Completed",
                items_total=10,
                items_completed=10 if status == "completed" else 7,
                started_at=now - timedelta(minutes=65 - order * 5),
                completed_at=completed_at,
            )
            phase.result_summary = {"demo": True, "phase": phase_name}
            session.add(phase)


def seed_autonomous(session: Session, user_id: str) -> None:
    now = utcnow()
    mission = AutonomousMission(
        id="demo-mission-checkout-guardian",
        project_id=DEMO_PROJECT_ID,
        name="Checkout Coverage Guardian",
        description="Continuously explores checkout, RTM gaps, and release readiness.",
        mission_type="mixed",
        status="running",
        timezone="UTC",
        autonomy_level="draft_validate",
        approval_policy="approval_required",
        max_runtime_minutes=45,
        max_llm_budget_usd=25.0,
        budget_used_usd=9.13,
        latest_run_id="demo-mission-run-1",
        last_run_at=now - timedelta(minutes=18),
        next_run_at=now + timedelta(hours=6),
        health_status="healthy",
        last_heartbeat_at=now - timedelta(minutes=3),
        current_stage="Browser exploration",
        next_action="Review one generated edge-case proposal",
        total_runs=14,
        total_findings=4,
        created_by=user_id,
        created_at=now - timedelta(days=7),
        updated_at=now - timedelta(minutes=3),
    )
    mission.target_urls = ["https://demo.quorvex.local/checkout", "https://demo.quorvex.local/rtm"]
    mission.config = {"demo": True, "focus": ["checkout", "assistant", "rtm"]}
    session.add(mission)
    session.flush()

    run = AutonomousMissionRun(
        id="demo-mission-run-1",
        mission_id=mission.id,
        project_id=DEMO_PROJECT_ID,
        mission_type="mixed",
        trigger_type="schedule",
        status="running",
        current_stage="Coordinating browser and RTM agents",
        budget_used_usd=0.74,
        started_at=now - timedelta(minutes=18),
        created_at=now - timedelta(minutes=18),
        updated_at=now - timedelta(minutes=3),
    )
    run.summary = {"agents": 5, "flows_reviewed": 8, "risk": "low"}
    session.add(run)
    session.flush()

    work_items = [
        ("demo-work-browser", "surface_mapper", "Map checkout browser states and screenshot evidence", "running", 90),
        ("demo-work-rtm", "rtm_mapper", "Link latest requirements to generated specs", "completed", 80),
        ("demo-work-regression", "regression_scout", "Run release-readiness smoke batch", "completed", 70),
        ("demo-work-spec", "spec_writer", "Draft edge-case Playwright test for live preview fallback", "completed", 65),
        ("demo-work-flake", "flake_triager", "Confirm no new flaky behavior in checkout suite", "completed", 50),
    ]
    for idx, (item_id, role, objective, status, priority) in enumerate(work_items, start=1):
        item = AutonomousAgentWorkItem(
            id=item_id,
            mission_id=mission.id,
            run_id=run.id,
            project_id=DEMO_PROJECT_ID,
            role=role,
            objective=objective,
            status=status,
            priority=priority,
            progress_json=dumps({"percent": 68 if status == "running" else 100, "message": objective}),
            result_json=dumps({"summary": objective, "risk": "low", "demo": True}),
            started_at=now - timedelta(minutes=18 - idx),
            completed_at=None if status == "running" else now - timedelta(minutes=10 - idx),
            created_at=now - timedelta(minutes=20 - idx),
            updated_at=now - timedelta(minutes=idx),
        )
        item.assigned_surface = ["checkout", "rtm", "assistant"] if idx == 1 else ["checkout"]
        session.add(item)
        session.flush()
        session.add(
            AutonomousAgentEvent(
                id=f"demo-event-{idx}",
                project_id=DEMO_PROJECT_ID,
                mission_id=mission.id,
                run_id=run.id,
                work_item_id=item_id,
                sequence=idx,
                event_type="browser_action" if idx == 1 else "assistant_output",
                level="info",
                message=objective,
                payload_json=dumps({"demo": True, "status": status}),
                created_at=now - timedelta(minutes=18 - idx),
            )
        )

    finding = AutonomousFinding(
        id="demo-finding-live-preview-gap",
        mission_id=mission.id,
        run_id=run.id,
        project_id=DEMO_PROJECT_ID,
        finding_type="coverage_gap",
        severity="medium",
        title="Live browser fallback needs an edge-case assertion",
        description="The browser-preview fallback is covered for normal agent runs; add one assertion for the unavailable-VNC path.",
        status="awaiting_approval",
        confidence=0.86,
        dedupe_key="demo-live-browser-fallback-gap",
        source_type="work_item",
        source_id="demo-work-spec",
        approval_required=True,
        created_at=now - timedelta(minutes=12),
        updated_at=now - timedelta(minutes=10),
    )
    finding.evidence = {"page": "/agents", "requirement": "REQ-023", "impact": "medium"}
    session.add(finding)
    session.flush()

    approval = AutonomousApproval(
        id="demo-approval-live-preview-test",
        mission_id=mission.id,
        run_id=run.id,
        finding_id=finding.id,
        project_id=DEMO_PROJECT_ID,
        action_type="persist_test",
        status="pending",
        requested_at=now - timedelta(minutes=9),
    )
    approval.requested_payload = {"suggested_file_path": "tests/generated/live-browser-preview.spec.ts", "risk": "medium"}
    session.add(approval)
    session.flush()

    proposal = AutonomousTestProposal(
        id="demo-proposal-live-preview-test",
        mission_id=mission.id,
        run_id=run.id,
        project_id=DEMO_PROJECT_ID,
        finding_id=finding.id,
        approval_id=approval.id,
        title="Live browser preview fallback stays reviewable",
        target_url="https://demo.quorvex.local/agents",
        route="/agents",
        test_type="e2e",
        rationale="Protects the demo-critical browser-observability path even when VNC is unavailable.",
        generated_spec_content="test('live browser preview fallback is reviewable', async ({ page }) => { /* demo */ });",
        suggested_file_path="tests/generated/live-browser-preview.spec.ts",
        risk_level="medium",
        approval_status="pending",
        dedupe_key="demo-live-browser-preview-proposal",
        source_type="autonomous_finding",
        source_id=finding.id,
        created_at=now - timedelta(minutes=8),
        updated_at=now - timedelta(minutes=8),
    )
    proposal.source_metadata = {"requirement": "REQ-023", "demo": True}
    session.add(proposal)


def seed_agents_and_chat(session: Session, user_id: str) -> None:
    now = utcnow()
    tools = [
        "browser_navigate",
        "browser_snapshot",
        "browser_take_screenshot",
        "getRTMMatrix",
        "getDashboardStats",
        "createCustomAgentDefinition",
        "startAdhocCustomAgent",
        "listAgentRuns",
        "getAgentRunReport",
        "createRTMEntry",
    ]
    definition = AgentDefinition(
        id="demo-agent-def-checkout-risk-scout",
        project_id=DEMO_PROJECT_ID,
        name="Checkout Risk Scout",
        description="Assistant-created custom agent for checkout, RTM, and browser evidence.",
        system_prompt=(
            "Inspect checkout and RTM coverage. Use browser evidence, summarize risk, "
            "and propose tests only when a human approval gate is appropriate."
        ),
        model="gpt-5.4-mini",
        timeout_seconds=900,
        status="active",
        created_at=now - timedelta(hours=2),
        updated_at=now - timedelta(hours=1, minutes=40),
    )
    definition.tool_ids = tools
    session.add(definition)

    structured_report = {
        "summary": "Checkout Risk Scout reviewed the checkout flow, RTM links, and browser evidence. The suite is release-ready with one medium-risk preview fallback test awaiting approval.",
        "scope": "Checkout, RTM, live browser preview, and assistant-created custom-agent workflow.",
        "pages_checked": [
            {"url": "https://demo.quorvex.local/checkout", "status": "Passed", "notes": "Primary checkout path completed."},
            {"url": "https://demo.quorvex.local/rtm", "status": "Passed", "notes": "22 of 24 requirements fully covered."},
            {"url": "https://demo.quorvex.local/agents", "status": "Review", "notes": "Fallback path has one proposed test."},
        ],
        "findings": [
            {
                "id": "F-001",
                "title": "Add unavailable-VNC fallback assertion",
                "severity": "medium",
                "confidence": "high",
                "details": "The browser preview remains reviewable, but the fallback state should be guarded by an explicit test.",
            }
        ],
        "test_ideas": [
            {
                "id": "T-001",
                "title": "Live browser preview fallback is reviewable",
                "priority": "medium",
                "rationale": "Protects the demo-critical observability story.",
            }
        ],
        "evidence": [
            {"type": "screenshot", "label": "Checkout browser preview", "path": "/artifacts/demo-agent-checkout-risk-scout/artifacts/browser-preview.png"},
            {"type": "rtm", "label": "REQ-023 partial coverage", "path": "/rtm"},
        ],
        "follow_up_actions": ["Approve generated fallback test", "Keep mission running on six-hour cadence"],
        "parse_status": "structured",
    }
    run = AgentRun(
        id="demo-agent-checkout-risk-scout",
        project_id=DEMO_PROJECT_ID,
        agent_type="custom",
        status="completed",
        created_at=now - timedelta(hours=1, minutes=35),
        config_json=dumps(
            {
                "agent_name": "Checkout Risk Scout",
                "definition_id": definition.id,
                "url": "https://demo.quorvex.local/checkout",
                "prompt": "Inspect checkout, RTM, and live browser preview readiness for release.",
                "selected_tools": [{"tool_name": "mcp__playwright__browser_snapshot"}, {"tool_name": "getRTMMatrix"}],
                "timeout_seconds": 900,
            }
        ),
        progress_json=dumps(
            {
                "phase": "completed",
                "tool_calls": 14,
                "browser_tool_calls": 5,
                "last_tool_label": "RTM coverage",
                "has_browser_tools": True,
                "recent_tools": [
                    {"name": "browser_navigate", "label": "Open checkout", "at": (now - timedelta(hours=1, minutes=32)).isoformat()},
                    {"name": "browser_take_screenshot", "label": "Capture browser evidence", "at": (now - timedelta(hours=1, minutes=30)).isoformat()},
                    {"name": "getRTMMatrix", "label": "Read RTM matrix", "at": (now - timedelta(hours=1, minutes=27)).isoformat()},
                ],
            }
        ),
        result_json=dumps(
            {
                "summary": structured_report["summary"],
                "duration_seconds": 184.4,
                "structured_report": structured_report,
                "output": "Release-ready. One medium-risk browser-preview fallback proposal is ready for approval.",
            }
        ),
    )
    session.add(run)

    live_run = AgentRun(
        id="demo-agent-live-browser-preview",
        project_id=DEMO_PROJECT_ID,
        agent_type="custom",
        status="running",
        created_at=now - timedelta(minutes=42),
        config_json=dumps(
            {
                "agent_name": "Live Browser Observer",
                "url": "https://demo.quorvex.local/checkout",
                "prompt": "Keep the checkout browser state available for reviewer inspection.",
                "selected_tools": [{"tool_name": "mcp__playwright__browser_navigate"}, {"tool_name": "mcp__playwright__browser_take_screenshot"}],
                "timeout_seconds": 900,
            }
        ),
        progress_json=dumps(
            {
                "phase": "running",
                "tool_calls": 7,
                "browser_tool_calls": 5,
                "last_tool_label": "Browser screenshot",
                "has_browser_tools": True,
                "message": "Watching checkout confirmation with browser evidence captured.",
            }
        ),
        result_json=None,
    )
    session.add(live_run)

    conversation = ChatConversation(
        id="demo-chat-custom-agent",
        project_id=DEMO_PROJECT_ID,
        user_id=user_id,
        title="Create a custom checkout QA agent",
        is_starred=True,
        summary="Assistant created Checkout Risk Scout, launched it, and summarized release-readiness findings.",
        created_at=now - timedelta(hours=2),
        updated_at=now - timedelta(hours=1, minutes=15),
    )
    session.add(conversation)
    messages = [
        ("user", "Create a custom agent that checks checkout risk, RTM coverage, and live browser evidence for the release demo."),
        (
            "assistant",
            "I created **Checkout Risk Scout** with browser, RTM, dashboard, and agent-report tools. It can inspect the app, verify traceability, and propose tests behind approval gates.",
        ),
        (
            "assistant",
            "The agent completed its run: pass rate is 98%, RTM coverage is 91.7%, and one medium-risk live-browser fallback test is ready for approval.",
        ),
        (
            "user",
            "Can this be done from chat next time too?",
        ),
        (
            "assistant",
            "Yes. From the assistant you can create custom agents, start runs, inspect RTM gaps, open reports, and turn findings into approval-gated test proposals without leaving the chat workflow.",
        ),
    ]
    for idx, (role, content) in enumerate(messages):
        session.add(
            ChatMessage(
                conversation_id=conversation.id,
                role=role,
                content=content,
                content_json=dumps([{"type": "text", "text": content}]),
                created_at=now - timedelta(hours=2) + timedelta(minutes=idx * 8),
            )
        )


def write_png(path: Path, width: int = 1280, height: int = 720) -> None:
    """Write a simple browser-like preview PNG using only the standard library."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            if y < 54:
                rgb = (18, 25, 43)
            elif y < 112:
                rgb = (247, 250, 252)
            elif 80 < x < 520 and 150 < y < 620:
                rgb = (238, 246, 255)
            elif 560 < x < 1180 and 150 < y < 300:
                rgb = (220, 252, 231)
            elif 560 < x < 1180 and 330 < y < 620:
                rgb = (239, 246, 255)
            elif (x // 18 + y // 18) % 2 == 0:
                rgb = (248, 250, 252)
            else:
                rgb = (241, 245, 249)
            row.extend(rgb)
        rows.append(b"\x00" + bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return len(data).to_bytes(4, "big") + kind + data + zlib.crc32(kind + data).to_bytes(4, "big")

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def seed_artifacts() -> None:
    for run_id in ["demo-agent-checkout-risk-scout", "demo-agent-live-browser-preview"]:
        write_png(PROJECT_ROOT / "runs" / run_id / "artifacts" / "browser-preview.png")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed polished demo data for the Quorvex video workflow")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "output")
    args = parser.parse_args()

    with Session(engine) as session:
        user = upsert_project_and_user(session)
        clean_project(session, DEMO_PROJECT_ID)
        user = upsert_project_and_user(session)
        spec_names = seed_specs(session)
        seed_runs(session, spec_names)
        seed_exploration(session)
        seed_requirements_and_rtm(session, spec_names)
        seed_autopilot(session)
        seed_autonomous(session, user.id)
        seed_agents_and_chat(session, user.id)
        write_auth_token(session, user, args.output_dir.resolve())
        session.commit()

    seed_artifacts()
    print(f"Seeded {DEMO_PROJECT_NAME} ({DEMO_PROJECT_ID})")
    print(f"Wrote recorder auth context to {args.output_dir.resolve() / 'demo-auth.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
