import os
import sys
import types
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlmodel import SQLModel, create_engine


def _stub_chromadb(monkeypatch):
    chromadb = types.ModuleType("chromadb")
    chromadb.PersistentClient = Mock()
    chromadb_config = types.ModuleType("chromadb.config")
    chromadb_config.Settings = Mock()
    embedding_functions = types.ModuleType("chromadb.utils.embedding_functions")
    embedding_functions.EmbeddingFunction = object
    chromadb_utils = types.ModuleType("chromadb.utils")
    chromadb_utils.embedding_functions = embedding_functions
    monkeypatch.setitem(sys.modules, "chromadb", chromadb)
    monkeypatch.setitem(sys.modules, "chromadb.config", chromadb_config)
    monkeypatch.setitem(sys.modules, "chromadb.utils", chromadb_utils)
    monkeypatch.setitem(sys.modules, "chromadb.utils.embedding_functions", embedding_functions)


def test_agent_memory_capture_redacts_and_deduplicates(monkeypatch):
    from orchestrator.memory import agent_memory as agent_memory_module
    from orchestrator.memory.agent_memory import AgentMemoryService

    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(agent_memory_module, "engine", engine)
    monkeypatch.setattr(AgentMemoryService, "_index_memory", lambda self, memory: None)
    monkeypatch.setenv("MEMORY_ENABLED", "true")

    service = AgentMemoryService()
    stored = service.capture_candidates(
        "Please remember that we prefer headless runs. api_key=abcdefghijklmnopqrstuvwxyz123456",
        project_id="project-a",
        source_type="chat_message",
        source_id="1",
        agent_type="assistant",
    )
    duplicate = service.capture_candidates(
        "Please remember that we prefer headless runs. api_key=abcdefghijklmnopqrstuvwxyz123456",
        project_id="project-a",
        source_type="chat_message",
        source_id="2",
        agent_type="assistant",
    )

    assert len(stored) == 1
    assert len(duplicate) == 1
    memories = service.search(project_id="project-a", limit=10, min_confidence=0.0)
    assert len(memories) == 1
    assert memories[0].kind == "user_preference"
    assert "[REDACTED]" in memories[0].content
    assert "abcdefghijklmnopqrstuvwxyz" not in memories[0].content


def test_agent_memory_context_injected_into_agent_runner(monkeypatch):
    from orchestrator.utils.agent_runner import AgentRunner

    class FakeMemoryService:
        def build_context(self, **kwargs):
            assert kwargs["project_id"] == "project-a"
            return "## Agent Memory\n- [user_preference] Prefer headless runs"

    monkeypatch.setenv("MEMORY_ENABLED", "true")
    monkeypatch.setenv("MEMORY_PROJECT_ID", "project-a")
    monkeypatch.setattr(
        "orchestrator.memory.agent_memory.get_agent_memory_service",
        lambda: FakeMemoryService(),
    )

    runner = AgentRunner(allowed_tools=[])
    prompt = runner._augment_prompt_with_agent_memory("Run the login test")

    assert prompt.startswith("## Agent Memory")
    assert "Run the login test" in prompt


def test_find_navigation_path_uses_page_node_type(monkeypatch):
    _stub_chromadb(monkeypatch)
    sys.modules.pop("orchestrator.memory.vector_store", None)
    sys.modules.pop("orchestrator.memory.manager", None)
    from orchestrator.memory.manager import MemoryManager

    manager = object.__new__(MemoryManager)
    from orchestrator.memory.graph_store import GraphStore

    graph_store = GraphStore(persist_file="/tmp/test_agent_memory_graph.json", project_id="project-a")
    graph_store.graph.clear()
    graph_store.add_page("home", "https://example.test")
    graph_store.add_page("login", "https://example.test/login")
    graph_store.add_navigation("home", "login")
    manager._graph_store = graph_store

    assert manager.find_navigation_path("https://example.test", "https://example.test/login") == ["home", "login"]
