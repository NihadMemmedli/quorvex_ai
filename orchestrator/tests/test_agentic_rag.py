import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-agentic-rag-tests")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture()
def memory_engine(monkeypatch):
    from orchestrator.memory import agent_memory as agent_memory_module
    from orchestrator.memory import agentic_rag as agentic_rag_module
    from orchestrator.memory.agent_memory import AgentMemoryService

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(agent_memory_module, "engine", engine)
    monkeypatch.setattr(agentic_rag_module, "engine", engine)
    monkeypatch.setattr(AgentMemoryService, "_index_memory", lambda self, memory: None)
    monkeypatch.setattr(AgentMemoryService, "_sync_knowledge_graph", lambda self, memory: None)
    monkeypatch.setenv("MEMORY_ENABLED", "true")
    monkeypatch.setenv("AGENTIC_RAG_ENABLED", "true")
    return engine


def test_agentic_rag_routes_sources_and_rejects_invalid():
    from orchestrator.memory.agentic_rag import AgenticRagService

    service = AgenticRagService()

    assert service.classify_intent("debug the failed login run", None) == "debugging"
    assert "run_summaries" in service.route_sources(intent="debugging")

    with pytest.raises(ValueError):
        service.route_sources(intent="general", requested_sources=["secrets"])


def test_agentic_rag_project_scope_review_filter_stale_warning_and_redaction(memory_engine):
    from orchestrator.memory.agent_memory import AgentMemoryService
    from orchestrator.memory.agentic_rag import AgenticRagRequest, AgenticRagService

    memory = AgentMemoryService()
    memory.create_memory(
        kind="project_fact",
        content="Login flow starts at /login and uses api_key=abcdefghijklmnopqrstuvwxyz123456.",
        summary="Login flow starts at /login and uses api_key=abcdefghijklmnopqrstuvwxyz123456.",
        project_id="project-a",
        confidence=0.95,
        importance=0.9,
    )
    memory.create_memory(
        kind="project_fact",
        content="Project B checkout flow starts at /checkout.",
        project_id="project-b",
        confidence=0.95,
        importance=0.9,
    )
    memory.create_memory(
        kind="agent_lesson",
        content="Review-required selector memory should not be injected.",
        project_id="project-a",
        confidence=0.95,
        importance=0.9,
        review_required=True,
    )

    result = AgenticRagService().retrieve(
        AgenticRagRequest(
            query="login flow api key selector",
            project_id="project-a",
            sources=["agent_memories"],
            max_items=5,
            include_debug=True,
        )
    )

    assert "Login flow starts at /login" in result["answer_context"]
    assert "abcdefghijklmnopqrstuvwxyz" not in result["answer_context"]
    assert "Project B checkout" not in result["answer_context"]
    assert "Review-required selector" not in result["answer_context"]
    assert any("not been verified" in warning for warning in result["warnings"])
    assert result["citations"]
    assert result["debug"]["retriever"] == "agentic_rag_v1"


def test_agentic_rag_partial_source_failure_returns_degraded_context(memory_engine, monkeypatch):
    from orchestrator.memory.agent_memory import AgentMemoryService
    from orchestrator.memory.agentic_rag import AgenticRagRequest, AgenticRagService

    AgentMemoryService().create_memory(
        kind="failure_pattern",
        content="Login failed because the submit button label changed after localization.",
        project_id="project-a",
        confidence=0.95,
        importance=0.8,
    )

    service = AgenticRagService()

    def fail_prd(*args, **kwargs):
        raise RuntimeError("prd store unavailable")

    monkeypatch.setattr(service, "_retrieve_prd_chunks", fail_prd)
    result = service.retrieve(
        AgenticRagRequest(
            query="debug login failure",
            project_id="project-a",
            sources=["agent_memories", "prd_chunks"],
            max_items=3,
            include_debug=True,
        )
    )

    assert "Login failed" in result["answer_context"]
    assert result["debug"]["source_errors"]["prd_chunks"] == "prd store unavailable"
    assert result["debug"]["selected_count"] >= 1


def test_agentic_context_api_success_and_invalid_source(monkeypatch):
    from orchestrator.api.memory import router

    class FakeService:
        def retrieve(self, request):
            if request.sources == ["bad"]:
                raise ValueError("Unsupported agentic RAG source(s): bad")
            return {
                "query": request.query,
                "answer_context": "## Retrieved Knowledge\n- [K1] Result",
                "citations": [{"label": "K1", "id": "1", "source": "agent_memories"}],
                "gaps": [],
                "recommended_next_tools": ["searchMemory"],
                "warnings": [],
                "debug": {"retriever": "agentic_rag_v1"} if request.include_debug else {},
            }

    monkeypatch.setattr("orchestrator.memory.agentic_rag.get_agentic_rag_service", lambda: FakeService())
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    ok = client.post(
        "/api/memory/agentic-context",
        json={"query": "login context", "project_id": "project-a", "include_debug": True},
    )
    assert ok.status_code == 200
    assert ok.json()["citations"][0]["label"] == "K1"
    assert ok.json()["debug"]["retriever"] == "agentic_rag_v1"

    bad = client.post("/api/memory/agentic-context", json={"query": "x", "sources": ["bad"]})
    assert bad.status_code == 400
