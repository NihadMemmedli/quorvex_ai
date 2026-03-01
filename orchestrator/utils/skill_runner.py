"""
Skill Runner - Low-level utility for executing Node.js Playwright scripts.

This module provides the infrastructure to execute arbitrary Playwright scripts
via the skill runner (run.js). It handles:
- Environment variable injection
- Subprocess execution
- Timeout handling
- Output parsing
"""

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SkillResult:
    """Result of a skill script execution."""

    success: bool
    output: Any = None
    error: dict[str, str] | None = None
    duration: int = 0
    screenshots: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


def get_skill_dir() -> Path:
    """Get the skill directory path from environment or default."""
    skill_dir = os.environ.get("SKILL_DIR")
    if skill_dir:
        return Path(skill_dir)

    # Default: relative to project root
    project_root = Path(__file__).parent.parent.parent
    return project_root / ".claude" / "skills" / "playwright"


def get_runner_path() -> Path:
    """Get the path to the skill runner script."""
    return get_skill_dir() / "run.js"


def run_skill_script(
    script_path: str,
    timeout_ms: int = 30000,
    headless: bool = True,
    slow_mo: int = 0,
    env_vars: dict[str, str] | None = None,
) -> SkillResult:
    """
    Execute a Playwright skill script.

    Args:
        script_path: Path to the JavaScript script file
        timeout_ms: Execution timeout in milliseconds
        headless: Whether to run browser in headless mode
        slow_mo: Slow down actions by N milliseconds
        env_vars: Additional environment variables to pass

    Returns:
        SkillResult with execution details
    """
    runner_path = get_runner_path()

    if not runner_path.exists():
        return SkillResult(
            success=False,
            error={"message": f"Skill runner not found: {runner_path}", "name": "FileNotFoundError"},
            exit_code=1,
        )

    if not Path(script_path).exists():
        return SkillResult(
            success=False,
            error={"message": f"Script not found: {script_path}", "name": "FileNotFoundError"},
            exit_code=1,
        )

    # Build environment
    env = os.environ.copy()
    env["HEADLESS"] = "true" if headless else "false"
    env["SLOW_MO"] = str(slow_mo)
    env["SKILL_TIMEOUT"] = str(timeout_ms)

    # Add any additional environment variables
    if env_vars:
        env.update(env_vars)

    # Execute the script
    try:
        result = subprocess.run(
            ["node", str(runner_path), script_path],
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000 + 10,  # Add buffer for cleanup
            env=env,
            cwd=str(get_skill_dir()),
        )

        # Parse JSON output
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        # Find the JSON result in stdout (last JSON object)
        json_result = None
        for line in reversed(stdout.split("\n")):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    json_result = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue

        if json_result:
            return SkillResult(
                success=json_result.get("success", False),
                output=json_result.get("output"),
                error=json_result.get("error"),
                duration=json_result.get("duration", 0),
                screenshots=json_result.get("screenshots", []),
                stdout=stdout,
                stderr=stderr,
                exit_code=result.returncode,
            )
        else:
            # No JSON result found - return raw output
            return SkillResult(
                success=result.returncode == 0,
                output=stdout if stdout else None,
                error={"message": stderr, "name": "ExecutionError"} if stderr else None,
                stdout=stdout,
                stderr=stderr,
                exit_code=result.returncode,
            )

    except subprocess.TimeoutExpired:
        return SkillResult(
            success=False,
            error={"message": f"Script execution timed out after {timeout_ms}ms", "name": "TimeoutError"},
            exit_code=124,
        )
    except Exception as e:
        return SkillResult(
            success=False,
            error={"message": str(e), "name": type(e).__name__},
            exit_code=1,
        )


def run_skill_code(
    code: str,
    timeout_ms: int = 30000,
    headless: bool = True,
    slow_mo: int = 0,
    env_vars: dict[str, str] | None = None,
) -> SkillResult:
    """
    Execute inline Playwright code.

    Args:
        code: JavaScript code to execute
        timeout_ms: Execution timeout in milliseconds
        headless: Whether to run browser in headless mode
        slow_mo: Slow down actions by N milliseconds
        env_vars: Additional environment variables

    Returns:
        SkillResult with execution details
    """
    # Write code to temporary file
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".js",
        prefix="playwright-skill-",
        delete=False,
    ) as f:
        f.write(code)
        script_path = f.name

    try:
        return run_skill_script(
            script_path=script_path,
            timeout_ms=timeout_ms,
            headless=headless,
            slow_mo=slow_mo,
            env_vars=env_vars,
        )
    finally:
        # Cleanup temp file
        try:
            os.unlink(script_path)
        except OSError:
            pass


def verify_skill_installation() -> bool:
    """
    Verify that the skill is properly installed.

    Returns:
        True if skill is ready to use
    """
    skill_dir = get_skill_dir()
    runner_path = get_runner_path()
    helpers_path = skill_dir / "lib" / "helpers.js"
    package_json = skill_dir / "package.json"
    node_modules = skill_dir / "node_modules"

    checks = {
        "Skill directory exists": skill_dir.exists(),
        "Runner script exists": runner_path.exists(),
        "Helpers exist": helpers_path.exists(),
        "package.json exists": package_json.exists(),
        "node_modules installed": node_modules.exists(),
    }

    all_passed = all(checks.values())

    if not all_passed:
        print("Skill installation check:")
        for check, passed in checks.items():
            status = "OK" if passed else "MISSING"
            print(f"  [{status}] {check}")

    return all_passed
