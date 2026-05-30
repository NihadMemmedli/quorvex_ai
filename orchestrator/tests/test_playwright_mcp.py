import json
import sys
from pathlib import Path


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
