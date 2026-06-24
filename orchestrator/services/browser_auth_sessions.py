"""Project-scoped reusable browser authentication sessions."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from orchestrator.api.credentials import (
    decrypt_credential,
    encrypt_credential,
    get_merged_credentials,
)
from orchestrator.api.models_db import BrowserAuthSession, Project
from orchestrator.api.settings import runtime_env_vars
from orchestrator.services.ai_runtime_config import (
    apply_runtime_env_aliases,
    infer_display_provider,
)
from orchestrator.services.browser_pool import OperationType
from orchestrator.services.browser_slots import (
    BrowserSlotAcquisitionError,
    browser_operation_slot,
)
from orchestrator.utils.agent_runner import AgentResult, AgentRunner
from orchestrator.utils.playwright_mcp import (
    browser_live_worker_enabled,
    write_playwright_mcp_config,
)

BASE_DIR = Path(__file__).resolve().parents[2]
AUTH_SESSIONS_DIR = Path(
    os.environ.get(
        "BROWSER_AUTH_SESSIONS_DIR", str(BASE_DIR / "runs" / "auth_sessions")
    )
)
BROWSER_AUTH_CAPTURE_VERSION = "direct-playwright-v2"
CLAUDE_CODE_AUTH_MODE = "claude_code_subscription"


class BrowserAuthSessionError(RuntimeError):
    """Raised when a browser auth session cannot be created or used."""


class BrowserAuthStorageStateMissingError(BrowserAuthSessionError):
    """Raised when MCP capture reports success but does not write storage state."""


@dataclass(frozen=True)
class ResolvedBrowserAuthSession:
    session_id: str
    storage_state_path: Path
    session_name: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ensure_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise BrowserAuthSessionError(f"Project '{project_id}' was not found")
    return project


def _validate_storage_state(value: dict[str, Any]) -> None:
    if not isinstance(value, dict):
        raise BrowserAuthSessionError("Storage state must be a JSON object")
    cookies = value.get("cookies", [])
    origins = value.get("origins", [])
    if not isinstance(cookies, list) or not isinstance(origins, list):
        raise BrowserAuthSessionError(
            "Storage state must include cookies and origins arrays"
        )


def encrypt_storage_state(storage_state: dict[str, Any]) -> str:
    _validate_storage_state(storage_state)
    return encrypt_credential(
        json.dumps(storage_state, separators=(",", ":"), sort_keys=True)
    )


def decrypt_storage_state(encrypted: str | None) -> dict[str, Any]:
    if not encrypted:
        raise BrowserAuthSessionError(
            "Browser auth session has no stored browser state"
        )
    plaintext = decrypt_credential(encrypted)
    if not plaintext:
        raise BrowserAuthSessionError(
            "Browser auth session state could not be decrypted"
        )
    try:
        state = json.loads(plaintext)
    except json.JSONDecodeError as exc:
        raise BrowserAuthSessionError(
            "Browser auth session state is not valid JSON"
        ) from exc
    _validate_storage_state(state)
    return state


def serialize_browser_auth_session(row: BrowserAuthSession) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "name": row.name,
        "base_url": row.base_url,
        "login_url": row.login_url,
        "username_key": row.username_key,
        "password_key": row.password_key,
        "username_selector": row.username_selector,
        "password_selector": row.password_selector,
        "username_continue_selector": row.username_continue_selector,
        "submit_selector": row.submit_selector,
        "success_url_pattern": row.success_url_pattern,
        "status": row.status,
        "is_default": row.is_default,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_validated_at": (
            row.last_validated_at.isoformat() if row.last_validated_at else None
        ),
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "failure_reason": row.failure_reason,
        "capture_backend_version": BROWSER_AUTH_CAPTURE_VERSION,
    }


def list_browser_auth_sessions(
    session: Session, project_id: str
) -> list[BrowserAuthSession]:
    _ensure_project(session, project_id)
    stmt = (
        select(BrowserAuthSession)
        .where(
            BrowserAuthSession.project_id == project_id,
            BrowserAuthSession.status != "revoked",
        )
        .order_by(
            BrowserAuthSession.is_default.desc(), BrowserAuthSession.created_at.desc()
        )
    )
    return list(session.exec(stmt).all())


def get_browser_auth_session_or_error(
    session: Session, project_id: str, session_id: str
) -> BrowserAuthSession:
    row = session.get(BrowserAuthSession, session_id)
    if not row or row.project_id != project_id:
        raise BrowserAuthSessionError("Browser auth session was not found")
    return row


def resolve_browser_auth_session_row(
    session: Session,
    project_id: str,
    *,
    browser_auth_session_id: str | None = None,
    use_default: bool = False,
) -> BrowserAuthSession | None:
    if browser_auth_session_id:
        return get_browser_auth_session_or_error(
            session, project_id, browser_auth_session_id
        )
    if use_default:
        stmt = select(BrowserAuthSession).where(
            BrowserAuthSession.project_id == project_id,
            BrowserAuthSession.is_default == True,
            BrowserAuthSession.status != "revoked",
        )
        return session.exec(stmt).first()
    return None


def ensure_browser_auth_session_usable(row: BrowserAuthSession) -> None:
    if row.status in {"revoked", "invalid", "expired"}:
        raise BrowserAuthSessionError(
            row.failure_reason
            or "Browser auth session is not usable. Refresh browser auth session."
        )
    if row.expires_at and row.expires_at <= _utcnow():
        row.status = "expired"
        row.failure_reason = (
            "Browser auth session has expired. Refresh browser auth session."
        )
        raise BrowserAuthSessionError(row.failure_reason)
    decrypt_storage_state(row.storage_state_json_encrypted)


def write_run_storage_state_file(row: BrowserAuthSession, run_dir: Path) -> Path:
    ensure_browser_auth_session_usable(row)
    state = decrypt_storage_state(row.storage_state_json_encrypted)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "browser-auth-storage-state.json"
    path.write_text(json.dumps(state, indent=2))
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def resolve_browser_auth_for_run(
    session: Session,
    project_id: str | None,
    *,
    run_dir: Path,
    browser_auth_session_id: str | None = None,
    use_default: bool = False,
) -> ResolvedBrowserAuthSession | None:
    if not project_id:
        raise BrowserAuthSessionError(
            "Browser auth session selection requires a project"
        )
    row = resolve_browser_auth_session_row(
        session,
        project_id,
        browser_auth_session_id=browser_auth_session_id,
        use_default=use_default,
    )
    if not row:
        if use_default:
            raise BrowserAuthSessionError(
                "Project default browser auth session was not found"
            )
        return None
    path = write_run_storage_state_file(row, run_dir)
    return ResolvedBrowserAuthSession(row.id, path, row.name)


def set_default_browser_auth_session(
    session: Session, project_id: str, session_id: str
) -> BrowserAuthSession:
    row = get_browser_auth_session_or_error(session, project_id, session_id)
    if row.status == "revoked":
        raise BrowserAuthSessionError(
            "Revoked browser auth sessions cannot be made default"
        )
    for other in session.exec(
        select(BrowserAuthSession).where(BrowserAuthSession.project_id == project_id)
    ).all():
        other.is_default = other.id == row.id
        session.add(other)
    session.commit()
    session.refresh(row)
    return row


def revoke_browser_auth_session(
    session: Session, project_id: str, session_id: str
) -> BrowserAuthSession:
    row = get_browser_auth_session_or_error(session, project_id, session_id)
    row.status = "revoked"
    row.is_default = False
    row.failure_reason = "Revoked by user"
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def validate_browser_auth_session(
    session: Session, project_id: str, session_id: str
) -> BrowserAuthSession:
    row = get_browser_auth_session_or_error(session, project_id, session_id)
    try:
        ensure_browser_auth_session_usable(row)
        row.status = "active"
        row.failure_reason = None
        row.last_validated_at = _utcnow()
    except BrowserAuthSessionError as exc:
        row.status = "invalid" if row.status != "expired" else "expired"
        row.failure_reason = str(exc)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _credential_value(credentials: dict[str, str], key: str, label: str) -> str:
    value = credentials.get(key)
    if not value:
        raise BrowserAuthSessionError(f"Missing {label} credential key '{key}'")
    return value


def _login_helper_script() -> str:
    return r"""
