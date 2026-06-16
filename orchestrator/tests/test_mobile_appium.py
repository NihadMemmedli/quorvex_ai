import json
from pathlib import Path

from orchestrator.utils.agent_runner import build_mcp_allowed_tools
from orchestrator.workflows.mobile_appium import (
    MobileAppiumConfig,
    MobileAppiumWorkflow,
    build_appium_mcp_config,
    extract_target_url,
)


def test_extract_target_url_prefers_mobile_url():
    content = """
# Mobile Smoke

Target URL: https://fallback.example
Mobile URL: https://mobile.example
"""
    assert extract_target_url(content) == "https://mobile.example"


def test_ios_safari_capabilities_include_signing_and_udid(tmp_path, monkeypatch):
    monkeypatch.setenv("IOS_TEAM_ID", "TEAM123")
    monkeypatch.setenv("IOS_BUNDLE_ID_PREFIX", "com.example.quorvex")
    monkeypatch.setenv("IOS_UDID", "device-udid")

    config = MobileAppiumConfig.from_env(target_url="https://example.com")
    config.tests_dir = str(tmp_path / "tests")
    config.screenshots_dir = str(tmp_path / "screenshots")
    workflow = MobileAppiumWorkflow(config)

    caps = workflow.build_ios_safari_capabilities()

    assert caps["platformName"] == "iOS"
    assert caps["browserName"] == "Safari"
    assert caps["appium:automationName"] == "XCUITest"
    assert caps["appium:udid"] == "device-udid"
    assert caps["appium:xcodeOrgId"] == "TEAM123"
    assert caps["appium:updatedWDABundleId"] == "com.example.quorvex.WebDriverAgentRunner"


def test_capabilities_file_overrides_defaults(tmp_path):
    caps_file = tmp_path / "capabilities.json"
    caps_file.write_text(
        json.dumps(
            {
                "ios": {
                    "appium:platformVersion": "17.5",
                    "appium:deviceName": "Nihad's iPhone",
                }
            }
        )
    )

    config = MobileAppiumConfig(capabilities_file=str(caps_file))
    workflow = MobileAppiumWorkflow(config)

    caps = workflow.load_capabilities(udid="detected-udid")

    assert caps["browserName"] == "Safari"
    assert caps["appium:udid"] == "detected-udid"
    assert caps["appium:platformVersion"] == "17.5"
    assert caps["appium:deviceName"] == "Nihad's iPhone"


def test_appium_mcp_config_uses_no_ui_and_capabilities(tmp_path):
    caps_file = tmp_path / "caps.json"
    config = MobileAppiumConfig(screenshots_dir=str(tmp_path / "shots"))

    mcp_config = build_appium_mcp_config(config, capabilities_file=str(caps_file))
    server = mcp_config["mcpServers"]["appium-mcp"]

    assert server["command"] == "npx"
    assert server["args"] == ["appium-mcp"]
    assert server["env"]["NO_UI"] == "true"
    assert server["env"]["CAPABILITIES_CONFIG"] == str(caps_file)


def test_appium_allowed_tools_are_prefixed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path(".mcp.json").write_text(json.dumps({"mcpServers": {"appium-mcp": {"command": "npx"}}}))

    tools = build_mcp_allowed_tools("appium", ["Read"], ["create_session", "appium_screenshot"])

    assert tools == [
        "Read",
        "mcp__appium-mcp__create_session",
        "mcp__appium-mcp__appium_screenshot",
    ]


def test_safari_smoke_script_uses_webdriverio_and_deletes_session(tmp_path):
    caps_file = tmp_path / "caps.json"
    caps_file.write_text("{}")
    config = MobileAppiumConfig(
        appium_server_url="http://127.0.0.1:4723",
        screenshots_dir=str(tmp_path / "screenshots"),
        tests_dir=str(tmp_path / "tests"),
    )
    workflow = MobileAppiumWorkflow(config)

    script = workflow.render_safari_smoke_script(
        test_name="Smoke",
        target_url="https://example.com",
        capabilities_path=caps_file,
        screenshot_name="smoke.png",
    )

    assert "require('webdriverio')" in script
    assert "await driver.url(\"https://example.com\")" in script
    assert "await driver.deleteSession()" in script
