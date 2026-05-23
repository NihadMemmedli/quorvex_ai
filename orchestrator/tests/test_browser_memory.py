import os
import sys
from pathlib import Path

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-browser-memory-tests")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine


def _memory_service(monkeypatch, project_id="project-a"):
    from orchestrator.memory import browser_memory as browser_memory_module
    from orchestrator.memory.browser_memory import ExplorationMemoryService

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(browser_memory_module, "engine", engine)
    monkeypatch.setattr(ExplorationMemoryService, "_index_page_state", lambda self, state, document: None)
    monkeypatch.setattr(ExplorationMemoryService, "_index_element", lambda self, element, state: None)
    monkeypatch.setattr(ExplorationMemoryService, "_project_state_to_graph", lambda self, state, elements: None)
    monkeypatch.setattr(
        ExplorationMemoryService,
        "_project_transition_to_graph",
        lambda self, transition, from_state, to_state: None,
    )
    return ExplorationMemoryService(project_id=project_id)


def test_snapshot_canonicalization_prefers_durable_locators():
    from orchestrator.memory.browser_memory import canonicalize_state, normalize_url_template

    assert normalize_url_template("https://example.test/users/123?utm_source=x&tab=settings") == (
        "https://example.test/users/{id}?tab=settings"
    )

    state = canonicalize_state(
        url="https://example.test/login",
        title="Login",
        snapshot_text='- textbox "Email" [ref=e1]\n- button "Sign in" [ref=e2]',
    )

    assert state.page_key.startswith("example.test|/login")
    assert state.state_key
    assert len(state.elements) == 2
    textbox = state.elements[0]
    assert textbox["locator_candidates"][0]["strategy"] == "role"
    assert textbox["locator_candidates"][0]["durable"] is True
    assert any(candidate["strategy"] == "label" for candidate in textbox["locator_candidates"])


def test_exploration_memory_seeds_states_transitions_and_frontier(monkeypatch):
    service = _memory_service(monkeypatch)
    counts = service.seed_from_action_trace(
        session_id="explore-1",
        entry_url="https://example.test",
        action_trace=[
            {"action": "navigate", "target": "https://example.test/login", "outcome": "ok"},
            {"action": "fill", "target": "Email", "outcome": "ok"},
            {"action": "click", "target": "Sign in", "outcome": "ok"},
        ],
    )

    bundle = service.get_memory_bundle(limit=10)

    assert counts["states"] >= 2
    assert counts["transitions"] == 3
    assert any(state["url"] == "https://example.test/login" for state in bundle["states"])
    assert all(state["source_fidelity"] == "action_trace" for state in bundle["states"])
    assert any(element["name"] in {"Email", "Sign in"} for element in bundle["elements"])
    assert any(item["action_type"] in {"fill", "click"} for item in bundle["frontier"])


def test_live_snapshot_memory_is_preferred_over_trace_fallback(monkeypatch):
    service = _memory_service(monkeypatch)
    service.seed_from_action_trace(
        session_id="explore-1",
        entry_url="https://example.test/login",
        action_trace=[{"action": "click", "target": "Sign in", "outcome": "ok"}],
    )
    live = service.upsert_page_state(
        session_id="explore-1",
        url="https://example.test/login",
        title="Login",
        snapshot_text='- button "Sign in" [ref=e1]\n- textbox "Email" [ref=e2]',
        source_fidelity="live_snapshot",
    )

    bundle = service.get_memory_bundle(query="sign in", limit=10)

    assert bundle["states"][0]["id"] == live.id
    assert bundle["states"][0]["source_fidelity"] == "live_snapshot"
    assert any(item["state_source_fidelity"] == "live_snapshot" for item in bundle["frontier"])


def test_browser_memory_delta_detects_page_state_changes_and_removed_pages(monkeypatch):
    from sqlmodel import Session

    from orchestrator.api.models_db import BrowserPageState
    from orchestrator.memory import browser_memory as browser_memory_module

    service = _memory_service(monkeypatch)
    service.upsert_page_state(
        session_id="baseline-run",
        url="https://example.test/login",
        title="Login",
        snapshot_text='- button "Sign in" [ref=e1]',
    )
    removed_state = service.upsert_page_state(
        session_id="baseline-run",
        url="https://example.test/settings",
        title="Settings",
        snapshot_text='- button "Save" [ref=e2]',
    )
    baseline = service.capture_memory_baseline()

    service.upsert_page_state(
        session_id="current-run",
        url="https://example.test/login",
        title="Login",
        snapshot_text='- textbox "Email" [ref=e1]\n- button "Continue" [ref=e2]',
    )
    service.upsert_page_state(
        session_id="current-run",
        url="https://example.test/dashboard",
        title="Dashboard",
        snapshot_text='- link "Settings" [ref=e3]',
    )
    with Session(browser_memory_module.engine) as db:
        row = db.get(BrowserPageState, removed_state.id)
        row.status = "inactive"
        db.add(row)
        db.commit()

    delta = service.compute_memory_delta(baseline)

    assert delta["summary"]["changed_page_states"] == 1
    assert delta["summary"]["new_page_states"] == 1
    assert delta["summary"]["removed_page_states"] == 1
    assert delta["page_states"]["changed"][0]["changed_fields"]["state_key"]
    assert delta["page_states"]["new"][0]["current"]["url"] == "https://example.test/dashboard"
    assert delta["page_states"]["removed"][0]["baseline"]["url"] == "https://example.test/settings"


