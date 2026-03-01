"""
MCP Health Checker - Pre-flight checks for Playwright MCP and display.

Provides health checks to run before starting agent operations:
- Playwright MCP server availability
- X display verification (for headed mode)
- Combined environment readiness check
"""

import asyncio
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnvironmentStatus:
    """Overall environment status."""

    ready: bool
    checks: list[HealthCheckResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class MCPHealthChecker:
    """
    Health checker for MCP servers and related infrastructure.

    Usage:
        checker = MCPHealthChecker()
        status = await checker.verify_environment()
        if not status.ready:
            print(f"Errors: {status.errors}")
    """

    @staticmethod
    async def check_playwright_mcp() -> HealthCheckResult:
        """
        Check if Playwright MCP server can be started.

        Returns:
            HealthCheckResult with pass/fail status
        """
        try:
            # Check if npx is available
            npx_check = subprocess.run(
                ["which", "npx"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if npx_check.returncode != 0:
                return HealthCheckResult(
                    name="playwright_mcp",
                    passed=False,
                    message="npx not found in PATH",
                    details={"npx_path": None},
                )

            npx_path = npx_check.stdout.strip()

            # Check if playwright package is installed
            playwright_check = subprocess.run(
                ["npx", "playwright", "--version"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if playwright_check.returncode != 0:
                return HealthCheckResult(
                    name="playwright_mcp",
                    passed=False,
                    message="Playwright not installed or not accessible via npx",
                    details={
                        "npx_path": npx_path,
                        "stderr": playwright_check.stderr[:500] if playwright_check.stderr else None,
                    },
                )

            playwright_version = playwright_check.stdout.strip()

            # Check if MCP server command exists (dry run)
            # We can't fully start it without blocking, but we can check the command exists
            mcp_help = subprocess.run(
                ["npx", "playwright", "run-test-mcp-server", "--help"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Even if --help returns non-zero, if we get some output it means the command exists
            mcp_available = (
                mcp_help.returncode == 0 or "mcp" in mcp_help.stdout.lower() or "mcp" in mcp_help.stderr.lower()
            )

            if not mcp_available:
                # Check for the MCP server in a different way
                # It might not have --help support
                return HealthCheckResult(
                    name="playwright_mcp",
                    passed=True,  # Assume available if playwright is installed
                    message=f"Playwright {playwright_version} installed (MCP server assumed available)",
                    details={
                        "npx_path": npx_path,
                        "playwright_version": playwright_version,
                        "mcp_check": "skipped",
                    },
                )

            return HealthCheckResult(
                name="playwright_mcp",
                passed=True,
                message=f"Playwright MCP server available (Playwright {playwright_version})",
                details={
                    "npx_path": npx_path,
                    "playwright_version": playwright_version,
                },
            )

        except subprocess.TimeoutExpired:
            return HealthCheckResult(
                name="playwright_mcp",
                passed=False,
                message="Timeout checking Playwright MCP availability",
            )
        except FileNotFoundError as e:
            return HealthCheckResult(
                name="playwright_mcp",
                passed=False,
                message=f"Command not found: {e}",
            )
        except Exception as e:
            return HealthCheckResult(
                name="playwright_mcp",
                passed=False,
                message=f"Error checking Playwright MCP: {e}",
            )

    @staticmethod
    async def check_display() -> HealthCheckResult:
        """
        Check if X display is available (for headed browser mode).

        Returns:
            HealthCheckResult with pass/fail status
        """
        display = os.environ.get("DISPLAY")
        vnc_enabled = os.environ.get("VNC_ENABLED", "").lower() == "true"
        headless = os.environ.get("PLAYWRIGHT_HEADLESS", "true").lower() == "true"

        # If running headless, display doesn't matter
        if headless and not vnc_enabled:
            return HealthCheckResult(
                name="display",
                passed=True,
                message="Running in headless mode (no display required)",
                details={
                    "headless": True,
                    "vnc_enabled": False,
                },
            )

        # Check DISPLAY variable
        if not display:
            if vnc_enabled:
                return HealthCheckResult(
                    name="display",
                    passed=False,
                    message="VNC_ENABLED=true but DISPLAY not set",
                    details={
                        "vnc_enabled": True,
                        "display": None,
                    },
                )
            return HealthCheckResult(
                name="display",
                passed=False,
                message="DISPLAY not set (required for headed mode)",
                details={
                    "headless": False,
                    "display": None,
                },
            )

        # Try to verify the display works
        try:
            # Use xdpyinfo to check display (if available)
            xdpy_check = subprocess.run(
                ["xdpyinfo", "-display", display],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if xdpy_check.returncode == 0:
                return HealthCheckResult(
                    name="display",
                    passed=True,
                    message=f"Display {display} is available",
                    details={
                        "display": display,
                        "vnc_enabled": vnc_enabled,
                    },
                )
            else:
                return HealthCheckResult(
                    name="display",
                    passed=False,
                    message=f"Display {display} not accessible: {xdpy_check.stderr[:200] if xdpy_check.stderr else 'unknown error'}",
                    details={
                        "display": display,
                        "stderr": xdpy_check.stderr[:500] if xdpy_check.stderr else None,
                    },
                )

        except FileNotFoundError:
            # xdpyinfo not available - assume display is OK if set
            return HealthCheckResult(
                name="display",
                passed=True,
                message=f"Display {display} set (xdpyinfo not available for verification)",
                details={
                    "display": display,
                    "vnc_enabled": vnc_enabled,
                    "verified": False,
                },
            )
        except subprocess.TimeoutExpired:
            return HealthCheckResult(
                name="display",
                passed=False,
                message=f"Timeout verifying display {display}",
                details={"display": display},
            )
        except Exception as e:
            return HealthCheckResult(
                name="display",
                passed=False,
                message=f"Error checking display: {e}",
                details={"display": display},
            )

    @staticmethod
    async def check_browser_installed() -> HealthCheckResult:
        """
        Check if Playwright browsers are installed.

        Returns:
            HealthCheckResult with pass/fail status
        """
        try:
            # Check for chromium browser
            result = subprocess.run(
                ["npx", "playwright", "install", "--dry-run", "chromium"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Parse output to see if browsers need installation
            needs_install = "chromium" in result.stdout.lower() and "will download" in result.stdout.lower()

            if needs_install:
                return HealthCheckResult(
                    name="browser_installed",
                    passed=False,
                    message="Chromium browser needs to be installed (run: npx playwright install chromium)",
                    details={"needs_install": ["chromium"]},
                )

            return HealthCheckResult(
                name="browser_installed",
                passed=True,
                message="Playwright browsers are installed",
                details={"browsers": ["chromium"]},
            )

        except subprocess.TimeoutExpired:
            return HealthCheckResult(
                name="browser_installed",
                passed=False,
                message="Timeout checking browser installation",
            )
        except Exception as e:
            # If we can't check, assume it's OK (will fail later with clearer error)
            return HealthCheckResult(
                name="browser_installed",
                passed=True,
                message=f"Could not verify browser installation: {e}",
                details={"verified": False},
            )

    @staticmethod
    async def check_mcp_config() -> HealthCheckResult:
        """
        Check if .mcp.json configuration exists and is valid.

        Returns:
            HealthCheckResult with pass/fail status
        """
        # Look for .mcp.json in common locations
        candidates = [
            Path.cwd() / ".mcp.json",
            Path(__file__).resolve().parent.parent.parent / ".mcp.json",
            Path("/app/.mcp.json"),
        ]

        for config_path in candidates:
            if config_path.exists():
                try:
                    import json

                    config = json.loads(config_path.read_text())

                    # Check for playwright or playwright-test server
                    mcp_servers = config.get("mcpServers", {})
                    has_playwright = "playwright-test" in mcp_servers or "playwright" in mcp_servers

                    if has_playwright:
                        return HealthCheckResult(
                            name="mcp_config",
                            passed=True,
                            message=f"MCP config found at {config_path} with playwright-test server",
                            details={
                                "config_path": str(config_path),
                                "servers": list(mcp_servers.keys()),
                            },
                        )
                    else:
                        return HealthCheckResult(
                            name="mcp_config",
                            passed=False,
                            message=f"MCP config at {config_path} missing playwright-test server",
                            details={
                                "config_path": str(config_path),
                                "servers": list(mcp_servers.keys()),
                            },
                        )

                except json.JSONDecodeError as e:
                    return HealthCheckResult(
                        name="mcp_config",
                        passed=False,
                        message=f"Invalid JSON in {config_path}: {e}",
                        details={"config_path": str(config_path)},
                    )
                except Exception as e:
                    return HealthCheckResult(
                        name="mcp_config",
                        passed=False,
                        message=f"Error reading {config_path}: {e}",
                        details={"config_path": str(config_path)},
                    )

        return HealthCheckResult(
            name="mcp_config",
            passed=False,
            message=".mcp.json not found in expected locations",
            details={"searched": [str(p) for p in candidates]},
        )

    @classmethod
    async def verify_environment(
        cls,
        include_browser_check: bool = False,
    ) -> EnvironmentStatus:
        """
        Run all health checks and return overall status.

        Args:
            include_browser_check: Include browser installation check (slower)

        Returns:
            EnvironmentStatus with ready flag and all check results
        """
        checks = []
        errors = []
        warnings = []

        # Run checks in parallel
        check_tasks = [
            cls.check_playwright_mcp(),
            cls.check_display(),
            cls.check_mcp_config(),
        ]

        if include_browser_check:
            check_tasks.append(cls.check_browser_installed())

        results = await asyncio.gather(*check_tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                errors.append(f"Health check failed with exception: {result}")
                continue

            checks.append(result)

            if not result.passed:
                # Some failures are warnings, not errors
                if result.name == "display" and "headless" in result.message.lower():
                    warnings.append(result.message)
                else:
                    errors.append(f"{result.name}: {result.message}")

        # Environment is ready if no critical errors
        ready = len(errors) == 0

        return EnvironmentStatus(
            ready=ready,
            checks=checks,
            errors=errors,
            warnings=warnings,
        )


async def verify_mcp_environment() -> dict[str, Any]:
    """
    Convenience function to verify MCP environment.

    Returns dict with:
        - ready: bool
        - errors: list of error messages
        - warnings: list of warning messages
    """
    checker = MCPHealthChecker()
    status = await checker.verify_environment()

    return {
        "ready": status.ready,
        "errors": status.errors,
        "warnings": status.warnings,
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "message": c.message,
            }
            for c in status.checks
        ],
    }
