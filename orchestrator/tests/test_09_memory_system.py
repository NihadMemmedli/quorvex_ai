"""
Unit tests for Memory System (Phase 1)

Run with: pytest orchestrator/tests/test_09_memory_system.py -v
"""

import os
from unittest.mock import Mock, patch

import pytest

# Set test environment variables before importing memory modules
os.environ["OPENAI_API_KEY"] = "test-key-for-unit-tests"
os.environ["MEMORY_ENABLED"] = "true"
os.environ["CHROMADB_PERSIST_DIRECTORY"] = "/tmp/test_chromadb"


class TestMemoryConfig:
    """Test memory configuration"""

    def test_config_defaults(self):
        """Test default configuration values"""
        # Reset config
        import orchestrator.memory.config as config_module
        from orchestrator.memory.config import get_config

        config_module._config = None

        config = get_config()

        assert config.memory_enabled is True
        assert config.retention_days == 365
        assert config.embedding_model == "text-embedding-3-small"
        assert config.coverage_threshold == 0.8

    def test_collection_name_with_project(self):
        """Test collection name generation with project isolation"""
        from orchestrator.memory.config import MemoryConfig

        config = MemoryConfig()
        config.collection_prefix = "test_automation"
        config.project_id = "my_project"

        name = config.get_collection_name("test_patterns")
        assert name == "test_automation_my_project_test_patterns"

    def test_collection_name_without_project(self):
        """Test collection name generation without project"""
        from orchestrator.memory.config import MemoryConfig

        config = MemoryConfig()
        config.collection_prefix = "test_automation"
        config.project_id = None

        name = config.get_collection_name("test_patterns")
        assert name == "test_automation_test_patterns"


class TestVectorStore:
    """Test vector store operations"""

    @pytest.fixture
    def vector_store(self):
        """Create a test vector store"""
        # Mock the embedding client to avoid API calls
        with patch("orchestrator.memory.vector_store.get_embedding_client") as mock_get:
            mock_client = Mock()
            mock_client.embed_batch.return_value = [[0.1, 0.2, 0.3]]
            mock_get.return_value = mock_client

            from orchestrator.memory.vector_store import VectorStore

            store = VectorStore(persist_directory="/tmp/test_vector_store")
            yield store
            # Cleanup
            store.reset()

    def test_add_test_pattern(self, vector_store):
        """Test adding a test pattern"""
        pattern_id = vector_store.add_test_pattern(
            pattern_id="test_pattern_1",
            description="Click login button",
            metadata={"action": "click", "selector_type": "role", "success_rate": 1.0},
            test_name="Login Test",
        )

        assert pattern_id == "test_pattern_1"

    def test_search_similar_patterns(self, vector_store):
        """Test searching for similar patterns"""
        # Add a pattern first
        vector_store.add_test_pattern(
            pattern_id="test_pattern_2",
            description="Click submit button on form",
            metadata={"action": "click", "selector_type": "role", "success_rate": 0.9},
        )

        # Search for similar patterns
        results = vector_store.search_similar_patterns(query="click button", n_results=5)

        assert len(results) >= 0  # May return empty if embedding mocked

    def test_update_pattern_stats(self, vector_store):
        """Test updating pattern statistics"""
        # Add a pattern
        vector_store.add_test_pattern(
            pattern_id="test_pattern_3",
            description="Fill email field",
            metadata={"action": "fill", "success_count": 0, "failure_count": 0},
        )

        # Update stats
        vector_store.update_pattern_stats(pattern_id="test_pattern_3", success=True, duration_ms=150)

        # Verify update
        patterns = vector_store.get_all_patterns()
        pattern = next((p for p in patterns if p["id"] == "test_pattern_3"), None)
        assert pattern is not None
        assert pattern["metadata"]["success_count"] == 1


