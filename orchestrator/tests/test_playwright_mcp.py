import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_write_playwright_test_mcp_config_uses_run_config_and_vnc_env(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import write_playwright_test_mcp_config

    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("VNC_ENABLED", "true")
    monkeypatch.setenv("HEADLESS", "false")
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "false")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")

    config_path = tmp_path / "playwright.config.ts"
    config_path.write_text("export default {};\n")

    runtime = write_playwright_test_mcp_config(
        run_dir=tmp_path,
        server_name="playwright-test",
        config_path=config_path,
        headless=False,
    )

    config = json.loads((tmp_path / ".mcp.json").read_text())
    server = config["mcpServers"]["playwright-test"]
    assert server["command"] == "npx"
    assert server["args"] == ["playwright", "run-test-mcp-server", "-c", str(config_path)]
    assert server["env"]["DISPLAY"] == ":99"
    assert server["env"]["VNC_ENABLED"] == "true"
    assert server["env"]["HEADLESS"] == "false"
    assert server["env"]["PLAYWRIGHT_HEADLESS"] == "false"
    assert server["env"]["CI"] == ""
    assert server["env"]["PLAYWRIGHT_WORKERS"] == "1"
    assert runtime["mcp_args"] == server["args"]
    assert runtime["mcp_env"]["DISPLAY"] == ":99"
    assert runtime["mcp_env"]["CI"] == ""


def test_live_browser_display_diagnostics_reports_vnc_server_availability(monkeypatch):
    from orchestrator.utils import playwright_mcp

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(playwright_mcp.socket, "create_connection", lambda *_args, **_kwargs: FakeSocket())

    diagnostics = playwright_mcp.live_browser_display_diagnostics()

    assert diagnostics["vnc_server_host"] == "localhost"
    assert diagnostics["vnc_server_port"] == 5900
    assert diagnostics["vnc_server_available"] is True


