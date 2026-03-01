"""
Memory Manager Module

Main interface for the memory system. Coordinates between vector store
and graph store to provide a unified memory API for the AI agent.
"""

import hashlib
import json
from datetime import datetime
from typing import Any

from .config import get_config, set_project
from .graph_store import GraphStore, get_graph_store
from .vector_store import VectorStore, get_vector_store


class MemoryManager:
    """
    Main memory manager that coordinates vector and graph storage.

    Provides high-level API for:
    - Storing and retrieving test patterns
    - Managing application element discovery
    - Querying similar tests and selectors
    - Coverage tracking
    """

    def __init__(self, project_id: str | None = None):
        """
        Initialize the memory manager.

        Args:
            project_id: Project identifier for isolation
        """
        self.config = get_config()

        # Set project for isolation BEFORE initializing stores
        if project_id:
            set_project(project_id)
            self.config.project_id = project_id

        effective_project = project_id or self.config.project_id or "default"
        print(f"[Memory] Initializing for project: {effective_project}")

        # Initialize stores AFTER project is set
        self.vector_store: VectorStore = get_vector_store()
        # self.graph_store is now a property

        # Log initial stats
        try:
            patterns = self.vector_store.get_all_patterns()
            print(f"[Memory] Loaded {len(patterns)} existing patterns")
        except Exception:
            pass  # Silently continue if stats can't be loaded

    @property
    def graph_store(self) -> GraphStore:
        """Get the current graph store instance"""
        return get_graph_store()

    # ========== Test Pattern Methods ==========

    def _generate_pattern_id(self, action: str, selector_type: str, selector_value: str) -> str:
        """Generate unique pattern ID from action and selector"""
        content = f"{action}:{selector_type}:{selector_value}"
        return hashlib.md5(content.encode()).hexdigest()

    def store_test_pattern(
        self,
        test_name: str,
        step_number: int,
        action: str,
        target: str,
        selector: dict[str, Any],
        success: bool = True,
        duration_ms: int = 0,
        metadata: dict[str, Any] = None,
    ) -> str:
        """
        Store a test pattern from execution.

        Args:
            test_name: Name of the test
            step_number: Step number in the test
            action: Action type (click, fill, etc.)
            target: Target description
            selector: Selector information (includes parsed fields like strategy, element_role, etc.)
            success: Whether the action succeeded
            duration_ms: Execution duration
            metadata: Additional metadata (page_url, playwright_selector, screenshot, spec_file)

        Returns:
            Pattern ID
        """
        selector_type = selector.get("type", "unknown")
        selector_value = selector.get("value", selector.get("name", target))

        pattern_id = self._generate_pattern_id(action, selector_type, selector_value)

        # Check if pattern exists
        existing_patterns = self.vector_store.get_all_patterns()
        existing = next((p for p in existing_patterns if p["id"] == pattern_id), None)

        if existing:
            # Update stats instead of adding new
            self.vector_store.update_pattern_stats(pattern_id, success, duration_ms)
            return pattern_id

        # Create description for embedding
        description = f"{action} on {target}"
        if selector.get("name"):
            description += f" ({selector['name']})"

        # Extract parsed selector fields
        strategy = selector.get("strategy", "")
        element_role = selector.get("element_role", "")
        element_name = selector.get("element_name", "")
        element_label = selector.get("element_label", "")
        element_text = selector.get("element_text", "")
        element_placeholder = selector.get("element_placeholder", "")
        element_testid = selector.get("element_testid", "")
        css_selector = selector.get("css_selector", "")

        # Extract metadata fields
        metadata = metadata or {}
        page_url = metadata.get("page_url", "")
        playwright_selector = metadata.get("playwright_selector", selector_value)
        screenshot = metadata.get("screenshot", "")
        spec_file = metadata.get("spec_file", "")

        # Build metadata with all fields (ChromaDB only accepts string, int, float, bool)
        pattern_metadata = {
            "test_name": test_name,
            "step_number": step_number,
            "action": action,
            "target": target,
            "selector_type": selector_type,
            "selector_value": selector_value,
            # New fields: Full Playwright code
            "playwright_selector": playwright_selector if isinstance(playwright_selector, str) else "",
            # New fields: Page context
            "page_url": page_url if isinstance(page_url, str) else "",
            # New fields: Parsed selector metadata
            "strategy": strategy,
            "element_role": element_role,
            "element_name": element_name,
            "element_label": element_label,
            "element_text": element_text,
            "element_placeholder": element_placeholder,
            "element_testid": element_testid,
            "css_selector": css_selector,
            # New fields: Additional context
            "spec_file": spec_file if isinstance(spec_file, str) else "",
            "screenshot": screenshot if isinstance(screenshot, str) else "",
            # Stats
            "success_count": 1 if success else 0,
            "failure_count": 0 if success else 1,
            "success_rate": 1.0 if success else 0.0,
            "avg_duration": duration_ms,
            "created_at": datetime.now().isoformat(),
        }

        self.vector_store.add_test_pattern(
            pattern_id=pattern_id, description=description, metadata=pattern_metadata, test_name=test_name
        )

        # Log pattern storage (only for new patterns, not updates)
        strategy_info = f" [{strategy}]" if strategy and strategy != "unknown" else ""
        print(f"[Memory] Stored pattern: {action} on {target[:40]}{'...' if len(target) > 40 else ''}{strategy_info}")

        return pattern_id

    def find_similar_tests(
        self, description: str, n_results: int = 5, min_success_rate: float = 0.5
    ) -> list[dict[str, Any]]:
        """
        Find similar tests based on description.

        Args:
            description: Test description to search for
            n_results: Maximum number of results
            min_success_rate: Minimum success rate filter

        Returns:
            List of similar test patterns
        """
        patterns = self.vector_store.search_similar_patterns(
            query=description,
            n_results=n_results * 2,  # Get more to filter
        )

        # Filter by success rate
        filtered = [p for p in patterns if p["metadata"].get("success_rate", 0) >= min_success_rate]

        result = filtered[:n_results]

        # Log query results
        if result:
            best_match = min(p.get("distance", 1.0) for p in result) if result else 1.0
            similarity = (1 - best_match) * 100 if best_match < 1 else 0
            print(f"[Memory] Found {len(result)} similar patterns (best match: {similarity:.0f}%)")
        else:
            print(f"[Memory] No similar patterns found for: {description[:50]}...")

        return result

    def get_successful_selectors(
        self, element_description: str, action: str | None = None, min_success_rate: float = 0.7
    ) -> list[dict[str, Any]]:
        """
        Get successful selectors for a similar element.

        Args:
            element_description: Description of the element
            action: Optional action type filter
            min_success_rate: Minimum success rate

        Returns:
            List of successful selector patterns
        """
        selectors = self.vector_store.get_successful_selectors(
            element_description=element_description, min_success_rate=min_success_rate
        )

        # Filter by action if specified
        if action:
            selectors = [s for s in selectors if s["metadata"].get("action") == action]

        # Log query results
        if selectors:
            best_selector = selectors[0]
            selector_value = best_selector.get("metadata", {}).get("selector_value", "")[:40]
            success_rate = best_selector.get("metadata", {}).get("success_rate", 0)
            print(
                f"[Memory] Found {len(selectors)} selectors for '{element_description[:30]}...' (best: {selector_value}, {success_rate:.0%})"
            )

        return selectors

    # ========== Application Element Methods ==========

    def store_discovered_element(
        self,
        url: str,
        element_type: str,
        selector: dict[str, Any],
        text: str = None,
        attributes: dict[str, Any] = None,
        page_id: str = None,
    ) -> str:
        """
        Store a discovered application element.

        Args:
            url: Page URL where element was found
            element_type: Type of element (button, input, etc.)
            selector: Selector information
            text: Element text content
            attributes: Additional HTML attributes
            page_id: Optional page ID for graph

        Returns:
            Element ID
        """
        # Generate element ID
        selector_str = json.dumps(selector, sort_keys=True)
        element_id = hashlib.md5(f"{url}:{selector_str}".encode()).hexdigest()

        # Create description for embedding
        description = f"{element_type}"
        if text:
            description += f" with text '{text}'"
        if selector.get("name"):
            description += f" ({selector['name']})"

        # Validation: Truncate description to avoid database issues with messy input
        if len(description) > 200:
            description = description[:197] + "..."

        # Build metadata (ChromaDB only accepts string, int, float, bool values)
        element_metadata = {
            "url": url,
            "element_type": element_type,
            "selector_type": selector.get("type", ""),
            "selector_value": selector.get("value", selector.get("name", "")),
            "text": text or "",
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "test_count": 0,
        }

        self.vector_store.add_application_element(
            element_id=element_id, description=description, metadata=element_metadata
        )

        # Also add to graph if page_id provided
        if page_id:
            # For graph store, we can include more complex metadata
            graph_metadata = {
                "url": url,
                "first_seen": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "test_count": 0,
            }
            if attributes:
                graph_metadata["attributes"] = attributes

            self.graph_store.add_element(
                element_id=element_id,
                page_id=page_id,
                element_type=element_type,
                selector=selector,
                text=text,
                metadata=graph_metadata,
            )

        return element_id

    def record_element_tested(self, element_id: str, test_name: str = None) -> None:
        """
        Record that an element was tested.

        Args:
            element_id: Element identifier
            test_name: Optional test name
        """
        self.graph_store.record_test_coverage(element_id, test_name)

    def store_discovered_flow(
        self,
        title: str,
        steps: list[Any] = None,
        happy_path: str = None,
        pages: list[str] = None,
        metadata: dict[str, Any] = None,
    ) -> str:
        """
        Store a discovered user flow in the graph.

        Args:
            title: Title of the flow
            steps: List of steps (action trace actions) or similar
            happy_path: Description of happy path
            pages: List of pages/URLs involved
            metadata: Additional metadata

        Returns:
            Flow ID
        """
        flow_id = hashlib.md5(f"{title}:{json.dumps(pages or [])}".encode()).hexdigest()

        # Determine start/end pages if possible
        start_page = None
        end_page = None

        if pages and len(pages) > 0:
            # We assume pages are URLs, so let's try to map them to page IDs if they exist
            # Or creating new pages if they don't?
            # For now, let's treat the 'page' argument as page IDs if they look like hashes,
            # or try to find the page node for a URL.

            # Helper to find page ID by URL
            def find_page_id(url):
                for n, attrs in self.graph_store.graph.nodes(data=True):
                    if attrs.get("type") == "page" and attrs.get("url") == url:
                        return n
                return None

            start_url = pages[0]
            start_page = find_page_id(start_url)

            if not start_page:
                # Create it if it doesn't exist? Ideally we should have stored pages before flows.
                # Use a deterministic ID for the page based on URL
                start_page = hashlib.md5(start_url.encode()).hexdigest()
                self.graph_store.add_page(start_page, start_url)

            if len(pages) > 1:
                end_url = pages[-1]
                end_page = find_page_id(end_url)
                if not end_page:
                    end_page = hashlib.md5(end_url.encode()).hexdigest()
                    self.graph_store.add_page(end_page, end_url)

        # If no start page, use a placeholder or handle gracefully
        if not start_page:
            # Just don't link it for now? Or create a "root" page?
            # GraphStore requires start_page currently.
            # Let's create a generic "Entry" page if needed
            start_page = "entry_point"
            self.graph_store.add_page(start_page, "/", title="Entry Point")

        # Build metadata
        flow_meta = {
            "title": title,
            "happy_path": happy_path,
            "step_count": len(steps) if steps else 0,
            **(metadata or {}),
        }

        self.graph_store.add_flow(
            flow_id=flow_id, name=title, start_page=start_page, end_page=end_page, metadata=flow_meta
        )

        return flow_id

    # ========== Coverage Methods ==========

    def get_coverage_summary(self, url: str | None = None) -> dict[str, Any]:
        """
        Get coverage summary.

        Args:
            url: Optional URL to filter by

        Returns:
            Coverage summary
        """
        graph_stats = self.graph_store.get_graph_stats()

        # Get all elements from vector store
        all_elements = self.vector_store.get_all_patterns()

        return {"graph_stats": graph_stats, "total_patterns": len(all_elements), "url": url}

    def get_coverage_gaps(self, url: str | None = None, max_results: int = 20) -> list[dict[str, Any]]:
        """
        Identify coverage gaps (untested elements and flows).

        Args:
            url: Optional URL to filter by
            max_results: Maximum results to return

        Returns:
            List of coverage gaps
        """
        gaps = []

        # Get untested elements from graph
        untested_elements = self.graph_store.get_untested_elements()

        for element in untested_elements[:max_results]:
            if url is None or element.get("url", "").startswith(url):
                gaps.append(
                    {
                        "type": "untested_element",
                        "element_id": element["id"],
                        "element_type": element.get("element_type"),
                        "selector": element.get("selector"),
                        "text": element.get("text"),
                        "url": element.get("url"),
                        "priority": "medium",
                    }
                )

        # Get orphan pages (pages not in any flow)
        orphan_pages = self.graph_store.get_orphan_pages()
        for page_id in orphan_pages[: max_results // 2]:
            page_attrs = self.graph_store.graph.nodes[page_id]
            if url is None or page_attrs.get("url", "").startswith(url):
                gaps.append(
                    {"type": "orphan_page", "page_id": page_id, "url": page_attrs.get("url"), "priority": "low"}
                )

        return gaps

    # ========== Test Suggestion Methods ==========

    def suggest_test_ideas(self, context: dict[str, Any], max_suggestions: int = 10) -> list[dict[str, Any]]:
        """
        Suggest new test ideas based on coverage gaps and patterns.

        Args:
            context: Context information (url, feature, etc.)
            max_suggestions: Maximum number of suggestions

        Returns:
            List of test suggestions
        """
        suggestions = []

        # Get coverage gaps
        gaps = self.get_coverage_gaps(url=context.get("url"), max_results=max_suggestions)

        for gap in gaps:
            if gap["type"] == "untested_element":
                element_type = gap.get("element_type", "element")
                text = gap.get("text", "")

                # Generate suggestion based on element type
                if element_type == "button":
                    suggestion = f"Test clicking the {text or 'button'}"
                elif element_type == "input":
                    suggestion = f"Test filling the {text or 'input field'}"
                elif element_type == "link":
                    suggestion = f"Test navigating via link '{text or ''}'"
                else:
                    suggestion = f"Test interacting with {element_type} {text or ''}"

                suggestions.append(
                    {
                        "description": suggestion,
                        "type": "element_coverage",
                        "gap": gap,
                        "priority": gap.get("priority", "medium"),
                    }
                )

        return suggestions[:max_suggestions]

    def store_test_idea(
        self, description: str, priority: str = "medium", category: str = "coverage", metadata: dict[str, Any] = None
    ) -> str:
        """
        Store a test idea for later use.

        Args:
            description: Test idea description
            priority: Priority level (low, medium, high)
            category: Category (coverage, negative, edge_case, etc.)
            metadata: Additional metadata

        Returns:
            Idea ID
        """
        idea_id = hashlib.md5(f"{description}:{category}".encode()).hexdigest()

        idea_metadata = {
            "priority": priority,
            "category": category,
            "created_at": datetime.now().isoformat(),
            "status": "suggested",
            **(metadata or {}),
        }

        self.vector_store.add_test_idea(idea_id=idea_id, description=description, metadata=idea_metadata)

        return idea_id

    # ========== Graph Query Methods ==========

    def get_application_map(self, url: str | None = None) -> dict[str, Any]:
        """
        Get application structure map.

        Args:
            url: Optional URL to filter by

        Returns:
            Application map data
        """
        stats = self.graph_store.get_graph_stats()
        flows = self.graph_store.get_all_flows()

        return {"stats": stats, "flows": flows, "url_filter": url}

    def find_navigation_path(self, from_url: str, to_url: str) -> list[str] | None:
        """
        Find navigation path between two URLs.

        Args:
            from_url: Starting URL
            to_url: Target URL

        Returns:
            List of page IDs in path, or None if no path found
        """
        # Find page IDs from URLs
        from_page = None
        to_page = None

        for node in self.graph_store.graph.nodes():
            attrs = self.graph_store.graph.nodes[node]
            if attrs.get("type") == "graph_store.NODE_TYPE_PAGE":
                if attrs.get("url") == from_url:
                    from_page = node
                if attrs.get("url") == to_url:
                    to_page = node

        if from_page and to_page:
            return self.graph_store.find_shortest_path(from_page, to_page)

        return None

    # ========== Batch Methods ==========

    def batch_store_patterns(self, patterns: list[dict[str, Any]]) -> list[str]:
        """
        Store multiple test patterns at once.

        Args:
            patterns: List of pattern dictionaries

        Returns:
            List of pattern IDs
        """
        ids = []
        for pattern in patterns:
            pattern_id = self.store_test_pattern(
                test_name=pattern.get("test_name", ""),
                step_number=pattern.get("step_number", 0),
                action=pattern.get("action", ""),
                target=pattern.get("target", ""),
                selector=pattern.get("selector", {}),
                success=pattern.get("success", True),
                duration_ms=pattern.get("duration_ms", 0),
                metadata=pattern.get("metadata", {}),
            )
            ids.append(pattern_id)
        return ids

    # ========== Maintenance Methods ==========

    def save(self) -> None:
        """Persist all data to disk"""
        self.graph_store.save()

    def clear_all(self) -> None:
        """Clear all stored data (use with caution)"""
        self.vector_store.reset()
        # Graph store will be recreated on next init


# Global memory manager instance
_memory_manager: MemoryManager | None = None


def get_memory_manager(project_id: str | None = None, force_refresh: bool = False) -> MemoryManager:
    """Get the global memory manager instance

    Args:
        project_id: Project identifier for isolation
        force_refresh: Force recreation of the manager even if one exists

    Returns:
        MemoryManager instance
    """
    global _memory_manager
    if (
        _memory_manager is None
        or force_refresh
        or (_memory_manager.config.project_id != project_id and project_id is not None)
    ):
        _memory_manager = MemoryManager(project_id=project_id)
    return _memory_manager