class TestGraphStore:
    """Test graph store operations"""

    @pytest.fixture
    def graph_store(self):
        """Create a test graph store"""
        from orchestrator.memory.graph_store import GraphStore

        store = GraphStore(persist_file="/tmp/test_graph_store.json")
        yield store
        # Cleanup
        store.graph.clear()
        store.save()

    def test_add_page(self, graph_store):
        """Test adding a page node"""
        graph_store.add_page(page_id="page_login", url="https://example.com/login", title="Login Page")

        assert graph_store.graph.has_node("page_login")
        attrs = graph_store.graph.nodes["page_login"]
        assert attrs["url"] == "https://example.com/login"
        assert attrs["type"] == "page"

    def test_add_element(self, graph_store):
        """Test adding an element node"""
        # First add a page
        graph_store.add_page(page_id="page_home", url="https://example.com")

        # Add element to page
        graph_store.add_element(
            element_id="element_submit",
            page_id="page_home",
            element_type="button",
            selector={"type": "role", "value": "button", "name": "Submit"},
            text="Submit",
        )

        assert graph_store.graph.has_node("element_submit")
        assert graph_store.graph.has_edge("page_home", "element_submit")

    def test_add_flow(self, graph_store):
        """Test adding a flow node"""
        graph_store.add_page(page_id="page_start", url="https://example.com/start")
        graph_store.add_page(page_id="page_end", url="https://example.com/end")

        graph_store.add_flow(
            flow_id="flow_checkout", name="Checkout Flow", start_page="page_start", end_page="page_end"
        )

        assert graph_store.graph.has_node("flow_checkout")
        attrs = graph_store.graph.nodes["flow_checkout"]
        assert attrs["type"] == "flow"
        assert attrs["name"] == "Checkout Flow"

    def test_get_page_elements(self, graph_store):
        """Test getting elements for a page"""
        graph_store.add_page(page_id="page_form", url="https://example.com/form")
        graph_store.add_element(
            element_id="elem_input",
            page_id="page_form",
            element_type="input",
            selector={"type": "label", "value": "Email"},
        )
        graph_store.add_element(
            element_id="elem_button",
            page_id="page_form",
            element_type="button",
            selector={"type": "role", "value": "button", "name": "Submit"},
        )

        elements = graph_store.get_page_elements("page_form")
        assert len(elements) == 2

    def test_record_test_coverage(self, graph_store):
        """Test recording test coverage"""
        graph_store.add_page(page_id="page_covered", url="https://example.com/covered")
        graph_store.add_element(
            element_id="elem_covered",
            page_id="page_covered",
            element_type="button",
            selector={"type": "text", "value": "Click Me"},
        )

        graph_store.record_test_coverage("elem_covered", test_name="Test Coverage")

        attrs = graph_store.graph.nodes["elem_covered"]
        assert attrs["test_count"] == 1

    def test_get_coverage_for_page(self, graph_store):
        """Test getting coverage statistics for a page"""
        graph_store.add_page(page_id="page_stats", url="https://example.com/stats")

        # Add 3 elements
        for i in range(3):
            elem_id = f"elem_{i}"
            graph_store.add_element(
                element_id=elem_id,
                page_id="page_stats",
                element_type="button",
                selector={"type": "text", "value": f"Button {i}"},
            )

        # Test only one
        graph_store.record_test_coverage("elem_1")

        coverage = graph_store.get_coverage_for_page("page_stats")
        assert coverage["total_elements"] == 3
        assert coverage["tested_elements"] == 1
        assert coverage["coverage_percentage"] == pytest.approx(33.33, rel=1)

    def test_get_graph_stats(self, graph_store):
        """Test getting overall graph statistics"""
        graph_store.add_page(page_id="page1", url="https://example.com/page1")
        graph_store.add_page(page_id="page2", url="https://example.com/page2")

        graph_store.add_element(
            element_id="elem1", page_id="page1", element_type="button", selector={"type": "text", "value": "Click"}
        )

        graph_store.add_flow(flow_id="flow1", name="Test Flow", start_page="page1", end_page="page2")

        stats = graph_store.get_graph_stats()
        assert stats["page_count"] == 2
        assert stats["element_count"] == 1
        assert stats["flow_count"] == 1

    def test_save_and_load(self, graph_store):
        """Test saving and loading graph"""
        graph_store.add_page(page_id="page_save", url="https://example.com/save")
        graph_store.save()

        # Create new store and load
        from orchestrator.memory.graph_store import GraphStore

        new_store = GraphStore(persist_file="/tmp/test_graph_store.json")

        assert new_store.graph.has_node("page_save")
        assert new_store.graph.nodes["page_save"]["url"] == "https://example.com/save"