def test_browser_memory_delta_detects_locator_drift(monkeypatch):
    from sqlmodel import Session, select

    from orchestrator.api.models_db import BrowserElement
    from orchestrator.memory import browser_memory as browser_memory_module

    service = _memory_service(monkeypatch)
    state = service.upsert_page_state(
        session_id="baseline-run",
        url="https://example.test/login",
        title="Login",
        snapshot_text='- button "Sign in" [ref=e1]',
    )
    baseline = service.capture_memory_baseline()

    with Session(browser_memory_module.engine) as db:
        element = db.exec(select(BrowserElement).where(BrowserElement.state_id == state.id)).first()
        element.locator_candidates_json = [
            {
                "strategy": "css",
                "locator": "button:nth-child(3)",
                "score": 0.35,
                "durable": False,
            }
        ]
        db.add(element)
        db.commit()

    delta = service.compute_memory_delta(baseline)

    assert delta["summary"]["locator_drift"] == 1
    drift = delta["elements"]["locator_drift"][0]["drift"]
    assert drift["best_locator.strategy"] == {"from": "role", "to": "css"}
    assert drift["best_locator.durable"] == {"from": True, "to": False}
    assert drift["best_locator.score_delta"] < 0


def test_frontier_work_is_actionable_ranked_and_leased(monkeypatch):
    service = _memory_service(monkeypatch)
    service.upsert_page_state(
        session_id="explore-1",
        url="https://example.test/login",
        title="Login",
        snapshot_text='- textbox "Email" [ref=e1]\n- button "Sign in" [ref=e2]\n- button "Delete account" [ref=e3]',
    )

    work = service.get_frontier_work(query="login email", limit=10, risk_max="medium")

    assert work
    assert all(item["state_url"] == "https://example.test/login" for item in work)
    assert all(item["best_locator"].get("locator") for item in work)
    assert all(item["risk_level"] in {"low", "medium"} for item in work)
    assert not any(item["name"] == "Delete account" for item in work)
    assert work == sorted(work, key=lambda item: item["rank_score"], reverse=True)

    claimed = service.claim_frontier_items(worker_id="worker-1", limit=2, query="login")

    assert len(claimed) == 2
    assert all(item["status"] == "in_progress" for item in claimed)
    assert all(item["lease_owner"] == "worker-1" for item in claimed)


def test_record_transition_completes_matching_frontier(monkeypatch):
    service = _memory_service(monkeypatch)
    from_state = service.upsert_page_state(
        session_id="explore-1",
        url="https://example.test/login",
        title="Login",
        snapshot_text='- button "Sign in" [ref=e1]',
    )
    frontier = service.get_frontier_work(query="sign in", limit=1)
    assert frontier and frontier[0]["status"] == "queued"

    to_state = service.upsert_page_state(
        session_id="explore-1",
        url="https://example.test/dashboard",
        title="Dashboard",
        snapshot_text='- link "Settings" [ref=e2]',
    )
    transition = service.record_transition(
        session_id="explore-1",
        from_state=from_state,
        to_state=to_state,
        action_type="click",
        target="Sign in",
        success=True,
    )

    completed = service.complete_frontier_item(frontier[0]["id"], transition_id=transition.id)
    assert completed["status"] == "completed"
    assert completed["lease_owner"] is None


def test_exploratory_prompt_includes_browser_memory_rules():
    from orchestrator.agents.exploratory_agent import ExploratoryAgent

    prompt = ExploratoryAgent.__new__(ExploratoryAgent)._build_exploration_prompt(
        url="https://example.test",
        instructions="Explore checkout",
        time_limit_minutes=5,
        auth_config={"type": "none"},
        test_data={},
        focus_areas=[],
        excluded_patterns=[],
        browser_memory_context="### Browser Exploration Memory\n- Frontier click \"Checkout\": locator=getByRole(...)",
    )

    assert "CONTEXT-ENGINEERED BROWSER MEMORY" in prompt
    assert "Stored memory is advisory" in prompt
    assert "browser_snapshot output and user instructions are authoritative" in prompt
    assert 'Frontier click "Checkout"' in prompt


def test_memory_context_builder_formats_actionable_frontier(monkeypatch):
    from orchestrator.memory import browser_memory as browser_memory_module
    from orchestrator.memory.context_builder import MemoryContextBuilder

    class FakeAgentMemoryService:
        def search(self, **kwargs):
            return []

    class FakeBrowserMemoryService:
        def get_memory_bundle(self, **kwargs):
            return {
                "states": [],
                "elements": [],
                "frontier": [
                    {
                        "id": "frontier-1",
                        "state_id": "state-1",
                        "state_url": "https://example.test/cart",
                        "element_id": "element-1",
                        "action_type": "click",
                        "name": "Checkout",
                        "best_locator": {"locator": 'getByRole("button", { name: "Checkout" })', "score": 0.9},
                        "rank_score": 0.82,
                        "risk_level": "low",
                        "attempts": 0,
                        "status": "queued",
                    }
                ],
            }

    monkeypatch.setattr(
        browser_memory_module,
        "get_exploration_memory_service",
        lambda project_id=None: FakeBrowserMemoryService(),
    )

    builder = MemoryContextBuilder(FakeAgentMemoryService())
    bundle = builder.build_bundle(query="checkout", project_id="project-a", include_graph=False)
    text = builder.format_prompt_context(bundle)

    assert "Browser Exploration Memory" in text
    assert "Use frontier items as prioritized candidates" in text
    assert "Frontier click \"Checkout\"" in text
    assert "provenance=state:state-1 element:element-1" in text
