"""
Full Native Pipeline - Unified pipeline using browser at every stage.

This is the default pipeline that uses:
- Native Planner (browser exploration for planning)
- Native Generator (live browser code generation)
- Native Healer or Hybrid Healing (test_run + diagnostic tools based healing)
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Add orchestrator to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load Claude credentials
from load_env import setup_claude_env

setup_claude_env()

# Use run-specific config directory if set (for parallel execution isolation)
# This must happen BEFORE importing workflow classes that use Agent SDK
config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
if config_dir:
    os.chdir(config_dir)

from utils.browser_cleanup import cleanup_orphaned_browsers
from utils.progress_reporter import extract_run_id_from_path, init_progress_reporter, report_progress
from utils.spec_detector import SpecDetector, SpecType
from workflows.native_api_generator import NativeApiGenerator
from workflows.native_api_healer import NativeApiHealer
from workflows.native_generator import NativeGenerator
from workflows.native_healer import HealerTimeoutError, NativeHealer
from workflows.native_planner import NativePlanner
from workflows.ralph_validator import RalphValidator


@dataclass
class TestResult:
    """Result of running a test"""

    passed: bool
    exit_code: int
    output: str
    error_summary: str = ""


class FullNativePipeline:
    """
    Unified native pipeline using browser at every stage.

    Always uses:
    - Native Planner (browser exploration)
    - Native Generator (live browser code generation)

    Healing varies based on mode:
    - Default: Native Healer (3 attempts using test_run and diagnostic tools)
    - Hybrid: Native Healer (3) + Ralph (up to 17 more)
    """

    def __init__(self, project_id: str = "default"):
        self.project_id = project_id
        self._load_project_credentials()
        self.native_planner = NativePlanner(project_id=project_id)
        self.native_generator = NativeGenerator()
        self.native_healer = NativeHealer()
        self.api_generator = NativeApiGenerator()
        self.api_healer = NativeApiHealer()

    def _load_project_credentials(self):
        """Load project credentials into os.environ.

        Credentials stored in the project's settings are decrypted and loaded
        into the environment so that {{PLACEHOLDER}} substitution in specs
        and generated code using process.env.* will work correctly.

        Project credentials override .env values.
        """
        if not self.project_id:
            logger.info("[Credentials] No project_id, skipping credential loading")
            return

        logger.info(f"[Credentials] Loading credentials for project: {self.project_id}")

        try:
            # Import here to avoid circular imports and optional dependency
            # Use full path from orchestrator package
            from sqlmodel import Session

            from orchestrator.api.credentials import get_merged_credentials
            from orchestrator.api.db import engine

            with Session(engine) as session:
                creds = get_merged_credentials(self.project_id, session)

            if creds:
                # Load credentials into environment
                for key, value in creds.items():
                    os.environ[key] = value
                logger.info(f"[Credentials] Loaded {len(creds)} credential(s): {list(creds.keys())}")
            else:
                logger.info("[Credentials] No credentials found for project")

        except ImportError as e:
            # Running without API/database (e.g., CLI-only mode)
            logger.info(f"[Credentials] Import error (CLI-only mode): {e}")
        except Exception as e:
            # Log but don't fail - credentials might not be needed
            logger.error(f"[Credentials] Error loading credentials: {e}")

    async def run(
        self,
        spec_path: str,
        run_dir: Path,
        browser: str = "chromium",
        hybrid_healing: bool = False,
        max_iterations: int = 20,
        skip_planning: bool = False,
        existing_test_path: str | None = None,
        force_api: bool = False,
    ) -> dict:
        """
        Run the full native pipeline.

        Args:
            spec_path: Path to the markdown spec file
            run_dir: Directory to store run artifacts
            browser: Browser to use (chromium, firefox, webkit)
            hybrid_healing: If True, use Native + Ralph healing
            max_iterations: Max iterations for hybrid mode
            skip_planning: If True, skip native planning (use existing spec as-is)
            existing_test_path: If provided, skip planning/generation and heal this test directly

        Returns:
            Dict with pipeline results
        """
        spec_file = Path(spec_path)
        spec_content = spec_file.read_text()

        # Extract URL from spec (resolves @include directives first)
        target_url = self._extract_url(spec_content, spec_path)
        if not target_url:
            logger.error("Spec must contain a target URL (e.g., 'Navigate to https://...')")
            logger.error("Note: @include templates are resolved when searching for URLs")
            # Write status file so the API wrapper can update DB
            (run_dir / "status.txt").write_text("error")
            return {
                "success": False,
                "error": "No target URL found in spec (checked includes too)",
                "stage": "url_extraction",
            }

        # Resolve includes for the full spec content
        resolved_spec_content = self._resolve_includes(spec_content, spec_path)

        logger.info("=" * 80)
        logger.info("FULL NATIVE PIPELINE")
        logger.info("=" * 80)
        logger.info(f"   Spec: {spec_file.name}")
        logger.info(f"   Target URL: {target_url}")
        logger.info(f"   Browser: {browser}")
        logger.info(f"   Healing Mode: {'Hybrid (Native -> Ralph)' if hybrid_healing else 'Native Only'}")

        # Initialize progress reporter for real-time UI updates
        run_id = extract_run_id_from_path(run_dir)
        if run_id:
            init_progress_reporter(run_id)

        # Save both original and resolved spec to run dir
        (run_dir / "spec.md").write_text(spec_content)
        (run_dir / "spec_resolved.md").write_text(resolved_spec_content)

        # Extract credentials from resolved spec (so we find credentials in templates too)
        credentials = self._extract_credentials(resolved_spec_content)
        login_url = self._extract_login_url(resolved_spec_content, target_url)

        # --- DETECT SPEC TYPE ---
        spec_type = SpecType.STANDARD
        try:
            spec_type = SpecDetector.detect_spec_type(spec_file)
        except Exception:
            pass
        if force_api:
            spec_type = SpecType.API

        # --- API TEST PIPELINE ---
        if spec_type == SpecType.API:
            return await self._run_api_pipeline(
                spec_path=spec_path,
                spec_content=resolved_spec_content,
                run_dir=run_dir,
                browser=browser,
                target_url=target_url,
                hybrid_healing=hybrid_healing,
                max_iterations=max_iterations,
            )

        # --- MIXED TEST PIPELINE ---
        if spec_type == SpecType.MIXED:
            logger.info("Mixed browser + API spec detected")
            logger.info("   Browser steps will use page fixture, API steps will use request fixture")
            # Mixed specs go through the normal browser pipeline with a flag
            # The generator handles [API] prefixed steps specially

        # --- HEALING-ONLY MODE ---
        # When existing_test_path is provided, skip Stages 1-2 and go directly to healing
        if existing_test_path:
            try:
                logger.info("Healing existing test (skipping planning/generation)...")
                report_progress("testing", "Running existing test...")

                test_path = Path(existing_test_path)
                if not test_path.exists():
                    error_msg = f"Existing test file not found: {existing_test_path}"
                    (run_dir / "status.txt").write_text("error")
                    self._write_pipeline_error(run_dir, error_msg, "healing_setup")
                    return {"success": False, "error": error_msg, "stage": "healing_setup"}

                # Create export.json for dashboard
                export_data = {
                    "testFilePath": str(test_path),
                    "code": test_path.read_text(),
                    "dependencies": ["@playwright/test"],
                    "notes": ["Healing existing test (skipped planning/generation)"],
                }
                (run_dir / "export.json").write_text(json.dumps(export_data, indent=2))

                # Stage 3: Run existing test
                logger.info("Stage 3: Running existing test...")

                result = self._run_test(str(test_path), str(run_dir), browser)

                if result.passed:
                    logger.info("Test PASSED!")
                    (run_dir / "status.txt").write_text("passed")
                    return {"success": True, "test_path": str(test_path), "attempts": 0, "stage": "completed"}

                logger.error(f"Test FAILED: {result.error_summary}")

                # Stage 4: Healing
                if hybrid_healing:
                    return await self._hybrid_healing(
                        test_path=test_path,
                        run_dir=run_dir,
                        browser=browser,
                        max_iterations=max_iterations,
                        spec_path=spec_path,
                    )
                else:
                    return await self._native_healing(
                        test_path=test_path, run_dir=run_dir, browser=browser, result=result
                    )
            except Exception as e:
                error_msg = f"Healing-only pipeline crashed: {e}"
                logger.error(error_msg, exc_info=True)
                try:
                    (run_dir / "status.txt").write_text("error")
                    self._write_pipeline_error(run_dir, error_msg, "healing")
                except Exception:
                    pass
                return {"success": False, "error": error_msg, "stage": "healing"}

        try:
            # Mark pipeline as running
            (run_dir / "status.txt").write_text("running")

            # Stage 1: Native Planning with browser exploration
            if not skip_planning:
                logger.info("Stage 1: Native Planning (browser exploration)...")
                report_progress("planning", "Exploring application structure...")

                # Use resolved spec for planning so planner sees included templates
                resolved_spec_path = run_dir / "spec_resolved.md"
                plan_path = await self._run_native_planner(
                    spec_path=str(resolved_spec_path),
                    run_dir=run_dir,
                    target_url=target_url,
                    login_url=login_url,
                    credentials=credentials,
                )

                if plan_path and plan_path.exists():
                    logger.info(f"Plan created: {plan_path}")
                else:
                    logger.warning("Planner didn't create a structured plan, continuing with original spec")

                # Safety-net: clean up any orphaned browsers from planner stage
                cleanup_orphaned_browsers()

            # Stage 2: Native Generation with live browser
            logger.info("Stage 2: Native Generation (live browser)...")
            report_progress("generating", "Creating test code with live browser...")

            # Use resolved spec for generation so all included content is visible
            # But keep the original spec name for the output file
            resolved_spec_path = run_dir / "spec_resolved.md"
            original_spec_name = spec_file.stem  # e.g., "12-create-trip-with-minimal-information"
            test_path = await self._run_native_generator(
                spec_path=str(resolved_spec_path), target_url=target_url, output_name=original_spec_name
            )

            if not test_path or not test_path.exists():
                error_msg = "Native generator failed to create test file"
                (run_dir / "status.txt").write_text("error")
                self._write_pipeline_error(run_dir, error_msg, "generation")
                return {"success": False, "error": error_msg, "stage": "generation"}

            # Validate generated test content
            try:
                gen_content = test_path.read_text()
                if len(gen_content.strip()) < 100:
                    error_msg = (
                        f"Generated test file is too small ({len(gen_content)} chars) - likely incomplete generation"
                    )
                    logger.error(error_msg)
                    (run_dir / "status.txt").write_text("error")
                    self._write_pipeline_error(run_dir, error_msg, "generation_validation")
                    return {"success": False, "error": error_msg, "stage": "generation_validation"}
                if "test(" not in gen_content and "test.describe" not in gen_content:
                    logger.warning(
                        "Generated test file may be invalid - missing test() or test.describe markers. "
                        "Proceeding to execution (healer may fix it)."
                    )
            except Exception as val_err:
                logger.warning(f"Could not validate generated test: {val_err}")

            logger.info(f"Test generated: {test_path}")

            # Create export.json for dashboard
            export_data = {
                "testFilePath": str(test_path),
                "code": test_path.read_text(),
                "dependencies": ["@playwright/test"],
                "notes": ["Generated with Native Generator"],
            }
            (run_dir / "export.json").write_text(json.dumps(export_data, indent=2))

            # Safety-net: clean up any orphaned browsers from generator stage
            cleanup_orphaned_browsers()

            # Stage 3: Run test
            logger.info("Stage 3: Running test...")
            report_progress("testing", "Running generated test...")

            result = self._run_test(str(test_path), str(run_dir), browser)

            if result.passed:
                logger.info("Test PASSED on first run!")
                (run_dir / "status.txt").write_text("passed")
                return {"success": True, "test_path": str(test_path), "attempts": 0, "stage": "completed"}

            logger.error(f"Test FAILED: {result.error_summary}")

            # Stage 4: Healing
            if hybrid_healing:
                healing_result = await self._hybrid_healing(
                    test_path=test_path,
                    run_dir=run_dir,
                    browser=browser,
                    max_iterations=max_iterations,
                    spec_path=spec_path,
                )
            else:
                healing_result = await self._native_healing(
                    test_path=test_path, run_dir=run_dir, browser=browser, result=result
                )

            # Safety-net: clean up any orphaned browsers from healing stage
            cleanup_orphaned_browsers()
            return healing_result

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            # Emergency cleanup on pipeline failure
            cleanup_orphaned_browsers()
            (run_dir / "status.txt").write_text("error")
            self._write_pipeline_error(run_dir, str(e), "exception")
            return {"success": False, "error": str(e), "stage": "exception"}

    async def _run_native_planner(
        self,
        spec_path: str,
        run_dir: Path,
        target_url: str,
        login_url: str | None = None,
        credentials: dict[str, str] | None = None,
    ) -> Path | None:
        """Run native planner to explore the app and enhance the spec."""

        spec_file = Path(spec_path)
        spec_content = spec_file.read_text()

        # Extract test name from spec
        test_name = self._extract_test_name(spec_content)

        # Build flow context from spec
        flow_context = f"""## Test: {test_name}