def test_live_browser_display_diagnostics_reports_vnc_server_error(monkeypatch):
    from orchestrator.utils import playwright_mcp

    def raise_connection_error(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(playwright_mcp.socket, "create_connection", raise_connection_error)

    diagnostics = playwright_mcp.live_browser_display_diagnostics()

    assert diagnostics["vnc_server_available"] is False
    assert "connection refused" in diagnostics["vnc_server_error"]


def test_write_playwright_test_mcp_config_preserves_headless_mode(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import write_playwright_test_mcp_config

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("VNC_ENABLED", "false")
    monkeypatch.setenv("HEADLESS", "true")
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "true")

    config_path = tmp_path / "playwright.config.ts"
    config_path.write_text("export default {};\n")

    write_playwright_test_mcp_config(
        run_dir=tmp_path,
        server_name="playwright-test",
        config_path=config_path,
        headless=True,
    )

    config = json.loads((tmp_path / ".mcp.json").read_text())
    server = config["mcpServers"]["playwright-test"]
    assert server["args"] == ["playwright", "run-test-mcp-server", "-c", str(config_path), "--headless"]
    assert server["env"]["HEADLESS"] == "true"
    assert server["env"]["PLAYWRIGHT_HEADLESS"] == "true"
    assert "CI" not in server["env"]
    assert "PLAYWRIGHT_WORKERS" not in server["env"]


def test_write_playwright_mcp_config_includes_storage_state_and_isolated(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import write_playwright_mcp_config

    monkeypatch.setenv("PLAYWRIGHT_MCP_COMMAND", "playwright-mcp")
    monkeypatch.setenv("PLAYWRIGHT_MCP_ARGS", "--browser chromium")

    storage_state = tmp_path / "state.json"
    storage_state.write_text('{"cookies":[],"origins":[]}')

    write_playwright_mcp_config(
        run_dir=tmp_path,
        server_name="playwright",
        project_root=tmp_path,
        storage_state_path=storage_state,
    )

    config = json.loads((tmp_path / ".mcp.json").read_text())
    args = config["mcpServers"]["playwright"]["args"]
    assert "--isolated" in args
    assert "--storage-state" in args
    assert args[args.index("--storage-state") + 1] == str(storage_state)


def test_write_playwright_mcp_config_includes_caps_and_redacts_secrets(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import write_playwright_mcp_config

    monkeypatch.setenv("PLAYWRIGHT_MCP_COMMAND", "playwright-mcp")
    monkeypatch.setenv("PLAYWRIGHT_MCP_ARGS", "--browser chromium")

    secrets = tmp_path / "secrets.env"
    secrets.write_text('BROWSER_AUTH_USERNAME="user@example.com"\n')

    runtime = write_playwright_mcp_config(
        run_dir=tmp_path,
        server_name="playwright-test",
        project_root=tmp_path,
        caps=("storage",),
        secrets_file=secrets,
    )

    config = json.loads((tmp_path / ".mcp.json").read_text())
    args = config["mcpServers"]["playwright-test"]["args"]
    assert "--caps" in args
    assert args[args.index("--caps") + 1] == "storage"
    assert "--secrets" in args
    assert args[args.index("--secrets") + 1] == str(secrets)
    assert "<run-local-secrets>" in runtime["mcp_args"]
    assert str(secrets) not in runtime["mcp_args"]


def test_resolve_playwright_chromium_executable_finds_chrome_linux64(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import resolve_playwright_chromium_executable

    chromium = tmp_path / "ms-playwright" / "chromium-9999" / "chrome-linux64" / "chrome"
    chromium.parent.mkdir(parents=True)
    chromium.write_text("#!/bin/sh\n")

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "ms-playwright"))
    monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_MCP_EXECUTABLE_PATH", raising=False)

    assert resolve_playwright_chromium_executable() == chromium


def test_resolve_playwright_chromium_executable_skips_inaccessible_home_cache(tmp_path, monkeypatch):
    from orchestrator.utils import playwright_mcp

    browser_root = tmp_path / "ms-playwright"
    chromium = browser_root / "chromium-9999" / "chrome-linux64" / "chrome"
    chromium.parent.mkdir(parents=True)
    chromium.write_text("#!/bin/sh\n")
    inaccessible = tmp_path / "inaccessible" / ".cache" / "ms-playwright"

    original_exists = playwright_mcp.Path.exists

    def exists_with_inaccessible_cache(path):
        if path == inaccessible:
            raise PermissionError(str(path))
        return original_exists(path)

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(browser_root))
    monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_MCP_EXECUTABLE_PATH", raising=False)
    monkeypatch.setattr(playwright_mcp.Path, "home", lambda: tmp_path / "inaccessible")
    monkeypatch.setattr(playwright_mcp.Path, "exists", exists_with_inaccessible_cache)

    assert playwright_mcp.resolve_playwright_chromium_executable() == chromium


def test_browser_runtime_status_handles_inaccessible_home_cache(tmp_path, monkeypatch):
    from orchestrator.utils import playwright_mcp

    inaccessible = tmp_path / "inaccessible" / ".cache" / "ms-playwright"
    original_exists = playwright_mcp.Path.exists

    def exists_with_inaccessible_cache(path):
        if path == inaccessible:
            raise PermissionError(str(path))
        if path == playwright_mcp.Path("/ms-playwright"):
            return False
        return original_exists(path)

    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_MCP_EXECUTABLE_PATH", raising=False)
    monkeypatch.setattr(playwright_mcp.Path, "home", lambda: tmp_path / "inaccessible")
    monkeypatch.setattr(playwright_mcp.Path, "exists", exists_with_inaccessible_cache)

    status = playwright_mcp.browser_runtime_status()

    assert status["browser_runtime"] == "unavailable"
    assert status["browser_executable"] is None


def test_write_playwright_test_mcp_config_injects_storage_state(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import write_playwright_test_mcp_config

    monkeypatch.setenv("HEADLESS", "true")
    storage_state = tmp_path / "state.json"
    storage_state.write_text('{"cookies":[],"origins":[]}')
    config_path = tmp_path / "playwright.config.ts"
    config_path.write_text(
        """import { defineConfig } from '@playwright/test';

export default defineConfig({
  use: {
    video: 'retain-on-failure',
  },
});
"""
    )

    write_playwright_test_mcp_config(
        run_dir=tmp_path,
        server_name="playwright-test",
        config_path=config_path,
        headless=True,
        storage_state_path=storage_state,
    )

    config_content = config_path.read_text()
    assert f"storageState: '{storage_state}'" in config_content
    mcp_config = json.loads((tmp_path / ".mcp.json").read_text())
    assert "--storage-state" not in mcp_config["mcpServers"]["playwright-test"]["args"]


def test_prepare_run_playwright_config_content_forces_headed_vnc_config(tmp_path):
    from orchestrator.utils.playwright_mcp import prepare_run_playwright_config_content

    source = """import { defineConfig } from '@playwright/test';

const webServerHost = process.env.PLAYWRIGHT_WEB_HOST || '0.0.0.0';

export default defineConfig({
  testDir: './tests/generated',
  outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || './test-results',
  workers: parseInt(process.env.PLAYWRIGHT_WORKERS || '4', 10),
  use: {
    video: 'retain-on-failure',
  },
});
"""

    prepared = prepare_run_playwright_config_content(
        source,
        base_dir=Path("/app"),
        run_dir=tmp_path,
        headless=False,
    )

    assert "const runHeaded = playwrightHeadless === 'false' || genericHeadless === 'false';" in prepared
    assert "workers: runHeaded ? 1 : configuredWorkers," in prepared
    assert "headless: runHeaded ? false : undefined," in prepared
    assert "testDir: '/app/tests/generated'" in prepared
    assert f"outputDir: process.env.PLAYWRIGHT_OUTPUT_DIR || '{tmp_path}/test-results'" in prepared
    assert "video: 'on'" in prepared

    prepared_again = prepare_run_playwright_config_content(
        prepared,
        base_dir=Path("/app"),
        run_dir=tmp_path,
        headless=False,
    )

    assert prepared_again.count("const runHeaded =") == 1
    assert prepared_again.count("headless: runHeaded ? false : undefined,") == 1


def test_prepare_run_playwright_config_content_keeps_seed_discoverable(tmp_path):
    from orchestrator.utils.playwright_mcp import prepare_run_playwright_config_content

    source = """import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testMatch: ['generated/**/*.spec.ts', 'e2e/**/*.spec.ts'],
});
"""

    prepared = prepare_run_playwright_config_content(
        source,
        base_dir=Path("/app"),
        run_dir=tmp_path,
        headless=False,
    )

    assert "testDir: '/app/tests'" in prepared
    assert "testMatch: ['seed.spec.ts', 'generated/**/*.spec.ts', 'e2e/**/*.spec.ts']" in prepared

    prepared_again = prepare_run_playwright_config_content(
        prepared,
        base_dir=Path("/app"),
        run_dir=tmp_path,
        headless=False,
    )

    assert prepared_again.count("testDir: '/app/tests'") == 1
    assert prepared_again.count("seed.spec.ts") == 1


def test_playwright_config_cli_arg_prefers_run_local_config(tmp_path):
    from orchestrator.utils.playwright_mcp import playwright_config_cli_arg

    config_path = tmp_path / "playwright.config.ts"
    config_path.write_text("export default {};\n")

    arg = playwright_config_cli_arg(tmp_path)

    assert "--config" in arg
    assert str(config_path) in arg


def test_cli_existing_code_run_uses_run_local_playwright_config(tmp_path, monkeypatch):
    from orchestrator import cli

    spec_path = tmp_path / "checkout.md"
    spec_path.write_text("# Checkout\n\n1. Open https://example.com")
    code_path = tmp_path / "checkout.spec.ts"
    code_path.write_text("import { test } from '@playwright/test';\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config_path = run_dir / "playwright.config.ts"
    config_path.write_text("export default {};\n")

    commands: list[str] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run_command(command, **_kwargs):
        commands.append(command)
        return Result()

    monkeypatch.setattr(cli, "run_command", fake_run_command)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "orchestrator/cli.py",
            str(spec_path),
            "--run-dir",
            str(run_dir),
            "--browser",
            "chromium",
            "--try-code",
            str(code_path),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == 0
    assert commands
    assert "--config" in commands[0]
    assert str(config_path) in commands[0]
