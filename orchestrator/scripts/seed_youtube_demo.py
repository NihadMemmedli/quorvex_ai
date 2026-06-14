#!/usr/bin/env python3
"""Seed deterministic data for the first Quorvex AI YouTube demo."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

ORCHESTRATOR_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ORCHESTRATOR_DIR.parent
sys.path.insert(0, str(ORCHESTRATOR_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from api.db import DATABASE_URL, engine, get_database_type, init_db
from api.models_db import (
    AgentRun,
    AgentRunEvent,
    Project,
    RegressionBatch,
    Requirement,
    RtmEntry,
    SpecMetadata,
    TestRun,
    get_spec_metadata,
)

DEMO_PROJECT_ID = "quorvex-demo-shop"
DEMO_PROJECT_NAME = "Quorvex Demo Shop"
DEMO_BASE_URL = "https://demo-shop.quorvex.local"
DEMO_SPEC_ROOT = "quorvex-demo-shop"


@dataclass(frozen=True)
class DemoSpec:
    path: str
    title: str
    description: str
    tags: list[str]
    content: str
    generated_test_path: str | None = None
    generated_test: str | None = None


@dataclass(frozen=True)
class DemoRun:
    key: str
    spec_name: str
    test_name: str
    status: str
    age: timedelta
    duration_seconds: int
    stage: str
    stage_message: str
    error_message: str | None = None
    healed: bool = False


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "demo"


def _project_name(project_id: str) -> str:
    return DEMO_PROJECT_NAME if project_id == DEMO_PROJECT_ID else f"{DEMO_PROJECT_NAME} ({project_id})"


def _specs(project_id: str) -> list[DemoSpec]:
    root = _slug(project_id)
    return [
        DemoSpec(
            path=f"{root}/checkout/checkout-payment-validation.md",
            title="Checkout rejects invalid payment data",
            description="Validates card form errors, failed authorization handling, and checkout-state recovery.",
            tags=["checkout", "payment", "critical", "youtube-demo"],
            generated_test_path=f"tests/generated/{root}/checkout-payment-validation.spec.ts",
            generated_test="""import { test, expect } from '@playwright/test';

test('checkout rejects expired card and preserves cart state', async ({ page }) => {
  await page.goto('/checkout');
  await page.getByLabel('Card number').fill('4242 4242 4242 4242');
  await page.getByLabel('Expiry').fill('01/20');
  await page.getByRole('button', { name: 'Pay now' }).click();
  await expect(page.getByText('Use a future expiration date')).toBeVisible();
  await expect(page.getByTestId('cart-total')).toHaveText('$86.40');
});
""",
            content="""# Test: Checkout rejects invalid payment data

## Base URL
https://demo-shop.quorvex.local

## Objective
Make failed payment validation actionable by checking the visible error, cart preservation, and retry path.

## Preconditions
- Customer is signed in as `qa.checkout@example.com`.
- Cart contains Everyday Backpack and USB-C Cable.
- Checkout is on the payment step.

## Steps
1. Open `/checkout`.
2. Fill card number `4242 4242 4242 4242`.
3. Fill expiry `01/20`.
4. Click **Pay now**.
5. Verify inline expiry validation appears.
6. Verify the order is not created.
7. Verify cart total remains `$86.40`.

## Expected Result
The checkout blocks submission, explains the validation issue, preserves cart state, and keeps the customer on the payment step.
""",
        ),
        DemoSpec(
            path=f"{root}/checkout/checkout-address-state.md",
            title="Checkout shipping state survives refresh",
            description="Covers stale checkout-state regressions between address, delivery, and payment steps.",
            tags=["checkout", "state", "flaky", "youtube-demo"],
            generated_test_path=f"tests/generated/{root}/checkout-address-state.spec.ts",
            generated_test="""import { test, expect } from '@playwright/test';

