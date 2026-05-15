"""
Mobile Appium workflow support.

This module provides the deterministic real-device smoke path used by the CLI
and API before broader AI-assisted Appium MCP generation is attempted. It keeps
mobile setup isolated from the existing Playwright browser pipeline.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent


@dataclass
class MobilePreflightCheck:
    name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class MobilePreflightResult:
    ready: bool
    checks: list[MobilePreflightCheck]
    errors: list[str]
    warnings: list[str]
    udid: str | None = None
    device_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "checks": [asdict(check) for check in self.checks],
            "errors": self.errors,
            "warnings": self.warnings,
            "udid": self.udid,
            "device_name": self.device_name,
        }


@dataclass
class MobileAppiumConfig:
    platform: str = "ios"
    appium_server_url: str = "http://127.0.0.1:4723"
    capabilities_file: str | None = None
    udid: str | None = None
    ios_team_id: str | None = None
    ios_bundle_id_prefix: str | None = None
    screenshots_dir: str = str(BASE_DIR / "runs" / "appium-screenshots")
    tests_dir: str = str(BASE_DIR / "tests" / "mobile")
    target_url: str = "https://example.com"
    appium_home: str | None = None

    @classmethod
    def from_env(
        cls,
        *,
        platform: str = "ios",
        appium_server_url: str | None = None,
        capabilities_file: str | None = None,
        target_url: str | None = None,
    ) -> "MobileAppiumConfig":
        return cls(
            platform=(platform or os.environ.get("MOBILE_PLATFORM") or "ios").lower(),
            appium_server_url=appium_server_url
            or os.environ.get("APPIUM_SERVER_URL")
            or "http://127.0.0.1:4723",
            capabilities_file=capabilities_file or os.environ.get("APPIUM_CAPABILITIES_CONFIG"),
            udid=os.environ.get("IOS_UDID"),
            ios_team_id=os.environ.get("IOS_TEAM_ID"),
            ios_bundle_id_prefix=os.environ.get("IOS_BUNDLE_ID_PREFIX"),
            screenshots_dir=os.environ.get("APPIUM_SCREENSHOTS_DIR")
            or str(BASE_DIR / "runs" / "appium-screenshots"),
            tests_dir=os.environ.get("MOBILE_TESTS_DIR") or str(BASE_DIR / "tests" / "mobile"),
            target_url=target_url or os.environ.get("MOBILE_TARGET_URL") or "https://example.com",
            appium_home=os.environ.get("APPIUM_HOME"),
        )


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "mobile-smoke"


def extract_target_url(spec_content: str, default: str = "https://example.com") -> str:
    patterns = [
        r"Mobile\s+URL:\s*(https?://[^\s'\"`]+)",
        r"Target\s+URL:\s*(https?://[^\s'\"`]+)",
        r"Navigate\s+to\s+(https?://[^\s'\"`]+)",
        r"Open\s+(https?://[^\s'\"`]+)",
        r"(https?://[^\s'\"`]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, spec_content, re.IGNORECASE)
        if match:
            return match.group(1).rstrip(".")
    return default


def extract_test_name(spec_path: Path, spec_content: str) -> str:
    for line in spec_content.splitlines():
        if line.startswith("# "):
            return line.replace("# ", "").replace("Test:", "").strip()
    return spec_path.stem.replace("-", " ").replace("_", " ").title()


class AppiumPreflightChecker:
    """Preflight checks for local real iPhone Appium execution."""

    def __init__(self, config: MobileAppiumConfig):
        self.config = config

    def run(self, require_server: bool = True) -> MobilePreflightResult:
        checks: list[MobilePreflightCheck] = []
        warnings: list[str] = []
        detected_udid: str | None = None
        detected_name: str | None = None

        checks.append(self._check_binary("node"))
        checks.append(self._check_binary("npx"))
        checks.append(self._check_node_version())
        checks.append(self._check_local_npm_package("appium-mcp"))
        checks.append(self._check_local_npm_package("appium"))
        checks.append(self._check_local_npm_package("webdriverio"))

        if self.config.platform == "ios":
            checks.append(self._check_xcode_selected())
            checks.append(self._check_xcodebuild())
            checks.append(self._check_xctrace())
            if self._is_local_server():
                checks.append(self._check_appium_driver("xcuitest"))
            device_check, detected_udid = self._check_ios_device()
            checks.append(device_check)
            name_check, detected_name = self._check_ios_device_name()
            checks.append(name_check)
            checks.append(self._check_env_value("IOS_TEAM_ID", self.config.ios_team_id))
            checks.append(self._check_env_value("IOS_BUNDLE_ID_PREFIX", self.config.ios_bundle_id_prefix))

        if self.config.capabilities_file:
            checks.append(self._check_capabilities_file(Path(self.config.capabilities_file)))

        if require_server:
            checks.append(self._check_appium_server())

        errors = [check.message for check in checks if not check.passed]
        ready = not errors
        return MobilePreflightResult(
            ready=ready,
            checks=checks,
            errors=errors,
            warnings=warnings,
            udid=self.config.udid or detected_udid,
            device_name=detected_name,
        )

    def _run_command(self, cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def _check_binary(self, name: str) -> MobilePreflightCheck:
        path = shutil.which(name)
        return MobilePreflightCheck(
            name=f"binary:{name}",
            passed=bool(path),
            message=f"{name} found at {path}" if path else f"{name} not found in PATH",
            details={"path": path},
        )

    def _check_node_version(self) -> MobilePreflightCheck:
        try:
            result = self._run_command(["node", "--version"], timeout=5)
            version = result.stdout.strip().lstrip("v")
            major = int(version.split(".")[0])
            passed = result.returncode == 0 and major >= 22
            return MobilePreflightCheck(
                name="node_version",
                passed=passed,
                message=f"Node.js {version} is available" if passed else "Node.js v22+ is required for appium-mcp",
                details={"version": version, "returncode": result.returncode},
            )
        except Exception as exc:
            return MobilePreflightCheck("node_version", False, f"Could not check Node.js version: {exc}")

    def _check_local_npm_package(self, package_name: str) -> MobilePreflightCheck:
        package_json = BASE_DIR / "node_modules" / package_name / "package.json"
        if package_json.exists():
            try:
                version = json.loads(package_json.read_text()).get("version")
            except Exception:
                version = None
            return MobilePreflightCheck(
                name=f"npm:{package_name}",
                passed=True,
                message=f"{package_name} is installed locally",
                details={"version": version, "path": str(package_json)},
            )
        return MobilePreflightCheck(
            name=f"npm:{package_name}",
            passed=False,
            message=f"{package_name} is not installed locally; run npm install",
        )

    def _is_local_server(self) -> bool:
        parsed = urlparse(self.config.appium_server_url)
        return parsed.hostname in (None, "localhost", "127.0.0.1", "::1")

    def _check_appium_driver(self, driver_name: str) -> MobilePreflightCheck:
        env = os.environ.copy()
        if self.config.appium_home:
            env["APPIUM_HOME"] = self.config.appium_home
        try:
            result = subprocess.run(
                ["npx", "appium", "driver", "list", "--installed"],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
            output = (result.stdout + result.stderr).strip()
            passed = result.returncode == 0 and driver_name.lower() in output.lower()
            return MobilePreflightCheck(
                name=f"appium_driver:{driver_name}",
                passed=passed,
                message=(
                    f"Appium {driver_name} driver is installed"
                    if passed
                    else f"Appium {driver_name} driver is not installed; run npx appium driver install {driver_name}"
                ),
                details={"output": output[:1000], "appiumHome": self.config.appium_home},
            )
        except Exception as exc:
            return MobilePreflightCheck(
                name=f"appium_driver:{driver_name}",
                passed=False,
                message=f"Could not check Appium {driver_name} driver: {exc}",
            )

    def _check_xcode_selected(self) -> MobilePreflightCheck:
        try:
            result = self._run_command(["xcode-select", "-p"], timeout=5)
            path = result.stdout.strip()
            passed = result.returncode == 0 and bool(path) and "CommandLineTools" not in path
            message = (
                f"Full Xcode developer directory selected: {path}"
                if passed
                else "Full Xcode is required; select it with sudo xcode-select -s /Applications/Xcode.app/Contents/Developer"
            )
            return MobilePreflightCheck("xcode_select", passed, message, {"path": path})
        except Exception as exc:
            return MobilePreflightCheck("xcode_select", False, f"Could not check xcode-select: {exc}")

    def _check_xcodebuild(self) -> MobilePreflightCheck:
        try:
            result = self._run_command(["xcodebuild", "-version"], timeout=10)
            output = (result.stdout + result.stderr).strip()
            passed = result.returncode == 0
            return MobilePreflightCheck(
                "xcodebuild",
                passed,
                output if passed else "xcodebuild failed; full Xcode is required for WebDriverAgent",
                {"output": output[:500], "returncode": result.returncode},
            )
        except Exception as exc:
            return MobilePreflightCheck("xcodebuild", False, f"Could not run xcodebuild: {exc}")

    def _check_xctrace(self) -> MobilePreflightCheck:
        try:
            result = self._run_command(["xcrun", "xctrace", "list", "devices"], timeout=20)
            output = (result.stdout + result.stderr).strip()
            passed = result.returncode == 0
            return MobilePreflightCheck(
                "xctrace",
                passed,
                "xctrace can list devices" if passed else "xctrace is unavailable; full Xcode is required",
                {"output": output[:1000], "returncode": result.returncode},
            )
        except Exception as exc:
            return MobilePreflightCheck("xctrace", False, f"Could not run xctrace: {exc}")

    def _check_ios_device(self) -> tuple[MobilePreflightCheck, str | None]:
        if not shutil.which("idevice_id"):
            return (
                MobilePreflightCheck(
                    "ios_device",
                    False,
                    "idevice_id not found; install libimobiledevice to detect connected iPhones",
                ),
                None,
            )

        try:
            result = self._run_command(["idevice_id", "-l"], timeout=15)
            devices = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            expected = self.config.udid
            detected = expected if expected in devices else (devices[0] if devices else None)
            passed = bool(detected) and (not expected or expected in devices)
            message = (
                f"Connected iOS device detected: {detected}"
                if passed
                else "No trusted, connected iOS device detected via idevice_id"
            )
            return MobilePreflightCheck("ios_device", passed, message, {"devices": devices}), detected
        except Exception as exc:
            return MobilePreflightCheck("ios_device", False, f"Could not detect iOS device: {exc}"), None

    def _check_ios_device_name(self) -> tuple[MobilePreflightCheck, str | None]:
        if not shutil.which("ideviceinfo"):
            return MobilePreflightCheck("ios_device_name", True, "ideviceinfo not installed; name check skipped"), None
        try:
            result = self._run_command(["ideviceinfo", "-k", "DeviceName"], timeout=15)
            name = result.stdout.strip()
            return MobilePreflightCheck(
                "ios_device_name",
                True,
                f"Device name: {name}" if name else "Device name unavailable",
                {"deviceName": name or None},
            ), (name or None)
        except Exception as exc:
            return MobilePreflightCheck("ios_device_name", True, f"Device name check skipped: {exc}"), None

    def _check_env_value(self, name: str, value: str | None) -> MobilePreflightCheck:
        return MobilePreflightCheck(
            name=f"env:{name}",
            passed=bool(value),
            message=f"{name} is set" if value else f"{name} is required for iOS WebDriverAgent signing",
        )

    def _check_capabilities_file(self, path: Path) -> MobilePreflightCheck:
        if not path.exists():
            return MobilePreflightCheck(
                "capabilities_file",
                False,
                f"Capabilities file not found: {path}",
                {"path": str(path)},
            )
        try:
            data = json.loads(path.read_text())
            passed = isinstance(data, dict)
            return MobilePreflightCheck(
                "capabilities_file",
                passed,
                f"Capabilities file is valid JSON: {path}" if passed else "Capabilities file must contain a JSON object",
                {"path": str(path)},
            )
        except Exception as exc:
            return MobilePreflightCheck("capabilities_file", False, f"Invalid capabilities JSON: {exc}")

    def _check_appium_server(self) -> MobilePreflightCheck:
        try:
            url = self.config.appium_server_url.rstrip("/") + "/status"
            request = Request(url, headers={"User-Agent": "quorvex-appium-preflight"})
            with urlopen(request, timeout=5) as response:
                body = response.read(4096).decode("utf-8", errors="replace")
                passed = 200 <= getattr(response, "status", 200) < 300
                return MobilePreflightCheck(
                    "appium_server",
                    passed,
                    f"Appium server reachable at {self.config.appium_server_url}"
                    if passed
                    else f"Appium server returned HTTP {getattr(response, 'status', 'unknown')}",
                    {"url": url, "response": body[:500]},
                )
        except Exception as exc:
            return MobilePreflightCheck(
                "appium_server",
                False,
                f"Appium server is not reachable at {self.config.appium_server_url}: {exc}",
            )


class MobileAppiumWorkflow:
    """Generate and run the iOS Safari smoke test through Appium/WebdriverIO."""

    def __init__(self, config: MobileAppiumConfig):
        self.config = config
        self.tests_dir = Path(config.tests_dir)
        self.screenshots_dir = Path(config.screenshots_dir)
        self.tests_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    def build_ios_safari_capabilities(self, udid: str | None = None) -> dict[str, Any]:
        capabilities: dict[str, Any] = {
            "platformName": "iOS",
            "browserName": "Safari",
            "appium:automationName": "XCUITest",
        }
        effective_udid = self.config.udid or udid
        if effective_udid:
            capabilities["appium:udid"] = effective_udid
        if self.config.ios_team_id:
            capabilities["appium:xcodeOrgId"] = self.config.ios_team_id
            capabilities["appium:xcodeSigningId"] = "iPhone Developer"
        if self.config.ios_bundle_id_prefix:
            capabilities["appium:updatedWDABundleId"] = (
                f"{self.config.ios_bundle_id_prefix}.WebDriverAgentRunner"
            )
        return capabilities

    def load_capabilities(self, udid: str | None = None) -> dict[str, Any]:
        capabilities = self.build_ios_safari_capabilities(udid=udid)
        if not self.config.capabilities_file:
            return capabilities

        data = json.loads(Path(self.config.capabilities_file).read_text())
        override = data.get("ios", data) if isinstance(data, dict) else {}
        if not isinstance(override, dict):
            raise ValueError("Capabilities file must contain a JSON object")
        merged = {**capabilities, **override}
        if udid and "appium:udid" not in merged:
            merged["appium:udid"] = udid
        return merged

    async def run_safari_smoke(self, spec_path: str, run_dir: Path) -> dict[str, Any]:
        spec_file = Path(spec_path)
        spec_content = spec_file.read_text()
        test_name = extract_test_name(spec_file, spec_content)
        target_url = extract_target_url(spec_content, default=self.config.target_url)
        self.config.target_url = target_url

        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "status.txt").write_text("running")
        (run_dir / "spec.md").write_text(spec_content)

        preflight = AppiumPreflightChecker(self.config).run(require_server=True)
        (run_dir / "mobile_preflight.json").write_text(json.dumps(preflight.to_dict(), indent=2))
        if not preflight.ready:
            error_msg = "; ".join(preflight.errors)
            (run_dir / "status.txt").write_text("error")
            (run_dir / "pipeline_error.json").write_text(
                json.dumps({"stage": "mobile_preflight", "error": error_msg}, indent=2)
            )
            return {
                "success": False,
                "stage": "mobile_preflight",
                "error": error_msg,
                "preflight": preflight.to_dict(),
                "test_type": "mobile",
            }

        capabilities = self.load_capabilities(udid=preflight.udid)
        capabilities_file = run_dir / "appium-capabilities.json"
        capabilities_file.write_text(json.dumps(capabilities, indent=2))

        output_name = slugify(test_name)
        test_path = self.tests_dir / f"{output_name}.mobile.spec.js"
        test_path.write_text(
            self.render_safari_smoke_script(
                test_name=test_name,
                target_url=target_url,
                capabilities_path=capabilities_file,
                screenshot_name=f"{output_name}.png",
            )
        )

        plan_data = {
            "testName": test_name,
            "specFileName": spec_file.name,
            "specFilePath": str(spec_file.absolute()),
            "targetUrl": target_url,
            "platform": "ios",
            "browser": "mobile-ios-safari",
            "steps": [
                {"stepNumber": 1, "action": "create_appium_session", "target": "iOS Safari"},
                {"stepNumber": 2, "action": "navigate", "target": target_url},
                {"stepNumber": 3, "action": "assert_title", "target": "non-empty title"},
                {"stepNumber": 4, "action": "screenshot", "target": "Safari page"},
            ],
        }
        (run_dir / "plan.json").write_text(json.dumps(plan_data, indent=2))
        (run_dir / "export.json").write_text(
            json.dumps(
                {
                    "testFilePath": str(test_path),
                    "code": test_path.read_text(),
                    "dependencies": ["webdriverio", "appium"],
                    "notes": ["Generated with Appium iOS Safari smoke workflow"],
                    "testType": "mobile",
                },
                indent=2,
            )
        )

        result = self._run_node_test(test_path=test_path, run_dir=run_dir)
        validation = {
            "status": "success" if result["passed"] else "failed",
            "mode": "appium_ios_safari_smoke",
            "testFile": str(test_path),
            "testType": "mobile",
            "targetUrl": target_url,
            "capabilitiesFile": str(capabilities_file),
            "message": "Mobile smoke passed" if result["passed"] else result["error_summary"],
            "output": result["output"][-5000:],
        }
        (run_dir / "validation.json").write_text(json.dumps(validation, indent=2))
        (run_dir / "status.txt").write_text("passed" if result["passed"] else "failed")

        return {
            "success": result["passed"],
            "stage": "completed" if result["passed"] else "mobile_execution",
            "test_path": str(test_path),
            "test_type": "mobile",
            "error": None if result["passed"] else result["error_summary"],
        }

    def render_safari_smoke_script(
        self,
        *,
        test_name: str,
        target_url: str,
        capabilities_path: Path,
        screenshot_name: str,
    ) -> str:
        parsed = urlparse(self.config.appium_server_url)
        protocol = parsed.scheme or "http"
        hostname = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if protocol == "https" else 4723)
        path = parsed.path if parsed.path and parsed.path != "/" else "/"
        screenshot_path = str((self.screenshots_dir / screenshot_name).absolute())
        safe_name = json.dumps(test_name)
        safe_url = json.dumps(target_url)

        return f"""const {{ remote }} = require('webdriverio');
