"""Shared agent-run progress and runtime recovery helpers."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time as time_module
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlmodel import Session

from orchestrator.services.agent_run_events import create_agent_run_event
from orchestrator.services.agent_runtimes import normalize_agent_runtime
from orchestrator.services.browser_auth_sessions import BrowserAuthSessionError
from utils.agent_report import _build_custom_agent_structured_report, _clean_text
from utils.agent_tool_allowlists import get_agent_allowed_tools
from utils.playwright_mcp import (
    prepare_run_playwright_config_content,
    resolve_playwright_chromium_executable,
    write_playwright_mcp_config,
    write_playwright_test_mcp_config,
)

from . import agent_run_observability, agent_run_runtime, spec_files
from .db import engine
from .models_db import AgentRun

logger = logging.getLogger(__name__)

RUNS_DIR = spec_files.RUNS_DIR
BASE_DIR = spec_files.BASE_DIR
AGENT_NOTE_MCP_SERVER_NAME = "quorvex-agent"
AGENT_NOTE_MCP_TOOL_NAME = "mcp__quorvex-agent__quorvex_record_note"


def _current_runs_dir() -> Path:
    main_module = sys.modules.get("orchestrator.api.main")
    return getattr(main_module, "RUNS_DIR", RUNS_DIR)


def _sync_agent_run_observability_runs_dir() -> None:
    agent_run_observability.RUNS_DIR = _current_runs_dir()


def _browser_auth_selection(config: dict[str, Any]) -> tuple[str | None, bool]:
    auth_config = config.get("browser_auth") if isinstance(config.get("browser_auth"), dict) else {}
    legacy_auth = config.get("auth") if isinstance(config.get("auth"), dict) else {}
    browser_auth_session_id = (
        config.get("browser_auth_session_id")
        or auth_config.get("session_id")
        or legacy_auth.get("browser_auth_session_id")
        or legacy_auth.get("session_id")
    )
    use_default = bool(
        config.get("use_project_default_browser_auth")
        or auth_config.get("use_project_default")
        or auth_config.get("use_project_default_browser_auth")
        or legacy_auth.get("use_default")
        or legacy_auth.get("use_project_default")
        or legacy_auth.get("use_project_default_browser_auth")
    )
    return browser_auth_session_id, use_default


def _browser_auth_request_fields_set(request: Any) -> set[str]:
    fields = getattr(request, "model_fields_set", None)
    if fields is None:
        fields = getattr(request, "__fields_set__", set())
    return set(fields or set())


def _without_spec_generation_auth(config: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in config.items()
        if key not in {"auth", "browser_auth", "browser_auth_session_id", "use_project_default_browser_auth"}
    }


def _apply_report_spec_browser_auth_request(
    inherited_config: dict[str, Any],
    request: Any | None,
) -> tuple[dict[str, Any], bool]:
    if request is None:
        return inherited_config, True

    fields_set = _browser_auth_request_fields_set(request)
    browser_auth_session_id = str(request.browser_auth_session_id or "").strip()
    if request.skip_browser_auth:
        return _without_spec_generation_auth(inherited_config), False
    if browser_auth_session_id:
        return {**_without_spec_generation_auth(inherited_config), "browser_auth_session_id": browser_auth_session_id}, False
    if request.use_project_default_browser_auth:
        return {**_without_spec_generation_auth(inherited_config), "use_project_default_browser_auth": True}, False
    if request.inherit_browser_auth or not fields_set:
        return inherited_config, True
    return _without_spec_generation_auth(inherited_config), False


def _safe_inherited_auth_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    safe_keys = {
        "browser_auth_session_id",
        "session_id",
        "session_name",
        "use_default",
        "use_project_default",
        "use_project_default_browser_auth",
    }
    return {key: value[key] for key in safe_keys if key in value and value[key] is not None}


def _build_spec_generation_source_config(
    source_config: dict[str, Any],
    *,
    target_url: str,
    project_id: str | None,
) -> dict[str, Any]:
    """Carry only non-secret context needed by browser-backed spec generation."""
    inherited: dict[str, Any] = {
        "url": str(source_config.get("url") or target_url or "").strip(),
    }
    if project_id:
        inherited["project_id"] = project_id
    elif source_config.get("project_id"):
        inherited["project_id"] = source_config.get("project_id")

    if source_config.get("browser_auth_session_id"):
        inherited["browser_auth_session_id"] = source_config.get("browser_auth_session_id")
    if source_config.get("use_project_default_browser_auth"):
        inherited["use_project_default_browser_auth"] = True

    auth_config = _safe_inherited_auth_config(source_config.get("auth"))
    if auth_config:
        inherited["auth"] = auth_config
    browser_auth_config = _safe_inherited_auth_config(source_config.get("browser_auth"))
    if browser_auth_config:
        inherited["browser_auth"] = browser_auth_config
    return inherited


def _spec_generation_auth_metadata(config: dict[str, Any], *, inherited: bool = True) -> dict[str, Any]:
    browser_auth_session_id, use_default = _browser_auth_selection(config)
    metadata: dict[str, Any] = {}
    if browser_auth_session_id:
        metadata["browser_auth_session_id"] = browser_auth_session_id
    if use_default:
        metadata["use_project_default_browser_auth"] = True
    if metadata and inherited:
        metadata["browser_auth_inherited"] = True
    return metadata


class AgentBrowserAuthResolutionError(RuntimeError):
    def __init__(self, message: str, *, browser_auth_session_id: str | None, use_default: bool):
        super().__init__(message)
        self.browser_auth_session_id = browser_auth_session_id
        self.use_default = use_default


class AgentBrowserAuthPreflightError(AgentBrowserAuthResolutionError):
    """Raised when an attached browser auth session cannot open the target."""


@dataclass(frozen=True)
class BrowserAuthPreflightResult:
    status: str
    url: str | None = None
    title: str | None = None
    failure_reason: str | None = None
    failure_kind: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "passed"


AUTH_PREFLIGHT_CHALLENGE_MESSAGE = (
    "Saved browser session was attached, but target opened a security challenge. "
    "Refresh the browser auth session or use a trusted browser context."
)
AUTH_PREFLIGHT_SESSION_FAILED_MESSAGE = (
    "Saved browser session was attached, but target did not open as an authenticated session. "
    "Refresh the browser auth session or use a trusted browser context."
)


def _sanitize_preflight_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parts = urlsplit(str(value))
    except ValueError:
        return str(value)[:500]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))[:500]


def _detect_browser_auth_preflight_failure(
    *,
    final_url: str | None,
    title: str | None,
    body_text: str | None,
    has_password_field: bool = False,
) -> tuple[str | None, str | None]:
    haystack = "\n".join(str(part or "") for part in [final_url, title, body_text]).lower()
    challenge_patterns = [
        r"\bjust a moment\b",
        r"\bsecurity check\b",
        r"\bchecking your browser\b",
        r"\bverify you are human\b",
        r"\bcloudflare\b",
        r"\bchallenge-platform\b",
        r"\bcaptcha\b",
        r"\bturnstile\b",
    ]
    if any(re.search(pattern, haystack, re.IGNORECASE) for pattern in challenge_patterns):
        return "challenge", AUTH_PREFLIGHT_CHALLENGE_MESSAGE
    if has_password_field:
        return "login", (
            "Saved browser session was attached, but target opened a password prompt. "
            "Refresh the browser auth session or use a trusted browser context."
        )
    try:
        path = urlsplit(str(final_url or "")).path.lower()
    except ValueError:
        path = str(final_url or "").lower()
    if re.search(r"(^|/)(login|signin|sign-in|auth|account/login)(/|$)", path):
        return "login", (
            "Saved browser session was attached, but target opened a login page. "
            "Refresh the browser auth session or use a trusted browser context."
        )
    login_text_patterns = [
        r"\bsign in\b",
        r"\blog in\b",
        r"\bforgot password\b",
        r"\bemail address\b.*\bpassword\b",
    ]
    if any(re.search(pattern, haystack, re.IGNORECASE | re.DOTALL) for pattern in login_text_patterns):
        return "login", (
            "Saved browser session was attached, but target still appears to require login. "
            "Refresh the browser auth session or use a trusted browser context."
        )
    return None, None


def _browser_auth_preflight_script(executable_path: str | None = None) -> str:
    executable_option = f", executablePath: {json.dumps(executable_path)}" if executable_path else ""
    return f"""
