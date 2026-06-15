"""Shared Playwright MCP runtime helpers."""

from __future__ import annotations

import json
import os
import re
import shlex
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    return sorted(existing, key=lambda path: path.parent.parent.name, reverse=True)[0]


def is_vnc_runtime() -> bool:
    """Return whether this process is configured to render browsers on the VNC display."""
    return (
        os.environ.get("VNC_ENABLED", "").lower() == "true"
        and os.environ.get("HEADLESS", "true").lower() == "false"
        and bool(os.environ.get("DISPLAY"))
    )


def _is_truthy_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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


def should_run_headless() -> bool:
    """Return whether MCP should launch Chromium headless for this process."""
    if is_vnc_runtime():
        return False
    return os.environ.get("HEADLESS", "true").lower() != "false"


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

    effective_headless = should_run_headless() if headless is None else headless
    env["HEADLESS"] = "true" if effective_headless else "false"
    env["PLAYWRIGHT_HEADLESS"] = "true" if effective_headless else "false"
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
) -> str:
    """Prepare a Playwright config copy for isolated run execution."""
    config_content = config_content.replace(
        "testDir: './tests/generated'", f"testDir: '{base_dir}/tests/generated'"
    )
    config_content = config_content.replace(
        'testDir: "./tests/generated"', f'testDir: "{base_dir}/tests/generated"'
    )
    config_content = config_content.replace(
        "testDir: './tests'", f"testDir: '{base_dir}/tests'"
    )
    config_content = config_content.replace(
        'testDir: "./tests"', f'testDir: "{base_dir}/tests"'
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
        storage_state = str(storage_state_path).replace("\\", "\\\\").replace("'", "\\'")
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


def write_playwright_test_mcp_config(
    *,
    run_dir: Path,
    server_name: str,
    config_path: Path,
    headless: bool,
    storage_state_path: Path | str | None = None,
) -> dict[str, Any]:
    """Write a run-local Playwright Test MCP config.

    The test MCP exposes planner_setup_page/generator_setup_page tools. It does
    not accept the generic @playwright/mcp flags, so keep its command shape
    separate from write_playwright_mcp_config().
    """
    mcp_output_dir = run_dir / "mcp-output"
    mcp_output_dir.mkdir(parents=True, exist_ok=True)

    if storage_state_path and config_path.exists():
        prepared = prepare_run_playwright_config_content(
            config_path.read_text(),
            base_dir=Path.cwd(),
            run_dir=run_dir,
            headless=headless,
            storage_state_path=storage_state_path,
        )
        config_path.write_text(prepared)

    args = ["playwright", "run-test-mcp-server", "-c", str(config_path)]
    if headless:
        args.append("--headless")

    mcp_env = _browser_mcp_env(headless)
    mcp_config = {
        "mcpServers": {
            server_name: {
                "command": "npx",
                "args": args,
                "env": mcp_env,
            }
        }
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    config_file = run_dir / ".mcp.json"
    config_file.write_text(json.dumps(mcp_config, indent=2))

    return {
        **browser_runtime_status(),
        "mcp_command": "npx",
        "mcp_args": args,
        "mcp_env": {key: mcp_env[key] for key in sorted(mcp_env)},
        "artifacts_dir": str(mcp_output_dir),
        "mcp_config_path": str(config_file),
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
    command, args, runtime = build_playwright_mcp_args(
        output_dir=artifacts_dir,
        project_root=project_root,
        storage_state_path=storage_state_path,
        caps=caps,
        secrets_file=secrets_file,
    )
    mcp_config = {"mcpServers": {server_name: {"command": command, "args": args}}}
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / ".mcp.json").write_text(json.dumps(mcp_config, indent=2))
    return {
        **runtime,
        "mcp_command": command,
        "mcp_args": _redact_storage_state_args(args),
        "artifacts_dir": str(artifacts_dir),
        "mcp_config_path": str(run_dir / ".mcp.json"),
    }
