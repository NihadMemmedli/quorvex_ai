"""Agent compatibility exports for the legacy main module facade."""

from __future__ import annotations

import sys
from typing import Any

from . import agent_facade_support


def configure_main_agent_facade(namespace: dict[str, Any]) -> None:
    """Configure agent helpers for the main facade."""

    def _agent_compat_runtime():
        return sys.modules[namespace["__name__"]]

    agent_facade_support.configure_agent_facade(_agent_compat_runtime, namespace)

    namespace.update(
        {
            "_agent_compat_runtime": _agent_compat_runtime,
            "agent_facade_support": agent_facade_support,
        }
    )
