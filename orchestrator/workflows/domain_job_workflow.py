"""Temporal workflow for durable domain background jobs."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

DOMAIN_JOB_RETRY_POLICY = RetryPolicy(maximum_attempts=1)


@workflow.defn(name="DomainJobWorkflow")
class DomainJobWorkflow:
    """Durable wrapper for existing domain-specific async job handlers."""

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await workflow.execute_activity(
            "execute_domain_job",
            payload,
            start_to_close_timeout=timedelta(hours=12),
            retry_policy=DOMAIN_JOB_RETRY_POLICY,
        )
