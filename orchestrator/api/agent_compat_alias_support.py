"""Main-compatible aliases for legacy agent helper delegates."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from . import agent_compat_support, agent_run_observability, agent_run_runtime_support


def _runtime() -> Any:
    from . import main

    return main._agent_compat_runtime()


def _sync_agent_run_observability_runs_dir() -> None:
    agent_compat_support.sync_agent_run_observability_runs_dir(_runtime())


_collect_agent_run_artifacts = agent_run_observability._collect_agent_run_artifacts


def _read_run_text_artifact(run_id: str, name: str, max_chars: int | None = None) -> str:
    return agent_compat_support.read_run_text_artifact(_runtime(), run_id, name, max_chars)


def _read_run_json_artifact(run_id: str, name: str) -> Any:
    return agent_compat_support.read_run_json_artifact(_runtime(), run_id, name)


def _run_artifact_counts(run_id: str, artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return agent_compat_support.run_artifact_counts(_runtime(), run_id, artifacts)


_jsonl_latest_url = agent_run_observability._jsonl_latest_url


def _latest_observed_url_for_run(run: Any) -> str | None:
    return agent_compat_support.latest_observed_url_for_run(_runtime(), run)


def _recover_custom_agent_partial_result(run: Any, error: Exception | str) -> dict[str, Any] | None:
    return agent_compat_support.recover_custom_agent_partial_result(_runtime(), run, error)


_agent_run_summary = agent_run_runtime_support._agent_run_summary
_exploratory_result_is_zero_evidence_failure = agent_run_runtime_support._exploratory_result_is_zero_evidence_failure
_exploratory_result_is_terminal_failure = agent_run_runtime_support._exploratory_result_is_terminal_failure
_exploratory_result_has_usable_evidence = agent_run_runtime_support._exploratory_result_has_usable_evidence
_merge_agent_failure_into_result = agent_run_runtime_support._merge_agent_failure_into_result


def _recover_exploratory_partial_result(run_id: str, config: dict[str, Any], error: Exception | str) -> dict[str, Any] | None:
    return agent_compat_support.recover_exploratory_partial_result(_runtime(), run_id, config, error)


_filter_agent_run_project = agent_run_observability._filter_agent_run_project


def _agent_report_project_filter(project_id: str):
    return agent_compat_support.agent_report_project_filter(_runtime(), project_id)


def _get_agent_report_run(session: Session, run_id: str, project_id: str) -> Any:
    return agent_compat_support.get_agent_report_run(_runtime(), session, run_id, project_id)


AGENT_PARTIAL_STATUS = agent_run_observability.AGENT_PARTIAL_STATUS
AGENT_TERMINAL_STATUSES = agent_run_observability.AGENT_TERMINAL_STATUSES
AGENT_ACTIVE_STATUSES = agent_run_observability.AGENT_ACTIVE_STATUSES


_coerce_progress_int = agent_run_observability._coerce_progress_int
_normalize_agent_run_progress = agent_run_observability._normalize_agent_run_progress


def _record_agent_run_event(
    run_id: str,
    *,
    event_type: str,
    message: str,
    level: str = "info",
    payload: dict[str, Any] | None = None,
    agent_task_id: str | None = None,
    session: Session | None = None,
) -> None:
    agent_compat_support.record_agent_run_event(
        _runtime(),
        run_id,
        event_type=event_type,
        message=message,
        level=level,
        payload=payload,
        agent_task_id=agent_task_id,
        session=session,
    )


async def _start_agent_run_temporal_or_fail(run: Any, session: Session, *, workflow_attempt: int | None = None) -> None:
    await agent_compat_support.start_agent_run_temporal_or_fail(
        _runtime(),
        run,
        session,
        workflow_attempt=workflow_attempt,
    )


async def _agent_run_temporal_payload(run: Any) -> dict[str, Any]:
    return await agent_compat_support.agent_run_temporal_payload(_runtime(), run)
