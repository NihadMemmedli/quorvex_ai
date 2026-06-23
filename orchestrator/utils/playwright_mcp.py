"""Shared Playwright MCP runtime helpers."""

from __future__ import annotations

import json
import os
import re
import shlex
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from utils.browser_dialog_recovery import playwright_dialog_auto_accept_handler
except ImportError:  # pragma: no cover - package import mode
    from orchestrator.utils.browser_dialog_recovery import playwright_dialog_auto_accept_handler

REAL_BROWSER_EXECUTABLE_NAMES = {
    "chrome",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "msedge",
    "firefox",
    "webkit",
}

BROWSER_ACTION_TIMEOUT_ENV = "AGENT_BROWSER_ACTION_TIMEOUT_SECONDS"
PLAYWRIGHT_MCP_ACTION_TIMEOUT_ENV = "PLAYWRIGHT_MCP_TIMEOUT_ACTION"
DEFAULT_BROWSER_ACTION_TIMEOUT_SECONDS = 30.0
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}
_FALSY_ENV_VALUES = {"0", "false", "no", "off"}


def _parse_positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def browser_action_timeout_config(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Return the inner Playwright action timeout used by browser MCP tools."""
    source = env if env is not None else os.environ
    raw_value = source.get(BROWSER_ACTION_TIMEOUT_ENV)
    timeout_seconds = _parse_positive_float(raw_value, DEFAULT_BROWSER_ACTION_TIMEOUT_SECONDS)
    using_default = raw_value is None
    if raw_value is not None:
        try:
            using_default = float(raw_value) <= 0
        except (TypeError, ValueError):
            using_default = True
    return {
        "browser_action_timeout_seconds": timeout_seconds,
        "browser_action_timeout_ms": int(timeout_seconds * 1000),
        "browser_action_timeout_env": BROWSER_ACTION_TIMEOUT_ENV,
        "browser_action_timeout_source": "default" if raw_value is None else "env",
        "browser_action_timeout_raw": raw_value,
        "browser_action_timeout_defaulted": using_default,
    }


def _parse_semver(version: str) -> tuple[int, int, int]:
    core = str(version).split("-", 1)[0]
    parts: list[int] = []
    for part in core.split(".")[:3]:
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def is_package_version_at_least(package_json: Path, minimum: str) -> bool:
    """Return whether package_json declares a semver version >= minimum."""
    if not package_json.exists():
        return False
    try:
        package = json.loads(package_json.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return _parse_semver(str(package.get("version", "0.0.0"))) >= _parse_semver(minimum)


def build_playwright_mcp_server_config(project_root: Path | None = None) -> dict[str, Any]:
    """Return a reliable Playwright MCP server command."""
    override = os.environ.get("PLAYWRIGHT_MCP_COMMAND")
    if override:
        args = os.environ.get("PLAYWRIGHT_MCP_ARGS", "--browser chromium").split()
        return {"command": override, "args": args}

    root = project_root or Path(__file__).resolve().parent.parent.parent
    local_bins = [
        root / "node_modules" / ".bin" / "playwright-mcp",
        root / "node_modules" / ".bin" / "mcp-server-playwright",
    ]
    local_pkg = root / "node_modules" / "@playwright" / "mcp" / "package.json"
    min_version = os.environ.get("PLAYWRIGHT_MCP_MIN_VERSION", "0.0.76")
    if is_package_version_at_least(local_pkg, min_version):
        for local_bin in local_bins:
            if local_bin.exists():
                return {"command": str(local_bin), "args": ["--browser", "chromium"]}

    package = os.environ.get("PLAYWRIGHT_MCP_PACKAGE", f"@playwright/mcp@{min_version}")
    return {"command": "npx", "args": ["-y", package, "--browser", "chromium"]}


def resolve_playwright_chromium_executable() -> Path | None:
    """Find a Chromium executable already installed in the runtime image."""
    override = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH") or os.environ.get(
        "PLAYWRIGHT_MCP_EXECUTABLE_PATH"
    )
    if override:
        path = Path(override)
        return path if path.exists() else None

    try:
        home_cache_root = Path.home() / ".cache" / "ms-playwright"
    except RuntimeError:
        home_cache_root = None

    roots = [
        Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]) if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") else None,
        Path("/ms-playwright"),
        home_cache_root,
    ]
    candidates: list[Path] = []
    for root in roots:
        try:
            if not root or not root.exists():
                continue
            candidates.extend(root.glob("chromium-*/chrome-linux/chrome"))
            candidates.extend(root.glob("chromium-*/chrome-linux64/chrome"))
            candidates.extend(root.glob("chrome-*/chrome-linux/chrome"))
            candidates.extend(root.glob("chrome-*/chrome-linux64/chrome"))
        except OSError:
            continue
    existing: list[Path] = []
    for candidate in candidates:
        try:
            if candidate.exists():
                existing.append(candidate)
        except OSError:
            continue
    if not existing:
        return None

    def _browser_revision_sort_key(path: Path) -> tuple[str, int, str]:
        browser_dir = path.parent.parent.name
        match = re.match(r"([a-z-]+)-(\d+)$", browser_dir)
        if match:
            return match.group(1), int(match.group(2)), browser_dir
        return browser_dir, -1, browser_dir

    return sorted(existing, key=_browser_revision_sort_key, reverse=True)[0]


def _env_bool_value(value: Any) -> bool | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in _TRUTHY_ENV_VALUES:
        return True
    if normalized in _FALSY_ENV_VALUES:
        return False
    return None


def _env_source(env: dict[str, str] | None = None) -> dict[str, str]:
    return env if env is not None else os.environ


def display_capable_vnc_enabled(env: dict[str, str] | None = None) -> bool:
    """Return whether headed browser launches have a VNC display to render on."""
    source = _env_source(env)
    return _env_bool_value(source.get("VNC_ENABLED")) is True and bool(source.get("DISPLAY"))


def requested_headless_from_env(env: dict[str, str] | None = None) -> bool | None:
    """Return an explicit headless env override.

    Either HEADLESS=false or PLAYWRIGHT_HEADLESS=false requests headed mode for
    compatibility with existing CLI/runtime configuration.
    """
    source = _env_source(env)
    saw_true = False
    for key in ("HEADLESS", "PLAYWRIGHT_HEADLESS"):
        if key in source:
            parsed = _env_bool_value(source.get(key))
            if parsed is False:
                return False
            if parsed is True:
                saw_true = True
    return True if saw_true else None


def display_aware_headless(requested_headless: bool, env: dict[str, str] | None = None) -> bool:
    """Force headless unless a headed request can actually render on VNC."""
    return True if requested_headless is False and not display_capable_vnc_enabled(env) else requested_headless


def is_vnc_runtime(env: dict[str, str] | None = None) -> bool:
    """Return whether this process is configured to render browsers on the VNC display."""
    if not display_capable_vnc_enabled(env):
        return False
    explicit_headless = requested_headless_from_env(env)
    return explicit_headless is None or explicit_headless is False


def _is_truthy_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return _env_bool_value(value) is True


def browser_live_worker_enabled() -> bool:
    """Return whether browser-capable agent work should use the VNC worker queue."""
    return is_vnc_runtime() or _is_truthy_env("LIVE_BROWSER_WORKER_ENABLED", default=False)


def resolve_vnc_ws_url() -> str | None:
    """Return the browser-facing noVNC websocket URL, if configured."""
    explicit = os.environ.get("VNC_PUBLIC_WS_URL")
    if explicit:
        return explicit.rstrip("/")

    public_url = os.environ.get("VNC_PUBLIC_URL")
    if public_url:
        normalized = public_url.rstrip("/")
        if normalized.startswith("https://"):
            normalized = "wss://" + normalized[len("https://") :]
        elif normalized.startswith("http://"):
            normalized = "ws://" + normalized[len("http://") :]
        if not normalized.endswith("/websockify"):
            normalized = f"{normalized}/websockify"
        return normalized

    if browser_live_worker_enabled():
        return "ws://localhost:6080/websockify"
    return None


def should_run_headless(env: dict[str, str] | None = None) -> bool:
    """Return whether MCP should launch Chromium headless for this process."""
    explicit_headless = requested_headless_from_env(env)
    if explicit_headless is not None:
        return display_aware_headless(explicit_headless, env)
    if display_capable_vnc_enabled(env):
        return False
    return True


def playwright_headed_cli_args(env: dict[str, str] | None = None) -> str:
    """Return Playwright CLI flags for visible execution when a display exists."""
    return "" if should_run_headless(env) else " --headed --workers=1"


def browser_runtime_status() -> dict[str, Any]:
    """Describe whether the current process can provide a visible browser stream."""
    executable = resolve_playwright_chromium_executable()
    vnc_url = resolve_vnc_ws_url()
    if browser_live_worker_enabled() and not is_vnc_runtime():
        return {
            "browser_runtime": "temporal_vnc_worker",
            "live_view_available": True,
            "runtime_message": "Browser execution is delegated to the live browser worker.",
            "browser_executable": str(executable) if executable else None,
            "vnc_url": vnc_url,
        }
    if not executable:
        return {
            "browser_runtime": "unavailable",
            "live_view_available": False,
            "runtime_message": "Playwright Chromium is not installed in this execution container.",
            "browser_executable": None,
            "vnc_url": vnc_url,
        }
    if is_vnc_runtime():
        return {
            "browser_runtime": "vnc",
            "live_view_available": True,
            "runtime_message": "Browser will run on the VNC display.",
            "browser_executable": str(executable),
            "vnc_url": vnc_url,
        }
    return {
        "browser_runtime": "headless_worker",
        "live_view_available": False,
        "runtime_message": "Browser execution is running headless or outside the VNC display.",
        "browser_executable": str(executable),
        "vnc_url": vnc_url,
    }


def _is_real_browser_process_line(line: str) -> bool:
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


def _browser_window_lines(xwininfo_output: str, browser_process_count: int) -> list[str]:
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


def live_browser_display_diagnostics() -> dict[str, Any]:
    """Report process/window evidence for the currently configured VNC display."""
    diagnostics: dict[str, Any] = {
        "display": os.environ.get("DISPLAY"),
        "vnc_server_host": "localhost",
        "vnc_server_port": 5900,
        "vnc_server_available": False,
        "browser_process_count": 0,
        "browser_window_count": None,
        "browser_process_seen": False,
        "browser_window_seen": False,
        "probed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        process_result = subprocess.run(
            ["ps", "-eo", "pid=,comm=,args="],
            capture_output=True,
            text=True,
            timeout=2,
        )
        lines = [
            line
            for line in process_result.stdout.splitlines()
            if _is_real_browser_process_line(line)
        ]
        diagnostics["browser_process_count"] = len(lines)
        diagnostics["browser_process_seen"] = len(lines) > 0
    except Exception as exc:
        diagnostics["process_probe_error"] = str(exc)

    try:
        with socket.create_connection(("localhost", 5900), timeout=1):
            diagnostics["vnc_server_available"] = True
    except OSError as exc:
        diagnostics["vnc_server_error"] = str(exc)

    if os.environ.get("DISPLAY"):
        try:
            env = os.environ.copy()
            window_result = subprocess.run(
                ["xwininfo", "-root", "-tree"],
                capture_output=True,
                text=True,
                timeout=2,
                env=env,
            )
            browser_windows = _browser_window_lines(
                window_result.stdout,
                int(diagnostics.get("browser_process_count") or 0),
            )
            diagnostics["browser_window_count"] = len(browser_windows)
            diagnostics["browser_window_seen"] = len(browser_windows) > 0
        except Exception as exc:
            diagnostics["window_probe_error"] = str(exc)
    return diagnostics


def build_playwright_mcp_args(
    *,
    output_dir: Path,
    project_root: Path | None = None,
    isolated: bool = True,
    storage_state_path: Path | str | None = None,
    caps: list[str] | tuple[str, ...] | None = None,
    secrets_file: Path | str | None = None,
) -> tuple[str, list[str], dict[str, Any]]:
    """Build command/args/runtime metadata for a run-local Playwright MCP config."""
    server = build_playwright_mcp_server_config(project_root)
    args = list(server["args"])
    executable = resolve_playwright_chromium_executable()
    if executable and "--executable-path" not in args:
        args.extend(["--executable-path", str(executable)])
    if "--output-dir" not in args:
        args.extend(["--output-dir", str(output_dir)])
    if isolated and "--isolated" not in args:
        args.append("--isolated")
    if storage_state_path and "--storage-state" not in args:
        args.extend(["--storage-state", str(storage_state_path)])
    if caps:
        requested_caps = [str(cap).strip() for cap in caps if str(cap).strip()]
        if requested_caps:
            if "--caps" in args:
                index = args.index("--caps")
                if index + 1 < len(args):
                    existing = [part.strip() for part in args[index + 1].split(",") if part.strip()]
                    merged = list(dict.fromkeys(existing + requested_caps))
                    args[index + 1] = ",".join(merged)
            else:
                args.extend(["--caps", ",".join(dict.fromkeys(requested_caps))])
    if secrets_file and "--secrets" not in args:
        args.extend(["--secrets", str(secrets_file)])
    if should_run_headless() and "--headless" not in args:
        args.append("--headless")
    timeout = browser_action_timeout_config()
    if "--timeout-action" not in args:
        args.extend(["--timeout-action", str(timeout["browser_action_timeout_ms"])])
    return str(server["command"]), args, browser_runtime_status()


def _browser_mcp_env(headless: bool | None = None) -> dict[str, str]:
    """Return env vars that keep MCP browser launches on the intended display."""
    env: dict[str, str] = {}
    passthrough = [
        "DISPLAY",
        "VNC_ENABLED",
        "PLAYWRIGHT_BROWSERS_PATH",
        "PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT",
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
        "PLAYWRIGHT_MCP_EXECUTABLE_PATH",
    ]
    for key in passthrough:
        value = os.environ.get(key)
        if value:
            env[key] = value

    effective_headless = should_run_headless() if headless is None else display_aware_headless(headless)
    env["HEADLESS"] = "true" if effective_headless else "false"
    env["PLAYWRIGHT_HEADLESS"] = "true" if effective_headless else "false"
    timeout = browser_action_timeout_config()
    env[BROWSER_ACTION_TIMEOUT_ENV] = f"{timeout['browser_action_timeout_seconds']:g}"
    env[PLAYWRIGHT_MCP_ACTION_TIMEOUT_ENV] = str(timeout["browser_action_timeout_ms"])
    if not effective_headless:
        # Playwright Test MCP defaults to headless when CI is truthy, even when
        # DISPLAY is set. Override inherited worker CI for visible VNC runs.
        env["CI"] = ""
        env["PLAYWRIGHT_WORKERS"] = "1"
    return env


def _redact_storage_state_args(args: list[str]) -> list[str]:
    redacted = list(args)
    for index, value in enumerate(redacted):
        if value == "--storage-state" and index + 1 < len(redacted):
            redacted[index + 1] = "<run-local-storage-state>"
        if value == "--secrets" and index + 1 < len(redacted):
            redacted[index + 1] = "<run-local-secrets>"
    return redacted


def write_browser_dialog_recovery_init_page(run_dir: Path) -> Path:
    """Write a Playwright MCP init page that accepts browser dialogs automatically."""
    path = run_dir / "browser-dialog-recovery.init.ts"
    path.write_text(
        "exports.default = async ({ page }) => {\n"
        f"{playwright_dialog_auto_accept_handler(indent='  ')}\n"
        "};\n",
        encoding="utf-8",
    )
    return path


def resolve_run_playwright_config(output_dir: Path | str | None = None) -> Path | None:
    """Return the run-local Playwright config when one is available."""
    candidates: list[Path] = []
    if output_dir:
        candidates.append(Path(output_dir) / "playwright.config.ts")
    candidates.append(Path.cwd() / "playwright.config.ts")
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def playwright_config_cli_arg(output_dir: Path | str | None = None) -> str:
    """Return a shell-safe Playwright --config argument for run-local execution."""
    config_path = resolve_run_playwright_config(output_dir)
    return f" --config {shlex.quote(str(config_path))}" if config_path else ""


def prepare_run_playwright_config_content(
    config_content: str,
    *,
    base_dir: Path,
    run_dir: Path,
    headless: bool,
    storage_state_path: Path | str | None = None,
    test_root_dir: Path | str | None = None,
) -> str:
    """Prepare a Playwright config copy for isolated run execution."""
    run_dir = Path(run_dir).resolve()
    configured_test_root = (
        Path(test_root_dir).resolve() if test_root_dir else run_dir / "tests"
    )
    config_content = config_content.replace(
        "testDir: './tests/generated'", f"testDir: '{configured_test_root}'"
    )
    config_content = config_content.replace(
        'testDir: "./tests/generated"', f'testDir: "{configured_test_root}"'
    )
    config_content = config_content.replace(
        "testDir: './tests'", f"testDir: '{configured_test_root}'"
    )
    config_content = config_content.replace(
        'testDir: "./tests"', f'testDir: "{configured_test_root}"'
    )
    config_content = config_content.replace(
        "outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || './test-results'",
        f"outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || '{run_dir}/test-results'",
    )
    config_content = config_content.replace(
        "testMatch: ['generated/**/*.spec.ts', 'e2e/**/*.spec.ts']",
        "testMatch: ['seed.spec.ts', 'generated/**/*.spec.ts', 'e2e/**/*.spec.ts']",
    )
    config_content = config_content.replace(
        'testMatch: ["generated/**/*.spec.ts", "e2e/**/*.spec.ts"]',
        'testMatch: ["seed.spec.ts", "generated/**/*.spec.ts", "e2e/**/*.spec.ts"]',
    )
    config_content = config_content.replace("video: 'retain-on-failure'", "video: 'on'")
    config_content = config_content.replace('video: "retain-on-failure"', 'video: "on"')

    if storage_state_path and "storageState:" not in config_content:
        storage_state = (
            str(Path(storage_state_path).resolve())
            .replace("\\", "\\\\")
            .replace("'", "\\'")
        )
        if "  use: {\n" in config_content:
            config_content = config_content.replace(
                "  use: {\n",
                f"  use: {{\n    storageState: '{storage_state}',\n",
                1,
            )
        else:
            config_content = re.sub(
                r"use:\s*{",
                f"use: {{\n    storageState: '{storage_state}',",
                config_content,
                count=1,
            )

    action_timeout = browser_action_timeout_config()
    if "const browserActionTimeout =" not in config_content:
        timeout_block = (
            "const configuredBrowserActionTimeoutSeconds = Number(process.env."
            f"{BROWSER_ACTION_TIMEOUT_ENV} || '{action_timeout['browser_action_timeout_seconds']:g}');\n"
            "const browserActionTimeout = Number.isFinite(configuredBrowserActionTimeoutSeconds) "
            "&& configuredBrowserActionTimeoutSeconds > 0\n"
            "  ? configuredBrowserActionTimeoutSeconds * 1000\n"
            f"  : {action_timeout['browser_action_timeout_ms']};\n"
        )
        export_match = re.search(r"^export\s+default\s+defineConfig\(", config_content, flags=re.MULTILINE)
        if export_match:
            config_content = (
                config_content[: export_match.start()]
                + timeout_block
                + "\n"
                + config_content[export_match.start() :]
            )
        else:
            config_content = timeout_block + "\n" + config_content

    if "actionTimeout:" not in config_content:
        if "  use: {\n" in config_content:
            config_content = config_content.replace(
                "  use: {\n",
                "  use: {\n    actionTimeout: browserActionTimeout,\n",
                1,
            )
        else:
            config_content = re.sub(
                r"use:\s*{",
                "use: {\n    actionTimeout: browserActionTimeout,",
                config_content,
                count=1,
            )

    if "navigationTimeout:" not in config_content:
        if "  use: {\n" in config_content:
            config_content = config_content.replace(
                "  use: {\n",
                "  use: {\n    navigationTimeout: 60_000,\n",
                1,
            )
        else:
            config_content = re.sub(
                r"use:\s*{",
                "use: {\n    navigationTimeout: 60_000,",
                config_content,
                count=1,
            )

    if headless:
        return config_content

    if "const runHeaded =" not in config_content:
        headed_env_block = (
            "const playwrightHeadless = process.env.PLAYWRIGHT_HEADLESS?.toLowerCase();\n"
            "const genericHeadless = process.env.HEADLESS?.toLowerCase();\n"
            "const runHeaded = playwrightHeadless === 'false' || genericHeadless === 'false';\n"
            "const configuredWorkers = parseInt(process.env.PLAYWRIGHT_WORKERS || '4', 10);\n"
        )
        marker_match = re.search(r"^const webServerHost = .+;\n", config_content, flags=re.MULTILINE)
        if marker_match:
            insert_at = marker_match.end()
            config_content = (
                config_content[:insert_at]
                + headed_env_block
                + config_content[insert_at:]
            )
        else:
            config_content = headed_env_block + config_content

    if "workers: runHeaded ? 1 : configuredWorkers" not in config_content:
        config_content = re.sub(
            r"workers:\s*parseInt\(process\.env\.PLAYWRIGHT_WORKERS\s*\|\|\s*['\"]4['\"],\s*10\),",
            "workers: runHeaded ? 1 : configuredWorkers,",
            config_content,
            count=1,
        )

    if "headless: runHeaded ? false : undefined" not in config_content:
        if "  use: {\n" in config_content:
            config_content = config_content.replace(
                "  use: {\n",
                "  use: {\n    headless: runHeaded ? false : undefined,\n",
                1,
            )
        else:
            config_content = re.sub(
                r"use:\s*{",
                "use: {\n    headless: runHeaded ? false : undefined,",
                config_content,
                count=1,
            )

    return config_content


def _configured_playwright_test_dir(config_path: Path, config_content: str) -> Path:
    match = re.search(r"testDir:\s*['\"]([^'\"]+)['\"]", config_content)
    if not match:
        return config_path.parent / "tests"
    configured = Path(match.group(1))
    if configured.is_absolute():
        return configured
    return config_path.parent / configured


def validate_run_seed_spec_preflight(
    *,
    run_dir: Path,
    config_path: Path,
    seed_file: str = "tests/seed.spec.ts",
) -> dict[str, Any]:
    """Validate that the run-local Playwright config can discover the MCP seed."""
    config_path = Path(config_path)
    seed_path = Path(seed_file)
    if not seed_path.is_absolute():
        seed_path = run_dir / seed_path
    seed_path = seed_path.resolve()

    if not config_path.exists():
        return {
            "ready": False,
            "error": f"Playwright config not found: {config_path}",
            "seed_file": seed_file,
            "seed_path": str(seed_path),
            "config_path": str(config_path),
        }

    config_content = config_path.read_text()
    test_dir = _configured_playwright_test_dir(config_path, config_content).resolve()
    if not seed_path.exists():
        return {
            "ready": False,
            "error": (
                f"Run-local seed test not found: {seed_path}. "
                f"Expected `{seed_file}` under run directory {run_dir}."
            ),
            "seed_file": seed_file,
            "seed_path": str(seed_path),
            "configured_test_dir": str(test_dir),
            "config_path": str(config_path),
        }

    try:
        seed_path.relative_to(test_dir)
    except ValueError:
        return {
            "ready": False,
            "error": (
                f"Run-local seed test {seed_path} is outside configured Playwright "
                f"testDir {test_dir}. Set testDir to the run-local tests directory."
            ),
            "seed_file": seed_file,
            "seed_path": str(seed_path),
            "configured_test_dir": str(test_dir),
            "config_path": str(config_path),
        }

    return {
        "ready": True,
        "seed_file": seed_file,
        "seed_path": str(seed_path),
        "configured_test_dir": str(test_dir),
        "config_path": str(config_path),
    }


def write_playwright_test_mcp_config(
    *,
    run_dir: Path,
    server_name: str,
    config_path: Path,
    headless: bool,
    storage_state_path: Path | str | None = None,
    agent_run_id: str | None = None,
) -> dict[str, Any]:
    """Write a run-local Playwright Test MCP config.

    The test MCP exposes planner_setup_page/generator_setup_page tools. It does
    not accept the generic @playwright/mcp flags, so keep its command shape
    separate from write_playwright_mcp_config().
    """
    mcp_output_dir = run_dir / "mcp-output"
    mcp_output_dir.mkdir(parents=True, exist_ok=True)
    effective_headless = display_aware_headless(headless)

    if config_path.exists():
        prepared = prepare_run_playwright_config_content(
            config_path.read_text(),
            base_dir=Path.cwd(),
            run_dir=run_dir,
            headless=effective_headless,
            storage_state_path=storage_state_path,
        )
        config_path.write_text(prepared)

    args = ["playwright", "run-test-mcp-server", "-c", str(config_path)]
    if effective_headless:
        args.append("--headless")

    mcp_env = _browser_mcp_env(effective_headless)
    mcp_servers: dict[str, dict[str, Any]] = {
        server_name: {
            "command": "npx",
            "args": args,
            "env": mcp_env,
            "alwaysLoad": True,
        }
    }
    if agent_run_id:
        project_root = Path(__file__).resolve().parents[2]
        note_env = {
            key: value
            for key in (
                "DATABASE_URL",
                "JWT_SECRET_KEY",
                "QUORVEX_NATIVE_AGENT_RUN_TYPES",
                "QUORVEX_NATIVE_AGENT_RUN_SHADOW",
                "QUORVEX_NATIVE_AGENT_RUNS_ENABLED",
            )
            if (value := os.environ.get(key))
        }
        note_env["QUORVEX_AGENT_RUN_ID"] = str(agent_run_id)
        mcp_servers["quorvex-agent"] = {
            "command": sys.executable,
            "args": [str(project_root / "tools" / "agent_note_mcp" / "server.py")],
            "env": note_env,
            "alwaysLoad": True,
        }

    mcp_config = {"mcpServers": mcp_servers}
    run_dir.mkdir(parents=True, exist_ok=True)
    config_file = run_dir / ".mcp.json"
    config_file.write_text(json.dumps(mcp_config, indent=2))

    return {
        **browser_runtime_status(),
        **browser_action_timeout_config(),
        "mcp_command": "npx",
        "mcp_args": args,
        "mcp_env": {key: mcp_env[key] for key in sorted(mcp_env)},
        "artifacts_dir": str(mcp_output_dir),
        "mcp_config_path": str(config_file),
        "dialog_recovery_attempted": True,
        "dialog_recovery_result": "run_local_seed_and_test_prelude",
        "dialog_recovery_seed_file": "tests/seed.spec.ts",
    }


REQUIRED_PLAYWRIGHT_TEST_MCP_TOOLS = {
    "planner_setup_page",
    "browser_navigate",
    "browser_snapshot",
    "planner_save_plan",
    "test_debug",
    "test_run",
}


def validate_playwright_test_mcp_contract(
    mcp_config_path: Path | str,
    *,
    required_tools: set[str] | None = None,
) -> dict[str, Any]:
    """Validate that a run-local MCP config targets the Playwright Test server.

    The custom `playwright run-test-mcp-server` command is the source of the
    planner/generator tools. We cannot cheaply introspect a server without
    launching an agent, so this validates the command shape that exposes those
    tools and reports the expected required tool set for preflight diagnostics.
    """
    path = Path(mcp_config_path)
    required = set(required_tools or REQUIRED_PLAYWRIGHT_TEST_MCP_TOOLS)
    try:
        config = json.loads(path.read_text())
    except Exception as exc:
        return {
            "ready": False,
            "error": f"Invalid MCP config at {path}: {exc}",
            "mcp_config_path": str(path),
            "required_tools": sorted(required),
        }

    servers = config.get("mcpServers") or {}
    server = servers.get("playwright-test") if isinstance(servers, dict) else None
    if not isinstance(server, dict):
        return {
            "ready": False,
            "error": "Run-local MCP config does not define a `playwright-test` server.",
            "mcp_config_path": str(path),
            "required_tools": sorted(required),
            "configured_servers": sorted(servers) if isinstance(servers, dict) else [],
        }

    args = [str(arg) for arg in (server.get("args") or [])]
    args_text = " ".join(args)
    if server.get("command") != "npx" or "playwright" not in args or "run-test-mcp-server" not in args:
        return {
            "ready": False,
            "error": "`playwright-test` is not configured as `npx playwright run-test-mcp-server`.",
            "mcp_config_path": str(path),
            "required_tools": sorted(required),
            "mcp_command": server.get("command"),
            "mcp_args": args,
        }

    return {
        "ready": True,
        "mcp_config_path": str(path),
        "server_name": "playwright-test",
        "mcp_command": server.get("command"),
        "mcp_args": args,
        "required_tools": sorted(required),
        "exposed_tools_verified_by": "playwright run-test-mcp-server command contract",
        "args_text": args_text,
    }


def write_playwright_mcp_config(
    *,
    run_dir: Path,
    server_name: str,
    project_root: Path | None = None,
    storage_state_path: Path | str | None = None,
    caps: list[str] | tuple[str, ...] | None = None,
    secrets_file: Path | str | None = None,
) -> dict[str, Any]:
    """Write a run-local MCP config and return runtime metadata."""
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    dialog_recovery_init_page = write_browser_dialog_recovery_init_page(run_dir)
    command, args, runtime = build_playwright_mcp_args(
        output_dir=artifacts_dir,
        project_root=project_root,
        storage_state_path=storage_state_path,
        caps=caps,
        secrets_file=secrets_file,
    )
    if "--init-page" not in args:
        args.extend(["--init-page", str(dialog_recovery_init_page)])
    mcp_env = _browser_mcp_env()
    mcp_config = {"mcpServers": {server_name: {"command": command, "args": args, "env": mcp_env}}}
    (run_dir / ".mcp.json").write_text(json.dumps(mcp_config, indent=2))
    return {
        **runtime,
        **browser_action_timeout_config(),
        "mcp_command": command,
        "mcp_args": _redact_storage_state_args(args),
        "mcp_env": {key: mcp_env[key] for key in sorted(mcp_env)},
        "artifacts_dir": str(artifacts_dir),
        "mcp_config_path": str(run_dir / ".mcp.json"),
        "dialog_recovery_attempted": True,
        "dialog_recovery_result": "init_page_registered",
        "dialog_recovery_init_page": str(dialog_recovery_init_page),
    }
