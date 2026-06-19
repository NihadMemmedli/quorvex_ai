"""Test-run and lifecycle compatibility exports for the legacy main module facade."""

from __future__ import annotations

import sys
from typing import Any

from . import main_lifecycle_event_facade_support, test_run_facade_support


def configure_main_test_lifecycle_facade(namespace: dict[str, Any]) -> None:
    """Configure test-run helpers and app lifecycle events for the main facade."""

    def _test_run_runtime():
        return sys.modules[namespace["__name__"]]

    app = namespace["app"]
    test_run_facade_support.configure_test_run_facade(_test_run_runtime, namespace)
    main_lifecycle_event_facade_support.configure_main_lifecycle_event_facade(
        app,
        _test_run_runtime,
        namespace,
    )

    namespace.update(
        {
            "_test_run_runtime": _test_run_runtime,
            "test_run_facade_support": test_run_facade_support,
            "main_lifecycle_event_facade_support": main_lifecycle_event_facade_support,
        }
    )
