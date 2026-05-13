import sys
import types
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_vector_store_collection_names_use_explicit_project(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMADB_PERSIST_DIRECTORY", str(tmp_path / "chroma"))

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
    sys.modules.pop("orchestrator.memory.vector_store", None)

    import orchestrator.memory.vector_store as vector_store_module

    with patch.object(vector_store_module, "get_embedding_client") as mock_get:
        mock_client = Mock()
        mock_client.embed_batch.return_value = [[0.1, 0.2, 0.3]]
        mock_get.return_value = mock_client

        from orchestrator.memory.vector_store import VectorStore

        alpha = VectorStore(project_id="alpha")
        beta = VectorStore(project_id="beta")

        assert alpha._get_collection_name("test_patterns").endswith("_alpha_test_patterns")
        assert beta._get_collection_name("test_patterns").endswith("_beta_test_patterns")
        assert vector_store_module.get_config().project_id is None


def test_graph_store_uses_explicit_project_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMADB_PERSIST_DIRECTORY", str(tmp_path / "chroma"))

    from orchestrator.memory.graph_store import GraphStore

    alpha = GraphStore(project_id="alpha")
    beta = GraphStore(project_id="beta")

    assert alpha.persist_file.name == "application_alpha.json"
    assert beta.persist_file.name == "application_beta.json"
    assert alpha.persist_file != beta.persist_file


def test_get_memory_manager_none_does_not_reuse_previous_project(monkeypatch):
    from orchestrator.memory import manager as manager_module

    class FakeConfig:
        def __init__(self, project_id):
            self.project_id = project_id

    class FakeMemoryManager:
        def __init__(self, project_id=None):
            self.config = FakeConfig(project_id or "default")

    monkeypatch.setattr(manager_module, "MemoryManager", FakeMemoryManager)
    manager_module._memory_manager = None

    alpha = manager_module.get_memory_manager(project_id="alpha")
    default = manager_module.get_memory_manager(project_id=None)

    assert alpha.config.project_id == "alpha"
    assert default.config.project_id == "default"
    assert default is not alpha

    manager_module._memory_manager = None
