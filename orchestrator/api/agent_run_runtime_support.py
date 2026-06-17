"""Shared agent-run progress and runtime recovery helpers."""

from __future__ import annotations

import json
import logging
import sys
import time as time_module
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session

from orchestrator.services.agent_runtimes import normalize_agent_runtime
from utils.agent_report import _build_custom_agent_structured_report, _clean_text

from . import agent_run_observability, spec_files
from .db import engine
from .models_db import AgentRun

logger = logging.getLogger(__name__)

RUNS_DIR = spec_files.RUNS_DIR


def _current_runs_dir() -> Path:
    main_module = sys.modules.get("orchestrator.api.main")
    return getattr(main_module, "RUNS_DIR", RUNS_DIR)


def _sync_agent_run_observability_runs_dir() -> None:
    agent_run_observability.RUNS_DIR = _current_runs_dir()


def _short_tool_name(tool_name: str | None) -> str:
    if not tool_name:
        return ""
    return str(tool_name).rsplit("__", 1)[-1] if "__" in str(tool_name) else str(tool_name)


def _collect_agent_run_artifacts(run_id: str) -> list[dict[str, Any]]:
    return agent_run_observability._collect_agent_run_artifacts(run_id)


def _read_run_text_artifact(run_id: str, name: str, max_chars: int | None = None) -> str:
    _sync_agent_run_observability_runs_dir()
    return agent_run_observability._read_run_text_artifact(run_id, name, max_chars)


def _read_run_json_artifact(run_id: str, name: str) -> Any:
    _sync_agent_run_observability_runs_dir()
    return agent_run_observability._read_run_json_artifact(run_id, name)


