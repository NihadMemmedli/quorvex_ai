"""FastAPI app wiring compatibility exports for the legacy main module facade."""

from __future__ import annotations

import sys
from typing import Any

from fastapi import FastAPI

from . import app_wiring_support


def configure_main_app_wiring_facade(namespace: dict[str, Any]) -> None:
    """Create and wire the main FastAPI app, then publish legacy exports."""

    def _main_runtime():
        return sys.modules[namespace["__name__"]]

    app = FastAPI(title="Quorvex AI API")
    app_wiring_support.configure_app(_main_runtime(), app)

    namespace.update(
        {
            "FastAPI": FastAPI,
            "_main_runtime": _main_runtime,
            "app": app,
            "app_wiring_support": app_wiring_support,
        }
    )
