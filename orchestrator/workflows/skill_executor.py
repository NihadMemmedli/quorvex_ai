"""
Skill Executor Workflow - Execute Playwright scripts for complex automation.

This workflow provides integration between the native pipeline and the skill-based
execution system. It allows executing arbitrary Playwright scripts for scenarios
that require more control than MCP tools provide.

Use cases:
- Network interception and mocking
- Complex multi-step atomic flows
- Custom retry logic
- Multi-tab coordination
- Performance testing
"""

import asyncio
import json
import logging
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Add orchestrator to path
sys.path.append(str(Path(__file__).parent.parent.parent))

logger = logging.getLogger(__name__)

# Load environment
from orchestrator.load_env import setup_claude_env

setup_claude_env()

from orchestrator.utils.skill_runner import (
    get_skill_dir,
    run_skill_script,
    verify_skill_installation,
)


@dataclass
class SkillExecutionResult:
    """Result of skill-based test execution."""

    success: bool
    script_path: str | None = None
    output: Any = None
    error: str | None = None
    duration_ms: int = 0
    screenshots: list[str] = field(default_factory=list)
    attempts: int = 1


class SkillExecutor:
    """
    Execute Playwright scripts for complex browser automation.

    This class provides the workflow for skill-based execution, including:
    - Script generation from specs
    - Script execution with retry
    - Error handling and reporting
    """

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        self.skill_dir = get_skill_dir()
        self.scripts_dir = Path(tempfile.gettempdir()) / "playwright-skill-scripts"
        self.scripts_dir.mkdir(parents=True, exist_ok=True)

    async def execute_script(
        self,
        script_content: str,
        script_name: str | None = None,
        timeout_ms: int = 30000,
        headless: bool = True,
        env_vars: dict[str, str] | None = None,
    ) -> SkillExecutionResult:
        """
        Execute a Playwright script.

        Args:
            script_content: JavaScript code to execute
            script_name: Optional name for the script file
            timeout_ms: Execution timeout in milliseconds
            headless: Whether to run in headless mode
            env_vars: Additional environment variables

        Returns:
            SkillExecutionResult with execution details
        """
        # Verify installation
        if not verify_skill_installation():
            return SkillExecutionResult(
                success=False,
                error="Skill not installed. Run 'make setup-skills' to install.",
            )

        # Generate script filename
        if not script_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            script_name = f"skill_{timestamp}"

        script_path = self.scripts_dir / f"{script_name}.js"

        # Write script to file
        script_path.write_text(script_content)
        logger.info(f"   [skill] Script saved: {script_path}")

        # Execute
        logger.info("   [skill] Executing script...")

        result = run_skill_script(
            script_path=str(script_path),
            timeout_ms=timeout_ms,
            headless=headless,
            env_vars=env_vars,
        )

        return SkillExecutionResult(
            success=result.success,
            script_path=str(script_path),
            output=result.output,
            error=result.error.get("message") if result.error else None,
            duration_ms=result.duration,
            screenshots=result.screenshots,
        )

    async def execute_script_file(
        self,
        script_path: str,
        timeout_ms: int = 30000,
        headless: bool = True,
        env_vars: dict[str, str] | None = None,
    ) -> SkillExecutionResult:
        """
        Execute an existing Playwright script file.

        Args:
            script_path: Path to the JavaScript script
            timeout_ms: Execution timeout
            headless: Whether to run headless
            env_vars: Additional environment variables

        Returns:
            SkillExecutionResult
        """
        if not Path(script_path).exists():
            return SkillExecutionResult(
                success=False,
                error=f"Script not found: {script_path}",
            )

        logger.info(f"   [skill] Executing: {script_path}")

        result = run_skill_script(
            script_path=script_path,
            timeout_ms=timeout_ms,
            headless=headless,
            env_vars=env_vars,
        )

        return SkillExecutionResult(
            success=result.success,
            script_path=script_path,
            output=result.output,
            error=result.error.get("message") if result.error else None,
            duration_ms=result.duration,
            screenshots=result.screenshots,
        )

    async def execute_with_retry(
        self,
        script_content: str,
        max_attempts: int = 3,
        timeout_ms: int = 30000,
        headless: bool = True,
        env_vars: dict[str, str] | None = None,
    ) -> SkillExecutionResult:
        """
        Execute a script with retry on failure.

        Args:
            script_content: JavaScript code
            max_attempts: Maximum retry attempts
            timeout_ms: Timeout per attempt
            headless: Whether to run headless
            env_vars: Additional environment variables

        Returns:
            SkillExecutionResult with attempt count
        """
        for attempt in range(1, max_attempts + 1):
            logger.info(f"   [skill] Attempt {attempt}/{max_attempts}")

            result = await self.execute_script(
                script_content=script_content,
                timeout_ms=timeout_ms,
                headless=headless,
                env_vars=env_vars,
            )

            if result.success:
                result.attempts = attempt
                return result

            if attempt < max_attempts:
                # Wait before retry with exponential backoff
                wait_time = 2**attempt
                logger.info(f"   [skill] Failed, retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)

        result.attempts = max_attempts
        return result

    def generate_script_from_spec(
        self,
        spec_content: str,
        target_url: str,
    ) -> str:
        """
        Generate a basic script template from a spec.

        This creates a starting point that can be customized or used
        with the skill executor agent for more complex scenarios.

        Args:
            spec_content: Markdown spec content
            target_url: Target URL from the spec

        Returns:
            JavaScript code template
        """
        # Extract steps from spec (simple parsing)
        steps = []
        in_steps = False
        for line in spec_content.split("\n"):
            line = line.strip()
            if line.lower().startswith("## steps"):
                in_steps = True
                continue
            if in_steps and line.startswith("##"):
                in_steps = False
                continue
            if in_steps and line:
                # Remove step numbers
                if line[0].isdigit() and "." in line[:3]:
                    line = line.split(".", 1)[1].strip()
                if line:
                    steps.append(line)

        # Generate script
        script = f"""// Auto-generated from spec
// Target: {target_url}

await page.goto('{target_url}');
await page.waitForLoadState('networkidle');

// Steps from spec:
{chr(10).join(f"// - {step}" for step in steps)}

// TODO: Implement steps above
// Use helpers: safeClick, safeType, retry, waitForNetworkIdle

const title = await page.title();
console.log('Page loaded:', title);

return {{ success: true, title }};
"""
        return script


async def run_skill(
    script_path: str,
    timeout_ms: int = 30000,
    headless: bool = True,
    project_id: str = "default",
) -> SkillExecutionResult:
    """
    Convenience function to run a skill script.

    Args:
        script_path: Path to the script file
        timeout_ms: Execution timeout
        headless: Whether to run headless
        project_id: Project ID for isolation

    Returns:
        SkillExecutionResult
    """
    executor = SkillExecutor(project_id=project_id)
    return await executor.execute_script_file(
        script_path=script_path,
        timeout_ms=timeout_ms,
        headless=headless,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Execute Playwright skill scripts")
    parser.add_argument("script", nargs="?", help="Path to script file")
    parser.add_argument("--code", help="Inline JavaScript code to execute")
    parser.add_argument("--timeout", type=int, default=30000, help="Timeout in ms")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument("--verify", action="store_true", help="Verify installation")
    args = parser.parse_args()

    async def main():
        if args.verify:
            if verify_skill_installation():
                logger.info("Skill installation verified successfully")
                return 0
            else:
                logger.error("Skill installation incomplete")
                return 1

        executor = SkillExecutor()

        if args.code:
            result = await executor.execute_script(
                script_content=args.code,
                timeout_ms=args.timeout,
                headless=args.headless,
            )
        elif args.script:
            result = await executor.execute_script_file(
                script_path=args.script,
                timeout_ms=args.timeout,
                headless=args.headless,
            )
        else:
            parser.print_help()
            return 1

        logger.info(
            json.dumps(
                {
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                    "duration_ms": result.duration_ms,
                    "screenshots": result.screenshots,
                },
                indent=2,
            )
        )

        return 0 if result.success else 1

    from orchestrator.logging_config import setup_logging

    setup_logging()
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except Exception as e:
        if "cancel scope" in str(e).lower():
            pass
        else:
            raise