test('checkout keeps shipping address after refresh', async ({ page }) => {
  await page.goto('/checkout/shipping');
  await page.getByLabel('Street address').fill('101 Market Street');
  await page.reload();
  await expect(page.getByLabel('Street address')).toHaveValue('101 Market Street');
});
""",
            content="""# Test: Checkout shipping state survives refresh

## Objective
Detect stale checkout-state bugs before customers lose progress during payment.

## Steps
1. Start checkout with a logged-in customer.
2. Enter a valid shipping address.
3. Continue to delivery.
4. Refresh the page.
5. Navigate back to shipping.

## Expected Result
The address remains populated and the checkout stepper reflects the current step.
""",
        ),
        DemoSpec(
            path=f"{root}/cart/cart-total-and-tax.md",
            title="Cart total matches line items, discount, tax, and shipping",
            description="Checks commerce math before checkout payment starts.",
            tags=["cart", "pricing", "critical", "youtube-demo"],
            generated_test_path=f"tests/generated/{root}/cart-total-and-tax.spec.ts",
            generated_test="""import { test, expect } from '@playwright/test';

test('cart total includes discount, tax, and shipping once', async ({ page }) => {
  await page.goto('/cart');
  await page.getByLabel('Discount code').fill('SPRING15');
  await page.getByRole('button', { name: 'Apply discount' }).click();
  await expect(page.getByTestId('cart-total')).toHaveText('$86.40');
});
""",
            content="""# Test: Cart total matches line items, discount, tax, and shipping

## Objective
Catch cart total mismatches that become payment and order reconciliation defects.

## Steps
1. Add Everyday Backpack and USB-C Cable to the cart.
2. Apply discount code `SPRING15`.
3. Select standard shipping.
4. Compare subtotal, discount, tax, shipping, and total.

## Expected Result
The rendered total is `$86.40`, matching the order preview returned by `/api/cart/price-preview`.
""",
        ),
        DemoSpec(
            path=f"{root}/auth/login-session-recovery.md",
            title="Login session recovers before checkout",
            description="Ensures expired sessions redirect back to the original checkout path.",
            tags=["login", "session", "checkout", "youtube-demo"],
            content="""# Test: Login session recovers before checkout

## Objective
Prevent customers from losing checkout intent after a session timeout.

## Steps
1. Open `/checkout` with an expired auth cookie.
2. Verify the app redirects to `/login?returnTo=/checkout`.
3. Sign in as `qa.checkout@example.com`.
4. Verify checkout resumes at the shipping step.

## Expected Result
Login succeeds and the customer returns to checkout with the cart intact.
""",
        ),
        DemoSpec(
            path=f"{root}/promotions/discount-code-guardrails.md",
            title="Discount code guardrails",
            description="Covers valid, expired, and one-time promotion behavior.",
            tags=["discount", "cart", "edge-case", "youtube-demo"],
            content="""# Test: Discount code guardrails

## Objective
Verify discount behavior is predictable and audit-friendly.

## Steps
1. Apply `SPRING15` and confirm the discount is accepted.
2. Apply `EXPIRED20` and confirm an expired-code message.
3. Try to apply `SPRING15` twice.

## Expected Result
Only one valid discount is applied and rejected codes do not change the cart total.
""",
        ),
        DemoSpec(
            path=f"{root}/orders/order-confirmation.md",
            title="Order confirmation includes payment and fulfillment signals",
            description="Validates the final customer-facing confirmation after checkout.",
            tags=["order-confirmation", "checkout", "smoke", "youtube-demo"],
            content="""# Test: Order confirmation includes payment and fulfillment signals

## Objective
Confirm successful checkout leaves enough evidence for support and QA triage.

## Steps
1. Complete checkout with a valid test card.
2. Land on `/orders/:id/confirmation`.
3. Verify order number, paid status, email receipt message, and estimated delivery.

