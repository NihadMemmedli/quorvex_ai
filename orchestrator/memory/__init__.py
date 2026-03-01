"""
Memory System for AI Test Automation

This package provides persistent memory capabilities for the AI agent,
including:
- Vector store for semantic similarity (ChromaDB)
- Graph store for application structure (NetworkX)
- Pattern extraction and retrieval
- Coverage tracking
- Exploration data storage
- Requirements and RTM management
"""

from .config import MemoryConfig
from .exploration_store import ExplorationStore, get_exploration_store
from .graph_store import GraphStore
from .manager import MemoryManager, get_memory_manager

__all__ = [
    "MemoryManager",
    "get_memory_manager",
    "MemoryConfig",
    "GraphStore",
    "ExplorationStore",
    "get_exploration_store",
]
__version__ = "0.1.0"