const { chromium } = require('playwright');

const loginUrl = process.env.BROWSER_AUTH_LOGIN_URL;
const username = process.env.BROWSER_AUTH_USERNAME;
const password = process.env.BROWSER_AUTH_PASSWORD;
const outputPath = process.env.BROWSER_AUTH_OUTPUT_PATH;
const usernameSelector = process.env.BROWSER_AUTH_USERNAME_SELECTOR || '';
const passwordSelector = process.env.BROWSER_AUTH_PASSWORD_SELECTOR || '';
const usernameContinueSelector = process.env.BROWSER_AUTH_USERNAME_CONTINUE_SELECTOR || '';
const submitSelector = process.env.BROWSER_AUTH_SUBMIT_SELECTOR || '';
const successUrlPattern = process.env.BROWSER_AUTH_SUCCESS_URL_PATTERN || '';
const headless = String(process.env.HEADLESS || process.env.PLAYWRIGHT_HEADLESS || 'true').toLowerCase() !== 'false';

const defaultUsernameSelectors = [
  'input[type="email"]',
  'input[name*="email" i]',
  'input[id*="email" i]',
  'input[name*="user" i]',
  'input[id*="user" i]',
  'input[autocomplete="username"]',
  'input[type="text"]'
];
const defaultPasswordSelectors = [
  'input[type="password"]',
  'input[autocomplete="current-password"]'
];
const defaultUsernameContinueSelectors = [
  'button:has-text("Next")',
  'button:has-text("Continue")',
  'button:has-text("Submit")',
  'button[type="submit"]',
  'input[type="submit"]',
  '[role="button"]:has-text("Next")',
  '[role="button"]:has-text("Continue")'
];
const defaultSubmitSelectors = [
  'button[type="submit"]',
  'input[type="submit"]',
  'button:has-text("Sign in")',
  'button:has-text("Log in")',
  'button:has-text("Login")',
  'button:has-text("Submit")',
  '[role="button"]:has-text("Sign in")',
  '[role="button"]:has-text("Log in")',
  '[role="button"]:has-text("Login")'
];

