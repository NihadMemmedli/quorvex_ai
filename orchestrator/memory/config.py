"""
Configuration for Memory System

Handles environment variables and settings for vector store, embeddings,
and memory persistence.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MemoryConfig:
    """Configuration for the memory system"""

    # Vector Store (ChromaDB)
    chroma_host: str = field(default_factory=lambda: os.getenv("CHROMADB_HOST", "localhost"))
    chroma_port: int = field(default_factory=lambda: int(os.getenv("CHROMADB_PORT", "8000")))
    persist_directory: str = field(
        default_factory=lambda: os.getenv(
            "CHROMADB_PERSIST_DIRECTORY", str(Path(__file__).parent.parent.parent / "data" / "chromadb")
        )
    )

    # Embeddings
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"))
    embedding_dimension: int = field(default_factory=lambda: int(os.getenv("EMBEDDING_DIMENSION", "1536")))

    # OpenAI API for embeddings
    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    anthropic_api_key: str | None = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))

    # Memory Settings
    memory_enabled: bool = field(default_factory=lambda: os.getenv("MEMORY_ENABLED", "true").lower() == "true")
    retention_days: int = field(default_factory=lambda: int(os.getenv("MEMORY_RETENTION_DAYS", "365")))
    collection_prefix: str = field(default_factory=lambda: os.getenv("MEMORY_COLLECTION_PREFIX", "test_automation"))

    # Project Isolation
    project_id: str | None = None  # Set dynamically based on current project

    # Coverage Settings
    coverage_enabled: bool = field(default_factory=lambda: os.getenv("COVERAGE_ENABLED", "true").lower() == "true")
    coverage_threshold: float = field(default_factory=lambda: float(os.getenv("COVERAGE_THRESHOLD", "0.8")))

    def __post_init__(self):
        """Ensure persist directory exists"""
        if self.persist_directory:
            Path(self.persist_directory).mkdir(parents=True, exist_ok=True)

    def get_collection_name(self, base_name: str) -> str:
        """
        Get a collection name with project isolation.

        Args:
            base_name: Base collection name (e.g., "test_patterns")

        Returns:
            Collection name with project prefix
        """
        parts = [self.collection_prefix]
        if self.project_id:
            parts.append(self.project_id)
        parts.append(base_name)
        return "_".join(parts)


# Global config instance
_config: MemoryConfig | None = None


def get_config() -> MemoryConfig:
    """Get the global memory configuration"""
    global _config
    if _config is None:
        _config = MemoryConfig()
    return _config


def set_config(config: MemoryConfig):
    """Set the global memory configuration"""
    global _config
    _config = config


def set_project(project_id: str):
    """Set the current project ID for isolation"""
    config = get_config()
    config.project_id = project_id