### Spec Content
{spec_content}

### Target URL
{target_url}
"""

        try:
            plan_path = await self.native_planner.generate_spec_from_flow_context(
                flow_title=test_name,
                flow_context=flow_context,
                target_url=target_url,
                login_url=login_url,
                credentials=credentials,
                output_dir=run_dir,
            )

            # Copy the enhanced plan to run_dir/plan.json if it exists
            if plan_path and plan_path.exists():
                # Create a plan.json for the dashboard
                plan_data = {
                    "testName": test_name,
                    "specFileName": spec_file.name,
                    "specFilePath": str(spec_file.absolute()),
                    "targetUrl": target_url,
                    "generatedPlanPath": str(plan_path),
                    "steps": [],  # Will be populated from the generated plan
                }
                (run_dir / "plan.json").write_text(json.dumps(plan_data, indent=2))

            return plan_path

        except Exception as e:
            logger.warning(f"Native planner error: {e}")
            return None

    async def _run_native_generator(
        self, spec_path: str, target_url: str, output_name: str | None = None
    ) -> Path | None:
        """Run native generator to create test code.

        Args:
            spec_path: Path to the spec file (can be resolved spec with includes expanded)
            target_url: URL of the application to test
            output_name: Override for output test file name (without extension)
        """
        try:
            test_path = await self.native_generator.generate_test(
                spec_path=spec_path, target_url=target_url, output_name=output_name
            )
            return test_path
        except Exception as e:
            logger.error(f"Native generator error: {e}")
            return None

    async def _native_healing(self, test_path: Path, run_dir: Path, browser: str, result: TestResult) -> dict:
        """Native healing: up to 3 attempts with test_run and diagnostic tools."""
        logger.info("Stage 4: Native Healing (up to 3 attempts)...")
        report_progress("healing", "Starting native healing...", healing_attempt=1)

        max_attempts = 3
        error_log = result.output

        for attempt in range(1, max_attempts + 1):
            logger.info(f"Healing attempt {attempt}/{max_attempts}...")
            report_progress("healing", f"Native healing attempt {attempt}/{max_attempts}...", healing_attempt=attempt)

            try:
                fixed_code = await self.native_healer.heal_test(
                    str(test_path),
                    error_log,
                    timeout_seconds=int(os.environ.get("HEALER_ATTEMPT_TIMEOUT_SECONDS", "600")),
                )

                if fixed_code:
                    logger.info("Re-running healed test...")
                    result = self._run_test(str(test_path), str(run_dir), browser)

                    if result.passed:
                        logger.info(f"Healed Test PASSED (after {attempt} attempt(s))!")
                        (run_dir / "status.txt").write_text("passed")

                        validation_result = {
                            "status": "success",
                            "mode": "native_healer",
                            "iterations": attempt,
                            "testFile": str(test_path),
                            "browser": browser,
                            "message": f"Test healed after {attempt} attempts",
                        }
                        (run_dir / "validation.json").write_text(json.dumps(validation_result, indent=2))

                        return {"success": True, "test_path": str(test_path), "attempts": attempt, "stage": "healed"}
                    else:
                        error_log = result.output
                        if attempt < max_attempts:
                            logger.warning("Test still failing, trying again...")
                else:
                    logger.warning("Healer returned no code")

            except HealerTimeoutError:
                logger.error(f"Healer timed out on attempt {attempt}/{max_attempts} — stopping retries")
                break

            except Exception as e:
                logger.warning(f"Healing error: {e}")

        logger.error(f"Native healing exhausted after {max_attempts} attempts")
        (run_dir / "status.txt").write_text("failed")

        validation_result = {
            "status": "failed",
            "mode": "native_healer",
            "iterations": max_attempts,
            "testFile": str(test_path),
            "browser": browser,
            "message": f"Failed after {max_attempts} native healing attempts",
        }
        (run_dir / "validation.json").write_text(json.dumps(validation_result, indent=2))

        return {"success": False, "test_path": str(test_path), "attempts": max_attempts, "stage": "healing_exhausted"}

    async def _run_api_pipeline(
        self,
        spec_path: str,
        spec_content: str,
        run_dir: Path,
        browser: str,
        target_url: str | None,
        hybrid_healing: bool = False,
        max_iterations: int = 20,
    ) -> dict:
        """
        Run the API-specific pipeline.

        Skips browser planning entirely - API tests generate code directly from spec.
        Uses lighter healing loop without browser MCP tools.
        """
        spec_file = Path(spec_path)

        logger.info("=" * 80)
        logger.info("API TEST PIPELINE")
        logger.info("=" * 80)
        logger.info(f"   Spec: {spec_file.name}")
        logger.info(f"   Target URL: {target_url}")
        logger.info("   Mode: API (no browser needed)")

        # Initialize progress reporter
        run_id = extract_run_id_from_path(run_dir)
        if run_id:
            init_progress_reporter(run_id)

        try:
            # Stage 1: API Generation (skip planning - not needed for API tests)
            logger.info("Stage 1: API Test Generation (direct from spec)...")
            report_progress("generating", "Creating API test code from spec...")

            original_spec_name = spec_file.stem
            test_path = await self.api_generator.generate_test(
                spec_path=spec_path, target_url=target_url, output_name=original_spec_name
            )

            if not test_path or not test_path.exists():
                error_msg = "API generator failed to create test file"
                (run_dir / "status.txt").write_text("error")
                self._write_pipeline_error(run_dir, error_msg, "api_generation")
                return {"success": False, "error": error_msg, "stage": "api_generation", "test_type": "api"}

            logger.info(f"API test generated: {test_path}")

            # Create export.json for dashboard
            export_data = {
                "testFilePath": str(test_path),
                "code": test_path.read_text(),
                "dependencies": ["@playwright/test"],
                "notes": ["Generated with API Test Generator"],
                "testType": "api",
            }
            (run_dir / "export.json").write_text(json.dumps(export_data, indent=2))

            # Stage 2: Run test
            logger.info("Stage 2: Running API test...")
            report_progress("testing", "Running API test...")

            result = self._run_test(str(test_path), str(run_dir), browser)

            if result.passed:
                logger.info("API test PASSED on first run!")
                (run_dir / "status.txt").write_text("passed")
                return {
                    "success": True,
                    "test_path": str(test_path),
                    "attempts": 0,
                    "stage": "completed",
                    "test_type": "api",
                }

            logger.error(f"API test FAILED: {result.error_summary}")

            # Stage 3: API Healing
            logger.info("Stage 3: API Test Healing (up to 3 attempts)...")
            report_progress("healing", "Starting API test healing...", healing_attempt=1)

            max_heal_attempts = 3
            error_log = result.output

            for attempt in range(1, max_heal_attempts + 1):
                logger.info(f"Healing attempt {attempt}/{max_heal_attempts}...")
                report_progress(
                    "healing", f"API healing attempt {attempt}/{max_heal_attempts}...", healing_attempt=attempt
                )

                try:
                    fixed_code = await self.api_healer.heal_test(str(test_path), error_log, spec_content)

                    if fixed_code:
                        logger.info("Re-running healed API test...")
                        result = self._run_test(str(test_path), str(run_dir), browser)

                        if result.passed:
                            logger.info(f"Healed API test PASSED (after {attempt} attempt(s))!")
                            (run_dir / "status.txt").write_text("passed")

                            validation_result = {
                                "status": "success",
                                "mode": "api_healer",
                                "iterations": attempt,
                                "testFile": str(test_path),
                                "browser": browser,
                                "testType": "api",
                                "message": f"API test healed after {attempt} attempts",
                            }
                            (run_dir / "validation.json").write_text(json.dumps(validation_result, indent=2))

                            return {
                                "success": True,
                                "test_path": str(test_path),
                                "attempts": attempt,
                                "stage": "healed",
                                "test_type": "api",
                            }
                        else:
                            error_log = result.output
                            if attempt < max_heal_attempts:
                                logger.warning("API test still failing, trying again...")
                    else:
                        logger.warning("Healer returned no code")

                except Exception as e:
                    logger.warning(f"Healing error: {e}")

            logger.error(f"API healing exhausted after {max_heal_attempts} attempts")
            (run_dir / "status.txt").write_text("failed")

            validation_result = {
                "status": "failed",
                "mode": "api_healer",
                "iterations": max_heal_attempts,
                "testFile": str(test_path),
                "browser": browser,
                "testType": "api",
                "message": f"API test failed after {max_heal_attempts} healing attempts",
            }
            (run_dir / "validation.json").write_text(json.dumps(validation_result, indent=2))

            return {
                "success": False,
                "test_path": str(test_path),
                "attempts": max_heal_attempts,
                "stage": "healing_exhausted",
                "test_type": "api",
            }

        except Exception as e:
            logger.error(f"API pipeline error: {e}", exc_info=True)
            (run_dir / "status.txt").write_text("error")
            self._write_pipeline_error(run_dir, str(e), "exception")
            return {"success": False, "error": str(e), "stage": "exception", "test_type": "api"}

    async def _hybrid_healing(
        self, test_path: Path, run_dir: Path, browser: str, max_iterations: int, spec_path: str
    ) -> dict:
        """Hybrid healing: Native (3) + Ralph (up to 17 more)."""
        logger.info("Stage 4: Hybrid Healing...")
        logger.info("   Phase 1: Native Healing (1-3 iterations)")
        logger.info(f"   Phase 2: Ralph Loop (4-{max_iterations} iterations)")
        report_progress("healing", "Starting hybrid healing (Native + Ralph)...", healing_attempt=1)

        # Use RalphValidator in hybrid mode which handles both phases
        validator = RalphValidator(max_iterations=max_iterations, hybrid_mode=True, native_phase_iterations=3)

        plan_file = run_dir / "plan.json"

        result = await validator.validate_and_fix(
            test_file=str(test_path),
            output_dir=str(run_dir),
            browser=browser,
            spec_file=spec_path,
            plan_file=str(plan_file) if plan_file.exists() else None,
        )

        if result.get("status") == "success":
            (run_dir / "status.txt").write_text("passed")
            return {
                "success": True,
                "test_path": str(test_path),
                "attempts": result.get("iterations", 0),
                "stage": "healed",
                "phase_succeeded": result.get("phaseSucceeded", "unknown"),
            }
        else:
            (run_dir / "status.txt").write_text("failed")
            return {
                "success": False,
                "test_path": str(test_path),
                "attempts": result.get("iterations", max_iterations),
                "stage": "healing_exhausted",
            }

    def _run_test(self, test_file: str, output_dir: str, browser: str) -> TestResult:
        """Run a Playwright test and return the result."""
        try:
            results_dir = Path(output_dir) / "test-results"
            report_dir = Path(output_dir) / "report"
            json_results_file = Path(output_dir) / "test-results.json"

            cmd = f"PLAYWRIGHT_OUTPUT_DIR='{results_dir}' PLAYWRIGHT_HTML_REPORT='{report_dir}' "
            cmd += f"PLAYWRIGHT_JSON_OUTPUT_FILE='{json_results_file}' "
            cmd += f"npx playwright test '{test_file}' --reporter=list,html,json --project {browser} --timeout=120000"

            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes to allow for multiple tests in a file
            )

            output = result.stdout + result.stderr
            passed = result.returncode == 0 and "passed" in output

            return TestResult(
                passed=passed,
                exit_code=result.returncode,
                output=output,
                error_summary=self._summarize_error(output) if not passed else "",
            )

        except subprocess.TimeoutExpired:
            return TestResult(
                passed=False,
                exit_code=-1,
                output="Test timed out after 600 seconds (10 minutes)",
                error_summary="Timeout - test suite took too long",
            )
        except Exception as e:
            return TestResult(passed=False, exit_code=-1, output=str(e), error_summary=str(e)[:100])

    def _resolve_includes(self, content: str, spec_path: str = None) -> str:
        """
        Resolve @include directives in spec content.
        Returns the expanded content with all includes resolved.
        """
        processed_lines = []

        base_dir = Path("specs")
        if spec_path:
            base_dir = Path(spec_path).parent

        lines = content.split("\n")
        for line in lines:
            # Check for @include "path/to/file.md"
            match = re.search(r'@include\s+"([^"]+)"', line)
            if match:
                ref_path = match.group(1)

                # Resolve path - try multiple strategies
                target_file = base_dir / ref_path
                if not target_file.exists():
                    # Try from project root
                    target_file = Path(ref_path)
                if not target_file.exists():
                    # Try relative to specs/
                    target_file = Path("specs") / ref_path
                if not target_file.exists():
                    # Try templates folder
                    target_file = Path("specs/templates") / Path(ref_path).name

                if target_file.exists():
                    template_content = target_file.read_text()
                    # Recursively resolve includes in the template
                    resolved_template = self._resolve_includes(template_content, str(target_file))
                    processed_lines.append(f"\n# --- Included from {ref_path} ---")
                    processed_lines.append(resolved_template)
                    processed_lines.append("# --- End Include ---\n")
                else:
                    # Keep the original line if file not found
                    processed_lines.append(f"<!-- Include not found: {ref_path} -->")
            else:
                processed_lines.append(line)

        return "\n".join(processed_lines)

    def _extract_url(self, spec_content: str, spec_path: str = None) -> str | None:
        """Extract target URL from spec content (after resolving includes)."""
        # First resolve all includes to get full content
        resolved_content = self._resolve_includes(spec_content, spec_path)

        # Look for Navigate to http(s)://...
        patterns = [
            r'Navigate to\s+(https?://[^\s\'"]+)',
            r'Go to\s+(https?://[^\s\'"]+)',
            r'Open\s+(https?://[^\s\'"]+)',
            r'##\s+Base\s+URL:\s*(https?://[^\s\'"]+)',  # API spec format
            r'Base\s+URL:\s*(https?://[^\s\'"]+)',
            r'URL:\s*(https?://[^\s\'"]+)',
            r'Target URL:\s*(https?://[^\s\'"]+)',
            r'(?:POST|GET|PUT|PATCH|DELETE)\s+(https?://[^\s\'"]+)',  # API step with full URL
            r'(https?://[^\s\'"]+)',  # Fallback: any URL
        ]

        for pattern in patterns:
            match = re.search(pattern, resolved_content, re.IGNORECASE)
            if match:
                return match.group(1).rstrip(".")

        return None

    def _extract_login_url(self, spec_content: str, target_url: str) -> str | None:
        """Extract login URL from spec or derive from target URL."""
        # Check for explicit login URL in spec
        login_patterns = [
            r'login\s+(?:page|url):\s*(https?://[^\s\'"]+)',
            r'sign[_-]?in\s+(?:page|url):\s*(https?://[^\s\'"]+)',
        ]

        for pattern in login_patterns:
            match = re.search(pattern, spec_content, re.IGNORECASE)
            if match:
                return match.group(1)

        # Check if there's a login step in the spec
        if re.search(r"(login|sign\s*in)", spec_content, re.IGNORECASE):
            from urllib.parse import urlparse

            parsed = urlparse(target_url)
            # Common login URL patterns
            for login_path in ["/login", "/signin", "/sign_in", "/users/sign_in", "/auth/login"]:
                return f"{parsed.scheme}://{parsed.netloc}{login_path}"

        return None

    def _extract_credentials(self, spec_content: str) -> dict[str, str] | None:
        """Extract credential placeholders from spec."""
        credentials = {}

        # Look for {{VAR_NAME}} patterns
        username_patterns = [
            r"\{\{(LOGIN_USERNAME|USERNAME|USER|EMAIL)\}\}",
            r"\{\{([A-Z_]*USERNAME[A-Z_]*)\}\}",
            r"\{\{([A-Z_]*EMAIL[A-Z_]*)\}\}",
        ]

        password_patterns = [
            r"\{\{(LOGIN_PASSWORD|PASSWORD|PASS)\}\}",
            r"\{\{([A-Z_]*PASSWORD[A-Z_]*)\}\}",
        ]

        for pattern in username_patterns:
            match = re.search(pattern, spec_content)
            if match:
                var_name = match.group(1)
                credentials["username"] = os.environ.get(var_name, "")
                credentials["username_var"] = var_name
                break

        for pattern in password_patterns:
            match = re.search(pattern, spec_content)
            if match:
                var_name = match.group(1)
                credentials["password"] = os.environ.get(var_name, "")
                credentials["password_var"] = var_name
                break

        return credentials if credentials else None

    def _extract_test_name(self, spec_content: str) -> str:
        """Extract test name from spec."""
        # Look for # Test: or # Title: pattern
        for line in spec_content.split("\n"):
            if line.startswith("# "):
                name = line[2:].strip()
                name = name.replace("Test:", "").strip()
                return name

        return "Unnamed Test"

    def _write_pipeline_error(self, run_dir: Path, error: str, stage: str) -> None:
        """Write pipeline_error.json so the API wrapper can populate DB error_message."""
        try:
            error_data = {"error": error[:2000], "stage": stage, "timestamp": datetime.now().isoformat()}
            # Include the tail of long errors so the root cause (often at the end) is visible
            if len(error) > 2000:
                error_data["error_tail"] = error[-500:]
            (run_dir / "pipeline_error.json").write_text(json.dumps(error_data, indent=2))
        except Exception as e:
            logger.warning(f"Failed to write pipeline_error.json: {e}")

    def _summarize_error(self, output: str) -> str:
        """Extract a brief error summary from full output."""
        # Priority error patterns
        error_patterns = [
            r"TimeoutError:.*",
            r"Error:.*",
            r"strict mode violation.*",
            r"element.*not found",
            r"Timeout \d+ms exceeded",
        ]

        for pattern in error_patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                return match.group(0)[:120]

        # Look for lines with error keywords
        for line in output.split("\n"):
            if re.search(r"(error|fail|timeout)", line, re.IGNORECASE):
                return line.strip()[:120]

        return "Unknown error"


async def run_full_native_pipeline(
    spec_path: str,
    run_dir: str,
    browser: str = "chromium",
    hybrid_healing: bool = False,
    max_iterations: int = 20,
    existing_test_path: str | None = None,
    force_api: bool = False,
) -> dict:
    """Convenience function to run the full native pipeline."""
    pipeline = FullNativePipeline()
    return await pipeline.run(
        spec_path=spec_path,
        run_dir=Path(run_dir),
        browser=browser,
        hybrid_healing=hybrid_healing,
        max_iterations=max_iterations,
        existing_test_path=existing_test_path,
        force_api=force_api,
    )


if __name__ == "__main__":
    from orchestrator.logging_config import setup_logging

    setup_logging()

    import argparse

    parser = argparse.ArgumentParser(description="Run Full Native Pipeline")
    parser.add_argument("spec", help="Path to the markdown spec file")
    parser.add_argument("--run-dir", help="Directory for run artifacts")
    parser.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    parser.add_argument("--hybrid", action="store_true", help="Use hybrid healing mode")
    parser.add_argument("--max-iterations", type=int, default=20)
    parser.add_argument("--existing-test", help="Existing test file to heal (skips planning/generation)")
    parser.add_argument("--api", action="store_true", help="Force API test mode")

    args = parser.parse_args()

    if args.run_dir:
        run_dir = Path(args.run_dir)
    else:
        run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_dir = Path(f"runs/{run_id}")

    run_dir.mkdir(parents=True, exist_ok=True)

    result = asyncio.run(
        run_full_native_pipeline(
            spec_path=args.spec,
            run_dir=str(run_dir),
            browser=args.browser,
            hybrid_healing=args.hybrid,
            max_iterations=args.max_iterations,
            existing_test_path=args.existing_test,
            force_api=getattr(args, "api", False),
        )
    )

    logger.info("=" * 80)
    if result.get("success"):
        logger.info(f"Pipeline SUCCEEDED - Test: {result.get('test_path')}")
    else:
        logger.error(f"Pipeline FAILED - Stage: {result.get('stage')}")
    logger.info("=" * 80)
