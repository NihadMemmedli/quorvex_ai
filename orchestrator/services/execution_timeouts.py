"""Shared timeout settings for long AI pipeline work."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

logger = logging.getLogger(__name__)

DEFAULT_AI_PIPELINE_TIMEOUT_SECONDS = 7200
MIN_AI_PIPELINE_TIMEOUT_SECONDS = 900
MAX_AI_PIPELINE_TIMEOUT_SECONDS = 86400
DEFAULT_TEST_RUN_QUEUE_WAIT_TIMEOUT_SECONDS = 86400
MAX_TEMPORAL_TEST_RUN_ACTIVITY_TIMEOUT_SECONDS = 129600
TEMPORAL_TEST_RUN_CLEANUP_BUFFER_SECONDS = 1800

AI_PIPELINE_TIMEOUT_ENV_KEYS = (
    "AI_PIPELINE_TIMEOUT_SECONDS",
    "AGENT_TIMEOUT_SECONDS",
    "EXPLORATION_TIMEOUT_SECONDS",
    "PLANNER_TIMEOUT_SECONDS",
    "GENERATOR_TIMEOUT_SECONDS",
    "HEALER_TIMEOUT_SECONDS",
    "HEALER_ATTEMPT_TIMEOUT_SECONDS",
    "BROWSER_SLOT_TIMEOUT",
    "AGENT_BROWSER_SLOT_TIMEOUT_SECONDS",
)


def clamp_ai_pipeline_timeout_seconds(value: object) -> int:
    """Normalize the UI-controlled AI pipeline timeout."""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = DEFAULT_AI_PIPELINE_TIMEOUT_SECONDS
    return max(MIN_AI_PIPELINE_TIMEOUT_SECONDS, min(MAX_AI_PIPELINE_TIMEOUT_SECONDS, seconds))


def get_persisted_ai_pipeline_timeout_seconds() -> int:
    """Read the persisted timeout, falling back to process/env defaults."""
    try:
        from sqlmodel import Session

        from orchestrator.api.db import engine
        from orchestrator.api.models_db import ExecutionSettings

        with Session(engine) as session:
            settings = session.get(ExecutionSettings, 1)
            if settings and settings.ai_pipeline_timeout_seconds:
                return clamp_ai_pipeline_timeout_seconds(settings.ai_pipeline_timeout_seconds)
    except Exception as exc:
        logger.debug("Unable to read persisted AI pipeline timeout: %s", exc)

    for env_key in ("AI_PIPELINE_TIMEOUT_SECONDS", "GENERATOR_TIMEOUT_SECONDS", "AGENT_TIMEOUT_SECONDS"):
        if os.environ.get(env_key):
            return clamp_ai_pipeline_timeout_seconds(os.environ.get(env_key))
    return DEFAULT_AI_PIPELINE_TIMEOUT_SECONDS


def ai_pipeline_timeout_env_vars(seconds: int | None = None) -> dict[str, str]:
    timeout = clamp_ai_pipeline_timeout_seconds(
        seconds if seconds is not None else get_persisted_ai_pipeline_timeout_seconds()
    )
    return {key: str(timeout) for key in AI_PIPELINE_TIMEOUT_ENV_KEYS}


def get_test_run_queue_wait_timeout_seconds(seconds: int | None = None) -> int:
    """Browser-slot queue budget for regression/test-run work."""
    configured = clamp_ai_pipeline_timeout_seconds(
        seconds if seconds is not None else get_persisted_ai_pipeline_timeout_seconds()
    )
    return max(DEFAULT_TEST_RUN_QUEUE_WAIT_TIMEOUT_SECONDS, configured)


def get_temporal_test_run_activity_timeout_seconds(
    *,
    queue_wait_timeout_seconds: int | None = None,
    execution_timeout_seconds: int | None = None,
) -> int:
    """Compute the durable activity budget for queue wait + execution + cleanup."""
    queue_timeout = (
        int(queue_wait_timeout_seconds)
        if queue_wait_timeout_seconds is not None
        else get_test_run_queue_wait_timeout_seconds()
    )
    execution_timeout = clamp_ai_pipeline_timeout_seconds(
        execution_timeout_seconds
        if execution_timeout_seconds is not None
        else get_persisted_ai_pipeline_timeout_seconds()
    )
    budget = queue_timeout + execution_timeout + TEMPORAL_TEST_RUN_CLEANUP_BUFFER_SECONDS
    return min(MAX_TEMPORAL_TEST_RUN_ACTIVITY_TIMEOUT_SECONDS, max(execution_timeout, budget))


def merge_ai_pipeline_timeout_env_vars(env_vars: Mapping[str, object] | None = None) -> dict[str, str]:
    """Return task env vars with the persisted long-running timeout keys injected."""
    merged = {str(key): str(value) for key, value in (env_vars or {}).items()}
    merged.update(ai_pipeline_timeout_env_vars())
    return merged


def apply_ai_pipeline_timeout_to_process(seconds: int | None = None) -> int:
    timeout = clamp_ai_pipeline_timeout_seconds(
        seconds if seconds is not None else get_persisted_ai_pipeline_timeout_seconds()
    )
    for key in AI_PIPELINE_TIMEOUT_ENV_KEYS:
        os.environ[key] = str(timeout)
    return timeout
