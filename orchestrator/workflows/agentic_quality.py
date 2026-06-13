"""
Agentic QA quality gates for the native Playwright pipeline.

The first version is intentionally deterministic and file-artifact based. It
adds structured judgment around generation/healing without making the default
pipeline depend on extra LLM calls before we have baseline metrics.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"
NON_HEALABLE_CATEGORIES = {"product_bug", "environment", "spec_impossible"}
HIGH_CONFIDENCE_THRESHOLD = 0.8
PLAN_SELECTOR_PATTERN = re.compile(
    r"\b(?:getByRole|getByLabel|getByPlaceholder|getByText|getByTestId|locator)\(",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    return data


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as exc:
        logger.warning(f"Could not read agentic artifact {path}: {exc}")
    return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        if not path.exists():
            return rows
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    except Exception as exc:
        logger.warning(f"Could not read agentic JSONL artifact {path}: {exc}")
    return rows


def _read_text(path: Path) -> str:
    try:
        if path.exists():
            return path.read_text().strip()
    except Exception as exc:
        logger.warning(f"Could not read agentic artifact {path}: {exc}")
    return ""


def extract_plan_selectors(plan_text: str, limit: int = 30) -> list[str]:
    """Extract locator lines from a planner markdown artifact."""
    selectors: list[str] = []
    seen: set[str] = set()
    for line in plan_text.splitlines():
        if not PLAN_SELECTOR_PATTERN.search(line):
            continue
        cleaned = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|>\s*)+", "", line).strip()
        if not cleaned or cleaned in seen:
            continue
        selectors.append(cleaned)
        seen.add(cleaned)
        if len(selectors) >= limit:
            break
    return selectors


def _summarize_costs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_stage: dict[str, dict[str, Any]] = {}
    total_usd = 0.0
    saw_cost = False
    for row in rows:
        stage = str(row.get("stage") or "unknown")
        stage_summary = by_stage.setdefault(
            stage,
            {
                "cost_usd": 0.0,
                "tool_calls": 0,
                "duration_seconds": 0.0,
                "runs": 0,
                "timed_out": 0,
            },
        )
        cost = row.get("cost_usd")
        if cost is not None:
            try:
                cost_value = float(cost)
                stage_summary["cost_usd"] += cost_value
                total_usd += cost_value
                saw_cost = True
            except (TypeError, ValueError):
                pass
        try:
            stage_summary["tool_calls"] += int(row.get("tool_calls") or 0)
        except (TypeError, ValueError):
            pass
        try:
            stage_summary["duration_seconds"] += float(row.get("duration_seconds") or 0)
        except (TypeError, ValueError):
            pass
        stage_summary["runs"] += 1
        if row.get("timed_out"):
            stage_summary["timed_out"] += 1

    return {
        "total_usd": round(total_usd, 6) if saw_cost else None,
        "by_stage": {
            stage: {
                **summary,
                "cost_usd": round(float(summary["cost_usd"]), 6),
                "duration_seconds": round(float(summary["duration_seconds"]), 3),
            }
            for stage, summary in by_stage.items()
        },
    }


def _stage_outcomes(
    run_dir: Path,
    validation: dict[str, Any],
    healing_attempts: dict[str, Any],
    run_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = _read_text(run_dir / "status.txt")
    attempts = healing_attempts.get("attempts") if isinstance(healing_attempts, dict) else []
    attempts = attempts if isinstance(attempts, list) else []
    validation_status = validation.get("status")
    validation_iterations = validation.get("iterations")
    try:
        iteration_count = int(validation_iterations or 0)
    except (TypeError, ValueError):
        iteration_count = 0

    run_metrics = run_metrics or {}
    first_run_passed = validation_status == "success" and iteration_count == 0 and not attempts
    if isinstance(run_metrics.get("initial_run_passed"), bool):
        first_run_passed = bool(run_metrics["initial_run_passed"])

    return {
        "planned": (run_dir / "plan.json").exists(),
        "generated": (run_dir / "export.json").exists() or bool(validation.get("testFile")),
        "first_run_passed": first_run_passed,
        "stable_first_pass": run_metrics.get("stable_first_pass"),
        "healed": bool(run_metrics.get("heal_rescued"))
        or any(bool(item.get("passed_after")) for item in attempts)
        or iteration_count > 0,
        "healing_attempts": int(run_metrics.get("healing_attempts") or len(attempts)),
        "status": status or None,
        "generation_repair_attempted": run_metrics.get("generation_repair_attempted"),
        "generation_repair_accepted": run_metrics.get("generation_repair_accepted"),
        "original_validation_error": run_metrics.get("original_validation_error"),
        "repaired_file_hash": run_metrics.get("repaired_file_hash")
        or run_metrics.get("generation_repaired_file_hash"),
    }


def normalize_test_design(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or {}
    flake_risk = str(data.get("flake_risk") or "medium").lower()
    if flake_risk not in {"low", "medium", "high"}:
        flake_risk = "medium"

    testability = str(data.get("testability") or "medium").lower()
    if testability not in {"low", "medium", "high"}:
        testability = "medium"

    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": data.get("created_at") or _now(),
        "flake_risk": flake_risk,
        "testability": testability,
        "recommended_strategy": data.get("recommended_strategy") or "browser_ui",
        "required_state": list(data.get("required_state") or []),
        "success_oracles": list(data.get("success_oracles") or []),
        "selector_guidance": list(data.get("selector_guidance") or []),
        "warnings": list(data.get("warnings") or []),
    }


def normalize_test_critic(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or {}
    issues = list(data.get("issues") or [])
    risk_level = str(data.get("risk_level") or ("high" if issues else "low")).lower()
    if risk_level not in {"low", "medium", "high"}:
        risk_level = "medium"

    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": data.get("created_at") or _now(),
        "risk_level": risk_level,
        "approved": bool(data.get("approved", risk_level != "high")),
        "issues": issues,
        "recommended_action": data.get("recommended_action") or ("review_warnings" if issues else "continue"),
    }


def normalize_failure_diagnosis(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or {}
    category = str(data.get("category") or "unknown").lower()
    allowed = {
        "test_bug",
        "selector_changed",
        "timing",
        "auth",
        "test_data",
        "environment",
        "product_bug",
        "spec_impossible",
        "unknown",
    }
    if category not in allowed:
        category = "unknown"

    try:
        confidence = float(data.get("confidence", 0.3))
    except (TypeError, ValueError):
        confidence = 0.3
    confidence = max(0.0, min(confidence, 1.0))

    heal_allowed = bool(data.get("heal_allowed", True))
    if category in NON_HEALABLE_CATEGORIES and confidence >= HIGH_CONFIDENCE_THRESHOLD:
        heal_allowed = False

    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": data.get("created_at") or _now(),
        "category": category,
        "confidence": confidence,
        "heal_allowed": heal_allowed,
        "root_cause": data.get("root_cause") or "Unable to determine root cause with high confidence.",
        "evidence": list(data.get("evidence") or []),
        "recommended_action": data.get("recommended_action") or ("heal" if heal_allowed else "do_not_heal"),
    }


def normalize_stability_report(data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or {}
    attempts = list(data.get("attempts") or [])
    total_runs = int(data.get("total_runs", len(attempts)))
    passed_runs = int(data.get("passed_runs", sum(1 for attempt in attempts if attempt.get("passed"))))
    failed_runs = int(data.get("failed_runs", max(total_runs - passed_runs, 0)))
    status = data.get("status") or ("stable" if failed_runs == 0 else "flaky")
    if status not in {"stable", "flaky", "skipped"}:
        status = "flaky" if failed_runs else "stable"

    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": data.get("created_at") or _now(),
        "status": status,
        "total_runs": total_runs,
        "passed_runs": passed_runs,
        "failed_runs": failed_runs,
        "attempts": attempts,
    }


class TestDesignAgent:
    """Analyzes a spec and planning output before code generation."""

    def analyze(
        self,
        *,
        spec_content: str,
        target_url: str | None,
        credentials: dict[str, str] | None,
        plan_path: Path | None,
        run_dir: Path,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        required_state: list[str] = []
        success_oracles: list[str] = []
        selector_guidance = [
            "Prefer getByRole/getByLabel/getByPlaceholder selectors before CSS selectors.",
            "Avoid nth()/first() unless the plan explains why the page has repeated equivalent elements.",
        ]

        content_lower = spec_content.lower()
        if credentials or re.search(r"\{\{[^}]*password[^}]*\}\}", spec_content, re.IGNORECASE):
            required_state.append("authenticated_user")
        if any(term in content_lower for term in ["create", "add", "delete", "edit", "update"]):
            required_state.append("isolated_test_data")
        if any(term in content_lower for term in ["toast", "animation", "loading", "async", "upload"]):
            warnings.append("Spec references asynchronous or transient UI behavior; wait on durable state changes.")
        if not target_url:
            warnings.append("No target URL was available for design analysis.")

        plan_text = ""
        plan_present = bool(plan_path and plan_path.exists())
        if plan_present and plan_path:
            try:
                plan_text = plan_path.read_text()
            except OSError as exc:
                logger.warning(f"Could not read planner artifact {plan_path}: {exc}")
                warnings.append(
                    "Planner produced a structured plan artifact, but it could not be read."
                )

        for line in spec_content.splitlines():
            if re.search(r"expect|verify|should|see|visible|appears|created|saved", line, re.IGNORECASE):
                success_oracles.append(line.strip("- ").strip())
            if len(success_oracles) >= 5:
                break

        if plan_text and len(success_oracles) < 5:
            for line in plan_text.splitlines():
                if re.search(r"expect|verify|should|see|visible|appears|created|saved", line, re.IGNORECASE):
                    oracle = line.strip("- ").strip()
                    if oracle:
                        success_oracles.append(oracle)
                if len(success_oracles) >= 5:
                    break

        if not plan_present:
            warnings.append("Planner did not produce a structured plan artifact.")
        elif plan_text:
            plan_selectors = extract_plan_selectors(plan_text)
            if plan_selectors:
                selector_guidance.append(
                    "Planner verified these selectors on the live app: "
                    + "; ".join(plan_selectors[:8])
                )

        flake_risk = "high" if len(warnings) >= 2 else "medium" if warnings else "low"
        testability = "low" if not target_url else "medium" if warnings else "high"
        strategy = "api_setup_plus_browser_assertion" if "isolated_test_data" in required_state else "browser_ui"

        design = normalize_test_design(
            {
                "flake_risk": flake_risk,
                "testability": testability,
                "recommended_strategy": strategy,
                "required_state": sorted(set(required_state)),
                "success_oracles": success_oracles,
                "selector_guidance": selector_guidance,
                "warnings": warnings,
            }
        )
        return _write_json(run_dir / "test_design.json", design)

    @staticmethod
    def condensed_context(design: dict[str, Any] | None) -> str:
        if not design:
            return ""
        return "\n".join(
            [
                f"Flake risk: {design.get('flake_risk')}",
                f"Testability: {design.get('testability')}",
                f"Recommended strategy: {design.get('recommended_strategy')}",
                f"Required state: {', '.join(design.get('required_state') or []) or 'none identified'}",
                f"Selector guidance: {'; '.join(design.get('selector_guidance') or [])}",
                f"Warnings: {'; '.join(design.get('warnings') or []) or 'none'}",
            ]
        )


class TestCriticAgent:
    """Reviews generated Playwright code for likely flake risks."""

    def review(self, *, test_path: Path, design: dict[str, Any] | None, run_dir: Path) -> dict[str, Any]:
        code = test_path.read_text() if test_path.exists() else ""
        issues: list[dict[str, Any]] = []

        checks = [
            (r"waitForTimeout\(", "high", "Uses waitForTimeout; prefer waiting for a locator, URL, or response."),
            (r"locator\(['\"]\\?\\.", "medium", "Uses CSS class selector; prefer role, label, text, or test id."),
            (r"\.first\(\)|\.nth\(", "medium", "Uses positional locator; ensure repeated elements are intentional."),
            (r"process\.env\.[A-Z0-9_]+!?", "low", "Uses environment credentials; ensure project credentials are configured."),
        ]
        for pattern, severity, message in checks:
            if re.search(pattern, code):
                issues.append({"severity": severity, "message": message})

        if "expect(" not in code:
            issues.append({"severity": "high", "message": "Generated code has no Playwright assertions."})
        if design and design.get("flake_risk") == "high":
            issues.append({"severity": "medium", "message": "Design stage marked this flow as high flake risk."})

        risk = "high" if any(i["severity"] == "high" for i in issues) else "medium" if issues else "low"
        critic = normalize_test_critic(
            {
                "risk_level": risk,
                "approved": True,
                "issues": issues,
                "recommended_action": "continue_with_warnings" if issues else "continue",
            }
        )
        return _write_json(run_dir / "test_critic.json", critic)


class FailureTriageAgent:
    """Classifies a failure before deciding whether healing is appropriate."""

    def diagnose(
        self,
        *,
        test_path: Path,
        error_output: str,
        design: dict[str, Any] | None,
        critic: dict[str, Any] | None,
        run_dir: Path,
    ) -> dict[str, Any]:
        text = error_output or ""
        lower = text.lower()
        category = "unknown"
        confidence = 0.35
        evidence: list[str] = []
        root_cause = "Failure needs healer investigation."

        has_structured_context = "## structured failure context" in lower or "playwright json summary" in lower
        has_confirmed_environment = has_structured_context and any(
            token in lower for token in ["econnrefused", "enotfound", "dns", "connection refused"]
        )
        has_confirmed_server_error = has_structured_context and any(
            token in lower for token in ['"status": 500', "http_status: 500", "response_status=500"]
        )

        patterns: list[tuple[str, float, str, list[str]]] = [
            (
                "environment",
                0.9 if has_confirmed_environment else 0.55,
                "Target environment or network may be unavailable.",
                ["econnrefused", "enotfound", "dns", "net::err", "connection refused"],
            ),
            (
                "product_bug",
                0.85 if has_confirmed_server_error else 0.55,
                "Application may have returned a server-side error.",
                ["500", "internal server error", "bad gateway", "service unavailable"],
            ),
            ("auth", 0.75, "Authentication or authorization failed.", ["401", "403", "unauthorized", "forbidden", "invalid credentials"]),
            ("spec_impossible", 0.85, "Expected behavior or element appears absent from the current app.", ["no such file", "spec impossible", "not implemented"]),
            ("selector_changed", 0.7, "Locator could not resolve to the expected element.", ["locator", "strict mode violation", "element not found", "waiting for locator"]),
            ("timing", 0.65, "Timeout while waiting for UI or navigation.", ["timeouterror", "timeout", "timed out"]),
            ("test_data", 0.65, "Required test data may be missing or already used.", ["already exists", "not found", "missing data", "duplicate"]),
            ("test_bug", 0.6, "Generated test code appears invalid.", ["syntaxerror", "referenceerror", "typeerror", "is not a function"]),
        ]
        for candidate, score, cause, needles in patterns:
            matched = [needle for needle in needles if needle in lower]
            if matched:
                category = candidate
                confidence = score
                root_cause = cause
                evidence = matched[:5]
                break

        if critic and critic.get("risk_level") == "high" and category == "unknown":
            category = "test_bug"
            confidence = 0.6
            root_cause = "Static critic found high-risk generated code."
            evidence.append("critic:risk_level=high")
        if design and design.get("testability") == "low" and category == "unknown":
            confidence = 0.55
            evidence.append("design:testability=low")

        diagnosis = normalize_failure_diagnosis(
            {
                "category": category,
                "confidence": confidence,
                "root_cause": root_cause,
                "evidence": evidence,
                "recommended_action": "skip_healing" if category in NON_HEALABLE_CATEGORIES and confidence >= HIGH_CONFIDENCE_THRESHOLD else "heal",
            }
        )
        return _write_json(run_dir / "failure_diagnosis.json", diagnosis)

    @staticmethod
    def condensed_context(diagnosis: dict[str, Any] | None) -> str:
        if not diagnosis:
            return ""
        return "\n".join(
            [
                f"Failure category: {diagnosis.get('category')}",
                f"Confidence: {diagnosis.get('confidence')}",
                f"Healing allowed: {diagnosis.get('heal_allowed')}",
                f"Root cause: {diagnosis.get('root_cause')}",
                f"Evidence: {', '.join(diagnosis.get('evidence') or []) or 'none'}",
            ]
        )


class StabilityVerifier:
    """Runs extra verification attempts after a test first passes."""

    def __init__(self, reruns: int | None = None):
        if reruns is None:
            reruns = int(os.environ.get("AGENTIC_STABILITY_RERUNS", "2"))
        self.reruns = max(0, reruns)

    def verify(
        self,
        *,
        test_file: str,
        output_dir: str,
        browser: str,
        run_test: Callable[[str, str, str], Any],
    ) -> dict[str, Any]:
        attempts: list[dict[str, Any]] = []
        for index in range(1, self.reruns + 1):
            result = run_test(test_file, output_dir, browser)
            attempts.append(
                {
                    "attempt": index,
                    "passed": bool(getattr(result, "passed", False)),
                    "exit_code": getattr(result, "exit_code", None),
                    "error_summary": getattr(result, "error_summary", "") or "",
                    "output_tail": (getattr(result, "output", "") or "")[-1200:],
                }
            )

        passed_runs = sum(1 for attempt in attempts if attempt["passed"])
        failed_runs = len(attempts) - passed_runs
        report = normalize_stability_report(
            {
                "status": "stable" if failed_runs == 0 else "flaky",
                "total_runs": len(attempts),
                "passed_runs": passed_runs,
                "failed_runs": failed_runs,
                "attempts": attempts,
            }
        )
        return _write_json(Path(output_dir) / "stability_report.json", report)


def build_agentic_summary(run_dir: Path) -> dict[str, Any]:
    design = _read_json(run_dir / "test_design.json") or {}
    critic = _read_json(run_dir / "test_critic.json") or {}
    diagnosis = _read_json(run_dir / "failure_diagnosis.json") or {}
    stability = _read_json(run_dir / "stability_report.json") or {}
    validation = _read_json(run_dir / "validation.json") or {}
    healing_attempts = _read_json(run_dir / "healing_attempts.json") or {}
    run_metrics = _read_json(run_dir / "run_metrics.json") or {}
    cost_rows = _read_jsonl(run_dir / "agent_costs.jsonl")
    issues = critic.get("issues") or []

    return {
        "schema_version": SCHEMA_VERSION,
        "design": {
            "flake_risk": design.get("flake_risk"),
            "testability": design.get("testability"),
            "recommended_strategy": design.get("recommended_strategy"),
            "warning_count": len(design.get("warnings") or []),
        },
        "critic": {
            "risk_level": critic.get("risk_level"),
            "issue_count": len(issues),
            "approved": critic.get("approved"),
        },
        "diagnosis": {
            "category": diagnosis.get("category"),
            "confidence": diagnosis.get("confidence"),
            "heal_allowed": diagnosis.get("heal_allowed"),
        },
        "stability": {
            "status": stability.get("status"),
            "total_runs": stability.get("total_runs"),
            "passed_runs": stability.get("passed_runs"),
            "failed_runs": stability.get("failed_runs"),
        },
        "costs": _summarize_costs(cost_rows),
        "stage_outcomes": _stage_outcomes(run_dir, validation, healing_attempts, run_metrics),
    }
