import json
import os
import re
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from logging_config import get_logger
from services.browser_pool import get_browser_pool
from utils.playwright_mcp import (
    browser_runtime_status as _default_browser_runtime_status,
)
from utils.playwright_mcp import (
    live_browser_display_diagnostics as _default_live_browser_display_diagnostics,
)

from . import spec_files
from .models_db import TestRun as DBTestRun

logger = get_logger(__name__)

BASE_DIR = spec_files.BASE_DIR
SPECS_DIR = spec_files.SPECS_DIR

RUN_BROWSER_METADATA_FILE = "browser-runtime.json"
RUN_SEED_SPEC_RELATIVE_PATH = Path("tests") / "seed.spec.ts"
RUN_TARGET_URL_PATTERNS = [
    r"Navigate to\s+(https?://[^\s'\"`]+)",
    r"Go to\s+(https?://[^\s'\"`]+)",
    r"Open\s+(https?://[^\s'\"`]+)",
    r"##\s+Base\s+URL:\s*(https?://[^\s'\"`]+)",
    r"Base\s+URL:\s*(https?://[^\s'\"`]+)",
    r"Target URL:\s*(https?://[^\s'\"`]+)",
    r"URL:\s*(https?://[^\s'\"`]+)",
    r"(https?://[^\s'\"`]+)",
]
REAL_BROWSER_EXECUTABLE_NAMES = {
    "chrome",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "msedge",
    "microsoft-edge",
    "firefox",
}
ACTIVE_RUN_STATUSES = {"queued", "pending", "running", "in_progress"}


def _main_runtime() -> Any | None:
    try:
        from . import main as main_runtime

        return main_runtime
    except Exception:
        return None


def _browser_runtime_status() -> dict[str, Any]:
    main_runtime = _main_runtime()
    runtime_status = getattr(main_runtime, "browser_runtime_status", None) if main_runtime else None
    if callable(runtime_status):
        return runtime_status()
    return _default_browser_runtime_status()


def _live_browser_display_diagnostics() -> dict[str, Any]:
    main_runtime = _main_runtime()
    diagnostics = getattr(main_runtime, "live_browser_display_diagnostics", None) if main_runtime else None
    if callable(diagnostics):
        return diagnostics()
    return _default_live_browser_display_diagnostics()


async def _browser_pool() -> Any:
    main_runtime = _main_runtime()
    pool = getattr(main_runtime, "BROWSER_POOL", None) if main_runtime else None
    return pool or await get_browser_pool()


def _strip_ansi(text: str) -> str:
    """Remove terminal color/control sequences from stored runner output."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _iter_playwright_specs(suite: dict[str, Any]):
    """Yield specs from a nested Playwright JSON suite tree."""
    for spec in suite.get("specs") or []:
        if isinstance(spec, dict):
            yield spec
    for child in suite.get("suites") or []:
        if isinstance(child, dict):
            yield from _iter_playwright_specs(child)


def _build_log_from_playwright_results(results: dict[str, Any]) -> str:
    """Build a readable execution log from Playwright's JSON reporter output."""
    lines: list[str] = []
    stats = results.get("stats") or {}
    if stats:
        lines.append("Playwright result summary")
        for key in ("expected", "unexpected", "flaky", "skipped", "duration"):
            if key in stats:
                lines.append(f"{key}: {stats[key]}")
        lines.append("")

    for suite in results.get("suites") or []:
        if not isinstance(suite, dict):
            continue
        for spec in _iter_playwright_specs(suite):
            title = spec.get("title") or "Untitled test"
            file_name = spec.get("file") or suite.get("file") or ""
            lines.append(f"Test: {title}")
            if file_name:
                lines.append(f"File: {file_name}")
            lines.append(f"Status: {'passed' if spec.get('ok') else 'failed'}")

            for test in spec.get("tests") or []:
                if not isinstance(test, dict):
                    continue
                project = test.get("projectName") or test.get("projectId")
                if project:
                    lines.append(f"Project: {project}")
                for result in test.get("results") or []:
                    if not isinstance(result, dict):
                        continue
                    status = result.get("status")
                    duration = result.get("duration")
                    if status or duration is not None:
                        duration_text = f" ({duration}ms)" if duration is not None else ""
                        lines.append(f"Result: {status or 'unknown'}{duration_text}")

                    error = result.get("error") or {}
                    if isinstance(error, dict) and error:
                        message = error.get("message")
                        if message:
                            lines.append("")
                            lines.append(_strip_ansi(str(message)).strip())
                        snippet = error.get("snippet")
                        if snippet:
                            lines.append("")
                            lines.append("Code frame:")
                            lines.append(_strip_ansi(str(snippet)).rstrip())

                    for attachment in result.get("attachments") or []:
                        if not isinstance(attachment, dict):
                            continue
                        name = attachment.get("name")
                        path = attachment.get("path")
                        if name and path:
                            lines.append(f"Attachment: {name} ({path})")
            lines.append("")

    for error in results.get("errors") or []:
        if isinstance(error, dict) and error.get("message"):
            lines.append("Global error:")
            lines.append(_strip_ansi(str(error["message"])).strip())
            lines.append("")

    return "\n".join(line for line in lines).strip()


