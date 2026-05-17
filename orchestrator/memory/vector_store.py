"""
Vector Store Module

Provides interface to ChromaDB for storing and retrieving vectors
with semantic search capabilities.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

try:
    import chromadb
    from chromadb.config import Settings
    from chromadb.utils import embedding_functions

    CHROMADB_AVAILABLE = True
except Exception:
    chromadb = None
    Settings = None
    embedding_functions = SimpleNamespace(EmbeddingFunction=object)
    CHROMADB_AVAILABLE = False

from .config import get_config
from .embeddings import get_embedding_client

# Global ChromaDB clients keyed by persist directory.
_chroma_clients: dict[str, Any] = {}


class _FallbackCollection:
    """Small in-process Chroma-compatible collection used when Chroma cannot import."""

    def __init__(self, name: str):
        self.name = name
        self._items: dict[str, dict[str, Any]] = {}

    def add(self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]]):
        for idx, item_id in enumerate(ids):
            self._items[item_id] = {
                "document": documents[idx] if documents else "",
                "metadata": metadatas[idx] if metadatas else {},
            }

    def update(
        self,
        ids: list[str],
        documents: list[str] | None = None,
        metadatas: list[dict[str, Any]] | None = None,
    ):
        for idx, item_id in enumerate(ids):
            item = self._items.setdefault(item_id, {"document": "", "metadata": {}})
            if documents is not None:
                item["document"] = documents[idx]
            if metadatas is not None:
                item["metadata"] = metadatas[idx]

    def get(
        self,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        rows = []
        for item_id, item in self._items.items():
            if ids is not None and item_id not in ids:
                continue
            if where and any(item["metadata"].get(key) != value for key, value in where.items()):
                continue
            rows.append((item_id, item))
        return {
            "ids": [item_id for item_id, _ in rows],
            "documents": [item["document"] for _, item in rows],
            "metadatas": [item["metadata"] for _, item in rows],
        }

    def query(self, query_texts: list[str], n_results: int = 5, where: dict[str, Any] | None = None) -> dict[str, Any]:
        query = (query_texts[0] if query_texts else "").lower()
        query_terms = set(query.split())
        rows = []
        for item_id, item in self._items.items():
            if where and any(item["metadata"].get(key) != value for key, value in where.items()):
                continue
            document = str(item["document"]).lower()
            overlap = len(query_terms & set(document.split())) if query_terms else 0
            distance = 1.0 / (overlap + 1)
            rows.append((distance, item_id, item))
        rows.sort(key=lambda row: row[0])
        rows = rows[:n_results]
        return {
            "ids": [[item_id for _, item_id, _ in rows]],
            "documents": [[item["document"] for _, _, item in rows]],
            "metadatas": [[item["metadata"] for _, _, item in rows]],
            "distances": [[distance for distance, _, _ in rows]],
        }

    def delete(self, ids: list[str]):
        for item_id in ids:
            self._items.pop(item_id, None)

    def count(self) -> int:
        return len(self._items)


class _FallbackClient:
    def __init__(self):
        self._collections: dict[str, _FallbackCollection] = {}

    def get_or_create_collection(self, name: str, embedding_function=None, metadata: dict[str, Any] | None = None):
        if name not in self._collections:
            self._collections[name] = _FallbackCollection(name)
        return self._collections[name]

    def list_collections(self):
        return list(self._collections.values())

    def reset(self):
        self._collections.clear()


def _get_chroma_client(persist_directory: str) -> Any:
    """Get or create a ChromaDB client for a persist directory."""
    resolved_directory = str(Path(persist_directory).resolve())
    if resolved_directory not in _chroma_clients:
        if CHROMADB_AVAILABLE:
            _chroma_clients[resolved_directory] = chromadb.PersistentClient(
                path=resolved_directory, settings=Settings(anonymized_telemetry=False, allow_reset=True)
            )
        else:
            _chroma_clients[resolved_directory] = _FallbackClient()
    return _chroma_clients[resolved_directory]


class VectorStore:
    """Interface to ChromaDB for semantic memory storage"""

    # Collection names
    COLLECTION_TEST_PATTERNS = "test_patterns"
    COLLECTION_APPLICATION_ELEMENTS = "application_elements"
    COLLECTION_TEST_IDEAS = "test_ideas"
    COLLECTION_PRD_CHUNKS = "prd_chunks"
    COLLECTION_SIMILAR_TESTS = "similar_tests"
    COLLECTION_AGENT_MEMORIES = "agent_memories"

    def __init__(self, persist_directory: str | None = None, project_id: str | None = None):
        """
        Initialize the vector store.

        Args:
            persist_directory: Directory to persist ChromaDB data
        """
        config = get_config()

        # Use configured persist directory
        self.persist_directory = persist_directory or config.persist_directory
        self.project_id = project_id if project_id is not None else config.project_id
        Path(self.persist_directory).mkdir(parents=True, exist_ok=True)

        # Use global ChromaDB client singleton
        self.client = _get_chroma_client(self.persist_directory)

        # Get embedding client for custom function
        self.embedding_client = get_embedding_client()

        # Custom embedding function that uses OpenAI
        class OpenAIEmbeddingFunction(embedding_functions.EmbeddingFunction):
            def __init__(self, embedding_client):
                self.embedding_client = embedding_client

            def __call__(self, input: list[str]) -> list[list[float]]:
                return self.embedding_client.embed_batch(input)

        self.embedding_function = OpenAIEmbeddingFunction(self.embedding_client)

    def _get_collection_name(self, base_name: str) -> str:
        """Get collection name with project isolation from this store instance."""
        config = get_config()
        parts = [config.collection_prefix]
        if self.project_id:
            parts.append(self.project_id)
        parts.append(base_name)
        return "_".join(parts)

    def get_or_create_collection(self, name: str):
        """
        Get or create a collection.

        Args:
            name: Base collection name

        Returns:
            ChromaDB collection
        """
        collection_name = self._get_collection_name(name)

        # Use get_or_create_collection to ensure embedding function is always applied
        collection = self.client.get_or_create_collection(
            name=collection_name, embedding_function=self.embedding_function, metadata={"hnsw:space": "cosine"}
        )

        return collection

    def add_test_pattern(
        self, pattern_id: str, description: str, metadata: dict[str, Any], test_name: str = None
    ) -> str:
        """
        Add a test pattern to the vector store.

        Args:
            pattern_id: Unique identifier for the pattern
            description: Text description for embedding
            metadata: Associated metadata (action, selector, success_rate, etc.)
            test_name: Optional test name

        Returns:
            The pattern_id
        """
        collection = self.get_or_create_collection(self.COLLECTION_TEST_PATTERNS)

        # Generate document text for embedding
        document = f"{test_name or ''}: {description}".strip()

        # Ensure metadata has at least one key (ChromaDB requirement)
        if not metadata:
            metadata = {"_placeholder": True}

        collection.add(ids=[pattern_id], documents=[document], metadatas=[metadata])

        return pattern_id

    def add_application_element(self, element_id: str, description: str, metadata: dict[str, Any]) -> str:
        """
        Add a discovered application element to the vector store.

        Args:
            element_id: Unique identifier for the element
            description: Text description for embedding
            metadata: Element metadata (url, selector, attributes, etc.)

        Returns:
            The element_id
        """
        collection = self.get_or_create_collection(self.COLLECTION_APPLICATION_ELEMENTS)

        # Ensure metadata has at least one key (ChromaDB requirement)
        if not metadata:
            metadata = {"_placeholder": True}

        collection.add(ids=[element_id], documents=[description], metadatas=[metadata])

        return element_id

    def add_test_idea(self, idea_id: str, description: str, metadata: dict[str, Any]) -> str:
        """
        Add a test idea to the vector store.

        Args:
            idea_id: Unique identifier for the idea
            description: Text description for embedding
            metadata: Idea metadata (priority, category, complexity, etc.)

        Returns:
            The idea_id
        """
        collection = self.get_or_create_collection(self.COLLECTION_TEST_IDEAS)

        # Ensure metadata has at least one key (ChromaDB requirement)
        if not metadata:
            metadata = {"_placeholder": True}

        collection.add(ids=[idea_id], documents=[description], metadatas=[metadata])

        return idea_id

    def get_all_test_ideas(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        Get all stored test ideas with optional metadata filtering.

        Args:
            filters: Optional metadata filters

        Returns:
            List of stored test ideas
        """
        collection = self.get_or_create_collection(self.COLLECTION_TEST_IDEAS)
        results = collection.get(where=filters, include=["documents", "metadatas"])

        ideas = []
        if results["ids"]:
            for i, idea_id in enumerate(results["ids"]):
                ideas.append(
                    {
                        "id": idea_id,
                        "document": results["documents"][i] if results["documents"] else None,
                        "metadata": results["metadatas"][i] if results["metadatas"] else {},
                    }
                )

        return ideas

    def search_test_ideas(
        self, query: str, n_results: int = 10, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """
        Search stored test ideas.

        Args:
            query: Search query text
            n_results: Number of results to return
            filters: Optional metadata filters

        Returns:
            List of matching test ideas
        """
        collection = self.get_or_create_collection(self.COLLECTION_TEST_IDEAS)
        results = collection.query(query_texts=[query], n_results=n_results, where=filters)

        ideas = []
        if results["ids"] and results["ids"][0]:
            for i, idea_id in enumerate(results["ids"][0]):
                ideas.append(
                    {
                        "id": idea_id,
                        "document": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i] if "distances" in results else None,
                    }
                )

        return ideas

    def search_similar_patterns(
        self, query: str, n_results: int = 5, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """
        Search for similar test patterns.

        Args:
            query: Search query text
            n_results: Number of results to return
            filters: Optional metadata filters

        Returns:
            List of similar patterns with metadata
        """
        collection = self.get_or_create_collection(self.COLLECTION_TEST_PATTERNS)

        results = collection.query(query_texts=[query], n_results=n_results, where=filters)

        patterns = []
        if results["ids"] and results["ids"][0]:
            for i, pattern_id in enumerate(results["ids"][0]):
                patterns.append(
                    {
                        "id": pattern_id,
                        "document": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i] if "distances" in results else None,
                    }
                )

        return patterns

    def search_similar_elements(
        self, query: str, n_results: int = 5, url_filter: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Search for similar application elements.

        Args:
            query: Search query text
            n_results: Number of results to return
            url_filter: Optional URL to filter by

        Returns:
            List of similar elements with metadata
        """
        collection = self.get_or_create_collection(self.COLLECTION_APPLICATION_ELEMENTS)

        where = {"url": url_filter} if url_filter else None

        results = collection.query(query_texts=[query], n_results=n_results, where=where)

        elements = []
        if results["ids"] and results["ids"][0]:
            for i, element_id in enumerate(results["ids"][0]):
                elements.append(
                    {
                        "id": element_id,
                        "document": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i] if "distances" in results else None,
                    }
                )

        return elements

    def get_successful_selectors(
        self, element_description: str, min_success_rate: float = 0.7, n_results: int = 10
    ) -> list[dict[str, Any]]:
        """
        Get successful selectors for a similar element.

        Args:
            element_description: Description of the element
            min_success_rate: Minimum success rate for selectors
            n_results: Number of results to return

        Returns:
            List of successful selector patterns
        """
        # Search for similar patterns with high success rate
        patterns = self.search_similar_patterns(query=element_description, n_results=n_results)

        # Filter by success rate
        successful = [p for p in patterns if p["metadata"].get("success_rate", 0) >= min_success_rate]

        return successful

    def get_all_patterns(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        Get all test patterns with optional filtering.

        Args:
            filters: Optional metadata filters

        Returns:
            List of all patterns
        """
        collection = self.get_or_create_collection(self.COLLECTION_TEST_PATTERNS)

        results = collection.get(where=filters, include=["documents", "metadatas"])

        patterns = []
        if results["ids"]:
            for i, pattern_id in enumerate(results["ids"]):
                patterns.append(
                    {
                        "id": pattern_id,
                        "document": results["documents"][i] if results["documents"] else None,
                        "metadata": results["metadatas"][i] if results["metadatas"] else {},
                    }
                )

        return patterns

    def update_pattern_stats(self, pattern_id: str, success: bool, duration_ms: int) -> None:
        """
        Update statistics for a test pattern.

        Args:
            pattern_id: Pattern identifier
            success: Whether the pattern succeeded
            duration_ms: Execution duration in milliseconds
        """
        collection = self.get_or_create_collection(self.COLLECTION_TEST_PATTERNS)

        # Get current metadata
        results = collection.get(ids=[pattern_id], include=["metadatas"])

        if not results["ids"]:
            return

        current_metadata = results["metadatas"][0] if results["metadatas"] else {}

        # Update stats
        success_count = current_metadata.get("success_count", 0) + (1 if success else 0)
        failure_count = current_metadata.get("failure_count", 0) + (0 if success else 1)
        total_count = success_count + failure_count
        success_rate = success_count / total_count if total_count > 0 else 0

        # Update average duration
        avg_duration = current_metadata.get("avg_duration", 0)
        if avg_duration > 0:
            avg_duration = (avg_duration + duration_ms) / 2
        else:
            avg_duration = duration_ms

        updated_metadata = {
            **current_metadata,
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": success_rate,
            "avg_duration": avg_duration,
        }

        collection.update(ids=[pattern_id], metadatas=[updated_metadata])

    def delete_pattern(self, pattern_id: str) -> None:
        """
        Delete a test pattern.

        Args:
            pattern_id: Pattern identifier
        """
        collection = self.get_or_create_collection(self.COLLECTION_TEST_PATTERNS)
        collection.delete(ids=[pattern_id])

    def clear_collection(self, collection_name: str) -> None:
        """
        Clear all items from a collection.

        Args:
            collection_name: Name of collection to clear
        """
        collection = self.get_or_create_collection(collection_name)

        # Get all IDs
        results = collection.get()
        if results["ids"]:
            collection.delete(ids=results["ids"])

    def reset(self) -> None:
        """Reset the entire vector store (delete all collections)"""
        self.client.reset()

    def add_prd_chunk(self, chunk_id: str, content: str, metadata: dict[str, Any]) -> str:
        """
        Add a PRD chunk to the vector store.

        Args:
            chunk_id: Unique identifier for the chunk
            content: Text content for embedding and storage
            metadata: Chunk metadata (feature, section, type, etc.)

        Returns:
            The chunk_id
        """
        collection = self.get_or_create_collection(self.COLLECTION_PRD_CHUNKS)

        # Ensure metadata has at least one key
        if not metadata:
            metadata = {"_placeholder": True}

        collection.add(ids=[chunk_id], documents=[content], metadatas=[metadata])

        return chunk_id

    def search_prd_context(self, query: str, project_id: str | None = None, n_results: int = 5) -> list[dict[str, Any]]:
        """
        Search for relevant PRD chunks.

        Args:
            query: Search query text
            project_id: Optional project ID to filter by
            n_results: Number of results to return

        Returns:
            List of relevant chunks with metadata
        """
        collection = self.get_or_create_collection(self.COLLECTION_PRD_CHUNKS)

        results = collection.query(query_texts=[query], n_results=n_results)

        # Format results
        hits = []
        if results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                hits.append(
                    {
                        "id": chunk_id,
                        "content": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i] if "distances" in results else None,
                    }
                )

        return hits

    def add_agent_memory(self, memory_id: str, content: str, metadata: dict[str, Any]) -> str:
        """Add or update an agent working-memory search document."""
        collection = self.get_or_create_collection(self.COLLECTION_AGENT_MEMORIES)
        metadata = metadata or {"_placeholder": True}
        existing = collection.get(ids=[memory_id], include=["metadatas"])
        if existing.get("ids"):
            collection.update(ids=[memory_id], documents=[content], metadatas=[metadata])
        else:
            collection.add(ids=[memory_id], documents=[content], metadatas=[metadata])
        return memory_id

    def search_agent_memories(
        self, query: str, n_results: int = 8, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Search agent working memories by semantic similarity."""
        collection = self.get_or_create_collection(self.COLLECTION_AGENT_MEMORIES)
        results = collection.query(query_texts=[query], n_results=n_results, where=filters)

        memories = []
        if results["ids"] and results["ids"][0]:
            for i, memory_id in enumerate(results["ids"][0]):
                memories.append(
                    {
                        "id": memory_id,
                        "document": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i] if "distances" in results else None,
                    }
                )
        return memories

    def delete_agent_memory(self, memory_id: str) -> None:
        """Delete an agent working-memory search document."""
        collection = self.get_or_create_collection(self.COLLECTION_AGENT_MEMORIES)
        collection.delete(ids=[memory_id])


# Global vector store instances keyed by persist directory and project.
_vector_store: VectorStore | None = None
_vector_stores: dict[tuple[str, str | None], VectorStore] = {}


def get_vector_store(project_id: str | None = None) -> VectorStore:
    """Get a vector store instance for an explicit project context."""
    global _vector_store
    config = get_config()
    effective_project_id = project_id if project_id is not None else config.project_id
    key = (str(Path(config.persist_directory).resolve()), effective_project_id)
    store = _vector_stores.get(key)
    if store is None:
        store = VectorStore(project_id=effective_project_id)
        _vector_stores[key] = store
    _vector_store = store
    return store
