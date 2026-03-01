"""
Resource Manager Service

Centralized management of concurrent resource usage across the application.
Provides semaphore-based queuing for:
- Agent runs (browser automation)
- Exploration sessions
- PRD processing

This prevents resource exhaustion when many users simultaneously request
resource-intensive operations.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ResourceType(Enum):
    """Types of resources that can be managed."""

    AGENT = "agent"
    EXPLORATION = "exploration"
    PRD = "prd"


@dataclass
class QueuedRequest:
    """Represents a request waiting in queue."""

    request_id: str
    resource_type: ResourceType
    queued_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceStatus:
    """Status of a resource pool."""

    active: int
    max_slots: int
    queued: int
    queue_positions: dict[str, int] = field(default_factory=dict)  # request_id -> position


class ResourceManager:
    """
    Centralized resource management for concurrent operations.

    Provides semaphore-based queuing to prevent resource exhaustion
    when multiple users request resource-intensive operations simultaneously.

    Usage:
        manager = await ResourceManager.get_instance()

        # Try to acquire a slot (non-blocking check)
        if await manager.try_acquire_agent_slot(request_id):
            try:
                # Do work...
            finally:
                await manager.release_agent_slot(request_id)
        else:
            position = manager.get_queue_position(ResourceType.AGENT, request_id)
            # Return queued status with position

    Configuration via environment variables:
        MAX_CONCURRENT_AGENTS: Default 8
        MAX_CONCURRENT_EXPLORATIONS: Default 5
        MAX_CONCURRENT_PRD: Default 3
        AGENT_TIMEOUT_MINUTES: Default 60
        EXPLORATION_TIMEOUT_MINUTES: Default 30
        PRD_TIMEOUT_MINUTES: Default 10
    """

    _instance: Optional["ResourceManager"] = None
    _lock: asyncio.Lock = None

    def __init__(self):
        # Semaphores for each resource type
        self._agent_semaphore: asyncio.Semaphore | None = None
        self._exploration_semaphore: asyncio.Semaphore | None = None
        self._prd_semaphore: asyncio.Semaphore | None = None

        # Configuration
        self._max_agents: int = 8
        self._max_explorations: int = 5
        self._max_prd: int = 3

        # Timeouts (minutes)
        self._agent_timeout: int = 60
        self._exploration_timeout: int = 30
        self._prd_timeout: int = 10

        # Track active and queued requests
        self._active_agents: dict[str, datetime] = {}  # request_id -> started_at
        self._active_explorations: dict[str, datetime] = {}
        self._active_prd: dict[str, datetime] = {}

        # Queue tracking for position reporting
        self._agent_queue: list[QueuedRequest] = []
        self._exploration_queue: list[QueuedRequest] = []
        self._prd_queue: list[QueuedRequest] = []

        # Locks for thread-safe queue operations
        self._queue_lock: asyncio.Lock | None = None

        self._initialized = False

    @classmethod
    async def get_instance(cls) -> "ResourceManager":
        """Get or create the singleton ResourceManager instance."""
        if cls._lock is None:
            cls._lock = asyncio.Lock()

        async with cls._lock:
            if cls._instance is None:
                cls._instance = ResourceManager()
                await cls._instance.initialize()
            return cls._instance

    @classmethod
    def get_instance_sync(cls) -> Optional["ResourceManager"]:
        """Get existing instance synchronously (may be None if not initialized)."""
        return cls._instance

    async def initialize(self):
        """Initialize the resource manager from environment variables."""
        if self._initialized:
            return

        # Read configuration from environment
        self._max_agents = int(os.environ.get("MAX_CONCURRENT_AGENTS", "8"))
        self._max_explorations = int(os.environ.get("MAX_CONCURRENT_EXPLORATIONS", "5"))
        self._max_prd = int(os.environ.get("MAX_CONCURRENT_PRD", "3"))

        self._agent_timeout = int(os.environ.get("AGENT_TIMEOUT_MINUTES", "60"))
        self._exploration_timeout = int(os.environ.get("EXPLORATION_TIMEOUT_MINUTES", "30"))
        self._prd_timeout = int(os.environ.get("PRD_TIMEOUT_MINUTES", "10"))

        # Initialize semaphores
        self._agent_semaphore = asyncio.Semaphore(self._max_agents)
        self._exploration_semaphore = asyncio.Semaphore(self._max_explorations)
        self._prd_semaphore = asyncio.Semaphore(self._max_prd)

        # Initialize queue lock
        self._queue_lock = asyncio.Lock()

        self._initialized = True

        logger.info(
            f"ResourceManager initialized: "
            f"agents={self._max_agents}, "
            f"explorations={self._max_explorations}, "
            f"prd={self._max_prd}"
        )

    async def reload_config(self):
        """Reload configuration from environment (for dynamic updates)."""
        new_max_agents = int(os.environ.get("MAX_CONCURRENT_AGENTS", "8"))
        new_max_explorations = int(os.environ.get("MAX_CONCURRENT_EXPLORATIONS", "5"))
        new_max_prd = int(os.environ.get("MAX_CONCURRENT_PRD", "3"))

        # Only recreate semaphores if limits changed
        if new_max_agents != self._max_agents:
            self._max_agents = new_max_agents
            self._agent_semaphore = asyncio.Semaphore(self._max_agents)
            logger.info(f"Agent limit updated to {self._max_agents}")

        if new_max_explorations != self._max_explorations:
            self._max_explorations = new_max_explorations
            self._exploration_semaphore = asyncio.Semaphore(self._max_explorations)
            logger.info(f"Exploration limit updated to {self._max_explorations}")

        if new_max_prd != self._max_prd:
            self._max_prd = new_max_prd
            self._prd_semaphore = asyncio.Semaphore(self._max_prd)
            logger.info(f"PRD limit updated to {self._max_prd}")

    # ==================== Agent Slots ====================

    async def try_acquire_agent_slot(self, request_id: str, timeout: float = 0) -> bool:
        """
        Try to acquire an agent slot.

        Args:
            request_id: Unique identifier for this request
            timeout: How long to wait (0 = non-blocking check)

        Returns:
            True if slot acquired, False if would need to wait
        """
        try:
            acquired = await asyncio.wait_for(
                self._agent_semaphore.acquire(), timeout=timeout if timeout > 0 else 0.001
            )
            if acquired:
                self._active_agents[request_id] = datetime.now(timezone.utc)
                # Remove from queue if present
                await self._remove_from_queue(ResourceType.AGENT, request_id)
                logger.debug(f"Agent slot acquired: {request_id}")
                return True
        except asyncio.TimeoutError:
            pass
        return False

    async def acquire_agent_slot(self, request_id: str) -> bool:
        """
        Acquire an agent slot, waiting if necessary.

        Args:
            request_id: Unique identifier for this request

        Returns:
            True when slot is acquired
        """
        # Add to queue for position tracking
        await self._add_to_queue(ResourceType.AGENT, request_id)

        await self._agent_semaphore.acquire()
        self._active_agents[request_id] = datetime.now(timezone.utc)

        # Remove from queue
        await self._remove_from_queue(ResourceType.AGENT, request_id)
        logger.debug(f"Agent slot acquired (after wait): {request_id}")
        return True

    async def release_agent_slot(self, request_id: str):
        """Release an agent slot."""
        if request_id in self._active_agents:
            del self._active_agents[request_id]
            self._agent_semaphore.release()
            logger.debug(f"Agent slot released: {request_id}")

    def get_agent_status(self) -> ResourceStatus:
        """Get current agent resource status."""
        return ResourceStatus(
            active=len(self._active_agents),
            max_slots=self._max_agents,
            queued=len(self._agent_queue),
            queue_positions={req.request_id: idx + 1 for idx, req in enumerate(self._agent_queue)},
        )

    # ==================== Exploration Slots ====================

    async def try_acquire_exploration_slot(self, request_id: str, timeout: float = 0) -> bool:
        """Try to acquire an exploration slot."""
        try:
            acquired = await asyncio.wait_for(
                self._exploration_semaphore.acquire(), timeout=timeout if timeout > 0 else 0.001
            )
            if acquired:
                self._active_explorations[request_id] = datetime.now(timezone.utc)
                await self._remove_from_queue(ResourceType.EXPLORATION, request_id)
                logger.debug(f"Exploration slot acquired: {request_id}")
                return True
        except asyncio.TimeoutError:
            pass
        return False

    async def acquire_exploration_slot(self, request_id: str) -> bool:
        """Acquire an exploration slot, waiting if necessary."""
        await self._add_to_queue(ResourceType.EXPLORATION, request_id)

        await self._exploration_semaphore.acquire()
        self._active_explorations[request_id] = datetime.now(timezone.utc)

        await self._remove_from_queue(ResourceType.EXPLORATION, request_id)
        logger.debug(f"Exploration slot acquired (after wait): {request_id}")
        return True

    async def release_exploration_slot(self, request_id: str):
        """Release an exploration slot."""
        if request_id in self._active_explorations:
            del self._active_explorations[request_id]
            self._exploration_semaphore.release()
            logger.debug(f"Exploration slot released: {request_id}")

    def get_exploration_status(self) -> ResourceStatus:
        """Get current exploration resource status."""
        return ResourceStatus(
            active=len(self._active_explorations),
            max_slots=self._max_explorations,
            queued=len(self._exploration_queue),
            queue_positions={req.request_id: idx + 1 for idx, req in enumerate(self._exploration_queue)},
        )

    # ==================== PRD Slots ====================

    async def try_acquire_prd_slot(self, request_id: str, timeout: float = 0) -> bool:
        """Try to acquire a PRD processing slot."""
        try:
            acquired = await asyncio.wait_for(self._prd_semaphore.acquire(), timeout=timeout if timeout > 0 else 0.001)
            if acquired:
                self._active_prd[request_id] = datetime.now(timezone.utc)
                await self._remove_from_queue(ResourceType.PRD, request_id)
                logger.debug(f"PRD slot acquired: {request_id}")
                return True
        except asyncio.TimeoutError:
            pass
        return False

    async def acquire_prd_slot(self, request_id: str) -> bool:
        """Acquire a PRD processing slot, waiting if necessary."""
        await self._add_to_queue(ResourceType.PRD, request_id)

        await self._prd_semaphore.acquire()
        self._active_prd[request_id] = datetime.now(timezone.utc)

        await self._remove_from_queue(ResourceType.PRD, request_id)
        logger.debug(f"PRD slot acquired (after wait): {request_id}")
        return True

    async def release_prd_slot(self, request_id: str):
        """Release a PRD processing slot."""
        if request_id in self._active_prd:
            del self._active_prd[request_id]
            self._prd_semaphore.release()
            logger.debug(f"PRD slot released: {request_id}")

    def get_prd_status(self) -> ResourceStatus:
        """Get current PRD resource status."""
        return ResourceStatus(
            active=len(self._active_prd),
            max_slots=self._max_prd,
            queued=len(self._prd_queue),
            queue_positions={req.request_id: idx + 1 for idx, req in enumerate(self._prd_queue)},
        )

    # ==================== Queue Management ====================

    async def _add_to_queue(self, resource_type: ResourceType, request_id: str, metadata: dict = None):
        """Add a request to the appropriate queue."""
        async with self._queue_lock:
            queue = self._get_queue(resource_type)
            # Don't add duplicates
            if not any(r.request_id == request_id for r in queue):
                queue.append(
                    QueuedRequest(
                        request_id=request_id,
                        resource_type=resource_type,
                        queued_at=datetime.now(timezone.utc),
                        metadata=metadata or {},
                    )
                )

    async def _remove_from_queue(self, resource_type: ResourceType, request_id: str):
        """Remove a request from the appropriate queue."""
        async with self._queue_lock:
            queue = self._get_queue(resource_type)
            queue[:] = [r for r in queue if r.request_id != request_id]

    def _get_queue(self, resource_type: ResourceType) -> list[QueuedRequest]:
        """Get the queue list for a resource type."""
        if resource_type == ResourceType.AGENT:
            return self._agent_queue
        elif resource_type == ResourceType.EXPLORATION:
            return self._exploration_queue
        elif resource_type == ResourceType.PRD:
            return self._prd_queue
        raise ValueError(f"Unknown resource type: {resource_type}")

    def get_queue_position(self, resource_type: ResourceType, request_id: str) -> int | None:
        """Get the queue position for a request (1-indexed)."""
        queue = self._get_queue(resource_type)
        for idx, req in enumerate(queue):
            if req.request_id == request_id:
                return idx + 1
        return None

    # ==================== Overall Status ====================

    def get_full_status(self) -> dict[str, Any]:
        """Get complete resource status for all resource types."""
        agent_status = self.get_agent_status()
        exploration_status = self.get_exploration_status()
        prd_status = self.get_prd_status()

        return {
            "agent_queue": {
                "active": agent_status.active,
                "max": agent_status.max_slots,
                "queued": agent_status.queued,
                "available": max(0, agent_status.max_slots - agent_status.active),
            },
            "exploration_queue": {
                "active": exploration_status.active,
                "max": exploration_status.max_slots,
                "queued": exploration_status.queued,
                "available": max(0, exploration_status.max_slots - exploration_status.active),
            },
            "prd_queue": {
                "active": prd_status.active,
                "max": prd_status.max_slots,
                "queued": prd_status.queued,
                "available": max(0, prd_status.max_slots - prd_status.active),
            },
            "limits": {
                "max_concurrent_agents": self._max_agents,
                "max_concurrent_explorations": self._max_explorations,
                "max_concurrent_prd": self._max_prd,
                "agent_timeout_minutes": self._agent_timeout,
                "exploration_timeout_minutes": self._exploration_timeout,
                "prd_timeout_minutes": self._prd_timeout,
            },
        }

    # ==================== Cleanup & Monitoring ====================

    async def cleanup_stale_slots(self):
        """
        Release slots for requests that have exceeded their timeout.
        Should be called periodically (e.g., every minute).
        """
        now = datetime.now(timezone.utc)
        cleaned = []

        # Check agents
        agent_timeout_seconds = self._agent_timeout * 60
        for request_id, started_at in list(self._active_agents.items()):
            if (now - started_at).total_seconds() > agent_timeout_seconds:
                await self.release_agent_slot(request_id)
                cleaned.append(f"agent:{request_id}")

        # Check explorations
        exploration_timeout_seconds = self._exploration_timeout * 60
        for request_id, started_at in list(self._active_explorations.items()):
            if (now - started_at).total_seconds() > exploration_timeout_seconds:
                await self.release_exploration_slot(request_id)
                cleaned.append(f"exploration:{request_id}")

        # Check PRD
        prd_timeout_seconds = self._prd_timeout * 60
        for request_id, started_at in list(self._active_prd.items()):
            if (now - started_at).total_seconds() > prd_timeout_seconds:
                await self.release_prd_slot(request_id)
                cleaned.append(f"prd:{request_id}")

        if cleaned:
            logger.warning(f"Cleaned up stale slots: {cleaned}")

        return cleaned

    def is_slot_available(self, resource_type: ResourceType) -> bool:
        """Check if a slot is immediately available (without waiting)."""
        if resource_type == ResourceType.AGENT:
            return len(self._active_agents) < self._max_agents
        elif resource_type == ResourceType.EXPLORATION:
            return len(self._active_explorations) < self._max_explorations
        elif resource_type == ResourceType.PRD:
            return len(self._active_prd) < self._max_prd
        return False


# Convenience function to get the singleton instance
async def get_resource_manager() -> ResourceManager:
    """Get the ResourceManager singleton instance."""
    return await ResourceManager.get_instance()
