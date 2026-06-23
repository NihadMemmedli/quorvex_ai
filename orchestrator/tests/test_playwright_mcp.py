import json
import shutil
import subprocess
import sys
import textwrap
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class _BeforeUnloadHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def do_GET(self):
        if self.path.startswith("/dirty"):
            body = b"""<!doctype html>
<html>
  <body>
    <h1>Dirty form</h1>
    <button id="dirty">Mark dirty</button>
    <script>
      let dirty = false;
      document.getElementById('dirty').addEventListener('click', () => {
        dirty = true;
        document.body.dataset.dirty = 'yes';
      });
      window.onbeforeunload = event => {
        if (!dirty) return;
        event.preventDefault();
        event.returnValue = '';
        return '';
      };
    </script>
  </body>
</html>"""
        elif self.path.startswith("/away"):
            body = b"<!doctype html><html><body><h1>Left page</h1></body></html>"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def beforeunload_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BeforeUnloadHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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
    assert server["alwaysLoad"] is True
    assert server["env"]["DISPLAY"] == ":99"
    assert server["env"]["VNC_ENABLED"] == "true"
    assert server["env"]["HEADLESS"] == "false"
    assert server["env"]["PLAYWRIGHT_HEADLESS"] == "false"
    assert server["env"]["CI"] == ""
    assert server["env"]["PLAYWRIGHT_WORKERS"] == "1"
    assert "PLAYWRIGHT_MCP_INIT_PAGE" not in server["env"]
    assert runtime["mcp_args"] == server["args"]
    assert runtime["mcp_env"]["DISPLAY"] == ":99"
    assert runtime["mcp_env"]["CI"] == ""
    assert runtime["dialog_recovery_attempted"] is True
    assert runtime["dialog_recovery_result"] == "run_local_seed_and_test_prelude"
    assert runtime["dialog_recovery_seed_file"] == "tests/seed.spec.ts"


def test_parse_browser_dialog_auto_accept_console_line():
    from orchestrator.utils.browser_dialog_recovery import parse_browser_dialog_recovery_console_line

    telemetry = parse_browser_dialog_recovery_console_line(
        "[quorvex] Browser dialog auto-accepted type=beforeunload message=Leave site?"
    )

    assert telemetry == {
        "browser_dialog_recovered": True,
        "dialog_recovery_attempted": True,
        "dialog_recovery_result": "auto_accepted",
        "dialog_recovery_dialog_type": "beforeunload",
        "dialog_recovery_message": "Leave site?",
    }


def test_browser_dialog_recovery_init_page_uses_commonjs_export(tmp_path):
    from orchestrator.utils.playwright_mcp import write_browser_dialog_recovery_init_page

    init_page = write_browser_dialog_recovery_init_page(tmp_path)
    content = init_page.read_text()

    assert "export default" not in content
    assert "exports.default = async ({ page }) => {" in content
    assert "page.on('dialog'" in content