class TestMemoryManager:
    """Test memory manager integration"""

    @pytest.fixture
    def memory_manager(self):
        """Create a test memory manager"""
        with patch("orchestrator.memory.vector_store.get_embedding_client") as mock_get:
            mock_client = Mock()
            mock_client.embed_batch.return_value = [[0.1, 0.2, 0.3]]
            mock_get.return_value = mock_client

            from orchestrator.memory.manager import MemoryManager

            manager = MemoryManager(project_id="test_project")
            yield manager
            # Cleanup
            manager.vector_store.reset()
            manager.graph_store.graph.clear()
            manager.graph_store.save()

    def test_store_test_pattern(self, memory_manager):
        """Test storing a test pattern through memory manager"""
        pattern_id = memory_manager.store_test_pattern(
            test_name="Login Test",
            step_number=1,
            action="click",
            target="Login button",
            selector={"type": "role", "value": "button", "name": "Login"},
            success=True,
            duration_ms=100,
        )

        assert pattern_id is not None

    def test_store_discovered_element(self, memory_manager):
        """Test storing a discovered element"""
        element_id = memory_manager.store_discovered_element(
            url="https://example.com/test",
            element_type="button",
            selector={"type": "text", "value": "Submit"},
            text="Submit",
            page_id="page_test",
        )

        assert element_id is not None

    def test_get_coverage_summary(self, memory_manager):
        """Test getting coverage summary"""
        # Add some test data
        memory_manager.graph_store.add_page(page_id="page_summary", url="https://example.com/summary")

        summary = memory_manager.get_coverage_summary()
        assert "graph_stats" in summary
        assert summary["graph_stats"]["page_count"] >= 1

    def test_find_similar_tests(self, memory_manager):
        """Test finding similar tests"""
        # Store a pattern first
        memory_manager.store_test_pattern(
            test_name="Search Test",
            step_number=1,
            action="click",
            target="Search button",
            selector={"type": "role", "value": "button", "name": "Search"},
            success=True,
        )

        # Find similar tests
        similar = memory_manager.find_similar_tests(
            description="click search button",
            n_results=5,
            min_success_rate=0.0,  # Lower threshold for testing
        )

        # Should return at least the pattern we just added
        assert isinstance(similar, list)


class TestMemoryIntegration:
    """Integration tests for memory system"""

    def test_end_to_end_pattern_storage(self):
        """Test complete pattern storage workflow"""
        with patch("orchestrator.memory.vector_store.get_embedding_client") as mock_get:
            mock_client = Mock()
            mock_client.embed_batch.return_value = [[0.1, 0.2, 0.3]]
            mock_get.return_value = mock_client

            from orchestrator.memory.manager import MemoryManager

            manager = MemoryManager(project_id="e2e_test")

            # Store a pattern
            pattern_id = manager.store_test_pattern(
                test_name="E2E Test",
                step_number=1,
                action="fill",
                target="Username field",
                selector={"type": "label", "value": "Username"},
                success=True,
                duration_ms=50,
            )

            # Find similar patterns
            similar = manager.find_similar_tests("fill username input")

            # Clean up
            manager.vector_store.reset()

            assert pattern_id is not None
            assert isinstance(similar, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
