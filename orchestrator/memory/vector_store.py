"""
Vector Store Module

Provides interface to ChromaDB for storing and retrieving vectors
with semantic search capabilities.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

from .config import get_config
from .embeddings import get_embedding_client

# Global ChromaDB client singleton (shared across all VectorStore instances)
_chroma_client: chromadb.PersistentClient | None = None


def _get_chroma_client(persist_directory: str) -> chromadb.PersistentClient:
    """Get or create the global ChromaDB client"""
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path=str(persist_directory), settings=Settings(anonymized_telemetry=False, allow_reset=True)
        )
    return _chroma_client


class VectorStore:
    """Interface to ChromaDB for semantic memory storage"""

    # Collection names
    COLLECTION_TEST_PATTERNS = "test_patterns"
    COLLECTION_APPLICATION_ELEMENTS = "application_elements"
    COLLECTION_TEST_IDEAS = "test_ideas"
    COLLECTION_PRD_CHUNKS = "prd_chunks"
    COLLECTION_SIMILAR_TESTS = "similar_tests"

    def __init__(self, persist_directory: str | None = None):
        """
        Initialize the vector store.

        Args:
            persist_directory: Directory to persist ChromaDB data
        """
        config = get_config()

        # Use configured persist directory
        self.persist_directory = persist_directory or config.persist_directory
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
        """Get collection name with project isolation - always uses current global config"""
        config = get_config()  # Get fresh config to handle project_id changes
        return config.get_collection_name(base_name)

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


# Global vector store instance
_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Get the global vector store instance"""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
