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

__all__ = [
    "MemoryManager",
    "get_memory_manager",
    "MemoryConfig",
    "GraphStore",
    "ExplorationStore",
    "get_exploration_store",
    "AgentMemoryService",
    "get_agent_memory_service",
]
__version__ = "0.1.0"


def __getattr__(name):
    if name in {"MemoryManager", "get_memory_manager"}:
        from .manager import MemoryManager, get_memory_manager

        return {"MemoryManager": MemoryManager, "get_memory_manager": get_memory_manager}[name]
    if name in {"AgentMemoryService", "get_agent_memory_service"}:
        from .agent_memory import AgentMemoryService, get_agent_memory_service

        return {
            "AgentMemoryService": AgentMemoryService,
            "get_agent_memory_service": get_agent_memory_service,
        }[name]
    if name in {"vector_store", "graph_store", "manager", "config"}:
        import importlib

        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
