from datetime import datetime
import os
import sys
import types

from sqlmodel import Session, SQLModel, create_engine

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-quality-gate-tests")

slowapi = types.ModuleType("slowapi")
slowapi_errors = types.ModuleType("slowapi.errors")
slowapi_util = types.ModuleType("slowapi.util")


class _Limiter:
    def __init__(self, *args, **kwargs):
        self._storage = types.SimpleNamespace(expirations={})


class _RateLimitExceeded(Exception):
    retry_after = 60


slowapi.Limiter = _Limiter
slowapi_errors.RateLimitExceeded = _RateLimitExceeded
slowapi_util.get_remote_address = lambda request: "test-client"
sys.modules.setdefault("slowapi", slowapi)
sys.modules.setdefault("slowapi.errors", slowapi_errors)
sys.modules.setdefault("slowapi.util", slowapi_util)

from orchestrator.api.github_ci import _quality_gate_status, _serialize_quality_gate
from orchestrator.api.models_db import PrImpactAnalysis, PrSelectedTest, RegressionBatch
from orchestrator.api.models_db import TestRun as DBTestRun


def _session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _analysis(**overrides):
    values = {
        "id": "pria_test",
        "project_id": "default",
        "provider": "github",
        "owner": "org",
        "repo": "app",
        "pr_number": 42,
        "title": "Checkout fix",
        "base_ref": "main",
        "head_ref": "feature",
        "head_sha": "abc123",
        "status": "completed",
        "risk_level": "medium",
        "confidence": "high",
        "changed_files_count": 2,
        "selected_tests_count": 1,
        "total_candidate_tests": 5,
        "saved_tests_count": 4,
        "completed_at": datetime.utcnow(),
    }
    values.update(overrides)
    return PrImpactAnalysis(**values)


def test_quality_gate_requires_full_suite_when_fallback_has_not_run():
    with _session() as session:
        analysis = _analysis(confidence="low", risk_level="high", fallback_reason="Config changed")
        session.add(analysis)
        session.commit()

        status = _quality_gate_status(analysis, None, session)

        assert status["state"] == "needs-full-suite"
        assert status["github_state"] == "error"


def test_quality_gate_reports_running_batch():
    with _session() as session:
        analysis = _analysis(batch_id="batch_1")
        batch = RegressionBatch(id="batch_1", project_id="default", total_tests=1, running=1, status="running")
        run = DBTestRun(id="run_1", spec_name="checkout.md", status="running", batch_id="batch_1")
        session.add(analysis)
        session.add(batch)
        session.add(run)
        session.commit()

        status = _quality_gate_status(analysis, batch, session)

        assert status["state"] == "running"
        assert status["github_state"] == "pending"


def test_quality_gate_reports_failed_batch_with_failed_test_details():
    with _session() as session:
        analysis = _analysis(batch_id="batch_1")
        batch = RegressionBatch(id="batch_1", project_id="default", total_tests=1, failed=1, status="completed")
        run = DBTestRun(
            id="run_1",
            spec_name="checkout.md",
            status="failed",
            batch_id="batch_1",
            error_message="expected receipt",
        )
        session.add(analysis)
        session.add(batch)
        session.add(run)
        session.add(
            PrSelectedTest(
                analysis_id=analysis.id,
                spec_name="checkout.md",
                test_path="tests/generated/checkout.spec.ts",
                reason="Checkout route changed",
            )
        )
        session.commit()

        payload = _serialize_quality_gate(analysis, session, include_details=True)

        assert payload["quality_gate"]["state"] == "failed"
        assert payload["quality_gate"]["github_state"] == "failure"
        assert payload["quality_gate"]["batch"]["failed_tests"][0]["spec_name"] == "checkout.md"


def test_quality_gate_reports_passed_batch():
    with _session() as session:
        analysis = _analysis(batch_id="batch_1")
        batch = RegressionBatch(id="batch_1", project_id="default", total_tests=1, passed=1, status="completed")
        run = DBTestRun(id="run_1", spec_name="checkout.md", status="passed", batch_id="batch_1")
        session.add(analysis)
        session.add(batch)
        session.add(run)
        session.commit()

        status = _quality_gate_status(analysis, batch, session)

        assert status["state"] == "passed"
        assert status["github_state"] == "success"