const fs = require('fs');

const capabilities = JSON.parse(fs.readFileSync({json.dumps(str(capabilities_path))}, 'utf8'));

async function main() {{
  const driver = await remote({{
    protocol: process.env.APPIUM_PROTOCOL || {json.dumps(protocol)},
    hostname: process.env.APPIUM_HOST || {json.dumps(hostname)},
    port: Number(process.env.APPIUM_PORT || {port}),
    path: process.env.APPIUM_PATH || {json.dumps(path)},
    logLevel: process.env.APPIUM_LOG_LEVEL || 'info',
    capabilities,
  }});

  try {{
    console.log('Running mobile smoke: ' + {safe_name});
    await driver.url({safe_url});
    await driver.waitUntil(async () => {{
      const title = await driver.getTitle();
      return Boolean(title && title.trim().length > 0);
    }}, {{ timeout: 30000, timeoutMsg: 'Safari page title did not become available' }});
    const title = await driver.getTitle();
    console.log(`Safari title: ${{title}}`);
    await driver.saveScreenshot({json.dumps(screenshot_path)});
  }} finally {{
    await driver.deleteSession();
  }}
}}

main().catch((error) => {{
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
}});
"""

    def _run_node_test(self, *, test_path: Path, run_dir: Path) -> dict[str, Any]:
        env = os.environ.copy()
        env["APPIUM_SERVER_URL"] = self.config.appium_server_url
        try:
            result = subprocess.run(
                ["node", str(test_path)],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                env=env,
                timeout=600,
            )
            output = result.stdout + result.stderr
            (run_dir / "mobile_execution.log").write_text(output)
            return {
                "passed": result.returncode == 0,
                "exit_code": result.returncode,
                "output": output,
                "error_summary": self._summarize_output(output),
            }
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "exit_code": -1,
                "output": "Mobile Appium smoke timed out after 600 seconds",
                "error_summary": "Mobile Appium smoke timed out",
            }

    def _summarize_output(self, output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if not lines:
            return "Mobile Appium execution failed without output"
        for line in reversed(lines):
            if "error" in line.lower() or "failed" in line.lower() or "xcode" in line.lower():
                return line[:500]
        return lines[-1][:500]


def build_appium_mcp_config(config: MobileAppiumConfig, capabilities_file: str | None = None) -> dict[str, Any]:
    env = {
        "NO_UI": "true",
        "SCREENSHOTS_DIR": config.screenshots_dir,
        "REMOTE_SERVER_URL_ALLOW_REGEX": os.environ.get("APPIUM_REMOTE_SERVER_URL_ALLOW_REGEX", r"^https?://"),
        "APPIUM_MCP_ON_CLIENT_DISCONNECT": os.environ.get("APPIUM_MCP_ON_CLIENT_DISCONNECT", "delete_all"),
    }
    if config.appium_home:
        env["APPIUM_HOME"] = config.appium_home
    cap_file = capabilities_file or config.capabilities_file
    if cap_file:
        env["CAPABILITIES_CONFIG"] = cap_file
    return {
        "mcpServers": {
            "appium-mcp": {
                "command": "npx",
                "args": ["appium-mcp"],
                "env": env,
            }
        }
    }