const {{ chromium }} = require('playwright');
const storageState = process.env.QUORVEX_AUTH_PREFLIGHT_STORAGE_STATE;
const targetUrl = process.env.QUORVEX_AUTH_PREFLIGHT_TARGET_URL;
const timeoutMs = Number(process.env.QUORVEX_AUTH_PREFLIGHT_TIMEOUT_MS || '15000');
const headless = String(process.env.HEADLESS || process.env.PLAYWRIGHT_HEADLESS || 'true').toLowerCase() !== 'false';

(async () => {{
  const browser = await chromium.launch({{ headless{executable_option} }});
  const context = await browser.newContext({{ storageState }});
  const page = await context.newPage();
  let responseStatus = null;
  try {{
    const response = await page.goto(targetUrl, {{ waitUntil: 'domcontentloaded', timeout: timeoutMs }});
    responseStatus = response ? response.status() : null;
    await page.waitForLoadState('domcontentloaded', {{ timeout: Math.min(timeoutMs, 5000) }}).catch(() => null);
    const result = await page.evaluate(() => {{
      const body = document.body ? document.body.innerText || '' : '';
      return {{
        url: window.location.href,
        title: document.title || '',
        body_text: body.slice(0, 5000),
        has_password_field: Boolean(document.querySelector('input[type="password"]')),
      }};
    }});
    console.log(JSON.stringify({{ ok: true, response_status: responseStatus, ...result }}));
  }} finally {{
    await browser.close();
  }}
}})().catch((error) => {{
  console.log(JSON.stringify({{ ok: false, error: error && error.message ? error.message : String(error) }}));
  process.exit(0);
}});
"""


def _run_browser_auth_preflight(
    *,
    storage_state_path: Path,
    target_url: str,
    timeout_seconds: int = 20,
    resolve_chromium_executable: Callable[[], Path | None] = resolve_playwright_chromium_executable,
) -> BrowserAuthPreflightResult:
    executable_path = resolve_chromium_executable()
    env = os.environ.copy()
    env["QUORVEX_AUTH_PREFLIGHT_STORAGE_STATE"] = str(storage_state_path)
    env["QUORVEX_AUTH_PREFLIGHT_TARGET_URL"] = target_url
    env["QUORVEX_AUTH_PREFLIGHT_TIMEOUT_MS"] = str(max(5, timeout_seconds) * 1000)
    try:
        result = subprocess.run(
            ["node", "-e", _browser_auth_preflight_script(str(executable_path) if executable_path else None)],
            cwd=str(BASE_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 5,
        )
    except subprocess.TimeoutExpired:
        return BrowserAuthPreflightResult(
            status="failed",
            failure_kind="timeout",
            failure_reason="Saved browser session validation timed out before the target page opened.",
        )

    output = (result.stdout or "").strip().splitlines()[-1] if (result.stdout or "").strip() else ""
    try:
        payload = json.loads(output) if output else {}
    except json.JSONDecodeError:
        payload = {}
    if not payload.get("ok"):
        error = str(payload.get("error") or result.stderr or "Browser auth session validation failed.").strip()
        return BrowserAuthPreflightResult(
            status="failed",
            failure_kind="preflight_error",
            failure_reason=f"Saved browser session validation failed before the target page opened: {error[:500]}",
        )

    failure_kind, failure_reason = _detect_browser_auth_preflight_failure(
        final_url=payload.get("url"),
        title=payload.get("title"),
        body_text=payload.get("body_text"),
        has_password_field=bool(payload.get("has_password_field")),
    )
    if failure_reason:
        return BrowserAuthPreflightResult(
            status="failed",
            url=_sanitize_preflight_url(payload.get("url")),
            title=str(payload.get("title") or "")[:300],
            failure_kind=failure_kind,
            failure_reason=failure_reason,
        )
    return BrowserAuthPreflightResult(
        status="passed",
        url=_sanitize_preflight_url(payload.get("url")),
        title=str(payload.get("title") or "")[:300],
    )


def _preflight_progress_payload(
    result: BrowserAuthPreflightResult,
    *,
    storage_state_attached: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "storage_state_attached": storage_state_attached,
        "auth_preflight_status": result.status,
        "auth_preflight_url": _sanitize_preflight_url(result.url),
        "auth_preflight_title": result.title,
    }
    if result.failure_reason:
        payload["auth_preflight_failure_reason"] = result.failure_reason
    if result.failure_kind:
        payload["auth_preflight_failure_kind"] = result.failure_kind
    return payload


def _record_browser_auth_preflight_event(run_id: str, result: BrowserAuthPreflightResult) -> None:
    create_agent_run_event(
        run_id=run_id,
        event_type="auth_preflight",
        level="info" if result.passed else "error",
        message="Browser auth preflight passed." if result.passed else result.failure_reason or AUTH_PREFLIGHT_SESSION_FAILED_MESSAGE,
        payload=_preflight_progress_payload(result, storage_state_attached=True),
    )


def _mark_agent_run_auth_preflight_failed(run_id: str, result: BrowserAuthPreflightResult) -> None:
    message = result.failure_reason or AUTH_PREFLIGHT_SESSION_FAILED_MESSAGE
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if not run:
            return
        if run.status in {"completed", "completed_partial", "failed", "cancelled", "timeout"}:
            return
        run.status = "failed"
        run.completed_at = datetime.utcnow()
        existing_result = run.result if isinstance(run.result, dict) else {}
        run.result = {
            **existing_result,
            "error": message,
            "failure_reason": "browser_auth_preflight_failed",
            "auth_preflight": _preflight_progress_payload(result, storage_state_attached=True),
        }
        run.finalization_status = "failed"
        run.progress = {
            **(run.progress or {}),
            **_preflight_progress_payload(result, storage_state_attached=True),
            "phase": "failed",
            "status": "failed",
            "message": message,
            "updated_at": datetime.utcnow().isoformat(),
        }
        session.add(run)
        session.commit()


def _resolve_agent_browser_auth_storage_path(
    *,
    run_id: str,
    project_id: str | None,
    config: dict[str, Any],
    run_dir: Path,
    resolve_browser_auth_for_run: Callable[..., Any],
    update_progress: Callable[[str, dict[str, Any]], None],
    preflight_runner: Callable[..., BrowserAuthPreflightResult] = _run_browser_auth_preflight,
    preflight_enabled: bool = False,
) -> Path | None:
    browser_auth_session_id, use_default = _browser_auth_selection(config)
    if not (browser_auth_session_id or use_default):
        return None
    try:
        with Session(engine) as db_session:
            resolved = resolve_browser_auth_for_run(
                db_session,
                project_id,
                run_dir=run_dir,
                browser_auth_session_id=browser_auth_session_id,
                use_default=use_default,
            )
    except BrowserAuthSessionError as exc:
        message = f"{exc}. Refresh browser auth session."
        update_progress(
            run_id,
            {
                "phase": "failed",
                "status": "failed",
                "message": message,
            },
        )
        raise AgentBrowserAuthResolutionError(
            message,
            browser_auth_session_id=browser_auth_session_id,
            use_default=use_default,
        ) from exc
    if resolved:
        update_progress(
            run_id,
            {
                "browser_auth_session_id": resolved.session_id,
                "browser_auth_session_name": resolved.session_name,
                "storage_state_attached": True,
                "message": "Using project browser auth session.",
            },
        )
        target_url = str(config.get("url") or "").strip()
        if preflight_enabled and target_url:
            preflight = preflight_runner(
                storage_state_path=resolved.storage_state_path,
                target_url=target_url,
            )
            update_progress(run_id, _preflight_progress_payload(preflight, storage_state_attached=True))
            _record_browser_auth_preflight_event(run_id, preflight)
            if not preflight.passed:
                _mark_agent_run_auth_preflight_failed(run_id, preflight)
                raise AgentBrowserAuthPreflightError(
                    preflight.failure_reason or AUTH_PREFLIGHT_SESSION_FAILED_MESSAGE,
                    browser_auth_session_id=resolved.session_id,
                    use_default=use_default,
                )
    return resolved.storage_state_path if resolved else None


def _prepare_custom_agent_mcp_config(
    run_id: str,
    storage_state_path: Path | str | None = None,
    *,
    include_browser_tools: bool = True,
    include_agent_note_tool: bool = False,
    update_progress: Callable[[str, dict[str, Any]], None],
) -> Path:
    """Create run-local MCP config for UI-created custom agents."""
    run_dir = _current_runs_dir() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    runtime: dict[str, Any] = {}
    if include_browser_tools:
        runtime = write_playwright_mcp_config(
            run_dir=run_dir,
            server_name="playwright-test",
            project_root=BASE_DIR,
            storage_state_path=storage_state_path,
        )
    if include_agent_note_tool:
        _add_agent_note_mcp_server(run_dir=run_dir, run_id=run_id)
        runtime = {
            **runtime,
            "agent_note_mcp_server": AGENT_NOTE_MCP_SERVER_NAME,
            "agent_note_tool": AGENT_NOTE_MCP_TOOL_NAME,
            "mcp_config_path": str(run_dir / ".mcp.json"),
        }
    update_progress(run_id, runtime)
    return run_dir


def _add_agent_note_mcp_server(*, run_dir: Path, run_id: str) -> None:
    config_path = run_dir / ".mcp.json"
    try:
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
    except Exception:
        config = {}
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        config["mcpServers"] = servers
    pythonpath_parts = [str(BASE_DIR)]
    if os.environ.get("PYTHONPATH"):
        pythonpath_parts.append(os.environ["PYTHONPATH"])
    servers[AGENT_NOTE_MCP_SERVER_NAME] = {
        "command": sys.executable,
        "args": [str(BASE_DIR / "tools" / "agent_note_mcp" / "server.py")],
        "env": {
            "PYTHONPATH": os.pathsep.join(pythonpath_parts),
            "QUORVEX_AGENT_RUN_ID": run_id,
        },
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _prepare_spec_generation_mcp_config(
    run_dir: Path,
    storage_state_path: Path | str | None = None,
) -> dict[str, Any]:
    """Create run-local Playwright Test MCP config for browser-backed spec generation."""
    run_dir.mkdir(parents=True, exist_ok=True)
    source_config_path = BASE_DIR / "playwright.config.ts"
    run_config_path = run_dir / "playwright.config.ts"
    config_content = source_config_path.read_text(encoding="utf-8")
    run_config_path.write_text(
        prepare_run_playwright_config_content(
            config_content,
            base_dir=BASE_DIR,
            run_dir=run_dir,
            headless=True,
            storage_state_path=storage_state_path,
        ),
        encoding="utf-8",
    )
    return write_playwright_test_mcp_config(
        run_dir=run_dir,
        server_name="playwright-test",
        config_path=run_config_path,
        headless=True,
        storage_state_path=storage_state_path,
    )


def _resolve_playwright_chromium_executable() -> Path | None:
    """Find a Chromium executable already installed in the backend image."""
    return resolve_playwright_chromium_executable()


def _playwright_chromium_probe_script(executable_path: str | None = None) -> str:
    """Return a Node probe that launches and closes the installed Chromium."""
    executable_option = f", executablePath: {json.dumps(executable_path)}" if executable_path else ""
    return f"""