def _run_artifact_counts(run_id: str, artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    _sync_agent_run_observability_runs_dir()
    return agent_run_observability._run_artifact_counts(run_id, artifacts)


def _recover_custom_agent_partial_result(run: AgentRun, error: Exception | str) -> dict[str, Any] | None:
    artifacts = _collect_agent_run_artifacts(run.id)
    raw_output = _read_run_text_artifact(run.id, "raw_output.txt")
    tool_calls = _read_run_json_artifact(run.id, "tool_calls.json")
    tool_calls = tool_calls if isinstance(tool_calls, list) else []
    counts = _run_artifact_counts(run.id, artifacts)
    if not raw_output.strip() and not artifacts and not tool_calls:
        return None

    def fallback_recovery() -> dict[str, Any]:
        structured = _build_custom_agent_structured_report(raw_output, run.config, artifacts)
        warnings = [
            "Structured JSON was not returned; a minimal report was synthesized from available evidence.",
            f"Custom agent recovered partial evidence after runtime failure: {error}",
        ]
        return {
            "summary": structured.get("summary") or _clean_text(raw_output, 500),
            "output": raw_output,
            "structured_report": structured,
            "error": str(error),
            "partial_results": True,
            "failure_reason": "runtime_failed_after_evidence",
            "contract_status": "partial",
            "repair_attempts": [
                {
                    "attempt": 1,
                    "strategy": "synthesize_minimal_report_from_evidence",
                    "status": "success",
                }
            ],
            "contract_warnings": warnings,
            "diagnostics": {
                "finalizer": {
                    "agent_type": "custom",
                    "source": "runtime_failure_recovery_fallback",
                    "recovered_after_error": True,
                    "error": str(error),
                    **counts,
                }
            },
        }

    try:
        from orchestrator.services.agent_run_finalizer import AgentRunFinalizer

        finalized = AgentRunFinalizer().finalize(
            run_id=run.id,
            agent_type="custom",
            config=run.config,
            raw_model_output=raw_output,
            tool_calls=tool_calls,
            runtime_diagnostics={
                "source": "runtime_failure_recovery",
                "recovered_after_error": True,
                "error": str(error),
                **counts,
            },
            artifacts=artifacts,
            existing_result=run.result if isinstance(run.result, dict) else None,
        )
    except Exception as exc:
        logger.debug("Failed to recover custom agent partial result for %s: %s", run.id, exc)
        return fallback_recovery()

    if finalized.status == "failed":
        return fallback_recovery()
    recovered = dict(finalized.result)
    recovered["error"] = str(error)
    recovered["partial_results"] = True
    recovered["failure_reason"] = "runtime_failed_after_evidence"
    recovered.setdefault("contract_warnings", [])
    if isinstance(recovered["contract_warnings"], list):
        warning = f"Custom agent recovered partial evidence after runtime failure: {error}"
        if warning not in recovered["contract_warnings"]:
            recovered["contract_warnings"].append(warning)
    return recovered


def _agent_run_summary(run: AgentRun) -> str | None:
    result = run.result or {}
    structured = result.get("structured_report") if isinstance(result, dict) else None
    if isinstance(structured, dict) and structured.get("summary"):
        return structured.get("summary")
    return result.get("summary") if isinstance(result, dict) else None


def _exploratory_result_is_zero_evidence_failure(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    action_trace = result.get("action_trace") if isinstance(result.get("action_trace"), list) else []
    flows = result.get("discovered_flows") if isinstance(result.get("discovered_flows"), list) else []
    flow_summaries = (
        result.get("discovered_flow_summaries")
        if isinstance(result.get("discovered_flow_summaries"), list)
        else []
    )
    try:
        total_flows = int(result.get("total_flows_discovered") or 0)
    except (TypeError, ValueError):
        total_flows = 0
    return bool(
        result.get("failure_reason") in {"zero_evidence_parse_fallback", "zero_evidence"}
        or (
            result.get("parsing_failed")
            and not action_trace
            and not flows
            and not flow_summaries
            and total_flows == 0
        )
    )


def _exploratory_result_is_terminal_failure(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("failure_reason") == "runtime_auth_failed":
        return True
    return _exploratory_result_is_zero_evidence_failure(result)


def _exploratory_result_has_usable_evidence(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    action_trace = result.get("action_trace") if isinstance(result.get("action_trace"), list) else []
    flow_summaries = (
        result.get("discovered_flow_summaries")
        if isinstance(result.get("discovered_flow_summaries"), list)
        else []
    )
    pages = result.get("pages_visited") if isinstance(result.get("pages_visited"), list) else []
    screenshots = result.get("screenshots") if isinstance(result.get("screenshots"), list) else []
    diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {}
    event_count = agent_run_observability._coerce_progress_int(diagnostics.get("evidence_event_count"), 0)
    successful_browser_actions = agent_run_observability._coerce_progress_int(
        diagnostics.get("successful_browser_tool_calls"), 0
    )
    return bool(action_trace or flow_summaries or pages or screenshots or event_count > 0 or successful_browser_actions > 0)


def _merge_agent_failure_into_result(result: Any, error: Exception | str, *, failure_reason: str) -> dict[str, Any]:
    merged = dict(result) if isinstance(result, dict) else {}
    error_text = str(error)
    diagnostics = dict(merged.get("diagnostics") or {})
    diagnostics["runtime_error"] = error_text
    merged["diagnostics"] = diagnostics
    merged["error"] = error_text
    merged.setdefault("failure_reason", failure_reason)
    merged["partial_results"] = True
    merged["exploration_status"] = merged.get("exploration_status") or "completed_partial"
    warnings = list(merged.get("contract_warnings") or [])
    warning = f"Explorer recovered partial evidence after runtime failure: {error_text}"
    if warning not in warnings:
        warnings.append(warning)
    merged["contract_warnings"] = warnings
    merged.setdefault("contract_warning", warning)
    merged.setdefault("summary", "Exploration recovered partial evidence after the agent runtime failed.")
    return merged


def _recover_exploratory_partial_result(run_id: str, config: dict[str, Any], error: Exception | str) -> dict[str, Any] | None:
    try:
        from orchestrator.agents.exploratory_agent import ExplorationState, ExploratoryAgent

        run_dir = _current_runs_dir() / run_id
        runtime_tool_calls: list[Any] = []
        tool_calls_path = run_dir / "tool_calls.json"
        if tool_calls_path.exists():
            try:
                loaded_calls = json.loads(tool_calls_path.read_text(encoding="utf-8"))
                if isinstance(loaded_calls, list):
                    runtime_tool_calls = loaded_calls
            except Exception as exc:
                logger.debug("Failed to read tool call recovery artifact for %s: %s", run_id, exc)
        processor = ExploratoryAgent()
        processor.state = ExplorationState(start_time=time_module.time())
        result = processor._process_results(
            "",
            {
                **config,
                "run_id": run_id,
                "_runtime_tool_calls": runtime_tool_calls,
                "_runtime_diagnostics": {
                    "runtime": normalize_agent_runtime(config.get("runtime")),
                    "recovered_after_error": True,
                    "error": str(error),
                },
            },
        )
        if _exploratory_result_has_usable_evidence(result):
            return _merge_agent_failure_into_result(
                result,
                error,
                failure_reason="runtime_failed_after_evidence",
            )
    except Exception as exc:
        logger.debug("Failed to recover exploratory partial result for %s: %s", run_id, exc)
    return None


def update_agent_run_progress(
    run_id: str,
    patch: dict[str, Any],
    *,
    agent_task_id: str | None = None,
    skip_terminal: bool = False,
) -> None:
    """Persist live progress for agent runs."""
    try:
        with Session(engine) as session:
            run = session.get(AgentRun, run_id)
            if not run:
                return
            if skip_terminal and run.status in {"completed", "completed_partial", "failed", "cancelled", "timeout"}:
                return
            existing = run.progress or {}
            recent_tools = list(existing.get("recent_tools") or [])
            progress_patch = dict(patch or {})
            last_tool = progress_patch.get("last_tool") or progress_patch.get("current_tool")
            if not last_tool:
                progress_patch.pop("last_tool", None)
                progress_patch.pop("current_tool", None)
                last_tool = existing.get("last_tool") or existing.get("current_tool")
            if last_tool and (not recent_tools or recent_tools[-1].get("name") != last_tool):
                recent_tools.append(
                    {
                        "name": str(last_tool),
                        "label": _short_tool_name(str(last_tool)),
                        "at": datetime.utcnow().isoformat(),
                    }
                )
                recent_tools = recent_tools[-12:]

            if agent_task_id is not None:
                progress_patch["agent_task_id"] = agent_task_id
            progress = {
                **existing,
                **progress_patch,
                "recent_tools": recent_tools,
                "updated_at": datetime.utcnow().isoformat(),
            }
            progress = agent_run_observability._normalize_agent_run_progress(progress)
            run.progress = progress
            if progress_patch.get("agent_task_id"):
                run.agent_task_id = str(progress_patch["agent_task_id"])
            session.add(run)
            session.commit()
    except Exception as exc:
        logger.debug("Failed to update custom agent progress for %s: %s", run_id, exc)
