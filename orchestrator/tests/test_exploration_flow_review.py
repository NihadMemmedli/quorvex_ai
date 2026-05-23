import os
import sys
import types
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, select

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-flow-review-tests")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

if "slowapi" not in sys.modules:
    slowapi = types.ModuleType("slowapi")
    slowapi_errors = types.ModuleType("slowapi.errors")
    slowapi_util = types.ModuleType("slowapi.util")

    class _Limiter:
        def __init__(self, *args, **kwargs):
            pass

        def limit(self, *_args, **_kwargs):
            def decorator(func):
                return func

            return decorator

    class _RateLimitExceeded(Exception):
        pass

    slowapi.Limiter = _Limiter
    slowapi_errors.RateLimitExceeded = _RateLimitExceeded
    slowapi_util.get_remote_address = lambda request: "test-client"
    sys.modules["slowapi"] = slowapi
    sys.modules["slowapi.errors"] = slowapi_errors
    sys.modules["slowapi.util"] = slowapi_util

from orchestrator.api.db import engine
from orchestrator.api.exploration import (  # noqa: E402
    FlowReviewBulkDecision,
    FlowReviewBulkDecisionRequest,
    _ensure_flow_generation_allowed,
    bulk_decide_exploration_flows,
)
from orchestrator.api.models_db import (  # noqa: E402
    DiscoveredApiEndpoint,
    DiscoveredFlow,
    DiscoveredFlowReview,
    ExplorationSession,
    FlowStep,
)
from orchestrator.memory.exploration_store import ExplorationStore  # noqa: E402


@pytest.fixture
def flow_review_store():
    SQLModel.metadata.create_all(engine, checkfirst=True)
    project_id = f"flow-review-{uuid4()}"
    session_id = f"explore-review-{uuid4()}"
    store = ExplorationStore(project_id=project_id)
    store.create_session(session_id=session_id, entry_url="https://example.test", strategy="goal_directed")

    try:
        yield store, project_id, session_id
    finally:
        with Session(engine) as db:
            flow_ids = [
                flow.id
                for flow in db.exec(
                    select(DiscoveredFlow).where(DiscoveredFlow.session_id == session_id)
                ).all()
            ]
            for review in db.exec(
                select(DiscoveredFlowReview).where(DiscoveredFlowReview.session_id == session_id)
            ).all():
                db.delete(review)
            for endpoint in db.exec(
                select(DiscoveredApiEndpoint).where(DiscoveredApiEndpoint.session_id == session_id)
            ).all():
                db.delete(endpoint)
            for flow_id in flow_ids:
                for step in db.exec(select(FlowStep).where(FlowStep.flow_id == flow_id)).all():
                    db.delete(step)
            for flow in db.exec(
                select(DiscoveredFlow).where(DiscoveredFlow.session_id == session_id)
            ).all():
                db.delete(flow)
            session = db.get(ExplorationSession, session_id)
            if session:
                db.delete(session)
            db.commit()


def _store_flow(store: ExplorationStore, session_id: str, name: str) -> DiscoveredFlow:
    return store.store_flow(
        session_id=session_id,
        flow_name=name,
        flow_category="navigation",
        start_url="https://example.test",
        end_url="https://example.test/done",
        step_count=1,
        steps=[{"action": "click", "element": name}],
    )


def test_discovered_flow_defaults_to_pending_and_can_be_approved(flow_review_store):
    store, _project_id, session_id = flow_review_store
    flow = _store_flow(store, session_id, "Browse dashboard")

    [(listed_flow, review)] = store.get_session_flows_with_reviews(session_id)
    assert listed_flow.id == flow.id
    assert review is not None
    assert review.review_status == "pending"

    result = store.set_flow_review_status(
        flow_id=flow.id,
        session_id=session_id,
        status="approve",
        reviewer="qa@example.test",
        comment="Looks useful",
    )

    assert result is not None
    _flow, approved = result
    assert approved.review_status == "approved"
    assert approved.reviewer == "qa@example.test"
    assert approved.comment == "Looks useful"
    assert approved.decided_at is not None
    assert store.get_flow_review_status_counts(session_id)["approved"] == 1


def test_generation_is_blocked_until_all_flows_are_approved_or_generated(flow_review_store):
    store, _project_id, session_id = flow_review_store
    first = _store_flow(store, session_id, "Approved flow")
    second = _store_flow(store, session_id, "Rejected flow")

    store.set_flow_review_status(first.id, session_id, "approved")
    store.set_flow_review_status(second.id, session_id, "rejected")

    with pytest.raises(HTTPException) as exc:
        _ensure_flow_generation_allowed(store, session_id)
    assert exc.value.status_code == 409
    assert exc.value.detail["review_status_counts"]["rejected"] == 1

    store.set_flow_review_status(second.id, session_id, "approved")
    counts = _ensure_flow_generation_allowed(store, session_id)
    assert counts["approved"] == 2

    assert store.mark_session_flows_generated(session_id) == 2
    counts = store.get_flow_review_status_counts(session_id)
    assert counts["approved"] == 0
    assert counts["generated"] == 2


@pytest.mark.asyncio
async def test_bulk_review_endpoint_returns_updated_flows_and_errors(flow_review_store):
    store, project_id, session_id = flow_review_store
    flow = _store_flow(store, session_id, "Bulk approved flow")

    response = await bulk_decide_exploration_flows(
        session_id=session_id,
        body=FlowReviewBulkDecisionRequest(
            reviewer="lead@example.test",
            decisions=[
                FlowReviewBulkDecision(flow_id=flow.id, decision="approved", comment="ship it"),
                FlowReviewBulkDecision(flow_id=999999, decision="rejected", comment="missing"),
            ],
        ),
        project_id=project_id,
        current_user=None,
    )

    assert response["status"] == "completed_with_errors"
    assert response["updated"][0]["id"] == flow.id
    assert response["updated"][0]["review_status"] == "approved"
    assert response["updated"][0]["reviewer"] == "lead@example.test"
    assert response["updated"][0]["review_comment"] == "ship it"
    assert response["errors"] == [{"flow_id": 999999, "error": "Flow not found or session mismatch"}]