const {{ chromium }} = require('playwright');
const headless = String(process.env.HEADLESS || 'true').toLowerCase() !== 'false';
(async () => {{
  const browser = await chromium.launch({{ headless{executable_option.strip()} }});
  await browser.close();
}})().catch((error) => {{
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
}});
"""


def _probe_custom_agent_browser(
    timeout_seconds: int = 30,
    *,
    resolve_chromium_executable: Callable[[], Path | None] = _resolve_playwright_chromium_executable,
) -> tuple[bool, str]:
    """Check whether the installed Playwright Chromium can launch without installing it."""
    env = os.environ.copy()
    env.setdefault("PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT", "300000")
    executable_path = resolve_chromium_executable()
    try:
        result = subprocess.run(
            ["node", "-e", _playwright_chromium_probe_script(str(executable_path) if executable_path else None)],
            cwd=str(BASE_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(
            str(value)
            for value in (getattr(exc, "stdout", None), getattr(exc, "stderr", None))
            if value
        ).strip()
        return False, output or f"Timed out after {timeout_seconds}s launching Playwright Chromium"

    combined_output = f"{result.stdout}\n{result.stderr}".strip()
    return result.returncode == 0, combined_output


def _custom_agent_uses_browser_tools(allowed_tools: list[Any]) -> bool:
    return agent_run_runtime.custom_agent_uses_browser_tools(allowed_tools)


def _custom_agent_browser_runs_via_queue() -> bool:
    return agent_run_runtime.custom_agent_browser_runs_via_queue()


def _agent_run_has_browser_tools(agent_type: str, config: dict[str, Any]) -> bool:
    """Return whether this agent run will need a Playwright browser."""
    if agent_type == "custom":
        return _custom_agent_uses_browser_tools(config.get("allowed_tools") or [])
    return agent_type in ("exploratory", "spec_generation")


def _generic_agent_runtime_prompt(agent_type: str, config: dict[str, Any]) -> str:
    """Build a Quorvex-owned prompt for non-Claude runtime adapters."""
    if agent_type == "exploratory":
        from orchestrator.agents.exploratory_agent import ExploratoryAgent

        agent = ExploratoryAgent()
        return agent._build_exploration_prompt(
            url=config.get("url"),
            instructions=config.get("instructions", ""),
            time_limit_minutes=int(config.get("time_limit_minutes") or 15),
            auth_config=config.get("auth") or {"type": "none"},
            test_data=config.get("test_data") or {},
            focus_areas=config.get("focus_areas") or [],
            excluded_patterns=config.get("excluded_patterns") or [],
            browser_memory_context=config.get("browser_memory_context") or "",
            advanced_tools=bool(config.get("advanced_tools") or config.get("record_video") or config.get("capture_video")),
        )
    if agent_type == "spec-synthesis":
        return "\n".join(
            [
                "You are a Quorvex test-spec synthesis agent.",
                "Use the supplied exploration result to draft production-ready test scenarios. Return JSON with summary and specs.",
                "Do not write repository files; propose content only.",
                f"Config JSON:\n{json.dumps(config, indent=2, default=str)}",
            ]
        )
    return "\n".join(
        [
            "You are a Quorvex QA automation agent.",
            "Complete the requested task and return a concise factual report.",
            f"Config JSON:\n{json.dumps(config, indent=2, default=str)}",
        ]
    )


KNOWN_AGENT_TYPE_TOOL_PROFILES = {
    "exploratory": "app-explorer-basic",
    "writer": "app-explorer-basic",
    "spec-synthesis": "text-analysis",
}


def _agent_tool_profile_for_run(agent_type: str, config: dict[str, Any]) -> str | None:
    configured = str(config.get("agent_tool_profile") or "").strip()
    if configured:
        return configured
    if agent_type == "exploratory" and bool(
        config.get("advanced_tools") or config.get("record_video") or config.get("capture_video")
    ):
        return "app-explorer-advanced"
    return KNOWN_AGENT_TYPE_TOOL_PROFILES.get(agent_type)


def _resolve_known_agent_allowed_tools(
    agent_type: str,
    config: dict[str, Any],
    *,
    mcp_config_dir: Path | str | None = None,
) -> list[str] | None:
    """Resolve explicit tools for known built-in agent types."""
    profile_name = _agent_tool_profile_for_run(agent_type, config)
    if not profile_name:
        return None
    config["agent_tool_profile"] = profile_name
    return get_agent_allowed_tools(profile_name, mcp_config_dir=mcp_config_dir)


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


def _is_claude_code_auth_failure_text(value: Any) -> bool:
    lowered = str(value or "").lower()
    return (
        "claude_code_auth_required" in lowered
        or "authentication_failed" in lowered
        or ("not logged in" in lowered and "run /login" in lowered)
        or ("token expired or incorrect" in lowered and "401" in lowered)
        or (
            "claude code authentication" in lowered
            and "claude_code_oauth_token" in lowered
        )
    )


def _recover_custom_agent_partial_result(run: AgentRun, error: Exception | str) -> dict[str, Any] | None:
    if _is_claude_code_auth_failure_text(error):
        return None
    artifacts = _collect_agent_run_artifacts(run.id)
    raw_output = _read_run_text_artifact(run.id, "raw_output.txt")
    if _is_claude_code_auth_failure_text(raw_output):
        return None
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
            existing_phase = str(existing.get("phase") or "").lower()
            incoming_phase = str(progress_patch.get("phase") or "").lower()
            active_phases = {"starting", "running", "tool_use", "tool_result", "browser_slot", "retrying"}
            if incoming_phase == "queued" and existing_phase in active_phases:
                progress_patch["phase"] = existing.get("phase")
            elif incoming_phase == "queued" and progress_patch.get("agent_task_id"):
                progress_patch["phase"] = "worker_wait"
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
            progress_phase = str(progress.get("phase") or "").lower()
            execution_evidence = (
                progress_phase in active_phases
                or int(progress.get("tool_calls") or 0) > 0
                or int(progress.get("browser_tool_calls") or progress.get("interactions") or 0) > 0
            )
            if run.status in {"queued", "pending", "waiting"} and execution_evidence:
                run.status = "running"
                if not run.started_at:
                    run.started_at = datetime.utcnow()
                progress["status"] = "running"
                if progress_phase in {"queued", "pending", "waiting", ""}:
                    progress["phase"] = "running"
                run.progress = progress
            session.add(run)
            session.commit()
    except Exception as exc:
        logger.debug("Failed to update custom agent progress for %s: %s", run_id, exc)