def test_browser_dialog_recovery_init_page_exposes_require_default(tmp_path):
    if not shutil.which("node"):
        pytest.skip("node is required for the CommonJS default export regression")

    from orchestrator.utils.playwright_mcp import write_browser_dialog_recovery_init_page

    init_page = write_browser_dialog_recovery_init_page(tmp_path)
    probe = textwrap.dedent(
        f"""
        const initPage = require({json.dumps(str(init_page))});
        if (typeof initPage.default !== 'function') {{
          throw new Error('default export is not callable');
        }}
        const page = {{
          on(event, handler) {{
            if (event !== 'dialog' || typeof handler !== 'function') {{
              throw new Error('dialog handler was not registered');
            }}
          }}
        }};
        Promise.resolve(initPage.default({{ page }})).catch(error => {{
          console.error(error && error.stack ? error.stack : error);
          process.exit(1);
        }});
        """
    )
    result = subprocess.run(
        ["node", "-e", probe],
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr


def test_generated_dialog_recovery_accepts_beforeunload_without_hanging(
    tmp_path,
    monkeypatch,
    beforeunload_server,
):
    if not shutil.which("node"):
        pytest.skip("node is required for the Playwright beforeunload regression")

    probe = subprocess.run(
        ["node", "-e", "require('playwright');"],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        timeout=10,
    )
    if probe.returncode != 0:
        pytest.skip(f"playwright is not available to node: {probe.stderr.strip()}")

    from orchestrator.api.run_files import write_run_seed_spec
    from orchestrator.utils.playwright_mcp import write_playwright_test_mcp_config

    monkeypatch.setenv("HEADLESS", "true")
    monkeypatch.setenv("BROWSER_HOST_INTERNAL", "127.0.0.1")
    target_url = f"{beforeunload_server}/dirty"
    away_url = f"{beforeunload_server}/away"
    seed_path = write_run_seed_spec(tmp_path, target_url)
    config_path = tmp_path / "playwright.config.ts"
    config_path.write_text("export default {};\n")
    write_playwright_test_mcp_config(
        run_dir=tmp_path,
        server_name="playwright-test",
        config_path=config_path,
        headless=True,
    )
    mcp_config = json.loads((tmp_path / ".mcp.json").read_text())
    assert "PLAYWRIGHT_MCP_INIT_PAGE" not in mcp_config["mcpServers"]["playwright-test"]["env"]

    script_path = tmp_path / "beforeunload-regression.cjs"
    script_path.write_text(
        textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const {{ createRequire }} = require('module');
            const rootRequire = createRequire({json.dumps(str(Path(__file__).resolve().parents[2] / "package.json"))});
            const {{ chromium }} = rootRequire('playwright');

            const seedPath = {json.dumps(str(seed_path))};
            const awayUrl = {json.dumps(away_url)};
            const logs = [];
            const originalLog = console.log;
            console.log = (...args) => {{
              logs.push(args.join(' '));
            }};

            function seedTargetUrl(path) {{
              const seed = fs.readFileSync(path, 'utf8');
              const match = seed.match(/const targetUrl = ("(?:[^"\\\\]|\\\\.)*");/);
              if (!match) throw new Error('targetUrl not found in seed spec');
              return JSON.parse(match[1]);
            }}

            async function applySeedPrelude(page, path) {{
              const seed = fs.readFileSync(path, 'utf8');
              const match = seed.match(/page\\.on\\('dialog',[\\s\\S]*?\\n  \\}}\\);/);
              if (!match) throw new Error('dialog handler not found in seed spec');
              const context = {{ page, console }};
              await vm.runInNewContext(`(async () => {{\\n${{match[0]}}\\n}})()`, context, {{ filename: path }});
            }}

            (async () => {{
              const browser = await chromium.launch({{ headless: true }});
              try {{
                const page = await browser.newPage();
                await applySeedPrelude(page, seedPath);
                await page.goto(seedTargetUrl(seedPath), {{ waitUntil: 'domcontentloaded', timeout: 5000 }});
                await page.click('#dirty');
                await page.goto(awayUrl, {{ waitUntil: 'domcontentloaded', timeout: 5000 }});
                const snapshotText = await page.locator('body').innerText({{ timeout: 5000 }});
                const heading = await page.textContent('h1');
                originalLog(JSON.stringify({{
                  heading,
                  logs,
                  snapshotText,
                  url: page.url(),
                }}));
              }} finally {{
                await browser.close();
              }}
            }})().catch(error => {{
              console.error(error && error.stack ? error.stack : error);
              process.exit(1);
            }});
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["node", str(script_path)],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        timeout=15,
    )
    if result.returncode != 0 and "Executable doesn't exist" in result.stderr:
        pytest.skip(result.stderr.strip())

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["heading"] == "Left page"
    assert payload["url"] == away_url
    assert "Left page" in payload["snapshotText"]
    assert any(
        "[quorvex] Browser dialog auto-accepted type=beforeunload" in line
        for line in payload["logs"]
    )


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
    assert "PLAYWRIGHT_MCP_INIT_PAGE" not in server["env"]
    assert "CI" not in server["env"]
    assert "PLAYWRIGHT_WORKERS" not in server["env"]


