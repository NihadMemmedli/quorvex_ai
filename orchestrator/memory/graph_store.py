"""
Graph Store Module

Provides interface to NetworkX for storing and querying application
structure as a graph (pages, elements, flows, relationships).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import networkx as nx

from .config import get_config


class GraphStore:
    """Interface to NetworkX for application structure storage"""

    def __init__(self, persist_file: str | None = None):
        """
        Initialize the graph store.

        Args:
            persist_file: File path to persist graph data
        """
        self.config = get_config()

        # Set up persistence file
        if persist_file is None:
            persist_dir = Path(self.config.persist_directory) / "graphs"
            persist_dir.mkdir(parents=True, exist_ok=True)
            project_suffix = f"_{self.config.project_id}" if self.config.project_id else ""
            persist_file = persist_dir / f"application{project_suffix}.json"

        self.persist_file = Path(persist_file)
        self.graph = nx.DiGraph()

        # Load existing graph if available
        self.last_loaded_at = 0
        self._load()

    def _load(self) -> None:
        """Load graph from persistence file"""
        if self.persist_file.exists():
            try:
                with open(self.persist_file) as f:
                    data = json.load(f)
                    self.last_loaded_at = self.persist_file.stat().st_mtime

                # Rebuild graph from JSON
                if "nodes" in data:
                    for node_data in data["nodes"]:
                        self.graph.add_node(node_data["id"], **node_data.get("attributes", {}))

                if "edges" in data:
                    for edge_data in data["edges"]:
                        self.graph.add_edge(edge_data["source"], edge_data["target"], **edge_data.get("attributes", {}))
            except Exception as e:
                print(f"Warning: Failed to load graph from {self.persist_file}: {e}")
                self.graph = nx.DiGraph()

    def save(self) -> None:
        """Save graph to persistence file"""
        self.persist_file.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "nodes": [{"id": node, "attributes": attrs} for node, attrs in self.graph.nodes(data=True)],
            "edges": [
                {"source": source, "target": target, "attributes": attrs}
                for source, target, attrs in self.graph.edges(data=True)
            ],
            "updated_at": datetime.now().isoformat(),
        }

        with open(self.persist_file, "w") as f:
            json.dump(data, f, indent=2)

    # Node types
    NODE_TYPE_PAGE = "page"
    NODE_TYPE_ELEMENT = "element"
    NODE_TYPE_FLOW = "flow"
    NODE_TYPE_FEATURE = "feature"
    NODE_TYPE_API = "api"  # For Phase 2

    # Edge types
    EDGE_TYPE_CONTAINS = "contains"
    EDGE_TYPE_NAVIGATES_TO = "navigates_to"
    EDGE_TYPE_STARTS_AT = "starts_at"
    EDGE_TYPE_ENDS_AT = "ends_at"
    EDGE_TYPE_REQUIRES = "requires"
    EDGE_TYPE_TESTS = "tests"

    def add_page(self, page_id: str, url: str, title: str = None, metadata: dict[str, Any] = None) -> None:
        """
        Add a page node to the graph.

        Args:
            page_id: Unique identifier for the page
            url: Page URL
            title: Optional page title
            metadata: Additional metadata
        """
        attrs = {
            "type": self.NODE_TYPE_PAGE,
            "url": url,
            "title": title or url,
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            **(metadata or {}),
        }

        # Update last_seen if page exists
        if self.graph.has_node(page_id):
            current_attrs = self.graph.nodes[page_id]
            attrs["first_seen"] = current_attrs.get("first_seen", attrs["first_seen"])

        self.graph.add_node(page_id, **attrs)

    def add_element(
        self,
        element_id: str,
        page_id: str,
        element_type: str,
        selector: dict[str, Any],
        text: str = None,
        metadata: dict[str, Any] = None,
    ) -> None:
        """
        Add an element node to the graph.

        Args:
            element_id: Unique identifier for the element
            page_id: Parent page ID
            element_type: Type of element (button, input, etc.)
            selector: Selector information
            text: Optional element text
            metadata: Additional metadata
        """
        attrs = {
            "type": self.NODE_TYPE_ELEMENT,
            "element_type": element_type,
            "selector": selector,
            "text": text,
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "test_count": 0,
            **(metadata or {}),
        }

        # Update last_seen and test_count if element exists
        if self.graph.has_node(element_id):
            current_attrs = self.graph.nodes[element_id]
            attrs["first_seen"] = current_attrs.get("first_seen", attrs["first_seen"])
            attrs["test_count"] = current_attrs.get("test_count", 0)

        self.graph.add_node(element_id, **attrs)

        # Add edge from page to element
        self.graph.add_edge(page_id, element_id, type=self.EDGE_TYPE_CONTAINS)

    def add_flow(
        self, flow_id: str, name: str, start_page: str, end_page: str = None, metadata: dict[str, Any] = None
    ) -> None:
        """
        Add a flow node to the graph.

        Args:
            flow_id: Unique identifier for the flow
            name: Flow name
            start_page: Starting page ID
            end_page: Optional ending page ID
            metadata: Additional metadata
        """
        attrs = {
            "type": self.NODE_TYPE_FLOW,
            "name": name,
            "start_page": start_page,
            "end_page": end_page,
            "created_at": datetime.now().isoformat(),
            **(metadata or {}),
        }

        self.graph.add_node(flow_id, **attrs)

        # Add edge from flow to start page
        self.graph.add_edge(flow_id, start_page, type=self.EDGE_TYPE_STARTS_AT)

        # Add edge to end page if specified
        if end_page:
            self.graph.add_edge(flow_id, end_page, type=self.EDGE_TYPE_ENDS_AT)

    def add_navigation(
        self, from_page: str, to_page: str, trigger: str = None, metadata: dict[str, Any] = None
    ) -> None:
        """
        Add a navigation edge between pages.

        Args:
            from_page: Source page ID
            to_page: Target page ID
            trigger: What triggers the navigation (e.g., element_id)
            metadata: Additional metadata
        """
        attrs = {
            "type": self.EDGE_TYPE_NAVIGATES_TO,
            "trigger": trigger,
            "first_seen": datetime.now().isoformat(),
            **(metadata or {}),
        }

        # Update first_seen if edge exists
        if self.graph.has_edge(from_page, to_page):
            current_attrs = self.graph.edges[from_page, to_page]
            attrs["first_seen"] = current_attrs.get("first_seen", attrs["first_seen"])

        self.graph.add_edge(from_page, to_page, **attrs)

    def record_test_coverage(self, element_id: str, test_name: str = None) -> None:
        """
        Record that an element was tested.

        Args:
            element_id: Element identifier
            test_name: Optional test name
        """
        if self.graph.has_node(element_id):
            current = self.graph.nodes[element_id]
            self.graph.nodes[element_id]["test_count"] = current.get("test_count", 0) + 1
            self.graph.nodes[element_id]["last_tested"] = datetime.now().isoformat()
            if test_name:
                tests = self.graph.nodes[element_id].get("tests", [])
                tests.append(test_name)
                self.graph.nodes[element_id]["tests"] = list(set(tests))

    def get_page_elements(self, page_id: str) -> list[dict[str, Any]]:
        """
        Get all elements on a page.

        Args:
            page_id: Page identifier

        Returns:
            List of element data
        """
        elements = []
        for successor in self.graph.successors(page_id):
            attrs = self.graph.nodes[successor]
            edge = self.graph.edges[page_id, successor]
            if edge.get("type") == self.EDGE_TYPE_CONTAINS and attrs.get("type") == self.NODE_TYPE_ELEMENT:
                elements.append({"id": successor, **attrs})
        return elements

    def get_untested_elements(self, page_id: str = None) -> list[dict[str, Any]]:
        """
        Get elements that haven't been tested.

        Args:
            page_id: Optional page ID to filter by

        Returns:
            List of untested element data
        """
        untested = []

        if page_id:
            nodes = [page_id] + list(self.graph.successors(page_id))
        else:
            nodes = self.graph.nodes()

        for node in nodes:
            attrs = self.graph.nodes[node]
            if attrs.get("type") == self.NODE_TYPE_ELEMENT and attrs.get("test_count", 0) == 0:
                untested.append({"id": node, **attrs})

        return untested

    def get_coverage_for_page(self, page_id: str) -> dict[str, Any]:
        """
        Get coverage statistics for a page.

        Args:
            page_id: Page identifier

        Returns:
            Coverage statistics
        """
        elements = self.get_page_elements(page_id)
        total = len(elements)
        tested = sum(1 for e in elements if e.get("test_count", 0) > 0)

        return {
            "page_id": page_id,
            "total_elements": total,
            "tested_elements": tested,
            "untested_elements": total - tested,
            "coverage_percentage": (tested / total * 100) if total > 0 else 0,
        }

    def find_shortest_path(self, from_page: str, to_page: str) -> list[str] | None:
        """
        Find shortest path between two pages.

        Args:
            from_page: Source page ID
            to_page: Target page ID

        Returns:
            List of page IDs in path, or None if no path exists
        """
        try:
            return nx.shortest_path(self.graph, from_page, to_page)
        except nx.NetworkXNoPath:
            return None

    def get_all_flows(self) -> list[dict[str, Any]]:
        """
        Get all defined flows.

        Returns:
            List of flow data
        """
        flows = []
        for node in self.graph.nodes():
            attrs = self.graph.nodes[node]
            if attrs.get("type") == self.NODE_TYPE_FLOW:
                flows.append({"id": node, **attrs})
        return flows

    def get_orphan_pages(self) -> list[str]:
        """
        Get pages that are not reachable from any flow.

        Returns:
            List of orphan page IDs
        """
        flow_pages = set()
        for node in self.graph.nodes():
            attrs = self.graph.nodes[node]
            if attrs.get("type") == self.NODE_TYPE_FLOW:
                if attrs.get("start_page"):
                    flow_pages.add(attrs["start_page"])
                if attrs.get("end_page"):
                    flow_pages.add(attrs["end_page"])

        orphans = []
        for node in self.graph.nodes():
            attrs = self.graph.nodes[node]
            if attrs.get("type") == self.NODE_TYPE_PAGE and node not in flow_pages:
                orphans.append(node)

        return orphans

    def get_graph_stats(self) -> dict[str, Any]:
        """
        Get statistics about the graph.

        Returns:
            Graph statistics
        """
        page_count = sum(1 for n in self.graph.nodes() if self.graph.nodes[n].get("type") == self.NODE_TYPE_PAGE)
        element_count = sum(1 for n in self.graph.nodes() if self.graph.nodes[n].get("type") == self.NODE_TYPE_ELEMENT)
        flow_count = sum(1 for n in self.graph.nodes() if self.graph.nodes[n].get("type") == self.NODE_TYPE_FLOW)

        tested_elements = sum(
            1
            for n in self.graph.nodes()
            if self.graph.nodes[n].get("type") == self.NODE_TYPE_ELEMENT
            and self.graph.nodes[n].get("test_count", 0) > 0
        )

        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "page_count": page_count,
            "element_count": element_count,
            "flow_count": flow_count,
            "tested_elements": tested_elements,
            "untested_elements": element_count - tested_elements,
            "element_coverage": (tested_elements / element_count * 100) if element_count > 0 else 0,
        }

    def export_dot(self, output_file: str = None) -> str:
        """
        Export graph to DOT format for visualization.

        Args:
            output_file: Optional file path to save DOT

        Returns:
            DOT format string
        """
        dot = nx.drawing.nx_pydot.to_pydot(self.graph)

        if output_file:
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
            dot.write_raw(output_file)

        return str(dot)


# Global graph store instance
# Global graph store instance
_graph_store: GraphStore | None = None


def get_graph_store(force_refresh: bool = False) -> GraphStore:
    """
    Get the global graph store instance.

    Checks if project_id has changed and reloads if necessary.
    """
    global _graph_store
    config = get_config()

    # Check if we need to reload (force refresh or project mismatch)
    reload_needed = False

    if _graph_store is None:
        reload_needed = True
    elif force_refresh:
        reload_needed = True
    else:
        # Check if current store file matches current project
        # This is a heuristic: check if the configured path matches the store's path
        # Re-calculating expected path:
        persist_dir = Path(config.persist_directory) / "graphs"
        project_suffix = f"_{config.project_id}" if config.project_id else ""
        expected_file = persist_dir / f"application{project_suffix}.json"

        if _graph_store.persist_file != expected_file:
            reload_needed = True

    if reload_needed:
        _graph_store = GraphStore()
        return _graph_store

    # Check if file has changed on disk since load
    if _graph_store and _graph_store.persist_file.exists():
        try:
            current_mtime = _graph_store.persist_file.stat().st_mtime
            if current_mtime > _graph_store.last_loaded_at:
                print(f"🔄 Graph file changed on disk, reloading: {_graph_store.persist_file.name}")
                _graph_store = GraphStore()
        except Exception:
            # Ignore errors checking mtime (e.g. file deleted)
            pass

    return _graph_store