function selectors(customSelector, defaults) {
  return customSelector.trim() ? [customSelector.trim()] : defaults;
}

async function securityChallengeReason(page) {
  const [title, bodyText, iframeCount] = await Promise.all([
    page.title().catch(() => ''),
    page.locator('body').innerText({ timeout: 1000 }).catch(() => ''),
    page.locator('iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"], [id*="cf-challenge"], [class*="cf-challenge"]').count().catch(() => 0),
  ]);
  const haystack = `${title}\n${bodyText}`.toLowerCase();
  if (
    iframeCount > 0 ||
    haystack.includes('security check') ||
    haystack.includes('checking your browser') ||
    haystack.includes('verify you are human') ||
    haystack.includes('just a moment') ||
    (haystack.includes('cloudflare') && (
      haystack.includes('security') ||
      haystack.includes('challenge') ||
      haystack.includes('checking')
    ))
  ) {
    return 'Security challenge detected on the login page. Automated login capture cannot bypass Cloudflare or anti-bot checks. Allowlist the capture browser or disable the challenge for this environment.';
  }
  return null;
}

async function throwIfSecurityChallenge(page) {
  const reason = await securityChallengeReason(page);
  if (reason) throw new Error(reason);
}

async function firstVisibleEditable(page, selectorList) {
  for (const selector of selectorList) {
    const locator = page.locator(selector);
    const count = await locator.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const candidate = locator.nth(index);
      const [visible, editable] = await Promise.all([
        candidate.isVisible().catch(() => false),
        candidate.isEditable().catch(() => false),
      ]);
      if (visible && editable) return candidate;
    }
  }
  return null;
}

async function firstVisibleEnabled(page, selectorList) {
  for (const selector of selectorList) {
    const locator = page.locator(selector);
    const count = await locator.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const candidate = locator.nth(index);
      const [visible, enabled] = await Promise.all([
        candidate.isVisible().catch(() => false),
        candidate.isEnabled().catch(() => false),
      ]);
      if (visible && enabled) return candidate;
    }
  }
  return null;
}

async function waitForVisibleEditable(page, selectorList, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  do {
    await throwIfSecurityChallenge(page);
    const candidate = await firstVisibleEditable(page, selectorList);
    if (candidate) return candidate;
    await page.waitForTimeout(250);
  } while (Date.now() < deadline);
  await throwIfSecurityChallenge(page);
  return null;
}

async function waitForVisibleEnabled(page, selectorList, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  do {
    await throwIfSecurityChallenge(page);
    const candidate = await firstVisibleEnabled(page, selectorList);
    if (candidate) return candidate;
    await page.waitForTimeout(250);
  } while (Date.now() < deadline);
  await throwIfSecurityChallenge(page);
  return null;
}

function successUrlRegex() {
  if (!successUrlPattern.trim()) return null;
  try {
    return new RegExp(successUrlPattern);
  } catch (error) {
    throw new Error(`success_url_pattern is not a valid regular expression: ${error.message}`);
  }
}

let browser;