## Expected Result
The order confirmation page displays a stable order number and captured payment status.
""",
        ),
    ]


def _runs(project_id: str) -> list[DemoRun]:
    root = _slug(project_id)
    checkout_payment = f"{root}/checkout/checkout-payment-validation.md"
    checkout_state = f"{root}/checkout/checkout-address-state.md"
    cart_total = f"{root}/cart/cart-total-and-tax.md"
    login = f"{root}/auth/login-session-recovery.md"
    discount = f"{root}/promotions/discount-code-guardrails.md"
    confirmation = f"{root}/orders/order-confirmation.md"
    return [
        DemoRun(
            key="checkout-selector-drift",
            spec_name=checkout_payment,
            test_name="checkout rejects invalid payment data",
            status="failed",
            age=timedelta(hours=2),
            duration_seconds=47,
            stage="testing",
            stage_message="Failed on payment form selector after checkout UI copy changed.",
            error_message="Locator getByRole('button', { name: 'Pay now' }) resolved to hidden element; selector drift on checkout payment step.",
        ),
        DemoRun(
            key="payment-validation-regression",
            spec_name=checkout_payment,
            test_name="expired card shows inline validation",
            status="failed",
            age=timedelta(days=1, hours=3),
            duration_seconds=39,
            stage="validation",
            stage_message="Assertion failed: invalid expiry no longer blocks order submission.",
            error_message="Expected text 'Use a future expiration date' but found 'Payment authorized'; payment validation regression.",
        ),
        DemoRun(
            key="cart-total-mismatch",
            spec_name=cart_total,
            test_name="cart total includes discount, tax, and shipping once",
            status="failed",
            age=timedelta(days=2, hours=1),
            duration_seconds=33,
            stage="validation",
            stage_message="Cart total mismatch after discount is applied.",
            error_message="Expected cart total '$86.40' but got '$91.40'; shipping was added twice after SPRING15 discount.",
        ),
        DemoRun(
            key="checkout-timeout",
            spec_name=checkout_state,
            test_name="checkout keeps shipping address after refresh",
            status="failed",
            age=timedelta(days=3, hours=4),
            duration_seconds=91,
            stage="testing",
            stage_message="Timeout waiting for checkout stepper to restore address state.",
            error_message="Timeout 30000ms exceeded while waiting for selector [data-testid='checkout-stepper'] after refresh.",
        ),
        DemoRun(
            key="stale-checkout-state",
            spec_name=login,
            test_name="login session recovers before checkout",
            status="failed",
            age=timedelta(days=4, hours=2),
            duration_seconds=44,
            stage="validation",
            stage_message="Stale checkout state redirects to cart instead of returning to checkout.",
            error_message="Session expired during checkout; expected /checkout after login but page URL remained /cart.",
        ),
        DemoRun(
            key="discount-pass",
            spec_name=discount,
            test_name="discount code guardrails",
            status="passed",
            age=timedelta(days=1, hours=8),
            duration_seconds=24,
            stage="done",
            stage_message="Discount guardrails passed.",
        ),
        DemoRun(
            key="order-confirmation-pass",
            spec_name=confirmation,
            test_name="order confirmation includes payment and fulfillment signals",
            status="passed",
            age=timedelta(days=2, hours=8),
            duration_seconds=28,
            stage="done",
            stage_message="Order confirmation smoke passed.",
        ),
        DemoRun(
            key="checkout-healed",
            spec_name=checkout_payment,
            test_name="checkout rejects expired card and preserves cart state",
            status="passed",
            age=timedelta(hours=8),
            duration_seconds=62,
            stage="healing_complete",
            stage_message="Native healer replaced the hidden Pay now locator with getByTestId('submit-payment').",
            healed=True,
        ),
        DemoRun(
            key="checkout-flaky-pass",
            spec_name=checkout_state,
            test_name="checkout keeps shipping address after refresh",
            status="passed",
            age=timedelta(days=5, hours=1),
            duration_seconds=67,
            stage="done",
            stage_message="Checkout state restoration passed on retry.",
        ),
        DemoRun(
            key="login-pass",
            spec_name=login,
            test_name="login session recovers before checkout",
            status="passed",
            age=timedelta(days=6),
            duration_seconds=31,
            stage="done",
            stage_message="Login recovery passed.",
        ),
    ]


def _json_dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _upsert_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project:
        project = session.exec(select(Project).where(Project.name == _project_name(project_id))).first()
    if not project:
        project = Project(id=project_id, name=_project_name(project_id))
        session.add(project)

    project.name = _project_name(project_id)
    project.base_url = DEMO_BASE_URL
    project.description = (
        "Seeded commerce checkout demo for the first Quorvex AI YouTube walkthrough: "
        "failed tests, agent findings, specs, and database quality signals."
    )
    project.settings = {
        "demo": "youtube-001",
        "audience": "QA engineers",
        "recording_path": [
            "/",
            "/runs",
            "/agents",
            "/specs",
            "/database-testing",
        ],
    }
    project.last_active = datetime.utcnow()
    session.add(project)
    session.flush()
    return project


def _seed_specs(project_id: str) -> list[str]:
    spec_names: list[str] = []
    now = datetime.utcnow()
    for spec in _specs(project_id):
        spec_path = PROJECT_ROOT / "specs" / spec.path
        _write_text(spec_path, spec.content)
        spec_names.append(spec.path)
        if spec.generated_test_path and spec.generated_test:
            _write_text(PROJECT_ROOT / spec.generated_test_path, spec.generated_test)

    with Session(engine) as session:
        for spec in _specs(project_id):
            meta = get_spec_metadata(session, spec.path, project_id)
            if not meta:
                meta = SpecMetadata(spec_name=spec.path, project_id=project_id)
            meta.project_id = project_id
            meta.description = spec.description
            meta.author = "Quorvex AI Demo Seed"
            meta.last_modified = now
            meta.tags = spec.tags
            session.add(meta)
        session.commit()
    return spec_names


def _run_id(project_id: str, key: str) -> str:
    return f"{_slug(project_id)}-{key}"


def _seed_runs(project_id: str) -> list[str]:
    now = datetime.utcnow()
    run_ids = [_run_id(project_id, item.key) for item in _runs(project_id)]
    batch_id = f"{_slug(project_id)}-nightly-checkout-regression"

    with Session(engine) as session:
        for run_id in run_ids:
            existing = session.get(TestRun, run_id)
            if existing:
                session.delete(existing)
        existing_batch = session.get(RegressionBatch, batch_id)
        if existing_batch:
            session.delete(existing_batch)
        session.commit()

        batch = RegressionBatch(
            id=batch_id,
            name="Nightly checkout regression - YouTube demo",
            triggered_by="demo-seed",
            browser="chromium",
            tags_used_json=json.dumps(["checkout", "cart", "payment"]),
            hybrid_mode=True,
            project_id=project_id,
            status="completed",
            total_tests=len(run_ids),
            passed=sum(1 for item in _runs(project_id) if item.status == "passed"),
            failed=sum(1 for item in _runs(project_id) if item.status == "failed"),
            started_at=now - timedelta(hours=2, minutes=15),
            completed_at=now - timedelta(hours=2),
            created_at=now - timedelta(hours=2, minutes=16),
        )
        session.add(batch)

        for item in _runs(project_id):
            run_id = _run_id(project_id, item.key)
            created_at = now - item.age
            completed_at = created_at + timedelta(seconds=item.duration_seconds)
            run = TestRun(
                id=run_id,
                spec_name=item.spec_name,
                status=item.status,
                test_name=item.test_name,
                browser="chromium",
                steps_completed=5 if item.status == "passed" else 3,
                total_steps=5,
                batch_id=batch_id,
                project_id=project_id,
                error_message=item.error_message,
                current_stage=item.stage,
                stage_started_at=created_at + timedelta(seconds=4),
                stage_message=item.stage_message,
                healing_attempt=1 if item.healed else None,
                test_type="browser",
                created_at=created_at,
                started_at=created_at + timedelta(seconds=2),
                completed_at=completed_at,
                agentic_summary={
                    "summary": item.stage_message,
                    "failure_category": _failure_category(item.error_message),
                    "healed": item.healed,
                    "evidence": [
                        f"/api/runs/{run_id}/logs",
                        f"runs/{run_id}/validation.json",
                    ],
                },
            )
            session.add(run)
        session.commit()

    for item in _runs(project_id):
        _write_run_artifacts(project_id, item, now - item.age)

    return run_ids


def _failure_category(error_message: str | None) -> str | None:
    if not error_message:
        return None
    lower = error_message.lower()
    if "selector" in lower or "locator" in lower:
        return "selector drift"
    if "timeout" in lower:
        return "timeout"
    if "session" in lower:
        return "stale checkout state"
    if "total" in lower:
        return "cart total mismatch"
    if "validation" in lower or "expected" in lower:
        return "payment validation regression"
    return "failure"


def _write_run_artifacts(project_id: str, item: DemoRun, created_at: datetime) -> None:
    run_id = _run_id(project_id, item.key)
    run_dir = PROJECT_ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    generated_test_path = next(
        (spec.generated_test_path for spec in _specs(project_id) if spec.path == item.spec_name and spec.generated_test_path),
        None,
    )

    final_state = "passed" if item.status == "passed" else "failed"
    steps = [
        {"name": "Open demo shop", "status": "passed", "duration": 4.2},
        {"name": "Prepare checkout state", "status": "passed", "duration": 8.5},
        {
            "name": item.test_name,
            "status": final_state,
            "duration": item.duration_seconds,
            **({"error": item.error_message} if item.error_message else {}),
        },
    ]
    _json_dump(
        run_dir / "run.json",
        {
            "finalState": final_state,
            "duration": item.duration_seconds,
            "testName": item.test_name,
            "specName": item.spec_name,
            "steps": steps,
            "startedAt": created_at.isoformat(),
        },
    )
    _json_dump(
        run_dir / "validation.json",
        {
            "status": "success" if item.status == "passed" else "failed",
            "mode": "native_healer" if item.healed else "validation",
            "iterations": 1 if item.healed else 0,
            "healed": item.healed,
            "failure_reason": item.error_message,
            "error": item.error_message,
            "steps": steps,
        },
    )
    _json_dump(
        run_dir / "plan.json",
        {
            "goal": item.test_name,
            "spec_name": item.spec_name,
            "stages": ["setup", "execute", "validate", "report"],
            "risk": _failure_category(item.error_message) or "smoke",
        },
    )
    if generated_test_path:
        _json_dump(
            run_dir / "export.json",
            {
                "testFilePath": generated_test_path,
                "specName": item.spec_name,
                "testName": item.test_name,
            },
        )
    (run_dir / "execution.log").write_text(
        "\n".join(
            [
                f"[{created_at.isoformat()}] starting {item.test_name}",
                f"[{(created_at + timedelta(seconds=5)).isoformat()}] loaded {DEMO_BASE_URL}",
                f"[{(created_at + timedelta(seconds=12)).isoformat()}] stage={item.stage} {item.stage_message}",
                f"[{(created_at + timedelta(seconds=item.duration_seconds)).isoformat()}] status={item.status}",
                *(["evidence: " + item.error_message] if item.error_message else ["evidence: assertions passed"]),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    mtime = created_at.timestamp()
    artifact_paths = [run_dir, run_dir / "run.json", run_dir / "validation.json", run_dir / "plan.json", run_dir / "execution.log"]
    if generated_test_path:
        artifact_paths.append(run_dir / "export.json")
    for path in artifact_paths:
        os.utime(path, (mtime, mtime))


def _seed_requirements(project_id: str) -> list[int]:
    root = _slug(project_id)
    specs_by_key = {
        "checkout-payment-validation": f"{root}/checkout/checkout-payment-validation.md",
        "checkout-state-recovery": f"{root}/checkout/checkout-address-state.md",
        "cart-total-accuracy": f"{root}/cart/cart-total-and-tax.md",
        "login-return-to-checkout": f"{root}/auth/login-session-recovery.md",
        "order-confirmation-audit": f"{root}/orders/order-confirmation.md",
    }
    requirements = [
        ("QDS-001", "Checkout blocks invalid payment data", "checkout-payment-validation", "critical"),
        ("QDS-002", "Checkout state survives refresh and retry", "checkout-state-recovery", "high"),
        ("QDS-003", "Cart total matches pricing preview", "cart-total-accuracy", "critical"),
        ("QDS-004", "Expired sessions return to checkout", "login-return-to-checkout", "high"),
        ("QDS-005", "Order confirmation exposes payment evidence", "order-confirmation-audit", "medium"),
    ]
    created_ids: list[int] = []
    with Session(engine) as session:
        existing = session.exec(
            select(Requirement).where(
                Requirement.project_id == project_id,
                Requirement.canonical_key.in_([item[2] for item in requirements]),
            )
        ).all()
        existing_ids = [req.id for req in existing if req.id is not None]
        if existing_ids:
            for entry in session.exec(select(RtmEntry).where(RtmEntry.requirement_id.in_(existing_ids))).all():
                session.delete(entry)
            session.commit()
        for req in existing:
            session.delete(req)
        session.commit()

        for code, title, key, priority in requirements:
            req = Requirement(
                project_id=project_id,
                req_code=code,
                title=title,
                description=f"Commerce QA requirement for the YouTube demo: {title}.",
                category="checkout",
                priority=priority,
                status="tested",
                canonical_key=key,
                truth_state="confirmed_requirement",
                source_type="demo_seed",
                confidence=0.95,
                confirmed_by="demo-seed",
                confirmed_at=datetime.utcnow(),
                acceptance_criteria_json=json.dumps(
                    [
                        "Behavior is covered by a markdown spec.",
                        "Historical run evidence exists in the demo project.",
                        "Failures produce an actionable QA finding.",
                    ]
                ),
            )
            session.add(req)
            session.flush()
            created_ids.append(req.id or 0)
            session.add(
                RtmEntry(
                    project_id=project_id,
                    requirement_id=req.id or 0,
                    test_spec_name=specs_by_key[key],
                    test_spec_path=str(PROJECT_ROOT / "specs" / specs_by_key[key]),
                    mapping_type="full",
                    dedupe_key=f"{project_id}:{key}",
                    confidence=0.94,
                    coverage_notes="Seeded for the first YouTube demo walkthrough.",
                )
            )
        session.commit()
    return created_ids


def _seed_agent_report(project_id: str) -> str:
    run_id = f"{_slug(project_id)}-agent-checkout-triage"
    now = datetime.utcnow()
    structured_report = {
        "summary": (
            "Checkout failures are concentrated around payment validation and state restoration. "
            "The cart total mismatch is likely a pricing preview/data issue, while selector drift is isolated to the payment button."
        ),
        "scope": "Triage failed checkout regression runs for Quorvex Demo Shop.",
        "pages_checked": [
            {"url": f"{DEMO_BASE_URL}/cart", "status": "issue found"},
            {"url": f"{DEMO_BASE_URL}/checkout", "status": "issue found"},
            {"url": f"{DEMO_BASE_URL}/checkout/payment", "status": "issue found"},
            {"url": f"{DEMO_BASE_URL}/orders/preview", "status": "passed"},
        ],
        "findings": [
            {
                "id": "F-001",
                "title": "Payment button locator drifted after copy and layout change",
                "severity": "high",
                "page": f"{DEMO_BASE_URL}/checkout/payment",
                "description": "The generated test still targets a hidden Pay now button. The visible submit control now uses data-testid submit-payment.",
                "evidence": "Run quorvex-demo-shop-checkout-selector-drift fails with a locator resolved to hidden element error.",
            },
            {
                "id": "F-002",
                "title": "Expired card validation allows order submission",
                "severity": "critical",
                "page": f"{DEMO_BASE_URL}/checkout/payment",
                "description": "The payment form no longer blocks an expired card before authorization.",
                "evidence": "Expected inline error was absent; run captured Payment authorized text.",
            },
            {
                "id": "F-003",
                "title": "Discounted cart total diverges from pricing preview",
                "severity": "high",
                "page": f"{DEMO_BASE_URL}/cart",
                "description": "The frontend displays shipping twice when SPRING15 is active.",
                "evidence": "Expected $86.40 but page showed $91.40.",
            },
        ],
        "test_ideas": [
            {
                "id": "T-001",
                "title": "Add API-backed cart total contract before checkout",
                "priority": "high",
                "page": f"{DEMO_BASE_URL}/cart",
                "steps": ["Create a cart with two line items", "Apply SPRING15", "Compare UI total against /api/cart/price-preview"],
                "expected": "UI total, API preview, and database order draft totals match.",
            },
            {
                "id": "T-002",
                "title": "Retry checkout after expired session",
                "priority": "medium",
                "page": f"{DEMO_BASE_URL}/checkout",
                "steps": ["Expire auth cookie", "Open checkout", "Sign in", "Verify returnTo path and cart state"],
                "expected": "The customer returns to checkout with the cart intact.",
            },
        ],
        "evidence": [
            {"id": "E-001", "type": "api", "label": "Failed run logs", "value": "/api/runs/quorvex-demo-shop-checkout-selector-drift/logs"},
            {"id": "E-002", "type": "file", "label": "Validation evidence", "value": "runs/quorvex-demo-shop-payment-validation-regression/validation.json"},
            {"id": "E-003", "type": "database", "label": "Database quality run", "value": "/database-testing/runs/dbt-demo-quality"},
        ],
        "follow_up_actions": [
            "Review the payment validation change before release.",
            "Stabilize the payment submit locator in generated Playwright specs.",
            "Connect cart total checks to database order/payment quality checks.",
        ],
        "parse_status": "structured",
    }

    with Session(engine) as session:
        for event in session.exec(select(AgentRunEvent).where(AgentRunEvent.run_id == run_id)).all():
            session.delete(event)
        existing = session.get(AgentRun, run_id)
        if existing:
            session.delete(existing)
        session.commit()

        run = AgentRun(
            id=run_id,
            agent_type="custom",
            runtime="claude_sdk",
            status="completed",
            project_id=project_id,
            agent_task_id=f"task-{run_id}",
            created_at=now - timedelta(hours=1, minutes=12),
            started_at=now - timedelta(hours=1, minutes=11),
            completed_at=now - timedelta(hours=1, minutes=7),
        )
        run.config = {
            "agent_name": "Checkout Failure Triage",
            "prompt": "Inspect failed checkout runs and return findings, evidence, test ideas, and follow-up actions.",
            "url": f"{DEMO_BASE_URL}/checkout",
            "selected_tools": ["read_run_logs", "inspect_specs", "database_testing_summary"],
        }
        run.progress = {
            "phase": "completed",
            "updated_at": (now - timedelta(hours=1, minutes=7)).isoformat(),
            "tool_calls": 5,
            "browser_tool_calls": 2,
            "last_tool": "read_run_logs",
        }
        run.result = {
            "summary": structured_report["summary"],
            "structured_report": structured_report,
            "duration_seconds": 248.0,
            "tool_calls": [
                {"name": "read_run_logs", "status": "completed"},
                {"name": "inspect_specs", "status": "completed"},
                {"name": "database_testing_summary", "status": "completed"},
            ],
            "output": json.dumps(structured_report, indent=2),
        }
        session.add(run)
        session.flush()

        events = [
            ("queued", "Queued checkout failure triage", "info", {"queue": "custom-agent"}),
            ("tool_call", "Loaded failed checkout run logs", "info", {"tool_name": "read_run_logs", "run_count": 5}),
            ("browser_action", "Captured checkout payment page state", "info", {"url": f"{DEMO_BASE_URL}/checkout/payment"}),
            ("tool_call", "Compared cart total spec to failed assertion", "info", {"tool_name": "inspect_specs"}),
            ("complete", "Structured report created with findings and test ideas", "info", {"findings": 3, "test_ideas": 2}),
        ]
        for sequence, (event_type, message, level, payload) in enumerate(events, start=1):
            event = AgentRunEvent(
                id=f"{run_id}-event-{sequence}",
                project_id=project_id,
                run_id=run_id,
                agent_task_id=run.agent_task_id,
                sequence=sequence,
                event_type=event_type,
                level=level,
                message=message,
                payload_json=json.dumps(payload),
                created_at=(run.started_at or now) + timedelta(seconds=sequence * 35),
            )
            session.add(event)
        session.commit()
    return run_id


def _seed_database_testing(project_id: str, *, reset_schema: bool, connection_host: str | None, connection_port: int | None) -> dict[str, Any]:
    scripts_dir = ORCHESTRATOR_DIR / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import seed_database_testing_demo as db_seed

    if get_database_type() == "postgresql" and reset_schema:
        return db_seed.seed_database_testing_demo(
            project_id=project_id,
            connection_host=connection_host,
            connection_port=connection_port,
        )

    profile = db_seed.connection_profile_from_url(
        DATABASE_URL,
        override_host=connection_host,
        override_port=connection_port,
    )
    return db_seed.ensure_demo_platform_data(project_id=project_id, profile=profile)


def seed_youtube_demo(
    *,
    project_id: str = DEMO_PROJECT_ID,
    include_database: bool = True,
    reset_database_schema: bool = True,
    connection_host: str | None = None,
    connection_port: int | None = None,
) -> dict[str, Any]:
    init_db()
    with Session(engine) as session:
        project = _upsert_project(session, project_id)
        session.commit()
        project_id = project.id or project_id

    spec_names = _seed_specs(project_id)
    run_ids = _seed_runs(project_id)
    requirement_ids = _seed_requirements(project_id)
    agent_run_id = _seed_agent_report(project_id)
    database_result = None
    if include_database:
        database_result = _seed_database_testing(
            project_id,
            reset_schema=reset_database_schema,
            connection_host=connection_host,
            connection_port=connection_port,
        )

    return {
        "project_id": project_id,
        "project_name": _project_name(project_id),
        "base_url": DEMO_BASE_URL,
        "specs": spec_names,
        "runs": run_ids,
        "agent_run_id": agent_run_id,
        "requirements": requirement_ids,
        "database_testing": database_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the Quorvex Demo Shop YouTube walkthrough data")
    parser.add_argument("--project-id", default=DEMO_PROJECT_ID, help="Project ID to seed")
    parser.add_argument("--skip-database", action="store_true", help="Do not seed database-testing demo rows")
    parser.add_argument("--no-reset-schema", action="store_true", help="Do not reset the PostgreSQL demo schema")
    parser.add_argument("--connection-host", default=None, help="Override host stored in the database-testing connection")
    parser.add_argument("--connection-port", type=int, default=None, help="Override port stored in the database-testing connection")
    args = parser.parse_args()

    result = seed_youtube_demo(
        project_id=args.project_id,
        include_database=not args.skip_database,
        reset_database_schema=not args.no_reset_schema,
        connection_host=args.connection_host,
        connection_port=args.connection_port,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