def _build_fallback_run_log(run_dir: Path) -> str | None:
    """Return a useful log when native runs did not write execution.log."""
    sections: list[str] = []

    status_file = run_dir / "status.txt"
    if status_file.exists():
        status = status_file.read_text(errors="replace").strip()
        if status:
            sections.append(f"Status\n{status}")

    results_file = run_dir / "test-results.json"
    if results_file.exists():
        try:
            results = json.loads(results_file.read_text(errors="replace"))
            if isinstance(results, dict):
                log = _build_log_from_playwright_results(results)
                if log:
                    sections.append(log)
        except Exception as exc:
            sections.append(f"Unable to parse test-results.json: {exc}")

    diagnosis_file = run_dir / "failure_diagnosis.json"
    if diagnosis_file.exists():
        try:
            diagnosis = json.loads(diagnosis_file.read_text(errors="replace"))
            if isinstance(diagnosis, dict):
                details = []
                for key in ("category", "confidence", "root_cause", "recommended_action"):
                    if diagnosis.get(key) is not None:
                        details.append(f"{key}: {diagnosis[key]}")
                evidence = diagnosis.get("evidence")
                if evidence:
                    details.append(f"evidence: {evidence}")
                if details:
                    sections.append("Failure diagnosis\n" + "\n".join(details))
        except Exception as exc:
            sections.append(f"Unable to parse failure_diagnosis.json: {exc}")

    context_files = sorted((run_dir / "test-results").glob("**/error-context.md"))
    if context_files:
        context_sections = []
        for context_file in context_files[:3]:
            try:
                context_sections.append(
                    f"### {context_file.relative_to(run_dir)}\n"
                    + context_file.read_text(errors="replace").strip()
                )
            except Exception:
                continue
        if context_sections:
            sections.append("Error context\n" + "\n\n".join(context_sections))

    return "\n\n".join(sections).strip() or None


