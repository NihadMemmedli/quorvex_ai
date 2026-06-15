"""Shared helpers for BrowserResourcePool slot acquisition."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

try:
    from services.browser_pool import OperationType, get_browser_pool
except ImportError:  # pragma: no cover - package-only imports in unit tests
    from orchestrator.services.browser_pool import OperationType, get_browser_pool

logger = logging.getLogger(__name__)


class BrowserSlotAcquisitionError(TimeoutError):
    """Raised when a browser-producing operation cannot acquire pool capacity."""


@asynccontextmanager
async def browser_operation_slot(
    *,
    request_id: str,
    operation_type: OperationType,
    description: str = "",
    timeout: float | None = None,
    max_operation_duration: int | None = None,
    cleanup_stale_minutes: int | None = 60,
):
    """Acquire a global browser slot and release it safely on exit."""

    pool = await get_browser_pool()
    if cleanup_stale_minutes is not None:
        try:
            await pool.cleanup_stale(max_age_minutes=cleanup_stale_minutes)
        except Exception as exc:
            logger.debug("Browser slot stale cleanup failed before %s: %s", request_id, exc)

    async with pool.browser_slot(
        request_id=request_id,
        operation_type=operation_type,
        description=description,
        timeout=timeout,
        max_operation_duration=max_operation_duration,
    ) as acquired:
        if not acquired:
            raise BrowserSlotAcquisitionError(f"Timeout waiting for browser slot for {description or request_id}")
        yield