def test_write_playwright_test_mcp_config_forces_headless_without_display(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import write_playwright_test_mcp_config

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("VNC_ENABLED", "true")
    monkeypatch.setenv("HEADLESS", "false")
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "false")

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
    assert server["args"] == ["playwright", "run-test-mcp-server", "-c", str(config_path), "--headless"]
    assert server["env"]["HEADLESS"] == "true"
    assert server["env"]["PLAYWRIGHT_HEADLESS"] == "true"
    assert "CI" not in server["env"]
    assert "PLAYWRIGHT_WORKERS" not in server["env"]
    assert runtime["mcp_args"] == server["args"]


def test_write_playwright_mcp_config_defaults_to_headless_without_env(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import write_playwright_mcp_config

    monkeypatch.setenv("PLAYWRIGHT_MCP_COMMAND", "playwright-mcp")
    monkeypatch.setenv("PLAYWRIGHT_MCP_ARGS", "--browser chromium")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("VNC_ENABLED", raising=False)
    monkeypatch.delenv("HEADLESS", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_HEADLESS", raising=False)

    runtime = write_playwright_mcp_config(
        run_dir=tmp_path,
        server_name="playwright-test",
        project_root=tmp_path,
    )

    config = json.loads((tmp_path / ".mcp.json").read_text())
    server = config["mcpServers"]["playwright-test"]
    assert "--headless" in server["args"]
    assert server["env"]["HEADLESS"] == "true"
    assert server["env"]["PLAYWRIGHT_HEADLESS"] == "true"
    assert runtime["mcp_env"]["HEADLESS"] == "true"


def test_write_playwright_mcp_config_ignores_stale_headed_env_without_display(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import write_playwright_mcp_config

    monkeypatch.setenv("PLAYWRIGHT_MCP_COMMAND", "playwright-mcp")
    monkeypatch.setenv("PLAYWRIGHT_MCP_ARGS", "--browser chromium")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("VNC_ENABLED", "true")
    monkeypatch.setenv("HEADLESS", "false")
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "false")

    runtime = write_playwright_mcp_config(
        run_dir=tmp_path,
        server_name="playwright-test",
        project_root=tmp_path,
    )

    config = json.loads((tmp_path / ".mcp.json").read_text())
    server = config["mcpServers"]["playwright-test"]
    assert "--headless" in server["args"]
    assert server["env"]["HEADLESS"] == "true"
    assert server["env"]["PLAYWRIGHT_HEADLESS"] == "true"
    assert "CI" not in server["env"]
    assert "PLAYWRIGHT_WORKERS" not in server["env"]
    assert runtime["mcp_env"]["HEADLESS"] == "true"


def test_playwright_headed_cli_args_requires_display_capable_vnc():
    from orchestrator.utils.playwright_mcp import playwright_headed_cli_args

    assert playwright_headed_cli_args({"HEADLESS": "false"}) == ""
    assert (
        playwright_headed_cli_args(
            {"VNC_ENABLED": "true", "DISPLAY": ":99", "PLAYWRIGHT_HEADLESS": "false"}
        )
        == " --headed --workers=1"
    )


def test_playwright_headed_cli_args_treats_either_headless_false_as_headed():
    from orchestrator.utils.playwright_mcp import playwright_headed_cli_args

    assert (
        playwright_headed_cli_args(
            {"VNC_ENABLED": "true", "DISPLAY": ":99", "HEADLESS": "true", "PLAYWRIGHT_HEADLESS": "false"}
        )
        == " --headed --workers=1"
    )


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
    assert "--init-page" in args
    init_page = Path(args[args.index("--init-page") + 1])
    assert init_page.exists()
    init_page_content = init_page.read_text()
    assert "export default" not in init_page_content
    assert "exports.default = async ({ page }) => {" in init_page_content
    assert "page.on('dialog'" in init_page_content


def test_write_playwright_mcp_config_includes_visible_vnc_env(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import write_playwright_mcp_config

    monkeypatch.setenv("PLAYWRIGHT_MCP_COMMAND", "playwright-mcp")
    monkeypatch.setenv("PLAYWRIGHT_MCP_ARGS", "--browser chromium")
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("VNC_ENABLED", "true")
    monkeypatch.setenv("HEADLESS", "false")
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "false")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")

    runtime = write_playwright_mcp_config(
        run_dir=tmp_path,
        server_name="playwright-test",
        project_root=tmp_path,
    )

    config = json.loads((tmp_path / ".mcp.json").read_text())
    server = config["mcpServers"]["playwright-test"]
    assert server["env"]["DISPLAY"] == ":99"
    assert server["env"]["VNC_ENABLED"] == "true"
    assert server["env"]["HEADLESS"] == "false"
    assert server["env"]["PLAYWRIGHT_HEADLESS"] == "false"
    assert server["env"]["CI"] == ""
    assert server["env"]["PLAYWRIGHT_WORKERS"] == "1"
    assert runtime["mcp_env"] == server["env"]


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
    assert runtime["dialog_recovery_attempted"] is True
    assert runtime["dialog_recovery_result"] == "init_page_registered"
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


def test_resolve_playwright_chromium_executable_picks_newest_installed_revision(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import resolve_playwright_chromium_executable

    browser_root = tmp_path / "ms-playwright"
    older = browser_root / "chromium-1226" / "chrome-linux64" / "chrome"
    newer = browser_root / "chromium-1228" / "chrome-linux64" / "chrome"
    lexicographic_trap = browser_root / "chromium-999" / "chrome-linux64" / "chrome"
    older.parent.mkdir(parents=True)
    newer.parent.mkdir(parents=True)
    lexicographic_trap.parent.mkdir(parents=True)
    older.write_text("#!/bin/sh\n")
    newer.write_text("#!/bin/sh\n")
    lexicographic_trap.write_text("#!/bin/sh\n")

    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(browser_root))
    monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", raising=False)
    monkeypatch.delenv("PLAYWRIGHT_MCP_EXECUTABLE_PATH", raising=False)

    assert resolve_playwright_chromium_executable() == newer


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


def test_write_playwright_test_mcp_config_injects_default_action_timeout(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import write_playwright_test_mcp_config

    monkeypatch.delenv("AGENT_BROWSER_ACTION_TIMEOUT_SECONDS", raising=False)
    config_path = tmp_path / "playwright.config.ts"
    config_path.write_text(
        """import { defineConfig } from '@playwright/test';

export default defineConfig({
  use: {
    trace: 'on-first-retry',
  },
});
"""
    )

    runtime = write_playwright_test_mcp_config(
        run_dir=tmp_path,
        server_name="playwright-test",
        config_path=config_path,
        headless=True,
    )

    config_content = config_path.read_text()
    assert "process.env.AGENT_BROWSER_ACTION_TIMEOUT_SECONDS || '30'" in config_content
    assert "actionTimeout: browserActionTimeout" in config_content
    assert runtime["browser_action_timeout_seconds"] == 30.0
    assert runtime["browser_action_timeout_env"] == "AGENT_BROWSER_ACTION_TIMEOUT_SECONDS"


def test_write_playwright_test_mcp_config_uses_action_timeout_env_override(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import write_playwright_test_mcp_config

    monkeypatch.setenv("AGENT_BROWSER_ACTION_TIMEOUT_SECONDS", "12")
    config_path = tmp_path / "playwright.config.ts"
    config_path.write_text(
        """import { defineConfig } from '@playwright/test';

export default defineConfig({
  use: {
    trace: 'on-first-retry',
  },
});
"""
    )

    runtime = write_playwright_test_mcp_config(
        run_dir=tmp_path,
        server_name="playwright-test",
        config_path=config_path,
        headless=True,
    )

    config_content = config_path.read_text()
    assert "process.env.AGENT_BROWSER_ACTION_TIMEOUT_SECONDS || '12'" in config_content
    assert "  : 12000;" in config_content
    assert runtime["browser_action_timeout_seconds"] == 12.0


def test_write_playwright_mcp_config_passes_generic_action_timeout(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import write_playwright_mcp_config

    monkeypatch.setenv("AGENT_BROWSER_ACTION_TIMEOUT_SECONDS", "30")
    runtime = write_playwright_mcp_config(
        run_dir=tmp_path,
        server_name="playwright",
        project_root=tmp_path,
    )

    mcp_config = json.loads((tmp_path / ".mcp.json").read_text())
    server = mcp_config["mcpServers"]["playwright"]
    assert "--timeout-action" in server["args"]
    assert server["args"][server["args"].index("--timeout-action") + 1] == "30000"
    assert server["env"]["AGENT_BROWSER_ACTION_TIMEOUT_SECONDS"] == "30"
    assert server["env"]["PLAYWRIGHT_MCP_TIMEOUT_ACTION"] == "30000"
    assert runtime["browser_action_timeout_seconds"] == 30.0


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
    assert f"testDir: '{tmp_path}/tests'" in prepared
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
  use: {
    trace: 'on-first-retry',
  },
});
"""

    prepared = prepare_run_playwright_config_content(
        source,
        base_dir=Path("/app"),
        run_dir=tmp_path,
        headless=False,
    )

    assert f"testDir: '{tmp_path}/tests'" in prepared
    assert "testMatch: ['seed.spec.ts', 'generated/**/*.spec.ts', 'e2e/**/*.spec.ts']" in prepared
    assert "navigationTimeout: 60_000" in prepared

    prepared_again = prepare_run_playwright_config_content(
        prepared,
        base_dir=Path("/app"),
        run_dir=tmp_path,
        headless=False,
    )

    assert prepared_again.count(f"testDir: '{tmp_path}/tests'") == 1
    assert prepared_again.count("seed.spec.ts") == 1
    assert prepared_again.count("navigationTimeout: 60_000") == 1


def test_prepare_run_playwright_config_content_resolves_relative_run_dir(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import prepare_run_playwright_config_content

    monkeypatch.chdir(tmp_path)
    run_dir = Path("runs") / "relative-run"
    source = """import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
});
"""

    prepared = prepare_run_playwright_config_content(
        source,
        base_dir=Path("/app"),
        run_dir=run_dir,
        headless=True,
    )

    assert f"testDir: '{(tmp_path / run_dir / 'tests').resolve()}'" in prepared


def test_prepare_run_playwright_config_content_resolves_relative_storage_state(tmp_path, monkeypatch):
    from orchestrator.utils.playwright_mcp import prepare_run_playwright_config_content

    monkeypatch.chdir(tmp_path)
    storage_state = Path("runs") / "relative-run" / "browser-auth-storage-state.json"
    source = """import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  use: {
    trace: 'on-first-retry',
  },
});
"""

    prepared = prepare_run_playwright_config_content(
        source,
        base_dir=Path("/app"),
        run_dir=Path("runs") / "relative-run",
        headless=True,
        storage_state_path=storage_state,
    )

    assert f"storageState: '{storage_state.resolve()}'" in prepared


def test_validate_run_seed_spec_preflight_requires_seed_under_configured_test_dir(tmp_path):
    from orchestrator.utils.playwright_mcp import validate_run_seed_spec_preflight

    config_path = tmp_path / "playwright.config.ts"
    config_path.write_text(
        f"export default {{ testDir: '{tmp_path}/tests', testMatch: ['seed.spec.ts'] }};\n"
    )
    seed_path = tmp_path / "tests" / "seed.spec.ts"
    seed_path.parent.mkdir(parents=True)
    seed_path.write_text("import { test } from '@playwright/test';\n")

    preflight = validate_run_seed_spec_preflight(
        run_dir=tmp_path,
        config_path=config_path,
    )

    assert preflight["ready"] is True
    assert preflight["seed_path"] == str(seed_path.resolve())


def test_validate_run_seed_spec_preflight_fails_when_seed_outside_test_dir(tmp_path):
    from orchestrator.utils.playwright_mcp import validate_run_seed_spec_preflight

    config_path = tmp_path / "playwright.config.ts"
    config_path.write_text(
        "export default { testDir: '/app/tests', testMatch: ['seed.spec.ts'] };\n"
    )
    seed_path = tmp_path / "tests" / "seed.spec.ts"
    seed_path.parent.mkdir(parents=True)
    seed_path.write_text("import { test } from '@playwright/test';\n")

    preflight = validate_run_seed_spec_preflight(
        run_dir=tmp_path,
        config_path=config_path,
    )

    assert preflight["ready"] is False
    assert "outside configured Playwright testDir" in preflight["error"]


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
