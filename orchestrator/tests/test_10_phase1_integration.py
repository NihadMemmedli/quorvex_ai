"""
End-to-End Integration Test for Phase 1 (Memory & Coverage System)

This test validates:
1. Memory system initialization
2. Pattern storage and retrieval
3. Graph store operations
4. Coverage tracking

Run with: pytest orchestrator/tests/test_10_phase1_integration.py -v --isolated
"""

import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set test environment variables before imports
os.environ["OPENAI_API_KEY"] = "test-key-for-integration-tests"
os.environ["MEMORY_ENABLED"] = "true"


class TestPhase1MemorySystem:
    """Test Phase 1 memory system integration"""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test data"""
        temp = tempfile.mkdtemp(prefix=f"test_{uuid.uuid4().hex[:8]}_")
        yield temp
        shutil.rmtree(temp, ignore_errors=True)

    @pytest.fixture
    def mock_embeddings(self):
        """Mock embedding client"""
        with patch("memory.vector_store.get_embedding_client") as mock_get:
            mock_client = Mock()
            mock_client.embed_batch.return_value = [[0.1, 0.2, 0.3, 0.4, 0.5]]
            mock_get.return_value = mock_client
            yield mock_client

    def test_memory_manager_initialization(self, temp_dir, mock_embeddings):
        """Test memory manager can be initialized"""
        from memory import MemoryManager

        os.environ["CHROMADB_PERSIST_DIRECTORY"] = temp_dir

        manager = MemoryManager(project_id="test_project")

        assert manager is not None
        assert manager.vector_store is not None
        assert manager.graph_store is not None

    def test_store_and_retrieve_pattern(self, temp_dir, mock_embeddings):
        """Test storing and retrieving test patterns"""
        from memory import MemoryManager

        os.environ["CHROMADB_PERSIST_DIRECTORY"] = temp_dir

        manager = MemoryManager(project_id="test_pattern_project")

        # Store a pattern
        pattern_id = manager.store_test_pattern(
            test_name="Login Test",
            step_number=1,
            action="click",
            target="Login button",
            selector={"type": "role", "value": "button", "name": "Login"},
            success=True,
            duration_ms=100,
        )

        assert pattern_id is not None

        # Find similar tests
        similar = manager.find_similar_tests(description="click login button", n_results=5, min_success_rate=0.0)

        assert isinstance(similar, list)

    def test_graph_store_operations(self, temp_dir):
        """Test graph store can track application structure"""
        from memory import GraphStore

        graph_file = Path(temp_dir) / "test_graph.json"

        store = GraphStore(persist_file=str(graph_file))

        # Add a page
        store.add_page(page_id="page_home", url="https://example.com", title="Home Page")

        # Add an element
        store.add_element(
            element_id="elem_submit",
            page_id="page_home",
            element_type="button",
            selector={"type": "text", "value": "Submit"},
            text="Submit",
        )

        # Add a flow
        store.add_flow(flow_id="flow_login", name="Login Flow", start_page="page_home")

        # Get coverage
        coverage = store.get_coverage_for_page("page_home")
        assert coverage["total_elements"] == 1

        # Get stats
        stats = store.get_graph_stats()
        assert stats["page_count"] == 1
        assert stats["element_count"] == 1
        assert stats["flow_count"] == 1

        # Save and verify persistence
        store.save()
        assert graph_file.exists()

    def test_coverage_summary(self, temp_dir, mock_embeddings):
        """Test getting coverage summary"""
        from memory import MemoryManager

        os.environ["CHROMADB_PERSIST_DIRECTORY"] = temp_dir

        manager = MemoryManager(project_id="test_coverage_project")

        summary = manager.get_coverage_summary()
        assert "graph_stats" in summary
        assert summary["graph_stats"]["total_nodes"] >= 0

    def test_test_ideas_generation(self, temp_dir, mock_embeddings):
        """Test generating test ideas from coverage gaps"""
        from memory import MemoryManager

        os.environ["CHROMADB_PERSIST_DIRECTORY"] = temp_dir

        manager = MemoryManager(project_id="test_ideas_project")

        # Store a test idea
        idea_id = manager.store_test_idea(
            description="Test login with invalid password", priority="high", category="negative_testing"
        )

        assert idea_id is not None


class TestPhase1CoverageTracking:
    """Test coverage tracking functionality"""

    def test_coverage_tracker(self):
        """Test element coverage tracker"""
        from coverage import CoverageTracker

        tracker = CoverageTracker()

        # Record some element interactions
        tracker.record_element(
            action="click", selector={"type": "role", "value": "button"}, success=True, url="https://example.com"
        )

        tracker.record_element(
            action="fill", selector={"type": "label", "value": "Email"}, success=True, url="https://example.com"
        )

        tracker.record_element(
            action="click",
            selector={"type": "text", "value": "Submit"},
            success=False,
            url="https://example.com",
            error="Element not found",
        )

        # Get summary
        summary = tracker.get_coverage_summary()
        assert summary["total_interactions"] == 3
        assert summary["successful_interactions"] == 2
        assert summary["failed_interactions"] == 1

        # Get covered URLs
        urls = tracker.get_covered_urls()
        assert "https://example.com" in urls

    def test_playwright_coverage_class(self):
        """Test PlaywrightCoverage helper class"""
        from coverage import PlaywrightCoverage

        # Test coverage script generation
        start_script = PlaywrightCoverage.setup_coverage_script()
        assert "startCoverage" in start_script

        collect_script = PlaywrightCoverage.collect_coverage_script()
        assert "collectCoverage" in collect_script

        # Test processing mock coverage data
        mock_coverage = '{"js": [], "css": []}'
        result = PlaywrightCoverage.process_coverage_data(mock_coverage)
        assert result["total_bytes"] == 0
        assert result["coverage_percentage"] == 0

    def test_merge_coverage_reports(self):
        """Test merging multiple coverage reports"""
        from coverage import merge_coverage_reports

        report1 = {
            "coverage_summary": {
                "total_elements": 10,
                "tested_elements": 5,
                "coverage_percentage": 50.0,
                "breakdown": {"buttons": {"total": 5, "tested": 3, "coverage": 60}},
            }
        }

        report2 = {
            "coverage_summary": {
                "total_elements": 20,
                "tested_elements": 15,
                "coverage_percentage": 75.0,
                "breakdown": {"buttons": {"total": 8, "tested": 6, "coverage": 75}},
            }
        }

        merged = merge_coverage_reports([report1, report2])

        assert merged["total_elements"] == 30
        assert merged["tested_elements"] == 20
        assert merged["coverage_percentage"] == pytest.approx(66.67, rel=0.1)
        assert merged["breakdown"]["buttons"]["total"] == 13
        assert merged["breakdown"]["buttons"]["tested"] == 9


class TestPhase1MemoryUnits:
    """Test individual memory components in isolation"""

    def test_vector_store_initialization(self):
        """Test vector store can be initialized"""
        import tempfile

        from memory.vector_store import VectorStore

        temp_dir = tempfile.mkdtemp()
        try:
            with patch("memory.vector_store.get_embedding_client") as mock_get:
                mock_client = Mock()
                mock_client.embed_batch.return_value = [[0.1, 0.2, 0.3]]
                mock_get.return_value = mock_client

                store = VectorStore(persist_directory=temp_dir)
                assert store is not None
                assert store.client is not None
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_graph_store_persistence(self):
        """Test graph store can persist data"""
        import tempfile

        from memory.graph_store import GraphStore

        temp_dir = tempfile.mkdtemp()
        try:
            graph_file = Path(temp_dir) / "test_persist.json"

            store = GraphStore(persist_file=str(graph_file))
            store.add_page("page1", "https://example.com", "Test")
            store.save()

            assert graph_file.exists()

            # Load and verify
            store2 = GraphStore(persist_file=str(graph_file))
            assert store2.graph.has_node("page1")
            assert store2.graph.nodes["page1"]["url"] == "https://example.com"
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestPhase1EndToEnd:
    """End-to-end test for Phase 1 functionality"""

    def test_full_memory_workflow(self):
        """Test complete memory workflow with isolated components"""
        import tempfile

        temp_dir = tempfile.mkdtemp()
        try:
            os.environ["CHROMADB_PERSIST_DIRECTORY"] = temp_dir

            with patch("memory.vector_store.get_embedding_client") as mock_get:
                mock_client = Mock()
                mock_client.embed_batch.return_value = [[0.1, 0.2, 0.3, 0.4, 0.5]]
                mock_get.return_value = mock_client

                from memory import GraphStore, MemoryManager

                # Test graph store independently
                graph_file = Path(temp_dir) / "e2e_graph.json"
                graph_store = GraphStore(persist_file=str(graph_file))

                graph_store.add_page("page_login", "https://example.com/login", "Login")
                graph_store.add_element(
                    "elem_username", "page_login", "input", {"type": "label", "value": "Username"}, None
                )

                stats = graph_store.get_graph_stats()
                assert stats["page_count"] == 1
                assert stats["element_count"] == 1

                # Test memory manager
                manager = MemoryManager(project_id="e2e_test")

                manager.store_test_pattern(
                    test_name="Login Test",
                    step_number=1,
                    action="fill",
                    target="Username",
                    selector={"type": "label", "value": "Username"},
                    success=True,
                    duration_ms=50,
                )

                summary = manager.get_coverage_summary()
                assert "graph_stats" in summary

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