(async () => {
  browser = await chromium.launch({ headless });
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(loginUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await throwIfSecurityChallenge(page);

  const usernameSelectors = selectors(usernameSelector, defaultUsernameSelectors);
  const passwordSelectors = selectors(passwordSelector, defaultPasswordSelectors);
  const usernameContinueSelectors = selectors(usernameContinueSelector, defaultUsernameContinueSelectors);
  const submitSelectors = selectors(submitSelector, defaultSubmitSelectors);
  const urlRegex = successUrlRegex();

  const usernameLocator = await waitForVisibleEditable(page, usernameSelectors, 15000);
  let passwordLocator = await waitForVisibleEditable(page, passwordSelectors, usernameLocator ? 1000 : 15000);

  if (!usernameLocator && !passwordLocator) {
    throw new Error('Login form not found. Could not find a visible editable username or password input on the login page.');
  }

  if (usernameLocator) {
    await usernameLocator.fill(username, { timeout: 30000 });
  }

  if (!passwordLocator) {
    const usernameContinue = await waitForVisibleEnabled(page, usernameContinueSelectors, 5000);
    if (usernameContinue) {
      await Promise.all([
        page.waitForLoadState('domcontentloaded', { timeout: 30000 }).catch(() => {}),
        page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {}),
        usernameContinue.click()
      ]);
    } else if (usernameLocator) {
      await Promise.all([
        page.waitForLoadState('domcontentloaded', { timeout: 30000 }).catch(() => {}),
        page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {}),
        usernameLocator.press('Enter')
      ]);
    }
    passwordLocator = await waitForVisibleEditable(page, passwordSelectors, 30000);
  }

  if (!passwordLocator) {
    throw new Error('Password field not found after submitting the username. Configure password_selector or username_continue_selector for this login flow.');
  }

  await passwordLocator.fill(password, { timeout: 30000 });

  const submit = await waitForVisibleEnabled(page, submitSelectors, 3000);
  if (submit) {
    await Promise.all([
      page.waitForLoadState('domcontentloaded', { timeout: 30000 }).catch(() => {}),
      page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {}),
      submit.click()
    ]);
  } else {
    await Promise.all([
      page.waitForLoadState('domcontentloaded', { timeout: 30000 }).catch(() => {}),
      page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {}),
      passwordLocator.press('Enter')
    ]);
  }
  await page.waitForLoadState('domcontentloaded', { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(1000);
  await throwIfSecurityChallenge(page);
  if (urlRegex) {
    await page.waitForURL(url => urlRegex.test(String(url)), { timeout: 30000 }).catch(() => {});
    if (!urlRegex.test(page.url())) {
      throw new Error(`Login capture did not reach expected success URL. Final URL '${page.url()}' did not match success_url_pattern '${successUrlPattern}'.`);
    }
  }
  await context.storageState({ path: outputPath });
  await browser.close();
})().catch(async (error) => {
  if (browser) {
    await browser.close().catch(() => {});
  }
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
"""


def create_storage_state_via_playwright(
    *,
    base_url: str,
    login_url: str,
    username: str,
    password: str,
    username_selector: str | None = None,
    password_selector: str | None = None,
    username_continue_selector: str | None = None,
    submit_selector: str | None = None,
    success_url_pattern: str | None = None,
    timeout_seconds: int = 120,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    del base_url
    run_dir = run_dir or _capture_run_dir("direct-playwright")
    run_dir.mkdir(parents=True, exist_ok=True)
    helper_path = run_dir / "browser-auth-login-helper.js"
    output_path = run_dir / "storage-state.json"
    helper_path.write_text(_login_helper_script(), encoding="utf-8")

    env = os.environ.copy()
    node_modules_path = str(BASE_DIR / "node_modules")
    env["NODE_PATH"] = (
        node_modules_path
        if not env.get("NODE_PATH")
        else os.pathsep.join([node_modules_path, env["NODE_PATH"]])
    )
    env.update(
        {
            "BROWSER_AUTH_LOGIN_URL": login_url,
            "BROWSER_AUTH_USERNAME": username,
            "BROWSER_AUTH_PASSWORD": password,
            "BROWSER_AUTH_OUTPUT_PATH": str(output_path),
            "BROWSER_AUTH_USERNAME_SELECTOR": username_selector or "",
            "BROWSER_AUTH_PASSWORD_SELECTOR": password_selector or "",
            "BROWSER_AUTH_USERNAME_CONTINUE_SELECTOR": username_continue_selector or "",
            "BROWSER_AUTH_SUBMIT_SELECTOR": submit_selector or "",
            "BROWSER_AUTH_SUCCESS_URL_PATTERN": success_url_pattern or "",
        }
    )
    try:
        completed = subprocess.run(
            ["node", str(helper_path)],
            cwd=BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BrowserAuthSessionError(
            f"Direct Playwright browser auth capture timed out after {timeout_seconds} seconds."
        ) from exc
    except OSError as exc:
        raise BrowserAuthSessionError(
            f"Direct Playwright browser auth capture could not start: {exc}"
        ) from exc

    if completed.returncode != 0:
        message = "\n".join(
            part for part in [completed.stderr, completed.stdout] if part
        ).strip()
        raise BrowserAuthSessionError(
            message or "Direct Playwright browser auth capture failed."
        )
    if not output_path.exists():
        raise BrowserAuthSessionError(
            "Direct Playwright storage state file was not produced."
        )
    try:
        state = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BrowserAuthSessionError(
            "Direct Playwright storage state file is not valid JSON."
        ) from exc
    _validate_storage_state(state)
    return state


def _capture_base_dir() -> Path:
    return AUTH_SESSIONS_DIR / "captures"


def _capture_run_dir(session_id: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _capture_base_dir() / f"{session_id}-{timestamp}"


def _dotenv_escape(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return f'"{escaped}"'


def _write_capture_secrets(run_dir: Path, *, username: str, password: str) -> Path:
    secrets_file = run_dir / "browser-auth-secrets.env"
    secrets_file.write_text(
        "\n".join(
            [
                f"BROWSER_AUTH_USERNAME={_dotenv_escape(username)}",
                f"BROWSER_AUTH_PASSWORD={_dotenv_escape(password)}",
                "",
            ]
        )
    )
    try:
        secrets_file.chmod(0o600)
    except OSError:
        pass
    return secrets_file


def _selector_hint(label: str, value: str | None) -> str:
    return f"- {label}: {value}" if value else f"- {label}: not provided"


def _build_capture_prompt(
    *,
    base_url: str,
    login_url: str,
    username_selector: str | None,
    password_selector: str | None,
    username_continue_selector: str | None,
    submit_selector: str | None,
    success_url_pattern: str | None,
    storage_filename: str,
) -> str:
    selector_hints = "\n".join(
        [
            _selector_hint("username selector hint", username_selector),
            _selector_hint("password selector hint", password_selector),
            _selector_hint(
                "username continue selector hint", username_continue_selector
            ),
            _selector_hint("submit selector hint", submit_selector),
            _selector_hint("success URL regex", success_url_pattern),
        ]
    )
    return f"""You are capturing a reusable browser login session through Playwright MCP.

Rules:
- Do not print, summarize, or reveal credential values.
- The MCP server has secrets named BROWSER_AUTH_USERNAME and BROWSER_AUTH_PASSWORD. When typing credentials, pass those exact secret names as the text/value so MCP substitutes and redacts them.
- Use browser_snapshot to inspect each page before deciding how to interact.
- Navigate to the login URL, complete the login naturally, and support email-first or multi-step login flows.
- Treat selector settings as optional hints only. Prefer the live snapshot and accessible element refs.
- If a Cloudflare, Turnstile, CAPTCHA, "verify you are human", "checking your browser", or other anti-bot/security challenge appears, stop immediately and report: security challenge detected.
- If a "Leave site?", unsaved changes, or beforeunload dialog appears, immediately call `browser_handle_dialog` with `accept: true`, then call `browser_snapshot` or `browser_take_screenshot` to verify page state. Preserve draft data only if the user explicitly requested it.
- Save storage state only after login has clearly succeeded.
- If the page reaches the success URL or otherwise shows the signed-in destination, call browser_storage_state immediately. Do not wait for ads, analytics, videos, or other background network requests to finish.
- Treat the initial page as usable once the login controls are visible; do not wait for full page load, network idle, ads, analytics, videos, or marketing resources.

Target:
- Base URL: {base_url}
- Login URL: {login_url}

Optional hints:
{selector_hints}

Required workflow:
1. Call browser_navigate for the login URL.
2. Call browser_snapshot and identify the current login controls.
3. Fill the username with BROWSER_AUTH_USERNAME and the password with BROWSER_AUTH_PASSWORD, handling any continue/next steps.
4. Submit the login form.
5. After submitting, call browser_evaluate with `() => window.location.href` to read the current URL. If a success URL regex is provided and the current URL matches it, call browser_storage_state with filename "{storage_filename}" immediately as the next tool call.
6. If the URL does not match yet, take one browser_snapshot, handle any visible post-login/security prompt, then check `window.location.href` again. Report a success URL pattern failure only after that second check still does not match.
7. Call browser_storage_state with filename "{storage_filename}" only after login succeeds. Do not call browser_wait_for once the success URL has matched.
8. Return a concise status report that does not include credentials.
"""


def _normalize_capture_error(message: str | None) -> str:
    raw = (message or "").strip()
    lower = raw.lower()
    if not raw:
        return "MCP browser auth capture failed."
    if "direct playwright fallback failed" in lower:
        return raw[-1200:]
    if "direct playwright" in lower:
        return raw[-1200:]
    if "not valid json storage state" in lower:
        return raw[-1200:]
    if "not logged in" in lower or "please run /login" in lower:
        return (
            "LLM runtime is not authenticated. Configure the provider API key in Settings or deployment "
            "environment secrets, then restart the backend and worker services if using environment secrets."
        )
    if any(
        token in lower
        for token in [
            "init-page",
            "init page",
            "browser-dialog-recovery.init",
            "unexpected token 'export'",
            "unexpected token export",
        ]
    ):
        return (
            "Playwright MCP browser auth capture infrastructure failed before navigation: "
            "the browser init page could not load."
        )
    if any(
        token in lower
        for token in [
            "security challenge",
            "cloudflare",
            "anti-bot",
            "captcha",
            "turnstile",
            "verify you are human",
            "checking your browser",
        ]
    ):
        return (
            "Security challenge detected during MCP browser auth capture. Automated capture cannot bypass "
            "Cloudflare, CAPTCHA, or anti-bot checks; allowlist the capture browser or disable the challenge "
            "for this environment."
        )
    if any(
        token in lower
        for token in [
            "login form not found",
            "username or password input",
            "no login form",
        ]
    ):
        return "Login form not found during MCP browser auth capture. Check the login URL or add selector hints."
    if any(
        token in lower
        for token in [
            "password field not found",
            "password step",
            "password selector",
            "password input",
        ]
    ):
        return (
            "Password step not reachable during MCP browser auth capture. Add a password selector or username "
            "continue selector hint for this login flow."
        )
    if any(
        token in lower
        for token in ["storage-state", "storage state", "browser_storage_state"]
    ):
        return "Storage state file not produced by MCP browser auth capture."
    if "[eval]" in lower or "locator.fill" in lower or "login helper" in lower:
        return "MCP browser auth capture failed before login completed. Check the login URL or selector hints."
    if "timeout" in lower or "timed out" in lower:
        return "MCP browser auth capture timed out before producing storage state."
    return raw[-1200:]


def _normalize_direct_capture_error(message: str | None) -> str:
    raw = (message or "").strip()
    lower = raw.lower()
    if not raw:
        return "Direct Playwright browser auth capture failed."
    if any(
        token in lower
        for token in [
            "security challenge",
            "cloudflare",
            "anti-bot",
            "captcha",
            "turnstile",
            "verify you are human",
            "checking your browser",
        ]
    ):
        return (
            "Security challenge detected during direct Playwright browser auth capture. Automated capture "
            "cannot bypass Cloudflare, CAPTCHA, or anti-bot checks; allowlist the capture browser or disable "
            "the challenge for this environment."
        )
    if "success_url_pattern is not a valid regular expression" in lower:
        return raw[-1200:]
    if any(
        token in lower
        for token in [
            "login form not found",
            "could not find a visible editable username or password input",
        ]
    ):
        return (
            "Direct Playwright login form not found. Check the login URL or add selector hints."
        )
    if "password field not found" in lower:
        return (
            "Direct Playwright password field not found after submitting the username. Add a password "
            "selector or username continue selector hint for this login flow."
        )
    if "did not reach expected success url" in lower:
        return raw[-1200:]
    if "storage state file was not produced" in lower:
        return "Direct Playwright storage state file was not produced."
    if "storage state file is not valid json" in lower:
        return "Direct Playwright storage state file is not valid JSON."
    if "could not start" in lower:
        return raw[-1200:]
    if "timed out" in lower or "timeout" in lower:
        return raw[-1200:]
    return raw[-1200:]


def _direct_capture_failure_can_use_mcp(message: str | None) -> bool:
    lower = (message or "").lower()
    if any(
        token in lower
        for token in [
            "security challenge",
            "cloudflare",
            "anti-bot",
            "captcha",
            "turnstile",
            "verify you are human",
            "checking your browser",
            "success_url_pattern is not a valid regular expression",
            "storage state file was not produced",
            "storage state file is not valid json",
            "could not start",
            "timed out",
            "timeout",
        ]
    ):
        return False
    return any(
        token in lower
        for token in [
            "login form not found",
            "could not find a visible editable username or password input",
            "password field not found",
            "did not reach expected success url",
            "final url",
            "page.goto",
            "net::",
        ]
    )


def _storage_state_candidates(
    *, run_dir: Path, artifacts_dir: Path, storage_filename: str
) -> list[Path]:
    candidates = [
        artifacts_dir / storage_filename,
        run_dir / storage_filename,
        *sorted(artifacts_dir.rglob("storage-state*.json")),
        *sorted(run_dir.rglob("storage-state*.json")),
    ]
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        try:
            key = candidate.resolve()
        except OSError:
            key = candidate
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _env_value(env_vars: dict[str, str] | None, key: str) -> str:
    if env_vars is not None and key in env_vars:
        return env_vars.get(key, "")
    return os.environ.get(key, "")


def _is_claude_code_subscription_env(env_vars: dict[str, str] | None) -> bool:
    auth_mode = _env_value(env_vars, "QUORVEX_LLM_AUTH_MODE").strip().lower()
    provider = _env_value(env_vars, "QUORVEX_LLM_PROVIDER").strip().lower()
    return auth_mode in {
        "claude_code",
        "claude-code",
        CLAUDE_CODE_AUTH_MODE,
    } or provider == CLAUDE_CODE_AUTH_MODE


def _claude_code_oauth_token(env_vars: dict[str, str] | None) -> str:
    token = _env_value(env_vars, "CLAUDE_CODE_OAUTH_TOKEN")
    if token:
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return token


async def _run_capture_agent(
    prompt: str,
    *,
    run_dir: Path,
    timeout_seconds: int,
    session_id: str,
    runtime_env: dict[str, str] | None = None,
) -> AgentResult:
    resolved_env = runtime_env if runtime_env is not None else runtime_env_vars()
    selection = apply_runtime_env_aliases(
        resolved_env,
        tier="tool_deep",
    )
    display_provider = infer_display_provider(selection.base_url)
    is_claude_code_subscription = _is_claude_code_subscription_env(resolved_env)
    if is_claude_code_subscription:
        if not _claude_code_oauth_token(resolved_env):
            raise BrowserAuthSessionError(
                "Claude Code OAuth token is not configured or not visible to the backend. Configure "
                "Claude Code subscription auth in Settings or deployment environment secrets, then restart "
                "the backend and worker services if using environment secrets."
            )
    elif not selection.api_key:
        raise BrowserAuthSessionError(
            f"LLM provider API key is not configured for {display_provider}. Configure the provider API key in "
            "Settings or deployment environment secrets, then restart the backend and worker services "
            "if using environment secrets."
        )
    allowed_tools = [
        "mcp__playwright-test__browser_navigate",
        "mcp__playwright-test__browser_snapshot",
        "mcp__playwright-test__browser_click",
        "mcp__playwright-test__browser_type",
        "mcp__playwright-test__browser_fill_form",
        "mcp__playwright-test__browser_press_key",
        "mcp__playwright-test__browser_wait_for",
        "mcp__playwright-test__browser_handle_dialog",
        "mcp__playwright-test__browser_evaluate",
        "mcp__playwright-test__browser_take_screenshot",
        "mcp__playwright-test__browser_storage_state",
        "mcp__playwright-test__browser_close",
    ]
    runner = AgentRunner(
        timeout_seconds=timeout_seconds,
        allowed_tools=allowed_tools,
        tools=list(allowed_tools),
        disallowed_tools=[
            "Bash",
            "Read",
            "Write",
            "Edit",
            "MultiEdit",
            "LS",
            "Grep",
            "Glob",
        ],
        strict_mcp_config=True,
        session_dir=run_dir,
        cwd=run_dir,
        owner_type="browser_auth_session",
        owner_id=session_id,
        owner_label=f"Browser auth capture {session_id}",
        requires_live_browser=browser_live_worker_enabled(),
        memory_agent_type="browser-auth-capture",
        memory_source_type="browser_auth_session",
        memory_source_id=session_id,
        memory_stage="browser_auth_capture",
        inject_memory=False,
        capture_memory=False,
        model_tier="tool_deep",
    )
    return await runner.run(prompt, timeout_override=timeout_seconds)


async def _run_capture_agent_with_browser_slot(
    prompt: str,
    *,
    run_dir: Path,
    timeout_seconds: int,
    session_id: str,
    runtime_env: dict[str, str] | None = None,
) -> AgentResult:
    async with browser_operation_slot(
        request_id=f"browser-auth:{session_id}",
        operation_type=OperationType.BROWSER_AUTH,
        description=f"Browser auth capture {session_id}",
        timeout=timeout_seconds,
        max_operation_duration=timeout_seconds + 60,
    ):
        return await _run_capture_agent(
            prompt,
            run_dir=run_dir,
            timeout_seconds=timeout_seconds,
            session_id=session_id,
            runtime_env=runtime_env,
        )


def _run_async_capture(
    prompt: str,
    *,
    run_dir: Path,
    timeout_seconds: int,
    session_id: str,
    runtime_env: dict[str, str] | None = None,
) -> AgentResult:
    result: AgentResult | None = None
    error: BaseException | None = None

    def target() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(
                _run_capture_agent_with_browser_slot(
                    prompt,
                    run_dir=run_dir,
                    timeout_seconds=timeout_seconds,
                    session_id=session_id,
                    runtime_env=runtime_env,
                )
            )
        except BaseException as exc:
            error = exc

    thread = threading.Thread(
        target=target, name=f"browser-auth-capture-{session_id[:8]}", daemon=True
    )
    thread.start()
    thread.join(timeout_seconds + 30)
    if thread.is_alive():
        raise BrowserAuthSessionError(
            _normalize_capture_error(
                f"capture timed out after {timeout_seconds} seconds"
            )
        )
    if error:
        if isinstance(error, BrowserSlotAcquisitionError):
            raise BrowserAuthSessionError(str(error)) from error
        raise BrowserAuthSessionError(_normalize_capture_error(str(error))) from error
    if result is None:
        raise BrowserAuthSessionError(
            "MCP browser auth capture failed without returning a result."
        )
    return result


def capture_storage_state_via_mcp_agent(
    *,
    session_id: str,
    base_url: str,
    login_url: str,
    username: str,
    password: str,
    username_selector: str | None = None,
    password_selector: str | None = None,
    username_continue_selector: str | None = None,
    submit_selector: str | None = None,
    success_url_pattern: str | None = None,
    timeout_seconds: int = 300,
    runtime_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    run_dir = _capture_run_dir(session_id)
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    secrets_file = _write_capture_secrets(run_dir, username=username, password=password)
    storage_filename = "storage-state.json"
    runtime = write_playwright_mcp_config(
        run_dir=run_dir,
        server_name="playwright-test",
        project_root=BASE_DIR,
        caps=("storage",),
        secrets_file=secrets_file,
    )
    prompt = _build_capture_prompt(
        base_url=base_url,
        login_url=login_url,
        username_selector=username_selector,
        password_selector=password_selector,
        username_continue_selector=username_continue_selector,
        submit_selector=submit_selector,
        success_url_pattern=success_url_pattern,
        storage_filename=storage_filename,
    )
    (run_dir / "capture-prompt.md").write_text(prompt)
    (run_dir / "capture-runtime.json").write_text(
        json.dumps(
            {**runtime, "capture_version": BROWSER_AUTH_CAPTURE_VERSION},
            indent=2,
            default=str,
        )
    )

    result = _run_async_capture(
        prompt,
        run_dir=run_dir,
        timeout_seconds=timeout_seconds,
        session_id=session_id,
        runtime_env=runtime_env,
    )
    if not result.success:
        raise BrowserAuthSessionError(
            _normalize_capture_error(result.error or result.output)
        )
    parse_error: Exception | None = None
    for candidate in _storage_state_candidates(
        run_dir=run_dir,
        artifacts_dir=artifacts_dir,
        storage_filename=storage_filename,
    ):
        if not candidate.exists():
            continue
        try:
            state = json.loads(candidate.read_text())
            _validate_storage_state(state)
            return state
        except Exception as exc:
            parse_error = exc
    if parse_error:
        raise BrowserAuthSessionError(
            "MCP browser auth capture produced storage state, but it was not valid JSON storage state."
        ) from parse_error
    raise BrowserAuthStorageStateMissingError(
        _normalize_capture_error("storage state file not produced")
    )


def refresh_browser_auth_session(
    session: Session, project_id: str, session_id: str
) -> BrowserAuthSession:
    row = get_browser_auth_session_or_error(session, project_id, session_id)
    credentials = get_merged_credentials(project_id, session)
    username = _credential_value(credentials, row.username_key, "username")
    password = _credential_value(credentials, row.password_key, "password")
    capture_kwargs = {
        "base_url": row.base_url,
        "login_url": row.login_url,
        "username": username,
        "password": password,
        "username_selector": row.username_selector,
        "password_selector": row.password_selector,
        "username_continue_selector": row.username_continue_selector,
        "submit_selector": row.submit_selector,
        "success_url_pattern": row.success_url_pattern,
    }
    try:
        try:
            state = create_storage_state_via_playwright(
                **capture_kwargs,
                run_dir=_capture_run_dir(f"{row.id}-playwright"),
            )
        except BrowserAuthSessionError as direct_exc:
            direct_message = _normalize_direct_capture_error(str(direct_exc))
            if not _direct_capture_failure_can_use_mcp(str(direct_exc)):
                raise BrowserAuthSessionError(direct_message) from direct_exc
            try:
                state = capture_storage_state_via_mcp_agent(
                    session_id=row.id,
                    runtime_env=runtime_env_vars(session),
                    **capture_kwargs,
                )
            except BrowserAuthSessionError as mcp_exc:
                mcp_message = _normalize_capture_error(str(mcp_exc))
                raise BrowserAuthSessionError(
                    f"Direct Playwright capture failed: {direct_message}; "
                    f"MCP fallback failed: {mcp_message}"
                ) from mcp_exc
        row.storage_state_json_encrypted = encrypt_storage_state(state)
        row.status = "active"
        row.failure_reason = None
        row.last_validated_at = _utcnow()
    except BrowserAuthSessionError as exc:
        row.status = "invalid"
        row.failure_reason = _normalize_capture_error(str(exc))
        session.add(row)
        session.commit()
        session.refresh(row)
        raise BrowserAuthSessionError(row.failure_reason) from exc
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _apply_capture_settings(
    row: BrowserAuthSession,
    *,
    base_url: str,
    login_url: str,
    username_key: str,
    password_key: str,
    username_selector: str | None = None,
    password_selector: str | None = None,
    username_continue_selector: str | None = None,
    submit_selector: str | None = None,
    success_url_pattern: str | None = None,
    expires_at: datetime | None = None,
) -> None:
    row.base_url = base_url.strip()
    row.login_url = login_url.strip()
    row.username_key = username_key.strip()
    row.password_key = password_key.strip()
    row.username_selector = (username_selector or "").strip() or None
    row.password_selector = (password_selector or "").strip() or None
    row.username_continue_selector = (username_continue_selector or "").strip() or None
    row.submit_selector = (submit_selector or "").strip() or None
    row.success_url_pattern = (success_url_pattern or "").strip() or None
    row.expires_at = expires_at or (_utcnow() + timedelta(days=30))
    row.storage_state_json_encrypted = None
    row.failure_reason = None
    row.last_validated_at = None
    row.status = "pending"
    row.is_default = False


def create_browser_auth_session(
    session: Session,
    *,
    project_id: str,
    name: str | None,
    base_url: str,
    login_url: str,
    username_key: str,
    password_key: str,
    username_selector: str | None = None,
    password_selector: str | None = None,
    username_continue_selector: str | None = None,
    submit_selector: str | None = None,
    success_url_pattern: str | None = None,
    expires_at: datetime | None = None,
    make_default: bool = False,
    storage_state: dict[str, Any] | None = None,
) -> BrowserAuthSession:
    _ensure_project(session, project_id)
    clean_name = (name or "Default browser session").strip()
    row = session.exec(
        select(BrowserAuthSession).where(
            BrowserAuthSession.project_id == project_id,
            BrowserAuthSession.name == clean_name,
        )
    ).first()
    if row is None:
        row = BrowserAuthSession(project_id=project_id, name=clean_name)
    _apply_capture_settings(
        row,
        base_url=base_url,
        login_url=login_url,
        username_key=username_key,
        password_key=password_key,
        username_selector=username_selector,
        password_selector=password_selector,
        username_continue_selector=username_continue_selector,
        submit_selector=submit_selector,
        success_url_pattern=success_url_pattern,
        expires_at=expires_at,
    )
    if storage_state is not None:
        row.storage_state_json_encrypted = encrypt_storage_state(storage_state)
        row.status = "active"
        row.last_validated_at = _utcnow()
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise BrowserAuthSessionError(
            f"Browser auth session name '{clean_name}' is already in use for this project. Try again."
        ) from exc
    session.refresh(row)

    if storage_state is None:
        row = refresh_browser_auth_session(session, project_id, row.id)

    if make_default:
        row = set_default_browser_auth_session(session, project_id, row.id)

    return row
