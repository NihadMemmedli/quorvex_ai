"""Contract finalization for standalone agent run results."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orchestrator.agents.exploratory_agent import ExplorationState, ExploratoryAgent
from orchestrator.agents.explorer_result_synthesizer import browser_tool_diagnostics
from orchestrator.utils.agent_report import (
    _build_custom_agent_structured_report,
    _clean_text,
    _extract_custom_report_candidate,
    _normalize_custom_agent_report,
)

PARTIAL_STATUS = "completed_partial"
REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = REPO_ROOT / "runs"


@dataclass
class FinalizedAgentRun:
    status: str
    result: dict[str, Any]


def _raw_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str)
    except Exception:
        return str(value)


def _merge_diagnostics(result: dict[str, Any], finalizer: dict[str, Any]) -> None:
    diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {}
    result["diagnostics"] = {**diagnostics, "finalizer": finalizer}


def _dedupe_strings(values: list[Any]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _artifact_evidence(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = [artifact for artifact in artifacts if isinstance(artifact, dict)]
    screenshots = [
        artifact
        for artifact in normalized
        if str(artifact.get("type") or "").lower() == "image"
        or str(artifact.get("name") or "").lower().endswith((".png", ".jpg", ".jpeg"))
    ]
    videos = [
        artifact
        for artifact in normalized
        if str(artifact.get("type") or "").lower() == "video"
        or str(artifact.get("name") or "").lower().endswith((".webm", ".mp4"))
    ]
    logs = [artifact for artifact in normalized if str(artifact.get("type") or "").lower() == "log"]
    return {
        "artifacts": normalized,
        "artifact_count": len(normalized),
        "screenshot_count": len(screenshots),
        "video_count": len(videos),
        "log_count": len(logs),
    }


def _contract_fields(
    *,
    contract_status: str,
    repair_attempts: list[dict[str, Any]],
    warnings: list[str],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract_status": contract_status,
        "repair_attempts": repair_attempts,
        "contract_warnings": _dedupe_strings(warnings),
        "diagnostics": diagnostics,
    }


def _collect_agent_run_artifacts(run_id: str) -> list[dict[str, Any]]:
    suffix_types = {
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".webm": "video",
        ".mp4": "video",
        ".json": "log",
        ".jsonl": "log",
        ".txt": "log",
    }
    artifacts: list[dict[str, Any]] = []
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        return artifacts
    for path in run_dir.glob("**/*"):
        if not path.is_file():
            continue
        artifact_type = suffix_types.get(path.suffix.lower())
        if not artifact_type:
            continue
        try:
            rel_path = path.relative_to(RUNS_DIR)
        except ValueError:
            continue
        artifacts.append({"name": path.name, "path": f"/artifacts/{rel_path}", "type": artifact_type})
    return artifacts[:100]


def _extract_json_text(output: str) -> str:
    blocks = re.findall(r"```(?:json)?\s*(.*?)\s*```", output, flags=re.DOTALL | re.IGNORECASE)
    for block in blocks:
        if block.strip().startswith("{"):
            return block.strip()
    stripped = output.strip()
    if stripped.startswith("{"):
        return stripped
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first >= 0 and last > first:
        return stripped[first : last + 1]
    return ""


def _repair_json_candidate(output: str) -> dict[str, Any] | None:
    candidate = _extract_json_text(output)
    if not candidate:
        return None
    repairs = [
        candidate,
        re.sub(r",(\s*[}\]])", r"\1", candidate),
    ]
    for repaired in repairs:
        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            report = parsed.get("structured_report")
            if isinstance(report, dict):
                return report
            if any(key in parsed for key in ("summary", "findings", "test_ideas", "pages_checked")):
                return parsed
    return None


def _has_evidence(raw_output: str, artifacts: list[dict[str, Any]], tool_calls: list[Any]) -> bool:
    if raw_output.strip():
        return True
    if artifacts:
        return True
    return bool(tool_calls)


def _short_tool_name(value: Any) -> str:
    name = str(value or "")
    return name.rsplit("__", 1)[-1] if "__" in name else name


def _browser_timeout_partial_reason(runtime_diagnostics: dict[str, Any], tool_calls: list[Any]) -> str | None:
    error_text = _raw_text(runtime_diagnostics.get("last_browser_error") or runtime_diagnostics.get("error") or "")
    error_type = str(runtime_diagnostics.get("error_type") or runtime_diagnostics.get("failure_category") or "")
    timed_out = (
        runtime_diagnostics.get("browser_tool_timeout") is True
        or error_type == "browser_tool_timeout"
        or "timed out" in error_text.lower()
        or "timeout" in error_text.lower()
    )
    timeout_tool = _short_tool_name(
        runtime_diagnostics.get("timed_out_tool_name")
        or runtime_diagnostics.get("blocked_tool_name")
        or runtime_diagnostics.get("last_tool")
    )
    for call in reversed(tool_calls):
        name = _short_tool_name(call.get("name") if isinstance(call, dict) else getattr(call, "name", ""))
        call_error = _raw_text(call.get("error") if isinstance(call, dict) else getattr(call, "error", ""))
        if name.startswith("browser_") and ("timeout" in call_error.lower() or "timed out" in call_error.lower()):
            timed_out = True
            timeout_tool = timeout_tool or name
            error_text = error_text or call_error
            break
    if not timed_out:
        return None

    def _number(value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    action_timeout = _number(runtime_diagnostics.get("browser_action_timeout_seconds"))
    tool_timeout = _number(runtime_diagnostics.get("browser_tool_timeout_seconds"))
    timeout_suffix = ""
    if action_timeout and tool_timeout:
        timeout_suffix = f" after {action_timeout:g}s/{tool_timeout:g}s"
    elif tool_timeout:
        timeout_suffix = f" after {tool_timeout:g}s"
    elif action_timeout:
        timeout_suffix = f" after {action_timeout:g}s"
    tool_label = timeout_tool or "browser action"
    return f"Recovered partial evidence after {tool_label} timed out{timeout_suffix}."


def _runtime_auth_failure_reason(runtime_diagnostics: dict[str, Any], raw_output: str, existing_result: dict[str, Any]) -> str | None:
    error_type = str(runtime_diagnostics.get("error_type") or runtime_diagnostics.get("failure_category") or "")
    error_text = _raw_text(
        runtime_diagnostics.get("error")
        or runtime_diagnostics.get("runtime_error")
        or existing_result.get("error")
        or raw_output
    )
    lowered = error_text.lower()
    if (
        error_type == "claude_code_auth_required"
        or "authentication_failed" in lowered
        or ("not logged in" in lowered and "run /login" in lowered)
        or ("token expired or incorrect" in lowered and "401" in lowered)
    ):
        return "Claude Code authentication failed. Refresh Claude Code OAuth in Settings or run Claude Code login/token setup for the backend runtime."
    return None


def _collect_native_context(run_id: str) -> dict[str, Any]:
    try:
        from sqlmodel import Session, select

        from orchestrator.api.db import engine
        from orchestrator.api.models_db import AgentRunEvidence, AgentRunNote
        from orchestrator.services.agent_native_runs import serialize_agent_run_note

        with Session(engine) as session:
            notes = session.exec(
                select(AgentRunNote).where(AgentRunNote.run_id == run_id).order_by(AgentRunNote.sequence.asc()).limit(100)
            ).all()
            evidence = session.exec(
                select(AgentRunEvidence)
                .where(AgentRunEvidence.run_id == run_id)
                .order_by(AgentRunEvidence.created_at.asc())
                .limit(200)
            ).all()
        return {
            "notes": [serialize_agent_run_note(note) for note in notes],
            "evidence": [
                {
                    "id": item.id,
                    "type": item.evidence_type,
                    "title": item.title,
                    "summary": item.summary,
                    "artifact_path": item.artifact_path,
                    "url": item.url,
                    "tool_name": item.tool_name,
                    "trace_span_id": item.trace_span_id,
                    "event_sequence": item.event_sequence,
                }
                for item in evidence
            ],
        }
    except Exception:
        return {"notes": [], "evidence": []}


def _apply_finding_gates(
    structured: dict[str, Any],
    *,
    artifacts: list[dict[str, Any]],
    tool_calls: list[Any],
    native_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    findings = structured.get("findings")
    if not isinstance(findings, list):
        return {"finding_count": 0, "downgraded_findings": 0, "warnings": []}
    durable_evidence_present = bool(artifacts or tool_calls or native_evidence or structured.get("evidence"))
    warnings: list[str] = []
    downgraded = 0
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            continue
        status = str(finding.get("status") or finding.get("verification_status") or "").strip().lower()
        if status in {"candidate", "rejected"}:
            finding["verification_status"] = status
            continue
        has_inline_evidence = bool(
            finding.get("evidence")
            or finding.get("evidence_ids")
            or finding.get("evidence_refs")
            or finding.get("artifact_path")
            or finding.get("url")
        )
        if durable_evidence_present or has_inline_evidence:
            finding.setdefault("verification_status", "verified")
            continue
        finding["verification_status"] = "partial"
        finding["partial_reason"] = finding.get("partial_reason") or "No durable evidence was linked to this finding."
        finding.setdefault("confidence", "low")
        downgraded += 1
        warnings.append(f"Finding {index + 1} was downgraded because it has no linked evidence.")
    return {"finding_count": len(findings), "downgraded_findings": downgraded, "warnings": warnings}


class AgentRunFinalizer:
    """Validate, repair, and enrich raw agent output before terminal persistence."""

    max_repair_attempts = 3

    def finalize(
        self,
        *,
        run_id: str,
        agent_type: str,
        config: dict[str, Any] | None,
        raw_model_output: Any = None,
        tool_calls: list[Any] | None = None,
        runtime_diagnostics: dict[str, Any] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        existing_result: dict[str, Any] | None = None,
        native_notes: list[dict[str, Any]] | None = None,
        native_evidence: list[dict[str, Any]] | None = None,
    ) -> FinalizedAgentRun:
        config = dict(config or {})
        tool_calls = list(tool_calls or [])
        artifacts = list(artifacts if artifacts is not None else _collect_agent_run_artifacts(run_id))
        native_context = _collect_native_context(run_id) if native_notes is None or native_evidence is None else {}
        native_notes = list(native_notes if native_notes is not None else native_context.get("notes") or [])
        native_evidence = list(native_evidence if native_evidence is not None else native_context.get("evidence") or [])
        if agent_type == "custom":
            return self._finalize_custom(
                run_id=run_id,
                config=config,
                raw_model_output=raw_model_output,
                tool_calls=tool_calls,
                runtime_diagnostics=runtime_diagnostics or {},
                artifacts=artifacts,
                existing_result=existing_result,
                native_notes=native_notes,
                native_evidence=native_evidence,
            )
        if agent_type == "exploratory":
            return self._finalize_explorer(
                run_id=run_id,
                config=config,
                raw_model_output=raw_model_output,
                tool_calls=tool_calls,
                runtime_diagnostics=runtime_diagnostics or {},
                artifacts=artifacts,
                existing_result=existing_result,
                native_notes=native_notes,
                native_evidence=native_evidence,
            )
        return self._finalize_generic(
            raw_model_output=raw_model_output,
            tool_calls=tool_calls,
            runtime_diagnostics=runtime_diagnostics or {},
            existing_result=existing_result,
        )

    def _finalize_custom(
        self,
        *,
        run_id: str,
        config: dict[str, Any],
        raw_model_output: Any,
        tool_calls: list[Any],
        runtime_diagnostics: dict[str, Any],
        artifacts: list[dict[str, Any]],
        existing_result: dict[str, Any] | None,
        native_notes: list[dict[str, Any]],
        native_evidence: list[dict[str, Any]],
    ) -> FinalizedAgentRun:
        raw_output = _raw_text(raw_model_output)
        base = dict(existing_result or {})
        if not raw_output:
            raw_output = _raw_text(base.get("output"))
        timeout_partial_reason = _browser_timeout_partial_reason(runtime_diagnostics, tool_calls)
        auth_failure_reason = _runtime_auth_failure_reason(runtime_diagnostics, raw_output, base)

        repair_attempts: list[dict[str, Any]] = []
        warnings: list[str] = []
        structured = base.get("structured_report") if isinstance(base.get("structured_report"), dict) else None
        contract_status = "valid" if structured else "invalid"

        if structured:
            structured = _normalize_custom_agent_report(structured, raw_output, config, artifacts)
            repair_attempts.append({"attempt": 0, "strategy": "existing_structured_report", "status": "valid"})
        else:
            parsed = _extract_custom_report_candidate(raw_output)
            if parsed:
                extracted_json = _extract_json_text(raw_output)
                parsed_after_json_error = False
                if extracted_json:
                    try:
                        json.loads(extracted_json)
                    except json.JSONDecodeError:
                        parsed_after_json_error = True
                structured = _normalize_custom_agent_report(parsed, raw_output, config, artifacts)
                contract_status = "valid" if raw_output.strip().startswith("{") and not parsed_after_json_error else "repaired"
                if parsed_after_json_error:
                    repair_attempts.append({"attempt": 1, "strategy": "parse_structured_json", "status": "failed"})
                    repair_attempts.append({"attempt": 2, "strategy": "repair_malformed_json", "status": "success"})
                else:
                    repair_attempts.append({"attempt": 1, "strategy": "parse_structured_json", "status": "success"})
            else:
                repair_attempts.append({"attempt": 1, "strategy": "parse_structured_json", "status": "failed"})
                repaired = _repair_json_candidate(raw_output)
                if repaired:
                    structured = _normalize_custom_agent_report(repaired, raw_output, config, artifacts)
                    contract_status = "repaired"
                    repair_attempts.append({"attempt": 2, "strategy": "repair_malformed_json", "status": "success"})
                else:
                    repair_attempts.append({"attempt": 2, "strategy": "repair_malformed_json", "status": "failed"})

        evidence_present = _has_evidence(raw_output, artifacts, tool_calls)
        if structured is None and auth_failure_reason:
            repair_attempts.append(
                {"attempt": 3, "strategy": "synthesize_minimal_report_from_evidence", "status": "skipped"}
            )
        elif structured is None and evidence_present:
            structured = _build_custom_agent_structured_report(raw_output, config, artifacts)
            contract_status = "partial"
            repair_attempts.append(
                {"attempt": 3, "strategy": "synthesize_minimal_report_from_evidence", "status": "success"}
            )
            warnings.append("Structured JSON was not returned; a minimal report was synthesized from available evidence.")
            if timeout_partial_reason:
                warnings.append(timeout_partial_reason)
        elif structured is None:
            repair_attempts.append(
                {"attempt": 3, "strategy": "synthesize_minimal_report_from_evidence", "status": "failed"}
            )

        diagnostics = {
            "agent_type": "custom",
            "raw_output_chars": len(raw_output),
            "artifacts": len(artifacts),
            "tool_calls": len(tool_calls),
            "native_note_count": len(native_notes),
            "native_evidence_count": len(native_evidence),
            "structured_report_present": structured is not None,
            "repair_attempt_count": len([item for item in repair_attempts if int(item.get("attempt") or 0) > 0]),
            "browser_timeout_recovery_reason": timeout_partial_reason,
            **runtime_diagnostics,
        }

        if structured is None:
            result = {
                **base,
                "summary": auth_failure_reason
                or "Custom agent failed: no structured output or recoverable evidence was produced.",
                "output": raw_output,
                "error": auth_failure_reason
                or base.get("error")
                or "No structured output or recoverable evidence was produced.",
            }
            if auth_failure_reason:
                result["failure_reason"] = "runtime_auth_failed"
            fields = _contract_fields(
                contract_status="invalid",
                repair_attempts=repair_attempts,
                warnings=warnings,
                diagnostics=diagnostics,
            )
            result["contract_status"] = fields["contract_status"]
            result["repair_attempts"] = fields["repair_attempts"]
            result.pop("contract_warning", None)
            result["contract_warnings"] = fields["contract_warnings"]
            _merge_diagnostics(result, fields["diagnostics"])
            return FinalizedAgentRun(status="failed", result=result)

        if not structured.get("findings") and not structured.get("test_ideas") and not structured.get("requirements"):
            warnings.append("The structured report contains no findings, test ideas, or candidate requirements.")
        gate_diagnostics = _apply_finding_gates(
            structured,
            artifacts=artifacts,
            tool_calls=tool_calls,
            native_evidence=native_evidence,
        )
        warnings.extend(gate_diagnostics["warnings"])

        result = {
            **base,
            "summary": structured.get("summary") or base.get("summary") or _clean_text(raw_output, 500),
            "output": raw_output,
            "structured_report": structured,
        }
        result["contract_status"] = contract_status
        result["repair_attempts"] = repair_attempts[: self.max_repair_attempts + 1]
        result.pop("contract_warning", None)
        result["contract_warnings"] = _dedupe_strings(warnings)
        status = PARTIAL_STATUS if contract_status == "partial" else "completed"
        if status == PARTIAL_STATUS:
            result["partial_reason"] = timeout_partial_reason or (result["contract_warnings"][0] if result["contract_warnings"] else None)
        _merge_diagnostics(result, {**diagnostics, "gates": gate_diagnostics})
        return FinalizedAgentRun(status=status, result=result)

    def _finalize_explorer(
        self,
        *,
        run_id: str,
        config: dict[str, Any],
        raw_model_output: Any,
        tool_calls: list[Any],
        runtime_diagnostics: dict[str, Any],
        artifacts: list[dict[str, Any]],
        existing_result: dict[str, Any] | None,
        native_notes: list[dict[str, Any]],
        native_evidence: list[dict[str, Any]],
    ) -> FinalizedAgentRun:
        raw_output = _raw_text(raw_model_output)
        repair_attempts: list[dict[str, Any]] = []
        warnings: list[str] = []
        timeout_partial_reason = _browser_timeout_partial_reason(runtime_diagnostics, tool_calls)

        if existing_result:
            result = dict(existing_result)
            if not raw_output:
                raw_output = _raw_text(result.get("output") or result.get("raw_output_preview"))
        else:
            processor = ExploratoryAgent()
            processor.state = ExplorationState(start_time=time.time())
            result = processor._process_results(
                raw_output,
                {
                    **config,
                    "run_id": run_id,
                    "_runtime_tool_calls": tool_calls,
                    "_runtime_diagnostics": runtime_diagnostics,
                },
            )
            repair_attempts.append({"attempt": 1, "strategy": "process_explorer_events", "status": "success"})

        flow_summaries = result.get("discovered_flow_summaries") if isinstance(result.get("discovered_flow_summaries"), list) else []
        unsupported_flow_candidates = (
            result.get("unsupported_flow_candidates")
            if isinstance(result.get("unsupported_flow_candidates"), list)
            else []
        )
        action_trace = result.get("action_trace") if isinstance(result.get("action_trace"), list) else []
        pages = result.get("pages_visited") if isinstance(result.get("pages_visited"), list) else []
        event_counts = result.get("event_counts") if isinstance(result.get("event_counts"), dict) else {}
        artifact_evidence = _artifact_evidence(artifacts)
        has_flows = bool(flow_summaries) or int(result.get("total_flows_discovered") or 0) > 0
        evidence_count = len(action_trace) + len(pages) + sum(int(value or 0) for value in event_counts.values())
        evidence_present = evidence_count > 0 or bool(tool_calls) or artifact_evidence["artifact_count"] > 0
        runtime_auth_failure = result.get("failure_reason") == "runtime_auth_failed"

        text = raw_output or json.dumps(result, default=str)
        claims_flows = bool(
            text
            and (
                re.search(r"\b(discovered|documented|found|identified|covered)\b.{0,80}\bflows?\b", text, re.I)
                or re.search(r"\b\d+\s+flows?\b", text, re.I)
            )
        )
        if claims_flows and not has_flows:
            repair_attempts.append(
                {
                    "attempt": 2,
                    "strategy": "evidence_to_flow_recovery",
                    "status": "failed",
                    "message": "No evidence-backed flow_candidate records could be created from cited events.",
                }
            )
            warnings.append(
                "The model claimed flow coverage, but no evidence-backed flow summaries were produced."
            )

        if unsupported_flow_candidates and not has_flows:
            warnings.append(
                "The model emitted flow candidates with missing evidence event ids; they are shown as unsupported and cannot generate tests."
            )

        if runtime_auth_failure or not evidence_present:
            contract_status = "invalid"
            status = "failed"
            warnings.append("No recoverable browser evidence was captured.")
        elif has_flows:
            contract_status = "repaired" if result.get("parsing_failed") else "valid"
            status = "completed"
        else:
            contract_status = "partial"
            status = PARTIAL_STATUS
            warnings.append("Evidence was captured, but no completed evidence-backed flow was observed.")
            if timeout_partial_reason:
                warnings.append(timeout_partial_reason)

        existing_warning = result.get("contract_warning") or result.get("exploration_status")
        warnings = _dedupe_strings(
            [
                *warnings,
                existing_warning,
                *(result.get("contract_warnings") if isinstance(result.get("contract_warnings"), list) else []),
            ]
        )
        result.pop("contract_warning", None)

        diagnostics = {
            "agent_type": "exploratory",
            "raw_output_chars": len(raw_output),
            "flow_summaries": len(flow_summaries),
            "action_trace": len(action_trace),
            "pages_visited": len(pages),
            "event_count": evidence_count,
            "artifact_count": artifact_evidence["artifact_count"],
            "screenshot_count": artifact_evidence["screenshot_count"],
            "native_note_count": len(native_notes),
            "native_evidence_count": len(native_evidence),
            "repair_attempt_count": len(repair_attempts),
            "browser_timeout_recovery_reason": timeout_partial_reason,
            **browser_tool_diagnostics(tool_calls),
            **runtime_diagnostics,
        }
        result["artifact_evidence"] = artifact_evidence
        result["contract_status"] = contract_status
        result["repair_attempts"] = repair_attempts[: self.max_repair_attempts]
        result["contract_warnings"] = warnings
        if status == PARTIAL_STATUS:
            result["partial_reason"] = timeout_partial_reason or (warnings[0] if warnings else None)
        _merge_diagnostics(result, diagnostics)
        return FinalizedAgentRun(status=status, result=result)

    def _finalize_generic(
        self,
        *,
        raw_model_output: Any,
        tool_calls: list[Any],
        runtime_diagnostics: dict[str, Any],
        existing_result: dict[str, Any] | None,
    ) -> FinalizedAgentRun:
        raw_output = _raw_text(raw_model_output)
        result = dict(existing_result or {})
        if not raw_output:
            raw_output = _raw_text(result.get("output"))
        result.setdefault("summary", _clean_text(raw_output, 500))
        result.setdefault("output", raw_output)
        result["contract_status"] = "valid" if raw_output.strip() or result else "invalid"
        result["repair_attempts"] = []
        result.pop("contract_warning", None)
        result["contract_warnings"] = [] if result["contract_status"] == "valid" else ["No agent output was returned."]
        _merge_diagnostics(
            result,
            {
                "agent_type": "generic",
                "raw_output_chars": len(raw_output),
                "tool_calls": len(tool_calls),
                **runtime_diagnostics,
            },
        )
        return FinalizedAgentRun(status="completed" if result["contract_status"] == "valid" else "failed", result=result)