def _read_text_if_exists(path: Path, *, max_chars: int | None = None) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(errors="replace")
    if max_chars is not None and len(text) > max_chars:
        return text[-max_chars:]
    return text


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(errors="replace"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _pipeline_error_message(error_data: dict[str, Any] | None) -> str | None:
    if not error_data:
        return None
    error = str(error_data.get("error") or "").strip()
    if not error:
        return None
    stage = str(error_data.get("stage") or "").strip()
    return f"[{stage}] {error}" if stage else error


def _format_pipeline_error_section(error_data: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in ("stage", "error", "error_tail", "timestamp"):
        value = error_data.get(key)
        if value:
            lines.append(f"{key}={value}")
    missing = error_data.get("missing_test_data") or error_data.get("missing")
    if isinstance(missing, list) and missing:
        lines.append(
            "missing_refs="
            + ", ".join(
                f"{item.get('ref')} ({item.get('reason') or 'not_found'})"
                for item in missing
                if isinstance(item, dict) and item.get("ref")
            )
        )
    return "\n".join(line for line in lines if line).strip()


def _format_test_data_section(run_dir: Path, pipeline_error: dict[str, Any] | None) -> str | None:
    lines: list[str] = []
    fixture_file = run_dir / "test-data" / "resolved-fixtures.json"
    fixture_data = _read_json_if_exists(fixture_file)

    refs: list[str] = []
    if fixture_data:
        refs = [str(item) for item in fixture_data.get("refs") or [] if item]
        items = fixture_data.get("items") if isinstance(fixture_data.get("items"), dict) else {}
        lines.append("fixture_file=" + str(fixture_file))
        lines.append("refs=" + (", ".join(refs) if refs else "-"))
        lines.append(f"resolved_count={len(items)}")
        lines.append("quorvex_test_data_file_injected=yes")

    missing = []
    if pipeline_error and pipeline_error.get("stage") == "test_data_resolution":
        missing = pipeline_error.get("missing_test_data") or pipeline_error.get("missing") or []
        refs = refs or [str(item) for item in pipeline_error.get("refs") or [] if item]
        if refs and not fixture_data:
            lines.append("refs=" + ", ".join(refs))
        if isinstance(missing, list) and missing:
            lines.append(
                "missing_refs="
                + ", ".join(
                    f"{item.get('ref')} ({item.get('reason') or 'not_found'})"
                    for item in missing
                    if isinstance(item, dict) and item.get("ref")
                )
            )
        lines.append("quorvex_test_data_file_injected=no")

    return "\n".join(line for line in lines if line).strip() or None


def _is_terminal_run_status(status: str | None) -> bool:
    return str(status or "").lower() in {
        "passed",
        "completed",
        "failed",
        "error",
        "cancelled",
        "canceled",
        "stopped",
        "aborted",
    }


def _format_browser_pool_status(status: dict[str, Any], run_id: str) -> tuple[str, str | None]:
    lines = [
        f"max_browsers={status.get('max_browsers')} running={status.get('running')} queued={status.get('queued')} available={status.get('available')}",
    ]
    running = [str(item) for item in status.get("running_requests") or []]
    queued = [str(item) for item in status.get("queued_requests") or []]
    if running:
        lines.append("running_requests=" + ", ".join(running))
    if queued:
        lines.append("queued_requests=" + ", ".join(queued))

    for detail in status.get("running_details") or []:
        if not isinstance(detail, dict):
            continue
        lines.append(
            "running_detail "
            f"{detail.get('request_id')} type={detail.get('operation_type')} "
            f"started_at={detail.get('started_at')} desc={detail.get('description')}"
        )

    blocker = None
    if run_id in running and any(item.startswith("agent:") for item in queued):
        blocker = "Planner agent is waiting for browser slot held by parent run."
        lines.insert(0, blocker)
    elif run_id not in running and any(item == run_id for item in queued):
        blocker = "Test run is waiting for a browser slot; no browser process has started yet."
        lines.insert(0, blocker)
    elif status.get("running", 0) == 0:
        blocker = "No browser process has started yet."

    return "\n".join(lines), blocker


async def compose_test_run_log_payload(run_db: DBTestRun, run_dir: Path) -> dict[str, Any]:
    """Build source-aware run log sections for active and completed browser runs."""
    sections: list[dict[str, Any]] = []
    diagnostics: dict[str, Any] = {}
    blocker_message: str | None = None
    pipeline_error = _read_json_if_exists(run_dir / "pipeline_error.json") if run_dir.exists() else None
    known_pipeline_error = bool(_pipeline_error_message(pipeline_error))

    lifecycle_lines = [
        f"run_id={run_db.id}",
        f"status={run_db.status}",
        f"stage={run_db.current_stage or '-'}",
        f"stage_message={run_db.stage_message or '-'}",
        f"queue_position={run_db.queue_position if run_db.queue_position is not None else '-'}",
        f"temporal_workflow_id={run_db.temporal_workflow_id or '-'}",
        f"temporal_run_id={run_db.temporal_run_id or '-'}",
    ]
    if run_db.browser_auth:
        lifecycle_lines.append("browser_auth=" + json.dumps(run_db.browser_auth, sort_keys=True))
    sections.append({"source": "db", "title": "Run Lifecycle", "content": "\n".join(lifecycle_lines)})

    if pipeline_error:
        diagnostics["pipeline_error"] = pipeline_error
        pipeline_error_text = _format_pipeline_error_section(pipeline_error)
        if pipeline_error_text:
            sections.append({"source": "pipeline_error.json", "title": "Pipeline Error", "content": pipeline_error_text})

    test_data_text = _format_test_data_section(run_dir, pipeline_error) if run_dir.exists() else None
    if test_data_text:
        sections.append({"source": "test_data", "title": "Test Data", "content": test_data_text})

    healing_attempts = _read_json_if_exists(run_dir / "healing_attempts.json") if run_dir.exists() else None
    if healing_attempts:
        diagnostics["healing_attempts"] = healing_attempts
        compact_attempts = []
        for attempt in (healing_attempts.get("attempts") or [])[:5]:
            if not isinstance(attempt, dict):
                continue
            compact_attempts.append(
                {
                    "attempt": attempt.get("attempt"),
                    "passed_after": attempt.get("passed_after"),
                    "error_category": attempt.get("error_category"),
                    "guardrail_status": attempt.get("guardrail_status"),
                    "first_tool": attempt.get("first_tool"),
                    "mcp_evidence_tools_used": attempt.get("mcp_evidence_tools_used"),
                    "missing_required_tools": attempt.get("missing_required_tools"),
                }
            )
        sections.append(
            {
                "source": "healing_attempts.json",
                "title": "Healing Attempts",
                "content": json.dumps({"attempts": compact_attempts}, indent=2),
            }
        )

    failure_evidence = _read_json_if_exists(run_dir / "failure_evidence_packet.json") if run_dir.exists() else None
    if failure_evidence:
        diagnostics["failure_evidence"] = failure_evidence
        sections.append(
            {
                "source": "failure_evidence_packet.json",
                "title": "Latest Failure Evidence",
                "content": json.dumps(
                    {
                        "attempt": failure_evidence.get("attempt"),
                        "failed_test": failure_evidence.get("failed_test"),
                        "mcp_evidence": failure_evidence.get("mcp_evidence"),
                        "error_summary": failure_evidence.get("error_summary"),
                    },
                    indent=2,
                ),
            }
        )

    execution_log = _read_text_if_exists(run_dir / "execution.log") if run_dir.exists() else None
    if execution_log:
        sections.append({"source": "execution.log", "title": "Run Log", "content": execution_log})
    else:
        fallback_log = _build_fallback_run_log(run_dir) if run_dir.exists() else None
        sections.append(
            {
                "source": "execution.log",
                "title": "Run Log",
                "content": fallback_log or "No execution.log has been written yet.",
            }
        )

    workflow_log = _read_text_if_exists(run_dir / "workflow.log") if run_dir.exists() else None
    if workflow_log:
        sections.append({"source": "workflow.log", "title": "Workflow Log", "content": workflow_log})

    try:
        pool = await _browser_pool()
        browser_status = await pool.get_status()
        browser_text, browser_blocker = _format_browser_pool_status(browser_status, run_db.id)
        diagnostics["browser_pool"] = browser_status
        suppress_browser_blocker = _is_terminal_run_status(run_db.status) and known_pipeline_error
        if browser_blocker and suppress_browser_blocker:
            browser_text = "\n".join(line for line in browser_text.splitlines() if line != browser_blocker)
        elif browser_blocker:
            blocker_message = browser_blocker
        sections.append({"source": "browser_pool", "title": "Browser Pool", "content": browser_text})
    except Exception as exc:
        sections.append(
            {"source": "browser_pool", "title": "Browser Pool", "content": f"Browser pool diagnostics unavailable: {exc}"}
        )

    if run_db.temporal_workflow_id:
        try:
            from orchestrator.services.temporal_client import get_test_run_temporal_diagnostics

            temporal = await get_test_run_temporal_diagnostics(run_db.temporal_workflow_id, run_db.temporal_run_id)
            diagnostics["temporal"] = temporal
            temporal_lines = [
                f"workflow_type={temporal.get('workflow_type')}",
                f"workflow_status={temporal.get('workflow_status')}",
                f"task_queue={temporal.get('task_queue')}",
                f"history_event_count={temporal.get('history_event_count')}",
                f"activities={len(temporal.get('activities') or [])}",
            ]
            if temporal.get("error"):
                temporal_lines.append(f"error={temporal.get('error')}")
            for activity in temporal.get("activities") or []:
                if not isinstance(activity, dict):
                    continue
                temporal_lines.append(
                    f"activity {activity.get('activity_type')} status={activity.get('status')} "
                    f"attempts={activity.get('attempt_count')} worker={activity.get('last_worker_identity') or '-'}"
                )
            sections.append({"source": "temporal", "title": "Temporal Workflow", "content": "\n".join(temporal_lines)})
        except Exception as exc:
            sections.append(
                {"source": "temporal", "title": "Temporal Workflow", "content": f"Temporal diagnostics unavailable: {exc}"}
            )
    else:
        sections.append(
            {
                "source": "temporal",
                "title": "Temporal Workflow",
                "content": "No Temporal workflow id has been recorded for this run.",
            }
        )

    combined_log = "\n\n".join(
        f"## {section['title']}\n{section['content']}"
        for section in sections
        if section.get("content")
    ).strip()
    return {
        "log": combined_log,
        "log_sections": sections,
        "diagnostics": diagnostics,
        "blocker_message": blocker_message,
    }


def build_run_browser_metadata(headless: bool, phase: str, task_queue: str | None = None) -> dict[str, Any]:
    """Describe whether this specific run should be visible in live browser view."""
    metadata = dict(_browser_runtime_status())
    runtime_live = bool(metadata.get("live_view_available"))
    live_view_available = runtime_live and not headless
    runtime_message = metadata.get("runtime_message")
    if headless:
        runtime_message = "Browser execution is running headless; live view is unavailable."
    elif not runtime_live:
        runtime_message = runtime_message or "No live browser runtime is available for this run."

    metadata.update(
        {
            "phase": phase,
            "headless": headless,
            "headed": not headless,
            "live_view_available": live_view_available,
            "runtime_message": runtime_message,
            "updated_at": datetime.utcnow().isoformat(),
        }
    )
    if task_queue:
        metadata["task_queue"] = task_queue
    return metadata


def merge_run_browser_metadata(
    base_metadata: dict[str, Any],
    extra_metadata: dict[str, Any],
    *,
    headless: bool,
    phase: str,
    task_queue: str | None = None,
) -> dict[str, Any]:
    metadata = {**base_metadata, **extra_metadata}
    metadata.update(
        {
            "phase": phase,
            "headless": headless,
            "headed": not headless,
            "live_view_available": bool(metadata.get("live_view_available")) and not headless,
            "updated_at": datetime.utcnow().isoformat(),
        }
    )
    if headless:
        metadata["runtime_message"] = "Browser execution is running headless; live view is unavailable."
    elif not metadata.get("runtime_message"):
        metadata["runtime_message"] = "Browser will run on the VNC display."
    if task_queue:
        metadata["task_queue"] = task_queue
    return metadata


def write_run_browser_metadata(run_dir: Path, metadata: dict[str, Any]) -> None:
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / RUN_BROWSER_METADATA_FILE).write_text(json.dumps(metadata, indent=2))
    except Exception as exc:
        logger.warning(f"Failed to write browser runtime metadata for {run_dir}: {exc}")


def load_run_browser_metadata(run_dir: Path) -> dict[str, Any]:
    metadata = dict(_browser_runtime_status())
    metadata_path = run_dir / RUN_BROWSER_METADATA_FILE
    if metadata_path.exists():
        try:
            saved = json.loads(metadata_path.read_text())
            if isinstance(saved, dict):
                metadata.update(saved)
        except Exception as exc:
            logger.warning(f"Failed to read browser runtime metadata from {metadata_path}: {exc}")
    metadata["live_view_available"] = bool(metadata.get("live_view_available"))
    return metadata


def extract_run_target_url_from_content(spec_content: str) -> str | None:
    for pattern in RUN_TARGET_URL_PATTERNS:
        match = re.search(pattern, spec_content, re.IGNORECASE)
        if match:
            return match.group(1).rstrip(".,);]")
    return None


def extract_run_target_url(spec_path: str) -> str | None:
    path = Path(spec_path)
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([BASE_DIR / path, SPECS_DIR / path])

    for candidate in candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            return extract_run_target_url_from_content(candidate.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"Failed to extract target URL from {candidate}: {exc}")
            return None
    return None


def browser_reachable_url(target_url: str | None) -> str | None:
    """Rewrite host-local URLs to an address reachable from Docker browsers."""
    if not target_url:
        return target_url
    try:
        parsed = urlsplit(target_url)
    except Exception:
        return target_url
    if parsed.scheme not in {"http", "https"}:
        return target_url
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
        return target_url

    replacement_host = os.environ.get("BROWSER_HOST_INTERNAL") or "host.docker.internal"
    netloc = replacement_host
    if parsed.port:
        netloc = f"{replacement_host}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def write_run_seed_spec(run_dir: Path, target_url: str | None) -> Path:
    seed_dst = run_dir / RUN_SEED_SPEC_RELATIVE_PATH
    seed_dst.parent.mkdir(parents=True, exist_ok=True)
    browser_url = browser_reachable_url(target_url)
    seed_content = "\n".join(
        [
            "import { test } from '@playwright/test';",
            "",
            f"const targetUrl = {json.dumps(browser_url or '')};",
            "",
            "test('seed target page', async ({ page }) => {",
            "  await page.goto(targetUrl || 'about:blank');",
            "});",
            "",
        ]
    )
    seed_dst.write_text(seed_content, encoding="utf-8")
    return seed_dst


def is_real_browser_process_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False

    parts = stripped.split(None, 2)
    command = ""
    args = stripped
    if len(parts) >= 3 and parts[0].isdigit():
        command = Path(parts[1]).name.lower()
        args = parts[2]
    elif len(parts) >= 2 and parts[0].isdigit():
        args = parts[1]

    if command in REAL_BROWSER_EXECUTABLE_NAMES:
        return True

    try:
        tokens = shlex.split(args)
    except ValueError:
        tokens = args.split()
    if not tokens:
        return False

    executable_name = Path(tokens[0]).name.lower()
    return executable_name in REAL_BROWSER_EXECUTABLE_NAMES


def browser_window_lines(xwininfo_output: str, browser_process_count: int) -> list[str]:
    browser_named_windows: list[str] = []
    unnamed_visible_windows: list[str] = []
    for line in xwininfo_output.splitlines():
        if re.search(r"\b(chrome|chromium|firefox|webkit)\b", line, re.IGNORECASE):
            browser_named_windows.append(line)
            continue
        if browser_process_count > 0 and re.search(
            r'0x[0-9a-f]+\s+(?:"(?:has no name|)"|\(has no name\):)',
            line,
            re.IGNORECASE,
        ):
            if re.search(r"\s[1-9]\d{2,}x[1-9]\d{2,}\+", line):
                unnamed_visible_windows.append(line)

    return browser_named_windows or unnamed_visible_windows


def live_browser_display_diagnostics_for_run() -> dict[str, Any]:
    return _live_browser_display_diagnostics()


def augment_active_browser_metadata(metadata: dict[str, Any], status: str | None) -> dict[str, Any]:
    if status not in {"queued", "pending", "running", "in_progress"}:
        return metadata
    if not metadata.get("live_view_available") or metadata.get("headless") is True:
        return metadata
    if metadata.get("browser_runtime") == "temporal_vnc_worker":
        # Execution is delegated to a live browser worker; local display
        # diagnostics describe the backend container and would be misleading.
        return metadata

    diagnostics = live_browser_display_diagnostics_for_run()
    metadata = dict(metadata)
    metadata["display_diagnostics"] = diagnostics
    if diagnostics.get("vnc_server_available") is False:
        metadata["runtime_message"] = "VNC server is unavailable inside the backend container."
    elif diagnostics.get("browser_window_count") in (0, None) and not metadata.get("runtime_message"):
        metadata["runtime_message"] = "VNC is connected; waiting for Playwright to launch a visible browser window."
    return metadata
