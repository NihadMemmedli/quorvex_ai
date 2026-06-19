"""Lifecycle event compatibility exports for the legacy main module facade."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from . import runtime_lifecycle_support

RuntimeFactory = Callable[[], Any]


def configure_main_lifecycle_event_facade(
    app: FastAPI, runtime_factory: RuntimeFactory, namespace: dict[str, Any]
) -> None:
    """Register app lifecycle events and publish main-module compatibility exports."""

    async def startup_event():
        await runtime_lifecycle_support.startup(runtime_factory())

    async def shutdown_event():
        """Gracefully shut down all running processes."""
        await runtime_lifecycle_support.shutdown(runtime_factory())

    app.on_event("startup")(startup_event)
    app.on_event("shutdown")(shutdown_event)

    namespace.update(
        {
            "startup_event": startup_event,
            "shutdown_event": shutdown_event,
        }
    )
